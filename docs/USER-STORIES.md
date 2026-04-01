# sive — User Stories v2

---

## Core product rules

These rules apply to every story. Any story that violates one of them should be treated as wrong, not the rules.

* Secrets are grouped into **tags** — each tag is a named group stored in a Bitwarden folder
* Tags are declared in order, **last tag wins** on key conflict — declare from most general to most specific
* Tag names are the user-facing concept — internal folder paths (`env/global`) are an implementation detail
* Global identity secrets belong in **shell mode** — loaded automatically, always available
* Sensitive project and runtime secrets belong in **exec mode** — injected only into the subprocess that needs them
* Silent unlock is built around **keychain-stored master password**
* The **encrypted local snapshot** is the primary cache — AES-256-GCM, snapshot key in OS keychain, no plaintext secrets on disk
* The encrypted local snapshot is updated behind the scenes — users should not need a separate sync command in normal use
* Personal account plus org access in one session is the **primary path** — separate-account support is a later phase
* `sive` never writes plaintext secrets to disk
* **Vaultwarden is the primary tested deployment target** — official Bitwarden cloud works identically since the `bw` CLI is server-agnostic
* **Server URL is always explicitly configured** — there is no assumed default server; a missing `server` field in `vaults.toml` is a config error
* `sive setup` is the main onboarding command — it bootstraps vault auth if needed and configures the current project directory

---

## MVP stories

These must work before anything else is built.

---

### US-01 · Silent global env on shell startup `[MVP]`

*As a developer opening any new terminal, I want my global identity secrets loaded automatically without typing anything, so I can start working immediately.*

* mise activates `sive` on shell init via the `MiseEnv` hook
* shell hook reads the **encrypted local snapshot only** — no vault calls, no network on the hot path
* snapshot is decrypted using a key from the OS keychain (in-memory after first unlock — ~1ms)
* snapshot freshness is handled internally by Sive — users should not need a separate sync command in normal use
* if snapshot is missing or stale, `sive` warns once to stderr and loads nothing — shell still opens
* zero prompts after setup in normal operation
* global shell integration exists, but its mise wiring is an internal implementation detail, not a user-facing setup surface

**Acceptance:**
* reboot machine, open terminal, `echo $ANTHROPIC_API_KEY` returns value
* no prompt appears
* second terminal opens instantly — snapshot read is ~1ms
* secrets stay fresh without manual `sive refresh`

---

### US-02 · Reboot persistence `[MVP]`

*As a developer who reboots frequently, I want secrets available immediately after reboot without any manual step, so reboots do not interrupt my workflow.*

* master password stored in OS keychain survives reboots
* `bw` login state persists in its own config directory on disk
* on first shell after reboot, `sive` silently unlocks and loads env
* no manual `bw login` or `bw unlock` needed in normal operation after initial setup
* if account state changes (password changed, new device, org policy), `sive setup` re-authenticates

**Acceptance:**
* reboot, open terminal, env is available within 5 seconds, no prompt

---

### US-03 · One-time machine setup `[MVP]`

*As a developer configuring a new machine, I want a single guided setup command that stores my Bitwarden credentials securely, so I never have to authenticate manually again.*

* `sive setup` is the primary first-run command
* flow:
    1. checks `bw` is installed, installs via mise if missing
    2. reads `~/.config/sive/vaults.toml`, creates with `[vaults.personal]` stub if missing
    3. if machine bootstrap is missing, for each configured vault — **all prompts are mandatory, no defaults**:
        * prompts for server URL (e.g. `https://vw.yourdomain.com`) — no default
        * writes `server` into `vaults.toml`
        * runs `bw config server <url>`
        * runs `bw login` interactively
        * prompts once for master password and stores it in the OS keychain
* validates silent unlock with `bw unlock --passwordenv SIVE_BW_PASSWORD --raw`
        * generates snapshot encryption key and stores it in the OS keychain
        * runs initial `sive refresh` to populate the snapshot
    4. installs or repairs hidden mise-based shell integration if needed
    5. prompts for which tags to load for the current directory
    6. writes `.sive` in the project root
* both commands are safe to re-run — idempotent

**Acceptance:**
* clean machine, run `sive setup`, open new shell, env is available
* re-running `sive setup` does not break existing config or snapshot
* `cd myproject && sive setup` writes `.sive` with selected tags

