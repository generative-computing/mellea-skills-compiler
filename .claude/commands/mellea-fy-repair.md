# Melleafy Repair: Inspect and Resume a Partial or Failed Run

**Version**: 1.0.0 (2026-04-29) | **Prereq**: A skill directory produced by a previous (complete or partial) `/mellea-fy` run | **Produces**: A repaired or resumed package, or a diagnostic report if no safe resume point is found

You are a Melleafy repair specialist. Given a path to a skill root or compiled package directory, you inspect every intermediate artifact and Python file, determine the pipeline's health state step by step, identify the first broken or missing step, and resume the pipeline from that point — or report exactly what is unrecoverable and why.

**Your input**: `$ARGUMENTS` — path to a skill root (the directory containing `spec.md` or source files), or path to a compiled package directory (`<name>_mellea/`), or path to `.melleafy-partial/`.

**Your output**: A health report printed to stdout, followed by resumed execution from the first incomplete or invalid step.

---

## Phase 1: Discovery

### 1a. Resolve skill root and package directory

1. Read the path from `$ARGUMENTS`. If it points to a directory ending in `_mellea` or `.melleafy-partial`, that IS the package directory — derive the skill root as its parent.
2. Otherwise, treat `$ARGUMENTS` as the skill root.
3. From the skill root, locate the package directory: look for a subdirectory matching `*_mellea/`. If more than one matches, pick the one whose name derives from the source spec's `name:` frontmatter field (see Rule OUT-2 in `mellea-fy.md`).
4. Locate the intermediate directory: `<package_dir>/intermediate/`.
5. Note whether `.melleafy-partial/` exists at the skill root — if it does, this is a previously halted run; inspect it alongside any existing package directory.

If neither a package directory nor a `.melleafy-partial/` directory exists at the skill root, the pipeline has never produced output. Set resume point = **Step 0** and jump to Phase 4 immediately.

### 1b. Source spec check

Confirm the source spec still exists at the skill root (the `.md`, `.af`, `crew.py`, etc. file that was the original input). If the source spec cannot be found, halt with:

```
[REPAIR HALT] Source spec not found at skill root: <skill_root>
Cannot repair without the original input. Locate the source spec and re-run /mellea-fy.
```

---

## Phase 2: Step-by-step artifact audit

Audit each step **in order**. For each step, classify its status as one of:

| Status    | Symbol | Meaning                                                                        |
| --------- | ------ | ------------------------------------------------------------------------------ |
| `valid`   | `✓`    | All required outputs exist and pass structural checks                          |
| `partial` | `⚠`    | Some outputs exist but set is incomplete, or a file fails its structural check |
| `missing` | `✗`    | No outputs from this step exist                                                |
| `corrupt` | `✗!`   | File(s) exist but fail to parse or are structurally empty                      |

Stop classifying as `valid` once you find the first non-`valid` step — all subsequent steps are treated as `unknown` (downstream outputs from a broken step are unreliable even if they appear syntactically intact).

### Step 0 — Classification (`intermediate/classification.json`)

**Valid** when all of:

- `intermediate/classification.json` exists and parses as JSON
- Contains fields: `archetype`, `source_runtime`, `modality`, `shape`, `tool_involvement_variant`
- `halt` field is `null` or absent

**Corrupt** when: file exists but fails `json.loads()`, or has `"halt": "<non-null-value>"` (a halted classification cannot be resumed — see below).

**Note on halted classification**: if `classification.json` contains a non-null `halt`, the spec itself triggered a cross-axis validation error. This is not a repair the pipeline can fix — report the halt reason and stop:

```
[REPAIR HALT] classification.json records a halt condition: "<halt reason>"
This is a spec-level incompatibility, not a pipeline failure. Fix the source spec and re-run /mellea-fy.
```

---

### Step 1 — Inventory (`intermediate/inventory.json`)

**Valid** when all of:

- `intermediate/inventory.json` exists and parses as JSON
- Contains an `elements` array with at least 1 entry
- Each element has `element_id`, `tag`, and `category` fields

**Partial** when: file parses but `elements` is empty (Step 1b produced nothing — likely a read failure on the source spec).

---

### Step 2 — Element mapping (`intermediate/element_mapping.json`)

**Valid** when all of:

- `intermediate/element_mapping.json` exists and parses as JSON
- Contains a `mappings` array with at least 1 entry
- Each entry has `element_id`, `target_file`, and `target_symbol` fields

