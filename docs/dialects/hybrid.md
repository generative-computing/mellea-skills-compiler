# Hybrid Dialect

**Version**: 1.0.0
**Status**: Seventh dialect doc, but distinct in kind. Where the other dialects describe specific source runtimes, Hybrid is a **classification outcome** that triggers when two or more dialects' signals tie. It's a meta-dialect: a procedure for composing other dialects' rules rather than a runtime of its own. The 10-section template partly fits and partly requires explicit adaptation.

**Prerequisite reading**: `spec.md` R1 (detection — especially the Hybrid threshold rule and the 1-signal-difference semantics), R22 (dialect mapping contract); all the runtime-specific dialect docs under `plans/dialects/` for per-runtime rules; `plans/steps/step-0-classification.md` §6 (source runtime detection); `plans/steps/step-1a-inventory.md`, `plans/steps/step-1b-tagging.md`, `plans/steps/step-2-mapping.md`, `plans/steps/step-2.5-dependencies.md`.

---

## What this document does

Describes what melleafy does when a spec's source-runtime classification outcome is `hybrid`. Hybrid classification happens when two or more supported runtimes have signal counts within 1 of each other after Step 0's detection pass (per R1 Hybrid threshold). This doc is the **reference for how multiple dialect rule sets combine** during Steps 1a, 1b, 2, 2.5, and 5.

Unlike the other dialect docs, Hybrid has:

