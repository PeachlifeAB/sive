"""sive set — write a secret into a Bitwarden tag folder."""

from __future__ import annotations

import sys

from ..core.bw import (
    BWError,
    create_folder,
    delete_item,
    find_folder_id,
    list_folders,
    list_items_in_folder,
    upsert_note,
)
from ..core.pending_queue import enqueue_pending
from ..core.project_config import read_project_tags, read_project_vault
from ..core.snapshot import read_snapshot, write_snapshot
from ..core.snapshot_crypto import ensure_key
from ..core.source_loader import SourceError, _ensure_session, load_source
from ..core.vaults import ConfigError, load_vault


def _echo(*values: object, sep: str = " ", end: str = "\n", file=None) -> None:
    stream = file or sys.stdout
    stream.write(sep.join(str(value) for value in values) + end)


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
        _echo(f"  Warning: could not patch local snapshot — {e}", file=sys.stderr)


def run(
    key: str,
    value: str | None = None,
    tag: str | None = None,
    vault_name: str = "personal",
    *,
    delete: bool = False,
) -> int:
    if tag is None:
        vault_name = read_project_vault()
        project_tags = read_project_tags()
        if not project_tags:
            _echo(
                "sive: no active project configuration; run `sive setup` or provide `--tag`",
                file=sys.stderr,
            )
            return 1
        tag = project_tags[-1]

    folder_path = f"env/{tag}"
    source = f"{vault_name}.folder:env/{tag}"

    try:
        vault = load_vault(vault_name)
    except ConfigError as e:
        _echo(f"sive: {e}", file=sys.stderr)
        return 1

    appdata_dir = str(vault.appdata_dir)

    try:
        session = _ensure_session(vault_name, None, appdata_dir=appdata_dir)
    except SourceError as e:
        if _is_network_error(e) and not delete:
            assert value is not None
            enqueue_pending(vault_name, key, value, tag)
            _patch_snapshot(vault_name, tag, key, value)
            _echo(f"  Queued {key} (vault unreachable) — will sync when connection returns")
            return 0
        if "not logged in" not in str(e).lower():
            _echo(f"sive: {e}", file=sys.stderr)
            return 1
        from ..commands.setup import run_relogin

        rc, session, _ = run_relogin(vault_name)
        if rc != 0 or not session:
            return 1

    try:
        folders = list_folders(session, appdata_dir=appdata_dir)
        folder_id = find_folder_id(folders, folder_path)
        if delete:
            if not folder_id:
                _echo(f"sive: tag '{tag}' was not found in the vault", file=sys.stderr)
                return 1
            matches = [
                item
                for item in list_items_in_folder(folder_id, session, appdata_dir=appdata_dir)
                if item.get("name") == key and item.get("type") == 2
            ]
            if not matches:
                _echo(f"sive: key '{key}' was not found in tag: {tag}", file=sys.stderr)
                return 1
            if len(matches) > 1:
                _echo(f"sive: key '{key}' is ambiguous in tag: {tag}", file=sys.stderr)
                return 1
            delete_item(matches[0]["id"], session, appdata_dir=appdata_dir)
        else:
            assert value is not None
            if not folder_id:
                folder_id = create_folder(folder_path, session, appdata_dir=appdata_dir)
            upsert_note(key, value, folder_id, session, appdata_dir=appdata_dir)
    except BWError as e:
        if _is_network_error(e) and not delete:
            assert value is not None
            enqueue_pending(vault_name, key, value, tag)
            _patch_snapshot(vault_name, tag, key, value)
            _echo(f"  Queued {key} (vault unreachable) — will sync when connection returns")
            return 0
        _echo(f"sive: {e}", file=sys.stderr)
        return 1

    _echo(f"  {'Deleted' if delete else 'Saved'} {key} {'from' if delete else 'to'} tag: {tag}")

    try:
        ensure_key(vault_name, tag)
        env = load_source(source, session_key=session)
        write_snapshot(vault_name, tag, env, [source])
    except Exception as e:
        _echo(f"  Warning: snapshot refresh failed — {e}", file=sys.stderr)
        mutation = "deleted from" if delete else "written to"
        _echo(
            f"  Key was {mutation} vault but local snapshot is not yet updated.",
            file=sys.stderr,
        )

    return 0
