"""Export pipeline: 5 stages (validate → load → translate → emit → lint)."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from packaging.version import Version


EXPORT_VERSION = "0.1.0"
MIN_MANIFEST_VERSION = Version("1.0.0")

SUPPORTED_TARGETS = {"langgraph", "claude-code", "mcp"}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Invocation:
    package_path: Path
    target: str
    out_path: Optional[Path] = None  # derived automatically if not set
    force: bool = False


@dataclass
class ParsedSignature:
    """Parsed from manifest entry_signature string."""
    function_name: str
    params: list[dict]          # [{name, type, required, default}, ...]
    return_type: str
    pattern: str                # "no_args" | "dict_unpack" | "single_positional"


@dataclass
class LoadedContext:
    invocation: Invocation
    manifest: dict
    package_source_dir: Path        # root that contains melleafy.json (skill root)
    python_package_dir: Path        # actual importable Python package directory
    supporting_asset_dirs: list[Path]  # dirs to copy alongside the package (e.g. scripts/)
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
            _halt(2, f"melleafy.json not found in {inv.package_path} or any *_mellea/ subdirectory")
        manifest_path = found[0]

    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        _halt(2, f"melleafy.json is not valid JSON: {e}")

    # Accept manifest_version (preferred) or format_version (emitted by melleafy v4.3.x).
    # Normalize 2-part versions like "1.0" → "1.0.0" before parsing.
    raw_mv = manifest.get("manifest_version") or manifest.get("format_version", "0.0.0")
    mv = raw_mv if raw_mv.count(".") >= 2 else raw_mv + ".0"
    try:
        if Version(mv) < MIN_MANIFEST_VERSION:
            _halt(2, f"manifest_version {raw_mv} < required {MIN_MANIFEST_VERSION}")
    except Exception:
        _halt(2, f"manifest_version '{raw_mv}' is not a valid semver string")

    if inv.target not in SUPPORTED_TARGETS:
        _halt(2, f"Unsupported target '{inv.target}'. Supported: {sorted(SUPPORTED_TARGETS)}")

    if inv.out_path is not None and not inv.force and inv.out_path.exists() and (
        not inv.out_path.is_dir() or any(inv.out_path.iterdir())
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
    sig_str = manifest.get("entry_signature") or manifest.get("run_pipeline_signature", "")
    if not sig_str:
        _halt(2, "manifest missing 'entry_signature'")

    sig = _parse_entry_signature(sig_str)

    entry_module = "pipeline"

    package_name = manifest.get("package_name")
    if not package_name:
        _halt(2, "manifest missing 'package_name'")

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
        _SKIP_DIRS = {package_name, "intermediate", "fixtures", "__pycache__",
                      ".venv", ".git"}
        supporting_asset_dirs = [
            d for d in skill_root.iterdir()
            if d.is_dir() and d.name not in _SKIP_DIRS and not d.name.startswith(".")
        ]
    else:
        python_package_dir = skill_root
        supporting_asset_dirs = []

    # Policy manifest (optional)
    policy_path = skill_root / "policy_manifest.json"
    policy_manifest_path = policy_path if policy_path.exists() else None

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
    """Split a parameter string on commas, respecting brackets.

    'a: str, b: Dict[str, int], c: int = 0' → ['a: str', 'b: Dict[str, int]', 'c: int = 0']
    A plain split(",") breaks on commas inside brackets (e.g. Dict[str, int]).
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in params_str:
        if ch in ("[", "(", "{"):
            depth += 1
            current.append(ch)
        elif ch in ("]", ")", "}"):
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _parse_entry_signature(sig_str: str) -> ParsedSignature:
    """Parse 'run_pipeline(a: str, b: int = 0) -> ReturnType' into ParsedSignature."""
    m = re.match(r"^(\w+)\(([^)]*)\)\s*(?:->\s*(.+))?$", sig_str.strip())
    if not m:
        return ParsedSignature(
            function_name="run_pipeline",
            params=[],
            return_type="Any",
            pattern="no_args",
        )

    func_name = m.group(1)
    params_str = m.group(2).strip()
    return_type = (m.group(3) or "Any").strip()

    params = []
    if params_str:
        for part in _split_params(params_str):
            part = part.strip()
            if not part:
                continue
            has_default = "=" in part
            name_type = part.split("=")[0].strip()
            if ":" in name_type:
                name, ptype = name_type.split(":", 1)
                name = name.strip()
                ptype = ptype.strip()
            else:
                name = name_type
                ptype = "Any"
            params.append({
                "name": name,
                "type": ptype,
                "required": not has_default,
                "default": part.split("=", 1)[1].strip() if has_default else None,
            })

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
        return translate_langgraph(loaded)
    elif loaded.invocation.target == "claude-code":
        from mellea_skills_compiler.export.targets.claude_code import (
            translate_claude_code,
        )
        return translate_claude_code(loaded)
    elif loaded.invocation.target == "mcp":
        from mellea_skills_compiler.export.targets.mcp import translate_mcp
        return translate_mcp(loaded)
    _halt(2, f"No translator for target '{loaded.invocation.target}'")


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
        "guardian_configured": False,
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
        lines += ["## Deployment guidance", "", plan.deployment_guidance, ""]
    target = loaded.invocation.target
    if target == "langgraph":
        next_steps = [
            "1. Review `graph.py` — the generated node calls `run_pipeline` directly.",
            "2. Install dependencies: `pip install -e .`",
            "3. Invoke: `python -c \"from graph import graph; print(graph.invoke({'input': {}})['output'])\"`",
            "4. For LangGraph Platform: deploy using `langgraph.json`.",
        ]
    elif target == "mcp":
        next_steps = [
            "1. Review `server.py` — the generated tool wraps `run_pipeline`.",
            "2. Install dependencies: `pip install -e .`",
            "3. Register with an MCP client using `mcp.json`.",
            "4. Invoke via the MCP client or: `python server.py`.",
        ]
    elif target == "claude-code":
        next_steps = [
            "1. Review `scripts/run.sh` — the generated script calls `run_pipeline`.",
            "2. Install dependencies: `pip install -e .`",
            "3. Make executable: `chmod +x scripts/run.sh`",
            "4. Register under `.claude/skills/` and invoke via `bash scripts/run.sh <args>`.",
        ]
    else:
        next_steps = [
            "1. Install dependencies: `pip install -e .`",
            "2. Consult the generated README.md for invocation instructions.",
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


def stage5_lint(result: EmitResult, loaded: LoadedContext, plan: TranslationPlan) -> None:
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
                    n for n in ast.walk(tree)
                    if isinstance(n, ast.Assign)
                    and any(
                        isinstance(t, ast.Name) and t.id == "graph"
                        for t in n.targets
                    )
                ]
                if not assigns:
                    failures.append("graph.py: no module-level `graph = ...` assignment found")
            except SyntaxError as e:
                failures.append(f"graph.py: syntax error — {e}")
    elif target == "claude-code":
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
                has_fastmcp_import = any(
                    isinstance(n, ast.ImportFrom)
                    and n.module == "mcp.server.fastmcp"
                    and any(a.name == "FastMCP" for a in n.names)
                    for n in ast.walk(tree)
                )
                if not has_fastmcp_import:
                    failures.append("server.py: missing 'from mcp.server.fastmcp import FastMCP'")
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

                has_tool_decorator = any(_has_mcp_tool_decorator(n) for n in ast.walk(tree))
                if not has_tool_decorator:
                    failures.append("server.py: no @mcp.tool() decorated function found")
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

    pkg_dir = result.out_path / plan.bundled_package_name
    if not pkg_dir.is_dir():
        failures.append(f"Bundled package directory '{plan.bundled_package_name}' not found")

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
            _halt(2, f"Cannot derive output path: melleafy.json not found under {inv.package_path}")
        try:
            pkg_name = json.loads((manifest_dir / "melleafy.json").read_text()).get("package_name", "")
        except Exception:
            pkg_name = ""
        if not pkg_name:
            _halt(2, "Cannot derive output path: manifest missing 'package_name'. Pass out_path explicitly.")
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
