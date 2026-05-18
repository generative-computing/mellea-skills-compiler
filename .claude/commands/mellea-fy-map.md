# Melleafy Step 2: Element-to-Primitive Mapping

**Version**: 4.1.0 | **Prereq**: `inventory.json`, `classification.json` | **Produces**: `element_mapping.json`

> **Schema**: Output `intermediate/element_mapping.json` MUST conform to `.claude/schemas/element_mapping.schema.json`.

Step 2 reads `inventory.json` and produces `element_mapping.json` — the routing decision for every element: which file in the generated package, which symbol, which Mellea primitive.

**Important**: Step 2 does NOT commit dispositions for tool-dependent elements. Every `TOOL_TEMPLATE` mapping entry is provisional (`final_target_file: "pending_step_2.5"`). Step 2.5 decides `real_impl` vs `stub` vs `mock` and amends.

---

## Tag-to-primitive table

| Tag               | Primary primitive                                             | Target file                 | Notes                                                                                                   |
| ----------------- | ------------------------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------- |
| `EXTRACT`         | `@generative` slot                                            | `slots.py`                  | Two-step pattern when schema complexity warrants (§below)                                               |
| `CLASSIFY`        | `@generative` slot                                            | `slots.py`                  | Return type: `-> Literal[...]` — Ollama supports constrained decoding                                   |
| `GENERATE`        | `m.instruct(format=Schema)`                                   | inline in `pipeline.py`     | `format=` always a concrete Pydantic model, never `dict`                                                |
| `VALIDATE_OUTPUT` | `Requirement`                                                 | `requirements.py`           | Uses `validation_fn=simple_validate(...)` for structural checks; bare `description` for semantic checks |
| `VALIDATE_DOMAIN` | `m.instruct(format=DomainSchema)`                             | inline in `pipeline.py`     | Checks external artifacts; produces structured verdict, not pass/fail boolean                           |
| `TRANSFORM`       | `m.transform()` or `m.instruct(format=Schema)`                | inline in `pipeline.py`     | `m.transform()` when types are known; `m.instruct` when transformation needs prompted reasoning         |
| `QUERY`           | `m.query()`                                                   | inline in `pipeline.py`     | Read-only question against data already in scope                                                        |
| `DECIDE`          | `m.instruct(format=DecisionSchema)`                           | inline in `pipeline.py`     | Gates remediation loops (see Remediate below)                                                           |
| `ORCHESTRATE`     | Plain Python control flow                                     | `pipeline.py`               | Not a Mellea primitive — describes flow (sequential phases, branches, loops)                            |
| `CONVERSE`        | `m.chat()`, pipeline parameter, or `NotImplementedError` stub | varies                      | Three realisations — see below                                                                          |
| `REMEDIATE`       | Bounded `while` loop with `m.instruct(format=PatchSchema)`    | `pipeline.py`               | Three mapping entries: modification + evaluation + loop wrapper                                         |
| `SCHEMA`          | Pydantic `BaseModel` class                                    | `schemas.py`                | One class per schema; no nested submodels buried in function defs                                       |
| `CONFIG`          | `Final[T]` constant                                           | `config.py`                 | Under `# === C<N> ... ===` section header                                                               |
| `TOOL_TEMPLATE`   | Python function                                               | `tools.py` (provisional)    | Amended by Step 2.5d based on disposition                                                               |
| `DETERMINISTIC`   | Plain Python function                                         | `pipeline.py` or `tools.py` | `tools.py` when shared across branches or >15 lines                                                     |
| `TOOL_INPUT`      | Pipeline parameter or `loader.py` call                        | `main.py` or `loader.py`    | Data a tool produces that feeds the pipeline                                                            |
| `NO_DECOMPOSE`    | No primitive                                                  | —                           | Recorded in `element_mapping.json` with `primitive: "none"` for invariant completeness                  |

---

## Alternative rules

### EXTRACT — one-step vs two-step pattern

Default: one `@generative` slot returning the target schema.

**Two-step pattern applies when** any of:

