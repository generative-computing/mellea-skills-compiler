# LangGraph Dialect

**Version**: 1.0.0
**Status**: Fourth dialect doc. First code-first dialect; stress-tests the template against a runtime whose spec is primarily Python code rather than structured text.

**Prerequisite reading**: `spec.md` R1 (detection), R22 (dialect mapping contract), R21 (modality); `plans/dialects/openclaw.md` (reference template); `plans/dialects/letta.md` (single-file-JSON adaptation); `plans/dialects/claude-code.md` (feature-rich Markdown workspace); `plans/generated-package-shape.md` (output shape); `plans/steps/step-1a-inventory.md`, `plans/steps/step-1b-tagging.md`.

---

## What this document does

Describes the concrete rules melleafy applies when processing a **LangGraph** source spec. LangGraph differs fundamentally from the Markdown/JSON dialects: **graph structure, state, nodes, and tools are all Python code**. There is exactly one declarative file in the LangGraph ecosystem — `langgraph.json` — and it exists only for LangGraph Platform deploys; many OSS LangGraph projects have no `langgraph.json` at all.

This dialect doc is the first to confront code-as-spec. The template's Section 2 (File inventory) therefore names **inventory surfaces within Python code** — AST-discoverable patterns — rather than files.

Key LangGraph concepts readers should have in mind:

- **StateGraph**: the graph builder. Accepts a state schema (`TypedDict` or Pydantic model), accumulates nodes and edges, compiles to a runnable graph.
- **State schema**: typically a `TypedDict` with `Annotated[list, add_messages]` fields or similar reducers.
- **Nodes**: Python functions `(state: State) -> State` or `(state: State) -> Command(...)`.
- **Edges**: `add_edge(src, dst)`, or conditional `add_conditional_edges(src, router_fn, {"label": "dst"})`.
- **Compile-time configuration**: `interrupt_before=[...]`, `interrupt_after=[...]`, `checkpointer=...`, `store=...`.
- **Runtime invocation**: `graph.invoke(state, config)`, `graph.stream(...)`, `graph.astream_events("v2", ...)`.
- **`langgraph.json`**: optional declarative manifest for LangGraph Platform deploys — names the graph entry points, dependencies, env, checkpointer, store config.

---

## 1. Detection signals

| Signal | Strength | Notes |
|---|---|---|
| `langgraph.json` present in workspace | strong | The only declarative LangGraph file; presence is unambiguous |
| Python file containing `from langgraph.graph import StateGraph` | strong | The canonical import; defining signal |
| Python file containing `Annotated[..., add_messages]` | strong | LangGraph-specific state-reducer idiom |
| Python file containing `StateGraph(<X>)` constructor call | strong | Graph-definition pattern |
| Python file referencing `checkpointer`, `Checkpointer`, or `MemorySaver` | medium | Characteristic of LangGraph persistence |
| Python file referencing `interrupt_before=[...]` or `interrupt(...)` | medium | Human-in-the-loop pattern |
| Python file referencing `Command(goto=...)` | medium | LangGraph-specific control flow |
| Python file referencing `Send(...)` API | medium | Dynamic branching |
| Python file referencing `BaseStore`, `InMemoryStore`, or `PostgresStore` | medium | LangGraph Store (long-term memory) |
| Import of `langgraph.prebuilt` | weak | Prebuilt agents; not definitive but suggestive |

**Disambiguating from other code-first runtimes.** Other v1-supported code-first runtimes (AutoGen, OpenAI Agents SDK, smolagents) have distinct imports:
- `from autogen_agentchat import ...` → AutoGen
- `from agents import ...` (with Agent SDK conventions) → OpenAI Agents SDK
- `from smolagents import CodeAgent, ToolCallingAgent` → smolagents

A spec containing both LangGraph and one of these other runtimes' imports is Hybrid.

**Precedence note.** R1 tiebreak order puts LangGraph after CrewAI but before AutoGen and others. In practice, LangGraph's signals (`StateGraph`, `add_messages`) are highly distinctive — `StateGraph` appears in no other runtime. Signal-count ties are rare.

**Hybrid threshold.** A project that uses LangGraph for orchestration and CrewAI for crew definitions is a plausible Hybrid. A project that imports both `langgraph` and `autogen_agentchat` is either Hybrid or one is a peripheral test file — melleafy's default is Hybrid; user can override.

**Handling the "no langgraph.json" case.** When `langgraph.json` is absent, detection relies entirely on Python-file imports. Step 1a's workspace traversal reads all `.py` files (subject to the 50 MB cap) and Step 0 scans their imports. The primary spec is the file the user passed to melleafy on the command line — it must contain at least one strong LangGraph signal.

---

## 2. Inventory surfaces (Step 1a, Step 1b)

