"""Export pipeline: 5 stages (validate → load → translate → emit → lint)."""

from __future__ import annotations

import ast
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from packaging.version import Version


EXPORT_VERSION = "0.1.0"
MIN_MANIFEST_VERSION = Version("1.0.0")

SUPPORTED_TARGETS = {"langgraph", "claude-code", "mcp", "pi"}

_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
_CLOSING_BRACKETS = {")", "]", "}"}


def _advance_expr_state(
    ch: str, quote: Optional[str], escaped: bool, stack: list[str]
) -> Optional[tuple[Optional[str], bool]]:
    """Advance quote/escape/bracket state by one char; return None on mismatch."""
    if quote is not None:
        if escaped:
            return quote, False
        if ch == "\\":
            return quote, True
        if ch == quote:
            return None, False
        return quote, False
    if ch in ("'", '"'):
        return ch, False
    if ch in _BRACKET_PAIRS:
        stack.append(_BRACKET_PAIRS[ch])
        return None, False
    if ch in _CLOSING_BRACKETS:
        if not stack or ch != stack[-1]:
            return None
        stack.pop()
        return None, False
    return None, False


def _is_balanced_expr(text: str) -> bool:
    """Return True iff all quotes and brackets in ``text`` are balanced."""
    quote: Optional[str] = None
    escaped = False
    stack: list[str] = []
    for ch in text:
        nxt = _advance_expr_state(ch, quote, escaped, stack)
        if nxt is None:
            return False
        quote, escaped = nxt
    return quote is None and not stack


def _split_signature_header(
    sig_str: str,
) -> Optional[tuple[str, str, Optional[str], bool]]:
    """Split ``name(params) -> ret`` with quote- and bracket-aware matching.

    Returns ``(func_name, params_str, return_type_or_empty, has_arrow)`` or
    ``None`` when the overall header shape is malformed or unbalanced.
    """
    s = sig_str.strip()
    open_idx = s.find("(")
    if open_idx <= 0:
        return None
    func_name = s[:open_idx].strip()
    if not func_name.isidentifier():
        return None

    quote: Optional[str] = None
    escaped = False
    stack: list[str] = []
    close_idx: Optional[int] = None
    for idx in range(open_idx, len(s)):
        nxt = _advance_expr_state(s[idx], quote, escaped, stack)
        if nxt is None:
            return None
        quote, escaped = nxt
        if quote is None and not stack:
            close_idx = idx
            break

    if close_idx is None or quote is not None or stack:
        return None

    params_str = s[open_idx + 1 : close_idx]
    rest = s[close_idx + 1 :].strip()
    if not rest:
        return func_name, params_str, None, False
    if rest.startswith("->"):
        return func_name, params_str, rest[2:].strip(), True
    return None


def _split_top_level(text: str, sep: str) -> tuple[str, Optional[str]]:
    """Split ``text`` on the first top-level ``sep`` outside brackets and quotes."""
    quote: Optional[str] = None
    escaped = False
    stack: list[str] = []
    for idx, ch in enumerate(text):
        if quote is None and not stack and ch == sep:
            if sep == "=":
                prev_ch = text[idx - 1] if idx > 0 else ""
                next_ch = text[idx + 1] if idx + 1 < len(text) else ""
                if prev_ch in ("=", "!", "<", ">") or next_ch == "=":
                    continue
            return text[:idx], text[idx + 1 :]
        nxt = _advance_expr_state(ch, quote, escaped, stack)
        if nxt is not None:
            quote, escaped = nxt
    return text, None


def _validate_manifest_version(raw_mv: Any) -> Optional[str]:
    """Validate raw manifest_version string against MIN_MANIFEST_VERSION.

    Returns an error message string if invalid, or None when valid.
    """
    if not isinstance(raw_mv, str) or isinstance(raw_mv, bool) or not raw_mv.strip():
        return f"manifest_version {raw_mv!r} is not a valid semver string"
    stripped = raw_mv.strip()
    mv = stripped if stripped.count(".") >= 2 else stripped + ".0"
    try:
        parsed = Version(mv)
    except Exception:
        return f"manifest_version '{raw_mv}' is not a valid semver string"
    if parsed < MIN_MANIFEST_VERSION:
        return f"manifest_version {raw_mv} < required {MIN_MANIFEST_VERSION}"
    return None


