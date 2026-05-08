from __future__ import annotations

import json as _json

from mellea.stdlib.requirements import check, req, simple_validate


def _validate_audit_completeness(output: str) -> bool:
    try:
        data = _json.loads(output)
        reviewed_files = data.get("reviewed_files", [])
        if not reviewed_files:
            return False
        checklist_summary = data.get("checklist_summary", {})
        expected_categories = {
            "Injection", "XSS", "Authentication", "Authorization/IDOR",
            "CSRF", "Race conditions", "Session", "Cryptography",
            "Information disclosure", "DoS", "Business logic",
        }
        if not expected_categories.issubset(set(checklist_summary.keys())):
            return False
        unverified_areas = data.get("unverified_areas")
        return unverified_areas is not None
    except (_json.JSONDecodeError, AttributeError):
        return False


audit_completeness_req = req(
    "All reviewed files must be listed, all 11 checklist categories must have a noted verdict, and an unverified areas section must be present",
    validation_fn=simple_validate(_validate_audit_completeness),
)

no_invented_issues_req = req(
    "The findings output must not fabricate issues. If no significant issues are found, the report must say so explicitly rather than inventing problems.",
)
