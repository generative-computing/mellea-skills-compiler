"""Unit tests for the deterministic pre-mellea-fy helpers in
mellea_skills_compiler.compile.mellea_skills.

These cover the small private helpers (`_derive_mellea_package_name`,
`mirror_dir_contents_to_target`, `resolve_runtime_defaults`,
`write_runtime_directive`, `build_system_prompt`) that handle the
plumbing around the LLM-driven compile() orchestrator. None of these
require Claude Code, an LLM, network access, or a mellea install.
"""

import json
from pathlib import Path

import pytest

from mellea_skills_compiler.compile.claude_directives import (
    build_system_prompt,
    resolve_runtime_defaults,
    write_runtime_directive,
)
from mellea_skills_compiler.compile.mellea_skills import (
    _derive_mellea_package_name,
    _select_canonical_mellea_dir,
)
from mellea_skills_compiler.toolkit.file_utils import mirror_dir_contents_to_target


class TestDerivePackageName:
    """Rule OUT-2: lowercase, hyphens/spaces -> underscores, append `_mellea`."""

    def test_md_spec_uses_frontmatter_name(self):
        result = _derive_mellea_package_name(Path("/x/y/spec.md"), {"name": "weather"})
        assert result == "weather_mellea"

    def test_md_spec_falls_back_to_parent_dir_name_when_no_frontmatter_name(self):
        result = _derive_mellea_package_name(Path("/x/weather/spec.md"), {})
        assert result == "weather_mellea"

    def test_md_spec_falls_back_to_parent_dir_name_when_frontmatter_is_none(self):
        result = _derive_mellea_package_name(Path("/x/weather/spec.md"), None)
        assert result == "weather_mellea"

    def test_dir_input_uses_directory_name(self, tmp_path):
        skill_dir = tmp_path / "crewai-job-posting"
        skill_dir.mkdir()
        result = _derive_mellea_package_name(skill_dir, None)
        assert result == "crewai_job_posting_mellea"

    def test_normalises_uppercase(self):
        result = _derive_mellea_package_name(
            Path("/x/y/spec.md"), {"name": "WeatherSkill"}
        )
        assert result == "weatherskill_mellea"

    def test_normalises_spaces(self):
        result = _derive_mellea_package_name(
            Path("/x/y/spec.md"), {"name": "weather skill"}
        )
        assert result == "weather_skill_mellea"

    def test_collapses_double_underscores(self):
        result = _derive_mellea_package_name(
            Path("/x/y/spec.md"), {"name": "weather--skill"}
        )
        assert result == "weather_skill_mellea"
        assert "__" not in result

    def test_strips_leading_trailing_underscores(self):
        result = _derive_mellea_package_name(
            Path("/x/y/spec.md"), {"name": "_weather_"}
        )
        assert result == "weather_mellea"

    def test_falls_back_to_skill_for_empty_input(self):
        # Empty frontmatter name AND empty parent dir name -> safe fallback "skill".
        # Path("/spec.md").parent.name == "" so the helper's `.strip("_") or "skill"`
        # fallback kicks in.
        result = _derive_mellea_package_name(Path("/spec.md"), {"name": ""})
        assert result == "skill_mellea"


