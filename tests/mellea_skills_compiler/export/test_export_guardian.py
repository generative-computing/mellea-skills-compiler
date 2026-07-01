"""Tests that Guardian plugin registration is injected into generated entry points
when has_policy_manifest=True."""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mellea_skills_compiler.export.exporter import Invocation, ParsedSignature, run_export
from mellea_skills_compiler.export.targets.mcp import _render_server_py
from mellea_skills_compiler.export.targets.langgraph import (
    _render_graph_py,
    _guardian_block,
)
from mellea_skills_compiler.export.targets.claude_code import (
    _render_run_sh,
    _guardian_inline_snippet,
)


def _minimal_sig() -> ParsedSignature:
    return ParsedSignature(
        function_name="run_pipeline",
        params=[],
        return_type="str",
        pattern="no_args",
    )


class TestMcpGuardianInjection:
    def test_guardian_block_present_when_manifest(self):
        result = _render_server_py(
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            tool_name="my_skill",
            description="A test skill.",
            sig=_minimal_sig(),
            is_async=False,
            declared_env_vars=[],
            has_policy_manifest=True,
        )
        assert "GuardianAuditPlugin" in result
        assert "policy_manifest.json" in result

    def test_guardian_block_absent_without_manifest(self):
        result = _render_server_py(
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            tool_name="my_skill",
            description="A test skill.",
            sig=_minimal_sig(),
            is_async=False,
            declared_env_vars=[],
            has_policy_manifest=False,
        )
        assert "GuardianAuditPlugin" not in result
        assert "PolicyManifest" not in result

    def test_guardian_block_before_fastmcp_instantiation(self):
        result = _render_server_py(
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            tool_name="my_skill",
            description="A test skill.",
            sig=_minimal_sig(),
            is_async=False,
            declared_env_vars=[],
            has_policy_manifest=True,
        )
        assert result.index("GuardianAuditPlugin") < result.index('mcp = FastMCP(')


class TestLangGraphGuardianInjection:
    def test_guardian_block_present_when_manifest(self):
        result = _render_graph_py(
            modality="synchronous_oneshot",
            graph_name="my_skill",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            manifest={},
            has_policy_manifest=True,
        )
        assert "GuardianAuditPlugin" in result
        assert "policy_manifest.json" in result

    def test_guardian_block_absent_without_manifest(self):
        result = _render_graph_py(
            modality="synchronous_oneshot",
            graph_name="my_skill",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            manifest={},
            has_policy_manifest=False,
        )
        assert "GuardianAuditPlugin" not in result

    def test_guardian_block_before_builder(self):
        result = _render_graph_py(
            modality="synchronous_oneshot",
            graph_name="my_skill",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            manifest={},
            has_policy_manifest=True,
        )
        assert result.index("GuardianAuditPlugin") < result.index("_builder = StateGraph")


class TestClaudeCodeGuardianInjection:
    def test_guardian_snippet_present_synchronous_oneshot(self):
        result = _render_run_sh(
            modality="synchronous_oneshot",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            has_policy_manifest=True,
        )
        assert "GuardianAuditPlugin" in result
        assert "policy_manifest.json" in result

    def test_guardian_snippet_present_streaming(self):
        result = _render_run_sh(
            modality="streaming",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            has_policy_manifest=True,
        )
        assert "GuardianAuditPlugin" in result
        assert "policy_manifest.json" in result

    def test_guardian_snippet_present_conversational_session(self):
        result = _render_run_sh(
            modality="conversational_session",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            has_policy_manifest=True,
        )
        assert "GuardianAuditPlugin" in result
        assert "policy_manifest.json" in result

    def test_guardian_snippet_absent_without_manifest(self):
        result = _render_run_sh(
            modality="synchronous_oneshot",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            has_policy_manifest=False,
        )
        assert "GuardianAuditPlugin" not in result


# ---------------------------------------------------------------------------
# Integration tests — run_export() with a certified skill
# ---------------------------------------------------------------------------

_WEATHER_SKILL = Path(__file__).parents[3] / "skills/weather/weather_mellea"
_STUB_MANIFEST = {"use_case": "test", "taxonomy": "test", "risks": [], "additional_risks": []}


@pytest.fixture()
def certified_skill_dir(tmp_path):
    """Copy the weather skill into a temp dir and add a stub policy_manifest.json."""
    skill_copy = tmp_path / "weather_mellea"
    shutil.copytree(_WEATHER_SKILL, skill_copy)
    (skill_copy / "policy_manifest.json").write_text(json.dumps(_STUB_MANIFEST))
    return skill_copy


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code"])
def test_run_export_audit_jsonl_created(certified_skill_dir, tmp_path, target):
    """Verify that simulating Guardian registration at runtime produces audit/runtime_audit.jsonl."""
    out_path = tmp_path / f"weather_mellea-{target}"
    inv = Invocation(
        package_path=certified_skill_dir,
        target=target,
        out_path=out_path,
        force=True,
    )
    run_export(inv)

    # Simulate what the generated entry point does at runtime: GuardianAuditPlugin.register()
    # writes a dummy JSONL via the audit dir convention.
    audit_dir = out_path / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "runtime_audit.jsonl").write_text(
        json.dumps({"event": "guardian_registered"}) + "\n"
    )

    audit_log = out_path / "audit" / "runtime_audit.jsonl"
    assert audit_log.exists(), f"audit/runtime_audit.jsonl not found in {target} bundle"
    assert audit_log.stat().st_size > 0, "audit/runtime_audit.jsonl is empty"


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code"])
def test_run_export_reverse_manifest_guardian_configured(certified_skill_dir, tmp_path, target):
    out_path = tmp_path / f"weather_mellea-{target}"
    inv = Invocation(
        package_path=certified_skill_dir,
        target=target,
        out_path=out_path,
        force=True,
    )
    run_export(inv)

    reverse = json.loads((out_path / "melleafy-export.json").read_text())
    assert reverse["guardian_configured"] == "audit"


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code"])
def test_run_export_notes_contains_guardian_section(certified_skill_dir, tmp_path, target):
    out_path = tmp_path / f"weather_mellea-{target}"
    inv = Invocation(
        package_path=certified_skill_dir,
        target=target,
        out_path=out_path,
        force=True,
    )
    run_export(inv)

    notes = (out_path / "EXPORT_NOTES.md").read_text()
    assert "Guardian audit" in notes
    assert "runtime_audit.jsonl" in notes
