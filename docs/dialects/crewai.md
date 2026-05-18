# CrewAI Dialect

**Version**: 1.0.0
**Status**: Sixth dialect doc. YAML + Python hybrid source model — tests the template against a runtime with two declarative files plus executable code, and with Flows as an optional higher-order composition layer.

**Prerequisite reading**: `spec.md` R1 (detection), R22 (dialect mapping contract), R21 (modality); `plans/dialects/openclaw.md` (reference template for Markdown workspaces); `plans/dialects/langgraph.md` (reference for code-first dialects); `plans/generated-package-shape.md` (output shape); `plans/steps/step-1a-inventory.md`, `plans/steps/step-1b-tagging.md`.

---

## What this document does

Describes the rules melleafy applies when processing a **CrewAI** source spec. CrewAI is YAML-first but code-adjacent: two declarative YAML files under `config/` (`agents.yaml`, `tasks.yaml`) describe the agents and tasks; Python files (`tools.py`, `crew.py`) carry executable content that references the YAML declarations. An optional higher layer — **Flows** (`@start`/`@listen`/`@router`/`@persist`) — composes crews into orchestrated pipelines.

CrewAI is the first dialect written here whose source model is genuinely **dual** — declarative and executable surfaces together, each complementing the other. The template's inventory section adapts by enumerating both surfaces.

Key CrewAI concepts readers should have in mind:

- **Crew**: a group of agents executing tasks, orchestrated by a `Process` (sequential or hierarchical).
- **`agents.yaml`**: per-agent declarations — `role`, `goal`, `backstory`, `llm`, `tools`, `memory`, `allow_delegation` (default **False**), `allowed_agents`, and more.
- **`tasks.yaml`**: per-task declarations — `description`, `expected_output`, `agent` reference, `context: [task_a, task_b]` for task-level dependencies, `async_execution`, `output_pydantic`, `human_input`, plus callbacks and guardrails.
- **`tools.py`**: `@tool`-decorated functions or `BaseTool` subclasses; MCP integration via `MCPServerAdapter`.
- **`crew.py`**: assembly logic; often uses `@CrewBase` for auto-resolution.
- **Flows**: separate composition layer using `@start`, `@listen`, `@router`, `@persist` decorators. Flows can call crews via `SomeCrew().crew().kickoff(inputs=...)`.
- **Memory backends**: filesystem-based (Chroma for STM/entity/knowledge, SQLite for LTM) under `~/Library/Application Support/CrewAI/<project>/` (macOS), `~/.local/share/CrewAI/<project>/` (Linux), or `CREWAI_STORAGE_DIR` override.

---

## 1. Detection signals

| Signal | Strength | Notes |
|---|---|---|
| `config/agents.yaml` AND `config/tasks.yaml` present | strong | The canonical CrewAI layout |
| `@CrewBase`, `@agent`, `@task`, `@crew` decorators in any `.py` file | strong | CrewAI-specific decorator set |
| `from crewai import Agent, Task, Crew` or similar | strong | Canonical import |
| `from crewai.flow.flow import Flow` + `@start`, `@listen`, `@router` decorators | strong | Flows signal |
| `.crewai/memory` directory in workspace | medium | Persistence artifact; survives across runs |
| `@crewai_event_bus.on(...)` | medium | Event-listener pattern |
| `tools.py` file at workspace root referencing `@tool` from `crewai.tools` | medium | Tool-declaration file |
| `Chroma` usage with CrewAI-style paths (`chroma.sqlite3`, `entities/`, `knowledge/`) | weak | Persistence pattern |
| `MCPServerAdapter` import | weak | MCP integration |

**Disambiguating from LangGraph.** Both have `Agent` in the import namespace, but the decorator sets are distinct. LangGraph uses `StateGraph`, `add_node`, `add_edge`; CrewAI uses `@agent`, `@task`, `@crew`. A spec importing both is Hybrid.

**Disambiguating from OpenAI Agents SDK.** Both have `@tool` decorators, but CrewAI's `@tool` is `from crewai.tools import tool` whereas Agents SDK uses `from agents import function_tool`. Also, Agents SDK uses pure Python Agent class construction; CrewAI emphasizes YAML declarations.

**Precedence note.** R1 tiebreak: CrewAI wins over LangGraph in exact ties. This happens rarely — CrewAI's YAML signals usually tip the count clearly.

**Hybrid threshold.** CrewAI + LangGraph is an uncommon but real Hybrid (a project that uses Flows to orchestrate at a higher level and LangGraph for internal reasoning loops). Detected by presence of both signal sets; follows R1's 1-signal-difference threshold.

---

## 2. File inventory rules (Step 1a)

CrewAI's workspace is structured: YAML under `config/`, Python at root, memory at system-specific locations.

### 2a. Primary declarative surfaces

