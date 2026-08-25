"""Tests for the mellea 0.7 grounding updates.

Covers:
  - ``_extract_forbidden_param_names`` prefers ``genstub`` on 0.7 and falls
    back to ``genslot`` on <0.7 or the static list.
  - ``.claude/data/compatibility.yaml`` is present and structured, with
    mirror pairs so nothing matches on both sides of a version boundary.
  - ``CORE_MODULES`` and ``_DOC_PAGES_FALLBACK`` carry the 0.7 additions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mellea_skills_compiler.compile import grounding


REPO_ROOT = Path(__file__).resolve().parents[3]


class TestForbiddenParamNames:
    def test_returns_real_names_from_genstub_on_0_7(self):
        names = grounding._extract_forbidden_param_names()
        assert "m" in names
        assert "context" in names
        assert "f_args" in names
        assert "f_kwargs" in names

    def test_does_not_return_deprecated_shim_warning(self, recwarn):
        """Preferring genstub avoids the DeprecationWarning that the
        smoke check now surfaces as a failure."""
        grounding._extract_forbidden_param_names()
        mellea_deprecations = [
            w for w in recwarn.list
            if issubclass(w.category, DeprecationWarning) and "mellea" in str(w.filename)
        ]
        assert not mellea_deprecations, (
            f"grounding.py emitted mellea DeprecationWarning(s): {mellea_deprecations}"
        )


class TestCompatibilityYaml:
    """The compatibility.yaml ships with 0.7 deltas and is well-formed."""

    def test_file_exists(self):
        path = REPO_ROOT / ".claude/data/compatibility.yaml"
        assert path.is_file(), (
            "compatibility.yaml is missing — Phase 1.4 of the mellea 0.7 upgrade "
            "must ship this file so the grounding phase surfaces 0.7 deltas to "
            "the LLM compile phase."
        )

    def test_path_resolves_from_any_cwd(self, tmp_path, monkeypatch):
        """Regression for review finding 6: the file must be findable when
        the compiler is invoked from outside the repo root."""
        # ``_resolve_compatibility_yaml_path`` should return the package-anchored
        # path regardless of CWD, because it walks up from __file__.
        monkeypatch.chdir(tmp_path)
        resolved = grounding._resolve_compatibility_yaml_path()
        assert resolved.exists(), (
            f"compatibility.yaml resolution broke from a foreign CWD: {resolved}"
        )
        assert resolved.samefile(REPO_ROOT / ".claude/data/compatibility.yaml")

    def test_env_override_wins(self, tmp_path, monkeypatch):
        """MELLEA_SKILLS_COMPILER_COMPATIBILITY_YAML lets tests / callers
        redirect to an alternate file."""
        alternate = tmp_path / "alt-compat.yaml"
        alternate.write_text("format_version: '1.0'\nentries: []\n")
        monkeypatch.setenv(
            "MELLEA_SKILLS_COMPILER_COMPATIBILITY_YAML", str(alternate)
        )
        assert grounding._resolve_compatibility_yaml_path() == alternate

    def test_load_warns_when_file_missing(self, tmp_path, monkeypatch, caplog):
        """Silent-degradation was the failure mode this finding fixed. A
        missing file must produce a visible WARNING, not empty output."""
        monkeypatch.setenv(
            "MELLEA_SKILLS_COMPILER_COMPATIBILITY_YAML",
            str(tmp_path / "does-not-exist.yaml"),
        )
        import logging
        with caplog.at_level(logging.WARNING):
            entries = grounding._load_compatibility_entries("0.7.0")
        assert entries == []
        assert any(
            "compatibility.yaml not found" in rec.getMessage()
            for rec in caplog.records
        ), (
            f"expected a WARNING for missing compatibility.yaml, got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_load_warns_when_yaml_is_malformed(self, tmp_path, monkeypatch, caplog):
        bad = tmp_path / "bad.yaml"
        bad.write_text(":: this: is: not [valid yaml\n")
        monkeypatch.setenv(
            "MELLEA_SKILLS_COMPILER_COMPATIBILITY_YAML", str(bad)
        )
        import logging
        with caplog.at_level(logging.WARNING):
            entries = grounding._load_compatibility_entries("0.7.0")
        assert entries == []
        assert any(
            "Failed to parse compatibility.yaml" in rec.getMessage()
            for rec in caplog.records
        )

    def test_yaml_is_well_formed_and_has_entries(self):
        import yaml
        path = REPO_ROOT / ".claude/data/compatibility.yaml"
        data = yaml.safe_load(path.read_text())
        assert "entries" in data
        assert len(data["entries"]) >= 5, "expected at least the 0.7 delta entries"

    def test_no_entry_matches_both_sides_of_0_7_boundary(self):
        """Version-conditional guidance must not fire on both <0.7 and >=0.7."""
        import yaml
        from packaging.specifiers import SpecifierSet

        path = REPO_ROOT / ".claude/data/compatibility.yaml"
        data = yaml.safe_load(path.read_text())
        for entry in data.get("entries", []):
            spec = entry.get("applies_when", "*")
            if spec == "*":
                continue
            ss = SpecifierSet(spec)
            matches_low = "0.6.0" in ss
            matches_high = "0.7.0" in ss
            assert not (matches_low and matches_high), (
                f"entry {entry.get('id')!r} matches both <0.7 and >=0.7 — "
                f"the mirror pair discipline requires each rule to fire on "
                f"only one side of the boundary"
            )

    def test_genslot_genstub_pair_is_mirrored(self):
        import yaml
        path = REPO_ROOT / ".claude/data/compatibility.yaml"
        data = yaml.safe_load(path.read_text())
        ids = {e["id"] for e in data.get("entries", [])}
        assert "genslot-genstub-rename" in ids
        assert "genslot-genstub-rename-legacy" in ids


class TestGroundingCoreModules:
    def test_core_modules_include_0_7_additions(self):
        for mod in [
            "mellea.stdlib.tools.shell",
            "mellea.stdlib.sampling.presets",
            "mellea.stdlib.requirements.python_reqs",
            "mellea.stdlib.requirements.plotting",
            "mellea.stdlib.requirements.rag",
            "mellea.stdlib.context.compactor",
        ]:
            assert mod in grounding.CORE_MODULES, (
                f"CORE_MODULES missing 0.7 addition {mod!r}. Without it, "
                f"the LLM compile phase grounds against a stale surface."
            )


class TestDocIndexFallback:
    def test_removes_stale_guide_paths(self):
        for stale in ["/guide/backends-and-configuration", "/guide/tools-and-agents"]:
            assert stale not in grounding._DOC_PAGES_FALLBACK, (
                f"doc index still lists Mintlify-era path {stale!r}; refresh "
                f"the snapshot from the live Docusaurus site."
            )

    def test_has_docusaurus_era_additions(self):
        for present in [
            "/observability/logging",
            "/observability/telemetry",
            "/integrations/mcp",
            "/how-to/safety-guardrails",
            "/tutorials/06-rag-with-mellea",
        ]:
            assert present in grounding._DOC_PAGES_FALLBACK, (
                f"doc index missing 0.7 Docusaurus path {present!r}"
            )
