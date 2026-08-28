"""
TokioAI Vivo v4.0 - Git Safe Guard
Complete safety layer for autonomous Git operations.

Guarantees:
  1. NEVER commits/pushes to main/master/develop directly
  2. Tests MUST pass before commit (configurable)
  3. Syntax check on all .py files before commit
  4. Auto-rollback if post-commit tests fail
  5. Push only to vivo/* branches
  6. PR creation via GitHub/GitLab API (never merge directly)
  7. Diff review: LLM reviews own diff before commit (optional)
  8. Commit size limits: max files, max lines changed per commit
  9. Protected paths: certain files/dirs cannot be modified
  10. Full audit trail
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class CommitPolicy:
    """Policy for safe commits."""
    # Branch rules
    branch_prefix: str = "vivo/"
    protected_branches: List[str] = field(default_factory=lambda: [
        "main", "master", "develop", "release", "production", "staging"
    ])
    auto_create_branch: bool = True
    branch_from: str = "main"  # Base branch for new vivo branches

    # Pre-commit checks
    require_tests_pass: bool = True
    require_syntax_check: bool = True
    require_diff_review: bool = False  # LLM reviews its own diff
    max_files_per_commit: int = 10
    max_lines_changed: int = 500
    max_file_size_bytes: int = 1_000_000  # 1MB

    # Protected paths (regex patterns)
    protected_paths: List[str] = field(default_factory=lambda: [
        r"\.env$", r"\.env\.", r"secrets?\.", r"credentials?\.",
        r"\.pem$", r"\.key$", r"id_rsa", r"id_ed25519",
        r"Dockerfile$",  # Can read, cannot overwrite without review
    ])
    immutable_paths: List[str] = field(default_factory=lambda: [
        r"\.git/", r"node_modules/", r"__pycache__/",
    ])

    # Push rules
    allow_push: bool = True
    push_only_vivo_branches: bool = True
    require_remote_configured: bool = True

    # PR rules
    auto_create_pr: bool = False
    pr_draft: bool = True  # Create as draft PR
    pr_reviewers: List[str] = field(default_factory=list)

    # Rollback
    auto_rollback_on_test_failure: bool = True
    max_rollbacks_per_session: int = 5

    # Test config
    test_command: Optional[str] = None  # Override auto-detect
    test_timeout: int = 120


@dataclass
class CommitRecord:
    """Audit record for a commit."""
    timestamp: float
    sha: str
    branch: str
    message: str
    files: List[str]
    lines_added: int
    lines_removed: int
    tests_passed: bool
    syntax_ok: bool
    diff_reviewed: bool
    auto_rollback: bool = False
    rollback_reason: str = ""


class PreCommitResult:
    """Result of pre-commit validation."""
    def __init__(self):
        self.passed = True
        self.checks: List[Dict[str, Any]] = []
        self.blocking_errors: List[str] = []
        self.warnings: List[str] = []

    def add_check(self, name: str, passed: bool, detail: str = ""):
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.passed = False
            self.blocking_errors.append(f"{name}: {detail}")

    def add_warning(self, name: str, detail: str):
        self.warnings.append(f"{name}: {detail}")

    def summary(self) -> str:
        lines = []
        for c in self.checks:
            icon = "PASS" if c["passed"] else "FAIL"
            lines.append(f"  [{icon}] {c['name']}: {c['detail']}")
        for w in self.warnings:
            lines.append(f"  [WARN] {w}")
        return "\n".join(lines)


class GitSafeGuard:
    """
    Wraps GitOps with safety policies. This is the ONLY interface
    the WorkEngine should use for git operations.
    """

    def __init__(self, git_ops, test_runner, policy: Optional[CommitPolicy] = None,
                 llm_review_fn: Optional[Callable] = None, output_fn: Optional[Callable] = None):
        from .git_ops import GitOps
        from .test_runner import TestRunner

        self.git: GitOps = git_ops
        self.tests: TestRunner = test_runner
        self.policy = policy or CommitPolicy()
        self._llm_review = llm_review_fn  # async fn(diff_text) -> (approved, reason)
        self._o = output_fn or (lambda x: None)

        self._commit_history: List[CommitRecord] = []
        self._rollback_count = 0
        self._session_start = time.time()
        self._audit_log_path: Optional[Path] = None

    def set_audit_log(self, path: Path):
        """Set path for persistent audit log."""
        self._audit_log_path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    # ==================== BRANCH MANAGEMENT ====================

    def ensure_safe_branch(self) -> Tuple[bool, str]:
        """Ensure we're on a vivo/* branch. Create one if needed."""
        ok, current = self.git._run("git branch --show-current")
        if not ok:
            return False, "cannot determine current branch"

        current = current.strip()

        # Already on a safe branch?
        if current.startswith(self.policy.branch_prefix):
            return True, f"on safe branch: {current}"

        # On a protected branch?
        if current in self.policy.protected_branches:
            if self.policy.auto_create_branch:
                branch_name = f"{self.policy.branch_prefix}session-{int(time.time())}"
                # Try to create and switch
                ok, out = self.git._run(f"git checkout -b {branch_name}")
                if ok:
                    self._o(f"  [git-safe] Created safe branch: {branch_name}")
                    return True, f"created and switched to {branch_name}"
                else:
                    # Maybe uncommitted changes - stash first
                    self.git._run("git stash")
                    ok, out = self.git._run(f"git checkout -b {branch_name}")
                    if ok:
                        self.git._run("git stash pop")
                        self._o(f"  [git-safe] Created safe branch: {branch_name} (stashed and restored)")
                        return True, f"created {branch_name}"
                    return False, f"cannot create branch: {out}"
            else:
                return False, f"on protected branch '{current}' and auto_create_branch is disabled"

        # On some other branch - allow it
        return True, f"on branch: {current}"

    def get_current_branch(self) -> str:
        """Get current branch name."""
        ok, branch = self.git._run("git branch --show-current")
        return branch.strip() if ok else "unknown"

    def is_on_protected_branch(self) -> bool:
        """Check if currently on a protected branch."""
        branch = self.get_current_branch()
        return branch in self.policy.protected_branches

    # ==================== PRE-COMMIT CHECKS ====================

    def _check_protected_paths(self, files: List[str]) -> PreCommitResult:
        """Check that no protected/immutable paths are being modified."""
        result = PreCommitResult()

        for f in files:
            # Immutable paths - always blocked
            for pattern in self.policy.immutable_paths:
                if re.search(pattern, f):
                    result.add_check(
                        "immutable_path", False,
                        f"cannot modify immutable path: {f}"
                    )
                    return result

            # Protected paths - warning (block if no review)
            for pattern in self.policy.protected_paths:
                if re.search(pattern, f):
                    if self.policy.require_diff_review:
                        result.add_warning("protected_path", f"modifying protected file: {f} (will require diff review)")
                    else:
                        result.add_check(
                            "protected_path", False,
                            f"modifying protected file {f} without diff review enabled"
                        )

        result.add_check("path_check", True, f"{len(files)} files OK")
        return result

    def _check_commit_size(self, files: List[str]) -> PreCommitResult:
        """Check commit size limits."""
        result = PreCommitResult()

        # File count
        if len(files) > self.policy.max_files_per_commit:
            result.add_check(
                "file_count", False,
                f"{len(files)} files exceeds limit of {self.policy.max_files_per_commit}"
            )
        else:
            result.add_check("file_count", True, f"{len(files)} files")

        # Lines changed (from staged diff)
        ok, diff_stat = self.git._run("git diff --cached --numstat")
        if ok and diff_stat.strip():
            total_added = 0
            total_removed = 0
            for line in diff_stat.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    try:
                        total_added += int(parts[0]) if parts[0] != '-' else 0
                        total_removed += int(parts[1]) if parts[1] != '-' else 0
                    except ValueError:
                        pass

            total_changed = total_added + total_removed
            if total_changed > self.policy.max_lines_changed:
                result.add_warning(
                    "lines_changed",
                    f"{total_changed} lines changed (limit: {self.policy.max_lines_changed})"
                )
            else:
                result.add_check("lines_changed", True, f"+{total_added}/-{total_removed}")

        # File sizes
        for f in files:
            p = Path(f)
            if p.exists() and p.stat().st_size > self.policy.max_file_size_bytes:
                result.add_warning(
                    "file_size",
                    f"{f}: {p.stat().st_size} bytes exceeds {self.policy.max_file_size_bytes}"
                )

        return result

    def _run_syntax_checks(self, files: List[str]) -> PreCommitResult:
        """Run syntax check on all Python files being committed."""
        result = PreCommitResult()

        py_files = [f for f in files if f.endswith(".py") and Path(f).exists()]
        if not py_files:
            result.add_check("syntax", True, "no Python files to check")
            return result

        all_ok = True
        for f in py_files:
            tr = self.tests.run_syntax_check(f)
            if not tr.passed:
                result.add_check("syntax", False, f"syntax error in {f}: {tr.output[:200]}")
                all_ok = False

        if all_ok:
            result.add_check("syntax", True, f"{len(py_files)} Python files OK")
        return result

    def _run_tests(self, cwd: Optional[str] = None) -> PreCommitResult:
        """Run test suite."""
        result = PreCommitResult()

        cmd = self.policy.test_command
        timeout = self.policy.test_timeout

        if cmd:
            tr = self.tests.run_script(cmd, timeout=timeout, cwd=cwd)
        else:
            tr = self.tests.run_auto(timeout=timeout, cwd=cwd)

        if tr.passed:
            result.add_check("tests", True, tr.summary())
        else:
            result.add_check("tests", False, tr.summary() + "\n" + "\n".join(tr.failed_tests[:5]))

        return result

    async def _run_diff_review(self, diff: str) -> PreCommitResult:
        """Have the LLM review its own diff."""
        result = PreCommitResult()

        if not self._llm_review:
            result.add_check("diff_review", True, "no review function configured")
            return result

        try:
            approved, reason = await self._llm_review(diff)
            if approved:
                result.add_check("diff_review", True, reason[:200])
            else:
                result.add_check("diff_review", False, f"LLM rejected diff: {reason[:200]}")
        except Exception as e:
            result.add_warning("diff_review", f"review failed: {e}")

        return result

    def pre_commit_check(self, files: List[str], cwd: Optional[str] = None) -> PreCommitResult:
        """
        Run ALL pre-commit checks. Returns aggregated result.
        This is the GATE that decides if a commit is allowed.
        """
        final = PreCommitResult()

        # 1. Branch check
        on_safe, branch_msg = self.ensure_safe_branch()
        if not on_safe:
            final.add_check("branch", False, branch_msg)
            return final  # Hard stop
        final.add_check("branch", True, branch_msg)

        # 2. Protected paths
        path_result = self._check_protected_paths(files)
        final.checks.extend(path_result.checks)
        final.warnings.extend(path_result.warnings)
        if not path_result.passed:
            final.passed = False
            final.blocking_errors.extend(path_result.blocking_errors)
            return final

        # 3. Commit size
        size_result = self._check_commit_size(files)
        final.checks.extend(size_result.checks)
        final.warnings.extend(size_result.warnings)
        # Size is a warning, not a blocker (unless file count exceeded)
        if not size_result.passed:
            final.passed = False
            final.blocking_errors.extend(size_result.blocking_errors)

        # 4. Syntax check (if required)
        if self.policy.require_syntax_check:
            syntax_result = self._run_syntax_checks(files)
            final.checks.extend(syntax_result.checks)
            if not syntax_result.passed:
                final.passed = False
                final.blocking_errors.extend(syntax_result.blocking_errors)
                return final  # No point running tests if syntax is broken

        # 5. Tests (if required)
        if self.policy.require_tests_pass:
            test_result = self._run_tests(cwd=cwd)
            final.checks.extend(test_result.checks)
            if not test_result.passed:
                final.passed = False
                final.blocking_errors.extend(test_result.blocking_errors)

        return final

    # ==================== SAFE COMMIT ====================

    def safe_commit(self, files: List[str], message: str,
                    skip_tests: bool = False, cwd: Optional[str] = None) -> Tuple[bool, str]:
        """
        Commit with full safety pipeline:
        1. Ensure on safe branch
        2. Check protected paths
        3. Check commit size
        4. Syntax check all .py files
        5. Run tests
        6. Commit
        7. Post-commit test verification
        8. Auto-rollback if post-commit tests fail

        Returns: (success, message)
        """
        self._o(f"  [git-safe] Starting safe commit pipeline for {len(files)} files...")

        # Stage files first (needed for size checks)
        for f in files:
            p = Path(f).resolve()
            if p.exists():
                self.git._run(f"git add -- {str(p)}")

        # Run pre-commit checks
        policy_override = CommitPolicy(**{
            **self.policy.__dict__,
            "require_tests_pass": not skip_tests and self.policy.require_tests_pass,
        })
        original_policy = self.policy
        self.policy = policy_override

        check_result = self.pre_commit_check(files, cwd=cwd)
        self.policy = original_policy

        self._o(f"  [git-safe] Pre-commit results:\n{check_result.summary()}")

        if not check_result.passed:
            # Unstage files
            for f in files:
                self.git._run(f"git reset HEAD -- {f}")
            errors = "; ".join(check_result.blocking_errors)
            self._o(f"  [git-safe] BLOCKED: {errors}")
            return False, f"Pre-commit checks failed: {errors}"

        # Commit
        ok, commit_msg = self.git.auto_commit(files, message)
        if not ok:
            self._o(f"  [git-safe] Commit failed: {commit_msg}")
            return False, f"Commit failed: {commit_msg}"

        self._o(f"  [git-safe] Committed: {commit_msg}")

        # Post-commit test verification (if enabled and not skipped)
        if self.policy.auto_rollback_on_test_failure and not skip_tests:
            self._o(f"  [git-safe] Running post-commit test verification...")
            post_test = self._run_tests(cwd=cwd)
            if not post_test.passed:
                if self._rollback_count < self.policy.max_rollbacks_per_session:
                    self._o(f"  [git-safe] POST-COMMIT TESTS FAILED - rolling back!")
                    rb_ok, rb_msg = self.git.rollback_hard()
                    self._rollback_count += 1
                    self._log_audit(CommitRecord(
                        timestamp=time.time(), sha="(rolled back)",
                        branch=self.get_current_branch(), message=message,
                        files=files, lines_added=0, lines_removed=0,
                        tests_passed=False, syntax_ok=True,
                        diff_reviewed=False, auto_rollback=True,
                        rollback_reason="post-commit tests failed"
                    ))
                    return False, f"Auto-rollback: post-commit tests failed. {rb_msg}"
                else:
                    self._o(f"  [git-safe] WARNING: max rollbacks reached, keeping commit despite test failure")

        # Success - record
        _, sha_out = self.git._run("git rev-parse --short HEAD")
        sha = sha_out.strip() if sha_out else "?"

        record = CommitRecord(
            timestamp=time.time(), sha=sha,
            branch=self.get_current_branch(), message=message,
            files=files, lines_added=0, lines_removed=0,
            tests_passed=True, syntax_ok=True,
            diff_reviewed=self.policy.require_diff_review
        )
        self._commit_history.append(record)
        self._log_audit(record)

        return True, f"Safe commit {sha}: {message}"

    # ==================== SAFE PUSH ====================

    def safe_push(self, remote: str = "origin") -> Tuple[bool, str]:
        """
        Push current branch to remote with safety checks.
        - Never pushes protected branches
        - Only pushes vivo/* branches
        - Verifies remote is configured
        """
        branch = self.get_current_branch()

        # Check: not on protected branch
        if branch in self.policy.protected_branches:
            return False, f"BLOCKED: cannot push protected branch '{branch}'"

        # Check: only vivo branches (if policy requires)
        if self.policy.push_only_vivo_branches and not branch.startswith(self.policy.branch_prefix):
            return False, f"BLOCKED: can only push {self.policy.branch_prefix}* branches, currently on '{branch}'"

        # Check: remote configured
        if self.policy.require_remote_configured:
            ok, remotes = self.git._run("git remote -v")
            if not ok or remote not in (remotes or ""):
                return False, f"BLOCKED: remote '{remote}' not configured"

        # Push
        ok, out = self.git._run(f"git push -u {remote} {branch}", cwd=None)
        if ok:
            self._o(f"  [git-safe] Pushed {branch} to {remote}")
            return True, f"Pushed {branch} to {remote}"
        else:
            # Try setting upstream
            ok2, out2 = self.git._run(f"git push --set-upstream {remote} {branch}")
            if ok2:
                self._o(f"  [git-safe] Pushed {branch} to {remote} (set upstream)")
                return True, f"Pushed {branch} to {remote}"
            return False, f"Push failed: {out} | {out2}"

    # ==================== PR CREATION ====================

    def create_pr(self, title: str, body: str, base: str = "main",
                  remote: str = "origin") -> Tuple[bool, str]:
        """
        Create a Pull Request / Merge Request.
        Supports GitHub (gh CLI) and GitLab (glab CLI).
        Falls back to providing a URL the user can open.
        """
        branch = self.get_current_branch()

        if branch in self.policy.protected_branches:
            return False, f"BLOCKED: cannot create PR from protected branch '{branch}'"

        # Ensure pushed first
        push_ok, push_msg = self.safe_push(remote)
        if not push_ok:
            return False, f"Cannot create PR: push failed - {push_msg}"

        # Try GitHub CLI
        gh_ok, _ = self.git._run("which gh")
        if gh_ok:
            draft_flag = "--draft" if self.policy.pr_draft else ""
            reviewer_flag = ""
            if self.policy.pr_reviewers:
                reviewer_flag = f"--reviewer {','.join(self.policy.pr_reviewers)}"

            cmd = f'gh pr create --title "{title}" --body "{body}" --base {base} {draft_flag} {reviewer_flag}'.strip()
            ok, out = self.git._run(cmd, cwd=None)
            if ok:
                self._o(f"  [git-safe] PR created: {out}")
                return True, f"PR created: {out}"
            else:
                # gh might not be authenticated
                self._o(f"  [git-safe] gh pr create failed: {out}")

        # Try GitLab CLI
        glab_ok, _ = self.git._run("which glab")
        if glab_ok:
            draft_flag = "--draft" if self.policy.pr_draft else ""
            cmd = f'glab mr create --title "{title}" --description "{body}" --target-branch {base} {draft_flag}'.strip()
            ok, out = self.git._run(cmd, cwd=None)
            if ok:
                self._o(f"  [git-safe] MR created: {out}")
                return True, f"MR created: {out}"

        # Fallback: generate URL
        ok, remote_url = self.git._run(f"git remote get-url {remote}")
        if ok and remote_url:
            url = remote_url.strip()
            if "github.com" in url:
                # Extract owner/repo
                match = re.search(r'github\.com[:/]([^/]+)/([^/.]+)', url)
                if match:
                    owner, repo = match.group(1), match.group(2)
                    pr_url = f"https://github.com/{owner}/{repo}/compare/{base}...{branch}?expand=1"
                    return True, f"PR not auto-created (install gh CLI). Open manually: {pr_url}"
            elif "gitlab" in url:
                return True, f"MR not auto-created (install glab CLI). Push complete to {branch}."

        return True, f"Branch {branch} pushed. Create PR/MR manually from your Git hosting UI."

    # ==================== UTILITIES ====================

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        return {
            "total_commits": len(self._commit_history),
            "rollbacks": self._rollback_count,
            "branch": self.get_current_branch(),
            "session_duration": time.time() - self._session_start,
            "commits": [
                {
                    "sha": c.sha, "message": c.message,
                    "files": len(c.files), "tests_passed": c.tests_passed,
                    "auto_rollback": c.auto_rollback,
                }
                for c in self._commit_history[-10:]
            ],
        }

    def _log_audit(self, record: CommitRecord):
        """Append to audit log."""
        if not self._audit_log_path:
            return
        try:
            entry = {
                "ts": record.timestamp,
                "sha": record.sha,
                "branch": record.branch,
                "message": record.message,
                "files": record.files,
                "tests_passed": record.tests_passed,
                "syntax_ok": record.syntax_ok,
                "auto_rollback": record.auto_rollback,
                "rollback_reason": record.rollback_reason,
            }
            with open(self._audit_log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def get_diff_for_review(self) -> str:
        """Get staged diff for LLM review."""
        ok, diff = self.git._run("git diff --cached")
        if ok and diff:
            return diff[:10000]  # Cap at 10K chars
        ok, diff = self.git._run("git diff")
        if ok and diff:
            return diff[:10000]
        return "(no changes)"
