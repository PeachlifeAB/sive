"""Verify the package version is set and reachable."""

from __future__ import annotations

import subprocess
import sys


def test_version_string_is_set():
    from sive import __version__

    assert __version__
    assert isinstance(__version__, str)


def test_version_flag_via_cli():
    result = subprocess.run(
        [sys.executable, "-m", "sive", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr  # argparse may print to stderr on some versions
    assert "sive" in output
    assert "0.1.0" in output


def test_version_flag_includes_commit_hash():
    import re

    result = subprocess.run(
        [sys.executable, "-m", "sive", "--version"],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    # Either "sive 0.1.0 (abc1234)" if in a git repo, or "sive 0.1.0" if not
    assert re.search(r"sive 0\.1\.0( \([0-9a-f]+\))?", output)
