# Melleafy Steps 3 + 5: Skeleton Emission and Body Generation

**Version**: 4.3.0 (2026-04-28) | **Prereq**: `dependency_plan.json` (Step 2.5 complete) | **Produces**: Populated Python package

> **Output path rule** (Rule OUT-3): All `.py` files (`pipeline.py`, `config.py`, `schemas.py`, `main.py`, etc.) are written inside `<package_name>/`. `pyproject.toml` is the only file written at the skill root (NOT inside `<package_name>/`). See `mellea-fy.md` §Output directory layout for the full tree.

Step 3 emits skeleton files (imports, signatures, docstring placeholders) from the element mapping and dependency plan. Step 5 invokes the LLM to fill in every code body. Read `/mellea-fy-behaviours` before generating any code — the Known Behaviours mitigations must be baked into every generated file.

---

## Step 3: File set and skeleton emission

### File set determined by mapping + dependency plan

| File                   | When generated                                                                           |
| ---------------------- | ---------------------------------------------------------------------------------------- |
| `pipeline.py`          | Always                                                                                   |
| `schemas.py`           | Always (at minimum contains `Final[str]` placeholder if no schemas found)                |
| `config.py`            | Always (persona text, model ID, loop budgets from `dependency_plan.json:bundle` entries) |
| `requirements.py`      | When any `VALIDATE_OUTPUT` elements exist                                                |
| `slots.py`             | When any `EXTRACT` or `CLASSIFY` elements map to `@generative`                           |
| `tools.py`             | When any C6 element has disposition `real_impl`                                          |
| `constrained_slots.py` | When any C6 element has disposition `stub` or `delegate_to_runtime`                      |
| `mobjects.py`          | When any `TRANSFORM` or `QUERY` elements exist                                           |
| `loader.py`            | When any C3 element has disposition `load_from_disk`                                     |
| `main.py`              | Always (CLI entry point)                                                                 |
| `pyproject.toml`       | Always                                                                                   |
| `fixtures/`            | Always (5–8 fixtures, generated in Step 4)                                               |
| `SETUP.md`             | When any C4, C5, C9, non-bundled C6, C7, non-default C8, or host-needing modality        |
| `README.md`            | Always                                                                                   |
| `melleafy.json`        | Always (skeleton in Step 3; finalised in Step 6)                                         |
| `dependencies.yaml`    | When any C6/C7/C8 entry is non-bundle                                                    |

### Modality-specific entry-point shape (R21)

The `run_pipeline` function signature and `main.py` shape vary by modality from `classification.json`:

| Modality                 | Entry point shape                                                           |
| ------------------------ | --------------------------------------------------------------------------- |
| `synchronous_oneshot`    | `run_pipeline(*params) -> OutputSchema` — simple function call              |
| `streaming`              | `run_pipeline(*params) -> Iterator[str]` — generator yielding tokens        |
| `conversational_session` | `run_pipeline(session_id: str, *params) -> OutputSchema` — session-keyed    |
| `review_gated`           | `run_pipeline(*params) -> ReviewRequest` — returns for human approval       |
| `scheduled`              | `run_pipeline() -> None` — no user-provided params; data fetched internally |
| `event_triggered`        | `run_pipeline(event: dict) -> None` — event payload as input                |
| `heartbeat`              | `run_pipeline(state: dict) -> dict` — stateful loop, returns updated state  |
| `realtime_media`         | `run_pipeline(stream: Iterator) -> Iterator` — streaming I/O                |

**Rule 3-1 — `run_pipeline` parameter type annotations**: Every parameter in the generated `run_pipeline` function signature MUST have an explicit Python type annotation. If the source spec declares a type for a parameter (e.g. from a typed function signature, a schema field, or an explicit type note in the spec text), use that type. If the source spec is untyped or ambiguous, default to `str`. Do not emit bare parameter names (e.g. `company_domain`) — emit `company_domain: str` instead. This applies to both required and optional (defaulted) parameters.

### Step 3a-pre: Bundled assets are already mirrored (Rule OUT-6)

Companion directories from the skill root (`scripts/`, `references/`, `assets/`) are mirrored into `<package_name>/` **deterministically by the compile pipeline**, _before_ mellea-fy runs. The model does not perform the copy — it is plumbing handled by `mellea_skills_compiler.compile.mellea_skills._mirror_companion_dirs`. By the time Step 3 begins, any companion directory that existed at the skill root is already present at `<package_name>/<dir>/` and can be referenced directly.

