"""Smoke check must fail on mellea DeprecationWarnings at runtime.

Compat report §3.4: this is what would have caught the ``genslot`` shim
usage before it silently reverted to fallback data. The mechanism has to
fire ONLY on mellea-originated warnings — app deps that emit DeprecationWarnings
for unrelated reasons must not be conflated.
"""

from __future__ import annotations

import warnings
from types import SimpleNamespace
from unittest.mock import patch

from mellea_skills_compiler.compile.smoke_check import (
    _mellea_deprecation_warnings,
    _run_one_fixture,
)
from mellea_skills_compiler.models import Fixture


def _warning_record(message, filename="/pkgs/mellea/thing.py", lineno=42, category=DeprecationWarning):
    return SimpleNamespace(
        message=message,
        category=category,
        filename=filename,
        lineno=lineno,
    )


class TestMelleaDeprecationFilter:
    def test_reports_deprecation_from_mellea_path(self):
        w = _warning_record("genslot is deprecated, use genstub")
        assert len(_mellea_deprecation_warnings([w])) == 1

    def test_ignores_deprecation_from_unrelated_lib(self):
        w = _warning_record("something", filename="/pkgs/other_lib/x.py")
        assert _mellea_deprecation_warnings([w]) == []

    def test_matches_by_message_text_when_path_ambiguous(self):
        w = _warning_record(
            "mellea.stdlib.components.genslot is deprecated",
            filename="/some/wrapper.py",
        )
        assert len(_mellea_deprecation_warnings([w])) == 1

    def test_message_text_filter_fires_on_prose_containing_mellea(self):
        """False-positive documentation.

        The message-text fallback in ``_mellea_deprecation_warnings`` is
        intentionally loose (belt-and-braces): if a DeprecationWarning
        originates from an unrelated lib but happens to mention "mellea"
        in prose (e.g. a config-doc string), it will be flagged. This test
        pins that behaviour so a future tightening is a conscious change,
        not an accidental one. If someone wants stricter matching, this
        test breaks and forces the discussion.
        """
        w = _warning_record(
            "some_other_lib config: 'mellea' is one of the supported adapters",
            filename="/pkgs/some_other_lib/config.py",
        )
        # Path check fails (not under /mellea/), so the filter falls to
        # message-text scanning. The text mentions "mellea" so the filter
        # fires. Documented as intentional-but-loose.
        assert len(_mellea_deprecation_warnings([w])) == 1

    def test_unrelated_lib_without_mellea_word_is_ignored(self):
        """Complement to the case above: unrelated warnings with no mellea
        mention pass through cleanly."""
        w = _warning_record(
            "some_other_lib.foo is deprecated, use some_other_lib.bar",
            filename="/pkgs/some_other_lib/foo.py",
        )
        assert _mellea_deprecation_warnings([w]) == []


class TestRunOneFixtureFailsOnMelleaDeprecation:
    def test_fixture_that_triggers_mellea_deprecation_fails_smoke(self):
        fixture = Fixture(id="fx1", context={}, description="")

        def pipeline_fn(**kwargs):
            warnings.warn(
                "mellea.stdlib.components.genslot is deprecated",
                DeprecationWarning,
                stacklevel=1,
            )

        result = _run_one_fixture(pipeline_fn, fixture)
        assert result.verdict == "failed"
        assert "DeprecationWarning" in (result.failure_message or "")

    def test_fixture_without_deprecation_passes(self):
        fixture = Fixture(id="fx1", context={}, description="")

        def pipeline_fn(**kwargs):
            return None

        result = _run_one_fixture(pipeline_fn, fixture)
        assert result.verdict == "passed"
