# Melleafy Steps 1a + 1b: File Inventory and Element Tagging

**Version**: 4.1.0 | **Prereq**: `classification.json` | **Produces**: `inventory.json`

> **Schema**: Output `intermediate/inventory.json` MUST conform to `.claude/schemas/inventory.schema.json`.

Step 1a reads files from the source based on the detected runtime's dialect. Step 1b takes those files and produces `inventory.json` — every significant element tagged with one of 17 tags and assigned to one of 9 dependency categories.

---

## Step 1a: File Inventory

Read source files per the runtime's dialect. The dialect doc at `melleafy-handoff/plans/dialects/<runtime>.md` defines exactly which files to read and their roles.

| Runtime             | Primary files                                                          | Roles                                                                      |
| ------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `openclaw`          | `SOUL.md`, `AGENTS.md`, `SETUP.md` (opt), `*.md` companions            | C1 identity, C2 operating rules, C8 runtime env                            |
| `claude_code`       | `CLAUDE.md`, `.claude/commands/*.md`, frontmatter files                | C1-C2 per frontmatter; C6 for tool declarations                            |
| `agent_skills_std`  | Single `.md` file with YAML frontmatter                                | All roles from frontmatter + body                                          |
| `letta`             | `.af` JSON file                                                        | Parsed as JSON with `json:<jq-path>` source references                     |
| `crewai`            | `crew.py`, `agents.yaml`, `tasks.yaml`, `tools.py`                     | Python AST + YAML                                                          |
| `langgraph`         | Python files with `StateGraph` construction                            | `py:<file>:<range>` source references                                      |
| `autogen`           | Python files with `AssistantAgent`/`UserProxyAgent`, `OAI_CONFIG_LIST` | Version split: `from autogen import` = 0.2; `from autogen_agentchat` = 0.4 |
| `openai_agents_sdk` | Python files with `Agent(`, `Runner.run_sync(`                         | `py:<file>:<range>` source references                                      |
| `smolagents`        | Python files with `CodeAgent(`/`ToolCallingAgent(`                     | `py:<file>:<range>` source references                                      |

**Also check**: whether the spec's parent directory contains `scripts/`, `references/`, or `assets/` directories (Agent Skills companion directories). If present, inventory their contents — scripts the spec references are tool-dependent inputs (C6); reference docs the spec says to "consult" are external data dependencies (C3 or C8). These directories are _mirror sources_ per Rule OUT-6 (see `mellea-fy.md`): they remain at the skill root as the source of truth, and Step 3a-pre copies them into `<package_name>/` before any code body is generated. Downstream steps may assume the package-internal copy is the runtime location, and emitted code MUST resolve their paths via `Path(__file__).parent / "<dir>/<file>"`.

**Output of Step 1a**: a list of `{filepath, role, frontmatter, content}` tuples consumed by Step 1b.

---

## Step 1b: Element Tagging and Categorisation

### The 17 tags

Every significant line of the source spec becomes an element with exactly one of:

| Tag               | Meaning                                                     | Typical Mellea target (Step 2)                      |
| ----------------- | ----------------------------------------------------------- | --------------------------------------------------- |
| `EXTRACT`         | Pull structured data from unstructured input                | `@generative` slot                                  |
| `CLASSIFY`        | Assign input to one of N categories                         | `@generative` slot returning `Literal`              |
| `GENERATE`        | Produce free-form text/artifact meeting a schema            | `m.instruct(format=Schema)`                         |
| `VALIDATE_OUTPUT` | Check the agent's own generated text                        | `Requirement` in `requirements.py`                  |
| `VALIDATE_DOMAIN` | Check external data/artifact (code, paper, patch)           | `m.instruct(format=VerdictSchema)` in `pipeline.py` |
| `TRANSFORM`       | Convert input of type A to type B                           | `m.transform()` or `m.instruct`                     |
| `QUERY`           | Read-only question against in-scope data                    | `m.query()`                                         |
| `DECIDE`          | Conditional branching based on structured input             | `m.instruct(format=DecisionSchema)`                 |
| `ORCHESTRATE`     | Pipeline control flow                                       | Plain Python in `pipeline.py`                       |
| `CONVERSE`        | Multi-turn interaction                                      | `m.chat()`, parameter, or stub                      |
| `REMEDIATE`       | Fix-and-verify loop                                         | `while` loop with `m.instruct(format=PatchSchema)`  |
| `SCHEMA`          | Typed output/input shape definition                         | Pydantic `BaseModel` in `schemas.py`                |
| `CONFIG`          | Named threshold, parameter, or constant                     | `Final[T]` in `config.py`                           |
| `TOOL_TEMPLATE`   | Parameterised tool callable                                 | Function in `tools.py` / `constrained_slots.py`     |
| `DETERMINISTIC`   | Pure Python logic requiring no LLM                          | Helper function in `pipeline.py` or `tools.py`      |
| `TOOL_INPUT`      | Data a tool produces that feeds the pipeline as a parameter | Parameter on `run_pipeline` or `loader.py` call     |
| `NO_DECOMPOSE`    | Prose, section headers, decorative text                     | No generation target                                |

