import json
import shutil
from pathlib import Path
from typing import Dict, Optional

from rich import print as rprint
from rich.console import Console
from rich.panel import Panel

from mellea_skills_compiler.compile.backend import (
    CompilationBackend,
    CompilationContext,
    CompilationResult,
    global_registry,
)
from mellea_skills_compiler.compile.claude_directives import (
    resolve_runtime_defaults,
    write_runtime_directive,
)
from mellea_skills_compiler.compile.grounding import (
    write_mellea_api_ref,
    write_mellea_doc_index,
)
from mellea_skills_compiler.compile.writers.renderer import render_writers
from mellea_skills_compiler.enums import SpecFileFormat
from mellea_skills_compiler.toolkit.file_utils import (
    mirror_dir_contents_to_target,
    parse_spec_file,
)
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()
console = Console(log_time=True)

IGNORE_COMPANION_DIRS_ITEMS = ["audit", "pyproject.toml"]


def _select_canonical_mellea_dir(spec_dir: Path, package_name: str) -> Path:
    """Return the canonical *_mellea directory list under ``spec_dir``.

    Filters ``spec_dir`` for entries ending in ``_mellea`` and resolves which
    one is the wrapper-canonical compiled package per the wrapper-derived
    ``package_name``. The LLM is now told the package name verbatim via
    ``build_system_prompt`` (see ``compile/claude_directives.py``), so under
    normal operation exactly one matching directory exists. The cases below
    are defensive — historical compiles produced stray sibling ``*_mellea``
    directories from LLM name-derivation drift on long hyphenated frontmatter
    names. Selecting by name rather than blind ``[0]`` avoids the wrapper
    rendering/validating a stray sibling on filesystem-ordering coincidence.

    Returns:
        A Path containing the canonical mellea directory

    Raises:
        Exception: if more than one ``*_mellea`` directory exists and none
            match ``package_name``. Cleaning up the stray sibling and
            re-running is required.
    """

    mellea_dirs = [
        d for d in spec_dir.iterdir() if d.is_dir() and d.name.endswith("_mellea")
    ]
    if len(mellea_dirs) > 1:
        canonical = [d for d in mellea_dirs if d.name == package_name]
        stray = [d for d in mellea_dirs if d.name != package_name]
        if canonical:
            LOGGER.warning(
                "Found %d *_mellea directories in %s; expected only one. "
                "Selecting canonical %r; stray sibling(s) %s likely "
                "originate from LLM name-derivation drift on long "
                "frontmatter names (Rule OUT-2). Clean them up after "
                "the compile completes.",
                len(mellea_dirs),
                spec_dir,
                canonical[0].name,
                [d.name for d in stray],
            )
            return canonical[0]
        raise Exception(
            f"Found {len(mellea_dirs)} *_mellea directories in "
            f"{spec_dir}, none matching the wrapper-derived "
            f"package name {package_name!r}: "
            f"{[d.name for d in mellea_dirs]}. Remove stray "
            f"directories and re-run."
        )
    if len(mellea_dirs) == 1 and mellea_dirs[0].name != package_name:
        LOGGER.warning(
            "Compiled package directory %r does not match the "
            "wrapper-derived package name %r — the LLM produced a "
            "different name. Proceeding with the LLM's directory, but "
            "downstream tooling that expects the canonical name may "
            "fail. Re-emit with the corrected name or rename the "
            "directory if this affects export.",
            mellea_dirs[0].name,
            package_name,
        )

    if not mellea_dirs:
        raise Exception(f"No *_mellea directory found in {spec_dir} after compilation")

    return mellea_dirs[0]


def _get_spec_md_path(spec_path: Path) -> Optional[Path]:
    spec_file_path = None
    if spec_path.is_dir():
        if (spec_path / SpecFileFormat.SKILL_FILE_MD).exists():
            spec_file_path = spec_path / SpecFileFormat.SKILL_FILE_MD
        elif (spec_path / SpecFileFormat.SPEC_FILE_MD).exists():
            spec_file_path = spec_path / SpecFileFormat.SPEC_FILE_MD
    elif spec_path.suffix == ".md":
        spec_file_path = spec_path

    return spec_file_path


