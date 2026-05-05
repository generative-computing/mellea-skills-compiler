"""Wrapper-side invocation of the deterministic writers in `.claude/melleafy/writers/`.

The writers (`config_writer.py`, `fixtures_writer.py`, ...) were originally
documented as "the LLM follows them" — but the slash command runs with
`--allowed-tools Read,Write,Edit` and cannot execute Python. So in practice
the LLM was mentally rendering the writer's output, which is unreliable for
anything more complex than `config.py`.

This module moves writer invocation into the compile pipeline, where Python
actually runs. Two operating modes:

  - WARN (observation only): render via the writer, diff against the file the
    LLM wrote, log a warning if they differ, do NOT overwrite.
  - ENFORCE: render via the writer, write authoritatively, deletes whatever
    the LLM put there. Combine with `Write(...)` deny rules in --settings to
    prevent the LLM writing the path in the first place.

Migration plan:
  1. WARN mode for `config_writer` (this commit) — gather evidence the diffs
     are stable and bounded across compiles.
  2. After ~5 clean compiles, flip `config_writer` to ENFORCE + add deny rule.
  3. Repeat for `fixtures_writer`.

Each writer module exposes a `render(emission: dict) -> str` function returning
Python source text. The wrapper reads the emission JSON the LLM emitted, calls
render(), and either compares-and-warns or writes-authoritatively.
"""

from __future__ import annotations

import difflib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from mellea_skills_compiler.compile import CLAUDE_DIR
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()


@dataclass(frozen=True)
class WriterSpec:
    """One renderable artifact: emission JSON in → Python source on disk out.

    `output_kind` controls how the writer is invoked:
      - "file" (default): writer module exposes `render(emission) -> str` and
        the renderer writes the returned text to `output_relpath`.
      - "directory": writer module exposes `write(emission, dir_path) -> list[Path]`
        and the renderer wipes `output_relpath` (preserving the dir itself)
        before invoking, so the writer is the sole producer of the dir's contents.
    """

    name: str  # human-readable label, e.g. "config.py"
    emission_relpath: str  # e.g. "intermediate/config_emission.json"
    output_relpath: str  # e.g. "config.py" or "fixtures"
    writer_path: Path  # absolute path to the .claude/melleafy/writers/*.py module
    output_kind: str = "file"  # "file" | "directory"


@dataclass
class RenderResult:
    name: str
    status: (
        str  # "match" | "diff" | "missing-emission" | "missing-output" | "writer-error"
    )
    detail: Optional[str] = None
    diff_lines_added: int = 0
    diff_lines_removed: int = 0


