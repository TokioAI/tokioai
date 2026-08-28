"""
TokioAI Vivo v4.0 - Work Engine (BULLETPROOF + GIT-SAFE)
The brain that DOES work: code, test, fix, commit, manage secrets, remember.

v4.0 capabilities:
- Build/test cycle: run_tests -> parse failures -> auto-fix loop
- GIT-SAFE: branch isolation, pre-commit tests, auto-rollback, PR creation
- Git auto-commit: every successful write/edit -> git commit (on safe branch only)
- Vault/secrets: encrypted secrets loaded into env for integrations
- Stuck detection v2: detect loops, escalate strategy, max retries
- Project memory: compressed persistent context that survives context window
- Output isolation: all output through VivoOutput (never stdout)
- Dual-model: gear2 routine + gear3 deep reasoning when stuck
- Sandbox mode: optional path restriction for write/edit
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ANSI colors
C_RESET = "\033[0m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_MAGENTA = "\033[35m"
C_WHITE = "\033[97m"
C_BLUE = "\033[34m"


def _run(cmd: str, timeout: int = 30, cwd: str = None) -> Tuple[bool, str]:
    """Run a shell command, return (success, output)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd
        )
        out = (r.stdout + "\n" + r.stderr).strip()
        ok = r.returncode == 0
        if not ok:
            out = f"[exit code {r.returncode}]\n{out}"
        return ok, out[:8000]
    except subprocess.TimeoutExpired:
        return False, f"[timeout after {timeout}s]"
    except Exception as e:
        return False, str(e)


def _read_file(path: str, offset: int = 0, max_lines: int = 500) -> str:
    """Read file content with offset and line limit."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"[file not found: {path}]"
        if p.stat().st_size > 5_000_000:
            return f"[file too large: {p.stat().st_size} bytes. Use grep_file or run_cmd 'head/tail' instead]"
        all_lines = p.read_text(errors="replace").splitlines()
        total = len(all_lines)
        if offset >= total:
            return f"[offset {offset} beyond file end ({total} lines)]"
        chunk = all_lines[offset:offset + max_lines]
        result = "\n".join(chunk)
        end_line = offset + len(chunk)
        header = f"[{path}: lines {offset+1}-{end_line} of {total}]"
        if end_line < total:
            footer = f"\n[... {total - end_line} more lines. Use offset={end_line} to continue]"
        else:
            footer = f"\n[END OF FILE]"
        return header + "\n" + result + footer
    except Exception as e:
        return f"[error reading {path}: {e}]"


def _grep_file(path: str, pattern: str, max_results: int = 30) -> str:
    """Search for pattern in a file."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"[file not found: {path}]"
        lines = p.read_text(errors="replace").splitlines()
        matches = []
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = None
        for i, line in enumerate(lines):
            if regex:
                if regex.search(line):
                    matches.append(f"L{i+1}: {line}")
            elif pattern.lower() in line.lower():
                matches.append(f"L{i+1}: {line}")
            if len(matches) >= max_results:
                break
        if not matches:
            return f"[no matches for '{pattern}' in {path} ({len(lines)} lines)]"
        return f"[{len(matches)} matches in {path}]\n" + "\n".join(matches)
    except Exception as e:
        return f"[error searching {path}: {e}]"


def _parse_llm_json(text: str) -> Optional[Dict]:
    """Robustly parse JSON from LLM response."""
    if not text:
        return None
    cleaned = text.strip()
    # Strip markdown fences
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Find deepest JSON object
    brace_start = cleaned.find('{')
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(cleaned)):
            if cleaned[i] == '{':
                depth += 1
            elif cleaned[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[brace_start:i+1])
                    except json.JSONDecodeError:
                        break
    return None