---

### US-04 · Graceful degradation `[MVP]`

*As a developer working offline or with connectivity issues, I want my shell to still open normally, so vault problems never block my work.*

* if secret loading fails for any reason, shell startup still succeeds
* `sive` emits one short line to stderr, nothing to stdout
* no blocking prompt
* no crash, no stack trace in normal operation
* internal diagnostics can still show degraded state when needed
* `SIVE_DEBUG=true` enables full stack traces for debugging

**Acceptance:**
* disconnect network, open new shell — shell opens, single warning appears, no crash
* misconfigured vault — shell opens, single warning, no crash
* missing keychain entry — shell opens, single warning, no crash

---

### US-05 · Internal observability `[MVP]`

*As a maintainer, I want internal diagnostics to show what sive is doing and what state it is in, so problems can be diagnosed without guessing.*

* internal diagnostics output:

```
sive 0.1.0

Active sources:
  personal.folder:env/global   14 vars   cache 4m old
  personal.folder:env/ai        3 vars   cache 4m old

Vaults:
  personal   unlocked   https://vw.yourdomain.com   synced 4m ago

Cache: fresh (TTL 8h, expires in 7h 56m)
```

* diagnostics never print secret values, only names and counts
* shows degraded state clearly when vault is unreachable or cache is stale

---

### US-16 · Self-hosted vault support `[MVP]`

*As a developer running a self-hosted Vaultwarden instance, I want sive to connect to my own server by default, so I am not dependent on Bitwarden cloud.*

* server URL is always explicitly configured in `vaults.toml` — no assumed default:

```toml
[vaults.personal]
server = "https://vw.yourdomain.com"
```

* a missing `server` field is a config error, not a silent fallback to `vault.bitwarden.com`
* when bootstrap is needed, `sive setup` prompts for server URL — the prompt has no pre-filled default
* `bw config server <url>` is called before every login
* Vaultwarden is the tested and supported primary deployment target
* official Bitwarden cloud works identically — `bw` CLI is server-agnostic after `bw config server`
* self-signed TLS supported via `NODE_EXTRA_CA_CERTS` passthrough configured in `sive setup`

**Note:** verify early in the MVP spike that your Vaultwarden instance requires no non-standard `bw config` beyond `bw config server`. If SSO, device approval, or non-standard auth flows are in use, test these in the auth spike before building anything else.

**Acceptance:**
* `vaults.toml` with no `server` field → bootstrap inside `sive setup` errors clearly, does not silently default
* when bootstrap is needed, `sive setup` prompts for server URL with no pre-filled value
* after setup pointing at a Vaultwarden instance, all MVP flows work identically to official Bitwarden cloud

---

## Phase 1 stories — shared and team sources

These come after MVP is stable.

---

### US-06 · Personal and team secrets in one session `[Phase 1]`

*As a developer who belongs to a Bitwarden organisation, I want personal secrets and team-shared secrets loaded together from a single login session, so I do not manage multiple logins manually.*

* personal secrets come from **folders** in the personal vault
* shared and team secrets come from **collections** in the organisation vault
* both are accessible from a single `bw` session — one login, one session key
* `sive` resolves each source type correctly:
    * `personal.folder:env/global` → `bw list items --folderid <id>`
    * `personal.collection:env/team-shared` → `bw list items --collectionid <id>`
* sources are merged in declared order, later entries win on conflict

**Acceptance:**
* one `bw login`
* diagnostics show vars from both a personal folder and an org collection
* no second login required

---

### US-07 · Per-project context switching `[Phase 1]`

*As a developer switching between projects, I want the active secret context to change automatically when I enter a project directory, so I never manually export variables.*

* project root `.sive` declares which non-sensitive tags to load:

```toml
version = 1
vault = "personal"
tags = ["global", "project-x"]
```

* `sive` loads the project tags on directory entry via the global mise hook
* on directory exit, project-specific vars are unloaded by mise
* works across bash, zsh, fish, nushell — mise handles all shell differences

**Important constraint:** only sources that are acceptable to load into the shell go here. Sensitive runtime secrets belong in US-09.

**Acceptance:**
* `cd project-x` → `echo $PROJECT_X_API_HOST` returns value
* `cd ..` → variable is unloaded

---

