"""Tests for TokioAI Security Configuration provider/key hardening."""
import pytest

from tokioai_cli import security_config as sec


class TestValidateKeyForProvider:
    def test_anthropic_key_valid(self):
        ok, err = sec.validate_key_for_provider("anthropic", "sk-ant-api03-" + "x" * 32)
        assert ok is True
        assert err is None

    def test_anthropic_key_wrong_prefix(self):
        ok, err = sec.validate_key_for_provider("anthropic", "sk-openai-" + "x" * 32)
        assert ok is False
        assert "prefix" in err.lower()

    def test_openai_key_valid(self):
        ok, err = sec.validate_key_for_provider("openai", "sk-" + "x" * 32)
        assert ok is True
        assert err is None

    def test_openai_project_key_valid(self):
        ok, err = sec.validate_key_for_provider("openai", "sk-proj-" + "x" * 32)
        assert ok is True

    def test_gemini_key_valid(self):
        ok, err = sec.validate_key_for_provider("gemini", "AIza" + "x" * 35)
        assert ok is True

    def test_gemini_key_wrong_prefix(self):
        ok, err = sec.validate_key_for_provider("gemini", "sk-" + "x" * 32)
        assert ok is False
        assert "AIza" in err

    def test_kimi_key_allows_any_sk(self):
        ok, err = sec.validate_key_for_provider("kimi", "sk-" + "x" * 32)
        assert ok is True

    def test_openrouter_key_valid(self):
        ok, err = sec.validate_key_for_provider("openrouter", "sk-or-v1-" + "x" * 48)
        assert ok is True

    def test_openrouter_key_rejects_generic_sk(self):
        ok, err = sec.validate_key_for_provider("openrouter", "sk-" + "x" * 48)
        assert ok is False
        assert "sk-or-v1-" in err

    def test_missing_key(self):
        ok, err = sec.validate_key_for_provider("openai", "")
        assert ok is False
        assert "missing" in err.lower()

    def test_rejects_private_key_pem(self):
        ok, err = sec.validate_key_for_provider("openai", "-----BEGIN PRIVATE KEY-----\nMIIC")
        assert ok is False
        assert "private key" in err.lower()


class TestDecideProviderExplicit:
    EMPTY_ENV = {k: None for k in [
        "VERTEX_PROJECT", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "KIMI_API_KEY",
        "MOONSHOT_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_HOST",
    ]}

    def test_explicit_provider_accepted(self):
        decision = sec.decide_provider("openai", "", {**self.EMPTY_ENV, "OPENAI_API_KEY": "sk-xxx"})
        assert decision.provider == "openai"
        assert decision.blocked is False

    def test_google_alias_normalized(self):
        decision = sec.decide_provider("google", "", {**self.EMPTY_ENV, "GEMINI_API_KEY": "AIza" + "x" * 35})
        assert decision.provider == "gemini"
        assert "normalized" in decision.warnings[0]

    def test_openrouter_model_with_explicit_openrouter(self):
        decision = sec.decide_provider("openrouter", "anthropic/claude-sonnet-4", self.EMPTY_ENV)
        assert decision.provider == "openrouter"

    def test_openrouter_proxy_disabled_by_default(self, monkeypatch):
        monkeypatch.setenv("TOKIO_ALLOW_OPENROUTER_PROXY", "0")
        env = {**self.EMPTY_ENV, "KIMI_API_KEY": "sk-" + "x" * 32}
        decision = sec.decide_provider("kimi", "moonshotai/kimi-k3", env)
        assert decision.provider == "kimi"
        assert "looks like OpenRouter" in decision.warnings[0]

    def test_openrouter_proxy_enabled(self, monkeypatch):
        monkeypatch.setenv("TOKIO_ALLOW_OPENROUTER_PROXY", "1")
        env = {**self.EMPTY_ENV, "KIMI_API_KEY": "sk-or-v1-" + "x" * 48}
        decision = sec.decide_provider("kimi", "moonshotai/kimi-k3", env)
        assert decision.provider == "openrouter"
        assert decision.key_source == "KIMI_API_KEY"

    def test_strict_mode_blocks_mismatched_openrouter_model(self, monkeypatch):
        monkeypatch.setenv("TOKIO_SECURITY_STRICT", "1")
        decision = sec.decide_provider("kimi", "moonshotai/kimi-k3", self.EMPTY_ENV)
        assert decision.blocked is True
        assert "cannot run OpenRouter-format model" in decision.block_reason


