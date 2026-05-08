import json
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
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel

from mellea_skills_compiler.compile import CLAUDE_DIR
from mellea_skills_compiler.compile.claude_directives import (
    build_system_prompt,
    derive_package_name,
    mirror_companion_dirs,
    resolve_runtime_defaults,
    write_compile_settings,
    write_runtime_directive,
)
from mellea_skills_compiler.compile.grounding import (
    write_mellea_api_ref,
    write_mellea_doc_index,
)
from mellea_skills_compiler.compile.proxy import ContextMgmtStrippingProxy
from mellea_skills_compiler.enums import (
    ClaudeResponseMessageType,
    ClaudeResponseType,
    InferenceModel,
    SpecFileFormat,
)
from mellea_skills_compiler.toolkit.file_utils import parse_spec_file
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()
console = Console(log_time=True)


def _get_spec_md_path(spec_path: Path):
    spec_file_path = None
    if spec_path.is_dir():
        if (spec_path / SpecFileFormat.SKILL_FILE_MD).exists():
            spec_file_path = spec_path / SpecFileFormat.SKILL_FILE_MD
        elif (spec_path / SpecFileFormat.SPEC_FILE_MD).exists():
            spec_file_path = spec_path / SpecFileFormat.SPEC_FILE_MD
    elif spec_path.suffix == ".md":
        spec_file_path = spec_path

    return spec_file_path


def validate(package_dir: Path, *, no_run: bool, all_fixtures: bool) -> None:
    """Shared implementation for the validate command and the compile auto-chain."""
    if not package_dir.exists() or not package_dir.is_dir():
        raise Exception("Package directory does not exist: %s", package_dir)

    from mellea_skills_compiler.compile.lints import run_lints

    lint_result = run_lints(package_dir)
    if lint_result.failed:
        for lint in lint_result.lints:
            if lint.verdict != "fail":
                continue
            LOGGER.error("[%s] %d failure(s):", lint.lint_id, len(lint.failures))
            for failure in lint.failures:
                location = failure.file
                if failure.line is not None:
                    location = f"{location}:{failure.line}"
                LOGGER.error("  %s — %s", location, failure.message)
        raise Exception(
            "Step 7 lints failed. Report at %s/intermediate/step_7_report.json",
            package_dir,
        )

    LOGGER.info(
        "Step 7 structural lints passed (%d lints checked).", len(lint_result.lints)
    )

    if no_run:
        LOGGER.info("Smoke-check skipped (--no-run).")
        return

    from mellea_skills_compiler.compile.smoke_check import run_smoke_check

    try:
        smoke_result = run_smoke_check(package_dir, all_fixtures=all_fixtures)
    except Exception as exc:
        raise Exception(
            "Smoke-check infrastructure error (could not even start): %s", exc
        )

    if smoke_result.overall_verdict == "failed":
        for fixture in smoke_result.fixtures:
            if fixture.verdict == "failed":
                LOGGER.error(
                    "Fixture '%s' failed: %s",
                    fixture.fixture_id,
                    fixture.failure_message,
                )
        raise Exception(
            "Smoke-check failed. Report at %s/intermediate/step_7b_report.json",
            package_dir,
        )

    LOGGER.info(
        "Smoke-check %s — %d fixture(s) executed.",
        smoke_result.overall_verdict,
        len(smoke_result.fixtures),
    )


