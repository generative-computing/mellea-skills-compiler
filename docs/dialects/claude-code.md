# Claude Code Dialect

**Version**: 1.0.0
**Status**: Third dialect doc. Stress-tests the template against the most feature-rich runtime in the v1 supported set — multiple skill locations with precedence, upward-walking CLAUDE.md, structured settings JSON, nine-plus hook events, subagents, MCP, session-scoped scheduling, plugin manifests.

**Prerequisite reading**: `spec.md` R1 (detection), R22 (dialect mapping contract), R21 (modality); `plans/dialects/openclaw.md` (reference template); `plans/dialects/letta.md` (the second dialect, for comparison); `plans/generated-package-shape.md` (output shape).

---

## What this document does

Describes the concrete rules melleafy applies when processing a **Claude Code** source spec. Claude Code is a **strict superset of the Agent Skills open standard** — every field in Agent Skills std works, plus roughly a dozen Claude Code extensions. In the v1 supported runtime set, Claude Code is the most widely used and the most feature-rich.

Key Claude Code concepts readers should have in mind:

- **Skill locations with precedence**: managed > user (`~/.claude/skills/`) > project (`.claude/skills/`) > plugin.
- **CLAUDE.md hierarchy**: project CLAUDE.md, private `CLAUDE.local.md` (ignored), user-level `~/.claude/CLAUDE.md`, walked upward from the spec directory to the repo root.
- **`@path/file` imports**: resolve recursively to depth 5.
- **Settings JSON**: `.claude/settings.json`, `.claude/settings.local.json`, `~/.claude/settings.json` (plus managed). Contains `permissions`, `env`, `hooks`, `mcpServers`, `defaultMode`.
- **Subagents**: `.claude/agents/*.md` — nested agent specs with their own frontmatter.
- **Plugin manifests**: `.claude-plugin/plugin.json` (required `name`), `.claude-plugin/marketplace.json`.
- **Slash commands and skills have merged** — both create `/name`, share the same frontmatter; when both exist the skill wins.

---

## 1. Detection signals

Step 0 classifies a spec as Claude Code when signals match. Because Claude Code is a superset of Agent Skills std, careful distinction is needed — a spec with *only* Agent Skills fields belongs to that runtime, not Claude Code.

| Signal | Strength | Notes |
|---|---|---|
| `.claude/` directory present in workspace root or any ancestor | strong | The defining artefact — presence indicates Claude Code environment |
| Frontmatter field `disable-model-invocation` | strong | Not in Agent Skills std; Claude Code–specific |
| Frontmatter field `user-invocable` | strong | Claude Code–specific |
| Frontmatter field `context: fork` | strong | Subagent context forking — Claude Code–specific |
| Frontmatter field `agent:` (subagent reference) | strong | Claude Code–specific |
| Frontmatter field `hooks:` at skill level | strong | Skill-scoped hooks — Claude Code extension of Agent Skills |
| Frontmatter field `paths:` (glob list for auto-load) | strong | Claude Code–specific |
| Frontmatter field `shell: bash \| powershell` | medium | Claude Code has this field; no other Tier-1 runtime does |
| Frontmatter field `argument-hint` or `arguments` | medium | Slash-command-specific fields |
| Frontmatter field `model:` | medium | Model pinning; Claude Code–specific in skills |
| Frontmatter field `effort:` | medium | Reasoning-effort pinning |
| Spec file is under `.claude/skills/`, `.claude/commands/`, or `.claude/agents/` | strong | Canonical Claude Code locations |
| `.claude/settings.json` present anywhere in workspace | strong | Settings JSON is always present in real Claude Code projects |
| `.mcp.json` present | medium | Also used by some non-Claude-Code MCP clients, but common in Claude Code |
| `.claude-plugin/plugin.json` present | medium | Plugin manifest; Claude Code–specific |
| `CLAUDE.md` file present at any level | medium | Not uniquely Claude Code (projects sometimes include it as convention) but strongly suggestive in combination |

**Disambiguating from Agent Skills std.** If the *only* matching signal is `SKILL.md` with standard frontmatter (`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`), and no Claude-Code-specific fields or locations, classify as Agent Skills std. Presence of any Claude Code extension (field or location) elevates to Claude Code.

**Precedence note.** Per R1's tiebreak order: Agent Skills std > Claude Code. If signal counts are exactly equal, Agent Skills std wins. But in practice the extension-field signals are "strong" and typically tip the count clearly toward Claude Code.

**Hybrid threshold.** A Claude Code project that also uses OpenClaw (as a development harness while targeting a different runtime) is a plausible Hybrid. Signals within 1 of another runtime trigger Hybrid per R1.

---

## 2. File inventory rules (Step 1a)

Claude Code's workspace is richer than OpenClaw's — more distinct file roles, upward directory walking, and multiple skill locations with precedence. Step 1a must assemble the full inventory across all these surfaces.

### 2a. Skill / command / agent files (the primary spec)

