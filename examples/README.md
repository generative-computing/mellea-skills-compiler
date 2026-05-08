# Compiled skill examples

This directory contains canonical compiled-skill outputs — full results of successful `mellea-skills compile <spec>` runs, kept versioned alongside the codebase as reference snapshots.

Each subdirectory shows the shape of a contract-correct compiled package:

- `<skill>_mellea/pipeline.py` — orchestrating Mellea pipeline
- `<skill>_mellea/config.py` — wrapper-rendered runtime constants (BACKEND, MODEL_ID, persona text, etc.)
- `<skill>_mellea/fixtures/__init__.py` — exports `ALL_FIXTURES: list[Callable]` of factory functions returning `(inputs, fixture_id, description)`
- `<skill>_mellea/intermediate/` — the JSON IR the LLM emitted (classification, inventory, mapping, dependency plan, runtime directive, etc.) plus the deterministic plumbing artifacts (mellea_api_ref.json, mellea_doc_index.json, fixtures_emission.json, config_emission.json)
- `<skill>_mellea/SETUP.md`, `mapping_report.md`, `melleafy.json` — documentation and manifest

## Canonical examples (validated end-to-end)

These four are confirmed runnable against the latest architecture (deny-rule + writer pipeline + 3 Python lints + smoke check):

| Skill                               | Tier                                                                             | Demo run                                                                                                                                   |
| ----------------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `weather/`                          | T1 — runs out of the box                                                         | `mellea-skills run skills/weather/weather_mellea --fixture rain_check_city`                                                                |
| `sentry-find-bugs/`                 | T1 (clean fixture) and T2 (codebase-scanning fixtures)                           | `mellea-skills run skills/sentry-find-bugs/sentry_find_bugs_mellea --fixture clean_secure_parameterized`                                   |
| `superpowers-systematic-debugging/` | T1 — different archetype (constrained reasoning + hypothesis)                    | `mellea-skills run skills/superpowers-systematic-debugging/superpowers_systematic_debugging_mellea --fixture architectural_issue_detected` |
| `clawdefender/`                     | T3 — adversarial input classification (requires `chmod +x scripts/*.sh` on Unix) | `mellea-skills run skills/clawdefender/clawdefender_mellea --fixture prompt_injection_critical`                                            |

`sentry-find-bugs` doubles as the canonical "fill the stub" walkthrough — `constrained_slots.py` ships two stub helpers (`grep_for_pattern`, `read_file_range`) used by the codebase-scanning fixtures. See `docs/FROM_STUBS_TO_RUNNING.md` for the implementation walkthrough.

## Other entries

The remaining subdirectories (`anthropic-doc-coauthoring/`, `checklist/`, `sentry-security-review/`, `sentry-skill-scanner/`, `slack/`) are older compile outputs from earlier architecture iterations. They may not satisfy the current factory-shape fixture contract or other recent invariants — refer to them with caution.

## Maintaining this directory

When the compile architecture changes (new schemas, new lints, new writer rules), regenerate the canonical examples to keep them representative:

```bash
mellea-skills compile skills/weather/spec.md
cp -r skills/weather/weather_mellea examples/mellea-fy-outputs/weather/
# ... repeat for each canonical skill
```

The mellea-fy slash command may implicitly Read these examples during compilation as in-context reference for new compiles. Keeping them current means new compiles benefit from the latest patterns; keeping them frozen means new compiles are influenced by patterns that may no longer be canonical.
