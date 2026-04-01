from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sive.core import sync_state
from sive.core.vaults import VaultConfig


def test_is_sync_due_without_state(tmp_path):
    with patch.object(sync_state, "STATE_DIR", tmp_path):
        assert sync_state.is_sync_due("personal") is True


def test_is_sync_due_false_after_recent_success(tmp_path):
    now = datetime(2026, 4, 1, 22, 0, tzinfo=UTC)
    with patch.object(sync_state, "STATE_DIR", tmp_path):
        sync_state.save_sync_state(
            "personal",
            {"last_successful_sync_at": sync_state.to_timestamp(now - timedelta(minutes=5))},
        )
        assert sync_state.is_sync_due("personal", now=now) is False


def test_acquire_lock_rejects_fresh_lock(tmp_path):
    with patch.object(sync_state, "STATE_DIR", tmp_path):
        assert sync_state.acquire_lock("personal") is True
        assert sync_state.acquire_lock("personal") is False


def test_maybe_trigger_background_sync_spawns_once(tmp_path):
    with (
        patch.object(sync_state, "STATE_DIR", tmp_path),
        patch.object(sync_state, "is_sync_due", return_value=True),
        patch.object(sync_state.subprocess, "Popen") as mock_popen,
        patch.object(sync_state, "sys") as mock_sys,
    ):
        mock_sys.executable = "/tmp/python"
        assert sync_state.maybe_trigger_background_sync("personal") is True
        assert sync_state.maybe_trigger_background_sync("personal") is False
    mock_popen.assert_called_once()


def test_maybe_trigger_background_sync_releases_lock_on_popen_failure(tmp_path):
    with (
        patch.object(sync_state, "STATE_DIR", tmp_path),
        patch.object(sync_state, "is_sync_due", return_value=True),
        patch.object(sync_state.subprocess, "Popen", side_effect=OSError("boom")),
        patch.object(sync_state, "sys") as mock_sys,
    ):
        mock_sys.executable = "/tmp/python"
        assert sync_state.maybe_trigger_background_sync("personal") is False
        assert sync_state.lock_path("personal").exists() is False


def test_run_sync_vault_updates_success_state(tmp_path):
    now = datetime(2026, 4, 1, 22, 0, tzinfo=UTC)
    with (
        patch.object(sync_state, "STATE_DIR", tmp_path),
        patch.object(sync_state, "utc_now", side_effect=[now, now]),
        patch.object(
            sync_state,
            "load_vault",
            return_value=VaultConfig(
                name="personal",
                server="https://vw.example.com",
                appdata_dir=Path("/tmp/sive-personal"),
            ),
        ),
        patch.object(sync_state, "get_password", return_value="secret"),
        patch.object(sync_state, "unlock", return_value="session"),
        patch.object(sync_state, "sync") as mock_sync,
        patch.object(sync_state, "_write_snapshot_from_session"),
    ):
        assert sync_state.run_sync_vault("personal") == 0

    with patch.object(sync_state, "STATE_DIR", tmp_path):
        state = sync_state.load_sync_state("personal")
        assert state["last_attempt_at"] == sync_state.to_timestamp(now)
        assert state["last_successful_sync_at"] == sync_state.to_timestamp(now)
        assert "last_error" not in state
    mock_sync.assert_called_once_with("session", appdata_dir="/tmp/sive-personal")


def test_run_sync_vault_updates_error_state(tmp_path):
    now = datetime(2026, 4, 1, 22, 0, tzinfo=UTC)
    with (
        patch.object(sync_state, "STATE_DIR", tmp_path),
        patch.object(sync_state, "utc_now", side_effect=[now, now]),
        patch.object(
            sync_state,
            "load_vault",
            return_value=VaultConfig(
                name="personal",
                server="https://vw.example.com",
                appdata_dir=Path("/tmp/sive-personal"),
            ),
        ),
        patch.object(sync_state, "get_password", return_value="secret"),
        patch.object(sync_state, "unlock", side_effect=RuntimeError("boom")),
    ):
        assert sync_state.run_sync_vault("personal") == 1

    with patch.object(sync_state, "STATE_DIR", tmp_path):
        state = sync_state.load_sync_state("personal")
        assert state["last_attempt_at"] == sync_state.to_timestamp(now)
        assert state["last_error_at"] == sync_state.to_timestamp(now)
        assert state["last_error"] == "boom"


def test_run_sync_vault_releases_lock_when_save_state_fails(tmp_path):
    with (
        patch.object(sync_state, "STATE_DIR", tmp_path),
        patch.object(
            sync_state,
            "load_vault",
            return_value=VaultConfig(
                name="personal",
                server="https://vw.example.com",
                appdata_dir=Path("/tmp/sive-personal"),
            ),
        ),
        patch.object(sync_state, "get_password", return_value="secret"),
        patch.object(sync_state, "unlock", return_value="session"),
        patch.object(sync_state, "sync"),
        patch.object(sync_state, "_write_snapshot_from_session"),
        patch.object(
            sync_state,
            "save_sync_state",
            side_effect=[None, RuntimeError("save failed"), None],
        ),
    ):
        assert sync_state.acquire_lock("personal") is True
        assert sync_state.run_sync_vault("personal") == 1
        assert sync_state.lock_path("personal").exists() is False