| File | Role | Inventory action |
|---|---|---|
| `config/agents.yaml` | Agent declarations — C1 (identity) + C2 (rules) + C6 (tool bindings) per agent | Parse YAML; each top-level agent key becomes a source of multiple elements |
| `config/tasks.yaml` | Task declarations — C2 (rules/dependencies) + C3 (inputs via `kickoff`) | Parse YAML; each top-level task key becomes a source |

### 2b. Primary executable surfaces

| File | Role | Inventory action |
|---|---|---|
| `tools.py` (at workspace root) | C6 Tools — `@tool` functions, `BaseTool` subclasses | Parse with AST; each decorated function / subclass becomes a C6 element |
| `crew.py` (at workspace root) | Assembly logic — `@CrewBase` methods, crew construction | Parse with AST; methods mapped to agent/task references |
| Any `.py` file with CrewAI decorators or imports | Additional assembly or utility | AST-walked per `plans/dialects/langgraph.md` §2 pattern |

**Rule 2b-1**: `crew.py` with `@CrewBase` decoration has implicit path resolution — `@agent` and `@task` decorated methods correspond to entries in `agents.yaml` and `tasks.yaml` by name. Melleafy's Step 1b cross-references the YAML names against the Python method names and surfaces mismatches in the inventory report.

**Rule 2b-2**: `crew.py` may use explicit construction (not `@CrewBase`) — `Agent(...)`, `Task(...)`, `Crew([...])` calls in module body. AST-walked the same way; the resulting elements are tagged identically regardless of construction style.

### 2c. Flows surface (optional higher-order layer)

If the project uses Flows (detected via `@start`, `@listen`, `@router`, `@persist` decorators or `Flow` imports):

| File | Role | Inventory action |
|---|---|---|
| Any `.py` file with Flow decorators | Orchestration layer atop crews | AST-walk for `@start`/`@listen`/`@router`/`@persist`/`@human_feedback` decorated methods |
| Flow class definitions (`class MyFlow(Flow[StateType])`) | State-carrying composition | Inventory state type as a SCHEMA element; methods as ORCHESTRATE elements |

**Rule 2c-1**: Flows compose crews. A `@start`-decorated method typically calls `SomeCrew().crew().kickoff(inputs=...)`. When melleafy detects this pattern, the crew reference is recorded but the crew's own YAML is *not* re-inventoried from scratch — the crew entries are referenced by name.

**Rule 2c-2**: a project may be crew-only, flow-only (flows without nested crews), or crew+flow. Detection produces a sub-variant recorded in the mapping report: `crewai_sub_variant ∈ {crew_only, flow_only, crew_and_flow}`.

### 2d. Supporting files

| File | Role | Inventory action |
|---|---|---|
| `.env` at workspace root | C7 credentials — CrewAI auto-calls `load_dotenv()` | Parse; one element per var |
| `.env.example` | C7 credential template | Same |
| `pyproject.toml` / `requirements.txt` | C8 dependencies | Parse; elements per package |
| `README.md` | Free-form | NO_DECOMPOSE unless spec references |

**Rule 2d-1**: CrewAI's auto-`load_dotenv()` means `.env` handling is implicit — the generated pipeline must reproduce this behavior (via python-dotenv in `main.py`). The mapping report documents this convention under "Runtime behaviors preserved."

### 2e. Memory backend artifacts (detection only)

| Path | Type | Inventory action |
|---|---|---|
| `~/Library/Application Support/CrewAI/<project>/` (macOS) | Memory root | **Detection only** — do not read contents |
| `~/.local/share/CrewAI/<project>/` (Linux) | Memory root | Same |
| `$CREWAI_STORAGE_DIR/<project>/` (override) | Memory root | Same |
| `chroma.sqlite3` under any of above | Short-term memory | Detection only |
| `long_term_memory_storage.db` | Long-term memory | Detection only |
| `entities/` subdirectory | Entity memory | Detection only |
| `knowledge/` subdirectory | Knowledge base | Detection only |

**Rule 2e-1**: memory backends are **detection-only** — their existence confirms that the spec has been run locally, but their contents are runtime state, not spec content. Bundling them would inline user-specific data into the generated package. The mapping report's Classification section notes "CrewAI memory backends detected; contents not inventoried (runtime state)."

**Rule 2e-2**: Chroma lock files (`chroma.sqlite3-journal`, etc.) prevent concurrent writes. If the workspace has multiple CrewAI projects sharing the same `CREWAI_STORAGE_DIR`, parallel runs would conflict. Melleafy flags this as a lint in Step 7's category-specific lint (C4/C5 section), but detection-time only — no halt.

### 2f. Missing files

Absence rules:

