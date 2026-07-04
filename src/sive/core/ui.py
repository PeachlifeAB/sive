"""Terminal UI helpers using gum, with plain-prompt fallback."""

from __future__ import annotations

import builtins
import getpass as _getpass
import shutil
import subprocess
import sys
from collections.abc import Callable
from typing import TextIO, TypeVar

_T = TypeVar("_T")


def echo(*values: object, sep: str = " ", end: str = "\n", file: TextIO | None = None) -> None:
    """Write terminal output without using debug-style print calls."""
    stream = file or sys.stdout
    stream.write(sep.join(str(value) for value in values) + end)


def eprint(*values: object, sep: str = " ", end: str = "\n") -> None:
    """Write terminal error output."""
    echo(*values, sep=sep, end=end, file=sys.stderr)


def ensure_homebrew_command(
    command: str,
    formula: str,
    noun: str,
    *,
    fallback: str = "",
) -> bool:
    """Ensure a command exists, offering a Homebrew install when missing."""
    if shutil.which(command):
        return True

    echo(f"  {noun} not found.")
    if confirm(f"Install {noun} with Homebrew now?", default=True):
        try:
            install = subprocess.run(["brew", "install", formula])
        except FileNotFoundError:
            install = subprocess.CompletedProcess(["brew", "install", formula], 127)
        if install.returncode == 0 and shutil.which(command):
            return True
        echo(f"  Homebrew install did not make '{command}' available.")

    echo(f"  Install it: brew install {formula}")
    if fallback:
        echo(f"  Or: {fallback}")
    return False


def style(
    text: str, *, bold: bool = False, foreground: str = "", background: str = "", padding: str = ""
) -> None:
    """Print styled text via gum style; falls back to plain print."""
    try:
        args = ["style"]
        if bold:
            args += ["--bold"]
        if foreground:
            args += ["--foreground", foreground]
        if background:
            args += ["--background", background]
        if padding:
            args += ["--padding", padding]
        args.append(text)
        result = subprocess.run(["gum", *args])
        if result.returncode == 130:
            raise KeyboardInterrupt
    except FileNotFoundError:
        echo(text)


def input(prompt: str, *, placeholder: str = "") -> str:  # noqa: A001
    """Prompt for a single line of text. Falls back to built-in input()."""
    try:
        args = ["gum", "input", "--prompt", f"{prompt}: "]
        if placeholder:
            args += ["--placeholder", placeholder]
        result = subprocess.run(args, stdout=subprocess.PIPE, text=True)
        if result.returncode == 130:
            raise KeyboardInterrupt
        if result.returncode != 0:
            raise FileNotFoundError
        return result.stdout.strip()
    except FileNotFoundError:
        return builtins.input(f"  {prompt}: ").strip()


def password(prompt: str) -> str:
    """Prompt for a hidden password. Falls back to getpass."""
    try:
        args = ["gum", "input", "--password", "--prompt", f"{prompt}: "]
        result = subprocess.run(args, stdout=subprocess.PIPE, text=True)
        if result.returncode == 130:
            raise KeyboardInterrupt
        if result.returncode != 0:
            raise FileNotFoundError
        return result.stdout.strip()
    except FileNotFoundError:
        return _getpass.getpass(f"  {prompt}: ")


def confirm(prompt: str, *, default: bool = True) -> bool:
    """Ask a yes/no question. Falls back to y/n input loop."""
    try:
        args = ["gum", "confirm", prompt]
        if default:
            args += ["--default"]
        result = subprocess.run(args)
        if result.returncode == 130:
            raise KeyboardInterrupt
        if result.returncode not in (0, 1):
            raise FileNotFoundError
        return result.returncode == 0
    except FileNotFoundError:
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            raw = builtins.input(f"  {prompt} {hint}: ").strip().lower()
            if raw in ("", "y", "yes"):
                return True
            if raw in ("n", "no"):
                return False


def spin(title: str, fn: Callable[[], _T]) -> _T:
    """Show progress text, then run fn() and propagate its result."""
    echo(f"  {title}")
    return fn()


def choose(header: str, options: list[str], *, selected: list[str] | None = None) -> list[str]:
    """Multi-select checkbox list via gum choose --no-limit. Falls back to plain input."""
    if not options:
        return []
    try:
        args = [
            "gum",
            "choose",
            "--no-limit",
            "--header",
            header,
            "--cursor",
            "> ",
            "--cursor-prefix",
            "[ ] ",
            "--selected-prefix",
            "[✓] ",
            "--unselected-prefix",
            "[ ] ",
        ]
        if selected:
            args += ["--selected", ",".join(selected)]
        args += options
        result = subprocess.run(args, stdout=subprocess.PIPE, text=True)
        if result.returncode == 130:
            raise KeyboardInterrupt
        if result.returncode != 0:
            raise FileNotFoundError
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except FileNotFoundError:
        echo(f"  {header}")
        for opt in options:
            echo(f"    • {opt}")
        raw = builtins.input("  Enter choices (space or comma separated): ").strip()
        chosen = [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
        valid = set(options)
        return [c for c in chosen if c in valid]
