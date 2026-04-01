"""Tests for snapshot read/write layer."""

from __future__ import annotations

import secrets
from pathlib import Path
from unittest.mock import patch

import pytest

from sive.core.snapshot import (
    SnapshotMeta,
    read_meta,
    read_snapshot,
    snapshot_exists,
    snapshot_path,
    write_meta,
    write_snapshot,
)
from sive.core.sync_state import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_key() -> bytes:
    return secrets.token_bytes(32)


def _patch_state_dir(tmp_path: Path):
    return patch("sive.core.snapshot.STATE_DIR", tmp_path)


def _patch_key(key: bytes):
    return patch("sive.core.snapshot.get_key", return_value=key)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_write_and_read_meta(tmp_path):
    meta = SnapshotMeta(
        vault="personal",
        tag="global",
        sources=["personal.folder:env/global"],
        updated_at=utc_now(),
        refresh_ok=True,
        item_count=5,
    )
    with _patch_state_dir(tmp_path):
        write_meta("personal", "global", meta)
        result = read_meta("personal", "global")

    assert result is not None
    assert result.vault == "personal"
    assert result.tag == "global"
    assert result.item_count == 5
    assert result.refresh_ok is True
    assert result.last_error is None


def test_read_meta_missing(tmp_path):
    with _patch_state_dir(tmp_path):
        assert read_meta("personal", "global") is None


def test_read_meta_corrupt(tmp_path):
    with _patch_state_dir(tmp_path):
        (tmp_path / "personal.global.meta.json").write_text("not json")
        assert read_meta("personal", "global") is None


def test_meta_is_stale(tmp_path):
    from datetime import timedelta

    now = utc_now()
    old = now - timedelta(hours=9)
    meta = SnapshotMeta(
        vault="personal",
        tag="global",
        sources=[],
        updated_at=old,
        refresh_ok=True,
        item_count=0,
    )
    assert meta.is_stale(now=now) is True


def test_meta_not_stale(tmp_path):
    from datetime import timedelta

    now = utc_now()
    recent = now - timedelta(minutes=10)
    meta = SnapshotMeta(
        vault="personal",
        tag="global",
        sources=[],
        updated_at=recent,
        refresh_ok=True,
        item_count=0,
    )
    assert meta.is_stale(now=now) is False


# ---------------------------------------------------------------------------
# Snapshot write / read
# ---------------------------------------------------------------------------


def test_write_and_read_snapshot(tmp_path):
    key = _fake_key()
    env = {"ANTHROPIC_API_KEY": "sk-test", "GITHUB_TOKEN": "ghp_test"}
    with _patch_state_dir(tmp_path), _patch_key(key):
        meta = write_snapshot("personal", "global", env, ["personal.folder:env/global"])
        result = read_snapshot("personal", "global")

    assert result == env
    assert meta.item_count == 2
    assert meta.refresh_ok is True


def test_read_snapshot_missing(tmp_path):
    with _patch_state_dir(tmp_path), _patch_key(_fake_key()):
        assert read_snapshot("personal", "global") is None


def test_read_snapshot_wrong_key(tmp_path):
    write_key = _fake_key()
    read_key = _fake_key()
    with _patch_state_dir(tmp_path), _patch_key(write_key):
        write_snapshot("personal", "global", {"X": "y"}, [])
    with _patch_state_dir(tmp_path), _patch_key(read_key):
        assert read_snapshot("personal", "global") is None


def test_write_snapshot_is_atomic(tmp_path):
    """No partial file visible during write — .tmp is renamed into place."""
    key = _fake_key()
    with _patch_state_dir(tmp_path), _patch_key(key):
        write_snapshot("personal", "global", {"K": "v"}, [])
        tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


def test_snapshot_exists(tmp_path):
    key = _fake_key()
    with _patch_state_dir(tmp_path), _patch_key(key):
        assert snapshot_exists("personal", "global") is False
        write_snapshot("personal", "global", {}, [])
        assert snapshot_exists("personal", "global") is True


def test_snapshot_path(tmp_path):
    with _patch_state_dir(tmp_path):
        p = snapshot_path("personal", "global")
    assert p == tmp_path / "personal.global.env.enc"


def test_invalid_vault_name_rejected(tmp_path):
    """Vault names with path separators or special chars must be rejected."""
    with _patch_state_dir(tmp_path):
        for bad in ["../evil", "per/sonal", "vault\x00name", "", "UPPER"]:
            with pytest.raises(ValueError):
                snapshot_path(bad, "global")


def test_invalid_tag_name_rejected(tmp_path):
    """Tag names with path separators or special chars must be rejected."""
    with _patch_state_dir(tmp_path):
        for bad in ["../evil", "my/tag", "tag\x00name", ""]:
            with pytest.raises(ValueError):
                snapshot_path("personal", bad)


def test_snapshot_file_permissions_0600(tmp_path):
    """Encrypted snapshot must not be world- or group-readable."""
    key = _fake_key()
    with _patch_state_dir(tmp_path), _patch_key(key):
        write_snapshot("personal", "global", {"SECRET": "value"}, [])
    enc_file = tmp_path / "personal.global.env.enc"
    mode = enc_file.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0600, got {oct(mode)}"


def test_two_tags_are_independent(tmp_path):
    """Secrets written to tag 'a' must not appear in tag 'b' and vice versa."""
    key_a = _fake_key()
    key_b = _fake_key()

    def get_key_by_tag(vault_name, tag):
        return key_a if tag == "a" else key_b

    with (
        _patch_state_dir(tmp_path),
        patch("sive.core.snapshot.get_key", side_effect=get_key_by_tag),
    ):
        write_snapshot("personal", "a", {"ONLY_IN_A": "val_a"}, [])
        write_snapshot("personal", "b", {"ONLY_IN_B": "val_b"}, [])
        result_a = read_snapshot("personal", "a")
        result_b = read_snapshot("personal", "b")

    assert result_a == {"ONLY_IN_A": "val_a"}
    assert result_b == {"ONLY_IN_B": "val_b"}
    assert "ONLY_IN_B" not in result_a
    assert "ONLY_IN_A" not in result_b


def test_snapshot_round_trip_exact_data(tmp_path):
    key = _fake_key()
    original = {"ANTHROPIC_API_KEY": "sk-xxx", "GITHUB_TOKEN": "ghp-yyy"}
    with _patch_state_dir(tmp_path), _patch_key(key):
        write_snapshot("personal", "global", original, ["personal.folder:env/global"])
        recovered = read_snapshot("personal", "global")

    assert recovered == original
