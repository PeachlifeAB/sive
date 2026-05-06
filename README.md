# sive

Load secrets from your vault into your shell via [mise](https://mise.jdx.dev) — silent unlock after one-time setup, no daemon, no shell-specific glue code.

```
open terminal → secrets already in shell
open nvim     → AI keys already there
open new tab  → instant from local snapshot
```

> [!NOTE]
> **Status:** MVP in progress. The current working path is macOS + Vaultwarden/Bitwarden with `.sive` project config and encrypted local snapshots. Everything else is intentionally deferred until that path is proven solid.

---

## Why

Most secret-loading workflows are too manual (run `bw unlock`, export, re-source on every machine) or too magical (background daemons, fragile per-shell hooks). `sive` takes a simpler path:

- a secrets vault is the source of truth
- mise handles shell integration across all shells
- the OS keychain stores the unlock credential for silent unlock
- secrets are fetched out-of-band and cached in an encrypted local snapshot

The result should feel boring, reliable, and fast.

> **Vault support:** The MVP targets Bitwarden and Vaultwarden via the `bw` CLI. The design is vault-agnostic — `vaults.toml` is keyed by vault name and the backend is pluggable. Other vault providers (1Password, HashiCorp Vault, etc.) are deferred, not excluded.

---

## Design rules

| Rule | Detail |
|---|---|
| Vault is pluggable | MVP uses `bw` (Bitwarden/Vaultwarden). Server URL is always explicit — no silent fallback to a default cloud server. |
| Secrets are grouped into **tags** | `global`, `ai`, `projectX` — each tag maps to a folder in your vault |
| Tags are ordered, last wins on conflict | Declare from most general to most specific: `["global", "ai", "projectX"]` |
| Global identity secrets → shell mode | `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, etc. — loaded automatically |
| Sensitive project secrets → exec mode | Database URLs, payment keys — injected only into the subprocess that needs them |
| Encrypted local snapshot is the primary cache | AES-256-GCM, key stored in OS keychain — no plaintext secrets on disk |
| No daemon | No background service, no socket |

---

## How it works

### Shell mode

For always-on global secrets (AI keys, identity tokens, GitHub credentials).

When a new shell starts:

1. mise runs the `sive` env hook
2. `sive` reads the encrypted local snapshot — no vault calls on the hot path
3. decrypts using a key stored in the OS keychain
4. loads env vars into the shell instantly

The hook path reads the local encrypted snapshot only. It does not call the vault during shell startup.

### Exec mode _(Phase 3, not yet built)_

For sensitive project secrets that should not live in the shell.

```bash
sive run -- node server.js
```

Or with a `.sive` reference file committed to the repo:

```
DATABASE_URL=vault://personal:env/project-x/DATABASE_URL
STRIPE_API_KEY=vault://personal:env/project-x/STRIPE_API_KEY
```

---

## Setup

### Prerequisites

- macOS (MVP scope)
- [mise](https://mise.jdx.dev) installed
- Python 3.11+
- [gum](https://github.com/charmbracelet/gum) (`brew install gum`) — used for styled prompts and spinners; falls back to plain text if missing
- `bw` CLI (installed automatically by `sive setup` when needed)

### Install

```bash
brew install PeachlifeAB/tap/sive
```

Or install from source with uv:

```bash
git clone git@github.com:PeachlifeAB/sive.git
cd sive
uv sync
```

### First-time setup

```bash
sive setup
```

On a new machine, `sive setup` will:

1. Verify `bw` is installed and install it automatically if missing
2. Prompt for your vault server URL (required — no default)
3. Run `bw config server <url>` and `bw login`
4. Prompt once for your email and master password and store them in macOS Keychain
5. Validate silent unlock
6. Install or repair hidden shell integration as needed
7. Configure the current directory for the tags you select

`sive setup` is the only onboarding command users should run. It performs vault bootstrap internally when needed.

> [!IMPORTANT]
> `server` is always required in `~/.config/sive/vaults.toml`. There is no built-in default server. A missing `server` field is a config error.

Example `~/.config/sive/vaults.toml`:

```toml
[vaults.personal]
server = "https://vw.yourdomain.com"
```

---

## Usage

```bash
sive setup              # Main onboarding + configure current project directory
sive set KEY [value]    # Write a secret into the active project tag or an explicit --tag
sive --version
```

The internal `sive _mise-env` command is called by the mise hook. It reads the local encrypted snapshot only — no vault calls, no network. It always exits 0 and always emits valid JSON so shell startup is never broken.

Related docs:
- [Command contracts](docs/COMMAND-CONTRACTS.md)
- [User stories](docs/USER-STORIES.md)

---

## Tags

A tag is a named group of secrets stored in a vault folder. Tags are declared in order — last tag wins on key conflicts.

```toml
# .sive in project root
version = 1
vault = "personal"
tags = ["global", "ai", "projectX"]
```

```bash
# Configure the current project directory interactively
sive setup

# Write a secret into the active project context (prompts for value)
sive set STRIPE_KEY

# Write a secret into an explicit tag
sive set STRIPE_KEY sk_live_xxx --tag projectX
```

Tag folder mapping is internal — users only see tag names, never folder paths.

| Tag | Vault folder (Bitwarden/Vaultwarden) |
|---|---|
| `global` | `env/global` |
| `ai` | `env/ai` |
| `projectX` | `env/projectX` |

---

## Failure contract

If secret loading fails for any reason:

- `sive` returns `{}` to stdout
- emits one short warning to stderr
- exits `0`

The shell opens normally. A broken shell startup is worse than missing env vars.

---

## Project structure

```
sive/
├── hooks/
│   └── mise_env.lua          # Thin Lua bridge — calls sive _mise-env
├── metadata.lua               # mise plugin metadata
├── src/sive/
│   ├── cli.py                 # Entry point
│   ├── commands/
│   │   ├── setup.py           # sive setup
│   │   ├── refresh.py         # sive refresh
│   │   ├── set_secret.py      # sive set KEY [value]
│   │   ├── status.py          # sive status
│   │   └── mise_env.py        # sive _mise-env (called by hook)
│   └── core/
│       ├── bw.py              # bw CLI wrapper (Bitwarden/Vaultwarden)
│       ├── keychain_macos.py  # macOS Keychain via security(1)
│       ├── project_config.py  # .sive project file read/write
│       ├── snapshot.py        # Encrypted snapshot read/write
│       ├── snapshot_crypto.py # AES-256-GCM encryption primitives
│       ├── source_loader.py   # Resolves source strings to env dicts
│       ├── sync_state.py      # Background sync state and locking
│       ├── ui.py              # gum-based TUI with plain fallback
│       └── vaults.py          # Reads ~/.config/sive/vaults.toml
└── tests/
```

---

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
uv run pytest

# Baseline check
./bin/repo-state
```
