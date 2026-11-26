"""Enforce a single-source mellea dependency pin across the compiler.

If ``constants.MELLEA_PIN`` drifts from any of the six rendered locations
(root ``pyproject.toml``, the four export targets, or the generate-step
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

# Matches a hardcoded mellea requirement string in any quoting style, with or
# without extras, and with any PEP 440 comparison operator, e.g.
# "mellea[hooks]>=0.7", 'mellea==0.7', "mellea [hooks] ~= 0.7", "mellea<1".
HARDCODED_PIN_RE = re.compile(
    r"""['"]\s*mellea\s*(\[[^\]]*\])?\s*(===|==|~=|!=|>=|<=|>|<)"""
)


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
        "src/mellea_skills_compiler/export/targets/pi.py",
    ],
)
def test_export_targets_derive_pin_from_constant(target_path):
    text = (REPO_ROOT / target_path).read_text()
    # The four targets must import MELLEA_PIN and interpolate it — no
    # hardcoded ``mellea[hooks]>=...`` string may appear.
    assert "from mellea_skills_compiler.constants import MELLEA_PIN" in text, (
        f"{target_path} does not import MELLEA_PIN; the pin is hardcoded."
    )
    hardcoded = [m.group(0) for m in HARDCODED_PIN_RE.finditer(text)]
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


@pytest.mark.parametrize(
    "snippet",
    [
        '"mellea[hooks]>=0.7"',
        "'mellea[hooks]>=0.7'",
        '"mellea>=0.7"',
        "'mellea>=0.7'",
        '"mellea==0.7.1"',
        '"mellea===0.7.1"',
        '"mellea~=0.7"',
        '"mellea>=0.7,<0.8"',
        '"mellea<=0.7"',
        '"mellea!=0.6"',
        '"mellea<1"',
        '"mellea>0.6"',
        '"mellea[hooks,extra]==0.7"',
        "'mellea[hooks] ~= 0.7'",
        '" mellea >= 0.7"',
    ],
)
def test_hardcoded_pin_regex_detects_variants(snippet):
    assert HARDCODED_PIN_RE.search(snippet), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        'f"{MELLEA_PIN}"',
        '"mellea-skills-compiler>=0.1"',
        '"mellea"',
        "import mellea",
        '"not-mellea>=1"',
    ],
)
def test_hardcoded_pin_regex_ignores_non_pins(snippet):
    assert not HARDCODED_PIN_RE.search(snippet), snippet
