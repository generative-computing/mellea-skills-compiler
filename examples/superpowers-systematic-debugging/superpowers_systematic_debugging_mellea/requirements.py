from mellea.stdlib.requirements import check, req


# C2 Operating Rules — Iron Law: root cause before fix
# Applies to all output-generating calls that could propose fixes.
require_root_cause_before_fix = req(
    "The response must demonstrate that root cause investigation was completed before any fix is proposed. "
    "The output must identify specifically WHAT the root cause is and WHY it causes the observed issue — "
    "not merely what to change."
)

# C2 Operating Rules — process sequencing: complete each phase before the next
require_no_process_skipping = check(
    "The response must not propose fixes before Phase 1 Root Cause Investigation is complete. "
    "Each phase must build on evidence gathered in the previous phase."
)

# C2 Operating Rules — anti-patterns: no premature fix proposals or rationalizations
# Merged from Red Flags (elem_028) and Common Rationalizations (elem_030).
require_no_premature_fix_proposals = check(
    "The output must not contain premature fix proposals, guess-and-check suggestions, "
    "or rationalizations for skipping investigation phases. "
    "Phrases such as 'just try', 'quick fix', 'probably', or listing fixes without evidence of root cause analysis are violations."
)

# Phase 3 — epistemic honesty in hypothesis formation
require_epistemic_honesty = req(
    "The hypothesis must be stated as a specific claim: 'I think X is the root cause because Y'. "
    "Any uncertainty must be acknowledged explicitly rather than glossed over or masked by confident-sounding language."
)

# Phase 4 — fix addresses root cause and is verifiable
require_fix_verification = req(
    "The fix plan must address the root cause identified in Phase 1, not the surface symptom. "
    "The plan must include verification steps confirming the issue is actually resolved without breaking other tests."
)
