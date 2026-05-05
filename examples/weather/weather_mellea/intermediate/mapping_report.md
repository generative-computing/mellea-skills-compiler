# Mapping Report — weather-mellea

**Generated**: 2026-04-30
**Source spec**: `skills/weather/spec.md`
**Package**: `weather_mellea`
**Melleafy version**: 4.3.2

---

## Classification

**Axis 1 — Reasoning Archetype**: Type D1 (Integration — thin service wrapper)
Evidence: Single HTTP endpoint (wttr.in), minimal decision logic, no multi-phase analysis.

**Axis 2 — Pipeline Shape**: One-shot
Rationale: Intent classification + deterministic URL dispatch — no phase-to-phase data accumulation.

**Axis 3 — Tool Involvement**: P2 (Pipeline calls tools deterministically)
Rationale: LLM classifies intent; Python constructs the wttr.in URL; no LLM-directed tool selection.

**Axis 4 — Source Runtime**: agent_skills_std (strong signals: YAML frontmatter `name:`/`description:`, `.md` extension)
Score: 4.5 vs next 0.5 — unambiguous.

**Axis 5 — Interaction Modality**: synchronous_oneshot (inferred, confidence 0.85)
Rationale: No session state, no scheduling, no event signals. Request → response.

---

## Element Mapping Summary

| Mapping ID | Element ID | Tag           | Category | Primitive   | Target File | Target Symbol                  |
| ---------- | ---------- | ------------- | -------- | ----------- | ----------- | ------------------------------ |
| map_001    | elem_001   | CONFIG        | C1       | Final       | config.py   | SKILL_NAME                     |
| map_002    | elem_002   | NO_DECOMPOSE  | —        | none        | —           | —                              |
| map_003    | elem_003   | CONFIG        | C8       | Final       | config.py   | REQUIRED_BINS                  |
| map_004    | elem_004   | NO_DECOMPOSE  | —        | none        | —           | —                              |
| map_005    | elem_005   | CONFIG        | C1       | Final       | config.py   | USE_WHEN_EXAMPLES              |
| map_006    | elem_006   | DECIDE        | C2       | m.instruct  | pipeline.py | run_pipeline (scope gate)      |
| map_007    | elem_007   | EXTRACT       | —        | @generative | slots.py    | extract_location               |
| map_008    | elem_008   | TOOL_TEMPLATE | C6       | function    | tools.py    | fetch_weather                  |
| map_009    | elem_009   | TOOL_TEMPLATE | C6       | function    | tools.py    | fetch_weather (unified)        |
| map_010    | elem_010   | TOOL_TEMPLATE | C6       | function    | tools.py    | fetch_weather (unified)        |
| map_011    | elem_011   | CONFIG        | C6       | Final       | config.py   | WEATHER_FORMAT_CODES           |
| map_012    | elem_012   | TOOL_TEMPLATE | C6       | Final       | config.py   | WEATHER_PRESET_FULL_CONDITIONS |
| map_013    | elem_013   | TOOL_TEMPLATE | C6       | Final       | config.py   | WEATHER_PRESET_RAIN_CHECK      |
| map_014    | elem_014   | TOOL_TEMPLATE | C6       | Final       | config.py   | WEATHER_PRESET_WEEK_FORECAST   |
| map_015    | elem_015   | CONFIG        | C8       | Final       | config.py   | WTTR_BASE_URL                  |

---

## Dependency Plan Summary

| Entry ID | Category           | Disposition | Source Elements              | Target                                        |
| -------- | ------------------ | ----------- | ---------------------------- | --------------------------------------------- |
| dep_001  | C1 Identity        | bundle      | elem_001, elem_005           | config.py:SKILL_NAME + related constants      |
| dep_002  | C2 Operating Rules | bundle      | elem_006                     | config.py:OUT_OF_SCOPE_CATEGORIES             |
| dep_003  | C8 Runtime         | bundle      | elem_003, elem_015           | config.py:WTTR_BASE_URL (prerequisites: curl) |
| dep_004  | C6 Tools           | real_impl   | elem_008, elem_009, elem_010 | tools.py:fetch_weather                        |
| dep_005  | C6 Tools           | bundle      | elem_011–014                 | config.py:WEATHER_FORMAT_CODES + presets      |

