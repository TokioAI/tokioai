"""Tests for TokioAI Security Layer."""
import os
import pytest

from tokioai_cli.safety import SafetyGuard, SafetyReport, default_guard, format_report


class TestSafetyGuard:
    def test_clean_text_passes_through(self):
        g = default_guard()
        text = "Hello, how do I list files in a directory?"
        clean, report = g.sanitize(text)
        assert clean == text
        assert report.redactions == []

    def test_openai_key_redacted(self):
        g = default_guard()
        text = "My key is sk-proj-ABCD1234567890abcdef1234567890abcdef12"
        clean, report = g.sanitize(text)
        assert "sk-proj-" not in clean
        assert "[REDACTED_API_KEY_1]" in clean
        assert report.redacted_categories == {"api_key": 1}

    def test_openrouter_key_redacted(self):
        g = default_guard()
        text = "My OpenRouter key is sk-or-v1-1234567890abcdef1234567890abcdef1234567890abcdef"
        clean, report = g.sanitize(text)
        assert "sk-or-v1-" not in clean
        assert "[REDACTED_API_KEY_1]" in clean
        assert report.redacted_categories == {"api_key": 1}

    def test_email_redacted(self):
        g = default_guard()
        text = "Contact me at admin@example.com please"
        clean, report = g.sanitize(text)
        assert "admin@example.com" not in clean
        assert "[REDACTED_EMAIL_1]" in clean

    def test_connection_string_redacted(self):
        g = default_guard()
        text = "Use postgres://user:secretpass@db.internal:5432/production"
        clean, report = g.sanitize(text)
        assert "secretpass" not in clean
        assert "[REDACTED_CONNECTION_STRING_1]" in clean

    def test_private_ip_redacted(self):
        g = default_guard()
        text = "Server is at 192.168.1.50 and gateway 10.0.0.1"
        clean, report = g.sanitize(text)
        assert "192.168.1.50" not in clean
        assert "10.0.0.1" not in clean
        assert report.redacted_categories == {"ip_address": 2}

    def test_allow_list_bypasses_redaction(self):
        g = default_guard()
        secret = "sk-proj-ALLOWED1234567890abcdef1234567890"
        g.add_allow(secret)
        clean, report = g.sanitize(f"Key: {secret}")
        assert clean == f"Key: {secret}"
        assert report.redactions == []

    def test_blocked_category_stops_send(self):
        g = SafetyGuard(block_categories={"api_key"})
        text = "Key: sk-proj-ABCD1234567890abcdef1234567890abcdef12"
        clean, report = g.sanitize(text)
        assert report.blocked is True
        assert "api_key" in report.block_reason
        # blocked text is returned unchanged
        assert "sk-proj-" in clean

    def test_report_summary(self):
        report = SafetyReport()
        assert report.summary() == "Safety: clean"

    def test_format_report(self):
        g = default_guard()
        _, report = g.sanitize("Email a@b.com and key sk-proj-1234567890abcdef1234567890abcdef12")
        summary = format_report(report)
        assert summary.startswith("[safety] redacted")
        assert "api_key" in summary
        assert "email" in summary

    def test_sanitize_messages_shape(self):
        g = default_guard()
        messages = [
            {"role": "user", "content": "My key is sk-proj-1234567890abcdef1234567890abcdef12"},
            {"role": "assistant", "content": "Got it"},
        ]
        clean, reports = g.sanitize_messages(messages)
        assert len(clean) == 2
        assert "[REDACTED_API_KEY_1]" in clean[0]["content"]
        assert reports[1].redactions == []


class TestDefaultGuardEnv:
    def test_paranoid_from_env(self, monkeypatch):
        monkeypatch.setenv("TOKIO_SAFETY_PARANOID", "1")
        g = default_guard()
        assert g.paranoid is True

    def test_block_categories_from_env(self, monkeypatch):
        monkeypatch.setenv("TOKIO_SAFETY_BLOCK", "api_key,email")
        g = default_guard()
        assert g.block_categories == {"api_key", "email"}