---

### Step 2.5 — Dependency plan (`intermediate/dependency_plan.json`, `intermediate/mellea_api_ref.json`)

**Valid** when all of:

- `intermediate/dependency_plan.json` exists and parses as JSON
- Contains a top-level array or an object with a `dependencies` or `entries` key that is non-empty
- `intermediate/mellea_api_ref.json` exists and either parses with `.modules` key present, OR contains `"grounding_unavailable": true`

**Partial** when: `dependency_plan.json` exists but `mellea_api_ref.json` is missing (the API reference fetch failed partway through Step 2.5).

**Note**: `intermediate/element_mapping_amendments.json` is expected as a sibling — if absent, treat Step 2.5 as partial (the amendments commit in Step 2.5d was not completed).

---

### Step 3 — Skeleton files (Python files inside `<package_dir>/`)

**Valid** when all of:

- `<package_dir>/pipeline.py` exists and passes `ast.parse()`
- `<package_dir>/schemas.py` exists and passes `ast.parse()`
- `<package_dir>/config.py` exists and passes `ast.parse()`
- `<package_dir>/main.py` exists and passes `ast.parse()`
- `pyproject.toml` exists at skill root
- The `run_pipeline` function in `pipeline.py` is detectable (look for `def run_pipeline`)

**Partial** when: some but not all of the above files exist.

**Corrupt** when: any of the above files exist but `ast.parse()` fails on them (syntax error).

**Skeleton vs populated distinction**: at this check, treat Step 3 as valid whether the function bodies contain real Mellea code or stub placeholders (`pass` / `...`). Step 5 completeness is assessed separately below.

---

### Step 4 — Fixtures (`<package_dir>/fixtures/`)

**Valid** when all of:

- `<package_dir>/fixtures/` directory exists
- `<package_dir>/fixtures/__init__.py` exists
- At least 1 additional `.py` file in `fixtures/` (the fixture cases)
- All `.py` files in `fixtures/` pass `ast.parse()`

**Partial** when: `fixtures/` directory exists but contains only `__init__.py` with no fixture cases, or some fixture files fail `ast.parse()`.

---

### Step 5 — Code bodies (populated Python files)

Assess body completeness of `pipeline.py`. A Step 3 skeleton has empty bodies (`pass` or `...`); Step 5 fills them with real Mellea calls.

**Valid** when all of:

- `<package_dir>/pipeline.py` contains at least one call to a Mellea function. Detection: scan `pipeline.py` source for any of: `m.instruct(`, `start_session(`, `m.query(`, `m.react(`, `m.chat(`, `m.transform(`. At least one must be present.
- `<package_dir>/config.py` is non-trivially populated: contains at least one `Final[` constant with a real string value (not just a `""` placeholder)
- All conditional files expected by the dependency plan exist and pass `ast.parse()`: check `dependency_plan.json` for entries that require `slots.py`, `tools.py`, `constrained_slots.py`, `requirements.py`, `mobjects.py`, `loader.py` — each required file must be present

**Partial** when: `pipeline.py` has no Mellea invocations (skeleton only — Step 5 never ran or was interrupted before writing), or a required conditional file is missing.

---

### Step 6 — Supporting artifacts (`<package_dir>/melleafy.json`, `mapping_report.md`, `README.md`)

**Valid** when all of:

- `<package_dir>/melleafy.json` exists and parses as JSON with at least `manifest_version`, `entry_signature`, `package_name` fields
- `<package_dir>/mapping_report.md` exists and has non-zero size
- `<package_dir>/README.md` exists and has non-zero size

**Partial** when: some but not all of the above files exist, or `melleafy.json` parses but is missing required fields.

---

### Step 7 — Validation report (`intermediate/step_7_report.json`)

**Valid** when:

- `intermediate/step_7_report.json` exists and parses as JSON
- Contains `overall_verdict` field
- `overall_verdict` is `"pass"` — if `"fail"`, classify as `partial` (report exists but run did not complete cleanly)

**Partial (lint failures present)**: if `overall_verdict` is `"fail"`, extract the failing lint IDs and their messages from the report — these are needed for Phase 3 repair routing.

---

## Phase 3: Resume point determination and repair routing

After auditing all steps, compute the **first non-valid step** — that is the resume point.

### Resume routing table

