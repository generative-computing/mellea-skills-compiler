"""Single-source constants used across the compiler and its export targets.

Keeping the mellea dependency pin here (instead of hardcoded strings in
`pyproject.toml`, three export-target templates, and the mellea-fy generate-step
doc) lets every rendered artefact reference the same value and lets a single
regression test enforce consistency (see
`tests/mellea_skills_compiler/test_pin_consistency.py`).

The pyproject.toml pin cannot be *derived* from this constant at build time
(PDM reads dependency strings statically), so it is kept in sync by the test
above rather than by import. If you change ``MELLEA_PIN``, also update
``pyproject.toml`` and ``.claude/commands/mellea-fy-generate.md``.
"""

from __future__ import annotations

# Supported upstream mellea range.
#
# Lower bound: 0.9.0 — the version the compiler is validated against (test
# suite and import/hook-payload probes run on 0.9.0). 0.7.x passed an earlier
# version of the suite, but 0.9.0 is the first release validated after 0.8
# removed/renamed several APIs (streaming ``stream()``, ``render_controls``,
# ``set_request_adapter``, ``json_util`` made private); 0.9 changed behaviour
# (async ``Requirement.validate`` now awaited, empty user content rejected),
# so compiled skills are only supported on 0.9+.
#
# Upper bound: <0.10 — mellea is pre-1.0 and ships breaking changes in minor
# releases (0.7 -> 0.8 did); cap at the next minor so a fresh install does not
# silently jump.
MELLEA_PIN = "mellea[hooks]>=0.9.0,<0.10"
