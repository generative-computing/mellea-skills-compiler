# OpenClaw Dialect

**Version**: 1.0.0
**Status**: Reference template — other dialect docs should follow this shape

**Prerequisite reading**: `spec.md` R1 (detection), R22 (dialect mapping contract), R21 (modality); `constitution.md` Articles 3, 7, 8, 13.

---

## What this document does

Describes the concrete rules melleafy applies when processing an **OpenClaw** source spec. Covers detection (Step 0), file inventory (Step 1a), the four-column mapping table (R22), modality signals (R21), and runtime-specific quirks.

When a future contributor wants to add a new source runtime, they write a dialect doc in this shape. When a future melleafy run encounters an OpenClaw spec, the code paths implementing each section below should point here.

---

## 1. Detection signals

Step 0 classifies a spec as OpenClaw when any of the following signals are present in the workspace directory (the source spec's parent):

| Signal | Strength | Notes |
|---|---|---|
| `SOUL.md` file | strong | Bootstrap file — highly distinctive |
| `IDENTITY.md` file | strong | Bootstrap file |
| `AGENTS.md` file | medium | Also used by some Claude Code conventions; the full OpenClaw set is what disambiguates |
| `HEARTBEAT.md` file | strong | Only OpenClaw uses this filename |
| `BOOTSTRAP.md` file | strong | Self-destructing first-run ritual; highly distinctive |
| `MEMORY.md` + `memory/` directory | strong | The directory pattern is OpenClaw-specific |
| `memory-wiki/` directory with `entities/`, `concepts/`, etc. | strong | OpenClaw wiki structure |
| `~/.openclaw/` config path exists on disk | strong | Per-user OpenClaw installation |
| `openclaw.json` with `agents.defaults.heartbeat` | strong | Workspace-level config |
| `TOOLS.md` + `USER.md` + `AGENTS.md` triad | medium | Partial bootstrap set |

**Precedence note.** Because OpenClaw reuses the `AGENTS.md` filename, single-signal detection on `AGENTS.md` alone is insufficient. Classification as OpenClaw requires at least one *strong* signal, or two *medium* signals. If only `AGENTS.md` matches (no stronger signals), classification defaults to Claude Code per the R1 precedence ordering (Claude Code > OpenClaw when tied).

**Hybrid threshold.** If OpenClaw signal count is within 1 of another runtime's signal count, classification is `Hybrid` per R1 and both runtimes' inventory rules run; the user should override if they know better.

---

## 2. File inventory rules (Step 1a)

When classification is OpenClaw, Step 1a reads the following files from the workspace:

### 2a. Bootstrap files

| File | Role in spec | Inventory action |
|---|---|---|
| `SOUL.md` | Persona, values, tone (C1 Identity) | Read entire content; split into elements per heading |
| `IDENTITY.md` | External presentation — name, role, emoji, avatar (C1 Identity) | Read entire content; each field becomes an element |
| `AGENTS.md` | Operating rules (C2) | Read content; each rule / directive becomes an element |
| Scoped `docs/AGENTS.md`, `ui/AGENTS.md` | Directory-scoped operating rules (C2) | Read if present; elements tagged with scope |
| `USER.md` | User facts (C3) | Read content; each fact becomes an element |
| `TOOLS.md` | Tool guidance (C6, doc-only) | Read content — this is *narrative about tools*, not tool definitions |
| `MEMORY.md` | Long-term memory layout / conventions (C5) | Read content; elements describe the memory structure |
| `HEARTBEAT.md` | Scheduling (C9) | Read content; cadence declarations become elements |
| `BOOTSTRAP.md` | First-run ritual (self-destructs) | Note presence; **do not bundle into generated code** (disposition: `remove` with rationale) |

### 2b. Memory / runtime state files

| Path | Role | Inventory action |
|---|---|---|
| `memory/YYYY-MM-DD.md` (today + yesterday) | Daily logs (C4 Short-term state) | Inventory the *file existence*, not contents — content is ephemeral and not bundled |
| `memory-wiki/entities/` | Entity notes (C5) | Inventory file list; element per file with frontmatter parsed |
| `memory-wiki/concepts/` | Concept notes (C5) | Same as entities |
| `memory-wiki/syntheses/` | Synthesis notes (C5) | Same |
| `memory-wiki/sources/` | Source notes (C5) | Same |
| `memory-wiki/_views/` | View definitions (C5) | Inventory — these are often generated |

### 2c. Config

| File | Role | Inventory action |
|---|---|---|
| `openclaw.json` (workspace level) | Agent config including `heartbeat.*` fields | Parse JSON; heartbeat config becomes C9 element |
| `~/.openclaw/` | User-level config | Do not read; note existence as detection signal only |

### 2d. Character limits and truncation

**Per-file limit**: 20,000 characters per bootstrap file.
**Aggregate budget**: 150,000 characters across all bootstrap files.

OpenClaw silently truncates files that exceed the per-file limit. When melleafy detects a file over 20,000 chars, it emits a **warning** (not a fatal error) and records the detection in the mapping report's "Conflicts flagged during inventory" section. Generation proceeds with the full content; if the content is used as `prefix=` text per the mapping table below, generation also emits a runtime warning that the OpenClaw runtime would have truncated it.

### 2e. Missing-file markers

OpenClaw injects a placeholder when a bootstrap file is absent. A missing file is **not an error**; inventory simply records it as absent. The only time absence becomes a problem is when the spec body explicitly references a missing file — that's a spec-author bug and melleafy records it in the mapping report but proceeds.

---

## 3. Frontmatter rules

**OpenClaw bootstrap files generally have no YAML frontmatter.** Parse them as free-form Markdown. Two exceptions:

1. `memory-wiki/*/*.md` files may have `claims:` frontmatter — a list of structured assertions. Parse if present.
2. `openclaw.json` is JSON, not Markdown with frontmatter; its field layout is the authoritative schema.

When generating a Mellea pipeline from an OpenClaw source, melleafy does **not** emit an OpenClaw-style `openclaw.json` — the generated pipeline is target-neutral Mellea Python. OpenClaw-specific config that would be needed to redeploy the pipeline back into OpenClaw is emitted as a SETUP.md section under "Host adapter — OpenClaw."

---

## 4. Dialect mapping table

This is the R22 contract: source signal → dependency category → default disposition → generation target.

| Source signal | Category | Default disposition | Generation target |
|---|---|---|---|
| `SOUL.md` body (persona, voice) | C1 | `bundle` | `config.PREFIX_TEXT`; inlined as `prefix=` argument to all `m.instruct()` calls |
| `IDENTITY.md:name` | C1 | `bundle` | `config.AGENT_NAME` constant |
| `IDENTITY.md:role` | C1 | `bundle` | `config.AGENT_ROLE` constant |
| `IDENTITY.md:emoji`, `IDENTITY.md:avatar` | C1 | `bundle` | `config.AGENT_METADATA` dict |
| `AGENTS.md` individual rule | C2 | `bundle` | Entry in `requirements.py:OPERATING_REQUIREMENTS` + prompt-text inline in relevant `m.instruct()` calls |
| Scoped `docs/AGENTS.md` | C2 | `bundle` | Prompt-text applied only in `m.instruct()` calls tagged for docs context |
| `USER.md:stable_fact` | C3 | `bundle` | `config.USER_CONTEXT` constant |
| `USER.md:overridable_fact` | C3 | `external_input` | Pipeline parameter `--user-context` on `main.py`; default from USER.md |
| `TOOLS.md` narrative about a tool | C6 | `bundle` (doc only; does not grant permissions) | Prompt text appended to the relevant tool's `m.instruct()` context |
| `MEMORY.md` body | C5 | `delegate_to_runtime` | `constrained_slots.py:recall_memory` stub; SETUP.md §5 (Long-term memory backend) |
| `memory/YYYY-MM-DD.md` daily log | C4 | `delegate_to_runtime` | `constrained_slots.py:load_working_state` stub; SETUP.md §4 (Short-term state backend) |
| `memory-wiki/entities/*.md` with `claims:` frontmatter | C5 | `delegate_to_runtime` | Stub + SETUP.md §5.1 (Wiki-structured memory); if present, emit a Known-Issue note about `claims:` parsing not being part of v1 |
| `HEARTBEAT.md` body | C9 | `delegate_to_runtime` | `config.SCHEDULE_CONFIG`; SETUP.md §6 (External scheduler); modality sets to `heartbeat` (R21) |
| `openclaw.json:heartbeat.every` | C9 | `delegate_to_runtime` | `config.SCHEDULE_CONFIG:cadence`; also drives `melleafy.json:schedule_config.type=interval` |
| `openclaw.json:heartbeat.activeHours` | C9 | `delegate_to_runtime` | `config.SCHEDULE_CONFIG:active_hours`; SETUP.md §6.1 notes "Mellea pipeline has no day-gating; wrap invocation in the scheduler" |
| `openclaw.json:heartbeat.lightContext` | C9 | *(not reproduced)* | Listed in mapping report's "Runtime-specific constructs not reproduced" — Mellea always passes full context |
| `openclaw.json:heartbeat.isolatedSession` | C9 | *(not reproduced)* | Same — Mellea has no equivalent session isolation policy |
| `BOOTSTRAP.md` presence | — | `remove` | Listed in mapping report's "Removed during audit" table with rationale: "BOOTSTRAP.md is a one-shot first-run ritual that self-destructs; not reproduced in generated pipeline" |
| `agents.list[]` entry (another agent in workspace) | C2 | *(deferred)* | Listed in Provenance appendix's "Detected but not handled" — cross-agent delegation is a Deferred Item |

**Override semantics.** Every row shows the *default* disposition. Any row can be overridden via `--dependencies=ask` elicitation or a `--dependencies=config:<path>` pre-authored decisions file. Overrides are recorded with `source_of_decision: "user"` in `dependency_plan.json` and `melleafy.json:categories_resolved`.

---

## 5. Modality signals (Step 0 Axis 5, R21)

OpenClaw has the strongest modality signal of any surveyed runtime: the `openclaw.json:heartbeat.*` block.

| Signal | Modality classification |
|---|---|
| `openclaw.json:heartbeat.every` present (e.g., `"30m"`, `"1h"`) | **`heartbeat`** — state-aware periodic self-invocation |
| `HEARTBEAT.md` present with cadence declaration in body | **`heartbeat`** — same |
| `HOOK.md` file present or `openclaw.json:hooks[]` entries | **`event_triggered`** — external event fires the agent |
| `openclaw cron add` invocations mentioned in workspace | **`scheduled`** (distinct from `heartbeat` — no state-aware skipping) |
| Neither heartbeat, hooks, nor cron present | **`synchronous_oneshot`** (default) |

**Composition.** OpenClaw specs can declare `heartbeat` + `event_triggered` simultaneously (the HEARTBEAT wakes on a cadence but can also be triggered via `openclaw system event --text "..." --mode now`). When both are detected, `heartbeat` is recorded as primary and `event_triggered` as secondary in `classification.json`.

**Generated shape per R21.** All OpenClaw heartbeat specs classify as host-needing modalities, so the generated Python is `synchronous_oneshot`-shaped (`run_pipeline()` callable), with:

- `config.SCHEDULE_CONFIG` populated with the detected cadence
- `melleafy.json:modality: "heartbeat"` (or `"event_triggered"`, or both)
- SETUP.md §6 naming candidate host adapters: APScheduler + SQLite (custom), or redeploying into OpenClaw itself via `agents.defaults.heartbeat` config

---

## 6. Quirks and workarounds

### 6a. BOOTSTRAP.md self-destructs

Source specs frequently reference BOOTSTRAP.md content in the main spec body ("as established in BOOTSTRAP.md..."). After the first OpenClaw run, BOOTSTRAP.md is deleted, so references to it are references to content that no longer exists at runtime. Melleafy handles this by:

1. Reading BOOTSTRAP.md during inventory (treating it as present).
2. Inlining any BOOTSTRAP.md content the spec body references into the relevant C1/C2 generated target (SOUL persona, AGENTS rules).
3. Marking BOOTSTRAP.md with `disposition: remove` in the dependency plan — it doesn't become its own bundled artifact.
4. Recording the inlining decision in the mapping report's "Runtime-specific constructs not reproduced."

### 6b. `activeHours` is not generatable in Mellea

OpenClaw's `heartbeat.activeHours` (e.g., `09:00-18:00`) is a scheduler-level concern. Mellea has no day-gating primitive. This is not a failure — it's a limitation reflected in SETUP.md §6.1:

> Your OpenClaw spec declared `activeHours: 09:00-18:00`. Mellea has no equivalent; the generated pipeline will run whenever its scheduler invokes it. Configure your scheduler (APScheduler, cron, OpenClaw itself) to respect active hours.

The `melleafy.json:schedule_config.active_hours` field *does* preserve the declaration, so a v2 host-adapter tool can re-emit it into the target scheduler's native format.

### 6c. `lightContext: true` is not generatable

Mellea always passes full context to each session. OpenClaw's `lightContext` optimisation has no equivalent. Recorded in the mapping report's "Runtime-specific constructs not reproduced" section. Not a SETUP.md concern because it's an optimisation, not a correctness issue.

### 6d. `memory-wiki/` wikilinks

`memory-wiki/*/*.md` files use `[[wikilink]]` syntax for cross-references. Mellea has no wiki primitive. When a spec body references a specific wiki file, melleafy:

1. Reads the referenced file and inventories its content.
2. If the reference is for reading (the agent consults the wiki), maps to `C5 delegate_to_runtime` with a stub.
3. If the reference is for writing (the agent updates the wiki), maps to `C5 delegate_to_runtime` with a stub *and* flags the operation as "side-effect on shared state" in the mapping report.

Wikilink *rewriting* (changing `[[old-name]]` references when the target file is renamed) is a Deferred Item — v1 generates stubs that raise `NotImplementedError` on rewrite operations.

### 6e. `claims:` frontmatter parsing

Some `memory-wiki/*/*.md` files have structured `claims:` frontmatter (a YAML list of assertions). Parsing semantics — whether each claim is independent, whether they compose, how they're scoped — is not fully documented in OpenClaw's published spec. Melleafy v1 treats the `claims:` list as opaque metadata: it's preserved in the inventory and referenced in the mapping report, but the generated stub does not attempt to reason over it structurally. Full `claims:` support is a Deferred Item.

### 6f. Heartbeat skip semantics

OpenClaw heartbeats are *state-aware*: the agent reads `memory/YYYY-MM-DD.md` or similar state files and decides whether to act. The stated skip outcomes include `HEARTBEAT_OK` (no action needed) and various `reason=empty-heartbeat-file`, `reason=no-tasks-due` patterns.

Melleafy's generated pipeline implements the cognition (decide whether to act) but not the skip mechanism itself — the SETUP.md §6 guidance explains that the host adapter is responsible for interpreting the pipeline's return value and translating skips into OpenClaw's wire protocol.

---

## 7. Reference inventory output (illustrative)

For a minimal OpenClaw spec with SOUL.md, IDENTITY.md, AGENTS.md, and HEARTBEAT.md, the inventory and mapping outputs look like this:

### Inventory (abridged)

```json
{
  "elements": [
    {"element_id": "elem_001", "source_file": "SOUL.md", "source_lines": "3-28", "tag": "CONVERSE", "category": "C1", "content_summary": "Warm, curious tone; prefers Socratic questioning"},
    {"element_id": "elem_002", "source_file": "IDENTITY.md", "source_lines": "1", "tag": "CONFIG", "category": "C1", "content_summary": "name: ticket-triage"},
    {"element_id": "elem_015", "source_file": "AGENTS.md", "source_lines": "5-7", "tag": "DECIDE", "category": "C2", "content_summary": "Rule: never auto-close a ticket without confirmation"},
    {"element_id": "elem_042", "source_file": "HEARTBEAT.md", "source_lines": "1-5", "tag": "ORCHESTRATE", "category": "C9", "content_summary": "Run every 30m during business hours"}
  ]
}
```

### Element mapping (abridged)

```json
{
  "mappings": [
    {"element_id": "elem_001", "target_file": "config.py", "target_symbol": "PREFIX_TEXT", "primitive": "bundle", "mellea_construct": "prefix= argument on all m.instruct"},
    {"element_id": "elem_002", "target_file": "config.py", "target_symbol": "AGENT_NAME", "primitive": "bundle", "mellea_construct": "constant"},
    {"element_id": "elem_015", "target_file": "requirements.py", "target_symbol": "OPERATING_REQUIREMENTS", "primitive": "Requirement", "mellea_construct": "Requirement(description=..., validation_fn=...)"},
    {"element_id": "elem_042", "target_file": "config.py", "target_symbol": "SCHEDULE_CONFIG", "primitive": "delegate", "mellea_construct": "constant + SETUP.md §6"}
  ]
}
```

### Dialect-specific notes in the mapping report

The mapping report for an OpenClaw spec contains, in its Provenance appendix:

- A "Runtime-specific constructs not reproduced" section listing `activeHours`, `lightContext`, `isolatedSession`.
- A "Removed during audit" entry for BOOTSTRAP.md if present.
- A "Detected but not handled (deferred)" section noting any `memory-wiki/` wikilinks, `claims:` frontmatter, or cross-agent `agents.list[]` references.

---

## 8. Deferred OpenClaw features (not handled in v1)

Listed here so users whose OpenClaw specs exercise one of these know they're seen, not silently dropped.

- **`claims:` frontmatter structured parsing.** v1 treats as opaque.
- **`memory-wiki/` wikilink rewriting.** v1 stubs raise on rewrite operations.
- **Cross-agent delegation via `agents.list[]`.** v1 records but does not generate cross-agent call code.
- **OpenClaw `hooks` with handler.ts.** v1 classifies as `event_triggered` modality but does not emit the handler.ts itself — TypeScript emission is out of scope.
- **OpenClaw-native host adapter.** v1 generates Mellea-neutral Python + SETUP.md guidance; a `melleafy export --host=openclaw` command that emits a ready-to-drop-in OpenClaw workspace is a v2 candidate.

---

## 9. Cross-references

- `spec.md` R1, R21, R22 — the contracts this dialect implements
- `spec.md` Deferred Items (harness adapter generation, native memory backend) — where OpenClaw features land that we don't handle in v1
- `constitution.md` Article 3 (source fidelity), Article 13 (deferred features explicit)
- `glossary.md` — `dialect`, `disposition`, `interaction modality`
- `melleafy.json` schema — the manifest fields this dialect populates
- Other dialect docs in `plans/dialects/` — their shape mirrors this one

---

## 10. Ratification notes

This dialect doc v1.0.0 was drafted as the first concrete subsidiary of `plan.md`, and intentionally serves as the template for the other eight dialects. If its structure proves wrong during implementation, it needs revision *first*, before the other dialect docs are drafted against it.

Open questions:

- Section 2d character limits — are these current OpenClaw numbers or historical? Worth validating against the latest OpenClaw docs before finalising.
- Section 4's mapping table is the core deliverable. Every row is a commitment. Any row that's wrong means v1 generates wrong code for that signal.
- Section 6 quirks — are there OpenClaw-specific things we're missing? Likely yes; this is the section that will grow most as real specs are encountered.
