"""macOS Keychain integration via the 'security' CLI."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

SERVICE_PREFIX = "sive"
_VALUE_PREFIX = "sive1:"


class KeychainError(Exception):
    pass


def _service(vault_name: str) -> str:
    return f"{SERVICE_PREFIX}/{vault_name}"


def _friendly_account(account: str) -> str:
    if account == "master_password":
        return "master password"
    if account == "email":
        return "email address"
    return account.replace("_", " ")


def _encode_value(value: str) -> str:
    encoded = base64.b64encode(value.encode()).decode("ascii")
    return f"{_VALUE_PREFIX}{encoded}"


def _decode_value(value: str) -> str:
    if not value.startswith(_VALUE_PREFIX):
        return value
    encoded = value.removeprefix(_VALUE_PREFIX)
    return base64.b64decode(encoded.encode("ascii")).decode()


def _sanitize_security_error(stderr: str) -> str:
    raw = stderr.strip()
    if not raw:
        return "macOS Keychain did not provide an error message."
    if "what a shameful experience" in raw:
        return "macOS returned a generic SecKeychain error."
    return raw


def _store_error(vault_name: str, account: str, stderr: str) -> KeychainError:
    secret_name = _friendly_account(account)
    details = _sanitize_security_error(stderr)
    return KeychainError(
        f"Could not save the {secret_name} in macOS Keychain.\n"
        f"\n"
        f"Vault: {vault_name}\n"
        f"Keychain item: {SERVICE_PREFIX}/{vault_name} / {account}\n"
        f"\n"
        f"Try this and run setup again:\n"
        f"  1. Open Keychain Access and unlock the login keychain.\n"
        f"  2. Or run: security unlock-keychain ~/Library/Keychains/login.keychain-db\n"
        f"  3. If the item exists but is broken, delete '{SERVICE_PREFIX}/{vault_name}' "
        f"entries in Keychain Access.\n"
        f"\n"
        f"Keychain said: {details}"
    )


def _add_generic_password(
    service: str, account: str, encoded_value: str
) -> subprocess.CompletedProcess:
    # `man security`: -U updates an existing item in place, avoiding a delete+add
    # sequence that could leave setup half-broken when delete succeeds but add fails.
    # The CLI cannot read `-w` from stdin; without a value it prompts on /dev/tty, so
    # the encoded value is passed as an arg. Args are a list to avoid shell expansion;
    # the value is still briefly visible to local process inspectors while it runs.
    return subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            service,
            "-a",
            account,
            "-w",
            encoded_value,
        ],
        capture_output=True,
        text=True,
    )


def _is_locked_keychain_error(stderr: str) -> bool:
    compact = stderr.lower().replace(" ", "").replace("-", "")
    return (
        "userinteractionisnotallowed" in compact
        or "interactionnotallowed" in compact
        or "could not be opened" in stderr.lower()
    )


def _unlock_login_keychain() -> bool:
    """Offer to unlock the login keychain and do so when the user consents.

    Returns True only when the keychain is unlocked afterward. ``security
    unlock-keychain`` inherits the tty so macOS prompts for the keychain password on
    stdin — works in a local terminal and over SSH when a tty is present.
    """
    from . import ui  # lazy import: ui imports no core modules, so no load-time cycle

    keychain = Path.home() / "Library" / "Keychains" / "login.keychain-db"
    if not keychain.exists():
        return False
    if not ui.confirm(
        "macOS Keychain is locked, so sive cannot store credentials. "
        "Unlock the login keychain now?",
        default=True,
    ):
        return False
    return (
        subprocess.run(
            ["security", "unlock-keychain", str(keychain)],
            check=False,
        ).returncode
        == 0
    )


def store_secret(vault_name: str, account: str, value: str) -> None:
    """Store a secret in Keychain under (service, account). Overwrites any existing entry."""
    service = _service(vault_name)
    encoded_value = _encode_value(value)
    result = _add_generic_password(service, account, encoded_value)
    if result.returncode != 0 and _is_locked_keychain_error(result.stderr):
        # Root-cause self-heal: a locked login keychain (or a non-GUI session) rejects
        # writes with "User interaction is not allowed". Unlock once and retry before
        # surfacing an error to the user.
        if _unlock_login_keychain():
            result = _add_generic_password(service, account, encoded_value)
    if result.returncode != 0:
        raise _store_error(vault_name, account, result.stderr)


def get_secret(vault_name: str, account: str, *, missing_hint: str = "") -> str:
    """Retrieve a secret from Keychain. Raises KeychainError if not found."""
    service = _service(vault_name)
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        hint = missing_hint or "Run 'sive setup' to store it."
        raise KeychainError(
            f"Keychain entry '{account}' for vault '{vault_name}' not found.\n{hint}"
        )
    return _decode_value(result.stdout.strip())


def delete_secret(vault_name: str, account: str) -> None:
    """Remove a secret from Keychain (best-effort)."""
    service = _service(vault_name)
    subprocess.run(
        ["security", "delete-generic-password", "-s", service, "-a", account],
        capture_output=True,
    )


_MASTER_PASSWORD_ACCOUNT = "master_password"


def store_password(vault_name: str, password: str) -> None:
    """Store master password in Keychain."""
    store_secret(vault_name, _MASTER_PASSWORD_ACCOUNT, password)


def get_password(vault_name: str) -> str:
    """Retrieve master password from Keychain. Raises KeychainError if not found."""
    return get_secret(
        vault_name,
        _MASTER_PASSWORD_ACCOUNT,
        missing_hint="Run 'sive setup' to store it.",
    )


def delete_password(vault_name: str) -> None:
    """Remove master password from Keychain (best-effort)."""
    delete_secret(vault_name, _MASTER_PASSWORD_ACCOUNT)


_EMAIL_ACCOUNT = "email"


def store_email(vault_name: str, email: str) -> None:
    store_secret(vault_name, _EMAIL_ACCOUNT, email)


def get_email(vault_name: str) -> str | None:
    try:
        return get_secret(vault_name, _EMAIL_ACCOUNT)
    except KeychainError:
        return None
