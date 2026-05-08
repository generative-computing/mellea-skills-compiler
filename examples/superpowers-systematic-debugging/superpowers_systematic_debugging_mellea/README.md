# Superpowers: Systematic Debugging

A four-phase debugging investigation pipeline built with [Mellea](https://docs.mellea.ai/). Guides structured root-cause investigation through error analysis, pattern recognition, hypothesis testing, and implementation planning. Enforces the core principle: **NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST**.

## What it does

The pipeline accepts a bug description and optional supporting context (error text, recent changes, code snippets, working examples), then runs four sequential investigation phases:

1. **Phase 1 — Root Cause Investigation**: Parses error messages, assesses reproducibility, summarises recent changes, and traces data flow backward through the call stack to identify the origin of the bad value.
2. **Phase 2 — Pattern Analysis**: Compares working and broken code to identify key structural and dependency differences.
3. **Phase 3 — Hypothesis and Testing**: Forms a single, specific hypothesis with evidence basis and testable approach, then evaluates whether it holds.
4. **Phase 4 — Implementation**: Produces a fix plan with a failing test description, targeted single-change fix, affected files, and verification steps. Detects when repeated fix attempts signal an architectural problem requiring team discussion.

Each phase gates entry to the next. The pipeline returns a structured `DebuggingReport` combining all phase outputs with a summary and next steps.

## Quick start

```bash
pip install -e .
```

### CLI usage

```bash
# Minimal — issue description only
superpowers-systematic-debugging "Function raises TypeError at line 47 when age is None"

# With error text and code context
superpowers-systematic-debugging "All auth tests fail after session middleware refactor" \
  --error-text "FAILED test_auth.py::test_login_valid_credentials - AssertionError: assert 401 == 200" \
  --recent-changes "Replaced cookie sessions with JWT tokens" \
  --code-context "def login(request): token = generate_jwt(user); return JsonResponse({'token': token})" \
  --output json
```

### Python API

```python
from superpowers_systematic_debugging_mellea import run_pipeline

report = run_pipeline(
    issue_description="All auth tests fail after session middleware refactor",
    error_text="FAILED test_auth.py::test_login_valid_credentials - assert 401 == 200",
    recent_changes="Replaced cookie sessions with JWT tokens",
    code_context="...",
    working_examples_text="...",
    fix_attempts_count=0,
)

print(report.summary)
if report.root_cause_evidence:
    print(f"Root cause: {report.root_cause_evidence.root_source}")
if report.fix_plan:
    print(f"Fix: {report.fix_plan.fix_description}")
if report.architectural_issue_detected:
    print("STOP — architectural issue detected. Discuss with your team.")
```

## Parameters

| Parameter               | Type  | Required | Description                                                                        |
| ----------------------- | ----- | -------- | ---------------------------------------------------------------------------------- |
| `issue_description`     | `str` | Yes      | Description of the bug, test failure, or unexpected behavior                       |
| `error_text`            | `str` | No       | Error messages, stack traces, or log output                                        |
| `recent_changes`        | `str` | No       | Recent code changes (git diff, commit log, dependency updates)                     |
| `code_context`          | `str` | No       | Relevant code snippets for data flow tracing                                       |
| `working_examples_text` | `str` | No       | Similar working code to compare against                                            |
| `fix_attempts_count`    | `int` | No       | Number of fix attempts already made (default: 0; ≥3 triggers architectural review) |

## Output: `DebuggingReport`

```python
class DebuggingReport(BaseModel):
    phase1_complete: bool
    error_analysis: Optional[ErrorAnalysis]        # error type, message, indicators
    reproduction_status: Optional[ReproductionResult]  # reproducibility + steps
    root_cause_evidence: Optional[RootCauseEvidence]   # origin, trace, fix hint
    pattern_analysis: Optional[PatternAnalysis]    # working vs broken comparison
    hypothesis: Optional[Hypothesis]               # specific hypothesis + confidence
    hypothesis_test: Optional[HypothesisTestResult]  # confirmed/rejected
    fix_plan: Optional[FixPlan]                    # test + fix + files + verification
    summary: str                                   # human-readable investigation summary
    next_steps: list[str]                          # ordered action items
    fix_attempts_count: int                        # passed through from input
    architectural_issue_detected: bool             # True when fix_attempts_count >= 3
```

## Model backend

Runs on `ollama` with `granite3.3:8b` (see `SETUP.md §3` for configuration). Requires a locally running Ollama instance with the model pulled.

## Fixtures

Six test fixtures are included in `fixtures/`. Run them to validate the installation:

```bash
python -m pytest fixtures/ -v
```

## When to use

- Any test failure, production bug, or unexpected behavior
- Especially under time pressure when the fix "seems obvious"
- After one or more failed fix attempts
- When you find yourself saying "quick fix for now" or "just try changing X"

## Iron Law

> **NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.**
>
> Proposing fixes before completing Phase 1 Root Cause Investigation violates the spirit of debugging.
