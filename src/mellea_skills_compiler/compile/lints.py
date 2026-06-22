"""Step 7 structural lints — Python implementations.

AST-precise structural checks where LLM application has proven unreliable
and the drift modes have caused post-compile breakage in shipped skills.
The remaining lints documented in `.claude/commands/mellea-fy-validate.md`
are still applied by the LLM during Step 7 of the slash command.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional, Set, Tuple


_BUNDLED_DIRS = ("scripts", "references", "assets")


def _col_offset_to_schema(node: Any) -> Optional[int]:
    """Convert an AST node's 0-indexed ``col_offset`` to a 1-indexed column.

    Python's ``ast.AST.col_offset`` is 0-indexed. LSP/IDE conventions and the
    step_7_report schema treat ``column`` as 1-indexed. Returns ``None`` when
    the node lacks the attribute.
    """
    col = getattr(node, "col_offset", None)
    if col is None:
        return None
    return col + 1


@dataclass
class LintFailure:
    file: str
    line: Optional[int]
    column: Optional[int]
    message: str
    rule_ref: Optional[str] = None


@dataclass
class LintResult:
    lint_id: str
    verdict: str  # "pass" | "fail" | "skipped" | "warning"
    files_checked: int = 0
    skipped_reason: Optional[str] = None
    failures: List[LintFailure] = field(default_factory=list)


@dataclass
class LintRunResult:
    overall_verdict: str  # "pass" | "fail"
    lints: List[LintResult]
    package_path: str
    checked_at: str

    @property
    def failed(self) -> bool:
        return self.overall_verdict == "fail"


# ─── Lint: fixtures-loader-contract ───


def lint_fixtures_loader_contract(package_dir: Path) -> LintResult:
    """`<package>/fixtures/__init__.py` must export ALL_FIXTURES or FIXTURES."""
    result = LintResult(lint_id="fixtures-loader-contract", verdict="pass")

    fixtures_init = package_dir / "fixtures" / "__init__.py"
    if not fixtures_init.exists():
        result.verdict = "skipped"
        result.skipped_reason = "fixtures/__init__.py not found"
        return result

    result.files_checked = 1
    try:
        tree = ast.parse(fixtures_init.read_text(), filename=str(fixtures_init))
    except SyntaxError as exc:
        result.verdict = "fail"
        result.failures.append(
            LintFailure(
                file=str(fixtures_init.relative_to(package_dir)),
                line=exc.lineno,
                column=exc.offset,
                message=f"SyntaxError prevents parsing fixtures/__init__.py: {exc.msg}",
                rule_ref="Rule 4-1 (mellea-fy-fixtures.md)",
            )
        )
        return result

    for node in tree.body:
        targets: List[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in ("ALL_FIXTURES", "FIXTURES"):
                return result  # pass

    result.verdict = "fail"
    result.failures.append(
        LintFailure(
            file=str(fixtures_init.relative_to(package_dir)),
            line=None,
            column=None,
            message=(
                "fixtures/__init__.py does not export ALL_FIXTURES (preferred: "
                "list[Callable] of factories returning (inputs, fixture_id, description)) "
                "or FIXTURES (alternative: list[dict] with keys 'id' and 'context'). "
                "See mellea-fy-fixtures.md for the contract; under the fixtures_writer.py "
                "architecture (Step 4) this should be unreachable, so a hand-edit or a "
                "writer bypass is the likely cause."
            ),
            rule_ref="R16, Rule 4-1 (mellea-fy-fixtures.md)",
        )
    )
    return result


# ─── Lint: bundled-asset-path-resolution ───


def _is_path_dunder_file_parent(node: ast.AST) -> bool:
    """True iff node is `Path(__file__).parent`."""
    if not isinstance(node, ast.Attribute) or node.attr != "parent":
        return False
    inner = node.value
    if not isinstance(inner, ast.Call) or not isinstance(inner.func, ast.Name):
        return False
    if inner.func.id != "Path" or len(inner.args) != 1:
        return False
    arg = inner.args[0]
    return isinstance(arg, ast.Name) and arg.id == "__file__"


def _is_file_rooted(node: ast.AST) -> bool:
    """Accept any expression directly rooted at __file__."""
    if isinstance(node, ast.Name) and node.id == "__file__":
        return True
    if _is_path_dunder_file_parent(node):
        return True
    if isinstance(node, ast.Call):
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id == "__file__":
                return True
    return False


def _collect_div_chain(node: ast.AST) -> Tuple[ast.AST, List[ast.AST]]:
    """Unwind a chained BinOp(Div) into (leftmost, [right operands left-to-right])."""
    rights: List[ast.AST] = []
    current = node
    while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
        rights.insert(0, current.right)
        current = current.left
    return current, rights


def _starts_with_bundled_dir(s: str) -> Optional[str]:
    """If string is or starts with a bundled directory name, return that name; else None."""
    for d in _BUNDLED_DIRS:
        if s == d or s.startswith(f"{d}/") or s.startswith(f"{d}\\"):
            return d
    return None


def _node_repr(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return f"<{type(node).__name__}>"


def _is_skipped_path(rel_path: str) -> bool:
    """fixtures/ are tests, intermediate/ is metadata — neither is runtime code."""
    parts = rel_path.replace("\\", "/").split("/")
    return parts[0] in ("fixtures", "intermediate") or "__pycache__" in parts


def _collect_file_root_aliases(tree: ast.AST) -> set[str]:
    """Return Name identifiers in `tree` that are bound to a `__file__`-rooted
    expression by a simple assignment.

    Accepts a Name as a valid `__file__`-rooted alias if it appears anywhere in
    `tree` as the target of an `Assign` or `AnnAssign` whose value satisfies
    `_is_file_rooted` — i.e. `Path(__file__).parent`, the bare `__file__` Name,
    or a `Call` taking `__file__` as an argument.

    Example:
      ```
      pkg_dir = Path(__file__).parent       # pkg_dir → alias
      references_dir = pkg_dir / "references"  # leftmost(pkg_dir) accepted
      ```

    The scan is file-wide (does not respect function scope). In machine-emitted
    code, alias shadowing is rare; we trade exactness for a meaningful False-
    positive reduction on the readable `<var> = Path(__file__).parent`
    convention.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        targets: List[ast.expr] = []
        value: Optional[ast.expr] = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None or not _is_file_rooted(value):
            continue
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                aliases.add(tgt.id)
    return aliases


def _leftmost_is_file_rooted(
    leftmost: ast.AST, aliases: set[str]
) -> bool:
    """True if `leftmost` is a `__file__`-rooted expression OR a Name alias
    bound to one earlier in the file."""
    if _is_path_dunder_file_parent(leftmost):
        return True
    if isinstance(leftmost, ast.Name) and leftmost.id in aliases:
        return True
    return False


def lint_bundled_asset_path_resolution(package_dir: Path) -> LintResult:
    """Reject any path-join construction that resolves a bundled-asset path
    via anything other than `Path(__file__).parent`."""
    result = LintResult(lint_id="bundled-asset-path-resolution", verdict="pass")

    py_files: List[Path] = []
    for p in sorted(package_dir.rglob("*.py")):
        rel = p.relative_to(package_dir).as_posix()
        if not _is_skipped_path(rel):
            py_files.append(p)
    result.files_checked = len(py_files)

    seen_failures: set[Tuple[str, Optional[int], Optional[int]]] = set()

    def _record(file_rel: str, node: ast.AST, msg: str) -> None:
        key = (file_rel, getattr(node, "lineno", None), getattr(node, "col_offset", None))
        if key in seen_failures:
            return
        seen_failures.add(key)
        result.failures.append(
            LintFailure(
                file=file_rel,
                line=key[1],
                column=key[2],
                message=msg,
                rule_ref="Rule OUT-6, Rule 2.5-2",
            )
        )

    for py_file in py_files:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue  # the parseable lint is responsible

        aliases = _collect_file_root_aliases(tree)

        for node in ast.walk(tree):
            # Pattern 1: BinOp(Div) chain — Path(...) / "scripts/..."
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                leftmost, rights = _collect_div_chain(node)
                bundled_hit: Optional[str] = None
                first_str: Optional[ast.Constant] = None
                for r in rights:
                    if isinstance(r, ast.Constant) and isinstance(r.value, str):
                        d = _starts_with_bundled_dir(r.value)
                        if d:
                            bundled_hit = d
                            first_str = r
                            break
                if bundled_hit is None or _leftmost_is_file_rooted(leftmost, aliases):
                    continue
                _record(
                    rel,
                    node,
                    (
                        f"Bundled asset path '{first_str.value}' is resolved via "
                        f"'{_node_repr(leftmost)}'. Bundled assets at "
                        f"<package_name>/{bundled_hit}/ MUST be resolved via "
                        f"`Path(__file__).parent / \"{bundled_hit}/<...>\"` "
                        f"(Rule OUT-6 in mellea-fy.md, Rule 2.5-2 in mellea-fy-deps.md). "
                        f"Common error: `Path(repo_root) / \"{bundled_hit}/...\"` — "
                        f"must be `Path(__file__).parent / \"{bundled_hit}\" / ...`. "
                        f"A local alias is fine: "
                        f"`pkg_dir = Path(__file__).parent` then `pkg_dir / \"{bundled_hit}\"` passes."
                    ),
                )

            # Pattern 2: os.path.join(base, "scripts", ...)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                fn = node.func
                if (
                    isinstance(fn.value, ast.Attribute)
                    and isinstance(fn.value.value, ast.Name)
                    and fn.value.value.id == "os"
                    and fn.value.attr == "path"
                    and fn.attr == "join"
                    and node.args
                ):
                    bundled_hit = None
                    first_str = None
                    for arg in node.args[1:]:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            d = _starts_with_bundled_dir(arg.value)
                            if d:
                                bundled_hit = d
                                first_str = arg
                                break
                    base = node.args[0]
                    base_is_file_rooted = _is_file_rooted(base) or (
                        isinstance(base, ast.Name) and base.id in aliases
                    )
                    if bundled_hit is None or base_is_file_rooted:
                        continue
                    _record(
                        rel,
                        node,
                        (
                            f"Bundled asset path '{first_str.value}' (via os.path.join) "
                            f"is resolved via '{_node_repr(node.args[0])}'. "
                            f"Bundled assets MUST be resolved relative to `__file__`. "
                            f"Prefer `Path(__file__).parent / \"{bundled_hit}\" / ...`."
                        ),
                    )

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Lint: runtime-defaults-bound ───


