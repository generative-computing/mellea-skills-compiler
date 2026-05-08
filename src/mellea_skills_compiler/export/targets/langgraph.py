"""LangGraph target: translate a LoadedContext into a TranslationPlan.

Supported modalities:
  synchronous_oneshot   — async node wrapping sync pipeline via asyncio.to_thread
  streaming             — async node with get_stream_writer(), graph.astream_events()
  conversational_session — async node, MemorySaver checkpointer, thread_id config
  scheduled             — async node + langgraph.json schedules block
  event_triggered       — async node, event dict state, platform webhook
  heartbeat             — async node, MemorySaver + HEARTBEAT_THREAD_ID constant + cron schedule

All non-streaming nodes are generated as `async def` wrapping the synchronous Mellea
pipeline via `asyncio.to_thread`. This prevents blocking LangGraph's ASGI event loop
when the pipeline makes synchronous I/O calls (e.g. Ollama, file writes).
"""

from __future__ import annotations

import json as _json
import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from mellea_skills_compiler.export.exporter import (
        AdapterFile,
        LoadedContext,
        ParsedSignature,
        TranslationPlan,
    )

SUPPORTED_MODALITIES = {
    "synchronous_oneshot",
    "streaming",
    "conversational_session",
    "scheduled",
    "event_triggered",
    "heartbeat",
}


def translate_langgraph(loaded: "LoadedContext") -> "TranslationPlan":
    from mellea_skills_compiler.export.exporter import AdapterFile, TranslationPlan

    manifest = loaded.manifest
    sig = loaded.sig
    warnings: list[str] = []

    graph_name = _resolve_graph_name(manifest)
    adapter_name = f"{graph_name}-langgraph-adapter"
    entry_function = sig.function_name
    package_name = manifest["package_name"]
    env_vars: list[str] = manifest.get("declared_env_vars", [])
    modality = manifest.get("modality", "synchronous_oneshot")
    export_version = _export_version()

    if modality not in SUPPORTED_MODALITIES:
        warnings.append(
            f"Modality '{modality}' is not fully supported by this target. "
            "Falling back to synchronous_oneshot adapter."
        )
        modality = "synchronous_oneshot"

    # Dispatch to modality-specific graph.py renderer
    graph_py = _render_graph_py(
        modality=modality,
        graph_name=graph_name,
        package_name=package_name,
        entry_module=loaded.entry_module,
        entry_function=entry_function,
        pattern=sig.pattern,
        params=sig.params,
        export_version=export_version,
        manifest=manifest,
    )

    state_py = _render_state_py(modality=modality, sig=sig)
    langgraph_json = _render_langgraph_json(
        graph_name=graph_name, env_vars=env_vars, modality=modality, manifest=manifest
    )
    pyproject_toml = _render_pyproject_toml(
        adapter_name=adapter_name,
        graph_name=graph_name,
        package_name=package_name,
        modality=modality,
    )
    readme = _render_readme(
        graph_name=graph_name,
        sig=sig,
        env_vars=env_vars,
        modality=modality,
    )

    adapter_files: list["AdapterFile"] = [
        AdapterFile("graph.py", graph_py),
        AdapterFile("state.py", state_py),
        AdapterFile("langgraph.json", langgraph_json),
        AdapterFile("pyproject.toml", pyproject_toml),
        AdapterFile("README.md", readme),
    ]
    if env_vars:
        adapter_files.append(AdapterFile(".env.example", _render_env_example(env_vars)))

    deployment_guidance = _deployment_guidance(modality, graph_name)

    return TranslationPlan(
        graph_name=graph_name,
        adapter_files=adapter_files,
        bundled_package_name=package_name,
        warnings=warnings,
        deployment_guidance=deployment_guidance,
    )


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------

def _resolve_graph_name(manifest: dict) -> str:
    rm = manifest.get("runtime_metadata", {})
    if rm:
        name = rm.get("c1_identity", {}).get("identity_fields", {}).get("name", "")
        if name:
            return _to_snake(name)
    pkg = manifest.get("package_name", "")
    return _to_snake(pkg) if pkg else "pipeline"