def _validate_entry_signature_str(sig_str: Any) -> Optional[str]:
    """Validate that an entry_signature string is well-formed for export.

    Returns an error message string if invalid, or None when valid.
    """
    if not isinstance(sig_str, str) or not sig_str.strip():
        return "manifest missing 'entry_signature'"
    header = _split_signature_header(sig_str)
    if header is None:
        return (
            f"manifest 'entry_signature' {sig_str!r} is malformed "
            "(expected '<func>(<params>) -> <ReturnType>')"
        )
    _, params_str, ret_str, has_arrow = header
    if has_arrow:
        if not ret_str:
            return (
                f"manifest 'entry_signature' {sig_str!r} has an empty return type after '->'"
            )
        if not _is_balanced_expr(ret_str):
            return (
                f"manifest 'entry_signature' {sig_str!r} has a malformed return type"
            )

    if params_str.strip():
        raw_parts = _split_params(params_str)
        for idx, raw_part in enumerate(raw_parts):
            part = raw_part.strip()
            if not part:
                # Allow a single trailing comma (e.g. `f(a: str,)`), reject leading/double commas.
                if idx == len(raw_parts) - 1 and idx > 0:
                    continue
                return (
                    f"manifest 'entry_signature' {sig_str!r} contains an empty parameter"
                )
            if not _is_balanced_expr(part):
                return (
                    f"manifest 'entry_signature' {sig_str!r} has unbalanced parameter "
                    f"syntax in {part!r}"
                )
            _, default_part = _split_top_level(part, "=")
            if default_part is not None and not default_part.strip():
                return (
                    f"manifest 'entry_signature' {sig_str!r} has an empty default value "
                    f"in {part!r}"
                )

    sig = _parse_entry_signature(sig_str)
    seen: set[str] = set()
    for p in sig.params:
        pname = p["name"]
        if not pname.isidentifier():
            return (
                f"manifest 'entry_signature' contains invalid parameter name "
                f"{pname!r} in {sig_str!r}"
            )
        if pname in seen:
            return (
                f"manifest 'entry_signature' contains duplicate parameter "
                f"{pname!r} in {sig_str!r}"
            )
        seen.add(pname)
    return None


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Invocation:
    package_path: Path
    target: str
    out_path: Optional[Path] = None  # derived automatically if not set
    force: bool = False
    enforce: bool = False


@dataclass
class ParsedSignature:
    """Parsed from manifest entry_signature string."""

    function_name: str
    params: list[dict]  # [{name, type, required, default}, ...]
    return_type: str
    pattern: str  # "no_args" | "dict_unpack" | "single_positional"


@dataclass
class LoadedContext:
    invocation: Invocation
    manifest: dict
    package_source_dir: Path  # root that contains melleafy.json (skill root)
    python_package_dir: Path  # actual importable Python package directory
    supporting_asset_dirs: list[
        Path
    ]  # dirs to copy alongside the package (e.g. scripts/)
    entry_module: str
    sig: ParsedSignature
    load_warnings: list[str] = field(default_factory=list)
    policy_manifest_path: Optional[Path] = None


@dataclass
class AdapterFile:
    relative_path: str
    content: str


@dataclass
class TranslationPlan:
    graph_name: str
    adapter_files: list[AdapterFile]
    bundled_package_name: str
    warnings: list[str] = field(default_factory=list)
    deployment_guidance: str = ""
    has_policy_manifest: bool = False
    enforce: bool = False


@dataclass
class EmitResult:
    out_path: Path
    files_written: int
    bytes_written: int


# ---------------------------------------------------------------------------
# Stage 1 — Validate
# ---------------------------------------------------------------------------


