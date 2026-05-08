# Letta / MemGPT Dialect

**Version**: 1.0.0
**Status**: Second dialect doc; stress-tests the OpenClaw template against a single-file-JSON runtime.

**Prerequisite reading**: `spec.md` R1 (detection), R22 (dialect mapping contract), R21 (modality); `plans/dialects/openclaw.md` (reference template); `plans/generated-package-shape.md` (what the output looks like).

---

## What this document does

Describes the concrete rules melleafy applies when processing a **Letta** (formerly MemGPT) source spec. Letta is architecturally unusual among the surveyed runtimes: rather than a workspace of Markdown files, a Letta spec is primarily a single JSON document — the `.af` (Agent File). This dialect doc therefore adapts the template for a single-file-with-structured-content runtime.

Key Letta concepts readers should have in mind:

- **Agent File (`.af`)**: JSON-serialised agent state, Apache-2.0 licensed, secrets nulled on export.
- **Core memory blocks**: typed memory with 2,000-character limits per block — `persona` and `human` are default; others can be added.
- **Archival memory**: agent-immutable vector-store-backed knowledge, *not serialised into `.af` today* (Letta roadmap item).
- **Tools**: carry `source_code`, `json_schema`, `pip_requirements`, `npm_requirements`.
- **Sleep-time agents**: a second agent running in parallel that shares memory blocks, consolidating them every N primary-agent steps.

---

## 1. Detection signals

Step 0 classifies a spec as Letta when any of the following is present in the workspace:

| Signal | Strength | Notes |
|---|---|---|
| `*.af` file in workspace root | strong | The defining artefact — JSON with Letta-specific top-level keys |
| `letta.config.yaml` file | strong | Workspace config; only Letta uses this name |
| Spec body references `persona` or `human` blocks (memory-block vocabulary) | medium | Disambiguates from other JSON agent formats |
| Spec body references `archival_memory_insert` / `archival_memory_search` | medium | Letta-specific tool names |
| Spec body references `sleep-time agent` or `enable_sleeptime` | strong | Only Letta has this architecture |
| Spec body references `request_heartbeat` as a tool parameter | medium | Legacy MemGPT signal; deprecated in `letta_v1_agent` but still in many older specs |
| `agent_type: "memgpt_agent"` or `"letta_v1_agent"` in the `.af` | strong | Explicit agent type declaration |
| Mention of LETTA_PG_URI, LETTA_SERVER_PASSWORD, or LETTA_ENCRYPTION_KEY | medium | Server-side env vars identify a Letta deployment |

**Precedence note.** Letta signals are highly distinctive — the `.af` file alone is unambiguous. Unlike OpenClaw (where `AGENTS.md` can be confused with Claude Code), Letta has no file-name collisions with other runtimes in the v1 supported set.

**Hybrid threshold.** If Letta signals are within 1 of another runtime's signals, `Hybrid` applies per R1. In practice the most likely hybrid pairing is Letta + Claude Code (a project that uses Claude Code as its dev environment while targeting Letta at runtime); both runtimes' inventory rules should then apply.

---

## 2. File inventory rules (Step 1a)

**Letta's main source is a single JSON file — not a workspace of Markdown files.** Section 2 therefore differs in shape from the OpenClaw template: instead of listing per-file rules, it lists per-top-level-key rules within the `.af` document, plus a small set of sibling files when present.

### 2a. Primary file — the `.af` (Agent File)

The `.af` file is parsed once; every inventory rule below operates on a JSON path into the parsed structure.

