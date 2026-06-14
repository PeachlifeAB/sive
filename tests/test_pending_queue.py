"""Tests for offline write queue."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from sive.core.pending_queue import drain_pending, enqueue_pending, load_pending


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("sive.core.pending_queue.STATE_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# enqueue_pending
# ---------------------------------------------------------------------------


def test_enqueue_writes_entry(state_dir: Path) -> None:
    enqueue_pending("personal", "EXA_API_KEY", "secret123", "global")

    entries = load_pending("personal")
    assert len(entries) == 1
    assert entries[0] == {"key": "EXA_API_KEY", "value": "secret123", "tag": "global"}


def test_enqueue_appends_multiple_entries(state_dir: Path) -> None:
    enqueue_pending("personal", "KEY_A", "val_a", "global")
    enqueue_pending("personal", "KEY_B", "val_b", "work")

    entries = load_pending("personal")
    assert len(entries) == 2
    assert entries[0]["key"] == "KEY_A"
    assert entries[1]["key"] == "KEY_B"


# ---------------------------------------------------------------------------
# drain_pending
# ---------------------------------------------------------------------------


def test_drain_calls_upsert_for_each_entry(state_dir: Path) -> None:
    enqueue_pending("personal", "KEY_A", "val_a", "global")
    enqueue_pending("personal", "KEY_B", "val_b", "work")

    mock_upsert = MagicMock()
    mock_folders = [
        {"name": "env/global", "id": "folder-global"},
        {"name": "env/work", "id": "folder-work"},
    ]

    with (
        patch("sive.core.pending_queue.list_folders", return_value=mock_folders),
        patch("sive.core.pending_queue.find_folder_id", side_effect=["folder-global", "folder-work"]),
        patch("sive.core.pending_queue.upsert_note", mock_upsert),
    ):
        drained = drain_pending("personal", session="sess", appdata_dir="/tmp/bw")

    assert drained == 2
    assert mock_upsert.call_count == 2


def test_drain_clears_queue_on_success(state_dir: Path) -> None:
    enqueue_pending("personal", "KEY_A", "val_a", "global")

    mock_folders = [{"name": "env/global", "id": "folder-global"}]
    with (
        patch("sive.core.pending_queue.list_folders", return_value=mock_folders),
        patch("sive.core.pending_queue.find_folder_id", return_value="folder-global"),
        patch("sive.core.pending_queue.upsert_note"),
    ):
        drain_pending("personal", session="sess", appdata_dir="/tmp/bw")

    assert load_pending("personal") == []


def test_drain_leaves_queue_on_network_error(state_dir: Path) -> None:
    enqueue_pending("personal", "KEY_A", "val_a", "global")

    with patch("sive.core.pending_queue.list_folders", side_effect=Exception("502")):
        drained = drain_pending("personal", session="sess", appdata_dir="/tmp/bw")

    assert drained == 0
    assert len(load_pending("personal")) == 1


def test_drain_empty_queue_is_noop(state_dir: Path) -> None:
    drained = drain_pending("personal", session="sess", appdata_dir="/tmp/bw")
    assert drained == 0
