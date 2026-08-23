"""
TokioAI Vivo - Safety
Validates commands, enforces autonomy levels, kill switch, and action rate limits.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ActionRecord:
    ts: float
    action_id: str
    command: str
    simulated: bool
    destructive: bool
    approved: bool


class SafetyEnforcer:
    """Safety layer: blocks dangerous commands, enforces autonomy levels, cooldowns."""

    DESTRUCTIVE_HINTS = [
        "restart", "reboot", "shutdown", "pkill", "kill", "rm -", "rm /", "dd ",
        "mkfs", "format", "fdisk", "parted", "umount", "iptables -F", "sysctl -w",
        r"echo\s+.+\s*>\s*/", r">>\s*/", "chmod 000", "chown -R", "userdel", "deluser",
    ]

    def __init__(self, config):
        from .config import VivoConfig
        self.cfg: VivoConfig = config
        self.recent_actions: List[ActionRecord] = []
        self._action_counter: Dict[str, List[float]] = {}
        self.last_kill_check = 0.0

    def is_destructive(self, command: str) -> bool:
        cmd = command.strip().lower()
        # Exact whitelist overrides
        for allowed in self.cfg.destructive_whitelist:
            if cmd.startswith(allowed.lower()):
                # still destructive, just allowed under autonomy 2+
                return True
        for blocked in self.cfg.blocked_commands:
            if blocked.lower() in cmd or cmd.startswith(blocked.lower()):
                return True
        for hint in self.DESTRUCTIVE_HINTS:
            try:
                if re.search(hint, cmd, re.IGNORECASE):
                    return True
            except re.error:
                if hint.lower() in cmd:
                    return True
        return False

    def is_blocked(self, command: str) -> Tuple[bool, str]:
        cmd = command.strip().lower()
        for blocked in self.cfg.blocked_commands:
            if blocked.lower() in cmd or cmd.startswith(blocked.lower()):
                return True, f"command matches blocked pattern: {blocked}"
        # Block remote hosts not in allowed list
        if re.search(r"ssh\s+[^@]+@", command):
            return True, "ssh to remote hosts not allowed in vivo actions"
        return False, ""

    def check_rate_limits(self, command: str, now: Optional[float] = None) -> Tuple[bool, str]:
        now = now or time.time()
        window = 3600.0
        # Global action limit
        self.recent_actions = [a for a in self.recent_actions if now - a.ts < window]
        if len(self.recent_actions) >= self.cfg.max_actions_per_hour:
            return False, f"max actions per hour reached ({self.cfg.max_actions_per_hour})"
        # Destructive action limit
        destructive_count = sum(1 for a in self.recent_actions if a.destructive)
        if self.is_destructive(command) and destructive_count >= self.cfg.max_destructive_per_hour:
            return False, f"max destructive actions per hour reached ({self.cfg.max_destructive_per_hour})"
        return True, ""

    def can_execute(self, command: str, autonomy_override: Optional[int] = None) -> Dict[str, any]:
        autonomy = autonomy_override if autonomy_override is not None else self.cfg.autonomy
        blocked, reason = self.is_blocked(command)
        if blocked:
            return {"ok": False, "reason": reason, "needs_approval": False}

        ok, reason = self.check_rate_limits(command)
        if not ok:
            return {"ok": False, "reason": reason, "needs_approval": False}

        destructive = self.is_destructive(command)

        if self.cfg.dry_run:
            return {"ok": True, "reason": "dry-run: will simulate", "destructive": destructive, "needs_approval": False, "dry_run": True}

        if autonomy == 0:
            return {"ok": True, "reason": "simulation mode: will simulate", "destructive": destructive, "needs_approval": False, "dry_run": True}

        if destructive:
            if autonomy == 1:
                return {"ok": False, "reason": "destructive action needs human approval (autonomy=assisted)", "destructive": True, "needs_approval": True}
            if autonomy == 2:
                allowed = any(command.strip().lower().startswith(w.lower()) for w in self.cfg.destructive_whitelist)
                if not allowed:
                    return {"ok": False, "reason": "destructive command not in whitelist (autonomy=trusted)", "destructive": True, "needs_approval": True}
            if autonomy == 3:
                return {"ok": True, "reason": "full autonomy: destructive allowed", "destructive": True, "needs_approval": False}

        return {"ok": True, "reason": "allowed", "destructive": destructive, "needs_approval": False}

    def record_action(self, command: str, simulated: bool, destructive: bool, approved: bool, action_id: str):
        now = time.time()
        self.recent_actions.append(ActionRecord(
            ts=now, action_id=action_id, command=command,
            simulated=simulated, destructive=destructive, approved=approved
        ))
        self.recent_actions = [a for a in self.recent_actions if now - a.ts < 3600.0]

    def kill_switch_file_path(self) -> Path:
        return self.cfg.vivo_dir / "STOP"

    def request_stop(self):
        self.kill_switch_file_path().write_text(str(time.time()))

    def should_stop(self) -> bool:
        path = self.kill_switch_file_path()
        if path.exists():
            return True
        # Also check stdin for STOP/PARA/KILL if interactive
        return False

    @staticmethod
    def parse_action_id(action_str: str) -> str:
        # Create a stable short id from command
        import hashlib
        return hashlib.sha1(action_str.encode()).hexdigest()[:12]
