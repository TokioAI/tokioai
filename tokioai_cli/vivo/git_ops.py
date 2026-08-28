"""
TokioAI Vivo v3 - Git Operations
Auto-commit on every successful file change. Rollback on failure.
Auto-init if not a git repo. Branch isolation (vivo/auto branch).
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple


class GitOps:
    """Automatic git versioning for Vivo file operations."""

    BRANCH_NAME = "vivo/auto"

    def __init__(self, workdir: Optional[str] = None, enabled: bool = True):
        self.workdir = workdir or os.getcwd()
        self.enabled = enabled
        self._initialized = False
        self._original_branch: Optional[str] = None
        self._commit_count = 0

    def _run(self, cmd: str, cwd: Optional[str] = None) -> Tuple[bool, str]:
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=15, cwd=cwd or self.workdir
            )
            out = (r.stdout + r.stderr).strip()
            return r.returncode == 0, out
        except Exception as e:
            return False, str(e)

    def is_git_repo(self) -> bool:
        ok, _ = self._run("git rev-parse --is-inside-work-tree")
        return ok

    def init(self) -> Tuple[bool, str]:
        """Initialize git if needed. Create vivo/auto branch."""
        if not self.enabled:
            return True, "git disabled"

        if not self.is_git_repo():
            ok, out = self._run("git init")
            if not ok:
                return False, f"git init failed: {out}"

        # Check if there are any commits at all
        has_commits, _ = self._run("git rev-parse HEAD")
        if not has_commits:
            # No commits yet - create initial commit
            self._run("git add -A")
            ok, out = self._run('git commit -m "Initial commit (auto by TokioAI Vivo)" --allow-empty')
            if not ok:
                # Configure git user if needed
                self._run('git config user.email "vivo@tokioai.local"')
                self._run('git config user.name "TokioAI Vivo"')
                self._run('git commit -m "Initial commit (auto by TokioAI Vivo)" --allow-empty')

        # Save original branch
        ok, branch = self._run("git branch --show-current")
        if ok and branch:
            self._original_branch = branch.strip()

        # Create or switch to vivo branch
        ok, _ = self._run(f"git branch {self.BRANCH_NAME}")
        # If branch already exists, that's fine
        ok, out = self._run(f"git checkout {self.BRANCH_NAME}")
        if not ok:
            # Maybe there are uncommitted changes - stash them
            self._run("git stash")
            ok, out = self._run(f"git checkout {self.BRANCH_NAME}")
            if not ok:
                # Fall back to current branch, just use it
                self._initialized = True
                return True, f"Using current branch (couldn't switch to {self.BRANCH_NAME})"

        self._initialized = True
        return True, f"Git ready on branch {self.BRANCH_NAME}"

    def auto_commit(self, files: list[str], message: str) -> Tuple[bool, str]:
        """Stage and commit specific files with a descriptive message."""
        if not self.enabled:
            return True, "git disabled"

        if not self._initialized:
            self.init()

        # Ensure git user is configured
        self._run('git config user.email "vivo@tokioai.local" 2>/dev/null || true')
        self._run('git config user.name "TokioAI Vivo" 2>/dev/null || true')

        # Stage the files
        for f in files:
            p = Path(f).resolve()
            if p.exists():
                self._run(f"git add -- {str(p)}")

        # Check if there are staged changes
        ok, diff = self._run("git diff --cached --stat")
        if not diff.strip():
            return True, "nothing to commit (no changes)"

        # Commit
        self._commit_count += 1
        full_msg = f"[vivo #{self._commit_count}] {message}"
        # Use single quotes inside double for safety
        safe_msg = full_msg.replace('"', "'")
        ok, out = self._run(f'git commit -m "{safe_msg}"')
        if ok:
            _, sha = self._run("git rev-parse --short HEAD")
            return True, f"committed {sha.strip()}: {message}"
        else:
            # Try again with git config
            self._run('git config user.email "vivo@tokioai.local"')
            self._run('git config user.name "TokioAI Vivo"')
            ok, out = self._run(f'git commit -m "{safe_msg}"')
            if ok:
                _, sha = self._run("git rev-parse --short HEAD")
                return True, f"committed {sha.strip()}: {message}"
            return False, f"commit failed: {out}"

    def rollback_last(self) -> Tuple[bool, str]:
        """Undo the last commit but keep files (soft reset)."""
        if not self.enabled:
            return True, "git disabled"

        ok, out = self._run("git reset --soft HEAD~1")
        if ok:
            self._commit_count = max(0, self._commit_count - 1)
            return True, "rolled back last commit"
        return False, f"rollback failed: {out}"

    def rollback_hard(self) -> Tuple[bool, str]:
        """Undo the last commit AND discard file changes."""
        if not self.enabled:
            return True, "git disabled"

        ok, out = self._run("git reset --hard HEAD~1")
        if ok:
            self._commit_count = max(0, self._commit_count - 1)
            return True, "hard rollback: last commit undone, files restored"
        return False, f"hard rollback failed: {out}"

    def get_diff_summary(self, n_commits: int = 5) -> str:
        """Get a summary of recent vivo commits."""
        ok, out = self._run(f"git log --oneline -{n_commits}")
        if ok:
            return out
        return "(no git history)"

    def get_status(self) -> str:
        """Get current git status."""
        ok, out = self._run("git status --short")
        if ok:
            branch_ok, branch = self._run("git branch --show-current")
            b = branch.strip() if branch_ok else "?"
            return f"branch: {b}\n{out}" if out else f"branch: {b} (clean)"
        return "(git status unavailable)"

    @property
    def commit_count(self) -> int:
        return self._commit_count