- `config/agents.yaml` absent + `@agent`-decorated methods exist in `.py`: normal — some projects define agents purely in code. Proceed with Python inventory.
- `config/tasks.yaml` absent + `@task`-decorated methods exist: same.
- Both YAML files absent AND no decorators: detection likely misfired; halt with diagnostic.
- `tools.py` absent: normal; crews may use only built-in or hosted tools.
- `crew.py` absent + `@CrewBase` not used: the project may rely on YAML-only crew definition; still proceed.

---

## 3. Structured-content rules

CrewAI has three kinds of structured content: YAML (under `config/`), Python AST (`.py` files), and `.env` text format.

### 3a. YAML parsing

Parsed with `yaml.safe_load`. Per-file validation:

**For `agents.yaml`**: each top-level key is an agent name. Per agent, fields include `role`, `goal`, `backstory`, `llm`, `tools` (list of tool names), `memory` (bool), `allow_delegation` (bool, default False), `allowed_agents` (list of agent names), `max_iter`, `max_rpm`, `respect_context_window`, `reasoning`, `multimodal`, `cache`, `step_callback`, `system_template`, `prompt_template`, `response_template`.

**For `tasks.yaml`**: each top-level key is a task name. Per task, fields include `description`, `expected_output`, `agent` (agent name reference), `context` (list of task-name references — **the dependency declaration**), `async_execution`, `output_file`, `output_pydantic` (class name reference), `human_input`, `markdown`, `callback`, `guardrails`.

**Rule 3a-1**: YAML parse errors halt Step 1a per the standard Step 1a §3b.1 policy (frontmatter parse failures are warnings; YAML file parse failures are halts because the file *is* the content).

**Rule 3a-2**: unknown top-level keys (neither an agent name pattern nor a reserved CrewAI config key) are warnings; proceed with detected keys.

### 3b. Cross-reference validation

CrewAI's YAML files reference each other and reference Python code. Melleafy validates at inventory time:

| Reference | Validation |
|---|---|
| `tasks.yaml:<task>.agent` → an agent in `agents.yaml` | Warn on unresolved |
| `tasks.yaml:<task>.context[]` → task names in `tasks.yaml` | Warn on unresolved or cycles |
| `agents.yaml:<agent>.tools` → `@tool`-decorated functions in `tools.py` | Warn on unresolved |
| `agents.yaml:<agent>.allowed_agents[]` → agents in `agents.yaml` | Warn on unresolved |
| `tasks.yaml:<task>.output_pydantic` → a class importable somewhere | Warn on unresolved |
| `@CrewBase` methods in `crew.py` → entries in YAML files | Warn on mismatch (§2b Rule 2b-1) |

**Rule 3b-1**: unresolved references are warnings, not halts. CrewAI itself often accepts loose references and resolves them at runtime; melleafy mirrors this leniency during inventory and lets Step 7 flag the same issues with file-and-line precision.

### 3c. Python AST parsing

Same machinery as LangGraph (`plans/dialects/langgraph.md` §3b). Relevant patterns for CrewAI:

- `@tool`-decorated functions → C6 source signals
- `class X(BaseTool)` with `_run` or `run` method → C6 source signals
- `@CrewBase`, `@agent`, `@task`, `@crew` decorators → cross-references to YAML entries
- `@start`, `@listen(MethodRef)`, `@router(MethodRef)`, `@persist` decorators → Flow orchestration elements
- `@human_feedback(emit=[...])` → review-gated modality signal (see §5)
- `@crewai_event_bus.on(EventType)` → event-triggered modality signal
- `Agent(...)`, `Task(...)`, `Crew([...])` direct construction calls → alternative to `@CrewBase`

### 3d. Docstrings

Module-level and function docstrings in `tools.py` and `crew.py` are inventoried as C1/C6 content (tool purpose descriptions). Comments (`# ...`) are not, matching LangGraph's §3c rule.

### 3e. `.env` format

Parsed as key=value pairs; values may be quoted or unquoted. Comments (`#`) are skipped. Empty values are preserved as empty strings (distinct from absent). Export statements (`export KEY=value`) are handled — the `export ` prefix is stripped.

---

## 4. Dialect mapping table

