"""TokioAI Security Layer — local PII/secrets sanitization before LLM calls.

Design principles:
- All scanning and redaction happens locally before any API call.
- We never upload detected secrets/PII. We replace them with stable placeholders.
- The layer is transparent: user sees a report of what was redacted.
- No false claims of perfection; the goal is "strong defence in depth".
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional


@dataclass
class Redaction:
    category: str          # e.g. 'api_key', 'email', 'private_key'
    detector: str          # name of the detector that matched
    placeholder: str       # e.g. '[REDACTED_API_KEY_1]'
    start: int
    end: int
    # We intentionally do NOT store the original value.


@dataclass
class SafetyReport:
    redactions: List[Redaction] = field(default_factory=list)
    blocked: bool = False
    block_reason: Optional[str] = None

    @property
    def redacted_categories(self) -> dict:
        counts: dict = {}
        for r in self.redactions:
            counts[r.category] = counts.get(r.category, 0) + 1
        return counts

    def summary(self) -> str:
        if not self.redactions and not self.blocked:
            return "Safety: clean"
        parts = []
        if self.blocked:
            parts.append(f"BLOCKED: {self.block_reason}")
        cats = self.redacted_categories
        if cats:
            items = ", ".join(f"{k}: {v}" for k, v in sorted(cats.items()))
            parts.append(f"redacted: {items}")
        return "Safety: " + "; ".join(parts)


class SecretPattern:
    """Named regex + category for a family of secrets."""

    def __init__(self, name: str, category: str, pattern: re.Pattern, priority: int = 0):
        self.name = name
        self.category = category
        self.pattern = pattern
        self.priority = priority


# ═══════════════════════════════════════════════════════════════════
# Built-in detectors
# ═══════════════════════════════════════════════════════════════════

def _build_default_patterns() -> List[SecretPattern]:
    patterns: List[SecretPattern] = []

    # API keys / tokens (common prefixes)
    patterns.append(SecretPattern(
        "generic_api_key",
        "api_key",
        re.compile(
            r"\b(?:api[_-]?key|apikey|auth[_-]?token|access[_-]?token|"
            r"secret[_-]?key|token|bearer|private[_-]?key)\s*[:=]\s*['\"]?"
            r"([a-zA-Z0-9_\-]{16,})['\"]?",
            re.IGNORECASE,
        ),
    ))

    # Explicit high-entropy tokens with known prefixes
    patterns.append(SecretPattern(
        "openai_api_key",
        "api_key",
        re.compile(r"\b(sk-(?:proj-|openai-)[a-zA-Z0-9]{32,})\b"),
    ))
    patterns.append(SecretPattern(
        "anthropic_api_key",
        "api_key",
        re.compile(r"\b(sk-ant-api03-[a-zA-Z0-9_-]{32,})\b"),
    ))
    patterns.append(SecretPattern(
        "openrouter_api_key",
        "api_key",
        re.compile(r"\b(sk-or-v1-[a-zA-Z0-9_-]{48,})\b"),
    ))
    patterns.append(SecretPattern(
        "google_api_key",
        "api_key",
        re.compile(r"\b(AIza[0-9A-Za-z_-]{35})\b"),
    ))
    patterns.append(SecretPattern(
        "github_pat",
        "api_key",
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,})\b"),
    ))
    patterns.append(SecretPattern(
        "aws_access_key",
        "api_key",
        re.compile(r"\b((?:AKIA|ASIA|AROA|AIDA)[A-Z0-9]{16})\b"),
    ))
    patterns.append(SecretPattern(
        "aws_secret_key",
        "api_key",
        re.compile(r"\b([A-Za-z0-9/+=]{40})\b"),
    ))

    # Passwords in connection strings / env vars
    patterns.append(SecretPattern(
        "password_assignment",
        "password",
        re.compile(
            r"\b(?:password|passwd|pwd|pass)\s*[:=]\s*['\"]?([^\s'\";]{8,})['\"]?",
            re.IGNORECASE,
        ),
    ))

    # Private keys / certificates
    patterns.append(SecretPattern(
        "pem_private_key",
        "private_key",
        re.compile(
            r"(-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
            r"[\s\S]{100,}?-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----)"
        ),
    ))

    # Email addresses
    patterns.append(SecretPattern(
        "email_address",
        "email",
        re.compile(r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b"),
    ))

    # Phone numbers (international-ish)
    patterns.append(SecretPattern(
        "phone_number",
        "phone",
        re.compile(r"\b(?:\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4})\b"),
    ))

    # IP addresses (v4 private ranges only)
    patterns.append(SecretPattern(
        "ipv4_address",
        "ip_address",
        re.compile(
            r"\b(?:10\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d))\."
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b|"
            r"\b127\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b|"
            r"\b172\.(?:1[6-9]|2[0-9]|3[01])\."
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b|"
            r"\b192\.168\."
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
        ),
    ))

    # Credit cards
    patterns.append(SecretPattern(
        "credit_card",
        "credit_card",
        re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    ))

    # National IDs (generic; add per-country as needed)
    patterns.append(SecretPattern(
        "generic_id_number",
        "national_id",
        re.compile(r"\b(?:dni|ssn|passport|nif|nie|cuil|cuit)\s*[:=]?\s*['\"]?([A-Za-z0-9]{6,20})['\"]?", re.IGNORECASE),
    ))

    # Database / connection strings
    patterns.append(SecretPattern(
        "connection_string",
        "connection_string",
        re.compile(
            r"\b((?:mongodb|postgres|mysql|redis|amqp|mqtts?)://"
            r"[^\s\"]+:[^\s\"]+@[^\s\"]+)\b",
            re.IGNORECASE,
        ),
    ))

    return patterns


class SafetyGuard:
    """Local, auditable sanitizer for LLM-bound messages."""

    def __init__(
        self,
        patterns: Optional[List[SecretPattern]] = None,
        allow_list: Optional[Iterable[str]] = None,
        paranoid: bool = False,
        block_categories: Optional[Iterable[str]] = None,
        on_detection: Optional[Callable[[SafetyReport], None]] = None,
    ):
        self.patterns = patterns if patterns is not None else _build_default_patterns()
        self.allow_list = set(allow_list or [])
        self.paranoid = paranoid
        self.block_categories = set(block_categories or [])
        self.on_detection = on_detection
        self._placeholder_counter: dict = {}

    def add_allow(self, value: str) -> "SafetyGuard":
        self.allow_list.add(value)
        return self

    def remove_allow(self, value: str) -> "SafetyGuard":
        self.allow_list.discard(value)
        return self

    def _next_placeholder(self, category: str) -> str:
        self._placeholder_counter[category] = self._placeholder_counter.get(category, 0) + 1
        n = self._placeholder_counter[category]
        return f"[REDACTED_{category.upper()}_{n}]"

    def scan(self, text: str) -> SafetyReport:
        """Scan text and return a report with non-overlapping redactions."""
        if not text:
            return SafetyReport()

        candidates: List[Redaction] = []

        for pat in self.patterns:
            for match in pat.pattern.finditer(text):
                value = match.group(0)
                if value in self.allow_list:
                    continue
                # Avoid matching obviously innocuous false positives
                if pat.name == "generic_api_key" and len(value) < 20:
                    continue
                if pat.name == "aws_secret_key" and not re.search(r"[A-Z]", value):
                    continue
                candidates.append(Redaction(
                    category=pat.category,
                    detector=pat.name,
                    placeholder=self._next_placeholder(pat.category),
                    start=match.start(),
                    end=match.end(),
                ))

        # Resolve overlaps: sort by start, then length descending, keep non-overlapping
        candidates.sort(key=lambda r: (r.start, -(r.end - r.start)))
        redactions: List[Redaction] = []
        last_end = -1
        for r in candidates:
            if r.start >= last_end:
                redactions.append(r)
                last_end = r.end

        report = SafetyReport(redactions=redactions)

        if self.block_categories:
            blocked = [r for r in redactions if r.category in self.block_categories]
            if blocked:
                report.blocked = True
                report.block_reason = (
                    f"blocked {len(blocked)} sensitive value(s) in categories: "
                    + ", ".join(sorted({r.category for r in blocked}))
                )

        if self.on_detection:
            self.on_detection(report)
        return report

    def sanitize(self, text: str) -> tuple[str, SafetyReport]:
        """Return sanitized text + report. Blocked text is returned unchanged but flagged."""
        report = self.scan(text)
        if report.blocked:
            return text, report

        # Apply redactions from end to start so indices stay valid
        out = text
        for r in sorted(report.redactions, key=lambda x: x.end, reverse=True):
            out = out[:r.start] + r.placeholder + out[r.end:]
        return out, report

    def sanitize_messages(self, messages: List[dict]) -> tuple[List[dict], List[SafetyReport]]:
        """Sanitize a list of message dicts (OpenAI/Anthropic shape)."""
        out: List[dict] = []
        reports: List[SafetyReport] = []
        for msg in messages:
            new_msg = dict(msg)
            content = new_msg.get("content")
            if isinstance(content, str):
                clean, report = self.sanitize(content)
                new_msg["content"] = clean
                reports.append(report)
            out.append(new_msg)
        return out, reports


# ═══════════════════════════════════════════════════════════════════
# Helpers for CLI integration
# ═══════════════════════════════════════════════════════════════════

def default_guard() -> SafetyGuard:
    """Factory for the guard used by the CLI."""
    paranoid = os.getenv("TOKIO_SAFETY_PARANOID", "0").lower() in ("1", "true", "yes")
    block_cats = os.getenv("TOKIO_SAFETY_BLOCK", "")
    block_list = [c.strip() for c in block_cats.split(",") if c.strip()] or None
    return SafetyGuard(paranoid=paranoid, block_categories=block_list)


def format_report(report: SafetyReport) -> str:
    if not report.redactions:
        return ""
    cats = report.redacted_categories
    parts = [f"{k}: {v}" for k, v in sorted(cats.items())]
    return f"[safety] redacted {'; '.join(parts)}"
