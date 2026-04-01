"""Read and validate ~/.config/sive/vaults.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "sive"
DATA_DIR = Path.home() / ".local" / "share" / "sive"
VAULTS_TOML = CONFIG_DIR / "vaults.toml"

VAULTS_TOML_TEMPLATE = """\
[vaults.personal]
server = ""  # Required — e.g. https://vw.yourdomain.com or https://vault.bitwarden.com
"""


@dataclass
class VaultConfig:
    name: str
    server: str
    appdata_dir: Path


class ConfigError(Exception):
    pass


def default_appdata_dir(name: str) -> Path:
    return DATA_DIR / "vaults" / name


def load_vault(name: str = "personal") -> VaultConfig:
    """Load and validate a vault config entry. Raises ConfigError on any problem."""
    if not VAULTS_TOML.exists():
        raise ConfigError(
            f"Config file not found: {VAULTS_TOML}\nRun 'sive setup' to configure sive."
        )

    try:
        with open(VAULTS_TOML, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {VAULTS_TOML}: {e}") from e

    vaults = data.get("vaults", {})
    if name not in vaults:
        raise ConfigError(
            f"Vault '{name}' not found in {VAULTS_TOML}\nRun 'sive setup' to configure it."
        )

    entry = vaults[name]
    server = entry.get("server", "").strip()
    if not server:
        raise ConfigError(
            f"Vault '{name}' is missing a 'server' URL in {VAULTS_TOML}\n"
            "Set it to your Bitwarden/Vaultwarden server URL, e.g.:\n"
            '  server = "https://vw.yourdomain.com"'
        )

    raw_appdata_dir = entry.get("appdata_dir", "").strip()
    appdata_dir = (
        Path(raw_appdata_dir).expanduser() if raw_appdata_dir else default_appdata_dir(name)
    )

    return VaultConfig(name=name, server=server, appdata_dir=appdata_dir)


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def write_vault_stub(name: str, server: str) -> None:
    """Write or update a vault entry in vaults.toml."""
    ensure_config_dir()

    if VAULTS_TOML.exists():
        with open(VAULTS_TOML, "rb") as f:
            data = tomllib.load(f)
    else:
        data = {}

    vaults = data.setdefault("vaults", {})
    vaults[name] = {**vaults.get(name, {}), "server": server}

    # Preserve other vault sections if they exist
    # For MVP only personal is supported, so simple write is fine
    with open(VAULTS_TOML, "w") as f:
        for vault_name, vault_data in vaults.items():
            f.write(f"[vaults.{vault_name}]\n")
            f.write(f'server = "{vault_data["server"]}"\n')
            if vault_data.get("appdata_dir"):
                f.write(f'appdata_dir = "{vault_data["appdata_dir"]}"\n')
            f.write("\n")