| Source signal | Category | Default disposition | Generation target |
|---|---|---|---|
| `agents.yaml:<n>.role` | C1 | `bundle` | `config.AGENTS[<n>]` dict; referenced in prompt-assembly |
| `agents.yaml:<n>.goal` | C1 | `bundle` | Same |
| `agents.yaml:<n>.backstory` | C1 | `bundle` | Same |
| `agents.yaml:<n>.llm` | C8 | `bundle` | `config.AGENT_LLMS[<n>]`; SETUP.md §3 documents backend selection |
| `agents.yaml:<n>.tools[]` | C6 | Inherited from each tool's disposition | `tools.py` or `constrained_slots.py` per tool |
| `agents.yaml:<n>.memory: true` | C4 | `delegate_to_runtime` | `constrained_slots.py:*_memory`; SETUP.md §4 |
| `agents.yaml:<n>.allow_delegation: true` | C2 + C6 | *(not reproduced in v1)* | Noted in "Runtime-specific constructs not reproduced" — CrewAI auto-injects delegation tools at runtime |
| `agents.yaml:<n>.allowed_agents[]` | C2 | `bundle` | `config.ALLOWED_AGENTS` dict; documented in README |
| `agents.yaml:<n>.max_iter` | C2 | `bundle` | `config.MAX_ITER_<n>` constant |
| `agents.yaml:<n>.max_rpm` | C8 | `bundle` | Rate-limit config; SETUP.md §3 |
| `agents.yaml:<n>.reasoning: true` | — | *(informational)* | Noted; affects Step 2 primitive choices for the agent's tasks |
| `agents.yaml:<n>.multimodal: true` | — | *(not reproduced)* | Listed in "Not reproduced" |
| `agents.yaml:<n>.system_template` / `prompt_template` / `response_template` | C1 | `bundle` | Prompt templates inlined into `config.PROMPT_TEMPLATES` |
| `tasks.yaml:<task>.description` | C2 | `bundle` | Inlined into `pipeline.py` as the task's prompt |
| `tasks.yaml:<task>.expected_output` | C2 | `bundle` | Expected-output text inlined as part of the prompt |
| `tasks.yaml:<task>.agent` | — | *(structural — not a standalone element)* | Used by Step 2 mapping to attach task to agent |
| `tasks.yaml:<task>.context[]` | — | `bundle` | Used by Step 2 to generate `ORCHESTRATE` control flow (task dependencies become sequencing in `pipeline.py`) |
| `tasks.yaml:<task>.output_pydantic` | — | `bundle` | Schema referenced; inlined into `schemas.py` or imported from source |
| `tasks.yaml:<task>.human_input: true` | C2 + modality | `delegate_to_runtime` | `constrained_slots.py:get_human_input`; drives `review_gated` secondary modality (see §5) |
| `tasks.yaml:<task>.async_execution: true` | — | `bundle` | `pipeline.py` uses `asyncio` for this task's invocation |
| `tasks.yaml:<task>.output_file` | — | *(informational)* | Noted; generated pipeline returns the output; user decides file routing |
| `tasks.yaml:<task>.callback` | C2 | `bundle` if simple, `stub` otherwise | Python callable reference; if resolved in `tools.py` → `real_impl` |
| `tasks.yaml:<task>.guardrails` | C2 | `bundle` | Each guardrail becomes a `Requirement` entry |
| `tools.py:@tool`-decorated function | C6 | `real_impl` | `tools.py:<tool_name>` |
| `tools.py:BaseTool` subclass | C6 | `real_impl` | `tools.py:<tool_name>` wrapped as a function for Mellea compatibility |
| `tools.py:MCPServerAdapter` usage | C6 | `stub` | `constrained_slots.py:*`; SETUP.md §3 names MCP server |
| `crew.py:@CrewBase.agents()` / `.tasks()` references | — | *(structural — resolves YAML references)* | Used by mapping; no direct generation target |
| `crew.py:Process.sequential` (default) | — | `bundle` | Sequential `pipeline.py` orchestration |
| `crew.py:Process.hierarchical` | C2 + modality | `bundle` with warning | Hierarchical manager pattern — v1 translates to sequential with a "manager" agent as dispatcher |
| Flow `@start`-decorated method | — | `bundle` | `pipeline.py:run_pipeline` entry point uses the @start method's logic |
| Flow `@listen(Method)` | — | `bundle` | `pipeline.py` sequential flow: after Method, call this |
| Flow `@router(Method)` | — | `bundle` | `pipeline.py:if/elif/else` based on router return |
| Flow `@persist` | C4 | `delegate_to_runtime` | `constrained_slots.py:flow_persist_load` / `flow_persist_save`; SETUP.md §4 |
| Flow `@human_feedback(emit=[...])` | C2 + modality | `delegate_to_runtime` | `constrained_slots.py:get_human_feedback`; drives `review_gated` modality |
| `@crewai_event_bus.on(EventType)` | C9 (event_triggered) | `delegate_to_runtime` | `handlers/<event>.py`; SETUP.md §7 |
| `.env` var entries | C7 | `external_input` | `.env.example` entries |
| `pyproject.toml:dependencies` | C8 | `bundle` | Merged into generated `pyproject.toml` |
| `~/Library/Application Support/CrewAI/...` detection | — | *(detection only)* | Noted; contents not inventoried |
| `CREWAI_STORAGE_DIR` reference in `.env` | C8 | `bundle` | Noted in SETUP.md §4 — user must set if using memory |

**Override semantics.** Default dispositions can be overridden via `--dependencies=ask` or `config:<path>` per the standard R22 contract.

