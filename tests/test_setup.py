from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sive.commands import setup


def test_setup_skip_keychain_still_patches_mise_config(capsys):
    from sive.core.vaults import VaultConfig

    with (
        patch("sive.commands.setup.ensure_bw_cli", return_value=True) as mock_ensure_bw_cli,
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
        # Vault is pre-configured (load_vault succeeds) so server URL is reused, not re-prompted.
        patch("sive.core.ui.input", side_effect=["me@example.com"]),
        patch("sive.core.ui.password", return_value="secret"),
        patch("sive.core.ui.confirm", return_value=False),
    ):
        exit_code = setup.run()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Setup complete. Open a new shell to activate sive." in captured.out
    # Already configured — vaults.toml must not be rewritten on a repeat setup.
    mock_write_vault_stub.assert_not_called()
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
    mock_ensure_bw_cli.assert_called_once_with()


def test_run_login_passes_own_session_key_to_refresh():
    """_run_login must hand refresh its own session_key rather than letting
    refresh derive a fresh unlock — a second unlock for the same appdata dir
    overwrites the vault's active key material and invalidates the first
    session, breaking anything downstream (e.g. run_project_setup's tag fetch)
    that still expects the login's session key to be valid."""
    from sive.core.vaults import VaultConfig

    with (
        patch("sive.commands.setup.ensure_bw_cli", return_value=True),
        patch("sive.commands.setup.write_vault_stub"),
        patch(
            "sive.commands.setup.load_vault",
            return_value=VaultConfig(
                name="personal",
                server="https://vw.example.com",
                appdata_dir=Path("/tmp/sive-personal"),
            ),
        ),
        patch("sive.commands.setup.set_server", return_value=False),
        patch(
            "sive.commands.setup.get_status",
            return_value={"status": "locked", "userEmail": "me@example.com"},
        ),
        patch("sive.commands.setup.unlock", return_value="the-session-key"),
        patch("sive.commands.setup.store_password"),
        patch("sive.commands.setup.store_email"),
        patch("sive.core.snapshot_crypto.ensure_key"),
        patch("sive.commands.refresh.run", return_value=0) as mock_run_refresh,
        patch("sive.commands.setup._patch_mise_config"),
        patch("sive.core.ui.style"),
        patch("sive.core.ui.spin", side_effect=lambda _title, fn: fn()),
        patch("sive.core.ui.input", side_effect=["me@example.com"]),
        patch("sive.core.ui.password", return_value="secret"),
        patch("sive.core.ui.confirm", return_value=True),
    ):
        exit_code = setup.run()

    assert exit_code == 0
    mock_run_refresh.assert_called_once_with(vault_name="personal", session_key="the-session-key")


def test_setup_idempotent_when_already_unlocked_and_password_stored(capsys):
    """Repeat setup with bw unlocked + password stored: zero prompts, just mise config."""
    from sive.core.vaults import VaultConfig

    with (
        patch("sive.commands.setup.ensure_bw_cli", return_value=True),
        patch(
            "sive.commands.setup.load_vault",
            return_value=VaultConfig(
                name="personal",
                server="https://vw.example.com",
                appdata_dir=Path("/tmp/sive-personal"),
            ),
        ),
        patch(
            "sive.commands.setup.get_status",
            return_value={"status": "unlocked", "userEmail": "me@example.com"},
        ),
        patch("sive.commands.setup._has_stored_password", return_value=True),
        patch("sive.commands.setup._patch_mise_config") as mock_patch_mise_config,
        patch("sive.commands.setup.write_vault_stub") as mock_write_vault_stub,
        patch("sive.commands.setup.set_server") as mock_set_server,
        patch("sive.core.ui.style"),
        patch("sive.core.ui.spin", side_effect=lambda _title, fn: fn()),
        patch("sive.core.ui.input") as mock_input,
        patch("sive.core.ui.password") as mock_password,
    ):
        exit_code = setup.run()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "already set up" in captured.out.lower()
    mock_patch_mise_config.assert_called_once_with()
    # Idempotent: nothing to authenticate, so no prompts, no re-write, no re-server.
    mock_input.assert_not_called()
    mock_password.assert_not_called()
    mock_write_vault_stub.assert_not_called()
    mock_set_server.assert_not_called()


