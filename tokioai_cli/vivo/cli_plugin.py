"""
TokioAI Vivo - CLI Plugin (v5.0 - WorkEngine Integration)
Integrates `tokio --vivo` commands with work mode support.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _fmt_money(v: float) -> str:
    return f"${v:.3f}"


def _print_status(cfg, status: dict):
    mode = status.get("mode", "monitor").upper()
    print(f"\nTOKIO VIVO STATUS ({mode} MODE)")
    print(f"  objective: {status['objective']}")
    print(f"  running: {status['running']}  uptime: {status['uptime_s']}s  ticks: {status['ticks']}")
    print(f"  health: {status['health']:.2f}  autonomy: {cfg.autonomy}  dry_run: {cfg.dry_run}")
    t = status['token_summary']
    print(f"  cost: {_fmt_money(t['session_cost_usd'])} session | {_fmt_money(t['hourly_cost_usd'])}/hr | {_fmt_money(t['daily_cost_usd'])}/day")
    print(f"  calls: G2={t['gear2_calls_total']} total ({t['gear2_calls_hour']}/hr) | G3={t['gear3_calls_total']} total ({t['gear3_calls_hour']}/hr)")
    if status.get("mode") == "work":
        print(f"  work: cycles={status.get('work_cycles', 0)} steps={status.get('work_steps', 0)} done={status.get('work_done', False)} errors={status.get('consecutive_errors', 0)}")
    print(f"  recent events:")
    for e in status.get('recent_events', []):
        print(f"    - [{e.get('severity','info')}] {e.get('type')}: {e.get('details')}")


def add_vivo_arguments(parser: argparse.ArgumentParser):
    """Add --vivo related args to main CLI parser."""
    # NOTE: Most args are defined in interactive.py's main() directly.
    # This function is kept for backward compatibility but is not the primary arg source.
    pass


def handle_vivo_args(args) -> bool:
    """Return True if vivo handling consumed the invocation."""
    from .config import VivoConfig

    cfg = VivoConfig.load()

    if getattr(args, "vivo_stop", False):
        from .safety import SafetyEnforcer
        safety = SafetyEnforcer(cfg)
        safety.request_stop()
        print("[TOKIO VIVO] Stop requested. The running instance will exit on next tick.")
        return True

    if getattr(args, "vivo_status", False):
        from .world_memory import WorldMemory
        from .token_guard import TokenGuard
        memory = WorldMemory(cfg)
        guard = TokenGuard(cfg)
        status = {
            "running": cfg.pidfile.exists(),
            "uptime_s": 0,
            "ticks": 0,
            "health": memory.health_score(),
            "token_summary": guard.summary(),
            "recent_events": memory.recent_events(5),
            "objective": cfg.objective,
            "mode": "work" if cfg.work_mode else "monitor",
        }
        if cfg.pidfile.exists():
            try:
                pid = int(cfg.pidfile.read_text().strip())
                status["pid"] = pid
                status["running"] = os.path.exists(f"/proc/{pid}")
            except Exception:
                pass
        # Try to read work engine state
        work_log_path = cfg.vivo_dir / "work_log.json"
        if work_log_path.exists():
            try:
                import json
                data = json.loads(work_log_path.read_text())
                status["work_steps"] = data.get("steps_done", 0)
                status["work_cycles"] = data.get("steps_done", 0)
                status["work_done"] = False
                status["consecutive_errors"] = 0
            except Exception:
                pass
        _print_status(cfg, status)
        return True

    if getattr(args, "vivo_follow", False):
        log_path = cfg.vivo_dir / "vivo.log"
        if not log_path.exists():
            print(f"[TOKIO VIVO] No log file yet at {log_path}")
            return True
        print(f"[TOKIO VIVO] Following {log_path} (Ctrl+C to stop)...")
        try:
            import subprocess
            subprocess.run(["tail", "-f", str(log_path)])
        except KeyboardInterrupt:
            pass
        return True

    if getattr(args, "vivo_log", False):
        work_log_path = cfg.vivo_dir / "work_log.json"
        if not work_log_path.exists():
            print("[TOKIO VIVO] No work log yet.")
            return True
        import json
        data = json.loads(work_log_path.read_text())
        print(f"Steps: {data.get('steps_done', 0)}")
        print(f"Objective: {data.get('objective', '?')}")
        print(f"Git commits: {data.get('git_commits', 0)}")
        for entry in data.get("log", [])[-20:]:
            ts = time.strftime("%H:%M:%S", time.localtime(entry.get("ts", 0)))
            action = entry.get("action", "?")
            success = "OK" if entry.get("success") else "FAIL"
            gear = entry.get("gear", 2)
            reasoning = entry.get("reasoning", "")[:80]
            print(f"  [{ts}] G{gear} {action} -> {success}: {reasoning}")
        return True

    if getattr(args, "vivo_reset", False):
        import shutil
        # Reset work state but keep config
        for f in ["work_log.json", "state.yaml", "memory.json", "project_memory.json",
                   "actions.log", "metrics.jsonl", "git_audit.jsonl", "vivo.log", "vivo.pid"]:
            p = cfg.vivo_dir / f
            if p.exists():
                p.unlink()
        kill_switch = cfg.vivo_dir / "STOP"
        if kill_switch.exists():
            kill_switch.unlink()
        print("[TOKIO VIVO] State reset. Config preserved.")
        return True

    if not getattr(args, "vivo", False) and not getattr(args, "vivo_resume", False):
        return False

    # === Apply overrides from CLI args ===

    if getattr(args, "objective", None):
        cfg.objective = args.objective
    if getattr(args, "autonomy", None) is not None:
        cfg.autonomy = args.autonomy
    if getattr(args, "dry_run", None):
        cfg.dry_run = True
    if getattr(args, "no_dry_run", None):
        cfg.dry_run = False
    if getattr(args, "budget_hour", None) is not None:
        cfg.budget_hourly_usd = args.budget_hour
    if getattr(args, "budget_session", None) is not None:
        cfg.budget_session_usd = args.budget_session
    if getattr(args, "gear2_model", None):
        cfg.gear2_model = args.gear2_model
    if getattr(args, "gear3_model", None):
        cfg.gear3_model = args.gear3_model
    if getattr(args, "provider", None):
        cfg.provider = args.provider
    if getattr(args, "tick", None) is not None:
        cfg.tick_interval = args.tick
    if getattr(args, "report_every", None) is not None:
        cfg.report_interval = args.report_every
    if getattr(args, "cortex_interval", None) is not None:
        cfg.cortex_interval = args.cortex_interval

    # Work Engine overrides (v5.0)
    if getattr(args, "work", None):
        cfg.work_mode = True
    if getattr(args, "monitor", None):
        cfg.work_mode = False
    if getattr(args, "project_dir", None):
        cfg.project_dir = args.project_dir
    if getattr(args, "sandbox_dir", None):
        cfg.sandbox_dir = args.sandbox_dir
    if getattr(args, "test_cmd", None):
        cfg.test_command = args.test_cmd
    if getattr(args, "work_tick", None) is not None:
        cfg.work_tick_interval = args.work_tick

    # Dual model
    if getattr(args, "dual", False):
        cfg.dual_model = True

    # Git settings
    if getattr(args, "no_git_tests", False):
        cfg.git_require_tests = False
    if getattr(args, "git_auto_rollback", None) and not getattr(args, "no_git_auto_rollback", False):
        cfg.git_auto_rollback = True
    if getattr(args, "no_git_auto_rollback", False):
        cfg.git_auto_rollback = False
    if getattr(args, "git_test_cmd", None):
        cfg.test_command = args.git_test_cmd
    if getattr(args, "git_max_files", None) is not None:
        cfg.git_max_files_per_commit = args.git_max_files
    if getattr(args, "git_max_lines", None) is not None:
        cfg.git_max_lines_per_commit = args.git_max_lines

    # Hours limit
    hours = getattr(args, "hours", None)
    if hours:
        cfg.budget_session_usd = max(cfg.budget_session_usd, cfg.budget_hourly_usd * hours)

    # Resume mode: do NOT reset state
    is_resume = getattr(args, "vivo_resume", False)

    # Safety: if not explicit --autonomy and not --dry-run, default to dry_run for safety
    if getattr(args, "autonomy", None) is None and not cfg.dry_run and getattr(args, "dry_run", None) is None:
        print("[TOKIO VIVO] Safety: no --autonomy or --dry-run specified; defaulting to dry_run=True")
        cfg.dry_run = True

    cfg.save()

    # Background mode
    if getattr(args, "bg", False):
        _run_background(cfg)
        return True

    from .vivo_loop import run_vivo
    run_vivo(cfg)
    return True


def _run_background(cfg):
    """Fork to background and run vivo."""
    import subprocess
    cmd = [sys.executable, "-m", "tokioai_cli", "--vivo"]
    if cfg.objective != "keep the system healthy and responsive":
        cmd += ["--objective", cfg.objective]
    cmd += ["--autonomy", str(cfg.autonomy)]
    if not cfg.dry_run:
        cmd += ["--no-dry-run"]
    if cfg.work_mode:
        cmd += ["--work"]
    else:
        cmd += ["--monitor"]

    env = os.environ.copy()
    log_path = cfg.vivo_dir / "vivo.log"

    print(f"[TOKIO VIVO] Starting in background...")
    print(f"  log: {log_path}")
    print(f"  follow: tokioai --vivo-follow")
    print(f"  status: tokioai --vivo-status")
    print(f"  stop:   tokioai --vivo-stop")

    with open(log_path, "a") as log_f:
        proc = subprocess.Popen(
            cmd, env=env, stdout=log_f, stderr=log_f,
            start_new_session=True,
        )
    print(f"  pid: {proc.pid}")
