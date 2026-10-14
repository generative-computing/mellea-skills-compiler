"""Unit tests for ClaudeCodeBackend implementation.

Tests the Claude Code backend's environment validation, compilation workflow,
and error handling without requiring actual Claude Code CLI or API credentials.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from mellea_skills_compiler.compile.backend import CompilationContext, CompilationResult
from mellea_skills_compiler.compile.backends.claude import ClaudeCodeBackend
from mellea_skills_compiler.enums import ClaudeMessageType


@pytest.fixture
def backend():
    """Create a ClaudeCodeBackend instance for testing."""
    return ClaudeCodeBackend()


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
        model="claude-3-7-sonnet-20250219",
        timeout=300,
        repair_mode=False,
        skill_backend="anthropic",
        skill_model="claude-3-5-sonnet-20241022",
        refresh_cache=False,
    )


class TestBackendMetadata:
    """Test backend metadata methods."""

    def test_get_backend_name(self, backend):
        """Test that get_backend_name returns 'Claude Code'."""
        assert backend.name() == "Claude Code"

    def test_supports_repair_mode(self, backend):
        """Test that supports_repair_mode returns True."""
        assert backend.supports_repair_mode() is True


class TestValidateEnvironment:
    """Test environment validation logic."""

    @patch("mellea_skills_compiler.compile.backends.claude.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    def test_validate_environment_success(
        self, mock_anthropic_class, mock_which, backend
    ):
        """Test successful environment validation."""
        # Mock claude CLI is available
        mock_which.return_value = "/usr/local/bin/claude"

        # Mock API credentials are set
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            # Mock Anthropic API returns models
            mock_anthropic = Mock()
            mock_model = Mock()
            mock_model.id = "claude-3-7-sonnet-20250219"
            mock_anthropic.models.list.return_value = [mock_model]
            mock_anthropic_class.return_value = mock_anthropic

            is_valid, error = backend.validate_environment()

            assert is_valid is True
            assert error is None

    @patch("mellea_skills_compiler.compile.backends.claude.shutil.which")
    def test_validate_environment_missing_claude_cli(self, mock_which, backend):
        """Test validation fails when claude CLI is not in PATH."""
        mock_which.return_value = None

        is_valid, error = backend.validate_environment()

        assert is_valid is False
        assert error is not None
        assert "Claude Code CLI not found" in error
        assert "https://docs.anthropic.com" in error

    @patch("mellea_skills_compiler.compile.backends.claude.shutil.which")
    def test_validate_environment_missing_api_key(self, mock_which, backend):
        """Test validation fails when API credentials are not set."""
        mock_which.return_value = "/usr/local/bin/claude"

        # Ensure no API credentials in environment
        with patch.dict(os.environ, {}, clear=True):
            is_valid, error = backend.validate_environment()

            assert is_valid is False
            assert error is not None
            assert "Anthropic credentials are not configured" in error
            assert "ANTHROPIC_API_KEY" in error or "ANTHROPIC_AUTH_TOKEN" in error

    @patch("mellea_skills_compiler.compile.backends.claude.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    def test_validate_environment_api_error(
        self, mock_anthropic_class, mock_which, backend
    ):
        """Test validation fails when API call raises exception."""
        mock_which.return_value = "/usr/local/bin/claude"

        # Mock API credentials are set
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            # Mock Anthropic API raises exception
            mock_anthropic = Mock()
            mock_anthropic.models.list.side_effect = Exception("API connection failed")
            mock_anthropic_class.return_value = mock_anthropic

            is_valid, error = backend.validate_environment()

            assert is_valid is False
            assert error is not None
            assert "Unable to validate Anthropic credentials" in error
            assert "API connection failed" in error

    @patch("mellea_skills_compiler.compile.backends.claude.shutil.which")
    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    def test_validate_environment_no_models(
        self, mock_anthropic_class, mock_which, backend
    ):
        """Test validation fails when no models are returned."""
        mock_which.return_value = "/usr/local/bin/claude"

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            # Mock Anthropic API returns empty list
            mock_anthropic = Mock()
            mock_anthropic.models.list.return_value = []
            mock_anthropic_class.return_value = mock_anthropic

            is_valid, error = backend.validate_environment()

            assert is_valid is False
            assert error is not None
            assert "no Claude models were returned" in error


class TestCompileMethod:
    """Test the compile() method with various scenarios."""

    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    @patch("mellea_skills_compiler.compile.backends.claude.subprocess.Popen")
    @patch(
        "mellea_skills_compiler.compile.backends.claude.socketserver.ThreadingTCPServer"
    )
    @patch("mellea_skills_compiler.compile.backends.claude.build_system_prompt")
    @patch("mellea_skills_compiler.compile.backends.claude.write_compile_settings")
    @patch("mellea_skills_compiler.compile.backends.claude.CompileMetadata.record_backend")
    def test_compile_success(
        self,
        mock_record_backend,
        mock_write_settings,
        mock_build_prompt,
        mock_tcp_server,
        mock_popen,
        mock_anthropic_class,
        backend,
        mock_context,
    ):
        """Test successful compilation workflow."""
        # Mock Anthropic API
        mock_anthropic = Mock()
        mock_model = Mock()
        mock_model.id = "claude-3-7-sonnet-20250219"
        mock_anthropic.models.list.return_value = [mock_model]
        mock_anthropic_class.return_value = mock_anthropic

        # Mock system prompt and settings
        mock_build_prompt.return_value = "System prompt with runtime defaults"
        mock_write_settings.return_value = Path("/tmp/settings.json")

        # Mock proxy server
        mock_server = Mock()
        mock_server.server_address = ("127.0.0.1", 8080)
        mock_tcp_server.return_value = mock_server

        # Mock subprocess - successful completion
        mock_process = Mock()

        # Mock stdout with JSON responses - readline returns lines then empty string
        mock_stdout_lines = [
            json.dumps(
                {
                    "type": ClaudeMessageType.ASSISTANT,
                    "message": {
                        "content": [
                            {
                                "type": ClaudeMessageType.TEXT,
                                "text": "Starting compilation...",
                            }
                        ]
                    },
                }
            )
            + "\n",
            "",  # Empty line signals end
        ]

        # Create a generator that yields lines then returns empty strings forever
        def stdout_generator():
            for line in mock_stdout_lines:
                yield line
            # After all lines, poll returns 0 (process finished)
            mock_process.poll.return_value = 0
            while True:
                yield ""

        stdout_gen = stdout_generator()
        mock_process.stdout = Mock()
        mock_process.stdout.readline = lambda: next(stdout_gen)
        mock_process.poll.return_value = None  # Still running initially
        mock_process.wait.return_value = 0  # Success exit code

        mock_process.stderr = Mock()
        mock_process.stderr.readline = Mock(return_value="")

        mock_popen.return_value = mock_process

        # Execute compilation
        result = backend.compile(mock_context)

        # Verify result
        assert result.success is True
        assert result.package_dir == mock_context.package_dir
        assert result.error_message is None
        assert "model" in result.metadata
        assert result.metadata["model"] == "claude-3-7-sonnet-20250219"

        # Verify subprocess was called
        mock_popen.assert_called_once()

        # Verify proxy server was set up and shut down
        mock_server.shutdown.assert_called_once()
        mock_server.server_close.assert_called_once()

    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    def test_compile_no_models_available(
        self, mock_anthropic_class, backend, mock_context
    ):
        """Test compilation fails when no models are available."""
        # Mock Anthropic API returns empty list
        mock_anthropic = Mock()
        mock_anthropic.models.list.return_value = []
        mock_anthropic_class.return_value = mock_anthropic

        result = backend.compile(mock_context)

        assert result.success is False
        assert "No claude models available" in result.error_message

    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    def test_compile_invalid_model(self, mock_anthropic_class, backend, mock_context):
        """Test compilation fails when specified model is not available."""
        # Mock Anthropic API returns different models
        mock_anthropic = Mock()
        mock_model = Mock()
        mock_model.id = "claude-3-5-sonnet-20241022"
        mock_anthropic.models.list.return_value = [mock_model]
        mock_anthropic_class.return_value = mock_anthropic

        # Request a model that doesn't exist
        mock_context.model = "claude-nonexistent-model"

        result = backend.compile(mock_context)

        assert result.success is False
        assert "Invalid Claude model provided" in result.error_message
        assert "claude-nonexistent-model" in result.error_message

    @patch("mellea_skills_compiler.compile.backends.claude.console")
    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    @patch("mellea_skills_compiler.compile.backends.claude.subprocess.Popen")
    @patch(
        "mellea_skills_compiler.compile.backends.claude.socketserver.ThreadingTCPServer"
    )
    @patch("mellea_skills_compiler.compile.backends.claude.build_system_prompt")
    @patch("mellea_skills_compiler.compile.backends.claude.write_compile_settings")
    @patch("mellea_skills_compiler.compile.backends.claude.time.time")
    @patch("mellea_skills_compiler.compile.backends.claude.CompileMetadata.record_backend")
    def test_compile_timeout(
        self,
        mock_record_backend,
        mock_time,
        mock_write_settings,
        mock_build_prompt,
        mock_tcp_server,
        mock_popen,
        mock_anthropic_class,
        mock_console,
        backend,
        mock_context,
    ):
        """Test compilation handles timeout correctly."""
        # Set a short timeout
        mock_context.timeout = 1

        # Mock Anthropic API
        mock_anthropic = Mock()
        mock_model = Mock()
        mock_model.id = "claude-3-7-sonnet-20250219"
        mock_anthropic.models.list.return_value = [mock_model]
        mock_anthropic_class.return_value = mock_anthropic

        # Mock system prompt and settings
        mock_build_prompt.return_value = "System prompt"
        mock_write_settings.return_value = Path("/tmp/settings.json")

        # Mock console.status
        mock_status = Mock()
        mock_console.status.return_value = mock_status
        mock_console.print = Mock()

        # Mock proxy server
        mock_server = Mock()
        mock_server.server_address = ("127.0.0.1", 8080)
        mock_tcp_server.return_value = mock_server

        # Mock time to simulate timeout
        start_time = 0
        elapsed_time = 0

        def mock_time_func():
            nonlocal elapsed_time
            result = start_time + elapsed_time
            elapsed_time += 2  # Each call advances by 2 seconds
            return result

        mock_time.side_effect = mock_time_func

        # Mock subprocess - never completes (always returns None for poll)
        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running
        mock_process.stdout = Mock()
        mock_process.stdout.readline = Mock(return_value="")
        mock_process.stderr = Mock()
        mock_process.stderr.readline = Mock(return_value="")
        mock_process.terminate = Mock()
        mock_process.wait = Mock()

        mock_popen.return_value = mock_process

        # Execute compilation
        result = backend.compile(mock_context)

        # Verify timeout was handled
        assert result.success is False
        assert "timeout" in result.error_message.lower()
        assert "1s" in result.error_message or "1.0s" in result.error_message

        # Verify process was terminated (may be called in timeout handler and finally block)
        assert mock_process.terminate.call_count >= 1

    @patch("mellea_skills_compiler.compile.backends.claude.console")
    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    @patch("mellea_skills_compiler.compile.backends.claude.subprocess.Popen")
    @patch(
        "mellea_skills_compiler.compile.backends.claude.socketserver.ThreadingTCPServer"
    )
    @patch("mellea_skills_compiler.compile.backends.claude.build_system_prompt")
    @patch("mellea_skills_compiler.compile.backends.claude.write_compile_settings")
    @patch("mellea_skills_compiler.compile.backends.claude.CompileMetadata.record_backend")
    def test_compile_subprocess_error(
        self,
        mock_record_backend,
        mock_write_settings,
        mock_build_prompt,
        mock_tcp_server,
        mock_popen,
        mock_anthropic_class,
        mock_console,
        backend,
        mock_context,
    ):
        """Test compilation handles subprocess errors correctly."""
        # Mock Anthropic API
        mock_anthropic = Mock()
        mock_model = Mock()
        mock_model.id = "claude-3-7-sonnet-20250219"
        mock_anthropic.models.list.return_value = [mock_model]
        mock_anthropic_class.return_value = mock_anthropic

        # Mock console.status
        mock_status = Mock()
        mock_console.status.return_value = mock_status
        mock_console.print = Mock()

        # Mock system prompt and settings
        mock_build_prompt.return_value = "System prompt"
        mock_write_settings.return_value = Path("/tmp/settings.json")

        # Mock proxy server
        mock_server = Mock()
        mock_server.server_address = ("127.0.0.1", 8080)
        mock_tcp_server.return_value = mock_server

        # Mock subprocess - fails with non-zero exit code
        mock_process = Mock()

        # Stdout returns empty immediately, then poll returns failure
        stdout_call_count = [0]

        def stdout_readline():
            stdout_call_count[0] += 1
            if stdout_call_count[0] == 1:
                mock_process.poll.return_value = 1  # Set to failed after first read
                return ""
            return ""

        mock_process.stdout = Mock()
        mock_process.stdout.readline = stdout_readline
        mock_process.poll.return_value = None  # Initially running
        mock_process.wait.return_value = 1  # Non-zero exit code

        # Stderr returns error message
        stderr_lines = ["Error: compilation failed\n", ""]
        stderr_iter = iter(stderr_lines)
        mock_process.stderr = Mock()
        mock_process.stderr.readline = lambda: next(stderr_iter, "")

        mock_popen.return_value = mock_process

        # Execute compilation
        result = backend.compile(mock_context)

        # Verify error was captured
        assert result.success is False
        assert "return code 1" in result.error_message
        assert "compilation failed" in result.error_message

    @patch("mellea_skills_compiler.compile.backends.claude.console")
    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    @patch("mellea_skills_compiler.compile.backends.claude.subprocess.Popen")
    @patch(
        "mellea_skills_compiler.compile.backends.claude.socketserver.ThreadingTCPServer"
    )
    @patch("mellea_skills_compiler.compile.backends.claude.build_system_prompt")
    @patch("mellea_skills_compiler.compile.backends.claude.write_compile_settings")
    @patch("mellea_skills_compiler.compile.backends.claude.CompileMetadata.record_backend")
    def test_compile_repair_mode(
        self,
        mock_record_backend,
        mock_write_settings,
        mock_build_prompt,
        mock_tcp_server,
        mock_popen,
        mock_anthropic_class,
        mock_console,
        backend,
        mock_context,
    ):
        """Test compilation uses repair mode command when repair_mode=True."""
        # Enable repair mode
        mock_context.repair_mode = True

        # Mock Anthropic API
        mock_anthropic = Mock()
        mock_model = Mock()
        mock_model.id = "claude-3-7-sonnet-20250219"
        mock_anthropic.models.list.return_value = [mock_model]
        mock_anthropic_class.return_value = mock_anthropic

        # Mock console.status
        mock_status = Mock()
        mock_console.status.return_value = mock_status
        mock_console.print = Mock()

        # Mock system prompt and settings
        mock_build_prompt.return_value = "System prompt"
        mock_write_settings.return_value = Path("/tmp/settings.json")

        # Mock proxy server
        mock_server = Mock()
        mock_server.server_address = ("127.0.0.1", 8080)
        mock_tcp_server.return_value = mock_server

        # Mock subprocess - successful
        mock_process = Mock()

        # Stdout returns empty immediately, then poll returns success
        stdout_call_count = [0]

        def stdout_readline():
            stdout_call_count[0] += 1
            if stdout_call_count[0] == 1:
                mock_process.poll.return_value = 0  # Set to success after first read
                return ""
            return ""

        mock_process.stdout = Mock()
        mock_process.stdout.readline = stdout_readline
        mock_process.poll.return_value = None  # Initially running
        mock_process.wait.return_value = 0  # Success exit code

        mock_process.stderr = Mock()
        mock_process.stderr.readline = Mock(return_value="")

        mock_popen.return_value = mock_process

        # Execute compilation
        result = backend.compile(mock_context)

        # Verify repair mode command was used
        call_args = mock_popen.call_args
        argv = call_args[0][0]

        # Should contain /mellea-fy-repair instead of /mellea-fy
        assert any("mellea-fy-repair" in arg for arg in argv)
        assert result.success is True

    @patch("mellea_skills_compiler.compile.backends.claude.Anthropic")
    @patch("mellea_skills_compiler.compile.backends.claude.subprocess.Popen")
    @patch(
        "mellea_skills_compiler.compile.backends.claude.socketserver.ThreadingTCPServer"
    )
    @patch("mellea_skills_compiler.compile.backends.claude.build_system_prompt")
    @patch("mellea_skills_compiler.compile.backends.claude.write_compile_settings")
    def test_compile_exception_handling(
        self,
        mock_write_settings,
        mock_build_prompt,
        mock_tcp_server,
        mock_popen,
        mock_anthropic_class,
        backend,
        mock_context,
    ):
        """Test compilation handles unexpected exceptions gracefully."""
        # Mock Anthropic API to raise exception
        mock_anthropic_class.side_effect = Exception("Unexpected error")

        # Execute compilation
        result = backend.compile(mock_context)

        # Verify exception was caught and returned as error
        assert result.success is False
        assert "Unexpected error" in result.error_message


class TestHelperMethods:
    """Test private helper methods."""

    @patch(
        "mellea_skills_compiler.compile.backends.claude.socketserver.ThreadingTCPServer"
    )
    @patch("mellea_skills_compiler.compile.backends.claude.threading.Thread")
    def test_setup_proxy_server(self, mock_thread, mock_tcp_server, backend):
        """Test proxy server setup."""
        # Mock server
        mock_server = Mock()
        mock_server.server_address = ("127.0.0.1", 8080)
        mock_tcp_server.return_value = mock_server

        # Mock thread
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance

        with patch.dict(
            os.environ, {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}
        ):
            proxy_server = backend._setup_proxy_server()

        # Verify server was created and started
        assert proxy_server == mock_server
        mock_thread_instance.start.assert_called_once()
        assert mock_thread_instance.daemon is True

    def test_build_claude_argv_normal_mode(self, backend, tmp_path):
        """Test building Claude Code arguments for normal compilation."""
        spec_path = tmp_path / "spec.md"
        settings_path = tmp_path / "settings.json"

        argv = backend._build_claude_argv(
            model="claude-3-7-sonnet-20250219",
            system_prompt="Test system prompt",
            compile_settings_path=settings_path,
            spec_path=spec_path,
            repair_mode=False,
        )

        # Verify key arguments are present
        assert "claude" in argv
        assert "-p" in argv
        assert "--model" in argv
        assert "claude-3-7-sonnet-20250219" in argv
        assert "--append-system-prompt" in argv
        assert "Test system prompt" in argv
        assert "--settings" in argv
        assert str(settings_path) in argv

        # Verify it uses /mellea-fy (not repair)
        assert any("./mellea-fy" in arg and "repair" not in arg for arg in argv)

    def test_build_claude_argv_repair_mode(self, backend, tmp_path):
        """Test building Claude Code arguments for repair mode."""
        spec_path = tmp_path / "spec.md"

        argv = backend._build_claude_argv(
            model="claude-3-7-sonnet-20250219",
            system_prompt="Test system prompt",
            compile_settings_path=None,
            spec_path=spec_path,
            repair_mode=True,
        )

        # Verify it uses /mellea-fy-repair
        assert any("mellea-fy-repair" in arg for arg in argv)

        # Verify no settings file when None
        assert "--settings" not in argv

    def test_cleanup_proxy(self, backend):
        """Test proxy server cleanup."""
        mock_server = Mock()

        backend._cleanup_proxy(mock_server)

        # Verify shutdown and close were called
        mock_server.shutdown.assert_called_once()
        mock_server.server_close.assert_called_once()

    def test_cleanup_proxy_handles_exceptions(self, backend):
        """Test proxy cleanup handles exceptions gracefully."""
        mock_server = Mock()
        mock_server.shutdown.side_effect = Exception("Shutdown failed")

        # Should not raise exception
        backend._cleanup_proxy(mock_server)

        # Verify shutdown was attempted
        mock_server.shutdown.assert_called_once()
