"""macOS Keychain integration via the 'security' CLI."""

from __future__ import annotations

import base64
import subprocess

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


def store_secret(vault_name: str, account: str, value: str) -> None:
    """Store a secret in Keychain under (service, account). Overwrites any existing entry."""
    service = _service(vault_name)
    encoded_value = _encode_value(value)
    result = subprocess.run(
        # `man security`: -U updates an existing item. This avoids the old delete+add
        # sequence, which could leave setup half-broken when delete succeeded but add failed.
        # The CLI cannot read `-w` from stdin; without a value it prompts on /dev/tty.
        # Passing args as a list avoids shell expansion, but the encoded value is still
        # briefly visible to local process inspectors while the security command runs.
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
