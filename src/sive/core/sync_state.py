from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .bw import sync, unlock
from .keychain_macos import get_password
from .vaults import load_vault

STATE_DIR = Path.home() / ".local" / "state" / "sive"
SYNC_MIN_INTERVAL = timedelta(minutes=15)
LOCK_TIMEOUT = timedelta(minutes=5)
STALE_WARNING_THRESHOLD = timedelta(hours=24)


def _validate_vault_name(vault_name: str) -> None:
    if not vault_name or ".." in vault_name or "/" in vault_name or "\\" in vault_name:
        raise ValueError(f"Invalid vault name: {vault_name!r}")


def state_path(vault_name: str) -> Path:
    _validate_vault_name(vault_name)
    return STATE_DIR / f"{vault_name}.sync.json"


def lock_path(vault_name: str) -> Path:
    _validate_vault_name(vault_name)
    return STATE_DIR / f"{vault_name}.sync.lock"


def load_sync_state(vault_name: str) -> dict[str, str]:
    path = state_path(vault_name)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_sync_state(vault_name: str, state: dict[str, str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(vault_name).write_text(json.dumps(state, indent=2) + "\n")


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_sync_due(vault_name: str, *, now: datetime | None = None) -> bool:
    state = load_sync_state(vault_name)
    now = now or utc_now()
    last_success = parse_timestamp(state.get("last_successful_sync_at"))
    if last_success is None:
        return True
    return now - last_success >= SYNC_MIN_INTERVAL


def acquire_lock(vault_name: str, *, now: datetime | None = None) -> bool:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = now or utc_now()
    path = lock_path(vault_name)
    if path.exists():
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if now - mtime <= LOCK_TIMEOUT:
            return False
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as handle:
        handle.write(to_timestamp(now) + "\n")
    return True


def release_lock(vault_name: str) -> None:
    lock_path(vault_name).unlink(missing_ok=True)


def maybe_trigger_background_sync(vault_name: str) -> bool:
    if not is_sync_due(vault_name):
        return False
    if not acquire_lock(vault_name):
        return False
    command = [sys.executable, "-m", "sive", "_sync-vault", vault_name]
    try:
        with open(os.devnull, "w") as sink:
            subprocess.Popen(
                command,
                stdout=sink,
                stderr=sink,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        return True
    except Exception:
        release_lock(vault_name)
        return False


def load_known_tags(vault_name: str) -> list[str]:
    """Return cached env/ tag names from the last successful sync. Empty list if not cached."""
    state = load_sync_state(vault_name)
    tags = state.get("known_tags", [])
    if not isinstance(tags, list):
        return []
    return [t for t in tags if isinstance(t, str) and t]


def run_sync_vault(vault_name: str) -> int:
    now = utc_now()
    state = load_sync_state(vault_name)
    state["last_attempt_at"] = to_timestamp(now)
    save_sync_state(vault_name, state)

    try:
        try:
            vault = load_vault(vault_name)
            password = get_password(vault_name)
            session = unlock(password, appdata_dir=str(vault.appdata_dir))
            sync(session, appdata_dir=str(vault.appdata_dir))
            _write_snapshot_from_session(vault_name, session)
            _update_known_tags(vault_name, session, str(vault.appdata_dir), state)
            state["last_successful_sync_at"] = to_timestamp(utc_now())
            state.pop("last_error_at", None)
            state.pop("last_error", None)
            save_sync_state(vault_name, state)
            return 0
        except Exception as exc:
            state["last_error_at"] = to_timestamp(utc_now())
            state["last_error"] = str(exc)
            save_sync_state(vault_name, state)
            return 1
    finally:
        release_lock(vault_name)


def _update_known_tags(vault_name: str, session: str, appdata_dir: str, state: dict) -> None:
    """Persist env/ tag names into sync state so setup can read them without a bw call."""
    import logging

    from .bw import list_env_tags
    try:
        state["known_tags"] = list_env_tags(session, appdata_dir=appdata_dir)
    except Exception as e:
        logging.getLogger(__name__).debug("_update_known_tags failed: %s", e)


def _write_snapshot_from_session(vault_name: str, session: str) -> None:
    """Re-read all sources and write one snapshot per tag using an existing bw session."""
    from ..commands.refresh import _default_sources, _tag_from_source
    from .snapshot import write_snapshot
    from .snapshot_crypto import ensure_key
    from .source_loader import load_source

    for source in _default_sources(vault_name):
        tag = _tag_from_source(source)
        ensure_key(vault_name, tag)
        env = load_source(source, session_key=session)
        write_snapshot(vault_name, tag, env, [source])


def sync_is_stale(vault_name: str, *, now: datetime | None = None) -> bool:
    state = load_sync_state(vault_name)
    now = now or utc_now()
    last_success = parse_timestamp(state.get("last_successful_sync_at"))
    if last_success is None:
        return True
    return now - last_success >= STALE_WARNING_THRESHOLD
