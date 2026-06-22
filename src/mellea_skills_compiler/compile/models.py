from dataclasses import dataclass
from types import ModuleType
from typing import Optional


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
    writer: ModuleType  # the corresponding writer module from mellea_skills_compiler/compile/writer/
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
