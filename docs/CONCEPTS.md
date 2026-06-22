#Concepts

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

**Step 2: Certify** — A single `mellea-skills certify` invocation performs end-to-end governance: AI Atlas Nexus identifies applicable risks from Granite Guardian, NIST AI RMF, and Credo UCF taxonomies and emits a `PolicyManifest`; Guardian hooks configured from that manifest monitor every `m.instruct()` call as fixtures execute; each governance requirement is classified as AUTOMATED, PARTIAL, or MANUAL based on runtime evidence; a compliance report and audit trail are written alongside the compiled pipeline.
