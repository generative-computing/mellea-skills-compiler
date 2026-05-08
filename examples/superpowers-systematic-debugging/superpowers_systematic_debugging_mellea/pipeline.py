from typing import Optional

from mellea import start_session
from mellea.backends.model_options import ModelOption
from mellea.stdlib.sampling import RepairTemplateStrategy
from pydantic import BaseModel, Field

from .config import BACKEND, LOOP_BUDGET, MAX_FIX_ATTEMPTS, MODEL_ID, PREFIX_TEXT
from .requirements import (
    require_epistemic_honesty,
    require_fix_verification,
    require_no_premature_fix_proposals,
    require_no_process_skipping,
    require_root_cause_before_fix,
)
from .schemas import (
    DebuggingReport,
    ErrorAnalysis,
    FixPlan,
    Hypothesis,
    HypothesisTestResult,
    PatternAnalysis,
    ReproductionResult,
    RootCauseEvidence,
)
from .slots import (
    classify_failure_pattern,
    extract_data_flow_trace_raw,
    extract_error_analysis_raw,
    extract_recent_changes_raw,
)


# KB1 / KB2 helpers — always parse thunks before field access
def _parse_instruct_result(thunk, model_class: type[BaseModel]):
    """Parse m.instruct(format=Model) result."""
    return model_class.model_validate_json(thunk.value)


def _safe_parse_with_fallback(thunk, model_class: type[BaseModel], **fallback_kwargs):
    """Parse with fallback — returns a default model on parse failure."""
    try:
        return model_class.model_validate_json(thunk.value)
    except Exception:
        return model_class(**fallback_kwargs)


# Private helper for final summary generation (separate schema to avoid KB5 priming conflict)
class _DebugSummaryOutput(BaseModel):
    summary: str = Field(description="High-level summary of the debugging investigation findings")
    next_steps: list[str] = Field(description="Concrete ordered actions to resolve the issue")


