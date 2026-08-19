#!/usr/bin/env python3
"""
TokioAI Dual-Model Router — Intelligent auto-routing between two models.

Routes each request to the cheapest model that can handle it.
Default: Kimi K2.7-code (70% of requests) + Kimi K3 (30% of requests)

The router analyzes each message BEFORE sending it and decides:
  - SIMPLE → K2.7-code (fast, cheap, great for code/tools/commands)
  - COMPLEX → K3 (slower, expensive, better for reasoning/architecture/security)

The split is automatic. Users see which model handled each request.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

# ── Default model IDs (OpenRouter) ──
DEFAULT_PRIMARY = "moonshotai/kimi-k2.7-code"     # cheap, fast, code-focused
DEFAULT_SECONDARY = "moonshotai/kimi-k3"           # expensive, smart, reasoning

# ── Pricing per million tokens ──
PRICING = {
    "moonshotai/kimi-k2.7-code": {"input": 0.71, "output": 3.50},
    "moonshotai/kimi-k3":        {"input": 3.00, "output": 15.00},
}


@dataclass
class RouterStats:
    """Track usage per model."""
    primary_calls: int = 0
    secondary_calls: int = 0
    primary_input_tokens: int = 0
    primary_output_tokens: int = 0
    secondary_input_tokens: int = 0
    secondary_output_tokens: int = 0
    primary_model: str = DEFAULT_PRIMARY
    secondary_model: str = DEFAULT_SECONDARY
    # History of routing decisions for transparency
    last_decisions: list = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return self.primary_calls + self.secondary_calls

    @property
    def primary_ratio(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.primary_calls / self.total_calls

    @property
    def primary_cost(self) -> float:
        p = PRICING.get(self.primary_model, {"input": 1.0, "output": 5.0})
        return (self.primary_input_tokens * p["input"] + self.primary_output_tokens * p["output"]) / 1_000_000

    @property
    def secondary_cost(self) -> float:
        p = PRICING.get(self.secondary_model, {"input": 3.0, "output": 15.0})
        return (self.secondary_input_tokens * p["input"] + self.secondary_output_tokens * p["output"]) / 1_000_000

    @property
    def total_cost(self) -> float:
        return self.primary_cost + self.secondary_cost

    @property
    def savings_estimate(self) -> float:
        """Estimate how much money was saved vs using secondary for everything."""
        p_sec = PRICING.get(self.secondary_model, {"input": 3.0, "output": 15.0})
        all_secondary_cost = (
            (self.primary_input_tokens + self.secondary_input_tokens) * p_sec["input"]
            + (self.primary_output_tokens + self.secondary_output_tokens) * p_sec["output"]
        ) / 1_000_000
        return all_secondary_cost - self.total_cost

    def record(self, model: str, input_tokens: int, output_tokens: int):
        if model == self.primary_model:
            self.primary_calls += 1
            self.primary_input_tokens += input_tokens
            self.primary_output_tokens += output_tokens
        else:
            self.secondary_calls += 1
            self.secondary_input_tokens += input_tokens
            self.secondary_output_tokens += output_tokens

    def add_decision(self, query_preview: str, chosen: str, reason: str, score: int):
        self.last_decisions.append({
            "query": query_preview[:80],
            "model": "K2.7" if chosen == self.primary_model else "K3",
            "reason": reason,
            "score": score,
            "time": time.strftime("%H:%M:%S"),
        })
        # Keep last 20 decisions
        if len(self.last_decisions) > 20:
            self.last_decisions = self.last_decisions[-20:]


# ── Complexity keywords and patterns ──

# Keywords that indicate COMPLEX reasoning (-> K3)
_COMPLEX_KEYWORDS = {
    # Architecture & design
    "architect", "architecture", "design pattern", "system design", "trade-off",
    "tradeoff", "scalability", "microservice", "monolith", "distributed",
    # Security deep analysis
    "vulnerability", "vulnerabilities", "exploit", "penetration", "threat model",
    "attack surface", "zero-day", "0day", "reverse engineer", "malware", "forensic",
    "incident response", "cve-", "privilege escalation", "lateral movement",
    "persistence", "hardening",
    # Strategy & planning
    "strategy", "roadmap", "migration plan", "refactor", "rewrite from scratch",
    "pros and cons", "compare", "versus", "which is better", "recommend",
    "should i", "best approach", "best practice", "production deployment",
    "high load", "under load", "at scale",
    # Creative & complex reasoning
    "explain why", "reason about", "analyze", "deep dive", "in-depth",
    "philosophical", "ethical", "implication", "implications", "consequences",
    "security implication", "what are the", "how does.*work",
    "creative", "brainstorm", "innovate", "novel approach",
    # Multi-step reasoning
    "step by step", "walk me through", "comprehensive", "thorough",
    "full audit", "security audit", "complete review", "end to end", "from scratch",
    # Complex code tasks
    "optimize algorithm", "time complexity", "space complexity",
    "concurrency", "race condition", "deadlock", "memory leak",
    "compiler", "parser", "abstract syntax", "type system",
}

# Keywords that indicate SIMPLE tasks (-> K2.7-code)
_SIMPLE_KEYWORDS = {
    # Direct commands
    "run", "execute", "install", "restart", "start", "stop", "kill",
    "ls", "cat", "grep", "find", "chmod", "chown", "mkdir", "rm",
    "apt", "pip", "npm", "yarn", "docker", "systemctl", "journalctl",
    # Quick lookups
    "what is", "how to", "show me", "list", "check", "status",
    "version", "where is", "path to",
    # File operations
    "create file", "edit file", "read file", "write file", "delete file",
    "rename", "move", "copy",
    # Simple code
    "fix this", "fix bug", "add line", "remove line", "replace",
    "syntax error", "typo", "import", "function", "variable",
    # Network basics
    "ping", "curl", "wget", "ssh", "scp", "rsync",
    "ip address", "port", "firewall", "iptables", "ufw",
    # Git basics
    "git pull", "git push", "git commit", "git status", "git diff",
    "git log", "git branch", "git checkout", "git merge",
}

# Patterns that suggest complex multi-turn reasoning
_COMPLEX_PATTERNS = [
    r"\b(why|how)\b.*\b(work|fail|crash|break|slow|handle|manage)\b",  # "why does X fail" / "how does X handle"
    r"\b(design|build|create|implement)\b.*\b(system|platform|framework|engine|model|gateway)\b",
    r"\b(secure|harden|protect|defend)\b.*\b(against|from)\b",
    r"\b(compare|contrast|evaluate|assess)\b",
    r"\b(what if|suppose|imagine|consider)\b",
    r"\b(review|audit|analyze)\b.*\b(code|security|performance|infra|log|system|vulnerabilit)\b",
    r"\b(explain|explica)\b.*\b(detail|depth|thoroughly|fully)\b",
    r"\bin[- ]depth\b",  # "in depth" / "in-depth" anywhere
    r"\b(threat model|attack surface)\b",
    r"\b(ventajas y desventajas|pros y contras|mejor manera|mejor enfoque)\b",
    r"\b(escalaci[oó]n|privilegio|c[oó]mo funciona)\b",
]

# Patterns that suggest simple direct tasks
_SIMPLE_PATTERNS = [
    r"^(run|show|list|check|get|find|cat|read|open|close)\b",
    r"^(install|update|upgrade|remove|delete|uninstall)\b",
    r"^(create|make|add|write|edit|modify|change|set)\b\s+\w",
    r"^(restart|start|stop|enable|disable)\b\s+\w",
    r"^(fix|patch|update)\b\s+(the|this|that)\b",
    r"^(git|docker|kubectl|terraform|ansible)\b",
]


def classify_complexity(user_input: str, conversation_depth: int = 0,
                        has_tool_results: bool = False) -> tuple[str, str, int]:
    """
    Classify a user message as SIMPLE or COMPLEX.

    Returns: (model_id, reason, score)
      - score: 0-100 where 0=trivial, 100=extremely complex
      - score < 50 → PRIMARY (K2.7-code)
      - score >= 50 → SECONDARY (K3)
    """
    text = user_input.lower().strip()
    score = 25  # baseline: slightly simple
    reasons = []

    # ── Length heuristic ──
    word_count = len(text.split())
    if word_count <= 8:
        score -= 10
        reasons.append("short_query")
    elif word_count >= 50:
        score += 15
        reasons.append("long_query")
    elif word_count >= 100:
        score += 25
        reasons.append("very_long_query")

    # ── Question complexity ──
    question_marks = text.count("?")
    if question_marks >= 3:
        score += 15
        reasons.append("multi_question")
    elif question_marks == 0 and word_count <= 10 and not any(
        text.startswith(w) for w in ("how ", "why ", "what ", "explain", "compare",
                                      "design", "analyze", "analiza", "explica",
                                      "compara", "diseña", "evalua", "evalúa")
    ):
        score -= 5
        reasons.append("direct_command")

    # ── Keyword matching ──
    # Use word-boundary matching for short keywords to avoid false substring matches
    # (e.g. "rm" matching inside "perform", "ls" matching inside "false")
    def _kw_match(kw: str, txt: str) -> bool:
        if len(kw) <= 3:
            return bool(re.search(r'\b' + re.escape(kw) + r'\b', txt))
        return kw in txt

    complex_hits = sum(1 for kw in _COMPLEX_KEYWORDS if _kw_match(kw, text))
    simple_hits = sum(1 for kw in _SIMPLE_KEYWORDS if _kw_match(kw, text))

    if complex_hits > 0:
        score += min(complex_hits * 15, 60)  # each complex keyword is strong signal
        reasons.append(f"complex_kw({complex_hits})")
    if simple_hits > 0:
        # Simple keywords carry LESS weight when complex keywords are also present
        # (e.g. "analyze this code for vulnerabilities" has both "analyze" and "fix")
        simple_weight = 4 if complex_hits > 0 else 7
        score -= min(simple_hits * simple_weight, 20)
        reasons.append(f"simple_kw({simple_hits})")

    # ── Pattern matching ──
    complex_pattern_hits = 0
    for pat in _COMPLEX_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            complex_pattern_hits += 1
    if complex_pattern_hits > 0:
        # Pattern matches are strong signals — boost more with multiple hits
        score += complex_pattern_hits * 14
        reasons.append(f"complex_pat({complex_pattern_hits})")

    simple_pattern_hits = 0
    for pat in _SIMPLE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            simple_pattern_hits += 1
    if simple_pattern_hits > 0:
        score -= simple_pattern_hits * 8
        reasons.append(f"simple_pat({simple_pattern_hits})")

    # ── Code detection ──
    # If the message contains code blocks, likely a code task -> K2.7-code handles well
    if "```" in text or text.count("\n") > 5:
        score -= 10
        reasons.append("has_code")

    # ── Conversation depth ──
    # Follow-up messages in deep conversations are often simple refinements
    if conversation_depth > 5 and word_count < 20:
        score -= 10
        reasons.append("follow_up")

    # ── Tool results context ──
    # If previous turn had tool results, next is usually "analyze this" or "now do X"
    if has_tool_results:
        score -= 5
        reasons.append("post_tool")

    # ── Spanish language patterns ──
    es_complex = sum(1 for w in (
        "explicame", "explícame", "analiza", "compara", "diseña", "diseña",
        "cómo funciona", "como funciona", "por qué", "por que",
        "qué pasaría", "que pasaria", "recomienda", "evalúa", "evalua",
        "estrategia", "arquitectura", "vulnerabilidad", "vulnerabilidades",
        "implicacion", "implicaciones", "seguridad", "privilege",
        "escalation", "escalacion", "amenaza", "threat", "mejor enfoque",
        "mejor manera", "la mejor", "pros y contras", "ventajas y desventajas",
    ) if w in text)
    if es_complex > 0:
        score += es_complex * 10
        reasons.append(f"complex_es({es_complex})")
    if any(w in text for w in ("ejecuta", "instala", "reinicia", "muestra", "busca",
                                 "crea", "borra", "abre", "cierra", "revisa")):
        score -= 8
        reasons.append("simple_es")

    # ── Clamp score ──
    score = max(0, min(100, score))

    # ── Decision ──
    reason_str = "+".join(reasons) if reasons else "baseline"
    return score, reason_str


class DualModelRouter:
    """
    Routes requests between two models based on complexity analysis.

    Usage:
        router = DualModelRouter()
        model = router.route("fix this bug in line 42")  # -> K2.7-code
        model = router.route("design a microservice architecture for...")  # -> K3
    """

    def __init__(
        self,
        primary_model: str = DEFAULT_PRIMARY,
        secondary_model: str = DEFAULT_SECONDARY,
        threshold: int = 50,  # score >= threshold -> secondary
    ):
        self.primary_model = primary_model
        self.secondary_model = secondary_model
        self.threshold = threshold
        self.stats = RouterStats(primary_model=primary_model, secondary_model=secondary_model)
        self._force_model: Optional[str] = None  # manual override

    def force(self, model: Optional[str]):
        """Force a specific model for next N requests. None = auto."""
        self._force_model = model

    def route(self, user_input: str, conversation_depth: int = 0,
              has_tool_results: bool = False) -> str:
        """
        Decide which model to use for this request.

        Returns the model ID string.
        """
        # Manual override
        if self._force_model:
            model = self._force_model
            self.stats.add_decision(
                user_input, model, "forced", 0 if model == self.primary_model else 100
            )
            return model

        score, reason = classify_complexity(user_input, conversation_depth, has_tool_results)

        if score >= self.threshold:
            model = self.secondary_model
        else:
            model = self.primary_model

        self.stats.add_decision(user_input, model, reason, score)
        return model

    def record_usage(self, model: str, input_tokens: int, output_tokens: int):
        """Record token usage after a response."""
        self.stats.record(model, input_tokens, output_tokens)

    def format_stats(self) -> str:
        """Format router statistics for display."""
        s = self.stats
        lines = []
        lines.append(f"Dual Router: {s.primary_model.split('/')[-1]} + {s.secondary_model.split('/')[-1]}")
        lines.append(f"  Threshold: score >= {self.threshold} -> {s.secondary_model.split('/')[-1]}")
        lines.append(f"  Total calls: {s.total_calls}")
        if s.total_calls > 0:
            lines.append(f"  K2.7-code: {s.primary_calls} ({s.primary_ratio*100:.0f}%) | ${s.primary_cost:.4f}")
            lines.append(f"  K3:        {s.secondary_calls} ({(1-s.primary_ratio)*100:.0f}%) | ${s.secondary_cost:.4f}")
            lines.append(f"  Total cost: ${s.total_cost:.4f}")
            if s.savings_estimate > 0:
                lines.append(f"  Savings vs all-K3: ${s.savings_estimate:.4f}")
        if s.last_decisions:
            lines.append(f"  Last decisions:")
            for d in s.last_decisions[-5:]:
                lines.append(f"    [{d['time']}] {d['model']} (score={d['score']}) {d['query'][:50]}")
        return "\n".join(lines)

    def format_badge(self, model: str) -> str:
        """Short badge to show which model was used."""
        if model == self.primary_model:
            return "K2.7"
        elif model == self.secondary_model:
            return "K3"
        else:
            return model.split("/")[-1]