def lint_runtime_defaults_bound(package_dir: Path) -> LintResult:
    """The compiled config.py must use the backend and model_id we instructed.

    Compares the BACKEND and MODEL_ID constants in <package>/config.py against
    the values recorded at <package>/intermediate/runtime_directive.json (which
    captures what the compile pipeline injected via the system prompt). If the
    LLM ignored the directive and emitted different values, this fails loudly.

    Skipped when the directive file is absent — usually because the package was
    compiled with an older pipeline that did not write the directive.
    """
    result = LintResult(lint_id="runtime-defaults-bound", verdict="pass")

    directive_path = package_dir / "intermediate" / "runtime_directive.json"
    config_path = package_dir / "config.py"

    if not directive_path.exists():
        result.verdict = "skipped"
        result.skipped_reason = (
            "intermediate/runtime_directive.json not found "
            "(probably compiled with an older pipeline version)"
        )
        return result
    if not config_path.exists():
        result.verdict = "skipped"
        result.skipped_reason = "config.py not found"
        return result

    try:
        directive = json.loads(directive_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        result.verdict = "skipped"
        result.skipped_reason = f"could not read runtime_directive.json: {exc}"
        return result

    expected_backend = directive.get("backend")
    expected_model_id = directive.get("model_id")
    if expected_backend is None or expected_model_id is None:
        result.verdict = "skipped"
        result.skipped_reason = (
            "runtime_directive.json missing 'backend' or 'model_id' field"
        )
        return result

    try:
        tree = ast.parse(config_path.read_text(), filename=str(config_path))
    except SyntaxError as exc:
        result.verdict = "fail"
        result.failures.append(
            LintFailure(
                file="config.py",
                line=exc.lineno,
                column=exc.offset,
                message=f"SyntaxError prevents parsing config.py: {exc.msg}",
                rule_ref="C8 runtime defaults",
            )
        )
        return result

    found: dict[str, object] = {}
    found_lines: dict[str, int] = {}
    for node in tree.body:
        target_name: Optional[str] = None
        value_node: Optional[ast.expr] = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target_name = node.targets[0].id
            value_node = node.value
        if target_name in ("BACKEND", "MODEL_ID") and isinstance(
            value_node, ast.Constant
        ):
            found[target_name] = value_node.value
            found_lines[target_name] = getattr(node, "lineno", None)

    result.files_checked = 1

    for name, expected in (("BACKEND", expected_backend), ("MODEL_ID", expected_model_id)):
        if name not in found:
            result.failures.append(
                LintFailure(
                    file="config.py",
                    line=None,
                    column=None,
                    message=(
                        f"config.py does not define a top-level constant {name}. "
                        f"The compile pipeline instructed the LLM to emit "
                        f"{name} = {expected!r}; verify the LLM output."
                    ),
                    rule_ref="C8 runtime defaults",
                )
            )
            continue
        actual = found[name]
        if actual != expected:
            result.failures.append(
                LintFailure(
                    file="config.py",
                    line=found_lines.get(name),
                    column=None,
                    message=(
                        f"config.py:{name} = {actual!r} but the compile pipeline "
                        f"instructed {name} = {expected!r}. To change the default, "
                        f"edit .claude/data/runtime_defaults.json or recompile with "
                        f"--backend / --model-id; do not edit config.py by hand."
                    ),
                    rule_ref="C8 runtime defaults",
                )
            )

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Lint: session-method-arity ───
#
# Required-positional checks for MelleaSession.{instruct,chat,transform,query}.
# Signatures pinned against Mellea 0.6.0 (verified via inspect.signature in
# mellea.stdlib.session.MelleaSession). Revisit on Mellea version bump.

_SESSION_METHOD_REQUIRED_PARAMS: dict = {
    "instruct": ("description",),
    "chat": ("content",),
    "transform": ("obj", "transformation"),
    "query": ("obj", "query"),
}

_SESSION_METHOD_LINT_SKIP_PARTS = frozenset({"__pycache__", "intermediate", "fixtures"})


def lint_session_method_arity(package_dir: Path) -> LintResult:
    """MelleaSession method calls must supply required positional arguments."""
    result = LintResult(lint_id="session-method-arity", verdict="pass")

    py_files: List[Path] = []
    for p in sorted(package_dir.rglob("*.py")):
        if any(part in _SESSION_METHOD_LINT_SKIP_PARTS for part in p.parts):
            continue
        py_files.append(p)
    result.files_checked = len(py_files)

    for py_file in py_files:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            method_name = node.func.attr
            if method_name not in _SESSION_METHOD_REQUIRED_PARAMS:
                continue

            required = _SESSION_METHOD_REQUIRED_PARAMS[method_name]
            n_positional = len(node.args)
            positional_filled = set(required[:n_positional])
            kw_filled = {kw.arg for kw in node.keywords if kw.arg is not None}
            missing = [p for p in required if p not in positional_filled and p not in kw_filled]
            if missing:
                missing_str = ", ".join(f"`{m}`" for m in missing)
                result.failures.append(
                    LintFailure(
                        file=rel,
                        line=getattr(node, "lineno", None),
                        column=getattr(node, "col_offset", None),
                        message=(
                            f"`.{method_name}(...)` missing required "
                            f"argument(s): {missing_str}. Pass them "
                            f"positionally or via keyword name. See "
                            f"MelleaSession.{method_name} in "
                            f"mellea.stdlib.session."
                        ),
                        rule_ref="session-method-arity",
                    )
                )

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Shared helpers: m.instruct / start_session pattern detection ───
#
# Used by instruct-result-parse-before-access, format-annotation, and
# session-boundary. The three lints share the same surface (pipeline.py,
# slots.py, constrained_slots.py) and the same notion of an "m.instruct(...)"
# call assigned to a Name target.


_INSTRUCT_LINT_FILES: Tuple[str, ...] = (
    "pipeline.py",
    "slots.py",
    "constrained_slots.py",
)


def _is_m_instruct_call(node: ast.AST) -> bool:
    """True iff node is a `Call` whose func is `m.instruct` (Attribute on Name 'm')."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "instruct":
        return False
    return isinstance(func.value, ast.Name) and func.value.id == "m"


def _instruct_call_has_format_kwarg(node: ast.Call) -> bool:
    """True iff an `m.instruct(...)` Call has a `format=` keyword."""
    return any(kw.arg == "format" for kw in node.keywords)


def _iter_function_scopes(tree: ast.AST):
    """Yield every FunctionDef/AsyncFunctionDef + the module-level scope."""
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


# ─── Lint: instruct-result-parse-before-access (KB1) ───
#
# `m.instruct(format=Model)` returns a `ComputedModelOutputThunk`, not a
# Pydantic model. Direct attribute access on the thunk (`thunk.some_field`)
# raises AttributeError at runtime. The thunk must be parsed first via
# `_safe_parse_with_fallback`, `_parse_instruct_result`, or
# `Model.model_validate_json(thunk.value)`.


_THUNK_CONSUMER_FUNC_NAMES: frozenset = frozenset({
    "_parse_instruct_result",
    "_safe_parse_with_fallback",
})


def _consumer_thunk_arg_nodes(call: ast.Call, raw_thunks: Set[str]) -> Set[int]:
    """Return id(arg_node) set for thunk-Name args sitting in the first
    positional slot of a documented parser call."""
    fname = (
        call.func.id if isinstance(call.func, ast.Name)
        else call.func.attr if isinstance(call.func, ast.Attribute)
        else None
    )
    if fname not in _THUNK_CONSUMER_FUNC_NAMES:
        return set()
    if not call.args:
        return set()
    first = call.args[0]
    if isinstance(first, ast.Name) and first.id in raw_thunks:
        return {id(first)}
    return set()


def _is_model_validate_json_on_thunk_value(
    call: ast.Call, raw_thunks: Set[str]
) -> Optional[str]:
    """If call is `Model.model_validate_json(thunk.value)` for a known thunk,
    return the thunk's name; otherwise None."""
    func = call.func
    if not (
        isinstance(func, ast.Attribute) and func.attr == "model_validate_json"
    ):
        return None
    if len(call.args) != 1:
        return None
    arg = call.args[0]
    if not (isinstance(arg, ast.Attribute) and arg.attr == "value"):
        return None
    inner = arg.value
    if isinstance(inner, ast.Name) and inner.id in raw_thunks:
        return inner.id
    return None


def _stmt_assigns_from_consumer(
    stmt: ast.stmt, raw_thunks: Set[str]
) -> Optional[Tuple[str, ast.Call]]:
    """If stmt is `var = consumer(thunk, ...)`, return (var_name, call)."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Name):
        return None
    call = stmt.value
    if not isinstance(call, ast.Call):
        return None
    fname = (
        call.func.id if isinstance(call.func, ast.Name)
        else call.func.attr if isinstance(call.func, ast.Attribute)
        else None
    )
    if fname not in _THUNK_CONSUMER_FUNC_NAMES:
        return None
    if not call.args:
        return None
    first = call.args[0]
    if not (isinstance(first, ast.Name) and first.id in raw_thunks):
        return None
    return target.id, call


def _scan_scope_for_kb1(
    scope: ast.AST, rel: str, failures: List[LintFailure]
) -> None:
    """Walk one function body statement-by-statement, tracking raw thunks."""
    raw_thunks: Set[str] = set()
    body = getattr(scope, "body", [])

    def _process_block(stmts):
        nonlocal raw_thunks
        for stmt in stmts:
            new_thunk_name: Optional[str] = None
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Call)
                and _is_m_instruct_call(stmt.value)
                and _instruct_call_has_format_kwarg(stmt.value)
            ):
                new_thunk_name = stmt.targets[0].id

            consumed = _stmt_assigns_from_consumer(stmt, raw_thunks)

            exempt_node_ids: Set[int] = set()
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Call):
                    exempt_node_ids |= _consumer_thunk_arg_nodes(sub, raw_thunks)
                    thunk_in_mvj = _is_model_validate_json_on_thunk_value(
                        sub, raw_thunks
                    )
                    if thunk_in_mvj is not None:
                        arg = sub.args[0]
                        exempt_node_ids.add(id(arg))
                        exempt_node_ids.add(id(arg.value))

            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Attribute):
                    base = sub.value
                    if not (
                        isinstance(base, ast.Name) and base.id in raw_thunks
                    ):
                        continue
                    if id(sub) in exempt_node_ids:
                        continue
                    failures.append(
                        LintFailure(
                            file=rel,
                            line=getattr(sub, "lineno", None),
                            column=getattr(sub, "col_offset", None),
                            message=(
                                f"`{base.id}` is the result of "
                                f"`m.instruct(..., format=Model)` and is a "
                                f"`ComputedModelOutputThunk`, NOT a Pydantic "
                                f"model. Direct attribute access "
                                f"`{base.id}.{sub.attr}` raises AttributeError"
                                f" at runtime (KB1). Parse the thunk first: "
                                f"`parsed = _safe_parse_with_fallback("
                                f"{base.id}, <Model>, **defaults)` (preferred)"
                                f", `parsed = _parse_instruct_result("
                                f"{base.id}, <Model>)`, or `<Model>."
                                f"model_validate_json({base.id}.value)`."
                            ),
                            rule_ref="KB1 (instruct returns thunk)",
                        )
                    )

            if consumed is not None:
                consumed_var, _ = consumed
                call = stmt.value
                first_arg = call.args[0]
                if isinstance(first_arg, ast.Name):
                    raw_thunks.discard(first_arg.id)
                raw_thunks.discard(consumed_var)
            elif new_thunk_name is not None:
                raw_thunks.add(new_thunk_name)
            else:
                if isinstance(stmt, ast.Assign):
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Name):
                            raw_thunks.discard(tgt.id)

            for attr in ("body", "orelse", "finalbody"):
                inner = getattr(stmt, attr, None)
                if isinstance(inner, list):
                    _process_block(inner)
            if isinstance(stmt, ast.Try):
                for handler in stmt.handlers:
                    _process_block(handler.body)

    _process_block(body)


def lint_instruct_result_parse_before_access(package_dir: Path) -> LintResult:
    """KB1: `m.instruct(format=Model)` returns a thunk, not a Pydantic model.

    The thunk MUST be parsed before any field access. Exempt patterns:
      - `_parse_instruct_result(thunk, M)`
      - `_safe_parse_with_fallback(thunk, M, **defaults)`
      - `M.model_validate_json(thunk.value)`
    """
    result = LintResult(
        lint_id="instruct-result-parse-before-access", verdict="pass"
    )

    files_to_check: List[Path] = []
    for fname in _INSTRUCT_LINT_FILES:
        p = package_dir / fname
        if p.exists():
            files_to_check.append(p)
    result.files_checked = len(files_to_check)

    for py_file in files_to_check:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        for scope in _iter_function_scopes(tree):
            _scan_scope_for_kb1(scope, rel, result.failures)

    seen: Set[Tuple[str, Optional[int], Optional[int], str]] = set()
    deduped: List[LintFailure] = []
    for f in result.failures:
        key = (f.file, f.line, f.column, f.message[:80])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    result.failures = deduped

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Lint: format-annotation ───
#
# Every `m.instruct(...)` call whose result is later parsed (via
# `Model.model_validate_json(thunk.value)`, `_parse_instruct_result(thunk, Model)`,
# or `_safe_parse_with_fallback(thunk, Model, ...)`) MUST carry a `format=`
# keyword. Without it, the LLM returns free-form JSON-shaped text instead of
# constrained-decoding output, and the Pydantic parse fails (or worse, silently
# succeeds on a poorly-shaped JSON object).


def lint_format_annotation(package_dir: Path) -> LintResult:
    """`m.instruct(...)` calls whose result is parsed must include `format=`.

    Detection:
      1. AST-parse pipeline.py / slots.py / constrained_slots.py.
      2. For every `Call` that is `m.instruct(...)` assigned to a Name target
         (`thunk = m.instruct(...)`), record whether it has `format=` and
         which variable holds the result.
      3. Walk for subsequent uses of that variable as:
           - argument to `<Model>.model_validate_json(<thunk>.value)`
           - first positional arg to `_parse_instruct_result(<thunk>, ...)`
           - first positional arg to `_safe_parse_with_fallback(<thunk>, ...)`
      4. If any such parse-use is found AND the original instruct call had
         no `format=` kwarg → hard failure on the m.instruct call line.
    """
    result = LintResult(lint_id="format-annotation", verdict="pass")

    files_to_check: List[Path] = []
    for fname in _INSTRUCT_LINT_FILES:
        p = package_dir / fname
        if p.exists():
            files_to_check.append(p)
    result.files_checked = len(files_to_check)

    for py_file in files_to_check:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue

        instruct_assignments: dict = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if not (
                isinstance(node.value, ast.Call) and _is_m_instruct_call(node.value)
            ):
                continue
            instruct_assignments[target.id] = (
                _instruct_call_has_format_kwarg(node.value),
                node.value,
            )

        if not instruct_assignments:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func

            # Pattern 1: <Model>.model_validate_json(thunk.value)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "model_validate_json"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Attribute)
                and node.args[0].attr == "value"
                and isinstance(node.args[0].value, ast.Name)
            ):
                thunk_name = node.args[0].value.id
                info = instruct_assignments.get(thunk_name)
                if info and not info[0]:
                    instruct_call = info[1]
                    result.failures.append(
                        LintFailure(
                            file=rel,
                            line=getattr(instruct_call, "lineno", None),
                            column=getattr(instruct_call, "col_offset", None),
                            message=(
                                f"m.instruct() result `{thunk_name}` is "
                                f"parsed via `<Model>.model_validate_json"
                                f"({thunk_name}.value)` but the m.instruct "
                                f"call has no `format=` keyword. Without "
                                f"`format=`, the model returns free-form "
                                f"text instead of constrained-decoded JSON; "
                                f"the parse will fail or silently produce "
                                f"a malformed object. Fix: add "
                                f"`format=<Model>` to the m.instruct call."
                            ),
                            rule_ref="format-annotation",
                        )
                    )
                continue

            # Patterns 2/3: _parse_instruct_result(thunk, ...) or
            # _safe_parse_with_fallback(thunk, ...)
            callee = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if callee not in (
                "_parse_instruct_result",
                "_safe_parse_with_fallback",
            ):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if not isinstance(first, ast.Name):
                continue
            info = instruct_assignments.get(first.id)
            if info and not info[0]:
                instruct_call = info[1]
                result.failures.append(
                    LintFailure(
                        file=rel,
                        line=getattr(instruct_call, "lineno", None),
                        column=getattr(instruct_call, "col_offset", None),
                        message=(
                            f"m.instruct() result `{first.id}` is parsed "
                            f"via `{callee}({first.id}, ...)` but the "
                            f"m.instruct call has no `format=` keyword. "
                            f"Without `format=`, the model returns free-"
                            f"form text and the helper's "
                            f"`model_validate_json` call inside will fail. "
                            f"Fix: add `format=<Model>` to the m.instruct "
                            f"call."
                        ),
                        rule_ref="format-annotation",
                    )
                )

    seen: Set[Tuple[str, Optional[int]]] = set()
    deduped: List[LintFailure] = []
    for f in result.failures:
        key = (f.file, f.line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    result.failures = deduped

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Lint: session-boundary (KB5) ───
#
# Mellea schema priming: once a session has generated N objects matching schema
# A, the next `m.instruct(format=B)` call in the same session keeps producing
# A-shaped output. The fix is to split the session — open a new
# `start_session()` block per distinct format type.


def _is_start_session_call(node: ast.AST) -> bool:
    """True iff node is a Call whose callee is the name `start_session`."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "start_session"
    if isinstance(func, ast.Attribute):
        return func.attr == "start_session"
    return False


def _instruct_format_type_name(node: ast.Call) -> Optional[str]:
    """If `node` is `<...>.instruct(format=X)`, return X's type name (or None)."""
    if not (
        isinstance(node.func, ast.Attribute) and node.func.attr == "instruct"
    ):
        return None
    for kw in node.keywords:
        if kw.arg != "format":
            continue
        if isinstance(kw.value, ast.Name):
            return kw.value.id
        if isinstance(kw.value, ast.Attribute):
            return kw.value.attr
    return None


def lint_session_boundary(package_dir: Path) -> LintResult:
    """Each `start_session(...)` block must use at most one distinct format type."""
    result = LintResult(lint_id="session-boundary", verdict="pass")

    files_to_check: List[Path] = []
    for fname in _INSTRUCT_LINT_FILES:
        p = package_dir / fname
        if p.exists():
            files_to_check.append(p)
    result.files_checked = len(files_to_check)

    for py_file in files_to_check:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            is_session = any(
                _is_start_session_call(item.context_expr) for item in node.items
            )
            if not is_session:
                continue

            format_types: Set[str] = set()
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                name = _instruct_format_type_name(child)
                if name is not None:
                    format_types.add(name)

            if len(format_types) <= 1:
                continue

            result.failures.append(
                LintFailure(
                    file=rel,
                    line=getattr(node, "lineno", None),
                    column=getattr(node, "col_offset", None),
                    message=(
                        f"start_session() block uses {len(format_types)} "
                        f"distinct format types: "
                        f"{', '.join(sorted(format_types))}. Mellea's schema "
                        f"priming means the LLM cannot reliably switch "
                        f"BaseModel schemas mid-session — after N successful "
                        f"generations of schema A, calls with format=B keep "
                        f"producing A-shaped output. Fix: split into "
                        f"separate `with start_session(...) as m:` blocks, "
                        f"one per distinct format type."
                    ),
                    rule_ref="KB5 (session schema priming)",
                )
            )

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Lint: validation-fn-not-called-directly ───
#
# Mellea's ``Requirement.validation_fn`` is internal sampling-loop plumbing.
# User-emitted code should never call ``<req>.validation_fn(...)`` directly:
# doing so triggers ``AttributeError: 'dict' object has no attribute
# 'last_output'`` at the ``simple_validate(...)`` wrapper. Use
# ``req.validate(backend, ctx, ...)`` for output validation, or plain Python
# ``if/raise ValueError(...)`` for input preconditions.

_VALIDATION_FN_LINT_SKIP_PARTS = frozenset(
    {"__pycache__", "intermediate", "fixtures"}
)


def lint_validation_fn_not_called_directly(package_dir: Path) -> LintResult:
    """Reject any direct call to ``<req>.validation_fn(...)`` in generated code."""
    result = LintResult(lint_id="validation-fn-not-called-directly", verdict="pass")

    py_files: List[Path] = []
    for p in sorted(package_dir.rglob("*.py")):
        if any(part in _VALIDATION_FN_LINT_SKIP_PARTS for part in p.parts):
            continue
        py_files.append(p)
    result.files_checked = len(py_files)

    for py_file in py_files:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "validation_fn":
                continue
            try:
                rendered = ast.unparse(node)
            except Exception:  # pragma: no cover — defensive
                rendered = "<call>"
            result.failures.append(
                LintFailure(
                    file=rel,
                    line=getattr(node, "lineno", None),
                    column=getattr(node, "col_offset", None),
                    message=(
                        f"`{rendered}` — direct call to `.validation_fn` is "
                        f"not the public Mellea API. `Requirement.validation_fn` "
                        f"is internal sampling-loop plumbing; invoking it "
                        f"directly typically raises AttributeError at runtime "
                        f"(the `simple_validate(...)` wrapper calls "
                        f"`ctx.last_output()` on its argument). For "
                        f"output validation use `req.validate(backend, ctx, ...)` "
                        f"or attach the Requirement to a sampling strategy. "
                        f"For input-argument preconditions use plain Python "
                        f"`if/raise ValueError(...)` — Requirement is for "
                        f"model-output validation, not input precondition checks."
                    ),
                    rule_ref="validation-fn-not-called-directly",
                )
            )

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Lint: fixture-pydantic-coercion ───
#
# Cross-file check: fixture inputs must not pass bare dict literals where
# ``run_pipeline``'s signature declares a Pydantic-typed parameter. The
# fixture-shape mismatch raises ``AttributeError: 'dict' object has no
# attribute '<field>'`` at smoke-check time.
#
# Detection-only. The durable structural fix lives in the fixtures writer
# (have it emit ``Model(**{...})`` instead of raw ``{...}``); that's
# tracked separately.


def _find_pydantic_classes_in_schemas(schemas_py: Path) -> set:
    """Return names of classes in schemas.py that transitively subclass BaseModel."""
    if not schemas_py.is_file():
        return set()
    try:
        tree = ast.parse(schemas_py.read_text())
    except SyntaxError:
        return set()

    pydantic: set = set()

    def _base_is_pydantic(base: ast.expr) -> bool:
        if isinstance(base, ast.Name):
            return base.id == "BaseModel" or base.id in pydantic
        if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
            return True
        return False

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name in pydantic:
                continue
            if any(_base_is_pydantic(b) for b in node.bases):
                pydantic.add(node.name)
                changed = True
    return pydantic


def _resolve_pydantic_annotation(node: ast.expr, pydantic_classes: set) -> Optional[str]:
    """Return the Pydantic class name if ``node`` annotates a Pydantic-typed param.

    Handles: ``Foo``, ``Optional[Foo]``, ``Foo | None``.
    """
    if isinstance(node, ast.Name):
        return node.id if node.id in pydantic_classes else None
    if isinstance(node, ast.Subscript):
        outer = node.value
        if isinstance(outer, ast.Name) and outer.id == "Optional":
            return _resolve_pydantic_annotation(node.slice, pydantic_classes)
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _resolve_pydantic_annotation(node.left, pydantic_classes)
        right = _resolve_pydantic_annotation(node.right, pydantic_classes)
        return left or right
    return None


def _pydantic_typed_run_pipeline_params(
    pipeline_py: Path, pydantic_classes: set
) -> dict:
    """Return ``{param_name: pydantic_class}`` for run_pipeline params typed as Pydantic."""
    if not pipeline_py.is_file():
        return {}
    try:
        tree = ast.parse(pipeline_py.read_text())
    except SyntaxError:
        return {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "run_pipeline":
            continue
        params: dict = {}
        for arg in node.args.args:
            if arg.annotation is None:
                continue
            cls = _resolve_pydantic_annotation(arg.annotation, pydantic_classes)
            if cls is not None:
                params[arg.arg] = cls
        return params
    return {}


def _check_fixture_inputs(
    fixture_py: Path, pydantic_params: dict
) -> List[Tuple[str, Optional[int], Optional[int], str]]:
    """Walk a fixture .py file; return (param_name, line, col, model_class) violations."""
    if not fixture_py.is_file():
        return []
    try:
        tree = ast.parse(fixture_py.read_text())
    except SyntaxError:
        return []

    violations: List[Tuple[str, Optional[int], Optional[int], str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "inputs"
            and isinstance(node.value, ast.Dict)
        ):
            continue
        for k_node, v_node in zip(node.value.keys, node.value.values):
            if not (isinstance(k_node, ast.Constant) and isinstance(k_node.value, str)):
                continue
            param_name = k_node.value
            if param_name not in pydantic_params:
                continue
            if isinstance(v_node, ast.Dict):
                violations.append(
                    (
                        param_name,
                        getattr(v_node, "lineno", None),
                        getattr(v_node, "col_offset", None),
                        pydantic_params[param_name],
                    )
                )
    return violations


def lint_fixture_pydantic_coercion(package_dir: Path) -> LintResult:
    """Fixture inputs must not pass bare dicts where run_pipeline expects Pydantic models."""
    result = LintResult(lint_id="fixture-pydantic-coercion", verdict="pass")

    pipeline_py = package_dir / "pipeline.py"
    schemas_py = package_dir / "schemas.py"
    fixtures_dir = package_dir / "fixtures"

    if not pipeline_py.is_file():
        result.verdict = "skipped"
        result.skipped_reason = "pipeline.py not found"
        return result
    if not fixtures_dir.is_dir():
        result.verdict = "skipped"
        result.skipped_reason = "fixtures/ directory not found"
        return result

    pydantic_classes = _find_pydantic_classes_in_schemas(schemas_py)
    pydantic_params = _pydantic_typed_run_pipeline_params(pipeline_py, pydantic_classes)

    if not pydantic_params:
        return result

    fixture_files = sorted(
        p for p in fixtures_dir.glob("*.py") if p.name != "__init__.py"
    )
    result.files_checked = len(fixture_files)

    for fixture_py in fixture_files:
        for param_name, line, col, model_class in _check_fixture_inputs(
            fixture_py, pydantic_params
        ):
            result.failures.append(
                LintFailure(
                    file=f"fixtures/{fixture_py.name}",
                    line=line,
                    column=col,
                    message=(
                        f"Fixture passes `{param_name}=<bare dict>` but "
                        f"`run_pipeline.{param_name}` is typed as "
                        f"`{model_class}` (Pydantic). At smoke-check time "
                        f"the first attribute access on `{param_name}` "
                        f"raises `AttributeError: 'dict' object has no "
                        f"attribute ...`. Fix either side: (a) construct "
                        f"the model in the fixture — "
                        f"`'{param_name}': {model_class}(**{{...}})`; "
                        f"(b) coerce at the pipeline entry — "
                        f"`if isinstance({param_name}, dict): "
                        f"{param_name} = {model_class}(**{param_name})`. "
                        f"The durable structural fix is writer-side "
                        f"(see lint header comment)."
                    ),
                    rule_ref="fixture-pydantic-coercion",
                )
            )

    if result.failures:
        result.verdict = "fail"
    return result




# ─── Lint: grounding-context-types ───
#
# Mellea's backend walks `m.instruct(grounding_context=...)` dict values
# and expects each value to be a CBlock, Component, or ModelOutputThunk
# (in practice: a string that gets wrapped). Anything else — a list, a
# dict, a list-of-dicts produced by `[obj.model_dump() for obj in ...]`
# — crashes at runtime with:
#
#     ValueError: parts should only contain CBlocks, Components, or
#     ModelOutputThunks; found `[{...}]` (type: <class 'list'>)
#
# Two severity tiers:
#   - Definite collections (literal `[...]`, `{...}`, `(...)`, comprehensions)
#     → hard `fail` (deterministic runtime crash).
#   - Ambiguous (`Name`, `Attribute`, arbitrary expressions) → `warning`
#     (advisory; the value MAY be a string at runtime, the lint can't tell).


_GROUNDING_CTX_FILES: Tuple[str, ...] = (
    "pipeline.py",
    "slots.py",
    "constrained_slots.py",
)

# AST node types whose VALUE is guaranteed-not-a-string at runtime. These
# crash deterministically.
_DEFINITE_COLLECTION_NODE_TYPES: Tuple[type, ...] = (
    ast.List,
    ast.Dict,
    ast.Set,
    ast.Tuple,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
)


def _is_str_call(node: ast.AST) -> bool:
    """True iff `node` is a `str(...)` Call expression."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "str":
        return True
    return False


def _grounding_value_kind(value: ast.expr) -> str:
    """Classify a single grounding_context dict-value AST node.

    Returns:
      - "ok"          — string literal, f-string, or `str(...)` call
      - "definite"    — guaranteed-collection type that crashes at runtime
      - "ambiguous"   — Name / Attribute / other expression that *might* be
                        a string at runtime but the lint can't tell
    """
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return "ok"
    if isinstance(value, ast.JoinedStr):  # f-string
        return "ok"
    if _is_str_call(value):
        return "ok"
    if isinstance(value, _DEFINITE_COLLECTION_NODE_TYPES):
        return "definite"
    return "ambiguous"


def lint_grounding_context_types(package_dir: Path) -> LintResult:
    """Every `grounding_context=` dict-literal value should be a string.

    Verdict:
      - `fail` if any definite-collection violation
      - `warning` if only ambiguous findings
      - `pass` otherwise
    """
    result = LintResult(lint_id="grounding-context-types", verdict="pass")

    files_to_check: List[Path] = []
    for fname in _GROUNDING_CTX_FILES:
        p = package_dir / fname
        if p.exists():
            files_to_check.append(p)
    result.files_checked = len(files_to_check)

    has_definite = False
    has_ambiguous = False

    for py_file in files_to_check:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "grounding_context":
                    continue
                if not isinstance(kw.value, ast.Dict):
                    continue
                for key_node, value_node in zip(kw.value.keys, kw.value.values):
                    kind = _grounding_value_kind(value_node)
                    if kind == "ok":
                        continue
                    key_label = (
                        repr(key_node.value)
                        if isinstance(key_node, ast.Constant)
                        else "<dynamic-key>"
                    )
                    line = getattr(value_node, "lineno", None) or getattr(
                        node, "lineno", None
                    )
                    column = getattr(value_node, "col_offset", None)
                    if kind == "definite":
                        has_definite = True
                        result.failures.append(
                            LintFailure(
                                file=rel,
                                line=line,
                                column=column,
                                message=(
                                    f"grounding_context key {key_label} has a "
                                    f"collection-literal value (list, dict, "
                                    f"tuple, set, or comprehension). Mellea's "
                                    f"backend walks grounding_context values "
                                    f"and expects each to be a CBlock / "
                                    f"Component / ModelOutputThunk — in "
                                    f"practice, a string. Collection-literal "
                                    f"values crash at m.instruct() with "
                                    f"`ValueError: parts should only contain "
                                    f"CBlocks, Components, or "
                                    f"ModelOutputThunks; found <list>`. Fix: "
                                    f"wrap with `str(...)`, e.g. "
                                    f"`{key_label}: str([r.model_dump() for r "
                                    f"in risks])`."
                                ),
                                rule_ref="grounding-context-types (hard, collection literal)",
                            )
                        )
                    else:  # ambiguous
                        has_ambiguous = True
                        result.failures.append(
                            LintFailure(
                                file=rel,
                                line=line,
                                column=column,
                                message=(
                                    f"grounding_context key {key_label} has a "
                                    f"non-string-literal value (Name, "
                                    f"Attribute, or other expression). It "
                                    f"may be a string at runtime, but the "
                                    f"lint cannot verify. To be safe and "
                                    f"explicit, wrap with `str(...)` — e.g. "
                                    f"`{key_label}: str(<expr>)`."
                                ),
                                rule_ref="grounding-context-types (advisory, ambiguous)",
                            )
                        )

    if has_definite:
        result.verdict = "fail"
    elif has_ambiguous:
        result.verdict = "warning"
    return result


# ─── Lint: stdlib-arg-types ───
#
# A Mellea API kwarg with a dict annotation receives a clearly-non-dict
# argument, crashing at runtime with:
#
#     AttributeError: '<TypeName>' object has no attribute 'items'
#
# Narrow first version: focuses on `grounding_context=` on the Mellea
# session `instruct`/`chat`/`act` family — that's where the observed
# runtime crashes happen. Broader Mellea-kwarg coverage is a follow-up.
#
# Detection: walk function defs, record each param's annotation, then
# walk Call nodes inside the function for `grounding_context=` kwargs.
# Flag when the value is provably non-dict: a non-dict Constant, an
# f-string, or a Name pointing to a function parameter with a provably
# non-dict annotation. Ambiguous cases (no annotation, `Any`, unions
# containing dict, attribute access, arbitrary call) are skipped — the
# lint surfaces only statically-provable misuse.


_STDLIB_ARG_TYPES_FILES: Tuple[str, ...] = (
    "pipeline.py",
    "slots.py",
    "requirements.py",
    "constrained_slots.py",
    "tools.py",
)

_GROUNDING_CONTEXT_METHODS: frozenset = frozenset({
    "instruct",
    "chat",
    "act",
    "ainstruct",
    "achat",
    "aact",
})

_DICT_FAMILY_BASES: frozenset = frozenset({
    "dict",
    "Dict",
    "Mapping",
    "MutableMapping",
    "OrderedDict",
    "DefaultDict",
})


def _annotation_is_dict_family(node: Optional[ast.expr]) -> Optional[bool]:
    """Classify a parameter annotation expression.

    Returns:
      * ``True``  — annotation IS dict-family (``dict``, ``dict[str, X]``,
        ``Mapping``, etc.).
      * ``False`` — annotation is provably NOT dict-family.
      * ``None``  — annotation is missing / ambiguous (``Any``, unions
        containing dict, generic ``object``, no annotation at all).
    """
    if node is None:
        return None
    if isinstance(node, ast.Name):
        if node.id in _DICT_FAMILY_BASES:
            return True
        if node.id == "Any" or node.id == "object":
            return None
        return False
    if isinstance(node, ast.Subscript):
        base = node.value
        if isinstance(base, ast.Name):
            if base.id in _DICT_FAMILY_BASES:
                return True
            if base.id in {"Optional", "Union"}:
                return None
            return False
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if node.value in _DICT_FAMILY_BASES:
            return True
        return False
    return None


def _classify_grounding_context_arg(
    value: ast.expr, param_annotations: Dict[str, ast.expr]
) -> Optional[str]:
    """Classify a single ``grounding_context=<expr>`` argument value.

    Returns:
      * ``"non_dict_literal"`` — value is a non-dict Constant or f-string.
      * ``"non_dict_param"``   — value is a Name pointing to a function
        parameter whose annotation is provably non-dict.
      * ``None`` — dict-shape or statically ambiguous.
    """
    if isinstance(value, ast.Dict):
        return None
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "dict":
        return None
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in _DICT_FAMILY_BASES:
        return None
    if isinstance(value, ast.Constant) and not isinstance(value.value, dict):
        if value.value is None:
            # `grounding_context=None` is treated as empty dict by some
            # Mellea versions; ambiguous wrt API, don't flag.
            return None
        return "non_dict_literal"
    if isinstance(value, ast.JoinedStr):
        return "non_dict_literal"
    if isinstance(value, ast.Name):
        annotation = param_annotations.get(value.id)
        if annotation is not None:
            classification = _annotation_is_dict_family(annotation)
            if classification is False:
                return "non_dict_param"
    return None


def _collect_function_param_annotations(
    func: ast.AST,
) -> Dict[str, ast.expr]:
    """Map each parameter name → its annotation AST node (or skip if
    no annotation)."""
    out: Dict[str, ast.expr] = {}
    args = func.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        if arg.annotation is not None:
            out[arg.arg] = arg.annotation
    if args.vararg and args.vararg.annotation is not None:
        out[args.vararg.arg] = args.vararg.annotation
    if args.kwarg and args.kwarg.annotation is not None:
        out[args.kwarg.arg] = args.kwarg.annotation
    return out


def lint_stdlib_arg_types(package_dir: Path) -> LintResult:
    """Flag clearly-non-dict arguments passed to Mellea API ``grounding_context=`` kwargs.

    Narrow MVP scope: only checks ``grounding_context=`` on session-method
    calls in the ``instruct``/``chat``/``act`` family.
    """
    result = LintResult(lint_id="stdlib-arg-types", verdict="pass")

    files_to_check: List[Path] = []
    for fname in _STDLIB_ARG_TYPES_FILES:
        p = package_dir / fname
        if p.exists():
            files_to_check.append(p)
    result.files_checked = len(files_to_check)

    for py_file in files_to_check:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue

        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            annotations = _collect_function_param_annotations(func)

            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute):
                    continue
                method_name = node.func.attr
                if method_name not in _GROUNDING_CONTEXT_METHODS:
                    continue
                for kw in node.keywords:
                    if kw.arg != "grounding_context":
                        continue
                    classification = _classify_grounding_context_arg(
                        kw.value, annotations
                    )
                    if classification is None:
                        continue
                    if classification == "non_dict_literal":
                        msg = (
                            f"`{method_name}(...)` call passes a "
                            f"non-dict literal as `grounding_context=`. "
                            f"Mellea iterates this argument with "
                            f"`.items()` — a string/int/list/bool "
                            f"argument crashes at runtime with "
                            f"`AttributeError: '<type>' object has no "
                            f"attribute 'items'`. Pass an actual dict, "
                            f"e.g. `grounding_context={{}}` or "
                            f"`grounding_context={{...}}`."
                        )
                    else:  # non_dict_param
                        param_ref = (
                            ast.unparse(kw.value)
                            if hasattr(ast, "unparse")
                            else getattr(kw.value, "id", "<expr>")
                        )
                        msg = (
                            f"`{method_name}(...)` call passes "
                            f"`grounding_context={param_ref}` where "
                            f"`{param_ref}` is a function parameter "
                            f"annotated with a non-dict type. Mellea "
                            f"iterates the argument with `.items()` and "
                            f"crashes with `AttributeError: '<type>' "
                            f"object has no attribute 'items'` at "
                            f"runtime. Either change the parameter "
                            f"annotation to a dict-family type, OR "
                            f"convert the value at the call site (e.g. "
                            f"`grounding_context={param_ref}.model_dump()`"
                            f" for a Pydantic model, or "
                            f"`grounding_context={{'key': str({param_ref})}}`"
                            f")."
                        )
                    result.failures.append(
                        LintFailure(
                            file=rel,
                            line=getattr(node, "lineno", None),
                            column=getattr(node, "col_offset", None),
                            message=msg,
                            rule_ref="stdlib-arg-types",
                        )
                    )

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Lint: prefix-persona (KB7) ───
#
# `m.instruct(prefix=<config_constant>)` is misuse: `prefix=` is for
# structured-output continuation (e.g. `prefix='{"result":"'`), not
# persona injection. Use `model_options={ModelOption.SYSTEM_PROMPT: ...}`
# instead. We flag bare Name expressions (config constants and
# uppercase-name candidates); plain string literals are accepted as a
# valid continuation prefix.


_PREFIX_PERSONA_LINT_FILES: Tuple[str, ...] = (
    "pipeline.py",
    "slots.py",
    "constrained_slots.py",
)


def _collect_config_constant_names(package_dir: Path) -> Set[str]:
    """Return the set of top-level constant names defined in `<package>/config.py`."""
    config_path = package_dir / "config.py"
    if not config_path.exists():
        return set()
    try:
        tree = ast.parse(config_path.read_text(), filename=str(config_path))
    except SyntaxError:
        return set()
    names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _collect_names_imported_from_config(tree: ast.AST) -> Set[str]:
    """Return names brought in via `from config import X` or `from .config import X`."""
    names: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if module == "config" or module.endswith(".config"):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _is_instruct_attribute_call(node: ast.AST) -> bool:
    """True iff node is an `<x>.instruct(...)` Call (any receiver)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == "instruct"


def lint_prefix_persona(package_dir: Path) -> LintResult:
    """`m.instruct(prefix=<config_constant>)` is misuse (KB7).

    `prefix=` is for structured-output continuation; not for persona /
    system-prompt injection.
    """
    result = LintResult(lint_id="prefix-persona", verdict="pass")

    config_constants = _collect_config_constant_names(package_dir)

    files_to_check: List[Path] = []
    for fname in _PREFIX_PERSONA_LINT_FILES:
        p = package_dir / fname
        if p.exists():
            files_to_check.append(p)
    result.files_checked = len(files_to_check)

    for py_file in files_to_check:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue

        config_imported = _collect_names_imported_from_config(tree)

        for node in ast.walk(tree):
            if not _is_instruct_attribute_call(node):
                continue
            for kw in node.keywords:
                if kw.arg != "prefix":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(
                    kw.value.value, str
                ):
                    continue
                if isinstance(kw.value, ast.Name):
                    name = kw.value.id
                    is_config_const = name in config_constants
                    is_config_import = name in config_imported
                    provenance = (
                        " (defined in config.py)"
                        if is_config_const
                        else (
                            " (imported from config)"
                            if is_config_import
                            else " (looks like a config constant — uppercase Name)"
                            if name.isupper()
                            else ""
                        )
                    )
                    result.failures.append(
                        LintFailure(
                            file=rel,
                            line=getattr(node, "lineno", None),
                            column=getattr(node, "col_offset", None),
                            message=(
                                f"`.instruct(prefix={name})`{provenance} uses "
                                f"the `prefix=` parameter to inject persona / "
                                f"system-prompt text. `prefix=` is for "
                                f"structured-output continuation (e.g. "
                                f"`prefix='{{\"result\":\"'`), not persona "
                                f"injection. Fix: use `model_options="
                                f"{{ModelOption.SYSTEM_PROMPT: {name}}}` "
                                f"instead (`from mellea.backends.model_options"
                                f" import ModelOption`)."
                            ),
                            rule_ref="KB7 (prefix= for persona vs SYSTEM_PROMPT)",
                        )
                    )

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Shared helpers: m.instruct / start_session pattern detection ───
#
# Used by instruct-result-parse-before-access, format-annotation, and
# session-boundary. The three lints share the same surface (pipeline.py,
# slots.py, constrained_slots.py) and the same notion of an "m.instruct(...)"
# call assigned to a Name target.


_INSTRUCT_LINT_FILES: Tuple[str, ...] = (
    "pipeline.py",
    "slots.py",
    "constrained_slots.py",
)


def _is_m_instruct_call(node: ast.AST) -> bool:
    """True iff node is a `Call` whose func is `m.instruct` (Attribute on Name 'm')."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "instruct":
        return False
    return isinstance(func.value, ast.Name) and func.value.id == "m"


def _instruct_call_has_format_kwarg(node: ast.Call) -> bool:
    """True iff an `m.instruct(...)` Call has a `format=` keyword."""
    return any(kw.arg == "format" for kw in node.keywords)


def _iter_function_scopes(tree: ast.AST):
    """Yield every FunctionDef/AsyncFunctionDef + the module-level scope."""
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node



# ─── Lint: import-soundness ───
#
# Every `mellea.*` import path in the compiled package must exist in the
# introspected Mellea API surface at `intermediate/mellea_api_ref.json`.
# Catches the LLM hallucinating shortened or non-existent import paths
# (e.g. `from mellea.model_options import ...` when the symbol lives at
# `mellea.backends.model_options`).
#
# Skipped when the api_ref is missing, malformed, or marked
# ``grounding_unavailable=true`` — the lint can't run without ground truth.


def _load_known_mellea_modules(package_dir: Path) -> Optional[Set[str]]:
    """Return the set of `mellea.*` module paths from the grounding file.

    Returns ``None`` if `intermediate/mellea_api_ref.json` is absent,
    malformed, or carries `grounding_unavailable=true`.
    """
    api_ref_path = package_dir / "intermediate" / "mellea_api_ref.json"
    if not api_ref_path.exists():
        return None
    try:
        data = json.loads(api_ref_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("grounding_unavailable", False):
        return None
    modules = data.get("modules")
    if not isinstance(modules, dict):
        return None
    return {k for k in modules.keys() if isinstance(k, str)}


def lint_import_soundness(package_dir: Path) -> LintResult:
    """Every `mellea.*` import path must exist in `mellea_api_ref.json:.modules`."""
    result = LintResult(lint_id="import-soundness", verdict="pass")

    known_modules = _load_known_mellea_modules(package_dir)
    if known_modules is None:
        result.verdict = "skipped"
        result.skipped_reason = (
            "intermediate/mellea_api_ref.json absent, malformed, or marked "
            "grounding_unavailable=true"
        )
        return result

    py_files: List[Path] = []
    for p in sorted(package_dir.rglob("*.py")):
        rel = p.relative_to(package_dir).as_posix()
        if not _is_skipped_path(rel):
            py_files.append(p)
    result.files_checked = len(py_files)

    for py_file in py_files:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue  # the parseable lint is responsible

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if not module.startswith("mellea"):
                    continue
                # `from mellea import generative` / `from mellea import
                # start_session` reaches top-level re-exports — accept
                # `mellea` itself as known even though the grounding
                # indexes sub-modules only.
                if module == "mellea":
                    continue
                if module in known_modules:
                    continue
                result.failures.append(
                    LintFailure(
                        file=rel,
                        line=getattr(node, "lineno", None),
                        column=_col_offset_to_schema(node),
                        message=(
                            f"`from {module} import ...` references a Mellea "
                            f"module path that does not exist in "
                            f"intermediate/mellea_api_ref.json:.modules. "
                            f"Common error: a shortened path (e.g. "
                            f"`mellea.model_options` instead of "
                            f"`mellea.backends.model_options`)."
                        ),
                        rule_ref="Rule 4-2 (import-soundness)",
                    )
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if not name.startswith("mellea"):
                        continue
                    if name in known_modules:
                        continue
                    result.failures.append(
                        LintFailure(
                            file=rel,
                            line=getattr(node, "lineno", None),
                            column=_col_offset_to_schema(node),
                            message=(
                                f"`import {name}` references a Mellea module "
                                f"path that does not exist in "
                                f"intermediate/mellea_api_ref.json:.modules."
                            ),
                            rule_ref="Rule 4-2 (import-soundness)",
                        )
                    )

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Lint: import-side-effects ───
#
# Module-level Call expressions execute at import time. The package must be
# importable for inspection / lint walks / test discovery without side
# effects; calls like `load_dotenv()`, `requests.get(...)` at module scope
# are forbidden. A small allowlist permits idempotent registry lookups
# (`logging.getLogger`, `os.environ.get`, `os.getenv`).


_IMPORT_SIDE_EFFECTS_FILES: Tuple[str, ...] = (
    "pipeline.py",
    "slots.py",
    "constrained_slots.py",
    "requirements.py",
    "schemas.py",
    "tools.py",
    "loader.py",
    "main.py",
    "config.py",
)

_ALLOWED_TOP_LEVEL_CALL_NAMES: frozenset = frozenset({
    "getLogger",  # logging.getLogger() — idempotent registry lookup
    "get",        # os.environ.get(...) for config
    "Final",      # typing.Final (legacy compatibility — not actually a call)
})


def _expr_callee_chain(node: ast.expr) -> Optional[str]:
    """Return the dotted callee chain of a Call.func, or None.

    Examples:
      `getLogger(__name__)` → "getLogger"
      `logging.getLogger(...)` → "logging.getLogger"
      `os.environ.get(...)` → "os.environ.get"
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        chain = node.attr
        cur = node.value
        while isinstance(cur, ast.Attribute):
            chain = cur.attr + "." + chain
            cur = cur.value
        if isinstance(cur, ast.Name):
            chain = cur.id + "." + chain
        return chain
    return None


def _is_allowed_top_level_call(call: ast.Call) -> bool:
    """Allowlist check: idempotent registry lookups + simple env reads."""
    chain = _expr_callee_chain(call.func)
    if chain is None:
        return False
    leaf = chain.rsplit(".", 1)[-1]
    if leaf in _ALLOWED_TOP_LEVEL_CALL_NAMES:
        return True
    if chain in ("logging.getLogger", "os.environ.get", "os.getenv"):
        return True
    return False


_KNOWN_SIDE_EFFECTING_CHAINS: frozenset = frozenset({
    "load_dotenv",
    "dotenv.load_dotenv",
    "requests.get",
    "requests.post",
    "urlopen",
    "urllib.request.urlopen",
})


def lint_import_side_effects(package_dir: Path) -> LintResult:
    """No module-level Calls outside the documented allowlist.

    Bare ``ast.Expr`` whose value is a Call (e.g. ``load_dotenv()`` at the
    top of a file) executes at import time; flagged. Module-level assignments
    where the RHS is a Call are flagged only when the callee is known to be
    side-effecting (network/env mutation) — allowing safe patterns like
    ``LOGGER = logging.getLogger(__name__)``.
    """
    result = LintResult(lint_id="import-side-effects", verdict="pass")

    files_to_check: List[Path] = []
    for fname in _IMPORT_SIDE_EFFECTS_FILES:
        p = package_dir / fname
        if p.exists():
            files_to_check.append(p)
    result.files_checked = len(files_to_check)

    for py_file in files_to_check:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue

        for stmt in tree.body:
            # Bare Call statement at module level
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                if _is_allowed_top_level_call(stmt.value):
                    continue
                chain = _expr_callee_chain(stmt.value.func) or "<unresolved>"
                result.failures.append(
                    LintFailure(
                        file=rel,
                        line=getattr(stmt, "lineno", None),
                        column=_col_offset_to_schema(stmt),
                        message=(
                            f"module-level call `{chain}(...)` executes at "
                            f"import time. Outside the allowlist "
                            f"(logging.getLogger, os.environ.get, os.getenv), "
                            f"this is forbidden because import-time side "
                            f"effects make the package un-importable for "
                            f"inspection / introduce test-order coupling / "
                            f"fail in non-runtime contexts. Move into a "
                            f"function call site or the run_pipeline entry."
                        ),
                        rule_ref="import-side-effects",
                    )
                )
            # Assignment with Call RHS at module level — fail only when the
            # callee is a known side-effecting name. Don't flag safe patterns
            # like `LOGGER = logging.getLogger(__name__)`.
            elif isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                if _is_allowed_top_level_call(stmt.value):
                    continue
                chain = _expr_callee_chain(stmt.value.func) or "<unresolved>"
                if chain in _KNOWN_SIDE_EFFECTING_CHAINS:
                    result.failures.append(
                        LintFailure(
                            file=rel,
                            line=getattr(stmt, "lineno", None),
                            column=_col_offset_to_schema(stmt),
                            message=(
                                f"module-level assignment "
                                f"`<var> = {chain}(...)` executes the callee "
                                f"at import. `{chain}` is known to have side "
                                f"effects (env mutation, network I/O) and is "
                                f"forbidden outside an explicit function "
                                f"scope. Move the call inside `run_pipeline` "
                                f"or another lazy entry point."
                            ),
                            rule_ref="import-side-effects",
                        )
                    )

    if result.failures:
        result.verdict = "fail"
    return result


# ─── Lint: parseable (Tier 1) ───
#
# Two checks: per-file ``ast.parse()`` on every .py under the package, and
# a subprocess ``python -c "import <pkg>.pipeline"`` to surface import
# errors AST can't see (wrong external import paths, etc.).


def lint_parseable(package_dir: Path) -> LintResult:
    """Every `.py` file under the package must parse, and `<pkg>.pipeline` must import.

    Two checks, executed in order:

      1. Per-file parseability: `ast.parse(p.read_text())` for every `.py`
         file directly under `<package_dir>/` and `<package_dir>/fixtures/`.
      2. Package importability: `python -c "import <package_name>.pipeline"`
         executed as a clean subprocess from `<package_dir>.parent`. This
         surfaces wrong external import paths (e.g.
         `mellea.stdlib.strategies` instead of `mellea.stdlib.sampling`)
         that `ast.parse()` cannot detect.

    Why a subprocess: importing the package directly in the lint process
    would pollute namespace, risk hanging on import side effects, or get
    masked by cached `sys.modules` entries. A clean child process surfaces
    exactly the error a downstream consumer (`pip install` + `python -c`)
    would see.

    Missing `pipeline.py`: returns one ERROR failure naming the absent
    entry module. Tier 1 should hard-fail loudly so the slash-command
    gate halts before Tier 2/3 lints run on a package with no entry.

    Scope: files directly under `<package_dir>/` and
    `<package_dir>/fixtures/` only.
    """
    import subprocess
    import sys

    result = LintResult(lint_id="parseable", verdict="pass")

    pipeline_path = package_dir / "pipeline.py"
    if not pipeline_path.exists():
        result.verdict = "fail"
        result.failures.append(
            LintFailure(
                file="pipeline.py",
                line=None,
                column=None,
                message=(
                    "pipeline.py absent — parseable lint cannot run. "
                    "The Tier 1 importability check requires the canonical "
                    "entry module `<package_name>/pipeline.py`. This is a "
                    "mandatory output of every compile (Rule 3-2)."
                ),
                rule_ref="mellea-fy-validate.md#tier-1-parseability",
            )
        )
        return result

    # ── Check 1: per-file ast.parse() ──
    py_files: List[Path] = []
    pkg_root_files = sorted(p for p in package_dir.glob("*.py"))
    fixtures_dir = package_dir / "fixtures"
    fixtures_files: List[Path] = []
    if fixtures_dir.is_dir():
        fixtures_files = sorted(p for p in fixtures_dir.glob("*.py"))
    py_files.extend(pkg_root_files)
    py_files.extend(fixtures_files)
    result.files_checked = len(py_files)

    for py_file in py_files:
        rel = py_file.relative_to(package_dir).as_posix()
        try:
            ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError as exc:
            result.failures.append(
                LintFailure(
                    file=rel,
                    line=exc.lineno,
                    column=exc.offset,
                    message=(
                        f"SyntaxError parsing {rel}: {exc.msg}. "
                        f"The file is not a valid Python module; "
                        f"downstream lints and runtime import will fail."
                    ),
                    rule_ref="mellea-fy-validate.md#tier-1-parseability",
                )
            )
        except Exception as exc:  # noqa: BLE001 — any read/decode error is fatal
            result.failures.append(
                LintFailure(
                    file=rel,
                    line=None,
                    column=None,
                    message=(
                        f"{type(exc).__name__} reading or parsing {rel}: {exc}."
                    ),
                    rule_ref="mellea-fy-validate.md#tier-1-parseability",
                )
            )

    # If any file failed to parse, skip the import check — the subprocess
    # import would crash on the same syntax error with a less specific
    # traceback.
    if result.failures:
        result.verdict = "fail"
        return result

    # ── Check 2: subprocess import of `<package_name>.pipeline` ──
    package_name = package_dir.name
    parent = package_dir.parent
    cmd = [sys.executable, "-c", f"import {package_name}.pipeline"]
    env_path = str(parent)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(parent),
            env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        result.failures.append(
            LintFailure(
                file="pipeline.py",
                line=None,
                column=None,
                message=(
                    f"Timeout (>30s) importing {package_name}.pipeline. "
                    f"Module-level code is likely blocking (infinite loop, "
                    f"blocking network call, or a deadlock). Import-time "
                    f"side effects are forbidden — see import-side-effects."
                ),
                rule_ref="mellea-fy-validate.md#tier-1-parseability",
            )
        )
        result.verdict = "fail"
        return result
    except Exception as exc:  # noqa: BLE001
        result.failures.append(
            LintFailure(
                file="pipeline.py",
                line=None,
                column=None,
                message=(
                    f"Failed to spawn subprocess for import check: "
                    f"{type(exc).__name__}: {exc}"
                ),
                rule_ref="mellea-fy-validate.md#tier-1-parseability",
            )
        )
        result.verdict = "fail"
        return result

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if len(stderr) > 2000:
            stderr = "... " + stderr[-2000:]
        result.failures.append(
            LintFailure(
                file="pipeline.py",
                line=None,
                column=None,
                message=(
                    f"`python -c 'import {package_name}.pipeline'` failed "
                    f"(exit {proc.returncode}). This catches wrong external "
                    f"import paths (e.g. `mellea.stdlib.strategies` vs the "
                    f"real `mellea.stdlib.sampling`) that ast.parse() cannot "
                    f"detect. Subprocess stderr:\n{stderr}"
                ),
                rule_ref="mellea-fy-validate.md#tier-1-parseability",
            )
        )
        result.verdict = "fail"
        return result

    return result



# ─── Runner ───


ALL_LINTS: Tuple[Callable[[Path], LintResult], ...] = (
    lint_fixtures_loader_contract,
    lint_bundled_asset_path_resolution,
    lint_runtime_defaults_bound,
    lint_session_method_arity,
    lint_instruct_result_parse_before_access,
    lint_format_annotation,
    lint_session_boundary,
    lint_validation_fn_not_called_directly,
    lint_fixture_pydantic_coercion,
    lint_grounding_context_types,
    lint_stdlib_arg_types,
    lint_prefix_persona,
    lint_parseable,
    lint_import_soundness,
    lint_import_side_effects,
)


def run_lints(package_dir: Path) -> LintRunResult:
    """Run all implemented Step 7 structural lints; write step_7_report.json."""
    results: List[LintResult] = [lint_fn(package_dir) for lint_fn in ALL_LINTS]
    overall = "fail" if any(r.verdict == "fail" for r in results) else "pass"
    run_result = LintRunResult(
        overall_verdict=overall,
        lints=results,
        package_path=str(package_dir),
        checked_at=datetime.now(timezone.utc).isoformat(),
    )

    intermediate = package_dir / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)
    report = {
        "format_version": "1.0",
        "checked_at": run_result.checked_at,
        "package_path": run_result.package_path,
        "overall_verdict": run_result.overall_verdict,
        "lints": [
            {
                "lint_id": r.lint_id,
                "verdict": r.verdict,
                "files_checked": r.files_checked,
                "skipped_reason": r.skipped_reason,
                "failures": [asdict(f) for f in r.failures],
            }
            for r in results
        ],
    }
    (intermediate / "step_7_report.json").write_text(json.dumps(report, indent=2))

    return run_result
