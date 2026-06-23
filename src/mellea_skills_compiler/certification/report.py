"""
Generate a certification report with audit trail evidence showing which requirements are
satisfied and how.
"""

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mellea_skills_compiler.enums import CoverageLevel, GuardianScore
from mellea_skills_compiler.models import (
    ComplianceSummary,
    PolicyManifest,
    RequirementClassification,
)


# ── Audit trail loading ─────────────────────────────────────────────


def load_audit_trail(path: str | Path) -> list[dict]:
    """Load JSONL audit trail into a list of dicts."""
    entries = []
    p = Path(path)
    if not p.exists():
        return entries
    with open(p) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries


# ── Evidence extractors ─────────────────────────────────────────────


def _extract_guardian_evidence(entries: list[dict]) -> list[str]:
    """Evidence from Guardian verdict entries."""
    gen_posts = [e for e in entries if e["hook"] == "generation_post_call"]
    if not gen_posts:
        return ["No generation events recorded."]

    total_verdicts = 0
    risks_checked = set()
    flagged = 0
    for e in gen_posts:
        for v in e.get("guardian_verdicts", []):
            total_verdicts += 1
            risks_checked.add(v["risk"])
            if v["label"] == GuardianScore.YES:
                flagged += 1

    evidence = [
        f"{len(gen_posts)} generation events monitored.",
        f"{total_verdicts} Guardian risk checks performed across {len(risks_checked)} risk categories: {', '.join(sorted(risks_checked))}.",
    ]
    if flagged:
        evidence.append(f"{flagged} risk incidents flagged.")
    else:
        evidence.append("No risk incidents detected.")
    return evidence


def _extract_audit_evidence(entries: list[dict]) -> list[str]:
    """Evidence from audit trail completeness."""
    if not entries:
        return ["No audit entries recorded."]

    hook_counts = Counter(e["hook"] for e in entries)
    ts = [e.get("timestamp", "") for e in entries if e.get("timestamp")]
    span = ""
    if len(ts) >= 2:
        span = f" Time span: {ts[0]} to {ts[-1]}."

    lines = [
        f"{len(entries)} total audit events recorded.{span}",
        "Hook coverage: "
        + ", ".join(f"{hook} ({count})" for hook, count in hook_counts.most_common())
        + ".",
    ]
    if all(e.get("policy_id") for e in entries):
        lines.append(f"All entries tagged with policy_id: '{entries[0]['policy_id']}'.")
    return lines


def _extract_io_evidence(entries: list[dict]) -> list[str]:
    """Evidence from input/output monitoring."""
    pre = [e for e in entries if e["hook"] == "generation_pre_call"]
    post = [e for e in entries if e["hook"] == "generation_post_call"]
    lines = []
    if pre:
        lines.append(f"{len(pre)} generation inputs captured (generation_pre_call).")
    if post:
        lines.append(f"{len(post)} generation outputs captured with Guardian checks.")
    return lines or ["No I/O monitoring events recorded."]


def _extract_incident_evidence(entries: list[dict]) -> list[str]:
    """Evidence from incident detection."""
    gen_posts = [e for e in entries if e["hook"] == "generation_post_call"]
    flagged = [e for e in gen_posts if e.get("risk_detected")]
    if flagged:
        return [
            f"{len(flagged)} of {len(gen_posts)} generations flagged for risk incidents."
        ]
    return [f"{len(gen_posts)} generations monitored — no incidents detected."]


def _extract_performance_evidence(entries: list[dict]) -> list[str]:
    """Evidence from performance monitoring."""
    with_latency = [e for e in entries if e.get("latency_ms")]
    if not with_latency:
        return ["No latency data recorded."]

    latencies = [e["latency_ms"] for e in with_latency]
    avg = sum(latencies) / len(latencies)
    return [
        f"{len(with_latency)} events with latency data.",
        f"Average latency: {avg:.0f}ms, range: {min(latencies):.0f}–{max(latencies):.0f}ms.",
    ]


def _evidence_for_requirement(
    classification: RequirementClassification,
    entries: list[dict],
) -> list[str]:
    """Collect evidence lines for a classified requirement."""
    if not classification.matched_controls:
        return []
    evidence = []
    seen_extractors: set[int] = set()
    for control in classification.matched_controls:
        extractor = EVIDENCE_EXTRACTORS.get(control)
        if extractor and id(extractor) not in seen_extractors:
            seen_extractors.add(id(extractor))
            evidence.extend(extractor(entries))
    return evidence


# Map pipeline control IDs to evidence extractors
EVIDENCE_EXTRACTORS: dict[str, Any] = {
    "pc-content-safety": _extract_guardian_evidence,
    "pc-input-screening": _extract_io_evidence,
    "pc-generation-audit": _extract_audit_evidence,
    "pc-component-audit": _extract_audit_evidence,
    "pc-validation-audit": _extract_audit_evidence,
    "pc-latency-monitoring": _extract_performance_evidence,
    "pc-incident-flagging": _extract_incident_evidence,
    "pc-policy-traceability": _extract_audit_evidence,
}


