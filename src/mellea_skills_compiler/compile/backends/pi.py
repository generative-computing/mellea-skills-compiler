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
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional

from rich.console import Console

from mellea_skills_compiler.compile.backend import (
    CompilationContext,
    CompilationResult,
)
from mellea_skills_compiler.compile.claude_directives import (
    _WRAPPER_RENDERED_PATHS,
    build_pi_system_prompt,
)
from mellea_skills_compiler.compile.metadata import CompileMetadata
from mellea_skills_compiler.enums import PiMessageType
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()
console = Console(log_time=True)

# Project prompt templates, resolved against the cwd as pi itself does.
_PI_PROMPTS_DIR = Path(".pi/prompts")

# Backticked `intermediate/` references in the templates, bare or behind a
# package-dir placeholder. Tree diagrams and example log lines are unquoted
# and deliberately left alone.
_INTERMEDIATE_REF = re.compile(
    r"`(?:<package_name>/|<package_dir>/|<name>_mellea/)?intermediate/"
)

# Backticked package-dir placeholders used as a path prefix (e.g.
# `<package_name>/` or `<package_dir>/melleafy.json`). Without this, only
# `intermediate/` paths are concrete and models file Step 6 output there.
# `<name>_mellea/` is left alone: the repair template uses it for "any
# compiled package", not this one.
_PACKAGE_DIR_REF = re.compile(r"`(?:<package_name>|<package_dir>)/")

