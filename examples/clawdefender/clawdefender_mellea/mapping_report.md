# ClawDefender Mellea — Mapping Report

Generated: 2026-04-30 | Melleafy version: 4.3.2 | Source: `skills/clawdefender/`

---

## 1. Classification

ClawDefender is an **Analytical Pipeline (Archetype A)** that operates sequentially across four phases: input reception, threat pattern dispatch, raw output collection, and structured result synthesis. Its dominant element profile — 16 C2 operating-rule constants and 10 C6 tool declarations — places it clearly in the analysis archetype family, where the primary concern is checking inputs against enumerated detection rules rather than generating novel content.

The pipeline follows a **Sequential shape** with four phases, driven by the deterministic tool dispatch pattern (P2). In explicit check modes, no LLM is invoked — the pipeline calls the bundled bash scripts directly and parses their output deterministically. The LLM is reserved for the `auto` mode, where it classifies intent in a first session and formats the raw tool output into a typed `SecurityScanResult` in a second session (schema priming isolation).

The source was detected as **agent_skills_std** (score 3.5 vs next-best openclaw 0.5) based on the YAML frontmatter `name:` / `description:` fields in `SKILL.md` and the single-file `.md` extension. The interaction modality is **synchronous_oneshot** — inferred from the absence of session state, scheduling, or event handler signals.

| Axis             | Value                                     | Confidence |
| ---------------- | ----------------------------------------- | ---------- |
| Archetype        | A (Analytical Pipeline)                   | 0.82       |
| Shape            | Sequential (4 phases)                     | —          |
| Tool involvement | P2 — pipeline calls tools (deterministic) | —          |
| Source runtime   | agent_skills_std                          | score 3.5  |
| Modality         | synchronous_oneshot                       | 0.85       |

---

## 2. Decomposition Summary

**Coverage**: 97.3% of non-blank, non-heading source lines across 4 source files.

| Source file               | Lines | Coverage |
| ------------------------- | ----- | -------- |
| `SKILL.md`                | 241   | 97.6%    |
| `scripts/clawdefender.sh` | 713   | 97.2%    |
| `scripts/sanitize.sh`     | 130   | 96.5%    |
| `_meta.json`              | 11    | 100%     |

**Element counts by tag:**

| Tag           | Count  |
| ------------- | ------ |
| CONFIG        | 23     |
| TOOL_TEMPLATE | 10     |
| DETERMINISTIC | 10     |
| NO_DECOMPOSE  | 7      |
| SCHEMA        | 3      |
| ORCHESTRATE   | 1      |
| **Total**     | **54** |

**Element counts by category:**

| Category               | Count  |
| ---------------------- | ------ |
| C2 Operating rules     | 16     |
| C6 Tools               | 10     |
| C1 Identity            | 5      |
| — (no dependency)      | 21     |
| C8 Runtime environment | 2      |
| **Total**              | **54** |

---

## 3. Element Mapping

### `config.py` (bundle entries)

| Element  | Source                | Tag    | Category | Target                                                  |
| -------- | --------------------- | ------ | -------- | ------------------------------------------------------- |
| elem_001 | SKILL.md:2            | CONFIG | C1       | `SKILL_NAME`                                            |
| elem_002 | SKILL.md:3            | CONFIG | C1       | `SKILL_DESCRIPTION`                                     |
| elem_005 | SKILL.md:20           | CONFIG | C8       | `REQUIRED_BINS`                                         |
| elem_008 | SKILL.md:49-51        | CONFIG | C2       | `SCORE_CRITICAL` (aggregated with elem_026)             |
| elem_010 | SKILL.md:81           | CONFIG | C1       | `PREFIX_TEXT`                                           |
| elem_021 | SKILL.md:212-222      | CONFIG | C2       | `EXCLUDED_PATHS`                                        |
| elem_023 | SKILL.md:232-237      | CONFIG | C1       | `SKILL_VERSION`                                         |
| elem_025 | clawdefender.sh:15-20 | CONFIG | C8       | `WORKSPACE_DIR`                                         |
| elem_026 | clawdefender.sh:31-35 | CONFIG | C2       | `SCORE_CRITICAL/HIGH/WARNING/INFO` (agg. with elem_008) |
| elem_054 | \_meta.json:1-11      | CONFIG | C1       | `SKILL_OWNER`                                           |

### `tools.py` (bundle pattern constants)

