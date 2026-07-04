from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = ROOT / "scripts" / "release.py"


def load_release_module():
    spec = importlib.util.spec_from_file_location("release", RELEASE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["release"] = module
    spec.loader.exec_module(module)
    return module


def test_release_verify_accepts_current_version():
    release = load_release_module()

    release.verify_repo_versions()


def test_formula_update_enforces_version_assertion(tmp_path):
    release = load_release_module()
    formula_dir = tmp_path / "Formula"
    formula_dir.mkdir()
    formula = formula_dir / "sive.rb"
    formula.write_text(
        "\n".join(
            [
                "class Sive < Formula",
                "  include Language::Python::Virtualenv",
                "",
                '  url "https://github.com/PeachlifeAB/sive/archive/refs/tags/0.1.2.tar.gz"',
                '  sha256 "dee6b9bf8342e8777d202575a3ce59e9bfd817f8078bb8ff97b856ccd1717db4"',
                '  depends_on "cryptography"',
                '  depends_on "python@3.13"',
                "",
                "  def install",
                "    virtualenv_install_with_resources",
                "  end",
                "",
                "  test do",
                '    assert_match "sive", shell_output("#{bin}/sive --version")',
                "  end",
                "end",
                "",
            ]
        ),
        encoding="utf-8",
    )

    release.update_formula(
        "0.1.3",
        tap=tmp_path,
        sha256="a" * 64,
    )

    content = formula.read_text(encoding="utf-8")
    assert "/releases/download/v0.1.3/sive-0.1.3.tar.gz" in content
    assert 'sha256 "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"' in content
    assert 'depends_on "uv"' not in content
    assert "include Language::Python::Virtualenv" in content
    assert "virtualenv_install_with_resources" in content
    assert 'depends_on "cryptography"' in content
    assert 'depends_on "python@3.13"' in content
    assert 'assert_match version.to_s, shell_output("#{bin}/sive --version")' in content


def test_mise_hook_noops_when_sive_binary_is_missing():
    hook = ROOT / "hooks" / "mise_env.lua"
    content = hook.read_text(encoding="utf-8")

    assert 'pcall(cmd.exec, "command -v sive")' in content
    assert "failed to exec _mise-env" in content
    assert content.index('pcall(cmd.exec, "command -v sive")') < content.index(
        "failed to exec _mise-env"
    )
    assert "return {" in content
