"""Deterministic writer: config_emission JSON → config.py Python source.

Input must conform to .claude/schemas/config_emission.schema.json.
Output is ready to write directly to <package_name>/config.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_HEADER = "from typing import Final"

_CATEGORY_LABELS: dict[str, str] = {
    "C1": "Identity & Behavioral Context",
    "C2": "Operating Rules",
    "C3": "User Facts",
    "C4": "Short-term State",
    "C5": "Long-term Memory",
    "C6": "Tools",
    "C7": "Credentials",
    "C8": "Runtime Environment",
    "C9": "Scheduling/Triggers",
}


def _value_repr(value: Any, py_type: str) -> str:
    """Produce safe Python source for a constant value.

    Multi-line strings are triple-quoted for readability (PREFIX_TEXT etc.).
    Falls back to repr() if the string itself contains triple-quote sequences.
    """
    if py_type == "str" and isinstance(value, str) and "\n" in value:
        if '"""' not in value:
            return f'"""{value}"""'
    return repr(value)


def render(emission: dict[str, Any] | str) -> str:
    """Render a config_emission JSON object as Python source.

    Args:
        emission: dict conforming to config_emission.schema.json, or a JSON string.

    Returns:
        Python source string with constants grouped by C-category and annotated
        with PROVENANCE comments where source location is available.
    """
    if isinstance(emission, str):
        emission = json.loads(emission)

    # Group constants by category, preserving intra-group order.
    groups: dict[str | None, list[dict]] = {}
    for constant in emission["constants"]:
        cat: str | None = constant.get("category") or None
        if cat not in groups:
            groups[cat] = []
        groups[cat].append(constant)

    # Emit C1..C9 in numeric order, ungrouped constants last.
    ordered_cats: list[str | None] = sorted(
        (k for k in groups if k is not None),
        key=lambda c: int(c[1:]),  # type: ignore[index]
    )
    if None in groups:
        ordered_cats.append(None)

    lines = [_HEADER, ""]
    first_section = True

    for cat in ordered_cats:
        if not first_section:
            lines.append("")
        first_section = False

        if cat is not None:
            label = _CATEGORY_LABELS.get(cat, cat)
            lines.append(f"# === {cat}: {label} ===")

        section_constants = groups[cat]
        for i, constant in enumerate(section_constants):
            name: str = constant["name"]
            value: Any = constant["value"]
            py_type: str = constant["type"]
            provenance: dict | None = constant.get("provenance")

            lines.append(f"{name}: Final[{py_type}] = {_value_repr(value, py_type)}")

            if provenance:
                src = provenance["source_file"]
                src_lines = provenance["source_lines"]
                lines.append(f"# PROVENANCE: {src}:{src_lines}")
                # Blank line after a provenance-annotated entry if more follow in this section.
                if i < len(section_constants) - 1:
                    lines.append("")

    return "\n".join(lines) + "\n"


def write(emission: dict[str, Any] | str, path: str | Path) -> None:
    """Write rendered config.py source to path."""
    Path(path).write_text(render(emission), encoding="utf-8")
