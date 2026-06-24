#!/usr/bin/env python3
"""Release automation for sive.

Usage:
  python scripts/release.py verify
  python scripts/release.py prepare 0.1.3
  python scripts/release.py formula 0.1.3 --tap ../homebrew-tap
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 unsupported by project
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "sive"
GITHUB_TARBALL = "https://github.com/PeachlifeAB/sive/archive/refs/tags/{version}.tar.gz"
VERSION_RE = r"\d+\.\d+\.\d+(?:[.-][A-Za-z0-9]+)?"


@dataclass(frozen=True)
class VersionSource:
    path: Path
    pattern: re.Pattern[str]
    label: str


VERSION_SOURCES = [
    VersionSource(
        ROOT / "src/sive/__init__.py",
        re.compile(r'__version__ = "(?P<version>[^\"]+)"'),
        "python package",
    ),
    VersionSource(
        ROOT / "pyproject.toml",
        re.compile(r'^version = "(?P<version>[^\"]+)"', re.MULTILINE),
        "pyproject",
    ),
    VersionSource(
        ROOT / "metadata.lua",
        re.compile(r'PLUGIN\.version = "(?P<version>[^\"]+)"'),
        "mise plugin metadata",
    ),
    VersionSource(
        ROOT / "uv.lock",
        re.compile(r'\[\[package\]\]\nname = "sive"\nversion = "(?P<version>[^\"]+)"'),
        "uv lock",
    ),
]


class ReleaseError(RuntimeError):
    """Raised when release automation detects unsafe state."""


def run(args: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(args))
    subprocess.run(args, cwd=cwd, check=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def extract_version(source: VersionSource) -> str:
    match = source.pattern.search(read_text(source.path))
    if not match:
        raise ReleaseError(f"{source.label}: version pattern not found in {source.path}")
    return match.group("version")


def replace_one(path: Path, pattern: str, replacement: str, *, flags: int = 0) -> None:
    content = read_text(path)
    new_content, count = re.subn(pattern, replacement, content, count=1, flags=flags)
    if count != 1:
        raise ReleaseError(f"expected one replacement in {path}, got {count}")
    write_text(path, new_content)


def replace_all(path: Path, old: str, new: str) -> None:
    content = read_text(path)
    if old not in content:
        raise ReleaseError(f"expected {old!r} in {path}")
    write_text(path, content.replace(old, new))


def pyproject_version() -> str:
    data = tomllib.loads(read_text(ROOT / "pyproject.toml"))
    return str(data["project"]["version"])


def assert_valid_version(version: str) -> None:
    if not re.fullmatch(VERSION_RE, version):
        raise ReleaseError(f"invalid version: {version!r}")


def update_repo_versions(version: str) -> None:
    assert_valid_version(version)
    current = pyproject_version()

    replace_one(
        ROOT / "src/sive/__init__.py",
        r'__version__ = "[^"]+"',
        f'__version__ = "{version}"',
    )
    replace_one(
        ROOT / "pyproject.toml",
        r'^version = "[^"]+"',
        f'version = "{version}"',
        flags=re.MULTILINE,
    )
    replace_one(
        ROOT / "metadata.lua",
        r'PLUGIN\.version = "[^"]+"',
        f'PLUGIN.version = "{version}"',
    )

    if current == version:
        return

    for path in [ROOT / "tests/test_version.py", ROOT / "docs/USER-STORIES.md"]:
        replace_all(path, current, version)
        replace_all(path, re.escape(current), re.escape(version))


def verify_repo_versions() -> None:
    versions = {source.label: extract_version(source) for source in VERSION_SOURCES}
    expected = versions["pyproject"]
    mismatches = {label: value for label, value in versions.items() if value != expected}
    if mismatches:
        details = ", ".join(f"{label}={value}" for label, value in sorted(versions.items()))
        raise ReleaseError(f"version mismatch: {details}")

    test_version = read_text(ROOT / "tests/test_version.py")
    if expected not in test_version or re.escape(expected) not in test_version:
        raise ReleaseError("tests/test_version.py does not assert current version")

    version_output = subprocess.run(
        [sys.executable, "-m", PROJECT_NAME, "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if expected not in version_output:
        raise ReleaseError(f"CLI version mismatch: expected {expected}, got {version_output!r}")

    print(f"version ok: {expected}")


def git_output(args: list[str], *, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def require_git_clean(*, cwd: Path = ROOT) -> None:
    status = git_output(["status", "--porcelain"], cwd=cwd)
    if status:
        raise ReleaseError(f"git working tree is dirty in {cwd}:\n{status}")


def require_not_published(version: str) -> None:
    tag_exists = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/tags/{version}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if tag_exists.returncode == 0:
        raise ReleaseError(f"tag already exists locally: {version}")


def verify_installed_tool(version: str) -> None:
    run(["uv", "tool", "install", "--force", "--no-cache", str(ROOT)])
    executable = Path.home() / ".local" / "bin" / PROJECT_NAME
    version_output = subprocess.run(
        [str(executable), "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    expected = f"{PROJECT_NAME} {version}"
    if version_output != expected:
        raise ReleaseError(
            f"installed tool mismatch: expected {expected!r}, got {version_output!r}"
        )
    print(f"installed tool ok: {version_output}")


def prepare(version: str) -> None:
    require_not_published(version)
    run(["uv", "run", "ruff", "check", "."])
    run(["uv", "run", "pytest"])
    update_repo_versions(version)
    run(["uv", "lock"])
    run(["uv", "run", "ruff", "format", "."])
    run(["uv", "run", "ruff", "check", "."])
    verify_repo_versions()
    run(["uv", "run", "pytest"])
    verify_installed_tool(version)


def tarball_sha256(version: str) -> str:
    url = GITHUB_TARBALL.format(version=version)
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        digest = hashlib.sha256(response.read()).hexdigest()
    return digest


def formula_path(tap: Path) -> Path:
    path = tap / "Formula" / "sive.rb"
    if not path.exists():
        raise ReleaseError(f"formula not found: {path}")
    return path


def update_formula(version: str, *, tap: Path, sha256: str | None) -> None:
    assert_valid_version(version)
    formula = formula_path(tap)
    digest = sha256 or tarball_sha256(version)
    content = read_text(formula)
    content = re.sub(
        r'url "https://github\.com/PeachlifeAB/sive/archive/refs/tags/[^\"]+\.tar\.gz"',
        f'url "{GITHUB_TARBALL.format(version=version)}"',
        content,
        count=1,
    )
    content = re.sub(r'sha256 "[a-f0-9]{64}"', f'sha256 "{digest}"', content, count=1)
    content = re.sub(
        r'assert_match .+, shell_output\("#\{bin\}/sive --version"\)',
        'assert_match version.to_s, shell_output("#{bin}/sive --version")',
        content,
        count=1,
    )
    write_text(formula, content)
    verify_formula(tap=tap, expected=version)


def verify_formula(*, tap: Path, expected: str | None = None) -> None:
    formula = formula_path(tap)
    content = read_text(formula)
    version = expected or pyproject_version()
    if f"/tags/{version}.tar.gz" not in content:
        raise ReleaseError(f"formula URL does not point at {version}")
    if 'assert_match version.to_s, shell_output("#{bin}/sive --version")' not in content:
        raise ReleaseError("formula test must assert version.to_s")
    if not re.search(r'sha256 "[a-f0-9]{64}"', content):
        raise ReleaseError("formula sha256 missing or invalid")
    if 'depends_on "uv"' in content:
        raise ReleaseError("formula must not install uv")
    if "include Language::Python::Virtualenv" not in content:
        raise ReleaseError("formula must use Homebrew Python virtualenv helper")
    if "virtualenv_install_with_resources" not in content:
        raise ReleaseError("formula must install with virtualenv_install_with_resources")
    if 'depends_on "python@3.13"' not in content:
        raise ReleaseError("formula must depend on python@3.13")
    if 'depends_on "cryptography"' not in content:
        raise ReleaseError("formula must depend on brewed cryptography")
    print(f"formula ok: {formula}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and verify sive releases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("verify", help="Verify in-repo release metadata consistency")

    prepare_parser = subparsers.add_parser("prepare", help="Bump version and run release checks")
    prepare_parser.add_argument("version", help="Release version, e.g. 0.1.3")

    formula_parser = subparsers.add_parser("formula", help="Update Homebrew tap formula")
    formula_parser.add_argument("version", help="Release version, e.g. 0.1.3")
    formula_parser.add_argument("--tap", type=Path, default=ROOT.parent / "homebrew-tap")
    formula_parser.add_argument("--sha256", help="Use known tarball sha instead of downloading")

    formula_verify = subparsers.add_parser("verify-formula", help="Verify Homebrew formula")
    formula_verify.add_argument("--tap", type=Path, default=ROOT.parent / "homebrew-tap")
    formula_verify.add_argument("--version", default=None)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "verify":
            verify_repo_versions()
        elif args.command == "prepare":
            prepare(args.version)
        elif args.command == "formula":
            update_formula(args.version, tap=args.tap.resolve(), sha256=args.sha256)
        elif args.command == "verify-formula":
            verify_formula(tap=args.tap.resolve(), expected=args.version)
        else:  # pragma: no cover - argparse prevents this
            raise ReleaseError(f"unknown command: {args.command}")
    except (ReleaseError, subprocess.CalledProcessError) as e:
        print(f"release: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