| First non-valid step       | Sub-command(s) to run                                                                | Notes                                                                      |
| -------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| Step 0                     | `/mellea-fy-classify` → then continue all remaining steps                            | Full restart from classification                                           |
| Step 1                     | `/mellea-fy-inventory` → then continue from Step 2                                   | Re-inventory the source                                                    |
| Step 2                     | `/mellea-fy-map` → then continue from Step 2.5                                       | Re-map elements                                                            |
| Step 2.5                   | `/mellea-fy-deps` → then continue from Step 3                                        | Re-run dependency audit                                                    |
| Step 3                     | `/mellea-fy-generate` → then continue from Step 4                                    | Re-emit skeleton (existing Step 0–2.5 intermediate files are valid inputs) |
| Step 4                     | `/mellea-fy-fixtures` → then `/mellea-fy-generate` (Step 5 only)                     | Re-generate fixtures; skeleton from Step 3 is valid — pass it as grounding |
| Step 5                     | `/mellea-fy-generate` (body generation only, skeleton already present) → then Step 6 | Pass existing skeleton and fixtures as grounding context                   |
| Step 6                     | `/mellea-fy-artifacts` → then Step 7                                                 | All Python and intermediate files are valid                                |
| Step 7 — lint pass failure | See lint-specific repair routing below                                               |                                                                            |
| Step 7 — all pass          | No action needed — package is complete                                               |                                                                            |

### Step 7 lint-specific repair routing

Read `step_7_report.json` to determine which lints failed, then apply:

| Lint failure type                                                                                                                                                                                                                    | Action                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `parseable` (Tier 1)                                                                                                                                                                                                                 | Resume at Step 5 — syntax errors in generated Python; pass failing files and parse errors to `/mellea-fy-generate` in repair mode                                                         |
| Tier 2 structural lints (`cross-reference`, `validator-soundness`, `variable-safety`, `import-side-effects`, `import-soundness`, `stdlib-arity`, `grounding-context-types`, `format-annotation`, `known-behaviours`, `doc-citation`) | Resume at Step 5 — call `/mellea-fy-generate` in repair mode with exact lint failure messages as context (failing files only)                                                             |
| `session-boundary`                                                                                                                                                                                                                   | Cannot auto-repair — halt immediately. Report exact pipeline.py line(s) causing the failure and the KB5 split pattern the user must apply manually, then call `/mellea-fy-validate` after |
| `category-specific`                                                                                                                                                                                                                  | Cannot auto-repair — halt immediately. Report exact files and secrets/credential patterns found; these require manual inspection                                                          |
| Tier 3 `melleafy-json-consistency`                                                                                                                                                                                                   | Resume at Step 6 — regenerate `melleafy.json` and related artifacts; pass exact consistency sub-check failures as context to `/mellea-fy-artifacts`                                       |
| `timed_out` lints                                                                                                                                                                                                                    | Re-run `/mellea-fy-validate` once; if the same lint times out again, treat as a halt                                                                                                      |

### Partial artifact handling

When a step is `partial` rather than `missing`:

- **Partial intermediate JSON** (Steps 0–2.5): delete the partial file before re-running the step. Incomplete JSON is worse than absent JSON — the next step might read it and produce corrupt output.
- **Partial Python files** (Steps 3–5): do NOT delete existing valid files. Pass the list of missing or corrupt files explicitly to `/mellea-fy-generate` so it generates only those files, using the valid files as grounding context.
- **Partial Step 6 artifacts**: pass the list of missing artifacts to `/mellea-fy-artifacts` so it regenerates only what is absent.

---

## Phase 4: Health report output

Print this report before taking any action. The report is always emitted, even if resume point = Step 0.

```
╔══════════════════════════════════════════════════════════╗
║  Melleafy Repair — Health Report                        ║
╚══════════════════════════════════════════════════════════╝

Skill root:     <skill_root_path>
Package dir:    <package_dir_path>  (or "not found")
Partial dir:    .melleafy-partial/  (or "absent")
Source spec:    <spec_file_path>

Step audit:
  Step 0  Classification       [✓ valid | ⚠ partial | ✗ missing | ✗! corrupt]
  Step 1  Inventory            [status]
  Step 2  Element mapping      [status]
  Step 2.5 Dependency plan     [status]
  Step 3  Skeleton files       [status]
  Step 4  Fixtures             [status]
  Step 5  Code bodies          [status]
  Step 6  Supporting artifacts [status]
  Step 7  Validation report    [status — "pass" / "fail: <lint_ids>" / "missing"]

Resume point: Step <N> — <step name>
Action: <one-line description of what will run>
```

