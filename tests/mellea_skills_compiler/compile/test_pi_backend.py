"""Unit tests for PiBackend implementation.

Tests the pi backend's environment validation, compilation workflow,
and error handling without requiring the actual pi CLI or credentials.
"""

import json
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from mellea_skills_compiler.compile.backend import CompilationContext, CompilationResult
from mellea_skills_compiler.compile.backends.pi import (
    PiBackend,
    _lock_protected_paths,
    _render_prompt_templates,
    _resolve_provider_and_model,
    _unlock_protected_paths,
)
from mellea_skills_compiler.enums import PiMessageType


@pytest.fixture
def backend():
    """Create a PiBackend instance for testing."""
    return PiBackend()


@pytest.fixture
def mock_context(tmp_path):
    """Create a mock CompilationContext for testing."""
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test Skill\n\nA test skill specification.")

    package_dir = tmp_path / "output"
    package_dir.mkdir()

    intermediate_dir = package_dir / "intermediate"
    intermediate_dir.mkdir()

    return CompilationContext(
        spec_path=spec_path,
        package_dir=package_dir,
        intermediate_dir=intermediate_dir,
        model="anthropic/claude-opus-4-7",
        timeout=300,
        repair_mode=False,
        skill_backend="anthropic",
        skill_model="claude-3-5-sonnet-20241022",
        refresh_cache=False,
    )


def _pi_event_line(event: dict) -> str:
    return json.dumps(event) + "\n"


class TestBackendMetadata:
    """Test backend metadata methods."""

    def test_identifier(self, backend):
        assert backend.identifier() == "pi"

    def test_name(self, backend):
        assert backend.name() == "Pi"

    def test_supports_repair_mode(self, backend):
        assert backend.supports_repair_mode() is True


class TestValidateEnvironment:
    """Test environment validation logic."""

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.run")
    def test_validate_environment_success(self, mock_run, mock_which, backend):
        mock_which.return_value = "/usr/local/bin/pi"
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps(
                {"status": "ready", "provider": "anthropic", "authType": "api_key"}
            ),
            stderr="",
        )

        is_valid, error = backend.validate_environment()

        assert is_valid is True
        assert error is None

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which")
    def test_validate_environment_missing_pi_cli(self, mock_which, backend):
        mock_which.return_value = None

        is_valid, error = backend.validate_environment()

        assert is_valid is False
        assert error is not None
        assert "pi CLI not found" in error

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.run")
    def test_validate_environment_not_ready(self, mock_run, mock_which, backend):
        mock_which.return_value = "/usr/local/bin/pi"
        mock_run.return_value = Mock(
            returncode=1,
            stdout=json.dumps(
                {
                    "status": "not_ready",
                    "provider": "anthropic",
                    "reason": "credentials_not_configured",
                }
            ),
            stderr="",
        )

        is_valid, error = backend.validate_environment()

        assert is_valid is False
        assert error is not None
        assert "credentials_not_configured" in error

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.run")
    def test_validate_environment_malformed_output(self, mock_run, mock_which, backend):
        mock_which.return_value = "/usr/local/bin/pi"
        mock_run.return_value = Mock(returncode=1, stdout="not json", stderr="boom")

        is_valid, error = backend.validate_environment()

        assert is_valid is False
        assert error is not None

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.run")
    def test_validate_environment_uses_default_provider(self, mock_run, mock_which, backend):
        mock_which.return_value = "/usr/local/bin/pi"
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps(
                {"status": "ready", "provider": "anthropic", "authType": "api_key"}
            ),
            stderr="",
        )

        backend.validate_environment()

        args = mock_run.call_args[0][0]
        assert args == ["/usr/local/bin/pi", "auth", "check", "--provider", "anthropic", "--json"]

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.run")
    def test_validate_environment_uses_supplied_provider(self, mock_run, mock_which, backend):
        mock_which.return_value = "/usr/local/bin/pi"
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps(
                {"status": "ready", "provider": "ollama", "authType": "none"}
            ),
            stderr="",
        )

        backend.validate_environment(provider="ollama")

        args = mock_run.call_args[0][0]
        assert args == ["/usr/local/bin/pi", "auth", "check", "--provider", "ollama", "--json"]

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.run")
    def test_validate_environment_not_ready_reports_supplied_provider(
        self, mock_run, mock_which, backend
    ):
        mock_which.return_value = "/usr/local/bin/pi"
        mock_run.return_value = Mock(
            returncode=1,
            stdout=json.dumps(
                {
                    "status": "not_ready",
                    "provider": "ollama",
                    "reason": "credentials_not_configured",
                }
            ),
            stderr="",
        )

        is_valid, error = backend.validate_environment(provider="ollama")

        assert is_valid is False
        assert "provider 'ollama'" in error