| Element                        | Source                        | Tag    | Category | Target symbol               |
| ------------------------------ | ----------------------------- | ------ | -------- | --------------------------- |
| elem_015 + elem_027 + elem_028 | SKILL.md:131-148 + sh:41-141  | CONFIG | C2       | `PROMPT_INJECTION_CRITICAL` |
| elem_016 + elem_030            | SKILL.md:149-157 + sh:166-181 | CONFIG | C2       | `CREDENTIAL_EXFIL`          |
| elem_017 + elem_029            | SKILL.md:158-165 + sh:143-164 | CONFIG | C2       | `COMMAND_INJECTION`         |
| elem_018 + elem_031            | SKILL.md:166-174 + sh:183-194 | CONFIG | C2       | `SSRF_PATTERNS`             |
| elem_019 + elem_032            | SKILL.md:175-180 + sh:196-223 | CONFIG | C2       | `PATH_TRAVERSAL`            |
| elem_033                       | clawdefender.sh:225-234       | CONFIG | C2       | `SENSITIVE_FILES`           |
| elem_034                       | clawdefender.sh:236-249       | CONFIG | C2       | `ALLOWED_DOMAINS`           |

### `tools.py` (real_impl tool functions)

| Element(s)          | Source                              | Tag           | Category | Target symbol               |
| ------------------- | ----------------------------------- | ------------- | -------- | --------------------------- |
| elem_007 + elem_045 | SKILL.md:40-48 + sh:517-588         | TOOL_TEMPLATE | C6       | `full_audit()`              |
| elem_009 + elem_050 | SKILL.md:53-78 + sanitize.sh:69-129 | TOOL_TEMPLATE | C6       | `sanitize_external_input()` |
| elem_011            | SKILL.md:83-96                      | TOOL_TEMPLATE | C6       | `check_url()`               |
| elem_012            | SKILL.md:98-108                     | TOOL_TEMPLATE | C6       | `check_prompt()`            |
| elem_013 + elem_046 | SKILL.md:110-119 + sh:590-631       | TOOL_TEMPLATE | C6       | `safe_install()`            |
| elem_014            | SKILL.md:121-127                    | TOOL_TEMPLATE | C6       | `validate_text()`           |
| elem_044            | clawdefender.sh:484-515             | TOOL_TEMPLATE | C6       | `scan_skill_files()`        |

### `schemas.py`

| Element  | Source                  | Tag    | Target               |
| -------- | ----------------------- | ------ | -------------------- |
| elem_051 | clawdefender.sh:453-478 | SCHEMA | `SecurityScanResult` |
| elem_052 | SKILL.md:49-51          | SCHEMA | `SeverityLevel`      |
| elem_053 | clawdefender.sh:433-436 | SCHEMA | `ThreatFinding`      |

Additionally: `ScanIntent` was added as a P2 companion schema (not a direct source element) to support the LLM intent classification step in `auto` mode.

### `pipeline.py`

| Element      | Source                  | Tag           | Target                                                   |
| ------------ | ----------------------- | ------------- | -------------------------------------------------------- |
| elem_043     | clawdefender.sh:408-478 | ORCHESTRATE   | `run_pipeline()` (main orchestrator), `_dispatch_tool()` |
| elem_035–042 | clawdefender.sh:255-402 | DETERMINISTIC | `_parse_raw_output()` helper                             |
| elem_047     | clawdefender.sh:637-713 | DETERMINISTIC | `_dispatch_tool()` dispatch table                        |
| elem_049     | sanitize.sh:18-67       | DETERMINISTIC | embedded in `sanitize_external_input()`                  |

### `main.py`

| Element  | Source                  | Tag           | Target                                    |
| -------- | ----------------------- | ------------- | ----------------------------------------- |
| elem_047 | clawdefender.sh:637-713 | DETERMINISTIC | `main()` CLI entry point, `_cli_dispatch` |

### No-decompose (not generated)

| Element  | Source           | Reason                                               |
| -------- | ---------------- | ---------------------------------------------------- |
| elem_003 | SKILL.md:6-8     | Section heading                                      |
| elem_004 | SKILL.md:10-18   | Installation prose (covered by SETUP.md)             |
| elem_006 | SKILL.md:22-36   | Quick-start shell examples                           |
| elem_020 | SKILL.md:181-210 | Automation integration examples                      |
| elem_022 | SKILL.md:224-229 | Exit code table (handled by subprocess return codes) |
| elem_024 | SKILL.md:239-241 | Credits prose                                        |
| elem_048 | sanitize.sh:1-17 | Script header documentation                          |

---

## 4. Judgment Calls

`element_mapping_judgment_calls.json` records zero LLM judgment calls. All elements were mapped mechanically:

