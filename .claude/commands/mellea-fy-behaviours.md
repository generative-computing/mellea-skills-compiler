# Melleafy: Known Mellea Behaviours & Workarounds

**Version**: 4.3.0 | tested against mellea 0.4.2

Generated pipelines MUST include these workarounds. Re-test after upgrading mellea — some may be resolved in future releases. Step 7's `known-behaviours` lint mechanically checks for KB1, KB2, KB3, KB4, KB6, KB7, KB11. Step 7's `session-boundary` lint covers KB5. KB9 is advisory only — no lint sub-check.

> **Import path grounding**: All `mellea.*` import paths shown in this document were verified against `intermediate/mellea_api_ref.json` at generation time. If any path raises `ModuleNotFoundError` after a mellea upgrade, consult `mellea_api_ref.json:.modules` — it is the authoritative module index for the current installed version. Step 7's `import-soundness` lint will catch any drifted path in generated packages at validation time.

## Citation tiers

Every KB entry ends with a citation marker indicating how the claim was established. When upgrading mellea, re-verify entries marked `**Verified**:` or `**Status**: empirically observed` — these have no stable external anchor.

| Marker                                               | Meaning                                                                      |
| ---------------------------------------------------- | ---------------------------------------------------------------------------- |
| `**Ref**: <url>`                                     | Covered by official mellea docs. Verify by reading the linked page.          |
| `**Verified**: mellea X.Y.Z source — <file>:<lines>` | Established by reading mellea source. Version-pinned — re-verify on upgrade. |
| `**Status**: empirically observed`                   | Observed at runtime, no doc or source anchor. Treat as fragile.              |

---

## KB1: `m.instruct()` returns a `ComputedModelOutputThunk`, not a Pydantic model

`m.instruct(format=Model)` returns a `ComputedModelOutputThunk` — a lazy wrapper around the raw string output. It is **NOT** a Pydantic model. Accessing any field (`thunk.query_type`), calling any Pydantic method (`thunk.model_dump()`, `thunk.model_dump_json()`), or accessing `thunk.parsed_repr` raises `AttributeError` at runtime.

**MUST** parse the thunk before any field access. Add these two helpers to every generated `pipeline.py` and call them immediately after every `m.instruct(format=Model)` call:

```python
def _parse_instruct_result(thunk, model_class: type[BaseModel]):
    """Parse m.instruct(format=Model) result."""
    return model_class.model_validate_json(thunk.value)

def _safe_parse_with_fallback(thunk, model_class: type[BaseModel], **fallback_kwargs):
    """Parse with fallback — returns a default model on parse failure."""
    try:
        return model_class.model_validate_json(thunk.value)
    except Exception:
        return model_class(**fallback_kwargs)
```

**Correct pattern**:

```python
intent_thunk = m.instruct(
    "Classify this query.",
    format=IntentSchema,
    strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
)
intent = _safe_parse_with_fallback(intent_thunk, IntentSchema, query_type="out_of_scope", location="")
# intent is now a Pydantic object — safe to access intent.query_type
```

**Wrong patterns** (all raise `AttributeError` at runtime):

```python
thunk = m.instruct(..., format=IntentSchema)
thunk.query_type        # AttributeError
thunk.model_dump()      # AttributeError
thunk.parsed_repr       # AttributeError (deprecated attribute, returns the thunk itself)
```

Note: `@generative` slots handle parsing internally and return typed values directly — no helper needed when calling them.

**Lint check**: `known-behaviours` sub-check 3a. Detection: parse `pipeline.py` with `ast`; identify variables assigned from `m.instruct(...)` calls with a `format=` keyword; flag any attribute access or method call on those variables that is not wrapped in `_parse_instruct_result(`, `_safe_parse_with_fallback(`, or `.model_validate_json(`. Hard failure.
**Status**: empirically observed — re-verify on mellea upgrade.
**Added**: 2026-04-29 (restored from v0c116fa, scope broadened from `.parsed_repr` to all field access) | **Last-validated**: 2026-04-29

---

## KB2: JSON truncation on complex outputs

