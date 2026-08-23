"""
TokioAI Vivo - Token Guard
Tracks token usage, call counts, and cost to enforce budgets.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class TokenSpend:
    ts: float
    gear: int
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class TokenGuardState:
    spends: List[TokenSpend] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    gear2_calls: int = 0
    gear3_calls: int = 0


class TokenGuard:
    """Budget-enforcing token guard with sliding windows."""

    # Approximate costs per 1M tokens (USD) for budgeting purposes.
    # Updated by cortex or user config if needed.
    DEFAULT_COSTS: Dict[str, Dict[str, float]] = {
        "meta-llama/llama-3.1-8b-instruct": {"input": 0.05, "output": 0.10},
        "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "anthropic/claude-3-haiku": {"input": 0.25, "output": 1.25},
        "moonshotai/kimi-k3": {"input": 3.00, "output": 12.00},
        "anthropic/claude-3-opus": {"input": 15.00, "output": 75.00},
        "anthropic/claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
        "google/gemini-1-5-pro": {"input": 1.25, "output": 5.00},
        "openai/gpt-4o": {"input": 2.50, "output": 10.00},
    }

    def __init__(self, config, state_path: Optional[Path] = None):
        from .config import VivoConfig
        self.cfg: VivoConfig = config
        self.state_path = state_path or config.vivo_dir / "token_guard.json"
        self.state = TokenGuardState()
        self._last_pruned = 0.0
        self.load()

    def _model_cost(self, model: str, kind: str) -> float:
        return self.DEFAULT_COSTS.get(model, {}).get(kind, 0.50 if kind == "input" else 2.00)

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        in_cost = (input_tokens / 1_000_000.0) * self._model_cost(model, "input")
        out_cost = (output_tokens / 1_000_000.0) * self._model_cost(model, "output")
        return round(in_cost + out_cost, 6)

    def record(self, gear: int, model: str, input_tokens: int, output_tokens: int):
        cost = self.estimate_cost(model, input_tokens, output_tokens)
        spend = TokenSpend(
            ts=time.time(),
            gear=gear,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self.state.spends.append(spend)
        self.state.total_cost_usd += cost
        self.state.total_input_tokens += input_tokens
        self.state.total_output_tokens += output_tokens
        if gear == 2:
            self.state.gear2_calls += 1
        elif gear == 3:
            self.state.gear3_calls += 1
        self._prune_old()
        self.save()

    def _window_cost(self, window_seconds: float) -> float:
        now = time.time()
        return sum(s.cost_usd for s in self.state.spends if now - s.ts <= window_seconds)

    def _window_calls(self, gear: int, window_seconds: float) -> int:
        now = time.time()
        return sum(1 for s in self.state.spends if s.gear == gear and now - s.ts <= window_seconds)

    def hourly_cost(self) -> float:
        return self._window_cost(3600.0)

    def daily_cost(self) -> float:
        return self._window_cost(86400.0)

    def can_use_gear(self, gear: int) -> Dict[str, any]:
        """Returns {'ok': bool, 'reason': str}."""
        if self.state.total_cost_usd >= self.cfg.budget_session_usd:
            return {"ok": False, "reason": f"session budget ${self.state.total_cost_usd:.3f}/${self.cfg.budget_session_usd:.2f} exceeded"}
        if self.hourly_cost() >= self.cfg.budget_hourly_usd:
            return {"ok": False, "reason": f"hourly budget ${self.hourly_cost():.3f}/${self.cfg.budget_hourly_usd:.2f} exceeded"}
        if self.daily_cost() >= self.cfg.budget_daily_usd:
            return {"ok": False, "reason": f"daily budget ${self.daily_cost():.3f}/${self.cfg.budget_daily_usd:.2f} exceeded"}

        limit = self.cfg.gear2_calls_per_hour if gear == 2 else self.cfg.gear3_calls_per_hour
        calls = self._window_calls(gear, 3600.0)
        if calls >= limit:
            return {"ok": False, "reason": f"gear {gear} call limit {calls}/{limit} per hour reached"}
        return {"ok": True, "reason": ""}

    def can_act(self, destructive: bool = False) -> Dict[str, any]:
        # Action rate limits tracked separately in executor; this is a fallback.
        return {"ok": True, "reason": ""}

    def _prune_old(self):
        now = time.time()
        if now - self._last_pruned < 60:
            return
        cutoff = now - 86400 * 7  # keep 7 days
        self.state.spends = [s for s in self.state.spends if s.ts > cutoff]
        self._last_pruned = now

    def summary(self) -> Dict[str, any]:
        return {
            "session_cost_usd": round(self.state.total_cost_usd, 4),
            "hourly_cost_usd": round(self.hourly_cost(), 4),
            "daily_cost_usd": round(self.daily_cost(), 4),
            "total_input_tokens": self.state.total_input_tokens,
            "total_output_tokens": self.state.total_output_tokens,
            "gear2_calls_total": self.state.gear2_calls,
            "gear3_calls_total": self.state.gear3_calls,
            "gear2_calls_hour": self._window_calls(2, 3600.0),
            "gear3_calls_hour": self._window_calls(3, 3600.0),
            "budget_hourly_usd": self.cfg.budget_hourly_usd,
            "budget_daily_usd": self.cfg.budget_daily_usd,
            "budget_session_usd": self.cfg.budget_session_usd,
        }

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self.state)
        data["spends"] = [asdict(s) for s in self.state.spends]
        with open(self.state_path, "w") as f:
            json.dump(data, f, indent=2)

    def load(self):
        if not self.state_path.exists():
            return
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            self.state.total_cost_usd = data.get("total_cost_usd", 0.0)
            self.state.total_input_tokens = data.get("total_input_tokens", 0)
            self.state.total_output_tokens = data.get("total_output_tokens", 0)
            self.state.gear2_calls = data.get("gear2_calls", 0)
            self.state.gear3_calls = data.get("gear3_calls", 0)
            self.state.spends = [TokenSpend(**s) for s in data.get("spends", [])]
        except Exception:
            self.state = TokenGuardState()