The template's Section 2 normally describes "files to read." For LangGraph, it describes **inventory surfaces** — AST patterns melleafy discovers inside Python files. Step 1a reads all Python files; Step 1b's section-discovery pass walks the AST to locate surfaces.

### 2a. The declarative surface: `langgraph.json` (if present)

When `langgraph.json` exists, it's parsed fully per its documented fields. This is the only non-code surface for LangGraph specs.

| JSON path | Role in spec | Inventory action |
|---|---|---|
| `graphs.<n>` | Names the graph entry point as `./path:var_name` | Drives which Python file is primary; becomes C8 metadata |
| `dependencies[]` | Python package requirements | Each becomes C8 element |
| `python_version` | Target Python version | C8 element |
| `env` | Either dict, `.env` path, or list of var names | C7 elements |
| `dockerfile_lines[]` | Dockerfile addenda | C8 elements |
| `pip_config_file` | pip config override | C8 element |
| `docker_compose_file` | External docker-compose reference | C8 element |
| `api_version` | Platform API version pin | C8 element |
| `checkpointer` | Checkpointer config (TTL, serde) | C4 element; `delegate_to_runtime` |
| `store` | Store config (index/embeddings) | C5 element; `delegate_to_runtime` |
| `auth` | Auth handler as `"pkg:obj"` reference | C2 element |
| `http` | HTTP-server config | C8 element |
| `webhooks` | Webhook definitions — LangGraph Platform feature | C9 element (event_triggered); `delegate_to_runtime` |
| `encryption` | Encryption config for stored state | C7-adjacent; C8 element |

**Rule 2a-1**: `langgraph.json` may be absent. When absent, every entry above that would have a value is *inferred from code signals* where possible — e.g., `checkpointer` inference from `.compile(checkpointer=...)` calls, `store` from `BaseStore` references. Inferred entries are marked with `source_of_decision: "inferred"` in `inventory.json`.

### 2b. The code surfaces

These are the AST patterns Step 1b's section-discovery pass identifies in each Python file. Each pattern produces one or more elements; exactly what category and tag depends on the pattern.

| Pattern | Role | Category | Typical tag |
|---|---|---|---|
| `StateGraph(<T>)` constructor call | Entry point for graph structure | — | `ORCHESTRATE` |
| TypedDict/Pydantic class used as graph state `<T>` | State schema | — | `SCHEMA` |
| `Annotated[<type>, <reducer>]` field in state schema | Field with reducer (e.g., `add_messages`) | — | `SCHEMA` (with metadata about the reducer) |
| Named function `def <n>(state: State) -> State` added to graph via `add_node` | A graph node | C1/C2/C6 depending on purpose | `EXTRACT`, `CLASSIFY`, `TRANSFORM`, etc. |
| Function returning `Command(goto=..., update=...)` | Node with dynamic control flow | — | `ORCHESTRATE` |
| `add_edge(src, dst)` call | Static edge | — | `ORCHESTRATE` |
| `add_conditional_edges(src, router, {...})` call | Conditional edge + router function | — | `ORCHESTRATE` + `DECIDE` for the router |
| `.compile(interrupt_before=[...])` | Compile-time review-gated points | — | Modality signal (see §5) |
| `.compile(interrupt_after=[...])` | Same | — | Same |
| `.compile(checkpointer=...)` | Checkpointer binding | C4 | `ORCHESTRATE` |
| `.compile(store=...)` | Store binding | C5 | `ORCHESTRATE` |
| `interrupt(<payload>)` call inside a node body | Dynamic review-gated pause | — | Modality signal |
| `@tool` decorator on a function | Tool declaration | C6 | `TOOL_TEMPLATE` |
| `BaseTool` subclass | Tool declaration | C6 | `TOOL_TEMPLATE` |
| `Send(node, state_fragment)` in a router | Dynamic branching | — | `ORCHESTRATE` |
| Prompt template strings (in node bodies) | Prompt content | C1/C2 depending on content | `CONFIG` or inline inside node |
| `from X import tool_name` where `X` is an MCP/adapter package | External tool import | C6 | `TOOL_TEMPLATE` (delegate) |

### 2c. Section discovery for Python code

Step 1b's section-discovery pass (plans/steps/step-1b-tagging.md §3a) walks the AST to identify candidate element boundaries. For LangGraph, the pass runs these discovery queries on each Python file:

1. All `ast.Call` nodes where the callable is `StateGraph`.
2. All `ast.ClassDef` referenced as the State type of a StateGraph.
3. All `ast.FunctionDef` referenced in `add_node` calls.
4. All `ast.Call` nodes with `.add_edge`, `.add_conditional_edges`, `.compile` method names.
5. All `ast.Call` nodes whose callable resolves to `@tool` decoration or `BaseTool` subclass instantiation.