The model's responsibility is **path-resolution discipline**: any code emitted in Step 5 that loads or invokes a bundled asset MUST resolve its path package-relatively via `Path(__file__).parent / "<dir>/<file>"`, **not** via a user-supplied `repo_root` argument or the process working directory. This invariant is what makes the generated package self-contained — a `pip install`-ed package, or one invoked from any cwd, finds its bundled assets via Python's own module-location machinery.

Step 7's `bundled-asset-path-resolution` lint catches violations at validation time. The `pyproject.toml` template (below) declares these directories under `[tool.setuptools.package-data]` so the mirrored copies ship with the installed wheel.

### Skeleton contents per file

**config.py**: C1 and C2 bundle entries become `Final[str]` constants under `# === C1: Identity ===` and `# === C2: Operating Rules ===` section headers. C8 bundle entries (model ID, backend) also here. Every constant gets a `# PROVENANCE: <source_file>:<source_lines>` comment. **In Step 5, the model emits JSON conforming to `.claude/schemas/config_emission.schema.json` — not Python source. The writer at `.claude/melleafy/writers/config_writer.py` renders the file.**

> **C8 backend rule**: `BACKEND` and `MODEL_ID` values are injected via the system prompt by the compile pipeline (sourced from `.claude/data/runtime_defaults.json`, with optional `--backend` / `--model-id` CLI overrides). Emit them in `config.py` exactly as instructed in the system prompt; do not invent alternatives. The Step 7 `runtime-defaults-bound` lint enforces this — divergence from the injected values is a hard failure.

_JSON the model emits:_

```json
{
  "constants": [
    {
      "name": "PREFIX_TEXT",
      "value": "<persona text from SOUL.md>",
      "type": "str",
      "category": "C1",
      "provenance": { "source_file": "SOUL.md", "source_lines": "1-45" }
    },
    {
      "name": "BACKEND",
      "value": "ollama",
      "type": "str",
      "category": "C8"
    },
    {
      "name": "MODEL_ID",
      "value": "granite3.3:8b",
      "type": "str",
      "category": "C8"
    },
    {
      "name": "LOOP_BUDGET",
      "value": 3,
      "type": "int"
    }
  ]
}
```

_Python source the writer renders from that JSON:_

```python
from typing import Final

# === C1: Identity & Behavioral Context ===
PREFIX_TEXT: Final[str] = """You are an AI assistant.\nYou help users with research tasks."""
# PROVENANCE: SOUL.md:1-45

# === C8: Runtime Environment ===
BACKEND: Final[str] = 'ollama'
MODEL_ID: Final[str] = 'granite3.3:8b'

LOOP_BUDGET: Final[int] = 3
```

**schemas.py**: One Pydantic `BaseModel` per `SCHEMA` element. Field descriptions pulled from the spec's output format description. For two-step pattern: include both the simplified raw schema and the full schema.

**requirements.py**: One `Requirement` object per `VALIDATE_OUTPUT` element. Group by spec section. Structural checks use `simple_validate()`; semantic checks use bare `Requirement(description=...)`. Include `check_only=True` for negative constraints.

**slots.py**: One `@generative` function per `EXTRACT`/`CLASSIFY` element. Return types:

- Classifications: `-> Literal[...]` — Ollama supports constrained decoding, so always use the typed return.
- Simple list extractions: `-> str` with "Set `result` to a comma-separated string of..." docstring — never `-> list[str]`. Split in `pipeline.py`: `[p.strip() for p in raw.split(",") if p.strip()] if raw.strip() else []`
- Structured extractions: Pydantic `BaseModel` (model fields provide the JSON structure; no bare-output risk)

Docstrings on all `@generative` slots MUST reference `result` explicitly (e.g. "Set `result` to..."). Never use "Reply with exactly one word", "Output only", "Return only". Simple schemas (≤4 fields, no `Literal` constraints, no nested models) go here directly. Complex schemas: slot extracts simplified version, Step 5 generates the `m.instruct` enrichment step inline in `pipeline.py`.

**`@generative` definition convention**: The decorator forbids `m` as a parameter name — passing it in the definition raises `ValueError` at import time. Function body must be `...`. `m` is passed as the first positional argument only at call time in `pipeline.py`.

