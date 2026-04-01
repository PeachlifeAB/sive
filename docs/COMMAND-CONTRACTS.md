# Sive command contracts

This document defines the intended public UX contracts for the commands users interact with directly. These contracts are product-facing and should avoid leaking the underlying `mise` integration layer in the normal path.

---

## `sive setup`

### Purpose
Configure the current directory for Sive. This is the main public onboarding command.

### Product rule
- Users should run `sive setup`.
- `sive setup` may bootstrap machine auth implicitly if required.
- The public project artifact is `.sive`.
- Users should not be told about `mise.toml`, `mise env`, or `mise trust` in the normal path.

### First-time flow on a new machine
```bash
cd myproject
sive setup
```

Expected behavior:
1. Detect whether machine bootstrap already exists.
2. If missing, prompt for required vault/bootstrap information.
3. Complete auth, keychain storage, and hidden shell-integration setup.
4. Prompt for project tags.
5. Write `.sive` in the current directory.
6. Generate any hidden integration state required for mise.
7. Print a Sive-native success message.

Example success message:
```text
This directory is now configured for tags: global, myproject
Secrets will be available automatically in new shells.
Run 'sive refresh' after vault changes.
```

### Repeat flow in another repo
```bash
cd another-project
sive setup
```

Expected behavior:
1. Detect that machine bootstrap already exists.
2. Skip auth prompts.
3. Prompt for project tags or preload prior defaults.
4. Write `.sive`.
5. Update hidden integration state.
6. Print success.

### Re-run flow in an already configured repo
```bash
sive setup
```

Expected behavior:
1. Read existing `.sive`.
2. Show or preload the current tags.
3. Allow the user to confirm or edit them.
4. Rewrite `.sive` only if the config changed.

### Failure contract
- Failures should stay Sive-native whenever possible.
- If hidden activation cannot complete, explain the Sive-level problem and the Sive-level recovery path.
- Do not default to raw `mise` remediation language unless there is no safer product-level alternative.

Example fallback message:
```text
Sive saved this directory's configuration, but automatic activation could not be completed.
Please retry `sive setup`.
```

---

## `sive set`

### Purpose
Create or update a secret in the active project context or an explicit tag.

### Product rule
- If the key is provided but the value is omitted, Sive prompts securely for the value.
- Without `--tag`, the default write target comes from the active `.sive` project context.
- Secret values must never be echoed back to the terminal.

### Interactive default
```bash
sive set OPENAI_API_KEY
```

Expected behavior:
1. If `--tag` is provided, use it.
2. Otherwise read `.sive` for the current directory.
3. If `.sive` is missing, fail and instruct the user to run `sive setup` or provide `--tag`.
4. If `.sive` contains multiple tags, use the last tag in the list as the writable target.
5. Prompt securely for the value.
6. Write the secret to the target tag.
7. Attempt to update the local snapshot for that tag immediately after the vault write.

Example prompt and success flow:
```text
Setting OPENAI_API_KEY for tag: myproject
Value for OPENAI_API_KEY: ********

Saved OPENAI_API_KEY to tag: myproject
Local snapshot updated.
```

### Inline value
```bash
sive set OPENAI_API_KEY sk-123
```

Warning: inline secrets can leak through shell history and process listings. Prefer `--stdin` for CI or other non-interactive use. Use inline values only for testing or non-sensitive data.

Expected behavior:
1. Resolve the target tag from `.sive` or `--tag`.
2. Use the supplied value without prompting.
3. Save the secret and print a short Sive-native success message.

Example success:
```text
Saved OPENAI_API_KEY to tag: myproject
```

### Non-interactive scripting
```bash
printf 'sk-123' | sive set OPENAI_API_KEY --stdin
```

Expected behavior:
- Support at least one explicit non-interactive input path such as `--stdin`.
- In non-interactive contexts, do not fall back to prompting.

If no value is available non-interactively, fail clearly:
```text
No value provided.
Pass a value as an argument, use --stdin, or run interactively.
```

---

## Relationship between the commands

- `sive setup` defines the directory's read context via `.sive`.
- `sive set` uses that context to determine the default write target when `--tag` is absent.
