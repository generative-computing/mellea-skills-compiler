"""Tests that Guardian plugin registration is injected into generated entry points
when has_policy_manifest=True."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mellea_skills_compiler.export.exporter import (
    Invocation,
    ParsedSignature,
    run_export,
)
from mellea_skills_compiler.export.targets.claude_code import (
    _guardian_inline_snippet,
    _render_run_sh,
)
from mellea_skills_compiler.export.targets.langgraph import (
    _guardian_block,
    _render_graph_py,
)
from mellea_skills_compiler.export.targets.mcp import _render_server_py
from mellea_skills_compiler.export.targets.pi import (
    _guardian_inline_snippet as _pi_guardian_inline_snippet,
    _render_run_sh as _pi_render_run_sh,
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
        assert "GuardianPluginFactory" in result

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
        assert "GuardianPluginFactory" not in result
        assert "PolicyManifest" not in result

    def test_guardian_block_before_mcpserver_instantiation(self):
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
        assert result.index("GuardianPluginFactory") < result.index("mcp = MCPServer(")


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
        assert "GuardianPluginFactory" in result

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
        assert "GuardianPluginFactory" not in result

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
        assert result.index("GuardianPluginFactory") < result.index("_builder = StateGraph")


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
        assert "GuardianPluginFactory" in result

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
        assert "GuardianPluginFactory" in result

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
        assert "GuardianPluginFactory" in result

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
        assert "GuardianPluginFactory" not in result

    def test_audit_plugin_bound_to_variable(self):
        """Verify audit_plugin is initialized and checked in finally block.
        The audit_plugin variable is initialized to None and conditionally checked
        before deregistration in the finally block."""
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
        # Verify audit_plugin is initialized
        assert "audit_plugin = None" in result
        # Verify AuditTrailPlugin is created (may or may not be assigned to audit_plugin)
        assert "AuditTrailPlugin(" in result
        # Verify the finally block safely checks audit_plugin before deregistering
        assert "if audit_plugin is not None:" in result
        assert "audit_plugin.deregister()" in result

    def test_generated_python_compiles(self):
        """Regression: the embedded `python -c` body must be valid Python. The old
        finally block referenced an undefined `audit_plugin`; guard against any
        recurrence by compiling the extracted body."""
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
        # Extract the body between `exec python -c "` and the closing `" -- "$@"`.
        start = result.index('exec python -c "') + len('exec python -c "')
        end = result.index('" -- "$@"')
        body = result[start:end]
        compile(body, "<generated run.sh body>", "exec")


class TestPiGuardianInjection:
    def test_guardian_snippet_present_synchronous_oneshot(self):
        result = _pi_render_run_sh(
            modality="synchronous_oneshot",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            has_policy_manifest=True,
        )
        assert "GuardianPluginFactory" in result

    def test_guardian_snippet_present_streaming(self):
        result = _pi_render_run_sh(
            modality="streaming",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            has_policy_manifest=True,
        )
        assert "GuardianPluginFactory" in result

    def test_guardian_snippet_present_conversational_session(self):
        result = _pi_render_run_sh(
            modality="conversational_session",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            has_policy_manifest=True,
        )
        assert "GuardianPluginFactory" in result

    def test_guardian_snippet_absent_without_manifest(self):
        result = _pi_render_run_sh(
            modality="synchronous_oneshot",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            has_policy_manifest=False,
        )
        assert "GuardianPluginFactory" not in result

    def test_generated_python_compiles(self):
        result = _pi_render_run_sh(
            modality="synchronous_oneshot",
            package_name="my_skill",
            entry_module="pipeline",
            entry_function="run_pipeline",
            pattern="no_args",
            params=[],
            export_version="0.1.0",
            has_policy_manifest=True,
        )
        start = result.index('exec python -c "') + len('exec python -c "')
        end = result.index('" -- "$@"')
        body = result[start:end]
        compile(body, "<generated run.sh body>", "exec")


class TestAuditWritabilityProbe:
    """Each target's generated entry point must probe the audit dir for write access
    and fail loudly before registering the audit plugin."""

    def test_audit_probe_in_generated_entry_point_mcp(self):
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
        assert "write_probe" in result
        assert "not writable" in result
        assert "SystemExit" in result
        assert result.index("not writable") < result.index("AuditTrailPlugin(log_path=")

    def test_audit_probe_in_generated_entry_point_langgraph(self):
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
        assert "write_probe" in result
        assert "not writable" in result
        assert "SystemExit" in result
        assert result.index("not writable") < result.index("AuditTrailPlugin(log_path=")

    def test_audit_probe_in_generated_entry_point_claude_code(self):
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
        assert "write_probe" in result
        assert "not writable" in result
        assert "sys.exit(1)" in result
        assert result.index("not writable") < result.index(
            "audit_plugin: AuditTrailPlugin = AuditTrailPlugin("
        )

    def test_claude_code_probe_uses_json_envelope_not_systemexit(self):
        """The claude-code probe runs inside a python -c string with an existing
        try/except Exception wrapper further down; SystemExit would bypass that
        wrapper's JSON envelope contract, so the probe must print the envelope and
        sys.exit(1) directly instead of raising."""
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
        start = result.index('exec python -c "') + len('exec python -c "')
        end = result.index('" -- "$@"')
        body = result[start:end]
        assert '"' not in body
        compile(body, "<generated run.sh body>", "exec")
        assert "raise SystemExit" not in body


# ---------------------------------------------------------------------------
# Integration tests — run_export() with a certified skill
# ---------------------------------------------------------------------------

_WEATHER_SKILL = Path(__file__).parents[3] / "examples/weather/weather_mellea"
_STUB_MANIFEST = {
    "use_case": "test",
    "taxonomy": "test",
    "risks": [],
    "additional_risks": [],
}


@pytest.fixture()
def certified_skill_dir(tmp_path):
    """Copy the weather skill into a temp dir with a stub policy_manifest.json in an audit_* dir."""
    skill_copy = tmp_path / "weather_mellea"
    shutil.copytree(_WEATHER_SKILL, skill_copy)
    # Create audit directory in the parent of the skill directory (where exporter looks for it)
    # Exporter searches for: <skill_root.parent>/audit/*/policy_manifest.json
    audit_parent = tmp_path / "audit"
    audit_dir = audit_parent / "audit_test"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "policy_manifest.json").write_text(json.dumps(_STUB_MANIFEST))
    return skill_copy


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code", "pi"])
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

    # Simulate what the generated entry point does at runtime: .register()
    # writes a dummy JSONL via the audit dir convention.
    audit_dir = out_path / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "runtime_audit.jsonl").write_text(
        json.dumps({"event": "guardian_registered"}) + "\n"
    )

    audit_log = out_path / "audit" / "runtime_audit.jsonl"
    assert audit_log.exists(), f"audit/runtime_audit.jsonl not found in {target} bundle"
    assert audit_log.stat().st_size > 0, "audit/runtime_audit.jsonl is empty"


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code", "pi"])
def test_run_export_reverse_manifest_guardian_configured(
    certified_skill_dir, tmp_path, target
):
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


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code", "pi"])
def test_run_export_notes_contains_guardian_section(
    certified_skill_dir, tmp_path, target
):
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


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code", "pi"])
def test_export_notes_audit_path_per_target(certified_skill_dir, tmp_path, target):
    out_path = tmp_path / f"weather_mellea-{target}"
    inv = Invocation(
        package_path=certified_skill_dir,
        target=target,
        out_path=out_path,
        force=True,
    )
    run_export(inv)

    notes = (out_path / "EXPORT_NOTES.md").read_text()
    assert "mkdir -p" in notes
    assert "fail at startup" in notes
    if target in ("claude-code", "pi"):
        assert "ADAPTER_DIR" in notes
    else:
        assert "<bundle_dir>/audit/runtime_audit.jsonl" in notes


# ---------------------------------------------------------------------------
# Enforce mode tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code", "pi"])
def test_enforce_flag_generates_enforce_plugin(certified_skill_dir, tmp_path, target):
    out_path = tmp_path / f"weather_mellea-{target}"
    inv = Invocation(
        package_path=certified_skill_dir,
        target=target,
        out_path=out_path,
        force=True,
        enforce=True,
    )
    run_export(inv)

    entry_files = {
        "mcp": out_path / "server.py",
        "langgraph": out_path / "graph.py",
        "claude-code": out_path / "scripts" / "run.sh",
        "pi": out_path / "scripts" / "run.sh",
    }
    content = entry_files[target].read_text()
    assert "GuardianPluginFactory" in content


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code", "pi"])
def test_enforce_flag_reverse_manifest(certified_skill_dir, tmp_path, target):
    out_path = tmp_path / f"weather_mellea-{target}"
    inv = Invocation(
        package_path=certified_skill_dir,
        target=target,
        out_path=out_path,
        force=True,
        enforce=True,
    )
    run_export(inv)

    reverse = json.loads((out_path / "melleafy-export.json").read_text())
    assert reverse["guardian_configured"] == "enforce"


@pytest.mark.parametrize("target", ["mcp", "langgraph", "claude-code", "pi"])
def test_enforce_flag_export_notes(certified_skill_dir, tmp_path, target):
    out_path = tmp_path / f"weather_mellea-{target}"
    inv = Invocation(
        package_path=certified_skill_dir,
        target=target,
        out_path=out_path,
        force=True,
        enforce=True,
    )
    run_export(inv)

    notes = (out_path / "EXPORT_NOTES.md").read_text()
    assert "enforce" in notes
    assert "PluginViolationError" in notes


# ---------------------------------------------------------------------------
# GuardianEnforcePlugin runtime blocking test
# ---------------------------------------------------------------------------


def test_guardian_enforce_plugin_blocks_on_risk():
    """GuardianEnforcePlugin raises PluginViolationError via Mellea's plugin manager when a risk is flagged."""
    import asyncio
    from unittest.mock import MagicMock

    from mellea.plugins import HookType, PluginViolationError, register, unregister
    from mellea.plugins.manager import invoke_hook

    from mellea_skills_compiler.enums import GuardianScore, HookStage
    from mellea_skills_compiler.models import GuardianVerdict, NexusRisk, PolicyManifest
    from mellea_skills_compiler.plugins.guardian import GuardianEnforcePlugin

    risk = NexusRisk(
        name="harm",
        description="harm description",
        guardian_prompt="harm",
        source="test",
        is_native=True,
    )
    manifest = PolicyManifest(
        use_case="test",
        taxonomy="test",
        risks=[risk],
        additional_risks=[],
    )
    plugin = GuardianEnforcePlugin(manifest.risks)
    plugin.register()

    yes_verdict = GuardianVerdict(
        risk="harm",
        label=GuardianScore.YES,
        raw_output="<score>yes</score>",
        hook_stage=HookStage.POST,
    )

    payload = MagicMock()
    payload.model_output = MagicMock()
    payload.model_output._action = MagicMock()
    payload.model_output.value = "flagged content"
    payload.prompt = [{"role": "user", "content": "test"}]

    try:
        with pytest.raises(PluginViolationError) as exc_info:
            with patch(
                "mellea_skills_compiler.plugins.guardian._run_guardian_post_checks",
                return_value=[yes_verdict],
            ):
                asyncio.run(invoke_hook(HookType.GENERATION_POST_CALL, payload))

        assert exc_info.value.code == "guardian_output_risk_detected"
    finally:
        unregister(plugin)