```python
# CORRECT — no m in definition, body is ...
@generative
def extract_sentiment(text: str) -> str:
    """Set `result` to one of: positive, negative, neutral."""
    ...

# WRONG — raises ValueError: cannot create a generative slot with disallowed parameter names: ['m']
@generative
def extract_sentiment(m, text: str) -> str:
    ...
```

Calling convention in `pipeline.py` (unchanged — `m` passed as first positional arg):

```python
with start_session(BACKEND, MODEL_ID) as m:
    sentiment = extract_sentiment(m, text=user_input)
```

**tools.py** (when any C6 has disposition `real_impl`):

- Domain/command allowlist — hard-coded `ALLOWED_DOMAINS` or `ALLOWED_COMMANDS`
- Error handling with timeouts and HTTP error codes
- Auth tokens read from environment variables
- `build_api_params()` or equivalent mapping spec-level names to API parameter names
- **Bundled-script invocation (Rule OUT-6)**: when the implementation invokes a script mirrored from the skill root (e.g. `scripts/bash/check-prerequisites.sh`), resolve the script path package-relatively. Use `Path(__file__).parent / "scripts/<...>"` — never `Path(repo_root) / "scripts/<...>"` and never rely on the process working directory. Example: `script_path = Path(__file__).parent / "scripts" / "bash" / "check-prerequisites.sh"`. The mirror is established by Step 3a-pre, so the path is guaranteed to resolve at runtime regardless of where the package is invoked from.
- Example structure:

```python
ALLOWED_DOMAINS = ["api.example.com"]
HTTP_TIMEOUT = 10

def http_get(url: str) -> str:
    """Fetch content from a URL. Validates against domain allowlist."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_DOMAINS:
        raise ValueError(f"Domain '{parsed.hostname}' not in allowlist")
    # ... execute with timeout and error handling
```

**Multi-mode subprocess wrappers**: if a shell script exposes multiple modes (e.g. `--check-prompt`, `--check-url`, `--check-command`), inspect how each mode receives its input before generating the wrapper:

- Modes that read from stdin (e.g. `input=$(cat)` in the script body) → call `subprocess.run(..., input=target, capture_output=True, text=True)`. Do NOT append `target` to the command list.
- Modes that take a positional argument → append `target` to the command list as before.

Apply this per-mode distinction at the call site in `pipeline.py` too: every branch calling the wrapper must forward the input correctly for that mode. A branch that omits `target=` for a stdin-consuming mode is a silent false-negative bug.

**constrained_slots.py** (when any C6 has disposition `stub` or `delegate_to_runtime`):

- Implements `ConstrainedGenerativeSlot`, `constrained` decorator, `filter_actions` locally
- Implements `ReactTool` / `ReactToolbox` locally
- Provides stub tool functions raising `NotImplementedError` with implementation instructions
- Wraps dependent slots from `slots.py` with `constrained()` — does NOT duplicate them

**pipeline.py** (standard structure):

- One function per `ORCHESTRATE` workflow
- `with start_session(BACKEND, MODEL_ID) as m:` context manager
- Calls slots, requirements, and mobjects from other files
- `DECIDE` logic: Python `if/elif/else` wrapping Mellea calls
- MUST convert all non-string `grounding_context` values to `str()`
- MUST use `format=PydanticModel` for every `m.instruct()` that produces structured output
- MUST parse the thunk after every `m.instruct(format=Model)` before accessing any field or calling any Pydantic method. `m.instruct()` returns a `ComputedModelOutputThunk` — NOT a Pydantic model. Direct field access (`thunk.field_name`) or `.model_dump()` raises `AttributeError`. Always include `_parse_instruct_result` and `_safe_parse_with_fallback` helpers in `pipeline.py` and call them immediately after every `m.instruct(format=Model)` call:

  ```python
  def _parse_instruct_result(thunk, model_class):
      return model_class.model_validate_json(thunk.value)

  def _safe_parse_with_fallback(thunk, model_class, **fallback_kwargs):
      try:
          return model_class.model_validate_json(thunk.value)
      except Exception:
          return model_class(**fallback_kwargs)
  ```

