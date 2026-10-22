# Using with pi

[pi](https://pi.dev) is a terminal coding agent. The Mellea Skills Compiler works
with it in two independent ways:

- **[Pi extension](#pi-extension)**: run `compile`, `validate`, `run`, and `certify`
  as slash commands from inside a pi session.
- **[Pi compilation backend](#pi-compilation-backend)**: use pi instead of Claude Code
  as the agent that performs compilation (`mellea-skills compile --backend pi`).

You can use either one without the other.

Neither is the `pi` export target. That one packages an already-compiled skill so pi
can load it as a skill. See [Exporting](EXPORTING.md#pi-target).

---

## Pi extension

The extension adds four slash commands to pi. Each one calls the `mellea-skills` CLI
and shows its output in the pi session:

| Command | Runs |
|---------|------|
| `/mellea-compile <path-to-spec.md> [flags...]` | `mellea-skills compile`, with the pi backend and this session's model |
| `/mellea-validate <compiled-skill-dir> [flags...]` | `mellea-skills validate` |
| `/mellea-run <compiled-skill-dir> [flags...]` | `mellea-skills run` |
| `/mellea-certify <compiled-skill-dir> [flags...]` | `mellea-skills certify` |

`/mellea-compile` compiles with the pi backend, using the provider and model currently
selected in your pi session. Pass `--backend`, `--provider` or `--model` to override
(for example, `--backend claude` to compile with Claude Code). Other flags are passed
through unchanged. See the [CLI reference](CLI.md) for what each command accepts.

### Prerequisites

- **pi 1.2.0 or later:**

    ```bash
    npm install -g --ignore-scripts @earendil-works/pi-coding-agent
    pi --version
    ```

- **`git`**, and either **[uv](https://docs.astral.sh/uv/)** or **Python 3.11 to
  3.14.3** (on Windows, the `py` launcher is enough), which the extension uses to
  install the compiler (see below).
- **A provider configured in pi** for compiling. See
  [Pi compilation backend](#pi-compilation-backend).
- **For `/mellea-run` and `/mellea-certify`:** an inference engine (Ollama or vLLM).
  See [Choose Inference Engine](INSTALLATION.md#choose-inference-engine).

Works on macOS, Linux and Windows. On Windows, `git` must be on `PATH` (Git for
Windows adds it), and long paths should be enabled
(`git config --global core.longpaths true`) because compiled packages nest deeply. WSL
also works.

### Install

```bash
pi install npm:mellea-skills-compiler-pi
```

This adds the extension to your global pi settings. Add `-l` to install it for the
current project only.

From a clone of this repo, `pi install ./extensions/pi` installs your local copy
instead, and `pi -e ./extensions/pi/extensions/mellea-skills.ts` loads it for one
session without installing.

**You don't need to install the `mellea-skills` CLI yourself.** The first time you run
any `/mellea-*` command, the extension clones the compiler at the release it was built
for, creates a Python environment, and installs the CLI into it, all under
`~/.cache/mellea-skills-compiler/<version>/` (`%USERPROFILE%\.cache\…` on Windows).
Each step is shown in the session as it
runs. This takes a few minutes, once per version. If setup is interrupted, the next
command starts again from scratch. If an existing install stops working, a new one is
built beside it and the old one is kept until the new one works, so a failed rebuild
(for example, offline) leaves the existing install in place. If two pi sessions start
at once, one installs and the other waits. To reset an install, delete that folder.

### Usage

The `/mellea-*` commands are pi slash commands, not shell commands. Start `pi` in the
folder that holds your skills; paths you pass are relative to it. Type `/` to see the
commands in autocomplete. With a spec at `weather/spec.md` (copied from this repo's
`skills/weather/`, for example):

```
/mellea-compile weather/spec.md
/mellea-validate weather/weather_mellea
/mellea-run weather/weather_mellea --input "What's the weather like in Dublin?"
/mellea-certify weather/weather_mellea
```

Each command shows a status indicator while it runs, then a single notification with
the CLI's output when it finishes. The compiled package is written next to the spec.

A flag value containing spaces can be wrapped in `"..."` or `'...'`, as in the
`--input` example above. This is a minimal quote-aware split, not a full shell parser:
backslash escapes and nested quotes are not supported.

### Known limitations

- **No cancellation.** A running `/mellea-*` command cannot be cancelled from inside the
  extension. Use pi's own process-level interrupt to stop one early.
- **No progress during a command, and no output in headless mode** (`pi -p`), where pi
  exits 0 even if the command failed. Use the `mellea-skills` CLI directly in scripts.
- **Compile time varies** with the model and pi's thinking level, from a couple of
  minutes to over half an hour. Resume a compile that stopped partway with
  `--repair-mode`.
- **Compiling writes next to the spec.** Compile from a copy if you don't want your
  skill folder changed.
- **The compile runs pi with `--approve`** inside the extension's own copy of the
  compiler, so that it can load the compiler's prompt templates. It does not do this in
  your own folders.

The extension's source and README are in
[`extensions/pi/`](https://github.com/generative-computing/mellea-skills-compiler/tree/main/extensions/pi).

---

## Pi compilation backend

`mellea-skills compile --backend pi` uses pi instead of Claude Code to run the
compilation. This section covers how to configure it for different providers.

### Choosing a provider

Pi reads custom providers from `models.json` in its agent folder: `~/.pi/agent/models.json`,
or `$PI_CODING_AGENT_DIR/models.json` if you set that variable. It does not read a file
from your working directory. The file can hold API keys, so keep it out of any git
repository. The right choice depends on how you are accessing your model:

| Situation | Provider setting | Notes |
|-----------|-----------------|-------|
| Direct Anthropic API key | `anthropic` (default) | Set `ANTHROPIC_API_KEY` |
| LiteLLM proxy / AWS Bedrock gateway | a name you choose, e.g. `anthropic-proxy` | Define it with `baseUrl` + `apiKey` in `models.json` |
| Ollama (local models) | `ollama` | Set `baseUrl` in `models.json` |

### Direct Anthropic API

No `models.json` needed. Export your key and compile:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
mellea-skills compile skills/weather/spec.md --backend pi
```

### LiteLLM proxy / AWS Bedrock gateway

If you access Claude through a LiteLLM proxy or an AWS Bedrock-based gateway, define
your own provider for it rather than using the built-in `anthropic`. Using `anthropic`
with a proxy key will produce an authentication error even if the key looks valid —
`anthropic` expects a real `ANTHROPIC_API_KEY`, not a proxy credential.

`anthropic-proxy` below is not a built-in pi provider; it is the name you give your
proxy, and any name works as long as you pass the same one to `--provider`. Add it to
`~/.pi/agent/models.json`, then check that `pi --list-models` shows it:

```json
{
  "providers": {
    "anthropic-proxy": {
      "baseUrl": "<your-litellm-proxy-url>",
      "api": "anthropic-messages",
      "apiKey": "<your-litellm-proxy-key>",
      "models": [
        {
          "id": "claude-sonnet-4-5",
          "reasoning": true,
          "input": ["text", "image"],
          "contextWindow": 200000,
          "maxTokens": 64000
        }
      ]
    }
  }
}
```

Then compile with:

```bash
mellea-skills compile skills/weather/spec.md --backend pi --provider anthropic-proxy
```

#### Still seeing errors? Add the `compat` key

If you still get this error after switching to `anthropic-proxy`:

```
API Error: 400 {"error":{"message":"{\"message\":\"tools.0.custom.eager_input_streaming:
Extra inputs are not permitted\"}...
```

Add a `"compat"` block to your provider entry to disable eager tool input streaming:

```json
{
  "providers": {
    "anthropic-proxy": {
      "baseUrl": "<your-litellm-proxy-url>",
      "api": "anthropic-messages",
      "apiKey": "<your-litellm-proxy-key>",
      "compat": { "supportsEagerToolInputStreaming": false },
      "models": [
        {
          "id": "claude-opus-4-6",
          "reasoning": true,
          "input": ["text", "image"],
          "contextWindow": 1050000,
          "maxTokens": 128000
        }
      ]
    }
  }
}
```

This disables a streaming feature that some AWS Bedrock-hosted deployments do not support.

### Ollama (local models)

> **Note:** Ollama support is experimental. Compilation quality may vary because the
> compiler prompts are tuned for Claude-class models. Use a capable ollama model
> (e.g. `granite4.2:30b`) for best results.

> **Terminal output during Ollama compile:** The terminal will show a "Processing…"
> spinner with no further output for the duration of the compile. This is expected —
> intermediate messages are only printed after each full model response completes, and
> large local models are slow to respond. The compile is still running; do not interrupt
> it. Output will appear once the first response finishes.

Add this to `~/.pi/agent/models.json`:

```json
{
  "providers": {
    "ollama": {
      "api": "openai-completions",
      "apiKey": "ollama",
      "baseUrl": "http://127.0.0.1:11434/v1",
      "models": [
        {
          "_launch": true,
          "id": "granite4.2:30b",
          "input": ["text"]
        }
      ]
    }
  }
}
```

Then compile with:

```bash
mellea-skills compile skills/weather/spec.md --backend pi --provider ollama --model granite4.2:30b
```

### Verifying credentials

Before running a compile, confirm pi has credentials for your provider:

```bash
pi auth check --provider anthropic          # direct Anthropic
pi auth check --provider anthropic-proxy    # your proxy provider
pi auth check --provider ollama             # local Ollama
```

Each should print `ready` when the credentials are correctly resolved. This only checks
that credentials resolve; it does not contact the provider, so `ready` doesn't mean the
endpoint is up. For Ollama, check the server directly:

```bash
curl -s http://127.0.0.1:11434/api/tags
```

### Troubleshooting

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `Authentication failed` or `401` when using `--provider anthropic` | Proxy key is not an `ANTHROPIC_API_KEY` | Define a proxy provider in `~/.pi/agent/models.json` with your proxy `baseUrl` and `apiKey`, and pass its name to `--provider` |
| `tools.0.custom.eager_input_streaming: Extra inputs are not permitted` | Older Bedrock deployment does not support this streaming feature | Already using your proxy provider? Add `"compat": { "supportsEagerToolInputStreaming": false }` to that provider block in `models.json` |
| Your provider is missing from `pi --list-models` | `models.json` is in the wrong place or misnamed | It must be `models.json` (plural) in `~/.pi/agent/`, or in `$PI_CODING_AGENT_DIR` if set |
| `pi auth check` prints `not ready` | Missing or mis-scoped credentials | Re-run `pi` and use `/login`, or set the correct environment variable for that provider |
| Compile starts then silently produces no output | Provider accepted the connection but the model rejected the request | The provider error message is printed to the terminal at the end of the compile run — scroll up to find it |
