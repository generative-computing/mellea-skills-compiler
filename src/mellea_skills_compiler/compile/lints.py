"""Step 7 structural lints — Python implementations.

Implements two lints from `.claude/commands/mellea-fy-validate.md`:

  - `bundled-asset-path-resolution` (Rule OUT-6, Rule 2.5-2)
  - `fixtures-loader-contract` (R16, Rule 4-1)

The other 14 lints documented in `mellea-fy-validate.md` are still applied
by the LLM during Step 7 of the slash command. These two are implemented in
Python because they are AST-precise structural checks where LLM application
has proven unreliable, and they catch the exact drift modes that have caused
post-compile breakage in shipped skills (see session history).
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple


_BUNDLED_DIRS = ("scripts", "references", "assets")


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
    verdict: str  # "pass" | "fail" | "skipped"
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
                if bundled_hit is None or _is_path_dunder_file_parent(leftmost):
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
                        f"must be `Path(__file__).parent / \"{bundled_hit}\" / ...`."
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
                    if bundled_hit is None or _is_file_rooted(node.args[0]):
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


# ─── Runner ───


ALL_LINTS: Tuple[Callable[[Path], LintResult], ...] = (
    lint_fixtures_loader_contract,
    lint_bundled_asset_path_resolution,
    lint_runtime_defaults_bound,
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