| JSON path | Role in spec | Inventory action |
|---|---|---|
| `agent_type` | Determines agent architecture (`memgpt_agent` vs `letta_v1_agent` vs `voice_convo_agent`) | Single element; drives modality classification |
| `core_memory.blocks[].label == "persona"` | Persona text — C1 Identity | Block value becomes one element; `block.description` and `block.limit` become metadata |
| `core_memory.blocks[].label == "human"` | User context — C3 User facts | Same shape as persona |
| `core_memory.blocks[]` (other labels) | Custom memory blocks — C1 or C3 depending on purpose | Element per block; category inferred from `description` field |
| `tools[]` | Tool definitions — C6 Tools | One element per tool; includes `source_code`, `json_schema`, `pip_requirements`, `npm_requirements` |
| `tool_rules[]` | Constraints on tool invocation order — C2 Operating rules | Element per rule |
| `model_config` | LLM config (model name, temperature, etc.) — C8 Runtime env | Single element |
| `messages[]` | Conversation history | **Not inventoried** — conversation history is not a spec element |
| `embedding_config` | Embedding model config — C8 Runtime env | Single element |
| `enable_sleeptime` / `sleeptime_agent_frequency` | Sleep-time agent config — C9 Scheduling | Element per field; drives heartbeat modality |
| `block_ids[]` | Shared memory references to other agents | Element; flagged as **cross-agent reference** (v1 doesn't reproduce) |

### 2b. Sibling files

Files alongside the `.af` that may also be read:

| File | Role | Inventory action |
|---|---|---|
| `letta.config.yaml` | Server-side config | Parse YAML; contents become C8 runtime env elements |
| `.env` or `.env.example` | Environment variables — C7 Credentials | Parse; one element per var. **Rule: Letta `.env` values must be unquoted (issue #3069).** Preserve verbatim |
| `README.md` (if present) | Free-form notes about the agent | Treat as prose — NO_DECOMPOSE unless the spec body references it directly |

### 2c. Memory block character limit

Core memory blocks have a hard limit of **2,000 characters** per block. This is the Letta documentation's figure (and issue #7 confirms it); a widely-repeated 5,000-char number is from third-party content and is incorrect.

When a block's `value` exceeds its `limit` field (typically 2,000 but user-configurable), Letta truncates at runtime. Melleafy:

1. Inventories the full content regardless.
2. Emits a warning in the mapping report's "Conflicts flagged during inventory" section.
3. Does not truncate — same policy as OpenClaw's oversize files per Constitution Article 3 (source fidelity).

### 2d. Archival memory is NOT in the `.af`

Letta's archival memory (pgvector-backed) is **agent-immutable** and **not serialised into `.af` today** (Letta roadmap). If the spec body implies archival use — references to `archival_memory_insert`, `archival_memory_search`, or describes accumulating knowledge across sessions — melleafy infers a C5 Long-term memory dependency even without a corresponding `.af` field. The dependency is always `delegate_to_runtime` (no native Mellea backend).

### 2e. Missing files

Absence rules:

- `.af` file absent: this is the defining Letta signal; if auto-detection said "Letta" but no `.af` exists, Step 0's detection was wrong — halt with a diagnostic asking for source-runtime override or `.af` file.
- `letta.config.yaml` absent: normal; not every Letta spec has one.
- `.env` / `.env.example` absent: normal; credentials may come from server-side config.

---

## 3. Frontmatter / structured-content rules

**Letta has no Markdown frontmatter.** The `.af` file is structured JSON throughout. The template's Section 3 becomes "JSON content rules" for Letta.

### 3a. JSON parsing

`.af` files are parsed with `json.loads`. Parse failure halts Step 1a with a pointer to the offending line/column (standard `json.JSONDecodeError` output). Unlike OpenClaw's Markdown files, there's no "parse as free-form Markdown" fallback — if the JSON is malformed, there's no recovery.

### 3b. Schema validation

Letta publishes no formal `.af` JSON Schema (as of v1). Melleafy uses a **permissive parse**: required top-level keys are `agent_type` and `core_memory`; everything else is optional. Unknown top-level keys are preserved and surfaced in the mapping report's "Detected but not handled" section.

### 3c. Secrets are nulled on export

Letta's `.af` export convention nulls secrets (API keys, tokens) before writing. A `.af` file received from a colleague should never contain real credentials — they're referenced by env-var name but the values are `null`. Melleafy preserves this invariant: when generating `.env.example`, melleafy reads the env-var names from the `.af` but never expects the values to be populated.

### 3d. `.af` version field

The file may carry a `version` field naming the Letta schema version that produced it. If present, melleafy records it in the mapping report's Classification section for traceability. If the field names a version melleafy hasn't tested against, emit a warning; generation proceeds.

---

## 4. Dialect mapping table

| Source signal | Category | Default disposition | Generation target |
|---|---|---|---|
| `core_memory.blocks[label="persona"].value` | C1 | `bundle` (if ≤2,000 chars) | `config.PREFIX_TEXT`; inlined as `prefix=` on all `m.instruct()` calls |
| `core_memory.blocks[label="persona"].value` (oversize) | C1 | `bundle` with warning | Same; warning in mapping report |
| `core_memory.blocks[label="human"].value` | C3 | `bundle` | `config.USER_CONTEXT`; default at generation time |
| `core_memory.blocks[other]` with description naming user-overridable content | C3 | `external_input` | Pipeline parameter via `main.py` |
| `core_memory.blocks[other]` with description naming agent-internal state | C4 | `delegate_to_runtime` | `constrained_slots.py:recall_block(<label>)` stub; SETUP.md §4 |
| `tools[].source_code` (Python, described concretely) | C6 | `real_impl` | `tools.py:<tool_name>` |
| `tools[].json_schema` without `source_code` | C6 | `stub` | `constrained_slots.py:<tool_name>` stub; SETUP.md §8 documents the required signature |
| `tools[].source_code` (TypeScript) | C6 | `stub` | v1 melleafy does not generate TS; recorded as `delegate_to_runtime` with SETUP.md note |
| `tool_rules[]` (ordering / validation rules) | C2 | `bundle` | `requirements.py:OPERATING_REQUIREMENTS` entry |
| `tools[].pip_requirements` | C8 | `bundle` | Appended to `pyproject.toml:dependencies` |
| `tools[].npm_requirements` | C8 | *(not reproduced)* | Listed in mapping report's "Runtime-specific constructs not reproduced" |
| `model_config.model` | C8 | `bundle` | `config.MODEL_NAME` constant; SETUP.md §3 notes how to configure the Mellea backend to match |
| `embedding_config.embedding_model` | C8 | `delegate_to_runtime` | Only needed if C5 archival is used; SETUP.md §5 |
| `enable_sleeptime: true` | C9 | `delegate_to_runtime` | `config.SCHEDULE_CONFIG`; SETUP.md §6; modality = `heartbeat` |
| `sleeptime_agent_frequency` | C9 | `delegate_to_runtime` | Populates `config.SCHEDULE_CONFIG.cadence` with "every N primary-agent steps" — not wall-clock time |
| `tools[].request_heartbeat: true` (legacy MemGPT) | — | *(not reproduced)* | Listed in "Runtime-specific constructs not reproduced"; deprecated in `letta_v1_agent` |
| Spec body references `archival_memory_insert` / `archival_memory_search` (no `.af` field) | C5 | `delegate_to_runtime` | `constrained_slots.py:archival_insert`, `archival_search`; SETUP.md §5 |
| `block_ids[]` (shared memory with other agents) | — | *(deferred)* | Listed in Provenance appendix's "Detected but not handled" — cross-agent memory sharing is a Deferred Item |
| `messages[]` (conversation history) | — | `remove` | Not reproduced; conversation history is not spec content |
| `agent_type: "memgpt_agent"` | — | informational | Recorded in mapping report; drives some downstream modality decisions |
| `agent_type: "letta_v1_agent"` | — | informational | Same |
| `agent_type: "voice_convo_agent"` | — | informational | Drives modality = `realtime_media` |
| `LETTA_PG_URI`, `LETTA_SERVER_PASSWORD`, `LETTA_ENCRYPTION_KEY` in env | C7 | `external_input` | `.env.example`; SETUP.md §2 |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `E2B_API_KEY` in env | C7 | `external_input` | Same — declared even if not directly referenced in `.af` |

**Override semantics.** Default dispositions are overridable via `--dependencies=ask` or `--dependencies=config:<path>` per the standard R22 contract.

---

## 5. Modality signals (Step 0 Axis 5, R21)

Letta has the second-strongest modality-declaration surface after OpenClaw — explicit fields in the `.af` determine modality deterministically.

| Signal | Modality classification |
|---|---|
| `enable_sleeptime: true` | **`heartbeat`** — state-aware periodic invocation via sleep-time agent |
| `agent_type: "voice_convo_agent"` | **`realtime_media`** — voice-first bidirectional audio |
| `agent_type: "memgpt_agent"` or `"letta_v1_agent"` with no sleep-time | **`conversational_session`** — Letta's default model ("the agent is the state"; clients don't pass history) |
| Spec describes `POST /v1/agents/{id}/schedule` usage | **`scheduled`** — wall-clock cron scheduled via Letta API |
| None of the above | **`conversational_session`** — Letta's implicit default even without explicit flags |

**Composition.** Letta specs can simultaneously declare `conversational_session` (default) and `heartbeat` (via sleep-time) — a primary agent in conversation with a user while a sleep-time agent consolidates memory in the background. When both apply, `conversational_session` is primary and `heartbeat` is secondary. `scheduled` with `heartbeat` is also possible but unusual — flag for manual review per R21 composition rules.

**Generated shape per R21.** Letta's default `conversational_session` is **Mellea-native** — it emits to shape §5c (`def run_pipeline(session: MelleaSession, message: str) -> str`). `heartbeat` and `scheduled` are host-needing; they fall back to synchronous_oneshot shape with SETUP.md §6/§7 guidance. `realtime_media` is also host-needing (requires LiveKit / Deepgram / Retell integration).

### 5a. `request_heartbeat` — NOT a modality

Legacy MemGPT's per-tool `request_heartbeat` parameter is sometimes confused with Letta sleep-time heartbeats but is architecturally different — it's an **intra-turn control signal** that schedules the next model step, not an external cadence. It's deprecated in `letta_v1_agent`. Melleafy records `request_heartbeat: true` tool settings in the mapping report but does not reproduce them; the generated pipeline uses Mellea's native control flow.

---

## 6. Quirks and workarounds

### 6a. Archival memory absence in `.af`

The biggest Letta-specific quirk: specs that clearly depend on archival memory (the spec body says "search across past sessions," "accumulate knowledge over time") often have NO corresponding field in the `.af` because archival passages aren't serialised there. Melleafy handles this by:

1. Inspecting the spec body / description text for archival-memory vocabulary.
2. Inferring a C5 dependency even without an `.af` field.
3. Marking it with `source_of_decision: "inferred"` in the dependency plan.
4. Surfacing prominently in the mapping report: "Archival memory inferred from spec body; `.af` file does not contain archival passages."

This is the only place in the Letta dialect where dependency detection relies on inference rather than structured fields.

### 6b. Sleep-time frequency is NOT wall-clock time

Letta's `sleeptime_agent_frequency` is expressed as "every N primary-agent steps" — not minutes, not cron expressions. A value of `5` means "after every 5 messages the primary agent processes." This is a fundamentally different trigger model from wall-clock scheduling.

Melleafy preserves this in `config.SCHEDULE_CONFIG`:

```python
SCHEDULE_CONFIG: Final[dict] = {
    "cadence": "every-5-primary-steps",  # Letta-specific; not a cron expression
    "source": "letta_sleeptime",
}
```

SETUP.md §6 explains that a host adapter must count primary-agent steps (not wall-clock time) to correctly dispatch the sleep-time agent. This limits host-adapter options — plain `cron` or APScheduler can't implement this without additional state.

### 6c. `.af` file size can be very large

Unlike OpenClaw's bootstrap files (20K per file limit), Letta `.af` files can be large — particularly when tool `source_code` is serialised inline and there are many tools. A production Letta agent's `.af` can approach 1 MB. Step 1a's 10 MB per-file cap accommodates this; no Letta-specific limit.

### 6d. Secret-nulling on export

When a `.af` file is exported from Letta, secrets are nulled to prevent leakage. Melleafy must preserve this invariant: any `null`-valued credential field is treated as "value is set at runtime from env" rather than "value is literally null." The consistency lint in `plans/lints/melleafy-json-consistency.md` should flag a package that bundles a non-null credential value that traces back to a `null` `.af` field.

### 6e. `tool_rules[]` vs `tools[].default_requires_approval`

Letta has two distinct concepts that look similar:

- `tool_rules[]` — top-level list of constraints on how tools are invoked (ordering, preconditions)
- `tools[].default_requires_approval` — per-tool boolean for approval-gated invocation

The first is C2 Operating rules (bundled as Requirements). The second is a C6 Tool attribute with a modality implication (`review_gated` as secondary). Melleafy distinguishes these in inventory:

- `tool_rules[]` rows → elements tagged `DECIDE` or `VALIDATE_OUTPUT`, category C2
- `default_requires_approval: true` → element tagged `CONVERSE` (since approval implies human input), category C6, with secondary modality `review_gated`

### 6f. Inter-agent messaging tools

Letta's `send_message_to_agent_async`, `send_message_to_agent_and_wait_for_reply`, and `send_message_to_agents_matching_all_tags` are cross-agent delegation primitives. v1 melleafy does not generate cross-agent call code — these are recorded as Deferred in the Provenance appendix. The corresponding tool declarations in `.af` are inventoried (they're tools) but their dispositions become `stub` with SETUP.md documenting that cross-agent wiring is a v2 candidate.