class TestDecideProviderAutoDetect:
    EMPTY_ENV = {k: None for k in [
        "VERTEX_PROJECT", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "KIMI_API_KEY",
        "MOONSHOT_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_HOST",
    ]}

    def test_auto_detect_openai(self):
        env = {**self.EMPTY_ENV, "OPENAI_API_KEY": "sk-" + "x" * 32}
        decision = sec.decide_provider("", "", env)
        assert decision.provider == "openai"
        assert decision.key_source == "OPENAI_API_KEY"

    def test_auto_detect_gemini(self):
        env = {**self.EMPTY_ENV, "GEMINI_API_KEY": "AIza" + "x" * 35}
        decision = sec.decide_provider("", "", env)
        assert decision.provider == "gemini"

    def test_auto_detect_kimi(self):
        env = {**self.EMPTY_ENV, "KIMI_API_KEY": "sk-" + "x" * 32}
        decision = sec.decide_provider("", "", env)
        assert decision.provider == "kimi"

    def test_auto_detect_openrouter(self):
        env = {**self.EMPTY_ENV, "OPENROUTER_API_KEY": "sk-or-v1-" + "x" * 48}
        decision = sec.decide_provider("", "", env)
        assert decision.provider == "openrouter"

    def test_require_explicit_provider_blocks_auto(self, monkeypatch):
        monkeypatch.setenv("TOKIO_REQUIRE_EXPLICIT_PROVIDER", "1")
        env = {**self.EMPTY_ENV, "OPENAI_API_KEY": "sk-" + "x" * 32}
        decision = sec.decide_provider("", "", env)
        assert decision.blocked is True
        assert "Explicit provider required" in decision.block_reason


class TestProviderLock:
    EMPTY_ENV = {k: None for k in [
        "VERTEX_PROJECT", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "KIMI_API_KEY",
        "MOONSHOT_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_HOST",
    ]}

    def test_lock_blocks_different_explicit_provider(self, monkeypatch):
        monkeypatch.setenv("TOKIO_PROVIDER_LOCK", "openai")
        decision = sec.decide_provider("gemini", "", self.EMPTY_ENV)
        assert decision.blocked is True
        assert "locked to 'openai'" in decision.block_reason

    def test_lock_allows_matching_explicit_provider(self, monkeypatch):
        monkeypatch.setenv("TOKIO_PROVIDER_LOCK", "openai")
        env = {**self.EMPTY_ENV, "OPENAI_API_KEY": "sk-" + "x" * 32}
        decision = sec.decide_provider("openai", "", env)
        assert decision.provider == "openai"
        assert decision.blocked is False

    def test_lock_restricts_auto_detection(self, monkeypatch):
        monkeypatch.setenv("TOKIO_PROVIDER_LOCK", "kimi")
        env = {**self.EMPTY_ENV, "OPENAI_API_KEY": "sk-" + "x" * 32, "KIMI_API_KEY": "sk-" + "x" * 32}
        decision = sec.decide_provider("", "", env)
        assert decision.provider == "kimi"

    def test_lock_blocks_auto_when_locked_creds_missing(self, monkeypatch):
        monkeypatch.setenv("TOKIO_PROVIDER_LOCK", "openai")
        env = {**self.EMPTY_ENV, "KIMI_API_KEY": "sk-" + "x" * 32}
        decision = sec.decide_provider("", "", env)
        assert decision.blocked is True
        assert "locked to 'openai'" in decision.block_reason


class TestEnvBools:
    def test_security_strict_mode(self, monkeypatch):
        monkeypatch.setenv("TOKIO_SECURITY_STRICT", "1")
        assert sec.security_strict_mode() is True

    def test_allow_openrouter_proxy_default_false(self, monkeypatch):
        monkeypatch.delenv("TOKIO_ALLOW_OPENROUTER_PROXY", raising=False)
        assert sec.allow_openrouter_proxy() is False

    def test_require_explicit_provider(self, monkeypatch):
        monkeypatch.setenv("TOKIO_REQUIRE_EXPLICIT_PROVIDER", "true")
        assert sec.require_explicit_provider() is True

    def test_provider_lock_from_env(self, monkeypatch):
        monkeypatch.setenv("TOKIO_PROVIDER_LOCK", "Anthropic")
        assert sec.provider_lock() == "anthropic"
