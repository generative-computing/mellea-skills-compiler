"""Unit tests for the deterministic config_writer.

The writer renders config_emission.json into a Python source string. Tests
exercise the category-grouping logic, the unknown-category tolerance path
(added 2026-05-26 after a real LLM emitted category='—'), and the value
representation choices.
"""

from __future__ import annotations

from mellea_skills_compiler.compile.writers import config_writer


def _load_writer():
    """Load config_writer.py as a module (it lives outside src/ on purpose)."""
    return config_writer


class TestConfigWriterRender:
    """Test cases for config_writer.render()."""

    def test_renders_basic_constants_in_category_order(self):
        writer = _load_writer()
        emission = {
            "constants": [
                {"name": "B_VAL", "value": "second", "type": "str", "category": "C8"},
                {"name": "A_VAL", "value": "first", "type": "str", "category": "C1"},
            ]
        }
        source = writer.render(emission)
        # C1 must appear before C8
        assert source.index("A_VAL") < source.index("B_VAL")
        # Section headers present
        assert "# === C1:" in source
        assert "# === C8:" in source

    def test_renders_ungrouped_constants_last(self):
        writer = _load_writer()
        emission = {
            "constants": [
                {"name": "LOOP_BUDGET", "value": 4, "type": "int"},
                {
                    "name": "MODEL_ID",
                    "value": "granite4.1:3b",
                    "type": "str",
                    "category": "C8",
                },
            ]
        }
        source = writer.render(emission)
        assert source.index("MODEL_ID") < source.index("LOOP_BUDGET")

    def test_tolerates_unknown_category_value(self):
        """LLM has been observed emitting placeholders like '—' for 'unclassified'.

        Previously raised `invalid literal for int() with base 10: ''` because
        the sort key called int(c[1:]) blindly. The writer should now treat
        unknown categories as a soft fallback and group them under their own
        raw-value section header without crashing.
        """
        writer = _load_writer()
        emission = {
            "constants": [
                {"name": "MODEL_ID", "value": "x", "type": "str", "category": "C8"},
                {
                    "name": "PRIORITY_LEVELS",
                    "value": "P1, P2, P3",
                    "type": "str",
                    "category": "—",
                },
                {"name": "BACKEND", "value": "ollama", "type": "str", "category": "C8"},
            ]
        }
        # Must not raise
        source = writer.render(emission)
        # All constants present
        assert "MODEL_ID" in source
        assert "BACKEND" in source
        assert "PRIORITY_LEVELS" in source
        # The unknown category gets a section header using its raw value
        assert "# === —" in source
        # Known C1..C9 categories sort before unknown ones
        assert source.index("MODEL_ID") < source.index("PRIORITY_LEVELS")

    def test_tolerates_arbitrary_string_category(self):
        """Any string category that doesn't match C[1-9] should sort lex after C-codes."""
        writer = _load_writer()
        emission = {
            "constants": [
                {"name": "X", "value": "1", "type": "str", "category": "C2"},
                {"name": "Y", "value": "2", "type": "str", "category": "misc"},
                {"name": "Z", "value": "3", "type": "str", "category": "C1"},
            ]
        }
        source = writer.render(emission)
        # Order: C1 (Z), C2 (X), misc (Y)
        assert source.index("Z: Final") < source.index("X: Final")
        assert source.index("X: Final") < source.index("Y: Final")

    def test_renders_provenance_comment(self):
        writer = _load_writer()
        emission = {
            "constants": [
                {
                    "name": "FOO",
                    "value": "bar",
                    "type": "str",
                    "category": "C1",
                    "provenance": {"source_file": "SKILL.md", "source_lines": "10-12"},
                },
            ]
        }
        source = writer.render(emission)
        assert "# PROVENANCE: SKILL.md:10-12" in source

    def test_multiline_string_uses_triple_quotes(self):
        writer = _load_writer()
        emission = {
            "constants": [
                {
                    "name": "PROMPT",
                    "value": "line 1\nline 2",
                    "type": "str",
                    "category": "C1",
                },
            ]
        }
        source = writer.render(emission)
        assert '"""line 1\nline 2"""' in source

    def test_falls_back_to_repr_when_string_contains_triple_quotes(self):
        writer = _load_writer()
        emission = {
            "constants": [
                {
                    "name": "DOCSTRING",
                    "value": 'has """triple""" quotes\nand newline',
                    "type": "str",
                    "category": "C1",
                },
            ]
        }
        # Must not raise. The triple-quote path is avoided; repr() is used.
        source = writer.render(emission)
        assert "DOCSTRING" in source
        assert "triple" in source
