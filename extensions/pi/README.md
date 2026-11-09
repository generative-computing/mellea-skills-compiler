# Mellea Skills Compiler — pi extension

Compile, validate, run, and certify agent skills with the
[Mellea Skills Compiler](https://github.com/generative-computing/mellea-skills-compiler)
from inside a [pi](https://pi.dev) session. The extension adds four slash
commands: `/mellea-compile`, `/mellea-validate`, `/mellea-run`, and
`/mellea-certify`. You don't need to install the compiler yourself, the
extension sets it up the first time you use it.

## Prerequisites

You need:

- **pi 1.2.0 or later, with a model provider set up.** Run `pi` and use
  `/login`, or set your provider's API key (for example `ANTHROPIC_API_KEY`).
  `/mellea-compile` uses the model selected in your pi session. To install pi:

    ```bash
    npm install -g --ignore-scripts @earendil-works/pi-coding-agent
    pi --version
    ```

- **`git`**, and either **[uv](https://docs.astral.sh/uv/)** or **Python 3.11
  to 3.14.3** (on Windows, the `py` launcher is enough). The extension uses
  these to install the compiler.
- **Already using pi?** `npm install -g` replaces your global pi, and
  `pi install` writes to your shared agent folder (`~/.pi/agent`). To keep an
  existing pi setup as it is, install pi 1.2.0 into its own folder
  (`npm install --ignore-scripts @earendil-works/pi-coding-agent` there), put
  that folder's `node_modules/.bin` first on `PATH`, and set
  `PI_CODING_AGENT_DIR` to a separate folder before running `pi install`. Use
  `pi install -l` instead to install the extension for one project only.
- **Ollama (or vLLM), running, with the default models pulled.** Compiled
  skills run on Ollama, so `/mellea-run` and `/mellea-certify` need it.
  `/mellea-compile` and `/mellea-validate` also run one fixture as a smoke
  check; without Ollama that check is skipped and you'll see
  `ollama server not running`. Install Ollama from
  [ollama.com/download](https://ollama.com/download), start it, then pull the
  default models:

    ```bash
    ollama pull granite4.1:3b
    ollama pull ibm/granite3.3-guardian:8b
    ```

  Ollama is expected at `http://localhost:11434`. If yours is elsewhere, set
  `OLLAMA_HOST` to its URL before starting pi.
  For vLLM, see
  [Choose Inference Engine](https://generative-computing.github.io/mellea-skills-compiler/INSTALLATION/#choose-inference-engine).

## Quick start

1. Install the extension:

    ```bash
    pi install npm:@ibm/mellea-skills-compiler-pi
    ```

2. Make a folder with a skill to compile. This downloads the example
   `weather` skill (or download
   [`skills/weather/spec.md`](https://github.com/generative-computing/mellea-skills-compiler/tree/main/skills/weather)
   by hand):

    ```bash
    mkdir -p my-skills/skills/weather && cd my-skills
    curl -fsSL -o skills/weather/spec.md \
      https://raw.githubusercontent.com/generative-computing/mellea-skills-compiler/main/skills/weather/spec.md
    ```

3. Confirm pi has credentials for the provider you'll compile with:

    ```bash
    pi auth check --provider <provider>   # prints "ready" when configured
    ```

   If it doesn't, see
   [Verifying credentials](https://generative-computing.github.io/mellea-skills-compiler/PI_SETUP/#verifying-credentials).

4. Start pi in that folder, and check that `mellea-skills.ts` is listed under
   `[Extensions]` in the startup banner:

    ```bash
    pi
    ```

5. Inside the pi session, run the commands. These are pi slash commands, not
   shell commands; type `/` to see them in autocomplete.

    ```
    /mellea-compile skills/weather/spec.md
    /mellea-validate skills/weather/weather_mellea
    /mellea-run skills/weather/weather_mellea --input "What's the weather like in Dublin?"
    /mellea-certify skills/weather/weather_mellea
    ```

The first command takes a few extra minutes while the compiler is set up.
Compiling writes a `weather_mellea/` package and a `pyproject.toml` next to the
spec, and can take from a couple of minutes to over half an hour depending on
the model; use a frontier-class model, as smaller models often stop partway.
Each command shows a status indicator while it runs, then one notification
with the output.

pi's status bar shows your session's model, not the one being compiled with.
The compile prints the provider and model it used when it finishes, and records
them in `<package>_mellea/compile_metadata.json`.

## First run

The first `/mellea-*` command clones the compiler at the release this
extension was built for and installs it into its own Python environment under
`~/.cache/mellea-skills-compiler/<version>/`
(`%USERPROFILE%\.cache\mellea-skills-compiler\<version>\` on Windows). This
happens once per version. If setup is interrupted, the next command starts it
again. To reset, delete that folder.

On Windows, `git` must be on `PATH`, and long paths should be enabled
(`git config --global core.longpaths true`). WSL also works.

## Commands

| Command | Runs |
|---------|------|
| `/mellea-compile <path-to-spec.md or skill-dir> [flags...]` | `mellea-skills compile`, with the pi backend and this session's provider and model |
| `/mellea-validate <compiled-skill-dir> [flags...]` | `mellea-skills validate` |
| `/mellea-run <compiled-skill-dir> [flags...]` | `mellea-skills run` |
| `/mellea-certify <compiled-skill-dir> [flags...]` | `mellea-skills certify` |

Paths are relative to the folder pi was started in. Flags are passed to the
CLI unchanged; see the
[CLI reference](https://generative-computing.github.io/mellea-skills-compiler/CLI/).
On `/mellea-compile`, `--provider` and `--model` override the session's
provider and model: pass both, or pass only the one that matches your session.
A skill directory works in place of a spec file if it contains a `SKILL.md` or
`spec.md`; the package is then named after the directory. A flag value with spaces can be wrapped in `"..."` or
`'...'` (no backslash escapes or nested quotes).

## Known limitations

- **No cancellation.** Use pi's own interrupt to stop a running command.
- **No output in headless mode** (`pi -p`), where pi exits 0 even if the
  command failed. Use the `mellea-skills` CLI directly in scripts and CI.
- **A stopped compile** can be resumed with
  `/mellea-compile <spec> --repair-mode`.
- **Compiling writes next to the spec.** Compile from a copy if you don't want
  your skill folder changed.
- **The compile runs pi with `--approve`** inside the extension's own copy of
  the compiler, so it can load the compiler's prompt templates. It does not do
  this in your own folders.
- **`/mellea-run` before `/mellea-certify` runs without Guardian checks**, and
  shows a warning telling you to run `mellea-skills ingest` or `mellea-skills
  certify`. There is no `ingest` command in pi: run `/mellea-certify` on the
  compiled skill once, and later `/mellea-run` calls use its Guardian policy.

## Developing the extension

From the root of a clone of the
[repo](https://github.com/generative-computing/mellea-skills-compiler),
`pi install ./extensions/pi` installs your local copy, and
`pi -e ./extensions/pi/extensions/mellea-skills.ts` loads it for one session
without installing.
