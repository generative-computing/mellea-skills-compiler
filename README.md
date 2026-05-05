<h1 align="center">Mellea Skills Compiler</h1>

<p align="center">
  <strong>Compiling and certifying agent skills with Mellea</strong><br>
  <em>Research preview — IBM Research, May 2026</em>
</p>

<p align="center">
  <a href="#what-is-mellea-skills-compiler">What</a> &middot;
  <a href="#why">Why</a> &middot;
  <a href="#how-it-works">How</a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#example-outputs">Examples</a> &middot;
  <a href="#next-steps">Next Steps</a> &middot;
  <a href="FAQ.md">FAQ</a>
</p>

---

> **Research preview (v0.1)** — This is an early-stage research project from IBM Research. The APIs, CLI, and artifact formats are subject to change. We welcome feedback via [Issues](../../issues).

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

**Step 1: Compile** — A `.md` specification is decomposed into a typed Mellea pipeline package: Pydantic schemas, `@generative` extraction slots, requirement validators, and multi-phase orchestration code. Two compilation paths are available: the `mellea-skills compile` CLI command, or the `/mellea-fy` command inside Claude Code. See [`src/mellea_skills_compiler/examples/`](src/mellea_skills_compiler/examples/) for pre-compiled examples.

**Step 2: Certify** — A single `mellea-skills certify` invocation performs end-to-end governance: AI Atlas Nexus identifies applicable risks from Granite Guardian, NIST AI RMF, and Credo UCF taxonomies and emits a `PolicyManifest`; Guardian hooks configured from that manifest monitor every `m.instruct()` call as fixtures execute; each governance requirement is classified as AUTOMATED, PARTIAL, or MANUAL based on runtime evidence; a compliance report and audit trail are written alongside the compiled pipeline.

## Install

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
   export ANTHROPIC_API_KEY = ""
   export ANTHROPIC_BASE_URL = ""
   ```

### Project Code

Clone code repository

```
git clone https://github.com/generative-computing/mellea-skills-compiler
```

Create Python environment and install library

```bash
# Requires Python >=3.11, <3.14.4
python3 -m venv .venv
source .venv/bin/activate

pip install -e .
```

Set Ollama API URL in the environment variables:

```bash
export OLLAMA_API_URL=<ollama-api-url>
```

## Quick Start

### You can download the skill specifications from GitHub or use your own specification file.

Example skills: https://github.com/generative-computing/mellea-skills-compiler/tree/main/skills

### Ollama Models

We recommend downloading the Ollama models `granite3.3:8b` and `ibm/granite3.3-guardian:8b` beforehand, as they are set as defaults.

For Risk Identification

```
ollama pull granite3.3:8b
```

For Risk Assessment

```
ollama pull ibm/granite3.3-guardian:8b
```

### Compile a skill specification

#### Option 1: compile skill with CLI (Recommended)

Compile a skill into a typed Mellea pipeline via the CLI:

```bash
mellea-skills compile <Your-local-path>/skills/weather/spec.md  # if skill is a single spec file.
mellea-skills compile <Your-local-path>/skills/weather          # if skill is a directory containing spec files
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

#### Option 2: compile skill with Claude code

Run `/mellea-fy` directly inside Claude Code:

```bash
./mellea-fy <Your-local-path>/skills/weather/spec.md
```

See [`mellea-fy/README.md`](mellea-fy/README.md) for detailed usage of the Claude Code command.

### Run Skill Pipeline

Run skill pipeline for a given fxiture

```bash
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --fixture rain_check   # provide path to the compiled skill directory and the fixture name
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --enforce              # Block execution when Guardian detects risks (default: audit-only)
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --no_guardian          # Skip Guardian checks even if a policy manifest exists.
```

### Run Full Certification Pipeline for Mellea skill

Run end-to-end certification — risk identification via AI Atlas Nexus, Guardian hook instrumentation, fixture execution, and compliance report — in a single command:

```bash
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea                      # provide path to the compiled skill directory
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea --enforce            # Block on risk detection
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea --fixture rain_check # Run specific fixture - rain_check
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea --model granite3.3:8b --guardian-model ibm/granite3.3-guardian:8b --inference-engine ollama    # Using different risk model, guardian model and inference engine
```

### Export Compiled Mellea Skill

Export a compiled Mellea skill to a deployment target - langgraph, claude-code, or mcp

**Note**: This command is experimental. Output structure and CLI interface may change in future releases without a deprecation period.

```bash
mellea-skills export --target mcp <Your-local-path>/skills/weather/weather_mellea         # Supported deployment target: mcp, langgraph, claude-code
mellea-skills export --target mcp --force <Your-local-path>/skills/weather/weather_mellea # '--force' overwrites output directory if it already exists.
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

The [`src/mellea_skills_compiler/examples/`](src/mellea_skills_compiler/examples/) directory contains pre-compiled, validated Mellea pipeline packages — runnable end-to-end against the project's Ollama + `granite3.3:8b` baseline. Each is a curated reference snapshot of what `mellea-skills compile` produces under the current architecture.

| Skill                                                                          | Tier    | Archetype                  | Description                                                                                                                                    |
| ------------------------------------------------------------------------------ | ------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| [weather](examples/weather/)                                                   | T1      | Fetch + summarise          | Public no-auth HTTP to `wttr.in`; intent classification dispatches to one of seven URL templates                                               |
| [sentry-find-bugs](examples/sentry-find-bugs/)                                 | T1 / T2 | Structured analysis        | Multi-phase OWASP review producing severity-classified findings; two stub helpers (`search_fn`, `read_file_fn`) for codebase-scanning fixtures |
| [superpowers-systematic-debugging](examples/superpowers-systematic-debugging/) | T1      | Constrained reasoning      | Four-phase debugging walk with hypothesis testing; `fix_attempts_count >= 3` triggers architectural-issue branch                               |
| [clawdefender](examples/clawdefender/)                                         | T3      | Adversarial classification | Prompt injection / SSRF / command injection / credential exfiltration detection; bundled scripts need `chmod +x` on Unix                       |

Each example includes the original `spec.md` (or `SKILL.md`), generated pipeline code, factory-shape fixtures, intermediate IR (`config_emission.json`, `fixtures_emission.json`, etc.), `mapping_report.md`, and `melleafy.json` manifest. See [`docs/README.md`](docs/README.md) for the runnable tutorial that walks through each one and [`docs/FROM_STUBS_TO_RUNNING.md`](docs/FROM_STUBS_TO_RUNNING.md) for the stub-implementation walkthrough.

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
  compile/                 # Compile Mellea skill specification into a Mellea pipeline using mellea-fy Claude command.
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
- **Claude Code required for compilation** — Both `mellea-skills compile` and `/mellea-fy` invoke Claude Code under the hood for specification decomposition
- **Static compliance classification** — YAML-based action-to-control mapping, not yet validated against ground truth
- **Single domain evaluation** — Certification pipeline has been tested primarily on security and utility skills
- **Python version constraints** — Python >=3.11 and <3.14.4 (ai-atlas-nexus requires 3.11+ and <3.14.4; Mellea supports 3.11+)

## Contributing

This is a research preview. We welcome feedback, bug reports, and suggestions via [Issues](../../issues). If you're interested in contributing or collaborating, please open an issue to start the conversation.

## Team

Elizabeth M. Daly, Dhaval Salwala, Inge Vejsbjerg, Seshu Tirupathi, Rebecka Nordenlöw, Jessica He, Kush R. Varshney, and Jordan McAfoose — IBM Research

## License

Apache 2.0 — see [LICENSE](LICENSE).
