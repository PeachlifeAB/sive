"""Thin wrapper around the Bitwarden CLI ('bw')."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


class BWError(Exception):
    pass


class BWNotInstalledError(BWError):
    pass


class BWAuthError(BWError):
    pass


ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TAG_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\-]*$")


def _run(
    args: list[str],
    env: dict[str, str] | None = None,
    timeout: int = 30,
    appdata_dir: str | Path | None = None,
) -> str:
    """Run a bw command and return stdout. Raises BWError on failure."""
    full_env = {**os.environ}
    if env:
        full_env.update(env)
    if appdata_dir is not None:
        full_env["BITWARDENCLI_APPDATA_DIR"] = str(appdata_dir)

    try:
        result = subprocess.run(
            ["bw", "--nointeraction"] + args,
            capture_output=True,
            text=True,
            env=full_env,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise BWNotInstalledError(
            "'bw' CLI not found. Install it via mise:\n  mise use -g \"npm:@bitwarden/cli@latest\""
        )
    except subprocess.TimeoutExpired:
        raise BWError(f"bw command timed out after {timeout}s: bw {' '.join(args[:2])}")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "not logged in" in stderr.lower() or "you are not logged in" in stderr.lower():
            raise BWAuthError("Not logged in. Run 'sive setup' to authenticate.")
        if "mac failed" in stderr.lower() or "invalid master password" in stderr.lower():
            raise BWAuthError("Incorrect master password.")
        raise BWError(f"bw {args[0]} failed: {stderr or result.stdout.strip()}")

    return result.stdout.strip()


def set_server(
    server_url: str,
    *,
    status: dict[str, Any] | None = None,
    appdata_dir: str | Path | None = None,
) -> bool:
    """Configure bw to talk to a specific server.

    bw rejects 'config server' when already logged in, even if the server
    matches. Check current server first and skip if it already matches.
    """
    try:
        current_status = status if status is not None else get_status(appdata_dir=appdata_dir)
        if (current_status.get("serverUrl") or "").rstrip("/") == server_url.rstrip("/"):
            return False
    except BWError:
        pass  # can't get status — attempt config anyway
    _run(["config", "server", server_url], appdata_dir=appdata_dir)
    return True


def get_status(*, appdata_dir: str | Path | None = None) -> dict[str, Any]:
    """Return parsed output of 'bw status'."""
    output = _run(["status"], appdata_dir=appdata_dir)
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"status": "unknown"}


def unlock(master_password: str, *, appdata_dir: str | Path | None = None) -> str:
    """Unlock the vault and return the session key."""
    env = {"SIVE_BW_PASSWORD": master_password}
    try:
        session_key = _run(
            ["unlock", "--passwordenv", "SIVE_BW_PASSWORD", "--raw"],
            env=env,
            appdata_dir=appdata_dir,
        )
    except BWError as e:
        raise BWAuthError(f"Unlock failed: {e}") from e
    if not session_key:
        raise BWAuthError("Unlock returned empty session key.")
    return session_key


def sync(session_key: str, *, appdata_dir: str | Path | None = None) -> None:
    """Sync vault with server."""
    _run(["sync", "--session", session_key], appdata_dir=appdata_dir)


def list_folders(
    session_key: str, *, appdata_dir: str | Path | None = None
) -> list[dict[str, Any]]:
    """Return list of vault folders."""
    output = _run(["list", "folders", "--session", session_key], appdata_dir=appdata_dir)
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return []


def list_items_in_folder(
    folder_id: str,
    session_key: str,
    *,
    appdata_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return list of items in a folder."""
    output = _run(
        ["list", "items", "--folderid", folder_id, "--session", session_key],
        appdata_dir=appdata_dir,
    )
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return []


def find_folder_id(folders: list[dict[str, Any]], name: str) -> str | None:
    """Find a folder by exact name. Returns folder ID or None."""
    for folder in folders:
        if folder.get("name") == name:
            return folder["id"]
    return None


def create_folder(name: str, session_key: str, *, appdata_dir: str | Path | None = None) -> str:
    """Create a folder and return its ID."""
    import base64

    payload = base64.b64encode(json.dumps({"name": name}).encode()).decode()
    output = _run(["create", "folder", payload, "--session", session_key], appdata_dir=appdata_dir)
    try:
        return json.loads(output)["id"]
    except (json.JSONDecodeError, KeyError) as e:
        raise BWError(f"Failed to parse create folder response: {e}") from e


def upsert_note(
    name: str,
    value: str,
    folder_id: str,
    session_key: str,
    *,
    appdata_dir: str | Path | None = None,
) -> None:
    """Create or update a Secure Note item with the given name in folder_id."""
    import base64

    # Find existing item with this name in this folder
    output = _run(
        ["list", "items", "--folderid", folder_id, "--session", session_key],
        appdata_dir=appdata_dir,
    )
    try:
        items = json.loads(output)
    except json.JSONDecodeError:
        items = []

    existing = next((i for i in items if i.get("name") == name and i.get("type") == 2), None)

    if existing:
        existing["notes"] = value
        payload = base64.b64encode(json.dumps(existing).encode()).decode()
        _run(
            ["edit", "item", existing["id"], payload, "--session", session_key],
            appdata_dir=appdata_dir,
        )
    else:
        item = {
            "organizationId": None,
            "collectionIds": [],
            "folderId": folder_id,
            "type": 2,
            "name": name,
            "notes": value,
            "favorite": False,
            "secureNote": {"type": 0},
            "fields": [],
            "reprompt": 0,
        }
        payload = base64.b64encode(json.dumps(item).encode()).decode()
        _run(["create", "item", payload, "--session", session_key], appdata_dir=appdata_dir)


def delete_item(item_id: str, session_key: str, *, appdata_dir: str | Path | None = None) -> None:
    _run(["delete", "item", item_id, "--session", session_key], appdata_dir=appdata_dir)


def list_env_tags(session_key: str, *, appdata_dir: str | Path | None = None) -> list[str]:
    """Return sorted tag names from vault folders matching env/<tag>."""
    folders = list_folders(session_key, appdata_dir=appdata_dir)
    tags = []
    for folder in folders:
        name = folder.get("name", "")
        if name.startswith("env/"):
            tag = name[4:]
            if tag and _TAG_RE.match(tag):
                tags.append(tag)
    return sorted(tags)


def delete_folder(
    folder_id: str, session_key: str, *, appdata_dir: str | Path | None = None
) -> None:
    _run(["delete", "folder", folder_id, "--session", session_key], appdata_dir=appdata_dir)


def extract_env_vars(items: list[dict[str, Any]]) -> dict[str, str]:
    """
    Extract env vars from vault items.

    Rules:
    - Item must be a secure note (type == 2)
    - Item name must match ^[A-Za-z_][A-Za-z0-9_]*$
    - Value is item.notes
    """
    result = {}
    for item in items:
        # type 2 = secure note
        if item.get("type") != 2:
            continue
        name = item.get("name", "")
        if not ENV_VAR_RE.match(name):
            continue
        notes = item.get("notes") or ""
        result[name] = notes
    return result
