"""
TokioAI Vivo - Main Loop (v5.0 - WorkEngine Integration)
The living organism loop with two modes:
  WORK MODE:   objective -> work_engine.work_cycle() -> execute structured actions (read/write/edit/run/git/test)
  MONITOR MODE: sense -> brainstem match -> cortex escalate -> action_executor (raw shell commands)

WorkEngine is the brain that DOES real work: code, test, fix, commit.
Brainstem/Cortex are the reflex layer for system monitoring.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


class VivoLoop:
    """Main autonomous loop with WorkEngine integration."""

    def __init__(self, config):
        from .config import VivoConfig
        from .world_memory import WorldMemory
        from .token_guard import TokenGuard
        from .safety import SafetyEnforcer
        from .llm_client import VivoLLMClient
        from .scheduler import Scheduler
        from .dashboard_server import DashboardServer
        from .vivo_output import VivoOutput

        self.cfg: VivoConfig = config
        self.memory = WorldMemory(config)
        self.token_guard = TokenGuard(config)
        self.safety = SafetyEnforcer(config)
        self.llm = VivoLLMClient(config)
        self.scheduler = Scheduler()
        self.dashboard = DashboardServer(config, self.memory, self.token_guard)

        # Output isolation
        self.output = VivoOutput(
            log_path=config.vivo_dir / "vivo.log",
            is_daemon=False,
        )

        # Work Engine (primary task execution)
        self.work_engine = None
        self._work_mode = config.work_mode

        if self._work_mode:
            from .work_engine import WorkEngine
            self.work_engine = WorkEngine(
                config=config,
                token_guard=self.token_guard,
                safety=self.safety,
                llm_client=self.llm,
                output=self.output,
            )
            # Change to project dir if specified
            if config.project_dir:
                project_dir = Path(config.project_dir).expanduser().resolve()
                if project_dir.exists():
                    os.chdir(str(project_dir))
                    self.output.line(f"  [work] project dir: {project_dir}")

        # Monitor subsystems (brainstem + cortex + watchdogs + executor)
        # Only fully initialized if monitor_while_working or not in work mode
        self._monitor_enabled = not self._work_mode or config.monitor_while_working
        self.brainstem = None
        self.cortex = None
        self.executor = None
        self.watchdogs = None

        if self._monitor_enabled:
            from .watchdogs import WatchdogManager
            from .brainstem import Brainstem
            from .cortex import Cortex
            from .action_executor import ActionExecutor
            self.watchdogs = WatchdogManager(config)
            self.brainstem = Brainstem(config, self.memory)
            self.cortex = Cortex(config, self.memory, self.token_guard, self.llm)
            self.executor = ActionExecutor(config, self.safety, self.memory, self.token_guard)

        self._running = False
        self._start_time = time.time()
        self._last_report = 0.0
        self._tick_count = 0
        self._work_cycles = 0
        self._work_done = False
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10
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
        # Telemetry / metrics write
        self.scheduler.add("telemetry", max(10.0, self.cfg.report_interval / 2), self._write_telemetry)
        # If monitoring alongside work, add cortex review
        if self._monitor_enabled and self.cortex:
            self.scheduler.add("cortex_review", self.cfg.cortex_interval, self._run_cortex_review)

    def _run_cortex_review(self):
        if self.cortex:
            return self.cortex.maybe_review(force=False)
        return None

    def _write_telemetry(self):
        metrics = {
            "ts": time.time(),
            "uptime_s": round(time.time() - self._start_time, 1),
            "tick": self._tick_count,
            "mode": "work" if self._work_mode else "monitor",
            "work_cycles": self._work_cycles,
            "work_done": self._work_done,
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
        tok = self.token_guard.summary()
        mode = "WORK" if self._work_mode else "MONITOR"
        ts = time.strftime("%H:%M:%S", time.localtime(now))
        uptime = round(now - self._start_time, 1)

        lines = [
            f"",
            f"[TOKIO VIVO {ts}] mode={mode} uptime={uptime}s health={self.memory.health_score():.2f}",
            f"  objective: {self.cfg.objective}",
            f"  autonomy={self.cfg.autonomy} dry_run={self.cfg.dry_run}",
            f"  tokens: ${tok['session_cost_usd']:.3f} session | ${tok['hourly_cost_usd']:.3f}/hr | G2={tok['gear2_calls_hour']} G3={tok['gear3_calls_hour']}",
        ]
        if self._work_mode:
            lines.append(f"  work: {self._work_cycles} cycles | done={self._work_done} | errors={self._consecutive_errors}")
            if self.work_engine:
                lines.append(f"  steps: {self.work_engine.steps_done}/{self.work_engine.steps_max}")
        events = self.memory.recent_events(5)
        if events:
            lines.append("  recent events:")
            for e in events:
                lines.append(f"    - [{e.get('severity','info')}] {e.get('type')}: {e.get('details')}")

        report_text = "\n".join(lines)
        self.output.line(report_text)
        # Also print to stdout for foreground visibility
        print(report_text)
        sys.stdout.flush()

    def _tick_work(self) -> Dict[str, Any]:
        """Execute one work cycle via WorkEngine."""
        if not self.work_engine or self._work_done:
            return {"status": "idle", "reason": "work_done" if self._work_done else "no_engine"}

        try:
            result = self.work_engine.work_cycle()
        except Exception as e:
            self._consecutive_errors += 1
            error_msg = f"work_cycle exception: {e}"
            self.output.line(f"  \033[31m[error]\033[0m {error_msg}")
            self.memory.add_event("work_error", "work_engine", "error", {"error": error_msg})
            if self._consecutive_errors >= self._max_consecutive_errors:
                self.output.line(f"  \033[31m[FATAL]\033[0m {self._max_consecutive_errors} consecutive errors. Stopping.")
                self.stop("consecutive_errors")
            return {"status": "error", "error": error_msg}

        self._work_cycles += 1
        action = result.get("action", "unknown")

        # Reset consecutive errors on success
        if result.get("result", {}).get("success", False) if isinstance(result.get("result"), dict) else False:
            self._consecutive_errors = 0
        elif action in ("think", "memory_read", "memory_write", "read_file", "grep_file", "list_dir", "git_status"):
            # These are inherently "successful" even if not explicitly marked
            self._consecutive_errors = 0
        elif action in ("llm_error", "parse_error"):
            self._consecutive_errors += 1
        else:
            # Partial reset for non-critical failures
            self._consecutive_errors = max(0, self._consecutive_errors - 1)

        # Check if work is done
        if result.get("done", False):
            self._work_done = True
            self.output.line(f"\n  \033[32m\033[1m[WORK COMPLETE]\033[0m Objective achieved after {self._work_cycles} cycles, {self.work_engine.steps_done} steps")
            self.memory.add_event("work_complete", "work_engine", "info", {
                "cycles": self._work_cycles,
                "steps": self.work_engine.steps_done,
                "objective": self.cfg.objective,
            })

        # Check budget exhaustion
        if result.get("budget_exhausted", False):
            self.output.line(f"  \033[33m[budget]\033[0m Budget exhausted, waiting...")

        return {
            "status": "work",
            "action": action,
            "step": result.get("step", 0),
            "gear": result.get("gear", 2),
            "done": result.get("done", False),
            "budget_exhausted": result.get("budget_exhausted", False),
        }

    def _tick_monitor(self) -> Dict[str, Any]:
        """Execute one monitor cycle via Brainstem + Cortex."""
        if not self._monitor_enabled or not self.brainstem:
            return {"status": "monitor_disabled"}

        # 1. Sense
        snapshot = self.watchdogs.snapshot() if self.watchdogs else {}
        self.brainstem.update_memory_from_snapshot(snapshot)

        # 2. Reflex / match
        decision = self.brainstem.evaluate(snapshot)
        executed = []
        if decision.action and decision.action != "noop":
            res = self.executor.execute(decision.action, source="brainstem")
            executed.append(res.to_dict())

        # 3. Escalate if needed
        cortex_result = None
        if self.cortex and self.cortex.should_escalate(decision):
            cortex_result = self.cortex.reason({"brainstem_decision": decision.to_dict(), "snapshot": snapshot})
            plan = cortex_result.get("plan") or []
            if plan and not cortex_result.get("needs_human", False):
                results = self.executor.execute_plan(plan, source="cortex_gear3")
                executed.extend([r.to_dict() for r in results])

        return {
            "status": "monitor",
            "decision": decision.to_dict(),
            "cortex": cortex_result,
            "executed": executed,
        }

    def tick(self) -> Dict[str, Any]:
        now = time.time()
        self._tick_count += 1

        # 1. Check kill switch
        if self.safety.should_stop():
            self.stop("kill_switch")
            return {"status": "stopped", "reason": "kill_switch"}

        # 2. Execute work or monitor
        if self._work_mode and not self._work_done:
            tick_result = self._tick_work()
        elif self._monitor_enabled:
            tick_result = self._tick_monitor()
        else:
            tick_result = {"status": "idle"}

        # 3. If work is done and not monitoring, stop
        if self._work_done and not self._monitor_enabled:
            self.stop("work_complete")

        # 4. Periodic scheduler (cortex review, telemetry)
        scheduled = self.scheduler.tick()

        # 5. Report
        self._report()

        return {
            "ts": now,
            "tick": self._tick_count,
            **tick_result,
            "scheduled": scheduled,
        }

    def run(self):
        self._running = True
        mode = "WORK" if self._work_mode else "MONITOR"
        print(f"[TOKIO VIVO] Starting organism mode ({mode})...")
        print(f"  objective: {self.cfg.objective}")
        print(f"  autonomy={self.cfg.autonomy} dry_run={self.cfg.dry_run}")
        print(f"  budget: ${self.cfg.budget_hourly_usd}/hr | ${self.cfg.budget_session_usd}/session")
        if self._work_mode:
            print(f"  work_engine: ON | dual_model={self.cfg.dual_model} | gear2={self.cfg.gear2_model} gear3={self.cfg.gear3_model}")
            print(f"  work_tick={self.cfg.work_tick_interval}s | monitor={'ON' if self._monitor_enabled else 'OFF'}")
            if self.cfg.sandbox_dir:
                print(f"  sandbox: {self.cfg.sandbox_dir}")
            if self.cfg.project_dir:
                print(f"  project: {self.cfg.project_dir}")
        else:
            print(f"  tick={self.cfg.tick_interval}s | cortex_interval={self.cfg.cortex_interval}s | report={self.cfg.report_interval}s")
        print(f"  kill switch: create file {self.safety.kill_switch_file_path()} or Ctrl+C")
        sys.stdout.flush()

        self.memory.add_event("vivo_started", "vivo_loop", "info", {
            "objective": self.cfg.objective,
            "autonomy": self.cfg.autonomy,
            "dry_run": self.cfg.dry_run,
            "mode": mode.lower(),
            "work_engine": self._work_mode,
        })
        self._report(force=True)

        try:
            while self._running:
                # Determine tick interval based on mode and state
                if self._work_mode and not self._work_done:
                    # Work mode: use work_tick_interval
                    sleep_time = self.cfg.work_tick_interval

                    # If budget exhausted, slow down
                    if not self.token_guard.can_use_gear(2)["ok"]:
                        sleep_time = max(sleep_time, 15.0)

                    # If too many errors, slow down
                    if self._consecutive_errors >= 3:
                        sleep_time = max(sleep_time, 10.0)
                else:
                    # Monitor mode or work complete: homeostasis
                    health = self.memory.health_score()
                    if health < 0.3:
                        sleep_time = max(self.cfg.tick_interval * 3, 5.0)
                    elif health < 0.6:
                        sleep_time = max(self.cfg.tick_interval * 1.5, 3.0)
                    else:
                        sleep_time = self.cfg.tick_interval

                self.tick()
                time.sleep(sleep_time)
        except KeyboardInterrupt:
            self.stop("keyboard_interrupt")
        finally:
            self._cleanup()

    def stop(self, reason: str = "unknown"):
        if not self._running:
            return
        self._running = False
        self.memory.add_event("vivo_stopped", "vivo_loop", "info", {"reason": reason})

        tok = self.token_guard.summary()
        lines = [
            f"\n[TOKIO VIVO] Stopping. Reason: {reason}",
            f"  final cost: ${tok['session_cost_usd']:.3f}",
        ]
        if self._work_mode:
            lines.append(f"  work cycles: {self._work_cycles} | steps: {self.work_engine.steps_done if self.work_engine else 0}")
            lines.append(f"  work done: {self._work_done}")

        stop_msg = "\n".join(lines)
        print(stop_msg)
        self.output.line(stop_msg)
        sys.stdout.flush()

    def _cleanup(self):
        """Cleanup on exit."""
        self._remove_pid()
        if self.output:
            self.output.close()

    def status(self) -> Dict[str, Any]:
        s = {
            "running": self._running,
            "uptime_s": round(time.time() - self._start_time, 1),
            "ticks": self._tick_count,
            "health": self.memory.health_score(),
            "token_summary": self.token_guard.summary(),
            "recent_events": self.memory.recent_events(5),
            "objective": self.cfg.objective,
            "mode": "work" if self._work_mode else "monitor",
        }
        if self._work_mode:
            s["work_cycles"] = self._work_cycles
            s["work_done"] = self._work_done
            s["work_steps"] = self.work_engine.steps_done if self.work_engine else 0
            s["consecutive_errors"] = self._consecutive_errors
        return s


def run_vivo(config) -> VivoLoop:
    loop = VivoLoop(config)
    loop.run()
    return loop
