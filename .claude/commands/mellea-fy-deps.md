# Melleafy Step 2.5: Dependency Audit and Elicitation

**Version**: 4.2.0 | **Prereq**: `inventory.json`, `element_mapping.json` | **Produces**: `dependency_plan.json`, `mellea_api_ref.json`, `mellea_doc_index.json`

> **Schema**: Output `intermediate/dependency_plan.json` MUST conform to `.claude/schemas/dependency_plan.schema.json`.

Step 2.5 is entirely deterministic — no LLM invocations. It reads `element_mapping.json` (where every `TOOL_TEMPLATE` entry has `final_target_file: "pending_step_2.5"`), assigns a **disposition** to every external dependency, elicits user input when the generation mode requires it, commits the plan, and amends `element_mapping.json` accordingly.

This step must not be skipped. Every external dependency must have an explicit disposition before Step 3 can emit skeletons.

---

## Four sub-steps

### 2.5a: Dependency audit

Collect every element from `inventory.json` whose category is C1–C9. For each, look up the default disposition from the table below. Group by category. Also apply any aggregation hints from Step 1b's cross-element pass.

**Aggregation during audit**: when two elements have `aggregation_hint` pointing at each other, merge them into one dependency entry with a combined `source_elements` list and the disposition that covers both.

**Output**: `intermediate/dependency_audit.json` — one entry per dependency with `entry_id`, `category`, `default_disposition`, `source_elements`, and `subtype` (for C6: `http`, `graphql`, `mcp`, `sdk`, `abstract`).

### 2.5b: Elicitation (ask and config modes only)

If generation mode is `auto` or `config:<path>`: skip to 2.5c.

If generation mode is `ask`: display a terminal UI (using `rich`) for each dependency in the audit. Show: category, source elements, default disposition, available alternatives. Allow the user to accept the default or override.

If generation mode is `config:<path>`: read the JSON config file. The config format mirrors `dependency_plan.json:plan[]` — a list of `{entry_id, disposition, override_rationale}` objects. Apply overrides to the audit results.

**Available override dispositions**:

- `bundle` — embed the dependency value directly in generated code (as a `config.py` constant)
- `real_impl` — generate real Python implementation (HTTP call, SDK usage, etc.)
- `stub` — generate a `NotImplementedError` stub for the user to implement
- `mock` — generate a mock implementation using fixture data (test/demo use)
- `delegate_to_runtime` — the host runtime provides this (session state, memory backends)
- `external_input` — supply at invocation time as a CLI flag or environment variable
- `load_from_disk` — read from a local file at runtime (reference docs, config files)
- `remove` — source element is a cross-reference artifact; don't generate anything

### 2.5c: Commit the plan

Write `dependency_plan.json` combining audit results with any user overrides.

```json
{
  "format_version": "1.0",
  "source_runtime": "openclaw",
  "generation_mode": "ask",
  "user_acknowledged_stubs": true,
  "plan": [
    {
      "entry_id": "dep_050",
      "category": "c6_tools",
      "disposition": "real_impl",
      "source_of_decision": "auto",
      "source_elements": ["elem_042"],
      "target": "tools.py:doi_lookup",
      "subtype": "http",
      "prerequisites": ["HTTP access to api.crossref.org"]
    },
    {
      "entry_id": "dep_051",
      "category": "c6_tools",
      "disposition": "stub",
      "source_of_decision": "user",
      "override_rationale": "Slack OAuth not available",
      "target": "constrained_slots.py:slack_post"
    }
  ]
}
```

`user_acknowledged_stubs`: set to `true` if the user interacted with the elicitation UI (ask mode) or provided a config file containing at least one stub disposition. Used by Step 6 to decide whether to suppress the auto-mode recap warning.

### 2.5d: Amend element_mapping.json

For each entry in `dependency_plan.json` with a non-default disposition, amend the corresponding entries in `element_mapping.json`:

- Update `final_target_file` from `"pending_step_2.5"` to the actual target (`tools.py`, `constrained_slots.py`, or `fixtures/mock_tools.py`)
- Record the amendment in `intermediate/element_mapping_amendments.json` for audit

**Constitution Article 4 compliance**: `element_mapping_amendments.json` always contains the full set of amendments, even if a disposition matches the default. This ensures the Step 6 mapping report's "Removed During Audit" section is authoritative. Never silently apply amendments — always record them.

### 2.5e: API reference generation

`intermediate/mellea_api_ref.json` is **already populated** by the compile pipeline before this slash command starts (see `src/mellea_skills_compiler/compile/grounding.py:write_mellea_api_ref`). The slash command runs with `--allowed-tools Read,Write,Edit` and cannot introspect the installed `mellea` package itself; the deterministic Python step does that work pre-invocation. Your only responsibility here is to **verify** the file exists and is well-formed before Step 5 / Step 7 consume it.

The file is grounding context for Step 5 (body generation) and the live signature source for Step 7's `stdlib-arity`, `import-soundness`, and `known-behaviours` lints.

Expected JSON shape when grounding is available:

```json
{
  "format_version": "1.0",
  "mellea_version": "<installed version>",
  "grounding_unavailable": false,
  "modules": {
    "<module.name>": { "<symbol>": { "signature": "<symbol(...)>" } }
  },
  "forbidden_param_names": ["f_args", "f_kwargs", "m", "..."],
  "compatibility": [
    /* entries from .claude/data/compatibility.yaml filtered to mellea_version */
  ]
}
```

`modules` covers a fixed CORE_MODULES set (`mellea.stdlib.requirements`, `mellea.stdlib.sampling`, `mellea.backends.model_options`) plus any modules referenced by `dependency_plan.json:plan[].target`. `forbidden_param_names` is extracted live from `mellea.stdlib.components.genslot._disallowed_param_names` when reachable.

When `mellea` is not installed the compile pipeline writes the `grounding_unavailable: true` shape:

```json
{
  "format_version": "1.0",
  "mellea_version": null,
  "grounding_unavailable": true,
  "modules": {},
  "forbidden_param_names": [
    "f_args",
    "f_kwargs",
    "m",
    "context",
    "backend",
    "model_options",
    "strategy",
    "precondition_requirements",
    "requirements"
  ],
  "compatibility": []
}
```

The `forbidden_param_names` static fallback is always present even when grounding is unavailable — the KB6 lint must always have something to check against.

Step 5 falls back to inline KB patterns from `/mellea-fy-behaviours` when `grounding_unavailable` is `true`. Step 7's `stdlib-arity` lint falls back to its static known-signature table.

**Output**: `intermediate/mellea_api_ref.json` — always written by the compile pipeline, even if empty.

### 2.5f: Doc index generation

`intermediate/mellea_doc_index.json` is **already populated** by the compile pipeline before this slash command starts (see `src/mellea_skills_compiler/compile/grounding.py:write_mellea_doc_index`). The slash command cannot make network calls; the deterministic Python step fetches `https://docs.mellea.ai/` (with a 24-hour cache and stale-cache fallback if the network is unreachable). Your only responsibility here is to **verify** the file exists and is well-formed before the doc-citation lint consumes it.

This file is the authoritative source for the doc-citation lint (item 8) — every KB `**Verified:**` URL is checked against it.

Expected JSON shape:

```json
{
  "format_version": "1.0",
  "fetched_at": "<ISO 8601 UTC>",
  "source": "https://docs.mellea.ai/",
  "fetch_status": "ok | failed: <reason>",
  "doc_pages": ["/getting-started/installation", "..."]
}
```

`doc_pages` is the sorted, deduplicated set of `href="/..."` links extracted from the docs.mellea.ai navigation. If the fetch failed and no cached copy was usable, the compile pipeline falls back to the canonical 2026-04-28 page list below and sets `fetch_status: "failed: <reason>"`. The doc-citation lint treats a missing or empty `doc_pages` list as "index unavailable — skip citation check" (warning, not failure), so a network-unreachable environment does not block generation.

The known doc pages from the navigation (as of 2026-04-28 — also imported by `compile/grounding.py` as its hardcoded fallback):

```
/getting-started/installation
/tutorials/01-your-first-generative-program
/tutorials/04-making-agents-reliable
/concepts/generative-functions
/concepts/requirements-system
/concepts/instruct-validate-repair
/concepts/mobjects-and-mify
/concepts/context-and-sessions
/how-to/enforce-structured-output
/how-to/write-custom-verifiers
/how-to/use-async-and-streaming
/how-to/use-context-and-sessions
/how-to/configure-model-options
/how-to/use-images-and-vision
/how-to/build-a-rag-pipeline
/guide/backends-and-configuration
/guide/tools-and-agents
/advanced/inference-time-scaling
/integrations/ollama
/integrations/openai
/integrations/bedrock
/integrations/watsonx
/integrations/huggingface
/integrations/vertex-ai
/integrations/langchain
```

**Output**: `intermediate/mellea_doc_index.json` — always written; `doc_pages` may be empty if fetch failed.

---

## Category default dispositions

| Category                                   | Default disposition   | Rationale                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------ | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1 Identity                                | `bundle`              | Persona text is always embedded in `config.py:PREFIX_TEXT`                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| C2 Operating rules                         | `bundle`              | Rules are embedded as docstring guidance or config constants                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| C3 User facts (stable)                     | `bundle`              | Stable facts go into config or grounding_context                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| C3 User facts (overridable)                | `external_input`      | Overridable facts become CLI flags                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| C4 Short-term state                        | `delegate_to_runtime` | Session state is provided by the host's session management                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| C5 Long-term memory                        | `delegate_to_runtime` | Memory backends are runtime-specific (Letta, pgvector, Chroma)                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| C6 Tools (HTTP/API with concrete endpoint) | `real_impl`           | Concrete endpoints can be implemented immediately                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| C6 Tools (abstract/capability-described)   | `stub`                | Abstract tools need user implementation                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| C7 Credentials                             | `external_input`      | Secrets always come from environment variables at runtime                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| C8 Runtime environment                     | `bundle`              | Model ID and backend go into config; packages into pyproject.toml. **`BACKEND` and `MODEL_ID` values are provided by the compile pipeline via the system prompt** (sourced from `.claude/data/runtime_defaults.json`, with optional `--backend` / `--model-id` CLI overrides). Use the values exactly as injected; do not invent alternatives. The Step 7 `runtime-defaults-bound` lint enforces consistency by comparing `config.py` against `<package_name>/intermediate/runtime_directive.json`. |
| C9 Scheduling/triggers                     | `delegate_to_runtime` | Cron, webhooks, and event loops are host-provided                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Cross-reference elements                   | `remove`              | Pure cross-reference artifacts produce no code                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

