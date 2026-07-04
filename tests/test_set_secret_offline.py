"""Tests for sive set offline behavior (vault unreachable)."""

from __future__ import annotations

import secrets
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sive.commands.set_secret import run
from sive.core.pending_queue import load_pending
from sive.core.snapshot import read_snapshot, write_snapshot
from sive.core.source_loader import SourceError


def _fake_key() -> bytes:
    return secrets.token_bytes(32)


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("sive.core.pending_queue.STATE_DIR", tmp_path)
    monkeypatch.setattr("sive.core.snapshot.STATE_DIR", tmp_path)
    monkeypatch.setattr("sive.core.sync_state.STATE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def vault_config():
    vault = MagicMock()
    vault.appdata_dir = "/tmp/bw"
    return vault


def test_set_queues_entry_when_vault_unreachable(state_dir: Path, vault_config: MagicMock) -> None:
    network_error = SourceError("bw unlock failed: ErrorResponse { statusCode: 502 }")

    with (
        patch("sive.commands.set_secret.load_vault", return_value=vault_config),
        patch("sive.commands.set_secret._ensure_session", side_effect=network_error),
        patch("sive.commands.set_secret.read_project_vault", return_value="personal"),
        patch("sive.commands.set_secret.read_project_tags", return_value=["global"]),
        patch("sive.core.pending_queue.STATE_DIR", state_dir),
    ):
        rc = run("EXA_API_KEY", "secret123", tag="global", vault_name="personal")

    assert rc == 0
    entries = load_pending("personal")
    assert len(entries) == 1
    assert entries[0]["key"] == "EXA_API_KEY"
    assert entries[0]["value"] == "secret123"
    assert entries[0]["tag"] == "global"


def test_set_patches_snapshot_when_vault_unreachable(
    state_dir: Path, vault_config: MagicMock
) -> None:
    key = _fake_key()
    # Pre-populate snapshot with an existing secret
    with (
        patch("sive.core.snapshot_crypto.get_key", return_value=key),
        patch("sive.core.snapshot.get_key", return_value=key),
    ):
        write_snapshot("personal", "global", {"EXISTING": "value"}, [])

    network_error = SourceError("bw unlock failed: ErrorResponse { statusCode: 502 }")

    with (
        patch("sive.commands.set_secret.load_vault", return_value=vault_config),
        patch("sive.commands.set_secret._ensure_session", side_effect=network_error),
        patch("sive.commands.set_secret.read_project_vault", return_value="personal"),
        patch("sive.commands.set_secret.read_project_tags", return_value=["global"]),
        patch("sive.core.pending_queue.STATE_DIR", state_dir),
        patch("sive.core.snapshot_crypto.get_key", return_value=key),
        patch("sive.core.snapshot.get_key", return_value=key),
    ):
        run("EXA_API_KEY", "secret123", tag="global", vault_name="personal")

    with patch("sive.core.snapshot.get_key", return_value=key):
        env = read_snapshot("personal", "global")

    assert env is not None
    assert env["EXA_API_KEY"] == "secret123"
    assert env["EXISTING"] == "value"


def test_set_fails_hard_on_auth_error(state_dir: Path, vault_config: MagicMock) -> None:
    auth_error = SourceError("not logged in")

    with (
        patch("sive.commands.set_secret.load_vault", return_value=vault_config),
        patch("sive.commands.set_secret._ensure_session", side_effect=auth_error),
        patch("sive.commands.set_secret.read_project_vault", return_value="personal"),
        patch("sive.commands.set_secret.read_project_tags", return_value=["global"]),
        patch("sive.commands.setup.run_relogin", return_value=(1, None, None)),
    ):
        rc = run("EXA_API_KEY", "secret123", tag="global", vault_name="personal")

    assert rc != 0
    assert load_pending("personal") == []
