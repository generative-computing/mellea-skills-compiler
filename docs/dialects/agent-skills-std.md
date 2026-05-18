# Agent Skills std Dialect

**Version**: 1.0.0
**Status**: Fifth dialect doc. The open-standard form — deliberately minimal and runtime-neutral. Shares its frontmatter core with Claude Code; everything distinctive about it is what it doesn't have.

**Prerequisite reading**: `spec.md` R1 (detection), R22 (dialect mapping contract), R21 (modality); `plans/dialects/openclaw.md` (reference template); `plans/dialects/claude-code.md` (the superset — Agent Skills std's extensions live there); `plans/generated-package-shape.md` (output shape).

---

## What this document does

Describes the rules melleafy applies when processing an **Agent Skills std** source spec. Agent Skills std is the open specification at agentskills.io — a minimal, runtime-neutral format for packaging agent instructions. It predates and is independent of any specific runtime. Claude Code, Codex, Cursor, and others layer their own invocation conventions on top.

What makes Agent Skills std distinctive is not its content but its **restraint**: it specifies packaging and progressive disclosure, and deliberately punts invocation modality, tool execution, and runtime concerns to the host.

Key Agent Skills std concepts readers should have in mind:

- **Progressive disclosure**: metadata (~100 tokens), instructions (<5000 tokens), resources loaded as needed.
- **Six-field frontmatter**: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools` — and nothing else under the open standard.
- **The Anthropic `quick_validate.py` validator**: rejects unknown keys. Strict allow-list.
- **Three conventional directories**: `scripts/`, `references/` (or `reference/`), `assets/`.
- **No runtime fields**: no `.claude/`, no `settings.json`, no `langgraph.json`, no `openclaw.json`. If those exist, the spec is a superset runtime, not Agent Skills std.

**Relationship to Claude Code.** Claude Code is a strict superset of Agent Skills std — every Agent Skills field works in Claude Code, plus the roughly dozen extensions documented in `plans/dialects/claude-code.md` §3. This doc is **not** a subset-by-reference; it's written to stand alone so an Agent Skills implementation doesn't require a Claude Code read. Where behavior is identical to Claude Code, this doc restates it briefly; where it diverges, the divergence is explicit.

---

## 1. Detection signals

Agent Skills std detection is fundamentally the **absence** of runtime-specific signals. A `SKILL.md` with only standard frontmatter fields and none of the runtime extensions is Agent Skills std.

| Signal | Strength | Notes |
|---|---|---|
| `SKILL.md` file as the primary spec | strong | The defining artefact |
| Frontmatter `name` matching regex `^[a-z0-9]+(-[a-z0-9]+)*$` | strong | Required-by-standard |
| Frontmatter `description` present | strong | Required-by-standard |
| Frontmatter fields limited to `{name, description, license, compatibility, metadata, allowed-tools, when_to_use}` | strong | No fields outside the std allow-list (plus the one known extension) |
| `scripts/`, `references/` / `reference/`, `assets/` directories sibling to `SKILL.md` | medium | Conventional layout |
| No `.claude/` directory at any level | medium | Rules out Claude Code |
| No `.mcp.json` at any level | medium | Rules out Claude Code and runtime-layered |
| No runtime-specific files (`langgraph.json`, `openclaw.json`, `.af`, `crew.py`, etc.) | medium | Rules out every other v1-supported runtime |

**Disambiguating from Claude Code.** This is the most common disambiguation needed. If the *only* matching signals are standard frontmatter plus conventional directories, and no Claude Code extension field appears, classify as Agent Skills std. **Presence of any Claude Code extension field or `.claude/` location elevates to Claude Code** (per `plans/dialects/claude-code.md` §1).

**Precedence note.** R1 tiebreak order puts Agent Skills std **first** — it wins strict ties. The rationale: Agent Skills std is the open, minimal format; when signals are balanced, treating a spec as Agent Skills std produces the more portable output.

**Hybrid threshold.** Agent Skills std rarely hybridises with another runtime because its defining characteristic is absence of runtime-specific signals. If Agent Skills std signals appear alongside (say) Claude Code signals, Claude Code wins outright on signal count — no Hybrid.

---

## 2. File inventory rules (Step 1a)

The workspace is the directory containing `SKILL.md`. Agent Skills std's workspace is smaller and more predictable than Claude Code's — no upward-walking CLAUDE.md, no `.claude/` directory.

### 2a. Primary spec

| File | Role | Inventory action |
|---|---|---|
| `SKILL.md` in the workspace root | C1 Identity + C2 Operating rules + metadata | Parse frontmatter; body decomposed per Step 1b |

The body is subject to the progressive-disclosure size guidance: ≤5,000 tokens, ≤500 lines. Specs exceeding either limit are inventoried in full (same policy as OpenClaw's oversize files) but flagged in the inventory report.

### 2b. Conventional directories

| Directory | Role | Inventory action |
|---|---|---|
| `scripts/` | C6 Tools (executable content) or TOOL_INPUT (data producers) | Each file becomes a candidate C6 element; classification depends on content |
| `references/` or `reference/` | C1 Identity / C2 Operating rules / C5 Long-term memory | Each file's content becomes elements; the tag depends on content |
| `assets/` | External data dependencies | Each file recorded as a TOOL_INPUT or referenced data source; v1 does not inline contents |

**Rule 2b-1**: the `references/` vs `reference/` naming disagreement is real — the open standard says plural (`references/`); `anthropics/skills` validator uses plural; `mcp-builder` and some other projects use singular. Step 1a checks for **both**; whichever exists is inventoried. If both exist simultaneously (rare), both are inventoried and the anomaly is flagged in the report.

**Rule 2b-2**: `assets/` files are treated as data referenced by the spec, not as spec content. They're recorded in the inventory with `role: "external asset"` and their contents are **not** inlined into elements. If the generated package needs access to an asset, the mapping report recommends the user bundle the asset alongside the generated package themselves — v1 melleafy does not copy assets into output.

### 2c. Non-standard but commonly-seen directories

Real Anthropic skills (in `anthropics/skills`) ship directories that aren't part of the open standard:

| Directory | Handling |
|---|---|
| `evals/` | Detect; note in report; **do not bundle** into output unless explicitly requested |
| `eval-viewer/` | Detect; note; do not bundle |
| `agents/` | Detect; note as possible cross-skill reference; do not inventory contents |
| `shared/` | Detect; note; contents not inventoried by default |

**Rule 2c-1**: these directories are common in practice but non-portable across Agent Skills implementations (not every host recognises them). Melleafy's conservative default is to detect them and flag their presence without bundling them into the generated package. A user who wants these bundled explicitly can override in Step 2.5 elicitation.

### 2d. Supporting files

| File | Role | Inventory action |
|---|---|---|
| `LICENSE.txt` (or similar) | Referenced by `license` frontmatter | Read if present; passed through to generated `LICENSE` file |
| `README.md` (if present) | Free-form notes | NO_DECOMPOSE unless spec body references it directly |
| `.env` / `.env.example` | C7 credentials | Parse; one element per var |

**Rule 2d-1**: Agent Skills std has no conventional place for env-var declaration (Claude Code uses `settings.env`; CrewAI uses project `.env` auto-loading). Melleafy's v1 policy: if a `.env.example` exists, inventory it. Otherwise, credential dependencies (C7) are inferred from spec body content (API names, auth patterns).

### 2e. No upward walking, no multi-location skill precedence

Unlike Claude Code, Agent Skills std has **no upward-walking CLAUDE.md hierarchy** and **no precedence-tiered skill locations** (no managed/user/project/plugin tiers). The workspace is literally "the SKILL.md's directory plus its conventional subdirectories."

**Rule 2e-1**: if an ancestor directory has a `CLAUDE.md`, it's ignored — Agent Skills std specs are not expected to have CLAUDE.md context. Detection is: if a CLAUDE.md *is* found in an ancestor, Step 0 should probably have classified as Claude Code, not Agent Skills std. This is a cross-check for detection quality.

### 2f. Missing files

Absence rules:

- `SKILL.md` absent: halt — Agent Skills std specs *must* have a SKILL.md. If detection said Agent Skills std but no SKILL.md exists, classification was wrong.
- `scripts/` / `references/` / `assets/` absent: normal; these are optional.
- `LICENSE.txt` absent but `license:` field references it: warn.
- `.env.example` absent: normal; credentials inferred from body.

---

## 3. Frontmatter rules — the strict allow-list

Agent Skills std's frontmatter is strictly validated. The Anthropic `quick_validate.py` rejects unknown keys. Melleafy enforces the same allow-list when the source is Agent Skills std.

### 3a. Authoritative field set

Six fields, per the open standard:

| Field | Required | Constraint |
|---|---|---|
| `name` | yes | 1–64 chars, regex `^[a-z0-9]+(-[a-z0-9]+)*$`, must match parent directory name |
| `description` | yes | 1–1024 chars; describes *what* + *when* |
| `license` | no | Free-form string or reference to a bundled `LICENSE.txt` |
| `compatibility` | no | ≤500 chars; free text for system packages, network, host product |
| `metadata` | no | map of string→string; convention stores `version`, `author` here |
| `allowed-tools` | no | **experimental**; space-separated string like `Bash(git:*) Bash(jq:*) Read` |

**Rule 3a-1**: `name` length quietly changed from 40 to 64 chars in PR #350. Older validators may reject names 41–64 chars long; melleafy accepts the full 1–64 range on input and surfaces length in the inventory report.

**Rule 3a-2**: `name` must equal the parent directory name — this is an implicit requirement across Agent Skills implementations. Step 1a cross-checks and warns if they differ.

**Rule 3a-3**: `allowed-tools` is formally experimental under the open standard. Melleafy parses it like any other C6 source signal but notes in the mapping report that the field is experimental — specs depending on it may not be portable to future Agent Skills versions.

### 3b. The `when_to_use` extension

`when_to_use` appears in real-world Agent Skills specs but **is not in the validator allow-list**. It's the most common extension. Melleafy's handling:

- **Parse it if present** — the content is spec-relevant
- **Append to `description` for internal use** — treat it as supplementary description content
- **Never emit it on output targeting Agent Skills std** — if melleafy ever regenerates a SKILL.md frontmatter (rare; not a v1 feature), it must not include `when_to_use` because `quick_validate.py` would reject the output

**Rule 3b-1**: unknown frontmatter fields *other than* `when_to_use` are errors under the standard. Melleafy surfaces them in the inventory report but does not halt — the spec is still processable, just not standard-compliant.

### 3c. Frontmatter parsing and validation

Parsed with `yaml.safe_load`. Same machinery as Claude Code (`plans/dialects/claude-code.md` §3d). Post-parse, melleafy validates:

- All required fields present
- All present fields are in the allow-list (plus `when_to_use`)
- Constraint checks per §3a

Validation failures become warnings in the inventory report, not halts. Constitution Article 1 requires generation to succeed for any parseable input.

---

## 4. Dialect mapping table

| Source signal | Category | Default disposition | Generation target |
|---|---|---|---|
| `name` frontmatter field | — | `bundle` | `pyproject.toml:name`, `README.md` title, `__init__.py:__agent_name__` |
| `description` frontmatter field | C1 | `bundle` | `config.AGENT_DESCRIPTION` |
| `when_to_use` frontmatter field | C1 | `bundle` | Appended to `config.AGENT_DESCRIPTION` |
| `license` frontmatter field | — | `bundle` | `pyproject.toml:license`; `LICENSE` file copied if `LICENSE.txt` exists |
| `compatibility` frontmatter field | C8 | `bundle` | `config.COMPATIBILITY_NOTE`; included in README; informational only |
| `metadata.version` | — | `bundle` | `pyproject.toml:version` |
| `metadata.author` | — | `bundle` | `pyproject.toml:authors` |
| `metadata.*` (other keys) | — | `bundle` | `config.METADATA` dict |
| `allowed-tools` entries (generic) | C6 | Varies per entry type | See per-pattern rules below |
| `allowed-tools` `Bash(pattern)` | C6 | `stub` | `constrained_slots.py:run_bash`; SETUP.md §8 |
| `allowed-tools` `Read(path-glob)` / `Write(...)` / `Edit(...)` | C6 | `stub` | Filesystem I/O deferred to host |
| `allowed-tools` `WebFetch(domain:*.example.com)` | C6 | `real_impl` | `tools.py:web_fetch` |
| `SKILL.md` body — main content | Varies (C1/C2/C6 mixed) | Decomposed per Step 1b | Various |
| File under `scripts/` | C6 | `real_impl` if Python/shell concrete | `tools.py:<script_name>` |
| File under `scripts/` (non-executable language) | C6 | `stub` | `constrained_slots.py`; SETUP.md §8 |
| File under `references/` or `reference/` — prose content | C1 / C2 | `bundle` | Inventoried as additional elements; mapped to `config.*` or `requirements.py` |
| File under `references/` or `reference/` — structured data | C5 | `load_from_disk` | `loader.py:load_<n>`; asset bundled alongside |
| File under `assets/` | — | `external_input` | Asset recorded in mapping report; user bundles alongside generated package |
| `LICENSE.txt` | — | `bundle` | Copied to output as `LICENSE` |
| `.env.example` entries | C7 | `external_input` | `.env.example` in generated package |
| `evals/` directory present | — | *(not reproduced)* | Noted in mapping report |
| `agents/` directory present | — | *(deferred)* | Noted as possible cross-skill reference |
| `shared/` directory present | — | *(not reproduced)* | Noted |

**Override semantics.** Default dispositions can be overridden via `--dependencies=ask` or `config:<path>` per the standard R22 contract.

**Rule 4-1**: Agent Skills std has no native C4 (short-term state), C9 (scheduling), or modality-declaring fields. Specs that imply these concerns (e.g., a spec body saying "remember where we left off") are inferred as C4 with `delegate_to_runtime` disposition. The inference is surfaced with `source_of_decision: "inferred"`.

**Rule 4-2**: the mapping is deliberately minimal — Agent Skills std has a small surface. Complexity lives in the SKILL.md body content, which Step 1b decomposes per its standard rules.

---

## 5. Modality signals (Step 0 Axis 5, R21)

**Agent Skills std deliberately declares nothing about invocation modality.** The open standard specifies packaging and progressive disclosure; the host runtime decides how skills are invoked.

**Rule 5-1**: Agent Skills std specs have **no explicit modality signals**. Step 0 Axis 5 Pass 1 (explicit declarations) returns empty. Classification relies entirely on Pass 2 (LLM inference) per `plans/steps/step-0-classification.md` §7b-3.

**Rule 5-2**: inference for Agent Skills std specs typically lands on `synchronous_oneshot` — a skill invoked once, runs to completion, returns a result. This is the default assumption when no other signals suggest otherwise.

**Rule 5-3**: when the spec body describes multi-turn interaction ("the user then provides..."), inference may produce `conversational_session`. When the spec describes streaming output ("produce each section as you finish it"), `streaming` is possible. These are LLM judgments, recorded with confidence scores.

**Rule 5-4**: host-needing modalities (`review_gated`, `scheduled`, `event_triggered`, `heartbeat`, `realtime_media`) are rare outcomes for Agent Skills std specs because nothing in the standard supports them. If the spec body clearly describes scheduling or event triggering, melleafy classifies accordingly but SETUP.md §6/§7 must explicitly note that the source format declares nothing about how these will be wired — the user is picking the host adapter from scratch.

**Generated shape per R21.** The generated package's entry-point shape follows whatever modality was inferred, per §5a–§5e of the shape doc. For the common case (`synchronous_oneshot` with low confidence), the shape is §5a and the mapping report surfaces the uncertainty.

### 5a. Low-confidence modality is normal

Because Agent Skills std has no explicit signals, **Pass 2 LLM confidence is the sole indicator of modality correctness.** Confidence below 0.7 triggers a retry per Step 0 §3b-1; after retry, the result is committed regardless. Unlike other dialects where low modality confidence is anomalous, for Agent Skills std it's expected.

**Rule 5a-1**: when inferred modality confidence is below 0.7 and the spec ships, the mapping report's Classification section includes a prominent note: "Modality inferred from spec body with confidence <0.7>. Agent Skills std declares no modality; review generated `main.py` entry-point shape to confirm it matches intended use."

---

## 6. Quirks and workarounds

### 6a. The `references/` vs `reference/` disagreement

Addressed in §2b rule 2b-1. This is not a quirk of Agent Skills std itself — it's a disagreement between the open-standard spec and real-world implementations. Melleafy handles both.

### 6b. Non-portable real-world extensions

Real Anthropic skills (in `anthropics/skills`) use features not in the open standard:

- `evals/`, `eval-viewer/` directories — test infrastructure
- `agents/` directory — cross-skill delegation (overlaps with Claude Code subagents)
- `shared/` directory — shared utilities

These work in Anthropic's tooling but are **not portable** across Agent Skills implementations. Melleafy flags their presence and doesn't bundle them by default — a user wanting to target Anthropic tooling specifically can override.

### 6c. `allowed-tools` is experimental

Marked experimental under the open standard. Future versions may remove it or change its semantics. Melleafy treats it as a C6 source signal (same as other tool declarations) but notes in mapping report that the field is unstable.

### 6d. No upward context walking

Unlike Claude Code, Agent Skills std has no ancestor-directory context. A SKILL.md spec is self-contained relative to its workspace. If the author needs context (e.g., project-wide conventions), it must be inlined into the SKILL.md body or placed in `references/`.

**Rule 6d-1**: melleafy does not read CLAUDE.md or similar ancestor files when processing Agent Skills std. If a spec relied on ancestor context that's not available, the spec was under-specified as Agent Skills std — the user's options are (a) classify as Claude Code instead, or (b) inline the context into the SKILL.md.

### 6e. No invocation contract

Agent Skills std says nothing about how the skill is invoked: no CLI flags, no function signatures, no session model. The host runtime defines all of this. Melleafy's generated package picks an invocation contract (typically `run_pipeline(input: Input) -> Output` via `main.py`) but this is a **melleafy decision, not a source-derived one**. The mapping report notes this explicitly:

> "Agent Skills std declares no invocation contract. The generated package exposes a synchronous function `run_pipeline(input)` and a `main.py` CLI entry point. If the skill was intended for a specific host (Claude Code, Codex, Cursor), the user may need an adapter layer."

### 6f. Progressive disclosure is a runtime concern

The Agent Skills std spec describes progressive disclosure as a **runtime behavior** — the host loads metadata first, instructions second, resources on demand. Melleafy-generated packages have no equivalent mechanism — everything is loaded at import time.

**Rule 6f-1**: specs that explicitly depend on progressive disclosure for token-budget reasons (very rare) won't get the same behavior from melleafy-generated packages. Noted in mapping report but not a common concern.

### 6g. Metadata convention vs spec

`metadata` in frontmatter is a free map of string→string. Convention stores `version` and `author` keys; some implementations add `keywords`, `homepage`, etc. Melleafy's mapping (§4) special-cases `version` and `author` to map to `pyproject.toml` fields; others land in a catch-all `config.METADATA` dict. If a specific implementation's convention emerges that melleafy should special-case, that's a mapping table addition.

### 6h. `compatibility` field semantics

The `compatibility` field is free-text up to 500 chars. Typical content: "Requires Python 3.11+; uses pandas; macOS only." Melleafy does not parse this field structurally — it's copied into `config.COMPATIBILITY_NOTE` verbatim and surfaced in README. The 500-char limit is a soft convention; melleafy warns on oversize but proceeds.

---

## 7. Reference inventory output (illustrative)

For a minimal Agent Skills std spec — a `SKILL.md` with frontmatter, a `scripts/` directory with one Python helper, and a `references/` directory with one prose reference:

### Inventory (abridged)

```json
{
  "elements": [
    {"element_id": "elem_001", "source_file": "SKILL.md", "source_lines": "frontmatter.name", "tag": "CONFIG", "category": "—", "content_summary": "Skill name: ticket-triage"},
    {"element_id": "elem_002", "source_file": "SKILL.md", "source_lines": "frontmatter.description", "tag": "CONFIG", "category": "C1", "content_summary": "Description: triage customer support tickets"},
    {"element_id": "elem_003", "source_file": "SKILL.md", "source_lines": "frontmatter.when_to_use", "tag": "CONFIG", "category": "C1", "content_summary": "When to use: whenever a new ticket arrives"},
    {"element_id": "elem_010", "source_file": "SKILL.md", "source_lines": "15-40", "tag": "ORCHESTRATE", "category": "C2", "content_summary": "Classification-then-routing workflow"},
    {"element_id": "elem_020", "source_file": "scripts/fetch_priority.py", "source_lines": "py:scripts/fetch_priority.py:1-30", "tag": "TOOL_TEMPLATE", "category": "C6", "content_summary": "Python helper: fetch ticket priority from API"},
    {"element_id": "elem_030", "source_file": "references/routing-rules.md", "source_lines": "1-50", "tag": "CONFIG", "category": "C2", "content_summary": "Routing rules reference: priority-to-team mapping"}
  ]
}
```

Note `source_lines` formats: `frontmatter.<field>` for frontmatter references, `py:<file>:<range>` for Python files under `scripts/`, line ranges for Markdown. These are shared conventions with other dialects (Claude Code, LangGraph respectively).

### Element mapping (abridged)

```json
{
  "mappings": [
    {"element_id": "elem_001", "target_file": "pyproject.toml", "target_symbol": "name", "primitive": "bundle"},
    {"element_id": "elem_002", "target_file": "config.py", "target_symbol": "AGENT_DESCRIPTION", "primitive": "bundle"},
    {"element_id": "elem_003", "target_file": "config.py", "target_symbol": "AGENT_DESCRIPTION", "primitive": "bundle"},
    {"element_id": "elem_010", "target_file": "pipeline.py", "target_symbol": "run_pipeline", "primitive": "orchestrate"},
    {"element_id": "elem_020", "target_file": "tools.py", "target_symbol": "fetch_priority", "primitive": "real_impl"},
    {"element_id": "elem_030", "target_file": "requirements.py", "target_symbol": "OPERATING_REQUIREMENTS", "primitive": "requirement"}
  ]
}
```

### Dialect-specific notes in the mapping report

- A "Modality inference" section noting confidence level and the rationale (since Agent Skills std has no explicit modality).
- A "Non-portable extensions detected" section listing `evals/`, `agents/`, `shared/` if present.
- An "Invocation contract" callout (per §6e) noting that Agent Skills std declares no contract; the generated package's shape is a melleafy decision.

---

## 8. Deferred Agent Skills std features (not handled in v1)

- **Cross-skill references via `agents/` directory** — not portable under the open standard; v1 flags but doesn't follow. v2 could offer explicit opt-in.
- **Progressive disclosure at runtime** (§6f) — v1 generates loaded-at-import packages.
- **Regenerating SKILL.md frontmatter as output target** — if a v2 feature lets users regenerate Agent Skills std-compliant SKILL.md from a Mellea package, strict adherence to the validator allow-list (no `when_to_use`) becomes important. Not a v1 concern.
- **Validator version tracking** — the allow-list field count could grow in future standard revisions. v1 targets the 2026-Q1 allow-list; future melleafy versions should track.
- **Host-specific adapter generation** — a user targeting Codex or Cursor from an Agent Skills std spec would benefit from an adapter layer; v1 produces a generic Mellea package.

---

## 9. Cross-references

- `spec.md` R1, R21, R22 — the contracts this dialect implements
- `plans/dialects/openclaw.md` — template this dialect adapts
- `plans/dialects/claude-code.md` — the superset runtime; Claude Code extensions live there
- `plans/dialects/letta.md` — for comparison of single-file source models
- `plans/dialects/langgraph.md` — for comparison of code-first source models
- `plans/generated-package-shape.md` — shape of the generated output
- `glossary.md` — `dialect`, `disposition`, `interaction modality`

---

## 10. Ratification notes

This dialect doc v1.0.0 was the fifth drafted, selected to validate the "subset-of-another-dialect" pattern — Agent Skills std is strictly contained in Claude Code's feature set, and writing this doc after Claude Code tests whether the subset relationship produces clean, non-duplicative documentation.

**What the template survived unchanged:**
- All ten sections translated directly without structural adaptation. This is expected — Agent Skills std's surface is a strict subset of what the template already handles.
- Sections 2, 3, 4, 5 are much shorter than Claude Code's because Agent Skills std has fewer surfaces to enumerate. This is a natural consequence of the source format's restraint.

**The subset pattern — what it means for dialect documentation:**
- Each dialect doc is **written to stand alone** (no subset-by-reference). A reader implementing Agent Skills std support shouldn't have to read Claude Code's doc first. This costs some duplication of frontmatter rules, but gains independence and local readability.
- Where Agent Skills std and Claude Code behavior is identical (e.g., `yaml.safe_load` for frontmatter), this doc names the behavior briefly and optionally cross-references Claude Code's §3d for detail. Readers who want only Agent Skills std context don't need to jump.
- Where Agent Skills std and Claude Code diverge (strict allow-list vs permissive, no upward walking vs CLAUDE.md hierarchy, no invocation contract vs full CLI surface), the divergence is called out explicitly.

**What this tells us about template generality.** Writing a subset dialect took noticeably less effort per section than writing Claude Code or LangGraph (which required new concepts). The template accommodates subsets naturally — there's no pressure to invent new structure just because the content is smaller. Good sign for the remaining three runtime-specific dialects (CrewAI, AutoGen, OpenAI Agents SDK, smolagents — each with a mix of novel concepts and shared Agent-Skills-adjacent ideas).

Open questions:

- **§5 modality as LLM-inference-only** is a correct outcome but leaves users with less-reliable classification than other dialects. Worth considering whether Agent Skills std specs should ship with a mandatory `--modality=<explicit>` flag that users provide when the inference is known to be wrong. v1 default: infer and warn on low confidence. v2: maybe a flag.
- **§3b `when_to_use` handling** (parse but don't emit on output) matters only if melleafy grows a "regenerate Agent Skills std spec" capability. v1 doesn't do this, so the rule is aspirational. Flagged as a v2 consistency concern.
- **§2c non-standard directory handling** treats `evals/`, `agents/`, `shared/` as "detect but don't bundle." A user targeting Anthropic's specific Agent Skills tooling may want these bundled. Worth a `--include-nonstandard-dirs` flag; not prioritised for v1.
- **§6g metadata convention** — if specific implementations develop their own `metadata` conventions (e.g., `metadata.category`, `metadata.tags`), melleafy should grow special cases. For now, the catch-all `config.METADATA` dict is adequate.
- **Relationship to Claude Code detection in practice** — the most common disambiguation mistake would be classifying a Claude Code spec as Agent Skills std because no `.claude/` directory exists in the specific skill's workspace but an ancestor has one. Step 1a §2e addresses this by not walking upward for Agent Skills std classifications. The cross-check is in Step 0 detection logic: signals are counted per the spec, but ancestor directories don't contribute to Agent Skills std detection.
- **The 2b-1 `references/`/`reference/` handling** assumes at most one of the two exists. If both exist (extremely rare but possible in a project that refactored), both are inventoried. Worth treating this as a warning in the inventory report.
- **Progressive disclosure** (§6f) is tangential to melleafy's generation model. Some Agent Skills users may specifically be *relying on* progressive disclosure for token-budget reasons. v1's "load everything at import" doesn't respect this. Flagged as a v2 concern if it ever matters.
