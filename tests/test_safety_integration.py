"""Integration tests for TokioAI safety layer in LLM client."""
import os
from unittest.mock import patch

import pytest

from tokioai_cli import ops
from tokioai_cli.ops import TokioOps


class TestSystemPromptSanitization:
    def test_safe_system_prompt_redacts_memory_secrets(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TOKIOAI_MODEL", "gpt-4o")
        monkeypatch.setenv("TOKIOAI_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-1234567890123456789012345678")

        # Point memory to temp file with sensitive content
        memory_file = tmp_path / "memory.md"
        memory_file.write_text("Admin password: SuperS3cr3t! and internal IP 192.168.7.7")
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("[]")

        with patch.object(ops, "MEMORY_FILE", str(memory_file)), \
             patch.object(ops, "TASKS_FILE", str(tasks_file)):
            client = TokioOps(provider="openai", model="gpt-4o")
            safe = client._safe_system_prompt()

        assert "SuperS3cr3t" not in safe
        assert "192.168.7.7" not in safe
        assert "[REDACTED_PASSWORD_1]" in safe
        assert "[REDACTED_IP_ADDRESS_1]" in safe

    def test_safe_system_prompt_leaves_clean_text(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TOKIOAI_MODEL", "gpt-4o")
        monkeypatch.setenv("TOKIOAI_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-1234567890123456789012345678")

        memory_file = tmp_path / "memory.md"
        memory_file.write_text("Remember to buy milk")
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("[]")

        with patch.object(ops, "MEMORY_FILE", str(memory_file)), \
             patch.object(ops, "TASKS_FILE", str(tasks_file)):
            client = TokioOps(provider="openai", model="gpt-4o")
            safe = client._safe_system_prompt()

        assert "Remember to buy milk" in safe
        assert "[REDACTED" not in safe
