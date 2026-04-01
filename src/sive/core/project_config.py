"""Read and write Sive project configuration."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

PROJECT_CONFIG = Path(".sive")
GLOBAL_MISE_CONFIG = Path.home() / ".config" / "mise" / "config.toml"


def _read_toml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read_project_config(config_path: Path | None = None) -> dict | None:
    return _read_toml(config_path or (Path.cwd() / PROJECT_CONFIG))


def read_project_tags(config_path: Path | None = None) -> list[str]:
    data = read_project_config(config_path)
    if not data:
        return []
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]


def read_project_vault(config_path: Path | None = None) -> str:
    data = read_project_config(config_path)
    if not data:
        return "personal"
    vault = data.get("vault")
    return vault if isinstance(vault, str) and vault.strip() else "personal"


def write_project_config(
    tags: list[str], vault: str = "personal", config_path: Path | None = None
) -> None:
    path = config_path or (Path.cwd() / PROJECT_CONFIG)
    normalized: list[str] = []
    for tag in tags:
        cleaned = tag.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    path.write_text(f"version = 1\nvault = {json.dumps(vault)}\ntags = {json.dumps(normalized)}\n")


def _read_mise_tags(path: Path) -> list[str]:
    data = _read_toml(path)
    if not data:
        return []
    env = data.get("env", {})
    sive = {}
    if isinstance(env, dict):
        if isinstance(env.get("_.sive"), dict):
            sive = env["_.sive"]
        elif isinstance(env.get("_"), dict) and isinstance(env["_"].get("sive"), dict):
            sive = env["_"].get("sive", {})
    tags = sive.get("tags", []) if isinstance(sive, dict) else []
    if not isinstance(tags, list):
        return []
    return [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]


def read_global_tags(config_path: Path | None = None) -> list[str]:
    return _read_mise_tags(config_path or GLOBAL_MISE_CONFIG)


def active_tags() -> list[str]:
    for getter in (read_project_tags, read_global_tags):
        tags = getter()
        if tags:
            return tags
    return ["global"]
