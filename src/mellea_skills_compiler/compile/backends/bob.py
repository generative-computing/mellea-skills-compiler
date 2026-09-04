"""Bob backend implementation for mellea-skills compilation.

This module implements the CompilationBackend protocol using IBM Bob CLI
as the compilation engine. It wraps the existing subprocess-based approach that invokes
the `/mellea-fy` and `/mellea-fy-repair` slash commands.

The BOBBackend is responsible for:
- Validating that Bob CLI is installed and configured
- Invoking Bob with appropriate arguments and system prompts
- Handling timeouts and errors gracefully
- Cleaning up resources (subprocesses) on completion or failure

This backend requires:
- Bob shell installed and accessible in PATH
- Valid IBM Bob API key - BOB_API_KEY
"""

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console

from mellea_skills_compiler.compile.backend import (
    CompilationContext,
    CompilationResult,
)
from mellea_skills_compiler.enums import BOBMessageType
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()
console = Console(log_time=True)


def authenticate_bob(
    prompt: str = "2+3=",
) -> Tuple[bool, str]:
    """Test the bob run command and report success/failure."""
    try:
        result = subprocess.run(
            ["bob", "run", prompt], capture_output=True, text=True, timeout=30
        )

        if result.returncode == 0:
            LOGGER.debug(f"✓ SUCCESS: bob run completed")
            return True, result.stdout
        else:
            LOGGER.debug(f"✗ FAILED: bob run exited with code {result.returncode}")
            return False, result.stderr

    except subprocess.TimeoutExpired:
        return False, "✗ FAILED: bob run timed out after 30 seconds"
    except Exception as e:
        return False, f"✗ FAILED: Unexpected error: {e}"