- Target schema has cross-reference fields (a field that references another field's value in the same document)
- Target schema has more than 3 levels of nesting
- Target schema has optional fields whose presence depends on earlier fields' values
- Target schema has more than 4 fields OR contains `Literal` constraints OR has nested `BaseModel` objects OR lists of complex objects

When two-step applies, produce **two** mapping entries sharing the same `element_id` (suffixed `-step1`, `-step2`):

1. `@generative` slot returning a simplified flat structure (`slots.py:extract_X_raw`)
2. `m.instruct(format=FullSchema, strategy=RepairTemplateStrategy(loop_budget=3))` inline in `pipeline.py`

The reason: `@generative` has no retry/repair mechanism — malformed JSON silently returns empty. `m.instruct(format=...)` with `RepairTemplateStrategy` retries and repairs.

### VALIDATE_OUTPUT — executable vs LLM-judged

Default: `Requirement` with executable `validation_fn` (structural check in plain Python).

LLM-judged (bare `Requirement(description=...)`) only when `content_full` contains words like "accurate," "appropriate," "reasonable," "matches the spirit of" — markers of semantic judgement that can't be expressed in Python.

Record the choice as `validation_kind: "executable" | "llm_judged"` in the mapping entry.

### CONVERSE — three realisations

1. **`m.chat()` — LLM self-talk**: when the source describes multi-turn reasoning within the pipeline ("consider counterarguments then respond"). Emitted inline in `pipeline.py`.
2. **Pipeline parameter with default**: when the source says "ask the user for X." X becomes a parameter on `run_pipeline` with a default, exposed as a CLI flag on `main.py`.
3. **`NotImplementedError` stub**: when the source describes genuine interactive back-and-forth that can't be reshaped into either above — e.g., "iterate with the user until they approve the output." SETUP.md §7 explains the host-adapter requirement.

Decision rule: pick (2) when `content_full` contains "ask the user" or "user provides"; (1) when phrasing is about the agent's own reasoning ("consider," "reflect"); (3) when neither fits. If `classification.json:modality == "conversational_session"`, prefer (1).

### REMEDIATE — loop structure

Three mapping entries for one source element:

1. **Modification step** — `m.instruct(format=PatchSchema)` producing a fix
2. **Evaluation step** — `m.instruct(format=VerdictSchema)` checking whether the fix worked
3. **Loop wrapper** — plain Python `while i < MAX_REMEDIATION_ITERATIONS` tying them together

All three route to `pipeline.py`. `MAX_REMEDIATION_ITERATIONS` is always a `config.py` constant with default 3.

### TOOL_TEMPLATE — provisional file routing

Step 2 always routes `TOOL_TEMPLATE` to `tools.py` initially. Step 2.5d amends based on disposition:

- `real_impl` → stays in `tools.py`
- `stub` or `delegate_to_runtime` → moved to `constrained_slots.py`
- `mock` → moved to `fixtures/mock_tools.py`

Record `final_target_file: "pending_step_2.5"` in the mapping entry until Step 2.5d runs.

---

## Dialect-specific overrides

The dialect mapping table in `docs/dialects/<runtime>.md` takes precedence over the general table above.

Precedence (highest first):

1. Dialect doc's mapping table (source-signal-specific rows)
2. Alternative rules above (tag-specific cases)
3. General tag-to-primitive table (the default)

Record every dialect override with `dialect_override_applied: "<runtime>:<row>"` in the mapping entry.

---

## When LLM judgement is invoked

Step 2 is mechanical wherever possible. LLM invocation is bounded to:

- `VALIDATE_OUTPUT` semantic-vs-executable classification when phrase-match heuristic is inconclusive
- `CONVERSE` realisation selection when element phrasing doesn't match the three rules
- `DETERMINISTIC` placement when length is borderline and call graph is unclear
- `EXTRACT` two-step eligibility in rare cases where schema analysis is ambiguous

Each invocation is scoped to a single element. Output goes into `intermediate/element_mapping_judgment_calls.json`.

---

## Output: `element_mapping.json`

```json
{
  "mapping_id": "map_001",
  "element_id": "elem_042",
  "target_file": "pipeline.py",
  "target_symbol": "run_pipeline",
  "primitive": "m.instruct",
  "primitive_details": {
    "format_schema": "TriageVerdict",
    "grounding_context_keys": ["ticket_text", "operating_rules"]
  },
  "final_target_file": "pipeline.py",
  "step_2_confidence": 0.9,
  "step_2_rationale": "DECIDE tag with clear enum output → m.instruct with format=DecisionSchema",
  "llm_judgement_required": false,
  "dialect_override_applied": null,
  "validation_kind": null
}
```

**Cross-checks before Step 2 declares done**:

- Count of mapping entries equals count of inventory entries (plus expansions for two-step and remediation)
- Every `NO_DECOMPOSE` element has a mapping entry with `primitive: "none"`
- No mapping entry has empty `target_file` or `target_symbol` (except `NO_DECOMPOSE`)
- Every `target_file` named is in the shape doc's always-emitted list or a conditional file whose trigger is predicted to fire
- Every `dialect_override_applied` non-null value references a real row in the detected runtime's dialect doc

Failure at any check is a generation-halt error. `.melleafy-partial/` retains the intermediate artifacts for debugging.