- MUST use `model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT}` to establish persona on `m.instruct()` calls (KB7 — `prefix=` is an output prefix, not a system prompt)
- SHOULD use `RepairTemplateStrategy(loop_budget=LOOP_BUDGET)` when requirements include structural `validation_fn`

**Canonical Mellea import paths** — use these exact paths; do not guess or infer alternatives:

```python
from mellea import start_session, generative
from mellea.stdlib.sampling import RepairTemplateStrategy
from mellea.stdlib.requirements import req, check, simple_validate
```

> **Rule 5-2 — Import path grounding**. **Fallback only — primary enforcement is via invariant 3 above.** Before writing any `from mellea.X import Y` statement, verify that the module path `mellea.X` exists in `intermediate/mellea_api_ref.json:.modules`. Any path not present there is invalid and must not be generated.
>
> Common error pattern: generating shortened paths that do not exist (e.g. `mellea.model_options`) when the symbol lives deeper in the hierarchy (e.g. `mellea.backends.model_options`). The `.modules` key is the ground truth — consult it, not training knowledge, for import paths.
>
> The KB entries in `/mellea-fy-behaviours` already show the canonical import for each KB-relevant symbol. For symbols not covered by a KB entry, derive the import path from `mellea_api_ref.json:.modules`.

> **Rule 5-4 — Stdlib function signature grounding**. **Fallback only — primary enforcement is via invariant 3 above.** Before emitting any call to a `mellea.stdlib.*` function, verify the function's argument count and keyword parameter names against the known-signature list below. Do not infer signatures by analogy to similar functions in other libraries (e.g. do not assume `(fn, error_message)` forms that exist in `pytest` or `pydantic` but not in Mellea).
>
> **Known signatures** (static fallback when `mellea_api_ref.json` is absent or `grounding_unavailable: true`):
>
> | Function          | Module                       | Signature                                                                             |
> | ----------------- | ---------------------------- | ------------------------------------------------------------------------------------- |
> | `simple_validate` | `mellea.stdlib.requirements` | `simple_validate(fn)` — **1 positional argument only**                                |
> | `req`             | `mellea.stdlib.requirements` | `req(description, *, validation_fn=None)` — 1 required positional, 1 optional keyword |
> | `check`           | `mellea.stdlib.requirements` | `check(requirement, output)` — 2 positional arguments                                 |
>
> **Common error pattern**: `simple_validate(_check_fn, "error message")` — the two-argument form is invalid. `simple_validate` wraps the validator function; the error message, if needed, is handled inside the validator function itself. The correct call is `simple_validate(_check_fn)`.
>
> For any `mellea.stdlib.*` function not in the table above, derive its signature from `intermediate/mellea_api_ref.json:.modules.<module>.<symbol>.signature` before emitting the call.

**Pipeline structure by tool involvement**:

_P0 — No tools_: pure `pipeline.py` calling `slots.py` and `requirements.py`.

_P4 — Tools provide input_: `main.py` gathers pre-pipeline data, passes as parameters to `run_pipeline()`.

_P2 — Pipeline calls tools (deterministic)_:

1. LLM classifies intent: `intent_thunk = m.instruct(format=IntentSchema, ...)` — result is a `ComputedModelOutputThunk`, NOT a Pydantic object; MUST parse immediately: `intent = _safe_parse_with_fallback(intent_thunk, IntentSchema, query_type="out_of_scope", ...)`
2. Scope check: `if intent.query_type == "out_of_scope": return` (deterministic, no tool call — `intent` here is the parsed Pydantic object, not the thunk)
3. Deterministic construction + tool execution: `TEMPLATES[intent.query_type].format(...)` → `tool_fn(url_or_params)`
4. LLM formats response (optional): `response_thunk = m.instruct(format=ResponseSchema, ...)` → `response = _safe_parse_with_fallback(response_thunk, ResponseSchema, ...)` with raw tool output as grounding
   MUST use two separate `start_session()` calls for steps 1 and 4 (schema priming).

_P3 — Pipeline calls tools (LLM-directed)_:

- Uses `m.react()` with a toolbox, or `m.instruct()` with `ModelOption.TOOLS`
- Mellea's `TOOL_PRE/POST_INVOKE` hooks fire automatically for governance

**pyproject.toml** (always):

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mellea[hooks]>=0.4.2",
    "pydantic>=2.0",
]