## Phase 2 stories — profile composition

---

### US-08 · Bitwarden-stored profiles `[Phase 2]`

*As a developer, I want a named profile to define a set of secret sources, so I can switch context with one word instead of maintaining long source lists on every machine.*

* profiles are Secure Notes stored in `env/profiles/<name>` in the personal vault
* profile content is a list of typed source lines:

```
personal.folder:env/global
personal.folder:env/ai
personal.collection:env/team-acme
personal.collection:env/project-x
```

* profiles live in Bitwarden and sync to every machine automatically
* no per-machine profile config is needed
* `.sive` references a profile name instead of a source list:

```toml
version = 1
profile = "project-x"
```

* sources are merged in declared order within the profile

**Acceptance:**
* update profile note in Bitwarden on machine A
* run `sive sync` on machine B
* machine B now loads the updated source set

---

### US-09 · Profile selection `[Phase 2]`

*As a developer, I want to switch my active profile manually, so I can change context without changing directory.*

* `sive use <profile>` writes the profile into the current project's `.sive`
* `sive use --global <profile>` writes it into Sive-managed global config
* mise picks up the change on the next prompt — no new shell required
* `sive use` without arguments shows the currently active profile

**Note:** `sive use` changes config and triggers a mise refresh. It does not directly mutate the current shell's env — that is a process boundary constraint, not a product limitation.

---

## Phase 3 stories — LLM-safe exec mode

---

### US-10 · Sensitive project secrets via exec mode `[Phase 3]`

*As a developer using AI coding tools, I want sensitive project secrets injected only into the process that needs them, so LLMs and other tools running in my shell cannot read them from the environment.*

* `sive run -- <command>` resolves secrets and injects them only into that subprocess
* the shell environment never contains the plaintext values
* the subprocess sees `process.env.STRIPE_API_KEY` normally — no app changes needed
* plaintext values exist only in subprocess memory for the lifetime of that process
* LLM tools, terminal sessions, and other shell children cannot see the values

**Product rule:** this is the mandatory path for:
* database credentials
* payment API keys
* third-party service secrets
* anything that should not be visible to AI tools in the terminal

**Acceptance:**
* `printenv STRIPE_API_KEY` in the shell → empty
* `sive run -- printenv STRIPE_API_KEY` → value appears

---

### US-11 · Reference files `[Phase 3]`

*As a developer, I want a committed file in my project that declares what secrets it needs without containing any values, so the file is safe to check in and documents the project's secret requirements.*

* `.sive` file in project root contains only reference strings:

```
STRIPE_API_KEY=bw://personal.collection:env/project-x/STRIPE_API_KEY
DATABASE_URL=bw://personal.collection:env/project-x/DATABASE_URL
PORT=8080
```

* safe to commit — contains zero plaintext secrets
* `sive run` reads `.sive` automatically if present in cwd
* acts as the canonical secret manifest for the project
* plain values (no `bw://` prefix) are passed through as-is

**Acceptance:**
* `cat .sive` shows only references
* `sive run -- node server.js` launches with resolved values in subprocess

---

## Phase 4 stories — write path

---

### US-12 · Write secrets from the CLI `[Phase 1]`

*As a developer, I want to create or update a secret from the terminal, so I never open the Bitwarden web UI for dev workflow secrets.*

* `sive set <VAR> [value] --tag <name>` — without `--tag`, default comes from the active `.sive` project context
* if value is omitted, prompts securely with no echo
* creates a new Secure Note if the item does not exist
* updates the existing Secure Note if it does
* warns at write time if the key exists in another tag that would override it:
    * `Warning: GITHUB_TOKEN also exists in 'projectX' — projectX loads after global, so projectX wins`
* runs `sive refresh` automatically after write so snapshot is immediately current
* never echoes the value back to stdout

**Acceptance:**
* `sive set GITHUB_TOKEN --tag global`
* prompts for value
* next new shell has `GITHUB_TOKEN` available without manual refresh

---

### US-13 · List and inspect `[Phase 4]`

*As a developer, I want to see what is currently loaded and where it comes from, so I can diagnose env issues without opening Bitwarden.*

* `sive list` shows all currently loaded var names and their source, never values:

```
ANTHROPIC_API_KEY   personal.folder:env/ai
GITHUB_TOKEN        personal.folder:env/global
STRIPE_API_KEY      personal.collection:env/project-x
```

