"""
Fixture coverage:
  C1 Identity: all fixtures (PREFIX_TEXT safety rule, SKILL_NAME/DESCRIPTION constants active)
  C2 Operating rules: all fixtures (pattern arrays PROMPT_INJECTION_CRITICAL, SSRF_PATTERNS, COMMAND_INJECTION, CREDENTIAL_EXFIL, ALLOWED_DOMAINS, SCORE_CRITICAL thresholds)
  C6 Tools: prompt_injection_critical (check_prompt), ssrf_metadata_url (check_url), command_injection_text (validate_text), safe_allowlisted_url (check_url), credential_exfil_sanitize (sanitize_external_input), empty_input_edge (validate_text)
  C8 Runtime environment: all fixtures (BACKEND, MODEL_ID, REQUIRED_BINS used by pipeline and tools)
"""
from typing import Callable

from .clean_text import make_clean_text
from .command_injection_text import make_command_injection_text
from .credential_exfil_sanitize import make_credential_exfil_sanitize
from .empty_input_edge import make_empty_input_edge
from .prompt_injection_critical import make_prompt_injection_critical
from .safe_allowlisted_url import make_safe_allowlisted_url
from .ssrf_metadata_url import make_ssrf_metadata_url


ALL_FIXTURES: list[Callable] = [
    make_prompt_injection_critical,
    make_clean_text,
    make_ssrf_metadata_url,
    make_command_injection_text,
    make_safe_allowlisted_url,
    make_credential_exfil_sanitize,
    make_empty_input_edge,
]
