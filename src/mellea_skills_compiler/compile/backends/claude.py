"""Claude Code backend implementation for mellea-skills compilation.

This module implements the CompilationBackend protocol using Anthropic's Claude Code CLI
as the compilation engine. It wraps the existing subprocess-based approach that invokes
the `/mellea-fy` and `/mellea-fy-repair` slash commands.

The ClaudeCodeBackend is responsible for:
- Validating that Claude Code CLI is installed and configured
- Setting up a local proxy to strip context_management from API requests
- Invoking Claude Code with appropriate arguments and system prompts
- Parsing the JSON streaming output to track compilation progress
- Handling timeouts and errors gracefully
- Cleaning up resources (proxy server, subprocesses) on completion or failure

This backend requires:
- Claude Code CLI installed and accessible in PATH
- Valid Anthropic API credentials (ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN)
- Network access to Anthropic API (or configured ANTHROPIC_BASE_URL)

Example usage:
    >>> from mellea_skills_compiler.compile.backends.claude import ClaudeCodeBackend
    >>> from mellea_skills_compiler.compile.backend import CompilationContext
    >>>
    >>> backend = ClaudeCodeBackend()
    >>> is_valid, error = backend.validate_environment()
    >>> if not is_valid:
    ...     print(f"Cannot use Claude Code: {error}")
    ...     exit(1)
    >>>
    >>> context = CompilationContext(
    ...     spec_path=Path("weather/spec.md"),
    ...     package_dir=Path("weather_mellea"),
    ...     intermediate_dir=Path("weather_mellea/intermediate"),
    ...     model="claude-3-7-sonnet-20250219",
    ...     timeout=300,
    ... )
    >>>
    >>> result = backend.compile(context)
    >>> if result.success:
    ...     print(f"Compiled successfully to {result.package_dir}")
    ... else:
    ...     print(f"Compilation failed: {result.error_message}")
"""

import json
import logging
import os
import shutil
import socketserver
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from anthropic import Anthropic
from rich.console import Console

from mellea_skills_compiler.compile.backend import (
    CompilationContext,
    CompilationResult,
)
from mellea_skills_compiler.compile.claude_directives import (
    build_system_prompt,
    write_compile_settings,
)
from mellea_skills_compiler.compile.metadata import CompileMetadata
from mellea_skills_compiler.compile.proxy import ContextMgmtStrippingProxy
from mellea_skills_compiler.enums import ClaudeMessageType, InferenceModel


LOGGER = logging.getLogger(__name__)
console = Console(log_time=True)


