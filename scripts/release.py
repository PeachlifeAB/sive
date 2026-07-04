#!/usr/bin/env python3
"""Release automation for sive.

Usage:
  python scripts/release.py verify
  python scripts/release.py prepare 0.1.3
  python scripts/release.py formula 0.1.3 --tap ../homebrew-tap
  python scripts/release.py release 0.1.3 --tap ../homebrew-tap
  python scripts/release.py release 0.1.3 --tap ../homebrew-tap --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 unsupported by project
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "sive"
GITHUB_SDIST = (
    "https://github.com/PeachlifeAB/sive/releases/download/v{version}/sive-{version}.tar.gz"
)
VERSION_RE = r"\d+\.\d+\.\d+(?:[.-][A-Za-z0-9]+)?"
VERSION_FULL_RE = re.compile(f"^{VERSION_RE}$")
INIT_VERSION_RE = re.compile(r'__version__ = "[^\"]+"')
PYPROJECT_VERSION_RE = re.compile(r'^version = "[^\"]+"', re.MULTILINE)
METADATA_VERSION_RE = re.compile(r'PLUGIN\.version = "[^\"]+"')
FORMULA_URL_RE = re.compile(
    r'url "https://github\.com/PeachlifeAB/sive/(?:archive/refs/tags|releases/download/v)[^\"]+\.tar\.gz"'
)
FORMULA_SHA_RE = re.compile(r'sha256 "[a-f0-9]{64}"')
FORMULA_TEST_RE = re.compile(r'assert_match .+, shell_output\("#\{bin\}/sive --version"\)')


def echo(*values: object, sep: str = " ", end: str = "\n", file: TextIO | None = None) -> None:
    stream = file or sys.stdout
    stream.write(sep.join(str(value) for value in values) + end)


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
    echo("+", " ".join(args))
    subprocess.run(args, cwd=cwd, check=True)


def _read_release_text(path: Path) -> str:
    return getattr(path, "read_text")(encoding="utf-8")


def _write_release_text(path: Path, content: str) -> None:
    getattr(path, "write_text")(content, encoding="utf-8")


def extract_version(source: VersionSource) -> str:
    match = source.pattern.search(_read_release_text(source.path))
    if not match:
        raise ReleaseError(f"{source.label}: version pattern not found in {source.path}")
    return match.group("version")


def replace_one(path: Path, pattern: re.Pattern[str], replacement: str) -> None:
    content = _read_release_text(path)
    new_content, count = pattern.subn(replacement, content, count=1)
    if count != 1:
        raise ReleaseError(f"expected one replacement in {path}, got {count}")
    _write_release_text(path, new_content)


def replace_all(path: Path, old: str, new: str) -> None:
    content = _read_release_text(path)
    if old not in content:
        raise ReleaseError(f"expected {old!r} in {path}")
    _write_release_text(path, content.replace(old, new))


def pyproject_version() -> str:
    data = tomllib.loads(_read_release_text(ROOT / "pyproject.toml"))
    return str(data["project"]["version"])


def assert_valid_version(version: str) -> None:
    if not VERSION_FULL_RE.fullmatch(version):
        raise ReleaseError(f"invalid version: {version!r}")


def update_repo_versions(version: str) -> None:
    assert_valid_version(version)
    current = pyproject_version()

    replace_one(
        ROOT / "src/sive/__init__.py",
        INIT_VERSION_RE,
        f'__version__ = "{version}"',
    )
    replace_one(
        ROOT / "pyproject.toml",
        PYPROJECT_VERSION_RE,
        f'version = "{version}"',
    )
    replace_one(
        ROOT / "metadata.lua",
        METADATA_VERSION_RE,
        f'PLUGIN.version = "{version}"',
    )

    if current == version:
        return

    for path in [ROOT / "tests/test_version.py"]:
        replace_all(path, current, version)
        replace_all(path, re.escape(current), re.escape(version))


def verify_repo_versions() -> None:
    versions = {source.label: extract_version(source) for source in VERSION_SOURCES}
    expected = versions["pyproject"]
    mismatches = {label: value for label, value in versions.items() if value != expected}
    if mismatches:
        details = ", ".join(f"{label}={value}" for label, value in sorted(versions.items()))
        raise ReleaseError(f"version mismatch: {details}")

    test_version = _read_release_text(ROOT / "tests/test_version.py")
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

    echo(f"version ok: {expected}")


def git_output(args: list[str], *, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def require_git_clean(*, cwd: Path = ROOT, warn: bool = False) -> None:
    status = git_output(["status", "--porcelain"], cwd=cwd)
    if not status:
        return
    if warn:
        echo(
            f"note: working tree dirty in {cwd} — commit before a real release",
            file=sys.stderr,
        )
        return
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
    echo(f"installed tool ok: {version_output}")


def prepare(version: str, *, dry_run: bool = False) -> None:
    require_not_published(version)
    run(["uv", "run", "ruff", "check", "."])
    run(["uv", "run", "pytest"])
    if dry_run:
        echo(
            f"[dry-run] bump versions to {version}, uv lock, ruff format, "
            "re-verify, re-test, reinstall tool"
        )
        return
    update_repo_versions(version)
    run(["uv", "lock"])
    run(["uv", "run", "ruff", "format", "."])
    run(["uv", "run", "ruff", "check", "."])
    verify_repo_versions()
    run(["uv", "run", "pytest"])
    verify_installed_tool(version)


def _github_sdist_url(version: str) -> str:
    assert_valid_version(version)
    url = GITHUB_SDIST.format(version=version)
    parsed = urllib.parse.urlparse(url)
    expected_path = f"/PeachlifeAB/sive/releases/download/v{version}/sive-{version}.tar.gz"
    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.path != expected_path:
        raise ReleaseError(f"unexpected release sdist URL: {url}")
    return url


def sdist_sha256(version: str) -> str:
    url = _github_sdist_url(version)
    response = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location", url],
        capture_output=True,
        check=True,
    )
    return hashlib.sha256(response.stdout).hexdigest()


def formula_path(tap: Path) -> Path:
    path = tap / "Formula" / "sive.rb"
    if not path.exists():
        raise ReleaseError(f"formula not found: {path}")
    return path


def update_formula(version: str, *, tap: Path, sha256: str | None) -> None:
    assert_valid_version(version)
    formula = formula_path(tap)
    digest = sha256 or sdist_sha256(version)
    content = _read_release_text(formula)
    content = FORMULA_URL_RE.sub(f'url "{GITHUB_SDIST.format(version=version)}"', content, count=1)
    content = FORMULA_SHA_RE.sub(f'sha256 "{digest}"', content, count=1)
    content = FORMULA_TEST_RE.sub(
        'assert_match version.to_s, shell_output("#{bin}/sive --version")', content, count=1
    )
    _write_release_text(formula, content)
    verify_formula(tap=tap, expected=version)


def verify_formula(*, tap: Path, expected: str | None = None) -> None:
    formula = formula_path(tap)
    content = _read_release_text(formula)
    version = expected or pyproject_version()
    if f"/releases/download/v{version}/sive-{version}.tar.gz" not in content:
        raise ReleaseError(f"formula URL does not point at {version}")
    if 'assert_match version.to_s, shell_output("#{bin}/sive --version")' not in content:
        raise ReleaseError("formula test must assert version.to_s")
    if not FORMULA_SHA_RE.search(content):
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
    echo(f"formula ok: {formula}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and verify sive releases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("verify", help="Verify in-repo release metadata consistency")

    prepare_parser = subparsers.add_parser("prepare", help="Bump version and run release checks")
    prepare_parser.add_argument("version", help="Release version, e.g. 0.1.3")

    formula_parser = subparsers.add_parser("formula", help="Update Homebrew tap formula")
    formula_parser.add_argument("version", help="Release version, e.g. 0.1.3")
    formula_parser.add_argument("--tap", type=Path, default=ROOT.parent / "homebrew-tap")
    formula_parser.add_argument("--sha256", help="Use known sdist sha instead of downloading")

    formula_verify = subparsers.add_parser("verify-formula", help="Verify Homebrew formula")
    formula_verify.add_argument("--tap", type=Path, default=ROOT.parent / "homebrew-tap")
    formula_verify.add_argument("--version", default=None)

    release_parser = subparsers.add_parser(
        "release", help="Full release: prepare + tag + push + GH release + brew bump"
    )
    release_parser.add_argument("version", help="Release version, e.g. 0.1.3")
    release_parser.add_argument(
        "--tap", type=Path, required=True, help="Path to homebrew-tap repo (required)"
    )
    release_parser.add_argument(
        "--dry-run", action="store_true", help="Preview without pushing or creating releases"
    )

    return parser.parse_args()


def _commit_version_bump(version: str, *, dry_run: bool) -> None:
    """Commit the version bump so the release tag points at the bumped tree."""
    if dry_run:
        echo(f"[dry-run] git add -A && git commit -m 'sive: v{version}'")
        return
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", f"sive: v{version}"])
    echo(f"committed version bump: v{version}")


def _git_tag_and_push(version: str, *, dry_run: bool) -> None:
    tag_name = f"v{version}"
    if dry_run:
        echo(f"[dry-run] git tag -a {tag_name} -m 'Release {version}'")
        echo(f"[dry-run] git push origin {tag_name}")
        return
    run(["git", "tag", "-a", tag_name, "-m", f"Release {version}"])
    run(["git", "push", "origin", tag_name])
    echo(f"tagged and pushed: {tag_name}")


def _create_github_release(version: str, *, dry_run: bool) -> str:
    """Build sdist, upload to GitHub release, return tarball sha256."""
    tag_name = f"v{version}"
    release_notes = f"Release {version}"

    if dry_run:
        echo("[dry-run] uv build --sdist  (then compute sha256)")
        echo(
            f"[dry-run] gh release create {tag_name} "
            f"--title '{release_notes}' --notes '{release_notes}' dist/sive-{version}.tar.gz"
        )
        return "<dry-run>"

    run(["uv", "build", "--sdist"])
    sdist_path = sorted(ROOT.glob("dist/sive-*.tar.gz"))[-1]
    sha256 = hashlib.sha256(sdist_path.read_bytes()).hexdigest()
    echo(f"sdist: {sdist_path.name} sha256={sha256}")

    notes_file = ROOT / ".release-notes.md"
    notes_file.write_text(release_notes, encoding="utf-8")
    run(
        [
            "gh",
            "release",
            "create",
            tag_name,
            "--title",
            release_notes,
            "--notes-file",
            str(notes_file),
            str(sdist_path),
        ]
    )
    notes_file.unlink(missing_ok=True)
    echo(f"github release created: {tag_name}")
    return sha256


def _bump_brew_formula(version: str, *, tap: Path, sha256: str, dry_run: bool) -> None:
    """Update the owned-tap formula and push it. For a tap we own, the direct push IS the bump."""
    tap = tap.resolve()
    formula = formula_path(tap)

    if dry_run:
        echo(f"[dry-run] update formula at {formula}")
        return

    update_formula(version, tap=tap, sha256=sha256)
    run(["git", "add", "Formula/sive.rb"], cwd=tap)
    run(["git", "commit", "-m", f"sive: v{version}"], cwd=tap)
    run(["git", "push", "origin", "main"], cwd=tap)
    echo(f"formula bumped and pushed: {formula}")


def release(version: str, *, tap: Path, dry_run: bool) -> None:
    """Full release flow: prepare, tag, push, GH release, brew bump."""
    echo(f"=== Release {version} ===")
    if dry_run:
        echo("*** DRY RUN — nothing will be pushed, created, or modified ***\n")

    require_git_clean(warn=dry_run)
    require_git_clean(cwd=tap.resolve(), warn=dry_run)
    prepare(version, dry_run=dry_run)
    _commit_version_bump(version, dry_run=dry_run)
    _git_tag_and_push(version, dry_run=dry_run)
    sha256 = _create_github_release(version, dry_run=dry_run)
    _bump_brew_formula(version, tap=tap, sha256=sha256, dry_run=dry_run)

    echo(f"\n=== Release {version} complete ===")


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
        elif args.command == "release":
            release(args.version, tap=args.tap, dry_run=args.dry_run)
        else:  # pragma: no cover - argparse prevents this
            raise ReleaseError(f"unknown command: {args.command}")
    except (ReleaseError, subprocess.CalledProcessError) as e:
        echo(f"release: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
