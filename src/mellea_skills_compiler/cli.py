import signal
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

import typer

from mellea_skills_compiler.enums import InferenceEngineType
from mellea_skills_compiler.toolkit.logging import configure_logger


app = typer.Typer(no_args_is_help=True)
LOGGER = configure_logger()


def signal_handler(sig, frame):
    print("\nInterrupted. Exiting...")
    sys.exit(0)


# Register signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


@app.callback()
def main() -> None:
    """
    Mellea Skills Compiler CLI - Agent specification certification pipeline.

    Transform AI agent skill specifications into certified, governed pipelines
    with comprehensive risk analysis and compliance reporting.
    """


@app.command(
    help="Melleafy Compile: Decompose an Agent Spec into Mellea Code",
    epilog="Compile Mellea skill specification into a Mellea pipeline using mellea-fy Claude command.",
)
def compile(
    ctx: typer.Context,
    spec_path: Annotated[
        str,
        typer.Argument(
            help="Path to the Mellea skill specification or the folder containing the skill specs.",
        ),
    ],
    model: Annotated[
        str,
        typer.Option(
            "--model",
            "-m",
            help="Claude model for compiling a skill. Default to Sonnet.",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            "-t",
            help="Claude session timeout in seconds. Default to 4500 (75min).",
        ),
    ] = 4500,
    repair_mode: Annotated[
        bool,
        typer.Option(
            "-r",
            "--repair-mode",
            help="Identify and correct any errors effectively in Mellea skill compilation.",
        ),
    ] = False,
    no_run: Annotated[
        bool,
        typer.Option(
            "--no-run",
            help="Skip the post-compile fixture smoke-check (default ON).",
        ),
    ] = False,
    refresh_cache: Annotated[
        bool,
        typer.Option(
            "--refresh-cache",
            help="Force refresh of grounding caches (~/.cache/mellea-skills-compiler/) before compile.",
        ),
    ] = False,
    skill_backend: Annotated[
        Optional[str],
        typer.Option(
            "--skill-backend",
            help="Override the LLM backend used by the compiled skill at runtime "
            "(default from mellea_skills_compiler/compile/claude/data/runtime_defaults.json).",
        ),
    ] = None,
    skill_model: Annotated[
        Optional[str],
        typer.Option(
            "--skill-model",
            help="Override the model id used by the compiled skill at runtime "
            "(default from mellea_skills_compiler/compile/claude/data/runtime_defaults.json).",
        ),
    ] = None,
):
    """
    Compile Mellea skill specification into a Mellea pipeline using mellea-fy Claude command.

    After mellea-fy returns successfully, automatically chains into validate:
    runs the structural lints (Step 7) and (unless --no-run) executes one fixture
    against the LLM backend. A green compile means compiled + lints passed +
    smoke-check passed (or skipped because backend was unreachable).
    """
    spec_path = Path(spec_path)
    try:
        from mellea_skills_compiler.compile import mellea_skills

        mellea_skills.compile(
            spec_path,
            model,
            timeout,
            repair_mode=repair_mode,
            no_run=no_run,
            refresh_cache=refresh_cache,
            skill_backend=skill_backend,
            skill_model=skill_model,
        )
    except Exception as e:
        LOGGER.error(str(e))
        raise typer.Exit(code=1)


@app.command(
    help="Validate a compiled Mellea skill (Step 7 lints + fixture smoke-check)"
)
def validate(
    ctx: typer.Context,
    pipeline_dir: Annotated[
        str,
        typer.Argument(
            help="Compiled skill pipeline directory (e.g. skills/<name>/<name>_mellea/).",
        ),
    ],
    no_run: Annotated[
        bool,
        typer.Option(
            "--no-run",
            help="Skip the post-lint fixture smoke-check (default ON).",
        ),
    ] = False,
    all_fixtures: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Run all fixtures (default: first only).",
        ),
    ] = False,
):
    """
    Run Step 7 structural lints and (unless --no-run) the fixture smoke-check.

    Exit codes:
      0  — lints passed, smoke-check passed or skipped (backend unreachable)
      11 — at least one lint failed
      12 — smoke-check failed (lint pass, but a fixture raised an exception)
    """
    try:
        from mellea_skills_compiler.compile import mellea_skills

        mellea_skills.validate(
            Path(pipeline_dir), no_run=no_run, all_fixtures=all_fixtures
        )
    except Exception as e:
        LOGGER.error(str(e))
        raise typer.Exit(code=1)


@app.command(help="Run Mellea Skill Pipeline")
def run(
    ctx: typer.Context,
    pipeline_dir: Annotated[
        str,
        typer.Argument(
            help="Compiled skill pipeline directory.",
        ),
    ],
    fixture: Annotated[
        str,
        typer.Option(
            "--fixture",
            "-f",
            help="Run pipeline for a specific fixture.",
        ),
    ],
    enforce: Annotated[
        bool,
        typer.Option(
            "--enforce",
            "-e",
            help="Block execution when Guardian detects risks (default: audit-only).",
        ),
    ] = False,
    no_guardian: Annotated[
        bool,
        typer.Option(
            "--no-guardian",
            "-ng",
            help="Skip Guardian checks even if a policy manifest exists.",
        ),
    ] = False,
):
    """
    Run Mellea Skill Pipeline.
    """

    try:
        from mellea_skills_compiler.certification.pipeline import skill_pipeline

        skill_pipeline(
            Path(pipeline_dir), fixture, enforce=enforce, no_guardian=no_guardian
        )
    except Exception as e:
        LOGGER.error(str(e))
        raise typer.Exit(code=1)