---

## 7. Reference inventory output (illustrative)

For a minimal Letta spec with a `.af` file containing persona, human, one tool, and `enable_sleeptime: true`:

### Inventory (abridged)

```json
{
  "elements": [
    {"element_id": "elem_001", "source_file": "agent.af", "source_lines": "json:core_memory.blocks[0]", "tag": "CONVERSE", "category": "C1", "content_summary": "Persona: helpful research assistant"},
    {"element_id": "elem_002", "source_file": "agent.af", "source_lines": "json:core_memory.blocks[1]", "tag": "CONFIG", "category": "C3", "content_summary": "Human: Alice, researcher at Acme Labs"},
    {"element_id": "elem_015", "source_file": "agent.af", "source_lines": "json:tools[0]", "tag": "TOOL_TEMPLATE", "category": "C6", "content_summary": "search_papers tool (Python, real_impl)"},
    {"element_id": "elem_042", "source_file": "agent.af", "source_lines": "json:enable_sleeptime + sleeptime_agent_frequency", "tag": "ORCHESTRATE", "category": "C9", "content_summary": "Sleep-time agent every 5 primary-agent steps"}
  ]
}
```

Note the `source_lines` convention: for JSON paths, the format is `"json:<jq-style-path>"` rather than line ranges. This is a dialect-specific extension of the standard `source_lines` format. Step 1b is aware of this convention and surfaces it faithfully in the mapping report.

