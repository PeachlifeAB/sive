"""sive refresh — fetch secrets from vault and write encrypted per-tag snapshots."""

from __future__ import annotations

import sys
import time

from ..core.keychain_macos import KeychainError
from ..core.project_config import active_tags
from ..core.snapshot import write_snapshot
from ..core.snapshot_crypto import KeychainError as CryptoKeychainError
from ..core.snapshot_crypto import ensure_key
from ..core.source_loader import SourceError, load_source


def run(vault_name: str = "personal", sources: list[str] | None = None) -> int:
    """
    Unlock vault, resolve sources, write one encrypted snapshot per tag.

    Sources default to active tags from mise config when not supplied.
    Always exits non-zero on failure (unlike _mise-env which must exit 0).
    """
    if sources is None:
        sources = _default_sources(vault_name)

    print(f"sive refresh: vault={vault_name} sources={sources}")

    t0 = time.monotonic()
    failed = 0

    for source in sources:
        try:
            tag = _tag_from_source(source)
        except ValueError as e:
            print(f"sive: invalid source '{source}': {e}", file=sys.stderr)
            failed += 1
            continue
        try:
            ensure_key(vault_name, tag)
        except (KeychainError, CryptoKeychainError) as e:
            print(f"sive: snapshot key error for tag '{tag}': {e}", file=sys.stderr)
            failed += 1
            continue

        try:
            env = load_source(source)
        except SourceError as e:
            print(f"sive: refresh failed for tag '{tag}': {e}", file=sys.stderr)
            failed += 1
            continue
        except Exception as e:
            print(f"sive: unexpected error for tag '{tag}': {e}", file=sys.stderr)
            failed += 1
            continue

        try:
            meta = write_snapshot(vault_name, tag, env, [source])
        except Exception as e:
            print(f"sive: failed to write snapshot for tag '{tag}': {e}", file=sys.stderr)
            failed += 1
            continue

        elapsed = time.monotonic() - t0
        print(f"  [{tag}] {meta.item_count} vars written ({elapsed:.1f}s)")

    return 1 if failed else 0


def _tag_from_source(source: str) -> str:
    source = source.strip()
    if not source:
        raise ValueError("Invalid source: empty source")

    # source format: {vault}.folder:env/{tag}
    if ":env/" in source:
        tag = source.split(":env/", 1)[1].strip()
    else:
        if "/" not in source:
            raise ValueError(f"Invalid source: {source!r}")
        tag = source.rsplit("/", 1)[-1].strip()

    if not tag:
        raise ValueError(f"Invalid source: {source!r}")

    return tag


def _default_sources(vault_name: str) -> list[str]:
    return [f"{vault_name}.folder:env/{tag}" for tag in active_tags()]
