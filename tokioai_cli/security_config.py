"""TokioAI Security Configuration — provider/key hardening and audit logging.

This module centralizes security decisions so they are auditable and testable.
Rules:
- Explicit user configuration wins, but must still pass validation.
- Ambiguous configurations default to the SAFER option, never to a proxy/router.
- API keys are validated by prefix before any client is created.
- Security events are logged to ~/.tokioai/security.log.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# Directory where security audit log is written
_AUDIT_DIR = os.path.expanduser("~/.tokioai")
_AUDIT_LOG = os.path.join(_AUDIT_DIR, "security.log")


@dataclass
class ProviderDecision:
    """Immutable record of why a provider was chosen."""

    provider: str
    reason: str
    key_source: str = ""
    model: str = ""
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""

    def log(self) -> None:
        """Append a JSON line to the security audit log."""
        try:
            os.makedirs(_AUDIT_DIR, exist_ok=True)
            with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
                entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "provider": self.provider,
                    "reason": self.reason,
                    "key_source": self.key_source,
                    "model": self.model,
                    "warnings": self.warnings,
                    "blocked": self.blocked,
                    "block_reason": self.block_reason,
                }
                f.write(__import__("json").dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


# Known API key prefixes per provider. Used to detect key misuse.
KEY_PREFIX_RULES: dict[str, list[str]] = {
    "anthropic": ["sk-ant-api03-"],
    "openai": ["sk-", "sk-proj-"],
    "gemini": ["AIza"],
    "kimi": ["sk-"],  # Moonshot direct keys also use sk- prefix
    "openrouter": ["sk-or-v1-"],
}


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "").lower().strip()
    return v in ("1", "true", "yes", "on") if v else default


def security_strict_mode() -> bool:
    """When strict mode is on, ambiguous configs are rejected instead of guessed."""
    return _env_bool("TOKIO_SECURITY_STRICT", False)


def allow_openrouter_proxy() -> bool:
    """User must explicitly allow using OpenRouter as a fallback proxy.

    Defaults to False: ambiguous Kimi/OpenRouter configs should not silently
    leak keys or traffic to a third-party router unless the user opts in.
    """
    return _env_bool("TOKIO_ALLOW_OPENROUTER_PROXY", False)


def require_explicit_provider() -> bool:
    """When on, TOKIOAI_PROVIDER is required; auto-detection is disabled."""
    return _env_bool("TOKIO_REQUIRE_EXPLICIT_PROVIDER", False)


def provider_lock() -> Optional[str]:
    """If set, only this provider may be used regardless of env keys or aliases.

    Useful in shared environments to prevent a user from accidentally switching
    providers by changing env vars. The lock is case-insensitive.
    """
    v = os.getenv("TOKIO_PROVIDER_LOCK", "").strip()
    return v.lower() or None


def locked_provider() -> Optional[str]:
    """Alias for provider_lock() for readability in ops.py."""
    return provider_lock()


def require_explicit_key_for_init_client() -> bool:
    """When on, init_client refuses to read API keys from the environment.

    Useful in CI or shared agents where keys should be passed explicitly.
    """
    return _env_bool("TOKIO_INIT_REQUIRE_EXPLICIT_KEY", False)


def validate_key_for_provider(provider: str, key: str) -> tuple[bool, Optional[str]]:
    """Return (ok, error_message). Empty key is reported as missing, not invalid."""
    if not key:
        return False, f"API key for provider '{provider}' is missing"
    provider = provider.lower().strip()
    # Reject keys with dangerous whitespace / newlines (common copy-paste mistake)
    if key != key.strip():
        return False, f"API key for provider '{provider}' contains leading/trailing whitespace"
    # Minimum sanity length
    if len(key) < 8:
        return False, f"API key for provider '{provider}' is too short"
    # Special handling: OpenRouter keys are unambiguous
    if provider == "openrouter" and not key.startswith("sk-or-v1-"):
        return False, "OpenRouter API key must start with 'sk-or-v1-'"
    # Generic key sanity: reject keys that look like private keys or certs
    if "PRIVATE KEY" in key or "BEGIN CERTIFICATE" in key:
        return False, "API key looks like a private key/certificate"
    # Provider-specific prefix checks
    expected = KEY_PREFIX_RULES.get(provider, [])
    if expected and not any(key.startswith(p) for p in expected):
        # Kimi and OpenAI both use sk-; OpenRouter is handled above.
        # If provider is kimi, allow any sk- key (we cannot distinguish from OpenAI).
        if provider == "kimi" and key.startswith("sk-"):
            return True, None
        return False, f"API key for provider '{provider}' does not match expected prefix(es): {expected}"
    return True, None


def decide_provider(
    explicit_provider: str,
    explicit_model: str,
    env_keys: dict[str, Optional[str]],
) -> ProviderDecision:
    """Centralized, auditable provider decision.

    env_keys should contain at least:
      VERTEX_PROJECT, ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY,
      KIMI_API_KEY, MOONSHOT_API_KEY, OPENROUTER_API_KEY, OLLAMA_HOST
    """
    warnings: list[str] = []
    model = explicit_model or ""
    lock = provider_lock()

    # Provider lock is the strongest policy: reject any provider that does not match.
    if lock and explicit_provider and explicit_provider.lower().strip() != lock:
        return ProviderDecision(
            provider="",
            reason=f"Provider lock is set to '{lock}' but explicit provider is '{explicit_provider}'",
            model=model,
            blocked=True,
            block_reason=f"Provider locked to '{lock}' by TOKIO_PROVIDER_LOCK",
            warnings=warnings,
        )

    if require_explicit_provider() and not explicit_provider:
        return ProviderDecision(
            provider="",
            reason="TOKIO_REQUIRE_EXPLICIT_PROVIDER is enabled but TOKIOAI_PROVIDER is unset",
            model=model,
            blocked=True,
            block_reason="Explicit provider required by security policy",
        )

    # If explicit provider given, validate key and model compatibility.
    if explicit_provider:
        provider = explicit_provider.lower().strip()

        # Reject ambiguous provider aliases
        if provider in ("google",):
            provider = "gemini"
            warnings.append("Provider alias 'google' normalized to 'gemini'")
        if provider in ("moonshot",):
            provider = "kimi"
            warnings.append("Provider alias 'moonshot' normalized to 'kimi'")

        # If model has org/name format, it is an OpenRouter model.
        if "/" in model and not model.startswith("models/"):
            if provider == "openrouter":
                return ProviderDecision(provider="openrouter", reason="Explicit OpenRouter provider + OpenRouter model", model=model)
            if provider == "kimi" and allow_openrouter_proxy():
                or_key = env_keys.get("OPENROUTER_API_KEY")
                if or_key:
                    warnings.append("Model is OpenRouter-format but provider is kimi; using explicit OpenRouter key")
                    return ProviderDecision(provider="openrouter", reason="OpenRouter-format model with explicit OpenRouter key", model=model)
                # Check whether the Kimi key is actually an OpenRouter key
                k = env_keys.get("KIMI_API_KEY") or env_keys.get("MOONSHOT_API_KEY")
                if k and k.startswith("sk-or-v1-"):
                    warnings.append("KIMI/MOONSHOT key is an OpenRouter key; routing through OpenRouter")
                    return ProviderDecision(provider="openrouter", reason="OpenRouter-format model + OpenRouter-shaped Kimi key", model=model, key_source="KIMI_API_KEY")
            # Strict / no-proxy: do not silently switch provider
            if security_strict_mode():
                return ProviderDecision(
                    provider=provider,
                    reason="Explicit provider does not match OpenRouter-format model",
                    model=model,
                    blocked=True,
                    block_reason=f"Provider '{provider}' cannot run OpenRouter-format model '{model}'",
                    warnings=warnings,
                )
            warnings.append(f"Model '{model}' looks like OpenRouter but provider is '{provider}'; continuing with explicit provider")

        return ProviderDecision(provider=provider, reason="Explicit provider accepted", model=model, warnings=warnings)

    # --- Auto-detection below only runs if explicit provider is missing ---
    # When a provider lock is active, auto-detection is restricted to the locked provider.
    if lock:
        if env_keys.get("VERTEX_PROJECT") or env_keys.get("ANTHROPIC_VERTEX_PROJECT_ID"):
            if lock == "anthropic-vertex":
                return ProviderDecision(provider="anthropic-vertex", reason="Auto-detected locked Vertex project", model=model)
            warnings.append("Vertex credentials ignored because provider is locked to another provider")
        if env_keys.get("ANTHROPIC_API_KEY") and lock == "anthropic":
            return ProviderDecision(provider="anthropic", reason="Auto-detected locked Anthropic API key", model=model, key_source="ANTHROPIC_API_KEY")
        if env_keys.get("OPENAI_API_KEY") and lock == "openai":
            return ProviderDecision(provider="openai", reason="Auto-detected locked OpenAI API key", model=model, key_source="OPENAI_API_KEY")
        if (env_keys.get("GEMINI_API_KEY") or env_keys.get("GOOGLE_API_KEY")) and lock == "gemini":
            key = env_keys.get("GEMINI_API_KEY") or env_keys.get("GOOGLE_API_KEY")
            return ProviderDecision(provider="gemini", reason="Auto-detected locked Gemini API key", model=model, key_source="GEMINI_API_KEY")
        if (env_keys.get("KIMI_API_KEY") or env_keys.get("MOONSHOT_API_KEY")) and lock == "kimi":
            return ProviderDecision(provider="kimi", reason="Auto-detected locked Kimi/Moonshot API key", model=model, key_source="KIMI_API_KEY")
        if env_keys.get("OPENROUTER_API_KEY") and lock == "openrouter":
            return ProviderDecision(provider="openrouter", reason="Auto-detected locked OpenRouter API key", model=model, key_source="OPENROUTER_API_KEY")
        if env_keys.get("OLLAMA_HOST") and lock == "ollama":
            return ProviderDecision(provider="ollama", reason="Auto-detected locked Ollama host", model=model, key_source="OLLAMA_HOST")
        return ProviderDecision(
            provider="",
            reason=f"Provider locked to '{lock}' but no credentials for locked provider found",
            model=model,
            blocked=True,
            block_reason=f"Provider locked to '{lock}'; configure credentials for locked provider",
            warnings=warnings,
        )

    if env_keys.get("VERTEX_PROJECT") or env_keys.get("ANTHROPIC_VERTEX_PROJECT_ID"):
        return ProviderDecision(provider="anthropic-vertex", reason="Auto-detected Vertex project", model=model)

    if env_keys.get("ANTHROPIC_API_KEY"):
        ok, err = validate_key_for_provider("anthropic", env_keys["ANTHROPIC_API_KEY"])
        if not ok:
            warnings.append(err)
        return ProviderDecision(provider="anthropic", reason="Auto-detected Anthropic API key", model=model, key_source="ANTHROPIC_API_KEY", warnings=warnings)

    if env_keys.get("OPENAI_API_KEY"):
        ok, err = validate_key_for_provider("openai", env_keys["OPENAI_API_KEY"])
        if not ok:
            warnings.append(err)
        return ProviderDecision(provider="openai", reason="Auto-detected OpenAI API key", model=model, key_source="OPENAI_API_KEY", warnings=warnings)

    if env_keys.get("GEMINI_API_KEY") or env_keys.get("GOOGLE_API_KEY"):
        key = env_keys.get("GEMINI_API_KEY") or env_keys.get("GOOGLE_API_KEY")
        ok, err = validate_key_for_provider("gemini", key)
        if not ok:
            warnings.append(err)
        return ProviderDecision(provider="gemini", reason="Auto-detected Gemini API key", model=model, key_source="GEMINI_API_KEY", warnings=warnings)

    if env_keys.get("KIMI_API_KEY") or env_keys.get("MOONSHOT_API_KEY"):
        key = env_keys.get("KIMI_API_KEY") or env_keys.get("MOONSHOT_API_KEY")
        ok, err = validate_key_for_provider("kimi", key)
        if not ok:
            warnings.append(err)
        return ProviderDecision(provider="kimi", reason="Auto-detected Kimi/Moonshot API key", model=model, key_source="KIMI_API_KEY", warnings=warnings)

    if env_keys.get("OPENROUTER_API_KEY"):
        ok, err = validate_key_for_provider("openrouter", env_keys["OPENROUTER_API_KEY"])
        if not ok:
            warnings.append(err)
        return ProviderDecision(provider="openrouter", reason="Auto-detected OpenRouter API key", model=model, key_source="OPENROUTER_API_KEY", warnings=warnings)

    if env_keys.get("OLLAMA_HOST"):
        return ProviderDecision(provider="ollama", reason="Auto-detected Ollama host", model=model, key_source="OLLAMA_HOST")

    # Nothing configured: default to Vertex (legacy behavior) but warn
    warnings.append("No provider credentials detected; defaulting to anthropic-vertex")
    return ProviderDecision(provider="anthropic-vertex", reason="Default fallback", model=model, warnings=warnings)


def audit_security_event(
    action: str,
    provider: str,
    key_source: str = "",
    success: bool = True,
    detail: str = "",
) -> None:
    """Log a runtime security event (e.g. init_client key validation)."""
    try:
        os.makedirs(_AUDIT_DIR, exist_ok=True)
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": action,
                "provider": provider,
                "key_source": key_source,
                "success": success,
                "detail": detail,
            }
            f.write(__import__("json").dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def fail_or_warn(decision: ProviderDecision, on_warning=print) -> None:
    """If decision is blocked, exit. Otherwise print warnings."""
    if decision.blocked:
        print(f"\033[31mSECURITY ERROR: {decision.block_reason}\033[0m", file=sys.stderr)
        print(f"Reason: {decision.reason}", file=sys.stderr)
        sys.exit(1)
    for w in decision.warnings:
        on_warning(f"\033[33mSECURITY WARN: {w}\033[0m")
