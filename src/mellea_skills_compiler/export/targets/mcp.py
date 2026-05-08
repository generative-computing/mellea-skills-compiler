"""MCP target: translate a LoadedContext into a TranslationPlan.

Supported modalities:
  synchronous_oneshot   — sync @mcp.tool() wrapping run_pipeline
  streaming             — async @mcp.tool() collecting async generator chunks
  conversational_session — sync @mcp.tool() (session state managed by pipeline)
  scheduled             — sync @mcp.tool() (schedule is handled externally)
  event_triggered       — sync @mcp.tool() with payload passthrough
  heartbeat             — sync @mcp.tool() (heartbeat state managed by pipeline)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from mellea_skills_compiler.export.exporter import (
        AdapterFile,
        LoadedContext,
        ParsedSignature,
        TranslationPlan,
    )

# Modalities that use async tool body
_ASYNC_MODALITIES = {"streaming"}

# MCP tool name must match ^[a-zA-Z_][a-zA-Z0-9_]{0,63}$
_TOOL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


def translate_mcp(loaded: "LoadedContext") -> "TranslationPlan":
    from mellea_skills_compiler.export.exporter import AdapterFile, TranslationPlan

    manifest = loaded.manifest
    sig = loaded.sig
    warnings: list[str] = []

    package_name = manifest["package_name"]
    modality = manifest.get("modality", "synchronous_oneshot")

    tool_name = _resolve_tool_name(manifest, package_name)
    description = _get_description(manifest)
    is_async = modality in _ASYNC_MODALITIES

    server_py = _render_server_py(
        package_name=package_name,
        entry_module=loaded.entry_module,
        entry_function=sig.function_name,
        tool_name=tool_name,
        description=description,
        sig=sig,
        is_async=is_async,
        declared_env_vars=manifest.get("declared_env_vars", []),
    )

    mcp_json = _render_mcp_json(
        tool_name=tool_name,
        package_name=package_name,
        declared_env_vars=manifest.get("declared_env_vars", []),
        is_streaming=is_async,
    )

    pyproject_toml = _render_pyproject_toml(
        tool_name=tool_name,
        package_name=package_name,
    )

    readme = _render_readme(
        tool_name=tool_name,
        package_name=package_name,
        modality=modality,
        sig=sig,
        declared_env_vars=manifest.get("declared_env_vars", []),
        is_streaming=is_async,
    )

    if is_async:
        warnings.append(
            "Streaming modality: tool runs the pipeline async and returns the joined result. "
            "Token-by-token streaming to MCP clients requires streamable-http transport."
        )

    adapter_files: list["AdapterFile"] = [
        AdapterFile("server.py", server_py),
        AdapterFile("mcp.json", mcp_json),
        AdapterFile("pyproject.toml", pyproject_toml),
        AdapterFile("README.md", readme),
    ]

    deployment_guidance = _deployment_guidance(tool_name, is_async)

    return TranslationPlan(
        graph_name=tool_name,
        adapter_files=adapter_files,
        bundled_package_name=package_name,
        warnings=warnings,
        deployment_guidance=deployment_guidance,
    )


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------

def _resolve_tool_name(manifest: dict, package_name: str) -> str:
    """Derive tool name: runtime_metadata identity name → package_name (sanitized)."""
    runtime_metadata = manifest.get("runtime_metadata", {})
    identity = runtime_metadata.get("identity_fields", {})
    name = identity.get("name", "")
    if not name:
        categories = manifest.get("categories_resolved", {})
        if isinstance(categories, dict):
            c1 = categories.get("c1_identity", {})
            if isinstance(c1, dict):
                entries = c1.get("entries", [])
                if entries and isinstance(entries[0], dict):
                    name = entries[0].get("name", "")
    if not name:
        name = package_name

    # Sanitize to valid MCP tool name
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_").lower()
    if not sanitized:
        sanitized = "pipeline"
    # Enforce max 63 chars after leading alpha
    if not sanitized[0].isalpha() and sanitized[0] != "_":
        sanitized = "_" + sanitized
    sanitized = sanitized[:64]

    return sanitized


def _get_description(manifest: dict) -> str:
    runtime_metadata = manifest.get("runtime_metadata", {})
    if isinstance(runtime_metadata, dict) and runtime_metadata:
        c1 = runtime_metadata.get("c1_identity", {})
        if isinstance(c1, dict):
            entries = c1.get("entries", [])
            if entries and isinstance(entries[0], dict):
                desc = entries[0].get("description", "")
                if desc:
                    return desc
    categories = manifest.get("categories_resolved", {})
    if isinstance(categories, dict):
        c1 = categories.get("c1_identity", {})
        if isinstance(c1, dict):
            entries = c1.get("entries", [])
            if entries and isinstance(entries[0], dict):
                desc = entries[0].get("description", "")
                if desc:
                    return desc
    return f"Invokes the {manifest.get('package_name', 'pipeline')} Mellea pipeline."


def _render_param_list(sig: "ParsedSignature") -> str:
    """Render Python function parameter list from ParsedSignature."""
    if not sig.params:
        return ""
    parts = []
    for p in sig.params:
        ptype = _map_type(p["type"])
        if p["required"]:
            parts.append(f"{p['name']}: {ptype}")
        else:
            default = p["default"] if p["default"] is not None else "None"
            parts.append(f"{p['name']}: {ptype} = {default}")
    return ", ".join(parts)


def _render_passthrough(sig: "ParsedSignature") -> str:
    """Render keyword argument passthrough: fn(a=a, b=b, ...)."""
    if not sig.params:
        return ""
    return ", ".join(f"{p['name']}={p['name']}" for p in sig.params)


def _map_type(t: str) -> str:
    """Map manifest type hint to a safe Python type for MCP tool signature."""
    _SAFE = {"str", "int", "float", "bool", "bytes"}
    t = t.strip()
    if t in _SAFE:
        return t
    # Complex types (union, custom class, etc.) → str
    return "str"


# ---------------------------------------------------------------------------
# server.py
# ---------------------------------------------------------------------------

def _render_server_py(
    *,
    package_name: str,
    entry_module: str,
    entry_function: str,
    tool_name: str,
    description: str,
    sig: "ParsedSignature",
    is_async: bool,
    declared_env_vars: list,
) -> str:
    param_list = _render_param_list(sig)
    passthrough = _render_passthrough(sig)
    fn_def = "async def" if is_async else "def"

    env_note = ""
    if declared_env_vars:
        var_names = [v if isinstance(v, str) else v.get("name", str(v)) for v in declared_env_vars]
        env_note = (
            "\n# Required environment variables: "
            + ", ".join(var_names)
            + "\n"
        )

    if is_async:
        tool_body = (
            f"    chunks = []\n"
            f"    async for chunk in {entry_function}({passthrough}):\n"
            f"        chunks.append(str(chunk))\n"
            f"    return ''.join(chunks)"
        )
    else:
        result_expr = f"{entry_function}({passthrough})" if passthrough else f"{entry_function}()"
        tool_body = (
            f"    result = {result_expr}\n"
            f"    if hasattr(result, 'model_dump'):\n"
            f"        import json as _json\n"
            f"        return _json.dumps(result.model_dump())\n"
            f"    return str(result) if result is not None else ''"
        )

    return (
        "import sys\n"
        "from mcp.server.fastmcp import FastMCP\n"
        f"from {package_name}.{entry_module} import {entry_function}\n"
        f"{env_note}\n"
        f'mcp = FastMCP(name="{tool_name}")\n'
        "\n"
        "\n"
        "@mcp.tool()\n"
        f"{fn_def} {tool_name}({param_list}) -> str:\n"
        f'    """{description}"""\n'
        f"{tool_body}\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        '    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"\n'
        '    if transport == "http":\n'
        '        mcp.run(transport="streamable-http")\n'
        "    else:\n"
        "        mcp.run()  # defaults to stdio\n"
    )


# ---------------------------------------------------------------------------
# mcp.json
# ---------------------------------------------------------------------------

def _render_mcp_json(
    *,
    tool_name: str,
    package_name: str,
    declared_env_vars: list,
    is_streaming: bool,
) -> str:
    import json

    env_vars: dict = {}
    for v in declared_env_vars:
        var_name = v if isinstance(v, str) else v.get("name", str(v))
        env_vars[var_name] = ""

    streaming_comment = ""
    if is_streaming:
        streaming_comment = (
            "Streaming modality: use the http transport entry for token-by-token streaming."
        )

    config: dict = {"mcpServers": {}}

    stdio_entry: dict = {
        "command": "python",
        "args": ["server.py"],
        "env": env_vars,
    }
    if streaming_comment:
        stdio_entry["_note"] = streaming_comment

    http_entry: dict = {
        "command": "python",
        "args": ["server.py", "http"],
        "env": env_vars,
    }

    config["mcpServers"][tool_name] = stdio_entry
    config["mcpServers"][f"{tool_name}-http"] = http_entry

    return json.dumps(config, indent=2) + "\n"


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------

def _render_pyproject_toml(*, tool_name: str, package_name: str) -> str:
    return (
        "[build-system]\n"
        'requires = ["setuptools>=68"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "\n"
        "[project]\n"
        f'name = "{tool_name}-mcp-adapter"\n'
        'version = "0.1.0"\n'
        f'description = "MCP server adapter for {tool_name}"\n'
        'requires-python = ">=3.11"\n'
        "dependencies = [\n"
        '    "mcp>=1.2.0",\n'
        "]\n"
        "\n"
        "[tool.setuptools.packages.find]\n"
        'where = ["."]\n'
        f'include = ["{package_name}*"]\n'
        "\n"
        "[project.scripts]\n"
        f'{tool_name}-server = "server:mcp.run"\n'
    )


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------

def _render_readme(
    *,
    tool_name: str,
    package_name: str,
    modality: str,
    sig: "ParsedSignature",
    declared_env_vars: list,
    is_streaming: bool,
) -> str:
    display_name = tool_name.replace("_", " ").title()

    env_section = ""
    if declared_env_vars:
        var_names = [v if isinstance(v, str) else v.get("name", str(v)) for v in declared_env_vars]
        lines = "\n".join(f"export {v}=<value>" for v in var_names)
        env_section = (
            "\n## Environment variables\n\n"
            "Set the following before running the server:\n\n"
            f"```bash\n{lines}\n```\n"
        )

    streaming_note = ""
    if is_streaming:
        streaming_note = (
            "\n> **Streaming note**: This pipeline yields tokens incrementally. "
            "Token-by-token streaming to MCP clients requires the `streamable-http` transport "
            "and a client that processes content deltas. The stdio transport delivers the "
            "complete result after all tokens are collected.\n"
        )

    param_table = ""
    if sig.params:
        rows = "\n".join(
            f"| `{p['name']}` | `{p['type']}` | {'Yes' if p['required'] else 'No'} |"
            for p in sig.params
        )
        param_table = (
            "\n## Parameters\n\n"
            "| Name | Type | Required |\n"
            "|------|------|----------|\n"
            f"{rows}\n"
        )

    return (
        f"# {display_name} — MCP Adapter\n"
        f"\n"
        f"MCP server adapter for the `{tool_name}` Mellea pipeline.\n"
        f"Registers the pipeline as an MCP tool discoverable by Claude Desktop, Claude Code, and other MCP clients.\n"
        f"{streaming_note}"
        f"\n"
        f"## Installation\n"
        f"\n"
        f"```bash\n"
        f"pip install -e .\n"
        f"```\n"
        f"{env_section}"
        f"\n"
        f"## Running the server\n"
        f"\n"
        f"**stdio transport** (default — for Claude Desktop / Claude Code local use):\n"
        f"\n"
        f"```bash\n"
        f"python server.py\n"
        f"```\n"
        f"\n"
        f"**streamable-http transport** (for network-accessible deployments):\n"
        f"\n"
        f"```bash\n"
        f"python server.py http\n"
        f"```\n"
        f"\n"
        f"## Registration\n"
        f"\n"
        f"Add to your MCP client config (e.g. `~/.claude/claude_desktop_config.json`):\n"
        f"\n"
        f"```json\n"
        f'{{\n'
        f'  "mcpServers": {{\n'
        f'    "{tool_name}": {{\n'
        f'      "command": "python",\n'
        f'      "args": ["/absolute/path/to/server.py"]\n'
        f'    }}\n'
        f'  }}\n'
        f'}}\n'
        f"```\n"
        f"\n"
        f"See `mcp.json` for a full example including both stdio and http transport entries.\n"
        f"{param_table}"
        f"\n"
        f"## Modality\n"
        f"\n"
        f"Exported modality: `{modality}`\n"
        f"\n"
        f"## Troubleshooting\n"
        f"\n"
        f"- **Authentication**: The generated server has no authentication. "
        f"For streamable-http in production, add authentication via FastMCP middleware or a reverse proxy.\n"
        f"- **Dependencies**: `pip install -e .` installs the MCP SDK and the bundled pipeline package.\n"
    )


# ---------------------------------------------------------------------------
# Deployment guidance (used in EXPORT_NOTES.md)
# ---------------------------------------------------------------------------

def _deployment_guidance(tool_name: str, is_streaming: bool) -> str:
    base = (
        f"Install with `pip install -e .` then run `python server.py` for stdio transport. "
        f"Register in your MCP client config pointing at the absolute path to `server.py`. "
        f"See `mcp.json` for both stdio and streamable-http registration examples."
    )
    if is_streaming:
        base += (
            " Streaming modality: use `python server.py http` and streamable-http transport "
            "for token-by-token output."
        )
    return base