When the LLM generates JSON for a complex Pydantic schema with large `grounding_context`, it may hit `max_tokens` and produce truncated JSON. `model_validate_json()` raises `ValidationError: EOF while parsing`. Generated pipelines MUST use `_safe_parse_with_fallback` (KB1) for any `m.instruct(format=Model)` call where the schema has more than 4 fields or any `list[...]`-typed field, or use `RepairTemplateStrategy` to retry on malformed output.

**Lint check**: `known-behaviours` sub-check 3b. Detection: parse `pipeline.py` and `schemas.py` with `ast`; for each `m.instruct(format=Model)` call, look up the model's field count and list annotations in `schemas.py`; if the model qualifies as complex (>4 fields or a `list[...]` field), assert the call has a `strategy=` keyword or the result variable is passed to `_safe_parse_with_fallback`. Hard failure.
**Status**: empirically observed — re-verify on mellea upgrade.
**Added**: 2026-04-29 (restored from v0c116fa) | **Last-validated**: 2026-04-29

---

## KB3: `validation_fn` receives `Context`, not `str` (by design)

When passing a function directly to `validation_fn=`, the function receives a `Context` object, NOT a plain string. Calling `.lower()`, `.split()`, etc. directly on it fails with `AttributeError`.

**Pattern A — RECOMMENDED**: Use `simple_validate()` wrapper:

```python
from mellea.stdlib.requirements import simple_validate

req("Must mention security", validation_fn=simple_validate(
    lambda x: "security" in x.lower()  # x is a str here
))
```

**Pattern B — raw validator**: accept `Context` and result string explicitly:

```python
def my_validator(ctx: Context, result: str) -> ValidationResult:
    if "security" not in result.lower():
        return ValidationResult(result=False, reason="Missing security mention")
    return ValidationResult(result=True)
```

Generated pipelines should prefer Pattern A for all structural validators in `requirements.py`.

**Lint check**: `validator-soundness` sub-check A (correct `(ctx, result)` signature).
**Ref**: https://docs.mellea.ai/how-to/write-custom-verifiers
**Added**: pre-2026-04-28 | **Last-validated**: 2026-04-28 | **Fixture**: tests/promptfoo/kb_03.yaml

---

## KB4: Validators on `format=` calls receive raw JSON strings

When `m.instruct(format=Model)` is used with `requirements=`, the `simple_validate()` lambda receives the **serialized JSON text** (e.g., `{"query_type": "current", "location": "Dublin"}`), not the parsed Pydantic model.

**Anti-pattern checklist for `format=` validators**:

1. **Field-name collision**: checking `"fix" in x` when the schema has a `fix: str` field always passes.
2. **Length on whole string**: `len(x) > N` measures the entire JSON blob, not field content.
3. **Line-splitting JSON**: `x.split("\n")` is unreliable — JSON may be compact or pretty-printed.
4. **Substring matching for enum values**: `"approve" in x` also matches `"approve_with_suggestions"`.

**Correct pattern** — parse the JSON and check actual fields:

```python
import json as _json

def _validate_findings_have_locations(output: str) -> bool:
    try:
        data = _json.loads(output)
        findings = data.get("findings", [])
        if not findings:
            return True  # no findings = nothing to validate
        return all(f.get("file_path", "").strip() for f in findings)
    except (_json.JSONDecodeError, AttributeError):
        return False

finding_location_req = req(
    "Each finding must cite a specific file path",
    validation_fn=simple_validate(_validate_findings_have_locations)
)
```

**Alternative** — validate after parsing in pipeline.py (preferred for complex checks):

```python
report = _parse_instruct_result(report_thunk, SecurityReport)
empty_fixes = [f for f in report.findings if not f.fix.strip()]
```

**Lint check**: `validator-soundness` sub-check B (non-vacuous lambda body).
**Ref**: https://docs.mellea.ai/how-to/write-custom-verifiers
**Added**: pre-2026-04-28 | **Last-validated**: 2026-04-28 | **Fixture**: tests/promptfoo/kb_04.yaml

---

## KB5: Schema priming

After generating N objects with schema A in the same session, the LLM may be unable to switch to schema B. **MUST use separate `start_session()` calls** for each distinct BaseModel format type.

**Self-check rules**:

