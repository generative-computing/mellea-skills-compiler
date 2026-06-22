"""Unit tests for mellea_skills_compiler.toolkit.file_utils module."""

import tempfile
from pathlib import Path

import pytest

from mellea_skills_compiler.toolkit.file_utils import (
    load_skill_pipeline,
    parse_spec_file,
)


class TestParseSkillMd:
    """Test cases for parse_spec_file function."""

    def test_parse_with_valid_frontmatter(self):
        """Test parsing a SKILL.md with valid YAML frontmatter."""
        content = """---
name: test-skill
description: A test skill
allowed-tools: Bash, Read, Write
---

This is the body of the skill."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_spec_file(path)

            assert result["frontmatter"]["name"] == "test-skill"
            assert result["frontmatter"]["description"] == "A test skill"
            assert result["frontmatter"]["allowed-tools"] == ["Bash", "Read", "Write"]
            assert result["body"] == "This is the body of the skill."
            assert str(path) in result["path"]
        finally:
            path.unlink()

    def test_parse_without_frontmatter(self):
        """Test parsing a file without frontmatter."""
        content = "This is just markdown content without frontmatter."

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_spec_file(path)

            assert result["frontmatter"] == {}
            assert result["body"] == content
            assert str(path) in result["path"]
        finally:
            path.unlink()

    def test_parse_allowed_tools_as_comma_separated_string(self):
        """Test parsing allowed-tools as comma-separated string."""
        content = """---
allowed-tools: "Bash, Read, Write, Glob"
---

Body content."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_spec_file(path)
            assert result["frontmatter"]["allowed-tools"] == [
                "Bash",
                "Read",
                "Write",
                "Glob",
            ]
        finally:
            path.unlink()

    def test_parse_allowed_tools_as_space_separated_string(self):
        """Test parsing allowed-tools as space-separated string without commas."""
        content = """---
allowed-tools: Bash Read Write
---

Body content."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_spec_file(path)
            assert result["frontmatter"]["allowed-tools"] == ["Bash", "Read", "Write"]
        finally:
            path.unlink()

    def test_parse_allowed_tools_as_list(self):
        """Test parsing allowed-tools as YAML list."""
        content = """---
allowed-tools:
  - Bash
  - Read
  - Write
---

Body content."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_spec_file(path)
            assert result["frontmatter"]["allowed-tools"] == ["Bash", "Read", "Write"]
        finally:
            path.unlink()

    def test_parse_openclaw_requires_bins(self):
        """Test that openclaw.requires.bins are added to allowed-tools."""
        content = """---
allowed-tools:
  - Bash
metadata:
  openclaw:
    requires:
      bins:
        - git
        - docker
      anyBins:
        - kubectl
---

Body content."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_spec_file(path)
            tools = result["frontmatter"]["allowed-tools"]
            assert "Bash" in tools
            assert "git" in tools
            assert "docker" in tools
            assert "kubectl" in tools
        finally:
            path.unlink()

    def test_parse_openclaw_no_duplicates(self):
        """Test that openclaw tools don't create duplicates."""
        content = """---
allowed-tools:
  - git
  - docker
metadata:
  openclaw:
    requires:
      bins:
        - git
        - docker
---

Body content."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_spec_file(path)
            tools = result["frontmatter"]["allowed-tools"]
            assert tools.count("git") == 1
            assert tools.count("docker") == 1
        finally:
            path.unlink()

    def test_parse_empty_frontmatter(self):
        """Test parsing with empty frontmatter section."""
        content = """Just a body."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_spec_file(path)
            # Empty frontmatter is parsed as None by yaml.safe_load, which becomes {}
            assert result["frontmatter"] == {} or result["frontmatter"] is None
            assert result["body"] == "Just a body."
        finally:
            path.unlink()

    def test_parse_malformed_yaml(self):
        """Test that malformed YAML in frontmatter raises an error."""
        content = """---
name: test
invalid yaml: [unclosed bracket
---

Body content."""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(Exception):  # yaml.YAMLError
                parse_spec_file(path)
        finally:
            path.unlink()