**Python vs LLM decision rule**: Before tagging an element as `CLASSIFY`/`EXTRACT`/`GENERATE`, ask: does this require judgment, interpretation, or natural language understanding?

- **Tag `DETERMINISTIC`**: config parsing, URL template filling, parameter mapping, enum lookups, JSON payload construction, string formatting, validation logic, numerical computations, `if/for/dict.get()/str.format()` operations.
- **Tag `CLASSIFY`/`EXTRACT`/`GENERATE`**: intent classification from natural language, severity assessment, content generation, natural language formatting, out-of-scope detection.

**VALIDATE_OUTPUT vs VALIDATE_DOMAIN** — this distinction is critical:

- `VALIDATE_OUTPUT`: checks on what _the agent itself produced_. → `Requirement`.
- `VALIDATE_DOMAIN`: checks the agent _performs on external data_ (code, papers, patches). → `m.instruct(format=VerdictSchema)`.
  If an element tagged `VALIDATE_OUTPUT` describes checking something other than the agent's own output, flag it as a probable tagging error.

### The nine dependency categories (C1–C9)

Every element gets a category (`C1`–`C9`) or `—` (no external dependency):

| Code | Category                       | What it is                                                   | Typical elements                                                |
| ---- | ------------------------------ | ------------------------------------------------------------ | --------------------------------------------------------------- |
| C1   | Identity & behavioral context  | Persona, role, tone, immutable rules                         | SOUL.md body, `## Identity` sections, `prefix=` text            |
| C2   | Operating rules & policy       | Conditional directives, approval gates, workflow rules       | AGENTS.md rules, `if X then Y` decision elements                |
| C3   | User & environment facts       | Stable external facts the pipeline needs but doesn't produce | Reference docs, domain-specific context files                   |
| C4   | Short-term / working state     | Per-session scratchpad, conversation history                 | Session variables, context accumulation across turns            |
| C5   | Long-term / archival memory    | Durable cross-session knowledge                              | User preference stores, knowledge bases                         |
| C6   | Tool / capability declarations | Executable tool definitions, API calls                       | `TOOL_TEMPLATE` elements, HTTP endpoints, MCP tools             |
| C7   | Credentials & secrets          | API keys, OAuth tokens, connection strings                   | Env-var references, `API_KEY` patterns                          |
| C8   | Runtime environment            | Packages, model ID, system requirements                      | `pyproject.toml` deps, model backend config                     |
| C9   | Scheduling & triggers          | Cron, heartbeat, webhook, file-change events                 | `schedule:` frontmatter, event handler patterns                 |
| —    | (no dependency)                | Logic that needs no external resource                        | `VALIDATE_OUTPUT`, `SCHEMA`, `NO_DECOMPOSE`, most `ORCHESTRATE` |

**Tag + category orthogonality** — forbidden combinations:

- `SCHEMA` with category ≠ `—` (schemas are structure, not external dependencies)
- `CONFIG` with category ∈ {C4, C5, C9} (these are always runtime-delegated, not bundled constants)
- `TOOL_TEMPLATE` with category ≠ C6 (tools are C6 by definition)
- `NO_DECOMPOSE` with category ≠ `—`

