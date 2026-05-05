from __future__ import annotations

from typing import Callable

from mellea import start_session
from mellea.backends.model_options import ModelOption
from mellea.stdlib.sampling import RepairTemplateStrategy
from pydantic import BaseModel

from .config import (
    BACKEND,
    LOOP_BUDGET,
    MODEL_ID,
    PREFIX_TEXT,
    READ_ONLY_MODE,
    SKIP_STYLISTIC_ISSUES,
)
from .constrained_slots import read_file_fn as _default_read_file_fn
from .constrained_slots import search_fn as _default_search_fn
from .requirements import audit_completeness_req, no_invented_issues_req
from .schemas import (
    AttackSurfaceMap,
    FileAttackSurface,
    FindingsReport,
    IssueReport,
    IssueVerdict,
    SecurityChecklist,
)
from .slots import extract_attack_surface_raw, extract_modified_files


ALL_CHECKLIST_CATEGORIES = [
    "Injection",
    "XSS",
    "Authentication",
    "Authorization/IDOR",
    "CSRF",
    "Race conditions",
    "Session",
    "Cryptography",
    "Information disclosure",
    "DoS",
    "Business logic",
]


def _parse_instruct_result(thunk, model_class: type[BaseModel]):
    """Parse m.instruct(format=Model) result."""
    return model_class.model_validate_json(thunk.value)


def _safe_parse_with_fallback(thunk, model_class: type[BaseModel], **fallback_kwargs):
    """Parse with fallback — returns a default model on parse failure."""
    try:
        return model_class.model_validate_json(thunk.value)
    except Exception:
        return model_class(**fallback_kwargs)


