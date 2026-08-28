"""
TokioAI Vivo v3 - Vault (Secrets Manager)
Lightweight encrypted secrets vault using Fernet (AES-128-CBC).
Secrets are stored encrypted at rest, decrypted into env vars at runtime.
The master key is derived from a passphrase or stored in a keyfile.

Usage:
  vault = Vault("/path/to/vault.enc", passphrase="my-passphrase")
  vault.set("OPENAI_API_KEY", "sk-...")
  vault.save()
  vault.load_into_env()  # Now os.environ has OPENAI_API_KEY
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Optional


class Vault:
    """Simple encrypted secrets vault using Fernet-compatible AES."""

    def __init__(self, vault_path: str | Path, passphrase: Optional[str] = None,
                 keyfile: Optional[str | Path] = None):
        self.vault_path = Path(vault_path)
        self._secrets: Dict[str, str] = {}
        self._key = self._derive_key(passphrase, keyfile)

    def _derive_key(self, passphrase: Optional[str], keyfile: Optional[str | Path]) -> bytes:
        """Derive a 32-byte key from passphrase or keyfile."""
        if keyfile:
            kf = Path(keyfile)
            if kf.exists():
                raw = kf.read_bytes().strip()
                return hashlib.sha256(raw).digest()

        if passphrase:
            return hashlib.sha256(passphrase.encode()).digest()

        # Try env var
        env_pass = os.environ.get("TOKIO_VAULT_PASS", "")
        if env_pass:
            return hashlib.sha256(env_pass.encode()).digest()

        # Try default keyfile
        default_kf = Path.home() / ".tokioai" / "vault.key"
        if default_kf.exists():
            raw = default_kf.read_bytes().strip()
            return hashlib.sha256(raw).digest()

        # Generate and save a key
        import secrets as sec
        key_raw = sec.token_bytes(32)
        default_kf.parent.mkdir(parents=True, exist_ok=True)
        default_kf.write_bytes(base64.b64encode(key_raw))
        default_kf.chmod(0o600)
        return hashlib.sha256(key_raw).digest()

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt using AES-256 via Fernet-like scheme (pure Python fallback)."""
        try:
            from cryptography.fernet import Fernet
            fernet_key = base64.urlsafe_b64encode(self._key)
            f = Fernet(fernet_key)
            return f.encrypt(plaintext.encode()).decode()
        except ImportError:
            # Pure Python XOR fallback (not as secure but functional)
            return self._xor_encrypt(plaintext)

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt."""
        try:
            from cryptography.fernet import Fernet
            fernet_key = base64.urlsafe_b64encode(self._key)
            f = Fernet(fernet_key)
            return f.decrypt(ciphertext.encode()).decode()
        except ImportError:
            return self._xor_decrypt(ciphertext)

    def _xor_encrypt(self, plaintext: str) -> str:
        """Simple XOR encrypt (fallback when cryptography not installed)."""
        data = plaintext.encode()
        key = self._key
        encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return "xor:" + base64.b64encode(encrypted).decode()

    def _xor_decrypt(self, ciphertext: str) -> str:
        """Simple XOR decrypt."""
        if ciphertext.startswith("xor:"):
            ciphertext = ciphertext[4:]
        data = base64.b64decode(ciphertext)
        key = self._key
        decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return decrypted.decode()

    def set(self, key: str, value: str):
        """Set a secret."""
        self._secrets[key] = value

    def get(self, key: str, default: str = "") -> str:
        """Get a secret."""
        return self._secrets.get(key, default)

    def delete(self, key: str):
        """Delete a secret."""
        self._secrets.pop(key, None)

    def list_keys(self) -> list[str]:
        """List all secret keys (not values)."""
        return list(self._secrets.keys())

    def save(self):
        """Save encrypted vault to disk."""
        plaintext = json.dumps(self._secrets, indent=2)
        encrypted = self._encrypt(plaintext)
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_text(encrypted)
        self.vault_path.chmod(0o600)

    def load(self) -> bool:
        """Load and decrypt vault from disk. Returns True if successful."""
        if not self.vault_path.exists():
            return False
        try:
            encrypted = self.vault_path.read_text().strip()
            plaintext = self._decrypt(encrypted)
            self._secrets = json.loads(plaintext)
            return True
        except Exception:
            return False

    def load_into_env(self, prefix: str = "") -> int:
        """Load all secrets into os.environ. Returns count loaded."""
        if not self._secrets:
            self.load()
        count = 0
        for key, value in self._secrets.items():
            env_key = f"{prefix}{key}" if prefix else key
            os.environ[env_key] = value
            count += 1
        return count

    def has_secrets(self) -> bool:
        """Check if vault has any secrets."""
        if self._secrets:
            return True
        return self.vault_path.exists()

    def mask_value(self, value: str) -> str:
        """Mask a secret for display: show first 4 and last 4 chars."""
        if len(value) <= 10:
            return "****"
        return f"{value[:4]}****{value[-4:]}"

    def summary(self) -> str:
        """Get a summary of vault contents (masked)."""
        if not self._secrets:
            self.load()
        if not self._secrets:
            return "(vault empty or not found)"
        lines = [f"Vault: {self.vault_path} ({len(self._secrets)} secrets)"]
        for key in sorted(self._secrets.keys()):
            lines.append(f"  {key} = {self.mask_value(self._secrets[key])}")
        return "\n".join(lines)
