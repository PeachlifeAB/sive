# Releasing Sive

Sive is published as a versioned GitHub release asset and distributed through
[`PeachlifeAB/homebrew-tap`](https://github.com/PeachlifeAB/homebrew-tap). The
producer automation lives in `scripts/release.py`; bottle construction and tap
publication follow the shared tap procedure in
[`docs/DEVELOPMENT.md`](https://github.com/PeachlifeAB/homebrew-tap/blob/main/docs/DEVELOPMENT.md).

## Release contract

A safe release has two phases:

1. Publish Sive upstream: synchronize versions, test, commit, push `main` and a
   `vX.Y.Z` tag, create the GitHub release sdist, and commit the formula update
   locally in the tap checkout.
2. Build and upload the mandatory Homebrew bottle, add its `bottle do` block,
   pass tap preflight, then push the tap once.

The upstream automation intentionally does **not** push the tap. Publishing the
formula before its bottle exists creates a temporarily invalid release and is
forbidden by the tap policy.

## Rule zero: inspect live state

Run this before release work and again before the final tap push:

```bash
task release:preflight
```

It reads both repositories, fetches the artifact currently pinned by the
formula, verifies its SHA-256, runs `brew style` and `brew audit --strict`, and
requires a bottle block. Before preparing a new version it can report the
current tag behind `HEAD`; that is expected release work. A dirty tree, unpushed
work, artifact drift, style/audit failure, or a missing bottle must never be
ignored at final handoff.

Historical tap failures justify this rule:

- Sive 0.1.2 used a SHA calculated from the wrong GitHub tarball.
- Sive 0.1.4 pointed at a tag archive instead of its published sdist asset.
- A formula shipped before `brew style` caught invalid dependency syntax.

Observed state, not remembered state, is the release authority.

## Version and artifact conventions

Sive uses `v`-prefixed tags (`v0.1.8`) and publishes
`sive-X.Y.Z.tar.gz` as a GitHub release asset. Do not copy bgtail's unprefixed
tag/archive convention.

The release version must agree in:

- `pyproject.toml`
- `src/sive/__init__.py`
- `uv.lock`
- `tests/test_version.py`
- the `vX.Y.Z` git tag
- `Formula/sive.rb`

`scripts/release.py` owns these updates and verifies the installed CLI. Tests
must run as `uv run python -m pytest`; invoking the generated `pytest` console
script directly is not relocatable because virtualenv shebangs contain absolute
paths.

## Release procedure

### 1. Run local gates

```bash
task test
```

This verifies formatting, lint, the complete test suite, release metadata, and
CLI version agreement.

### 2. Study current release state

```bash
task release:preflight
```

Resolve dirty or unpushed state before the real release. Read every remaining
failure and confirm it represents the planned version transition.

### 3. Preview the release

```bash
task release:dry-run VERSION=0.1.8
```

The dry run executes the current gates and prints every mutating operation
without changing either repository.

### 4. Publish upstream and create the local formula handoff

```bash
uv run python scripts/release.py release 0.1.8 --tap ../homebrew-tap
```

This command:

1. updates and verifies all version sources;
2. commits the version bump;
3. creates the annotated `v0.1.8` tag;
4. pushes upstream `main` and the tag together;
5. builds and uploads the GitHub release sdist;
6. updates and commits `Formula/sive.rb` locally; and
7. stops before pushing the tap.

Do not re-tag a published version. If a release asset must change, publish a new
version so the formula URL and SHA remain immutable.

### 5. Build and attach the Homebrew bottle

Follow **Building and Releasing a Bottle** in
`../homebrew-tap/docs/DEVELOPMENT.md` for `sive`. Build from source, run the
formula test, create and upload the bottle, then add the matching `bottle do`
block to `Formula/sive.rb`.

The tap already contains the local formula-version commit from step 4. Commit
the bottle block separately so the artifact handoff remains auditable.

### 6. Gate and publish the tap

From the Sive repository:

```bash
task release:formula-verify
task release:preflight
```

Both commands must pass. The preflight may warn that the tap has local unpushed
commits; this is the expected final handoff. Then push from the tap repository:

```bash
cd ../homebrew-tap
git push origin main
```

Return to Sive and prove the published state:

```bash
cd ../sive
task release:preflight
```

### 7. Verify as a user

```bash
brew update
brew install peachlifeab/tap/sive
sive --version
brew test peachlifeab/tap/sive
```

The install output must say it is pouring the expected bottle rather than
building Sive from source.

## Recovery

- Before the upstream push: discard or amend the local version commit.
- After the upstream release but before the tap push: leave the old tap version
  published, fix the local formula/bottle handoff, and rerun preflight.
- After the tap push: restore the prior formula commit or publish a new patch
  version. Never move an existing release tag.
