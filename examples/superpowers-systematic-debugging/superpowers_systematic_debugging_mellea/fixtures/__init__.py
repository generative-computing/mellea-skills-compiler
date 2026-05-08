"""
Fixture coverage (R16 — exercises C1, C2, C3, C8 = 4 distinct C-categories):

  C1 Identity (PREFIX_TEXT persona): all fixtures — persona applied via SYSTEM_PROMPT on every m.instruct call
  C2 Operating Rules (5 requirements): all fixtures — require_root_cause_before_fix, require_no_process_skipping,
    require_no_premature_fix_proposals, require_epistemic_honesty, require_fix_verification applied across phases
  C3 User Facts (reference comparison): working_example_comparison — exercises Phase 2 working_examples_text
    parameter and the C3 'compare against references' operating rule
  C8 Runtime Environment (MAX_FIX_ATTEMPTS, BACKEND, MODEL_ID): architectural_issue_detected — triggers
    fix_attempts_count >= MAX_FIX_ATTEMPTS (3) threshold and classify_failure_pattern slot;
    test_failure_after_refactor exercises BACKEND/MODEL_ID session handling
"""
from typing import Callable

from .architectural_issue_detected import make_architectural_issue_detected
from .intermittent_import_failure import make_intermittent_import_failure
from .minimal_description_only import make_minimal_description_only
from .simple_type_error import make_simple_type_error
from .test_failure_after_refactor import make_test_failure_after_refactor
from .working_example_comparison import make_working_example_comparison


ALL_FIXTURES: list[Callable] = [
    make_simple_type_error,
    make_test_failure_after_refactor,
    make_working_example_comparison,
    make_architectural_issue_detected,
    make_intermittent_import_failure,
    make_minimal_description_only,
]