The primary spec is the `SKILL.md` (or `.md` under `.claude/commands/` or `.claude/agents/`) the user passed on the command line.

| File | Role in spec | Inventory action |
|---|---|---|
| Primary spec file with Claude Code frontmatter | C1 Identity + C2 Operating rules + C6 Tool declarations via `allowed-tools` | Parse frontmatter; body is decomposed per Step 1b |
| `SKILL.md` body | Mixed — depends on content | Decomposed by Step 1b |

**Rule 2a-1**: melleafy reads the spec file exactly once, even if multiple SKILL.md files exist at different precedence tiers. The one passed on the command line wins; others are noted in the report but not inventoried.

### 2b. Upward-walking CLAUDE.md

CLAUDE.md files accumulate rules from every ancestor directory up to the repo root (detected by `.git`) or the user's home directory, whichever comes first.

| File | Role | Inventory action |
|---|---|---|
| `./CLAUDE.md` (sibling to spec) | C1 Identity (project-level) | Read; contribute elements |
| `../CLAUDE.md` | Same | Read; contribute elements |
| Walking upward until repo root | Same | Read each; contribute elements |
| `~/.claude/CLAUDE.md` (user-level) | C3 User facts (user-level defaults) | Read; contribute elements |
| `./CLAUDE.local.md` (private) | — | **Ignore** — Claude Code treats this as user-private, not spec content |
| Managed enterprise CLAUDE.md | — | Detection only; do not inventory — may contain enterprise rules melleafy should not reproduce |

**Rule 2b-1**: the upward walk stops at the first of: the repo root (directory containing `.git`), the user's home directory, or the filesystem root. It does not cross filesystem boundaries.

**Rule 2b-2**: topmost CLAUDE.md (closest to the spec) is "most specific"; `~/.claude/CLAUDE.md` is "most general." When contributing elements to the inventory, more specific CLAUDE.md files' elements get higher `element_id` numbers (because they're read later in the traversal), so source order in `inventory.json` roughly matches specificity.

**Rule 2b-3**: `--add-dir` roots from the Claude Code CLI are **not** inventoried by default. The environment variable `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` would enable this, but melleafy does not honour it in v1 — reading arbitrary directories introduces scope ambiguity. Flagged as a v2 option.

### 2c. `.claude/` directory

The `.claude/` directory lives in the workspace root (or any ancestor, but the closest to the spec wins). It contains:

| File / Path | Role | Inventory action |
|---|---|---|
| `.claude/settings.json` | C2 Operating rules + C7 Credentials + C6 Tools + C9 Scheduling | Parse JSON; each top-level key becomes a source of multiple elements |
| `.claude/settings.local.json` | Same, but user-private | Parse and merge per deep-merge rules; mark merged elements with `source: "local"` |
| `~/.claude/settings.json` | Same, user-level defaults | Parse and merge; mark as `source: "user"` |
| `.claude/agents/*.md` | Subagents — cross-skill references (C10-like, currently deferred) | Record existence; do not fully inventory content in v1 |
| `.claude/skills/<name>/SKILL.md` | Other skills in the project | Detection only — v1 doesn't reproduce multi-skill packages |
| `.claude/commands/*.md` | Other slash commands in the project | Detection only |
| `.claude/hooks/hooks.json` (if plugin-bundled) | C9 Scheduling (event-triggered) + C2 Operating rules | Parse and merge with settings.json hooks |

**Rule 2c-1**: `.claude/settings.local.json` contains user-private overrides. Step 1a reads it but any credentials or workstation-specific paths found are flagged with `sensitive: true` — they must not end up in the generated package's `config.py`.

**Rule 2c-2**: the `defaultMode` field in settings.json is a runtime default for permission mode (`default | acceptEdits | plan | bypassPermissions | auto | dontAsk`). `plan` mode has modality implications (see §5).

**Rule 2c-3**: subagents in `.claude/agents/*.md` are related agent specs. v1 melleafy does not expand them — each is its own spec that should be processed separately. The mapping report records subagent references as cross-skill references in the Provenance appendix.

### 2d. MCP server configuration

| File | Role | Inventory action |
|---|---|---|
| `.mcp.json` in workspace root | C6 Tools (external MCP servers) | Parse; each `mcpServers.<name>` becomes a tool-declaration element |
| `mcpServers` block within `.claude/settings.json` | Same | Merged with `.mcp.json` per settings-merge rules |

**Rule 2d-1**: MCP tools use the naming convention `mcp__<server>__<tool>` when referenced from `allowed-tools` or from the pipeline body. The inventoried element preserves this naming.

**Rule 2d-2**: an MCP server declared in settings but with no `allowed-tools` entry referencing any of its tools is an "unused MCP server." Step 7's cross-reference lint flags this as a warning.

### 2e. Plugin manifests

