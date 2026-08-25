"""Import-soundness lint flags the deprecated ``genslot`` module.

Complements the grounding fallback + the smoke-check DeprecationWarning
gate: the lint runs at validate-time, before any runtime, so a compiled
package that still emits ``from mellea.stdlib.components.genslot import ...``
never reaches smoke.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mellea_skills_compiler.compile.lints import lint_import_soundness


@pytest.fixture
def stub_grounding(tmp_path: Path) -> Path:
    """Build a minimal package_dir with a grounded api_ref that lists genstub."""
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    (intermediate / "mellea_api_ref.json").write_text(
        json.dumps(
            {
                "format_version": "1.0",
                "mellea_version": "0.7.0",
                "grounding_unavailable": False,
                "modules": {
                    "mellea.stdlib.components.genstub": {},
                    "mellea.stdlib.requirements": {},
                    "mellea.backends.model_options": {},
                },
            }
        )
    )
    return tmp_path


def test_genslot_import_is_flagged(stub_grounding: Path):
    (stub_grounding / "pipeline.py").write_text(
        "from mellea.stdlib.components.genslot import SyncGenerativeStub\n"
    )
    result = lint_import_soundness(stub_grounding)
    assert result.verdict == "fail"
    messages = [f.message for f in result.failures]
    assert any("genslot" in m and "genstub" in m for m in messages), (
        f"lint didn't produce a genslot-specific message; got: {messages}"
    )


def test_genstub_import_is_accepted(stub_grounding: Path):
    (stub_grounding / "pipeline.py").write_text(
        "from mellea.stdlib.components.genstub import SyncGenerativeStub\n"
    )
    result = lint_import_soundness(stub_grounding)
    assert result.verdict == "pass"


def test_bare_from_mellea_import_still_works(stub_grounding: Path):
    """`from mellea import start_session` reaches top-level re-exports and stays valid."""
    (stub_grounding / "pipeline.py").write_text(
        "from mellea import start_session, generative\n"
    )
    result = lint_import_soundness(stub_grounding)
    assert result.verdict == "pass"