# Intermediate files the compile pipeline writes before pi starts. The step
# templates only ask the model to verify them, so they are locked read-only.
_PIPELINE_WRITTEN_PATHS: tuple[str, ...] = (
    "intermediate/runtime_directive.json",
    "intermediate/mellea_api_ref.json",
    "intermediate/mellea_doc_index.json",
)


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

        If `context.repair_mode` is True but no prior compilation exists
        (`intermediate/classification.json` is absent), this falls back to a
        fresh `/mellea-fy` run instead of `/mellea-fy-repair` — pi's own
        agentic judgment sometimes pauses to ask for confirmation when the
        repair template's Step-0 routing entry names `/mellea-fy-classify`
        as the resume sub-command in one-shot mode, rather than proceeding
        automatically the way the template instructs. Requesting `/mellea-fy`
        directly for this case sidesteps that pause; `ClaudeCodeBackend`
        follows the same template correctly and needs no such workaround.

        Args:
            context: Compilation parameters including paths, model, timeout, etc.

        Returns:
            CompilationResult with success status, package directory, and metadata.
            Also fails if pi exits 0 without producing
            `intermediate/classification.json` — a clean exit with no output
            (e.g. pi stopped to ask a question in one-shot mode) is not success.
        """
        process = None
        process_exited = False
        prompts_dir = Path(tempfile.mkdtemp(prefix="mellea-pi-prompts-"))
        placeholders: Optional[List[Path]] = None
        try:
            classification_path = context.intermediate_dir / "classification.json"
            never_compiled = not classification_path.exists()
            effective_repair_mode = context.repair_mode and not never_compiled

            if context.repair_mode and never_compiled:
                console.print(
                    "\n[yellow]No prior compilation found for this skill "
                    "(intermediate/classification.json missing) — running a "
                    "fresh /mellea-fy compile instead of /mellea-fy-repair.[/]\n"
                )

            pi_default_settings = _get_default_settings()
            provider_label = context.provider or pi_default_settings.get("defaultProvider", "anthropic")
            model_label = context.model or pi_default_settings.get("defaultModel", "default")
            console.print(
                f"\n[green]{'Repairing' if effective_repair_mode else 'Compiling'} using {self.name()}, "
                f"provider:[/] {provider_label}[green], model:[/] {model_label}\n"
            )

            # Record the chosen compilation backend and model in compile metadata
            CompileMetadata.record_backend(
                backend=self.identifier(), backend_model=model_label, provider=provider_label
            )

            # Absolute paths in everything the model sees, so it never has to
            # compose one from the cwd (small models get that wrong and write
            # outside the repo).
            package_dir = context.package_dir.resolve()
            _render_prompt_templates(package_dir, prompts_dir)

            system_prompt = build_pi_system_prompt(
                context.skill_backend or "anthropic",
                context.skill_model or context.model or "",
                context.defaults_source,
                package_dir,
                prompts_dir,
                Path(".claude/schemas").resolve(),
            )

            pi_argv = self._build_pi_argv(
                spec_path=context.spec_path.resolve(),
                repair_mode=effective_repair_mode,
                model=context.model,
                provider=context.provider,
                system_prompt=system_prompt,
                prompts_dir=prompts_dir,
            )

            placeholders = _lock_protected_paths(context.package_dir)

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
            # Error from the most recent assistant message only. Pi retries
            # transient provider errors (e.g. a truncated Ollama stream), so
            # an error followed by a successful message is not a failure.
            last_api_error: Optional[str] = None

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
                            if event["message"].get("stopReason") == "error":
                                last_api_error = str(
                                    event["message"].get(
                                        "errorMessage", "unknown error"
                                    )
                                )
                            else:
                                last_api_error = None
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

            if last_api_error:
                return CompilationResult(
                    success=False,
                    package_dir=context.package_dir,
                    error_message=(
                        f"Pi reported an error from provider '{provider_label}': "
                        f"{last_api_error}"
                    ),
                )

            if not classification_path.exists():
                return CompilationResult(
                    success=False,
                    package_dir=context.package_dir,
                    error_message=(
                        "Pi exited with return code 0 but produced no "
                        f"{classification_path} — the run likely stopped early "
                        "(e.g. pi asked a clarifying question instead of "
                        "completing) rather than compiling the skill."
                    ),
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
            if placeholders is not None:
                _unlock_protected_paths(context.package_dir, placeholders)
            prompts_dir.chmod(0o700)
            shutil.rmtree(prompts_dir, ignore_errors=True)

    def validate_environment(
        self, provider: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """Check if pi CLI and credentials are available.

        Args:
            provider: Provider to check credentials for (e.g. "anthropic",
                "ollama"). Defaults to "anthropic" when not supplied, matching
                the other two backends' effective default — this is
                intentionally NOT pi's own CLI-level default of "google".

        Returns:
            A tuple of (is_valid, error_message).
        """
        effective_provider = provider or "anthropic"

        pi_executable = shutil.which("pi")
        if pi_executable is None:
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
                    [pi_executable, "auth", "check", "--provider", effective_provider, "--json"],
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
                f"Pi credentials are not configured for provider '{effective_provider}' ({reason}). "
                f"Run 'pi auth' or configure the appropriate credentials for '{effective_provider}'."
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
        provider: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompts_dir: Optional[Path] = None,
    ) -> list[str]:
        """Build the command-line arguments for invoking pi.

        Args:
            spec_path: Path to the skill specification file
            repair_mode: Whether to use /mellea-fy-repair instead of /mellea-fy
            model: Optional model identifier to pass via --model
            provider: Optional provider identifier to pass via --provider.
                When None, --provider is omitted entirely and pi falls back
                to whatever --model's "provider/id" prefix implies, or its
                own CLI default if neither is set.
            system_prompt: Optional text appended via --append-system-prompt,
                mirroring ClaudeCodeBackend's use of the same flag to tell the
                LLM to run all steps without pausing and to emit
                *_emission.json instead of writing wrapper-rendered paths.
            prompts_dir: Optional directory of rewritten prompt templates.
                When set, project templates are disabled and this directory
                is loaded instead, so `/mellea-fy` expands from it.

        Returns:
            List of command-line arguments ready for subprocess.Popen
        """
        command = "/mellea-fy-repair" if repair_mode else "/mellea-fy"
        pi_argv: List[str] = [
            # On Windows npm installs pi as pi.cmd, which CreateProcess only
            # finds by full path.
            shutil.which("pi") or "pi",
            "-p",
            f"{command} {spec_path}",
            "--mode",
            "json",
            "--approve",
            "--tools",
            "read,write,edit,ls,find,grep",
        ]

        if prompts_dir:
            pi_argv.extend(
                ["--no-prompt-templates", "--prompt-template", str(prompts_dir)]
            )

        if system_prompt:
            pi_argv.extend(["--append-system-prompt", system_prompt])

        if provider:
            pi_argv.extend(["--provider", provider])

        if model:
            pi_argv.extend(["--model", model])

        LOGGER.debug(f"Pi command - {' '.join(pi_argv)}")

        return pi_argv


def _render_prompt_templates(package_dir: Path, out_dir: Path) -> None:
    """Copy the mellea-fy prompt templates into ``out_dir`` with concrete paths.

    The templates say ``intermediate/<file>.json`` relative to the compiled
    package, but weaker models resolve that against the spec's directory.
    Substituting the real package path removes the ambiguity rather than
    relying on the system prompt to explain it. Backticked package-dir
    placeholders and ``.claude/`` paths are made concrete too, so the model
    never composes a path from the cwd.

    Args:
        package_dir: The compiled package directory (e.g. ``skills/x/x_mellea``).
        out_dir: Directory to write the rewritten ``mellea-fy*.md`` files into.
    """
    package = package_dir.as_posix()
    claude_dir = f"`{Path('.claude').resolve().as_posix()}/"
    for template in sorted(_PI_PROMPTS_DIR.glob("mellea-fy*.md")):
        text = _INTERMEDIATE_REF.sub(f"`{package}/intermediate/", template.read_text())
        text = _PACKAGE_DIR_REF.sub(f"`{package}/", text)
        text = text.replace("`.claude/", claude_dir)
        rendered = out_dir / template.name
        rendered.write_text(text)
        rendered.chmod(0o444)
    # Read-only so the model cannot overwrite the step specs it is meant to
    # follow (observed with qwen3-coder rewriting them before Step 0).
    out_dir.chmod(0o555)


def _lock_protected_paths(package_dir: Path) -> List[Path]:
    """Make paths the model must not write read-only for the pi run.

    Pi has no path-scoped deny rule like Claude Code's ``--settings``, and
    weaker models ignore system-prompt instructions about these paths, so a
    write to any of them fails with a permission error instead:

    - wrapper-rendered paths (``config.py``, ``fixtures/``), created as empty
      placeholders when missing;
    - intermediate files the pipeline has already written;
    - an empty ``intermediate/`` next to the spec, so a model that resolves
      ``intermediate/`` against the skill directory is refused rather than
      silently writing there. An existing directory there is left alone.

    Args:
        package_dir: The compiled package directory.

    Returns:
        The placeholders this call created, for `_unlock_protected_paths`.
    """
    created: List[Path] = []
    for rel in _WRAPPER_RENDERED_PATHS:
        is_dir = rel.endswith("/**")
        path = package_dir / rel.removesuffix("/**")
        if not path.exists():
            path.mkdir() if is_dir else path.touch()
            created.append(path)
        if is_dir:
            for child in path.rglob("*"):
                child.chmod(0o555 if child.is_dir() else 0o444)
            path.chmod(0o555)
        else:
            path.chmod(0o444)
    for rel in _PIPELINE_WRITTEN_PATHS:
        path = package_dir / rel
        if path.exists():
            path.chmod(0o444)
    skill_root_intermediate = package_dir.parent / "intermediate"
    if not skill_root_intermediate.exists():
        skill_root_intermediate.mkdir()
        skill_root_intermediate.chmod(0o555)
        created.append(skill_root_intermediate)
    return created


def _unlock_protected_paths(package_dir: Path, created: List[Path]) -> None:
    """Undo `_lock_protected_paths` so the wrapper can render and clean up.

    Restores write permission and removes placeholders that are still empty.
    """
    for rel in _WRAPPER_RENDERED_PATHS:
        path = package_dir / rel.removesuffix("/**")
        if not path.exists():
            continue
        if path.is_dir():
            path.chmod(0o755)
            for child in path.rglob("*"):
                child.chmod(0o755 if child.is_dir() else 0o644)
        else:
            path.chmod(0o644)
    for rel in _PIPELINE_WRITTEN_PATHS:
        path = package_dir / rel
        if path.exists():
            path.chmod(0o644)
    for path in created:
        if path.is_dir():
            path.chmod(0o755)
            if not any(path.iterdir()):
                path.rmdir()
        elif path.is_file() and path.stat().st_size == 0:
            path.unlink()


def _get_default_settings() -> dict:
    """Read pi's settings from ~/.pi/agent/settings.json.

    Returns:
        The parsed settings (e.g. ``defaultProvider``, ``defaultModel``), or an
        empty dict if the file does not exist.
    """
    settings_path = Path.home() / ".pi" / "agent" / "settings.json"
    if not settings_path.is_file():
        return {}
    with open(settings_path) as f:
        return json.load(f)
