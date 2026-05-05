# Melleafy Mapping Report: superpowers-systematic-debugging

Generated: 2026-04-30 | Melleafy 4.3.2 | Package: `superpowers_systematic_debugging_mellea`

---

## 1. Classification

**Axis 1 — Reasoning Archetype**: Type C (Diagnosis)
Confidence: 0.82. Evidence: the spec uses "investigate", "reproduce", "root cause", and "hypothesis" as core vocabulary. The structure is hypothesis-driven with explicit gating: four sequential phases where each phase's completion is a prerequisite for the next, and an Iron Law gate at the top ("NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST") that overrides all other activity. The archetype C signal is unambiguous — this is not a transformation or generation task but a structured investigation that produces evidence and a fix recommendation only after root cause is established.

**Axis 2 — Pipeline Shape**: Sequential (4 phases)
Rationale: The spec names four explicitly ordered phases. Phase 1 evidence is prerequisite for Phase 2 pattern comparison. Phase 2 pattern analysis informs Phase 3 hypothesis formation. Phase 3 hypothesis confirmation gates Phase 4 implementation. Each phase output is passed as grounding context to the next.

**Axis 3 — Tool Involvement**: P0 (No tools)
Rationale: The spec describes pure reasoning methodology. All four phases produce structured analytical output from user-supplied input; no API calls, external data fetches, database queries, or tool invocations are required.

**Axis 4 — Source Runtime**: agent_skills_std (score 3.5; next: claude_code 0.5)
Signals: YAML frontmatter with `name:` and `description:` keys (strong, 2.0×); `.md` extension with `model:` key (medium, 1.0×); single-file, no Python (weak, 0.5×).

**Axis 5 — Interaction Modality**: synchronous_oneshot (inferred, confidence 0.85)
Rationale: No explicit `modality:` frontmatter key. No session state references, scheduling patterns, streaming signals, or event-handler patterns detected. The spec's `run_pipeline` shape is unambiguously request-in / response-out.

---

## 2. Decomposition Summary

### Element counts by tag

| Tag             | Count  |
| --------------- | ------ |
| SCHEMA          | 8      |
| ORCHESTRATE     | 8      |
| VALIDATE_OUTPUT | 6      |
| EXTRACT         | 6      |
| NO_DECOMPOSE    | 6      |
| GENERATE        | 3      |
| DECIDE          | 2      |
| CONFIG          | 2      |
| VALIDATE_DOMAIN | 1      |
| CLASSIFY        | 1      |
| **Total**       | **43** |

### Element counts by category

| Category                   | Count  |
| -------------------------- | ------ |
| — (no external dependency) | 33     |
| C2 (Operating rules)       | 7      |
| C8 (Runtime environment)   | 2      |
| C3 (User facts)            | 1      |
| **Total**                  | **43** |

### Cross-tab: Tag × Category

| Tag             | C2  | C3  | C8  | —   | Total |
| --------------- | --- | --- | --- | --- | ----- |
| CONFIG          |     |     | 2   |     | 2     |
| VALIDATE_OUTPUT | 4   |     |     | 2   | 6     |
| ORCHESTRATE     | 3   | 1   |     | 4   | 8     |
| NO_DECOMPOSE    |     |     |     | 6   | 6     |
| EXTRACT         |     |     |     | 6   | 6     |
| VALIDATE_DOMAIN |     |     |     | 1   | 1     |
| GENERATE        |     |     |     | 3   | 3     |
| DECIDE          |     |     |     | 2   | 2     |
| CLASSIFY        |     |     |     | 1   | 1     |
| SCHEMA          |     |     |     | 8   | 8     |
| **Total**       | 7   | 1   | 2   | 33  | 43    |

### Aggregate statistics

- **Total elements**: 43 (34 spec-derived + 8 inferred SCHEMA + 1 CONFIG threshold)
- **Source files read**: 1 (`spec.md`)
- **Coverage ratio**: 1.00 (204/204 denominator lines — 100%)
- **Two-step expansions**: 3 (elem_008, elem_010, elem_013 → 3 extra mapping entries → 46 total mappings)
- **Mapping entries total**: 46

---

## 3. Element Mapping

Grouped by target file. Two-step elements appear under both their step-1 and step-2 files.

### `config.py`

| Element ID | Source          | Tag    | Category | Symbol             | Primitive    |
| ---------- | --------------- | ------ | -------- | ------------------ | ------------ |
| elem_001   | spec.md:1-4     | CONFIG | C8       | `SKILL_NAME`       | `Final[str]` |
| elem_043   | spec.md:195-196 | CONFIG | C8       | `MAX_FIX_ATTEMPTS` | `Final[int]` |

