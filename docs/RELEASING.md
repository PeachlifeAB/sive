# Releasing Sive

Sive releases are orchestrated by the shared engine in
[`PeachlifeAB/homebrew-tap`](https://github.com/PeachlifeAB/homebrew-tap). Sive
owns product tests and package metadata; the tap owns release state transitions,
formula updates, Homebrew CI, bottles, publication, and installed-user proof.

## Contract

- `[project].version` in `pyproject.toml` is the only authored version.
- Sive tags remain `vX.Y.Z`.
- The source artifact is `sive-X.Y.Z.tar.gz` attached to the matching GitHub release.
- The tap formula uses `Language::Python::Virtualenv` and a functional version test.
- Formula updates are pull requests. `brew test-bot` builds every required macOS
  bottle; pinned-head `brew pr-pull` publishes them.
- Published tags and release assets are immutable.

## Commands

Every release command requires an explicit version:

```bash
task release:dry-run VERSION=X.Y.Z
task release:prepare VERSION=X.Y.Z
task release:verify VERSION=X.Y.Z
task release:publish VERSION=X.Y.Z
task release:resume VERSION=X.Y.Z
task release:post-verify VERSION=X.Y.Z
task release VERSION=X.Y.Z
```

`task release VERSION=X.Y.Z` is the normal path. It validates clean synchronized
repositories, runs `task test`, commits the prepared version before creating the
tag, publishes the sdist, opens the formula pull request, waits for all bottles,
publishes through `brew pr-pull`, and verifies the explicit Homebrew executable.

## Preflight

Run before release work and after publication:

```bash
task release:preflight
```

Preflight prints freshly observed producer, tap, artifact, formula, and bottle
state. Any dirty tree, unpushed commit, tag/version mismatch, checksum drift,
audit failure, or missing bottle blocks publication.

## Recovery

Use the same version after an interrupted release:

```bash
task release:resume VERSION=X.Y.Z
```

Resume reconstructs progress from Git, GitHub, the formula pull request,
workflow checks, and bottle assets. It refuses conflicting commits, checksums,
pull-request heads, or formula versions. Never move a published tag or replace a
published asset; publish a new patch version when immutable state is wrong.

## User-path proof

Post-verification executes `$(brew --prefix)/bin/sive`, not an ambient uv-tool
binary. The release is complete only when this real upgrade path succeeds:

```bash
brew update
brew upgrade sive
"$(brew --prefix)/bin/sive" --version
brew test peachlifeab/tap/sive
```

`scripts/release.py` remains temporarily as a parity reference. Do not extend or
invoke it for new releases; remove it after both Sive and bgtail have completed a
release through the shared engine.