**Rule 4-1**: `allow_delegation: true` is explicitly **not reproduced** in v1. CrewAI's runtime injects "Delegate work to co-worker" and "Ask question to co-worker" tools dynamically at `Crew.kickoff()` time. Melleafy would need to generate these tools statically, which would require knowing the full crew composition at generation time. The `allowed_agents` field restricts targets if delegation is reproduced. For v1, this is a Deferred Item — generated packages warn in their docstring that delegation is not reproduced, and the mapping report surfaces the same.

**Rule 4-2**: `Process.hierarchical` specifies a manager-worker pattern where one agent dispatches tasks to others. v1's translation is approximate — a "manager" helper function in `pipeline.py` that dispatches to worker agents in sequence. This is semantically close but not structurally identical. Mapping report documents the approximation.

---

## 5. Modality signals (Step 0 Axis 5, R21)

CrewAI has the most **declarative** modality signals of any dialect we've covered so far — `tasks.yaml` encodes modality choices as spec-level booleans.

| Signal | Modality classification |
|---|---|
| `Crew.kickoff(inputs={...})` call pattern | **`synchronous_oneshot`** — the default |
| `LLMStreamChunkEvent` via `crewai_event_bus` usage | **`streaming`** (as secondary — event-bus streaming) |
| `memory=True` on any agent or crew | **`conversational_session`** as secondary (enables cross-session memory) |
| `tasks.yaml:<task>.human_input: true` | **`review_gated`** as secondary |
| Flow `@human_feedback(emit=[...])` decorator | **`review_gated`** as secondary (Flows-only variant) |
| `@crewai_event_bus.on(EventType)` | **`event_triggered`** as primary (if no other invocation pattern present) or secondary |
| `tasks.yaml:<task>.async_execution: true` | *(behavior — not modality)* — affects generated code shape but not modality classification |
| Scheduling references (`cron` in spec body) | **`scheduled`** — but CrewAI OSS has no native scheduling (see §6) |

**Rule 5-1**: CrewAI OSS has **no native scheduling**. The CrewAI AMP (Autonomous Multi-Agent Platform) enterprise product offers scheduling; OSS does not. If a spec declares scheduling intent (typically in prose), modality classifies as `scheduled` with `delegate_to_runtime` disposition and SETUP.md §6 names "external cron or AMP" as options.

**Rule 5-2**: `async_execution: true` on a task enables concurrent execution of that task alongside others but does not change the external modality of `Crew.kickoff()`. From outside, the crew is still synchronous. Generated code uses `asyncio` internally for the flagged task; the entry point remains `def run_pipeline(inputs) -> Output`.

**Rule 5-3**: `memory=True` on an agent enables CrewAI's built-in memory system (Chroma-backed). This makes the crew **conversational** across sessions — repeated `kickoff()` calls with the same memory state produce context-aware responses. Modality classification adds `conversational_session` as secondary.

**Rule 5-4**: `human_input: true` on a task is CrewAI's stdin-blocking HITL pattern. Generated code emits a `get_human_input()` stub that reads from stdin; SETUP.md §7 names the host adapter options (web UI, Slack prompt, etc.).

### 5a. Flows modality signals

Flows add their own modality signals:

- `@start`-decorated method → entry point; modality follows the rest of the spec
- `@human_feedback(emit=[...])` → `review_gated` with a structured emit (channel routing for the feedback request)
- `@persist` → enables `conversational_session` for the flow's state

**Rule 5a-1**: a Flow with `@human_feedback(emit=["slack", "email"])` declares that the feedback request should route to multiple channels. v1 melleafy doesn't reproduce the emit routing — the stub just receives input from stdin. Mapping report documents the routing declaration as a "Runtime-specific construct not reproduced."

### 5b. Composition common case

The canonical CrewAI modality composition is `synchronous_oneshot + conversational_session + review_gated` — a crew with memory, some tasks marked `human_input`, invoked via `kickoff()`. Primary is `synchronous_oneshot`; secondaries include the others. Generated shape is §5a (synchronous) with stubs for the review-gated tasks.

---

## 6. Quirks and workarounds

### 6a. YAML-to-Python reference resolution

The biggest structural aspect of CrewAI inventory: **agents are declared in YAML but their behavior is shaped by Python code**. An agent's `tools: [calc, search]` references entries in `tools.py`; its `llm:` references a model config that may be in `crew.py` or inferred. Melleafy's cross-reference validation (§3b) catches mismatches at inventory time, but the mapping stage has to bridge YAML declarations with Python implementations.

**Rule 6a-1**: the mapping approach is: each YAML-declared agent becomes a **bundle of config constants** (role, goal, backstory → `config.AGENTS[<n>]`) plus **references to the Python tools** the agent uses. The generated `pipeline.py` assembles these at runtime — it instantiates prompts from config, calls tools from `tools.py`, applies requirements from `requirements.py`. This preserves CrewAI's declarative/executable split semantically.

