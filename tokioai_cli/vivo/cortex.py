"""
TokioAI Vivo - Cortex
Reasoning layer: Gear 2 (cheap) for summaries/classification,
Gear 3 (expensive) for deep reasoning and planning.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional


class Cortex:
    """Token-efficient reasoning engine."""

    GEAR2_SYSTEM = """You are the Gear-2 fast cortex of TokioAI Vivo, an autonomous organism.
You receive a compressed world model and decide ONE of:
1. CLASSIFY anomaly severity (info/warning/error/critical).
2. SELECT the best pre-made plan from a list.
3. REQUEST Gear-3 if situation is novel or strategic.
Respond ONLY with valid JSON. No markdown. No explanation.
Output format:
{
  "decision": "classify|select_plan|escalate",
  "severity": "info|warning|error|critical",
  "plan": "name of selected plan or null",
  "escalate_to_gear3": false,
  "reason": "one short sentence",
  "actions": ["action1", "action2"]
}
"""

    GEAR3_SYSTEM = """You are the Gear-3 strategic cortex of TokioAI Vivo, an autonomous organism.
You receive a compressed world model with objective, health, anomalies, and recent actions.
Your job: reason deeply and return a concise plan. Be extremely terse to save tokens.
Rules:
- Assessment: max 2 sentences.
- Plan: max 3 actions.
- Each action must be an EXECUTABLE shell command or robot_* action (e.g. robot_stop). Do NOT use labels with colons.
- If multiple shell steps, chain with "&&" or ";".
- Prefer simple, low-risk actions.
- If destructive action needed, justify in 6 words.
- If uncertain, set needs_human=true and human_message to a one-line question.
- You may propose a new rule to learn.
Respond ONLY with valid JSON. No markdown. No explanation.
Output format:
{
  "assessment": "2 sentences max",
  "plan": ["action1", "action2"],
  "new_rule": {"condition": "...", "action": "...", "priority": 50} or null,
  "needs_human": false,
  "human_message": ""
}
"""

    def __init__(self, config, memory, token_guard, llm_client):
        from .config import VivoConfig
        self.cfg: VivoConfig = config
        self.memory = memory
        self.token_guard = token_guard
        self.llm = llm_client

    def maybe_review(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """Run Gear 2 review if interval passed or forced."""
        now = time.time()
        last = self.memory.state.last_cortex_ts or 0
        if not force and now - last < self.cfg.cortex_interval:
            return None

        budget_ok = self.token_guard.can_use_gear(2)
        if not budget_ok["ok"]:
            self.memory.add_event("cortex_gear2_skipped", "cortex", "warning", {"reason": budget_ok["reason"]})
            return None

        payload = self.memory.to_cortex_payload()
        user_prompt = json.dumps(payload, indent=2, default=str)
        result = self.llm.call_structured(2, self.GEAR2_SYSTEM, user_prompt, max_tokens=600)

        if result.get("ok"):
            self.token_guard.record(2, self.cfg.gear2_model, result.get("input_tokens", 0), result.get("output_tokens", 0))
            self.memory.state.last_cortex_ts = now
            self.memory.save()
            parsed = result.get("parsed") or {}
            self.memory.add_event("cortex_gear2_review", "cortex", parsed.get("severity", "info"), parsed)
            return parsed
        else:
            self.memory.add_event("cortex_gear2_error", "cortex", "error", {"error": result.get("error")})
            return {"decision": "error", "reason": result.get("error"), "actions": []}

    def reason(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run Gear 3 deep reasoning. Use sparingly."""
        budget_ok = self.token_guard.can_use_gear(3)
        if not budget_ok["ok"]:
            self.memory.add_event("cortex_gear3_skipped", "cortex", "warning", {"reason": budget_ok["reason"]})
            return {"assessment": budget_ok["reason"], "plan": [], "new_rule": None, "needs_human": True}

        payload = self.memory.to_cortex_payload()
        payload["trigger"] = context
        user_prompt = json.dumps(payload, indent=2, default=str)
        result = self.llm.call_structured(3, self.GEAR3_SYSTEM, user_prompt, max_tokens=500)

        if result.get("ok"):
            self.token_guard.record(3, self.cfg.gear3_model, result.get("input_tokens", 0), result.get("output_tokens", 0))
            parsed = result.get("parsed") or {}
            self.memory.add_event("cortex_gear3_reasoning", "cortex", "info", parsed)
            # Learn rule if proposed
            new_rule = parsed.get("new_rule")
            if new_rule:
                from .world_memory import Rule
                rule = Rule(
                    id=f"learned_{int(time.time())}",
                    condition=new_rule.get("condition", ""),
                    action=new_rule.get("action", ""),
                    priority=new_rule.get("priority", 50),
                    source="learned",
                )
                self.memory.add_or_update_rule(rule)
                self.memory.add_event("rule_learned", "cortex", "info", {"rule": rule.id})
            return parsed
        else:
            self.memory.add_event("cortex_gear3_error", "cortex", "error", {"error": result.get("error")})
            return {"assessment": f"Gear-3 error: {result.get('error')}", "plan": [], "new_rule": None, "needs_human": True}

    def should_escalate(self, brainstem_decision) -> bool:
        """Heuristic: if brainstem wants escalation or repeated failures, use Gear 3."""
        if brainstem_decision.escalate:
            return True
        recent = self.memory.recent_events(10, severity_min="warning")
        # If same event repeated 3+ times (except cortex internal errors counted separately)
        from collections import Counter
        types = [e.get("type") for e in recent if not e.get("type", "").startswith("cortex_gear2_error")]
        c = Counter(types)
        if any(v >= 3 for v in c.values()):
            return True
        # A single gear2 error is recoverable; escalate only on repeated gear2 errors
        gear2_errors = [e for e in recent if e.get("type") == "cortex_gear2_error"]
        if len(gear2_errors) >= 2:
            return True
        return False
