"""
Fixture coverage:
  C1 Identity (persona applied as expert security reviewer): all fixtures
  C2 Operating rules (skip stylistic issues, read-only mode, prioritization): all fixtures
  C6 Tools (gather_diff real_impl exercised; search_fn/read_file_fn stubs gracefully skipped): positive_sql_injection, positive_missing_authz, mixed_partial_csrf_fix
  C8 Runtime environment (BACKEND/MODEL_ID config consumed by all sessions): all fixtures
"""
from typing import Callable

from .clean_secure_parameterized import make_clean_secure_parameterized
from .edge_comments_only import make_edge_comments_only
from .edge_empty_diff import make_edge_empty_diff
from .mixed_partial_csrf_fix import make_mixed_partial_csrf_fix
from .positive_missing_authz import make_positive_missing_authz
from .positive_sql_injection import make_positive_sql_injection


ALL_FIXTURES: list[Callable] = [
    make_positive_sql_injection,
    make_positive_missing_authz,
    make_clean_secure_parameterized,
    make_edge_empty_diff,
    make_edge_comments_only,
    make_mixed_partial_csrf_fix,
]