### 6b. `allow_delegation` is not reproduced (v1)

Per Rule 4-1. This is the biggest single gap in v1's CrewAI support. Delegation means one agent can call another agent as a tool. CrewAI injects these tools at runtime; melleafy would need to generate them statically, requiring full crew-composition knowledge. Deferred.

**Rule 6b-1**: generated packages for specs with `allow_delegation: true` include a docstring warning: "This crew declared `allow_delegation: true`. Inter-agent delegation is not reproduced in v1 — tasks run in the sequence declared in `tasks.yaml:<task>.context`, not with dynamic delegation." Users reviewing can confirm the generated flow matches intent.

### 6c. `@CrewBase` auto-resolution

When `crew.py` uses `@CrewBase`, YAML paths resolve automatically and `load_dotenv()` is called. When it doesn't, everything is explicit. Melleafy generates code that **always explicitly loads `.env`** (via `python-dotenv` in `main.py`) regardless of which source pattern was used. This preserves the runtime behavior for both patterns.

### 6d. Memory backend filesystem paths

CrewAI memory backends use platform-specific paths. Melleafy's generated code uses an **explicit `CREWAI_STORAGE_DIR` env var** rather than the platform-specific defaults — this avoids hidden filesystem dependencies and makes deployment portable. SETUP.md §4 documents the env var; the user sets it to whatever directory suits their deployment.

**Rule 6d-1**: if a spec specifically depends on the platform-default path (e.g., a comment says "memory lives in `~/Library/Application Support/CrewAI`"), the mapping report flags the assumption under "Runtime behaviors preserved" but does not reproduce the platform conditional. v2 could grow platform-aware defaults.

### 6e. Chroma lock file concurrency

CrewAI's Chroma-backed memory uses a single SQLite file per backend. Concurrent writes from parallel crews lock each other out. Melleafy's mapping documents this in SETUP.md §4 and flags in Step 7's category-specific lint — the check is "if the generated package is meant to run as multiple instances, ensure each has a distinct `CREWAI_STORAGE_DIR`."

### 6f. `output_pydantic` is a typed output contract

When a task declares `output_pydantic: SomeClass`, the task's output is validated against that class. This is structurally similar to Mellea's `m.instruct(format=SomeClass)` pattern, and melleafy's mapping uses it directly — the declared Pydantic class is inlined into `schemas.py` and referenced in the task's generated code.

**Rule 6f-1**: the class declared in `output_pydantic` must be importable. If it's defined in a separate file not inventoried (rare), Step 1a warns. If it's defined inline in `crew.py`, it's inventoried as a SCHEMA element.

### 6g. Flow state is typed via generic parameter

`class MyFlow(Flow[StateModel])` uses a generic parameter to declare the state type. `StateModel` is typically a Pydantic model. Melleafy inventories `StateModel` as a SCHEMA element and uses it as the state-passing type in the generated `pipeline.py`. When the generic is `Flow[dict]` (no typed state), melleafy generates a plain `dict` state — less safe but matches source.

### 6h. `Process.hierarchical` translation

Per Rule 4-2. Translated to a sequential pipeline with a "manager" helper function. The translation loses CrewAI's dynamic task-routing behavior (the manager decides at runtime which worker to dispatch); v1 uses a declarative dispatch pattern (manager calls workers in the order declared in `tasks.yaml:context`). Mapping report documents the translation.

### 6i. `@crewai_event_bus.on()` event families

CrewAI's event bus handles many event families: Crew, Agent, Task, Tool, Knowledge, Memory, MCP, LLM, Guardrail, Flow, HITL, A2A, System. v1 melleafy maps any event listener to a handler stub in `handlers/<event_family>.py` with a SETUP.md §7 note. Fine-grained event-specific handling (e.g., distinguishing `CrewKickoffStartedEvent` from `CrewKickoffEndedEvent`) is preserved in the stub signature but the implementation is user-side.

### 6j. CrewAI default flips between versions

CrewAI has had default flips across versions — `allow_delegation` defaulted to True in old versions, now False. `memory` defaulted differently at different points. Melleafy's mapping uses the **current default** (as of 2026-Q1); specs targeting older versions may produce subtle behavior differences. The mapping report notes the current defaults used.

### 6k. MCP via `MCPServerAdapter`

CrewAI integrates MCP via `MCPServerAdapter`. The adapter takes a server config and exposes the server's tools. Melleafy stubs MCP tools in `constrained_slots.py` because MCP servers are external processes the generated package doesn't manage. SETUP.md §3 names the MCP server and documents how the user wires it.

### 6l. No native scheduling in OSS

Per Rule 5-1. `scheduled` modality for CrewAI implies external cron or the AMP enterprise product. SETUP.md §6 documents both options.

