"""Enforce a single-source mellea dependency pin across the compiler.

If ``constants.MELLEA_PIN`` drifts from any of the four rendered locations
(root ``pyproject.toml``, the three export targets, or the generate-step
template) an install with mismatched pins can silently resolve to a broken
range — the mellea 0.7 upgrade landed precisely because we had four
different values in the tree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mellea_skills_compiler.constants import MELLEA_PIN


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_pin_matches_constant():
    text = (REPO_ROOT / "pyproject.toml").read_text()
    assert f'"{MELLEA_PIN}"' in text, (
        f"pyproject.toml does not carry the current MELLEA_PIN ({MELLEA_PIN!r}). "
        f"Update the dependency line to match constants.py."
    )


@pytest.mark.parametrize(
    "target_path",
    [
        "src/mellea_skills_compiler/export/targets/mcp.py",
        "src/mellea_skills_compiler/export/targets/claude_code.py",
        "src/mellea_skills_compiler/export/targets/langgraph.py",
    ],
)
def test_export_targets_derive_pin_from_constant(target_path):
    text = (REPO_ROOT / target_path).read_text()
    # The three targets must import MELLEA_PIN and interpolate it — no
    # hardcoded ``mellea[hooks]>=...`` string may appear.
    assert "from mellea_skills_compiler.constants import MELLEA_PIN" in text, (
        f"{target_path} does not import MELLEA_PIN; the pin is hardcoded."
    )
    hardcoded = re.findall(r'"mellea\[hooks\]>=[^"]+"', text)
    assert not hardcoded, (
        f"{target_path} still contains hardcoded mellea pin(s): {hardcoded}. "
        f"Use `f'\"{{MELLEA_PIN}}\"'` instead."
    )


def test_generate_step_template_matches_pin():
    """The mellea-fy-generate.md template rendered into compiled packages
    must carry the same pin as the compiler package itself."""
    text = (REPO_ROOT / ".claude/commands/mellea-fy-generate.md").read_text()
    # The template is markdown; just require the exact pin string appears.
    assert MELLEA_PIN in text, (
        f".claude/commands/mellea-fy-generate.md does not carry the current "
        f"MELLEA_PIN ({MELLEA_PIN!r}). Update the template."
    )