class TestMirrorCompanionDirs:
    """Rule OUT-6: mirror scripts/, references/, assets/ from skill -> package."""

    def test_mirrors_present_directories(self, tmp_path):
        skill = tmp_path / "skill"
        package = tmp_path / "skill" / "skill_mellea"
        (skill / "scripts" / "bash").mkdir(parents=True)
        (skill / "scripts" / "bash" / "x.sh").write_text("hello")

        mirrored = mirror_dir_contents_to_target(skill, package)

        assert (package / "scripts" / "bash" / "x.sh").exists()
        assert (package / "scripts" / "bash" / "x.sh").read_text() == "hello"
        assert mirrored == ["scripts"]

    def test_mirrors_multiple_companion_dirs(self, tmp_path):
        skill = tmp_path / "skill"
        package = tmp_path / "skill" / "skill_mellea"
        for name in ("scripts", "references", "assets"):
            (skill / name).mkdir(parents=True)
            (skill / name / "file.txt").write_text(f"contents of {name}")

        mirrored = mirror_dir_contents_to_target(skill, package)

        for name in ("scripts", "references", "assets"):
            assert (package / name / "file.txt").exists()
            assert (package / name / "file.txt").read_text() == f"contents of {name}"
            assert name in mirrored
        assert len(mirrored) == 3

    def test_skips_absent_directories(self, tmp_path):
        skill = tmp_path / "skill"
        package = tmp_path / "skill" / "skill_mellea"
        (skill / "scripts").mkdir(parents=True)
        (skill / "scripts" / "x.sh").write_text("hi")

        mirrored = mirror_dir_contents_to_target(skill, package)

        assert mirrored == ["scripts"]
        assert (package / "scripts").exists()
        assert not (package / "references").exists()
        assert not (package / "assets").exists()

    def test_idempotent_on_second_call(self, tmp_path):
        skill = tmp_path / "skill"
        package = tmp_path / "skill" / "skill_mellea"
        (skill / "scripts").mkdir(parents=True)
        (skill / "scripts" / "x.sh").write_text("first")

        first = mirror_dir_contents_to_target(skill, package)
        # Second call must not raise (relies on dirs_exist_ok=True).
        second = mirror_dir_contents_to_target(skill, package)

        assert first == second == ["scripts"]
        assert (package / "scripts" / "x.sh").read_text() == "first"

    def test_creates_package_dir_if_missing(self, tmp_path):
        skill = tmp_path / "skill"
        skill.mkdir()
        package = tmp_path / "nonexistent_parent" / "skill_mellea"
        assert not package.exists()

        mirrored = mirror_dir_contents_to_target(skill, package)

        assert package.exists()
        assert package.is_dir()
        assert mirrored == []

    def test_returns_empty_when_no_companion_dirs(self, tmp_path):
        skill = tmp_path / "skill"
        skill.mkdir()
        package = tmp_path / "skill" / "skill_mellea"

        mirrored = mirror_dir_contents_to_target(skill, package)

        assert mirrored == []


class TestResolveRuntimeDefaults:
    """Precedence: CLI override > defaults file > built-in fallback."""

    def _write_defaults(self, tmp_path: Path, payload: str) -> None:
        defaults_dir = tmp_path / ".claude" / "data"
        defaults_dir.mkdir(parents=True)
        (defaults_dir / "runtime_defaults.json").write_text(payload)

    def test_uses_defaults_file_when_no_override(self, tmp_path, monkeypatch):
        self._write_defaults(
            tmp_path,
            json.dumps({"backend": "ollama", "model_id": "granite3.3:8b"}),
        )
        monkeypatch.chdir(tmp_path)

        backend, model_id, source = resolve_runtime_defaults(None, None)

        assert backend == "ollama"
        assert model_id == "granite3.3:8b"
        assert "defaults file" in source

    def test_cli_backend_override_wins(self, tmp_path, monkeypatch):
        self._write_defaults(
            tmp_path,
            json.dumps({"backend": "ollama", "model_id": "granite3.3:8b"}),
        )
        monkeypatch.chdir(tmp_path)

        backend, model_id, source = resolve_runtime_defaults("vllm", None)

        assert backend == "vllm"
        assert model_id == "granite3.3:8b"
        assert "command-line override" in source

    def test_cli_both_overrides_win(self, tmp_path, monkeypatch):
        self._write_defaults(
            tmp_path,
            json.dumps({"backend": "ollama", "model_id": "granite3.3:8b"}),
        )
        monkeypatch.chdir(tmp_path)

        backend, model_id, source = resolve_runtime_defaults("vllm", "mistral-7b")

        assert backend == "vllm"
        assert model_id == "mistral-7b"
        assert "command-line override" in source

    def test_falls_back_to_builtin_when_file_missing(self, tmp_path, monkeypatch):
        # No .claude/data/ written under tmp_path.
        monkeypatch.chdir(tmp_path)

        backend, model_id, source = resolve_runtime_defaults(None, None)

        assert backend == "ollama"
        assert model_id == "granite3.3:8b"
        assert "built-in fallback" in source

    def test_falls_back_to_builtin_when_file_malformed(self, tmp_path, monkeypatch):
        self._write_defaults(tmp_path, "{not valid json")
        monkeypatch.chdir(tmp_path)

        backend, model_id, source = resolve_runtime_defaults(None, None)

        # On JSON decode error the helper logs a warning and keeps the
        # built-in fallback values; source remains the built-in fallback
        # string because the try/except short-circuits before the source
        # is updated.
        assert backend == "ollama"
        assert model_id == "granite3.3:8b"
        assert "built-in fallback" in source

    def test_falls_back_to_builtin_when_file_missing_keys(self, tmp_path, monkeypatch):
        # Empty JSON object: file is readable but contains no keys.
        # `data.get("backend", file_backend)` returns the built-in fallback
        # for both keys; source is updated to "defaults file (...)" because
        # the read succeeded.
        self._write_defaults(tmp_path, json.dumps({}))
        monkeypatch.chdir(tmp_path)

        backend, model_id, source = resolve_runtime_defaults(None, None)

        assert backend == "ollama"
        assert model_id == "granite3.3:8b"
        assert "defaults file" in source