---

## 7. Reference inventory output (illustrative)

For a minimal CrewAI spec — `config/agents.yaml` with one agent, `config/tasks.yaml` with two tasks (one with `human_input`), `tools.py` with one tool, and `crew.py` with `@CrewBase`:

### Inventory (abridged)

```json
{
  "elements": [
    {"element_id": "elem_001", "source_file": "config/agents.yaml", "source_lines": "yaml:researcher.role", "tag": "CONFIG", "category": "C1", "content_summary": "Agent 'researcher': role = Senior researcher"},
    {"element_id": "elem_002", "source_file": "config/agents.yaml", "source_lines": "yaml:researcher.backstory", "tag": "CONFIG", "category": "C1", "content_summary": "Agent 'researcher': backstory (3 paragraphs)"},
    {"element_id": "elem_003", "source_file": "config/agents.yaml", "source_lines": "yaml:researcher.tools", "tag": "TOOL_TEMPLATE", "category": "C6", "content_summary": "Agent 'researcher' uses tools: [search, calc]"},
    {"element_id": "elem_010", "source_file": "config/tasks.yaml", "source_lines": "yaml:extract_claims.description", "tag": "EXTRACT", "category": "C2", "content_summary": "Task 'extract_claims': extract key claims from input"},
    {"element_id": "elem_011", "source_file": "config/tasks.yaml", "source_lines": "yaml:review_claims.human_input", "tag": "CONVERSE", "category": "C2", "content_summary": "Task 'review_claims' requires human approval"},
    {"element_id": "elem_020", "source_file": "tools.py", "source_lines": "py:tools.py:5-20", "tag": "TOOL_TEMPLATE", "category": "C6", "content_summary": "@tool search: DuckDuckGo web search"},
    {"element_id": "elem_030", "source_file": "crew.py", "source_lines": "py:crew.py:10-40", "tag": "ORCHESTRATE", "category": "—", "content_summary": "@CrewBase class with sequential process"}
  ]
}
```