def stage1_validate(inv: Invocation) -> dict:
    """Read and validate melleafy.json. Returns raw manifest dict."""
    manifest_path = inv.package_path / "melleafy.json"
    if not manifest_path.exists():
        # New layout: melleafy.json lives inside <package_name>/ subdir (Rule OUT-3).
        # Fall back to old layout (skill root) for backwards compatibility.
        candidates = [
            d / "melleafy.json"
            for d in sorted(inv.package_path.iterdir())
            if d.is_dir() and d.name.endswith("_mellea")
        ]
        found = [c for c in candidates if c.exists()]
        if not found:
            _halt(
                2,
                f"melleafy.json not found in {inv.package_path} or any *_mellea/ subdirectory",
            )
        manifest_path = found[0]

    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        _halt(2, f"melleafy.json is not valid JSON: {e}")

    if not isinstance(manifest, dict):
        _halt(2, f"melleafy.json must be a JSON object, got {type(manifest).__name__}")

    # Accept manifest_version (preferred) or format_version (emitted by melleafy v4.3.x).
    # Normalize 2-part versions like "1.0" → "1.0.0" before parsing.
    raw_mv = manifest.get("manifest_version") or manifest.get("format_version", "0.0.0")
    mv_err = _validate_manifest_version(raw_mv)
    if mv_err:
        _halt(2, mv_err)

    if inv.target not in SUPPORTED_TARGETS:
        _halt(
            2,
            f"Unsupported target '{inv.target}'. Supported: {sorted(SUPPORTED_TARGETS)}",
        )

    if (
        inv.out_path is not None
        and not inv.force
        and inv.out_path.exists()
        and (not inv.out_path.is_dir() or any(inv.out_path.iterdir()))
    ):
        _halt(3, f"Output path {inv.out_path} is non-empty. Pass --force to overwrite.")

    return manifest


# ---------------------------------------------------------------------------
# Stage 2 — Load
# ---------------------------------------------------------------------------


def stage2_load(inv: Invocation, manifest: dict) -> LoadedContext:
    """Parse manifest fields, derive entry point, detect policy manifest."""
    warnings: list[str] = []

    # Accept entry_signature (preferred) or run_pipeline_signature (emitted by melleafy v4.3.x).
    sig_str = manifest.get("entry_signature") or manifest.get(
        "run_pipeline_signature", ""
    )
    sig_err = _validate_entry_signature_str(sig_str)
    if sig_err:
        _halt(2, sig_err)

    sig = _parse_entry_signature(sig_str)

    entry_module = "pipeline"

    package_name = manifest.get("package_name")
    if not isinstance(package_name, str) or not package_name.strip():
        _halt(2, "manifest missing 'package_name'")
    if not package_name.isidentifier():
        _halt(2, f"manifest 'package_name' {package_name!r} is not a valid Python identifier")

    # Locate the importable Python package.
    # If <skill_root>/<package_name>/ exists with __init__.py, use it.
    # Otherwise fall back to the skill root itself (older layout).
    skill_root = inv.package_path
    nested = skill_root / package_name
    if nested.is_dir() and (nested / "__init__.py").exists():
        python_package_dir = nested
        # Collect skill-root sibling dirs that are supporting assets (e.g. scripts/).
        # Under the current layout, intermediate/ and fixtures/ live inside
        # <package_name>/ so won't appear here; kept in skip set for old-layout compat.
        _SKIP_DIRS = {
            package_name,
            "intermediate",
            "fixtures",
            "__pycache__",
            ".venv",
            ".git",
        }
        supporting_asset_dirs = [
            d
            for d in skill_root.iterdir()
            if d.is_dir() and d.name not in _SKIP_DIRS and not d.name.startswith(".")
        ]
    else:
        python_package_dir = skill_root
        supporting_asset_dirs = []

    # Policy manifest (optional) — check the skill dir itself first, then any
    # subdirectory inside an `audit/` sibling directory produced by the certify command
    # (i.e. <skill_root.parent>/audit/*/policy_manifest.json).
    policy_manifest_path: Optional[Path] = None
    if (skill_root / "policy_manifest.json").exists():
        policy_manifest_path = skill_root / "policy_manifest.json"
    else:
        audit_parent: Path = Path(skill_root.parent / "audit")
        if audit_parent.exists():
            for audit_dir in reversed(list(audit_parent.glob("*"))):
                if (audit_dir / "policy_manifest.json").exists():
                    policy_manifest_path = audit_dir / "policy_manifest.json"
                    break

    return LoadedContext(
        invocation=inv,
        manifest=manifest,
        package_source_dir=skill_root,
        python_package_dir=python_package_dir,
        supporting_asset_dirs=supporting_asset_dirs,
        entry_module=entry_module,
        sig=sig,
        load_warnings=warnings,
        policy_manifest_path=policy_manifest_path,
    )


