"""Tests for source_loader.py — the core of the MVP data flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sive.core.source_loader import SourceError, load_source, load_sources

# ---------------------------------------------------------------------------
# Source string parsing
# ---------------------------------------------------------------------------


def test_invalid_source_format_raises():
    with pytest.raises(SourceError, match="Invalid source format"):
        load_source("not-valid")


def test_invalid_source_no_folder_type_raises():
    with pytest.raises(SourceError, match="Invalid source format"):
        load_source("personal:env/global")


def test_invalid_source_wrong_separator_raises():
    with pytest.raises(SourceError, match="Invalid source format"):
        load_source("personal/folder/env/global")


# ---------------------------------------------------------------------------
# Config error propagation
# ---------------------------------------------------------------------------


@patch("sive.core.source_loader.load_vault")
def test_missing_vault_config_raises_source_error(mock_load_vault):
    from sive.core.vaults import ConfigError

    mock_load_vault.side_effect = ConfigError("Vault not found")

    with pytest.raises(SourceError, match="Vault not found"):
        load_source("personal.folder:env/global")


@patch("sive.core.source_loader.load_vault")
@patch("sive.core.source_loader.get_password")
def test_missing_keychain_entry_raises_source_error(mock_get_password, mock_load_vault):
    from sive.core.keychain_macos import KeychainError
    from sive.core.vaults import VaultConfig

    mock_load_vault.return_value = VaultConfig(
        name="personal",
        server="https://vw.example.com",
        appdata_dir=Path("/tmp/sive-personal"),
    )
    mock_get_password.side_effect = KeychainError("not found in Keychain")

    with pytest.raises(SourceError, match="not found in Keychain"):
        load_source("personal.folder:env/global")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@patch("sive.core.source_loader.load_vault")
@patch("sive.core.source_loader.get_password")
@patch("sive.core.source_loader.unlock")
@patch("sive.core.source_loader.list_folders")
@patch("sive.core.source_loader.list_items_in_folder")
@patch("sive.core.source_loader.extract_env_vars")
def test_load_source_happy_path(
    mock_extract,
    mock_list_items,
    mock_list_folders,
    mock_unlock,
    mock_get_password,
    mock_load_vault,
):
    from sive.core.vaults import VaultConfig

    mock_load_vault.return_value = VaultConfig(
        name="personal",
        server="https://vw.example.com",
        appdata_dir=Path("/tmp/sive-personal"),
    )
    mock_get_password.return_value = "masterpass"
    mock_unlock.return_value = "session-token-abc"
    mock_list_folders.return_value = [{"id": "folder-1", "name": "env/global"}]
    mock_list_items.return_value = [{"type": 2, "name": "ANTHROPIC_API_KEY", "notes": "sk-xxx"}]
    mock_extract.return_value = {"ANTHROPIC_API_KEY": "sk-xxx"}

    result = load_source("personal.folder:env/global")

    assert result == {"ANTHROPIC_API_KEY": "sk-xxx"}
    mock_unlock.assert_called_once_with("masterpass", appdata_dir=str(Path("/tmp/sive-personal")))
    mock_list_folders.assert_called_once_with(
        "session-token-abc", appdata_dir=str(Path("/tmp/sive-personal"))
    )
    mock_list_items.assert_called_once_with(
        "folder-1",
        "session-token-abc",
        appdata_dir=str(Path("/tmp/sive-personal")),
    )


@patch("sive.core.source_loader.load_vault")
@patch("sive.core.source_loader.get_password")
@patch("sive.core.source_loader.list_folders")
@patch("sive.core.source_loader.list_items_in_folder")
@patch("sive.core.source_loader.extract_env_vars")
def test_load_source_uses_provided_session(
    mock_extract,
    mock_list_items,
    mock_list_folders,
    mock_get_password,
    mock_load_vault,
):
    """When a session key is already provided, keychain is not consulted."""
    from sive.core.vaults import VaultConfig

    mock_load_vault.return_value = VaultConfig(
        name="personal",
        server="https://vw.example.com",
        appdata_dir=Path("/tmp/sive-personal"),
    )
    mock_list_folders.return_value = [{"id": "folder-1", "name": "env/global"}]
    mock_list_items.return_value = []
    mock_extract.return_value = {}

    load_source("personal.folder:env/global", session_key="existing-session")

    mock_get_password.assert_not_called()
    mock_list_folders.assert_called_once_with(
        "existing-session", appdata_dir=str(Path("/tmp/sive-personal"))
    )


# ---------------------------------------------------------------------------
# list_folders failure
# ---------------------------------------------------------------------------


@patch("sive.core.source_loader.load_vault")
@patch("sive.core.source_loader.get_password")
@patch("sive.core.source_loader.unlock")
@patch("sive.core.source_loader.list_folders")
def test_list_folders_failure_raises_source_error(
    mock_list_folders,
    mock_unlock,
    mock_get_password,
    mock_load_vault,
):
    from sive.core.bw import BWError
    from sive.core.vaults import VaultConfig

    mock_load_vault.return_value = VaultConfig(
        name="personal",
        server="https://vw.example.com",
        appdata_dir=Path("/tmp/sive-personal"),
    )
    mock_get_password.return_value = "masterpass"
    mock_unlock.return_value = "session-abc"
    mock_list_folders.side_effect = BWError("connection refused")

    with pytest.raises(SourceError, match="bw list folders failed"):
        load_source("personal.folder:env/global")


# ---------------------------------------------------------------------------
# Folder not found
# ---------------------------------------------------------------------------


@patch("sive.core.source_loader.load_vault")
@patch("sive.core.source_loader.get_password")
@patch("sive.core.source_loader.unlock")
@patch("sive.core.source_loader.list_folders")
def test_missing_folder_raises_source_error(
    mock_list_folders,
    mock_unlock,
    mock_get_password,
    mock_load_vault,
):
    from sive.core.vaults import VaultConfig

    mock_load_vault.return_value = VaultConfig(
        name="personal",
        server="https://vw.example.com",
        appdata_dir=Path("/tmp/sive-personal"),
    )
    mock_get_password.return_value = "masterpass"
    mock_unlock.return_value = "session-abc"
    mock_list_folders.return_value = []

    with pytest.raises(SourceError, match="not found in vault"):
        load_source("personal.folder:env/global")


@patch("sive.core.source_loader.load_vault")
@patch("sive.core.source_loader.get_password")
@patch("sive.core.source_loader.unlock")
@patch("sive.core.source_loader.list_folders")
@patch("sive.core.source_loader.list_items_in_folder")
@patch("sive.core.source_loader.extract_env_vars")
def test_load_sources_groups_work_by_vault(
    mock_extract,
    mock_list_items,
    mock_list_folders,
    mock_unlock,
    mock_get_password,
    mock_load_vault,
):
    from sive.core.vaults import VaultConfig

    mock_load_vault.return_value = VaultConfig(
        name="personal",
        server="https://vw.example.com",
        appdata_dir=Path("/tmp/sive-personal"),
    )
    mock_get_password.return_value = "masterpass"
    mock_unlock.return_value = "session-token-abc"
    mock_list_folders.return_value = [
        {"id": "folder-global", "name": "env/global"},
        {"id": "folder-ai", "name": "env/ai"},
    ]
    mock_list_items.side_effect = [
        [{"id": "item-global"}],
        [{"id": "item-ai"}],
    ]
    mock_extract.side_effect = [
        {"SHARED": "global", "GLOBAL_ONLY": "1"},
        {"SHARED": "ai", "AI_ONLY": "1"},
    ]

    result = load_sources(["personal.folder:env/global", "personal.folder:env/ai"])

    assert result == {"SHARED": "ai", "GLOBAL_ONLY": "1", "AI_ONLY": "1"}
    mock_load_vault.assert_called_once_with("personal")
    mock_unlock.assert_called_once_with("masterpass", appdata_dir=str(Path("/tmp/sive-personal")))
    mock_list_folders.assert_called_once_with(
        "session-token-abc", appdata_dir=str(Path("/tmp/sive-personal"))
    )
    assert mock_list_items.call_args_list == [
        (
            ("folder-global", "session-token-abc"),
            {"appdata_dir": str(Path("/tmp/sive-personal"))},
        ),
        (
            ("folder-ai", "session-token-abc"),
            {"appdata_dir": str(Path("/tmp/sive-personal"))},
        ),
    ]


@patch("sive.core.source_loader._build_vault_context")
def test_load_sources_uses_vault_specific_session_keys(mock_build_context):
    from sive.core.source_loader import VaultContext

    mock_build_context.side_effect = [
        VaultContext(
            session="session-a", appdata_dir="/tmp/a", folder_ids={"env/global": "folder-a"}
        ),
        VaultContext(
            session="session-b", appdata_dir="/tmp/b", folder_ids={"env/global": "folder-b"}
        ),
    ]

    with (
        patch("sive.core.source_loader.list_items_in_folder", return_value=[]),
        patch("sive.core.source_loader.extract_env_vars", return_value={}),
    ):
        load_sources(
            ["personal.folder:env/global", "work.folder:env/global"],
            session_keys={"personal": "session-a", "work": "session-b"},
        )

    assert mock_build_context.call_args_list[0].kwargs["session_key"] == "session-a"
    assert mock_build_context.call_args_list[1].kwargs["session_key"] == "session-b"
