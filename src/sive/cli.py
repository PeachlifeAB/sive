"""sive — entry point."""

from __future__ import annotations

import argparse
import subprocess
import sys

from . import __version__
from .core import ui


def _echo(*values: object, sep: str = " ", end: str = "\n", file=None) -> None:
    stream = file or sys.stdout
    stream.write(sep.join(str(value) for value in values) + end)


def _version_string() -> str:
    try:
        import os

        package_dir = os.path.dirname(os.path.abspath(__file__))
        repo_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=package_dir,
        )
        if repo_result.returncode != 0:
            return f"sive {__version__}"

        repo_root = repo_result.stdout.strip()
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode == 0:
            short_hash = result.stdout.strip()
            return f"sive {__version__} ({short_hash})"
    except Exception:
        pass
    return f"sive {__version__}"


def main() -> None:
    try:
        _main()
    except KeyboardInterrupt:
        _echo("\nAborted.", file=sys.stderr)
        sys.exit(130)


def _print_top_level_help() -> None:
    _echo(
        "usage: sive [-h] [--version] <command> [<args>]\n\n"
        "Make secrets available automatically for the current project.\n\n"
        "commands:\n"
        "  setup     Configure current project directory\n"
        "  set       Write a secret to a tag folder\n"
        "  refresh   Sync local encrypted snapshots from the vault\n\n"
        "options:\n"
        "  -h, --help  show this help message and exit\n"
        "  --version   show program's version number and exit\n\n"
        "Examples:\n"
        "  sive setup\n"
        "  sive setup --tag work --tag personal\n"
        "  sive set OPENAI_API_KEY\n"
        "  sive set OPENAI_API_KEY --tag work\n"
        "  sive refresh"
    )


def _main() -> None:
    if len(sys.argv) == 1 or sys.argv[1] in {"-h", "--help"}:
        _print_top_level_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        prog="sive",
        description="Make secrets available automatically for the current project.",
        epilog=(
            "Examples:\n"
            "  sive setup\n"
            "  sive setup --tag work --tag personal\n"
            "  sive set OPENAI_API_KEY\n"
            "  sive set OPENAI_API_KEY --tag work\n"
            "  printf %s 'my-secret-value' | sive set MY_KEY\n"
            "  sive refresh"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=_version_string())

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # sive setup
    setup_parser = subparsers.add_parser("setup", help="Configure current project directory")
    setup_parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        metavar="TAG",
        help="Tag to load in this project (repeatable); omit to be prompted",
    )
    setup_parser.add_argument(
        "--no-global",
        action="store_true",
        default=False,
        help="Do not auto-include the 'global' tag (strict isolation)",
    )

    subparsers.add_parser("status", help=argparse.SUPPRESS)

    # sive _mise-env (internal, called by Lua hook)
    mise_env_parser = subparsers.add_parser(
        "_mise-env",
        help=argparse.SUPPRESS,
    )
    mise_env_parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        help="Tag name, e.g. global",
    )
    # sive refresh
    refresh_parser = subparsers.add_parser(
        "refresh", help="Sync local encrypted snapshots from the vault"
    )
    refresh_parser.add_argument(
        "--vault", default="personal", help="Vault name (default: personal)"
    )
    refresh_parser.add_argument(
        "--source", action="append", dest="sources", help="Override source specs"
    )

    # sive set
    set_parser = subparsers.add_parser("set", help="Write a secret to a tag folder")
    set_parser.add_argument("key", help="Variable name (e.g. MY_API_KEY)")
    set_parser.add_argument(
        "--tag",
        default=None,
        help="Override the target tag (default: most-specific active tag)",
    )
    set_parser.add_argument("--vault", default="personal", help="Vault name (default: personal)")

    sync_parser = subparsers.add_parser("_sync-vault", help=argparse.SUPPRESS)
    sync_parser.add_argument("vault_name")

    args = parser.parse_args()

    if args.command == "setup":
        from .commands.setup import run_project_setup

        sys.exit(run_project_setup(tags=args.tags, no_global=args.no_global))

    elif args.command == "status":
        from .commands.status import run

        sys.exit(run())

    elif args.command == "_mise-env":
        from .commands.mise_env import run

        sys.exit(run(args.tags))

    elif args.command == "refresh":
        from .commands.refresh import run

        sys.exit(run(vault_name=args.vault, sources=args.sources))

    elif args.command == "set":
        from .commands.set_secret import run

        if not sys.stdin.isatty():
            value = sys.stdin.read().strip()
            if not value:
                _echo("sive: stdin is empty", file=sys.stderr)
                sys.exit(1)
        else:
            try:
                value = ui.password(f"Value for {args.key}")
            except EOFError:
                _echo("No input received, aborting.", file=sys.stderr)
                sys.exit(1)
        sys.exit(run(args.key, value, tag=args.tag, vault_name=args.vault))

    elif args.command == "_sync-vault":
        from .core.sync_state import run_sync_vault

        sys.exit(run_sync_vault(args.vault_name))

    else:
        parser.print_help()
        sys.exit(0)
