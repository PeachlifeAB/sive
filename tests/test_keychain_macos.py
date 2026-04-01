"""Tests for keychain_macos.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sive.core.keychain_macos import (
    KeychainError,
    delete_password,
    get_password,
    store_password,
)

# ---------------------------------------------------------------------------
# get_password
# ---------------------------------------------------------------------------


def test_get_password_returns_value_on_success():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "my-secret-password\n"

    with patch("subprocess.run", return_value=mock_result):
        result = get_password("personal")

    assert result == "my-secret-password"


def test_get_password_raises_keychain_error_when_not_found():
    mock_result = MagicMock()
    mock_result.returncode = 44  # security CLI not found exit code
    mock_result.stdout = ""

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(KeychainError, match="Keychain entry 'master_password'.*not found"):
            get_password("personal")


def test_get_password_strips_trailing_newline():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "password-with-newline\n"

    with patch("subprocess.run", return_value=mock_result):
        result = get_password("personal")

    assert result == "password-with-newline"


# ---------------------------------------------------------------------------
# store_password
# ---------------------------------------------------------------------------


def test_store_password_calls_security_add():
    delete_result = MagicMock(returncode=0)
    add_result = MagicMock(returncode=0, stderr="")

    with patch("subprocess.run", side_effect=[delete_result, add_result]) as mock_run:
        store_password("personal", "my-password")

    add_call = mock_run.call_args_list[1]
    cmd = add_call[0][0]
    assert "add-generic-password" in cmd
    assert "sive/personal" in cmd
    # The security CLI does not accept -w via stdin. The value must be passed inline.
    # See keychain_macos.py store_secret for the full explanation.
    assert "-w" in cmd
    assert cmd[cmd.index("-w") + 1] == "my-password"


def test_store_password_raises_on_failure():
    delete_result = MagicMock(returncode=0)
    add_result = MagicMock(returncode=1, stderr="SecKeychainItemAdd failed")

    with patch("subprocess.run", side_effect=[delete_result, add_result]):
        with pytest.raises(KeychainError, match="Failed to store 'master_password' in Keychain"):
            store_password("personal", "my-password")


# ---------------------------------------------------------------------------
# Service name format
# ---------------------------------------------------------------------------


def test_service_name_includes_vault_name():
    mock_result = MagicMock(returncode=0, stdout="pass\n")

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        get_password("work")

    cmd = mock_run.call_args[0][0]
    assert "sive/work" in cmd


def test_delete_password_is_best_effort_on_failure():
    mock_result = MagicMock(returncode=44)

    # Should not raise even if delete fails
    with patch("subprocess.run", return_value=mock_result):
        delete_password("personal")  # no exception