1. **One BaseModel type per session** — if the session uses `format=ModelA`, no other BaseModel type appears in the same session.
2. `list[ModelA]` and `ModelA` are the same type for priming purposes.
3. Multiple `@generative` slots returning the same type are safe in one session.
4. Note: `@generative` slots generate their own `<FunctionName>Response` model internally. Each distinct slot's response model is a distinct schema for priming purposes.

```python
# WRONG — 3 different schemas in one session
with start_session(BACKEND, MODEL_ID) as m:
    vulns = extract_vulnerabilities(m, ...)       # list[Vulnerability]
    gaps = extract_compliance_gaps(m, ...)         # list[ComplianceGap]
    risks = extract_iam_risks(m, ...)             # list[IAMRisk]

# RIGHT — one schema per session
with start_session(BACKEND, MODEL_ID) as m1:
    vulns = extract_vulnerabilities(m1, ...)      # list[Vulnerability]

with start_session(BACKEND, MODEL_ID) as m2:
    gaps = extract_compliance_gaps(m2, ...)

with start_session(BACKEND, MODEL_ID) as m3:
    risks = extract_iam_risks(m3, ...)

# @generative slots sharing the same response model type can share a session
severity = classify_severity(m1, ...)             # ClassifySeverityResponse — same session OK if no other schema used
```

**Lint check**: `session-boundary` lint (dedicated Tier 2 lint).
**Ref**: https://docs.mellea.ai/concepts/context-and-sessions
**Added**: pre-2026-04-28 | **Last-validated**: 2026-04-28 | **Fixture**: tests/promptfoo/kb_05.yaml

---

## KB6: Reserved parameter names in `@generative` slots

`@generative` slots enforce a disallowed-parameter-names list. The authoritative list lives in `intermediate/mellea_api_ref.json:.forbidden_param_names` (populated at Step 2.5e). The full static fallback list for mellea 0.4.2:

- **`m`** — the session object is injected by the decorator
- **`context`** — collides with Mellea internals
- **`backend`**, **`model_options`**, **`strategy`** — reserved runtime kwargs
- **`precondition_requirements`**, **`requirements`** — reserved IVR kwargs
- **`f_args`**, **`f_kwargs`** — reserved decorator internals

Declaring any of these raises `ValueError: cannot create a generative slot with disallowed parameter names`. Use domain-specific names instead — for any forbidden name, choose a domain-specific alternative (e.g. `surrounding_context`, `finding_context`, `source_text`, `doc_context` in place of `context`; `run_args`, `run_kwargs` in place of `f_args`, `f_kwargs`).

**Correct definition pattern** — domain-specific parameters only; body is `...`:

```python
@generative
def classify_check_mode(input_text: str, mode_hint: str = "auto") -> str:
    """Set `result` to one of: prompt, url, command, sanitize, audit."""
    ...
```

**Correct calling pattern** — `m` passed as first positional argument at call time, NOT declared:

```python
with start_session(BACKEND, MODEL_ID) as m:
    result = classify_check_mode(m, input_text=text)
```

Use `surrounding_context`, `finding_context`, `source_text`, `doc_context`, etc. instead of `context`.

**Lint check**: `known-behaviours` sub-check 3f.
**Ref**: https://docs.mellea.ai/concepts/generative-functions
**Added**: 2026-04-27 | **Last-validated**: 2026-04-28 | **Fixture**: tests/promptfoo/kb_06.yaml

---

## KB7: Use `ModelOption.SYSTEM_PROMPT` for persona text; `prefix=` is an output prefix

`ModelOption.SYSTEM_PROMPT` is the **recommended** way to attach persona text to `m.instruct()` calls. Mellea handles per-backend serialization of the system prompt automatically — this is specifically why the docs recommend it over constructing system-role messages manually.

`prefix=` in `m.instruct()` is **not** a system prompt. It is "a prefix prepended before the model's generation" — an output-side prefix. Do not use `prefix=` to set persona text.