def run_pipeline(
    issue_description: str,
    error_text: str = "",
    recent_changes: str = "",
    code_context: str = "",
    working_examples_text: str = "",
    fix_attempts_count: int = 0,
) -> DebuggingReport:
    """Run the systematic debugging investigation pipeline.

    Executes all four phases in sequence:
    Phase 1: Root Cause Investigation
    Phase 2: Pattern Analysis
    Phase 3: Hypothesis and Testing
    Phase 4: Implementation planning

    Iron Law: NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.
    Each phase must complete before the next begins.
    """
    error_analysis: Optional[ErrorAnalysis] = None
    reproduction_status: Optional[ReproductionResult] = None
    root_cause_evidence: Optional[RootCauseEvidence] = None
    pattern_analysis: Optional[PatternAnalysis] = None
    hypothesis: Optional[Hypothesis] = None
    hypothesis_test: Optional[HypothesisTestResult] = None
    fix_plan: Optional[FixPlan] = None
    architectural_issue_detected = False

    # === Phase 1: Root Cause Investigation ===

    # Step 1 — extract raw error signals (two-step step 1, KB5: own session per @generative schema)
    raw_error: str = ""
    if error_text.strip():
        with start_session(BACKEND, MODEL_ID) as m:
            raw_error = extract_error_analysis_raw(m, error_text=error_text)

    # Step 1 — enrich raw signals into structured ErrorAnalysis (two-step step 2)
    # KB2: ErrorAnalysis has list[str] fields → use RepairTemplateStrategy + _safe_parse_with_fallback
    if raw_error.strip():
        with start_session(BACKEND, MODEL_ID) as m:
            error_thunk = m.instruct(
                "Produce a complete, structured analysis of this error using the extracted signals. "
                "Focus on application code frames, not library internals.",
                model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
                grounding_context={
                    "error_text": error_text,
                    "raw_error_signals": raw_error,
                },
                format=ErrorAnalysis,
                strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
            )
            error_analysis = _safe_parse_with_fallback(
                error_thunk,
                ErrorAnalysis,
                error_type="unknown",
                error_message=error_text[:200] if error_text else "not provided",
                stack_trace_summary="",
            )

    # Step 2 — assess reproducibility
    # KB2: ReproductionResult has list[str] → RepairTemplateStrategy + fallback
    with start_session(BACKEND, MODEL_ID) as m:
        repro_thunk = m.instruct(
            "Assess whether this issue can be reproduced based on the description and available context. "
            "Determine the exact reproduction steps and frequency.",
            model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
            grounding_context={
                "issue_description": issue_description,
                "error_text": error_text if error_text else "not provided",
                "code_context": code_context if code_context else "not provided",
            },
            format=ReproductionResult,
            requirements=[require_no_process_skipping],
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
        )
        reproduction_status = _safe_parse_with_fallback(
            repro_thunk,
            ReproductionResult,
            is_reproducible=False,
            frequency="cannot_reproduce",
        )

    # Step 3 — extract recent changes summary (two-step step 1)
    # KB5: own session for this @generative schema
    raw_changes: str = ""
    with start_session(BACKEND, MODEL_ID) as m:
        raw_changes = extract_recent_changes_raw(
            m,
            issue_description=issue_description,
            changes_text=recent_changes if recent_changes else "not provided",
        )

    # Step 4 — trace data flow backward to origin (two-step step 1)
    # KB5: own session for this @generative schema
    raw_trace: str = ""
    if error_text.strip() or code_context.strip():
        with start_session(BACKEND, MODEL_ID) as m:
            raw_trace = extract_data_flow_trace_raw(
                m,
                error_text=error_text if error_text else "not provided",
                code_source_text=code_context if code_context else "not provided",
            )

    # Step 4 — enrich trace into structured RootCauseEvidence (two-step step 2)
    # KB2: RootCauseEvidence has list[str] + 5 fields → RepairTemplateStrategy + fallback
    _trace_is_unknown = not raw_trace.strip() or raw_trace.startswith("UNKNOWN|UNKNOWN")
    if not _trace_is_unknown:
        with start_session(BACKEND, MODEL_ID) as m:
            trace_thunk = m.instruct(
                "Build a complete backward call-chain trace from the raw signals. "
                "Identify where the bad value originates, trace each step backward, and pinpoint the root source. "
                "Fix at the source, not at the symptom.",
                model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
                grounding_context={
                    "issue_description": issue_description,
                    "error_text": error_text if error_text else "not provided",
                    "code_context": code_context if code_context else "not provided",
                    "raw_trace": raw_trace,
                    "recent_changes_summary": raw_changes,
                },
                format=RootCauseEvidence,
                requirements=[require_root_cause_before_fix],
                strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
            )
            root_cause_evidence = _safe_parse_with_fallback(
                trace_thunk,
                RootCauseEvidence,
                origin_location="unknown — investigation required",
                bad_value_description=issue_description[:200],
                root_source="investigation required",
                fix_recommendation="Complete Phase 1 investigation before proposing a fix",
            )

    # === Phase 2: Pattern Analysis ===
    # Find working examples, compare against references, identify differences, understand dependencies
    # KB2: PatternAnalysis has list[str] fields → RepairTemplateStrategy + fallback
    with start_session(BACKEND, MODEL_ID) as m:
        pattern_thunk = m.instruct(
            "Analyze patterns between working code and the broken code. "
            "Find every difference however small. Identify all missing dependencies. "
            "If implementing a reference pattern, it must be read COMPLETELY before applying.",
            model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
            grounding_context={
                "issue_description": issue_description,
                "code_context": code_context if code_context else "not provided",
                "working_examples": working_examples_text if working_examples_text else "not provided",
                "recent_changes_summary": raw_changes,
                "root_cause_evidence": str(root_cause_evidence.model_dump()) if root_cause_evidence else "Phase 1 incomplete",
            },
            format=PatternAnalysis,
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
        )
        pattern_analysis = _safe_parse_with_fallback(
            pattern_thunk,
            PatternAnalysis,
            pattern_summary="Pattern analysis could not be completed with the available information",
        )

    # === Phase 3: Hypothesis and Testing ===

    # Step 1 — form a single, specific hypothesis
    with start_session(BACKEND, MODEL_ID) as m:
        hyp_thunk = m.instruct(
            "State a single specific hypothesis about the root cause. "
            "Format: 'I think X is the root cause because Y'. "
            "Base it on the evidence gathered in Phases 1 and 2. "
            "Be specific and honest — say 'I don't know' if uncertain.",
            model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
            grounding_context={
                "issue_description": issue_description,
                "error_analysis": str(error_analysis.model_dump()) if error_analysis else "not available",
                "root_cause_evidence": str(root_cause_evidence.model_dump()) if root_cause_evidence else "not available",
                "pattern_analysis": str(pattern_analysis.model_dump()) if pattern_analysis else "not available",
            },
            format=Hypothesis,
            requirements=[require_epistemic_honesty],
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
        )
        hypothesis = _safe_parse_with_fallback(
            hyp_thunk,
            Hypothesis,
            root_cause_statement="Hypothesis could not be formed — more investigation needed",
            evidence_basis="incomplete",
            test_approach="Gather more information before forming a hypothesis",
            confidence_level="low",
        )

    # Step 3 — verify or assess the hypothesis
    with start_session(BACKEND, MODEL_ID) as m:
        test_thunk = m.instruct(
            "Assess whether the hypothesis can be verified based on available information. "
            "Describe the minimal single change that would confirm or refute it. "
            "ONE variable at a time — do not propose multiple changes.",
            model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
            grounding_context={
                "hypothesis": str(hypothesis.model_dump()),
                "issue_description": issue_description,
                "error_text": error_text if error_text else "not provided",
                "code_context": code_context if code_context else "not provided",
            },
            format=HypothesisTestResult,
            requirements=[require_epistemic_honesty],
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
        )
        hypothesis_test = _safe_parse_with_fallback(
            test_thunk,
            HypothesisTestResult,
            hypothesis_confirmed=False,
            test_performed="assessment pending",
            result_observed="insufficient information to confirm — gather more data",
        )

    # === Phase 4: Implementation ===

    # DECIDE: check fix attempt count against the architectural threshold (elem_025)
    # If fix_attempts_count >= MAX_FIX_ATTEMPTS, classify the failure pattern
    if fix_attempts_count >= MAX_FIX_ATTEMPTS:
        # KB5: classify_failure_pattern uses its own @generative schema — own session
        with start_session(BACKEND, MODEL_ID) as m:
            failure_class = classify_failure_pattern(
                m,
                investigation_summary=(
                    f"Issue: {issue_description}. "
                    f"Fix attempts already made: {fix_attempts_count}. "
                    f"Hypothesis: {hypothesis.root_cause_statement if hypothesis else 'unknown'}. "
                    f"Pattern analysis: {pattern_analysis.pattern_summary if pattern_analysis else 'incomplete'}."
                ),
                fix_count=fix_attempts_count,
            )
        architectural_issue_detected = failure_class == "architectural_problem"
    else:
        architectural_issue_detected = False

    # Generate fix plan only when the hypothesis is actionable and not blocked by architectural concerns
    _hypothesis_actionable = (
        hypothesis_test is not None
        and (hypothesis_test.hypothesis_confirmed or fix_attempts_count < MAX_FIX_ATTEMPTS)
        and not architectural_issue_detected
    )
    if _hypothesis_actionable:
        # KB2: FixPlan has list[str] fields → RepairTemplateStrategy + fallback
        with start_session(BACKEND, MODEL_ID) as m:
            fix_thunk = m.instruct(
                "Create a precise fix plan that addresses the root cause. "
                "Step 1: describe the simplest failing test to create FIRST. "
                "Step 2: describe ONE change that fixes the root cause — not the symptom. "
                "No bundled changes. No 'while I'm here' improvements.",
                model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
                grounding_context={
                    "root_cause": str(root_cause_evidence.model_dump()) if root_cause_evidence else "not determined",
                    "hypothesis": str(hypothesis.model_dump()) if hypothesis else "not formed",
                    "hypothesis_test": str(hypothesis_test.model_dump()),
                    "issue_description": issue_description,
                    "architectural_issue_detected": str(architectural_issue_detected),
                },
                format=FixPlan,
                requirements=[require_root_cause_before_fix, require_fix_verification],
                strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
            )
            fix_plan = _safe_parse_with_fallback(
                fix_thunk,
                FixPlan,
                failing_test_description="Write the simplest test that reproduces the identified root cause",
                fix_description="Address root cause identified in Phase 1 (investigation still in progress)",
                is_architectural_issue=architectural_issue_detected,
            )

    # === Build final summary ===
    # KB5: _DebugSummaryOutput is a distinct schema — own session
    with start_session(BACKEND, MODEL_ID) as m:
        summary_thunk = m.instruct(
            "Synthesize the complete debugging investigation into a clear summary and ordered next steps. "
            "The summary must reflect the evidence found, not restate the problem. "
            "Next steps must be concrete and actionable.",
            model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
            grounding_context={
                "issue_description": issue_description,
                "phase1_findings": str(root_cause_evidence.model_dump()) if root_cause_evidence else "Phase 1 incomplete",
                "phase2_patterns": str(pattern_analysis.model_dump()) if pattern_analysis else "Phase 2 incomplete",
                "phase3_hypothesis": str(hypothesis.model_dump()) if hypothesis else "not formed",
                "phase4_fix_plan": str(fix_plan.model_dump()) if fix_plan else "not ready",
                "fix_attempts_count": str(fix_attempts_count),
                "architectural_issue_detected": str(architectural_issue_detected),
            },
            format=_DebugSummaryOutput,
            requirements=[require_root_cause_before_fix, require_no_premature_fix_proposals],
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
        )
        summary_output = _safe_parse_with_fallback(
            summary_thunk,
            _DebugSummaryOutput,
            summary="Investigation completed. Review the structured findings for next actions.",
            next_steps=["Review Phase 1 findings", "Form and test a specific hypothesis", "Apply the identified fix at the root source"],
        )

    # Construct the final report directly from individually-computed phase objects
    return DebuggingReport(
        phase1_complete=root_cause_evidence is not None,
        error_analysis=error_analysis,
        reproduction_status=reproduction_status,
        root_cause_evidence=root_cause_evidence,
        pattern_analysis=pattern_analysis,
        hypothesis=hypothesis,
        hypothesis_test=hypothesis_test,
        fix_plan=fix_plan,
        summary=summary_output.summary,
        next_steps=summary_output.next_steps,
        fix_attempts_count=fix_attempts_count,
        architectural_issue_detected=architectural_issue_detected,
    )