def run_pipeline(
    diff: str,
    search_fn: Callable[[str], list[str]] = _default_search_fn,
    read_file_fn: Callable[[str, int, int], str] = _default_read_file_fn,
) -> FindingsReport:
    """Run the full security analysis pipeline against a git diff.

    Args:
        diff: Full git diff of the branch vs the default branch.
        search_fn: Callable that searches the repo for test files matching a pattern.
        read_file_fn: Callable that reads lines start..end of a file path.

    Returns:
        FindingsReport with confirmed issues, file coverage, and checklist summary.
    """
    # Phase 1 — extract modified file list (KB5: separate session per @generative type)
    with start_session(BACKEND, MODEL_ID) as m1:
        raw_files = extract_modified_files(m1, diff=diff)

    modified_files = (
        [p.strip() for p in raw_files.split(",") if p.strip()]
        if raw_files.strip()
        else []
    )

    # Phase 1 completeness guard — if diff looks truncated, augment with full file reads
    if modified_files and (not diff.strip() or len(diff) < 500):
        augmented_parts = [diff]
        for fp in modified_files:
            try:
                content = read_file_fn(fp, 1, 5000)
                augmented_parts.append(f"\n=== Full content of {fp} ===\n{content}")
            except (NotImplementedError, OSError):
                pass
        diff = "\n".join(augmented_parts)

    if not modified_files:
        return FindingsReport(
            reviewed_files=[],
            checklist_summary={cat: "unverified" for cat in ALL_CHECKLIST_CATEGORIES},
            unverified_areas=["No modified files found in diff — cannot proceed with analysis."],
            issues=[],
        )

    file_list_str = ",".join(modified_files)

    # Phase 2 — attack surface mapping, step 1: raw extraction (KB5: separate session)
    with start_session(BACKEND, MODEL_ID) as m2:
        raw_surface = extract_attack_surface_raw(m2, diff=diff, file_list=file_list_str)

    # Phase 2 — attack surface mapping, step 2: structured parse via RepairTemplateStrategy
    with start_session(BACKEND, MODEL_ID) as m3:
        attack_map_thunk = m3.instruct(
            "Parse the raw attack surface extraction into the structured AttackSurfaceMap schema. "
            "Map each file to its categorised security-relevant operations.",
            model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
            grounding_context={
                "extract_attack_surface_raw_result": str(raw_surface),
                "diff": diff,
                "file_list": file_list_str,
            },
            format=AttackSurfaceMap,
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
        )
    attack_map = _safe_parse_with_fallback(attack_map_thunk, AttackSurfaceMap)

    # Phase 3 — per-file security checklist (KB5: one session, same format= type for all files)
    all_checklist_results: list[SecurityChecklist] = []
    skip_note = " Do NOT flag stylistic or formatting issues." if SKIP_STYLISTIC_ISSUES else ""
    read_only_note = " Do NOT suggest code changes — report findings only." if READ_ONLY_MODE else ""

    with start_session(BACKEND, MODEL_ID) as m4:
        for file_path in modified_files:
            file_surface = attack_map.files.get(file_path, FileAttackSurface())
            checklist_thunk = m4.instruct(
                f"Run the full 11-item security checklist on the file: {file_path}. "
                "Check EVERY category. For each category set verdict to 'issue', 'clean', or 'unverified'. "
                "For 'issue' verdicts, extract the finding and evidence from the diff."
                + skip_note
                + read_only_note,
                model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
                grounding_context={
                    "diff": diff,
                    "file_path": file_path,
                    "attack_surface": str(file_surface.model_dump()),
                },
                format=SecurityChecklist,
                strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
            )
            checklist = _safe_parse_with_fallback(
                checklist_thunk,
                SecurityChecklist,
                file_path=file_path,
                checks=[],
            )
            all_checklist_results.append(checklist)

    # Phase 4 — per-issue verification (KB5: one session, same format= type for all issues)
    issue_candidates = [
        (checklist.file_path, chk)
        for checklist in all_checklist_results
        for chk in checklist.checks
        if chk.verdict == "issue"
    ]

    confirmed_issues: list[IssueReport] = []

    with start_session(BACKEND, MODEL_ID) as m5:
        for file_path, candidate in issue_candidates:
            # Search for existing tests covering this scenario
            test_search_results: list[str] = []
            try:
                test_search_results = search_fn(
                    candidate.category.lower().replace("/", "_").replace(" ", "_")
                )
            except (NotImplementedError, Exception):
                test_search_results = []

            # Read surrounding file context to confirm the issue is real
            file_context = ""
            try:
                file_context = read_file_fn(file_path, 1, 200)
            except (NotImplementedError, OSError):
                file_context = ""

            verdict_thunk = m5.instruct(
                f"Verify whether the {candidate.category} finding in {file_path} is a confirmed real issue. "
                "Check if it is already handled elsewhere in the changed code, "
                "whether existing tests cover it, and whether the evidence is concrete.",
                model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
                grounding_context={
                    "issue_candidate": str(candidate.model_dump()),
                    "diff": diff,
                    "test_search_results": str(test_search_results),
                    "file_context": file_context,
                },
                format=IssueVerdict,
                strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
            )
            verdict = _safe_parse_with_fallback(
                verdict_thunk,
                IssueVerdict,
                confirmed=False,
                already_handled=False,
                has_tests=False,
                report=None,
            )
            if verdict.confirmed and not verdict.already_handled and verdict.report is not None:
                confirmed_issues.append(verdict.report)

    # Phase 5 — pre-conclusion audit: build checklist summary and unverified areas
    checklist_summary: dict[str, str] = {}
    for category in ALL_CHECKLIST_CATEGORIES:
        verdicts_for_cat = [
            chk.verdict
            for result in all_checklist_results
            for chk in result.checks
            if chk.category == category
        ]
        if "issue" in verdicts_for_cat:
            checklist_summary[category] = "issue"
        elif "unverified" in verdicts_for_cat:
            checklist_summary[category] = "unverified"
        elif verdicts_for_cat:
            checklist_summary[category] = "clean"
        else:
            checklist_summary[category] = "unverified"

    unverified_areas: list[str] = [
        f"{result.file_path}: {chk.category} — could not fully verify"
        for result in all_checklist_results
        for chk in result.checks
        if chk.verdict == "unverified"
    ]

    # Phase 5 — structured final report via LLM (applies audit requirements via IVR)
    with start_session(BACKEND, MODEL_ID) as m6:
        report_thunk = m6.instruct(
            "Phase 5 Pre-Conclusion Audit: "
            "List every reviewed file, confirm every checklist category verdict, "
            "note any areas that could not be fully verified, "
            "then produce the final findings report with all confirmed issues."
            + read_only_note,
            model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
            grounding_context={
                "reviewed_files": file_list_str,
                "checklist_results": str([r.model_dump() for r in all_checklist_results]),
                "confirmed_issues": str([i.model_dump() for i in confirmed_issues]),
                "checklist_summary": str(checklist_summary),
                "unverified_areas": str(unverified_areas),
            },
            format=FindingsReport,
            requirements=[audit_completeness_req, no_invented_issues_req],
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
        )

    report = _safe_parse_with_fallback(
        report_thunk,
        FindingsReport,
        issues=confirmed_issues,
        reviewed_files=modified_files,
        checklist_summary=checklist_summary,
        unverified_areas=unverified_areas,
    )
    return report
