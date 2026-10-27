# CLI reference

You can choose to use a Node.js interactive CLI, or a Command based CLI.

## Node.js Interactive CLI

Begin operation by using the Mellea Skills Compiler Node.js Interactive CLI or skip to the next step to use command-based CLI.

```
./mellea-skills-ui.sh
```

## Command-based CLI

| Command | What it does |
|---------|--------------|
| [`compile`](#compile-agent-skill) | Compile a skill spec into a typed Mellea pipeline |
| [`validate`](#validate-compiled-skill) | Lint a compiled pipeline and smoke-check a fixture |
| [`run`](#run-skill-pipeline) | Run a compiled pipeline against an input or fixture |
| [`certify`](#run-full-certification-pipeline-for-mellea-skill) | Run the full certification pipeline |
| [`ingest`](#ingest-skill-spec) | Identify risks and governance actions for a spec |
| [`export`](#export-compiled-mellea-skill) | Export a compiled pipeline to another agent harness |
| `version` | Print the installed version |

Run `mellea-skills <command> --help` for the full help text of any command.

The examples below use `skills/weather/weather_mellea`, which is created when you compile `skills/weather/spec.md`. A pre-compiled copy is available at `examples/weather/weather_mellea` if you want to try `validate`, `run`, `certify`, or `export` without compiling first.

### Compile Agent Skill
#### Compile Agent Skill - Option 1 (Recommended)

Compile a skill into a typed Mellea pipeline via the CLI:

```bash
# if skill is a single spec file.
mellea-skills compile <Your-local-path>/skills/weather/spec.md

# if skill is a directory containing spec files
mellea-skills compile <Your-local-path>/skills/weather
```

The `--backend` flag selects which agent performs the compilation (`claude`, `bob`, or `pi`):
```bash
# Explicit backend selection as claude
mellea-skills compile <Your-local-path>/skills/weather/spec.md --backend claude

# Explicit backend selection as bob
mellea-skills compile <Your-local-path>/skills/weather/spec.md --backend bob

# Explicit backend selection as pi (provider defaults to 'anthropic')
mellea-skills compile <Your-local-path>/skills/weather/spec.md --backend pi --provider anthropic

# Uses 'claude' by default
mellea-skills compile <Your-local-path>/skills/weather/spec.md
```

For pi provider setup (direct Anthropic, LiteLLM / Bedrock proxy, Ollama), see [Using with pi](PI_SETUP.md#choosing-a-provider).

Compile uses Sonnet as the default claude model. To use different claude model,

```bash
mellea-skills compile <Your-local-path>/skills/weather/spec.md --model aws/claude-opus-4-5
mellea-skills compile <Your-local-path>/skills/weather --model aws/claude-opus-4-5
```

Melleafy Repair: Identify and correct any errors effectively in Mellea skill compilation

```bash
mellea-skills compile --repair-mode <Your-local-path>/skills/weather --model aws/claude-opus-4-5
```

| Flag | Default | Description |
|------|---------|-------------|
| `--backend`, `-b` | `claude` | Compilation backend: `claude`, `bob`, or `pi` |
| `--provider` | `anthropic` | Provider for `--backend pi` (e.g. `anthropic`, `anthropic-proxy`, `ollama`); ignored otherwise |
| `--model`, `-m` | Sonnet | Model used to compile the skill |
| `--timeout`, `-t` | `4500` | Compile session timeout, in seconds (75 min) |
| `--repair-mode`, `-r` | off | Identify and correct errors in an existing compilation |
| `--skip-smoke-check` | off | Skip the post-compile fixture smoke-check |
| `--refresh-cache` | off | Refresh the grounding caches (`~/.cache/mellea-skills-compiler/`) before compiling |
| `--skill-backend` | from `runtime_defaults.json` | LLM backend the compiled skill uses at runtime |
| `--skill-model` | from `runtime_defaults.json` | Model id the compiled skill uses at runtime |

#### Compile Agent Skill - Option 2 (Inside an agent)

**Using Claude Code**

Run the `/mellea-fy` slash command inside a Claude Code session:

```
/mellea-fy <Your-local-path>/skills/weather/spec.md
```

**Using IBM Bob**

Run `/mellea-fy` directly inside Bob Shell:

```
/mellea-fy <Your-local-path>/skills/weather/spec.md
```

**Using pi**

Run `/mellea-compile` inside a pi session. See [Using with pi](PI_SETUP.md#pi-extension).

See [`.claude/commands/README.md`](https://github.com/generative-computing/mellea-skills-compiler/blob/main/.claude/commands/README.md) for detailed usage of the `/mellea-fy` command.

### Validate Compiled Skill

Run the static lints on a compiled pipeline, then smoke-check it against a fixture:

```bash
mellea-skills validate <Your-local-path>/skills/weather/weather_mellea          # lints + first fixture
mellea-skills validate <Your-local-path>/skills/weather/weather_mellea --all    # lints + every fixture
mellea-skills validate <Your-local-path>/skills/weather/weather_mellea --no-run # lints only
```

| Flag | Default | Description |
|------|---------|-------------|
| `--no-run` | off | Skip the post-lint fixture smoke-check |
| `--all` | off | Run all fixtures (default: first only) |

### Run Skill Pipeline

Run a compiled skill pipeline against an input or a fixture:

```bash
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --input "What's the weather like in Dublin?" # provide a raw string as an input
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --input file://<Your-local-path>/input.json  # provide a JSON file as an input
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --input -  # provide input as stdin for each required parameters
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --fixture rain_check_city   # provide a fixture name as an input
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --enforce              # Block execution when Guardian detects risks (default: audit-only)
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --no-guardian          # Skip Guardian checks even if a policy manifest exists.
```

Fixture names are the module names under the compiled package's `fixtures/` directory.

| Flag | Default | Description |
|------|---------|-------------|
| `--input`, `-i` | — | Input value: a raw string, `file://<path>` to read from a file, or `-` for stdin |
| `--fixture`, `-f` | — | Use a fixture as the input |
| `--enforce`, `-e` | off | Block execution when Guardian detects risks (default: audit-only) |
| `--no-guardian`, `-ng` | off | Skip Guardian checks even if a policy manifest exists |
| `--guardian-model` | engine default | Guardian model for risk assessment |
| `--inference-engine` | `ollama` | Inference service: `ollama` or `vllm` |

### Run Full Certification Pipeline for Mellea skill

Run end-to-end certification — risk identification via AI Atlas Nexus, Guardian hook instrumentation, fixture execution, and compliance report — in a single command:

```bash
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea                      # provide path to the compiled skill directory
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea --enforce            # Block on risk detection
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea -n 5                 # Evaluate 5 fixtures (default: 3)
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea --risk-model granite4.1:3b --guardian-model ibm/granite3.3-guardian:8b --inference-engine ollama    # Using different risk model, guardian model and inference engine
```

| Flag | Default | Description |
|------|---------|-------------|
| `-n` | `3` | Number of fixtures to evaluate |
| `--enforce`, `-e` | off | Run the pipeline in enforce mode (block on risk detection) |
| `--risk-model` | engine default | Model for risk and action identification |
| `--guardian-model` | engine default | Guardian model for risk assessment |
| `--inference-engine` | `ollama` | Inference service: `ollama` or `vllm` |

### Ingest Skill Spec

Identify risks and governance actions for a skill spec, without compiling or running it:

```bash
mellea-skills ingest <Your-local-path>/skills/weather/spec.md
mellea-skills ingest <Your-local-path>/skills/weather/spec.md --dry-run   # preview without making LLM calls
```

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Preview without making LLM calls |
| `--risk-model` | engine default | Model for risk and action identification |
| `--inference-engine`, `-i` | `ollama` | Inference service: `ollama` or `vllm` |

### Export Compiled Mellea Skill

Export a compiled Mellea skill to a deployment target: `langgraph`, `claude-code`, `mcp`, or `pi`.

**Note**: This command is experimental. Output structure and CLI interface may change in future releases without a deprecation period.

```bash
mellea-skills export --target mcp <Your-local-path>/skills/weather/weather_mellea         # Supported deployment targets: langgraph, claude-code, mcp, pi
mellea-skills export --target mcp --force <Your-local-path>/skills/weather/weather_mellea # '--force' overwrites output directory if it already exists.
```

| Flag | Default | Description |
|------|---------|-------------|
| `--target`, `-t` | required | Deployment target: `langgraph`, `claude-code`, `mcp`, or `pi` |
| `--force`, `-f` | off | Overwrite the output directory if it already exists |
| `--enforce`, `-e` | off | Register Guardian in enforce mode (block on risk detection). Default: audit-only |

See [Exporting](EXPORTING.md) for what each target produces.

### Output directories

`certify` writes to a new timestamped directory under `audit/`, next to the compiled package. `run` writes to a timestamped directory under `runs/`:

```
skills/weather/
├── weather_mellea/                       # compiled package
├── audit/
│   └── <DD-MM-YYYY_HH-MM-SS>/            # one per certify run
│       ├── policy_manifest.json          # Policy manifest (risks + governance actions)
│       ├── POLICY.md                     # Human-readable policy document
│       ├── CERTIFICATION.md              # Certification report with coverage summary
│       ├── audit_trail.jsonl             # Runtime Guardian verdicts
│       └── fixture_results.json          # Fixture execution results
└── runs/
    └── <DD-MM-YYYY_HH-MM-SS>/            # one per run
        ├── audit_trail.jsonl             # Runtime Guardian verdicts (when Guardian is active)
        └── fixture_results.json          # Result of the run
```

`run` uses the policy manifest from the most recent `audit/` directory that has one.
