"""Tests for deleting Sive secrets through the vault trash flow."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from sive.commands.set_secret import run
from sive.core.bw import BWError, delete_item


@pytest.fixture
def vault_config() -> MagicMock:
    vault = MagicMock()
    vault.appdata_dir = "/tmp/bw"
    return vault


def _delete_patches(vault_config: MagicMock):
    return (
        patch("sive.commands.set_secret.load_vault", return_value=vault_config),
        patch("sive.commands.set_secret._ensure_session", return_value="session"),
        patch(
            "sive.commands.set_secret.list_folders",
            return_value=[{"id": "folder", "name": "env/prod"}],
        ),
        patch(
            "sive.commands.set_secret.list_items_in_folder",
            return_value=[{"id": "item", "name": "API_KEY", "type": 2}],
        ),
        patch("sive.commands.set_secret.delete_item"),
        patch("sive.commands.set_secret.ensure_key"),
        patch("sive.commands.set_secret.load_source", return_value={}),
        patch("sive.commands.set_secret.write_snapshot"),
    )


def test_delete_moves_exact_secure_note_to_trash_and_refreshes_snapshot(
    vault_config: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    patches = _delete_patches(vault_config)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4] as delete,
        patches[5],
        patches[6],
        patches[7],
    ):
        assert run("API_KEY", tag="prod", vault_name="personal", delete=True) == 0

    delete.assert_called_once_with("item", "session", appdata_dir="/tmp/bw")
    captured = capsys.readouterr()
    assert "Deleted API_KEY from tag: prod" in captured.out
    assert captured.err == ""


def test_delete_requires_active_project_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch("sive.commands.set_secret.read_project_tags", return_value=[]),
        patch("sive.commands.set_secret.load_vault") as load_vault,
    ):
        assert run("API_KEY", delete=True) == 1

    load_vault.assert_not_called()
    assert "run `sive setup` or provide `--tag`" in capsys.readouterr().err


def test_delete_uses_active_project_context(vault_config: MagicMock) -> None:
    patches = _delete_patches(vault_config)
    with (
        patches[0],
        patches[1],
        patch("sive.commands.set_secret.read_project_vault", return_value="work"),
        patch("sive.commands.set_secret.read_project_tags", return_value=["global", "prod"]),
        patches[2],
        patches[3],
        patches[4] as delete,
        patches[5],
        patches[6],
        patches[7],
    ):
        assert run("API_KEY", vault_name="personal", delete=True) == 0

    delete.assert_called_once_with("item", "session", appdata_dir="/tmp/bw")


def test_delete_requires_existing_folder_and_key(vault_config: MagicMock) -> None:
    with (
        patch("sive.commands.set_secret.load_vault", return_value=vault_config),
        patch("sive.commands.set_secret._ensure_session", return_value="session"),
        patch("sive.commands.set_secret.list_folders", return_value=[]),
        patch("sive.commands.set_secret.create_folder") as create_folder,
        patch("sive.commands.set_secret.delete_item") as delete,
    ):
        assert run("MISSING", tag="prod", delete=True) == 1

    create_folder.assert_not_called()
    delete.assert_not_called()


def test_delete_rejects_duplicate_matching_notes(vault_config: MagicMock) -> None:
    with (
        patch("sive.commands.set_secret.load_vault", return_value=vault_config),
        patch("sive.commands.set_secret._ensure_session", return_value="session"),
        patch(
            "sive.commands.set_secret.list_folders",
            return_value=[{"id": "folder", "name": "env/prod"}],
        ),
        patch(
            "sive.commands.set_secret.list_items_in_folder",
            return_value=[
                {"id": "one", "name": "API_KEY", "type": 2},
                {"id": "two", "name": "API_KEY", "type": 2},
            ],
        ),
        patch("sive.commands.set_secret.delete_item") as delete,
    ):
        assert run("API_KEY", tag="prod", delete=True) == 1

    delete.assert_not_called()


def test_delete_reports_stale_snapshot_after_success(
    vault_config: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    patches = _delete_patches(vault_config)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patch("sive.commands.set_secret.load_source", side_effect=RuntimeError("refresh failed")),
        patches[7],
    ):
        assert run("API_KEY", tag="prod", delete=True) == 0

    captured = capsys.readouterr()
    assert "Deleted API_KEY from tag: prod" in captured.out
    assert "deleted from vault but local snapshot is not yet updated" in captured.err


def test_delete_returns_vault_error(vault_config: MagicMock) -> None:
    with (
        patch("sive.commands.set_secret.load_vault", return_value=vault_config),
        patch("sive.commands.set_secret._ensure_session", return_value="session"),
        patch("sive.commands.set_secret.list_folders", side_effect=BWError("vault unavailable")),
    ):
        assert run("API_KEY", tag="prod", delete=True) == 1


def test_delete_item_uses_bitwarden_delete_command() -> None:
    with patch("sive.core.bw._run") as command:
        delete_item("item", "session", appdata_dir="/tmp/bw")

    command.assert_called_once_with(
        ["delete", "item", "item", "--session", "session"], appdata_dir="/tmp/bw"
    )


def test_delete_alias_delegates_to_set_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    from sive import cli

    monkeypatch.setattr(sys, "argv", ["sive", "delete", "API_KEY", "--tag", "prod"])
    with (
        patch("sive.commands.set_secret.run", return_value=0) as command,
        pytest.raises(SystemExit) as exc,
    ):
        cli._main()

    assert exc.value.code == 0
    command.assert_called_once_with("API_KEY", tag="prod", vault_name="personal", delete=True)


def test_set_delete_rejects_stdin_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sive import cli

    monkeypatch.setattr(sys, "argv", ["sive", "set", "API_KEY", "--delete", "--stdin"])
    with pytest.raises(SystemExit) as exc:
        cli._main()

    assert exc.value.code == 1
    assert "does not accept a value" in capsys.readouterr().err


def test_set_delete_rejects_value_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sive import cli

    monkeypatch.setattr(sys, "argv", ["sive", "set", "API_KEY", "secret", "--delete"])
    with pytest.raises(SystemExit) as exc:
        cli._main()

    assert exc.value.code == 1
    assert "does not accept a value" in capsys.readouterr().err