### `requirements.py`

| Element ID          | Source                   | Tag             | Category | Symbol                               | Primitive                     |
| ------------------- | ------------------------ | --------------- | -------- | ------------------------------------ | ----------------------------- |
| elem_002            | spec.md:10-14            | VALIDATE_OUTPUT | C2       | `require_root_cause_before_fix`      | `req()` llm_judged            |
| elem_006            | spec.md:48-48            | VALIDATE_OUTPUT | C2       | `require_no_process_skipping`        | `check()` llm_judged          |
| elem_021            | spec.md:164-168          | VALIDATE_OUTPUT | —        | `require_epistemic_honesty`          | `req()` llm_judged            |
| elem_024            | spec.md:187-190          | VALIDATE_OUTPUT | —        | `require_fix_verification`           | `req()` llm_judged            |
| elem_028 ∪ elem_030 | spec.md:217-232, 247-256 | VALIDATE_OUTPUT | C2       | `require_no_premature_fix_proposals` | `check()` llm_judged (merged) |

### `slots.py`

| Element ID     | Source          | Tag                    | Category | Symbol                        | Primitive                    |
| -------------- | --------------- | ---------------------- | -------- | ----------------------------- | ---------------------------- |
| elem_008-step1 | spec.md:54-58   | EXTRACT (two-step 1/2) | —        | `extract_error_analysis_raw`  | `@generative → str`          |
| elem_010-step1 | spec.md:66-70   | EXTRACT (two-step 1/2) | —        | `extract_recent_changes_raw`  | `@generative → str`          |
| elem_013-step1 | spec.md:110-120 | EXTRACT (two-step 1/2) | —        | `extract_data_flow_trace_raw` | `@generative → str`          |
| elem_026       | spec.md:199-204 | CLASSIFY               | —        | `classify_failure_pattern`    | `@generative → Literal[...]` |

### `schemas.py`

| Element ID | Source          | Tag    | Category | Symbol                 | Primitive   |
| ---------- | --------------- | ------ | -------- | ---------------------- | ----------- |
| elem_035   | spec.md:54-58   | SCHEMA | —        | `ErrorAnalysis`        | `BaseModel` |
| elem_036   | spec.md:60-64   | SCHEMA | —        | `ReproductionResult`   | `BaseModel` |
| elem_037   | spec.md:110-120 | SCHEMA | —        | `RootCauseEvidence`    | `BaseModel` |
| elem_038   | spec.md:124-143 | SCHEMA | —        | `PatternAnalysis`      | `BaseModel` |
| elem_039   | spec.md:147-152 | SCHEMA | —        | `Hypothesis`           | `BaseModel` |
| elem_040   | spec.md:159-162 | SCHEMA | —        | `HypothesisTestResult` | `BaseModel` |
| elem_041   | spec.md:172-185 | SCHEMA | —        | `FixPlan`              | `BaseModel` |
| elem_042   | spec.md:1-296   | SCHEMA | —        | `DebuggingReport`      | `BaseModel` |

### `pipeline.py`

