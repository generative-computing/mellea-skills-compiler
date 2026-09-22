# Melleafy Step 0: Five-Axis Classification

**Version**: 4.0.0 | **Prereq**: None | **Produces**: `classification.json`

> **Schema**: Output `intermediate/classification.json` MUST conform to `.claude/schemas/classification.schema.json`.

Classify the source spec along five axes before any other step runs. The classification drives dialect selection (Step 1a), category defaults (Step 2.5), entry-point shape (Step 3), and modality validation (Step 7).

---

## Processing order

Run axes in this order — each informs the next:

1. **Axis 4 — Source runtime** (drives which dialect doc applies to Axes 2 and 3)
2. **Axis 5 — Interaction modality** (explicit-first, then inferential)
3. **Axis 3 — Tool involvement** (informed by Axis 4's dialect mapping table)
4. **Axis 1 — Reasoning archetype** (informed by Axes 2, 3, 4)
5. **Axis 2 — Pipeline shape** (informed by Axis 1)

---

## Axis 1: Reasoning Archetype

What kind of thinking does the skill do?

| Type                  | What it does                                | Decomposition strategy                                                     |
| --------------------- | ------------------------------------------- | -------------------------------------------------------------------------- |
| **A: Analysis**       | Sequential phases → structured findings     | Full slot decomposition, two-step enrichment                               |
| **B: Generation**     | Intent + constraints → generated artifact   | Decompose intent capture and draft generation                              |
| **C: Diagnosis**      | Hypothesis-driven investigation with gating | Decompose reasoning; live system interaction as stubs or grounding_context |
| **D1: Integration**   | Thin wrapper around a single service/API    | Decompose only the intent classification layer                             |
| **D2: Orchestration** | Multi-step coordination of tools/agents     | Decompose only the decision logic                                          |
| **E: Knowledge**      | Passive rules, conventions, best practices  | Depends on Axis 2 (pipeline shape)                                         |

**Detection signals**:

- Count `EXTRACT` + `CLASSIFY` + `VALIDATE_DOMAIN` tags → high count suggests **A**
- Count `GENERATE` + `SCHEMA` tags → high count suggests **B**
- "hypothesis", "root cause", "investigate", "reproduce" → **C**
- Single-service wrapper with minimal decision logic → **D1**
- "spawn", "subagent", "dispatch", "CI/CD", "merge", "deploy" → **D2**
- Mostly guidelines, checklists, or "when X, do Y" rules → **E**

---

## Axis 2: Pipeline Shape

| Shape          | When                                                | Pipeline structure                           |
| -------------- | --------------------------------------------------- | -------------------------------------------- |
| **Sequential** | 3+ distinct phases where each output feeds the next | Multi-phase `m.instruct(format=PhaseSchema)` |
| **One-shot**   | Flat spec or all knowledge applies simultaneously   | Single `m.instruct(format=OutputSchema)`     |

For Types A, B, C: almost always **Sequential**.
For Types D1, D2: usually **One-shot** for the decision logic component.
For Type E: assess internal structure — named stages or sequential dependencies → Sequential; flat rules → One-shot.

---

## Axis 3: Tool Involvement

| Pattern                                      | Description                                                       | Generated files                                   |
| -------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------- |
| **P0: No tools**                             | Pure reasoning                                                    | No `tools.py`, no `dependencies.yaml`             |
| **P4: Tools provide input**                  | Tools run BEFORE pipeline; output feeds reasoning as parameters   | `dependencies.yaml`, optionally `loader.py`       |
| **P2: Pipeline calls tools (deterministic)** | LLM classifies intent; Python constructs tool calls from template | `tools.py` with allowlist, `constrained_slots.py` |
| **P3: Pipeline calls tools (LLM-directed)**  | LLM decides which tool to call and with what arguments            | `tools.py` with `m.react()`                       |

---

## Axis 4: Source Runtime

The source runtime determines which dialect doc applies. Detection is signal-based with weighted scoring.

### Signal weighting

Each detection signal has a weight:

- **Strong (2.0)**: definitive marker — unambiguous runtime indicator
- **Medium (1.0)**: characteristic pattern — common in this runtime, rare in others
- **Weak (0.5)**: circumstantial — present in this runtime but also in others

### Supported runtimes

| Runtime             | Strong signals                                          | Medium signals                                          | Weak signals                    |
| ------------------- | ------------------------------------------------------- | ------------------------------------------------------- | ------------------------------- |
| `agent_skills_std`  | `---` frontmatter + `name:`, `description:` YAML fields | `.md` extension, `model:` frontmatter key               | Single-file, no Python          |
| `claude_code`       | `CLAUDE.md`, `.claude/commands/` directory              | `bash_command:`, `allowed_tools:`                       | Markdown-primary                |
| `openclaw`          | `SOUL.md` + `AGENTS.md` in same directory               | `.md` files with `## Identity`, `## Rules` sections     | Multi-file workspace            |
| `letta`             | `.af` file extension, JSON with `agent_type` key        | `"human_input_pause"`, `"memory"` keys                  | Single JSON file                |
| `crewai`            | `crew.py` or `Crew(` in Python, `@CrewBase`             | `@agent`, `@task`, `@crew` decorators                   | YAML `agents.yaml`+`tasks.yaml` |
| `langgraph`         | `StateGraph(`, `add_node(`, `add_edge(`                 | `from langgraph` imports                                | Python with graph construction  |
| `autogen`           | `from autogen import` or `from autogen_agentchat`       | `OAI_CONFIG_LIST`, `AssistantAgent(`, `UserProxyAgent(` | Python multi-agent              |
| `openai_agents_sdk` | `Agent(instructions=`, `Runner.run_sync(`               | `@function_tool`, `handoffs=[`                          | `from agents import`            |
| `smolagents`        | `CodeAgent(`, `ToolCallingAgent(`                       | `from smolagents`, `additional_authorized_imports`      | `HfApiModel(`                   |

### R1 Hybrid detection

1. Compute weighted signal score for each runtime.
2. Find the two highest-scoring runtimes.
3. If their scores differ by ≤ 1.0 → classify as `hybrid`.
4. Tiebreaker precedence (when within threshold): `agent_skills_std` > `claude_code` > `openclaw` > `crewai` > `langgraph` > `autogen` > `letta` > `openai_agents_sdk` > `smolagents`.

If a spec provides `--source-runtime=<runtime>` on the command line, skip detection and use the override (record in `classification.json:source_runtime_override`).

### R2 — Generated SKILL.md suppression (re-run safety)

Melleafy Step 6 writes a generated `SKILL.md` inside `<package_name>/` for non-.md source runtimes (CrewAI, LangGraph, Letta, etc.). Because `<package_name>/` is a subdirectory, Step 0 does not scan it during signal computation — no suppression logic is needed for the normal case.

**Residual guard**: if a `SKILL.md` is found at the skill root itself (e.g., left from an older melleafy run that placed it there, or manually created), read the first 30 lines and look for `"auto-generated by Melleafy"`. If found:

1. **Exclude it** from signal computation — do not let its YAML frontmatter contribute to the `agent_skills_std` score.
2. **Add a warning** to `classification.json:warnings`: `"SKILL.md at skill root appears to be a melleafy-generated file — excluded from source runtime detection."`

**Scope**: applies only to `.md` files at the skill root containing the auto-generation marker. A genuine `SKILL.md` written by the user (without the marker) participates in signal scoring normally.

Unrecognised specs with no signals → `unknown` runtime. Melleafy can still process these using the generic inventory pass, but no dialect-specific mapping table applies.

---

## Axis 5: Interaction Modality

Eight modalities. Detection is explicit-first: look for declared modality signals in the source first; infer only if none are found.

| Modality                 | Declared by                                                           | Description                        |
| ------------------------ | --------------------------------------------------------------------- | ---------------------------------- |
| `synchronous_oneshot`    | Absence of other modality signals                                     | Request-in, response-out, no state |
| `streaming`              | "stream", "streaming output", `stream=True` references                | Token-by-token output              |
| `conversational_session` | Session state references, "conversation history", `m.chat()` patterns | Multi-turn with memory             |
| `review_gated`           | "approve", "human review", "gate", `result.interruptions`             | Human-in-the-loop approval step    |
| `scheduled`              | Cron patterns, "every N hours", `schedule:` frontmatter key           | Time-triggered execution           |
| `event_triggered`        | Webhook references, "on push", "on PR", event handler patterns        | Event-driven                       |
| `heartbeat`              | "monitor", "watchdog", "poll every", "continuous"                     | Polling loop                       |
| `realtime_media`         | Audio/video/image stream references                                   | Real-time media processing         |

**Explicit-first rule**: If the source has a `modality:` frontmatter key or an `activeHours:` / `isolatedSession:` directive (OpenClaw), treat those as definitive. Only apply inferential detection when no explicit signals exist.

**Composition validation** — some combinations are impossible (halt with error):

- `heartbeat` + `synchronous_oneshot` — contradictory

Multiple modalities are valid (e.g., `scheduled` + `event_triggered`). Record primary in `modality`, others in `secondary_modalities`.

---

## Cross-axis validation

After computing all five axes, run these consistency checks:

| Condition                                            | Action                                                                          |
| ---------------------------------------------------- | ------------------------------------------------------------------------------- |
| Axis 3 = P0 (no tools) AND Axis 1 = D1 (integration) | Halt — D1 without tools is incoherent                                           |
| Axis 2 = Sequential AND phase count ≤ 1              | Warn — Sequential classification needs at least 2 phases                        |
| Axis 5 = `realtime_media` AND Axis 1 ∈ {A, B}        | Warn — realtime media with analysis/generation archetypes may need host adapter |
| Axis 4 = `hybrid` AND no `--source-runtime` override | Warn — hybrid specs need manual review                                          |

---

## Output: `classification.json`

```json
{
  "format_version": "1.0",
  "archetype": "A",
  "archetype_confidence": 0.88,
  "shape": "Sequential",
  "shape_phase_count": 3,
  "tool_involvement": "Tools provide input",
  "tool_involvement_variant": "P4",
  "source_runtime": "openclaw",
  "source_runtime_override": null,
  "source_runtime_scores": { "openclaw": 5.5, "agent_skills_std": 1.0 },
  "hybrid_threshold_triggered": false,
  "modality": "synchronous_oneshot",
  "modality_confidence": 0.75,
  "secondary_modalities": [],
  "warnings": ["Axis 5 inferred — no explicit modality signals found"],
  "halt": null
}
```

If any halt condition fires, set `"halt": "<reason>"` and stop — do not proceed to Step 1a.

---

## Mapping report: Classification section

Document the classification as the first section of the mapping report (generated in Step 6):

```
## Classification

**Axis 1 — Reasoning Archetype**: Type A (Analytical Pipeline)
Evidence: 8 EXTRACT/CLASSIFY/VALIDATE_DOMAIN elements identified across §2–§5.

**Axis 2 — Pipeline Shape**: Sequential (3 phases)
Rationale: Phase 1 (extraction) feeds Phase 2 (assessment) feeds Phase 3 (report generation).

**Axis 3 — Tool Involvement**: P4 (Tools provide input)
Rationale: Spec reads code files and test outputs before analysis; no tool calls inside the pipeline.

**Axis 4 — Source Runtime**: openclaw (score 5.5; next: agent_skills_std 1.0)
Signals: SOUL.md + AGENTS.md directory structure (strong, 2.0); `## Identity` section in SOUL.md (medium, 1.0).

**Axis 5 — Interaction Modality**: synchronous_oneshot (inferred, confidence 0.75)
Rationale: No explicit modality declarations found; no session state, scheduling, or event signals detected.
```