### Two-pass processing

**Pass 1 — Section discovery**: lightweight LLM invocation per file producing candidate element boundaries `{start_line, end_line, rough_kind}`. `rough_kind` is one of `{rule, check, constant, tool_ref, schema, prose, other}` — not a tag yet. Output schema is one class (`SectionBoundary`) with primitive fields.

**Pass 2 — Element refinement**: single LLM invocation processing all candidate boundaries and returning `List[InventoryElement]`. Each element in the list is the full element record: `tag`, `category`, `content_summary`, metadata. The `List[InventoryElement]` schema uses one class — KB5 schema priming concerns do not apply to melleafy compilation calls (KB5 governs Mellea pipeline sessions inside compiled skills, not the compilation process itself).

**Retry protocol** (when refinement produces invalid output):

1. Retry 1: include the validation error and re-invoke.
2. Retry 2: widen context to include neighboring elements.
3. Retry 3: split the element into two and re-invoke each separately.
   After 3 retries: record as `tag: NO_DECOMPOSE, category: "—", notes: "refinement failed after 3 retries: <reason>"`. Step 1b does not halt on single-element failure.

**Cross-element pass** (deterministic — no LLM): after all elements are refined, identify aggregation candidates:

- Two `VALIDATE_OUTPUT` elements with near-identical content → flag with `aggregation_hint`
- Two `CONFIG` elements targeting the same constant name → flag
- Three+ sequential `ORCHESTRATE` elements → flag as "orchestration chain"
  Aggregation hints are advisory; Step 2.5a commits.

### Coverage measurement

Target: ≥95% of non-blank, non-heading source lines represented in `inventory.json`.

Denominator: all source lines excluding pure whitespace and Markdown heading lines (`^\s*#+\s`).
Numerator: lines within some element's `source_lines` range.

Record in `intermediate/coverage_report.json`. If coverage < 0.95: retry section discovery with relaxed boundary heuristics on the lowest-coverage files. If still < 0.95 after retry: halt with a generation-halt error.

### Decomposition rules

**Compound elements**: if an element contains multiple operations ("Identify and rule out failure modes" = EXTRACT + VALIDATE), split before mapping.

**Conditional elements**: model the condition as a `DECIDE` gate wrapping the relevant sub-elements.

**Checklist elements**: group into a single Mellea construct or split — use judgment based on whether independent pass/fail tracking is needed.

**Cross-cutting requirements**: if a quality standard applies globally to all outputs, define it once in `requirements.py` and attach to every `m.instruct()` call.

**Remediation loops**: if the spec describes an iterative fix-and-verify cycle, tag the modification step `REMEDIATE` and the evaluation step `EXTRACT` or `VALIDATE_DOMAIN`. Implement as a bounded `while` loop with `MAX_REMEDIATION_ITERATIONS` in `config.py`.

---

## Output: `inventory.json`

Every element has this shape:

```json
{
  "element_id": "elem_042",
  "source_file": "AGENTS.md",
  "source_lines": "15-22",
  "tag": "DECIDE",
  "category": "C2",
  "content_summary": "Escalate critical-priority tickets before auto-triaging",
  "content_full": "When a ticket arrives with priority:critical,\nalways escalate to L2 before\nrunning the auto-triage workflow.",
  "confidence": { "tag": 0.95, "category": 0.9 },
  "aggregation_hint": null,
  "notes": null,
  "dialect_attribution": "openclaw:AGENTS.md body rule"
}
```

Element IDs are `elem_<NNN>` (zero-padded, source order). IDs are stable within a run but not across re-runs when source changes.

**Cross-checks before Step 1b declares done**:

- Coverage ≥ 0.95
- Every element has `tag` in the 17-tag set
- Every element has `category` in `{C1..C9, "—"}`
- No element has a forbidden tag+category combination
- `element_id` values are sequential with no gaps
- Every `source_file` refers to a file from Step 1a's list
