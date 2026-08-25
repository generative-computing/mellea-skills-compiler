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
# Lower bound: 0.7.0 — first release in which the compiler's Guardian
# post-check path is repairable (before 0.7 the ``ModelOutputThunk._action``
# private attribute was the only way to reach the originating action; from
# 0.7 that moved into a ``_CallInfo`` sub-object at ``_call.action``, and
# ``payload.generation_id`` became public on both pre- and post-call
# payloads, enabling id-based correlation instead).
#
# Upper bound: <0.8 — upstream ``main`` is already ``0.8.0.dev0`` at the time
# of writing (2026-08-14); without an upper bound a fresh install a week
# from now would silently jump a major and re-break.
MELLEA_PIN = "mellea[hooks]>=0.7.0,<0.8"
