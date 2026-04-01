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