---

## The four generation modes

### `auto` (default)

Apply all category defaults. No user interaction. If any disposition produces a `stub` or `delegate_to_runtime`, Step 6 emits an auto-mode recap to stdout:

```
Generated package at <output_path>.

⚠ This package contains stubs and runtime-delegated dependencies.
  Stubs: 2 (C6 Tools)
  Delegates: 3 (C4: 1, C5: 1, C9: 1)

See SETUP.md §8 for stubs to implement and §4–§7 for delegated backends.
Re-run with --dependencies=ask to review defaults interactively.
```

### `ask`

Display a rich terminal UI for each dependency entry. For each entry:

- Show the element's `content_summary` and `source_lines`
- Show the default disposition with a one-line explanation of why
- List available alternative dispositions
- Accept input: Enter = accept default, letter = select alternative

After all entries: show a summary table of all committed dispositions. Ask for final confirmation before proceeding.

### `config:<path>`

Read a JSON config file at `<path>`. Format: `{"overrides": [{"entry_id": "dep_050", "disposition": "stub", "override_rationale": "..."}]}`. Apply these overrides on top of category defaults. Entries not listed in the config get their category default.

### `strict`

Apply category defaults. Before writing any files: check if any entry has `disposition ∈ {stub, delegate_to_runtime}`. If yes, halt with exit code 10 and a list of all entries that would produce stubs. The user must either re-run in `ask` mode to override them, or pass a config file with explicit `real_impl` dispositions for each.

Exit code 10 is distinct from all generated package exit codes (0–4) and from the lint failure code (11).

---

## Disposition effects on generated code

| Disposition           | `tools.py`          | `constrained_slots.py`                       | `config.py` / other                                                                                                     | `SETUP.md` mention                          |
| --------------------- | ------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `real_impl`           | Full implementation | —                                            | —                                                                                                                       | Only if prerequisites needed                |
| `stub`                | —                   | `NotImplementedError` stub with instructions | —                                                                                                                       | Yes — §8 lists stubs to implement           |
| `mock`                | —                   | —                                            | `fixtures/mock_tools.py` (mock)                                                                                         | Only in fixture docs                        |
| `delegate_to_runtime` | —                   | —                                            | —                                                                                                                       | Yes — §4–§7 explains the backend            |
| `external_input`      | —                   | —                                            | —                                                                                                                       | Yes — §2 (C7) or §3 (C8) with env var setup |
| `load_from_disk`      | —                   | —                                            | `loader.py` loads from `<package_dir>/references/` (Rule OUT-6 mirror) via `Path(__file__).parent / "references" / ...` | Yes — §1 with download commands             |
| `bundle`              | —                   | —                                            | Constant in `config.py`                                                                                                 | No                                          |
| `remove`              | —                   | —                                            | —                                                                                                                       | No                                          |

> **Rule 2.5-2 — Bundled-asset path resolution (Rule OUT-6 alignment)**: when a `real_impl` C6 implementation invokes a script or binary mirrored from the skill root into `<package_dir>/scripts/...`, or when a `load_from_disk` C3 implementation reads a mirrored reference under `<package_dir>/references/...`, the generated code MUST resolve the path package-relatively via `Path(__file__).parent / "<dir>/<file>"`. Never use `Path(repo_root) / ...`, never rely on the process working directory, and never accept the path via a function argument that the caller is expected to fill. The mirror at `<package_dir>/<dir>/` is established by Step 3a-pre (see `mellea-fy-generate.md`). This invariant is what lets `pip install`-ed packages and packages invoked from arbitrary directories find their bundled assets.

---

## Cross-checks before Step 2.5 declares done

- Every element from `inventory.json` with category ≠ `—` has a corresponding entry in `dependency_plan.json`
- Every entry's `disposition` is one of the 8 valid values
- No entry has `final_target_file: "pending_step_2.5"` remaining in `element_mapping.json`
- `element_mapping_amendments.json` records every change (even if no changes: write an empty `amendments: []` list)
- `intermediate/mellea_api_ref.json` exists and contains `forbidden_param_names` (non-empty list) and `compatibility` (list, may be empty)
- `intermediate/mellea_doc_index.json` exists (`fetch_status: "failed: ..."` with empty `doc_pages` is acceptable in offline environments)
- If mode is `strict` and any stub/delegate entry exists: halt was issued (don't reach this check — halt happens before)
