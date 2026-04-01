"""sive _mise-env — called by the mise Lua hook at shell startup.

Fast path: decrypt local tag snapshots only. No live bw calls, no network.
If a tag snapshot is missing or unreadable, warns once to stderr and skips it.
"""

from __future__ import annotations

import json
import os
import sys

from ..core.project_config import active_tags
from ..core.snapshot import read_snapshot, snapshot_exists


def run(tags: list[str]) -> int:
    """Return merged snapshot env as JSON and never fail shell startup.

    Contract:
      - stdout: JSON object on success, '{}' on failure
      - stderr: short warnings only
      - exit code: always 0
    """
    try:
        if not tags:
            tags = active_tags()

        vault_name = "personal"
        env: dict[str, str] = {}

        for tag in tags:
            if not snapshot_exists(vault_name, tag):
                _warn(f"sive: no snapshot for tag '{tag}' — run 'sive setup' to populate")
                continue
            result = read_snapshot(vault_name, tag)
            if result is None:
                _warn(f"sive: could not read snapshot for tag '{tag}' — run 'sive setup'")
                continue
            env.update(result)

        json.dump(env, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    except Exception as e:
        if os.getenv("SIVE_DEBUG"):
            _warn(f"sive: error reading snapshots — using empty env ({e})")
        else:
            _warn("sive: error reading snapshots — using empty env")
        json.dump({}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0


def _warn(msg: str) -> None:
    print(msg, file=sys.stderr)