- No unique detection signals of its own (§1 is about the *classification path* to Hybrid, not signals)
- No file inventory rules of its own (§2 describes how contributing runtimes' rules are merged)
- No frontmatter rules of its own (§3 same)
- No mapping rows of its own (§4 describes conflict resolution between contributing runtimes' rows)
- A composition-specific modality handling (§5)

Hybrid is a **meta-procedure**, not a runtime description.

Key concepts readers should have in mind:

- **Primary runtime**: the contributing runtime with the highest signal count among ties. If signal counts are exactly equal, R1's tiebreak list decides: Agent Skills std > Claude Code > OpenClaw > CrewAI > LangGraph > AutoGen > Letta > Agents SDK > smolagents.
- **Contributing runtime(s)**: all other runtimes whose signals were within 1 of the primary.
- **Conflict**: when two contributing runtimes' rules disagree about a specific source signal — different category, different disposition, or different target file.
- **Composition**: the process of applying multiple dialects' rules and merging their outputs into a single inventory / mapping / plan.

---

## 1. The path to Hybrid classification

No signals fire Hybrid directly. Hybrid is what Step 0 produces when:

- The winning runtime's signal count is within 1 of the second-place runtime's signal count, AND
- Neither runtime is `unknown` (zero signals matched), AND
- The user has not passed `--source-runtime <specific-runtime>` to override detection.

**Rule 1-1**: Hybrid can involve two or more contributing runtimes. The within-1 threshold applies pairwise between the primary and each would-be contributor. Example: if OpenClaw has 8 signals, Claude Code has 7, and Letta has 6 signals, the primary is OpenClaw, Claude Code is a contributor (within 1 of 8), and Letta is not (within 2 of 8, outside threshold) — so the hybrid is OpenClaw + Claude Code, not OpenClaw + Claude Code + Letta.

**Rule 1-2**: the within-1 threshold uses **weighted signal counts** per `plans/steps/step-0-classification.md` §6b (strong=2, medium=1, weak=0.5). Not raw signal counts.

**Rule 1-3**: `--source-runtime=hybrid` is a valid CLI argument and forces Hybrid classification regardless of detection. In this case, melleafy asks the user to declare which runtimes are contributing (via an interactive prompt or a `--contributing-runtimes=a,b,c` flag). Without contributing-runtime information, Hybrid classification cannot proceed — there are no dialect rules to merge.

### 1a. Common hybrid pairings

Observed in practice:

| Pairing | Typical scenario |
|---|---|
| Claude Code + OpenClaw | Project uses Claude Code as dev environment, targets OpenClaw at runtime |
| Claude Code + Letta | Letta agent with a Claude Code wrapper for development |
| CrewAI + LangGraph | Flows composing over LangGraph subgraphs, or the reverse |
| Agent Skills std + Claude Code | Edge case where `.claude/` exists as artifact from previous iteration but frontmatter is Agent-Skills-only |
| OpenClaw + Letta | Memory-heavy spec targeting either runtime; signals overlap on heartbeat + memory |

**Rule 1a-1**: rare but possible: three-way hybrids (e.g., Claude Code + OpenClaw + Letta). The composition rules in this doc scale to N contributors, but the user experience degrades — elicitation prompts per-entry grow linearly with contributor count. The mapping report warns when N ≥ 3.

### 1b. What Hybrid classification records in `classification.json`

Step 0 produces a `classification.json` with:

```json
{
  "source_runtime": "hybrid",
  "source_runtime_override": null,
  "hybrid_threshold_triggered": true,
  "hybrid_primary": "openclaw",
  "hybrid_contributors": ["claude_code"],
  "source_runtime_scores": {"openclaw": 8, "claude_code": 7, "letta": 6, ...},
  "source_runtime_signals": { ... full signal table per runtime ... }
}
```

The `hybrid_primary` and `hybrid_contributors` fields are unique to Hybrid classifications. They drive every composition decision in Steps 1a, 1b, 2, 2.5, and 5.

---

## 2. File inventory composition (Step 1a)

Step 1a's job for a Hybrid spec is: apply **all contributing runtimes' file inventory rules** and merge the results into one file list.

### 2a. Per-runtime inventory pass

For each contributing runtime (primary + all contributors), Step 1a runs its normal inventory pass per that runtime's dialect doc §2. The outputs are merged.

**Rule 2a-1**: the workspace root is determined by the **primary runtime's Section 2** rules. For OpenClaw the workspace is the spec's parent directory; for Claude Code it's the first ancestor containing `.claude/` or `.git/`. If primary is OpenClaw, OpenClaw's workspace rule applies even when Claude Code is a contributor.

**Rule 2a-2**: contributing runtimes' inventory passes **do not change the workspace root** — they scan the primary's workspace for their own file patterns. A Claude Code `.claude/settings.json` found inside an OpenClaw workspace is inventoried per Claude Code's rules.

**Rule 2a-3**: files unique to one contributing runtime are added to the file list with `dialect_rule_id` pointing at that runtime's dialect doc. A `SOUL.md` inventoried under OpenClaw's rules and a `settings.json` inventoried under Claude Code's rules appear as siblings in the file list.

### 2b. Overlap handling

When the same file is inventoried by two contributing runtimes (rare but possible — e.g., a `README.md` or a `.env` file might be handled similarly by multiple dialects):

**Rule 2b-1**: the file appears exactly once in the file list, with `dialect_rule_id` being an array of all matching rule IDs, and `role` being a combined role string.

**Rule 2b-2**: when two runtimes assign *incompatible* roles to the same file (e.g., OpenClaw says "C2 operating rules" but Letta says "C3 user context" — implausible but illustrative), the primary runtime's role wins and the contributor's role is recorded in the inventory report as `conflicting_roles` metadata.

### 2c. Credential-location handling

Multiple runtimes may declare different credential conventions. Step 1a records each credential reference from each runtime's rules:

- Claude Code's `.claude/.credentials.json` or macOS Keychain references
- OpenClaw's `~/.openclaw/.env` and `~/.openclaw/credentials/`
- Letta's server env vars (`LETTA_PG_URI`, etc.)
- CrewAI's project `.env`
- LangGraph's `langgraph.json:env`

**Rule 2c-1**: credentials are **detection-only** (contents never read) regardless of which runtime's rules applied. Each credential location referenced across contributing runtimes is noted in the inventory report; SETUP.md §2 in the generated package enumerates all of them so the user can configure any one.

### 2d. Missing-file semantics

When a file is expected-but-absent per one runtime's rules and absent-as-expected per another:

**Rule 2d-1**: "expected" wins over "optional." If OpenClaw's rules say SOUL.md is optional but Claude Code's rules say SKILL.md is required, SKILL.md's absence takes precedence as the concerning one. The inventory report records both.

**Rule 2d-2**: files absent under all contributing runtimes' rules are simply not present; no note in the report.

### 2e. Cross-runtime file references

Some files referenced by one runtime's rules may exist as artifacts of another runtime's system. Example: a `.claude/settings.json:mcpServers` declaration references an MCP server that a Letta spec also declares via `tools[].source_code`. Both runtimes' rules treat this as a C6 element but with different target files.

**Rule 2e-1**: cross-runtime references are resolved **deferred to Step 2** — inventory just records each reference as-seen per its own runtime's rules. Step 2's mapping phase sees both references and marks them as a "Hybrid conflict" entry that Step 2.5's elicitation surfaces.

---

## 3. Structured-content rules composition

Each contributing runtime has its own structured-content rules (Section 3 in its dialect doc). For Hybrid specs, all contributing runtimes' rules apply to their own files.

### 3a. Per-runtime parsing

When Step 1a reads a file inventoried under Claude Code's rules, Claude Code's frontmatter/JSON parsing applies. When it reads a file inventoried under OpenClaw's rules, OpenClaw's parsing applies. There's no cross-pollination — each file is parsed per the rules that inventoried it.

**Rule 3a-1**: a file that was inventoried under two runtimes simultaneously (§2b overlap case) uses the primary runtime's parsing rules.

### 3b. Content-type conflicts

Rare but possible: a file named `SKILL.md` might contain Markdown content that could be interpreted per Claude Code's rules or per Agent Skills std's strict allow-list. When the primary runtime's frontmatter rules would accept fields that the contributing runtime's rules reject (or vice versa), the primary runtime's rules apply.

**Rule 3b-1**: frontmatter fields that are valid under the primary runtime but rejected by the contributor's rules don't produce errors — they produce a warning in the inventory report noting the contributor would reject them.

---

## 4. Mapping-table composition (Step 2)

Step 2's mapping phase receives the merged inventory from Step 1a and must produce a single `element_mapping.json`. When the same source signal could be mapped per multiple contributing runtimes' rules, the composition logic kicks in.

### 4a. Mapping table application order

For each element in the inventory:

1. Check the element's `dialect_rule_id` to see which runtime(s) claimed it during inventory.
2. If claimed by only one runtime, apply that runtime's Section 4 mapping rules.
3. If claimed by multiple runtimes, attempt each runtime's mapping rules:
   - If all runtimes map the element to the same category + disposition + target file, use that mapping (no conflict).
   - If any of the three differs, flag as a **Hybrid conflict**.

### 4b. Hybrid conflict resolution

A conflict is any case where two contributing runtimes' mapping rules disagree on category, disposition, or target file for the same element.

**Rule 4b-1**: default resolution is "**primary wins**" — the primary runtime's mapping row applies, and the conflict is recorded in `element_mapping_judgment_calls.json` with `conflict_type: "hybrid"` and the alternative mapping(s) noted.

**Rule 4b-2**: Step 2.5 elicitation (in `ask` mode) surfaces Hybrid conflicts as high-priority items. The user sees:

```
[Hybrid conflict] elem_042: tool_ref to GitHub API
  Primary (Claude Code) says: C6 Tools → real_impl → tools.py:github_fetch
  Contributor (OpenClaw) says: C6 Tools → real_impl → tools.py:github_fetch + C7 credential GITHUB_TOKEN
  
  [p]rimary wins   [c]ontributor wins   [m]erge   [d]etail   [s]kip
  ›
```

**Rule 4b-3**: the "merge" option combines both runtimes' outputs (e.g., in the example above, produce both the tool and the credential entry). Merge is valid only when the conflict is about *additions* rather than *contradictions*. If one runtime says "bundle" and another says "stub" for the same signal, merge is not offered.

**Rule 4b-4**: in `auto` mode, "primary wins" is applied silently, and the mapping report surfaces every conflict prominently under a "Hybrid conflicts auto-resolved" section.

### 4c. Elements unique to one contributor

Elements that exist only per one contributing runtime's rules (no overlap with the primary's view) are mapped using **only that contributor's rules**. The primary's mapping table doesn't apply because it didn't see the element at inventory time.

### 4d. Shared elements — merged metadata

Sometimes both runtimes see the same element but each contributes distinct metadata. Example: both Claude Code and OpenClaw might see an `allowed-tools` entry referencing GitHub, but Claude Code adds a `WebFetch(domain:*.github.com)` network constraint while OpenClaw adds a `~/.openclaw/credentials/github.token` credential reference.

**Rule 4d-1**: when two runtimes see the same source signal with non-conflicting metadata, the element's `metadata` field merges both. The mapping preserves the fuller picture.

### 4e. Target-file conflicts

A rare but important case: two runtimes might both want to route an element to the same target file but with different symbol names. E.g., Claude Code's MCP-tool rule maps to `constrained_slots.py:<server>_<tool>`, while Letta's tool rule maps the same conceptual tool to `tools.py:<tool>`. Both target files exist in the generated package; the conflict is which file should contain the implementation.

**Rule 4e-1**: target-file conflicts follow the "primary wins" default unless the element's disposition differs — if Claude Code says `stub` and Letta says `real_impl`, the stub wins (defensive — the tool may not work without the runtime's native integration).

