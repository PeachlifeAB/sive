"""Read and write encrypted env snapshots.

File layout under STATE_DIR (~/.local/state/sive/):
  <vault>.<tag>.env.enc    — AES-256-GCM encrypted JSON env dict (one per tag)
  <vault>.<tag>.meta.json  — plaintext metadata (no secrets)

Writes are atomic: write to a .tmp sibling, then rename.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sive.core.snapshot_crypto import decrypt_env, encrypt_env, get_key
from sive.core.sync_state import STATE_DIR, parse_timestamp, to_timestamp, utc_now

SNAPSHOT_STALE_THRESHOLD = timedelta(hours=8)

_VAULT_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
_TAG_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]{0,63}$")


def _safe_vault_name(vault_name: str) -> str:
    """Reject vault names that could escape the state directory."""
    if not _VAULT_NAME_RE.match(vault_name):
        raise ValueError(f"Invalid vault name: {vault_name!r}")
    return vault_name


def _safe_tag_name(tag: str) -> str:
    """Reject tag names that could escape the state directory."""
    if not _TAG_NAME_RE.match(tag):
        raise ValueError(f"Invalid tag name: {tag!r}")
    return tag


def _enc_path(vault_name: str, tag: str) -> Path:
    return STATE_DIR / f"{_safe_vault_name(vault_name)}.{_safe_tag_name(tag)}.env.enc"


def _meta_path(vault_name: str, tag: str) -> Path:
    return STATE_DIR / f"{_safe_vault_name(vault_name)}.{_safe_tag_name(tag)}.meta.json"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    closed = False
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.close(fd)
        closed = True
        os.replace(tmp, path)
    except:  # noqa: E722
        tmp.unlink(missing_ok=True)
        raise
    finally:
        if not closed:
            try:
                os.close(fd)
            except OSError:
                pass


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except:  # noqa: E722
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


@dataclass
class SnapshotMeta:
    vault: str
    tag: str
    sources: list[str]
    updated_at: datetime
    refresh_ok: bool
    item_count: int
    last_error: str | None = None

    def is_stale(
        self, *, now: datetime | None = None, threshold: timedelta = SNAPSHOT_STALE_THRESHOLD
    ) -> bool:
        now = now or utc_now()
        return now - self.updated_at >= threshold

    def age_seconds(self, *, now: datetime | None = None) -> float:
        now = now or utc_now()
        return (now - self.updated_at).total_seconds()


def read_meta(vault_name: str, tag: str) -> SnapshotMeta | None:
    path = _meta_path(vault_name, tag)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    updated_at = parse_timestamp(data.get("updated_at"))
    if updated_at is None:
        return None
    return SnapshotMeta(
        vault=data.get("vault", vault_name),
        tag=data.get("tag", tag),
        sources=data.get("sources", []),
        updated_at=updated_at,
        refresh_ok=data.get("refresh_ok", False),
        item_count=data.get("item_count", 0),
        last_error=data.get("last_error"),
    )


def write_meta(vault_name: str, tag: str, meta: SnapshotMeta) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "vault": meta.vault,
        "tag": meta.tag,
        "sources": meta.sources,
        "updated_at": to_timestamp(meta.updated_at),
        "refresh_ok": meta.refresh_ok,
        "item_count": meta.item_count,
        "last_error": meta.last_error,
    }
    _atomic_write_text(_meta_path(vault_name, tag), json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Snapshot read / write
# ---------------------------------------------------------------------------


def write_snapshot(
    vault_name: str, tag: str, env: dict[str, str], sources: list[str]
) -> SnapshotMeta:
    """Encrypt and write env for one tag to disk. Returns the written metadata."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    key = get_key(vault_name, tag)
    blob = encrypt_env(env, key)
    _atomic_write_bytes(_enc_path(vault_name, tag), blob)
    meta = SnapshotMeta(
        vault=vault_name,
        tag=tag,
        sources=sources,
        updated_at=utc_now(),
        refresh_ok=True,
        item_count=len(env),
        last_error=None,
    )
    write_meta(vault_name, tag, meta)
    return meta


def read_snapshot(vault_name: str, tag: str) -> dict[str, str] | None:
    """Decrypt and return env dict for one tag, or None if missing or unreadable."""
    path = _enc_path(vault_name, tag)
    if not path.exists():
        return None
    try:
        key = get_key(vault_name, tag)
        return decrypt_env(path.read_bytes(), key)
    except Exception:
        return None


def snapshot_path(vault_name: str, tag: str) -> Path:
    """Return the .enc path for use in watch_files declarations."""
    return _enc_path(vault_name, tag)


def snapshot_exists(vault_name: str, tag: str) -> bool:
    return _enc_path(vault_name, tag).exists()
