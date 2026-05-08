from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FileAttackSurface(BaseModel):
    user_inputs: list[str] = Field(default_factory=list)
    db_queries: list[str] = Field(default_factory=list)
    auth_checks: list[str] = Field(default_factory=list)
    session_ops: list[str] = Field(default_factory=list)
    external_calls: list[str] = Field(default_factory=list)
    crypto_ops: list[str] = Field(default_factory=list)


class AttackSurfaceMap(BaseModel):
    files: dict[str, FileAttackSurface] = Field(default_factory=dict)


class SecurityCheckResult(BaseModel):
    category: Literal[
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
    verdict: Literal["issue", "clean", "unverified"]
    finding: str | None = Field(
        default=None,
        description=(
            "If the verdict is 'issue', extract the specific finding from the code diff; "
            "otherwise null. Do not ask for clarification."
        ),
    )
    evidence: str | None = Field(
        default=None,
        description=(
            "If the verdict is 'issue', extract the evidence from the code diff "
            "that supports the finding; otherwise null. Do not ask for clarification."
        ),
    )


class SecurityChecklist(BaseModel):
    file_path: str
    checks: list[SecurityCheckResult]


class IssueReport(BaseModel):
    file_line: str = Field(
        description="File path and approximate line reference in format 'path/to/file.py:LINE'."
    )
    severity: Literal["Critical", "High", "Medium", "Low"]
    problem: str = Field(description="Concise description of what is wrong.")
    evidence: str = Field(
        description="Concrete evidence from the diff that this issue is real and not already fixed."
    )
    fix: str = Field(description="Concrete, actionable suggestion to fix the issue.")
    references: list[str] | None = Field(
        default=None,
        description=(
            "Extract any applicable OWASP, RFC, or other standards references; "
            "null if no standard reference applies. Do not ask for clarification."
        ),
    )


class IssueVerdict(BaseModel):
    confirmed: bool = Field(
        description="Extract whether this is a confirmed real issue based on the code analysis."
    )
    already_handled: bool = Field(
        default=False,
        description="Extract whether this issue is already handled elsewhere in the changed code.",
    )
    has_tests: bool = Field(
        default=False,
        description="Extract whether existing tests cover this vulnerability scenario.",
    )
    report: IssueReport | None = Field(
        default=None,
        description=(
            "If confirmed is True, extract the full issue report from the analysis; "
            "otherwise null. Do not ask for additional information."
        ),
    )


class FindingsReport(BaseModel):
    issues: list[IssueReport] = Field(default_factory=list)
    reviewed_files: list[str] = Field(default_factory=list)
    checklist_summary: dict[str, str] = Field(default_factory=dict)
    unverified_areas: list[str] = Field(default_factory=list)
