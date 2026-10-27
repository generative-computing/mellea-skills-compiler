# Using with pi

[pi](https://pi.dev) is a terminal coding agent. The Mellea Skills Compiler works
with it in two independent ways:

- **[Pi extension](#pi-extension)**: run `compile`, `validate`, `run`, and `certify`
  as slash commands from inside a pi session.
- **[Pi compilation backend](https://github.com/generative-computing/mellea-skills-compiler#compile-agent-skill---option-1-recommended)**:
  use pi instead of Claude Code as the agent that performs compilation from a clone
  of this repo. Setup is in
  [Pi Setup](https://github.com/generative-computing/mellea-skills-compiler#pi-setup)
  in the repo README; see [Choosing a provider](#choosing-a-provider) below for
  provider configuration.

You can use either one without the other.

Neither is the `pi` export target. That one packages an already-compiled skill so pi
can load it as a skill. See [Exporting](EXPORTING.md#pi-target).

---

## Pi extension

The extension adds four slash commands to pi. Each one calls the `mellea-skills` CLI
and shows its output in the pi session. You don't need to install the CLI yourself,
the extension sets it up the first time you use it.


### Pre-requisites

- **pi 1.2.0 or later, with a model provider set up** (run `pi` and use `/login`, or
  set your provider's API key). To install pi:

    ```bash
    npm install -g --ignore-scripts @earendil-works/pi-coding-agent
    pi --version
    ```

- **`git`**, and either **[uv](https://docs.astral.sh/uv/)** or **Python 3.11 to
  3.14.3** (on Windows, the `py` launcher is enough). The extension uses these to
  install the compiler.
- **Ollama (or vLLM), running, with the default models pulled.** Compiled skills run
  on Ollama, so `/mellea-run` and `/mellea-certify` need it. `/mellea-compile` and
  `/mellea-validate` also run one fixture as a smoke check; without Ollama that check
  is skipped and you'll see `ollama server not running`. Install Ollama from
  [ollama.com/download](https://ollama.com/download), start it, then pull the default
  models:

    ```bash
    ollama pull granite4.1:3b
    ollama pull ibm/granite3.3-guardian:8b
    ```

  Ollama is expected at `http://localhost:11434`. If yours is elsewhere, set both
  `OLLAMA_HOST` (used by the compiled skill) and `OLLAMA_API_URL` (used for
  certification's risk and Guardian checks) to its URL before starting pi. For vLLM,
  see [Choose Inference Engine](INSTALLATION.md#choose-inference-engine).

### Quick start

From a clone of this repo, simply doing `pi install ./extensions/pi` installs your local copy instead. The extension's source is in
[`extensions/pi/`](https://github.com/generative-computing/mellea-skills-compiler/tree/main/extensions/pi). However, if you've NOT ALREADY CLONED the repo, you can use the steps below:

1. Install the extension:

    ```bash
    pi install npm:@ibm/mellea-skills-compiler-pi
    ```

2. Make a folder with a skill to compile, for example the `weather` skill from this
   repo:

    ```bash
    mkdir -p my-skills/skills/weather && cd my-skills
    curl -fsSL -o skills/weather/spec.md \
      https://raw.githubusercontent.com/generative-computing/mellea-skills-compiler/main/skills/weather/spec.md
    ```

3. Confirm pi has credentials for the provider you'll compile with
      ```
      pi auth check --provider <provider>   # prints "ready" when configured
      ```
   If not properly configured, see [Verifying credentials](#verifying-credentials) below.

4. Start pi in that folder, and check that `mellea-skills.ts` is listed under
   `[Extensions]` in the startup banner:

    ```bash
    pi
    ```

5. Inside the pi session, run the commands. These are pi slash commands, not shell
   commands; type `/` to see them in autocomplete.

    ```
    /mellea-compile skills/weather/spec.md
    /mellea-validate skills/weather/weather_mellea
    /mellea-run skills/weather/weather_mellea --input "What's the weather like in Dublin?"
    /mellea-certify skills/weather/weather_mellea
    ```

The first command takes a few extra minutes while the compiler is cloned and
installed under `~/.cache/mellea-skills-compiler/<version>/` (once per version; delete
that folder to reset). Compiling writes a `weather_mellea/` package next to the spec
and can take from a couple of minutes to over half an hour depending on the model.

Paths are relative to the folder pi was started in. Flags are passed to the CLI
unchanged (see the [CLI reference](CLI.md)); on `/mellea-compile`,
`--provider` or `--model` override the session defaults. If the compile fails because
of your provider, see [Choosing a provider](#choosing-a-provider) below.

On Windows, `git` must be on `PATH`, and long paths should be enabled
(`git config --global core.longpaths true`). WSL also works.

### Verifying credentials

Before running a compile, confirm pi has credentials for your provider:

```bash
pi auth check --provider anthropic          # direct Anthropic
pi auth check --provider anthropic-proxy    # your proxy provider
pi auth check --provider ollama             # local Ollama
```

Each should print `ready` when the credentials are correctly resolved. This only checks
that credentials resolve; it does not contact the provider, so `ready` doesn't mean the
endpoint is up.

For Ollama, check the server directly:

```bash
curl -s http://127.0.0.1:11434/api/tags
```

### Known limitations

- **No cancellation.** Use pi's own interrupt to stop a running command.
- **No output in headless mode** (`pi -p`), where pi exits 0 even if the command
  failed. Use the `mellea-skills` CLI directly in scripts.
- **A stopped compile** can be resumed with `/mellea-compile <spec> --repair-mode`.
- **Compiling writes next to the spec.** Compile from a copy if you don't want your
  skill folder changed.
- **The compile runs pi with `--approve`** inside the extension's own copy of the
  compiler, so it can load the compiler's prompt templates. It does not do this in
  your own folders.
- **`/mellea-run` before `/mellea-certify` runs without Guardian checks**, and shows a
  warning telling you to run `mellea-skills ingest` or `mellea-skills certify`. There
  is no `ingest` command in pi: run `/mellea-certify` on the compiled skill once, and
  later `/mellea-run` calls use its Guardian policy.


---

## Choosing a provider

You can Configure credentials for the provider pi will use. Either run:

```
pi  #then from inside your pi session use `/login` to authenticate interactively.
```

OR pi reads custom providers from `models.json` in its agent folder: `~/.pi/agent/models.json`,
or `$PI_CODING_AGENT_DIR/models.json` if you set that variable. It does not read a file
from your working directory. The file can hold API keys, so keep it out of any git
repository. The right choice depends on how you are accessing your model:

| Situation | Provider setting | Notes |
|-----------|-----------------|-------|
| Direct Anthropic API key | `anthropic` (default) | Set `ANTHROPIC_API_KEY` |
| LiteLLM proxy / AWS Bedrock gateway | a name you choose, e.g. `anthropic-proxy` | Define it with `baseUrl` + `apiKey` in `models.json` |
| Ollama (local models) | `ollama` | Set `baseUrl` in `models.json` |

Whichever provider you choose, make sure `defaultProvider` in
`~/.pi/agent/settings.json` names it, and that `defaultModel` is one of that
provider's models. `/mellea-compile` uses your pi session's provider and model, and if
you pass `--provider` without `--model`, your defaults are used instead. For example,
for a proxy provider named `anthropic-proxy`:

```json
{
  "defaultProvider": "anthropic-proxy",
  "defaultModel": "claude-sonnet-4-5"
}
```

Keep any other settings already in the file.

### Direct Anthropic API

No `models.json` needed. Export your key and then compile as normal:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
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

Then compile with additional flag `--provider anthropic-proxy`.

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

Then compile with additional flags `--provider ollama --model granite4.2:30b --timeout 21600`.

Local models are much slower than hosted Claude. A small skill such as `weather` took
about 110 minutes with `granite4.2:30b`, longer than the default 75-minute `--timeout`,
so raise it as shown above.

#### Choosing an Ollama model

The compile reads roughly 200 KB of step instructions and has to follow strict rules
about which files it may write, so it needs a large model that follows instructions
reliably and calls tools rather than describing them. Results from compiling `weather`:

| Model | Result |
|-------|--------|
| `granite4.2:30b` | Compiles successfully (about 110 min) |
| `qwen3-coder` | Fast, but ignores file-placement rules and does not produce the required `*_emission.json` files, so the compile fails |
| `granite3.3:8b` | Prints commands as text instead of calling tools; the compile stops immediately |
| `granite4.2:3b` | Loses track of the working directory and writes files outside the repository |

Models other than these have not been tested.

#### Check the compiled skill by running it

A successful compile means the package parses, passes the structural lints, and its
fixtures import and run. It does not prove that the skill's tools work: fixtures do not
make live network calls, and generated tools may catch errors and return them as
ordinary strings. Run the compiled skill against a real input before relying on it.

### Troubleshooting

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `Authentication failed` or `401` when using `--provider anthropic` | Proxy key is not an `ANTHROPIC_API_KEY` | Define a proxy provider in `~/.pi/agent/models.json` with your proxy `baseUrl` and `apiKey`, and pass its name to `--provider` |
| `tools.0.custom.eager_input_streaming: Extra inputs are not permitted` | Older Bedrock deployment does not support this streaming feature | Already using your proxy provider? Add `"compat": { "supportsEagerToolInputStreaming": false }` to that provider block in `models.json` |
| Your provider is missing from `pi --list-models` | `models.json` is in the wrong place or misnamed | It must be `models.json` (plural) in `~/.pi/agent/`, or in `$PI_CODING_AGENT_DIR` if set |
| `pi auth check` prints `not ready` | Missing or mis-scoped credentials | Re-run `pi` and use `/login`, or set the correct environment variable for that provider |
| Compile starts then silently produces no output | Provider accepted the connection but the model rejected the request | The provider error message is printed to the terminal at the end of the compile run — scroll up to find it |
| `Mellea-fy skill compilation failed due to timeout` with an Ollama model | Local models take far longer than the default 75-minute limit | Re-run with a larger `--timeout`, e.g. `--timeout 21600` (6 hours) |
| `config_emission.json not found` or `fixtures_emission.json not found` | The model wrote `config.py` / `fixtures/` directly (blocked during pi runs) instead of emitting the JSON the compiler renders from | Use a more capable model; see [Choosing an Ollama model](#choosing-an-ollama-model) |
| `Pi exited with return code 0 but produced no .../classification.json` | The model stopped without doing any work — it asked a question or replied with text instead of calling tools | Use a model that supports tool calling reliably; see [Choosing an Ollama model](#choosing-an-ollama-model) |
| `--provider X doesn't match your default provider Y, so using your default` | `--provider` was passed without `--model`, and pi's `defaultModel` belongs to a different provider | Pass `--model` as well to compile with the provider you named |