def compile(
    spec_path: Path,
    model: Optional[str] = None,
    timeout: int = 4500,
    repair_mode: bool = False,
    no_run: bool = False,
    refresh_cache: bool = False,
    skill_backend: Optional[str] = None,
    skill_model: Optional[str] = None,
) -> None:
    # clears screen
    subprocess.call("clear")

    # print mellea-fy header
    console.print()
    if repair_mode:
        console.rule(
            f"[bold yellow] Melleafy Repair: Inspect and Resume a Partial or Failed Run[/]"
        )
    else:
        console.rule(
            f"[bold yellow] Melleafy: Decompose an Agent Spec into Mellea Code[/]"
        )
    console.print()

    # For spec file input only: verify that file ends in a .md extension
    if spec_path.suffix and spec_path.suffix != ".md":
        raise ValueError(
            f"Skill specification input can only be a markdown (.md) file or a valid skill directory."
        )
    # For [spec file / spec directory] input, Verify that destination exists
    elif not spec_path.exists():
        raise FileNotFoundError(
            f"The skill specification file or directory cannot be found: {spec_path}"
        )

    # print specs frontmatter if available
    if spec_md_path := _get_spec_md_path(spec_path):
        try:
            specs = parse_spec_file(spec_md_path)
            rprint(
                Panel(
                    json.dumps(
                        specs.get("frontmatter", {"Name", spec_path.name}), indent=2
                    ),
                    title="Specification",
                    subtitle=str(spec_path),
                )
            )
        except Exception:
            console.print(f"Spec Path: " + str(spec_path))
    else:
        console.print(f"Spec Path: " + str(spec_path))

    # Check and verify claude model
    available_models = [model.id for model in Anthropic().models.list()]
    if not available_models:
        raise ValueError(f"No claude models available with your API key.")

    if model:
        if model in available_models:
            # user provided model in available in available models.
            pass
        else:
            raise ValueError(
                f"Invalid Claude model provided - {model}\nAvailable: {available_models}"
            )
    else:
        # User did not provide the Claude model. Therefore, filter the available models by the GraniteClaw default and select the first one.
        models = [
            model
            for model in available_models
            if InferenceModel.CLAUDE_MODEL in model.lower()
        ]
        if not models:
            # Available models does not have the GraniteClaw default. Ask user to choose one.
            raise ValueError(
                f"Please provide claude model via --model option.\nAvailable: {available_models}"
            )
        else:
            # Use the first model to compile given skill
            model = models[0]

    console.print(
        f"\n[green]{'Repairing' if repair_mode else 'Compiling'} using Claude model:[/] {model}\n"
    )

    # Start a local proxy that strips context_management from API requests.
    # The IBM LiteLLM proxy rejects that field; Claude Code sends it automatically.
    # Forward to the real upstream (ANTHROPIC_BASE_URL if set, else api.anthropic.com).
    _real_base = os.environ.get(
        "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
    ).rstrip("/")
    _parsed = urlparse(_real_base)
    proxy_server = socketserver.ThreadingTCPServer(
        ("127.0.0.1", 0), ContextMgmtStrippingProxy
    )
    proxy_server.allow_reuse_address = True
    proxy_server.upstream_scheme = _parsed.scheme
    proxy_server.upstream_host = _parsed.netloc
    proxy_server.upstream_path_prefix = _parsed.path
    proxy_port = proxy_server.server_address[1]
    proxy_thread = threading.Thread(target=proxy_server.serve_forever)
    proxy_thread.daemon = True
    proxy_thread.start()

    subprocess_env = {
        **os.environ,
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{proxy_port}",
    }

    # Rule OUT-6 — mirror companion directories from skill root into the
    # package directory BEFORE invoking mellea-fy. This is deterministic
    # plumbing (not the LLM's job) so the mirror cannot be skipped or
    # mis-applied. The LLM then generates code in a package directory that
    # already contains its bundled scripts/references/assets, reinforcing
    # the Path(__file__).parent path-resolution invariant.
    skill_dir = spec_path if spec_path.is_dir() else spec_path.parent
    _frontmatter: dict | None = None
    if not spec_path.is_dir() and spec_path.suffix == ".md":
        try:
            _frontmatter = parse_spec_file(spec_path).get("frontmatter")
        except Exception:
            _frontmatter = None
    package_name = derive_package_name(spec_path, _frontmatter)
    package_dir = skill_dir / package_name
    try:
        mirrored = mirror_companion_dirs(skill_dir, package_dir)
        if mirrored:
            LOGGER.info(
                "Mirrored companion dirs into %s/: %s (Rule OUT-6)",
                package_name,
                ", ".join(mirrored),
            )
    except Exception as mirror_exc:
        LOGGER.warning(
            "Companion-directory mirror failed for %s: %s. mellea-fy will continue.",
            package_dir,
            mirror_exc,
        )

    # Pre-populate the deterministic grounding artifacts (Steps 2.5e and 2.5f
    # of mellea-fy). The slash command runs with --allowed-tools Read,Write,Edit,
    # so it cannot introspect the installed mellea package or fetch
    # docs.mellea.ai itself. We write `mellea_api_ref.json` and
    # `mellea_doc_index.json` here; the slash command's responsibility shrinks
    # to verifying the files exist and consuming them.
    intermediate_dir = package_dir / "intermediate"
    try:
        write_mellea_api_ref(intermediate_dir, refresh=refresh_cache)
        write_mellea_doc_index(intermediate_dir, refresh=refresh_cache)
    except Exception as exc:
        LOGGER.warning(
            "Grounding generation failed: %s. mellea-fy will fall back.", exc
        )

    # Resolve which backend and model the compiled skill will use at runtime,
    # record the choice for the post-compile lint, and bake the values into
    # the system prompt so the LLM puts the correct constants in config.py.
    chosen_backend, chosen_model_id, defaults_source = resolve_runtime_defaults(
        skill_backend, skill_model
    )
    LOGGER.info(
        "Compiled skill will use backend=%r, model=%r (from %s).",
        chosen_backend,
        chosen_model_id,
        defaults_source,
    )
    try:
        write_runtime_directive(
            intermediate_dir, chosen_backend, chosen_model_id, defaults_source
        )
    except Exception as exc:
        LOGGER.warning(
            "Could not record runtime directive (%s). Compile will continue; "
            "the post-compile lint will skip its runtime-defaults check.",
            exc,
        )
    system_prompt = build_system_prompt(
        chosen_backend, chosen_model_id, defaults_source
    )

    # Write the per-invocation Claude Code settings file with deny rules for
    # the paths the wrapper renders authoritatively (currently config.py).
    # Passed to claude via --settings; deny rules are honoured deterministically
    # in -p mode (verified in the synthetic test).
    try:
        compile_settings_path = write_compile_settings(intermediate_dir, package_dir)
    except Exception as exc:
        LOGGER.warning(
            "Could not write per-invocation settings (%s). Falling back to no "
            "deny rules; the wrapper will still overwrite wrapper-rendered paths.",
            exc,
        )
        compile_settings_path = None

    # Start compilation process
    process = None
    claude_argv = [
        "claude",
        "-p",
        "--model",
        f"{model}",
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

    claude_argv.append(
        f"'{"./mellea-fy-repair" if repair_mode else "./mellea-fy"} {str(spec_path)}'"
    )

    # Set Mellea-fy process start time
    start_time = time.time()

    # Create processing animation
    processing = console.status(
        "[italic bold yellow]Processing...[/]", spinner_style="status.spinner"
    )

    try:
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
            for line in iter(process.stderr.readline, ""):
                if line:
                    stderr_lines.append(line.strip())

        # Thread for reading stderr
        stderr_thread = threading.Thread(target=read_stderr)
        stderr_thread.daemon = True
        stderr_thread.start()

        # Read stdout in main thread
        processing.start()
        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                raise TimeoutError(
                    f"Mellea-fy skill compilation failed due to timeout. Process timed out after {elapsed}s (limit: {timeout}s)"
                )

            # Read output
            output = process.stdout.readline()

            if output == "" and process.poll() is not None:
                processing.stop()
                break

            if output:
                try:
                    response = json.loads(output.strip())
                    if response.get("type", None) == ClaudeResponseType.ASSISTANT:
                        for message_content in response.get("message", {}).get(
                            "content", []
                        ):
                            if (
                                message_content.get("type", None)
                                == ClaudeResponseMessageType.TEXT
                            ):
                                console.print(
                                    f"[cyan]{message_content.get('text', '')}[/]\n"
                                )
                except json.decoder.JSONDecodeError as e:
                    console.print("Claude message parsing error: " + str(e))

        # Wait for stderr thread
        stderr_thread.join(timeout=1)

        # Print error if process failed.
        return_code = process.wait(timeout=1)
        if return_code != 0:
            raise subprocess.SubprocessError(
                f"Mellea-fy skill compilation failed with return code {return_code}. "
                f"Error: {' '.join(stderr_lines)}"
            )

        # copy spec file into the compiled directory (name may differ from frontmatter
        # because melleafy normalises hyphens → underscores per Rule OUT-2)
        skill_dir = spec_path if spec_path.is_dir() else spec_path.parent
        mellea_dirs = [
            d for d in skill_dir.iterdir() if d.is_dir() and d.name.endswith("_mellea")
        ]
        if mellea_dirs:
            # Wrapper-side writer invocation (migration phase: WARN only).
            # Reads intermediate/<artifact>_emission.json, runs the deterministic
            # writer in .claude/melleafy/writers/, and diffs the output against
            # the file the LLM put on disk. Logs WARN on diff so we can build
            # confidence the diffs are stable before flipping to ENFORCE mode.
            try:
                from mellea_skills_compiler.compile.writer_renderer import (
                    default_writer_specs,
                    render_writers,
                )

                # Repo root = directory holding `.claude/`. Walk up from the
                # package dir until we find it.
                repo_root = mellea_dirs[0]
                for parent in [repo_root, *repo_root.parents]:
                    if (parent / ".claude" / "melleafy" / "writers").is_dir():
                        repo_root = parent
                        break
                render_writers(
                    mellea_dirs[0],
                    default_writer_specs(repo_root),
                    enforce=True,  # config.py promoted from WARN to ENFORCE in Step 3
                )
            except Exception as renderer_exc:  # noqa: BLE001
                LOGGER.warning(
                    "Writer renderer failed (non-fatal during migration): %s",
                    renderer_exc,
                )

            # validate compiled skill pipeline
            validate(mellea_dirs[0], no_run=no_run, all_fixtures=False)

            if spec_md_path:
                shutil.copy(spec_md_path, mellea_dirs[0] / SpecFileFormat.SKILL_FILE_MD)
        else:
            raise Exception(
                f"No *_mellea directory found in {skill_dir} after compilation"
            )

    except (TimeoutError, subprocess.SubprocessError):
        processing.stop()
        if process and process.poll() is None:
            process.kill()
            process.wait()
        raise
    except Exception as e:
        processing.stop()
        if process and process.poll() is None:
            process.kill()
            process.wait()
        raise Exception(f"Mellea-fy skill compilation failed: {str(e)}") from e
    finally:
        proxy_server.shutdown()

    console.print(
        f"\nMelleafy {'Repair' if repair_mode else 'Compile'} completed successfully.\n"
    )