Note `source_lines` formats: `yaml:<dotted-path>` for YAML references, `py:<file>:<range>` for Python (matching LangGraph's convention). Four source_lines conventions are now in use across dialects — `line_range`, `frontmatter.<field>`, `json:<path>`, and now `yaml:<path>`.

### Element mapping (abridged)

```json
{
  "mappings": [
    {"element_id": "elem_001", "target_file": "config.py", "target_symbol": "AGENTS['researcher']['role']", "primitive": "bundle"},
    {"element_id": "elem_002", "target_file": "config.py", "target_symbol": "AGENTS['researcher']['backstory']", "primitive": "bundle"},
    {"element_id": "elem_003", "target_file": "pipeline.py", "target_symbol": "_researcher_tools", "primitive": "reference"},
    {"element_id": "elem_010", "target_file": "pipeline.py", "target_symbol": "_task_extract_claims", "primitive": "@generative"},
    {"element_id": "elem_011", "target_file": "constrained_slots.py", "target_symbol": "get_human_input_review_claims", "primitive": "stub"},
    {"element_id": "elem_020", "target_file": "tools.py", "target_symbol": "search", "primitive": "real_impl"},
    {"element_id": "elem_030", "target_file": "pipeline.py", "target_symbol": "run_pipeline", "primitive": "orchestrate"}
  ]
}
```

### Dialect-specific notes in the mapping report

- A "YAML-Python reference resolution" section confirming cross-references (YAML tool names → `tools.py` implementations, task→agent bindings, etc.).
- A "Runtime-specific constructs not reproduced" section listing `allow_delegation`, `multimodal`, `@human_feedback emit` routing, Process.hierarchical manager pattern (if translated).
- A "CrewAI sub-variant" note: "crew_only" / "flow_only" / "crew_and_flow" (§2c Rule 2c-2).
- A "Default version flip awareness" callout noting which CrewAI defaults were used (§6j).

---

## 8. Deferred CrewAI features (not handled in v1)

- **Inter-agent delegation** via `allow_delegation: true` — v1 doesn't reproduce runtime tool injection. Users with delegation-heavy crews should manually wire the generated code.
- **`Process.hierarchical` full semantics** — v1 translates to sequential with a "manager" helper. Dynamic task routing is lost.
- **Native scheduling (AMP feature)** — v1 stubs; SETUP.md §6 documents options.
- **Multimodal agents** (`multimodal: true`) — v1 generates text-only pipelines.
- **Flow `@human_feedback emit` channel routing** — v1 ignores routing; stubs receive from stdin.
- **Event-bus event-family-specific handlers** — v1 handles generically; specific events (e.g., `CrewKickoffStartedEvent` vs `...EndedEvent`) are differentiated in stub signatures but not in behavior.
- **`MCPServerAdapter` full integration** — v1 stubs MCP tools; user wires the server externally.
- **Chroma memory bundling** — v1 never bundles memory state; user's deployment recreates memory on first run.
- **Platform-default memory paths** — v1 requires explicit `CREWAI_STORAGE_DIR`; platform-specific defaults not reproduced.
- **Training data handling** (`Crew.train()` is a CrewAI feature for optimising prompts over examples) — v1 doesn't reproduce; user uses base prompts.
- **Knowledge sources** declared via `Knowledge` class — inventoried but treated as C5 delegate; not bundled.

---

## 9. Cross-references

- `spec.md` R1, R21, R22 — the contracts this dialect implements
- `plans/dialects/openclaw.md` — template; file-inventory pattern
- `plans/dialects/langgraph.md` — Python AST handling; `py:` source_lines format
- `plans/dialects/letta.md` — structured-content patterns (JSON analog to YAML)
- `plans/dialects/claude-code.md` — Markdown workspace patterns for reference
- `plans/generated-package-shape.md` — shape of the generated output
- `glossary.md` — `dialect`, `disposition`, `interaction modality`
- `melleafy.json` schema — the manifest fields this dialect populates

---

## 10. Ratification notes

This dialect doc v1.0.0 was the sixth drafted, selected to complete the set of file-based dialects before tackling the remaining pure-code dialects (AutoGen, OpenAI Agents SDK, smolagents).

**What the template survived unchanged:**
- Section 1 (Detection signals) — the signal-count model accommodates CrewAI's mix of YAML and Python signals without restructure.
- Section 4 (Dialect mapping table) — the longest we've produced (about 40 rows), but the four-column shape held.
- Sections 5, 6, 7, 8, 9 — translated directly.

**What the template needed to adapt:**
- **Section 2 (File inventory)** — became genuinely dual-surface: Section 2a for YAML (declarative) plus Section 2b for Python (executable). The template already supports "multiple sub-sections per section" so this was natural; Letta had one structured-data section, Claude Code had multiple file types, LangGraph had one declarative + one code surface, and CrewAI has both.
- **Section 2c (Flows as higher-order layer)** — a new sub-section shape for runtime polymorphism within one dialect. Flows are optional and compose over crews; the template accommodated by treating them as their own Section 2 sub-section.
- **Section 3 (Structured-content rules)** — YAML parsing section uses the same shape as Letta's §3a (JSON parsing) and Claude Code's §3a (JSON parsing); proves YAML and JSON are interchangeable at this level of abstraction.
- **Section 6 (Quirks)** — grew to twelve sub-sections (6a–6l) because CrewAI has the most distinct runtime behaviors to document. The template's Quirks section has no fixed size; this was fine.
- **§7 `source_lines` convention** introduces `yaml:<dotted-path>` as a fourth format. The proliferation continues; the plan is still to formalise all four as `source_range: {format, value}` in Step 1b.

**Runtime polymorphism observation.** CrewAI is the first dialect where a single spec can use different architectural patterns — crew-only, flow-only, or crew+flow. Each variant is a valid CrewAI spec; melleafy records which variant applies in the mapping report. This is worth flagging for other dialects that might have similar polymorphism (AutoGen has OSS vs AGS; OpenAI Agents SDK has plain vs Swarm vs SandboxAgent).

Open questions:

- **§6b `allow_delegation` not reproduced** is the biggest single gap. For CrewAI users relying on delegation, v1 generates sequential code that loses the dynamic routing. Worth corpus-testing how common delegation-heavy crews are in real specs.
- **§6h `Process.hierarchical` translation to sequential** loses dynamic dispatch. A user whose spec explicitly needs manager-style routing would find the v1 translation inadequate. Consider a dedicated "hierarchical-pattern preservation" option in v2.
- **§6j default-flip awareness** notes CrewAI's defaults have changed across versions. Worth a `--crewai-version=<v>` override flag for specs targeting older CrewAI; v1 uses current defaults.
- **§5b composition** is opinionated about which modality is primary vs secondary. A spec with `human_input: true` on every task arguably has `review_gated` as primary. Worth tuning with corpus data.
- **§2b Rule 2b-1 auto-resolution vs explicit construction** — melleafy treats both patterns identically, but the generated code could in principle match the source pattern more faithfully (e.g., using `@CrewBase`-style resolution in generated code if the source used it). v1 chose uniform output shape; v2 could add a preservation option.
- **Flow `@persist` state semantics** — CrewAI's Flow persistence uses Pydantic models serialised to specific backend locations. v1's stub-based handling is generic; richer support is a v2 concern.
- **Cross-reference validation at inventory time** (§3b) is warn-only. Worth considering whether unresolved `agent:` references in `tasks.yaml` should halt, since they represent broken specs. Argument for halt: clearer user feedback. Argument against: CrewAI itself is lenient. Sticking with warn for v1.