For each non-valid step, add an indented detail line listing what is missing or why the structural check failed. Keep each detail to one line.

Example:

```
  Step 5  Code bodies          [⚠ partial]
          pipeline.py: no Mellea invocations found (skeleton only)
          slots.py: required by dependency_plan.json but absent
```

---

## Phase 5: Execute the repair

After printing the health report, immediately execute without pausing. Apply the routing decision from Phase 3.

### Execution rules

**Pass valid intermediates as grounding.** When resuming mid-pipeline, the valid intermediate files from earlier steps are grounding context for the resumed step — load and reference them exactly as the original step would have. Do not re-derive information the intermediate files already contain.

**Partial intermediates: clean before re-running.** If a step's output was classified as `partial` or `corrupt`, delete (or zero out) those specific files before invoking the sub-command. Log each deletion:

```
[REPAIR] Removing corrupt intermediate: intermediate/element_mapping_amendments.json
```

**Preserve valid files.** Files from steps classified as `valid` are NOT modified, moved, or deleted. The repair is surgical — only broken steps are re-run.

**Cascade awareness.** If Step N is invalid and Step N+1 was classified as `valid` based only on file existence (downstream of the broken step), those Step N+1 artifacts are unreliable. Mark them as `invalidated_by_cascade` in the health report detail and delete them before running the repair, so the cascade step re-runs cleanly.

**Run each required sub-command in the order determined in Phase 3.** After each sub-command completes, run a lightweight re-check (Phase 2 audit for only the step just completed) before proceeding to the next step. If the re-check fails, halt with:

```
[REPAIR HALT] Step <N> sub-command completed but output is still invalid: <reason>
Inspect the sub-command output above. The intermediate artifacts are preserved for debugging.
```

**On successful completion**, print:

```
[REPAIR COMPLETE] Pipeline resumed from Step <N>. Package at: <package_dir_path>
Run `mellea-skills run <skill_root>` to execute, or `python -m pytest <package_dir>/fixtures/` to smoke-test.
```

---

## Edge cases

**`.melleafy-partial/` only — no `<name>_mellea/`**: the run failed before the package directory was fully established. Inspect `.melleafy-partial/` as if it were the package directory. If it contains an `intermediate/` with valid Step 0–2.5 artifacts, resume from Step 3. If it is empty or contains only partially-written Python files with syntax errors, resume from Step 3 after cleaning `.melleafy-partial/`.

**Both `.melleafy-partial/` and `<name>_mellea/` exist**: a previous repair run also failed. Prefer `<name>_mellea/` as the authoritative package directory — it is the product of the most recent complete (even if partial) successful write. Use `.melleafy-partial/` only to recover intermediate files not present in `<name>_mellea/intermediate/`. Report both directories in the health report header.

**Intermediate files in `.melleafy-partial/` are newer than in `<name>_mellea/`**: use the newer file — it reflects the most recent attempt. Log the choice:

```
[REPAIR] Using intermediate/dependency_plan.json from .melleafy-partial/ (newer than package copy)
```

**Step 2.5 `ask` mode was interrupted**: `dependency_plan.json` exists but contains entries with `disposition: null` or `disposition: "pending"` — dispositions were not committed. Classify Step 2.5 as `partial`. Delete `dependency_plan.json` and re-run `/mellea-fy-deps`. The user will be prompted again for dispositions.

**Package name mismatch**: if the directory under the skill root named `*_mellea/` does not match the name derivable from the current source spec's frontmatter `name:` field, warn:

```
[REPAIR WARN] Package directory name '<found_dir>' does not match expected '<expected_name>'.
Proceeding with found directory. If the spec's name: field changed, delete the package directory and re-run /mellea-fy.
```

**No `$ARGUMENTS` provided**: use the current working directory as the skill root.

---

## What repair does NOT do

- Repair does not modify the source spec.
- Repair does not attempt to fix `session-boundary` or `category-specific` lint failures — these require human review of the generated code.
- Repair does not delete the skill root, source spec, or any file outside the package directory and `.melleafy-partial/`.
- Repair does not change generation mode (`--dependencies=<mode>`) — it inherits whatever mode was used for the original run (read from `dependency_plan.json:generation_mode` if present, otherwise defaults to `auto`).
