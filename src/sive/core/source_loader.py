"""Resolve a sive source string to an env var dict."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .bw import (
    BWError,
    extract_env_vars,
    list_folders,
    list_items_in_folder,
    unlock,
)
from .keychain_macos import KeychainError, get_password
from .vaults import ConfigError, load_vault

# Matches: <vault>.folder:<selector>
SOURCE_RE = re.compile(r"^(?P<vault>[a-z_][a-z0-9_]*)\.folder:(?P<selector>.+)$")


class SourceError(Exception):
    pass


@dataclass(frozen=True)
class FolderSource:
    source: str
    vault_name: str
    folder_selector: str


@dataclass
class VaultContext:
    session: str
    appdata_dir: str
    folder_ids: dict[str, str]


def _parse_source(source: str) -> FolderSource:
    m = SOURCE_RE.match(source)
    if not m:
        raise SourceError(
            f"Invalid source format: '{source}'\nExpected format: <vault>.folder:<folder-name>"
        )

    return FolderSource(
        source=source,
        vault_name=m.group("vault"),
        folder_selector=m.group("selector"),
    )


def _build_vault_context(
    folder_source: FolderSource, session_key: str | None = None
) -> VaultContext:
    try:
        vault = load_vault(folder_source.vault_name)
    except ConfigError as e:
        raise SourceError(str(e)) from e

    session = _ensure_session(
        folder_source.vault_name,
        session_key,
        appdata_dir=str(vault.appdata_dir),
    )

    try:
        folders = list_folders(session, appdata_dir=str(vault.appdata_dir))
    except BWError as e:
        raise SourceError(f"bw list folders failed: {e}") from e

    return VaultContext(
        session=session,
        appdata_dir=str(vault.appdata_dir),
        folder_ids={folder.get("name", ""): folder.get("id", "") for folder in folders},
    )


def _ensure_session(
    vault_name: str,
    existing_session: str | None,
    *,
    appdata_dir: str,
) -> str:
    """Return a valid bw session key, unlocking silently if needed."""
    if existing_session:
        return existing_session

    # Try to get master password from keychain and unlock
    try:
        password = get_password(vault_name)
    except KeychainError as e:
        raise SourceError(str(e)) from e

    try:
        return unlock(password, appdata_dir=appdata_dir)
    except BWError as e:
        raise SourceError(f"Silent unlock failed: {e}") from e


def load_source(source: str, session_key: str | None = None) -> dict[str, str]:
    """
    Resolve a source string like 'personal.folder:env/global' to an env var dict.

    Raises SourceError on any failure.
    """
    folder_source = _parse_source(source)
    context = _build_vault_context(folder_source, session_key=session_key)

    folder_id = context.folder_ids.get(folder_source.folder_selector)
    if not folder_id:
        raise SourceError(
            f"Folder '{folder_source.folder_selector}' not found"
            f" in vault '{folder_source.vault_name}'."
        )

    try:
        items = list_items_in_folder(
            folder_id,
            context.session,
            appdata_dir=context.appdata_dir,
        )
    except BWError as e:
        raise SourceError(f"bw list items failed: {e}") from e

    return extract_env_vars(items)


def load_sources(sources: list[str], session_keys: dict[str, str] | None = None) -> dict[str, str]:
    parsed_sources = [_parse_source(source) for source in sources]
    vault_contexts: dict[str, VaultContext] = {}

    for folder_source in parsed_sources:
        if folder_source.vault_name in vault_contexts:
            continue
        try:
            vault_contexts[folder_source.vault_name] = _build_vault_context(
                folder_source,
                session_key=(session_keys or {}).get(folder_source.vault_name),
            )
        except SourceError as e:
            raise SourceError(f"{folder_source.source}: {e}") from e

    merged_env: dict[str, str] = {}
    for folder_source in parsed_sources:
        context = vault_contexts[folder_source.vault_name]
        folder_id = context.folder_ids.get(folder_source.folder_selector)
        if not folder_id:
            raise SourceError(
                f"{folder_source.source}: Folder '{folder_source.folder_selector}'"
                f" not found in vault '{folder_source.vault_name}'."
            )
        try:
            items = list_items_in_folder(
                folder_id,
                context.session,
                appdata_dir=context.appdata_dir,
            )
        except BWError as e:
            raise SourceError(f"{folder_source.source}: bw list items failed: {e}") from e
        merged_env.update(extract_env_vars(items))

    return merged_env
