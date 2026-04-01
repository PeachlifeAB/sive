"""Tests for snapshot_crypto encrypt/decrypt primitives and key lifecycle."""

import secrets
from unittest.mock import patch

import pytest

from sive.core.keychain_macos import KeychainError
from sive.core.snapshot_crypto import decrypt_env, encrypt_env, ensure_key


def _key() -> bytes:
    return secrets.token_bytes(32)


def test_roundtrip_empty():
    key = _key()
    assert decrypt_env(encrypt_env({}, key), key) == {}


def test_roundtrip_vars():
    key = _key()
    env = {"ANTHROPIC_API_KEY": "sk-test", "GITHUB_TOKEN": "ghp_test"}
    assert decrypt_env(encrypt_env(env, key), key) == env


def test_wrong_key_raises():
    env = {"FOO": "bar"}
    key = _key()
    blob = encrypt_env(env, key)
    wrong_key = secrets.token_bytes(32)
    with pytest.raises(Exception):
        decrypt_env(blob, wrong_key)


def test_tampered_ciphertext_raises():
    key = _key()
    blob = bytearray(encrypt_env({"FOO": "bar"}, key))
    blob[-1] ^= 0xFF  # flip last byte
    with pytest.raises(Exception):
        decrypt_env(bytes(blob), key)


def test_each_encrypt_unique():
    key = _key()
    env = {"X": "y"}
    assert encrypt_env(env, key) != encrypt_env(env, key)


# ---------------------------------------------------------------------------
# ensure_key — idempotent key creation per (vault, tag)
# ---------------------------------------------------------------------------


def test_ensure_key_creates_when_missing():
    """ensure_key stores a new key when none exists."""
    with (
        patch("sive.core.snapshot_crypto.get_secret", side_effect=KeychainError("not found")),
        patch("sive.core.snapshot_crypto.store_secret") as mock_store,
    ):
        ensure_key("personal", "global")
    mock_store.assert_called_once()


def test_ensure_key_noop_when_present():
    """ensure_key does not overwrite an existing key."""
    with (
        patch("sive.core.snapshot_crypto.get_secret", return_value="deadbeef" * 8),
        patch("sive.core.snapshot_crypto.store_secret") as mock_store,
    ):
        ensure_key("personal", "global")
    mock_store.assert_not_called()


def test_ensure_key_idempotent_across_multiple_calls():
    """Calling ensure_key twice only stores once."""
    call_count = 0

    def get_side_effect(vault, account, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise KeychainError("not found")
        return "deadbeef" * 8

    with (
        patch("sive.core.snapshot_crypto.get_secret", side_effect=get_side_effect),
        patch("sive.core.snapshot_crypto.store_secret") as mock_store,
    ):
        ensure_key("personal", "global")
        ensure_key("personal", "global")
    mock_store.assert_called_once()


def test_ensure_key_uses_tag_in_account_name():
    """Each tag gets a distinct keychain account."""
    stored_accounts = []

    def capture_store(vault, account, value):
        stored_accounts.append(account)

    with (
        patch("sive.core.snapshot_crypto.get_secret", side_effect=KeychainError("not found")),
        patch("sive.core.snapshot_crypto.store_secret", side_effect=capture_store),
    ):
        ensure_key("personal", "global")
        ensure_key("personal", "myproject")

    assert stored_accounts == ["snapshot_key:global", "snapshot_key:myproject"]
