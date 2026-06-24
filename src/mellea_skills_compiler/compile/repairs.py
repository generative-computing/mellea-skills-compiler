"""Deterministic post-generation repairs applied to a compiled package before lints.

These fix structural mismatches the LLM writer can introduce, so the emitted
package honours its own typed contracts without depending on the model getting
every detail right.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from mellea_skills_compiler.compile.lints import (
    _find_pydantic_classes_in_schemas,
    _resolve_pydantic_annotation,
)
from mellea_skills_compiler.toolkit.logging import configure_logger

LOGGER = configure_logger(__name__)

_MARKER = "# [pydantic-coercion]"


def params_coerced_at_entry(pipeline_py: Path) -> set:
    """Return run_pipeline params already guarded by ``if isinstance(p, dict): ...``.

    Shared by the repair (to avoid double-injecting) and the
    ``fixture-pydantic-coercion`` lint (to credit entry coercion as a valid fix).
    """
    try:
        tree = ast.parse(pipeline_py.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    func = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "run_pipeline"),
        None,
    )
    if func is None:
        return set()
    coerced = set()
    for stmt in func.body:
        if not isinstance(stmt, ast.If) or not isinstance(stmt.test, ast.Call):
            continue
        test = stmt.test
        if (
            isinstance(test.func, ast.Name)
            and test.func.id == "isinstance"
            and len(test.args) == 2
            and isinstance(test.args[0], ast.Name)
            and isinstance(test.args[1], ast.Name)
            and test.args[1].id == "dict"
        ):
            coerced.add(test.args[0].id)
    return coerced


def coerce_pydantic_params_at_entry(package_dir: Path) -> List[str]:
    """Make ``run_pipeline`` tolerant of bare-dict inputs for Pydantic-typed params.

    Fixtures emit plain dict literals for structured inputs, but ``run_pipeline``
    frequently types those parameters as Pydantic models and then accesses
    attributes on them — which raises ``AttributeError: 'dict' object has no
    attribute ...`` at smoke-check time (lint ``fixture-pydantic-coercion``).

    This injects ``if isinstance(p, dict): p = Cls(**p)`` at the top of
    ``run_pipeline`` for each parameter whose annotation resolves to a Pydantic
    model defined in ``schemas.py``. The model classes are already imported in
    ``pipeline.py`` (they are used as annotations), so no new imports are needed.

    Idempotent (guarded by a marker comment); preserves the rest of the file.
    Returns the list of parameter names that were coerced.
    """
    pipeline_py = package_dir / "pipeline.py"
    schemas_py = package_dir / "schemas.py"
    if not pipeline_py.is_file():
        return []

    pydantic = _find_pydantic_classes_in_schemas(schemas_py)
    if not pydantic:
        return []

    src = pipeline_py.read_text(encoding="utf-8")
    if _MARKER in src:  # already applied
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    func = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "run_pipeline"),
        None,
    )
    if func is None or not func.body:
        return []

    already = params_coerced_at_entry(pipeline_py)
    inject = []
    for arg in func.args.args:
        if arg.annotation is None or arg.arg in already:
            continue
        cls = _resolve_pydantic_annotation(arg.annotation, pydantic)
        if cls:
            inject.append((arg.arg, cls))
    if not inject:
        return []

    # Insert immediately before the first real (non-docstring) body statement so
    # the indentation matches and a leading docstring is preserved.
    body = func.body
    first = body[0]
    is_docstring = (
        isinstance(first, ast.Expr)
        and isinstance(getattr(first, "value", None), ast.Constant)
        and isinstance(first.value.value, str)
    )
    anchor = body[1] if (is_docstring and len(body) > 1) else first
    insert_idx = anchor.lineno - 1  # 0-based line index to insert before
    indent = " " * anchor.col_offset

    snippet = [f"{indent}{_MARKER} tolerate dict fixture inputs for typed params\n"]
    for pname, cls in inject:
        snippet.append(f"{indent}if isinstance({pname}, dict):\n")
        snippet.append(f"{indent}    {pname} = {cls}(**{pname})\n")

    lines = src.splitlines(keepends=True)
    new_lines = lines[:insert_idx] + snippet + lines[insert_idx:]
    new_src = "".join(new_lines)

    # Safety: only write if the result still parses.
    try:
        ast.parse(new_src)
    except SyntaxError:
        LOGGER.warning("pydantic-coercion repair produced unparseable pipeline.py; skipping")
        return []

    pipeline_py.write_text(new_src, encoding="utf-8")
    coerced = [p for p, _ in inject]
    LOGGER.info("Applied pydantic-coercion repair to run_pipeline params: %s", ", ".join(coerced))
    return coerced


_HELPER_NAME = "_ground_literal"
_HELPER_SRC = (
    f'\n\ndef {_HELPER_NAME}(_v):\n'
    '    """Wrap grounding data so Mellea\'s Jinja rendering treats it literally.\n\n'
    "    Mellea renders grounding_context VALUES as Jinja templates\n"
    "    (Instruction.apply_user_dict_from_jinja). When a value is data that happens\n"
    "    to contain ``{{ }}`` / ``{% %}`` (fetched API docs, code under review, etc.)\n"
    "    Jinja mis-parses it and raises UndefinedError / TemplateSyntaxError. Wrapping\n"
    "    in a raw block makes Jinja emit the content verbatim.\n"
    '    """\n'
    '    return "{% raw %}" + str(_v) + "{% endraw %}"\n'
)


