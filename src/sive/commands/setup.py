"""sive login / sive setup — vault authentication and project configuration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..core import ui
from ..core.bw import BWError, ensure_bw_cli, get_status, list_env_tags, set_server, unlock
from ..core.keychain_macos import KeychainError, store_email, store_password
from ..core.keychain_macos import get_email as get_stored_email
from ..core.keychain_macos import get_password as get_stored_password
from ..core.project_config import write_project_config
from ..core.sync_state import load_known_tags
from ..core.vaults import CONFIG_DIR, VAULTS_TOML, ConfigError, load_vault, write_vault_stub


def _echo(*values: object, sep: str = " ", end: str = "\n", file=None) -> None:
    stream = file or sys.stdout
    stream.write(sep.join(str(value) for value in values) + end)


MISE_CONFIG_DIR = Path.home() / ".config" / "mise"
GLOBAL_MISE_CONFIG = MISE_CONFIG_DIR / "config.toml"

SIVE_MISE_DIRECTIVE = "_.sive = {}"
MISE_SETTINGS_BLOCK = """[settings]
env_cache = false
"""

MISE_ENV_BLOCK = f"""
{MISE_SETTINGS_BLOCK.strip()}

[env]
{SIVE_MISE_DIRECTIVE}
"""


def run() -> int:
    # Called only by tests. Not registered as a public CLI command.
    rc, _, _ = _run_login()
    return rc


def _print_keychain_error(error: KeychainError) -> None:
    for line in str(error).splitlines():
        _echo(f"  {line}" if line else "", file=sys.stderr)


def _run_login() -> tuple[int, str | None, str | None]:
    """Run vault login flow. Returns (exit_code, session_key, appdata_dir)."""
    ui.style("sive setup", bold=True, foreground="#FAFAFA", background="#7D56F4", padding="0 1")
    _echo()

    # Step 1: Check bw is installed
    _echo("Checking for bw CLI...")
    if not ensure_bw_cli():
        return 1, None, None

    # Step 2: Ensure vaults.toml exists — but don't overwrite existing
    vault_name = "personal"
    if not VAULTS_TOML.exists():
        _echo(f"\nCreating {VAULTS_TOML} ...")
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Step 3: Prompt for server URL — always required, no default
    _echo(f"\nConfigure vault '{vault_name}':")
    server_url = ""
    while not server_url:
        server_url = ui.input("Server URL", placeholder="https://vw.yourdomain.com")
        if not server_url:
            _echo("  Server URL is required.")

    # Write/update vaults.toml
    write_vault_stub(vault_name, server_url)
    _echo(f"  Written to {VAULTS_TOML}")

    vault = load_vault(vault_name)
    appdata_dir = str(vault.appdata_dir)
    status = ui.spin("Checking vault status...", lambda: _get_status_or_empty(appdata_dir))

    try:
        server_changed = ui.spin(
            f"Configuring bw to use {server_url} ...",
            lambda: set_server(server_url, status=status, appdata_dir=appdata_dir),
        )
    except BWError as e:
        _echo(f"  Error: {e}", file=sys.stderr)
        return 1, None, None

    if server_changed:
        status = {}

    _echo("\nLogging in to Bitwarden...")
    email = ui.input("Email")
    master_password = ui.password("Master password")

    bw_status = status.get("status", "unauthenticated")
    bw_email = status.get("userEmail", "")

    if bw_status in ("locked", "unlocked"):
        if bw_email.lower() == email.lower():
            _echo(f"  Already logged in as {bw_email}.")
        else:
            _echo(
                f"  Already logged in as {bw_email}.\n"
                f"  Run 'BITWARDENCLI_APPDATA_DIR={vault.appdata_dir} bw logout'"
                f" first to switch to {email}.",
                file=sys.stderr,
            )
            return 1, None, None
    else:
        env = {**os.environ, "SIVE_BW_PASSWORD": master_password}
        env["BITWARDENCLI_APPDATA_DIR"] = appdata_dir

        def _do_login() -> int:
            return subprocess.run(
                ["bw", "login", email, "--passwordenv", "SIVE_BW_PASSWORD"],
                env=env,
                capture_output=True,
            ).returncode

        rc = ui.spin("Logging in...", _do_login)
        if rc != 0:
            _echo("  Login failed.", file=sys.stderr)
            return 1, None, None
        _echo("  Logged in.")

    if not ui.confirm("Store master password in macOS Keychain for silent unlock?"):
        _echo("  Skipped. Silent unlock will not work without a stored password.")
        _patch_mise_config()
        _echo("\nSetup complete. Open a new shell to activate sive.")
        return 0, None, None

    try:
        session_key = ui.spin(
            "Validating unlock...", lambda: unlock(master_password, appdata_dir=appdata_dir)
        )
    except BWError as e:
        _echo(f"  Unlock failed: {e}", file=sys.stderr)
        _echo("  Master password NOT stored. Re-run 'sive setup' to retry.")
        return 1, None, None

    try:
        store_password(vault_name, master_password)
        store_email(vault_name, email)
    except KeychainError as e:
        _print_keychain_error(e)
        _echo(
            "  Bitwarden login worked, but silent unlock is disabled until Keychain is fixed.",
            file=sys.stderr,
        )
        if ui.confirm("Continue setup without silent unlock?", default=True):
            _patch_mise_config()
            _echo("\nSetup complete. Open a new shell to activate sive.")
            _echo("Run 'sive setup' again after fixing Keychain to enable silent unlock.")
            return 0, None, None
        return 1, None, None
    _echo("  Credentials stored in Keychain.")

    from ..core.snapshot_crypto import ensure_key

    ui.spin("Ensuring snapshot encryption key...", lambda: ensure_key(vault_name, "global"))
    _echo("  Snapshot key ready in Keychain.")

    from .refresh import run as run_refresh

    if ui.spin("Running initial refresh...", lambda: run_refresh(vault_name=vault_name)) != 0:
        _echo("  Warning: initial refresh failed — run 'sive refresh' manually.", file=sys.stderr)

    _patch_mise_config()

    _echo("\nSetup complete. Open a new shell to activate sive.")
    return 0, session_key, appdata_dir


def run_project_setup(tags: list[str] | None = None, no_global: bool = False) -> int:
    ui.style("sive setup", bold=True, foreground="#FAFAFA", background="#7D56F4", padding="0 1")
    _echo()

    login_session: tuple[str, str] | None = None
    if not _bootstrap_ready():
        _echo("Sive needs to connect this Mac to your vault first.\n")
        rc, sk, ad = _run_login()
        if rc != 0:
            return 1
        if sk and ad:
            login_session = (sk, ad)

    if tags is None:
        available = load_known_tags("personal")
        if not available:

            def _fetch() -> list[str]:
                try:
                    # login_session is None when the user skipped keychain storage during
                    # _run_login. _unlock_vault will also return None in that case (no stored
                    # password yet). The free-text tag prompt is the correct fallback here.
                    session = login_session or _unlock_vault("personal")
                    if session:
                        sk, ad = session
                        return list_env_tags(sk, appdata_dir=ad)
                    return []
                except Exception as e:
                    _echo(f"\n  Warning: could not load tags from vault ({e})", file=sys.stderr)
                    return []

            available = ui.spin("Loading tags from vault...", _fetch)
        if available:
            tags = ui.choose("Select project tags", available)
            if not tags:
                _echo("  No tags selected. Aborted.", file=sys.stderr)
                return 1
        else:
            raw = ui.input("Project tag(s) to load", placeholder="e.g. myproject")
            if not raw:
                _echo("  No tags entered. Aborted.", file=sys.stderr)
                return 1
            tags = [t.strip() for t in raw.replace(",", " ").split() if t.strip()]

    if not tags:
        _echo("  No tags provided.", file=sys.stderr)
        return 1

    _patch_mise_config()

    # Auto-prepend global unless opted out or already present
    if not no_global and "global" not in tags:
        tags = ["global"] + tags

    from ..core.snapshot_crypto import ensure_key

    vault_name = "personal"
    for tag in tags:
        try:
            ensure_key(vault_name, tag)
        except Exception as e:
            _echo(
                f"  Warning: could not create snapshot key for tag '{tag}': {e}",
                file=sys.stderr,
            )

    write_project_config(tags, vault=vault_name)
    tag_list = ", ".join(tags)
    _echo(f"\n  This directory is now configured for tags: {tag_list}")
    _echo("  Secrets will be available automatically in new shells.")
    return 0


def _unlock_vault(vault_name: str) -> tuple[str, str] | None:
    """Silent unlock. Returns (session_key, appdata_dir) or None on any error."""
    try:
        vault = load_vault(vault_name)
        password = get_stored_password(vault_name)
        session_key = unlock(password, appdata_dir=str(vault.appdata_dir))
        return session_key, str(vault.appdata_dir)
    except KeychainError:
        return None
    except BWError as e:
        _echo(f"  Warning: silent unlock failed ({e})", file=sys.stderr)
        return None
    except Exception as e:
        _echo(f"  Warning: unexpected error during unlock ({e})", file=sys.stderr)
        return None


def run_relogin(vault_name: str = "personal") -> tuple[int, str | None, str | None]:
    """Re-authenticate a configured vault.

    Returns (exit_code, session_key, appdata_dir).
    """
    try:
        vault = load_vault(vault_name)
    except ConfigError as e:
        _echo(f"sive: {e}", file=sys.stderr)
        return 1, None, None

    appdata_dir = str(vault.appdata_dir)
    status = _get_status_or_empty(appdata_dir)

    try:
        set_server(vault.server, status=status, appdata_dir=appdata_dir)
    except BWError as e:
        _echo(f"sive: {e}", file=sys.stderr)
        return 1, None, None

    bw_status = status.get("status", "unauthenticated")
    bw_email = status.get("userEmail", "")

    _echo("Vault session expired. Please log in again.")
    stored_email = get_stored_email(vault_name)
    email = stored_email or bw_email
    if not email:
        email = ui.input("Email")
    else:
        _echo(f"  Email: {email}")
    master_password = ui.password("Master password")

    if bw_status in ("locked", "unlocked"):
        if bw_email.lower() != email.lower():
            _echo(
                f"sive: already logged in as {bw_email}. Run "
                f"'BITWARDENCLI_APPDATA_DIR={appdata_dir} bw logout' to switch.",
                file=sys.stderr,
            )
            return 1, None, None
    else:
        env = {
            **os.environ,
            "SIVE_BW_PASSWORD": master_password,
            "BITWARDENCLI_APPDATA_DIR": appdata_dir,
        }
        rc = ui.spin(
            "Logging in...",
            lambda: (
                subprocess.run(
                    ["bw", "login", email, "--passwordenv", "SIVE_BW_PASSWORD"],
                    env=env,
                    capture_output=True,
                ).returncode
            ),
        )
        if rc != 0:
            _echo("sive: login failed.", file=sys.stderr)
            return 1, None, None

    try:
        session_key = ui.spin(
            "Unlocking...", lambda: unlock(master_password, appdata_dir=appdata_dir)
        )
    except BWError as e:
        _echo(f"sive: unlock failed: {e}", file=sys.stderr)
        return 1, None, None

    try:
        store_password(vault_name, master_password)
        store_email(vault_name, email)
    except KeychainError as e:
        _print_keychain_error(e)
        _echo(
            "  Logged in for this command, but silent unlock is still disabled.",
            file=sys.stderr,
        )
        return 0, session_key, appdata_dir

    _echo("  Logged in and keychain updated.")
    return 0, session_key, appdata_dir


def _bootstrap_ready() -> bool:
    try:
        vault = load_vault("personal")
        get_stored_password("personal")
        status = _get_status_or_empty(str(vault.appdata_dir))
        return status.get("status") in ("locked", "unlocked")
    except (ConfigError, KeychainError):
        return False


def _global_mise_config_path() -> Path:
    """Return the only mise config path this command is allowed to edit."""
    config_dir = MISE_CONFIG_DIR.expanduser().resolve()
    config_path = GLOBAL_MISE_CONFIG.expanduser().resolve()
    if config_path.parent != config_dir:
        raise RuntimeError(f"Refusing to edit mise config outside {config_dir}: {config_path}")
    return config_path


def _read_mise_config(config_path: Path) -> str:
    with config_path.open(encoding="utf-8") as f:
        return f.read()


def _assert_mise_config_path(config_path: Path) -> None:
    if config_path.name != "config.toml":
        raise RuntimeError(f"Refusing to edit unexpected mise config filename: {config_path}")


def _write_mise_config(config_path: Path, content: str) -> None:
    _assert_mise_config_path(config_path)
    with config_path.open("w", encoding="utf-8") as f:
        f.write(content)


def _append_mise_config(config_path: Path, content: str) -> None:
    _assert_mise_config_path(config_path)
    with config_path.open("a", encoding="utf-8") as f:
        f.write(content)


def _patch_mise_config() -> None:
    """Add sive env directive to global mise config if not already present."""
    if not ui.ensure_homebrew_command("mise", "mise", "mise"):
        return

    config_path = _global_mise_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        content = _read_mise_config(config_path)
        if "_.sive" in content:
            if SIVE_MISE_DIRECTIVE in content:
                normalized = content.replace("env_cache = true", "env_cache = false")
                normalized = normalized.replace('env_cache_ttl = "15m"\n', "")
                if normalized != content:
                    _write_mise_config(config_path, normalized)
                    _echo(f"\nUpdated sive config in {config_path} ...")
                    _echo("  Done.")
                    return
                return  # already configured, nothing to do
            import re

            updated = re.sub(r"_.sive\s*=\s*\{[^\n]*\}", SIVE_MISE_DIRECTIVE, content)
            updated = updated.replace("env_cache = true", "env_cache = false")
            updated = updated.replace('env_cache_ttl = "15m"\n', "")
            _write_mise_config(config_path, updated)
            _echo(f"\nUpdated sive config in {config_path} ...")
            _echo("  Done.")
            return
        # If any conflicting sections exist, do not blindly append —
        # duplicate TOML sections produce invalid or conflicting config.
        conflicting = [s for s in ("[settings]", "[env]") if s in content]
        if conflicting:
            _echo(f"\nCannot safely patch {config_path}")
            _echo(f"  Existing sections that would conflict: {', '.join(conflicting)}")
            _echo("  Add this manually to your mise config:\n")
            _print_manual_mise_guidance(indent="  ")
            return
        _echo(f"\nPatching {config_path} ...")
        _append_mise_config(config_path, f"\n[env]\n{SIVE_MISE_DIRECTIVE}\n")
    else:
        _echo(f"\nCreating {config_path} ...")
        _write_mise_config(config_path, MISE_ENV_BLOCK.strip() + "\n")

    _echo("  Done.")


def _get_status_or_empty(appdata_dir: str) -> dict[str, str]:
    try:
        return get_status(appdata_dir=appdata_dir)
    except BWError:
        return {}


def _print_manual_mise_guidance(*, indent: str = "") -> None:
    for line in MISE_SETTINGS_BLOCK.strip().splitlines():
        _echo(f"{indent}{line}")
    _echo()
    _echo(f"{indent}[env]")
    _echo(f"{indent}{SIVE_MISE_DIRECTIVE}")
    _echo()