def test_patch_mise_config_creates_only_sive_mise_hook_without_bw_tool(tmp_path):
    config_dir = tmp_path / "mise"
    config_file = config_dir / "config.toml"

    with (
        patch.object(setup, "MISE_CONFIG_DIR", config_dir),
        patch.object(setup, "GLOBAL_MISE_CONFIG", config_file),
        patch("sive.core.ui.ensure_homebrew_command", return_value=True),
        patch.object(setup, "_materialize_mise_hook_script", return_value=setup.SIVE_HOOK_SCRIPT),
    ):
        setup._patch_mise_config()

    content = config_file.read_text()
    assert "[settings]" in content
    assert "env_cache = false" in content
    assert "[env]" in content
    assert setup.SIVE_MISE_DIRECTIVE in content
    assert "[tools]" not in content
    assert "bitwarden" not in content.lower()
    assert "_.sive" not in content


def test_patch_mise_config_merges_into_existing_settings_and_env(tmp_path):
    """A pre-existing [settings]/[env] with unrelated keys gets the sive hook
    merged in, not refused — the user should never have to hand-edit TOML."""
    config_dir = tmp_path / "mise"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text('[settings]\nlegacy = true\n\n[env]\nMY_VAR = "keep-me"\n')

    with (
        patch.object(setup, "MISE_CONFIG_DIR", config_dir),
        patch.object(setup, "GLOBAL_MISE_CONFIG", config_file),
        patch("sive.core.ui.ensure_homebrew_command", return_value=True),
        patch.object(setup, "_materialize_mise_hook_script", return_value=setup.SIVE_HOOK_SCRIPT),
    ):
        setup._patch_mise_config()

    content = config_file.read_text()
    assert "legacy = true" in content
    assert 'MY_VAR = "keep-me"' in content
    assert "env_cache = false" in content
    assert setup.SIVE_MISE_DIRECTIVE in content
    assert content.count("[settings]") == 1
    assert content.count("[env]") == 1


def test_patch_mise_config_skips_directive_when_hook_script_missing(tmp_path, capsys):
    """The `_.source` directive is unsafe without the script it points at — never write it then."""
    config_dir = tmp_path / "mise"
    config_file = config_dir / "config.toml"

    with (
        patch.object(setup, "MISE_CONFIG_DIR", config_dir),
        patch.object(setup, "GLOBAL_MISE_CONFIG", config_file),
        patch("sive.core.ui.ensure_homebrew_command", return_value=True),
        patch.object(setup, "_materialize_mise_hook_script", return_value=None),
    ):
        setup._patch_mise_config()

    assert not config_file.exists()
    captured = capsys.readouterr()
    assert "env hook" in captured.out
    assert setup.SIVE_MISE_DIRECTIVE not in captured.out


def test_patch_mise_config_migrates_legacy_vfox_directive(tmp_path):
    """A pre-existing `_.sive = {}` vfox directive (which crashes mise) gets replaced."""
    config_dir = tmp_path / "mise"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text("[settings]\nenv_cache = true\n\n[env]\n_.sive = {}\n")

    with (
        patch.object(setup, "MISE_CONFIG_DIR", config_dir),
        patch.object(setup, "GLOBAL_MISE_CONFIG", config_file),
        patch("sive.core.ui.ensure_homebrew_command", return_value=True),
        patch.object(setup, "_materialize_mise_hook_script", return_value=setup.SIVE_HOOK_SCRIPT),
    ):
        setup._patch_mise_config()

    content = config_file.read_text()
    assert "_.sive" not in content
    assert setup.SIVE_MISE_DIRECTIVE in content
    assert "env_cache = false" in content


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
