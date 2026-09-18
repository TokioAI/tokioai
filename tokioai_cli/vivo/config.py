"""
TokioAI Vivo - Configuration
Autonomous organism mode configuration and runtime state.
"""
from __future__ import annotations

import os
import yaml
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_VIVO_DIR = Path.home() / ".tokioai" / "vivo"
DEFAULT_CONFIG_PATH = DEFAULT_VIVO_DIR / "config.yaml"
DEFAULT_STATE_PATH = DEFAULT_VIVO_DIR / "state.yaml"
DEFAULT_MEMORY_PATH = DEFAULT_VIVO_DIR / "memory.json"
DEFAULT_ACTIONS_LOG = DEFAULT_VIVO_DIR / "actions.log"
DEFAULT_METRICS_LOG = DEFAULT_VIVO_DIR / "metrics.jsonl"
DEFAULT_RULES_PATH = DEFAULT_VIVO_DIR / "rules.yaml"
DEFAULT_PIDFILE = DEFAULT_VIVO_DIR / "vivo.pid"


@dataclass
class VivoConfig:
    objective: str = "keep the system healthy and responsive"
    autonomy: int = 1  # 0=simulation, 1=assisted, 2=trusted, 3=full
    dry_run: bool = True

    # Timing
    tick_interval: float = 2.0  # seconds for brainstem loop
    cortex_interval: float = 300.0  # seconds between Gear 2 reviews
    report_interval: float = 60.0  # seconds between CLI reports

    # Token guard / budget
    budget_hourly_usd: float = 0.50
    budget_daily_usd: float = 5.00
    budget_session_usd: float = 10.00
    gear2_calls_per_hour: int = 60
    gear3_calls_per_hour: int = 5
    max_actions_per_hour: int = 200
    max_destructive_per_hour: int = 10

    # Models
    gear2_model: str = "meta-llama/llama-3.1-8b-instruct"
    gear3_model: str = "moonshotai/kimi-k3"
    provider: str = "openrouter"  # or vertex, anthropic, openai, gemini

    # Paths
    vivo_dir: Path = field(default_factory=lambda: DEFAULT_VIVO_DIR)
    state_path: Path = field(default_factory=lambda: DEFAULT_STATE_PATH)
    memory_path: Path = field(default_factory=lambda: DEFAULT_MEMORY_PATH)
    actions_log: Path = field(default_factory=lambda: DEFAULT_ACTIONS_LOG)
    metrics_log: Path = field(default_factory=lambda: DEFAULT_METRICS_LOG)
    rules_path: Path = field(default_factory=lambda: DEFAULT_RULES_PATH)
    pidfile: Path = field(default_factory=lambda: DEFAULT_PIDFILE)

    # Safety
    destructive_whitelist: List[str] = field(default_factory=lambda: [
        "systemctl restart",
        "docker restart",
        "pkill -f",
        "shutdown -r",
        "reboot",
    ])
    blocked_commands: List[str] = field(default_factory=lambda: [
        "rm -rf /",
        "mkfs",
        "dd if=/dev/zero",
        ":(){ :|:& };:",
        "format",
    ])
    allowed_hosts: List[str] = field(default_factory=lambda: ["localhost", "127.0.0.1"])

    # Work Engine (autonomous task execution)
    work_mode: bool = True  # True = objective-driven work, False = monitoring-only
    sandbox_dir: Optional[str] = None  # restrict file writes to this dir (None = unrestricted)
    project_dir: Optional[str] = None  # working directory for work engine
    test_command: Optional[str] = None  # e.g. "pytest", "npm test" (auto-detected if None)
    dual_model: bool = True  # use gear2 for routine, gear3 for deep reasoning
    work_tick_interval: float = 5.0  # seconds between work cycles (separate from monitor tick)
    monitor_while_working: bool = False  # run brainstem/cortex alongside work engine

    # Git-safe settings (used by work engine)
    git_branch_prefix: str = "vivo/"
    git_require_tests: bool = True
    git_require_review: bool = False
    git_auto_rollback: bool = True
    git_auto_pr: bool = False
    git_max_files_per_commit: int = 10
    git_max_lines_per_commit: int = 500

    # Sensors / integrations
    enable_system_watchdogs: bool = True
    enable_picar_watchdogs: bool = False
    enable_network_watchdogs: bool = True
    enable_log_watchdogs: bool = False
    picar_proxy_url: Optional[str] = None
    tokionav_state_path: Optional[Path] = None

    # Notification
    notify_on_anomaly: bool = False
    notify_command: Optional[str] = None  # e.g. "ntfy send 'alert'"

    def __post_init__(self):
        for p in ["vivo_dir", "state_path", "memory_path", "actions_log", "metrics_log", "rules_path", "pidfile"]:
            val = getattr(self, p)
            if isinstance(val, str):
                setattr(self, p, Path(val))
        self.vivo_dir.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Path):
                d[k] = str(v)
        return d

    def save(self, path: Optional[Path] = None) -> None:
        path = path or DEFAULT_CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "VivoConfig":
        path = path or DEFAULT_CONFIG_PATH
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        # Convert paths back
        for p in ["vivo_dir", "state_path", "memory_path", "actions_log", "metrics_log", "rules_path", "pidfile"]:
            if p in data and isinstance(data[p], str):
                data[p] = Path(data[p])
        # Filter unknown keys
        known = {k for k in cls.__dataclass_fields__}
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)

    def effective_model(self, gear: int) -> str:
        if gear == 2:
            return self.gear2_model
        if gear == 3:
            return self.gear3_model
        return self.gear2_model


def load_env_or_config() -> VivoConfig:
    """Load config, with env overrides for sensitive/common knobs."""
    cfg = VivoConfig.load()

    if os.environ.get("TOKIO_VIVO_OBJECTIVE"):
        cfg.objective = os.environ["TOKIO_VIVO_OBJECTIVE"]
    if os.environ.get("TOKIO_VIVO_AUTONOMY"):
        cfg.autonomy = int(os.environ["TOKIO_VIVO_AUTONOMY"])
    if os.environ.get("TOKIO_VIVO_DRY_RUN"):
        cfg.dry_run = os.environ["TOKIO_VIVO_DRY_RUN"].lower() in ("1", "true", "yes")
    if os.environ.get("TOKIO_VIVO_BUDGET_HOUR"):
        cfg.budget_hourly_usd = float(os.environ["TOKIO_VIVO_BUDGET_HOUR"])
    if os.environ.get("TOKIO_VIVO_PROVIDER"):
        cfg.provider = os.environ["TOKIO_VIVO_PROVIDER"]
    if os.environ.get("TOKIO_VIVO_GEAR2_MODEL"):
        cfg.gear2_model = os.environ["TOKIO_VIVO_GEAR2_MODEL"]
    if os.environ.get("TOKIO_VIVO_GEAR3_MODEL"):
        cfg.gear3_model = os.environ["TOKIO_VIVO_GEAR3_MODEL"]

    return cfg
