# Melleafy Step 6: Supporting Artifact Generation

**Version**: 4.1.2 | **Prereq**: Step 5 complete | **Produces**: `mapping_report.md`, `melleafy.json`, `SETUP.md`, `README.md`, `SKILL.md` (non-.md sources only)

> **Schema**: Output `melleafy.json` MUST conform to `.claude/schemas/melleafy.schema.json`.

> **Output path rule** (Rule OUT-3): All files produced by Step 6 (`mapping_report.md`, `melleafy.json`, `SETUP.md`, `README.md`, `SKILL.md`) are written **inside `<package_name>/`** — NOT at the skill root. See `mellea-fy.md` §Output directory layout for the full tree.

Step 6 produces all human-facing documentation. LLM invocations here are narrative-only — structured data (`melleafy.json`, `dependencies.yaml`) is generated deterministically from `dependency_plan.json`. No modification of Python files.

---

## Mapping report (`mapping_report.md`)

Nine sections in fixed order — non-negotiable (section headers are mechanically consistent so automated tools can locate them):

1. **Classification** — the five axes from `classification.json` in reader-friendly order (archetype → shape → tool involvement → source runtime → modality). Includes the one-paragraph LLM-generated classification narrative and the R14 auto-mode recap callout if applicable.

2. **Decomposition Summary** — element counts by tag and category (cross-tab table), aggregate statistics: coverage ratio from Step 1b, total element count, unique source files.

3. **Element Mapping** — every element with `element_id`, source location, tag, category, mapped target file, and target symbol. Grouped by target file for readability.

4. **Judgment Calls** — elements flagged with `llm_judgement_required: true` from Step 2, plus Step 5 retries with `attempts > 1`. Each entry includes a LLM-generated one-paragraph explanation referencing the specific tag, category, or recipe involved (generic explanations trigger retry).

5. **Removed During Audit** — table from `element_mapping_amendments.json:removed[]` with rationale per row. If no elements were removed, writes "No elements removed during audit."

6. **Provenance Appendix** (header)

7. **Source file contributions** — for each file Step 1a read, which elements came from which line ranges.

8. **Runtime-specific constructs not reproduced** — dialect-doc rows that matched the source but are not reproduced in v1. For each: what was declared, why melleafy doesn't reproduce it, what the user should do.

9. **Detected but not handled (deferred)** — features the source references that melleafy does not support in v1 (per spec R10).

**Rule**: deterministic tables take priority over LLM narrative. If narrative contradicts a table, the narrative is the bug. Empty sections still appear with a single-line placeholder rather than being omitted.

---

## SETUP.md (conditional)

Emitted when: any C4, C5, C9, non-bundled C6, C7, non-default C8, or host-needing modality entry exists in `dependency_plan.json`.

Numbered sections in fixed order (conditional sections omitted when not triggered):

- **§1 Install** — always present: `pip install -e .` and verification
- **§2 Environment variables** (C7) — if any C7 entries: env vars to set, with `export VAR=<your_key_here>` commands
- **§3 Model backend** (C8) — always present: backend config and model ID setup
- **§4 Short-term state** (C4) — if any C4 entries: session state backend options
- **§5 Long-term memory** (C5) — if any C5 entries: memory backend options (Chroma, pgvector, Letta server)
- **§6 Scheduling** (C9) — if any C9 entries: cron/webhook setup
- **§7 Host adapter for `<modality>`** — if modality is `review_gated`, `conversational_session`, `realtime_media`, or `streaming`: host adapter implementation instructions
- **§8 Generated stubs to implement** — if any `stub` or `delegate_to_runtime` dispositions: table listing every stub with its target symbol and implementation instructions
- **§9 Fixtures and smoke test** — always present: how to run `python -m pytest fixtures/` and the expected output

SETUP.md sections do NOT invent backend options. The C8 default is always `ollama` with `granite3.3:8b` unless the source spec explicitly names a different backend.

---

## `melleafy.json` finalisation (R20)

Step 3 wrote the skeleton. Step 6 populates `categories_resolved` and remaining fields from `dependency_plan.json`. This is entirely deterministic — no LLM.

Key fields added in Step 6:

```json
{
  "categories_resolved": {
    "c1_identity": {
      "count": 2,
      "disposition": "bundle",
      "entries": [
        {
          "entry_id": "dep_001",
          "disposition": "bundle",
          "target": "config.py:PREFIX_TEXT",
          "description": "<content_summary of the source C1 element from inventory.json>"
        }
      ]
    },
    "c2_operating_rules": {"count": 5, "disposition": "bundle", "entries": [...]},
    "c6_tools": {
      "count": 3,
      "entries": [
        {"entry_id": "dep_050", "disposition": "real_impl", "target": "tools.py:doi_lookup"},
        {"entry_id": "dep_051", "disposition": "stub", "target": "constrained_slots.py:slack_post"}
      ]
    }
  },
  "entry_signature": "run_pipeline(ticket_text: str, priority: str = 'normal') -> TriageReport",
  "pipeline_parameters": [
    {"name": "ticket_text", "type": "str", "required": true},
    {"name": "priority", "type": "str", "required": false, "default": "normal"}
  ],
  "declared_env_vars": ["SLACK_API_TOKEN", "JIRA_API_KEY"]
}
```

**Rule 6-1 — `categories_resolved` shape invariant**: `categories_resolved` MUST always be emitted as a JSON object keyed by category code (`c1_identity`, `c2_operating_rules`, etc.), never as an array. Even when a category has zero resolved entries, its key must be present with `{"count": 0, "entries": []}`. An array-valued `categories_resolved` (e.g. `["C1", "C2"]`) is a malformed manifest and must not be produced.

