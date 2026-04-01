"""sive set — write a secret into a Bitwarden tag folder."""

from __future__ import annotations

import sys


def run(key: str, value: str, tag: str | None = None, vault_name: str = "personal") -> int:
    from ..core.bw import BWError, create_folder, find_folder_id, list_folders, upsert_note
    from ..core.project_config import read_project_tags, read_project_vault
    from ..core.snapshot import write_snapshot
    from ..core.snapshot_crypto import ensure_key
    from ..core.source_loader import SourceError, _ensure_session, load_source
    from ..core.vaults import ConfigError, load_vault

    if tag is None:
        vault_name = read_project_vault()
    if tag is None:
        project_tags = read_project_tags()
        if not project_tags:
            print(
                "sive: no .sive project config found — run 'sive setup' or use --tag",
                file=sys.stderr,
            )
            return 1
        tag = project_tags[-1]

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
        print(f"sive: {e}", file=sys.stderr)
        return 1

    try:
        folders = list_folders(session, appdata_dir=appdata_dir)
        folder_id = find_folder_id(folders, folder_path)
        if not folder_id:
            folder_id = create_folder(folder_path, session, appdata_dir=appdata_dir)
        upsert_note(key, value, folder_id, session, appdata_dir=appdata_dir)
    except BWError as e:
        print(f"sive: {e}", file=sys.stderr)
        return 1

    print(f"  Saved {key} to tag: {tag}")

    # Refresh only this tag's snapshot — other tags are untouched.
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