| Element ID                     | Source               | Tag                    | Category | Symbol                          | Primitive                                 |
| ------------------------------ | -------------------- | ---------------------- | -------- | ------------------------------- | ----------------------------------------- |
| elem_003 ∪ elem_007            | spec.md:18-22, 52-58 | ORCHESTRATE            | C2       | `run_pipeline`                  | function (merged via dep_003)             |
| elem_008-step2                 | spec.md:54-58        | EXTRACT (two-step 2/2) | —        | `phase1_error_analysis`         | `m.instruct(format=ErrorAnalysis)`        |
| elem_009                       | spec.md:60-64        | VALIDATE_DOMAIN        | —        | `phase1_check_reproducibility`  | `m.instruct(format=ReproductionResult)`   |
| elem_010-step2                 | spec.md:66-70        | EXTRACT (two-step 2/2) | —        | `phase1_extract_recent_changes` | `m.instruct` inline                       |
| elem_011                       | spec.md:72-87        | ORCHESTRATE            | —        | `phase1_gather_evidence`        | function                                  |
| elem_013-step2                 | spec.md:110-120      | EXTRACT (two-step 2/2) | —        | `phase1_trace_data_flow`        | `m.instruct(format=RootCauseEvidence)`    |
| elem_014 ∪ elem_016 ∪ elem_017 | spec.md:124-143      | EXTRACT                | —        | `phase2_pattern_analysis`       | `m.instruct(format=PatternAnalysis)`      |
| elem_015                       | spec.md:130-133      | ORCHESTRATE            | C3       | `phase2_compare_references`     | function                                  |
| elem_018                       | spec.md:147-152      | GENERATE               | —        | `phase3_form_hypothesis`        | `m.instruct(format=Hypothesis)`           |
| elem_019                       | spec.md:154-157      | ORCHESTRATE            | —        | `phase3_test_minimally`         | function                                  |
| elem_020                       | spec.md:159-162      | DECIDE                 | —        | `phase3_verify_hypothesis`      | `m.instruct(format=HypothesisTestResult)` |
| elem_022 ∪ elem_023            | spec.md:172-185      | GENERATE               | —        | `phase4_create_fix_plan`        | `m.instruct(format=FixPlan)`              |
| elem_025                       | spec.md:192-197      | DECIDE                 | —        | `phase4_check_fix_count`        | function (Python `if/else`)               |
| elem_027                       | spec.md:206-213      | ORCHESTRATE            | —        | `phase4_architectural_review`   | function                                  |
| elem_029                       | spec.md:236-243      | ORCHESTRATE            | C2       | `handle_redirection_signals`    | function                                  |
| elem_032                       | spec.md:269-276      | ORCHESTRATE            | —        | `handle_no_root_cause`          | function                                  |

### No target (NO_DECOMPOSE)

| Element ID | Source          | Content summary                               |
| ---------- | --------------- | --------------------------------------------- |
| elem_004   | spec.md:26-32   | When to Use activation criteria               |
| elem_005   | spec.md:34-44   | "Use especially under time pressure" guidance |
| elem_012   | spec.md:89-108  | Illustrative bash diagnostic example          |
| elem_031   | spec.md:260-265 | Quick Reference table                         |
| elem_033   | spec.md:280-288 | Supporting Techniques cross-references        |
| elem_034   | spec.md:292-296 | Real-World Impact statistics                  |

---

## 4. Judgment Calls

### elem_013 — two-step EXTRACT for `extract_data_flow_trace_raw` / `phase1_trace_data_flow`

The Phase 1 Step 5 "Trace Data Flow" element (spec.md:110-120) produces a `RootCauseEvidence` schema with five fields: `origin_location`, `trace_steps` (list[str]), `bad_value_description`, `root_source`, and `fix_recommendation`. The two-step EXTRACT pattern was selected because `trace_steps` is a `list[str]` field, and `RootCauseEvidence` exceeds the four-field threshold. The concern is that a single `@generative` slot returning this full schema risks silent empty returns on complex multi-frame stack traces — `@generative` has no retry/repair mechanism. The decision maps to a `@generative` slot that extracts a flat pipe-delimited summary (`extract_data_flow_trace_raw → str`), followed by an `m.instruct(format=RootCauseEvidence, strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET))` step that parses the enriched, structured output with retry/repair protection. Alternatives considered: one-step `@generative` slot returning the full schema (rejected — silent failure risk on complex call chains with multiple trace frames).

### elem_024 — llm_judged `Requirement` for `require_fix_verification`

The Phase 4 Step 3 "Verify Fix" element (spec.md:187-190) asks three questions: "Test passes now? No other tests broken? Issue actually resolved?" The third question — "issue actually resolved?" — is semantic and cannot be expressed as a Python `validation_fn` in a pure-reasoning (P0) pipeline where no test runner output or execution environment is available. The decision was to use a bare `req()` (llm_judged) Requirement rather than an executable `simple_validate()` validator. Alternatives considered: executable Requirement checking a `test_passed: bool` field (rejected — the "issue actually resolved" criterion is not structurally verifiable through field-presence checks in a reasoning-only context; the llm_judged approach preserves the semantic intent).

---

## 5. Removed During Audit

No elements removed during audit.

_(Source: `intermediate/element_mapping_amendments.json:amendments` — empty list. This skill is P0 (no tools), all dependency entries have `bundle` disposition, and no `TOOL_TEMPLATE` elements exist that would require target-file amendment.)_

---

## 6. Provenance Appendix

### §7 Source file contributions

