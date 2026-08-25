# Mellea Skills Compiler

  <strong>Compiling and certifying agent skills with Mellea</strong><br>
  <em>Research preview — IBM Research, May 2026</em>



  <a href="#what-is-mellea-skills-compiler">What</a> &middot;
  <a href="#why">Why</a> &middot;
  <a href="#how-it-works">How</a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#example-outputs">Examples</a> &middot;
  <a href="#next-steps">Next Steps</a> &middot;
  <a href="FAQs.md">FAQs</a> &middot;
  <a href="https://github.com/generative-computing/mellea-skills-compiler/blob/main/docs/Mellea_Skills_Compiler-tech_report.pdf">Tech Report</a> &middot;
  <a href="#citation">Cite</a>


---

> **Research preview (v0.1)** — This is an early-stage research project from IBM Research. The APIs, CLI, and artifact formats are subject to change. We welcome feedback via [Issues](https://github.com/generative-computing/mellea-skills-compiler/issues).

> **Coming soon** (active development):
>
> - Interactive dependency resolution during compile
> - Export for additional agent harnesses — MCP, LangGraph, and Claude Code available today, all experimental
> - Support for compiling non-`.md` agent skills
> - Increased coverage for different interaction modalities (streaming, conversational session, scheduled, event-triggered)

## What is Mellea Skills Compiler?

Mellea Skills Compiler is a certification pipeline for AI agent skills. It takes a natural-language skill specification (a `.md` file) and produces a **typed, instrumented program** with policy-driven guardrails and auditable execution traces.

The pipeline composes three IBM Research technologies:

| Component                                                                          | Role                                                                     | Source     |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ---------- |
| **[Mellea](https://github.com/generative-computing/mellea)**                       | Structured generative programs with typed schemas, validation, and hooks | Apache 2.0 |
| **[Granite Guardian](https://huggingface.co/ibm-granite/granite-guardian-3.3-8b)** | Runtime risk detection integrated via Mellea's hook system               | Apache 2.0 |
| **[AI Atlas Nexus](https://github.com/IBM/ai-atlas-nexus)**                        | Governance knowledge graph mapping use cases to risks across taxonomies  | Apache 2.0 |

## Why

AI agents increasingly ship as natural-language specifications — Markdown files, YAML configs, system prompts — executed by LLMs without formal verification, runtime monitoring, or compliance documentation. The specification format is right for rapid development, but specifications alone don't guarantee reliable execution at scale.

Mellea Skills Compiler addresses three governance gaps:

- **Specification opacity** — When an LLM interprets a Markdown spec, contradictions are silently resolved through implicit judgement. Structured decomposition surfaces these conflicts as testable failures.
- **Runtime unobservability** — Agent outputs are typically unmonitored. Mellea Skills Compiler instruments every LLM generation with Guardian risk checks and JSONL audit trails.
- **Compliance disconnect** — Enterprise frameworks (NIST AI RMF, EU AI Act) require documented evidence of risk management. Mellea Skills Compiler maps governance requirements to runtime capabilities and produces evidence packages.

## How It Works

Mellea Skills Compiler operates as a two-step user workflow — `compile` then `certify`:

```
SKILL.md / spec.md          COMPILE                                CERTIFY
Natural-language      →    mellea-fy                          →    AI Atlas Nexus → policy manifest
agent specification        spec → typed pipeline                   Guardian hooks instrument runtime
                           contradictions surfaced                 fixtures executed + audited
                                                                   compliance classification + report
```

**Step 1: Compile** — A `.md` specification is decomposed into a typed Mellea pipeline package: Pydantic schemas, `@generative` extraction slots, requirement validators, and multi-phase orchestration code. Two compilation paths are available: the `mellea-skills compile` CLI command, or the `/mellea-fy` command inside Claude Code. See [`examples/`](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples/) for pre-compiled examples.

> **Backend Abstraction** — The compilation process uses a pluggable backend architecture. Currently, Claude Code and IBM Bob backends are supported (via `--backend claude` or `--backend bob`). The abstraction layer enables future support for alternative local LLMs.

**Step 2: Certify** — A single `mellea-skills certify` invocation performs end-to-end governance: AI Atlas Nexus identifies applicable risks from Granite Guardian, NIST AI RMF, and Credo UCF taxonomies and emits a `PolicyManifest`; Guardian hooks configured from that manifest monitor every `m.instruct()` call as fixtures execute; each governance requirement is classified as AUTOMATED, PARTIAL, or MANUAL based on runtime evidence; a compliance report and audit trail are written alongside the compiled pipeline.

## Install

Mellea Skills Compiler requires a backend to compile skills. You can use either **Claude Code** or **IBM Bob** — pick whichever you have access to and follow the corresponding setup below.

### Claude Setup

  1. Claude Code is required to compile a Mellea skill. Please ensure that the Claude Code is installed by following the guide here: https://code.claude.com/docs/en/quickstart

  2. Set relevant platform-specific environment variables to communicate with your Claude platform.

      For example, Claude via LiteLLM Gateway requires following env variables:

      ```
      export ANTHROPIC_BASE_URL = ""
      export ANTHROPIC_AUTH_TOKEN = ""
      ```

      or if you have an ANTHROPIC_API_KEY

      ```
      export ANTHROPIC_BASE_URL = ""
      export ANTHROPIC_API_KEY = ""
      ```

### IBM Bob

  1. Please ensure that the IBM Bob shell is installed by following the guide here: https://bob.ibm.com/docs/shell/getting-started/install-and-setup. Only Bob v2.x.x is supported.

  2. IBM Bob authentication works via IBMid, SSO and API key authentication. Please check https://bob.ibm.com/docs/shell/getting-started/install-and-setup#authentication for more details. Set relevant platform-specific environment variables to communicate with your IBM Bob platform.

      For example, API key authentication requires following env variable:

      ```
      export BOB_API_KEY = ""
      ```

### Project Code

Clone code repository

```
git clone https://github.com/generative-computing/mellea-skills-compiler
```

#### Create Python environment and install library

```bash
# Requires Python >=3.11, <3.14.4
python3 -m venv .venv
source .venv/bin/activate

pip install -e .
```

#### Choose Inference Engine

| Engine | Use Case | Deployment | Configuration | Characteristics |
|--------|----------|-----------|---------------|-----------------|
| **Ollama** | Development, testing, prototyping | Local workstation | `export OLLAMA_API_URL=<api-url>` (default: `http://localhost:11434`) | Lightweight, easy setup, minimal dependencies, no external services required |
| **vLLM** | Production deployments, high-throughput | Local instance or hosted service | `export VLLM_API_URL_RISK_MODEL=<api-url>` and `export VLLM_API_URL_GUARDIAN_MODEL=<api-url>` | Optimized serving, dynamic batching, GPU acceleration, supports multiple model endpoints |

**Engine Selection**: Specify via `--inference-engine` flag in `certify` and `run` commands. Engines are swappable without recompiling skills—risk identification and Guardian verdicts run on the selected backend transparently.


- For Ollama, set API URL in the environment variables:

  ```bash
  export OLLAMA_API_URL=http://localhost:11434 # Ollama api URL
  ```

- For online vLLM, set API URL and API KEY(optionally) in the environment variables:

  ```bash
  # api url and api key of hosted risk model
  export VLLM_API_URL_RISK_MODEL=http://localhost:8000
  export VLLM_API_KEY_RISK_MODEL=YOUR_API_KEY

  # api url and api key of hosted guardian model
  export VLLM_API_URL_GUARDIAN_MODEL=http://localhost:8001
  export VLLM_API_KEY_GUARDIAN_MODEL=YOUR_API_KEY
  ```

- For offline vLLM, there is no need to set API URL and API KEY in the environment variables. Please install `vllm` using pip when using the offline service.
  ```bash
  pip install vllm
  ```

## Quick Start

### You can download the skill specifications from GitHub or use your own specification file.

Example skills: https://github.com/generative-computing/mellea-skills-compiler/tree/main/skills

### Risk Identification and Assessment Models

You can change these models using the `--risk-model` and `--guardian-model` parameters when executing the **Run** and **Certify** commands. To use the default models, follow the instructions below.

For Ollama, we recommend downloading the Ollama models beforehand, as they are set as defaults. They will be downloaded during the first request

```
ollama pull granite4.1:3b
ollama pull ibm/granite3.3-guardian:8b
```

For vLLM, you can use the Hugging Face CLI to download default models, or they will be downloaded during the first request.

```
hf download ibm-granite/granite-4.1-3b
hf download ibm-granite/granite-guardian-3.3-8b
```

### Node.js Interactive CLI

Begin operation by using the Mellea Skills Compiler Node.js Interactive CLI or skip to the next step to use command-based CLI.

```
./mellea-skills-ui.sh
```

### Command-based CLI

### Compile Agent Skill - Option 1 (Recommended)

Compile a skill into a typed Mellea pipeline via the CLI:

```bash
# if skill is a single spec file.
mellea-skills compile <Your-local-path>/skills/weather/spec.md

# if skill is a directory containing spec files
mellea-skills compile <Your-local-path>/skills/weather
```

The `--backend` flag allows you to specify which compilation backend to use (currently `claude` and `bob` are supported):
```bash
# Explicit backend selection as claude
mellea-skills compile <Your-local-path>/skills/weather/spec.md --backend claude

# Explicit backend selection as bob
mellea-skills compile <Your-local-path>/skills/weather/spec.md --backend bob

# Uses 'claude' by default
mellea-skills compile <Your-local-path>/skills/weather/spec.md
```

Compile uses Sonnet as the default claude model. To use different claude model,

```bash
mellea-skills compile <Your-local-path>/skills/weather/spec.md --model aws/claude-opus-4-5
mellea-skills compile <Your-local-path>/skills/weather --model aws/claude-opus-4-5
```

Melleafy Repair: Identify and correct any errors effectively in Mellea skill compilation

```bash
mellea-skills compile --repair-mode <Your-local-path>/skills/weather --model aws/claude-opus-4-5
```

### Compile Agent Skill - Option 2

**Using Claude Code**

Run `/mellea-fy` directly inside Claude Code:

```bash
./mellea-fy <Your-local-path>/skills/weather/spec.md
```

**Using IBM Bob**

Run `/mellea-fy` directly inside Bob Shell:

```bash
/mellea-fy <Your-local-path>/skills/weather/spec.md
```

See [`mellea-fy/README.md`](https://github.com/generative-computing/mellea-skills-compiler/blob/main/mellea-fy/README.md) for detailed usage of the Claude Code command.

### Run Skill Pipeline

Run skill pipeline for a given fixture

```bash
# provide a raw string as an input
mellea-skills run <Your-local-path>/weather/weather_mellea --input "Whats the weather like in Dublin?"

# provide a JSON file as an input
mellea-skills run <Your-local-path>/weather/weather_mellea --input file://<Your-local-path>/input.json

# provide input as stdin for each required parameters
mellea-skills run <Your-local-path>/weather/weather_mellea --input -

# provide a fixture name as an input
mellea-skills run <Your-local-path>/weather/weather_mellea --fixture rain_check

 # Block execution when Guardian detects risks (default: audit-only)
mellea-skills run <Your-local-path>/weather/weather_mellea --enforce

# Skip Guardian checks even if a policy manifest exists.
mellea-skills run <Your-local-path>/weather/weather_mellea --no-guardian
```

#### Input Format Examples

1. Raw String

For skills with a single parameter, you can pass a plain string directly:
```
mellea-skills run skills/weather/weather_mellea --input "What's the weather like in Dublin?"
```

2. JSON String

For skills with multiple parameters, pass a JSON object with parameter names as keys:
```
mellea-skills run skills/sentry/sentry_mellea --input '{"query": "What's the weather like in Dublin right now?"}'
```

3. File Input (JSON)

Use file:// prefix to read structured JSON from a file:
```
mellea-skills run skills/weather/weather_mellea --input file://input.json
```
input.json:
```
{
  "query": "What's the weather like in Dublin right now?"
}
```

4. File Input (YAML)

YAML files are also supported via file:// prefix:
```
mellea-skills run skills/example/example_mellea --input file://input.yaml
```
input.yaml:
```
query: What's the weather like in Dublin right now?
```

5. Interactive Stdin Input

Use - to prompt for each parameter interactively:
```bash
mellea-skills run skills/weather/weather_mellea --input -
# This will prompt:
Enter query: What's the weather like in Dublin right now?
```

6. Fixture Input (Alternative to --input)

Use a pre-defined fixture instead of --input:
```bash
mellea-skills run skills/weather/weather_mellea --fixture current_weather_city
```

### Run Full Certification Pipeline for Mellea skill

Run end-to-end certification — risk identification via AI Atlas Nexus, Guardian hook instrumentation, fixture execution, and compliance report — in a single command:

Pass `--inference-engine ollama` for Ollama or `--inference-engine vllm` for vLLM inference service.

```bash
# Provide path to the compiled skill directory. Uses default parameters.
mellea-skills certify examples/weather/weather_mellea

# Block on risk detection
mellea-skills certify examples/weather/weather_mellea --enforce

# Number of fixtures to evaluate for pipeline certification. Default is 3.
mellea-skills certify examples/weather/weather_mellea --n_fixtures 4

# Using Ollama risk model, guardian model and inference engine
mellea-skills certify examples/weather/weather_mellea --risk-model granite4.1:3b --guardian-model ibm/granite3.3-guardian:8b --inference-engine ollama

# Using vLLM risk model, guardian model and inference engine
mellea-skills certify examples/weather/weather_mellea --risk-model ibm-granite/granite-4.1-3b --guardian-model ibm-granite/granite-guardian-3.3-8b --inference-engine vllm
```

### Export Compiled Mellea Skill

Export a compiled Mellea skill to a deployment target - langgraph, claude-code, mcp, or pi

**Note**: This command is experimental. Output structure and CLI interface may change in future releases without a deprecation period.

```bash
# Supported deployment target: mcp, langgraph, claude-code, pi
mellea-skills export --target mcp <Your-local-path>/skills/weather/weather_mellea

# '--force' overwrites output directory if it already exists.
mellea-skills export --target mcp --force <Your-local-path>/skills/weather/weather_mellea
```

### Certification artifacts

All outputs are written to `audit/` adjacent to the compiled directory:

```
skills/weather/audit/
├── policy_manifest.json        # Policy manifest (risks + governance actions)
├── POLICY.md                   # Human-readable policy document
├── CERTIFICATION.md            # Certification report with coverage summary
├── audit_trail.jsonl           # Runtime Guardian verdicts
└── pipeline_report.json        # Pipeline execution output
```

## Example Outputs

The [`examples/`](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples) directory contains pre-compiled, validated Mellea pipeline packages — runnable end-to-end against the project's Ollama + `granite4.1:3b` baseline. Each is a curated reference snapshot of what `mellea-skills compile` produces under the current architecture.

| Skill                                                                          | Tier    | Archetype                  | Description                                                                                                                                    |
| ------------------------------------------------------------------------------ | ------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| [weather](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples/weather/)                                                   | T1      | Fetch + summarise          | Public no-auth HTTP to `wttr.in`; intent classification dispatches to one of seven URL templates                                               |
| [sentry-find-bugs](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples/sentry-find-bugs/)                                 | T1 / T2 | Structured analysis        | Multi-phase OWASP review producing severity-classified findings; two stub helpers (`search_fn`, `read_file_fn`) for codebase-scanning fixtures |
| [superpowers-systematic-debugging](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples/superpowers-systematic-debugging/) | T1      | Constrained reasoning      | Four-phase debugging walk with hypothesis testing; `fix_attempts_count >= 3` triggers architectural-issue branch                               |
| [clawdefender](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples/clawdefender/)                                         | T3      | Adversarial classification | Prompt injection / SSRF / command injection / credential exfiltration detection; bundled scripts need `chmod +x` on Unix                       |

Each example includes the original `spec.md` (or `SKILL.md`), generated pipeline code, factory-shape fixtures, intermediate IR (`config_emission.json`, `fixtures_emission.json`, etc.), `mapping_report.md`, and `melleafy.json` manifest. See [`docs/TUTORIAL.md`](docs/TUTORIAL.md) for the runnable tutorial that walks through each one and [`docs/FROM_STUBS_TO_RUNNING.md`](docs/FROM_STUBS_TO_RUNNING.md) for the stub-implementation walkthrough.

## Skills

The [`skills/`](skills/) directory contains 16 skill specifications drawn from multiple sources (Sentry, Anthropic, community contributions, and IBM Research). Four of these ship as pre-compiled examples (see above); the rest can be compiled locally via `mellea-skills compile skills/<name>/spec.md`.

Skills are classified into three tiers by what's needed to run a fixture against the compiled package:

- **T1** — Runs out of the box. No stubs, no external services, no credentials.
- **T2** — Runs after filling 1–2 stubs or supplying a small bundled artifact.
- **T3** — Requires external integration before any fixture completes (CLI tool, API key, OAuth, runtime helper).

See [`skills/README.md`](skills/README.md) for the full per-skill tier table and source attribution.

## Repository Structure

```
src/mellea_skills_compiler/  # pip-installable package
  certification/           # Ingest → policy → compliance → certification report
  compile/                 # Compile Mellea skill specification into a Mellea pipeline using mellea-fy Claude or Bob shell.
  guardian/                # Granite Guardian hooks for Mellea pipelines
  toolkit/                 # Shared utilities and enums
  export/                  # Export a compiled Mellea skill to a deployment target
mellea-fy/                 # Claude Code /mellea-fy command definition
skills/                    # Skill specs, compiled pipelines, and fixtures
examples/                  # mellea-fy output examples and demos
tests/                     # Test suite
```

## Running Tests

```bash
pytest -s tests
```

See [`tests/README.md`](tests/README.md) for details.

## Next Steps

Mellea Skills Compiler is an active research project. The current release demonstrates the core pipeline; several directions are in progress.

### Evaluation and evidence

- **Cross-model evaluation** — We are developing a systematic comparison framework for how specification decomposition affects skill behaviour across model sizes and task types, capturing both correctness and predictability dimensions.
- **Cost-benefit analysis** — Decomposition increases LLM call count compared to monolithic execution. Quantifying the efficiency-governance tradeoff is part of the ongoing work.

### Compiler robustness

- **Compiler reflection loop** — Currently, `/mellea-fy` is a single-pass compiler with no automated self-review. We are building a validate-and-repair cycle: generate, validate (syntax, imports, fixture execution), and repair broken files — applying the same reflection pattern the compiled pipelines already use internally.
- **Modular compiler specification** — The mellea-fy command spec is itself a large natural-language document. We are investigating decomposing it into smaller, independently-testable modules to improve consistency.

### Pipeline capabilities

- **Specification linting** — Self-consistency analysis to detect contradictions in skill specs before compilation. Decomposition surfaces spec quality issues that monolithic execution can resolve silently; we are developing this into a standalone quality gate.
- **Per-phase model routing** — Decomposed pipelines enable routing each phase to a different model tier; classification and extraction phases tend to suit smaller models, while complex reasoning phases benefit from larger ones. The optimisation surface is being explored.
- **Closed-loop repair** — Feeding Guardian verdicts back into Mellea's existing repair loops, moving from "guardrails that flag" to "guardrails that fix."
- **Ecosystem-scale governance** — Applying the certification pipeline to skill registries at scale.

## Known Limitations

- **Research preview** — APIs, CLI, and artifact formats may change
- **Static compliance classification** — YAML-based action-to-control mapping, not yet validated against ground truth
- **Single domain evaluation** — Certification pipeline has been tested primarily on security and utility skills
- **Python version constraints** — Python >=3.11 and <3.14.4 (ai-atlas-nexus requires 3.11+ and <3.14.4; Mellea supports 3.11+)

## Contributing

This is a research preview. We welcome feedback, bug reports, and suggestions via [Issues](https://github.com/generative-computing/mellea-skills-compiler/issues). If you're interested in contributing or collaborating, please open an issue to start the conversation.

## Team

Elizabeth M. Daly, Dhaval Salwala, Inge Vejsbjerg, Seshu Tirupathi, Rebecka Nordenlöw, Lamogha Chiazor, Jessica He, Kush R. Varshney, and Jordan McAfoose — IBM Research

## Citation

A technical report describing the system architecture, design rationale, and governance pipeline is included in this repository: [`docs/Mellea_Skills_Compiler-tech_report.pdf`](docs/Mellea_Skills_Compiler-tech_report.pdf).

If you use Mellea Skills Compiler in your work, please cite:

```bibtex
@techreport{daly2026mellea,
  title       = {Mellea Skills Compiler: Compiling and Certifying Agent Skills with Mellea},
  author      = {Daly, Elizabeth M. and Salwala, Dhaval and Vejsbjerg, Inge and
                 Tirupathi, Seshu and Nordenl{\"o}w, Rebecka and Chiazor, Lamogha and He, Jessica and
                 Varshney, Kush R. and McAfoose, Jordan},
  institution = {IBM Research},
  year        = {2026},
  month       = {May},
  type        = {Technical Report},
  url         = {https://github.com/generative-computing/mellea-skills-compiler/blob/main/docs/Mellea_Skills_Compiler-tech_report.pdf}
}
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