# ---------------------------------------------------------------------------
# Startup fails loudly when the audit directory isn't writable
# ---------------------------------------------------------------------------

_RUNNING_AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


@pytest.mark.skipif(_RUNNING_AS_ROOT, reason="chmod-based write denial is a no-op for root")
class TestStartupFailsWhenAuditDirNotWritable:
    """Exercises the actual probe logic (mkdir/touch/unlink/except) emitted into each
    target's entry point, against a real unwritable directory — without importing the
    heavier mcp/langgraph/mellea runtime the full entry point would need."""

    def _make_unwritable_parent(self, tmp_path):
        parent = tmp_path / "bundle"
        parent.mkdir()
        os.chmod(parent, 0o500)
        return parent

    def test_mcp_probe_exits_when_not_writable(self, tmp_path):
        parent = self._make_unwritable_parent(tmp_path)
        script = (
            "from pathlib import Path\n"
            f"_audit_log = Path({str(parent)!r}) / 'audit' / 'runtime_audit.jsonl'\n"
            "_audit_dir = _audit_log.parent\n"
            "try:\n"
            "    _audit_dir.mkdir(parents=True, exist_ok=True)\n"
            "    _probe = _audit_dir / '.write_probe'\n"
            "    _probe.touch()\n"
            "    _probe.unlink()\n"
            "except OSError as _e:\n"
            "    raise SystemExit(\n"
            "        f'[guardian] audit trail directory {_audit_dir} is not writable: {_e}. '\n"
            "        'Grant write access (see EXPORT_NOTES.md) or remove policy_manifest.json to disable Guardian.'\n"
            "    )\n"
        )
        try:
            with pytest.raises(SystemExit) as exc_info:
                exec(compile(script, "<probe>", "exec"), {})
            assert "not writable" in str(exc_info.value)
        finally:
            os.chmod(parent, 0o700)

    def test_claude_code_probe_exits_with_json_envelope(self, tmp_path, capsys):
        parent = self._make_unwritable_parent(tmp_path)
        script = (
            "import json, sys\n"
            "from pathlib import Path\n"
            f"_audit_dir = Path({str(parent)!r}) / 'audit'\n"
            "try:\n"
            "    _audit_dir.mkdir(parents=True, exist_ok=True)\n"
            "    _probe = _audit_dir / '.write_probe'\n"
            "    _probe.touch()\n"
            "    _probe.unlink()\n"
            "except OSError as _e:\n"
            "    print(json.dumps({'status': 'error', 'message': f'[guardian] audit dir {_audit_dir} not writable: {_e}'}), file=sys.stderr)\n"
            "    sys.exit(1)\n"
        )
        try:
            with pytest.raises(SystemExit) as exc_info:
                exec(compile(script, "<probe>", "exec"), {})
            assert exc_info.value.code == 1
            stderr = capsys.readouterr().err
            envelope = json.loads(stderr)
            assert envelope["status"] == "error"
            assert "not writable" in envelope["message"]
        finally:
            os.chmod(parent, 0o700)

    def test_probe_succeeds_when_writable(self, tmp_path):
        """Sanity check: the probe only fails when the directory is genuinely unwritable."""
        parent = tmp_path / "bundle"
        parent.mkdir()
        script = (
            "from pathlib import Path\n"
            f"_audit_log = Path({str(parent)!r}) / 'audit' / 'runtime_audit.jsonl'\n"
            "_audit_dir = _audit_log.parent\n"
            "_audit_dir.mkdir(parents=True, exist_ok=True)\n"
            "_probe = _audit_dir / '.write_probe'\n"
            "_probe.touch()\n"
            "_probe.unlink()\n"
        )
        exec(compile(script, "<probe>", "exec"), {})
        assert (parent / "audit").is_dir()