class ClaudeCodeBackend:
    """Claude Code backend for mellea-skills compilation.

    This backend implements the CompilationBackend protocol by wrapping the existing
    Claude Code subprocess approach. It invokes the Claude Code CLI with the
    `/mellea-fy` or `/mellea-fy-repair` slash commands to decompose skill specifications
    into Mellea pipeline components.

    The backend handles:
    - Model validation via Anthropic API
    - Local proxy server setup to strip context_management from requests
    - Claude Code subprocess invocation with appropriate arguments
    - JSON streaming output parsing to track compilation progress
    - Timeout handling and graceful termination
    - Error handling and cleanup of resources

    Architecture:
    - Uses a local proxy server to modify API requests before forwarding to Anthropic
    - Runs Claude Code in project mode (-p) with restricted tools (Read, Write, Edit)
    - Streams JSON output to track compilation steps and detect completion
    - Enforces deny rules via settings file to prevent overwriting wrapper-rendered files

    Attributes:
        None (stateless backend, all state passed via CompilationContext)

    Example:
        >>> backend = ClaudeCodeBackend()
        >>>
        >>> # Validate environment before use
        >>> is_valid, error = backend.validate_environment()
        >>> if not is_valid:
        ...     raise RuntimeError(f"Claude Code not available: {error}")
        >>>
        >>> # Execute compilation
        >>> context = CompilationContext(
        ...     spec_path=Path("weather/spec.md"),
        ...     package_dir=Path("weather_mellea"),
        ...     intermediate_dir=Path("weather_mellea/intermediate"),
        ...     model="claude-3-7-sonnet-20250219",
        ... )
        >>> result = backend.compile(context)
    """

    @staticmethod
    def identifier() -> str:
        """Internal identifer for the given compiler

        Returns:
            str: Return Compiler identifer - "claude"
        """
        return "claude"

    def name(self) -> str:
        """Return human-readable backend name for logging and display.

        Returns:
            The string "Claude Code"

        Example:
            >>> backend = ClaudeCodeBackend()
            >>> print(f"Using backend: {backend.name()}")
            Using backend: Claude Code
        """
        return "Claude Code"

    def compile(self, context: CompilationContext) -> CompilationResult:
        """Execute the full compilation workflow using Claude Code.

        This method orchestrates the 10-step compilation process by invoking the
        Claude Code CLI with the `/mellea-fy` or `/mellea-fy-repair` slash command.

        The compilation workflow:
        1. Validate the specified model is available via Anthropic API
        2. Start a local proxy server to strip context_management from requests
        3. Build the Claude Code command-line arguments
        4. Invoke Claude Code subprocess with system prompt and settings
        5. Parse JSON streaming output to track progress
        6. Handle timeout if context.timeout > 0
        7. Detect compilation completion or errors
        8. Clean up proxy server and subprocess
        9. Return CompilationResult with success status and artifacts

        Args:
            context: Compilation parameters including paths, model, timeout, etc.

        Returns:
            CompilationResult with success status, package directory, and metadata.
            On success, result.success=True and result.package_dir contains the
            compiled Mellea package. On failure, result.success=False and
            result.error_message contains a description of what went wrong.

        Raises:
            RuntimeError: If Claude Code is not available or configured incorrectly
            TimeoutError: If compilation exceeds context.timeout (when timeout > 0)

        Example:
            >>> backend = ClaudeCodeBackend()
            >>> context = CompilationContext(
            ...     spec_path=Path("weather/spec.md"),
            ...     package_dir=Path("weather_mellea"),
            ...     intermediate_dir=Path("weather_mellea/intermediate"),
            ...     model="claude-3-7-sonnet-20250219",
            ...     timeout=300,
            ...     repair_mode=False,
            ... )
            >>> result = backend.compile(context)
            >>> if result.success:
            ...     print(f"Package created at {result.package_dir}")
            ... else:
            ...     print(f"Compilation failed: {result.error_message}")
        """
        proxy_server = None
        process = None

        try:
            # Step 1: Check and verify claude model
            available_models = [model.id for model in Anthropic().models.list()]
            if not available_models:
                return CompilationResult(
                    success=False,
                    package_dir=context.package_dir,
                    error_message="No claude models available with your API key.",
                )

            model = context.model
            if model:
                if model not in available_models:
                    return CompilationResult(
                        success=False,
                        package_dir=context.package_dir,
                        error_message=f"Invalid Claude model provided - {model}\nAvailable: {available_models}",
                    )
            else:
                # User did not provide the Claude model. Filter by default and select first.
                models = [
                    m
                    for m in available_models
                    if InferenceModel.CLAUDE_MODEL in m.lower()
                ]
                if not models:
                    return CompilationResult(
                        success=False,
                        package_dir=context.package_dir,
                        error_message=f"Please provide claude model via --model option.\nAvailable: {available_models}",
                    )
                model = models[0]

            # Record the chosen compilation backend and model in compile metadata
            CompileMetadata.record_backend(
                backend=self.identifier(), backend_model=model
            )

            console.print(
                f"\n[green]{'Repairing' if context.repair_mode else 'Compiling'} using {self.name()}, model:[/] {model}\n"
            )

            # Step 2: Start proxy server to strip context_management from API requests
            proxy_server = self._setup_proxy_server()
            proxy_port = proxy_server.server_address[1]

            subprocess_env = {
                **os.environ,
                "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{proxy_port}",
            }

            # Step 3: Build system prompt with runtime defaults
            system_prompt = build_system_prompt(
                context.skill_backend or "anthropic",
                context.skill_model or model,
                context.defaults_source,
                context.package_dir,
            )

            # Step 4: Write compile settings with deny rules
            try:
                compile_settings_path = write_compile_settings(
                    context.intermediate_dir, context.package_dir
                )
            except Exception as exc:
                LOGGER.warning(
                    "Could not write per-invocation settings (%s). Falling back to no "
                    "deny rules; the wrapper will still overwrite wrapper-rendered paths.",
                    exc,
                )
                compile_settings_path = None

            # Step 5: Build Claude Code command-line arguments
            claude_argv = self._build_claude_argv(
                model=model,
                system_prompt=system_prompt,
                compile_settings_path=compile_settings_path,
                spec_path=context.spec_path,
                repair_mode=context.repair_mode,
            )

            # Step 6: Execute Claude Code subprocess
            start_time = time.time()
            processing = console.status(
                "[italic bold yellow]Processing...[/]", spinner_style="status.spinner"
            )

            process = subprocess.Popen(
                claude_argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=subprocess_env,
            )

            stderr_lines = []

            def read_stderr():
                if process.stderr:
                    for line in iter(process.stderr.readline, ""):
                        if line:
                            stderr_lines.append(line.strip())

            # Thread for reading stderr
            stderr_thread = threading.Thread(target=read_stderr)
            stderr_thread.daemon = True
            stderr_thread.start()

            # Step 7: Parse streaming JSON output
            processing.start()
            while True:
                elapsed = time.time() - start_time
                if context.timeout > 0 and elapsed >= context.timeout:
                    raise Exception(
                        f"Mellea-fy skill compilation failed due to timeout. Process timed out after {elapsed:.1f}s (limit: {context.timeout}s)"
                    )

                # Read output
                output = process.stdout.readline()

                if output == "" and process.poll() is not None:
                    processing.stop()
                    break

                if output:
                    try:
                        response = json.loads(output.strip())
                        if response.get("type") == ClaudeMessageType.ASSISTANT:
                            for message_content in response.get("message", {}).get(
                                "content", []
                            ):
                                if (
                                    message_content.get("type")
                                    == ClaudeMessageType.TEXT
                                ):
                                    console.print(
                                        f"[cyan]{message_content.get('text', '')}[/]\n"
                                    )
                    except json.decoder.JSONDecodeError as e:
                        console.print("Claude message parsing error: " + str(e))

            # Wait for stderr thread
            stderr_thread.join(timeout=1)

            # Check return code
            return_code = process.wait(timeout=1)
            if return_code != 0:
                return CompilationResult(
                    success=False,
                    package_dir=context.package_dir,
                    error_message=f"Mellea-fy skill compilation failed with return code {return_code}. Error: {' '.join(stderr_lines)}",
                )

            # Success!
            return CompilationResult(
                success=True,
                package_dir=context.package_dir,
                intermediate_artifacts={},
                metadata={"model": model, "elapsed_time": time.time() - start_time},
            )

        except Exception as e:
            return CompilationResult(
                success=False,
                package_dir=context.package_dir,
                error_message=str(e),
            )
        finally:
            # Step 8: Cleanup
            if proxy_server:
                self._cleanup_proxy(proxy_server)
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

    def validate_environment(self) -> tuple[bool, Optional[str]]:
        """Check if Claude Code CLI and API credentials are available.

        This method verifies that all prerequisites for using Claude Code are met:
        1. Claude Code CLI is installed and accessible in PATH
        2. Anthropic API credentials are configured (ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN)
        3. The API credentials are valid by checking that models can be listed

        This should be called before attempting compilation to provide early,
        actionable error messages to users.

        Returns:
            A tuple of ``(is_valid, error_message)`` where ``is_valid`` is ``True``
            when Claude Code is usable and ``error_message`` contains a remediation
            hint when validation fails.

        Example:
            >>> backend = ClaudeCodeBackend()
            >>> is_valid, error = backend.validate_environment()
            >>> if not is_valid:
            ...     print(f"Cannot use Claude Code backend: {error}")
        """
        if shutil.which("claude") is None:
            return False, (
                "Claude Code CLI not found in PATH. "
                "Install it from https://docs.anthropic.com/en/docs/claude-code."
            )

        anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        anthropic_auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if not anthropic_api_key and not anthropic_auth_token:
            return False, (
                "Anthropic credentials are not configured. "
                "Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN before compiling."
            )

        try:
            available_models = [model.id for model in Anthropic().models.list()]
        except Exception as exc:
            return False, (
                "Unable to validate Anthropic credentials by listing models: " f"{exc}"
            )

        if not available_models:
            return False, (
                "Anthropic credentials are configured, but no Claude models were "
                "returned for this account."
            )

        return True, None

    def supports_repair_mode(self) -> bool:
        """Indicate that Claude Code supports repair mode.

        Claude Code supports repair mode via the `/mellea-fy-repair` slash command,
        which attempts to fix compilation errors by analyzing failed artifacts and
        regenerating specific components.

        Returns:
            True (Claude Code supports repair mode)

        Example:
            >>> backend = ClaudeCodeBackend()
            >>> if backend.supports_repair_mode():
            ...     print("Repair mode available")
            ...     context.repair_mode = True
        """
        return True

    def _setup_proxy_server(self) -> socketserver.ThreadingTCPServer:
        """Set up a local proxy server to strip context_management from API requests.

        The IBM LiteLLM proxy rejects the context_management field that Claude Code
        sends automatically. This proxy intercepts requests, removes that field,
        and forwards to the real Anthropic API (or configured ANTHROPIC_BASE_URL).

        Returns:
            A running ThreadingTCPServer instance. The server runs in a daemon thread
            and will be automatically cleaned up when the process exits.

        Example:
            >>> proxy_server = self._setup_proxy_server()
            >>> proxy_port = proxy_server.server_address[1]
            >>> # Use http://127.0.0.1:{proxy_port} as ANTHROPIC_BASE_URL
        """
        _real_base = os.environ.get(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
        ).rstrip("/")
        _parsed = urlparse(_real_base)

        proxy_server = socketserver.ThreadingTCPServer(
            ("127.0.0.1", 0), ContextMgmtStrippingProxy
        )
        proxy_server.allow_reuse_address = True
        proxy_server.upstream_scheme = _parsed.scheme  # type: ignore[attr-defined]
        proxy_server.upstream_host = _parsed.netloc  # type: ignore[attr-defined]
        proxy_server.upstream_path_prefix = _parsed.path  # type: ignore[attr-defined]

        proxy_thread = threading.Thread(target=proxy_server.serve_forever)
        proxy_thread.daemon = True
        proxy_thread.start()

        LOGGER.debug(
            "Started proxy server on port %d forwarding to %s",
            proxy_server.server_address[1],
            _real_base,
        )

        return proxy_server

    def _build_claude_argv(
        self,
        model: str,
        system_prompt: str,
        compile_settings_path: Optional[Path],
        spec_path: Path,
        repair_mode: bool,
    ) -> list[str]:
        """Build the command-line arguments for invoking Claude Code.

        Constructs the full argv list for subprocess.Popen, including:
        - Project mode (-p)
        - Model selection
        - System prompt injection
        - Allowed tools (Read, Write, Edit)
        - Output format (stream-json)
        - Permission mode (acceptEdits)
        - Settings file (if provided)
        - The mellea-fy or mellea-fy-repair command

        Args:
            model: Claude model identifier (e.g., "claude-3-7-sonnet-20250219")
            system_prompt: System prompt to inject with runtime defaults
            compile_settings_path: Optional path to settings file with deny rules
            spec_path: Path to the skill specification file
            repair_mode: Whether to use /mellea-fy-repair instead of /mellea-fy

        Returns:
            List of command-line arguments ready for subprocess.Popen

        Example:
            >>> argv = self._build_claude_argv(
            ...     model="claude-3-7-sonnet-20250219",
            ...     system_prompt="Use backend=anthropic...",
            ...     compile_settings_path=Path("settings.json"),
            ...     spec_path=Path("weather/spec.md"),
            ...     repair_mode=False,
            ... )
            >>> # argv = ["claude", "-p", "--model", "claude-3-7-sonnet-20250219", ...]
        """
        claude_argv = [
            "claude",
            "-p",
            "--model",
            model,
            "--append-system-prompt",
            system_prompt,
            "--allowed-tools",
            "Read,Write,Edit",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
        ]

        if compile_settings_path is not None:
            claude_argv.extend(["--settings", str(compile_settings_path)])

        mellea_fy_command = "./mellea-fy-repair" if repair_mode else "./mellea-fy"
        claude_argv.append(f"'{mellea_fy_command} {str(spec_path)}'")

        LOGGER.debug("Claude Code command: %s", " ".join(claude_argv))

        return claude_argv

    def _cleanup_proxy(self, proxy_server: socketserver.ThreadingTCPServer) -> None:
        """Shut down the proxy server and clean up resources.

        Args:
            proxy_server: The proxy server instance to shut down

        Example:
            >>> proxy_server = self._setup_proxy_server()
            >>> try:
            ...     # Use proxy_server
            ...     pass
            ... finally:
            ...     self._cleanup_proxy(proxy_server)
        """
        try:
            proxy_server.shutdown()
            proxy_server.server_close()
            LOGGER.debug("Proxy server shut down successfully")
        except Exception as e:
            LOGGER.warning("Error shutting down proxy server: %s", e)