| Source file | Lines   | Elements                                                                            |
| ----------- | ------- | ----------------------------------------------------------------------------------- |
| `spec.md`   | 1-4     | elem_001 (frontmatter CONFIG)                                                       |
| `spec.md`   | 10-14   | elem_002 (core principle VALIDATE_OUTPUT)                                           |
| `spec.md`   | 18-22   | elem_003 (Iron Law ORCHESTRATE)                                                     |
| `spec.md`   | 26-32   | elem_004 (When to Use NO_DECOMPOSE)                                                 |
| `spec.md`   | 34-44   | elem_005 (activation guidance NO_DECOMPOSE)                                         |
| `spec.md`   | 48-48   | elem_006 (phase sequencing VALIDATE_OUTPUT)                                         |
| `spec.md`   | 52-58   | elem_007 (phase gate ORCHESTRATE)                                                   |
| `spec.md`   | 54-58   | elem_008 (error message EXTRACT) + elem_035 (ErrorAnalysis SCHEMA)                  |
| `spec.md`   | 60-64   | elem_009 (reproducibility VALIDATE_DOMAIN) + elem_036 (ReproductionResult SCHEMA)   |
| `spec.md`   | 66-70   | elem_010 (recent changes EXTRACT)                                                   |
| `spec.md`   | 72-87   | elem_011 (multi-component evidence ORCHESTRATE)                                     |
| `spec.md`   | 89-108  | elem_012 (bash example NO_DECOMPOSE)                                                |
| `spec.md`   | 110-120 | elem_013 (data flow EXTRACT) + elem_037 (RootCauseEvidence SCHEMA)                  |
| `spec.md`   | 124-143 | elem_014, elem_016, elem_017 (Phase 2 EXTRACTs) + elem_038 (PatternAnalysis SCHEMA) |
| `spec.md`   | 130-133 | elem_015 (reference comparison ORCHESTRATE C3)                                      |
| `spec.md`   | 147-152 | elem_018 (hypothesis GENERATE) + elem_039 (Hypothesis SCHEMA)                       |
| `spec.md`   | 154-157 | elem_019 (minimal test ORCHESTRATE)                                                 |
| `spec.md`   | 159-162 | elem_020 (verify DECIDE) + elem_040 (HypothesisTestResult SCHEMA)                   |
| `spec.md`   | 164-168 | elem_021 (epistemic honesty VALIDATE_OUTPUT)                                        |
| `spec.md`   | 172-185 | elem_022, elem_023 (Phase 4 GENERATEs) + elem_041 (FixPlan SCHEMA)                  |
| `spec.md`   | 187-190 | elem_024 (verify fix VALIDATE_OUTPUT)                                               |
| `spec.md`   | 192-197 | elem_025 (fix count DECIDE)                                                         |
| `spec.md`   | 195-196 | elem_043 (MAX_FIX_ATTEMPTS CONFIG)                                                  |
| `spec.md`   | 199-204 | elem_026 (pattern CLASSIFY)                                                         |
| `spec.md`   | 206-213 | elem_027 (architectural review ORCHESTRATE)                                         |
| `spec.md`   | 217-232 | elem_028 (Red Flags VALIDATE_OUTPUT)                                                |
| `spec.md`   | 236-243 | elem_029 (redirection signals ORCHESTRATE)                                          |
| `spec.md`   | 247-256 | elem_030 (rationalizations VALIDATE_OUTPUT)                                         |
| `spec.md`   | 260-265 | elem_031 (Quick Reference NO_DECOMPOSE)                                             |
| `spec.md`   | 269-276 | elem_032 (no-root-cause exception ORCHESTRATE)                                      |
| `spec.md`   | 280-288 | elem_033 (Supporting Techniques NO_DECOMPOSE)                                       |
| `spec.md`   | 292-296 | elem_034 (Impact statistics NO_DECOMPOSE)                                           |
| `spec.md`   | 1-296   | elem_042 (DebuggingReport aggregate SCHEMA — inferred)                              |

Inferred SCHEMA elements (elem_035–elem_042) have no single source line range; they were derived from the element that defines the corresponding pipeline output shape.

### §8 Runtime-specific constructs not reproduced

The `agent_skills_std` dialect does not declare any runtime-specific constructs (tools, MCP integrations, scheduling frontmatter, or session hooks) beyond YAML frontmatter fields. All frontmatter fields were captured in Step 0 and Step 1a. No dialect-specific constructs were left unreproduced in v1.

### §9 Detected but not handled (deferred)

**Related skill cross-references** (spec.md:280-288): The spec references `root-cause-tracing.md`, `defense-in-depth.md`, `condition-based-waiting.md`, and the `superpowers:test-driven-development` companion skill. Melleafy v1 does not support cross-skill invocation or dynamic skill composition. These references are documented in `README.md §When to use` and preserved as prose. A future melleafy release may support composing skills via skill-dispatch primitives.
