"""sive set — write a secret into a Bitwarden tag folder."""

from __future__ import annotations

import sys

from ..core.bw import BWError, create_folder, find_folder_id, list_folders, upsert_note
from ..core.pending_queue import enqueue_pending
from ..core.project_config import read_project_tags, read_project_vault
from ..core.snapshot import read_snapshot, write_snapshot
from ..core.snapshot_crypto import ensure_key
from ..core.source_loader import SourceError, _ensure_session, load_source
from ..core.vaults import ConfigError, load_vault

_NETWORK_MARKERS = ("502", "503", "econnrefused", "timeout", "network", "fetch", "statuscode")


def _is_network_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _NETWORK_MARKERS)


def _patch_snapshot(vault_name: str, tag: str, key: str, value: str) -> None:
    """Merge key into existing local snapshot without hitting the vault."""
    try:
        ensure_key(vault_name, tag)
        env = read_snapshot(vault_name, tag) or {}
        env[key] = value
        source = f"{vault_name}.folder:env/{tag}"
        write_snapshot(vault_name, tag, env, [source])
    except Exception as e:
        print(f"  Warning: could not patch local snapshot — {e}", file=sys.stderr)


def run(key: str, value: str, tag: str | None = None, vault_name: str = "personal") -> int:
    if tag is None:
        vault_name = read_project_vault()
    if tag is None:
        project_tags = read_project_tags()
        tag = project_tags[-1] if project_tags else "global"

    folder_path = f"env/{tag}"
    source = f"{vault_name}.folder:env/{tag}"

    try:
        vault = load_vault(vault_name)
    except ConfigError as e:
        print(f"sive: {e}", file=sys.stderr)
        return 1

    appdata_dir = str(vault.appdata_dir)

    try:
        session = _ensure_session(vault_name, None, appdata_dir=appdata_dir)
    except SourceError as e:
        if _is_network_error(e):
            enqueue_pending(vault_name, key, value, tag)
            _patch_snapshot(vault_name, tag, key, value)
            print(f"  Queued {key} (vault unreachable) — will sync when connection returns")
            return 0
        if "not logged in" not in str(e).lower():
            print(f"sive: {e}", file=sys.stderr)
            return 1
        from ..commands.setup import run_relogin
        rc, session, _ = run_relogin(vault_name)
        if rc != 0 or not session:
            return 1

    try:
        folders = list_folders(session, appdata_dir=appdata_dir)
        folder_id = find_folder_id(folders, folder_path)
        if not folder_id:
            folder_id = create_folder(folder_path, session, appdata_dir=appdata_dir)
        upsert_note(key, value, folder_id, session, appdata_dir=appdata_dir)
    except BWError as e:
        if _is_network_error(e):
            enqueue_pending(vault_name, key, value, tag)
            _patch_snapshot(vault_name, tag, key, value)
            print(f"  Queued {key} (vault unreachable) — will sync when connection returns")
            return 0
        print(f"sive: {e}", file=sys.stderr)
        return 1

    print(f"  Saved {key} to tag: {tag}")

    try:
        ensure_key(vault_name, tag)
        env = load_source(source, session_key=session)
        write_snapshot(vault_name, tag, env, [source])
    except Exception as e:
        print(f"  Warning: snapshot refresh failed — {e}", file=sys.stderr)
        print(
            "  Secret was written to vault but local snapshot is not yet updated.", file=sys.stderr
        )

    return 0
