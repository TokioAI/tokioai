"""
TokioAI Vivo - Main Loop
The living organism loop: sense -> match -> act -> escalate -> learn -> report.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict


class VivoLoop:
    """Main autonomous loop."""

    def __init__(self, config):
        from .config import VivoConfig
        from .world_memory import WorldMemory
        from .token_guard import TokenGuard
        from .safety import SafetyEnforcer
        from .watchdogs import WatchdogManager
        from .brainstem import Brainstem
        from .cortex import Cortex
        from .action_executor import ActionExecutor
        from .llm_client import VivoLLMClient
        from .scheduler import Scheduler
        from .dashboard_server import DashboardServer

        self.cfg: VivoConfig = config
        self.memory = WorldMemory(config)
        self.token_guard = TokenGuard(config)
        self.safety = SafetyEnforcer(config)
        self.watchdogs = WatchdogManager(config)
        self.brainstem = Brainstem(config, self.memory)
        self.llm = VivoLLMClient(config)
        self.cortex = Cortex(config, self.memory, self.token_guard, self.llm)
        self.executor = ActionExecutor(config, self.safety, self.memory, self.token_guard)
        self.scheduler = Scheduler()
        self.dashboard = DashboardServer(config, self.memory, self.token_guard)

        self._running = False
        self._start_time = time.time()
        self._last_report = 0.0
        self._tick_count = 0
        self._setup_signals()
        self._write_pid()
        self._setup_scheduler()

    def _setup_signals(self):
        def handler(signum, frame):
            self.stop("signal")
        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    def _write_pid(self):
        try:
            self.cfg.pidfile.write_text(str(os.getpid()))
        except Exception:
            pass

    def _remove_pid(self):
        try:
            if self.cfg.pidfile.exists():
                self.cfg.pidfile.unlink()
        except Exception:
            pass

    def _setup_scheduler(self):
        # Periodic Gear-2 review
        self.scheduler.add("cortex_review", self.cfg.cortex_interval, self._run_cortex_review)
        # Telemetry / metrics write
        self.scheduler.add("telemetry", max(10.0, self.cfg.report_interval / 2), self._write_telemetry)

    def _run_cortex_review(self):
        return self.cortex.maybe_review(force=False)

    def _write_telemetry(self):
        metrics = {
            "ts": time.time(),
            "uptime_s": round(time.time() - self._start_time, 1),
            "tick": self._tick_count,
            "token_summary": self.token_guard.summary(),
            "health": self.memory.health_score(),
            "recent_events": len(self.memory.recent_events(50)),
        }
        try:
            with open(self.cfg.metrics_log, "a") as f:
                f.write(json.dumps(metrics) + "\n")
        except Exception:
            pass
        return metrics

    def _report(self, force: bool = False):
        now = time.time()
        if not force and now - self._last_report < self.cfg.report_interval:
            return
        self._last_report = now
        summary = {
            "ts": now,
            "objective": self.cfg.objective,
            "autonomy": self.cfg.autonomy,
            "dry_run": self.cfg.dry_run,
            "uptime_s": round(now - self._start_time, 1),
            "ticks": self._tick_count,
            "health": self.memory.health_score(),
            "token_summary": self.token_guard.summary(),
            "recent_events": self.memory.recent_events(5),
            "status": "alive",
        }
        self._print_report(summary)

    def _print_report(self, summary: Dict[str, Any]):
        ts = time.strftime("%H:%M:%S", time.localtime(summary["ts"]))
        print(f"\n[TOKIO VIVO {ts}] status=alive uptime={summary['uptime_s']}s health={summary['health']}")
        print(f"  objective: {summary['objective']}")
        print(f"  autonomy={summary['autonomy']} dry_run={summary['dry_run']}")
        tok = summary["token_summary"]
        print(f"  tokens: ${tok['session_cost_usd']:.3f} session | ${tok['hourly_cost_usd']:.3f}/hr | G2={tok['gear2_calls_hour']} G3={tok['gear3_calls_hour']}")
        if summary["recent_events"]:
            print("  recent events:")
            for e in summary["recent_events"]:
                print(f"    - [{e.get('severity','info')}] {e.get('type')}: {e.get('details')}")
        sys.stdout.flush()

    def tick(self) -> Dict[str, Any]:
        now = time.time()
        self._tick_count += 1

        # 1. Check kill switch
        if self.safety.should_stop():
            self.stop("kill_switch")
            return {"status": "stopped", "reason": "kill_switch"}

        # 2. Sense
        snapshot = self.watchdogs.snapshot()
        self.brainstem.update_memory_from_snapshot(snapshot)

        # 3. Reflex / match
        decision = self.brainstem.evaluate(snapshot)
        executed = []
        if decision.action and decision.action != "noop":
            res = self.executor.execute(decision.action, source="brainstem")
            executed.append(res.to_dict())

        # 4. Escalate if needed
        cortex_result = None
        if self.cortex.should_escalate(decision):
            cortex_result = self.cortex.reason({"brainstem_decision": decision.to_dict(), "snapshot": snapshot})
            plan = cortex_result.get("plan") or []
            if plan and not cortex_result.get("needs_human", False):
                results = self.executor.execute_plan(plan, source="cortex_gear3")
                executed.extend([r.to_dict() for r in results])

        # 5. Execute Gear2 actions if any (from periodic review)
        gear2_actions = self.memory.state.events
        gear2_pending = [e for e in gear2_actions if e.get("type") == "cortex_gear2_review" and e.get("details", {}).get("actions")]
        if gear2_pending:
            latest_gear2 = gear2_pending[-1]
            actions = latest_gear2.get("details", {}).get("actions", [])
            if actions and not latest_gear2.get("details", {}).get("executed", False):
                results = self.executor.execute_plan(actions, source="cortex_gear2")
                executed.extend([r.to_dict() for r in results])
                # Mark as executed
                latest_gear2["details"]["executed"] = True
                self.memory.save()

        # 5. Periodic scheduler (cortex review, telemetry)
        scheduled = self.scheduler.tick()

        # 6. Report
        self._report()

        return {
            "ts": now,
            "tick": self._tick_count,
            "decision": decision.to_dict(),
            "cortex": cortex_result,
            "executed": executed,
            "scheduled": scheduled,
        }

    def run(self):
        self._running = True
        print(f"[TOKIO VIVO] Starting organism mode...")
        print(f"  objective: {self.cfg.objective}")
        print(f"  autonomy={self.cfg.autonomy} dry_run={self.cfg.dry_run}")
        print(f"  budget: ${self.cfg.budget_hourly_usd}/hr | ${self.cfg.budget_session_usd}/session")
        print(f"  tick={self.cfg.tick_interval}s | cortex_interval={self.cfg.cortex_interval}s | report={self.cfg.report_interval}s")
        print(f"  kill switch: create file {self.safety.kill_switch_file_path()} or Ctrl+C")
        sys.stdout.flush()

        self.memory.add_event("vivo_started", "vivo_loop", "info", {
            "objective": self.cfg.objective,
            "autonomy": self.cfg.autonomy,
            "dry_run": self.cfg.dry_run,
        })
        self._report(force=True)

        try:
            while self._running:
                # Homeostasis: adjust tick based on health
                health = self.memory.health_score()
                if health < 0.3:
                    # Critical: slow down, be conservative
                    sleep_time = max(self.cfg.tick_interval * 3, 5.0)
                elif health < 0.6:
                    # Warning: slightly slower
                    sleep_time = max(self.cfg.tick_interval * 1.5, 3.0)
                else:
                    # Healthy: normal pace
                    sleep_time = self.cfg.tick_interval

                self.tick()

                # Adaptive sleep: if budget exceeded, slow down more
                if not self.token_guard.can_use_gear(2)["ok"]:
                    time.sleep(max(sleep_time, 10.0))
                else:
                    time.sleep(sleep_time)
        except KeyboardInterrupt:
            self.stop("keyboard_interrupt")
        finally:
            self._remove_pid()

    def stop(self, reason: str = "unknown"):
        if not self._running:
            return
        self._running = False
        self.memory.add_event("vivo_stopped", "vivo_loop", "info", {"reason": reason})
        print(f"\n[TOKIO VIVO] Stopping. Reason: {reason}")
        print(f"  final cost: ${self.token_guard.summary()['session_cost_usd']:.3f}")
        sys.stdout.flush()
        self._remove_pid()

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "uptime_s": round(time.time() - self._start_time, 1),
            "ticks": self._tick_count,
            "health": self.memory.health_score(),
            "token_summary": self.token_guard.summary(),
            "recent_events": self.memory.recent_events(5),
            "objective": self.cfg.objective,
        }


def run_vivo(config) -> VivoLoop:
    loop = VivoLoop(config)
    loop.run()
    return loop