Each discovered pattern becomes a candidate boundary with `rough_kind` set appropriately (`schema`, `node`, `edge`, `tool`, `compile_config`). Step 1b's element-refinement pass then processes each candidate individually — exactly the same flow as for Markdown, just with Python-derived boundaries.

**Rule 2c-1**: AST walking is the *only* source of boundaries for LangGraph. Step 1b does not attempt to split Python source files at arbitrary line boundaries — that would produce half-expressions and fragment nodes. AST-derived boundaries respect the syntax tree.

### 2d. Source lines convention for code

LangGraph elements use a Python-aware `source_lines` format:

- `"py:<line_start>-<line_end>"` — a contiguous range of source lines corresponding to an AST node
- `"py:<file>:<line_start>-<line_end>"` — when multiple Python files are inventoried (most LangGraph projects have ≥2 files: graph + state)
- `"py:<file>:<func_name>"` — shorthand for "the full body of the named function/class"

This is a third `source_lines` convention, joining Letta's `json:<path>` and Claude Code's `frontmatter.<field>`. Step 1b is aware of all three. See the ratification notes for the formalisation task.

### 2e. Multi-file LangGraph projects

A real LangGraph project typically has:

- `graph.py` — defines the StateGraph, nodes, compile call
- `state.py` — defines the TypedDict
- `tools.py` — defines tools
- `prompts.py` — prompt templates as string constants
- `langgraph.json` — if deployed to LangGraph Platform

Melleafy's Step 1a reads all Python files in the workspace; each is inventoried per the surfaces above. Cross-file references (e.g., `graph.py` imports `State` from `state.py`) are resolved by the AST walker using standard Python import semantics — the inventory records the originating file for each element regardless of where the graph is assembled.

**Rule 2e-1**: the *primary spec file* passed on the command line becomes the "entry-point file" — the one that builds the StateGraph. Other Python files in the workspace are "supporting files." Step 1b inventories all of them, but the mapping report in Step 5 distinguishes entry-point from supporting contributions.

**Rule 2e-2**: files not reachable from the primary spec's import graph are **still inventoried** (melleafy is conservative about file scope). They appear in the report with a note that they're unreachable. This protects against accidentally omitting relevant files due to lazy imports or dynamic imports.

### 2f. Python file discovery and limits

- Step 1a's 50 MB workspace cap applies.
- Python files over 10 MB are rejected (unlikely for a LangGraph spec, but the limit exists).
- `__pycache__`, `.venv`, `venv`, `env`, `.pytest_cache`, `node_modules` are skipped per Step 1a §1a.4.
- Test files matching `test_*.py` or `*_test.py` are inventoried but marked with `role: "test"` — they're typically not part of the spec, though they may contain fixtures melleafy can learn from.

### 2g. Supporting files (non-Python)

| File | Role | Inventory action |
|---|---|---|
| `pyproject.toml` / `requirements.txt` / `setup.py` | C8 dependencies | Parse; elements per package |
| `.env` / `.env.example` | C7 credentials | Parse; one element per var |
| `README.md` (if present) | Free-form notes | NO_DECOMPOSE unless spec references it |
| `.mcp.json` (rare but possible) | C6 MCP tools | Inventoried if present — LangGraph can consume MCP via adapter libraries |

---

## 3. Structured-content rules

LangGraph has two kinds of structured content: JSON (`langgraph.json`) and Python source.

### 3a. `langgraph.json` parsing