[project.scripts]
<package-name> = "<package_module>.main:main"

# Rule OUT-6 — declare mirrored companion directories as package data so
# bundled scripts/references/assets ship with the installed wheel. Include
# only the directories that exist after Step 3a-pre's mirror.
[tool.setuptools.package-data]
"<package_module>" = ["scripts/**/*", "references/**/*", "assets/**/*"]
```

Note: the `openai-agents` package is NOT added to dependencies for Agents SDK source specs — the generated package uses Mellea, not the Agents SDK.

---

## Step 5: Code body generation

Step 5 fills every skeleton placeholder with real code. For `config.py`, the model emits JSON and the writer renders Python source (invariant 1).

### Step 5 invariants

Read once; apply throughout all file generation.

**1. `config.py` output is JSON, not Python source.** Emit a JSON object conforming to `.claude/schemas/config_emission.schema.json`. The deterministic writer at `.claude/melleafy/writers/config_writer.py` renders the file — do not write Python source for `config.py` directly.

**2. All other files output Python source.** Generate one file per LLM invocation (Rule 5-3). Wait for each file's body before starting the next.

**3. Before generating any file, consult `intermediate/mellea_api_ref.json`:**

- `.modules` — valid `mellea.*` paths for imports
- `.modules.<module>.<symbol>.signature` — exact signature for any `mellea.stdlib.*` symbol (nested under `.modules`)
- `.forbidden_param_names` — disallowed `@generative` parameter names
- `.compatibility` — Mellea-version-gated workarounds to inject

If `grounding_unavailable: true`, fall back to the KB patterns in `/mellea-fy-behaviours` and the static signature tables in Rules 5-2 and 5-4.

**4. Use canonical fixture pairs from `<package_name>/fixtures/` as concrete examples** (already produced by Step 4) for the file being generated. Use these as the reference for correct Mellea usage, not training memory.

**5. Behavioral guidance is in `/mellea-fy-behaviours`.** Read it once before generating any file body.

**6. Step 7 lint failures, not these instructions, are the source of truth for correctness.** Generate per spec; let the repair loop correct lint failures rather than anticipating every possible check.

> **Rule 5-3 — File-level batching**: Generate all code bodies for a given output file in a single LLM invocation. Do not make one invocation per element. For each file in the skeleton (e.g. `pipeline.py`, `config.py`, `slots.py`, `tools.py`), issue one invocation that generates the complete file contents, guided by all relevant element mapping entries for that file. KB5 schema priming concerns do not apply to melleafy compilation calls (KB5 governs Mellea pipeline sessions inside compiled skills, not the compilation process itself).

Each invocation uses a prompt template with all element-specific mapping entries for that file as variable substitution.

### KB defenses baked into every invocation

Before generating any body, include in the context:

- The specific Known Behaviours relevant to the primitive being generated
- The element's source text and mapping rationale
- The dependency plan entries affecting this element

### Per-file body generation order

Generate bodies in this order (dependency order):

1. `schemas.py` — Pydantic models first (all other files reference them)
2. `config.py` — emit JSON conforming to `.claude/schemas/config_emission.schema.json`; the writer at `.claude/melleafy/writers/config_writer.py` renders the Python source (slots.py references `LOOP_BUDGET`, `PREFIX_TEXT`, etc.)
3. `requirements.py` — requirement functions (pipeline.py references them)
4. `slots.py` — `@generative` slot bodies
5. `tools.py` / `constrained_slots.py` — tool implementations
6. `mobjects.py` — mified object definitions
7. `loader.py` — file loader functions
8. `pipeline.py` — the orchestrating pipeline (references all above)
9. `main.py` — CLI entry point

### Remediation loop bodies (when REMEDIATE elements exist)

```python
# In pipeline.py — bounded remediation loop
MAX_REMEDIATION_ITERATIONS: Final[int] = 3  # in config.py

patched_code = original_code
remediation_count = 0
verdict = initial_verdict

