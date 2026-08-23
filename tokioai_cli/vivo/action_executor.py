"""
TokioAI Vivo - Action Executor
Runs approved actions locally or via robot proxy, with simulation support.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional


class ActionResult:
    def __init__(self, action: str, ok: bool, output: str = "", error: str = "",
                 simulated: bool = False, destructive: bool = False, approved: bool = False):
        self.action = action
        self.ok = ok
        self.output = output
        self.error = error
        self.simulated = simulated
        self.destructive = destructive
        self.approved = approved
        self.ts = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "action": self.action,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "simulated": self.simulated,
            "destructive": self.destructive,
            "approved": self.approved,
        }


class ActionExecutor:
    """Executes actions with safety checks and simulation."""

    def __init__(self, config, safety, memory, token_guard):
        from .config import VivoConfig
        from .safety import SafetyEnforcer
        from .world_memory import WorldMemory
        from .token_guard import TokenGuard
        self.cfg: VivoConfig = config
        self.safety: SafetyEnforcer = safety
        self.memory: WorldMemory = memory
        self.token_guard: TokenGuard = token_guard

    def _run_shell(self, cmd: str, timeout: int = 15) -> ActionResult:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return ActionResult(cmd, r.returncode == 0, r.stdout.strip(), r.stderr.strip())
        except Exception as e:
            return ActionResult(cmd, False, "", str(e))

    def _robot_action(self, action: str) -> ActionResult:
        """Translate robot actions to PiCar proxy calls."""
        proxy = self.cfg.picar_proxy_url or os.getenv("PICAR_PROXY_URL", "http://[REDACTED_IP_ADDRESS_142]:5000")
        try:
            import requests
            if action == "robot_stop_and_pivot":
                requests.post(f"{proxy}/stop", timeout=3)
                requests.post(f"{proxy}/pivot", json={"direction": "left", "angle": 30}, timeout=3)
                self.memory.record_turn("left")
                return ActionResult(action, True, "robot stopped and pivoted left 30", "")
            if action == "robot_reverse_and_scan":
                requests.post(f"{proxy}/backward", json={"speed": 20, "duration": 0.8}, timeout=3)
                requests.post(f"{proxy}/pivot", json={"direction": "right", "angle": 45}, timeout=3)
                self.memory.record_turn("right")
                return ActionResult(action, True, "robot reversed and scanned", "")
            if action == "robot_stop":
                requests.post(f"{proxy}/stop", timeout=3)
                return ActionResult(action, True, "robot stopped", "")
            if action == "robot_forward":
                requests.post(f"{proxy}/forward", json={"speed": 25, "duration": 0.5}, timeout=3)
                return ActionResult(action, True, "robot forward", "")
            if action == "robot_backward":
                requests.post(f"{proxy}/backward", json={"speed": 25, "duration": 0.5}, timeout=3)
                return ActionResult(action, True, "robot backward", "")
            if action == "robot_turn_left":
                requests.post(f"{proxy}/pivot", json={"direction": "left", "angle": 30}, timeout=3)
                self.memory.record_turn("left")
                return ActionResult(action, True, "robot turned left", "")
            if action == "robot_turn_right":
                requests.post(f"{proxy}/pivot", json={"direction": "right", "angle": 30}, timeout=3)
                self.memory.record_turn("right")
                return ActionResult(action, True, "robot turned right", "")
            return ActionResult(action, False, "", f"unknown robot action: {action}")
        except Exception as e:
            return ActionResult(action, False, "", f"robot proxy error: {e}")

    def execute(self, action: str, source: str = "brainstem") -> ActionResult:
        action = action.strip()
        if not action or action.lower() == "noop":
            return ActionResult(action, True, "no operation", simulated=False)

        check = self.safety.can_execute(action)
        destructive = check.get("destructive", False)
        simulated = check.get("dry_run", False) or self.cfg.dry_run

        if not check["ok"]:
            # Needs approval (autonomy 1) or blocked
            self.memory.add_event("action_blocked", "executor", "warning", {"action": action, "reason": check["reason"]})
            return ActionResult(action, False, "", check["reason"], simulated=False, destructive=destructive, approved=False)

        result: Optional[ActionResult] = None
        if simulated:
            result = ActionResult(action, True, f"[SIMULATED] would execute: {action}", "", simulated=True, destructive=destructive, approved=True)
        elif action.startswith("robot_"):
            result = self._robot_action(action)
            result.destructive = destructive
            result.simulated = simulated
            result.approved = True
        else:
            result = self._run_shell(action)
            result.destructive = destructive
            result.simulated = simulated
            result.approved = True

        from .safety import SafetyEnforcer
        self.safety.record_action(action, simulated, destructive, result.ok, SafetyEnforcer.parse_action_id(action))
        self.memory.add_event(
            "action_executed" if result.ok else "action_failed",
            source,
            "info" if result.ok else "error",
            result.to_dict(),
        )
        self._log_action(result)
        return result

    def execute_plan(self, plan: List[str], source: str = "cortex") -> List[ActionResult]:
        results = []
        for action in plan:
            if self.safety.should_stop():
                self.memory.add_event("execution_stopped", "executor", "warning", {"reason": "kill switch activated"})
                break
            results.append(self.execute(action, source))
            time.sleep(0.2)
        return results

    def _log_action(self, result: ActionResult):
        try:
            with open(self.cfg.actions_log, "a") as f:
                f.write(json.dumps(result.to_dict(), default=str) + "\n")
        except Exception:
            pass
