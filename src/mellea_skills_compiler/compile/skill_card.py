"""Agent skill card for a compiled package.
(schema v1.2 - https://github.com/evaleval/agent-skill-cards)

Every value is read or computed from the package directory. Any section the
package cannot fill is named in ``stamp.not_assembled``. 

``skill_card.json`` and ``skill_card.md`` will be written to the package root. Those two files and
``compile_metadata.json`` are left out of the file list and package hash.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

import mellea_skills_compiler
from mellea_skills_compiler.toolkit.file_utils import parse_spec_file
from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()

SCHEMA_VERSION = "skill-card-v1.2"
CARD_JSON = "skill_card.json"
CARD_MD = "skill_card.md"

# Left out of the file list and package hash: self-referential or volatile.
_EXCLUDED_FILES = {CARD_JSON, CARD_MD, "compile_metadata.json"}
_EXCLUDED_DIRS = {"__pycache__", ".melleafy-partial"}
_AUDIT_DIR_FORMAT = "%d-%m-%Y_%H-%M-%S"
_COMPANION_DIRS = {"scripts": "script", "references": "reference", "assets": "asset"}


# ── helpers ────────────────────────────────────────────────────────
def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _kind(rel: Path) -> str:
    parts = rel.parts
    if parts[0] == "intermediate":
        return "intermediate"
    if parts[0] == "fixtures":
        return "fixture"
    if parts[0] in _COMPANION_DIRS:
        return _COMPANION_DIRS[parts[0]]
    if rel.suffix == ".py":
        return "code"
    if rel.suffix in (".md", ".rst", ".txt"):
        return "doc"
    if rel.suffix in (".json", ".yaml", ".yml", ".toml"):
        return "manifest"
    return "other"


def list_package_files(package_dir: Path) -> List[Dict[str, Any]]:
    """File list (path, size, sha256, kind), sorted by path."""
    rows: List[Dict[str, Any]] = []
    for p in sorted(package_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(package_dir)
        if rel.name in _EXCLUDED_FILES and len(rel.parts) == 1:
            continue
        if any(part in _EXCLUDED_DIRS for part in rel.parts) or p.suffix == ".pyc":
            continue
        rows.append(
            {
                "path": rel.as_posix(),
                "size": p.stat().st_size,
                "sha256": _sha256(p),
                "kind": _kind(rel),
            }
        )
    return rows


def package_hash(files: List[Dict[str, Any]]) -> str:
    """Hash over the sorted (path, sha256) pairs of the file list."""
    h = hashlib.sha256()
    for row in files:
        h.update(f"{row['path']}\0{row['sha256']}\n".encode())
    return h.hexdigest()


def _git_commit(package_dir: Path) -> Optional[str]:
    try:
        return subprocess.check_output(
            ["git", "-C", str(package_dir), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _return_type(entry_signature: Optional[str]) -> Optional[str]:
    if not entry_signature or "->" not in entry_signature:
        return None
    return entry_signature.rsplit("->", 1)[1].strip()


def _check_row(
    check_id: str, tool: str, report_rel: str, report: Optional[dict], verdict_key: str
) -> Optional[Dict[str, Any]]:
    if not report:
        return None
    return {
        "id": check_id,
        "tool": f"{tool} {mellea_skills_compiler.__version__}",
        "date": report.get("checked_at"),
        "scope": report.get("package_path"),
        "result": report.get(verdict_key),
        "report": report_rel,
    }


def latest_audit_dir(package_dir: Path) -> Optional[Path]:
    """Newest ``<skill root>/audit/<dd-mm-YYYY_HH-MM-SS>`` holding a policy manifest."""
    found = []
    for d in (package_dir.resolve().parent / "audit").glob("*"):
        try:
            stamp = datetime.strptime(d.name, _AUDIT_DIR_FORMAT)
        except ValueError:
            continue
        if (d / "policy_manifest.json").exists():
            found.append((stamp, d))
    return max(found)[1] if found else None


def _certification(audit_dir: Path) -> Optional[Dict[str, Any]]:
    """Risks and certification summary from an audit directory."""
    manifest = _read_json(audit_dir / "policy_manifest.json")
    if manifest is None:
        return None
    runtime_checked = {r.get("name") for r in manifest.get("risks", [])}
    risks = [
        {
            "name": r.get("name"),
            "description": r.get("description"),
            "taxonomy": r.get("taxonomy"),
            "identified_by": r.get("source"),
            "runtime_checked": r.get("name") in runtime_checked,
        }
        for r in manifest.get("risks", []) + manifest.get("additional_risks", [])
    ]
    fixtures = _read_json(audit_dir / "fixture_results.json") or []
    fixture_counts: Dict[str, int] = {}
    for f in fixtures:
        fixture_counts[f.get("status")] = fixture_counts.get(f.get("status"), 0) + 1
    return {
        "audit_dir": audit_dir.name,
        "policy_manifest_sha256": _sha256(audit_dir / "policy_manifest.json"),
        "generated_at": manifest.get("generated_at"),
        "risk_model": manifest.get("model"),
        "risks": risks,
        "governance_actions": [
            {"id": a.get("id"), "name": a.get("name"), "source": a.get("source")}
            for a in manifest.get("governance_actions", [])
        ],
        "fixture_runs": fixture_counts,
        "reports": sorted(
            f.name
            for f in audit_dir.iterdir()
            if f.name in ("POLICY.md", "CERTIFICATION.md", "audit_trail.jsonl")
        ),
    }


# ── assembly ───────────────────────────────────────────────────────
def build_card(package_dir: Path) -> Dict[str, Any]:
    """Assemble the card dict from artifacts in ``package_dir``."""
    package_dir = package_dir.resolve()
    melleafy = _read_json(package_dir / "melleafy.json") or {}
    meta = _read_json(package_dir / "compile_metadata.json") or {}
    classification = _read_json(package_dir / "intermediate" / "classification.json") or {}
    step7 = _read_json(package_dir / "intermediate" / "step_7_report.json")
    step7b = _read_json(package_dir / "intermediate" / "step_7b_report.json")

    skill_md = package_dir / "SKILL.md"
    frontmatter: Dict[str, Any] = {}
    if skill_md.exists():
        try:
            frontmatter = parse_spec_file(skill_md).get("frontmatter", {}) or {}
        except Exception as exc:
            LOGGER.warning("Could not parse %s frontmatter: %s", skill_md, exc)

    deps: List[dict] = []
    deps_path = package_dir / "dependencies.yaml"
    if deps_path.exists():
        try:
            deps = (yaml.safe_load(deps_path.read_text()) or {}).get("dependencies", [])
        except yaml.YAMLError as exc:
            LOGGER.warning("Could not parse %s: %s", deps_path, exc)

    params = melleafy.get("pipeline_parameters", [])
    entry_sig = melleafy.get("entry_signature")
    files = list_package_files(package_dir)
    kind_counts: Dict[str, int] = {}
    for row in files:
        kind_counts[row["kind"]] = kind_counts.get(row["kind"], 0) + 1

    env_meta = meta.get("environment", {})
    compiler = meta.get("compiler", {})
    audit_dir = latest_audit_dir(package_dir)
    certification = _certification(audit_dir) if audit_dir else None

    not_assembled = [
        "what_it_does.exclusions",
        "what_it_does.adoption",
        "what_it_needs.cost",
        "what_it_touches.side_effects",
        "what_it_touches.network_access",
        "what_it_touches.machine_access",
        "known.checks",
        "known.findings.vulnerabilities",
        "known.findings.limitations",
        "known.evaluations",
        "who.maintenance_status",
    ]
    if certification is None:
        not_assembled.append("known.findings.risks (no audit directory)")
    if not frontmatter.get("license"):
        not_assembled.append("who.license (not stated in SKILL.md frontmatter)")
    if not (frontmatter.get("author") or frontmatter.get("metadata", {}).get("author")):
        not_assembled.append("who.authorship (not stated in SKILL.md frontmatter)")

    return {
        "schema": SCHEMA_VERSION,
        "what_it_does": {
            "name": frontmatter.get("name") or melleafy.get("package_name"),
            "description": frontmatter.get("description"),
            "inputs": [
                {
                    "name": p.get("name"),
                    "form": p.get("type"),
                    "required": p.get("required"),
                }
                for p in params
            ],
            "outputs": (
                [{"form": _return_type(entry_sig), "source": "entry_signature"}]
                if _return_type(entry_sig)
                else []
            ),
        },
        "what_it_needs": {
            "compatibility": {
                "mellea": env_meta.get("mellea"),
                "python": env_meta.get("python"),
                "source_runtime": melleafy.get("source_runtime"),
                "modality": melleafy.get("modality"),
                "archetype": classification.get("archetype") or melleafy.get("archetype"),
                "compiled_with": {
                    "backend": compiler.get("backend"),
                    "model": compiler.get("model"),
                },
            },
            "software_dependencies": [
                {
                    "entry_id": d.get("entry_id"),
                    "category": d.get("category"),
                    "disposition": d.get("disposition"),
                    "target": d.get("target"),
                    "prerequisites": d.get("prerequisites", []),
                }
                for d in deps
            ],
            # Variable names only, never values.
            "credentials": melleafy.get("declared_env_vars", []),
        },
        "what_it_touches": {
            "tools_and_permissions": {
                "allowed_tools": frontmatter.get("allowed-tools", []),
                "bundled_tool_implementations": [
                    {
                        "target": e.get("target"),
                        "disposition": e.get("disposition"),
                    }
                    for e in melleafy.get("categories_resolved", {})
                    .get("c6_tools", {})
                    .get("entries", [])
                ],
            },
        },
        "known": {
            # Third-party skill-checker runs only. The compiler's own lints and
            # smoke check are recorded under ``compiler_validation``.
            "checks": [],
            "findings": {
                "vulnerabilities": [],
                "risks": certification["risks"] if certification else [],
                "limitations": [],
            },
            "evaluations": [],
            # The compiler's own certification run; its fixture runs are not evaluations.
            "certification": (
                {k: v for k, v in certification.items() if k != "risks"}
                if certification
                else None
            ),
            "compiler_validation": [
                row
                for row in (
                    _check_row(
                        "val-step7-lints",
                        "mellea-skills-compiler lints",
                        "intermediate/step_7_report.json",
                        step7,
                        "overall_verdict",
                    ),
                    _check_row(
                        "val-step7b-smoke",
                        "mellea-skills-compiler smoke-check",
                        "intermediate/step_7b_report.json",
                        step7b,
                        "overall_verdict",
                    ),
                )
                if row
            ],
        },
        "who": {
            "authorship": {
                "author": frontmatter.get("author")
                or frontmatter.get("metadata", {}).get("author"),
            },
            "license": frontmatter.get("license"),
        },
        "files": {
            "version": {
                "package_sha256": package_hash(files),
                "author_version": frontmatter.get("version")
                or frontmatter.get("metadata", {}).get("version"),
                "commit": _git_commit(package_dir),
            },
            "source": {
                "producing_tool": f"mellea-skills-compiler {mellea_skills_compiler.__version__}",
                "melleafy_version": melleafy.get("melleafy_version"),
            },
            "file_list": files,
            "counts_by_kind": kind_counts,
        },
        "stamp": {
            "assembler": f"mellea-skills-compiler {mellea_skills_compiler.__version__}",
            "date": datetime.now(UTC).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "excluded_from_file_list": sorted(_EXCLUDED_FILES),
            "not_assembled": not_assembled,
        },
    }


# ── rendering ──────────────────────────────────────────────────────
def _cell(value: Any) -> str:
    text = "—" if value in (None, "", []) else str(value)
    return re.sub(r"\s+", " ", text).replace("|", "\\|")


def _table(headers: List[str], rows: List[List[Any]]) -> List[str]:
    if not rows:
        return ["_None recorded._", ""]
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out + [""]


def render_markdown(card: Dict[str, Any]) -> str:
    do, need, touch = card["what_it_does"], card["what_it_needs"], card["what_it_touches"]
    known, who, files, stamp = card["known"], card["who"], card["files"], card["stamp"]
    comp = need["compatibility"]
    L: List[str] = [f"# Skill card: {do['name']}", "", f"_Schema: {card['schema']}_", ""]

    L += ["## 1. What it does", "", f"**Description:** {_cell(do['description'])}", ""]
    L += ["### Inputs", ""]
    L += _table(
        ["Name", "Form", "Required"],
        [[i["name"], i["form"], i["required"]] for i in do["inputs"]],
    )
    L += ["### Outputs", ""]
    L += _table(["Form", "Source"], [[o["form"], o["source"]] for o in do["outputs"]])

    L += ["## 2. What it needs", "", "### Compatibility", ""]
    L += [
        f"- Mellea: {_cell(comp['mellea'])}; Python: {_cell(comp['python'])}",
        f"- Source runtime: {_cell(comp['source_runtime'])}; modality: {_cell(comp['modality'])}; archetype: {_cell(comp['archetype'])}",
        f"- Compiled with: {_cell(comp['compiled_with']['backend'])} / {_cell(comp['compiled_with']['model'])}",
        "",
        "### Software dependencies",
        "",
    ]
    L += _table(
        ["Entry", "Category", "Disposition", "Target", "Prerequisites"],
        [
            [d["entry_id"], d["category"], d["disposition"], d["target"], "; ".join(d["prerequisites"])]
            for d in need["software_dependencies"]
        ],
    )
    L += ["### Credentials (names only)", ""]
    L += _table(
        ["Variable"],
        [[c.get("name") if isinstance(c, dict) else c] for c in need["credentials"]],
    )

    tools = touch["tools_and_permissions"]
    L += ["## 3. What it touches", "", "### Tools and permissions", ""]
    L += [f"- Allowed tools (SKILL.md): {_cell(', '.join(tools['allowed_tools']))}", ""]
    L += _table(
        ["Bundled tool target", "Disposition"],
        [[t["target"], t["disposition"]] for t in tools["bundled_tool_implementations"]],
    )

    L += ["## 4. What is known about it", "", "### Checks", ""]
    L += _table(["ID", "Tool", "Date", "Scope", "Result", "Report"], [])
    L += ["### Findings: risks", ""]
    L += _table(
        ["Name", "Description", "Taxonomy", "Identified by", "Runtime-checked"],
        [
            [r["name"], r["description"], r["taxonomy"], r["identified_by"], r["runtime_checked"]]
            for r in known["findings"]["risks"]
        ],
    )
    L += ["### Evaluations", ""] + _table(["ID"], [])
    cert = known["certification"]
    if cert:
        runs = ", ".join(f"{k}={v}" for k, v in sorted(cert["fixture_runs"].items()))
        L += [
            "### Certification run (not a third-party check)",
            "",
            f"- Audit directory: `{cert['audit_dir']}`; risk model: {_cell(cert['risk_model'])}",
            f"- Fixture runs: {_cell(runs)}; governance actions: {len(cert['governance_actions'])}",
            f"- Reports: {_cell(', '.join(cert['reports']))}",
            "",
        ]
    L += ["### Compiler validation (not a third-party check)", ""]
    L += _table(
        ["ID", "Tool", "Date", "Result", "Report"],
        [
            [r["id"], r["tool"], r["date"], r["result"], r["report"]]
            for r in known["compiler_validation"]
        ],
    )

    L += [
        "## 5. Who stands behind it",
        "",
        f"- Author: {_cell(who['authorship']['author'])}",
        f"- License (as stated): {_cell(who['license'])}",
        "",
        "## 6. Which files exactly",
        "",
        f"- Package SHA-256: `{files['version']['package_sha256']}`",
        f"- Author version: {_cell(files['version']['author_version'])}; commit: {_cell(files['version']['commit'])}",
        f"- Produced by: {files['source']['producing_tool']}",
        f"- Counts by kind: {', '.join(f'{k}={v}' for k, v in sorted(files['counts_by_kind'].items()))}",
        "",
    ]
    L += _table(
        ["Path", "Size", "Kind", "SHA-256"],
        [[f["path"], f["size"], f["kind"], f["sha256"][:12]] for f in files["file_list"]],
    )

    L += [
        "## 7. About this card",
        "",
        f"- Assembler: {stamp['assembler']}",
        f"- Date: {stamp['date']}; schema: {stamp['schema_version']}",
        f"- Excluded from file list and hash: {', '.join(stamp['excluded_from_file_list'])}",
        "",
        "**Not assembled by this run:**",
        "",
    ]
    L += [f"- {item}" for item in stamp["not_assembled"]]
    return "\n".join(L) + "\n"


# ── entry points ───────────────────────────────────────────────────
def write_card(package_dir: Path) -> Dict[str, Any]:
    """Build and write ``skill_card.json`` and ``skill_card.md``; return the card."""
    card = build_card(package_dir)
    (package_dir / CARD_JSON).write_text(json.dumps(card, indent=2) + "\n")
    (package_dir / CARD_MD).write_text(render_markdown(card))
    return card


def check_card(package_dir: Path) -> Optional[str]:
    """Return None if the stored card matches the package, else a reason string."""
    stored = _read_json(package_dir / CARD_JSON)
    if stored is None:
        return f"{CARD_JSON} is missing or unreadable"
    current = package_hash(list_package_files(package_dir.resolve()))
    recorded = stored.get("files", {}).get("version", {}).get("package_sha256")
    if recorded != current:
        return "package files changed since the card was assembled"
    latest = latest_audit_dir(package_dir)
    recorded_audit = (stored.get("known", {}).get("certification") or {}).get("audit_dir")
    if (latest.name if latest else None) != recorded_audit:
        return "audit directory changed since the card was assembled"
    return None