| File | Role | Inventory action |
|---|---|---|
| `.claude-plugin/plugin.json` | C8 Runtime env (plugin metadata) | Parse; `name`, `version`, `dependencies` become C8 elements |
| `.claude-plugin/marketplace.json` | C8 Runtime env (plugin discovery) | Detection only — v1 does not reproduce marketplace bundling |

### 2f. `@path/file` imports

Claude Code supports `@path/file` references in spec bodies and CLAUDE.md files. These resolve recursively up to depth 5 and the referenced file's content becomes part of the inventory.

**Rule 2f-1**: melleafy resolves `@` references during Step 1a. Each referenced file is added to the file list with `role: "C1/C2/C3 inline import from <source_file>"` (category inferred from referenced file content and the context of the reference).

**Rule 2f-2**: cycles are detected (A imports B, B imports A) and broken — the second encounter of any file is skipped with a warning.

**Rule 2f-3**: depth beyond 5 is also a warning; the 5-deep file is inventoried, deeper imports are not followed.

### 2g. Credential locations

| Location | Platform | Inventory action |
|---|---|---|
| macOS Keychain `Claude Code-credentials` | macOS | **Detection only** — never read from Keychain; never access user credentials |
| `~/.claude/.credentials.json` (mode 0600) | Linux / Windows | **Detection only** — record existence for SETUP.md §2, never read contents |
| `settings.env` in settings.json | Cross-platform | Read the env-var *names*, never the values |
| `apiKeyHelper` script reference in settings.json | Cross-platform | Record existence; never execute |

**Rule 2g-1**: Claude Code's credential resolution order is: cloud provider → `ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY` → `apiKeyHelper` → `CLAUDE_CODE_OAUTH_TOKEN` → subscription OAuth. Melleafy documents this order in SETUP.md §2 for packages whose generated code reads Anthropic credentials; it does not reproduce the resolution logic.

### 2h. Workspace root determination

For Claude Code, the "workspace root" (per Step 1a §1a.1) is the first ancestor directory containing any of: `.claude/`, `.git/`, or the user's home directory. This is distinct from OpenClaw (where workspace = spec's parent) because Claude Code's multi-file structure spans directories.

**Rule 2h-1**: when an ancestor has `.git/` but no `.claude/`, treat the git root as workspace root. This lets melleafy find CLAUDE.md files above the spec.

**Rule 2h-2**: if the spec is outside any git repo and has no `.claude/` ancestor, fall back to the spec's parent directory. Warn in the inventory report that workspace scope may be incomplete.

### 2i. Missing files

Absence handling:

- `.claude/settings.json` absent: normal; the spec may be self-contained. No warning.
- `CLAUDE.md` absent anywhere: normal; not every project has one.
- `.mcp.json` absent: normal; many skills use no MCP servers.
- `.claude-plugin/` absent: normal; most skills aren't plugins.

No Claude Code source file is strictly required beyond the primary spec itself.

---

## 3. Frontmatter rules

Claude Code frontmatter is YAML — same parsing machinery as OpenClaw. The field set is larger.

### 3a. Agent Skills std fields (inherited)