def _load_writer_module(writer_path: Path):
    """Import a writer module from a path and return the module object."""
    spec = importlib.util.spec_from_file_location(writer_path.stem, writer_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load writer from {writer_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_writer(writer_path: Path) -> Callable[[dict], str]:
    """Return the file-mode writer's `render(emission) -> str` function."""
    module = _load_writer_module(writer_path)
    if not hasattr(module, "render"):
        raise AttributeError(f"writer {writer_path} has no render() function")
    return module.render


def _load_writer_dir(writer_path: Path) -> Callable[[dict, Path], list]:
    """Return the directory-mode writer's `write(emission, out_dir)` function."""
    module = _load_writer_module(writer_path)
    if not hasattr(module, "write"):
        raise AttributeError(
            f"writer {writer_path} has no write(emission, out_dir) function "
            f"required for directory-mode WriterSpec"
        )
    return module.write


def _render_one(package_dir: Path, spec: WriterSpec, *, enforce: bool) -> RenderResult:
    """Render one writer artifact and either warn-on-diff or write-authoritatively."""
    emission_path = package_dir / spec.emission_relpath
    output_path = package_dir / spec.output_relpath

    if not emission_path.exists():
        return RenderResult(
            name=spec.name,
            status="missing-emission",
            detail=(
                f"{spec.emission_relpath} not found — the LLM did not emit the IR. "
                f"In WARN mode this is a soft skip; in ENFORCE mode the package is "
                f"unrenderable and compile should fail."
            ),
        )

    try:
        emission = json.loads(emission_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return RenderResult(
            name=spec.name,
            status="writer-error",
            detail=f"could not read or parse {spec.emission_relpath}: {exc}",
        )

    if spec.output_kind == "directory":
        return _render_directory(spec, emission, output_path, enforce=enforce)
    return _render_file(spec, emission, output_path, enforce=enforce)


def _render_file(
    spec: WriterSpec, emission: dict, output_path: Path, *, enforce: bool
) -> RenderResult:
    """Single-file writer dispatch (config.py shape)."""
    try:
        render_fn = _load_writer(spec.writer_path)
        rendered = render_fn(emission)
    except Exception as exc:  # noqa: BLE001
        return RenderResult(
            name=spec.name,
            status="writer-error",
            detail=f"writer {spec.writer_path.name} raised: {exc}",
        )

    if not output_path.exists():
        if enforce:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered)
            return RenderResult(
                name=spec.name,
                status="match",
                detail=f"rendered {spec.output_relpath} (LLM did not write one)",
            )
        return RenderResult(
            name=spec.name,
            status="missing-output",
            detail=(
                f"{spec.output_relpath} not on disk — LLM appears to have skipped "
                f"this artifact entirely. WARN mode does not render."
            ),
        )

    actual = output_path.read_text()
    if actual == rendered:
        return RenderResult(name=spec.name, status="match")

    diff = list(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=f"on-disk {spec.output_relpath}",
            tofile=f"writer-rendered {spec.output_relpath}",
            n=1,
        )
    )
    added = sum(
        1 for line in diff if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in diff if line.startswith("-") and not line.startswith("---")
    )

    if enforce:
        output_path.write_text(rendered)
        return RenderResult(
            name=spec.name,
            status="match",
            detail=f"overwrote {spec.output_relpath} with writer output (-{removed}/+{added} lines)",
            diff_lines_added=added,
            diff_lines_removed=removed,
        )

    return RenderResult(
        name=spec.name,
        status="diff",
        detail=f"on-disk differs from writer (-{removed}/+{added} lines)",
        diff_lines_added=added,
        diff_lines_removed=removed,
    )


def _render_directory(
    spec: WriterSpec, emission: dict, output_path: Path, *, enforce: bool
) -> RenderResult:
    """Directory-output writer dispatch (fixtures/ shape).

    Strategy:
      - ENFORCE: wipe the LLM's contents under output_path (everything except
        the dir itself), then invoke the writer's `write(emission, output_path)`.
        The writer is the sole producer of dir contents; any pytest-style or
        INPUT-only drift the LLM may have written is gone.
      - WARN: render to a temp dir, count how many files differ from
        on-disk, log a warning. Do not modify on-disk files.
    """
    try:
        write_fn = _load_writer_dir(spec.writer_path)
    except Exception as exc:  # noqa: BLE001
        return RenderResult(
            name=spec.name,
            status="writer-error",
            detail=f"writer {spec.writer_path.name} dir-mode load failed: {exc}",
        )

    if enforce:
        output_path.mkdir(parents=True, exist_ok=True)
        # Wipe everything inside (preserve the dir itself so cwd/imports stay valid).
        wiped = 0
        for child in output_path.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
                wiped += 1
            elif child.is_dir() and child.name != "__pycache__":
                # Only wipe pycache dirs leniently; deeper subdirs would be
                # surprising for fixtures so log them rather than wipe blindly.
                _wipe_dir(child)
                wiped += 1
        try:
            written = write_fn(emission, output_path)
        except Exception as exc:  # noqa: BLE001
            return RenderResult(
                name=spec.name,
                status="writer-error",
                detail=f"writer.write() raised: {exc}",
            )
        return RenderResult(
            name=spec.name,
            status="match",
            detail=(
                f"rendered {len(written)} file(s) into {spec.output_relpath}/ "
                f"(wiped {wiped} pre-existing entries)"
            ),
        )

    # WARN mode: render to a tempdir, compare to on-disk
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        try:
            written = write_fn(emission, tmp)
        except Exception as exc:  # noqa: BLE001
            return RenderResult(
                name=spec.name,
                status="writer-error",
                detail=f"writer.write() raised: {exc}",
            )
        rendered_names = {p.name for p in written}
        actual_names = (
            {p.name for p in output_path.iterdir() if p.is_file()}
            if output_path.is_dir()
            else set()
        )
        only_rendered = sorted(rendered_names - actual_names)
        only_actual = sorted(actual_names - rendered_names - {"__pycache__"})
        if not only_rendered and not only_actual:
            return RenderResult(name=spec.name, status="match")
        return RenderResult(
            name=spec.name,
            status="diff",
            detail=(
                f"on-disk vs writer differ: "
                f"only_rendered={only_rendered or '[]'}, "
                f"only_actual={only_actual or '[]'}"
            ),
            diff_lines_added=len(only_rendered),
            diff_lines_removed=len(only_actual),
        )


def _wipe_dir(path: Path) -> None:
    """Recursively remove a directory and all its contents."""
    import shutil

    shutil.rmtree(path)


def render_writers(
    package_dir: Path, specs: List[WriterSpec], *, enforce: bool = False
) -> List[RenderResult]:
    """Render every writer in `specs` against the package and log outcomes.

    With `enforce=False` (default for migration phase), only logs WARN on diff
    and never overwrites. With `enforce=True`, the writer's output becomes the
    authoritative source for the artifact.
    """
    results: List[RenderResult] = []
    for spec in specs:
        try:
            result = _render_one(package_dir, spec, enforce=enforce)
        except Exception as exc:  # noqa: BLE001
            result = RenderResult(
                name=spec.name,
                status="writer-error",
                detail=f"unexpected error: {exc}",
            )
        results.append(result)
        _log_result(result, enforce=enforce)
    return results


def _log_result(result: RenderResult, *, enforce: bool) -> None:
    if result.status == "match":
        if result.detail:
            LOGGER.info("[writer:%s] %s", result.name, result.detail)
        else:
            LOGGER.info("[writer:%s] matches on-disk file", result.name)
    elif result.status == "diff":
        # In WARN mode this is the signal we are watching for during migration.
        LOGGER.warning(
            "[writer:%s] %s. The on-disk file was written by the LLM and differs "
            "from what the deterministic writer would produce. Once these diffs "
            "are bounded across a few compiles, the writer can be flipped to ENFORCE.",
            result.name,
            result.detail,
        )
    elif result.status == "missing-emission":
        # Soft in WARN mode; would be hard halt in ENFORCE mode.
        level = LOGGER.error if enforce else LOGGER.warning
        level("[writer:%s] %s", result.name, result.detail)
    elif result.status == "missing-output":
        LOGGER.warning("[writer:%s] %s", result.name, result.detail)
    elif result.status == "writer-error":
        LOGGER.warning("[writer:%s] %s", result.name, result.detail)


def default_writer_specs(repo_root) -> List[WriterSpec]:
    """Wrapper-rendered artifacts. Order matters only for log readability.

    Add new specs as each migration step lands. Each spec must satisfy:
      - file-mode writer (`output_kind="file"`): module exposes `render(emission) -> str`
      - dir-mode writer  (`output_kind="directory"`): module exposes
        `write(emission, out_dir) -> list[Path]`
    """
    writers_dir = repo_root / ".claude" / "melleafy" / "writers"
    return [
        WriterSpec(
            name="config.py",
            emission_relpath="intermediate/config_emission.json",
            output_relpath="config.py",
            writer_path=writers_dir / "config_writer.py",
        ),
        WriterSpec(
            name="fixtures/",
            emission_relpath="intermediate/fixtures_emission.json",
            output_relpath="fixtures",
            writer_path=writers_dir / "fixtures_writer.py",
            output_kind="directory",
        ),
    ]
