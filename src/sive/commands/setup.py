"""sive login / sive setup — vault authentication and project configuration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..core import ui
from ..core.bw import BWError, get_status, list_env_tags, set_server, unlock
from ..core.keychain_macos import KeychainError, store_email, store_password
from ..core.keychain_macos import get_email as get_stored_email
from ..core.keychain_macos import get_password as get_stored_password
from ..core.project_config import write_project_config
from ..core.sync_state import load_known_tags
from ..core.vaults import CONFIG_DIR, VAULTS_TOML, ConfigError, load_vault, write_vault_stub

MISE_CONFIG_DIR = Path.home() / ".config" / "mise"
GLOBAL_MISE_CONFIG = MISE_CONFIG_DIR / "config.toml"

SIVE_MISE_DIRECTIVE = "_.sive = {}"
MISE_SETTINGS_BLOCK = """[settings]
env_cache = false
"""

MISE_ENV_BLOCK = f"""
[tools]
"npm:@bitwarden/cli" = "latest"

{MISE_SETTINGS_BLOCK.strip()}

[env]
{SIVE_MISE_DIRECTIVE}
"""


def run() -> int:
    # Called only by tests. Not registered as a public CLI command.
    rc, _, _ = _run_login()
    return rc


def _run_login() -> tuple[int, str | None, str | None]:
    """Run vault login flow. Returns (exit_code, session_key, appdata_dir)."""
    ui.style("sive setup", bold=True, foreground="#FAFAFA", background="#7D56F4", padding="0 1")
    print()

    # Step 1: Check bw is installed
    print("Checking for bw CLI...")
    try:
        result = subprocess.run(["bw", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  bw {result.stdout.strip()} found.")
        else:
            _print_bw_install_hint()
            return 1, None, None
    except FileNotFoundError:
        _print_bw_install_hint()
        return 1, None, None

    # Step 2: Ensure vaults.toml exists — but don't overwrite existing
    vault_name = "personal"
    if not VAULTS_TOML.exists():
        print(f"\nCreating {VAULTS_TOML} ...")
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Step 3: Prompt for server URL — always required, no default
    print(f"\nConfigure vault '{vault_name}':")
    server_url = ""
    while not server_url:
        server_url = ui.input("Server URL", placeholder="https://vw.yourdomain.com")
        if not server_url:
            print("  Server URL is required.")

    # Write/update vaults.toml
    write_vault_stub(vault_name, server_url)
    print(f"  Written to {VAULTS_TOML}")

    vault = load_vault(vault_name)
    appdata_dir = str(vault.appdata_dir)
    status = ui.spin("Checking vault status...", lambda: _get_status_or_empty(appdata_dir))

    try:
        server_changed = ui.spin(
            f"Configuring bw to use {server_url} ...",
            lambda: set_server(server_url, status=status, appdata_dir=appdata_dir),
        )
    except BWError as e:
        print(f"  Error: {e}", file=sys.stderr)
        return 1, None, None

    if server_changed:
        status = {}

    print("\nLogging in to Bitwarden...")
    email = ui.input("Email")
    master_password = ui.password("Master password")

    bw_status = status.get("status", "unauthenticated")
    bw_email = status.get("userEmail", "")

    if bw_status in ("locked", "unlocked"):
        if bw_email.lower() == email.lower():
            print(f"  Already logged in as {bw_email}.")
        else:
            print(
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
            print("  Login failed.", file=sys.stderr)
            return 1, None, None
        print("  Logged in.")

    if not ui.confirm("Store master password in macOS Keychain for silent unlock?"):
        print("  Skipped. Silent unlock will not work without a stored password.")
        _patch_mise_config()
        print("\nSetup complete. Open a new shell to activate sive.")
        return 0, None, None

    try:
        session_key = ui.spin("Validating unlock...", lambda: unlock(master_password, appdata_dir=appdata_dir))
    except BWError as e:
        print(f"  Unlock failed: {e}", file=sys.stderr)
        print("  Master password NOT stored. Re-run 'sive setup' to retry.")
        return 1, None, None

    try:
        store_password(vault_name, master_password)
        store_email(vault_name, email)
    except KeychainError as e:
        print(f"  Failed to store credentials in Keychain: {e}", file=sys.stderr)
        return 1, None, None
    print("  Credentials stored in Keychain.")

    from ..core.snapshot_crypto import ensure_key

    ui.spin("Ensuring snapshot encryption key...", lambda: ensure_key(vault_name, "global"))
    print("  Snapshot key ready in Keychain.")

    from .refresh import run as run_refresh

    if ui.spin("Running initial refresh...", lambda: run_refresh(vault_name=vault_name)) != 0:
        print("  Warning: initial refresh failed — run 'sive refresh' manually.", file=sys.stderr)

    _patch_mise_config()

    print("\nSetup complete. Open a new shell to activate sive.")
    return 0, session_key, appdata_dir


def run_project_setup(tags: list[str] | None = None, no_global: bool = False) -> int:
    ui.style("sive setup", bold=True, foreground="#FAFAFA", background="#7D56F4", padding="0 1")
    print()

    login_session: tuple[str, str] | None = None
    if not _bootstrap_ready():
        print("Sive needs to connect this Mac to your vault first.\n")
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
                    print(f"\n  Warning: could not load tags from vault ({e})", file=sys.stderr)
                    return []
            available = ui.spin("Loading tags from vault...", _fetch)
        if available:
            tags = ui.choose("Select project tags", available)
            if not tags:
                print("  No tags selected. Aborted.", file=sys.stderr)
                return 1
        else:
            raw = ui.input("Project tag(s) to load", placeholder="e.g. myproject")
            if not raw:
                print("  No tags entered. Aborted.", file=sys.stderr)
                return 1
            tags = [t.strip() for t in raw.replace(",", " ").split() if t.strip()]

    if not tags:
        print("  No tags provided.", file=sys.stderr)
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
            print(f"  Warning: could not create snapshot key for tag '{tag}': {e}", file=sys.stderr)

    write_project_config(tags, vault=vault_name)
    tag_list = ", ".join(tags)
    print(f"\n  This directory is now configured for tags: {tag_list}")
    print("  Secrets will be available automatically in new shells.")
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
        print(f"  Warning: silent unlock failed ({e})", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Warning: unexpected error during unlock ({e})", file=sys.stderr)
        return None


def run_relogin(vault_name: str = "personal") -> tuple[int, str | None, str | None]:
    """Re-authenticate an already-configured vault. Returns (exit_code, session_key, appdata_dir)."""
    try:
        vault = load_vault(vault_name)
    except ConfigError as e:
        print(f"sive: {e}", file=sys.stderr)
        return 1, None, None

    appdata_dir = str(vault.appdata_dir)
    status = _get_status_or_empty(appdata_dir)

    try:
        set_server(vault.server, status=status, appdata_dir=appdata_dir)
    except BWError as e:
        print(f"sive: {e}", file=sys.stderr)
        return 1, None, None

    bw_status = status.get("status", "unauthenticated")
    bw_email = status.get("userEmail", "")

    print("Vault session expired. Please log in again.")
    stored_email = get_stored_email(vault_name)
    email = stored_email or bw_email
    if not email:
        email = ui.input("Email")
    else:
        print(f"  Email: {email}")
    master_password = ui.password("Master password")

    if bw_status in ("locked", "unlocked"):
        if bw_email.lower() != email.lower():
            print(
                f"sive: already logged in as {bw_email}. Run "
                f"'BITWARDENCLI_APPDATA_DIR={appdata_dir} bw logout' to switch.",
                file=sys.stderr,
            )
            return 1, None, None
    else:
        env = {**os.environ, "SIVE_BW_PASSWORD": master_password, "BITWARDENCLI_APPDATA_DIR": appdata_dir}
        rc = ui.spin("Logging in...", lambda: subprocess.run(
            ["bw", "login", email, "--passwordenv", "SIVE_BW_PASSWORD"],
            env=env, capture_output=True,
        ).returncode)
        if rc != 0:
            print("sive: login failed.", file=sys.stderr)
            return 1, None, None

    try:
        session_key = ui.spin("Unlocking...", lambda: unlock(master_password, appdata_dir=appdata_dir))
    except BWError as e:
        print(f"sive: unlock failed: {e}", file=sys.stderr)
        return 1, None, None

    try:
        store_password(vault_name, master_password)
        store_email(vault_name, email)
    except KeychainError as e:
        print(f"sive: failed to store credentials in Keychain: {e}", file=sys.stderr)
        return 1, None, None

    print("  Logged in and keychain updated.")
    return 0, session_key, appdata_dir


def _bootstrap_ready() -> bool:
    try:
        vault = load_vault("personal")
        get_stored_password("personal")
        status = _get_status_or_empty(str(vault.appdata_dir))
        return status.get("status") in ("locked", "unlocked")
    except (ConfigError, KeychainError):
        return False


def _print_bw_install_hint() -> None:
    print("  'bw' CLI not found.", file=sys.stderr)
    print('  Install it: mise use -g "npm:@bitwarden/cli@latest"', file=sys.stderr)


def _patch_mise_config() -> None:
    """Add sive env directive to global mise config if not already present."""
    MISE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if GLOBAL_MISE_CONFIG.exists():
        content = GLOBAL_MISE_CONFIG.read_text()
        if "_.sive" in content:
            if SIVE_MISE_DIRECTIVE in content:
                normalized = content.replace("env_cache = true", "env_cache = false")
                normalized = normalized.replace('env_cache_ttl = "15m"\n', "")
                if normalized != content:
                    GLOBAL_MISE_CONFIG.write_text(normalized)
                    print(f"\nUpdated sive config in {GLOBAL_MISE_CONFIG} ...")
                    print("  Done.")
                    return
                return  # already configured, nothing to do
            import re

            updated = re.sub(r"_.sive\s*=\s*\{[^\n]*\}", SIVE_MISE_DIRECTIVE, content)
            updated = updated.replace("env_cache = true", "env_cache = false")
            updated = updated.replace('env_cache_ttl = "15m"\n', "")
            GLOBAL_MISE_CONFIG.write_text(updated)
            print(f"\nUpdated sive config in {GLOBAL_MISE_CONFIG} ...")
            print("  Done.")
            return
        # If any conflicting sections exist, do not blindly append —
        # duplicate TOML sections produce invalid or conflicting config.
        conflicting = [s for s in ("[tools]", "[settings]", "[env]") if s in content]
        if conflicting:
            print(f"\nCannot safely patch {GLOBAL_MISE_CONFIG}")
            print(f"  Existing sections that would conflict: {', '.join(conflicting)}")
            print("  Add this manually to your mise config:\n")
            _print_manual_mise_guidance(indent="  ")
            return
        print(f"\nPatching {GLOBAL_MISE_CONFIG} ...")
        with open(GLOBAL_MISE_CONFIG, "a") as f:
            f.write(f"\n[env]\n{SIVE_MISE_DIRECTIVE}\n")
    else:
        print(f"\nCreating {GLOBAL_MISE_CONFIG} ...")
        GLOBAL_MISE_CONFIG.write_text(MISE_ENV_BLOCK.strip() + "\n")

    print("  Done.")


def _get_status_or_empty(appdata_dir: str) -> dict[str, str]:
    try:
        return get_status(appdata_dir=appdata_dir)
    except BWError:
        return {}


def _print_manual_mise_guidance(*, indent: str = "") -> None:
    for line in MISE_SETTINGS_BLOCK.strip().splitlines():
        print(f"{indent}{line}")
    print()
    print(f"{indent}[env]")
    print(f"{indent}{SIVE_MISE_DIRECTIVE}")
    print()