def _split_params(params_str: str) -> list[str]:
    """Split a parameter string on commas, respecting brackets and quotes.

    'a: str, b: Dict[str, int], c: tuple = ()' → ['a: str', 'b: Dict[str, int]', 'c: tuple = ()']
    A plain split(",") breaks on commas inside brackets or quoted defaults.
    """
    parts: list[str] = []
    quote: Optional[str] = None
    escaped = False
    stack: list[str] = []
    current: list[str] = []
    for ch in params_str:
        if quote is None and not stack and ch == ",":
            parts.append("".join(current))
            current = []
            continue
        nxt = _advance_expr_state(ch, quote, escaped, stack)
        if nxt is not None:
            quote, escaped = nxt
        current.append(ch)
    if current or parts:
        parts.append("".join(current))
    return parts


def _parse_entry_signature(sig_str: str) -> ParsedSignature:
    """Parse 'run_pipeline(a: str, b: int = 0) -> ReturnType' into ParsedSignature."""
    header = _split_signature_header(sig_str)
    if header is None:
        return ParsedSignature(
            function_name="run_pipeline",
            params=[],
            return_type="Any",
            pattern="no_args",
        )

    func_name, params_raw, ret_str, _ = header
    params_str = params_raw.strip()
    return_type = ret_str or "Any"

    params = []
    if params_str:
        for part in _split_params(params_str):
            part = part.strip()
            if not part:
                continue
            name_type_raw, default_raw = _split_top_level(part, "=")
            has_default = default_raw is not None
            name_type = name_type_raw.strip()
            pname_raw, ptype_raw = _split_top_level(name_type, ":")
            if ptype_raw is not None:
                name = pname_raw.strip()
                ptype = ptype_raw.strip() or "Any"
            else:
                name = name_type
                ptype = "Any"
            params.append(
                {
                    "name": name,
                    "type": ptype,
                    "required": not has_default,
                    "default": default_raw.strip() if default_raw is not None else None,
                }
            )

    # Determine pattern (Rule 3d-1)
    required = [p for p in params if p["required"]]
    if not params:
        pattern = "no_args"
    elif len(required) == 1 and required[0]["type"] in ("str", "int", "float", "bool"):
        pattern = "single_positional"
    else:
        pattern = "dict_unpack"

    return ParsedSignature(
        function_name=func_name,
        params=params,
        return_type=return_type,
        pattern=pattern,
    )


# ---------------------------------------------------------------------------
# Stage 3 — Translate
# ---------------------------------------------------------------------------


def stage3_translate(loaded: LoadedContext) -> TranslationPlan:
    """Build TranslationPlan from LoadedContext. Dispatches to target module."""
    if loaded.invocation.target == "langgraph":
        from mellea_skills_compiler.export.targets.langgraph import translate_langgraph

        plan = translate_langgraph(loaded)
    elif loaded.invocation.target == "claude-code":
        from mellea_skills_compiler.export.targets.claude_code import (
            translate_claude_code,
        )

        plan = translate_claude_code(loaded)
    elif loaded.invocation.target == "mcp":
        from mellea_skills_compiler.export.targets.mcp import translate_mcp

        plan = translate_mcp(loaded)
    elif loaded.invocation.target == "pi":
        from mellea_skills_compiler.export.targets.pi import translate_pi

        plan = translate_pi(loaded)
    else:
        _halt(2, f"No translator for target '{loaded.invocation.target}'")
    plan.has_policy_manifest = loaded.policy_manifest_path is not None
    plan.enforce = loaded.invocation.enforce
    return plan


# ---------------------------------------------------------------------------
# Stage 4 — Emit
# ---------------------------------------------------------------------------