### Element mapping (abridged)

```json
{
  "mappings": [
    {"element_id": "elem_001", "target_file": "config.py", "target_symbol": "PREFIX_TEXT", "primitive": "bundle"},
    {"element_id": "elem_002", "target_file": "config.py", "target_symbol": "USER_CONTEXT", "primitive": "bundle"},
    {"element_id": "elem_015", "target_file": "tools.py", "target_symbol": "search_papers", "primitive": "real_impl"},
    {"element_id": "elem_042", "target_file": "config.py", "target_symbol": "SCHEDULE_CONFIG", "primitive": "delegate"}
  ]
}
```

### Dialect-specific notes in the mapping report

For a Letta spec, the mapping report's Provenance appendix includes:

- A "Runtime-specific constructs not reproduced" section listing `npm_requirements`, `request_heartbeat`, cross-agent `block_ids`.
- An "Archival memory inference" note if C5 was inferred from spec body rather than `.af` fields.
- A note on the sleep-time cadence: "Cadence is expressed as primary-agent steps, not wall-clock time. Host adapter must track step counts."

---

## 8. Deferred Letta features (not handled in v1)

- **Archival memory full serialisation.** When Letta adds archival passages to `.af` (roadmap), melleafy's C5 inference (§6a) becomes unnecessary — the passages can be read directly.
- **Cross-agent memory sharing via `block_ids`.** v1 records but does not reproduce.
- **Inter-agent messaging tools** (`send_message_to_agent_async`, etc.). v1 stubs; v2 could generate delegation scaffolding.
- **TypeScript tools** (`tools[].source_code` with TS language). v1 doesn't generate TS; flagged as not reproduced.
- **`auth-profiles.json`** — Letta's credential store format. v1 doesn't parse; users manage credentials via env.
- **Letta native voice** (`voice_convo_agent` agent type). v1 classifies as `realtime_media` modality and stubs; v2 could generate LiveKit-compatible wrappers.
- **Letta-native scheduling** (POST /schedule). v1 records as C9 delegate; v2 could emit a cron-scheduled wrapper.

