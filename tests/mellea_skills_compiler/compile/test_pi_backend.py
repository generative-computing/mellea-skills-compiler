"""Unit tests for PiBackend implementation.

Tests the pi backend's environment validation, compilation workflow,
and error handling without requiring the actual pi CLI or credentials.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from mellea_skills_compiler.compile.backend import CompilationContext, CompilationResult
from mellea_skills_compiler.compile.backends.pi import PiBackend
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
        assert args == ["pi", "auth", "check", "--provider", "anthropic", "--json"]

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
        assert args == ["pi", "auth", "check", "--provider", "ollama", "--json"]

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
    def test_compile_repair_mode(self, mock_popen, backend, mock_context):
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


class TestHelperMethods:
    """Test argv-building helper."""

    def test_build_pi_argv_normal_mode(self, backend, tmp_path):
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
        assert argv[tools_index + 1] == "read,write,edit"

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