def stage4_emit(plan: TranslationPlan, loaded: LoadedContext) -> EmitResult:
    """Write all files. Uses .partial/ pattern for atomic write."""
    out = loaded.invocation.out_path
    partial = out.parent / (out.name + ".partial")

    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True, exist_ok=True)

    try:
        # Copy bundled Python package, skipping export output and partial dirs
        pkg_dst = partial / plan.bundled_package_name
        pkg_name = plan.bundled_package_name
        _export_output_dirs = set()
        for t in SUPPORTED_TARGETS:
            _export_output_dirs.add(f"{pkg_name}-{t}")
            _export_output_dirs.add(f"{pkg_name}-{t}.partial")
        _copy_dir(loaded.python_package_dir, pkg_dst, skip_names=_export_output_dirs)

        # Copy supporting asset directories (e.g. scripts/) alongside the package
        for asset_dir in loaded.supporting_asset_dirs:
            _copy_dir(asset_dir, partial / asset_dir.name)

        # Write adapter files
        for af in plan.adapter_files:
            dest = partial / af.relative_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(af.content, encoding="utf-8")

        # Copy policy manifest if present
        if loaded.policy_manifest_path:
            shutil.copy2(loaded.policy_manifest_path, partial / "policy_manifest.json")

        # Reverse manifest
        reverse = _build_reverse_manifest(plan, loaded)
        (partial / "melleafy-export.json").write_text(
            json.dumps(reverse, indent=2), encoding="utf-8"
        )

        # EXPORT_NOTES.md
        notes = _build_export_notes(plan, loaded)
        (partial / "EXPORT_NOTES.md").write_text(notes, encoding="utf-8")

    except Exception:
        _write_halt_reason(partial, sys.exc_info())
        raise

    # os.replace() on POSIX cannot rename over a non-empty directory (ENOTEMPTY).
    # Stage 1 already verified force=True if out is non-empty, so rmtree is safe here.
    if out.exists():
        shutil.rmtree(out)
    os.replace(partial, out)

    files = sum(1 for _ in out.rglob("*") if _.is_file())
    byt = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    return EmitResult(out_path=out, files_written=files, bytes_written=byt)