No stubs. No delegate_to_runtime entries. No SETUP.md §8 stubs section needed.

---

## Aggregation Decisions

**TOOL_TEMPLATE unification (elem_008/009/010 → fetch_weather)**
All three Command sections (Current Weather, Forecasts, Format Options) resolve to HTTP GET requests to `wttr.in/{location}{endpoint_params}`. Unified into a single `fetch_weather(location: str, endpoint_params: str) -> str` function. The `_ENDPOINT_PARAMS` dispatch dict in `pipeline.py` covers all variants deterministically.

**Quick Response folding (elem_012/013/014 → config.py presets)**
The three Quick Response examples are named format-string presets. Rather than emitting separate TOOL_TEMPLATE functions (which would duplicate `fetch_weather`), they were folded into `WEATHER_PRESET_FULL_CONDITIONS`, `WEATHER_PRESET_RAIN_CHECK`, and `WEATHER_PRESET_WEEK_FORECAST` `Final[str]` constants in `config.py`. The pipeline's `_ENDPOINT_PARAMS` dict references these constants.

---

## Generated File Set

| File                | Reason                                                                                |
| ------------------- | ------------------------------------------------------------------------------------- |
| `pipeline.py`       | Always — contains `run_pipeline(query: str) -> str`                                   |
| `schemas.py`        | Contains WeatherIntent (m.instruct format=) and WeatherQueryType enum                 |
| `config.py`         | C1/C2/C6/C8 bundle constants (rendered by config_writer.py from config_emission.json) |
| `slots.py`          | @generative extract_location slot (elem_007)                                          |
| `tools.py`          | C6 real_impl: fetch_weather (dep_004)                                                 |
| `main.py`           | CLI entry point                                                                       |
| `fixtures/`         | 7 fixtures covering C1/C2/C6/C8 (rendered from fixtures_emission.json)                |
| `README.md`         | Always                                                                                |
| `SETUP.md`          | dep_003 has prerequisites (curl binary)                                               |
| `melleafy.json`     | Always (finalised in Step 6)                                                          |
| `dependencies.yaml` | C6 dep_004 has runtime prerequisites                                                  |
| `pyproject.toml`    | Always (at skill root)                                                                |

Files NOT emitted (no trigger):

- `requirements.py` — no VALIDATE_OUTPUT elements
- `constrained_slots.py` — no stub/delegate_to_runtime C6 dispositions
- `mobjects.py` — no TRANSFORM/QUERY elements
- `loader.py` — no load_from_disk dispositions

---

## KB Compliance Notes

| KB   | Applied                                                                                                      | Where                |
| ---- | ------------------------------------------------------------------------------------------------------------ | -------------------- |
| KB1  | `_safe_parse_with_fallback` called immediately after `m.instruct(format=WeatherIntent)`                      | `pipeline.py:97-102` |
| KB2  | `RepairTemplateStrategy(loop_budget=LOOP_BUDGET)` on WeatherIntent (5 fields + Optional fields)              | `pipeline.py:94`     |
| KB5  | Two separate `start_session()` calls: Session 1 for @generative slot, Session 2 for m.instruct               | `pipeline.py:79-102` |
| KB6  | `extract_location(query: str)` — no forbidden param names; `m` passed only at call time                      | `slots.py`           |
| KB7  | `model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT}` on `m.instruct` call                                | `pipeline.py:87`     |
| KB11 | `WeatherIntent.location` and `.out_of_scope_reason` both have `"Do not ask for it."` extraction instructions | `schemas.py:39-52`   |

---

## Removed During Audit

None. All 15 elements mapped cleanly.

---

## Warnings

None.
