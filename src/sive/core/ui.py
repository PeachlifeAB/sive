"""Terminal UI helpers using gum, with plain-prompt fallback."""

from __future__ import annotations

import builtins
import getpass as _getpass
import subprocess
import sys
import threading
from typing import Callable, TypeVar

_T = TypeVar("_T")



def style(text: str, *, bold: bool = False, foreground: str = "", background: str = "", padding: str = "") -> None:
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
        builtins.print(text)


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
    """Run fn() in a thread while showing an animated spinner. Returns fn's result.

    Falls back to a plain print + blocking call if gum is not available.
    Propagates exceptions raised by fn.
    """
    result_box: list[_T] = []
    exc_box: list[BaseException] = []

    def worker() -> None:
        try:
            result_box.append(fn())
        except BaseException as e:
            exc_box.append(e)

    try:
        subprocess.run(["gum", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        builtins.print(f"  {title}")
        try:
            result_box.append(fn())
        except BaseException as e:
            raise e
        return result_box[0]

    t = threading.Thread(target=worker, daemon=True)
    spinner = subprocess.Popen(
        ["gum", "spin", "--spinner", "dot", "--title", title, "--", "sleep", "3600"],
    )
    t.start()
    t.join()
    spinner.terminate()
    spinner.wait()

    if exc_box:
        raise exc_box[0]
    return result_box[0]


def choose(header: str, options: list[str], *, selected: list[str] | None = None) -> list[str]:
    """Multi-select checkbox list via gum choose --no-limit. Falls back to plain input."""
    if not options:
        return []
    try:
        args = [
            "gum", "choose",
            "--no-limit",
            "--header", header,
            "--cursor", "> ",
            "--cursor-prefix", "[ ] ",
            "--selected-prefix", "[✓] ",
            "--unselected-prefix", "[ ] ",
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
        builtins.print(f"  {header}")
        for opt in options:
            builtins.print(f"    • {opt}")
        raw = builtins.input("  Enter choices (space or comma separated): ").strip()
        chosen = [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
        valid = set(options)
        return [c for c in chosen if c in valid]
