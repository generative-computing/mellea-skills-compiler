# Frequently Asked Questions

## General

### What is the Mellea Skills Compiler?

A pipeline that takes a natural-language agent skill specification (a `.md` file) and produces a typed, instrumented Python program with policy-driven guardrails and auditable execution traces. It composes three IBM Research technologies — Mellea (typed generative programs), Granite Guardian (runtime risk detection), and AI Atlas Nexus (governance knowledge graph) — into a single compile-instrument-certify workflow.

### What problem does this solve?

AI agent skills are increasingly authored as Markdown files and executed by LLMs without formal verification, runtime monitoring, or compliance documentation. This creates three gaps:

1. **Specification opacity** — contradictions in specs are silently resolved by the model's implicit judgement
2. **Runtime unobservability** — no audit trail of what the agent generated or whether outputs were safe
3. **Compliance disconnect** — no standard way to map governance requirements to runtime capabilities

The Mellea Skills Compiler addresses all three through its compile, instrument, and certify stages.

### Is this production-ready?

No. This is a **research preview** (v0.1). The pipeline works end-to-end and produces real artifacts, but APIs, CLI commands, and output formats are subject to change. We are publishing early to gather feedback and identify collaborators.

### What is Mellea named after?

Mellea is named after the honey mushroom (_Armillaria mellea_) — a metaphor for the typed, structured generative programs the library produces.

---

## Architecture

### What are the pipeline stages?

The user-facing workflow is two commands — `compile` then `certify`:

1. **Compile** — A `.md` specification is decomposed into a typed Mellea pipeline package with Pydantic schemas, extraction slots, validators, and orchestration code. You can compile via the CLI (`mellea-skills compile <spec>`) or via the `/mellea-fy` command inside Claude Code. See [`src/mellea_skills_compiler/examples/`](src/mellea_skills_compiler/examples/) for pre-compiled examples.

2. **Certify** — A single `mellea-skills certify` invocation does three things end-to-end: AI Atlas Nexus identifies applicable risks from the Granite Guardian, NIST AI RMF, and Credo UCF taxonomies and emits a `PolicyManifest` (JSON); Guardian hooks configured from that manifest monitor every LLM generation as fixtures execute; each governance requirement is classified as AUTOMATED, PARTIAL, or MANUAL based on runtime evidence, producing a certification report with evidence chains.

### What is Mellea?

