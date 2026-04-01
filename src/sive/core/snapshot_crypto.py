"""AES-256-GCM encryption for sive snapshot files.

Key lifecycle:
  - Generated once per (vault, tag) at setup via ensure_key()
  - Stored in macOS Keychain as account 'snapshot_key:{tag}' under the vault service
  - Retrieved on each decrypt via get_key()

Wire format: nonce (12 bytes) || ciphertext+tag (variable)
"""

from __future__ import annotations

import json
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from sive.core.keychain_macos import (
    KeychainError,
    delete_secret,
    get_secret,
    store_secret,
)

_NONCE_BYTES = 12
_KEY_BYTES = 32


def _key_account(tag: str) -> str:
    return f"snapshot_key:{tag}"


# ---------------------------------------------------------------------------
# Keychain helpers
# ---------------------------------------------------------------------------


def ensure_key(vault_name: str, tag: str) -> None:
    """Create and store a snapshot key for (vault, tag) if one does not exist. No-op if present."""
    account = _key_account(tag)
    try:
        get_secret(vault_name, account)
        return  # already exists — do not regenerate
    except KeychainError as e:
        if "not found" not in str(e).lower():
            raise
    store_secret(vault_name, account, secrets.token_hex(_KEY_BYTES))


def get_key(vault_name: str, tag: str) -> bytes:
    """Return the 32-byte snapshot key for (vault, tag) from the Keychain."""
    return bytes.fromhex(
        get_secret(
            vault_name,
            _key_account(tag),
            missing_hint="Run 'sive setup' to initialise it.",
        )
    )


def delete_key(vault_name: str, tag: str) -> None:
    try:
        delete_secret(vault_name, _key_account(tag))
    except Exception:
        return


# ---------------------------------------------------------------------------
# Encrypt / decrypt
# ---------------------------------------------------------------------------


def encrypt_env(env: dict[str, str], key: bytes) -> bytes:
    """Encrypt an env dict to bytes. Returns nonce || ciphertext+tag."""
    nonce = secrets.token_bytes(_NONCE_BYTES)
    plaintext = json.dumps(env, separators=(",", ":")).encode()
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt_env(data: bytes, key: bytes) -> dict[str, str]:
    """Decrypt bytes produced by encrypt_env. Returns env dict."""
    nonce = data[:_NONCE_BYTES]
    ciphertext = data[_NONCE_BYTES:]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return json.loads(plaintext)
