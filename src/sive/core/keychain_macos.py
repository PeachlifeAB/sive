"""macOS Keychain integration via the 'security' CLI."""

from __future__ import annotations

import subprocess

SERVICE_PREFIX = "sive"


class KeychainError(Exception):
    pass


def _service(vault_name: str) -> str:
    return f"{SERVICE_PREFIX}/{vault_name}"


def store_secret(vault_name: str, account: str, value: str) -> None:
    """Store a secret in Keychain under (service, account). Overwrites any existing entry."""
    service = _service(vault_name)
    subprocess.run(
        ["security", "delete-generic-password", "-s", service, "-a", account],
        capture_output=True,
    )
    result = subprocess.run(
        # The `security` CLI reads the password from /dev/tty directly when `-w` is the
        # last argument with no value — it does NOT read from stdin. Passing `input=value`
        # via subprocess stores an empty string. The inline `-w <value>` form is the only
        # form that works with this CLI.
        # Known limitation: the value appears in `ps aux` for the duration of this call.
        # Future hardening: replace with a library that calls the Keychain API directly
        # (e.g. keyring, or ctypes against Security.framework) to avoid any CLI exposure.
        ["security", "add-generic-password", "-s", service, "-a", account, "-w", value],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise KeychainError(f"Failed to store '{account}' in Keychain: {result.stderr.strip()}")


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
    return result.stdout.strip()


def delete_secret(vault_name: str, account: str) -> None:
    """Remove a secret from Keychain (best-effort)."""
    service = _service(vault_name)
    subprocess.run(
        ["security", "delete-generic-password", "-s", service, "-a", account],
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Convenience wrappers for the master password account
# ---------------------------------------------------------------------------

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