**Rule 6-2 — C1 entry description**: For every entry in `categories_resolved.c1_identity.entries[]`, include a `description` field containing the `content_summary` of the source element from `inventory.json` (joined via `source_elements[0]`). If `content_summary` is absent or empty, use the first sentence of `content_full`, truncated to 200 characters. If neither is available, omit the field rather than emitting an empty string. Entries in other categories (C2–C9) do not require a `description` field unless their source element carries semantic content that downstream consumers would use.

`entry_signature` is derived by AST-inspecting the generated `pipeline.py:run_pipeline` function signature — not LLM-generated.

Before Step 6 declares done, verify `melleafy.json` contains the hard-required fields consumed by the export command: `manifest_version` (≥ 1.1.0), `entry_signature`, and `package_name`. No schema file is consulted — requirements are defined by `exporter.py:stage1_validate` and `stage2_load`.

---

## Auto-mode recap (R14)

When `dependency_plan.json:generation_mode == "auto"` AND plan contains any `stub` or `delegate_to_runtime` disposition:

1. Print to stdout:

```
Generated package at <output_path>.

⚠ This package contains stubs and runtime-delegated dependencies.
  Stubs: 2 (C6 Tools)
  Delegates: 3 (C4: 1, C5: 1, C9: 1)

See SETUP.md §8 for stubs to implement and §4–§7 for delegated backends.
Re-run with --dependencies=ask to review defaults interactively.
```

2. Also write this recap as a callout at the top of the mapping report's Classification section.

Do NOT emit recap when mode is `ask` or `config` (user already acknowledged stubs), or when no stubs/delegates are present.

---

## LLM-generated narrative pieces (summary)

Narrative pieces are batched to minimise LLM call count. KB5 schema priming concerns do not apply to melleafy compilation calls (KB5 governs Mellea pipeline sessions inside compiled skills, not the compilation process itself). Batching rules:

- **Single invocation** where pieces share the same input context: `classification_narrative` and `deferred_feature_entry` can be generated together.
- **Separate invocations only** when input contexts are meaningfully different or the combined context would exceed the model's practical window.
- `judgment_call_explanation` entries: if ≤3 judgment calls exist, generate all in one invocation with a list of `{element_id, explanation}` pairs. If >3, batch into groups of 3.
- `setup_section_body` entries: all SETUP.md §4–§7 bodies in one invocation.

Recipes:

| Recipe                            | Generates                                        | Context                                 |
| --------------------------------- | ------------------------------------------------ | --------------------------------------- |
| `classification_narrative`        | One-paragraph lede for Classification section    | All five axes + element counts          |
| `judgment_call_explanation`       | One paragraph per judgment call                  | Specific trace entry + element summary  |
| `runtime_specific_not_reproduced` | Short explanation per non-reproduced dialect row | Dialect-row identifier + rationale      |
| `deferred_feature_entry`          | Short paragraph per deferred R10 feature         | Detection record + spec.md entry name   |
| `setup_section_body`              | Section body for SETUP.md §4–§7                  | Dependency entries + known backend list |

---

---

## Final action: Generate `SKILL.md` if absent (non-.md sources only)

After all other Step 6 artifacts are written, check whether a `SKILL.md` exists inside `<package_name>/`.

**Condition**: generate `SKILL.md` if **both** are true:

- No `SKILL.md` exists inside `<package_name>/`
- The source runtime is a non-.md dialect (CrewAI, LangGraph, Letta, or any dialect whose source files are not `.md`)

For `.md`-source runtimes (OpenClaw, agent-skills-std, Claude Code), the source file already provides SKILL.md-compatible frontmatter — skip this action.

**Generated `SKILL.md` template**:

```markdown
---
name: <skill-directory-name in kebab-case>
description: "<one-sentence description — double-quoted; no unescaped colons or newlines>"
---

> **Note — auto-generated by Melleafy 4.3.2**: This `SKILL.md` was created as a
> compatibility shim so the Mellea Skills Compiler CLI (`mellea-skills run`) can locate
> and execute this skill. The original source for this skill is not a `.md` file
> (dialect: `<detected dialect>`). This file is a **work in progress** — it provides
> the minimum frontmatter required for CLI operation. A more comprehensive approach
> to non-`.md` source formats is planned for a future melleafy release.
>
> For the full package description, see `README.md`. For setup instructions, see `SETUP.md`.

# <Human-readable skill title>

<First paragraph of README.md body — the "What it does" summary.>

**Source runtime**: <dialect>
**Source files**: <comma-separated list of original source files>
**Generated**: <ISO date>
```

**Derivation rules**:

- `name`: skill directory name in kebab-case (must match the directory exactly)
- `description`: first sentence of the README.md introduction, truncated to ≤120 chars; fall back to `melleafy.json:entry_signature` if README not yet written
- `description` must be double-quoted if it contains `:`, `-`, or special chars
- Body: first paragraph of README.md body, verbatim
- `Source files`: list from `classification.json:classification_signals` source file keys, or the original input path(s)

For the full package description, users of this generated `SKILL.md` should refer to `README.md` inside `<package_name>/`.

---

## Cross-checks before Step 6 declares done

- `mapping_report.md` has all 9 sections in fixed order
- No `<!-- populated in Step 6 -->` placeholders remain
- `melleafy.json` contains hard-required fields: `manifest_version` (≥ 1.1.0), `entry_signature`, `package_name`
- Every element in "Element Mapping" links to an existing target symbol
- Every dialect-doc "not reproduced" row that matched the source has a paragraph in §8
- Every detected Deferred Item has a paragraph in §9
- `dependencies.yaml` entries match `dependency_plan.json` entries
- If auto mode + stubs present, recap appears in both stdout and mapping report
- If source is non-.md: `SKILL.md` exists **inside `<package_name>/`** with valid YAML frontmatter (`name` and `description` fields present, description double-quoted)