---

## 9. Cross-references

- `spec.md` R1, R21, R22 — the contracts this dialect implements
- `spec.md` Deferred Items — harness adapter, native memory backend (both particularly relevant for Letta)
- `plans/dialects/openclaw.md` — template this dialect adapts
- `plans/generated-package-shape.md` — what the generated package looks like
- `glossary.md` — `dialect`, `disposition`, `interaction modality`
- `melleafy.json` schema — the manifest fields this dialect populates

---

## 10. Ratification notes

This dialect doc v1.0.0 was the second one drafted, selected deliberately to stress-test the OpenClaw template against a fundamentally different source-runtime shape (single JSON file vs. Markdown workspace).

**What the template survived unchanged:**
- Section 1 (Detection signals) — worked identically
- Section 4 (Dialect mapping table) — the four-column shape is runtime-agnostic; the "source signal" column became JSON paths instead of file references
- Section 5 (Modality signals) — runtimes express modality differently but the axis structure is fixed
- Sections 6–10 — shape translated directly

**What the template needed to adapt:**
- Section 2 (File inventory) — became "JSON path inventory inside the `.af`" instead of "files in workspace." The underlying intent (name every source surface inventoried) is preserved; the structure is different.
- Section 3 (Frontmatter) — "Markdown frontmatter" doesn't apply; replaced with "JSON parsing and structured-content rules."
- Section 7 (Reference inventory output) — `source_lines` format extended to include a `"json:<path>"` convention for JSON-derived elements.

