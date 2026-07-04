from __future__ import annotations

from unittest.mock import patch

import pytest

from sive.commands.refresh import _tag_from_source, run


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("personal.folder:env/global", "global"),
        (" personal.folder:env/ai ", "ai"),
        ("env/projectX", "projectX"),
    ],
)
def test_tag_from_source_returns_non_empty_tag(source, expected):
    assert _tag_from_source(source) == expected


@pytest.mark.parametrize("source", ["", "   ", "personal.folder:env/", "env/"])
def test_tag_from_source_rejects_invalid_source(source):
    with pytest.raises(ValueError):
        _tag_from_source(source)


def test_tag_from_source_rejects_missing_separator():
    with pytest.raises(ValueError):
        _tag_from_source("global")


def test_refresh_continues_after_invalid_source(capsys):
    with (
        patch("sive.commands.refresh.ensure_key") as mock_key,
        patch("sive.commands.refresh.load_source", return_value={"A": "1"}),
        patch("sive.commands.refresh.write_snapshot"),
    ):
        exit_code = run(vault_name="personal", sources=["global", "personal.folder:env/test"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "invalid source 'global'" in captured.err
    mock_key.assert_called_once_with("personal", "test")


def test_refresh_reuses_caller_session_key_without_reunlocking(tmp_path):
    """A caller-supplied session_key must flow to sync() and load_source() as-is —
    deriving a second unlock for the same appdata dir invalidates the caller's
    own session key on disk (each `bw unlock` overwrites the vault's active key
    material), which is exactly what broke `sive setup`'s post-login tag fetch."""
    from sive.core.vaults import VaultConfig

    vault = VaultConfig(name="personal", server="https://vw.example.com", appdata_dir=tmp_path)

    with (
        patch("sive.core.vaults.load_vault", return_value=vault),
        patch("sive.commands.refresh.sync") as mock_sync,
        patch("sive.commands.refresh.ensure_key"),
        patch("sive.commands.refresh.load_source", return_value={}) as mock_load_source,
        patch("sive.commands.refresh.write_snapshot"),
        patch(
            "sive.commands.refresh._ensure_session", return_value="caller-session"
        ) as mock_ensure,
    ):
        exit_code = run(
            vault_name="personal",
            sources=["personal.folder:env/global"],
            session_key="caller-session",
        )

    assert exit_code == 0
    mock_ensure.assert_called_once_with("personal", "caller-session", appdata_dir=str(tmp_path))
    mock_sync.assert_called_once_with("caller-session", appdata_dir=str(tmp_path))
    mock_load_source.assert_called_once_with(
        "personal.folder:env/global", session_key="caller-session"
    )
