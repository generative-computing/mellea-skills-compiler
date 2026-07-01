import json
from pathlib import Path
from typing import Optional

from mellea_skills_compiler.toolkit.logging import configure_logger

LOGGER = configure_logger()


# Defaults for the LLM backend and model that compiled skills use at runtime.
# Sourced from .claude/data/runtime_defaults.json with optional CLI overrides.
_RUNTIME_DEFAULTS_PATH = Path(".claude/data/runtime_defaults.json")
_RUNTIME_DEFAULTS_FALLBACK = {"backend": "ollama", "model_id": "granite3.3:8b"}


def resolve_runtime_defaults(
    skill_backend_override: Optional[str], skill_model_override: Optional[str]
) -> tuple[str, str, str]:
    """Pick the backend and model_id to bake into the compiled skill.

    Precedence: CLI overrides win, then the defaults file, then a built-in
    fallback if the file is missing or unreadable. Returns
    (backend, model_id, source) where source records where the values came
    from for the compile log.
    """
    file_backend = _RUNTIME_DEFAULTS_FALLBACK["backend"]
    file_model_id = _RUNTIME_DEFAULTS_FALLBACK["model_id"]
    source = "built-in fallback"
    if _RUNTIME_DEFAULTS_PATH.exists():
        try:
            data = json.loads(_RUNTIME_DEFAULTS_PATH.read_text())
            file_backend = data.get("backend", file_backend)
            file_model_id = data.get("model_id", file_model_id)
            source = f"defaults file ({_RUNTIME_DEFAULTS_PATH})"
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning(
                "Could not read %s (%s). Using built-in fallback values: backend=%r, model_id=%r.",
                _RUNTIME_DEFAULTS_PATH,
                exc,
                file_backend,
                file_model_id,
            )
    if skill_backend_override or skill_model_override:
        source = "command-line override"
    return (
        skill_backend_override or file_backend,
        skill_model_override or file_model_id,
        source,
    )


# Paths under <package_name>/ that the wrapper renders authoritatively from
# emission JSON. The slash command must NOT write or edit these — `--settings`
# deny rules block the Write/Edit tool calls, and the wrapper overwrites with
# the writer's output post-mellea-fy. Add new entries here as each writer is
# migrated to enforce mode. Glob patterns are supported (verified end-to-end
# in the synthetic deny-rule test: `Write(forbidden/**)` blocked nested writes).
_WRAPPER_RENDERED_PATHS: tuple[str, ...] = (
    "config.py",
    "fixtures/**",
)


def write_compile_settings(intermediate_dir: Path, package_dir: Path) -> Path:
    """Write a per-invocation Claude Code --settings file with the deny rules.

    Path-scoped Write/Edit denies prevent the LLM from clobbering files the
    wrapper will render after the slash command exits. acceptEdits permission
    mode does NOT override deny — Anthropic's evaluation order is deny → mode
    → allow (verified end-to-end in the synthetic deny-rule test).

    Important: the deny rule paths must match what the LLM actually tries to
    write. Claude Code interprets relative paths against the subprocess cwd
    (the user's shell cwd, typically the repo root). So the deny path must be
    the full path-from-cwd to the package, not just the bare package name.
    Earlier versions used `package_name/<rel>`, which mis-scoped the deny to
    `<cwd>/<package_name>/<rel>` and confused the LLM into creating the
    package at the wrong location.
    """
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    # Resolve the path the LLM's Write tool calls will actually use.
    try:
        rel_pkg = package_dir.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        # package_dir is outside cwd — Claude Code accepts absolute paths too.
        rel_pkg = package_dir.resolve()
    deny_rules: list[str] = []
    for rel in _WRAPPER_RENDERED_PATHS:
        target = f"{rel_pkg.as_posix()}/{rel}"
        deny_rules.append(f"Write({target})")
        deny_rules.append(f"Edit({target})")
    settings = {
        "permissions": {
            "deny": deny_rules,
        },
    }
    path = intermediate_dir / "_compile_settings.json"
    path.write_text(json.dumps(settings, indent=2))
    return path


def write_runtime_directive(
    intermediate_dir: Path, backend: str, model_id: str, source: str
) -> Path:
    """Save the chosen backend and model_id alongside the package.

    The post-compile lint reads this file to confirm the generated config.py
    actually used these values (and didn't drift from what we instructed).
    """
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": "1.0",
        "backend": backend,
        "model_id": model_id,
        "source": source,
    }
    path = intermediate_dir / "runtime_directive.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def build_system_prompt(
    backend: str, model_id: str, source: str, mellea_package_dir: Path
) -> str:
    """Assemble the instruction string passed to the mellea-fy slash command.

    Combines the existing autonomous-run directive with the resolved backend
    and model_id values, plus a notice listing the paths the wrapper renders
    authoritatively from JSON (the LLM cannot Write/Edit them — denied via
    --settings). This tells the LLM to emit the IR JSON instead of trying to
    write the rendered source itself, so the first attempt is correct rather
    than denied-then-retried.

    ``mellea_package_dir`` is the wrapper-derived Rule OUT-2 path (e.g.
    ``weather_mellea``) substituted into the prompt body so the LLM uses the
    same path the wrapper computes for ``mirror_dir_contents_to_target`` and the
    post-session ``*_mellea`` discovery.
    """
    wrapper_rendered_lines = "\n".join(
        f"  - {mellea_package_dir}/{p}" for p in _WRAPPER_RENDERED_PATHS
    )
    return (
        "Run the complete 10-step pipeline (Steps 0 through 7) autonomously from start to finish. "
        "Do NOT pause between steps, do NOT ask for user confirmation to proceed, and do NOT stop "
        "after any individual step completes. Invoke each sub-command in sequence and continue "
        "immediately to the next step.\n\n"
        f"The compiled package directory path is exactly `{mellea_package_dir}`. "
        f"Use this exact path wherever the slash-command directives reference "
        f"`<mellea_package_dir>`; do NOT re-derive it from the frontmatter. The wrapper "
        f"has already applied Rule OUT-2 and the post-session discovery expects "
        f"this exact directory path.\n\n"
        f"The following paths are rendered by the compile pipeline from the JSON you emit "
        f"in {mellea_package_dir}/intermediate/ — DO NOT write or edit them yourself; the Write "
        f"and Edit tools are denied for these paths and the wrapper will render them "
        f"deterministically after you exit:\n"
        f"{wrapper_rendered_lines}\n"
        f"Emit the corresponding *_emission.json files under {mellea_package_dir}/intermediate/ "
        f"conforming to .claude/schemas/*_emission.schema.json instead.\n\n"
        f"Runtime defaults (source: {source}). The values below MUST appear in "
        f"config_emission.json so the wrapper renders them into {mellea_package_dir}/config.py:\n"
        f"  BACKEND = {backend!r}\n"
        f"  MODEL_ID = {model_id!r}\n"
        f"Do not invent alternative values, and do not omit either constant. "
        f"The post-compile lint will verify config.py against the recorded values "
        f"at {mellea_package_dir}/intermediate/runtime_directive.json."
    )