**What this tells us about the template's generality.** The template is a good fit for any runtime that has:
(a) detectable signals, (b) a set of source surfaces from which elements are extracted, (c) a category-per-surface mapping, (d) modality declarations somewhere in the spec.

Letta satisfies all four with a structurally different source format than OpenClaw, and the template accommodated that without restructuring. The other seven dialect docs (Claude Code, CrewAI, LangGraph, AutoGen, Agents SDK, smolagents, Hybrid, Agent Skills std) should all fit the same shape — they're mostly Markdown-file or Python-code workspaces, which are less unusual than Letta's JSON-file model.

Open questions:

- **The "json:<jq-path>" source_lines convention** (§7) is my invention. If we add more structured-file runtimes (e.g., any dialect targeting YAML-heavy configs), we should extend this formally — perhaps to `source_range: {"format": "json_path" | "line_range", "value": "..."}` in `inventory.json`. Worth formalising during Step 1b implementation.
- **§6a archival memory inference** is the only place in Letta's dialect where inventory relies on text inspection rather than structured fields. This is brittle — keyword matching on "archival" or "across sessions" may miss or false-positive. An LLM-assisted inference would be more robust but reintroduces KB 5 risk. Flagged for revisit if the heuristic proves inadequate.
- **§6b sleep-time frequency in steps, not time.** The `config.SCHEDULE_CONFIG.cadence: "every-5-primary-steps"` format needs corresponding recognition in the `melleafy.json` schema's `schedule_config` — the current schema has `interval`, `cron`, `event` variants but not "step-counted." Worth adding a fourth variant `step_counted` in a manifest_version 1.2.0, or treating Letta sleep-time as a special case of `interval` with unusual units.
- **§2a `messages[]` exclusion.** I excluded conversation history from inventory because it's runtime state, not spec content. Worth confirming: are there Letta agent specs where `messages[]` encodes system-prompt-like context the user wants reproduced? If yes, we'd need a rule for "exclude unless the user explicitly opts in."
- **Cross-agent `block_ids` and `send_message_to_agent_*`** are deferred but common. A Letta user writing a multi-agent spec will hit these on day one. Worth considering whether v1 should at least emit a SETUP.md section pointing at the v2 adapter work, rather than silently listing them as deferred.