| Field | Source | Notes |
|---|---|---|
| `name` | Agent Skills std | Required; ≤64 chars (quietly changed from 40 in PR #350) |
| `description` | Agent Skills std | Required |
| `license` | Agent Skills std | Optional |
| `compatibility` | Agent Skills std | Optional; free text, ≤500 chars |
| `metadata` | Agent Skills std | Optional dict |
| `allowed-tools` | Agent Skills std (experimental) | Space-separated string; in Claude Code this pre-approves tools (doesn't restrict) |
| `when_to_use` | Community convention | Not in the Agent Skills validator's allow-list; Claude Code treats as description supplement |

### 3b. Claude Code extensions

| Field | Type | Semantics |
|---|---|---|
| `disable-model-invocation` | bool | Skill is never auto-loaded by model; user-invocable only |
| `user-invocable` | bool | Appears as a `/name` command |
| `context: fork` | literal | Creates a forked context (subagent-like) when invoked |
| `agent` | string | Delegate to a named subagent |
| `hooks` | dict | Skill-scoped lifecycle hooks (PreToolUse, PostToolUse, Stop) |
| `paths` | list of glob strings | Auto-load when editing matching files |
| `shell` | `"bash"` \| `"powershell"` | Shell for any bash-tool invocations |
| `argument-hint` | string | Human-readable hint for slash-command arguments |
| `arguments` | list of dicts | Structured arguments for slash commands |
| `model` | string | Pin a model for this skill |
| `effort` | `"low"` \| `"medium"` \| `"high"` | Reasoning effort hint |

### 3c. Subagent frontmatter

Files under `.claude/agents/*.md` have additional fields:

| Field | Type | Semantics |
|---|---|---|
| `tools` | list | Tool allowlist (NOT the same as `allowed-tools`, which pre-approves) |
| `disallowedTools` | list | Explicit denylist |
| `permissionMode` | enum | `acceptEdits` / `plan` / `bypassPermissions` / `default` / `dontAsk` |
| `maxTurns` | int | Cap on turn count |
| `skills` | list | Preloads full skill content (distinct from main sessions, where only descriptions are loaded) |
| `mcpServers` | list | MCP server allowlist for this subagent |
| `memory` | `"user"` \| `"project"` \| `"local"` | Enables persistent `~/.claude/agent-memory/MEMORY.md` |
| `background` | bool | Runs in background |
| `isolation` | literal (`"worktree"`) | Git worktree isolation |
| `color` | string | UI hint |
| `initialPrompt` | string | Initial prompt for the subagent |

**Rule 3c-1**: v1 melleafy does not expand subagents into the generated package. Subagent files are detected and their existence recorded, but their content is not inventoried as part of the primary spec.

**Rule 3c-2**: **plugin-bundled subagents cannot use `hooks`, `mcpServers`, or `permissionMode`** (Claude Code security rule). If these fields appear in a plugin-bundled subagent, Step 1a records the anomaly in the inventory report.

### 3d. Frontmatter parsing and validation

Frontmatter is parsed with `yaml.safe_load`. Claude Code–specific fields are validated against the field set above. Unknown fields are not errors — Claude Code itself accepts them — but they're flagged in the inventory report with `unknown_frontmatter_field: true` for reviewer awareness.

### 3e. Slash command vs skill disambiguation

When a file could be either a slash command (under `.claude/commands/`) or a skill (under `.claude/skills/`), the path determines which it is. If both locations have files with the same name, **skills win** per Claude Code's merge rule. Inventory records the precedence outcome.

---

## 4. Dialect mapping table

This table covers the most common Claude Code source signals. Rows are ordered by the mapping table convention (category within file-type).

| Source signal | Category | Default disposition | Generation target |
|---|---|---|---|
| `name` frontmatter field | — | `bundle` | `pyproject.toml:name`, `README.md` title, `__init__.py:__agent_name__` |
| `description` frontmatter field | C1 | `bundle` | `config.AGENT_DESCRIPTION` |
| `license` frontmatter field | — | `bundle` | `pyproject.toml:license`, `LICENSE` file generated if upstream file exists |
| `compatibility` frontmatter field | C8 | `bundle` | `config.COMPATIBILITY_NOTE`; appears in README |
| `metadata.*` frontmatter fields | — | `bundle` | `config.METADATA` dict |
| `allowed-tools` entries | C6 | Varies per entry type (see below) | `tools.py` or `constrained_slots.py` |
| `allowed-tools` entry `Bash(pattern)` | C6 | `stub` | `constrained_slots.py:run_bash` (shell execution is host-needing) |
| `allowed-tools` entry `Read(path-glob)`, `Write(...)`, `Edit(...)` | C6 | `stub` | `constrained_slots.py:*`; filesystem I/O deferred to host |
| `allowed-tools` entry `WebFetch(domain:*.example.com)` | C6 | `real_impl` | `tools.py:web_fetch` using `requests` with URL allowlist |
| `allowed-tools` entry `mcp__<server>__<tool>` | C6 | `stub` | `constrained_slots.py:<server>_<tool>`; SETUP.md §3 names the MCP server |
| `disable-model-invocation: true` | C2 | *(informational)* | Noted in mapping report; affects Step 2.5b elicitation (can't be user-invocable) |
| `user-invocable: true` | — | `bundle` | `main.py` argparse gets a `--user-invocable-mode` flag (informational) |
| `context: fork` | C1 | *(not reproduced)* | Listed in "Runtime-specific constructs not reproduced" |
| `agent: <name>` | — | *(not reproduced)* | Cross-skill reference; listed as deferred |
| `hooks:` frontmatter dict | C9 (event_triggered) + C2 | `delegate_to_runtime` | Noted in mapping report; `handler.py` skeleton for each hook; SETUP.md §7 |
| `paths:` frontmatter list | — | *(informational)* | Auto-load pattern — noted in README; not reproduced |
| `shell: bash` or `powershell` | C8 | `bundle` | `config.DEFAULT_SHELL`; affects `run_bash` stub if used |
| `argument-hint` / `arguments` | C3 | `external_input` | Pipeline parameter promotion via `main.py` |
| `model: <name>` | C8 | `bundle` | `config.MODEL_NAME`; SETUP.md §3 explains backend-selection |
| `effort: <level>` | C8 | `bundle` | `config.REASONING_EFFORT`; passed through to backend |
| `SKILL.md` body — main content | Varies (C1, C2, C6 mixed) | Decomposed per Step 1b | Various |
| `@path/file` import inside SKILL.md body | Resolved per §2f | Inherits the referenced file's category | Inherited target |
| `CLAUDE.md` file — main content | C1 + C2 | `bundle` | Merged into `config.PREFIX_TEXT` and `requirements.py` rules |
| `CLAUDE.md` imports via `@path` | Resolved per §2f | Inherits | Inherited |
| `~/.claude/CLAUDE.md` content | C3 | `external_input` | User-level context — template suggests pipeline parameter with default |
| `.claude/settings.json:permissions.allow[]` entries | C2 | `bundle` | Informational in `requirements.py` — Claude Code's permission allowlist becomes prose-only guidance (Mellea has no permission system) |
| `.claude/settings.json:permissions.ask[]` entries | C2 + modality | `delegate_to_runtime` | `constrained_slots.py:confirm_action`; drives secondary `review_gated` modality |
| `.claude/settings.json:permissions.deny[]` entries | C2 | `bundle` | `Requirement` with denying `validation_fn` (enforced) |
| `.claude/settings.json:env[]` entries | C7 | `external_input` | `.env.example` entries |
| `.claude/settings.json:hooks[]` entries | C9 (event_triggered) | `delegate_to_runtime` | `handler.py` skeletons; SETUP.md §7 names candidate host |
| `.claude/settings.json:mcpServers[]` entries | C6 | `stub` (unless user overrides) | `constrained_slots.py` stub per MCP tool; SETUP.md §3 names MCP server |
| `.claude/settings.json:defaultMode` | — | `bundle` | `config.DEFAULT_PERMISSION_MODE`; drives modality (see §5) |
| `.mcp.json:mcpServers[]` | C6 | `stub` | Same as settings.json mcpServers |
| `.claude-plugin/plugin.json:name` | — | `bundle` | `pyproject.toml:name` (uses plugin name if spec doesn't override) |
| `.claude-plugin/plugin.json:dependencies[]` | C8 | `bundle` | Appended to `pyproject.toml:dependencies` |
| `.claude-plugin/marketplace.json` contents | — | *(not reproduced)* | Noted; v1 doesn't produce marketplace bundles |
| Hooks event: `PreToolUse`, `PostToolUse`, `Stop`, etc. | C9 (event_triggered) | `delegate_to_runtime` | Per hook, a handler stub; SETUP.md §7 |
| Hooks matcher syntax (tool-name patterns) | — | `bundle` | Copied into handler stub docstrings |
| JSON-on-stdin / exit-code hook contract | C8 | *(informational)* | Documented in SETUP.md §7 |
| `/loop` scheduled task (session-scoped) | C9 (scheduled) | `delegate_to_runtime` | `config.SCHEDULE_CONFIG`; modality = `scheduled`; SETUP.md §6 explains session-scoped limitation |
| Claude Code Routines (cloud cron) | — | *(not reproduced)* | Cloud-managed; no local spec representation |
| Auto-memory `MEMORY.md` (≤200 lines or ≤25 KB injected) | C4 | `delegate_to_runtime` | `constrained_slots.py:recall_memory`; SETUP.md §4 |
| Subagent `memory: user \| project \| local` | C5 | `delegate_to_runtime` | `constrained_slots.py:*`; SETUP.md §5 |
| Subagent cross-reference via `agent:` field | — | *(deferred)* | Noted as cross-skill reference |

**Override semantics.** Default dispositions can be overridden via `--dependencies=ask` or `config:<path>` per the standard R22 contract.

**Rule 4-1**: the distinction between `allowed-tools` (Claude Code pre-approval — doesn't restrict) and subagent `tools` (strict allowlist) matters. Melleafy reads both but treats them differently in the mapping: `allowed-tools` informs which tools to generate; subagent `tools` is not reproduced because subagents aren't expanded in v1.

---

## 5. Modality signals (Step 0 Axis 5, R21)

Claude Code has a richer modality declaration surface than most runtimes because it supports multiple invocation modes simultaneously.

| Signal | Modality classification |
|---|---|
| Spec invoked via `claude -p` / `--print` | **`synchronous_oneshot`** — Claude Code's default headless mode |
| `--output-format stream-json` referenced in spec body | **`streaming`** — same one-shot control flow, incremental output |
| Spec invoked via `--resume` or `--continue` | **`conversational_session`** — JSONL state at `~/.claude/projects/` |
| `/fork` or `--fork-session` referenced | **`conversational_session`** with branching — no v1-distinct modality, but noted in mapping report |
| `permissionMode: "plan"` in settings or subagent | **`review_gated`** as secondary modality (primary depends on other signals) |
| Hooks declared in settings.json or skill frontmatter | **`event_triggered`** as secondary modality |
| `/loop [interval]` referenced or CronCreate tool usage | **`scheduled`** — session-scoped cron |
| None of the above | **`synchronous_oneshot`** — the implicit default |

**Composition.** Claude Code commonly composes modalities:

- **`conversational_session` + `streaming`** — chatbot shape with incremental output. Very common.
- **`synchronous_oneshot` + `review_gated`** — one-shot run that pauses for user approval in plan mode.
- **`event_triggered` + `streaming`** — SessionStart hook that runs a streaming prompt.
- **`scheduled` + `review_gated`** — a `/loop` task that requires approval before tool invocation. Awkward; flag for manual review.

**Generated shape per R21.** The four composable primaries (`synchronous_oneshot`, `streaming`, `conversational_session`, `conversational + memory`) emit to shapes §5a–§5d. The host-needing modalities (`review_gated`, `scheduled`, `event_triggered`) fall back to `synchronous_oneshot` shape with SETUP.md §5/§6/§7 guidance.

### 5a. `defaultMode` interaction

`.claude/settings.json:defaultMode` affects modality as follows:

- `default` → no modality change
- `acceptEdits` → no modality change (behavior, not modality)
- `plan` → `review_gated` secondary — the user reviews a plan before execution
- `bypassPermissions` → no modality change (all permissions auto-approve)
- `auto` → no modality change
- `dontAsk` → no modality change

**Rule 5a-1**: `plan` mode is the only `defaultMode` value that affects modality classification. It adds `review_gated` as a secondary modality; the primary stays whatever it otherwise would have been.

### 5b. `/loop` limitations

Claude Code's `/loop` scheduling is **session-scoped** — tasks persist only for the lifetime of the user's Claude Code session (7-day recurring expiry, 50 tasks max). This is a weaker scheduling contract than OpenClaw (persistent cron) or Letta (server-side persistent schedules).

**Rule 5b-1**: when classifying as `scheduled` modality due to `/loop`, SETUP.md §6 names the limitation explicitly: "Claude Code `/loop` is session-scoped. For production deployment, use an external scheduler (cron, APScheduler, cloud CronJob)."

### 5c. Claude Code Routines

Claude Code Routines are Anthropic-cloud-managed scheduled runs with no local spec representation. **Melleafy cannot target Routines from local spec processing.** If a spec mentions Routines, it's recorded as deferred.

---

## 6. Quirks and workarounds

### 6a. Settings merge order

Settings are read from up to four locations and deep-merged:

1. Managed enterprise settings (if present) — **highest precedence**; do not override
2. `~/.claude/settings.json` (user)
3. `.claude/settings.local.json` (user's project-private overrides)
4. `.claude/settings.json` (project)

For conflicting keys, the higher-precedence source wins. Array-valued keys (e.g., `permissions.allow[]`) are concatenated, not replaced. Permission rules are evaluated in the order **deny > ask > allow** regardless of which file they came from.

Melleafy's inventory preserves the source file for each merged element: `source: "project" | "local" | "user" | "managed"`. This is surfaced in the mapping report so reviewers see where each rule originated.

### 6b. `CLAUDE.local.md` is ignored

`CLAUDE.local.md` is treated by Claude Code as user-private notes that should not be part of the committed spec. Melleafy ignores it entirely — never inventories, never warns about its presence. This is intentional: a user running melleafy on their own machine with `CLAUDE.local.md` containing personal notes should not accidentally ship those notes.

### 6c. `allowed-tools` pre-approves, doesn't restrict

The Agent Skills std `allowed-tools` field means "tools allowed." Claude Code extends the semantics: the list **pre-approves** tools (skipping the approval dialog), but the agent can still use tools not in the list if the user approves at runtime. This is subtly different from a strict allowlist.

**Rule 6c-1**: melleafy treats `allowed-tools` as a set of tools to generate (all appear in `tools.py` or stubs), but does not enforce that only those tools are called. The generated pipeline may invoke additional tools if the source spec body references them. This is intentional — reproducing Claude Code's "pre-approval" semantics exactly would require runtime permission machinery Mellea doesn't have.

### 6d. Subagent plugins can't use hooks/mcpServers/permissionMode

Plugin-distributed subagents (those shipped via `.claude-plugin/plugin.json`) are forbidden from using `hooks`, `mcpServers`, or `permissionMode` fields (Claude Code security rule). Melleafy doesn't generate plugin-distributed anything in v1, but inventory records this invariant in the mapping report when the spec is a plugin-bundled subagent.

### 6e. SDK vs CLI differences

Claude Code has both a CLI (`claude -p ...`) and a Python SDK. Some frontmatter fields are CLI-only:

- `allowed-tools` — CLI pre-approves; SDK ignores
- `shell: bash` vs `powershell` — CLI controls the shell; SDK uses stdlib subprocess

Melleafy produces Mellea Python packages that are SDK-callable. When the source spec declares CLI-only fields, they're recorded in the mapping report's "Runtime-specific constructs not reproduced" section.

### 6f. Auto-compaction dropping context

Claude Code auto-compacts long conversations by dropping older tool outputs then summarising. Invoked skills are re-attached to the summary with a **25,000-token combined budget, first 5,000 tokens per skill, oldest dropped first**. This is a runtime behavior that affects what the agent "sees" during execution.

**Rule 6f-1**: melleafy does not reproduce auto-compaction. The generated Mellea pipeline processes its inputs directly. If the source spec relies on auto-compaction semantics (unlikely but possible for specs explicitly designed to work around it), those behaviors won't match between Claude Code and melleafy-generated output. Noted in the mapping report as an implicit runtime-specific construct.

### 6g. `settings.env` vs `.env`

Claude Code's `.claude/settings.json:env` is a **dict** of env-var definitions embedded in settings JSON. Regular `.env` files are also supported but distinct. Melleafy inventories both:

- `settings.env` — C7 elements recorded with `source: "settings.json"`
- `.env` files — C7 elements recorded with `source: ".env"`

When a variable appears in both, the settings.json version wins (per Claude Code's merge rules).

### 6h. MCP server allowlist per subagent

Subagents have their own `mcpServers` allowlist — a subagent can use a subset of the project's MCP servers. Since v1 doesn't expand subagents, this is recorded but not enforced. If a v2 adds subagent expansion, the per-subagent MCP allowlist would drive which tools are available in each subagent's generated package.

### 6i. `apiKeyHelper` script

Claude Code supports an `apiKeyHelper` script that emits API keys on stdout. This is a credential-resolution mechanism, not a spec field. Melleafy records the reference in the mapping report (as a note in SETUP.md §2) but does not execute the script — executing arbitrary scripts is outside melleafy's scope per security principles.

---

## 7. Reference inventory output (illustrative)

For a minimal Claude Code spec — a single `SKILL.md` with frontmatter, a project `CLAUDE.md`, and a `.claude/settings.json` with some hooks and permissions:

### Inventory (abridged)

```json
{
  "elements": [
    {"element_id": "elem_001", "source_file": "CLAUDE.md", "source_lines": "1-15", "tag": "CONFIG", "category": "C1", "content_summary": "Project-level persona"},
    {"element_id": "elem_010", "source_file": "SKILL.md", "source_lines": "frontmatter.description", "tag": "CONFIG", "category": "C1", "content_summary": "Skill description"},
    {"element_id": "elem_011", "source_file": "SKILL.md", "source_lines": "frontmatter.allowed-tools", "tag": "TOOL_TEMPLATE", "category": "C6", "content_summary": "Tools: Bash, Read, Write"},
    {"element_id": "elem_020", "source_file": "SKILL.md", "source_lines": "25-40", "tag": "ORCHESTRATE", "category": "C2", "content_summary": "Extraction-and-summarisation workflow"},
    {"element_id": "elem_050", "source_file": ".claude/settings.json", "source_lines": "json:permissions.deny[0]", "tag": "VALIDATE_OUTPUT", "category": "C2", "content_summary": "Never run `rm -rf`"},
    {"element_id": "elem_051", "source_file": ".claude/settings.json", "source_lines": "json:hooks.PreToolUse[0]", "tag": "ORCHESTRATE", "category": "C9", "content_summary": "PreToolUse hook: log every tool call"}
  ]
}
```

Note `source_lines` formats: line ranges for Markdown; `frontmatter.<field>` for frontmatter references; `json:<jq-path>` for JSON imports (same convention as Letta dialect §7).

### Element mapping (abridged)

```json
{
  "mappings": [
    {"element_id": "elem_001", "target_file": "config.py", "target_symbol": "PREFIX_TEXT", "primitive": "bundle"},
    {"element_id": "elem_010", "target_file": "config.py", "target_symbol": "AGENT_DESCRIPTION", "primitive": "bundle"},
    {"element_id": "elem_011", "target_file": "constrained_slots.py", "target_symbol": "run_bash", "primitive": "stub"},
    {"element_id": "elem_020", "target_file": "pipeline.py", "target_symbol": "run_pipeline", "primitive": "orchestrate"},
    {"element_id": "elem_050", "target_file": "requirements.py", "target_symbol": "OPERATING_REQUIREMENTS", "primitive": "requirement"},
    {"element_id": "elem_051", "target_file": "handlers/pre_tool_use.py", "target_symbol": "handle_pre_tool_use", "primitive": "delegate"}
  ]
}
```

### Dialect-specific notes in the mapping report

- A "Runtime-specific constructs not reproduced" section listing `context: fork`, `/loop` session-scoped limitations, auto-compaction semantics, `defaultMode: plan`, plugin `.claude-plugin/marketplace.json`.
- A "Settings merge order" note if `.claude/settings.local.json` was present, explaining which settings were overridden.
- An "Upward-walking CLAUDE.md" note listing which ancestor CLAUDE.md files were inventoried.
- A "Hook delegation" note listing which hooks were detected and are stubbed in `handlers/`.

---

## 8. Deferred Claude Code features (not handled in v1)

- **Subagent expansion.** `.claude/agents/*.md` subagents are detected but not inventoried. v2 could expand each into its own generated package linked by cross-reference.
- **Plugin bundling.** `.claude-plugin/plugin.json` is read for metadata but v1 doesn't emit plugin bundles.
- **Marketplace manifests.** `.claude-plugin/marketplace.json` is informational only.
- **Cross-skill references** via `agent:` field or Agent tool invocations — noted but not resolved.
- **`context: fork` runtime behavior** — v1 doesn't reproduce forked contexts.
- **`--add-dir` roots with `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1`** — not honoured in v1.
- **Claude Code Routines** (cloud-managed cron) — no local spec representation; cannot target.
- **Auto-compaction exact semantics** — v1 Mellea packages don't reproduce the token-budget context management.
- **`apiKeyHelper` script execution** — recorded as a reference; v1 never executes user scripts.
- **Permission resolution `deny > ask > allow`** — partially honoured (deny becomes validating `Requirement`; ask becomes `review_gated` stub; allow becomes prose). Full semantics would require runtime permission middleware.

---

## 9. Cross-references

- `spec.md` R1, R21, R22 — the contracts this dialect implements
- `spec.md` Deferred Items — especially harness adapter, native memory backend, cross-skill references
- `plans/dialects/openclaw.md` — template this dialect adapts
- `plans/dialects/letta.md` — a differently-shaped dialect for comparison (single JSON file)
- `plans/generated-package-shape.md` — what the generated package looks like
- `glossary.md` — `dialect`, `disposition`, `interaction modality`
- `melleafy.json` schema — the manifest fields this dialect populates

---

## 10. Ratification notes

This dialect doc v1.0.0 was the third drafted, selected for being the most feature-rich and widely-used runtime in the v1 supported set.

**What the template survived unchanged:**
- Section 1 (Detection signals) — worked identically; the signal-count model accommodates Claude Code's many signals without restructure.
- Section 4 (Dialect mapping table) — the four-column shape accommodates Claude Code's many source signals. The table is the longest among the three dialect docs written so far, but the structure is the same.
- Section 5 (Modality signals) — composition is the biggest workout here; the section's format handles multi-modality well.
- Sections 6–10 — translated directly.

**What the template needed to adapt:**
- Section 2 (File inventory) — became substantially more complex because Claude Code has multiple distinct surfaces (SKILL.md, CLAUDE.md hierarchy, `.claude/` directory, `.mcp.json`, plugin manifests, credentials). The section is organised as nine sub-sections (2a–2i) rather than OpenClaw's handful. The template handled this by allowing Section 2 to have as many sub-sections as needed.
- Section 3 (Frontmatter) — expanded to three sub-sections (Agent Skills inherited, Claude Code extensions, subagent additions) because Claude Code's frontmatter is richer and has field-inheritance semantics. Template accommodated without restructure.
- Section 7 (Reference inventory output) — uses the same `source_lines` convention extensions as Letta (`json:<path>`, `frontmatter.<field>`). These are now two data points for formalising the convention in Step 1b.

**What this tells us about template generality.** Three dialects (OpenClaw, Letta, Claude Code) with three different source shapes — Markdown workspace, single JSON file, Markdown workspace with upward-walking directory structure — all fit the 10-section template. The template is sufficiently general for the Tier-1 runtimes.

Open questions:

- **§2b upward-walking CLAUDE.md** stops at the git repo root. For monorepo setups with multiple projects in one git repo, this could over-inventory (reading CLAUDE.md files from sibling project directories). v1 accepts this; v2 could add a `--workspace-scope=skill|project|repo` flag. Flagged for later.
- **§4 mapping table for `allowed-tools`** categorises each tool pattern type (`Bash(...)`, `Read(...)`, `WebFetch(...)`, `mcp__...`) into disposition defaults. The Bash/Read/Write/Edit tools default to `stub` because shell/filesystem execution is host-needing; `WebFetch` defaults to `real_impl` because HTTP fetching is Python-native. This asymmetry is deliberate but worth corpus-testing — real Claude Code specs may have patterns the table doesn't cover (e.g., `Notebook*` tools).
- **§5a `defaultMode: plan` affecting modality** — I classified this as adding `review_gated` secondary. Alternative: `plan` is a behavior (not modality) and shouldn't affect classification. Defensible both ways; sticking with the modality interpretation because the generated package's control flow would genuinely differ (emit a "plan preview" step) — which is a modality-level choice.
- **§6c `allowed-tools` pre-approval semantics** — I deliberately chose to not enforce the "only these tools" interpretation because Mellea has no permission machinery. This means generated packages may call tools the user hasn't "pre-approved," which is subtly different behavior from the source spec. Worth highlighting in README prominently.
- **§2f `@path/file` imports recurse to depth 5** — matches Claude Code's own limit. Cycle detection is specified; total-file-count limits are not. A deeply-connected spec could pull in many files. Step 1a's 50 MB workspace cap acts as a backstop.
- **Subagent `skills:` preloading** is a distinctive Claude Code feature — subagents see full skill content, not just descriptions. Since v1 doesn't expand subagents, this is deferred, but it could affect how melleafy handles multi-skill packages in v2.
- **§2g credentials handling** lists platforms separately. The underlying resolution order (§2g rule 2g-1) is common across platforms; the difference is only storage location. Could be simplified to "detection only; platform-specific" without losing information.
