from __future__ import annotations

from sive.core.project_config import active_tags, read_project_tags, write_project_config


def test_write_and_read_project_config(tmp_path):
    config_path = tmp_path / ".sive"
    write_project_config(["global", "projectX"], vault="personal", config_path=config_path)

    assert read_project_tags(config_path) == ["global", "projectX"]


def test_active_tags_prefers_project_config(tmp_path, monkeypatch):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    write_project_config(["global", "projectX"], config_path=project_root / ".sive")

    monkeypatch.chdir(project_root)

    assert active_tags() == ["global", "projectX"]