def _make_pipeline_package(root: Path, name: str, pipeline_source: str) -> Path:
    """Materialise a synthetic <name>/pipeline.py package under `root`.

    Returns the package directory (a child of `root` named `name`).
    """
    pkg_dir = root / name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "pipeline.py").write_text(pipeline_source)
    return pkg_dir


class TestLoadSkillPipeline:
    """Test cases for load_skill_pipeline — entry-point resolution.

    Regression target: skills with helper `run_*` functions defined alongside
    `run_pipeline` previously had the smoke check pick the alphabetically-
    first match (e.g. `run_assessment_method` < `run_pipeline`), which
    caused TypeError on the fixture's `user_input=...` kwargs because the
    helper had a different signature.
    """

    def test_prefers_run_pipeline_over_alphabetically_earlier_helper(self):
        """run_assessment_method sorts before run_pipeline; resolver must pick run_pipeline."""
        source = (
            "def run_assessment_method(org_context, refs):\n"
            "    return ('helper', org_context, refs)\n"
            "\n"
            "def run_pipeline(user_input, doc=''):\n"
            "    return ('canonical', user_input, doc)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg_dir = _make_pipeline_package(Path(tmp), "synthetic_a_helper_pkg", source)
            fn = load_skill_pipeline(pkg_dir)
            # The canonical entry point takes user_input by kwarg and returns the canonical marker
            assert fn.__name__ == "run_pipeline"
            assert fn(user_input="hello") == ("canonical", "hello", "")

    def test_falls_back_to_first_run_function_when_no_run_pipeline(self):
        """If pipeline.py only defines run_other, that's the entry point."""
        source = (
            "def run_assessment_method(arg):\n"
            "    return ('only-helper', arg)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg_dir = _make_pipeline_package(Path(tmp), "synthetic_no_canonical_pkg", source)
            fn = load_skill_pipeline(pkg_dir)
            assert fn.__name__ == "run_assessment_method"

    def test_prefers_run_pipeline_over_run_zzz_helper(self):
        """run_zzz sorts after run_pipeline; verifies the fix isn't accidentally a sort-direction flip."""
        source = (
            "def run_pipeline(user_input):\n"
            "    return ('canonical', user_input)\n"
            "\n"
            "def run_zzz_helper(x):\n"
            "    return ('helper', x)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pkg_dir = _make_pipeline_package(Path(tmp), "synthetic_z_helper_pkg", source)
            fn = load_skill_pipeline(pkg_dir)
            assert fn.__name__ == "run_pipeline"

    def test_prefers_local_run_pipeline_over_imported(self):
        """An imported run_* (e.g. from a sibling module) must not shadow a locally-defined run_pipeline."""
        source = (
            "from .helpers import run_helper  # noqa: F401\n"
            "\n"
            "def run_pipeline(user_input):\n"
            "    return ('canonical', user_input)\n"
        )
        helpers = "def run_helper(x):\n    return ('imported', x)\n"
        with tempfile.TemporaryDirectory() as tmp:
            pkg_dir = _make_pipeline_package(Path(tmp), "synthetic_with_import_pkg", source)
            (pkg_dir / "helpers.py").write_text(helpers)
            fn = load_skill_pipeline(pkg_dir)
            assert fn.__name__ == "run_pipeline"
            assert fn.__module__.endswith("pipeline")

    def test_raises_when_pipeline_module_missing(self):
        """Missing pipeline.py raises with a helpful message."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg_dir = Path(tmp) / "missing_pipeline_pkg"
            pkg_dir.mkdir()
            (pkg_dir / "__init__.py").write_text("")
            # No pipeline.py
            with pytest.raises(Exception, match="pipeline.py"):
                load_skill_pipeline(pkg_dir)

    def test_raises_when_no_run_function_defined(self):
        """A pipeline.py with no run_* function raises 'No run_* function found'."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg_dir = _make_pipeline_package(
                Path(tmp), "synthetic_no_run_pkg", "x = 1\n"
            )
            with pytest.raises(Exception, match="No run_"):
                load_skill_pipeline(pkg_dir)
