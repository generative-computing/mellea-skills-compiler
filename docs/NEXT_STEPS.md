# Next Steps

Mellea Skills Compiler is an active research project. The current release demonstrates the core pipeline; several directions are in progress.

> **Research preview (v0.1)** — This is an early-stage research project from IBM Research. The APIs, CLI, and artifact formats are subject to change. We welcome feedback via [Issues](https://github.com/generative-computing/mellea-skills-compiler/issues).

> **Coming soon** (active development):
>
> - Interactive dependency resolution during compile
> - Export for additional agent harnesses — MCP, LangGraph, and Claude Code available today, all experimental
> - Support for compiling non-`.md` agent skills
> - Increased coverage for different interaction modalities (streaming, conversational session, scheduled, event-triggered)


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