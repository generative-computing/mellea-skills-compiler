# Exporting Compiled Skills to Other Agent Harnesses

After [`FROM_STUBS_TO_RUNNING.md`](FROM_STUBS_TO_RUNNING.md), the next question is usually: _"Now that I have a working compiled skill, can I run it under a framework that isn't Mellea?"_

This page describes the current state of export support and what the experimental `mellea-skills export` command does today. Anything outside the three supported targets is not export — it's a hand-written wrapper, and the work involved scales with how different the target harness is from a Python function call.

---

## 1. Current State

This release is a **research preview**. There is an **experimental** `mellea-skills export` subcommand that targets three deployment harnesses: **LangGraph**, **Claude Code**, and **MCP** (Model Context Protocol). It lives on the [`export-pipeline`](../../../tree/export-pipeline) branch and is gated behind an `[EXPERIMENTAL]` flag — output structure and CLI surface may change between releases without a deprecation period.

What "experimental" means here, concretely:

- The exporter runs end-to-end and produces deployable artifacts for the three supported targets.
- Tests cover the core translation pipeline (`tests/mellea_skills_compiler/export/test_exporter.py`, ~490 lines) but coverage is narrower than the compile path.
- Output file layouts, adapter conventions, and warning text may shift.
- Not every modality is supported on every target (see §4).

Out-of-the-box export in this research preview is limited to the three targets above. There is **no** built-in export path for OpenClaw, NanoClaw, CrewAI, Letta, AutoGen, smolagents, OpenAI Agents SDK, or other harnesses. For those, §3 sketches what hand-wrapping looks like — how much of the wrapping you have to do depends on how far the target's idioms are from a typed Python function call.

---

## 2. What a Compiled Package Exposes

Every compiled `<name>_mellea/` package presents the same surface, and the exporter consumes it:

| Artifact            | Role                                                                                                                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pipeline.py`       | Defines `run_pipeline(...)` — the typed entry point. Signature varies by skill modality.                                                                                                                      |
| `schemas.py`        | Pydantic models for inputs and outputs. `run_pipeline` returns a typed result.                                                                                                                                |
| `config.py`         | `BACKEND`, `MODEL_ID`, persona text, loop budgets, and other constants.                                                                                                                                       |
| `fixtures/`         | Factory functions returning `(inputs, fixture_id, description)` — sample inputs and expected behaviour.                                                                                                       |
| `melleafy.json`     | Manifest with `manifest_version`, `entry_signature`, `package_name`, `source_runtime`, `modality`, `categories_resolved`, `pipeline_parameters`, and `declared_env_vars`. The contract the exporter consumes. |
| `mapping_report.md` | Element-to-primitive mapping (which spec sections produced which pipeline components).                                                                                                                        |
| `SETUP.md`          | Backend setup and any external dependencies (env vars, services, stubs).                                                                                                                                      |

The two contractually load-bearing pieces for export are `pipeline.py:run_pipeline` (the callable) and `melleafy.json` (the typed metadata).

---

## 3. Hand-Wrapping a Compiled Skill (Not an Export)

If your target harness isn't `langgraph`, `claude-code`, or `mcp`, you're writing a wrapper by hand. The recipes below sketch what that looks like for the supported targets (in case the experimental exporter doesn't fit your needs) and for harnesses we don't target. Treat them as starting points: the further your target diverges from "call a typed Python function", the more glue you have to write yourself, and Mellea-specific behaviours (typed validators, repair loops, Guardian hooks) only run inside the bundled package — not at the harness boundary.

### As a Python library

```python
# Anywhere — your own script, an MCP server, a LangGraph node, a FastAPI handler.
from weather_mellea.pipeline import run_pipeline

result = run_pipeline(query="Will it rain in Tokyo tomorrow?")
print(result)
```

The compiled package installs via its own `pyproject.toml` (`pip install -e ./skills/weather/`). Once installed, `from <package_name> import pipeline` works from any process.

This is the path most users take for first-time integration with a harness we don't natively target. It is not free — you still own the harness-specific glue (state schema, error mapping, async semantics, scheduling, secrets) — but the compiled package itself is a plain Python import.

### As a LangGraph node (manual)

```python
# Conceptual — paths and state shapes are skill-specific.
from langgraph.graph import StateGraph
from weather_mellea.pipeline import run_pipeline