while not verdict.passed and remediation_count < MAX_REMEDIATION_ITERATIONS:
    # Modification step: generate a fix
    with start_session(BACKEND, MODEL_ID) as m_fix:
        fix = m_fix.instruct(
            "Generate a minimal patch to address the identified issue.",
            grounding_context={
                "current_code": patched_code,
                "verdict": str(verdict.model_dump()),
            },
            format=CodeFix,
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
        )
        fix_obj = _parse_instruct_result(fix, CodeFix)

    patched_code = fix_obj.patched_code
    remediation_count += 1

    # Re-evaluation step
    with start_session(BACKEND, MODEL_ID) as m_eval:
        verdict = _parse_instruct_result(
            m_eval.instruct("Re-evaluate...", grounding_context={"code": patched_code}, format=Verdict),
            Verdict
        )
```

### Schema field access rule

After writing `pipeline.py` and `tools.py`, cross-reference every `model.field_name` access against the model's field definitions in `schemas.py`. Accessing a field that doesn't exist raises `AttributeError` at runtime. Correct field access patterns are shown in the fixture examples injected via the grounding context — use those as the reference for how generated code should access schema fields.

### Sequential extraction rule

When 3+ independent slots read the same input, call them sequentially on a single session — do NOT use `asyncio.gather()` with shared sessions (concurrent session sharing is unsafe in Mellea):

```python
with start_session(BACKEND, MODEL_ID) as m:
    # Same BaseModel return type — safe in one session
    primary_findings = extract_primary_findings(m, code_text=code)
    secondary_findings = extract_secondary_findings(m, code_text=code)
    config_issues = extract_config_issues(m, code_text=code)
```

### Two-step pattern in pipeline.py bodies

When Step 2 mapped an element to the two-step pattern:

```python
# Step 1: @generative extracts simplified data (already in slots.py)
raw_paths = extract_raw_attack_paths(m, code_text=code, threat_summary=summary)

# Step 2: m.instruct() structures into full schema with repair strategy
if raw_paths:
    paths_thunk = m.instruct(
        "Enrich these attack paths with risk ratings, impact, and likelihood assessments.",
        model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
        grounding_context={
            "raw_attack_paths": str([p.model_dump() for p in raw_paths]),
            "code_text": code,
        },
        format=AttackPathList,
        strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
    )
    attack_paths = _safe_parse_with_fallback(paths_thunk, AttackPathList, paths=[]).paths
```

### CONVERSE realisation bodies

For realisation (2) — pipeline parameter:

```python
def run_pipeline(
    user_query: str,                    # from CONVERSE element
    reference_context: str = "",        # from TOOL_INPUT or loader
) -> OutputSchema:
    ...
```

For realisation (3) — stub:

```python
def _get_user_approval(draft: str) -> str:
    """Interactive approval step — requires host adapter. See SETUP.md §7."""
    raise NotImplementedError(
        "This step requires a host adapter for interactive user input. "
        "Implement this function or provide the approved draft as a parameter."
    )
```

### `melleafy.json` skeleton (Step 3, finalised in Step 6)

```json
{
  "format_version": "1.0",
  "manifest_version": "1.1.0",
  "package_name": "<package_name>",
  "generated_at": "<ISO timestamp>",
  "melleafy_version": "4.0.0",
  "source_runtime": "<from classification.json>",
  "modality": "<from classification.json>",
  "archetype": "<from classification.json>",
  "categories_resolved": "<populated in Step 6>",
  "entry_signature": "<populated in Step 6>",
  "pipeline_parameters": "<populated in Step 6>",
  "declared_env_vars": []
}
```

---

## Cross-checks before Step 5 declares done

- `intermediate/mellea_api_ref.json` was consulted before code body generation (or `grounding_unavailable: true` was noted and KB fallback used)
- Fixture pair examples from `<package_name>/fixtures/` (Step 4) were used as grounding context for each generated file (invariant 4)

---

## Step 5 repair mode

Invoked by the top-level repair loop (see `mellea-fy.md`) after a Step 7 Tier 1 or structural Tier 2 failure. Distinct from a normal Step 5 invocation in three ways:

**Scope**: read `intermediate/step_7_report.json`. Generate only the files listed under failing lint entries. Pass all files with no failures through unchanged.

**Additional context per failing file**: inject the exact lint failure entries as a structured block before the generation context:

```
LINT FAILURES IN <filename> (repair round <N>):
  [<lint_id>] line <L> col <C>: <message>
```

**Cap**: repair mode may be invoked at most twice (`repair_round ∈ {1, 2}`). If Step 7 still fails after round 2, do not generate further — return control to the top-level orchestrator, which halts and preserves `.melleafy-partial/`.