class BOBBackend:
    """Bob backend for mellea-skills compilation.

    This backend implements the CompilationBackend protocol by wrapping the existing
    Bob subprocess approach. It invokes the Bob CLI with the
    `/mellea-fy` or `/mellea-fy-repair` slash commands to decompose skill specifications
    into Mellea pipeline components.

    The backend handles:
    - Bob subprocess invocation with appropriate arguments
    - JSON streaming output parsing to track compilation progress
    - Timeout handling and graceful termination
    - Error handling and cleanup of resources

    Attributes:
        None (stateless backend, all state passed via CompilationContext)

    Example:
        >>> backend = BOBBackend()
        >>>
        >>> # Validate environment before use
        >>> is_valid, error = backend.validate_environment()
        >>> if not is_valid:
        ...     raise RuntimeError(f"Bob not available: {error}")
        >>>
        >>> # Execute compilation
        >>> context = CompilationContext(
        ...     spec_path=Path("weather/spec.md"),
        ...     package_dir=Path("weather_mellea"),
        ...     timeout=300,
        ...     repair_mode=False,
        ... )
        >>> result = backend.compile(context)
    """

    @staticmethod
    def identifier() -> str:
        """Internal identifer for the given compiler

        Returns:
            str: Return Compiler identifer - "bob"
        """
        return "bob"

    def name(self) -> str:
        """Return human-readable backend name for logging and display.

        Returns:
            The string "IBM Bob"

        Example:
            >>> backend = BOBBackend()
            >>> print(f"Using backend: {backend.name()}")
            Using backend: IBM Bob
        """
        return "IBM Bob"

    def compile(self, context: CompilationContext) -> CompilationResult:
        """Execute the full compilation workflow using Bob.

        This method orchestrates the 10-step compilation process by invoking the
        Bob CLI with the `/mellea-fy` or `/mellea-fy-repair` slash command.

        The compilation workflow:
        1. Validate the specified model is available via Anthropic API
        2. Build the Bob command-line arguments
        3. Invoke Bob subprocess with system prompt and settings
        4. Parse JSON streaming output to track progress
        5. Handle timeout if context.timeout > 0
        6. Detect compilation completion or errors
        7. Clean up proxy server and subprocess
        8. Return CompilationResult with success status and artifacts

        Args:
            context: Compilation parameters including paths, model, timeout, etc.

        Returns:
            CompilationResult with success status, package directory, and metadata.
            On success, result.success=True and result.package_dir contains the
            compiled Mellea package. On failure, result.success=False and
            result.error_message contains a description of what went wrong.

        Raises:
            RuntimeError: If Bob is not available or configured incorrectly
            TimeoutError: If compilation exceeds context.timeout (when timeout > 0)

        Example:
            >>> backend = BOBBackend()
            >>> context = CompilationContext(
            ...     spec_path=Path("weather/spec.md"),
            ...     package_dir=Path("weather_mellea"),
            ...     timeout=300,
            ...     repair_mode=False,
            ... )
            >>> result = backend.compile(context)
            >>> if result.success:
            ...     print(f"Package created at {result.package_dir}")
            ... else:
            ...     print(f"Compilation failed: {result.error_message}")
        """
        process = None
        try:
            console.print(
                f"\n[green]{'Repairing' if context.repair_mode else 'Compiling'} using {self.name()}\n"
            )

            if context.model:
                LOGGER.warning(
                    f"The '--model:{context.model}' value will be ignored for compilation. "
                    "IBM Bob automatically selects the appropriate model based on the task requirements."
                )

            # Step 5: Build Bob command-line arguments
            bob_argv = self._build_bob_argv(
                spec_path=context.spec_path,
                repair_mode=context.repair_mode,
            )

            # Step 6: Execute Bob subprocess
            start_time = time.time()
            processing = console.status(
                "[italic bold yellow]Processing...[/]", spinner_style="status.spinner"
            )

            process = subprocess.Popen(
                bob_argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
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
            event_message: str = ""
            if process.stdout is None:
                raise Exception("Failed to open stdout pipe for Bob subprocess")

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
                        event_type = response.get("type")
                        if event_type == BOBMessageType.MESSAGE:
                            event_message += response.get("content", " ")
                        elif event_message and event_type == BOBMessageType.TOOL_USE:
                            console.print(f"\n[cyan]{event_message}[/]")
                            event_message = ""
                        elif event_type == BOBMessageType.ERROR:
                            LOGGER.error(response.get("message", ""))
                        elif event_type == BOBMessageType.RESULT:
                            console.print(f"[blue]Summary:[/]\n")
                            mins, secs = divmod(
                                response["stats"]["duration_ms"] / 1000, 60
                            )
                            console.print(
                                f"[cyan]Status: {response.get('status')}[/]\n"
                                f"[cyan]Total Time ⏱️: {int(mins)}m {int(secs)}s.[/]\n"
                            )
                    except json.decoder.JSONDecodeError as e:
                        console.print("Bob message parsing error - " + str(e))

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
                metadata={"elapsed_time": time.time() - start_time},
            )

        except Exception as e:
            return CompilationResult(
                success=False,
                package_dir=context.package_dir,
                error_message=str(e),
            )
        finally:
            # Step 8: Cleanup
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

    def validate_environment(self) -> tuple[bool, Optional[str]]:
        """Check if Bob CLI and API credentials are available.

        This method verifies that all prerequisites for using Bob are met:
        1. Bob CLI is installed and accessible in PATH
        2. Bob SSO authentication or Bob API key (BOB_API_KEY) is is configured.

        This should be called before attempting compilation to provide early,
        actionable error messages to users.

        Returns:
            A tuple of ``(is_valid, error_message)`` where ``is_valid`` is ``True``
            when Bob is usable and ``error_message`` contains a remediation
            hint when validation fails.

        Example:
            >>> backend = BOBBackend()
            >>> is_valid, error = backend.validate_environment()
            >>> if not is_valid:
            ...     print(f"Cannot use Bob backend: {error}")
        """
        if shutil.which("bob") is None:
            return False, (
                "Bob CLI not found in PATH. "
                "Install it from https://bob.ibm.com/docs/shell/getting-started/install-and-setup"
            )

        with console.status(
            "[italic bold yellow]Authenticating Bob...[/]",
            spinner_style="status.spinner",
        ):
            status, msg = authenticate_bob()

        if not status:
            return False, msg

        return True, None

    def _build_bob_argv(
        self,
        spec_path: Path,
        repair_mode: bool,
    ) -> list[str]:
        """Build the command-line arguments for invoking Bob.

        Constructs the full argv list for subprocess.Popen, including:
        - Trust workspace
        - Accept License
        - Output format (stream-json)
        - The mellea-fy or mellea-fy-repair command
        - Spec Path

        Args:
            spec_path: Path to the skill specification file
            repair_mode: Whether to use /mellea-fy-repair instead of /mellea-fy

        Returns:
            List of command-line arguments ready for subprocess.Popen

        Example:
            >>> argv = self._build_bob_argv(
            ...     spec_path=Path("weather/spec.md"),
            ...     repair_mode=False,
            ... )
            >>> # argv = ["bob", "run", "--trust", "--accept-license", "--format", "stream-json", "/mellea-fy", "skills/weather"]
        """
        bob_argv: List[str] = [
            "bob",
            "run",
            "--trust",
            "--accept-license",
            "--format",
            "stream-json",
            "/mellea-fy-repair" if repair_mode else "/mellea-fy",
            f"{spec_path}",
        ]

        LOGGER.debug(f"Bob command - {' '.join(bob_argv)}")

        return bob_argv