class TestCompileMethod:
    """Test the compile() workflow."""

    @pytest.fixture(autouse=True)
    def _patch_compile_deps(self):
        """Suppress side-effectful helpers that are not under test."""
        with (
            patch(
                "mellea_skills_compiler.compile.backends.pi._get_default_settings",
                return_value={},
            ),
            patch(
                "mellea_skills_compiler.compile.backends.pi.CompileMetadata.record_backend"
            ),
        ):
            yield

    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
    def test_compile_success(self, mock_popen, backend, mock_context):
        events = [
            _pi_event_line({"type": "session", "id": "s1"}),
            _pi_event_line({"type": "agent_start"}),
            _pi_event_line({"type": "turn_start"}),
            _pi_event_line(
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Compilation complete."}],
                    },
                }
            ),
            _pi_event_line({"type": "turn_end", "message": {"role": "assistant"}}),
            _pi_event_line({"type": "agent_end", "messages": []}),
            _pi_event_line({"type": "agent_settled"}),
            "",
        ]

        (mock_context.intermediate_dir / "classification.json").write_text("{}")

        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = events
        mock_process.stderr.readline.side_effect = [""]
        mock_process.poll.side_effect = [None] * (len(events) - 1) + [0]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        result = backend.compile(mock_context)

        assert result.success is True
        assert result.package_dir == mock_context.package_dir
        assert result.error_message is None

    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
    def test_compile_passes_system_prompt(self, mock_popen, backend, mock_context):
        """compile() appends the pi-specific directive so pi runs all steps

        without pausing and emits *_emission.json instead of writing
        wrapper-rendered paths directly (mirrors ClaudeCodeBackend's
        --append-system-prompt usage).
        """
        (mock_context.intermediate_dir / "classification.json").write_text("{}")

        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = [""]
        mock_process.stderr.readline.side_effect = [""]
        mock_process.poll.side_effect = [0]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        backend.compile(mock_context)

        argv = mock_popen.call_args[0][0]
        assert "--append-system-prompt" in argv
        prompt_idx = argv.index("--append-system-prompt")
        system_prompt = argv[prompt_idx + 1]
        assert "Do NOT pause" in system_prompt
        assert str(mock_context.package_dir) in system_prompt

    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
    def test_compile_nonzero_exit(self, mock_popen, backend, mock_context):
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = [""]
        mock_process.stderr.readline.side_effect = [""]
        mock_process.poll.side_effect = [0]
        mock_process.wait.return_value = 1
        mock_popen.return_value = mock_process

        result = backend.compile(mock_context)

        assert result.success is False
        assert result.error_message is not None
        assert "return code 1" in result.error_message

    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
    def test_compile_exit_zero_without_classification_fails(
        self, mock_popen, backend, mock_context
    ):
        """Pi exiting 0 without producing classification.json is not success

        (e.g. pi stopped to ask a clarifying question instead of compiling).
        """
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = [""]
        mock_process.stderr.readline.side_effect = [""]
        mock_process.poll.side_effect = [0]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        result = backend.compile(mock_context)

        assert result.success is False
        assert "classification.json" in result.error_message

    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
    def test_compile_timeout(self, mock_popen, backend, mock_context):
        mock_context.timeout = 0.01

        mock_process = MagicMock()

        def slow_readline():
            import time as _time

            _time.sleep(0.05)
            return ""

        mock_process.stdout.readline.side_effect = slow_readline
        mock_process.stderr.readline.side_effect = [""]
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        result = backend.compile(mock_context)

        assert result.success is False
        assert "timeout" in result.error_message.lower()

    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
    def test_compile_repair_mode_with_prior_output_uses_repair_command(
        self, mock_popen, backend, mock_context
    ):
        """Repair mode invokes /mellea-fy-repair when there is something to resume."""
        (mock_context.intermediate_dir / "classification.json").write_text("{}")
        mock_context.repair_mode = True
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = [""]
        mock_process.stderr.readline.side_effect = [""]
        mock_process.poll.side_effect = [0]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        backend.compile(mock_context)

        argv = mock_popen.call_args[0][0]
        assert "/mellea-fy-repair" in " ".join(argv)

    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
    def test_compile_repair_mode_with_nothing_to_resume_uses_fresh_command(
        self, mock_popen, backend, mock_context
    ):
        """Repair mode falls back to /mellea-fy when nothing was ever compiled.

        Pi sometimes pauses to ask a clarifying question when
        /mellea-fy-repair's Step-0 routing entry names /mellea-fy-classify as
        the resume sub-command in one-shot mode, instead of proceeding
        automatically as the template instructs. Routing to /mellea-fy
        directly for this case sidesteps that pause.
        """
        mock_context.repair_mode = True
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = [""]
        mock_process.stderr.readline.side_effect = [""]
        mock_process.poll.side_effect = [0]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        backend.compile(mock_context)

        argv = mock_popen.call_args[0][0]
        joined = " ".join(argv)
        assert "/mellea-fy-repair" not in joined
        assert "/mellea-fy " in joined or joined.endswith("/mellea-fy")