Parsed with `json.loads`. Schema validation is permissive: only `graphs` is strictly required (and even that's only required when deploying). Unknown fields are preserved and surfaced in the mapping report's "Detected but not handled" section.

**Rule 3a-1**: the `env` field accepts three shapes (dict, `.env` path string, list of var names). Each shape is handled:

- dict → each key-value becomes a C7 element with literal default
- `.env` path → read the referenced file, parse for var names
- list of strings → each string is a var name with no default

Melleafy normalises all three into the same C7 element shape in `inventory.json`.

### 3b. Python AST parsing

Melleafy uses Python's `ast` module to parse `.py` files. Syntax errors are recoverable at the file level — if `graph.py` fails to parse, other Python files still inventory. The failed file is recorded in the inventory report with `status: "syntax_error"` and the error position. The mapping report names which file failed.

**Rule 3b-1**: melleafy does not attempt to repair broken Python source. If the primary spec has a syntax error, Step 0's detection may succeed (based on other Python files) but Step 1b will fail to produce a complete inventory. This manifests as a coverage-threshold halt in Step 1b's cross-checks.

### 3c. Docstring and comment handling

Python function and class docstrings *are* inventoried content. Module-level docstrings describe the spec's overall intent; function docstrings describe node purposes. Both become part of the `content_full` for the element containing them.

Comments (`# ...`) are *not* inventoried. They're developer-targeted explanation, not spec content. A comment like `# TODO: refactor this` is not meaningful to melleafy's downstream tagging.

### 3d. Type annotations

Type annotations on function parameters and return types *are* inventoried. A node with signature `def extract(state: ExtractState) -> ExtractState` tells Step 1b the state types involved, which informs schema mapping decisions. Type hints are read from `typing` and `Annotated` forms specifically.

---

## 4. Dialect mapping table

| Source signal | Category | Default disposition | Generation target |
|---|---|---|---|
| `StateGraph(<T>)` construction | — | `bundle` | Skipped — state-graph assembly is conceptually replaced by Mellea pipeline, not reproduced |
| State TypedDict / Pydantic class (`<T>`) | — | `bundle` | `schemas.py:<ClassName>` — the state schema becomes a Mellea Pydantic model |
| State field with `Annotated[list, add_messages]` | — | `bundle` | `schemas.py` field with a standard `list[Message]` type; the reducer is not reproduced |
| State field with other reducer (`operator.add`, custom) | — | `bundle` with warning | Same; reducer behavior not reproduced — listed in "Runtime-specific constructs not reproduced" |
| Node function body referencing prompt strings | C1 / C2 | `bundle` | `config.<NODE>_PROMPT` constant + `m.instruct()` call in `pipeline.py` |
| Node function body with typed structured output | — | `bundle` | `@generative` slot or `m.instruct(format=Schema)` in pipeline |
| Node function body returning `Command(goto=X, update=Y)` | — | `bundle` | Plain Python control flow in `pipeline.py` — `goto` translates to explicit sequencing |
| Router function used in `add_conditional_edges` | — | `bundle` | `pipeline.py` function with `DECIDE`-tagged semantics |
| `add_edge(src, dst)` call | — | *(not reproduced)* | Implicit in pipeline sequencing |
| `add_conditional_edges(src, router, {label: dst, ...})` | — | `bundle` | `pipeline.py:if/elif/else` chain based on router output |
| `.compile(interrupt_before=[...])` | C2 + modality | `delegate_to_runtime` | Modality classification (see §5); SETUP.md §7 documents checkpointer requirement |
| `.compile(interrupt_after=[...])` | Same | Same | Same |
| `interrupt(<payload>)` dynamic call | Same | Same | `constrained_slots.py:resume_point` stub; SETUP.md §7 |
| `.compile(checkpointer=...)` | C4 | `delegate_to_runtime` | `constrained_slots.py:load_checkpoint, save_checkpoint`; SETUP.md §4 |
| `.compile(store=BaseStore(...))` | C5 | `delegate_to_runtime` | `constrained_slots.py:store_get, store_put`; SETUP.md §5 |
| `@tool`-decorated function body | C6 | `real_impl` (if Python concrete) | `tools.py:<tool_name>` |
| `BaseTool` subclass with `_run` method | C6 | `real_impl` | `tools.py:<tool_name>` |
| Tool imported from `langchain_community.tools` | C6 | `stub` (v1 doesn't bundle langchain_community) | `constrained_slots.py:<tool_name>`; SETUP.md §8 |
| `Send(<node>, <state>)` in a router | — | `bundle` | `pipeline.py` parallel execution via `asyncio.gather` or ordered for-loop (semantics preserved) |
| `langgraph.json:dependencies[]` | C8 | `bundle` | Appended to `pyproject.toml:dependencies` |
| `langgraph.json:env.<VAR>` (dict form) | C7 | `external_input` | `.env.example` with the declared default |
| `langgraph.json:env` as `.env` path | C7 | `external_input` | `.env.example` generated from the referenced `.env` |
| `langgraph.json:env[]` (list form) | C7 | `external_input` | `.env.example` with empty defaults |
| `langgraph.json:auth.path` | C2 | `delegate_to_runtime` | `constrained_slots.py:auth_handler`; SETUP.md documents the auth object shape |
| `langgraph.json:http.*` config | C8 | `bundle` | `config.HTTP_CONFIG` dict |
| `langgraph.json:webhooks[]` | C9 (event_triggered) | `delegate_to_runtime` | `handlers/` directory with per-webhook stubs; SETUP.md §7 |
| `langgraph.json:checkpointer` config | C4 | `delegate_to_runtime` | Same as compile-time checkpointer |
| `langgraph.json:store` config | C5 | `delegate_to_runtime` | Same as compile-time store |
| `langgraph.json:encryption` | C7 | *(not reproduced)* | v1 doesn't reproduce checkpointer encryption; listed in not-reproduced |
| `langgraph.json:dockerfile_lines[]` | C8 | *(not reproduced)* | Listed in "Detected but not handled" — v1 produces pure-Python packages |
| LangGraph Platform cron reference (POST /runs/crons) | C9 (scheduled) | `delegate_to_runtime` | Noted in SETUP.md §6; v1 generates the pipeline, not the cron registration |
| Module-level docstring | C1 | `bundle` (if describes agent intent) | `config.AGENT_DESCRIPTION` |
| Node function docstring | C1 per node | `bundle` | Docstring preserved on generated `@generative` slot or pipeline helper |

**Override semantics.** Default dispositions can be overridden via `--dependencies=ask` or `config:<path>` per the standard R22 contract.

**Rule 4-1**: the "state graph" concept itself is not reproduced. Melleafy's generated pipeline is a sequential/branching Python function, not a `StateGraph`-equivalent. The mapping semantically translates `add_node(X, fn)` + `add_edge(X, Y)` into "call `fn` then call `fn_Y` in `run_pipeline`." This is a **semantic translation**, not a structural mirror — and the mapping report's Provenance appendix documents the translation for each node.

---

## 5. Modality signals (Step 0 Axis 5, R21)

LangGraph's modality signals are largely at the `.compile(...)` call site and the invocation site.

| Signal | Modality classification |
|---|---|
| `graph.invoke(state, config)` in spec body or docstrings | **`synchronous_oneshot`** |
| `graph.stream(...)` or `graph.astream_events("v2", ...)` | **`streaming`** |
| `graph.invoke(..., config={"configurable": {"thread_id": ...}})` + checkpointer | **`conversational_session`** — thread_id + checkpointer is the LangGraph conversational idiom |
| `.compile(interrupt_before=[...])` or `.compile(interrupt_after=[...])` | **`review_gated`** (primary if no other invocation pattern present; secondary if composed with invoke/stream) |
| `interrupt(<payload>)` in node bodies | **`review_gated`** (dynamic form) |
| `langgraph.json:webhooks[]` | **`event_triggered`** (LangGraph Platform only) |
| LangGraph Platform cron (`POST /runs/crons`) | **`scheduled`** (LangGraph Platform only) |
| None of the above | **`synchronous_oneshot`** — the default assumption |

**Composition.** LangGraph is known for the `conversational + review_gated` HITL tutorial pattern — thread_id + checkpointer + `interrupt()`. This is the canonical composition. Melleafy emits it as:
- Primary: `conversational_session`
- Secondary: `review_gated`
- Generated shape: conversational (§5c/§5d of shape doc) with explicit "resume_point" stubs at the interrupt locations

Other compositions:
- **`streaming + review_gated`** — possible but unusual; flag for manual review
- **`scheduled + review_gated`** — Platform-only; awkward (who resumes a cron-fired interrupt?); flag for manual review

**Generated shape per R21.** The four composable primaries that emit to pure Mellea Python are: `synchronous_oneshot`, `streaming`, `conversational_session`, `conversational + memory`. LangGraph's `review_gated` and Platform-only `scheduled`/`event_triggered` are host-needing — they fall back to `synchronous_oneshot` shape with SETUP.md §5/§6/§7 guidance.

### 5a. Checkpointer detection is load-bearing for modality

A LangGraph spec using `thread_id` in invocation configs without a `.compile(checkpointer=...)` call is **non-functional** (threads require a checkpointer to persist). Step 0's modality classifier flags this:

- If `thread_id` is referenced but no checkpointer is declared, classify as `conversational_session` but add a warning: "Spec uses thread_id without a checkpointer declaration. SETUP.md §4 will require configuring one."

### 5b. LangGraph OSS vs LangGraph Platform

Several LangGraph modalities are **Platform-only** (closed-source, license-gated):

- `scheduled` (cron via `POST /runs/crons`)
- `event_triggered` (webhooks via `langgraph.json:webhooks`)

Melleafy records these as detected but classifies them as `delegate_to_runtime`. The generated package doesn't reproduce Platform behavior — the user must host the pipeline on LangGraph Platform to use these modalities, or adapt with an external scheduler/webhook server. SETUP.md §6/§7 names the options.

---

## 6. Quirks and workarounds

### 6a. Graph structure is not reproduced — semantics are

The biggest conceptual gap between LangGraph and Mellea: Mellea has no `StateGraph` equivalent. A LangGraph spec's graph is the structural skeleton — nodes, edges, state — but melleafy generates **sequential Python code with branches** that executes the same semantics.

Example translation:

LangGraph source:
```python
builder = StateGraph(State)
builder.add_node("extract", extract_fn)
builder.add_node("summarize", summarize_fn)
builder.add_edge(START, "extract")
builder.add_edge("extract", "summarize")
builder.add_edge("summarize", END)
graph = builder.compile()
```

Melleafy generated:
```python
def run_pipeline(input: Input) -> Output:
    with start_session() as m:
        state = State(input=input)
        state = _extract(state, m)    # was the "extract" node
        state = _summarize(state, m)  # was the "summarize" node
        return state.output
```

This works for simple linear flows. For branches (via `add_conditional_edges` or `Command(goto=X)`), the translation becomes explicit `if/elif/else` in `pipeline.py`. For `Send(...)` (dynamic parallel), the translation uses `asyncio.gather` or a for-loop.

**Rule 6a-1**: the mapping report's Provenance appendix documents this translation per-graph. A reviewer comparing the source graph to the generated pipeline sees:
- Which node became which Python helper
- Which edge became which sequential/conditional/parallel construct
- Which compile-time options became SETUP.md sections

### 6b. State reducers are behavior, not structure

LangGraph state fields can carry reducers — `Annotated[list, add_messages]` means "when a node returns messages, append them to the list." The most common reducer is `add_messages`; others include `operator.add` for concatenating lists.

**Rule 6b-1**: v1 melleafy does not reproduce reducers. The generated `schemas.py` has a plain `list[Message]` field. Nodes that produced partial state updates (returning `{"messages": [new_msg]}` to be merged) are translated to explicit mutation (`state.messages.append(new_msg)`). This matches semantics for `add_messages` and `operator.add` but not for custom reducers.

**Rule 6b-2**: custom reducers (functions other than `add_messages` and standard operators) are flagged in the mapping report's "Runtime-specific constructs not reproduced" section with their specific reducer name and function signature, so users reviewing can decide whether the explicit-mutation translation is semantically equivalent.

### 6c. No native scheduling or webhooks in OSS

LangGraph's OSS distribution has no scheduling module or webhook handler. These features exist only in LangGraph Platform. A spec that declares `langgraph.json:webhooks` or references Platform cron:

- Is still inventoried (the declarations are spec content)
- Categorised as C9 event_triggered / scheduled
- Default disposition is `delegate_to_runtime`
- SETUP.md §6 / §7 explicitly notes "LangGraph OSS has no scheduler; use external cron or deploy to LangGraph Platform"

### 6d. `thread_id` flows via config, not function argument

LangGraph's conversational pattern uses `config={"configurable": {"thread_id": "..."}}` passed to `invoke`. This is a runtime configuration channel, not a function parameter.

**Rule 6d-1**: melleafy's generated `run_pipeline(session, message)` signature for conversational mode uses a MelleaSession parameter — the analog to LangGraph's thread_id + checkpointer is the session object. The mapping is:

- LangGraph `thread_id` → Mellea `session.id`
- LangGraph checkpointer → Mellea session's chat context storage
- LangGraph `invoke(None, config)` (resume) → not directly expressible; handled via SETUP.md §7 for review-gated specs

### 6e. Subgraphs are Python objects

LangGraph supports subgraphs — one StateGraph used as a node in another. v1 melleafy:

- Inventories each StateGraph definition as its own unit
- For subgraphs used as nodes: the subgraph's nodes are *inlined* into the parent pipeline's node list, prefixed with the subgraph name (e.g., `subgraph_foo.extract`, `subgraph_foo.summarize`)
- Alternatively, if inline-expansion is inappropriate (e.g., subgraph is itself complex), treat as a Deferred Item

**Rule 6e-1**: the decision between inlining and deferring is a Step 2 judgement call (subgraph with fewer than 5 nodes inlines; larger subgraphs defer with a warning). This is a specifically LangGraph-driven Step 2 decision that generalises from the standard Step 2 mapping.

### 6f. `Send` API for dynamic parallelism

The `Send(node, state_fragment)` API lets a router dynamically dispatch parallel branches. Translating to Mellea:

- Static parallelism (known branch count) → `asyncio.gather(...)` in `pipeline.py`
- Dynamic parallelism (branch count derived at runtime) → `asyncio.gather(*[node_fn(s) for s in state_fragments])` with explicit collection

Both translations preserve semantics; the choice is a Step 2 decision based on whether the router is static or dynamic.

### 6g. Checkpointer tables are implementation detail

LangGraph's SQLite checkpointer writes tables `checkpoints` + `writes`; Postgres uses `checkpoints` + `checkpoint_blobs` + `checkpoint_writes`. These are internal schemas melleafy does not need to reproduce. SETUP.md §4 names Mellea-compatible alternatives (in-memory session state for ephemeral use; SQLite or Redis for persistence via user-supplied adapter).

**Rule 6g-1**: if a spec explicitly references the LangGraph checkpointer SQL schema (very rare — typically only in migration scripts), the schema is inventoried but not reproduced. It's listed in "Runtime-specific constructs not reproduced."

### 6h. LangGraph Platform Store namespace semantics

LangGraph Store uses `(namespace_tuple, key) → value` with optional vector indexing. This is a structured store model — richer than a flat key-value. The `namespace_tuple` is typically `(user_id, resource_type)`.

**Rule 6h-1**: v1 melleafy stubs store access in `constrained_slots.py:store_get(namespace_tuple, key)` and `store_put(...)`. The user's adapter implementation can use any backend (Redis, Postgres, or a LangGraph Store if they want). The namespace structure is preserved in the stub signature.

### 6i. Auth object shape

`langgraph.json:auth` references a Python object via `"pkg:obj"` string. The referenced object is typically a callable or class. v1 doesn't execute or introspect the referenced object — melleafy records the reference in `constrained_slots.py:auth_handler` with a SETUP.md §2 note explaining the shape the user must provide.

### 6j. `langchain_community` tool imports

Many real LangGraph projects import tools from `langchain_community.tools` (e.g., `DuckDuckGoSearchRun`). v1 melleafy does not bundle `langchain_community`:

- Tool is inventoried with its class name
- Disposition defaults to `stub`
- `constrained_slots.py` stub includes a SETUP.md §8 note naming the langchain_community class and how the user can wire it

This is intentional — `langchain_community` has many dependencies, some of which are unfree or problematic. v2 may add opt-in bundling.

---

## 7. Reference inventory output (illustrative)

For a minimal LangGraph spec — `graph.py`, `state.py`, and a `langgraph.json`:

### Inventory (abridged)

```json
{
  "elements": [
    {"element_id": "elem_001", "source_file": "state.py", "source_lines": "py:state.py:1-15", "tag": "SCHEMA", "category": "—", "content_summary": "State TypedDict with messages + extracted claims"},
    {"element_id": "elem_002", "source_file": "graph.py", "source_lines": "py:graph.py:10-25", "tag": "EXTRACT", "category": "C1", "content_summary": "extract_claims node: pulls structured claims from input text"},
    {"element_id": "elem_003", "source_file": "graph.py", "source_lines": "py:graph.py:28-42", "tag": "DECIDE", "category": "C2", "content_summary": "route_verified: decides whether claims need additional verification"},
    {"element_id": "elem_004", "source_file": "graph.py", "source_lines": "py:graph.py:60-65", "tag": "ORCHESTRATE", "category": "—", "content_summary": "compile() with MemorySaver checkpointer; interrupt_before=['verify']"},
    {"element_id": "elem_050", "source_file": "langgraph.json", "source_lines": "json:graphs.main", "tag": "CONFIG", "category": "C8", "content_summary": "Primary graph entry: ./graph.py:graph"},
    {"element_id": "elem_051", "source_file": "langgraph.json", "source_lines": "json:env.OPENAI_API_KEY", "tag": "CONFIG", "category": "C7", "content_summary": "Required env var: OPENAI_API_KEY"}
  ]
}
```

### Element mapping (abridged)

```json
{
  "mappings": [
    {"element_id": "elem_001", "target_file": "schemas.py", "target_symbol": "State", "primitive": "bundle"},
    {"element_id": "elem_002", "target_file": "slots.py", "target_symbol": "extract_claims", "primitive": "@generative"},
    {"element_id": "elem_003", "target_file": "pipeline.py", "target_symbol": "_route_verified", "primitive": "decide"},
    {"element_id": "elem_004", "target_file": "constrained_slots.py", "target_symbol": "checkpoint_and_interrupt", "primitive": "stub"},
    {"element_id": "elem_050", "target_file": "config.py", "target_symbol": "GRAPH_NAME", "primitive": "bundle"},
    {"element_id": "elem_051", "target_file": ".env.example", "target_symbol": "OPENAI_API_KEY", "primitive": "external_input"}
  ]
}
```

### Dialect-specific notes in the mapping report

- A "Graph-to-pipeline translation" section showing how each LangGraph node became a Python helper in `pipeline.py`, and which edges became sequential vs conditional vs parallel constructs.
- A "Runtime-specific constructs not reproduced" section listing `operator.add` / custom reducers, `Command(goto=...)` dynamic routing that couldn't be statically traced, `Send` API where parallelism was dynamic, checkpointer SQL schema references.
- A "LangGraph OSS limitations" callout when the spec referenced Platform-only features (scheduling, webhooks).

---

## 8. Deferred LangGraph features (not handled in v1)

- **Subgraph inline-expansion heuristic** (§6e) is a provisional 5-node threshold. Real corpus data may suggest a different rule.
- **Custom state reducers** beyond `add_messages` / `operator.add` — listed in not-reproduced; v2 could emit helper functions that apply the reducer explicitly.
- **`Send` API with fully-dynamic branch counts** — v1 handles static and list-comprehension-driven dynamic cases; truly runtime-determined parallelism (e.g., branch count from an LLM response) is deferred.
- **LangGraph Platform features** — scheduling, webhooks, encryption, auth resolution. These require Platform hosting, outside v1's scope.
- **`langchain_community` tools** — not bundled. User wires via stub.
- **Durable workflows via Temporal** (occasionally used with LangGraph for long-running state) — entirely separate runtime model; not in scope.
- **Streaming events decomposition** — LangGraph's `astream_events("v2")` produces structured events (`on_chain_start`, `on_tool_end`, etc.). V1 emits a simple streaming generator; users who need structured events wire them themselves.
- **Auth callbacks** with complex state — `langgraph.json:auth` is stubbed with a simple signature; richer auth patterns (per-user token refresh, session-bound scopes) are deferred.
- **Dynamic graph construction** — if a spec builds StateGraphs conditionally at runtime (e.g., different graphs for different user tiers), v1 can't statically inventory them all. Listed as Deferred.

---

## 9. Cross-references

- `spec.md` R1, R21, R22 — the contracts this dialect implements
- `plans/dialects/openclaw.md` — template this dialect adapts
- `plans/dialects/letta.md` — JSON-file-source comparison
- `plans/dialects/claude-code.md` — Markdown-workspace comparison
- `plans/steps/step-1a-inventory.md` — file reading; Python files handled per §2f
- `plans/steps/step-1b-tagging.md` — section-discovery pass; AST walking covered in §3a
- `plans/generated-package-shape.md` — shape of the generated output
- `glossary.md` — `dialect`, `disposition`, `interaction modality`
- `melleafy.json` schema — the manifest fields this dialect populates

---

## 10. Ratification notes

This dialect doc v1.0.0 was the fourth drafted. Selection was deliberate: LangGraph is the first code-first dialect, and its template-fit validates (or challenges) the 10-section shape against a fundamentally different source-spec model.

**What the template survived unchanged:**
- Section 1 (Detection signals) — worked identically. Signal counting doesn't care whether signals are frontmatter fields or Python imports.
- Section 4 (Dialect mapping table) — the four-column shape accommodated AST patterns as "source signals" without restructure. The mapping table is shorter than Claude Code's but conceptually more dense per row.
- Section 5 (Modality signals) — code patterns fit the signal table format. Runtime invocation idioms (`graph.invoke`, `graph.stream`) are just another kind of signal.
- Sections 6–10 — translated directly.

**What the template needed to adapt:**
- **Section 2 (Inventory surfaces)** — became "AST patterns inside Python code" instead of "files in a workspace." The underlying intent (enumerate the source surfaces inventory reads from) is preserved; the surfaces are different. Subsections 2b (code surfaces table) and 2c (section discovery for Python code) are new shape Section 2 needed.
- **Section 3 (Structured-content rules)** — became about JSON parsing + Python AST parsing instead of YAML frontmatter. The intent (specify how structured content is read and validated) is preserved.
- **Source lines convention (§2d)** — introduced `py:<file>:<range>` as a third format alongside Letta's `json:<path>` and Claude Code's `frontmatter.<field>`. Three data points now; worth formalising.

**What this tells us about template generality.** The template fits code-first runtimes as well as text-first ones, provided Section 2 is understood as "enumerate the inventory surfaces" rather than "list the files to read." The source-surface abstraction is the template's actual contract. This is a useful reframing for the remaining code-first dialects (AutoGen, OpenAI Agents SDK, smolagents).

Open questions:

- **§2c AST section discovery** specifies a fixed list of discovery queries. Real LangGraph specs may use patterns the list doesn't cover (e.g., a metaprogramming trick that generates nodes dynamically). Step 1b's refinement pass would fall back to treating unmatched code as prose, which is a lossy default. Worth corpus-testing.
- **§4 mapping table** translates graph structure to sequential/branching Python. The semantic translation is straightforward for linear flows; for complex control flow (many `Command(goto=...)` with state-dependent targets, or deeply nested conditional edges), the translation could become unreadable. Worth a worked example with a non-trivial graph.
- **§6b custom reducers** — v1 doesn't reproduce them. For a spec where a custom reducer is load-bearing (e.g., a set-union reducer that deduplicates), the translation is incorrect. Worth making this a hard warning, not just "listed in not-reproduced."
- **§6e subgraph inlining at 5-node threshold** is a guess. Real corpus data may show the right threshold is 3 or 10. Also, subgraphs that are reused multiple times (once as a node in graph A, once as a node in graph B) shouldn't be inlined at all — they're sharing, which inlining would duplicate. Worth revisiting.
- **§5b OSS vs Platform modalities** handles Platform-only features cleanly but the SETUP.md §6/§7 message is generic. Real LangGraph users targeting Platform may want more specific guidance (which exact Platform features they're giving up by using melleafy). Worth detailed SETUP.md templates per Platform feature.
- **`source_lines` format proliferation** (`py:`, `json:`, `frontmatter.`) now has three variants. Formalising as a structured `source_range: {"format": "line_range" | "json_path" | "frontmatter_field" | "py_function", "value": "..."}` is probably the right fix in Step 1b's next iteration. Cross-dialect cleanup item.
- **Syntax error handling** (§3b) — a syntax error in the primary spec file is essentially unrecoverable in v1. Worth considering whether melleafy should suggest `black` or `ruff --fix` as a pre-processing step for near-valid files.
