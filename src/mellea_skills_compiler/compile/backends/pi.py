"""Pi backend implementation for mellea-skills compilation.

This module implements the CompilationBackend protocol using the pi coding agent
(@earendil-works/pi-coding-agent) as the compilation engine. It wraps a subprocess-based
approach that invokes the `/mellea-fy` and `/mellea-fy-repair` prompt templates.

The PiBackend is responsible for:
- Validating that the pi CLI is installed and credentials resolve
- Invoking pi with appropriate arguments
- Parsing the --mode json event stream to track compilation progress
- Handling timeouts and errors gracefully
- Cleaning up resources (subprocess) on completion or failure

This backend requires:
- pi CLI installed and accessible in PATH
- Provider credentials configured for pi (checked via `pi auth check`)
"""

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional

from rich.console import Console

from mellea_skills_compiler.compile.backend import (
    CompilationContext,
    CompilationResult,
)
from mellea_skills_compiler.enums import PiMessageType
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()
console = Console(log_time=True)


class PiBackend:
    """Pi backend for mellea-skills compilation.

    This backend implements the CompilationBackend protocol by wrapping the pi CLI
    in one-shot (`-p --mode json`) mode. It invokes the `/mellea-fy` or
    `/mellea-fy-repair` prompt template to decompose skill specifications into
    Mellea pipeline components.

    Example:
        >>> backend = PiBackend()
        >>> is_valid, error = backend.validate_environment()
        >>> if not is_valid:
        ...     raise RuntimeError(f"Pi not available: {error}")
        >>> context = CompilationContext(
        ...     spec_path=Path("weather/spec.md"),
        ...     package_dir=Path("weather_mellea"),
        ...     intermediate_dir=Path("weather_mellea/intermediate"),
        ...     timeout=300,
        ...     repair_mode=False,
        ... )
        >>> result = backend.compile(context)
    """

    @staticmethod
    def identifier() -> str:
        """Return internal identifier for the given compiler.

        Returns:
            str: "pi"
        """
        return "pi"

    def name(self) -> str:
        """Return human-readable backend name for logging and display.

        Returns:
            The string "Pi"
        """
        return "Pi"

    def compile(self, context: CompilationContext) -> CompilationResult:
        """Execute the full compilation workflow using pi.

        Args:
            context: Compilation parameters including paths, model, timeout, etc.

        Returns:
            CompilationResult with success status, package directory, and metadata.
        """
        process = None
        process_exited = False
        try:
            console.print(
                f"\n[green]{'Repairing' if context.repair_mode else 'Compiling'} using {self.name()}\n"
            )

            pi_argv = self._build_pi_argv(
                spec_path=context.spec_path,
                repair_mode=context.repair_mode,
                model=context.model,
            )

            start_time = time.time()
            processing = console.status(
                "[italic bold yellow]Processing...[/]", spinner_style="status.spinner"
            )

            process = subprocess.Popen(
                pi_argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            stderr_lines: List[str] = []

            def read_stderr():
                if process.stderr:
                    for line in iter(process.stderr.readline, ""):
                        if line:
                            stderr_lines.append(line.strip())

            stderr_thread = threading.Thread(target=read_stderr)
            stderr_thread.daemon = True
            stderr_thread.start()

            processing.start()
            if process.stdout is None:
                raise Exception("Failed to open stdout pipe for pi subprocess")

            while True:
                elapsed = time.time() - start_time
                if context.timeout > 0 and elapsed >= context.timeout:
                    raise Exception(
                        f"Mellea-fy skill compilation failed due to timeout. Process timed out after {elapsed:.1f}s (limit: {context.timeout}s)"
                    )

                output = process.stdout.readline()
                poll_result = process.poll()

                if output == "" and poll_result is not None:
                    process_exited = True
                    processing.stop()
                    break

                if output:
                    try:
                        event = json.loads(output.strip())
                        event_type = event.get("type")
                        if (
                            event_type == PiMessageType.MESSAGE_END
                            and event.get("message", {}).get("role") == "assistant"
                        ):
                            content = event["message"].get("content", [])
                            text = "".join(
                                block.get("text", "")
                                for block in content
                                if block.get("type") == "text"
                            )
                            if text:
                                console.print(f"\n[cyan]{text}[/]")
                        elif event_type == PiMessageType.AGENT_SETTLED:
                            console.print("[blue]Summary:[/]\n")
                            elapsed_final = time.time() - start_time
                            mins, secs = divmod(elapsed_final, 60)
                            console.print(
                                f"[cyan]Total Time ⏱️: {int(mins)}m {int(secs)}s.[/]\n"
                            )
                    except json.decoder.JSONDecodeError as e:
                        console.print("Pi message parsing error - " + str(e))

            stderr_thread.join(timeout=1)

            return_code = process.wait(timeout=1)
            if return_code != 0:
                return CompilationResult(
                    success=False,
                    package_dir=context.package_dir,
                    error_message=f"Mellea-fy skill compilation failed with return code {return_code}. Error: {' '.join(stderr_lines)}",
                )

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
            if process and not process_exited and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

    def validate_environment(self) -> tuple[bool, Optional[str]]:
        """Check if pi CLI and credentials are available.

        Returns:
            A tuple of (is_valid, error_message).
        """
        if shutil.which("pi") is None:
            return False, (
                "pi CLI not found in PATH. "
                "Install it via 'npm install -g @earendil-works/pi-coding-agent'."
            )

        with console.status(
            "[italic bold yellow]Checking pi credentials...[/]",
            spinner_style="status.spinner",
        ):
            try:
                result = subprocess.run(
                    ["pi", "auth", "check", "--provider", "anthropic", "--json"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                return False, "pi auth check timed out after 30 seconds"
            except Exception as e:
                return False, f"Failed to run pi auth check: {e}"

        try:
            status = json.loads(result.stdout)
        except json.decoder.JSONDecodeError:
            return False, (
                f"pi auth check returned unparseable output. "
                f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
            )

        if result.returncode != 0 or status.get("status") != "ready":
            reason = status.get("reason", "unknown reason")
            return False, (
                f"Pi credentials are not configured for provider 'anthropic' ({reason}). "
                "Run 'pi auth' or configure ANTHROPIC_API_KEY."
            )

        return True, None

    def supports_repair_mode(self) -> bool:
        """Indicate whether this backend supports repair mode.

        Returns:
            True, since PiBackend supports the /mellea-fy-repair workflow.
        """
        return True

    def _build_pi_argv(
        self,
        spec_path: Path,
        repair_mode: bool,
        model: Optional[str],
    ) -> list[str]:
        """Build the command-line arguments for invoking pi.

        Args:
            spec_path: Path to the skill specification file
            repair_mode: Whether to use /mellea-fy-repair instead of /mellea-fy
            model: Optional model identifier to pass via --model

        Returns:
            List of command-line arguments ready for subprocess.Popen
        """
        command = "/mellea-fy-repair" if repair_mode else "/mellea-fy"
        pi_argv: List[str] = [
            "pi",
            "-p",
            f"{command} {spec_path}",
            "--mode",
            "json",
            "--approve",
            "--tools",
            "read,write,edit",
        ]

        if model:
            pi_argv.extend(["--model", model])

        LOGGER.debug(f"Pi command - {' '.join(pi_argv)}")

        return pi_argv