def escape_grounding_context_values(package_dir: Path) -> List[str]:
    """Wrap every ``grounding_context={...}`` value so incidental Jinja syntax in the
    data is not executed as a template. Idempotent; preserves the rest of the file.
    Returns the list of source segments wrapped.
    """
    pipeline_py = package_dir / "pipeline.py"
    if not pipeline_py.is_file():
        return []
    src = pipeline_py.read_text(encoding="utf-8")
    if _HELPER_NAME in src:  # already applied
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    lines = src.splitlines(keepends=True)
    line_start = [0]
    for ln in lines:
        line_start.append(line_start[-1] + len(ln))

    def offset(lineno: int, col: int) -> int:
        return line_start[lineno - 1] + col

    # Collect (start, end) char spans of every value in a grounding_context dict.
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "grounding_context" and isinstance(kw.value, ast.Dict):
                for k, v in zip(kw.value.keys, kw.value.values):
                    # Skip ``**unpacking`` entries: ast.Dict represents `{**X}` with a
                    # None key and X as the value. Wrapping X would turn `{**X}` into
                    # `{**_ground_literal(X)}` (i.e. `**<str>`) → "'str' object is not a
                    # mapping". Only wrap explicitly-keyed string values.
                    if k is None or v.end_lineno is None:
                        continue
                    spans.append((offset(v.lineno, v.col_offset),
                                  offset(v.end_lineno, v.end_col_offset)))
    if not spans:
        return []

    wrapped = []
    new = src
    for s, e in sorted(spans, reverse=True):  # splice from end to keep offsets valid
        seg = new[s:e]
        wrapped.append(seg)
        new = f"{new[:s]}{_HELPER_NAME}({seg}){new[e:]}"

    # Inject the helper after the last top-level import.
    insert_line = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and getattr(node, "col_offset", 1) == 0:
            insert_line = max(insert_line, node.end_lineno or node.lineno)
    helper_at = line_start[insert_line]  # char offset just after that import line
    new = new[:helper_at] + _HELPER_SRC + new[helper_at:]

    try:
        ast.parse(new)
    except SyntaxError:
        LOGGER.warning("grounding-escape repair produced unparseable pipeline.py; skipping")
        return []

    pipeline_py.write_text(new, encoding="utf-8")
    LOGGER.info("Applied grounding-escape repair to %d grounding_context value(s)", len(wrapped))
    return wrapped