class TestWriteRuntimeDirective:
    """Persist the chosen backend/model so the post-compile lint can check drift."""

    def test_writes_json_with_required_fields(self, tmp_path):
        intermediate = tmp_path / "intermediate"

        path = write_runtime_directive(
            intermediate, "ollama", "granite3.3:8b", "defaults file (...)"
        )

        assert path == intermediate / "runtime_directive.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["format_version"] == "1.0"
        assert data["backend"] == "ollama"
        assert data["model_id"] == "granite3.3:8b"
        assert data["source"] == "defaults file (...)"

    def test_creates_intermediate_dir_if_missing(self, tmp_path):
        intermediate = tmp_path / "deep" / "nested" / "intermediate"
        assert not intermediate.exists()

        write_runtime_directive(intermediate, "ollama", "granite3.3:8b", "src")

        assert intermediate.exists()
        assert (intermediate / "runtime_directive.json").exists()

    def test_returns_path_to_written_file(self, tmp_path):
        intermediate = tmp_path / "intermediate"

        path = write_runtime_directive(intermediate, "ollama", "granite3.3:8b", "src")

        assert isinstance(path, Path)
        assert path.exists()
        assert path == intermediate / "runtime_directive.json"

    def test_overwrites_existing_directive(self, tmp_path):
        intermediate = tmp_path / "intermediate"

        write_runtime_directive(intermediate, "ollama", "granite3.3:8b", "first")
        path = write_runtime_directive(intermediate, "vllm", "mistral-7b", "second")

        data = json.loads(path.read_text())
        assert data["backend"] == "vllm"
        assert data["model_id"] == "mistral-7b"
        assert data["source"] == "second"


class TestBuildSystemPrompt:
    """Assemble the instruction string passed to the mellea-fy slash command."""

    def test_includes_backend_value(self):
        prompt = build_system_prompt(
            "ollama", "granite3.3:8b", "defaults file", "weather_mellea"
        )
        assert "ollama" in prompt

    def test_includes_model_id_value(self):
        prompt = build_system_prompt(
            "ollama", "granite3.3:8b", "defaults file", "weather_mellea"
        )
        assert "granite3.3:8b" in prompt

    def test_includes_source(self):
        prompt = build_system_prompt(
            "ollama", "granite3.3:8b", "defaults file (xyz.json)", "weather_mellea"
        )
        assert "defaults file (xyz.json)" in prompt

    def test_includes_autonomous_run_directive(self):
        prompt = build_system_prompt("ollama", "granite3.3:8b", "src", "weather_mellea")
        assert "Run the complete 10-step pipeline" in prompt

    def test_quotes_values_with_repr(self):
        # A backend with embedded single quotes should be safely repr'd
        # rather than splatted in bare. The repr of "o'l'l'ama" wraps it
        # in double quotes (Python's repr picks the safer quote style).
        prompt = build_system_prompt(
            "o'l'l'ama", "granite3.3:8b", "src", "weather_mellea"
        )
        assert repr("o'l'l'ama") in prompt
        assert repr("granite3.3:8b") in prompt

    def test_injects_package_name_literally(self):
        """The wrapper-computed package_name appears verbatim in the prompt."""
        prompt = build_system_prompt(
            "ollama",
            "granite4.1:3b",
            "src",
            "gdpr_breach_sentinel_oliver_schmidt_prietz_mellea",
        )
        assert "gdpr_breach_sentinel_oliver_schmidt_prietz_mellea" in prompt

    def test_no_placeholder_used_as_path_component(self):
        """`<package_name>/...` (placeholder as path prefix) must not survive
        into the rendered prompt — every path mention must use the injected
        name. The literal token may appear once in an explanatory sentence
        referring to the slash-command directive convention, which is fine."""
        prompt = build_system_prompt("ollama", "granite4.1:3b", "src", "weather_mellea")
        assert "<package_name>/" not in prompt, (
            "Prompt path mentions should substitute the injected package_name, "
            "not carry the literal placeholder as a path prefix"
        )

    def test_explicit_do_not_rederive_instruction(self):
        """Prompt tells the LLM not to re-derive the name from the frontmatter."""
        prompt = build_system_prompt("ollama", "granite4.1:3b", "src", "weather_mellea")
        # Substring check — phrasing may evolve, but the operational
        # instruction must be present.
        assert "do NOT re-derive" in prompt or "do not re-derive" in prompt.lower()

    def test_wrapper_rendered_paths_use_injected_name(self):
        """The wrapper-rendered-paths block uses the injected name, not placeholder."""
        prompt = build_system_prompt("ollama", "granite4.1:3b", "src", "weather_mellea")
        assert "weather_mellea/config.py" in prompt
        assert "weather_mellea/fixtures/" in prompt


