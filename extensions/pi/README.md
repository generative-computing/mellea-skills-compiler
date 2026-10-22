# Mellea Skills Compiler — pi extension

Run the [Mellea Skills Compiler](https://generative-computing.github.io/mellea-skills-compiler/) `compile`, `validate`, `run`,
and `certify` commands from inside a [pi](https://pi.dev) session, as
`/mellea-compile`, `/mellea-validate`, `/mellea-run`, and `/mellea-certify`.

## Prerequisites

- **`git`**, and either **[uv](https://docs.astral.sh/uv/)** or **Python 3.11
  to 3.14.3** (on Windows, the `py` launcher from python.org's installer is
  enough). These are used to install the compiler on first use (see below).
- **pi 1.2.0 or later.**
- **For `/mellea-run` and `/mellea-certify`:** an inference engine (Ollama or
  vLLM). See the [Installation guide](https://generative-computing.github.io/mellea-skills-compiler/INSTALLATION/#choose-inference-engine).

Works on macOS, Linux and Windows. On Windows, `git` must be on `PATH`
(Git for Windows adds it), and long paths should be enabled
(`git config --global core.longpaths true`) because the compiled packages
nest deeply. WSL also works.

### The compiler is installed automatically

You don't need to install the `mellea-skills` CLI yourself. The first time
you run any `/mellea-*` command, the extension:

1. clones the compiler at the release this extension was built for,
2. creates a Python environment for it, and
3. installs `mellea-skills` into that environment,

all under `~/.cache/mellea-skills-compiler/<version>/`
(`%USERPROFILE%\.cache\mellea-skills-compiler\<version>\` on Windows). Each step is shown in
the session as it runs. This takes a few minutes and only happens once per
version; later commands reuse the install.

- **Interrupted setup:** the next command starts it again from scratch.
- **Broken install:** if an existing install stops working, a new one is built
  beside it, and the old one is only removed once the new one works. If the
  rebuild fails (for example, offline), the existing install is kept and you
  see a warning.
- **Several pi sessions:** if two sessions start at once, one installs and the
  other waits for it.
- **Reset:** delete `~/.cache/mellea-skills-compiler/<version>/`.

## Install

### 1. Install pi

If you don't already have the [pi](https://pi.dev) coding agent, install it
with one of:

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
```

Confirm it's on your `PATH`:

```bash
pi --version
```

### 2. Install this extension

From npm:

```bash
pi install npm:mellea-skills-compiler-pi
```

Or from the root of a local clone of this repo:

```bash
pi install ./extensions/pi
```

This adds the extension to your global pi settings, so it loads in every pi
session. Use `pi install -l ./extensions/pi` to install it for this project
only (`.pi/settings.json`) instead.

To try it for a single session without installing anything:

```bash
pi -e ./extensions/pi/extensions/mellea-skills.ts
```

### 3. Start a pi session

The `/mellea-*` commands are pi slash commands, **not** shell commands —
typing `/mellea-run ...` directly into zsh/bash will fail with
`no such file or directory`. Start pi from the folder that holds your skills;
paths you pass to the commands are relative to it:

```bash
pi
```

Check that `mellea-skills.ts` is listed under `[Extensions]` in pi's startup
banner, then type `/` in the session to see the four `/mellea-*` commands in
autocomplete.

## Commands

- `/mellea-compile <path-to-spec.md> [flags...]` — runs `mellea-skills compile`
  with the **pi backend**, using this session's current provider and model.
  The compiled package is written next to the spec. Pass `--backend`,
  `--provider` or `--model` to override (for example `--backend claude` to
  compile with Claude Code instead); other flags are passed through as-is
  (`--timeout`, `--repair-mode`, etc.).
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

Run these **inside a pi session**, with a skill spec at `weather/spec.md`
under the folder pi was started in (any skill from the
[`skills/`](https://github.com/generative-computing/mellea-skills-compiler/tree/main/skills)
directory works):

```
# Compile a spec into a Mellea pipeline, using this session's model
/mellea-compile weather/spec.md

# Validate the compiled skill (lints + fixture smoke-check)
/mellea-validate weather/weather_mellea

# Run it against a natural-language input (needs Ollama or vLLM running)
/mellea-run weather/weather_mellea --input "What's the weather like in Dublin?"

# Certify it (needs Ollama or vLLM running)
/mellea-certify weather/weather_mellea
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

- **No cancellation.** pi's per-command abort signal (`ctx.signal`) is only
  populated while the agent is actively streaming a turn, not during a
  command handler, so a running `/mellea-*` command cannot be cancelled from
  within the extension. Use pi's own process-level interrupt to stop one early.
- **No progress during a command.** A compile shows "Compiling..." until it
  finishes, then one notification with the CLI's output. In headless mode
  (`pi -p`) there is no output and pi exits 0 even if the command failed. Run
  the `mellea-skills` CLI directly for scripts and CI.
- **Compile time varies a lot** with the model and with pi's thinking level,
  from a couple of minutes to over half an hour for larger skills. A compile
  that stops partway can be resumed with `/mellea-compile <spec> --repair-mode`.
- **Compiling writes next to the spec**: a `<name>_mellea/` package and a
  `pyproject.toml`. Compile from a copy if you don't want your skill folder
  changed.
- **The compile trusts the managed install's pi config.** The compile runs pi
  with `--approve` inside the extension's own copy of the compiler
  (under `~/.cache/mellea-skills-compiler/<version>/`), so it can load the
  compiler's prompt templates. It does not do this in your own folders.
- **Export is experimental.** Exported skills can get a generic description,
  and the exported `run.sh` can drop arguments for some pipeline signatures.
  Check the exported `SKILL.md` and `scripts/run.sh` before sharing a bundle.