def _derive_mellea_package_name(spec_path: Path, frontmatter: Optional[Dict]) -> str:
    """Apply Rule OUT-2 (lowercase, hyphens/spaces → underscores, append `_mellea`).

    For .md sources, prefer the frontmatter `name:` field; fall back to the
    parent directory name. For directory inputs (multi-file runtimes), use
    the directory name.
    """
    if spec_path.is_dir():
        raw = spec_path.name
    else:
        raw = (frontmatter or {}).get("name") or spec_path.parent.name
    name = str(raw).lower().replace("-", "_").replace(" ", "_")
    while "__" in name:
        name = name.replace("__", "_")
    name = name.strip("_") or "skill"
    return f"{name}_mellea"


def validate(package_dir: Path, *, no_run: bool, all_fixtures: bool) -> None:
    """Shared implementation for the validate command and the compile auto-chain."""
    if not package_dir.exists() or not package_dir.is_dir():
        raise Exception(f"Package directory does not exist: {package_dir}")

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
            f"Step 7 lints failed. Report at {str(package_dir)}/intermediate/step_7_report.json"
        )

    LOGGER.info(
        "Step 7 structural lints passed (%d lints checked).",
        len(lint_result.lints),
    )

    if no_run:
        LOGGER.info("Smoke-check skipped (--no-run).")
        return

    from mellea_skills_compiler.compile.smoke_check import run_smoke_check

    try:
        smoke_result = run_smoke_check(package_dir, all_fixtures=all_fixtures)
    except Exception as exc:
        raise Exception(
            f"Smoke-check infrastructure error (could not even start): {exc}"
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
            f"Smoke-check failed. Report at {package_dir}/intermediate/step_7b_report.json"
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
    skip_smoke_check: bool = False,
    refresh_cache: bool = False,
    skill_backend: Optional[str] = None,
    skill_model: Optional[str] = None,
    backend: str = "claude",
    provider: Optional[str] = None,
) -> None:
    """Compile an agent specification into a Mellea skill package.

    Validates the backend environment, mirrors companion directories into the package,
    pre-populates grounding artefacts (API ref and doc index), and delegates the actual
    LLM-driven compilation to the chosen backend. On success, writers are rendered and the
    package is validated.

    Args:
        spec_path (Path): Path to the skill specification — either a ``spec.md``
            / ``SKILL.md`` file or a skill directory that contains one.
        model (Optional[str], optional): Model identifier passed to the
            *compilation* backend (i.e. the model that writes the code), e.g.
            ``"claude-opus-4-5"``. When ``None`` the backend's own default is
            used. Defaults to None.
        timeout (int, optional): Maximum wall-clock seconds allowed for the
            backend compilation step. Defaults to 4500.
        repair_mode (bool, optional): When ``True`` the backend runs a repair
            workflow that inspects a partial or failed previous run and resumes
            from where it left off, rather than starting a fresh compilation.
            Defaults to False.
        skip_smoke_check (bool, optional): When ``True`` the post-compile validation step
            skips executing the skill's test fixtures, performing only static
            checks. Defaults to False.
        refresh_cache (bool, optional): When ``True`` forces regeneration of
            cached grounding artefacts (``mellea_api_ref.json`` and
            ``mellea_doc_index.json``) even if up-to-date copies already exist.
            Defaults to False.
        skill_backend (Optional[str], optional): Runtime inference backend that
            the *compiled skill* will use when executed by end-users. Overrides the project-level
            ``runtime_defaults.json`` when supplied. Defaults to None.
        skill_model (Optional[str], optional): Runtime model identifier that the
            *compiled skill* will use when executed, e.g.
            ``"granite4.1:3b"``. Overrides the project-level
            ``runtime_defaults.json`` when supplied. Defaults to None.
        backend (str, optional): Compilation backend identifier used to look up
            the backend implementation from the global registry (e.g.
            ``"claude"``, ``"bob"``). Defaults to "claude".
        provider (Optional[str], optional): Provider identifier passed to the
            *compilation* backend when it supports provider selection
            (pi-only currently, e.g. "anthropic", "ollama"). Ignored by
            backends that don't support it. Defaults to None.

    Raises:
        RuntimeError: If the requested backend is unavailable or if compilation
            or post-compile validation fails.
        ValueError: If ``spec_path`` has an extension other than ``.md``.
        FileNotFoundError: If ``spec_path`` does not exist on disk.
    """
    # clears screen
    console.clear()

    # Get the backend implementation and validate its environment
    backend_impl: CompilationBackend = global_registry.get_backend(identifier=backend)
    if backend == "pi":
        is_valid, error_msg = backend_impl.validate_environment(provider=provider)
    else:
        is_valid, error_msg = backend_impl.validate_environment()
    if not is_valid:
        raise RuntimeError(f"Provided backend '{backend}' not available - {error_msg}")

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

    # Get spec related fields
    spec_frontmatter: Optional[Dict] = None
    spec_dir = spec_path if spec_path.is_dir() else spec_path.parent
    spec_md_path = _get_spec_md_path(spec_path)
    try:
        if spec_md_path:
            spec_frontmatter = parse_spec_file(spec_md_path).get("frontmatter")
    except Exception as e:
        LOGGER.warning(f"Failed to parse spec file {spec_md_path}: {e}")

    if spec_frontmatter:
        rprint(
            Panel(
                json.dumps(spec_frontmatter, indent=2),
                title="Specification",
                subtitle=str(spec_path),
            )
        )
    else:
        display_name = spec_path.name.replace("_", " ").title()
        rprint(
            Panel(
                f"Name: {display_name}\nPath: {str(spec_path)}",
                title="Specification",
            )
        )

    # Derive mellea package name from the spec frontmatter
    mellea_package_name = _derive_mellea_package_name(spec_path, spec_frontmatter)
    mellea_package_dir = spec_dir / mellea_package_name

    # Rule OUT-6 — mirror companion directories from skill root into the
    # package directory BEFORE invoking mellea-fy. This is deterministic
    # plumbing (not the LLM's job) so the mirror cannot be skipped or
    # mis-applied. The LLM then generates code in a package directory that
    # already contains its bundled scripts/references/assets, reinforcing
    # the Path(__file__).parent path-resolution invariant.
    try:
        mirrored = mirror_dir_contents_to_target(
            spec_dir,
            mellea_package_dir,
            ignore_patterns=IGNORE_COMPANION_DIRS_ITEMS + [mellea_package_name],
        )
        if mirrored:
            LOGGER.info(
                f"Mirrored {len(mirrored)} item(s) into {mellea_package_name}/: {', '.join(mirrored)} (Rule OUT-6)"
            )
    except Exception as mirror_exc:
        LOGGER.warning(
            f"Companion-directory mirror failed for {mellea_package_dir}: {mirror_exc}. mellea-fy will continue."
        )

    # Pre-populate the deterministic grounding artifacts (Steps 2.5e and 2.5f
    # of mellea-fy). The slash command runs with --allowed-tools Read,Write,Edit,
    # so it cannot introspect the installed mellea package or fetch
    # docs.mellea.ai itself. We write `mellea_api_ref.json` and
    # `mellea_doc_index.json` here; the slash command's responsibility shrinks
    # to verifying the files exist and consuming them.
    intermediate_dir = mellea_package_dir / "intermediate"
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
        "Compiled skill will use inference service=%r, model=%r (from %s).",
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

    # Build compilation context and execute via backend
    context: CompilationContext = CompilationContext(
        spec_path=spec_path,
        package_dir=mellea_package_dir,
        intermediate_dir=intermediate_dir,
        model=model,
        timeout=timeout,
        repair_mode=repair_mode,
        skill_backend=chosen_backend,
        skill_model=chosen_model_id,
        defaults_source=defaults_source,
        refresh_cache=refresh_cache,
        provider=provider,
    )

    result: CompilationResult = backend_impl.compile(context)
    if not result.success:
        raise RuntimeError(f"Compilation failed - {result.error_message}")
    LOGGER.info("Backend compilation completed successfully")

    # Post-compile: render writers, validate, copy spec file
    try:
        mellea_dir: Path = _select_canonical_mellea_dir(spec_dir, mellea_package_name)
        if spec_md_path:
            shutil.copy(spec_md_path, mellea_dir / SpecFileFormat.SKILL_FILE_MD)
        render_writers(mellea_dir, enforce=True)
        validate(mellea_dir, no_run=skip_smoke_check, all_fixtures=False)
    except Exception as e:
        raise RuntimeError(
            f"Compilation failed with backend '{backend}': {str(e)}"
        ) from e

    console.print(
        f"\nMelleafy {'Repair' if repair_mode else 'Compile'} completed successfully.\n"
    )
