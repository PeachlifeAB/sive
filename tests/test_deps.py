from __future__ import annotations

import subprocess
from unittest.mock import patch

from sive.core.ui import ensure_homebrew_command


def test_dependency_check_returns_true_when_command_exists():
    with patch("shutil.which", return_value="/opt/homebrew/bin/mise") as mock_which:
        assert ensure_homebrew_command("mise", "mise", "mise")

    mock_which.assert_called_once_with("mise")


def test_dependency_check_can_install_missing_command_with_homebrew(capsys):
    install_result = subprocess.CompletedProcess(["brew", "install", "mise"], 0)

    with (
        patch("shutil.which", side_effect=[None, "/opt/homebrew/bin/mise"]),
        patch("sive.core.ui.confirm", return_value=True) as mock_confirm,
        patch("subprocess.run", return_value=install_result) as mock_run,
    ):
        assert ensure_homebrew_command("mise", "mise", "mise")

    captured = capsys.readouterr()
    mock_confirm.assert_called_once_with("Install mise with Homebrew now?", default=True)
    mock_run.assert_called_once_with(["brew", "install", "mise"])
    assert "mise not found" in captured.out


def test_dependency_check_prints_manual_fallback_when_declined(capsys):
    with (
        patch("shutil.which", return_value=None),
        patch("sive.core.ui.confirm", return_value=False),
        patch("subprocess.run") as mock_run,
    ):
        assert not ensure_homebrew_command(
            "bw",
            "bitwarden-cli",
            "Bitwarden CLI ('bw')",
            fallback="npm install -g @bitwarden/cli",
        )

    captured = capsys.readouterr()
    mock_run.assert_not_called()
    assert "Install it: brew install bitwarden-cli" in captured.out
    assert "Or: npm install -g @bitwarden/cli" in captured.out
    assert "mise use -g" not in captured.out
