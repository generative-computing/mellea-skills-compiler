"""Unit tests for mellea_skills_compiler.guardian.audit_trail module."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mellea_skills_compiler.models import PolicyManifest
from mellea_skills_compiler.plugins.audit import AuditTrailPlugin, GuardianAuditPlugin


@pytest.fixture
def temp_audit_file():
    """Create a temporary audit trail file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def guardian_plugin():
    """Create a GuardianAuditPlugin instance."""
    from mellea_skills_compiler.enums import GovernanceTaxonomy
    from mellea_skills_compiler.models import NexusRisk

    return GuardianAuditPlugin(
        manifest=PolicyManifest(
            taxonomy="granite-guardian",
            risks=[
                NexusRisk(
                    name="jailbreak",
                    description="Jailbreak attempts",
                    guardian_prompt="jailbreak",
                    source="ai-atlas-nexus",
                    is_native=True,
                    taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
                ),
                NexusRisk(
                    name="harm",
                    description="Harmful content",
                    guardian_prompt="harm",
                    source="ai-atlas-nexus",
                    is_native=True,
                    taxonomy=GovernanceTaxonomy.IBM_GRANITE_GUARDIAN,
                ),
            ],
            additional_risks=None,
            use_case="test_use_case",
        )
    )


@pytest.fixture
def audit_plugin(temp_audit_file, guardian_plugin):
    """Create an AuditTrailPlugin instance."""
    return AuditTrailPlugin(
        log_path=temp_audit_file,
        guardian_plugin=guardian_plugin,
    )


class TestAuditTrailPluginInit:
    """Test cases for AuditTrailPlugin initialization."""

    def test_init_with_defaults(self, temp_audit_file, audit_plugin, guardian_plugin):
        """Test plugin initialization with default values."""

        assert audit_plugin.log_path == temp_audit_file
        assert audit_plugin.policy_id == "nexus-granite-guardian"
        assert audit_plugin.guardian_plugin is guardian_plugin
        assert audit_plugin._entries == []

    def test_init_with_guardian_ref(self, temp_audit_file):
        """Test plugin initialization with Guardian reference."""
        guardian_mock = MagicMock()
        plugin = AuditTrailPlugin(
            log_path=temp_audit_file,
            guardian_plugin=guardian_mock,
        )

        assert plugin.guardian_plugin is guardian_mock


class TestAuditTrailWrite:
    """Test cases for _write method."""

    def test_write_entry(self, audit_plugin, temp_audit_file):
        """Test writing an audit entry."""
        entry = {"hook": "test_hook", "data": "test_data"}

        audit_plugin._write(entry)

        # Check that entry was added to internal list
        assert len(audit_plugin._entries) == 1
        assert audit_plugin._entries[0]["hook"] == "test_hook"
        assert "timestamp" in audit_plugin._entries[0]

        # Check that entry was written to file
        with open(temp_audit_file) as f:
            lines = f.readlines()
            assert len(lines) == 1
            written_entry = json.loads(lines[0])
            assert written_entry["hook"] == "test_hook"
            assert written_entry["data"] == "test_data"

    def test_write_entry_with_policy_id(self, audit_plugin, temp_audit_file):
        """Test that policy_id is added to entries when set."""
        entry = {"hook": "test_hook"}

        audit_plugin._write(entry)

        with open(temp_audit_file) as f:
            written_entry = json.loads(f.read())
            assert written_entry["policy_id"] == "nexus-granite-guardian"

    def test_write_multiple_entries(self, audit_plugin, temp_audit_file):
        """Test writing multiple entries."""
        audit_plugin._write({"hook": "hook1"})
        audit_plugin._write({"hook": "hook2"})
        audit_plugin._write({"hook": "hook3"})

        assert len(audit_plugin._entries) == 3

        with open(temp_audit_file) as f:
            lines = f.readlines()
            assert len(lines) == 3


