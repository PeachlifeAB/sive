"""Offline write queue — entries written here when vault is unreachable."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .bw import find_folder_id, list_folders, upsert_note

STATE_DIR = Path.home() / ".local" / "state" / "sive"


def _queue_path(vault_name: str) -> Path:
    return STATE_DIR / f"{vault_name}.pending.json"


def load_pending(vault_name: str) -> list[dict[str, Any]]:
    path = _queue_path(vault_name)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_pending(vault_name: str, entries: list[dict[str, Any]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _queue_path(vault_name)
    tmp = path.with_suffix(".tmp")
    getattr(tmp, "write_text")(json.dumps(entries, indent=2) + "\n")
    os.replace(tmp, path)


def enqueue_pending(vault_name: str, key: str, value: str, tag: str) -> None:
    entries = load_pending(vault_name)
    entries.append({"key": key, "value": value, "tag": tag})
    _save_pending(vault_name, entries)


def drain_pending(vault_name: str, session: str, appdata_dir: str) -> int:
    entries = load_pending(vault_name)
    if not entries:
        return 0

    try:
        folders = list_folders(session, appdata_dir=appdata_dir)
    except Exception:
        return 0

    drained = 0
    remaining = []
    for entry in entries:
        try:
            folder_id = find_folder_id(folders, f"env/{entry['tag']}")
            if folder_id is None:
                remaining.append(entry)
                continue
            upsert_note(entry["key"], entry["value"], folder_id, session, appdata_dir=appdata_dir)
            drained += 1
        except Exception:
            remaining.append(entry)

    _save_pending(vault_name, remaining)
    return drained
