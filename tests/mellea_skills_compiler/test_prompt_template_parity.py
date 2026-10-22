"""The pi prompt templates must stay identical to the Claude Code commands."""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE_COMMANDS = _REPO_ROOT / ".claude" / "commands"
_PI_PROMPTS = _REPO_ROOT / ".pi" / "prompts"


def test_same_templates_in_both_dirs():
    claude = {p.name for p in _CLAUDE_COMMANDS.glob("mellea-fy*.md")}
    pi = {p.name for p in _PI_PROMPTS.glob("mellea-fy*.md")}

    assert claude
    assert claude == pi


@pytest.mark.parametrize(
    "name", sorted(p.name for p in _CLAUDE_COMMANDS.glob("mellea-fy*.md"))
)
def test_template_is_identical(name):
    assert (_PI_PROMPTS / name).read_bytes() == (_CLAUDE_COMMANDS / name).read_bytes(), (
        f".pi/prompts/{name} differs from .claude/commands/{name}; edit both copies"
    )