class TestAuditTrailHooks:
    """Test cases for audit trail hooks."""

    def test_log_pre_call(self, audit_plugin):
        """Test generation_pre_call hook."""
        import asyncio

        # Mock action with format_for_llm method
        action = MagicMock()
        llm_format = MagicMock()
        llm_format.args = {"arg1": "value1", "arg2": "value2"}
        action.format_for_llm.return_value = llm_format

        payload = MagicMock()
        payload.prompt = "Test prompt"
        payload.action = action
        payload.session_id = "session-1"
        payload.request_id = "req-1"
        payload.model_options = {"temperature": 0.7}

        ctx = MagicMock()

        asyncio.run(audit_plugin.log_pre_call(payload, ctx))

        assert len(audit_plugin._entries) == 1
        entry = audit_plugin._entries[0]
        assert entry["hook"] == "generation_pre_call"
        assert entry["session_id"] == "session-1"
        assert entry["request_id"] == "req-1"
        assert "input_preview" in entry

    def test_log_post_call_without_risk(self, audit_plugin):
        """Test generation_post_call hook without risk detection."""
        from mellea_skills_compiler.models import GuardianVerdict

        # Add verdicts to guardian plugin
        audit_plugin.guardian_plugin.all_verdicts = [
            GuardianVerdict(risk="jailbreak", label="No", raw_output="<score>no</score>"),
            GuardianVerdict(risk="harm", label="No", raw_output="<score>no</score>"),
        ]

        payload = MagicMock()
        payload.model_output = MagicMock(value="Test output")
        payload.latency_ms = 150
        payload.session_id = "session-1"
        payload.request_id = "req-1"

        ctx = MagicMock()

        asyncio.run(audit_plugin.log_post_call(payload, ctx))

        assert len(audit_plugin._entries) == 1
        entry = audit_plugin._entries[0]
        assert entry["hook"] == "generation_post_call"
        assert entry["latency_ms"] == 150
        assert entry["risk_detected"] is False
        assert len(entry["guardian_verdicts"]) == 2

    def test_log_post_call_with_risk(self, audit_plugin):
        """Test generation_post_call hook with risk detection."""
        from mellea_skills_compiler.models import GuardianVerdict

        # Add verdicts to guardian plugin with one risk detected
        audit_plugin.guardian_plugin.all_verdicts = [
            GuardianVerdict(risk="jailbreak", label="Yes", raw_output="<score>yes</score>"),
            GuardianVerdict(risk="harm", label="No", raw_output="<score>no</score>"),
        ]

        payload = MagicMock()
        payload.model_output = MagicMock(value="Test output")
        payload.latency_ms = 200
        payload.session_id = "session-1"
        payload.request_id = "req-1"

        ctx = MagicMock()

        asyncio.run(audit_plugin.log_post_call(payload, ctx))

        entry = audit_plugin._entries[0]
        assert entry["risk_detected"] is True

    def test_log_component_start(self, audit_plugin):
        """Test component_pre_execute hook."""
        payload = MagicMock()
        payload.session_id = "session-1"
        payload.component_type = "TestComponent"

        ctx = MagicMock()

        asyncio.run(audit_plugin.log_component_start(payload, ctx))

        entry = audit_plugin._entries[0]
        assert entry["hook"] == "component_pre_execute"
        assert entry["session_id"] == "session-1"
        assert entry["component_type"] == "TestComponent"

    def test_log_component_success(self, audit_plugin):
        """Test component_post_success hook."""
        payload = MagicMock()
        payload.session_id = "session-1"
        payload.component_type = "TestComponent"
        payload.latency_ms = 100

        ctx = MagicMock()

        asyncio.run(audit_plugin.log_component_success(payload, ctx))

        entry = audit_plugin._entries[0]
        assert entry["hook"] == "component_post_success"
        assert entry["session_id"] == "session-1"
        assert entry["latency_ms"] == 100

    def test_log_component_error(self, audit_plugin):
        """Test component_post_error hook."""
        payload = MagicMock()
        payload.session_id = "session-1"
        payload.component_type = "TestComponent"
        payload.error = "Test error message"

        ctx = MagicMock()

        asyncio.run(audit_plugin.log_component_error(payload, ctx))

        entry = audit_plugin._entries[0]
        assert entry["hook"] == "component_post_error"
        assert entry["error"] == "Test error message"
        assert entry["session_id"] == "session-1"
        assert entry["component_type"] == "TestComponent"

    def test_log_validation(self, audit_plugin):
        """Test validation_post_check hook."""
        payload = MagicMock()
        payload.session_id = "session-1"
        payload.passed = True
        payload.reason = "Validation passed"

        ctx = MagicMock()

        asyncio.run(audit_plugin.log_validation(payload, ctx))

        entry = audit_plugin._entries[0]
        assert entry["hook"] == "validation_post_check"
        assert entry["passed"] is True
        assert entry["reason"] == "Validation passed"

    def test_log_tool_pre(self, audit_plugin):
        """Test tool_pre_invoke hook."""
        tool_call = MagicMock()
        tool_call.name = "test_tool"
        tool_call.args = {"arg1": "value1"}

        payload = MagicMock()
        payload.session_id = "session-1"
        payload.model_tool_call = tool_call

        ctx = MagicMock()

        asyncio.run(audit_plugin.log_tool_pre(payload, ctx))

        entry = audit_plugin._entries[0]
        assert entry["hook"] == "tool_pre_invoke"
        assert entry["tool_name"] == "test_tool"
        assert "arg1" in entry["tool_args"]

    def test_log_tool_post(self, audit_plugin):
        """Test tool_post_invoke hook."""
        tool_call = MagicMock()
        tool_call.name = "test_tool"
        tool_call.args = {"arg1": "value1"}

        payload = MagicMock()
        payload.session_id = "session-1"
        payload.model_tool_call = tool_call
        payload.tool_output = "Tool output"
        payload.execution_time_ms = 50
        payload.success = True
        payload.error = None

        ctx = MagicMock()

        asyncio.run(audit_plugin.log_tool_post(payload, ctx))

        entry = audit_plugin._entries[0]
        assert entry["hook"] == "tool_post_invoke"
        assert entry["tool_name"] == "test_tool"
        assert entry["execution_time_ms"] == 50
        assert entry["success"] is True