def _to_snake(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    return s or "pipeline"


def _export_version() -> str:
    from mellea_skills_compiler.export.exporter import EXPORT_VERSION
    return EXPORT_VERSION


# ---------------------------------------------------------------------------
# graph.py dispatcher
# ---------------------------------------------------------------------------

def _render_graph_py(
    *,
    modality: str,
    graph_name: str,
    package_name: str,
    entry_module: str,
    entry_function: str,
    pattern: str,
    params: list[dict],
    export_version: str,
    manifest: dict,
) -> str:
    ctx = dict(
        graph_name=graph_name,
        package_name=package_name,
        entry_module=entry_module,
        entry_function=entry_function,
        pattern=pattern,
        params=params,
        export_version=export_version,
        manifest=manifest,
    )
    dispatch = {
        "synchronous_oneshot": _graph_synchronous_oneshot,
        "streaming": _graph_streaming,
        "conversational_session": _graph_conversational_session,
        "scheduled": _graph_scheduled,
        "event_triggered": _graph_event_triggered,
        "heartbeat": _graph_heartbeat,
    }
    return dispatch[modality](**ctx)


def _node_body(entry_function: str, pattern: str, *, state_key: str = "input") -> str:
    """Generate the pipeline invocation body for a sync node."""
    if pattern == "no_args":
        return f"    result = {entry_function}()\n"
    if pattern == "single_positional":
        return f'    result = {entry_function}(state["{state_key}"])\n'
    return (
        f'    input_val = state.get("{state_key}")\n'
        f"    if input_val is None:\n"
        f"        result = {entry_function}()\n"
        f"    elif isinstance(input_val, dict):\n"
        f"        result = {entry_function}(**input_val)\n"
        f"    else:\n"
        f"        raise TypeError(\n"
        f'            f"Expected dict or None for state[\\"{state_key}\\"]; '
        f'got {{type(input_val).__name__}}"\n'
        f"        )\n"
    )


def _named_async_call(entry_function: str, params: list[dict]) -> str:
    """Generate async node body: asyncio.to_thread with named state attribute access."""
    if not params:
        return f"    result = await asyncio.to_thread({entry_function})\n"
    args = ", ".join(f"{p['name']}=state.{p['name']}" for p in params)
    return f"    result = await asyncio.to_thread({entry_function}, {args})\n"


def _param_fields(params: list[dict]) -> str:
    """Generate Pydantic BaseModel field definitions from ParsedSignature params."""
    if not params:
        return ""
    lines = []
    for p in params:
        name = p.get("name", "")
        typ = p.get("type") or "Any"
        required = p.get("required", True)
        default = p.get("default")
        if not required:
            # default is already a Python literal string from the parsed signature (e.g. '""', '"foo"')
            val = "None" if (default is None or default == "None") else default
            lines.append(f"    {name}: Optional[Any] = {val}")
        elif typ == "str":
            lines.append(f'    {name}: str = ""')
        elif typ == "int":
            lines.append(f"    {name}: int = 0")
        elif typ == "float":
            lines.append(f"    {name}: float = 0.0")
        elif typ == "bool":
            lines.append(f"    {name}: bool = False")
        else:
            lines.append(f"    {name}: Optional[Any] = None")
    return "\n".join(lines) + "\n"


def _output_type(return_type: str) -> str:
    """Map a return type string to an Optional Pydantic field annotation."""
    if return_type in {"str", "int", "float", "bool", "bytes"}:
        return f"Optional[{return_type}]"
    return "Optional[Any]"


def _header(graph_name: str, package_name: str, entry_module: str,
            entry_function: str, export_version: str, extra_imports: str = "") -> str:
    return (
        f'"""LangGraph adapter for {graph_name}.\n\n'
        f"Generated by melleafy-export v{export_version}.\n"
        f"Wraps the Mellea pipeline at {package_name}.{entry_module}.{entry_function}\n"
        f'as a single-node StateGraph.\n"""\n\n'
        f"import asyncio\n\n"
        + extra_imports
        + f"from langgraph.graph import END, StateGraph\n"
        f"from {package_name}.{entry_module} import {entry_function}\n\n"
        f"from state import PipelineState\n\n\n"
    )


# ---------------------------------------------------------------------------
# Modality variants
# ---------------------------------------------------------------------------

def _graph_synchronous_oneshot(
    *, graph_name, package_name, entry_module, entry_function,
    params, export_version, **_
) -> str:
    h = _header(graph_name, package_name, entry_module, entry_function, export_version)
    node = (
        "async def invoke_pipeline(state: PipelineState) -> dict:\n"
        + _named_async_call(entry_function, params)
        + '    return {"output": result}\n'
    )
    footer = (
        "\n\n_builder = StateGraph(PipelineState)\n"
        '_builder.add_node("invoke_pipeline", invoke_pipeline)\n'
        '_builder.set_entry_point("invoke_pipeline")\n'
        '_builder.add_edge("invoke_pipeline", END)\n\n'
        "graph = _builder.compile()\n"
    )
    return h + node + footer


def _graph_streaming(
    *, graph_name, package_name, entry_module, entry_function,
    params, export_version, **_
) -> str:
    extra = "from langgraph.config import get_stream_writer\n\n"
    h = _header(graph_name, package_name, entry_module, entry_function,
                export_version, extra_imports=extra)

    if not params:
        call = f"    async for chunk in {entry_function}():\n"
    elif len(params) == 1:
        call = f"    async for chunk in {entry_function}(state.{params[0]['name']}):\n"
    else:
        args = ", ".join(f"{p['name']}=state.{p['name']}" for p in params)
        call = f"    async for chunk in {entry_function}({args}):\n"

    node = (
        "async def invoke_pipeline(state: PipelineState) -> dict:\n"
        "    writer = get_stream_writer()\n"
        "    output_chunks = []\n"
        + call
        + '        writer({"type": "token", "content": str(chunk)})\n'
        "        output_chunks.append(str(chunk))\n"
        '    return {"output": "".join(output_chunks)}\n'
    )
    footer = (
        "\n\n_builder = StateGraph(PipelineState)\n"
        '_builder.add_node("invoke_pipeline", invoke_pipeline)\n'
        '_builder.set_entry_point("invoke_pipeline")\n'
        '_builder.add_edge("invoke_pipeline", END)\n\n'
        "graph = _builder.compile()\n"
        "\n# Invoke with:\n"
        "# async for event in graph.astream_events(input_state, version='v2'):\n"
        "#     if event['event'] == 'on_custom_event' and event.get('name') == 'token':\n"
        "#         print(event['data']['content'], end='')\n"
    )
    return h + node + footer


def _graph_conversational_session(
    *, graph_name, package_name, entry_module, entry_function,
    params, export_version, **_
) -> str:
    extra = "from langgraph.checkpoint.memory import MemorySaver\n\n"
    h = _header(graph_name, package_name, entry_module, entry_function,
                export_version, extra_imports=extra)

    node = (
        "async def invoke_pipeline(state: PipelineState) -> dict:\n"
        "    # session history is carried in state.messages; pipeline result appended\n"
        + _named_async_call(entry_function, params)
        + '    turn = {"role": "assistant", "content": str(result)}\n'
        '    return {"output": result, "messages": state.messages + [turn]}\n'
    )
    footer = (
        "\n\n_builder = StateGraph(PipelineState)\n"
        '_builder.add_node("invoke_pipeline", invoke_pipeline)\n'
        '_builder.set_entry_point("invoke_pipeline")\n'
        '_builder.add_edge("invoke_pipeline", END)\n\n'
        "graph = _builder.compile(checkpointer=MemorySaver())\n"
        "\n# Invoke with:\n"
        '# config = {"configurable": {"thread_id": "my-conversation-1"}}\n'
    )
    return h + node + footer


def _graph_scheduled(
    *, graph_name, package_name, entry_module, entry_function,
    export_version, **_
) -> str:
    # Scheduled graphs use no-args pattern — triggered by scheduler, no runtime input
    h = _header(graph_name, package_name, entry_module, entry_function, export_version)
    node = (
        "async def invoke_pipeline(state: PipelineState) -> dict:\n"
        "    # Triggered on schedule — no input expected\n"
        f"    result = await asyncio.to_thread({entry_function})\n"
        '    return {"output": result}\n'
    )
    footer = (
        "\n\n_builder = StateGraph(PipelineState)\n"
        '_builder.add_node("invoke_pipeline", invoke_pipeline)\n'
        '_builder.set_entry_point("invoke_pipeline")\n'
        '_builder.add_edge("invoke_pipeline", END)\n\n'
        "graph = _builder.compile()\n"
        "\n# Schedule is declared in langgraph.json — see the 'schedules' block.\n"
    )
    return h + node + footer


def _graph_event_triggered(
    *, graph_name, package_name, entry_module, entry_function,
    export_version, **_
) -> str:
    h = _header(graph_name, package_name, entry_module, entry_function, export_version)
    node = (
        "async def invoke_pipeline(state: PipelineState) -> dict:\n"
        "    # state.event carries the webhook payload dict\n"
        f"    result = await asyncio.to_thread({entry_function}, state.event)\n"
        '    return {"output": result}\n'
    )
    footer = (
        "\n\n_builder = StateGraph(PipelineState)\n"
        '_builder.add_node("invoke_pipeline", invoke_pipeline)\n'
        '_builder.set_entry_point("invoke_pipeline")\n'
        '_builder.add_edge("invoke_pipeline", END)\n\n'
        "graph = _builder.compile()\n"
        "\n# Deploy via LangGraph Platform: configure a webhook to POST to this graph.\n"
        "# The webhook body is passed as state.event.\n"
    )
    return h + node + footer


def _graph_heartbeat(
    *, graph_name, package_name, entry_module, entry_function,
    export_version, manifest, **_
) -> str:
    extra = "from langgraph.checkpoint.memory import MemorySaver\n\n"
    h = _header(graph_name, package_name, entry_module, entry_function,
                export_version, extra_imports=extra)

    node = (
        f'HEARTBEAT_THREAD_ID = "{graph_name}-heartbeat"\n\n\n'
        "async def invoke_pipeline(state: PipelineState) -> dict:\n"
        "    # Heartbeat: pipeline receives prior state and returns updated state\n"
        f"    new_state = await asyncio.to_thread({entry_function}, state.heartbeat_state)\n"
        '    return {"heartbeat_state": new_state, "output": new_state}\n'
    )
    footer = (
        "\n\n_builder = StateGraph(PipelineState)\n"
        '_builder.add_node("invoke_pipeline", invoke_pipeline)\n'
        '_builder.set_entry_point("invoke_pipeline")\n'
        '_builder.add_edge("invoke_pipeline", END)\n\n'
        "graph = _builder.compile(checkpointer=MemorySaver())\n"
        "\n# Run a heartbeat tick:\n"
        '# config = {"configurable": {"thread_id": HEARTBEAT_THREAD_ID}}\n'
        '# graph.invoke({"heartbeat_state": None}, config=config)\n'
        "# Schedule is declared in langgraph.json — see the 'schedules' block.\n"
    )
    return h + node + footer


# ---------------------------------------------------------------------------
# state.py
# ---------------------------------------------------------------------------

def _render_state_py(*, modality: str, sig: "ParsedSignature") -> str:
    base = (
        '"""State schema for the LangGraph wrapper graph."""\n\n'
        "from typing import Any, Optional\n"
        "from pydantic import BaseModel\n\n\n"
    )
    out_type = _output_type(sig.return_type)
    fields = _param_fields(sig.params)

    if modality == "conversational_session":
        return (
            base
            + "class PipelineState(BaseModel):\n"
            + (fields if fields else "")
            + "    messages: list[dict] = []\n"
            + f"    output: {out_type} = None\n"
        )

    if modality == "event_triggered":
        return (
            base
            + "class PipelineState(BaseModel):\n"
            "    event: Optional[Any] = None  # webhook payload\n"
            f"    output: {out_type} = None\n"
        )

    if modality == "heartbeat":
        return (
            base
            + "class PipelineState(BaseModel):\n"
            "    heartbeat_state: Optional[Any] = None  # persisted between ticks via MemorySaver\n"
            f"    output: {out_type} = None\n"
        )

    # synchronous_oneshot, streaming, scheduled
    return (
        base
        + "class PipelineState(BaseModel):\n"
        + (fields if fields else "")
        + f"    output: {out_type} = None\n"
    )


# ---------------------------------------------------------------------------
# langgraph.json
# ---------------------------------------------------------------------------

def _render_langgraph_json(
    *, graph_name: str, env_vars: list[str], modality: str, manifest: dict
) -> str:
    doc: dict = {
        "dependencies": ["."],
        "graphs": {graph_name: "./graph.py:graph"},
    }

    if modality in ("scheduled", "heartbeat"):
        cron = _resolve_cron(manifest, modality)
        doc["schedules"] = [
            {"graph_id": graph_name, "schedule": cron, "input": {}}
        ]

    if env_vars:
        doc["env"] = env_vars

    return _json.dumps(doc, indent=2) + "\n"


def _resolve_cron(manifest: dict, modality: str) -> str:
    """Extract cron expression from manifest or return a placeholder."""
    sc = manifest.get("schedule_config", {})
    if modality == "heartbeat":
        every = sc.get("heartbeat", {}).get("every", "")
        if every:
            return _interval_to_cron(every)
    elif modality == "scheduled":
        cron = sc.get("cron", "") or sc.get("schedule", "")
        if cron:
            return cron
    return "0 * * * *"  # placeholder — update before deployment


def _interval_to_cron(interval: str) -> str:
    """Convert simple interval strings like '1h', '30m' to cron expressions."""
    interval = interval.strip().lower()
    if interval.endswith("h"):
        try:
            h = int(interval[:-1])
            return f"0 */{h} * * *" if h < 24 else "0 0 * * *"
        except ValueError:
            pass
    if interval.endswith("m"):
        try:
            m = int(interval[:-1])
            return f"*/{m} * * * *"
        except ValueError:
            pass
    return "0 * * * *"


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------

def _render_pyproject_toml(
    *, adapter_name: str, graph_name: str, package_name: str, modality: str
) -> str:
    extra_deps = ""
    if modality in ("conversational_session", "heartbeat"):
        extra_deps = '\n    "langgraph-checkpoint>=0.0.1",'

    return (
        "[build-system]\n"
        'requires = ["setuptools>=68"]\n'
        'build-backend = "setuptools.build_meta"\n\n'
        "[project]\n"
        f'name = "{adapter_name}"\n'
        'version = "0.1.0"\n'
        f'description = "LangGraph adapter for {graph_name} Mellea pipeline ({modality})"\n'
        'requires-python = ">=3.11"\n'
        "dependencies = [\n"
        '    "langgraph>=0.2.0",'
        f"{extra_deps}\n"
        "]\n\n"
        "[tool.setuptools.packages.find]\n"
        'where = ["."]\n'
        f'include = ["{package_name}*"]\n'
    )


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

_MODALITY_INVOCATION = {
    "synchronous_oneshot": (
        "result = graph.invoke({{\"input\": {example_input}}})\n"
        "print(result[\"output\"])"
    ),
    "streaming": (
        "import asyncio\n\n"
        "async def run():\n"
        "    async for event in graph.astream_events({{\"input\": {example_input}}}, version='v2'):\n"
        "        if event['event'] == 'on_custom_event':\n"
        "            print(event['data']['content'], end='')\n\n"
        "asyncio.run(run())"
    ),
    "conversational_session": (
        "config = {{\"configurable\": {{\"thread_id\": \"my-session\"}}}}\n"
        "result = graph.invoke({{\"input\": {example_input}}}, config=config)\n"
        "print(result[\"output\"])\n"
        "# Continue the conversation — same thread_id carries history:\n"
        "result2 = graph.invoke({{\"input\": \"follow-up question\"}}, config=config)"
    ),
    "scheduled": (
        "# Scheduled invocation — triggered by langgraph.json cron expression.\n"
        "# Manual trigger for testing:\n"
        "result = graph.invoke({{}})\nprint(result[\"output\"])"
    ),
    "event_triggered": (
        "# Triggered by webhook payload. Manual trigger for testing:\n"
        "event_payload = {{\"source\": \"webhook\", \"data\": \"...\"}}\n"
        "result = graph.invoke({{\"event\": event_payload}})\nprint(result[\"output\"])"
    ),
    "heartbeat": (
        "from graph import graph, HEARTBEAT_THREAD_ID\n\n"
        "config = {{\"configurable\": {{\"thread_id\": HEARTBEAT_THREAD_ID}}}}\n"
        "# First tick:\n"
        "result = graph.invoke({{\"heartbeat_state\": None}}, config=config)\n"
        "# Subsequent ticks use the same thread_id — MemorySaver carries state."
    ),
}


def _render_readme(
    *, graph_name: str, sig: "ParsedSignature", env_vars: list[str], modality: str
) -> str:
    example_input = _build_example_input(sig)
    invocation = _MODALITY_INVOCATION.get(modality, _MODALITY_INVOCATION["synchronous_oneshot"])
    invocation = invocation.format(example_input=example_input)

    env_section = ""
    if env_vars:
        env_lines = "\n".join(f"{v}=your_{v.lower()}_here" for v in env_vars)
        env_section = f"\n## Environment variables\n\nCreate `.env`:\n\n```\n{env_lines}\n```\n"

    return (
        f"# {graph_name} — LangGraph Adapter ({modality})\n\n"
        f"Exported LangGraph adapter for the `{graph_name}` Mellea pipeline.\n\n"
        f"## Installation\n\n```bash\npip install -e .\n```\n"
        f"{env_section}\n"
        f"## Invocation\n\n```python\nfrom graph import graph\n\n{invocation}\n```\n\n"
        f"## LangGraph Platform\n\nDeploy using `langgraph.json` with the LangGraph CLI or Platform UI.\n"
    )


def _build_example_input(sig: "ParsedSignature") -> str:
    if sig.pattern == "no_args":
        return "None"
    if sig.pattern == "single_positional":
        return '"your input here"'
    items = []
    for p in sig.params:
        if p["type"] == "str":
            val = f'"{p["default"] or ""}"'
        elif p["type"] in ("int", "float"):
            val = p["default"] or "0"
        elif p["type"] == "bool":
            val = p["default"] or "False"
        else:
            val = "None"
        items.append(f'"{p["name"]}": {val}')
    return "{" + ", ".join(items) + "}"


def _render_env_example(env_vars: list[str]) -> str:
    return "\n".join(f"{v}=" for v in env_vars) + "\n"


def _deployment_guidance(modality: str, graph_name: str) -> str:
    guides = {
        "synchronous_oneshot": "Install with `pip install -e .` and invoke via `graph.invoke()`.",
        "streaming": "Use `graph.astream_events()` to receive token-level chunks.",
        "conversational_session": (
            "Pass the same `thread_id` in config across calls to continue a session. "
            "MemorySaver stores state in-process; swap for SqliteSaver for persistence."
        ),
        "scheduled": (
            f"Update the `schedule` cron in langgraph.json before deploying to LangGraph Platform. "
            "The placeholder `0 * * * *` fires every hour."
        ),
        "event_triggered": (
            "Configure a LangGraph Platform webhook to POST to this graph. "
            "The webhook body lands in state['event']."
        ),
        "heartbeat": (
            f"Update the `schedule` cron in langgraph.json. "
            f"All ticks use HEARTBEAT_THREAD_ID='{graph_name}-heartbeat' so MemorySaver "
            "carries state between ticks. Swap MemorySaver for SqliteSaver for durability."
        ),
    }
    return guides.get(modality, "Review graph.py and langgraph.json before deploying.")
