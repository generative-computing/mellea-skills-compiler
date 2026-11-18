"""Tests for deterministic skill-card assembly (stage 1)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mellea_skills_compiler.cli import app
from mellea_skills_compiler.compile import skill_card


def _make_package(tmp_path: Path) -> Path:
    pkg = tmp_path / "demo_mellea"
    (pkg / "intermediate").mkdir(parents=True)
    (pkg / "fixtures").mkdir()
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "x.pyc").write_bytes(b"junk")
    (pkg / "pipeline.py").write_text("print('hi')\n")
    (pkg / "fixtures" / "case.py").write_text("X = 1\n")
    (pkg / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Does a demo.\nallowed-tools: Bash, Read\n"
        "license: MIT\n---\n\n# Demo\n"
    )
    (pkg / "dependencies.yaml").write_text(
        "dependencies:\n  - entry_id: dep_001\n    category: c6_tools\n"
        "    disposition: stub\n    target: main.py:f\n    prerequisites: [git]\n"
    )
    (pkg / "melleafy.json").write_text(
        json.dumps(
            {
                "package_name": "demo_mellea",
                "entry_signature": "run_pipeline(x: str) -> Report",
                "pipeline_parameters": [{"name": "x", "type": "str", "required": True}],
                "declared_env_vars": ["API_KEY"],
                "categories_resolved": {"c6_tools": {"entries": [{"target": "main.py:f", "disposition": "stub"}]}},
            }
        )
    )
    (pkg / "intermediate" / "step_7_report.json").write_text(
        json.dumps({"checked_at": "2026-01-01T00:00:00Z", "package_path": "p", "overall_verdict": "pass"})
    )
    return pkg


class TestBuildCard:
    def test_maps_package_artifacts(self, tmp_path):
        card = skill_card.build_card(_make_package(tmp_path))
        assert card["what_it_does"]["name"] == "demo"
        assert card["what_it_does"]["inputs"][0] == {"name": "x", "form": "str", "required": True}
        assert card["what_it_does"]["outputs"][0]["form"] == "Report"
        assert card["what_it_needs"]["credentials"] == ["API_KEY"]
        assert card["what_it_needs"]["software_dependencies"][0]["prerequisites"] == ["git"]
        assert card["what_it_touches"]["tools_and_permissions"]["allowed_tools"] == ["Bash", "Read"]
        assert card["who"]["license"] == "MIT"

    def test_compiler_validation_not_reported_as_checks(self, tmp_path):
        card = skill_card.build_card(_make_package(tmp_path))
        assert card["known"]["checks"] == []
        assert card["known"]["compiler_validation"][0]["result"] == "pass"

    def test_unfillable_sections_are_declared_not_silently_empty(self, tmp_path):
        card = skill_card.build_card(_make_package(tmp_path))
        joined = " ".join(card["stamp"]["not_assembled"])
        assert "risks" in joined and "evaluations" in joined
        assert "who.authorship" in joined  # no author in frontmatter

    def test_file_list_excludes_pycache_and_card_files(self, tmp_path):
        pkg = _make_package(tmp_path)
        skill_card.write_card(pkg)
        paths = {f["path"] for f in skill_card.build_card(pkg)["files"]["file_list"]}
        assert "pipeline.py" in paths
        assert not any("pycache" in p for p in paths)
        assert skill_card.CARD_JSON not in paths and skill_card.CARD_MD not in paths


def _add_audit(pkg: Path, name: str, risk: str = "harm") -> Path:
    audit = pkg.parent / "audit" / name
    audit.mkdir(parents=True)
    (audit / "policy_manifest.json").write_text(
        json.dumps(
            {
                "model": "risk-model",
                "generated_at": "2026-01-02T00:00:00Z",
                "risks": [{"name": risk, "description": "d", "source": "ai-atlas-nexus", "taxonomy": "t"}],
                "additional_risks": [{"name": "extra", "description": "e", "source": "ai-atlas-nexus", "taxonomy": "t"}],
                "governance_actions": [{"id": "g1", "name": "act", "source": "nist"}],
            }
        )
    )
    (audit / "fixture_results.json").write_text(json.dumps([{"status": "success"}, {"status": "blocked"}]))
    (audit / "CERTIFICATION.md").write_text("report")
    return audit


class TestAuditRefresh:
    def test_risks_come_from_latest_audit(self, tmp_path):
        pkg = _make_package(tmp_path)
        _add_audit(pkg, "31-12-2025_10-00-00", risk="old")
        _add_audit(pkg, "01-02-2026_09-00-00", risk="new")  # later date, earlier string
        card = skill_card.build_card(pkg)
        risks = {r["name"]: r for r in card["known"]["findings"]["risks"]}
        assert set(risks) == {"new", "extra"}
        assert risks["new"]["runtime_checked"] and not risks["extra"]["runtime_checked"]
        cert = card["known"]["certification"]
        assert cert["audit_dir"] == "01-02-2026_09-00-00"
        assert cert["fixture_runs"] == {"success": 1, "blocked": 1}
        assert cert["reports"] == ["CERTIFICATION.md"]
        assert not any("risks" in n for n in card["stamp"]["not_assembled"])

    def test_without_audit_risks_are_declared_unassembled(self, tmp_path):
        card = skill_card.build_card(_make_package(tmp_path))
        assert card["known"]["certification"] is None
        assert any("known.findings.risks" in n for n in card["stamp"]["not_assembled"])

    def test_audit_does_not_change_package_hash(self, tmp_path):
        pkg = _make_package(tmp_path)
        before = skill_card.build_card(pkg)["files"]["version"]["package_sha256"]
        _add_audit(pkg, "01-02-2026_09-00-00")
        assert skill_card.build_card(pkg)["files"]["version"]["package_sha256"] == before

    def test_check_detects_new_audit(self, tmp_path):
        pkg = _make_package(tmp_path)
        skill_card.write_card(pkg)
        assert skill_card.check_card(pkg) is None
        _add_audit(pkg, "01-02-2026_09-00-00")
        assert "audit" in skill_card.check_card(pkg)
        skill_card.write_card(pkg)
        assert skill_card.check_card(pkg) is None

    def test_markdown_lists_risks(self, tmp_path):
        pkg = _make_package(tmp_path)
        _add_audit(pkg, "01-02-2026_09-00-00")
        md = skill_card.render_markdown(skill_card.build_card(pkg))
        assert "| harm |" in md and "01-02-2026_09-00-00" in md


class TestHashStability:
    def test_hash_unchanged_by_card_regeneration(self, tmp_path):
        pkg = _make_package(tmp_path)
        h1 = skill_card.write_card(pkg)["files"]["version"]["package_sha256"]
        h2 = skill_card.write_card(pkg)["files"]["version"]["package_sha256"]
        assert h1 == h2

    def test_check_detects_stale_card(self, tmp_path):
        pkg = _make_package(tmp_path)
        assert skill_card.check_card(pkg) is not None  # missing
        skill_card.write_card(pkg)
        assert skill_card.check_card(pkg) is None
        (pkg / "pipeline.py").write_text("print('changed')\n")
        assert "changed" in skill_card.check_card(pkg)


class TestCli:
    def test_card_command_writes_and_checks(self, tmp_path):
        pkg = _make_package(tmp_path)
        runner = CliRunner()
        assert runner.invoke(app, ["card", str(pkg)]).exit_code == 0
        assert (pkg / skill_card.CARD_MD).read_text().startswith("# Skill card: demo")
        assert runner.invoke(app, ["card", str(pkg), "--check"]).exit_code == 0
        (pkg / "pipeline.py").write_text("changed\n")
        assert runner.invoke(app, ["card", str(pkg), "--check"]).exit_code == 1

    def test_card_command_rejects_non_package(self, tmp_path):
        assert CliRunner().invoke(app, ["card", str(tmp_path)]).exit_code == 1