class TestAuditTrailSummary:
    """Test cases for summary method."""

    def test_summary_empty(self, audit_plugin):
        """Test summary with no entries."""
        summary = audit_plugin.summary()

        assert summary["total_events"] == 0
        assert summary["generations"] == 0
        assert summary["tool_calls"] == 0
        assert summary["generation_risks_flagged"] == 0
        assert summary["tool_risks_flagged"] == 0

    def test_summary_with_entries(self, audit_plugin):
        """Test summary with multiple entries."""
        from mellea_skills_compiler.models import GuardianVerdict

        # Add verdicts to guardian plugin
        audit_plugin.guardian_plugin.all_verdicts = [
            GuardianVerdict(risk="test", label="No", raw_output="<score>no</score>"),
            GuardianVerdict(risk="test2", label="No", raw_output="<score>no</score>"),
        ]

        # Add generation entries
        gen_payload = MagicMock()
        gen_payload.model_output = MagicMock(value="Output")
        gen_payload.latency_ms = 100
        gen_payload.session_id = "s1"
        gen_payload.request_id = "r1"

        asyncio.run(audit_plugin.log_post_call(gen_payload, MagicMock()))

        # Add tool entry
        tool_call = MagicMock()
        tool_call.name = "tool"
        tool_call.args = {}

        tool_payload = MagicMock()
        tool_payload.session_id = "s1"
        tool_payload.model_tool_call = tool_call
        tool_payload.tool_output = "output"
        tool_payload.execution_time_ms = 50
        tool_payload.success = True
        tool_payload.error = None

        asyncio.run(audit_plugin.log_tool_post(tool_payload, MagicMock()))

        summary = audit_plugin.summary()

        assert summary["total_events"] == 2
        assert summary["generations"] == 1
        assert summary["tool_calls"] == 1

    def test_summary_with_risks(self, audit_plugin):
        """Test summary counts risk detections."""
        from mellea_skills_compiler.models import GuardianVerdict

        # Add verdict with risk detected to guardian plugin
        audit_plugin.guardian_plugin.all_verdicts = [
            GuardianVerdict(risk="test", label="Yes", raw_output="<score>yes</score>"),
        ]

        # Add generation with risk
        payload = MagicMock()
        payload.model_output = MagicMock(value="Output")
        payload.latency_ms = 100
        payload.session_id = "s1"
        payload.request_id = "r1"

        asyncio.run(audit_plugin.log_post_call(payload, MagicMock()))

        summary = audit_plugin.summary()

        assert summary["generation_risks_flagged"] == 1
