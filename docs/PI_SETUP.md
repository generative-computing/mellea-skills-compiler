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
| `/mellea-compile <path-to-spec.md> [flags...]` | `mellea-skills compile` |
| `/mellea-validate <compiled-skill-dir> [flags...]` | `mellea-skills validate` |
| `/mellea-run <compiled-skill-dir> [flags...]` | `mellea-skills run` |
| `/mellea-certify <compiled-skill-dir> [flags...]` | `mellea-skills certify` |

Flags are passed through to the CLI unchanged. See the [CLI reference](CLI.md) or
`mellea-skills <command> --help` for what each command accepts.

### Prerequisites

- **The `mellea-skills` CLI on your `PATH`.** The extension does not install it. Follow
  the [Installation](INSTALLATION.md) guide, then confirm:

    ```bash
    mellea-skills version
    ```

- **pi 1.2.0.** The extension is tested against this version only:

    ```bash
    npm install -g --ignore-scripts @earendil-works/pi-coding-agent@1.2.0
    pi --version
    ```

- **Whatever the underlying commands need.** `/mellea-compile` needs a configured
  compilation backend (Claude Code by default), and `/mellea-certify` needs an inference
  engine (Ollama or vLLM). The extension reports a missing `mellea-skills` CLI, but it
  does not check for these.

### Install

From the root of a clone of this repo:

```bash
pi install ./extensions/pi
```

This adds the extension to your global pi settings. Add `-l` (for example,
`pi install -l ./extensions/pi`) to install it for the current project only.

To try it for one session without installing:

```bash
pi -e ./extensions/pi/extensions/mellea-skills.ts
```

### Usage

The `/mellea-*` commands are pi slash commands, not shell commands. Start `pi` first.
To use the example paths below, start it from the repo root. Type `/` to see the
commands in autocomplete.

```
/mellea-compile skills/weather/spec.md
/mellea-validate examples/weather/weather_mellea
/mellea-run examples/weather/weather_mellea --input "What's the weather like in Dublin?"
/mellea-certify examples/weather/weather_mellea
```

Each command shows a status indicator while it runs, then a single notification with
the CLI's output when it finishes.

A flag value containing spaces can be wrapped in `"..."` or `'...'`, as in the
`--input` example above. This is a minimal quote-aware split, not a full shell parser:
backslash escapes and nested quotes are not supported.

### Known limitations

- **No auto-install.** A missing `mellea-skills` CLI is reported as an error that points
  to the install docs. The extension does not install anything for you.
- **No cancellation.** A running `/mellea-*` command cannot be cancelled from inside the
  extension. Use pi's own process-level interrupt to stop one early.

The extension's source and README are in
[`extensions/pi/`](https://github.com/generative-computing/mellea-skills-compiler/tree/main/extensions/pi).

---

## Pi compilation backend

`mellea-skills compile --backend pi` uses pi instead of Claude Code to run the
compilation. This section covers how to configure it for different providers.

### Choosing a provider

Pi supports multiple providers via a `model.json` configuration file. The right choice
depends on how you are accessing Claude:

| Situation | Provider setting | Notes |
|-----------|-----------------|-------|
| Direct Anthropic API key | `anthropic` (default) | Set `ANTHROPIC_API_KEY` |
| LiteLLM proxy / AWS Bedrock gateway | `anthropic-proxy` | Set `baseUrl` + `apiKey` in `model.json` |
| Ollama (local models) | `ollama` | Set `baseUrl` in `model.json` |

### Direct Anthropic API

No `model.json` needed. Export your key and compile:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
mellea-skills compile skills/weather/spec.md --backend pi
```

### LiteLLM proxy / AWS Bedrock gateway

If you access Claude through a LiteLLM proxy or an AWS Bedrock-based gateway, use
`--provider anthropic-proxy` rather than the default `anthropic`. Using `anthropic`
with a proxy key will produce an authentication error even if the key looks valid —
`anthropic` expects a real `ANTHROPIC_API_KEY`, not a proxy credential.

Create or update a `model.json` file (pi looks for this in your working directory):

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

Before running a compile, confirm pi can reach your provider:

```bash
pi auth check --provider anthropic          # direct Anthropic
pi auth check --provider anthropic-proxy    # LiteLLM / Bedrock proxy
pi auth check --provider ollama             # local Ollama
```

Each should print `ready` when the credentials are correctly resolved.

### Troubleshooting

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `Authentication failed` or `401` when using `--provider anthropic` | Proxy key is not an `ANTHROPIC_API_KEY` | Switch to `--provider anthropic-proxy` and configure `model.json` with your proxy `baseUrl` and `apiKey` |
| `tools.0.custom.eager_input_streaming: Extra inputs are not permitted` | Older Bedrock deployment does not support this streaming feature | Already on `anthropic-proxy`? Add `"compat": { "supportsEagerToolInputStreaming": false }` to that provider block in `model.json` |
| `pi auth check` prints `not ready` | Missing or mis-scoped credentials | Re-run `pi` and use `/login`, or set the correct environment variable for that provider |
| Compile starts then silently produces no output | Provider accepted the connection but the model rejected the request | The provider error message is printed to the terminal at the end of the compile run — scroll up to find it |
