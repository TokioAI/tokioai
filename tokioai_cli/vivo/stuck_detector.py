"""
TokioAI Vivo v3 - Stuck Detector
Detects when the agent is looping, retrying the same failed approach,
or making no progress. Provides escape strategies.

Detection signals:
1. Same action type N times in a row
2. Same file being read repeatedly
3. Same error appearing multiple times
4. No new files/reports in M steps
5. Edit/write failing repeatedly on same file
"""
from __future__ import annotations

import hashlib
import time
from collections import Counter, deque
from typing import Dict, List, Optional, Tuple


class StuckDetector:
    """Detect when the agent is stuck and suggest escape strategies."""

    # Thresholds
    SAME_ACTION_THRESHOLD = 5          # Same action type N times in a row
    SAME_FILE_READ_THRESHOLD = 3       # Same file read N times in recent window
    SAME_ERROR_THRESHOLD = 3           # Same error N times in recent window
    NO_PROGRESS_THRESHOLD = 30         # v3.6: raised from 15 - audit tasks read many files before writing
    RETRY_SAME_EDIT_THRESHOLD = 3      # Same edit attempted N times in recent window
    MAX_RETRIES_PER_ERROR = 5          # Max fix attempts for the same error

    def __init__(self):
        self._action_history: deque = deque(maxlen=50)
        self._file_reads: Counter = Counter()
        self._error_hashes: Counter = Counter()
        self._edits_attempted: Counter = Counter()
        self._last_progress_step = -1  # v3.6: -1 means "not set yet"
        self._first_step_seen: int = -1  # v3.6: track first step to handle resume
        self._total_steps = 0
        self._files_touched: set = set()
        self._reports_count = 0
        self._stuck_count = 0
        self._escape_strategies_used: List[str] = []

    def record_action(self, action: str, params: dict, success: bool,
                      result: str, step: int):
        """Record an action for stuck analysis."""
        # v3.6: On first call (including resume), initialize baseline
        if self._first_step_seen < 0:
            self._first_step_seen = step
            self._last_progress_step = step  # Assume progress at start
        self._total_steps = step

        entry = {
            "action": action, "params_hash": self._hash_params(params),
            "success": success, "step": step, "ts": time.time(),
            "path": params.get("path", ""),  # v3.6: store raw path for diagnostics
        }
        self._action_history.append(entry)

        # Track file reads
        if action == "read_file":
            path = params.get("path", "")
            self._file_reads[path] += 1

        # Track errors
        if not success and result:
            err_hash = self._hash_error(result)
            self._error_hashes[err_hash] += 1

        # Track edits
        if action in ("write_file", "edit_file"):
            path = params.get("path", "")
            edit_hash = self._hash_edit(action, params)
            self._edits_attempted[edit_hash] += 1
            if success:
                self._files_touched.add(path)
                self._last_progress_step = step

        # Track reports
        if action == "report":
            self._reports_count += 1
            self._last_progress_step = step

        # Any new file analyzed counts as progress
        if action == "read_file" and success and self._file_reads.get(params.get("path", ""), 0) <= 1:
            self._last_progress_step = step

        # v3.6: successful commands with new hashes count as progress
        if action == "run_cmd" and success:
            self._last_progress_step = step

        # v3.6: grep_file is also exploration progress
        if action == "grep_file" and success:
            self._last_progress_step = step

    def is_stuck(self) -> Tuple[bool, str]:
        """Check if the agent appears stuck. Returns (is_stuck, reason).
        
        v3.6: Only checks RECENT actions (last WINDOW_SIZE) to avoid
        false positives from historical reads that the agent has moved on from.
        """
        WINDOW_SIZE = 8  # Only look at the last N actions

        if len(self._action_history) < 3:
            return False, ""

        recent_all = list(self._action_history)[-WINDOW_SIZE:]

        # Check 1: Same action type repeated (consecutive)
        recent_actions = list(self._action_history)[-self.SAME_ACTION_THRESHOLD:]
        if len(recent_actions) >= self.SAME_ACTION_THRESHOLD:
            actions = [e["action"] for e in recent_actions]
            if len(set(actions)) == 1 and actions[0] not in ("think",):
                return True, f"repeating '{actions[0]}' {self.SAME_ACTION_THRESHOLD}x in a row"

        # Check 2: Same file read too many times IN RECENT WINDOW
        recent_file_reads: Counter = Counter()
        recent_file_paths: dict = {}  # hash -> path for messages
        for e in recent_all:
            if e["action"] == "read_file":
                fhash = e.get("params_hash", "")
                recent_file_reads[fhash] += 1
                recent_file_paths[fhash] = e.get("path", fhash[:12])
        for fhash, count in recent_file_reads.items():
            if count >= self.SAME_FILE_READ_THRESHOLD:
                fname = recent_file_paths.get(fhash, "unknown")
                return True, f"reading '{fname}' {count} times in last {WINDOW_SIZE} actions"

        # Check 3: Same error repeated IN RECENT WINDOW
        recent_errors: Counter = Counter()
        for e in recent_all:
            if not e.get("success", True):
                recent_errors[e.get("params_hash", "err")] += 1
        for _, count in recent_errors.items():
            if count >= self.SAME_ERROR_THRESHOLD:
                return True, f"same error occurring {count} times recently"

        # Check 4: No progress in many steps
        steps_since_progress = self._total_steps - self._last_progress_step
        if steps_since_progress >= self.NO_PROGRESS_THRESHOLD:
            return True, f"no progress in {steps_since_progress} steps"

        # Check 5: Same edit failing repeatedly IN RECENT WINDOW
        recent_edits: Counter = Counter()
        for e in recent_all:
            if e["action"] in ("write_file", "edit_file") and not e.get("success", True):
                recent_edits[e.get("params_hash", "")] += 1
        for _, count in recent_edits.items():
            if count >= self.RETRY_SAME_EDIT_THRESHOLD:
                return True, f"same edit/write attempted {count} times recently"

        return False, ""

    def get_escape_strategy(self, reason: str) -> str:
        """Suggest an escape strategy based on why we're stuck."""
        strategies = []

        if "repeating" in reason and "read_file" in reason:
            strategies = [
                "STOP re-reading the same file. Use grep_file to find specific parts.",
                "Switch to list_dir to find OTHER relevant files.",
                "Use run_cmd 'find . -name ...' to search more broadly.",
                "Write a report summarizing what you know so far, then change approach.",
            ]
        elif "repeating" in reason and ("write_file" in reason or "edit_file" in reason):
            strategies = [
                "STOP trying the same edit. Read the file FIRST to understand current state.",
                "Use run_cmd to validate the file: python -c 'import ast; ast.parse(open(...).read())'",
                "Try a COMPLETELY different approach to the same problem.",
                "If edit_file fails, try write_file with the entire corrected content.",
                "Report the issue and move to a different part of the objective.",
            ]
        elif "same error" in reason:
            strategies = [
                "The same error keeps happening. Try a fundamentally different approach.",
                "Search the codebase for similar patterns: grep_file or run_cmd 'grep -rn'.",
                "Check dependencies: run_cmd 'pip list' or read requirements.txt.",
                "Read error documentation: run_cmd 'python -c \"help(module)\"'.",
                "Skip this sub-task and work on something else first.",
            ]
        elif "no progress" in reason:
            strategies = [
                "You have been exploring without acting for too long.",
                "Write a report of everything you have learned so far.",
                "Pick the single most impactful change and DO IT.",
                "If blocked, add a TODO item and move to the next part of the objective.",
                "Re-read the objective and ask: what is the SIMPLEST next step?",
            ]
        else:
            strategies = [
                "Change your approach completely.",
                "Write a report about what's blocking you.",
                "Try working on a different part of the objective.",
                "Use 'think' to reason about why you're stuck, then act differently.",
            ]

        # Rotate through strategies so we don't keep suggesting the same one
        idx = self._stuck_count % len(strategies)
        self._stuck_count += 1
        chosen = strategies[idx]
        self._escape_strategies_used.append(chosen)
        return chosen

    def reset_file_counter(self, path: str):
        """Reset read counter for a specific file (after it was modified)."""
        self._file_reads[path] = 0

    def reset_error_counters(self):
        """Reset error counters (after a successful fix)."""
        self._error_hashes.clear()

    def reset_all(self):
        """Full reset."""
        self._action_history.clear()
        self._file_reads.clear()
        self._error_hashes.clear()
        self._edits_attempted.clear()
        self._last_progress_step = 0
        self._total_steps = 0
        self._files_touched.clear()
        self._reports_count = 0
        self._stuck_count = 0

    def get_stats(self) -> Dict:
        return {
            "total_steps": self._total_steps,
            "files_touched": len(self._files_touched),
            "reports": self._reports_count,
            "stuck_events": self._stuck_count,
            "steps_since_progress": self._total_steps - self._last_progress_step,
            "unique_errors": len(self._error_hashes),
        }

    @staticmethod
    def _hash_params(params: dict) -> str:
        """Hash params for dedup detection."""
        key = json.dumps(params, sort_keys=True, default=str) if params else ""
        return hashlib.md5(key.encode()).hexdigest()[:8]

    @staticmethod
    def _hash_error(error: str) -> str:
        """Hash error message (normalize first)."""
        # Strip line numbers and timestamps for better dedup
        import re
        normalized = re.sub(r'line \d+', 'line N', error)
        normalized = re.sub(r'\d{4}-\d{2}-\d{2}', 'DATE', normalized)
        normalized = re.sub(r'\d+:\d+:\d+', 'TIME', normalized)
        return hashlib.md5(normalized[:500].encode()).hexdigest()[:8]

    @staticmethod
    def _hash_edit(action: str, params: dict) -> str:
        """Hash an edit attempt."""
        key = f"{action}:{params.get('path', '')}:{params.get('old_text', '')[:100]}"
        return hashlib.md5(key.encode()).hexdigest()[:8]


# Need json for _hash_params
import json