class TestPiExecutable:
    """pi is an npm shim; on Windows that's pi.cmd, which needs a full path."""

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which")
    def test_build_pi_argv_uses_resolved_executable(self, mock_which, backend, tmp_path):
        mock_which.return_value = r"C:\Users\u\AppData\Roaming\npm\pi.CMD"
        argv = backend._build_pi_argv(spec_path=tmp_path / "spec.md", repair_mode=False, model=None)

        assert argv[0] == r"C:\Users\u\AppData\Roaming\npm\pi.CMD"

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.run")
    def test_auth_check_uses_resolved_executable(self, mock_run, mock_which, backend):
        mock_which.return_value = r"C:\Users\u\AppData\Roaming\npm\pi.CMD"
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps({"status": "ready"}), stderr="")

        backend.validate_environment()

        assert mock_run.call_args[0][0][0] == r"C:\Users\u\AppData\Roaming\npm\pi.CMD"


class TestHelperMethods:
    """Test argv-building helper."""

    @patch("mellea_skills_compiler.compile.backends.pi.shutil.which", return_value=None)
    def test_build_pi_argv_normal_mode(self, _mock_which, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(spec_path=spec_path, repair_mode=False, model=None)

        assert argv[0] == "pi"
        assert "-p" in argv
        assert "--mode" in argv
        assert "json" in argv
        assert any("/mellea-fy" in part and str(spec_path) in part for part in argv)

    def test_build_pi_argv_includes_approve_flag(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(spec_path=spec_path, repair_mode=False, model=None)

        assert "--approve" in argv

    def test_build_pi_argv_uses_lowercase_tool_names(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(spec_path=spec_path, repair_mode=False, model=None)

        assert "--tools" in argv
        tools_index = argv.index("--tools")
        assert argv[tools_index + 1] == "read,write,edit,ls,find,grep"

    def test_build_pi_argv_repair_mode(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(spec_path=spec_path, repair_mode=True, model=None)

        assert any("/mellea-fy-repair" in part for part in argv)

    def test_build_pi_argv_with_model(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(
            spec_path=spec_path, repair_mode=False, model="anthropic/claude-opus-4-7"
        )

        assert "--model" in argv
        assert "anthropic/claude-opus-4-7" in argv

    def test_build_pi_argv_with_provider(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(
            spec_path=spec_path, repair_mode=False, model=None, provider="ollama"
        )

        assert "--provider" in argv
        provider_idx = argv.index("--provider")
        assert argv[provider_idx + 1] == "ollama"

    def test_build_pi_argv_with_system_prompt(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(
            spec_path=spec_path,
            repair_mode=False,
            model=None,
            system_prompt="Do NOT pause between steps.",
        )

        assert "--append-system-prompt" in argv
        prompt_idx = argv.index("--append-system-prompt")
        assert argv[prompt_idx + 1] == "Do NOT pause between steps."

    def test_build_pi_argv_without_system_prompt_omits_flag(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(
            spec_path=spec_path, repair_mode=False, model=None, system_prompt=None
        )

        assert "--append-system-prompt" not in argv

    def test_build_pi_argv_without_provider_omits_flag(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(
            spec_path=spec_path, repair_mode=False, model=None, provider=None
        )

        assert "--provider" not in argv

    def test_build_pi_argv_with_provider_and_model(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(
            spec_path=spec_path,
            repair_mode=False,
            model="llama3",
            provider="ollama",
        )

        assert "--provider" in argv
        assert "--model" in argv
        provider_idx = argv.index("--provider")
        model_idx = argv.index("--model")
        assert argv[provider_idx + 1] == "ollama"
        assert argv[model_idx + 1] == "llama3"

    def test_build_pi_argv_with_prompts_dir(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        prompts_dir = tmp_path / "prompts"
        argv = backend._build_pi_argv(
            spec_path=spec_path, repair_mode=False, model=None, prompts_dir=prompts_dir
        )

        assert "--no-prompt-templates" in argv
        template_idx = argv.index("--prompt-template")
        assert argv[template_idx + 1] == str(prompts_dir)

    def test_build_pi_argv_without_prompts_dir_omits_flags(self, backend, tmp_path):
        spec_path = tmp_path / "spec.md"
        argv = backend._build_pi_argv(spec_path=spec_path, repair_mode=False, model=None)

        assert "--no-prompt-templates" not in argv
        assert "--prompt-template" not in argv


class TestRenderPromptTemplates:
    """Tests for _render_prompt_templates path substitution."""

    def test_substitutes_intermediate_paths(self, tmp_path, monkeypatch):
        src = tmp_path / ".pi" / "prompts"
        src.mkdir(parents=True)
        (src / "mellea-fy-classify.md").write_text(
            "Output `intermediate/classification.json` now.\n"
            "Compare against `<package_name>/intermediate/runtime_directive.json`.\n"
            "Locate `<package_dir>/intermediate/` and `<name>_mellea/intermediate/`.\n"
        )
        (src / "other.md").write_text("`intermediate/x.json`")
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "out"
        out.mkdir()

        _render_prompt_templates(Path("skills/foo/foo_mellea"), out)

        text = (out / "mellea-fy-classify.md").read_text()
        assert "`skills/foo/foo_mellea/intermediate/classification.json`" in text
        assert "`skills/foo/foo_mellea/intermediate/runtime_directive.json`" in text
        assert "`skills/foo/foo_mellea/intermediate/` and `skills/foo/foo_mellea/intermediate/`" in text
        assert "<package_name>" not in text
        assert not (out / "other.md").exists()

    def test_substitutes_package_dir_paths(self, tmp_path, monkeypatch):
        src = tmp_path / ".pi" / "prompts"
        src.mkdir(parents=True)
        (src / "mellea-fy-artifacts.md").write_text(
            "Step 6 files are written inside `<package_name>/`.\n"
            "Write `<package_dir>/melleafy.json`.\n"
            "Repair accepts any compiled package (`<name>_mellea/`).\n"
        )
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "out"
        out.mkdir()

        _render_prompt_templates(Path("skills/foo/foo_mellea"), out)

        text = (out / "mellea-fy-artifacts.md").read_text()
        assert "inside `skills/foo/foo_mellea/`" in text
        assert "`skills/foo/foo_mellea/melleafy.json`" in text
        assert "`<name>_mellea/`" in text

    def test_makes_claude_paths_absolute(self, tmp_path, monkeypatch):
        src = tmp_path / ".pi" / "prompts"
        src.mkdir(parents=True)
        (src / "mellea-fy-classify.md").write_text(
            "Conform to `.claude/schemas/classification.schema.json`."
        )
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "out"
        out.mkdir()

        _render_prompt_templates(Path("skills/foo/foo_mellea"), out)

        expected = f"`{(tmp_path / '.claude').resolve().as_posix()}/schemas/classification.schema.json`"
        assert expected in (out / "mellea-fy-classify.md").read_text()

    def test_leaves_unquoted_references_alone(self, tmp_path, monkeypatch):
        src = tmp_path / ".pi" / "prompts"
        src.mkdir(parents=True)
        tree = "```\npkg/\n    └── intermediate/\n```\n[REPAIR] Removing intermediate/x.json\n"
        (src / "mellea-fy.md").write_text(tree)
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "out"
        out.mkdir()

        _render_prompt_templates(Path("skills/foo/foo_mellea"), out)

        assert (out / "mellea-fy.md").read_text() == tree

    def test_rendered_templates_are_read_only(self, tmp_path, monkeypatch):
        src = tmp_path / ".pi" / "prompts"
        src.mkdir(parents=True)
        (src / "mellea-fy-classify.md").write_text("spec")
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "out"
        out.mkdir()

        _render_prompt_templates(Path("skills/foo/foo_mellea"), out)

        with pytest.raises(PermissionError):
            (out / "mellea-fy-classify.md").write_text("overwritten")
        with pytest.raises(PermissionError):
            (out / "mellea-fy-new.md").write_text("new")
        out.chmod(0o700)


def _assistant_end(stop_reason=None, error_message=None):
    message = {"role": "assistant", "content": [{"type": "text", "text": "step"}]}
    if stop_reason:
        message["stopReason"] = stop_reason
    if error_message:
        message["errorMessage"] = error_message
    return _pi_event_line({"type": "message_end", "message": message})


@patch("mellea_skills_compiler.compile.backends.pi.CompileMetadata.record_backend")
@patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
class TestProviderErrorHandling:
    """Only an error on pi's final assistant message fails the compile."""

    def _run(self, mock_popen, backend, mock_context, events):
        events = events + [_pi_event_line({"type": "agent_settled"}), ""]
        (mock_context.intermediate_dir / "classification.json").write_text("{}")
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = events
        mock_process.stderr.readline.side_effect = [""]
        mock_process.poll.side_effect = [None] * (len(events) - 1) + [0]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        return backend.compile(mock_context)

    def test_recovered_provider_error_succeeds(
        self, mock_popen, _record, backend, mock_context
    ):
        result = self._run(
            mock_popen,
            backend,
            mock_context,
            [
                _assistant_end("error", "Stream ended without finish_reason"),
                _assistant_end(),
            ],
        )

        assert result.success is True

    def test_final_provider_error_fails(self, mock_popen, _record, backend, mock_context):
        result = self._run(
            mock_popen,
            backend,
            mock_context,
            [_assistant_end(), _assistant_end("error", "401 invalid x-api-key")],
        )

        assert result.success is False
        assert "401 invalid x-api-key" in result.error_message


class TestResolveProviderAndModel:
    """--provider without --model is filled in from pi's settings."""

    SETTINGS = {"defaultProvider": "anthropic-proxy", "defaultModel": "claude-sonnet-4-6"}

    def test_default_provider_gets_default_model(self, capsys):
        assert _resolve_provider_and_model("anthropic-proxy", None, self.SETTINGS) == (
            "anthropic-proxy",
            "claude-sonnet-4-6",
        )
        assert "doesn't match" not in capsys.readouterr().out

    def test_other_provider_falls_back_to_defaults_with_notice(self, capsys):
        assert _resolve_provider_and_model("anthropic", None, self.SETTINGS) == (
            "anthropic-proxy",
            "claude-sonnet-4-6",
        )
        out = " ".join(capsys.readouterr().out.split())
        assert "--provider anthropic doesn't match your default provider anthropic-proxy" in out
        assert "please provide a --model too" in out

    @pytest.mark.parametrize(
        "provider, model, settings",
        [
            ("ollama", "llama3", SETTINGS),
            (None, None, SETTINGS),
            (None, "claude-opus-4-7", SETTINGS),
            ("anthropic", None, {}),
            ("anthropic", None, {"defaultProvider": "anthropic"}),
        ],
    )
    def test_left_unchanged(self, provider, model, settings):
        assert _resolve_provider_and_model(provider, model, settings) == (provider, model)

    @patch("mellea_skills_compiler.compile.backends.pi.CompileMetadata.record_backend")
    @patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
    @patch(
        "mellea_skills_compiler.compile.backends.pi._get_default_settings",
        return_value=SETTINGS,
    )
    def test_compile_passes_resolved_model_to_pi(
        self, _settings, mock_popen, _record, backend, mock_context
    ):
        mock_context.provider = "anthropic-proxy"
        mock_context.model = None
        (mock_context.intermediate_dir / "classification.json").write_text("{}")
        events = [_assistant_end(), _pi_event_line({"type": "agent_settled"}), ""]
        mock_process = MagicMock()
        mock_process.stdout.readline.side_effect = events
        mock_process.stderr.readline.side_effect = [""]
        mock_process.poll.side_effect = [None] * (len(events) - 1) + [0]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        backend.compile(mock_context)

        argv = mock_popen.call_args[0][0]
        assert argv[argv.index("--provider") + 1] == "anthropic-proxy"
        assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"


class TestProtectedPathLock:
    """Tests for the read-only paths during a pi run."""

    @pytest.fixture
    def package_dir(self, tmp_path):
        package_dir = tmp_path / "skill" / "skill_mellea"
        (package_dir / "intermediate").mkdir(parents=True)
        return package_dir

    def test_lock_blocks_writes_and_unlock_removes_placeholders(self, package_dir):
        created = _lock_protected_paths(package_dir)

        with pytest.raises(PermissionError):
            (package_dir / "config.py").write_text("BACKEND = 'x'")
        with pytest.raises(PermissionError):
            (package_dir / "fixtures" / "case.py").write_text("x")

        _unlock_protected_paths(created)

        assert not (package_dir / "config.py").exists()
        assert not (package_dir / "fixtures").exists()

    def test_unlock_keeps_and_restores_existing_paths(self, package_dir):
        (package_dir / "config.py").write_text("BACKEND = 'ollama'")
        (package_dir / "fixtures").mkdir()
        (package_dir / "fixtures" / "case.py").write_text("x")

        created = _lock_protected_paths(package_dir)
        assert created[package_dir / "config.py"] is not None
        with pytest.raises(PermissionError):
            (package_dir / "config.py").write_text("overwritten")

        _unlock_protected_paths(created)

        (package_dir / "config.py").write_text("BACKEND = 'ollama'")
        (package_dir / "fixtures" / "new.py").write_text("x")
        assert (package_dir / "fixtures" / "case.py").read_text() == "x"

    def test_pipeline_written_intermediates_are_read_only(self, package_dir):
        directive = package_dir / "intermediate" / "runtime_directive.json"
        directive.write_text('{"backend": "ollama"}')

        created = _lock_protected_paths(package_dir)

        with pytest.raises(PermissionError):
            directive.write_text('{"BACKEND": "ollama"}')
        (package_dir / "intermediate" / "classification.json").write_text("{}")

        _unlock_protected_paths(created)

        assert directive.read_text() == '{"backend": "ollama"}'
        directive.write_text('{"backend": "ollama", "source": "x"}')

    def test_skill_root_intermediate_is_blocked_then_removed(self, package_dir):
        skill_root_intermediate = package_dir.parent / "intermediate"

        created = _lock_protected_paths(package_dir)

        assert skill_root_intermediate.is_dir()
        with pytest.raises(PermissionError):
            (skill_root_intermediate / "classification.json").write_text("{}")

        _unlock_protected_paths(created)

        assert not skill_root_intermediate.exists()

    def test_existing_skill_root_intermediate_is_left_alone(self, package_dir):
        skill_root_intermediate = package_dir.parent / "intermediate"
        skill_root_intermediate.mkdir()
        (skill_root_intermediate / "notes.json").write_text("{}")

        created = _lock_protected_paths(package_dir)
        (skill_root_intermediate / "other.json").write_text("{}")
        _unlock_protected_paths(created)

        assert skill_root_intermediate not in created
        assert (skill_root_intermediate / "notes.json").exists()

    def test_unlock_restores_original_modes(self, package_dir):
        config = package_dir / "config.py"
        config.write_text("BACKEND = 'ollama'")
        config.chmod(0o600)
        (package_dir / "fixtures").mkdir()
        script = package_dir / "fixtures" / "run.py"
        script.write_text("x")
        script.chmod(0o755)
        directive = package_dir / "intermediate" / "runtime_directive.json"
        directive.write_text("{}")
        directive.chmod(0o640)

        _unlock_protected_paths(_lock_protected_paths(package_dir))

        assert stat.S_IMODE(config.stat().st_mode) == 0o600
        assert stat.S_IMODE(script.stat().st_mode) == 0o755
        assert stat.S_IMODE(directive.stat().st_mode) == 0o640

    def test_failed_lock_undoes_partial_work(self, package_dir):
        (package_dir / "config.py").write_text("BACKEND = 'ollama'")
        real_mkdir = Path.mkdir

        def failing_mkdir(self, *args, **kwargs):
            if self.name == "fixtures":
                raise OSError("disk full")
            return real_mkdir(self, *args, **kwargs)

        with patch.object(Path, "mkdir", failing_mkdir):
            with pytest.raises(OSError, match="disk full"):
                _lock_protected_paths(package_dir)

        (package_dir / "config.py").write_text("still writable")
        assert not (package_dir / "fixtures").exists()
        assert not (package_dir.parent / "intermediate").exists()

    def test_failed_lock_removes_created_placeholders(self, package_dir):
        real_chmod = Path.chmod

        def failing_chmod(self, mode, *args, **kwargs):
            if self.name == "fixtures" and mode == 0o555:
                raise PermissionError("chmod refused")
            return real_chmod(self, mode, *args, **kwargs)

        with patch.object(Path, "chmod", failing_chmod):
            with pytest.raises(PermissionError, match="chmod refused"):
                _lock_protected_paths(package_dir)

        assert not (package_dir / "config.py").exists()
        assert not (package_dir / "fixtures").exists()


@patch("mellea_skills_compiler.compile.backends.pi.CompileMetadata.record_backend")
@patch("mellea_skills_compiler.compile.backends.pi.subprocess.Popen")
def test_compile_passes_absolute_paths_to_pi(mock_popen, _record, backend, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    package_dir = Path("skills/foo/foo_mellea")
    (package_dir / "intermediate").mkdir(parents=True)
    (package_dir / "intermediate" / "classification.json").write_text("{}")
    Path("skills/foo/spec.md").write_text("# Foo")
    context = CompilationContext(
        spec_path=Path("skills/foo/spec.md"),
        package_dir=package_dir,
        intermediate_dir=package_dir / "intermediate",
        model="granite3.3:8b",
        timeout=300,
        repair_mode=False,
        skill_backend="ollama",
        skill_model="granite4.1:3b",
        refresh_cache=False,
    )
    events = [_assistant_end(), _pi_event_line({"type": "agent_settled"}), ""]
    mock_process = MagicMock()
    mock_process.stdout.readline.side_effect = events
    mock_process.stderr.readline.side_effect = [""]
    mock_process.poll.side_effect = [None] * (len(events) - 1) + [0]
    mock_process.wait.return_value = 0
    mock_popen.return_value = mock_process

    backend.compile(context)

    argv = mock_popen.call_args[0][0]
    assert f"/mellea-fy {(tmp_path / 'skills/foo/spec.md').resolve()}" in argv
    system_prompt = argv[argv.index("--append-system-prompt") + 1]
    assert f"`{package_dir.resolve()}/intermediate/`" in system_prompt
    assert f"{(tmp_path / '.claude/schemas').resolve()}/" in system_prompt
