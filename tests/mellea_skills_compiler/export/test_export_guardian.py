"""Tests that Guardian plugin registration is injected into generated entry points
when has_policy_manifest=True."""

from mellea_skills_compiler.export.exporter import ParsedSignature
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
        assert "register_plugins" in result
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
        assert "register_plugins" not in result
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
        assert result.index("register_plugins") < result.index('mcp = FastMCP(')


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
        assert "register_plugins" in result
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
        assert "register_plugins" not in result

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
        assert result.index("register_plugins") < result.index("_builder = StateGraph")


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
        assert "register_plugins" in result
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
        assert "register_plugins" in result
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
        assert "register_plugins" in result
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
        assert "register_plugins" not in result