---

## 5. Modality signals composition (Step 0 Axis 5)

Modality detection for Hybrid specs runs both contributing runtimes' Pass 1 (explicit signals) and merges results.

### 5a. Explicit signals union

Each contributing runtime's explicit modality signals are evaluated. The results:

- If primary and contributor agree (same modality), that modality wins.
- If they produce different modalities, the primary wins as **primary modality** and the contributor's modality is added to `secondary_modalities`.

**Rule 5a-1**: if the contributor's modality would be host-needing (`review_gated`, `scheduled`, `event_triggered`, `heartbeat`, `realtime_media`) while the primary's is Mellea-native, the combination is recorded as "primary with secondary host-adapter requirement." SETUP.md §5/§6/§7 in the generated package names the secondary.

### 5b. Common composition patterns

Common pairings and their modality outcomes:

| Primary | Contributor | Primary modality | Secondary modality | Notes |
|---|---|---|---|---|
| OpenClaw | Claude Code | `heartbeat` (if declared) | — | Claude Code adds no runtime-specific modality signals beyond OpenClaw's |
| Claude Code | OpenClaw | Inferred from Claude Code | `heartbeat` (if OpenClaw declares) | OpenClaw's `openclaw.json:heartbeat.every` adds heartbeat as secondary |
| CrewAI | LangGraph | Per CrewAI rules | `review_gated` or others per LangGraph | Both have their own modality signals |
| Letta | Claude Code | Per Letta rules | — | Claude Code rarely adds modality beyond Letta's explicit signals |
| Agent Skills std | Claude Code | (Edge case — shouldn't happen; see §6) | — | — |

**Rule 5b-1**: Pass 2 (LLM inference) runs only if **neither** contributing runtime has any explicit modality signals. This is rare for Hybrid classifications (if one runtime has explicit signals, use them).

### 5c. Composition validation

The standard R21 composition validation (`plans/steps/step-0-classification.md` §7c) applies. Specifically:

- `realtime_media` + `batch` is still impossible regardless of Hybrid status.
- `scheduled + review_gated` is still awkward.
- Any composition producing `unknown` in secondary is still a schema error.

**Rule 5c-1**: composition rules apply to the *merged* modality set, not per-runtime. If the primary's `conversational_session` and a contributor's `review_gated` together make a valid composition (they do — it's the LangGraph HITL canonical pattern), the composition is accepted.

---

## 6. Known edge cases

### 6a. Agent Skills std + Claude Code

This pairing is an edge case because Claude Code is a **strict superset** of Agent Skills std — if both sets of signals match, Claude Code should elevate and Hybrid shouldn't trigger. In practice, the signal-count can tie if:

- The spec has only Agent-Skills-std-compliant frontmatter (no Claude Code extensions)
- The workspace has a `.claude/` directory (maybe from a previous iteration or accidentally included)

**Rule 6a-1**: when Agent Skills std + Claude Code would produce a Hybrid classification, melleafy **promotes to Claude Code** (not Hybrid). The rationale: Claude Code's rules accept Agent Skills std frontmatter (it's a superset), so treating the spec as Claude Code loses no information; treating as Hybrid would split inventory across two rule sets needlessly.

**Rule 6a-2**: this is the one hybrid pairing that doesn't produce a Hybrid outcome. Every other pairing proceeds normally.

### 6b. Code-first + code-first

Hybrid between two code-first runtimes (e.g., LangGraph + AutoGen) is unusual but possible. AST pattern discovery runs both sets of patterns on each Python file. Elements matching patterns from both runtimes are flagged as shared; elements matching only one are attributed to that runtime.

**Rule 6b-1**: cross-framework Python imports are signals — a file that imports from both `langgraph` and `autogen_agentchat` is likely a bridge file mixing both runtimes. Flagged prominently in the mapping report.

### 6c. Three-way Hybrids

Per Rule 1a-1, three-way Hybrids are rare but possible. Composition scales:

- Inventory runs all three passes and merges.
- Mapping uses three-way conflict resolution (primary > contributor 1 > contributor 2 precedence).
- Modality composition may produce up to three secondary modalities.

**Rule 6c-1**: the mapping report's Classification section includes a prominent warning: "Three contributing runtimes detected. Review Hybrid conflicts carefully; consider whether this is the intended source spec shape."

### 6d. Hybrid + `--source-runtime` override

`--source-runtime <specific-runtime>` overrides detection. When applied to a spec that would otherwise have been Hybrid, the specific runtime becomes primary and **no contributing runtimes apply** — the override collapses the composition to a single dialect. Elements that would have been attributed to contributors are now either:

- Inventoried per the specified runtime (if its rules match), or
- Not inventoried at all.

**Rule 6d-1**: the override causes a warning in the mapping report: "Source was detected as Hybrid ({primary} + {contributors}); overridden to {specified runtime}. Elements unique to {contributors} may be missed."

### 6e. Workspace-root ambiguity

Different runtimes have different workspace-root rules:

- OpenClaw: spec's parent directory
- Claude Code: first ancestor with `.claude/` or `.git/`
- CrewAI: spec's parent directory (`config/` is a sibling)

When contributing runtimes would produce different workspace roots, the primary wins (Rule 2a-1). The inventory report notes which rule determined the root.

### 6f. Melleafy.json manifest handling

The generated package's `melleafy.json` records Hybrid classification:

```json
{
  "source_runtime": "hybrid",
  "hybrid_primary": "openclaw",
  "hybrid_contributors": ["claude_code"],
  "target_runtime": "mellea",
  ...
}
```

**Rule 6f-1**: downstream consumers of `melleafy.json` (the v2 `melleafy export --host=<n>` tool, for instance) can use `hybrid_primary` as the canonical source for host-adapter generation. This preserves the primary's semantics without requiring the adapter tool to understand all contributing runtimes.

---

## 7. Reference inventory output (illustrative)

For an OpenClaw + Claude Code Hybrid spec — OpenClaw workspace with SOUL.md, AGENTS.md, plus a `.claude/settings.json`:

### Classification outcome

```json
{
  "source_runtime": "hybrid",
  "hybrid_primary": "openclaw",
  "hybrid_contributors": ["claude_code"],
  "source_runtime_scores": {"openclaw": 8, "claude_code": 7, "letta": 1, ...}
}
```

### Inventory (abridged)

```json
{
  "elements": [
    {"element_id": "elem_001", "source_file": "SOUL.md", "source_lines": "1-40", "tag": "CONFIG", "category": "C1", "content_summary": "Persona — research assistant", "dialect_rule_id": "openclaw:2a:soul_md"},
    {"element_id": "elem_010", "source_file": "AGENTS.md", "source_lines": "10-25", "tag": "ORCHESTRATE", "category": "C2", "content_summary": "Workflow: extract → summarize → cite", "dialect_rule_id": "openclaw:2a:agents_md"},
    {"element_id": "elem_030", "source_file": ".claude/settings.json", "source_lines": "json:permissions.deny[0]", "tag": "VALIDATE_OUTPUT", "category": "C2", "content_summary": "Never run rm -rf", "dialect_rule_id": "claude_code:2c:settings_json"},
    {"element_id": "elem_031", "source_file": ".claude/settings.json", "source_lines": "json:hooks.PreToolUse[0]", "tag": "ORCHESTRATE", "category": "C9", "content_summary": "PreToolUse hook: log every tool call", "dialect_rule_id": "claude_code:2c:settings_json"}
  ]
}
```

### Element mapping (abridged, showing a conflict)

```json
{
  "mappings": [
    {"element_id": "elem_001", "target_file": "config.py", "target_symbol": "PREFIX_TEXT", "primitive": "bundle"},
    {"element_id": "elem_010", "target_file": "pipeline.py", "target_symbol": "run_pipeline", "primitive": "orchestrate"},
    {"element_id": "elem_030", "target_file": "requirements.py", "target_symbol": "OPERATING_REQUIREMENTS", "primitive": "requirement", "dialect_override_applied": "claude_code"},
    {"element_id": "elem_031", "target_file": "handlers/pre_tool_use.py", "target_symbol": "handle_pre_tool_use", "primitive": "delegate", "conflict": {"type": "hybrid", "alternative": {"runtime": "openclaw", "target_file": "constrained_slots.py", "reason": "OpenClaw has no PreToolUse equivalent"}, "resolution": "contributor_only"}}
  ]
}
```

### Dialect-specific notes in the mapping report

A Hybrid classification produces these distinctive sections in the mapping report:

- **Classification** section: "Hybrid classification: primary = OpenClaw (score 8), contributor = Claude Code (score 7). Processing applied both rule sets."
- **Hybrid conflicts auto-resolved** (for `auto` mode) OR **Hybrid conflicts surfaced for user review** (for `ask` mode): each conflict with resolution.
- **Contributions by runtime**: which elements came from which runtime's rules. Useful for users reviewing to confirm every source surface was read.
- **Missing-under-primary, present-under-contributor** notes: where a contributor's rules added elements the primary's rules would have missed.

---

## 8. Deferred Hybrid features (not handled in v1)

- **Three-way-plus Hybrids with complex conflicts** (§6c) — v1 handles them but the user experience degrades with conflict volume. v2 could add conflict-batching or summarisation.
- **Explicit hybrid-rule authoring** — users cannot author custom composition rules in v1. The rules are always "primary wins with contributor augmentation." If users want different semantics, they override via `--source-runtime` to collapse.
- **Hybrid-specific SETUP.md templates** — v1 assembles SETUP.md from the primary's template with contributor additions. Richer per-hybrid templates (e.g., "how to deploy an OpenClaw + Claude Code hybrid") are deferred.
- **Conflict machine-learnability** — v1's conflict resolution is rule-based. v2 could learn patterns from user elicitation choices and suggest resolutions for similar future conflicts.
- **Cross-runtime element aggregation** — v1 aggregates only within a single runtime's rules. If the same semantic rule is expressed both as an OpenClaw AGENTS.md line and a Claude Code settings.json `permissions.deny[]` entry, v1 records both; aggregating them as a single element is deferred.

---

## 9. Cross-references

- `spec.md` R1 (detection precedence + Hybrid threshold), R22 (dialect mapping contract)
- All individual dialect docs under `plans/dialects/`: OpenClaw, Claude Code, Letta, Agent Skills std, LangGraph, CrewAI (and future: AutoGen, OpenAI Agents SDK, smolagents)
- `plans/steps/step-0-classification.md` §6 (source runtime detection — including Hybrid rules)
- `plans/steps/step-1a-inventory.md` — base file inventory procedure
- `plans/steps/step-1b-tagging.md` — base tagging procedure
- `plans/steps/step-2-mapping.md` §4 (dialect overrides)
- `plans/steps/step-2.5-dependencies.md` §3 (elicitation in `ask` mode — where conflicts surface)
- `plans/steps/step-5-artifacts.md` §1a (mapping report structure)

---

## 10. Ratification notes

This dialect doc v1.0.0 was the seventh drafted, and it's unusual in kind. The other six describe specific source runtimes with detection signals, file inventories, frontmatter rules, and mapping tables. Hybrid has none of those in itself — it's a composition procedure for when two (or more) other runtimes' signals tie.

**How much of the template fit:**

- Section 1 (Detection signals) — **partial fit**. No signals unique to Hybrid; instead this section describes the classification path to Hybrid and the composition's own metadata (primary, contributors).
- Section 2 (File inventory rules) — **partial fit**. No rules of its own; instead describes how contributing runtimes' rules merge. Section retained but content is all about composition.
- Section 3 (Structured-content rules) — **partial fit**. No rules of its own; parsing delegates to each contributor's rules.
- Section 4 (Dialect mapping table) — **reshaped**. No mapping rows; instead describes conflict resolution between contributors' rows. The section is about *meta-mapping*, not about mapping.
- Section 5 (Modality signals) — **partial fit**. No signals of its own; composition rules instead.
- Section 6 (Quirks and workarounds) — **fits naturally**. Becomes "Known edge cases for Hybrid."
- Section 7 (Reference inventory output) — **fits**. Shows an example Hybrid classification and mapping.
- Sections 8, 9, 10 — **fit naturally**. No adaptation needed.

**What this tells us about template generality.** Hybrid stretches the template — about half the sections needed content-reshaping rather than content-filling — but the 10-section skeleton held. The template assumes "this doc describes a source runtime"; Hybrid isn't really a source runtime, so sections 1-5 became meta-descriptions. A reader skimming the section headers sees familiar structure (Detection, Inventory, Frontmatter, Mapping, Modality), and the content within each makes sense as "how Hybrid handles this concern."

The alternative — inventing a new section structure just for Hybrid — would have been worse. It would have reduced cross-doc consistency and forced readers to learn a second layout. Treating Hybrid as a "dialect whose rules are composition rules" keeps the template uniform.

**Relationship to the six runtime-specific dialect docs.** This doc is light on content compared to the others because it delegates almost everything to them. Its job is to specify the composition procedure. A reader working on a specific Hybrid (say, OpenClaw + Claude Code) uses *this* doc for the merge rules, the OpenClaw doc for OpenClaw-specific details, and the Claude Code doc for Claude Code-specific details. Hybrid is the glue, not the substance.

Open questions:

- **§1a's "common pairings" table** is based on plausible scenarios, not measured data. Worth corpus-testing to see which hybrids actually appear in practice — some of the listed pairings may never occur, and unlisted ones may be more common than expected.
- **§4b's "primary wins" default** is opinionated. An alternative ("merge always, flag conflicts as critical") is defensible but more disruptive. The conservative default keeps generation moving; a v2 could offer `--hybrid-resolution=primary|merge|halt`.
- **§6a's Agent Skills std + Claude Code promotion** is a special case. There might be other "superset/subset" pairings we should handle similarly — e.g., if AutoGen 0.2 and 0.4 signals tie (same runtime, different versions), should we promote to the newer? Not addressed in v1; flagged for when more runtimes are added.
- **§4d merged metadata** assumes metadata from different runtimes is compatible to combine. If runtimes encode conflicting metadata (e.g., one runtime's `reasoning_mode: "plan"` and another's `reasoning_mode: "exec"` for the same element), merge is unsafe. Worth adding a metadata-conflict-detection rule.
- **§6b cross-framework Python imports** flags bridge files but doesn't suggest how to handle them. A file importing both `langgraph` and `autogen_agentchat` is either a Hybrid artifact or a genuine bridge module; the distinction matters for generation but isn't automated.
- **No detection signals for Hybrid-specific intent.** Some specs are authored with hybrid intent from the start (e.g., a project that deliberately uses Claude Code for dev ergonomics and OpenClaw for deployment). Others are hybrid by accident (artifact directories from a migration). Step 0 cannot distinguish these; Rule 6d's `--source-runtime` override is the only user-side recourse. Worth considering a `--hybrid-intent=authored|accidental` flag for richer treatment.
- **Three-way Hybrid workflow** (§6c) works in principle but elicitation UX grows linearly. A real user facing 15 conflicts across three runtimes may abandon elicitation. v2 could add conflict-grouping or batch resolution.
- **Schema-level formalisation** — `hybrid_primary` and `hybrid_contributors` fields are specified here but need to be added to the formal `classification.json` JSON Schema (deferred task per `spec.md`). Same for the `conflict` field in `element_mapping.json`.