* `sive list --profile <name>` shows what a named profile would load
* `sive list --source <source>` shows what a single source contains

---

### US-14 · Force cache refresh `[Phase 4]`

*As a developer, I want to force a cache refresh after updating a secret, so I do not have to wait for the normal TTL to expire.*

* `sive sync` runs `bw sync` against all configured vaults and clears mise `env_cache`
* `sive sync --vault <name>` limits the sync to one configured vault
* next shell prompt reloads from Bitwarden
* per-source TTL configuration is a later enhancement

---

## Phase 5 stories — multiple accounts and servers

---

### US-15 · Multiple Bitwarden accounts `[Phase 5]`

*As a developer with more than one Bitwarden account, I want sive to manage multiple account sessions transparently, so I can source secrets from any of them.*

* `vaults.toml` supports multiple named account entries:

```toml
[vaults.personal]
server = "https://vault.bitwarden.com"

[vaults.acme]
server = "https://bw.acme.com"
appdata_dir = "~/.local/share/sive/vaults/acme"
```

* each account with a unique `appdata_dir` gets its own isolated `bw` state
* each account gets its own keychain entry
* bootstrap inside `sive setup` runs `bw login` once per configured account when needed
* source references use the vault name as prefix: `acme.collection:env/project-x`
* `sive` routes each `bw` call to the correct account automatically

---

## Phase 6 stories — cross-platform and onboarding polish

---

### US-17 · Linux keychain support `[Phase 6]`

*As a developer on Linux, I want sive to store credentials securely using the system secret store, so the experience is equivalent to macOS.*

* uses `secret-tool` via `libsecret` where available
* falls back to a locked encrypted file on headless servers where no secret-tool is available
* keychain backend is selected automatically at runtime

---

### US-18 · Windows support `[Phase 6]`

*As a developer on Windows, I want sive to work natively, so I can use the same tool regardless of OS.*

* uses Windows Credential Manager via `keyring` Python package
* `bw` installed via mise on Windows as before
* tested on PowerShell and Git Bash

---

### US-19 · One-command bootstrap `[Phase 6]`

*As a developer setting up sive for the first time, I want one command to install everything, so onboarding takes under five minutes on any supported machine.*

```bash
curl -fsSL https://get.sive.dev | sh
```

* installs mise if missing, using the official mise installer
* installs `bw` via mise
* installs the `sive` mise plugin
* runs `sive setup` interactively
* shell rc is patched if mise activate is missing
* safe to re-run

---

## Non-goals — revised and precise

* No background daemon or persistent process
* No plaintext secrets written to disk **by sive** — `bw` manages its own encrypted vault cache independently
* No shell-specific integration code — mise handles all shell differences
* No reimplementing Bitwarden sync — `bw sync` owns that
* No managing non-secret configuration — sive is for secrets only
* No Bitwarden Secrets Manager dependency — Bitwarden Password Manager only, including personal vault and organisation collections
* No auto-injecting sensitive project/runtime secrets into the shell environment — that is exec mode's job

---

## Story to phase map

| Story | Description | Phase |
|---|---|---|
| US-01 | Silent global env on shell startup | MVP |
| US-02 | Reboot persistence | MVP |
| US-03 | One-time machine setup via `sive setup` (with implicit bootstrap) | MVP |
| US-04 | Graceful degradation | MVP |
| US-05 | Status and observability | MVP |
| US-16 | Self-hosted vault support | MVP |
| US-12 | Write secrets from the CLI (`sive set`) | Phase 1 |
| US-06 | Personal and team secrets in one session | Phase 1 |
| US-07 | Per-project context switching | Phase 1 |
| US-08 | Bitwarden-stored profiles | Phase 2 |
| US-09 | Profile selection | Phase 2 |
| US-10 | Sensitive project secrets via exec mode | Phase 3 |
| US-11 | Reference files | Phase 3 |
| US-13 | List and inspect | Phase 4 |
| US-14 | Force cache refresh | Phase 4 |
| US-15 | Multiple Bitwarden accounts | Phase 5 |
| US-17 | Linux keychain support | Phase 6 |
| US-18 | Windows support | Phase 6 |
| US-19 | One-command bootstrap | Phase 6 |