```python
# CORRECT — attach persona via SYSTEM_PROMPT
from mellea.backends.model_options import ModelOption

result = m.instruct(
    "Analyse this security report.",
    model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
    grounding_context={"report": report_text},
    format=SecurityReport,
)

# WRONG — prefix= is an output prefix, not a system prompt
result = m.instruct(
    "Analyse this security report.",
    prefix=PREFIX_TEXT,
    grounding_context={"report": report_text},
    format=SecurityReport,
)
```

**Lint check**: `known-behaviours` sub-check 3g. Detects `prefix=<config_constant>` being used as a persona mechanism. Note: `prefix=` for structured output generation patterns is permitted.
**Ref**: https://docs.mellea.ai/how-to/configure-model-options
**Added**: pre-2026-04-28 | **Last-validated**: 2026-04-28 | **Fixture**: tests/promptfoo/kb_07.yaml

---

## KB9: `return_sampling_results` for debugging

Pass `return_sampling_results=True` to `m.instruct()` to get a `SamplingResult` containing all sampling attempts and their validation outcomes. Useful for diagnosing why a requirement keeps failing in the IVR loop. **Not for production pipelines** — adds overhead and changes the return type.

**Advisory only — no lint sub-check.** This entry documents a debugging pattern; the `known-behaviours` lint does not enforce it. Set `return_sampling_results=False` (or omit it) in all generated production pipelines.
**Ref**: https://docs.mellea.ai/concepts/instruct-validate-repair
**Added**: pre-2026-04-28 | **Last-validated**: 2026-04-28 | **Fixture**: none

---

## Negative constraints: the Purple Elephant Effect

For negative constraints (things the output should NOT contain), use `check_only=True` to avoid telling the LLM "don't do X" in the prompt (which makes it think about X):

```python
from mellea.stdlib.requirements import check

# check() is shorthand for Requirement(description=..., check_only=True)
no_vague_language = check("Output must not contain vague phrases like 'in general' or 'possibly'")
```

**Ref**: https://docs.mellea.ai/concepts/requirements-system
**Added**: pre-2026-04-28 | **Last-validated**: 2026-04-28 | **Fixture**: none

---

## KB11: `Optional` fields in P2 extraction schemas need explicit extraction guidance

When a `m.instruct(format=IntentSchema)` call in a P2 pipeline includes `Optional` fields that correspond to values the user may have already stated in their input (order numbers, dates, ticket IDs, quantities), the LLM defaults to its conversational reflex: asking the user to confirm rather than extracting the value from the text already given.

A `Field(description=...)` that merely names the field (e.g. `"Order number, if applicable."`) is insufficient — it describes what the field holds but does not instruct the model to extract it. The model is left free to ask instead.

**Anti-pattern**:

```python
class BookingIntent(BaseModel):
    destination: str
    departure_date: Optional[str] = Field(default=None, description="The departure date.")
```

**Correct pattern** — extraction instruction with three elements: name the source, specify the action, prohibit re-asking:

```python
from typing import Optional
from pydantic import BaseModel, Field

class BookingIntent(BaseModel):
    destination: str
    departure_date: Optional[str] = Field(
        default=None,
        description=(
            "Extract the departure date if the user has stated it in their message; "
            "otherwise null. Do not ask for it."
        ),
    )
    return_date: Optional[str] = Field(
        default=None,
        description="Return date if the user mentioned one; do not ask for it.",
    )
```

The extraction instruction must contain at least one of: `"extract"`, `"do not ask"`, or `"if the"` (case-insensitive match). A description that lacks all three will be detected as a lint failure.

This applies to any `Optional` field in a P2 `m.instruct` schema where the value is user-supplied. Fields synthesised from context (e.g., `reply_to` derived from the sender address in the surrounding envelope) do not require extraction guidance.

**Lint check**: `known-behaviours` sub-check 3m. Detection: parse `schemas.py` with `ast`; find `BaseModel` subclasses named `*Schema`, `*Intent`, or referenced as `format=` in a `m.instruct` call; for each `Optional`-annotated field, assert `Field(description=...)` is present and contains at least one of `"extract"`, `"do not ask"`, `"if the"`.
**Ref**: https://docs.mellea.ai/how-to/enforce-structured-output
**Added**: 2026-04-28 | **Last-validated**: 2026-04-28 | **Fixture**: tests/promptfoo/kb_11.yaml
