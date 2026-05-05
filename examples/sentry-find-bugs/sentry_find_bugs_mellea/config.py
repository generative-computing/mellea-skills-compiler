from typing import Final


# === C1: Identity & Behavioral Context ===
PREFIX_TEXT: Final[str] = 'You are an expert security code reviewer. Your role is to identify bugs, security vulnerabilities, and code quality issues in code changes. You apply rigorous security analysis including OWASP Top 10 checks, race condition detection, authentication/authorization verification, and business logic review. You report only real, confirmed issues with concrete evidence and actionable fixes. You never invent issues, never make code changes, and never skip checklist items.'
# PROVENANCE: spec.md:1-4

# === C8: Runtime Environment ===
SKILL_NAME: Final[str] = 'find-bugs'
# PROVENANCE: spec.md:2

BACKEND: Final[str] = 'ollama'
MODEL_ID: Final[str] = 'granite3.3:8b'

LOOP_BUDGET: Final[int] = 3
ISSUE_PRIORITY_ORDER: Final[str] = 'security_vulnerability,bug,code_quality'
# PROVENANCE: spec.md:60

SKIP_STYLISTIC_ISSUES: Final[bool] = True
# PROVENANCE: spec.md:62

READ_ONLY_MODE: Final[bool] = True
# PROVENANCE: spec.md:75