class WorkEngine:
    """
    v3.5 Work Engine with full autonomous capabilities.
    """

    WORK_SYSTEM_PROMPT = """You are TokioAI Vivo -- an autonomous AI agent running in persistent mode.
You are working on an objective given by your operator. You have full access to the local machine.

ACTIONS AVAILABLE:

=== File Operations ===
- read_file: Read a file (supports chunked reading)
    params: {"path": "/path/to/file", "offset": 0, "max_lines": 500}
- grep_file: Search for a pattern inside a file
    params: {"path": "/path/to/file", "pattern": "search text or regex"}
- list_dir: List directory contents
    params: {"path": "/path/to/dir", "recursive": false, "pattern": "*.py"}
- write_file: Write/create a file (auto-commits to git)
    params: {"path": "/path/to/file", "content": "file content"}
- edit_file: Replace text in a file (must be unique match, auto-commits)
    params: {"path": "/path/to/file", "old_text": "exact text", "new_text": "replacement"}

=== Execution ===
- run_cmd: Execute a shell command (bash)
    params: {"cmd": "command", "timeout": 30}
- run_tests: Run tests and get structured results (auto-detects pytest/npm/cargo/go)
    params: {"target": "path or test name", "timeout": 120, "cwd": "/optional/dir"}
- run_syntax_check: Check a Python file for syntax errors (fast, no execution)
    params: {"path": "/path/to/file.py"}

=== Version Control (GIT-SAFE) ===
- git_status: Show current git status, branch, and recent commits
    params: {}
- git_diff: Show what changed since last commit
    params: {"file": "optional specific file"}
- git_safe_commit: SAFE commit with pre-commit pipeline (syntax + tests + branch check)
    params: {"files": ["/path/to/file1", "/path/to/file2"], "message": "descriptive commit message", "skip_tests": false}
    NOTE: This runs syntax checks, tests, and ensures you're on a safe branch.
    If tests fail, the commit is BLOCKED. If post-commit tests fail, auto-rollback happens.
    ALWAYS use this instead of raw git commands.
- git_push: Push current branch to remote (only vivo/* branches allowed)
    params: {"remote": "origin"}
    NOTE: NEVER pushes to main/master/develop. Only vivo/* branches.
- git_create_pr: Create a Pull Request (requires gh or glab CLI)
    params: {"title": "PR title", "body": "PR description", "base": "main"}
    NOTE: Creates a DRAFT PR. You push, reviewer approves. Never auto-merge.
- git_rollback: Undo the last commit (keeps files changed but uncommitted)
    params: {"hard": false}
    NOTE: hard=true also reverts file contents

=== Memory (survives across sessions and context windows) ===
- memory_read: Read project memory (facts, decisions, progress, todo, errors)
    params: {}
- memory_write: Write to project memory
    params: {"category": "facts|decisions|progress|todo|errors|architecture", "text": "content"}
    IMPORTANT: Use this FREQUENTLY to save important discoveries, decisions, and progress.
    This is how you remember things across hundreds of cycles.
- memory_complete_todo: Mark a TODO item as done
    params: {"text": "item description"}

=== Meta ===
- think: Internal reasoning (no side effects, free)
    params: {}
- report: Report findings/progress to the operator
    params: {"title": "Title", "body": "details"}
- done: Mark objective as complete
    params: {"summary": "What was accomplished"}

RULES:
1. Be methodical: explore first, understand, then act.
2. One action per response.
3. USE read_file with offset for large files (>200 lines).
4. USE grep_file to find specific code instead of reading entire files.
5. NEVER delete or destroy data.
6. After writing/editing code, ALWAYS run_syntax_check or run_tests to verify.
7. If tests fail, read the error, fix the code, test again (BUILD-TEST-FIX loop).
8. Use memory_write FREQUENTLY to save discoveries and progress.
9. If stuck on the same thing 3x, CHANGE STRATEGY completely.
10. When done, write a final report and use 'done'.

GIT-SAFE CODING RULES (CRITICAL):
11. NEVER use run_cmd for git operations. Use git_safe_commit, git_push, git_create_pr.
12. When you have a working, tested set of changes, use git_safe_commit to commit them.
13. git_safe_commit will run syntax checks and tests BEFORE committing. If they fail, fix first.
14. After a batch of commits, use git_push to push to remote (only vivo/* branches).
15. When your feature/fix is complete, use git_create_pr to create a Draft PR for review.
16. You are ALWAYS on a vivo/* branch. NEVER try to switch to main/master.
17. Small, focused commits. Each commit should do ONE thing.
18. Write meaningful commit messages: "fix: ...", "feat: ...", "refactor: ...", "test: ..."

WORKFLOW for writing code:
  1. Understand requirements (read existing code, list_dir)
  2. Plan the change (think)
  3. Save plan to memory (memory_write category=decisions)
  4. Write/edit the code
  5. run_syntax_check on the file
  6. run_tests to verify
  7. If tests fail: read error, fix, test again (max 5 retries)
  8. Save progress to memory (memory_write category=progress)
  9. Move to next task

Respond ONLY with valid JSON (no markdown, no explanation):
{"reasoning": "your thinking", "action": "action_name", "params": {...}}"""

    def __init__(self, config, token_guard, safety, llm_client, output=None):
        self.cfg = config
        self.token_guard = token_guard
        self.safety = safety
        self.llm = llm_client
        self.out = output

        # Work state
        self.work_log: List[Dict[str, Any]] = []
        self.reports: List[Dict[str, Any]] = []
        self.steps_done = 0
        self.steps_max = 5000
        self._start_time = time.time()
        self._files_analyzed: List[str] = []

        # Stuck detection (v2)
        self._last_action_type = ""
        self._gear3_escalation_count = 0

        # Persistence
        self.work_log_path = config.vivo_dir / "work_log.json"

        # === NEW v4.0 MODULES ===

        # Git ops + Git Safe Guard
        from .git_ops import GitOps
        from .git_safe import GitSafeGuard, CommitPolicy
        git_enabled = config.autonomy >= 2 and not config.dry_run
        self.git = GitOps(workdir=os.getcwd(), enabled=git_enabled)
        if git_enabled:
            ok, msg = self.git.init()
            self._o(f"  {C_BLUE}[git]{C_RESET} {msg}")

        # Build commit policy from config
        commit_policy = CommitPolicy(
            branch_prefix=getattr(config, 'git_branch_prefix', 'vivo/'),
            require_tests_pass=getattr(config, 'git_require_tests', True),
            require_syntax_check=True,
            require_diff_review=getattr(config, 'git_require_review', False),
            auto_rollback_on_test_failure=getattr(config, 'git_auto_rollback', True),
            test_command=config.test_command,
            test_timeout=120,
            auto_create_pr=getattr(config, 'git_auto_pr', False),
            pr_draft=True,
            max_files_per_commit=getattr(config, 'git_max_files_per_commit', 10),
            max_lines_changed=getattr(config, 'git_max_lines_per_commit', 500),
        )

        # Project memory
        from .project_memory import ProjectMemory
        mem_path = config.vivo_dir / "project_memory.json"
        self.project_memory = ProjectMemory(mem_path)

        # Test runner
        from .test_runner import TestRunner
        self.test_runner = TestRunner(workdir=os.getcwd())

        # Git Safe Guard (wraps git + test_runner)
        self.git_safe = GitSafeGuard(
            git_ops=self.git,
            test_runner=self.test_runner,
            policy=commit_policy,
            output_fn=self._o,
        )
        audit_path = config.vivo_dir / "git_audit.jsonl"
        self.git_safe.set_audit_log(audit_path)
        if git_enabled:
            safe_ok, safe_msg = self.git_safe.ensure_safe_branch()
            self._o(f"  {C_BLUE}[git-safe]{C_RESET} {safe_msg}")

        # Stuck detector
        from .stuck_detector import StuckDetector
        self.stuck_detector = StuckDetector()

        # Vault (load secrets if available)
        from .vault import Vault
        vault_path = config.vivo_dir / "vault.enc"
        self.vault = Vault(vault_path)
        if self.vault.has_secrets():
            count = self.vault.load_into_env()
            if count > 0:
                self._o(f"  {C_BLUE}[vault]{C_RESET} Loaded {count} secrets into environment")

        # Auto-fix state
        self._fix_attempts: Dict[str, int] = {}  # error_hash -> attempts
        self._max_fix_attempts = 5

        self._load_work_log()

    def _o(self, text: str):
        """Write to output (isolated from stdout)."""
        if self.out:
            self.out.line(text)

    def _load_work_log(self):
        try:
            if self.work_log_path.exists():
                data = json.loads(self.work_log_path.read_text())
                self.work_log = data.get("log", [])[-50:]
                self.reports = data.get("reports", [])[-20:]
                self.steps_done = data.get("steps_done", 0)
                self._files_analyzed = data.get("files_analyzed", [])
        except Exception:
            pass

    def _save_work_log(self):
        try:
            self.work_log_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "log": self.work_log[-100:],
                "reports": self.reports[-30:],
                "steps_done": self.steps_done,
                "objective": self.cfg.objective,
                "files_analyzed": self._files_analyzed[-50:],
                "last_save": time.time(),
                "git_commits": self.git.commit_count if self.git.enabled else 0,
                "memory_stats": self.project_memory.summary_stats(),
            }
            self.work_log_path.write_text(json.dumps(data, indent=2, default=str))
        except Exception:
            pass

    def _build_context(self) -> str:
        """Build context for the LLM."""
        lines = []
        lines.append(f"OBJECTIVE: {self.cfg.objective}")
        lines.append(f"WORKING DIRECTORY: {os.getcwd()}")
        lines.append(f"AUTONOMY: {self.cfg.autonomy} (0=sim, 1=read-only, 2=trusted, 3=full)")
        if self.cfg.autonomy <= 1:
            lines.append("NOTE: Read-only mode. You can read files and run safe commands only.")
        lines.append(f"DRY_RUN: {self.cfg.dry_run}")
        lines.append(f"STEPS COMPLETED: {self.steps_done}")
        lines.append(f"SESSION TIME: {int(time.time() - self._start_time)}s")
        lines.append(f"GIT: {'enabled (auto-commit on)' if self.git.enabled else 'disabled'}")

        # Vault info
        vault_keys = self.vault.list_keys() if self.vault.has_secrets() else []
        if vault_keys:
            lines.append(f"SECRETS AVAILABLE: {', '.join(vault_keys)}")

        # Resume indicator
        if self.steps_done > 0 and (time.time() - self._start_time) < 30:
            lines.append("")
            lines.append("*** RESUMED SESSION ***")
            lines.append(f"Previously completed {self.steps_done} steps, {len(self.reports)} reports.")
            lines.append("Check memory_read for project context. Do NOT re-read files already analyzed.")

        # Project memory (compressed context that survives)
        mem_ctx = self.project_memory.get_context_string(max_chars=3000)
        if mem_ctx.strip():
            lines.append("")
            lines.append("=== PROJECT MEMORY (persistent) ===")
            lines.append(mem_ctx)
            lines.append("=== END MEMORY ===")

        # Files already analyzed
        if self._files_analyzed:
            lines.append(f"\nFILES ALREADY ANALYZED ({len(self._files_analyzed)}):")
            for f in self._files_analyzed[-15:]:
                lines.append(f"  - {f}")

        # Stuck detector status
        stuck_stats = self.stuck_detector.get_stats()
        if stuck_stats["stuck_events"] > 0:
            lines.append(f"\nWARNING: {stuck_stats['stuck_events']} stuck events detected this session.")

        # Test history
        test_hist = self.test_runner.get_history(n=3)
        if test_hist:
            lines.append("\nRECENT TEST RESULTS:")
            for th in test_hist:
                r = th.get("result", {})
                status = "PASS" if r.get("passed") else "FAIL"
                lines.append(f"  [{status}] {th.get('cmd', '?')[:60]} ({r.get('total', 0)} tests)")

        # Work history: progressive summarization
        total = len(self.work_log)
        if total > 0:
            lines.append("\nWORK HISTORY:")

            # Old entries: ultra-compact
            if total > 7:
                old = self.work_log[:-7]
                lines.append(f"  [{len(old)} older steps - key actions:]")
                # Show only non-think, non-read actions from old history
                for entry in old[-6:]:
                    action = entry.get("action", "?")
                    if action in ("think",):
                        continue
                    reasoning = entry.get("reasoning", "")[:50]
                    success = "OK" if entry.get("success") else "FAIL"
                    lines.append(f"    [{action}] {reasoning}... -> {success}")

            # Recent: brief
            recent = self.work_log[-7:-2] if total > 2 else self.work_log[:-2] if total > 2 else []
            for entry in recent:
                action = entry.get("action", "?")
                reasoning = entry.get("reasoning", "")[:80]
                success = "OK" if entry.get("success") else "FAIL"
                result_brief = str(entry.get("result", ""))[:150]
                lines.append(f"  [{action}] {reasoning} -> {success}: {result_brief}")

            # Last 2: full detail
            last = self.work_log[-2:] if total >= 2 else self.work_log
            if last:
                lines.append("\nLAST ACTIONS (full):")
                for entry in last:
                    action = entry.get("action", "?")
                    reasoning = entry.get("reasoning", "")
                    result_full = str(entry.get("result", ""))
                    success = "OK" if entry.get("success") else "FAIL"
                    lines.append(f"  [{action}] {reasoning}")
                    lines.append(f"    -> {success}:")
                    for rline in result_full.split("\n")[:40]:
                        lines.append(f"    {rline}")
                    if len(result_full.split("\n")) > 40:
                        lines.append(f"    ... [{len(result_full.split(chr(10))) - 40} more lines]")
                    lines.append("")

        lines.append("What is the next step? Respond with a single JSON action.")
        return "\n".join(lines)

    def _execute_action(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an action and return result."""
        result = {"success": False, "output": "", "action": action}

        try:
            # === FILE OPERATIONS ===
            if action == "read_file":
                path = params.get("path", "")
                if not path:
                    result["output"] = "ERROR: no path specified"
                    return result
                offset = int(params.get("offset", 0))
                max_lines = min(int(params.get("max_lines", 500)), 1000)
                content = _read_file(path, offset=offset, max_lines=max_lines)
                result["success"] = not content.startswith("[error") and not content.startswith("[file not found")
                result["output"] = content
                if result["success"] and offset == 0 and path not in self._files_analyzed:
                    self._files_analyzed.append(path)
                short = path.split("/")[-1]
                self._print_action(f"READ {short} (L{offset+1}+{max_lines})", content[:200])

            elif action == "grep_file":
                path = params.get("path", "")
                pattern = params.get("pattern", "")
                if not path or not pattern:
                    result["output"] = "ERROR: path and pattern required"
                    return result
                content = _grep_file(path, pattern, max_results=int(params.get("max_results", 30)))
                result["success"] = not content.startswith("[error")
                result["output"] = content
                self._print_action(f"GREP '{pattern}' in {path.split('/')[-1]}", content[:300])

            elif action == "list_dir":
                path = params.get("path", ".")
                recursive = params.get("recursive", False)
                file_pattern = params.get("pattern", "")
                try:
                    p = Path(path).expanduser()
                    if not p.exists():
                        result["output"] = f"ERROR: directory not found: {path}"
                        return result
                    if recursive:
                        if file_pattern:
                            entries = sorted([str(e.relative_to(p)) for e in p.rglob(file_pattern)])
                        else:
                            entries = sorted([str(e.relative_to(p)) for e in p.rglob("*") if not any(skip in str(e) for skip in [".git/", "__pycache__", ".pyc", "node_modules", ".venv"])])
                    else:
                        entries = sorted([e.name + ("/" if e.is_dir() else "") for e in p.iterdir() if not e.name.startswith(".")])
                    result["success"] = True
                    result["output"] = f"[{path}: {len(entries)} items]\n" + "\n".join(entries[:200])
                    if len(entries) > 200:
                        result["output"] += f"\n[... {len(entries) - 200} more]"
                    self._print_action(f"LIST {path}", f"{len(entries)} entries")
                except Exception as e:
                    result["output"] = f"ERROR listing {path}: {e}"

            elif action == "write_file":
                path = params.get("path", "")
                content = params.get("content", "")
                if not path:
                    result["output"] = "ERROR: no path specified"
                    return result
                # Sandbox check
                if self.cfg.sandbox_dir:
                    sandbox = Path(self.cfg.sandbox_dir).resolve()
                    target = Path(path).expanduser().resolve()
                    if not str(target).startswith(str(sandbox)):
                        result["output"] = f"BLOCKED: write outside sandbox ({sandbox})"
                        self._print_action(f"BLOCKED WRITE: {path}", "outside sandbox")
                        return result
                if self.cfg.autonomy <= 1 and not self.cfg.dry_run:
                    result["output"] = f"BLOCKED: write_file requires autonomy 2+. Current: {self.cfg.autonomy}"
                    self._print_action(f"BLOCKED WRITE: {path}", "autonomy too low")
                    return result
                if self.cfg.dry_run:
                    result["output"] = f"[DRY RUN] Would write {len(content)} chars to {path}"
                    result["success"] = True
                    result["simulated"] = True
                    self._print_action(f"DRY WRITE: {path}", f"{len(content)} chars")
                    return result
                try:
                    p = Path(path).expanduser()
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content)
                    result["success"] = True
                    result["output"] = f"Written {len(content)} chars to {path}"
                    self._print_action(f"WRITE: {path}", f"{len(content)} chars")
                    # Auto git commit (using safe guard - syntax check on write)
                    if self.git.enabled:
                        ok, msg = self.git.auto_commit([str(p)], f"write {p.name}")
                        if ok:
                            self._o(f"    {C_BLUE}[git]{C_RESET} {C_DIM}{msg}{C_RESET}")
                    # Auto syntax check if Python
                    if path.endswith(".py"):
                        syntax_r = self.test_runner.run_syntax_check(str(p))
                        if not syntax_r.passed:
                            self._o(f"    {C_RED}[syntax]{C_RESET} {C_DIM}{syntax_r.output[:200]}{C_RESET}")
                            result["output"] += f"\n\nWARNING: Syntax error detected! {syntax_r.output[:300]}"
                    # Reset stuck detector for this file
                    self.stuck_detector.reset_file_counter(path)
                except Exception as e:
                    result["output"] = f"ERROR writing {path}: {e}"

            elif action == "edit_file":
                path = params.get("path", "")
                old_text = params.get("old_text", "")
                new_text = params.get("new_text", "") if params.get("new_text") is not None else ""
                if not path or not old_text:
                    result["output"] = "ERROR: path and old_text required"
                    return result
                # Sandbox check
                if self.cfg.sandbox_dir:
                    sandbox = Path(self.cfg.sandbox_dir).resolve()
                    target = Path(path).expanduser().resolve()
                    if not str(target).startswith(str(sandbox)):
                        result["output"] = f"BLOCKED: edit outside sandbox ({sandbox})"
                        self._print_action(f"BLOCKED EDIT: {path}", "outside sandbox")
                        return result
                if self.cfg.autonomy <= 1 and not self.cfg.dry_run:
                    result["output"] = f"BLOCKED: edit_file requires autonomy 2+. Current: {self.cfg.autonomy}"
                    self._print_action(f"BLOCKED EDIT: {path}", "autonomy too low")
                    return result
                if self.cfg.dry_run:
                    result["output"] = f"[DRY RUN] Would edit {path}"
                    result["success"] = True
                    result["simulated"] = True
                    self._print_action(f"DRY EDIT: {path}", "simulated")
                    return result
                try:
                    p = Path(path).expanduser()
                    text = p.read_text()
                    count = text.count(old_text)
                    if count == 0:
                        result["output"] = f"ERROR: old_text not found in {path}. The file may have changed. Re-read it with read_file first."
                    elif count > 1:
                        result["output"] = f"ERROR: old_text found {count} times (must be unique). Use a longer/more specific snippet."
                    else:
                        new_content = text.replace(old_text, new_text, 1)
                        p.write_text(new_content)
                        result["success"] = True
                        result["output"] = f"Edited {path}: 1 replacement made"
                        # Auto git commit
                        if self.git.enabled:
                            ok, msg = self.git.auto_commit([str(p)], f"edit {p.name}")
                            if ok:
                                self._o(f"    {C_BLUE}[git]{C_RESET} {C_DIM}{msg}{C_RESET}")
                        self.stuck_detector.reset_file_counter(path)
                    self._print_action(f"EDIT: {path}", result["output"])
                except Exception as e:
                    result["output"] = f"ERROR editing {path}: {e}"

            # === EXECUTION ===
            elif action == "run_cmd":
                cmd = params.get("cmd", "")
                timeout = min(int(params.get("timeout", 30)), 120)
                if not cmd:
                    result["output"] = "ERROR: no command specified"
                    return result
                check = self.safety.can_execute(cmd, autonomy_override=self.cfg.autonomy)
                if not check["ok"]:
                    if check.get("dry_run"):
                        result["output"] = f"[DRY RUN] Would execute: {cmd}"
                        result["success"] = True
                        result["simulated"] = True
                        self._print_action(f"DRY RUN: {cmd[:60]}", "simulated")
                    else:
                        result["output"] = f"BLOCKED: {check['reason']}"
                        self._print_action(f"BLOCKED: {cmd[:60]}", check['reason'])
                    return result
                ok, out = _run(cmd, timeout)
                result["success"] = ok
                result["output"] = out
                self.safety.record_action(
                    cmd, False, check.get("destructive", False), True,
                    self.safety.parse_action_id(cmd)
                )
                status = "OK" if ok else "FAIL"
                self._print_action(f"CMD [{status}]: {cmd[:60]}", out[:300])

            elif action == "run_tests":
                target = params.get("target", "")
                timeout = min(int(params.get("timeout", 120)), 300)
                cwd = params.get("cwd", None)
                if self.cfg.dry_run:
                    result["output"] = f"[DRY RUN] Would run tests: {target}"
                    result["success"] = True
                    result["simulated"] = True
                    self._print_action("DRY RUN TESTS", "simulated")
                    return result
                test_result = self.test_runner.run_auto(target=target, timeout=timeout, cwd=cwd)
                result["success"] = test_result.passed
                result["output"] = test_result.summary() + "\n\n" + test_result.output[:4000]
                if test_result.passed:
                    self._print_action(f"TESTS: {C_GREEN}PASSED{C_RESET}", test_result.summary())
                    self.stuck_detector.reset_error_counters()
                else:
                    failure_ctx = self.test_runner.get_failure_context(test_result)
                    result["output"] = failure_ctx
                    self._print_action(f"TESTS: {C_RED}FAILED{C_RESET}", test_result.summary())

            elif action == "run_syntax_check":
                path = params.get("path", "")
                if not path:
                    result["output"] = "ERROR: no path specified"
                    return result
                test_result = self.test_runner.run_syntax_check(path)
                result["success"] = test_result.passed
                result["output"] = test_result.output
                status = f"{C_GREEN}OK{C_RESET}" if test_result.passed else f"{C_RED}ERROR{C_RESET}"
                self._print_action(f"SYNTAX [{status}]: {path.split('/')[-1]}", test_result.output[:200])

            # === GIT (SAFE) ===
            elif action == "git_status":
                status = self.git.get_status()
                recent = self.git.get_diff_summary(n_commits=10)
                safe_stats = self.git_safe.get_session_stats()
                result["success"] = True
                result["output"] = (
                    f"{status}\n\nRecent commits:\n{recent}\n\n"
                    f"Git-Safe session: {safe_stats['total_commits']} safe commits, "
                    f"{safe_stats['rollbacks']} rollbacks, branch: {safe_stats['branch']}"
                )
                self._print_action("GIT STATUS", status[:200])

            elif action == "git_diff":
                file_arg = params.get("file", "")
                cmd = f"git diff {'-- ' + file_arg if file_arg else ''}"
                ok, out = _run(cmd)
                result["success"] = ok
                result["output"] = out if out else "(no changes)"
                self._print_action("GIT DIFF", out[:200] if out else "(clean)")

            elif action == "git_safe_commit":
                files = params.get("files", [])
                message = params.get("message", "vivo auto-commit")
                skip_tests = params.get("skip_tests", False)
                if not files:
                    result["output"] = "ERROR: 'files' list required. Provide paths of files to commit."
                    return result
                if self.cfg.dry_run:
                    result["output"] = f"[DRY RUN] Would safe-commit {len(files)} files: {message}"
                    result["success"] = True
                    result["simulated"] = True
                    self._print_action("DRY SAFE COMMIT", f"{len(files)} files")
                    return result
                if self.cfg.autonomy < 2:
                    result["output"] = f"BLOCKED: git_safe_commit requires autonomy 2+. Current: {self.cfg.autonomy}"
                    self._print_action("BLOCKED COMMIT", "autonomy too low")
                    return result
                ok, msg = self.git_safe.safe_commit(files, message, skip_tests=skip_tests)
                result["success"] = ok
                result["output"] = msg
                self._print_action(
                    f"SAFE COMMIT: {C_GREEN if ok else C_RED}{'OK' if ok else 'BLOCKED'}{C_RESET}",
                    msg
                )

            elif action == "git_push":
                remote = params.get("remote", "origin")
                if self.cfg.dry_run:
                    result["output"] = f"[DRY RUN] Would push to {remote}"
                    result["success"] = True
                    result["simulated"] = True
                    return result
                if self.cfg.autonomy < 2:
                    result["output"] = f"BLOCKED: git_push requires autonomy 2+. Current: {self.cfg.autonomy}"
                    return result
                ok, msg = self.git_safe.safe_push(remote)
                result["success"] = ok
                result["output"] = msg
                self._print_action(f"GIT PUSH: {'OK' if ok else 'BLOCKED'}", msg)

            elif action == "git_create_pr":
                title = params.get("title", "Vivo auto-PR")
                body = params.get("body", "Automated changes by TokioAI Vivo")
                base = params.get("base", "main")
                if self.cfg.dry_run:
                    result["output"] = f"[DRY RUN] Would create PR: {title}"
                    result["success"] = True
                    result["simulated"] = True
                    return result
                if self.cfg.autonomy < 2:
                    result["output"] = f"BLOCKED: git_create_pr requires autonomy 2+. Current: {self.cfg.autonomy}"
                    return result
                ok, msg = self.git_safe.create_pr(title, body, base=base)
                result["success"] = ok
                result["output"] = msg
                self._print_action(f"CREATE PR: {'OK' if ok else 'FAILED'}", msg)

            elif action == "git_rollback":
                hard = params.get("hard", False)
                if self.cfg.dry_run:
                    result["output"] = f"[DRY RUN] Would rollback (hard={hard})"
                    result["success"] = True
                    result["simulated"] = True
                    return result
                if hard:
                    ok, msg = self.git.rollback_hard()
                else:
                    ok, msg = self.git.rollback_last()
                result["success"] = ok
                result["output"] = msg
                self._print_action(f"GIT ROLLBACK {'(hard)' if hard else ''}", msg)

            # === MEMORY ===
            elif action == "memory_read":
                ctx = self.project_memory.get_context_string(max_chars=5000)
                stats = self.project_memory.summary_stats()
                result["success"] = True
                result["output"] = f"Memory stats: {json.dumps(stats)}\n\n{ctx}" if ctx.strip() else "Project memory is empty. Use memory_write to start recording."
                self._print_action("MEMORY READ", f"stats: {json.dumps(stats)}")

            elif action == "memory_write":
                category = params.get("category", "facts")
                text = params.get("text", "")
                if not text:
                    result["output"] = "ERROR: text required"
                    return result
                if category == "facts":
                    self.project_memory.add_fact(text)
                elif category == "decisions":
                    self.project_memory.add_decision(text)
                elif category == "progress":
                    self.project_memory.add_progress(text)
                elif category == "todo":
                    priority = int(params.get("priority", 0))
                    self.project_memory.add_todo(text, priority=priority)
                elif category == "errors":
                    resolution = params.get("resolution", "")
                    self.project_memory.record_error(text, resolution=resolution)
                elif category == "architecture":
                    self.project_memory.add_architecture_note(text)
                else:
                    result["output"] = f"ERROR: unknown category '{category}'. Use: facts, decisions, progress, todo, errors, architecture"
                    return result
                result["success"] = True
                result["output"] = f"Saved to memory/{category}: {text[:100]}"
                self._print_action(f"MEMORY WRITE [{category}]", text[:100])

            elif action == "memory_complete_todo":
                text = params.get("text", "")
                if not text:
                    result["output"] = "ERROR: text required"
                    return result
                done = self.project_memory.complete_todo(text)
                result["success"] = done
                result["output"] = f"TODO completed: {text}" if done else f"TODO not found: {text}"
                self._print_action("MEMORY TODO DONE", text[:80])

            # === META ===
            elif action == "think":
                result["success"] = True
                result["output"] = "thought recorded"

            elif action == "report":
                title = params.get("title", "Report")
                body = params.get("body", "")
                report = {"ts": time.time(), "title": title, "body": body, "step": self.steps_done}
                self.reports.append(report)
                result["success"] = True
                result["output"] = "report saved"
                self._print_report(title, body)
                # Also save to project memory
                self.project_memory.add_progress(f"Report: {title}")

            elif action == "done":
                summary = params.get("summary", "Objective completed")
                result["success"] = True
                result["output"] = summary
                result["done"] = True
                self._print_done(summary)
                self.project_memory.add_progress(f"DONE: {summary}")

            else:
                result["output"] = (
                    f"Unknown action: '{action}'. Valid actions: "
                    "read_file, grep_file, list_dir, write_file, edit_file, "
                    "run_cmd, run_tests, run_syntax_check, "
                    "git_status, git_diff, git_safe_commit, git_push, git_create_pr, git_rollback, "
                    "memory_read, memory_write, memory_complete_todo, "
                    "think, report, done"
                )

        except Exception as e:
            result["output"] = f"EXCEPTION: {traceback.format_exc()}"
            result["success"] = False

        return result

    def _should_escalate_to_gear3(self) -> bool:
        """Check if we should use gear3 (deep reasoning)."""
        if not getattr(self.cfg, 'dual_model', False):
            return False
        # Escalate when stuck
        is_stuck, _ = self.stuck_detector.is_stuck()
        if is_stuck and self._gear3_escalation_count < 10:
            return True
        # Periodic strategic review every 25 steps
        if self.steps_done > 0 and self.steps_done % 25 == 0:
            return True
        return False

    def work_cycle(self) -> Dict[str, Any]:
        """One cycle of autonomous work."""
        if self.steps_done >= self.steps_max:
            return {"action": "limit", "result": "max steps reached", "done": True}

        # === STUCK DETECTION ===
        is_stuck, stuck_reason = self.stuck_detector.is_stuck()
        gear = 2

        if is_stuck:
            escape = self.stuck_detector.get_escape_strategy(stuck_reason)
            self._o(f"  {C_RED}[stuck]{C_RESET} {stuck_reason}")
            self._o(f"  {C_YELLOW}[escape]{C_RESET} {escape}")

            # Inject escape strategy as a forced action
            self.work_log.append({
                "ts": time.time(), "step": self.steps_done,
                "reasoning": f"SYSTEM: Stuck detected ({stuck_reason}). Strategy: {escape}",
                "action": "think", "params": {}, "success": True,
                "result": escape,
            })
            self.steps_done += 1

            # Escalate to gear3 if available
            if self._should_escalate_to_gear3():
                gear = 3
                self._gear3_escalation_count += 1
                self._o(f"  {C_MAGENTA}[gear3]{C_RESET} Escalating to deep reasoning model")

        # Periodic gear3 review
        if gear == 2 and self._should_escalate_to_gear3():
            gear = 3
            self._gear3_escalation_count += 1
            self._o(f"  {C_MAGENTA}[gear3]{C_RESET} Periodic strategic review")

        # Budget check
        budget_ok = self.token_guard.can_use_gear(gear)
        if not budget_ok["ok"]:
            if gear == 3:
                gear = 2
                budget_ok = self.token_guard.can_use_gear(2)
                if not budget_ok["ok"]:
                    return {"action": "budget_wait", "result": budget_ok["reason"], "done": False, "budget_exhausted": True}
            else:
                return {"action": "budget_wait", "result": budget_ok["reason"], "done": False, "budget_exhausted": True}

        # Build context
        context = self._build_context()
        model = self.cfg.effective_model(gear)

        system_prompt = self.WORK_SYSTEM_PROMPT
        if gear == 3:
            system_prompt += "\n\nYou are in STRATEGIC REVIEW mode. Take a step back. Evaluate progress. If stuck, propose a completely new strategy. If making progress, optimize the plan."

        # Call LLM
        result = self.llm.call_structured(
            gear=gear,
            system_prompt=system_prompt,
            user_prompt=context,
            max_tokens=4000,
        )

        if not result.get("ok"):
            self._print_error(f"LLM error: {result.get('error', 'unknown')}")
            return {"action": "llm_error", "result": result.get("error"), "done": False, "budget_exhausted": False}

        # Record token usage
        self.token_guard.record(gear, model, result.get("input_tokens", 0), result.get("output_tokens", 0))

        # Parse response
        parsed = result.get("parsed")
        if not parsed:
            parsed = _parse_llm_json(result.get("text", ""))
        if not parsed:
            raw = result.get("text", "")
            self._print_error(f"Could not parse LLM response: {raw[:200]}")
            self.work_log.append({
                "ts": time.time(), "step": self.steps_done,
                "reasoning": "SYSTEM: LLM response was not valid JSON",
                "action": "parse_error", "params": {}, "success": False,
                "result": raw[:500],
            })
            self.steps_done += 1
            self._save_work_log()
            return {"action": "parse_error", "result": raw[:200], "done": False, "budget_exhausted": False}

        reasoning = parsed.get("reasoning", "")
        action = parsed.get("action", "think")
        params = parsed.get("params", {})
        if params is None:
            params = {}

        # Print reasoning
        self._print_thinking(reasoning)

        # Execute
        exec_result = self._execute_action(action, params)

        # Record in stuck detector
        self.stuck_detector.record_action(
            action, params, exec_result.get("success", False),
            exec_result.get("output", ""), self.steps_done
        )

        # Record in work log
        entry = {
            "ts": time.time(),
            "step": self.steps_done,
            "reasoning": reasoning,
            "action": action,
            "params": {k: (v[:300] if isinstance(v, str) and len(v) > 300 else v) for k, v in params.items()},
            "success": exec_result.get("success", False),
            "result": exec_result.get("output", "")[:5000],
            "simulated": exec_result.get("simulated", False),
            "gear": gear,
        }
        self.work_log.append(entry)
        self.steps_done += 1
        self._save_work_log()

        return {
            "action": action,
            "result": exec_result,
            "done": exec_result.get("done", False),
            "budget_exhausted": False,
            "gear": gear,
            "step": self.steps_done,
        }

    def reset(self):
        """Reset for a new objective."""
        self.work_log = []
        self.reports = []
        self.steps_done = 0
        self._files_analyzed = []
        self._start_time = time.time()
        self._last_action_type = ""
        self._gear3_escalation_count = 0
        self.stuck_detector.reset_all()
        self._fix_attempts.clear()
        self._save_work_log()

    # ---- Output (through VivoOutput) ----

    def _print_thinking(self, reasoning: str):
        if reasoning:
            self._o(f"  {C_DIM}{C_CYAN}[thinking]{C_RESET} {C_DIM}{reasoning}{C_RESET}")

    def _print_action(self, label: str, detail: str):
        detail_lines = str(detail).split("\n")
        max_show = 12
        if len(detail_lines) > max_show:
            detail = "\n".join(detail_lines[:max_show]) + f"\n    ... ({len(detail_lines) - max_show} more lines)"
        self._o(f"  {C_YELLOW}[action]{C_RESET} {C_BOLD}{label}{C_RESET}")
        if detail:
            for line in str(detail).split("\n")[:max_show + 1]:
                self._o(f"    {C_DIM}{line}{C_RESET}")

    def _print_report(self, title: str, body: str):
        self._o(f"")
        self._o(f"  {C_GREEN}{C_BOLD}[REPORT] {title}{C_RESET}")
        for line in body.split("\n"):
            self._o(f"  {C_GREEN}  {line}{C_RESET}")
        self._o(f"")

    def _print_done(self, summary: str):
        self._o(f"")
        self._o(f"  {C_GREEN}{C_BOLD}[DONE] {summary}{C_RESET}")
        self._o(f"")

    def _print_error(self, msg: str):
        self._o(f"  {C_RED}[error]{C_RESET} {msg}")