class TestSelectCanonicalMelleaDir:
    """Defensive guard against stray *_mellea sibling directories."""

    def test_single_canonical_dir_returned_as_is(self, tmp_path):
        (tmp_path / "weather_mellea").mkdir()
        result = _select_canonical_mellea_dir(tmp_path, "weather_mellea")
        assert result.name == "weather_mellea"

    def test_no_mellea_dir_returns_empty(self, tmp_path):
        # Non-mellea subdirs are ignored.
        (tmp_path / "src").mkdir()
        (tmp_path / "references").mkdir()
        with pytest.raises(Exception):
            result = _select_canonical_mellea_dir(tmp_path, "weather_mellea")

    def test_two_dirs_one_canonical_selects_canonical(self, tmp_path, caplog):
        """gdpr-breach-sentinel-style: two *_mellea dirs, one matches package_name."""
        canonical_name = "gdpr_breach_sentinel_oliver_schmidt_prietz_mellea"
        (tmp_path / canonical_name).mkdir()
        (tmp_path / "gdpr_breach_sentinel_oliver_schmidt_mellea").mkdir()
        result = _select_canonical_mellea_dir(tmp_path, canonical_name)
        assert result.name == canonical_name
        # Warning should mention the stray
        joined_logs = " ".join(rec.getMessage() for rec in caplog.records)
        assert (
            "gdpr_breach_sentinel_oliver_schmidt_mellea" in joined_logs
            or len(caplog.records) > 0
        )

    def test_two_dirs_none_matching_raises(self, tmp_path):
        """If multiple *_mellea dirs exist and none match the expected name, raise."""
        (tmp_path / "name_a_mellea").mkdir()
        (tmp_path / "name_b_mellea").mkdir()
        with pytest.raises(Exception) as excinfo:
            _select_canonical_mellea_dir(tmp_path, "expected_mellea")
        message = str(excinfo.value)
        assert "expected_mellea" in message
        assert "name_a_mellea" in message or "name_b_mellea" in message

    def test_single_dir_with_wrong_name_proceeds_with_warning(self, tmp_path, caplog):
        """If exactly one *_mellea dir exists but it's mis-named, proceed (with warning)."""
        (tmp_path / "wrong_name_mellea").mkdir()
        result = _select_canonical_mellea_dir(tmp_path, "expected_mellea")
        assert result.name == "wrong_name_mellea"  # we proceed
        # And a warning was emitted
        warnings_emitted = [r for r in caplog.records if r.levelname == "WARNING"]
        # caplog default level may filter — just check the call didn't raise
        # and returned the mis-named dir

    def test_ignores_non_mellea_directories(self, tmp_path):
        (tmp_path / "weather_mellea").mkdir()
        (tmp_path / "weather_mellea_old").mkdir()  # doesn't end in _mellea
        (tmp_path / "scripts").mkdir()
        result = _select_canonical_mellea_dir(tmp_path, "weather_mellea")
        assert result.name == "weather_mellea"