[Mellea](https://github.com/generative-computing/mellea) is an open-source IBM Research library for structured LLM generation. It provides typed Pydantic schemas, `@generative`-decorated extraction functions, requirement validators with repair loops, and a hook system for plugin-based instrumentation. The Mellea Skills Compiler uses Mellea as the runtime for compiled pipelines and as the integration surface for Guardian.

### What is `/mellea-fy`?

A Claude Code slash command that performs the LLM-driven specification decomposition. Given a `.md` skill specification, it produces a complete Mellea pipeline package alongside the spec. The command definition lives in [`mellea-fy/`](mellea-fy/). The `mellea-skills compile` CLI wraps `/mellea-fy` and adds deterministic plumbing on either side (companion-directory mirroring, grounding pre-population, runtime-defaults injection, structural lints, fixture smoke check). See [`mellea-fy/README.md`](mellea-fy/README.md) for details.

### What is AI Atlas Nexus?

[AI Atlas Nexus](https://github.com/IBM/ai-atlas-nexus) is a governance knowledge graph that consolidates AI risk and capability taxonomies. The Mellea Skills Compiler uses Nexus to automatically identify applicable risks from a use-case description, mapping across the Granite Guardian taxonomy (for runtime checks), NIST AI RMF (for governance actions), and Credo UCF (for mitigation controls).

### What is Granite Guardian?

[Granite Guardian](https://huggingface.co/ibm-granite/granite-guardian-3.3-8b) is an enterprise-grade risk detection model for generative AI. The compiler integrates Guardian as a Mellea hook plugin, checking every LLM generation for risks like harm, social bias, jailbreaking, and hallucination. It operates in two modes: AUDIT (observe and log) and ENFORCE (block on detection).

### What is the PolicyManifest?

A JSON document generated from a skill's use-case description via Nexus. It contains:

- **Guardian risks** — runtime risk checks with system prompts (native tag or custom criteria)
- **Governance actions** — NIST AI RMF and Credo UCF requirements applicable to this skill

The manifest drives all downstream instrumentation — Guardian hook configuration and compliance classification.

### What is the certification report?

A structured Markdown document (`CERTIFICATION.md`) that combines:

- Guardian verdict summary (per-risk check counts, flag rates, pass rates)
- Audit trail statistics (event counts by hook type, latency distribution)
- Per-requirement evidence chains linking NIST/Credo requirements to specific audit trail data
- Known limitations and coverage gaps

It documents precisely what was checked, what was found, and what remains uncovered. It does not assert that the agent is "safe."

---

## Skill formats and decomposition

### What format do skill specs come in?

The canonical and fully-supported format is a single `.md` file with YAML frontmatter (compatible with the Anthropic Agent Skills standard and OpenClaw conventions). The frontmatter declares the skill's `name`, `description`, and optional fields like `allowed-tools` and `metadata.openclaw.requires`; the body is natural-language workflow text the compiler decomposes.

### Can I use non-`.md` agent formats?

Support for non-`.md` source formats is **experimental**. The compiler currently has dialect detection for:

- CrewAI (`agents.yaml` + `crew.py` + `tasks.yaml`)
- Letta (`.af` JSON files)
- LangGraph (Python files with `StateGraph` construction)
- AutoGen, OpenAI Agents SDK, smolagents (basic detection)

See [`mellea-fy-inventory.md`](src/mellea_skills_compiler/compile/claude/commands/mellea-fy-inventory.md) for the full dialect detection table. Behaviour against these formats is less mature than `.md` — drift in fixture shape and pipeline structure is more common, and full coverage of all dialects is a roadmap item.

### What kinds of skills can the compiler handle?

Skills fall into distinct patterns based on how they use LLM generation and tools:

| Pattern                         | Description                                                            | Example skills                                   |
| ------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------ |
| **Generative artifact**         | Intent → structured output via multi-phase LLM generation              | `checklist`, `anthropic-doc-coauthoring`         |
| **Deterministic tool dispatch** | LLM classifies intent, then deterministic code executes the action     | `weather`, `slack`                               |
| **Analytical pipeline**         | Input → structured analysis via domain-specific extraction             | `sentry-find-bugs`, `dstiliadis-security-review` |
| **Constrained reasoning**       | Hypothesis-driven multi-phase investigation with conditional branching | `superpowers-systematic-debugging`               |
| **Adversarial classification**  | Refuse + label rather than generate                                    | `clawdefender`                                   |

### Does decomposition always help?

The effect of decomposition depends on the task type. For tasks where structured output and multi-constraint correctness matter, decomposition tends to help. For tasks that benefit from holistic context (e.g., free-form code generation), decomposition can introduce overhead without correctness gains. Systematic evaluation across model sizes and task types is part of the ongoing research.

### What is specification linting?

When a skill spec is decomposed into independent typed slots, contradictions that a monolithic prompt resolves through implicit judgement become explicit failures. This is an incidental benefit of decomposition: it surfaces specification quality signals that are invisible in monolithic execution. Developing this into a standalone quality gate is a roadmap item.

---

## Dependencies and stubs

### How does the compiler handle external dependencies?

During Step 2.5 of compilation (Dependency Audit), every external dependency the spec references — credentials, tools, runtime backends, scheduling triggers — is classified into one of nine categories (C1–C9) and assigned a **disposition** that decides how the compiler handles it:

| Disposition           | Meaning                                                                     |
| --------------------- | --------------------------------------------------------------------------- |
| `bundle`              | Embed the value directly in `config.py` (e.g., persona text, model ID)      |
| `real_impl`           | Generate a real Python implementation (e.g., HTTP call to a known endpoint) |
| `stub`                | Generate a `NotImplementedError` placeholder for the user to fill in        |
| `mock`                | Generate a mock implementation in `fixtures/mock_tools.py` (test/demo only) |
| `delegate_to_runtime` | The host runtime provides this (session state, memory backends)             |
| `external_input`      | Supply at invocation time as a CLI flag or environment variable             |
| `load_from_disk`      | Read from a local file at runtime (reference docs, config files)            |
| `remove`              | Source element produces no code (cross-reference artifacts)                 |

In `auto` mode (the default), the compiler picks dispositions from a fixed table per category. In `ask` mode, the compiler walks the user through each dependency interactively at compile time.

### What are stubs and how do I fill them?

A stub is a function in the compiled package that ends with `raise NotImplementedError(...)`. Stubs appear when the spec references a tool whose implementation the spec didn't pin down (typically C6 abstract tools — "send a message," "fetch a document"). The user fills the body before the relevant pipeline branches can execute.

See [`docs/FROM_STUBS_TO_RUNNING.md`](docs/FROM_STUBS_TO_RUNNING.md) for a worked walkthrough using `sentry-find-bugs`'s two stubs (`search_fn`, `read_file_fn`).

### What if my skill needs an API key or service that's not available?

The compiler emits a stub. The compiled package will run for fixtures whose code paths don't touch that stub; fixtures that do will raise `NotImplementedError` until the stub is filled. Stubs come with docstrings describing the expected signature and (often) example implementations that work as starting points.

### Why is `auto` mode the default?

To keep the first compile experience non-interactive and reproducible. Interactive dependency resolution at compile time is on the roadmap as `ask` mode improves.

---

## Usage

### What do I need to run the Mellea Skills Compiler?

- Python >=3.11 and <3.14.4 (ai-atlas-nexus requires 3.11+ and <3.14.4; Mellea supports 3.11+)
- Claude Code (for the `/mellea-fy` compilation step)
- Ollama running locally with `granite3.3:8b` pulled (for compiled-skill execution and Guardian checks)

### Can I run just the compilation step without certification?

Yes. `mellea-skills compile <spec>` produces a standalone Mellea pipeline package that can be used independently. The certification pipeline (`mellea-skills certify`) is a separate step.

### How do I run a fixture against a compiled package?

```bash
mellea-skills run <package_dir> --fixture <fixture_id>
```

Each compiled `<name>_mellea/` directory ships a `fixtures/` subdirectory; the fixture id matches the filename (without `.py`). See [`docs/README.md`](docs/README.md) for end-to-end examples.

### What format are audit trails in?

JSONL (one JSON object per line), appended to `audit_trail.jsonl`. Each entry includes a timestamp, hook type, policy identifier, payload contents (input/output text, Guardian verdicts, latency), and component provenance.

### What if my compile fails?

Long-running generative pipelines fail. A spec might be partially compiled when the Claude session times out, a lint round can exhaust without converging, or an intermediate artifact can land in a partial state. The CLI ships a repair mode for these cases:

```bash
mellea-skills compile <spec_path> --repair-mode
```

(or the short form `-r`). This dispatches to the `/mellea-fy-repair` Claude command, which:

1. Audits every step's intermediate artifacts (`classification.json`, `inventory.json`, `element_mapping.json`, …) and the generated Python files.
2. Classifies each step as `valid` / `partial` / `missing` / `corrupt`.
3. Identifies the first broken step and resumes the pipeline from there — re-using earlier `valid` outputs rather than starting over.
4. Halts with a diagnostic report when a failure is not auto-recoverable (spec-level halts, `session-boundary` lint failures, `category-specific` security findings).

Repair operates on the same skill directory as the original compile — point it at the skill root, the `<name>_mellea/` package directory, or a `.melleafy-partial/` directory left by an interrupted run. See [`src/mellea_skills_compiler/compile/claude/commands/mellea-fy-repair.md`](src/mellea_skills_compiler/compile/claude/commands/mellea-fy-repair.md) for the audit phases, resume-point routing, and the lint-specific repair table.

### How does compliance classification work?

Each NIST or Credo governance action is classified against the pipeline's runtime capabilities using a static YAML mapping under [`src/mellea_skills_compiler/certification/data/`](src/mellea_skills_compiler/certification/data/):

| Classification | Meaning                                                          |
| -------------- | ---------------------------------------------------------------- |
| **AUTOMATED**  | 2+ implemented pipeline controls cover this requirement          |
| **PARTIAL**    | 1 implemented control, but organisational process also needed    |
| **MANUAL**     | Requires organisational process beyond technical instrumentation |

---

## Exporting to other agent harnesses

### Can I export a compiled skill to a different agent framework?

Yes — there is an experimental `mellea-skills export <package_path> <target>` subcommand on the [`export-pipeline`](../../tree/export-pipeline) branch (landing on `main` shortly) targeting three harnesses:

| Target                           | Status       | Output                                                                                                                                                                                                                       |
| -------------------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **LangGraph**                    | Experimental | `graph.py`, `state.py`, `langgraph.json`, `pyproject.toml`, `README.md`. Async node wraps `run_pipeline` via `asyncio.to_thread`; modality-aware (streaming, conversational session, scheduled, event-triggered, heartbeat). |
| **Claude Code**                  | Experimental | `SKILL.md`, `scripts/run.sh`, `pyproject.toml`, `README.md`. Bash entry point shells out to the bundled Python pipeline.                                                                                                     |
| **MCP** (Model Context Protocol) | Experimental | `server.py` (FastMCP), `mcp.json`, `pyproject.toml`, `README.md`. One `@mcp.tool()` per pipeline entry; sync or async based on modality.                                                                                     |

The compiled Mellea package is bundled inside each export so the result is self-contained.

Out-of-the-box export in this research preview is limited to the three targets above. There is **no** built-in export path for OpenClaw, NanoClaw, CrewAI, Letta, AutoGen, smolagents, OpenAI Agents SDK, or other harnesses — for those you write the wrapper yourself, and how much glue that is depends on how far the target's idioms are from a typed Python function call. See [`docs/EXPORTING.md`](docs/EXPORTING.md) for the full breakdown of the export pipeline (5-stage validate → load → translate → emit → lint), per-target modality support, and what hand-wrapping a non-supported harness looks like.

### Why is export experimental?

The exporter runs end-to-end and is covered by tests, but output file layouts, adapter conventions, and warning text may shift between releases without a deprecation period. The compiled package is also shaped around Mellea's runtime (typed `m.instruct(format=...)`, hook system, repair loops); other harnesses have different idioms and the mappings preserve typed I/O but lose Mellea-specific behaviours like Guardian hooks. The targets and contract evolve as we learn which features users need preserved.

### What about other harnesses (OpenClaw, NanoClaw, CrewAI, Letta, AutoGen, smolagents, OpenAI Agents SDK)?

Not currently export targets. The compiler can detect some of these as input dialects (see [`mellea-fy-inventory.md`](src/mellea_skills_compiler/compile/claude/commands/mellea-fy-inventory.md)) — that lets you compile a skill _from_ one of those formats, not export _to_ it. If you need to run a compiled skill under one of these harnesses today, you write the wrapper yourself. Adding more native export targets is roadmap, not a current feature.

---

## Limitations and scope

### Why does compilation require Claude Code?

Both `mellea-skills compile` and `/mellea-fy` invoke Claude Code under the hood to perform the LLM-driven decomposition. Claude Code must be installed and authenticated on your system. The compilation step is intentionally separated from the certification pipeline so that alternative compilers could be substituted in future.

### Is the compliance classification verified?

Not yet. The current implementation uses a static YAML mapping of governance action IDs to pipeline controls. Ground-truth validation is a planned future work item. The classification should be treated as indicative, not authoritative.

### Can I use this with models other than Granite?

The compiled Mellea pipelines can target any model supported by Mellea's backend configuration; today the project default is `ollama` + `granite3.3:8b` (set in [`src/mellea_skills_compiler/compile/claude/data/runtime_defaults.json`](src/mellea_skills_compiler/compile/claude/data/runtime_defaults.json), overridable per compile via `--skill-backend` / `--skill-model`). The certification pipeline's Guardian checks currently use Granite Guardian 3.3 8B via Ollama. The `/mellea-fy` compilation step itself uses Claude (typically Sonnet) and is not configurable to use other LLMs at this time.

### What about evaluation and benchmarks?

Systematic evaluation across model sizes and task types is in progress. We will publish results when they're ready; in the meantime, treat the project as an architectural demonstration rather than a benchmarked-and-validated production tool.
