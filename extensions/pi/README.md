# Mellea Skills Compiler — pi extension

Run the [Mellea Skills Compiler](../../README.md) `compile`, `validate`, `run`,
and `certify` commands from inside a [pi](https://pi.dev) session, as
`/mellea-compile`, `/mellea-validate`, `/mellea-run`, and `/mellea-certify`.

## Prerequisites

This extension shells out to the `mellea-skills` CLI — it does not bundle or
install it. Before using `/mellea-compile` or `/mellea-certify`, install the
compiler following the [main README's Install section](../../README.md#installation)
(`pip install -e .` from a clone of this repo), and confirm `mellea-skills`
resolves on your `PATH`:

```bash
mellea-skills version
```

Claude Code and an inference engine (Ollama or vLLM) are also required by the
underlying CLI — see the main README for setup. This extension does not
install any of these for you; if a command isn't found, it reports which one
and points back here.

## Install

### 1. Install pi

If you don't already have the [pi](https://pi.dev) coding agent, install it
with one of:

```bash
# macOS / Linux
curl -fsSL https://pi.dev/install.sh | sh

# or via npm
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
```

Confirm it's on your `PATH`:

```bash
pi --version
```

### 2. Install this extension

From the root of a local clone of this repo:

```bash
pi install ./extensions/pi
```

This adds the extension to your global pi settings, so it loads in every pi
session. Use `pi install -l ./extensions/pi` to install it for this project
only (`.pi/settings.json`) instead. Once this package is published, it will
also be installable from a git/npm source — see pi's package docs.

To try it for a single session without installing anything:

```bash
pi -e ./extensions/pi/extensions/mellea-skills.ts
```

### 3. Start a pi session

The `/mellea-*` commands are pi slash commands, **not** shell commands —
typing `/mellea-run ...` directly into zsh/bash will fail with
`no such file or directory`. Start pi first, from the repo root so the
example paths below resolve:

```bash
pi
```

Check that `mellea-skills.ts` is listed under `[Extensions]` in pi's startup
banner, then type `/` in the session to see the four `/mellea-*` commands in
autocomplete.

## Commands

- `/mellea-compile <path-to-spec.md> [flags...]` — runs `mellea-skills compile`.
  Flags are passed through as-is; see `mellea-skills compile --help` for the
  full list (`--backend`, `--model`, `--timeout`, `--repair-mode`, etc.).
- `/mellea-validate <compiled-skill-dir> [flags...]` — runs `mellea-skills
  validate` (Step 7 lints + fixture smoke-check). Flags are passed through
  as-is; see `mellea-skills validate --help` (`--no-run`, `--all`).
- `/mellea-run <compiled-skill-dir> [flags...]` — runs `mellea-skills run`
  against a compiled pipeline. Flags are passed through as-is; see
  `mellea-skills run --help` (`--fixture`, `--input`, `--enforce`,
  `--no-guardian`, `--guardian-model`, `--inference-engine`).
- `/mellea-certify <compiled-skill-dir> [flags...]` — runs `mellea-skills
  certify`. Flags are passed through as-is; see `mellea-skills certify
  --help` (`--enforce`, `--inference-engine`, `--risk-model`,
  `--guardian-model`, etc.).

## Examples

Run these **inside the pi session** started from the repo root (paths are
relative to pi's working directory):

```
# Compile a spec into a Mellea pipeline (needs Claude Code configured)
/mellea-compile skills/weather/spec.md

# Validate a compiled skill (lints + fixture smoke-check)
/mellea-validate examples/weather/weather_mellea

# Run a compiled skill against a natural-language input
/mellea-run examples/weather/weather_mellea --input "What's the weather like in Dublin?"

# Certify a compiled skill (needs Ollama or vLLM running)
/mellea-certify examples/weather/weather_mellea
```

Each command shows a status indicator while it runs, then a single
notification with the CLI's output once it finishes.

Command names are prefixed with `mellea-` to avoid colliding with other pi
extensions or with pi's own built-in commands (pi ships a built-in `/export`,
for example — a generic name like `/run` or `/export` is exactly the kind of
name another package could plausibly also claim).

A flag value containing spaces can be quoted with `"..."` or `'...'`, e.g.:

```
/mellea-run <compiled-skill-dir> --input "What's the weather like in Dublin?"
```

This is a minimal quote-aware split (no backslash escapes, no nested
quotes) — not a full shell parser — but it's enough for the common case of
a natural-language `--input` value or a `--input '{"json": "value"}'`
payload.

## Known limitations

- No auto-install: missing `mellea-skills`, Claude Code, or an inference
  engine surfaces as an error with a pointer to setup docs, not an automatic
  fix.
- No cancellation: pi's per-command abort signal (`ctx.signal`) is only
  populated while the agent is actively streaming a turn, not during a
  command handler — so a long-running `/mellea-compile`, `/mellea-validate`,
  `/mellea-run`, or `/mellea-certify` cannot currently be cancelled from
  within the extension. Use pi's own process-level interrupt if you need to
  stop one early.
