"""sive status — show vault state and active tags."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from ..core.bw import BWError, BWNotInstalledError, get_status
from ..core.keychain_macos import KeychainError, get_password
from ..core.sync_state import load_sync_state, sync_is_stale
from ..core.vaults import ConfigError, load_vault


def _echo(*values: object, sep: str = " ", end: str = "\n", file=None) -> None:
    stream = file or sys.stdout
    stream.write(sep.join(str(value) for value in values) + end)


def run() -> int:
    from .. import __version__

    _echo(f"sive {__version__}\n")

    try:
        vault = load_vault("personal")
    except ConfigError as e:
        _echo(f"Config error: {e}", file=sys.stderr)
        return 1

    try:
        status = get_status(appdata_dir=str(vault.appdata_dir))
    except BWNotInstalledError:
        _echo("bw CLI: NOT INSTALLED", file=sys.stderr)
        _echo("  Install: brew install bitwarden-cli", file=sys.stderr)
        _echo("  Or: npm install -g @bitwarden/cli", file=sys.stderr)
        return 1
    except BWError as e:
        _echo(f"bw CLI: error — {e}", file=sys.stderr)
        return 1

    keychain_ok = True
    try:
        get_password("personal")
    except KeychainError:
        keychain_ok = False

    bw_status = status.get("status", "unknown")
    server_url = status.get("serverUrl") or vault.server
    user_email = status.get("userEmail", "")
    server_matches = server_url.rstrip("/") == vault.server.rstrip("/")
    sync_state = load_sync_state(vault.name)
    active_tags, cache_enabled, cache_ttl = _read_mise_state()

    _echo("Vault:")
    _echo(f"  name: {vault.name}")
    _echo(f"  configured server: {vault.server}")
    _echo(f"  current server: {server_url}")
    _echo(f"  server matches config: {'yes' if server_matches else 'no'}")
    _echo(f"  appdata dir: {vault.appdata_dir}")
    _echo(f"  status: {bw_status}")
    _echo(f"  keychain: {'ok' if keychain_ok else 'not set'}")
    if user_email:
        _echo(f"  user: {user_email}")

    _echo()

    _echo("Active tags:")
    if active_tags:
        for tag in active_tags:
            _echo(f"  - {tag}")
    else:
        _echo("  sive not configured in mise")

    _echo()
    _echo("Cache:")
    _echo(f"  mise env_cache: {'enabled' if cache_enabled else 'disabled'}")
    _echo(f"  mise env_cache_ttl: {cache_ttl or 'unset'}")

    _echo()
    _echo("Background sync:")
    _echo(f"  last successful sync: {sync_state.get('last_successful_sync_at', 'never')}")
    _echo(f"  last attempt: {sync_state.get('last_attempt_at', 'never')}")
    _echo(f"  stale: {'yes' if sync_is_stale(vault.name) else 'no'}")
    if sync_state.get("last_error"):
        _echo(f"  last error at: {sync_state.get('last_error_at', 'unknown')}")
        _echo(f"  last error: {sync_state['last_error']}")

    if not keychain_ok:
        _echo(
            "\nWarning: master password not in Keychain — silent unlock will fail.",
            file=sys.stderr,
        )
        return 1

    if not active_tags:
        _echo("Warning: no active tags configured.", file=sys.stderr)
    if not cache_enabled:
        _echo("Warning: mise env_cache is disabled.", file=sys.stderr)
    if not server_matches:
        _echo("Warning: current vault server does not match configured server.", file=sys.stderr)

    if not active_tags or not cache_enabled or not server_matches:
        return 1

    return 0


def _read_mise_state() -> tuple[list[str], bool, str]:
    mise_config = Path.home() / ".config" / "mise" / "config.toml"
    if not mise_config.exists():
        return [], False, ""

    try:
        data = tomllib.loads(mise_config.read_text())
    except tomllib.TOMLDecodeError as _error:
        return [], False, ""

    settings = data.get("settings", {})
    env = data.get("env", {})
    sive = {}
    if isinstance(env, dict):
        if isinstance(env.get("_.sive"), dict):
            sive = env["_.sive"]
        elif isinstance(env.get("_"), dict) and isinstance(env["_"].get("sive"), dict):
            sive = env["_"]["sive"]
    tags = sive.get("tags") if isinstance(sive, dict) else None
    if tags is None:
        normalized_tags = []
    elif isinstance(tags, str):
        normalized_tags = [tags]
    else:
        try:
            normalized_tags = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
        except TypeError as _error:
            normalized_tags = []
    return (
        normalized_tags,
        bool(settings.get("env_cache", False)),
        str(settings.get("env_cache_ttl", "")),
    )
