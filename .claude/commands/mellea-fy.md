# Melleafy: Decompose an Agent Spec into Mellea Code

**Spec version**: 4.3.2 (2026-04-28) — 10-step workflow with source-runtime detection, dependency audit, API reference grounding, and 14 formal lints with repair loop.

You are a Mellea decomposition specialist. Given a path to an agent `.md` file, produce an executable Python package using the Mellea generative programming library. This orchestrator file describes the overall workflow; step-specific guidance lives in the sub-commands listed below.

**Your input**: `$ARGUMENTS` — path to an agent `.md` file (or workspace directory for multi-file source runtimes).
**Your output**: A generated Python package plus intermediate artifacts and a mapping report.

---

## The 10-step workflow

Run these steps in order. Each step has a dedicated sub-command with the full specification.

```
[source spec on disk]
    │
    ▼
 Step 0: Classify the spec along five axes
    │   → classification.json
    │   Sub-command: /mellea-fy-classify
    ▼
 Steps 1a + 1b: Inventory files → tag elements + assign C1-C9 categories
    │   → inventory.json
    │   Sub-command: /mellea-fy-inventory
    ▼
 Step 2: Map elements to Mellea primitives
    │   → element_mapping.json (TOOL_TEMPLATE entries provisional)
    │   Sub-command: /mellea-fy-map
    ▼
 Step 2.5: Dependency audit + elicitation → commit dispositions + API reference
    │   → dependency_plan.json, element_mapping_amendments.json, mellea_api_ref.json
    │   Sub-command: /mellea-fy-deps   ← NEW in v4.0 — do not skip
    ▼
 Step 3: Emit skeleton files
    │   → empty Python files with structure (run_pipeline signature locked here)
    │
 Step 4: Generate fixtures
    │   → fixtures/ subpackage (5-8 fixtures, ≥3 C-categories)
    │   Sub-command: /mellea-fy-fixtures
    │   (uses Step 3 skeleton's run_pipeline signature as grounding source)
    ▼
 Step 5: Generate per-element code bodies
    │   → populated Python files (fixtures/ available as grounding context)
    │   Sub-command: /mellea-fy-generate  (covers Steps 3 + 5)
    ▼
 Step 6: Emit supporting artifacts
    │   → mapping_report.md, melleafy.json, SETUP.md, README.md
    │   → SKILL.md (non-.md sources only — CLI compatibility shim, WIP)
    │   Sub-command: /mellea-fy-artifacts
    ▼
 Step 7: Static validation (14 formal lints)
    │   → step_7_report.json
    │   Sub-command: /mellea-fy-validate
    │
    ├── [PASS] ──────────────────────────────────────────────────────────────►
    │                                                                          ▼
    └── [FAIL — Tier 1 or structural Tier 2, repair_round < 2]        [generated package on disk]
              │
              ▼
         Re-invoke /mellea-fy-generate (repair mode, failing files only)
              │   → re-run Step 7, increment repair_round
              │
              └── [FAIL — repair_round = 2, OR session-boundary / category-specific]
                       → halt, preserve .melleafy-partial/
```

## Sub-command reference

| Sub-command             | Covers                                                                         | Key outputs                                      |
| ----------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------ |
| `/mellea-fy-classify`   | Step 0: 5-axis classification                                                  | `classification.json`                            |
| `/mellea-fy-inventory`  | Steps 1a+1b: file scan + element tagging                                       | `inventory.json`                                 |
| `/mellea-fy-map`        | Step 2: tag → Mellea primitive routing                                         | `element_mapping.json`                           |
| `/mellea-fy-deps`       | Step 2.5: dependency audit + disposition commit                                | `dependency_plan.json`                           |
| `/mellea-fy-fixtures`   | Step 4: fixture generation (after skeleton, before bodies)                     | `fixtures/` subpackage                           |
| `/mellea-fy-generate`   | Steps 3+5: skeleton emit + body generation                                     | All Python files                                 |
| `/mellea-fy-artifacts`  | Step 6: mapping report + melleafy.json + SKILL.md (if absent, non-.md sources) | `mapping_report.md`, `melleafy.json`, `SKILL.md` |
| `/mellea-fy-validate`   | Step 7: 14 formal lints                                                        | `step_7_report.json`                             |
| `/mellea-fy-behaviours` | Reference: KB3–KB9, KB11 workarounds                                           | (reference only — read before Step 4)            |

