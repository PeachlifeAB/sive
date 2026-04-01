from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from sive.commands import setup


def test_setup_skip_keychain_still_patches_mise_config(capsys):
    from sive.core.vaults import VaultConfig

    version_result = subprocess.CompletedProcess(["bw", "--version"], 0, stdout="2026.2.0\n")

    with (
        patch("sive.commands.setup.subprocess.run", return_value=version_result) as mock_run,
        patch("sive.commands.setup.write_vault_stub") as mock_write_vault_stub,
        patch(
            "sive.commands.setup.load_vault",
            return_value=VaultConfig(
                name="personal",
                server="https://vw.example.com",
                appdata_dir=Path("/tmp/sive-personal"),
            ),
        ),
        patch("sive.commands.setup.set_server", return_value=False) as mock_set_server,
        patch(
            "sive.commands.setup.get_status",
            return_value={
                "status": "locked",
                "userEmail": "me@example.com",
                "serverUrl": "https://vw.example.com",
            },
        ),
        patch("sive.commands.setup._patch_mise_config") as mock_patch_mise_config,
        patch("sive.core.ui.style"),  # suppress styled output; not asserted
        patch("sive.core.ui.spin", side_effect=lambda _title, fn: fn()),  # transparent passthrough
        patch("sive.core.ui.input", side_effect=["https://vw.example.com", "me@example.com"]),
        patch("sive.core.ui.password", return_value="secret"),
        patch("sive.core.ui.confirm", return_value=False),
    ):
        exit_code = setup.run()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Setup complete. Open a new shell to activate sive." in captured.out
    mock_write_vault_stub.assert_called_once_with("personal", "https://vw.example.com")
    mock_set_server.assert_called_once_with(
        "https://vw.example.com",
        status={
            "status": "locked",
            "userEmail": "me@example.com",
            "serverUrl": "https://vw.example.com",
        },
        appdata_dir="/tmp/sive-personal",
    )
    mock_patch_mise_config.assert_called_once_with()
    mock_run.assert_called_once_with(["bw", "--version"], capture_output=True, text=True)


def test_patch_mise_config_conflict_guidance_includes_cache_settings(tmp_path, capsys):
    config_dir = tmp_path / "mise"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text("[settings]\nlegacy = true\n")

    with (
        patch.object(setup, "MISE_CONFIG_DIR", config_dir),
        patch.object(setup, "GLOBAL_MISE_CONFIG", config_file),
    ):
        setup._patch_mise_config()

    captured = capsys.readouterr()
    assert "Cannot safely patch" in captured.out
    assert "[settings]" in captured.out
    assert "env_cache = false" in captured.out
    assert "[env]" in captured.out
    assert setup.SIVE_MISE_DIRECTIVE in captured.out


def test_run_project_setup_writes_dot_sive(capsys):
    with (
        patch("sive.commands.setup._bootstrap_ready", return_value=True),
        patch("sive.commands.setup.write_project_config") as mock_write,
        patch("sive.core.snapshot_crypto.ensure_key") as mock_ensure_key,
        patch("sive.core.ui.style"),  # suppress styled output; not asserted
        patch("sive.core.ui.spin", side_effect=lambda _title, fn: fn()),  # transparent passthrough
    ):
        exit_code = setup.run_project_setup(tags=["projectX"], no_global=False)

    captured = capsys.readouterr()
    assert exit_code == 0
    mock_write.assert_called_once_with(["global", "projectX"], vault="personal")
    mock_ensure_key.assert_any_call("personal", "global")
    mock_ensure_key.assert_any_call("personal", "projectX")
    assert "This directory is now configured for tags: global, projectX" in captured.out