- CONFIG/C2 pattern arrays (elem_027–034) were routed to `tools.py` rather than `config.py` because the `config_emission.schema.json` only allows scalar JSON values (`str`, `int`, `float`, `bool`). List-valued pattern arrays cannot be encoded in `config_emission.json` and were instead emitted as `Final[tuple[str, ...]]` constants in `tools.py`. This deviation is recorded in `element_mapping.json:step_2_rationale` for each affected entry.
- DETERMINISTIC elem_047 (CLI dispatch) was routed to `main.py:_cli_dispatch` rather than the default `tools.py` placement, as CLI dispatch belongs in the package entry point.

---

## 5. Removed During Audit

No elements were removed during audit.

`element_mapping_amendments.json` records 10 amendments, all updating `final_target_file` from `"pending_step_2.5"` to `"tools.py"` for TOOL_TEMPLATE elements after Step 2.5d committed the dependency plan with `real_impl` dispositions for all C6 tools.

---

## 6. Provenance Appendix

### 7. Source file contributions

**`SKILL.md`** (241 lines, agent_skills_std primary spec):

- Lines 2–3: elem_001 (SKILL_NAME), elem_002 (SKILL_DESCRIPTION) — frontmatter C1 constants
- Lines 20: elem_005 (REQUIRED_BINS) — C8 runtime requirement
- Lines 40–127: elem_007, 009, 011, 012, 013, 014 — C6 tool descriptions (aggregated with bash implementations)
- Lines 49–51: elem_008 (SCORE_CRITICAL/display labels), elem_052 (SeverityLevel schema)
- Lines 81: elem_010 (PREFIX_TEXT safety rule) — C1 behavioral constant
- Lines 131–180: elem_015–019 — C2 detection category descriptions (aggregated with bash patterns)
- Lines 212–222: elem_021 (EXCLUDED_PATHS) — C2 operating rule
- Lines 232–237: elem_023 (SKILL_VERSION) — C1 identity
- Lines 239–241: elem_024 — NO_DECOMPOSE credits
- Remaining lines: elem_003, 006, 020, 022 — NO_DECOMPOSE prose and examples

**`scripts/clawdefender.sh`** (713 lines, tool implementation and config patterns):

- Lines 15–35: elem_025, 026 — C8/C2 workspace and score threshold constants
- Lines 41–249: elem_027–034 — C2 pattern arrays (PROMPT_INJECTION_CRITICAL through ALLOWED_DOMAINS)
- Lines 255–402: elem*035–042 — DETERMINISTIC helper functions (log_finding, check_patterns, validate*\*)
- Lines 408–478: elem_043, 051, 053 — ORCHESTRATE validate_input + SCHEMA definitions
- Lines 484–631: elem_044, 045, 046 — TOOL_TEMPLATE tool functions (scan_skill_files, full_audit, safe_install)
- Lines 637–713: elem_047 — DETERMINISTIC CLI dispatch

**`scripts/sanitize.sh`** (130 lines, sanitize wrapper):

- Lines 1–17: elem_048 — NO_DECOMPOSE header documentation
- Lines 18–67: elem_049 — DETERMINISTIC flag parsing and setup
- Lines 69–129: elem_050 — TOOL_TEMPLATE sanitize core logic

**`_meta.json`** (11 lines, registry metadata):

- Lines 1–11: elem_054 — C1 SKILL_OWNER constant

### 8. Runtime-specific constructs not reproduced

No runtime-specific constructs from the `agent_skills_std` dialect were left unreproduced. All frontmatter fields (`name`, `description`) and all body elements were processed.

The `agent_skills_std` dialect does not specify bash-to-Python subprocess conventions. The subprocess stdin vs. positional-arg distinction (identified during Step 3 code generation) was resolved by inspecting each script's input method: `--check-prompt` and `sanitize.sh` read from stdin (`<<< "$INPUT"`), while `--check-url`, `--validate`, `--install`, and `--scan-skill` take positional arguments.

### 9. Detected but not handled (deferred)

**Whitelist management (`--whitelist`)**: The `clawdefender.sh --whitelist` command (elem_047 CLI dispatch) manages a domain whitelist JSON file. This was classified as a DETERMINISTIC element mapping to `main.py` CLI dispatch. A dedicated `manage_whitelist()` tool function is not generated — the bash script handles whitelist mutations natively. Users who need programmatic whitelist management should invoke the bundled script directly: `subprocess.run([str(_clawdefender_script()), "--whitelist", action, domain])`.

**Interactive `safe_install` approval prompt**: The `safe_install()` bash function prompts `y/N` interactively when findings are detected. The Python wrapper runs the script without a TTY (`capture_output=True`), so the interactive prompt is not surfaced. The generated `safe_install()` tool function returns the full script output; callers must inspect `SecurityScanResult.raw_output` or `result.clean` to decide whether to proceed. For automated pipelines, pass `--non-interactive` if the script supports it, or treat `clean=False` from `scan_skill_files()` as the rejection signal.