## Intermediate artifacts

All intermediate artifacts persist in `intermediate/` inside the output directory. A failed run leaves whatever was produced under `.melleafy-partial/` for debugging. The full artifact trail is:

```
intermediate/
  classification.json
  inventory.json
  element_mapping.json
  element_mapping_amendments.json   ← from Step 2.5d
  dependency_plan.json
  mellea_api_ref.json               ← from Step 2.5e
  element_mapping_judgment_calls.json
  coverage_report.json
  step_1b_trace.json
  step_7_report.json
```

## Key design principles

**Autonomous execution — no confirmation pauses.** Run all 10 steps from start to finish without stopping to ask the user whether to proceed. Do not output phrases like "Ready to proceed?", "Shall I continue?", or "Proceed to Step N?" between steps. Each step completes and the next begins immediately. The only permitted halts are: (a) Step 2.5 `ask` mode disposition elicitation, (b) a `strict` mode disposition conflict, or (c) a repair-loop exhaustion at Step 7. In all other cases, proceed.

**Deterministic workflow with scoped LLM invocations** — melleafy is not an LLM agent. LLM invocations occur at specific, scoped steps: Step 1b (element tagging), Step 2 (narrow judgement calls), Step 4 (fixture generation), Step 5 (body generation), Step 6 (narrative prose). Steps 0, 1a, 2.5, 3, and 7 are entirely deterministic.

**Source fidelity** — every significant line of the source spec becomes an inventory element (≥95% coverage). Nothing is silently skipped.

**Dispositions are explicit** — Step 2.5 produces a `dependency_plan.json` where every external dependency has an explicit disposition (`bundle`, `real_impl`, `stub`, `mock`, `delegate_to_runtime`, `external_input`, `load_from_disk`, or `remove`). In `auto` mode, defaults are applied silently; in `ask` mode, the user approves each; in `strict` mode, any stub-requiring disposition halts before writing files.

**One BaseModel per session** — schema priming (KB 5) is the most impactful Known Behaviour. All generated code must respect the one-schema-per-session rule. See `/mellea-fy-behaviours` for the full KB list.

**Lints are non-configurable** — Step 7's 14 lints all run unconditionally. There is no `--skip-lint` flag. Tier 1 and structural Tier 2 lint failures trigger a bounded repair loop: `/mellea-fy-generate` is re-invoked (failing files only, with exact lint messages as context) for up to 2 rounds before halting. `session-boundary` and `category-specific` failures always halt immediately — no repair is attempted. See `/mellea-fy-validate` for lint details.

## Output directory layout

**Rule OUT-1 — Co-location model.** Output is written into the same directory as the source spec (or the workspace directory for multi-file runtimes). The directory containing the spec IS the skill root. The compiled package is created as a subdirectory of the skill root.

- Input: `<skill-root>/spec.md` (e.g. `path/to/weather/spec.md`)
- Skill root: `<skill-root>/` (e.g. `path/to/weather/`)
- Compiled package: `<skill-root>/<package_name>/` (e.g. `path/to/weather/weather_mellea/`)

**Rule OUT-2 — Package name derivation.** `<package_name>` is a valid Python identifier derived from the skill's frontmatter `name:` field (or skill directory name for multi-file runtimes — CrewAI, LangGraph, Letta, etc.):

1. Take the `name:` value (or directory name)
2. Lowercase
3. Replace hyphens and spaces with underscores
4. Append `_mellea` suffix
5. Strip any leading/trailing underscores; collapse double underscores

Examples: `weather` → `weather_mellea` | `security-review` → `security_review_mellea` | `research-lead` → `research_lead_mellea`

**Rule OUT-3 — Package directory contains all compiled output.** With one exception — `pyproject.toml` (Step 3) — every file generated by melleafy is written inside `<package_name>/`. The skill root contains the source spec, `pyproject.toml`, and any source files preserved for non-.md runtimes:

```
<skill-root>/                           ← wherever the source spec lives
│
├── spec.md / SKILL.md                  ← source spec (untouched by melleafy)
├── pyproject.toml                      ← Step 3 — melleafy-generated file at skill root
│
│   ── Source files for non-.md runtimes (preserved at skill root) ──
├── agents.yaml / crew.py / ...
│
│   ── Companion directories (preserved at skill root; mirrored into <package_name>/ — Rule OUT-6) ──
├── scripts/                            ← optional; mirrored at Step 3
├── references/                         ← optional; mirrored at Step 3
├── assets/                             ← optional; mirrored at Step 3
│
└── <package_name>/                     ← e.g. weather_mellea/ — all other output
    │
    │   ── Python package files ──
    ├── __init__.py
    ├── __main__.py
    ├── pipeline.py
    ├── config.py
    ├── schemas.py
    ├── main.py
    ├── requirements.py                 ← conditional
    ├── slots.py                        ← conditional
    ├── tools.py                        ← conditional
    ├── constrained_slots.py            ← conditional
    ├── mobjects.py                     ← conditional
    └── loader.py                       ← conditional
    │
    │   ── Documentation & manifests ──
    ├── melleafy.json                   ← Step 6
    ├── mapping_report.md               ← Step 6
    ├── README.md                       ← Step 6
    ├── SETUP.md                        ← Step 6, conditional
    ├── SKILL.md                        ← Step 6, non-.md sources only (generated if absent)
    ├── dependencies.yaml               ← Step 2.5, conditional
    │
    │   ── Bundled runtime assets (Rule OUT-6 — mirrored from skill root at Step 3) ──
    ├── scripts/                        ← if <skill-root>/scripts/ exists
    ├── references/                     ← if <skill-root>/references/ exists
    ├── assets/                         ← if <skill-root>/assets/ exists
    │
    │   ── Test fixtures ──
    ├── fixtures/                       ← Step 4
    │   ├── __init__.py
    │   └── <case>.py ...
    │
    │   ── Intermediate artifacts ──
    └── intermediate/
        ├── classification.json         ← Step 0
        ├── inventory.json              ← Step 1b
        ├── element_mapping.json        ← Step 2
        ├── element_mapping_amendments.json ← Step 2.5d
        ├── dependency_plan.json        ← Step 2.5c
        ├── mellea_api_ref.json         ← Step 2.5e
        ├── element_mapping_judgment_calls.json
        ├── coverage_report.json
        ├── step_1b_trace.json
        └── step_7_report.json          ← Step 7
```

**Rule OUT-4 — `fixtures/` is inside `<package_name>/`.** `fixtures/` is written inside `<package_name>/`, not at skill root. The `pyproject.toml` `[tool.setuptools.packages.find]` includes only `<package_name>*` — `fixtures/` is excluded from the installed package but physically inside the package directory for CLI discoverability. Run fixtures via `python -m pytest <package_name>/fixtures/` from the skill root.

**Rule OUT-5 — `.melleafy-partial/` on failure.** When a run fails (Step 7 lint failure or earlier halt), in-progress artifacts are preserved at `<skill-root>/.melleafy-partial/` — a sibling of `<package_name>/` within the skill root. Inspect this directory to debug the failure; it is safe to delete once the issue is resolved. Re-running after fixing will overwrite it.

**Rule OUT-6 — Companion-directory mirror.** Companion directories at the skill root (`scripts/`, `references/`, `assets/`) are mirrored into `<package_name>/` at Step 3 (skeleton emission), _before_ any code body generation. The skill-root copy is the source of truth (untouched by melleafy on subsequent runs); the package copy is treated as compiled output (regenerated each run). The mirror makes the package self-contained: any code inside `<package_name>/` that needs to invoke a bundled script or load a bundled reference MUST resolve the path package-relatively via `Path(__file__).parent / "<dir>/<file>"` — never via a user-supplied `repo_root` argument or the process working directory. Companion directories that are absent at the skill root are not created in the package. The pyproject.toml `[tool.setuptools.package-data]` section (Step 3) declares these directories so they are included in the installed wheel.

---

## Generation modes

Pass `--dependencies=<mode>` to control disposition elicitation:

| Mode            | Behavior                                                             |
| --------------- | -------------------------------------------------------------------- |
| `auto`          | Apply category default dispositions; print recap if any stubs result |
| `ask`           | Interactive terminal UI — approve/override each dependency           |
| `config:<path>` | Read dispositions from a JSON config file                            |
| `strict`        | Halt before writing files if any disposition would produce a stub    |

Default: `auto`.
