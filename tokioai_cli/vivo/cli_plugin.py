"""
TokioAI Vivo - CLI Plugin
Integrates `tokio --vivo` commands.
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
    print(f"\nTOKIO VIVO STATUS")
    print(f"  objective: {status['objective']}")
    print(f"  running: {status['running']}  uptime: {status['uptime_s']}s  ticks: {status['ticks']}")
    print(f"  health: {status['health']:.2f}  autonomy: {cfg.autonomy}  dry_run: {cfg.dry_run}")
    t = status['token_summary']
    print(f"  cost: {_fmt_money(t['session_cost_usd'])} session | {_fmt_money(t['hourly_cost_usd'])}/hr | {_fmt_money(t['daily_cost_usd'])}/day")
    print(f"  calls: G2={t['gear2_calls_total']} total ({t['gear2_calls_hour']}/hr) | G3={t['gear3_calls_total']} total ({t['gear3_calls_hour']}/hr)")
    print(f"  recent events:")
    for e in status['recent_events']:
        print(f"    - [{e.get('severity','info')}] {e.get('type')}: {e.get('details')}")


def add_vivo_arguments(parser: argparse.ArgumentParser):
    """Add --vivo related args to main CLI parser."""
    parser.add_argument("--vivo", action="store_true", help="Enter autonomous organism mode")
    parser.add_argument("--vivo-stop", action="store_true", help="Stop a running vivo instance")
    parser.add_argument("--vivo-status", action="store_true", help="Show vivo status")
    parser.add_argument("--objective", default=None, help="Set vivo objective")
    parser.add_argument("--autonomy", type=int, default=None, choices=[0, 1, 2, 3], help="Autonomy level (0=sim,1=assisted,2=trusted,3=full)")
    parser.add_argument("--dry-run", action="store_true", default=None, help="Simulate actions")
    parser.add_argument("--budget-hour", type=float, default=None, help="Hourly budget USD")
    parser.add_argument("--budget-session", type=float, default=None, help="Session budget USD")
    parser.add_argument("--gear2-model", default=None, help="Gear 2 model")
    parser.add_argument("--gear3-model", default=None, help="Gear 3 model")
    parser.add_argument("--provider", default=None, help="LLM provider for vivo")
    parser.add_argument("--tick", type=float, default=None, help="Tick interval seconds")
    parser.add_argument("--report-every", type=float, default=None, help="Report interval seconds")


def handle_vivo_args(args) -> bool:
    """Return True if vivo handling consumed the invocation."""
    from .config import VivoConfig

    cfg = VivoConfig.load()

    if args.vivo_stop:
        from .safety import SafetyEnforcer
        safety = SafetyEnforcer(cfg)
        safety.request_stop()
        print("[TOKIO VIVO] Stop requested. The running instance will exit on next tick.")
        return True

    if args.vivo_status:
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
        }
        if cfg.pidfile.exists():
            try:
                pid = int(cfg.pidfile.read_text().strip())
                status["pid"] = pid
                status["running"] = os.path.exists(f"/proc/{pid}")
            except Exception:
                pass
        _print_status(cfg, status)
        return True

    if not args.vivo:
        return False

    # Apply overrides
    if args.objective:
        cfg.objective = args.objective
    if args.autonomy is not None:
        cfg.autonomy = args.autonomy
    if args.dry_run is not None:
        cfg.dry_run = True
    if getattr(args, "no_dry_run", None):
        cfg.dry_run = False
    if args.budget_hour is not None:
        cfg.budget_hourly_usd = args.budget_hour
    if args.budget_session is not None:
        cfg.budget_session_usd = args.budget_session
    if args.gear2_model:
        cfg.gear2_model = args.gear2_model
    if args.gear3_model:
        cfg.gear3_model = args.gear3_model
    if args.provider:
        cfg.provider = args.provider
    if args.tick:
        cfg.tick_interval = args.tick
    if args.report_every:
        cfg.report_interval = args.report_every
    if getattr(args, "cortex_interval", None):
        cfg.cortex_interval = args.cortex_interval

    # Safety: if not explicit --autonomy and not --dry-run, default to dry_run for safety
    if args.autonomy is None and not cfg.dry_run and args.dry_run is None:
        print("[TOKIO VIVO] Safety: no --autonomy or --dry-run specified; defaulting to dry_run=True")
        cfg.dry_run = True

    cfg.save()

    from .vivo_loop import run_vivo
    run_vivo(cfg)
    return True
