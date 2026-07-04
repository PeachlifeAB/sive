#!/bin/sh
# sive mise env hook — sourced via `_.source` in mise.toml.
# Runs `sive _mise-env`, which reads encrypted per-tag snapshots only
# (no live Bitwarden calls), and exports the result into the shell.
# mise diffs the environment before/after sourcing this script and
# merges any exported vars — see the `_.source` directive in mise docs.

command -v sive >/dev/null 2>&1 || return 0

sive_env_json="$(sive _mise-env 2>/dev/null)" || sive_env_json="{}"

eval "$(
  printf '%s' "$sive_env_json" | python3 -c '
import json, sys, shlex
try:
    data = json.load(sys.stdin)
except ValueError:
    data = {}
for key, value in data.items():
    print(f"export {shlex.quote(key)}={shlex.quote(str(value))}")
'
)"