def generate_certification_report(
    manifest: PolicyManifest,
    compliance: ComplianceSummary,
    audit_trail: list[dict],
    audit_path: str = "",
) -> str:
    """Generate a Markdown certification report with evidence.

    Args:
        manifest (PolicyManifest): _description_
        compliance (ComplianceSummary): _description_
        audit_trail (list[dict]): _description_
        audit_path (str, optional): _description_. Defaults to "".

    Returns:
        str: _description_
    """
    now = datetime.now(UTC).isoformat()
    total = len(compliance.classifications)
    counts = compliance.counts

    lines = [
        "# Certification Report",
        "",
        f"**Generated**: {now}  ",
        f"**Policy**: {manifest.use_case}  ",
        f"**Audit trail**: `{audit_path}` ({len(audit_trail)} events)  ",
        f"**Policy manifest taxonomy**: {manifest.taxonomy}",
        "",
        "---",
        "",
        "## Coverage Summary",
        "",
    ]

    for level in ["AUTOMATED", "PARTIAL", "MANUAL"]:
        count = counts[level]
        pct = (count / total * 100) if total else 0
        lines.append(f"- **{level}**: {count} of {total} requirements ({pct:.0f}%)")
    lines.append("")

    # ── Guardian runtime checks ─────────────────────────────────
    lines.extend(
        [
            "---",
            "",
            "## 1. Guardian Runtime Checks",
            "",
        ]
    )
    guardian_evidence = _extract_guardian_evidence(audit_trail)
    for ev in guardian_evidence:
        lines.append(f"- {ev}")
    lines.append("")

    # Per-risk table
    gen_posts = [e for e in audit_trail if e["hook"] == "generation_post_call"]
    risk_stats: dict[str, dict] = defaultdict(lambda: {"checks": 0, "flagged": 0})
    for e in gen_posts:
        for v in e.get("guardian_verdicts", []):
            risk_stats[v["risk"]]["checks"] += 1
            if v["label"] == GuardianScore.YES:
                risk_stats[v["risk"]]["flagged"] += 1

    if risk_stats:
        lines.extend(
            [
                "| Risk | Checks | Flagged | Pass Rate |",
                "|------|--------|---------|-----------|",
            ]
        )
        for risk, stats in risk_stats.items():
            total_checks = stats["checks"]
            flagged = stats["flagged"]
            passed = total_checks - flagged
            rate = (passed / total_checks * 100) if total_checks else 0
            lines.append(f"| {risk} | {total_checks} | {flagged} | {rate:.0f}% |")
        lines.append("")

    # ── Requirements per taxonomy ────────────────────────────────
    by_source: dict[str, list[RequirementClassification]] = defaultdict(list)
    for c in compliance.classifications:
        by_source[c.action.source].append(c)

    section_num = 2
    for source, cls_list in by_source.items():
        lines.extend(
            [
                "---",
                "",
                f"## {section_num}. Governance Requirements ({source})",
                "",
            ]
        )
        for level in [
            CoverageLevel.AUTOMATED,
            CoverageLevel.PARTIAL,
            CoverageLevel.MANUAL,
        ]:
            subset = [c for c in cls_list if c.coverage == level]
            if not subset:
                continue
            lines.extend(
                [
                    f"### {level.value} ({len(subset)})",
                    "",
                ]
            )
            for c in subset:
                desc = c.action.description
                if len(desc) > 200:
                    desc = desc[:197] + "..."
                lines.extend(
                    [
                        f"- **[{c.action.id}]** {desc}",
                    ]
                )
                if c.matched_controls:
                    ctrl_str = c.matched_controls
                    lines.append(f"  - Controls: {ctrl_str}")
                if c.coverage in (CoverageLevel.AUTOMATED, CoverageLevel.PARTIAL):
                    evidence = _evidence_for_requirement(c, audit_trail)
                    if evidence:
                        lines.append(f"  - Evidence: {'; '.join(evidence)}")
                lines.append("")
        section_num += 1

    # ── Audit trail summary ─────────────────────────────────────
    lines.extend(
        [
            "---",
            "",
            f"## {section_num}. Audit Trail Summary",
            "",
        ]
    )
    audit_evidence = _extract_audit_evidence(audit_trail)
    for ev in audit_evidence:
        lines.append(f"- {ev}")
    lines.append("")

    perf_evidence = _extract_performance_evidence(audit_trail)
    for ev in perf_evidence:
        lines.append(f"- {ev}")
    lines.append("")

    # ── Gaps and recommendations ────────────────────────────────
    section_num += 1
    partial_items = compliance.partial
    if partial_items:
        lines.extend(
            [
                "---",
                "",
                f"## {section_num}. Gaps and Recommendations",
                "",
                "The following requirements are partially covered and could be "
                "upgraded to AUTOMATED with additional hook configuration or "
                "organizational process:",
                "",
            ]
        )
        for c in partial_items:
            lines.append(f"- **[{c.action.id}]** {c.action.name or ''}")
        lines.append("")

    # ── Known limitations ─────────────────────────────────────────
    section_num += 1
    lines.extend(
        [
            "---",
            "",
            f"## {section_num}. Known Limitations",
            "",
            "The following governance capabilities are not yet implemented:",
            "",
            "- **Tool access governance**: No `tool_pre_invoke`/`tool_post_invoke` "
            "hooks are active. MCP tool calls are not audited or rate-limited. "
            "For agents using MCP-based skills (e.g. OpenClaw, where 65% of skills "
            "wrap MCP servers), this is a significant gap.",
            "- **Enforcement mode**: Guardian currently runs in AUDIT mode "
            "(observe-only). Risk detections are logged but do not block unsafe "
            "outputs. Switching to SEQUENTIAL mode with `block()` returns would "
            "provide runtime enforcement.",
            "- **Proactive autonomy**: Agents with autonomous scheduling (e.g. "
            "OpenClaw heartbeat mode) can generate outputs without user prompting. "
            "Governance hooks for unsolicited autonomous actions are not yet "
            "implemented.",
            "",
        ]
    )

    return "\n".join(lines)