def _copy_dir(src: Path, dst: Path, skip_names: set[str] | None = None) -> None:
    """Copy src directory to dst, skipping __pycache__, .pyc files, and any skip_names."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in ("__pycache__",) or item.suffix == ".pyc":
            continue
        if skip_names and item.name in skip_names:
            continue
        if item.is_dir():
            _copy_dir(item, dst / item.name, skip_names)
        else:
            shutil.copy2(item, dst / item.name)


def _build_reverse_manifest(plan: TranslationPlan, loaded: LoadedContext) -> dict:
    return {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "target": loaded.invocation.target,
        "graph_name": plan.graph_name,
        "bundled_package": plan.bundled_package_name,
        "source_manifest": loaded.manifest,
        "warnings": plan.warnings + loaded.load_warnings,
        "policy_manifest_bundled": loaded.policy_manifest_path is not None,
        "guardian_configured": (
            "enforce"
            if loaded.policy_manifest_path is not None and loaded.invocation.enforce
            else "audit" if loaded.policy_manifest_path is not None else False
        ),
    }


def _build_export_notes(plan: TranslationPlan, loaded: LoadedContext) -> str:
    manifest = loaded.manifest
    lines = [
        "# Export Notes",
        "",
        f"**Target**: {loaded.invocation.target}",
        f"**Source skill**: `{manifest.get('package_name', '?')}`",
        f"**Modality**: `{manifest.get('modality', '?')}`",
        f"**Exported**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    all_warnings = loaded.load_warnings + plan.warnings
    if all_warnings:
        lines += ["## Warnings", ""]
        for w in all_warnings:
            lines.append(f"- {w}")
        lines.append("")
    if plan.deployment_guidance:
        guidance = plan.deployment_guidance
        if loaded.policy_manifest_path is not None:
            guidance = (
                "Install `mellea-skills-compiler` before running: `pip install git+https://github.com/generative-computing/mellea-skills-compiler.git`. "
                + guidance
            )
        lines += ["## Deployment guidance", "", guidance, ""]
    target = loaded.invocation.target
    guardian = loaded.policy_manifest_path is not None
    install_step = (
        "Install dependencies: `pip install -e . && pip install git+https://github.com/generative-computing/mellea-skills-compiler.git`"
        if guardian
        else "Install dependencies: `pip install -e .`"
    )
    if target == "langgraph":
        state_key = (
            loaded.sig.params[0]["name"]
            if loaded.sig.pattern == "single_positional" and loaded.sig.params
            else "input"
        )
        next_steps = [
            "1. Review `graph.py` — the generated node calls `run_pipeline` directly.",
            f"2. {install_step}",
            f"3. Invoke: `python -c \"import asyncio; from graph import graph; print(asyncio.run(graph.ainvoke({{'{state_key}': {{}} }}))['output'])\"`",
            "4. For LangGraph Platform: deploy using `langgraph.json`.",
        ]
    elif target == "mcp":
        next_steps = [
            "1. Review `server.py` — the generated tool wraps `run_pipeline`.",
            f"2. {install_step}",
            "3. Register with an MCP client using `mcp.json`.",
            "4. Invoke via the MCP client or: `python server.py`.",
        ]
    elif target == "claude-code":
        next_steps = [
            "1. Review `scripts/run.sh` — the generated script calls `run_pipeline`.",
            f"2. {install_step}",
            "3. Make executable: `chmod +x scripts/run.sh`",
            "4. Register under `.claude/skills/` and invoke via `bash scripts/run.sh <args>`.",
        ]
    elif target == "pi":
        next_steps = [
            "1. Review `scripts/run.sh` — the generated script calls `run_pipeline`.",
            f"2. {install_step}",
            "3. Make executable: `chmod +x scripts/run.sh`",
            "4. Register under `.pi/skills/` (or `.agents/skills/`) and invoke via `bash scripts/run.sh <args>`.",
        ]
    else:
        next_steps = [
            f"1. {install_step}",
            "2. Consult the generated README.md for invocation instructions.",
        ]
    if guardian:
        mode = "enforce" if loaded.invocation.enforce else "audit"
        mode_note = (
            "**Mode**: enforce — risky operations will be **blocked** at runtime with a `PluginViolationError`. "
            "To switch to audit-only (observe but do not block), re-export without `--enforce`."
            if loaded.invocation.enforce
            else "**Mode**: audit — Guardian observes and logs but does not block operations."
        )
        if target in ("claude-code", "pi"):
            audit_path_line = "- **Audit log**: `$ADAPTER_DIR/audit/runtime_audit.jsonl` (defaults to `./audit` if `ADAPTER_DIR` is unset)."
            audit_cmd_line = '  `mkdir -p "$ADAPTER_DIR/audit"` (or `mkdir -p ./audit` if `ADAPTER_DIR` is unset)'
        else:
            audit_path_line = "- **Audit log**: `<bundle_dir>/audit/runtime_audit.jsonl`."
            audit_cmd_line = "  `mkdir -p <bundle_dir>/audit`"
        lines += [
            "## Guardian audit",
            "",
            f"This bundle was exported from a certified skill. Guardian {mode}-mode is active.",
            "",
            f"- {mode_note}",
            audit_path_line,
            "- **Write access**: the process running the entry point must have write permission to this"
            " directory. Create it if it does not exist:",
            audit_cmd_line,
            "- If the directory does not exist or isn't writable, the entry point will **fail at"
            " startup** (a loud, non-zero-exit error) rather than silently losing audit evidence.",
            "- To suppress Guardian at runtime, remove `policy_manifest.json` from the bundle directory.",
            "",
        ]
    lines += ["## Next steps", ""] + next_steps
    return "\n".join(lines) + "\n"


def _write_halt_reason(partial: Path, exc_info: Any) -> None:
    try:
        import traceback

        tb = "".join(traceback.format_exception(*exc_info))
        (partial / "HALT_REASON.md").write_text(f"# Export halted\n\n```\n{tb}\n```\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Stage 5 — Lint
# ---------------------------------------------------------------------------


def stage5_lint(
    result: EmitResult, loaded: LoadedContext, plan: TranslationPlan
) -> None:
    """Basic structural lint on emitted files. Halts with exit code 4 on failure."""
    failures: list[str] = []
    target = loaded.invocation.target

    if target == "langgraph":
        graph_py = result.out_path / "graph.py"
        if not graph_py.exists():
            failures.append("graph.py not found in output")
        else:
            try:
                tree = ast.parse(graph_py.read_text())
                assigns = [
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, ast.Assign)
                    and any(
                        isinstance(t, ast.Name) and t.id == "graph" for t in n.targets
                    )
                ]
                if not assigns:
                    failures.append(
                        "graph.py: no module-level `graph = ...` assignment found"
                    )
            except SyntaxError as e:
                failures.append(f"graph.py: syntax error — {e}")
    elif target == "claude-code":
        skill_md = result.out_path / "SKILL.md"
        if not skill_md.exists():
            failures.append("SKILL.md not found in output")
        run_sh = result.out_path / "scripts" / "run.sh"
        if not run_sh.exists():
            failures.append("scripts/run.sh not found in output")
    elif target == "pi":
        skill_md = result.out_path / "SKILL.md"
        if not skill_md.exists():
            failures.append("SKILL.md not found in output")
        run_sh = result.out_path / "scripts" / "run.sh"
        if not run_sh.exists():
            failures.append("scripts/run.sh not found in output")
    elif target == "mcp":
        server_py = result.out_path / "server.py"
        if not server_py.exists():
            failures.append("server.py not found in output")
        else:
            try:
                tree = ast.parse(server_py.read_text())
                has_mcpserver_import = any(
                    isinstance(n, ast.ImportFrom)
                    and n.module == "mcp.server.mcpserver"
                    and any(a.name == "MCPServer" for a in n.names)
                    for n in ast.walk(tree)
                )
                if not has_mcpserver_import:
                    failures.append(
                        "server.py: missing 'from mcp.server.mcpserver import MCPServer'"
                    )

                def _has_mcp_tool_decorator(node: ast.AST) -> bool:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        return False
                    for dec in node.decorator_list:
                        if isinstance(dec, ast.Attribute) and dec.attr == "tool":
                            return True
                        if isinstance(dec, ast.Call):
                            func = dec.func
                            if isinstance(func, ast.Attribute) and func.attr == "tool":
                                return True
                    return False

                has_tool_decorator = any(
                    _has_mcp_tool_decorator(n) for n in ast.walk(tree)
                )
                if not has_tool_decorator:
                    failures.append(
                        "server.py: no @mcp.tool() decorated function found"
                    )
            except SyntaxError as e:
                failures.append(f"server.py: syntax error — {e}")
        mcp_json = result.out_path / "mcp.json"
        if not mcp_json.exists():
            failures.append("mcp.json not found in output")
        else:
            try:
                import json as _json

                data = _json.loads(mcp_json.read_text())
                if "mcpServers" not in data:
                    failures.append("mcp.json: missing 'mcpServers' key")
            except Exception as e:
                failures.append(f"mcp.json: invalid JSON — {e}")

    if loaded.policy_manifest_path is not None:
        entry_files = {
            "langgraph": result.out_path / "graph.py",
            "mcp": result.out_path / "server.py",
            "claude-code": result.out_path / "scripts" / "run.sh",
            "pi": result.out_path / "scripts" / "run.sh",
        }
        entry_file = entry_files.get(target)
        if entry_file and entry_file.exists():
            content = entry_file.read_text()
            if "GuardianPluginFactory" not in content:
                failures.append(
                    f"{entry_file.name}: policy_manifest.json present but "
                    f"no Guardian plugin factory found in generated entry point"
                )

    pkg_dir = result.out_path / plan.bundled_package_name
    if not pkg_dir.is_dir():
        failures.append(
            f"Bundled package directory '{plan.bundled_package_name}' not found"
        )

    if (result.out_path / "melleafy-export.json").stat().st_size == 0:
        failures.append("melleafy-export.json is empty")

    if failures:
        print("Stage 5 lint FAILED:")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(4)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _resolve_manifest_dir(package_path: Path) -> Optional[Path]:
    """Return the directory containing melleafy.json, or None if not found."""
    if (package_path / "melleafy.json").exists():
        return package_path
    for d in sorted(package_path.iterdir()):
        if d.is_dir() and d.name.endswith("_mellea") and (d / "melleafy.json").exists():
            return d
    return None


def run_export(inv: Invocation) -> EmitResult:
    if inv.out_path is None:
        manifest_dir = _resolve_manifest_dir(inv.package_path)
        if manifest_dir is None:
            _halt(
                2,
                f"Cannot derive output path: melleafy.json not found under {inv.package_path}",
            )
        try:
            raw_manifest = json.loads((manifest_dir / "melleafy.json").read_text())
        except json.JSONDecodeError as e:
            _halt(2, f"melleafy.json is not valid JSON: {e}")
        if not isinstance(raw_manifest, dict):
            _halt(
                2,
                f"melleafy.json must be a JSON object, got {type(raw_manifest).__name__}",
            )
        pkg_name = raw_manifest.get("package_name", "")
        if not isinstance(pkg_name, str) or not pkg_name.strip():
            _halt(
                2,
                "Cannot derive output path: manifest missing 'package_name'. Pass out_path explicitly.",
            )
        inv.out_path = manifest_dir / f"{pkg_name}-{inv.target}"

    manifest = stage1_validate(inv)
    loaded = stage2_load(inv, manifest)
    plan = stage3_translate(loaded)
    result = stage4_emit(plan, loaded)
    stage5_lint(result, loaded, plan)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _halt(code: int, msg: str) -> None:
    print(f"Export halted: {msg}", file=sys.stderr)
    sys.exit(code)