def weather_node(state):
    result = run_pipeline(query=state["user_query"])
    return {"weather": result}

graph = StateGraph(WeatherState)
graph.add_node("weather", weather_node)
```

The compiled pipeline runs to completion as a single LangGraph node. Mellea-specific behaviours — typed validators, repair loops, Guardian hooks — execute inside that node and are not exposed as separate LangGraph nodes. The native exporter (§4) generates a similar single-node wrapper but adds modality-aware async handling, state schema, and a `langgraph.json` manifest.

### As an MCP server (manual)

```python
# Conceptual.
from mcp.server import FastMCP
from weather_mellea.pipeline import run_pipeline

mcp = FastMCP("weather")

@mcp.tool()
def weather(query: str) -> dict:
    return run_pipeline(query=query).model_dump()
```

The native exporter (§4) generates this scaffold for you, including a `mcp.json` manifest, env-var declarations, and async handling for streaming modalities.

### As a Claude Code skill (manual)

A Claude Code skill is a Markdown file (`SKILL.md`) the agent loads, optionally backed by helper scripts under `scripts/`. Wrapping a compiled skill this way means letting Claude Code shell out to a Python helper:

1. Create `SKILL.md` describing the skill and how to invoke it.
2. Add `scripts/run.sh` that calls `python -m <package_name>.pipeline` with the right arguments.
3. Distribute via `pyproject.toml` so the package is on `PATH`.

The native exporter (§4) generates all four artifacts.

---

## 4. The `mellea-skills export` Command (Experimental)

```bash
mellea-skills export <package_path> <target> [--force]
```

Where:

- `<package_path>` — the compiled skill directory (the one containing `melleafy.json`, or a parent that holds a single `*_mellea/` subdirectory).
- `<target>` — one of `langgraph`, `claude-code`, `mcp`.
- `--force` / `-f` — overwrite the output directory if it already exists.

Output is written to `<package_name>/<package_name>-<target>/` inside the skill directory, and the compiled Mellea package is bundled inside it so the export is self-contained.

The exporter runs five stages: **validate** (read `melleafy.json`, check `manifest_version` ≥ 1.0.0), **load** (resolve the importable Python package, parse `entry_signature`), **translate** (target-specific adapter rendering), **emit** (write files, copy bundled package), **lint** (post-emit checks). On success, the exporter logs file count, byte count, and the output path.

### LangGraph target

Generated artifacts:

| File             | Purpose                                                                                     |
| ---------------- | ------------------------------------------------------------------------------------------- |
| `graph.py`       | LangGraph `StateGraph` with one async node wrapping `run_pipeline` via `asyncio.to_thread`. |
| `state.py`       | TypedDict state schema derived from the entry signature and return type.                    |
| `langgraph.json` | LangGraph platform manifest (graph entry, env vars, optional schedules block).              |
| `pyproject.toml` | Adapter package with the bundled compiled skill as a dependency.                            |
| `README.md`      | Per-target deployment guidance.                                                             |

Modalities supported: `synchronous_oneshot`, `streaming`, `conversational_session`, `scheduled`, `event_triggered`, `heartbeat`. `streaming` uses `get_stream_writer()` and `graph.astream_events()`; `conversational_session` adds `MemorySaver` checkpointing keyed on `thread_id`; `heartbeat` emits a cron-driven schedule.

What's preserved: typed I/O via the bundled Pydantic schemas, modality-aware async behaviour, env-var declarations.
What's lost: phase-level node decomposition (the whole Mellea pipeline runs inside one LangGraph node), Guardian hooks (no native LangGraph hook surface).

### Claude Code target

Generated artifacts:

| File             | Purpose                                                                                                   |
| ---------------- | --------------------------------------------------------------------------------------------------------- |
| `SKILL.md`       | Skill description with input/output contract derived from `melleafy.json`.                                |
| `scripts/run.sh` | Bash entry point that invokes the bundled Python pipeline with arguments forwarded as JSON or positional. |
| `pyproject.toml` | Installable package so `run.sh` can resolve the bundled module.                                           |
| `README.md`      | Installation and invocation instructions.                                                                 |

Modalities supported: `synchronous_oneshot`, `streaming` (unbuffered async streaming via `run.sh`), `conversational_session` (session carry-forward via a `--session` JSON arg).

What's preserved: invocation via Claude Code's skill mechanism, modality-aware streaming, the bundled package's typed pipeline.
What's lost: typed contract at the Claude Code surface (Claude dispatches via prompt + script, not function call).

### MCP target

Generated artifacts:

| File             | Purpose                                                                                                      |
| ---------------- | ------------------------------------------------------------------------------------------------------------ |
| `server.py`      | `FastMCP` server with one `@mcp.tool()` per pipeline entry. Sync for most modalities; async for `streaming`. |
| `mcp.json`       | MCP manifest with tool name, description, env-var declarations.                                              |
| `pyproject.toml` | Installable adapter package.                                                                                 |
| `README.md`      | Server invocation, env-var setup, transport notes.                                                           |

Modalities supported: `synchronous_oneshot`, `conversational_session`, `scheduled`, `event_triggered`, `heartbeat` (all sync), and `streaming` (async tool body that joins the async-generator output).

What's preserved: typed inputs (validated by Pydantic at the tool boundary), structured outputs, env-var contract.
What's lost: token-by-token streaming to MCP clients (would require `streamable-http` transport — not configured by the exporter today).

---

## 5. Harnesses We Do Not Export To

To set expectations clearly: **this research preview does not currently export to OpenClaw, NanoClaw, CrewAI, Letta, AutoGen, OpenAI Agents SDK, smolagents, or any harness outside the three above.** The compiler can _detect_ several of these as input dialects (see [`mellea-fy-inventory.md`](../src/mellea_skills_compiler/compile/claude/commands/mellea-fy-inventory.md) for the dialect detection table) — that lets you compile a skill _from_ one of those formats, but it does not produce an export _to_ it.

If you need to run a compiled skill under one of these harnesses, you write the wrapper yourself. The §3 patterns are the starting point; the typed contract in `melleafy.json` tells you what shape the wrapper has to bridge. More native export targets are on the roadmap, not in this preview.

---

## 6. Stable vs Unstable Contract

If you're writing your own integration (manual or via your own exporter), the following are stable and safe to build against:

- **`run_pipeline` is the entry point.** Modality-specific signatures are documented in [`mellea-fy-generate.md`](../src/mellea_skills_compiler/compile/claude/commands/mellea-fy-generate.md). Synchronous one-shot is the most common.
- **Pydantic schemas in `schemas.py` define the I/O contract.** Output models are non-`Optional` for hard-required fields; nullable fields use `Optional`.
- **`melleafy.json` is versioned.** `manifest_version` ≥ 1.0.0 is required by the exporter; the current emitted version is `1.1.0`.
- **Fixtures in `fixtures/` follow the `ALL_FIXTURES = [factory, ...]` contract.** Each factory returns `(inputs_dict, fixture_id, description)` — runnable input examples for any wrapper that needs them.

What's _not_ stable yet:

- **`mellea-skills export` output layout.** File names, adapter conventions, and warning text may change across releases while the command is experimental.
- **`intermediate/` JSON shapes.** Several intermediate files (`fixtures_emission.json`, `runtime_directive.json`, etc.) are tied to the deterministic writer pipeline and may change as that architecture evolves.
- **The `Invocation` / `LoadedContext` / `TranslationPlan` Python API in `export/exporter.py`.** Subject to change while the export command is experimental — invoke via the CLI rather than importing.

---

## 7. Where to Track This

- For experimental export today: `mellea-skills export --help` after checking out the [`export-pipeline`](../../../tree/export-pipeline) branch (or `main` once it lands).
- For hand-wrapping a non-supported harness: §3 documents the patterns; the wrapper is yours to maintain.
- For typed contract questions: read `melleafy.json` for the package you're integrating, and the spec at `mellea-fy-artifacts.md` for what each field means.
- For status of the export feature graduating from experimental to stable: check the project [Issues](../../../issues).
