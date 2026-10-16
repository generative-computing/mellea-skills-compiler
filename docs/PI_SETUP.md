# Pi Backend Setup

This guide covers how to configure the `--backend pi` compilation path for different
provider scenarios. It supplements the brief setup steps in the main README.

---

## Choosing a provider

Pi supports multiple providers via a `model.json` configuration file. The right choice
depends on how you are accessing Claude:

| Situation | Provider setting | Notes |
|-----------|-----------------|-------|
| Direct Anthropic API key | `anthropic` (default) | Set `ANTHROPIC_API_KEY` |
| LiteLLM proxy / AWS Bedrock gateway | `anthropic-proxy` | Set `baseUrl` + `apiKey` in `model.json` |
| Ollama (local models) | `ollama` | Set `baseUrl` in `model.json` |

---

## Direct Anthropic API

No `model.json` needed. Export your key and compile:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
mellea-skills compile skills/weather/spec.md --backend pi
```

---

## LiteLLM proxy / AWS Bedrock gateway

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

### Still seeing errors? Add the `compat` key

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

---

## Ollama (local models)

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

---

## Verifying credentials

Before running a compile, confirm pi can reach your provider:

```bash
pi auth check --provider anthropic          # direct Anthropic
pi auth check --provider anthropic-proxy    # LiteLLM / Bedrock proxy
pi auth check --provider ollama             # local Ollama
```

Each should print `ready` when the credentials are correctly resolved.

---

## Troubleshooting

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `Authentication failed` or `401` when using `--provider anthropic` | Proxy key is not an `ANTHROPIC_API_KEY` | Switch to `--provider anthropic-proxy` and configure `model.json` with your proxy `baseUrl` and `apiKey` |
| `tools.0.custom.eager_input_streaming: Extra inputs are not permitted` | Older Bedrock deployment does not support this streaming feature | Already on `anthropic-proxy`? Add `"compat": { "supportsEagerToolInputStreaming": false }` to that provider block in `model.json` |
| `pi auth check` prints `not ready` | Missing or mis-scoped credentials | Re-run `pi` and use `/login`, or set the correct environment variable for that provider |
| Compile starts then silently produces no output | Provider accepted the connection but the model rejected the request | The provider error message is printed to the terminal at the end of the compile run — scroll up to find it |