@app.command(help="Run Risk Analysis and Policy Generation Pipeline for Mellea skills")
def ingest(
    ctx: typer.Context,
    spec_path: Annotated[
        str,
        typer.Argument(
            help="Mellea Skill spec path",
            rich_help_panel="Arguments",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Preview without making LLM calls", show_default=True
        ),
    ] = False,
    model: Annotated[
        Optional[str],
        typer.Option(
            "--model",
            "-m",
            help="Model to use for Risk and Action Identification. The `--inference-engine` option must support the model. If set to None, the default model for the inference engine will be used.",
        ),
    ] = None,
    inference_engine: Annotated[
        Literal["ollama"],
        typer.Option(
            "--inference-engine",
            "-i",
            callback=lambda x: x.upper(),
            help="Service to use for LLM inference. Supported: ollama",
        ),
    ] = "ollama",
):
    """
    Run risk analysis on a skill specification.

    Analyzes the skill spec to identify risks and generate a policy document
    without running full certification.
    """
    try:
        from mellea_skills_compiler.certification.ingest import ingest_one

        ingest_one(
            Path(spec_path),
            dry_run,
            model,
            InferenceEngineType[inference_engine],
        )
    except Exception as e:
        LOGGER.error(str(e))
        raise typer.Exit(code=1)


@app.command(help="Run Full Certification Pipeline for Mellea skill")
def certify(
    ctx: typer.Context,
    pipeline_dir: Annotated[
        str,
        typer.Argument(
            help="Compiled skill pipeline directory.",
            rich_help_panel="Arguments",
        ),
    ],
    fixture: Annotated[
        Optional[str],
        typer.Option(
            "--fixture",
            "-f",
            help="Run pipeline for a specific fixture.",
        ),
    ] = None,
    enforce: Annotated[
        bool,
        typer.Option(
            "--enforce",
            "-e",
            help="Run pipeline in enforce mode (block on risk detection)",
        ),
    ] = False,
    model: Annotated[
        Optional[str],
        typer.Option(
            "--model",
            "-m",
            help="Model to use for Risk and Action Identification. The `--inference-engine` option must support the model. If set to None, the default model for the inference engine will be used.",
        ),
    ] = None,
    guardian_model: Annotated[
        Optional[str],
        typer.Option(
            "--guardian-model",
            "-g",
            help="Model to use for Risk Assessment. The `--inference-engine` option must support the model. If set to None, the default guardian model for the inference engine will be used.",
        ),
    ] = None,
    inference_engine: Annotated[
        Literal["ollama"],
        typer.Option(
            "--inference-engine",
            "-i",
            callback=lambda x: x.upper(),
            help="Service to use for LLM inference. Supported: ollama",
        ),
    ] = "ollama",
):
    """
    Run full certification pipeline on a compiled skill.

    Performs comprehensive certification including risk identification,
    compliance classification, and runtime Guardian checks.
    """
    try:
        from mellea_skills_compiler.certification.pipeline import full_pipeline

        full_pipeline(
            Path(pipeline_dir),
            fixture,
            enforce,
            model,
            guardian_model,
            InferenceEngineType[inference_engine],
        )
    except Exception as e:
        LOGGER.error(str(e))
        raise typer.Exit(code=1)


@app.command(
    help="[EXPERIMENTAL] Export a compiled Mellea skill to a deployment target"
)
def export(
    ctx: typer.Context,
    package_path: Annotated[
        str,
        typer.Argument(
            help="Path to the compiled skill directory (must contain melleafy.json).",
        ),
    ],
    target: Annotated[
        str,
        typer.Option(
            "--target",
            "-t",
            help="Deployment target: langgraph | claude-code | mcp",
        ),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite output directory if it already exists.",
        ),
    ] = False,
):
    """
    Export a compiled Mellea skill to a deployment target (langgraph, claude-code, or mcp).

    Output is written to <package_name>/<package_name>-<target> inside the skill directory.

    NOTE: This command is experimental. Output structure and CLI interface may change
    in future releases without a deprecation period.
    """
    LOGGER.warning(
        "export is an experimental feature — output structure and interface may change between releases"
    )
    try:
        from mellea_skills_compiler.export.exporter import Invocation, run_export

        inv = Invocation(
            package_path=Path(package_path),
            target=target,
            force=force,
        )
        result = run_export(inv)
        LOGGER.info(
            "Export complete: %d files, %d bytes → %s",
            result.files_written,
            result.bytes_written,
            result.out_path,
        )
    except SystemExit:
        raise
    except Exception as e:
        LOGGER.error(str(e))
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
