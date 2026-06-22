# mellea-fy — Claude Code Skill

`/mellea-fy` is the Claude Code slash command that compiles agent specifications into governed Mellea pipelines. It runs the LLM-driven decomposition phase of the Mellea Skills Compiler workflow.

In most cases you don't invoke `/mellea-fy` directly — `mellea-skills compile` calls it under the hood and adds deterministic plumbing on either side (companion-directory mirroring, grounding pre-population, runtime-defaults injection, structural lints, fixture smoke check). For an end-to-end walkthrough see [`docs/TUTORIAL.md`](../docs/TUTORIAL.md).

## Usage

### Recommended: via the CLI

```bash
mellea-skills compile skills/checklist/spec.md
```

This invokes `/mellea-fy` automatically inside Claude Code, then chains into the post-compile pipeline (writer-rendered `config.py` and `fixtures/`, Step 7 lints, smoke check).

### Alternative: directly inside Claude Code

```
/mellea-fy skills/checklist/spec.md
```

When invoked this way, only the LLM phase runs — the wrapper-side deterministic steps (companion-directory mirror, grounding fetch, runtime-defaults injection, post-compile lints + smoke check) are skipped. Use this only when you specifically want to exercise the decomposition without the surrounding pipeline.

## Output

The compile produces a decomposed pipeline co-located with the spec:

```
skills/checklist/
├── spec.md                    # Your original spec (input, untouched)
├── pyproject.toml             # Generated — pip-installable package
├── SKILL.md                   # Generated — CLI compatibility shim (non-.md sources only)
├── scripts/                   # Optional companion dir, mirrored into the package
└── checklist_mellea/          # Generated package
    ├── pipeline.py
    ├── config.py              # Wrapper-rendered from intermediate/config_emission.json
    ├── schemas.py
    ├── slots.py
    ├── main.py
    ├── tools.py / constrained_slots.py / requirements.py / mobjects.py / loader.py  # Conditional, per dispositions
    ├── fixtures/              # Wrapper-rendered from intermediate/fixtures_emission.json (5–8 fixtures)
    ├── scripts/               # Mirrored from skill root if present (Rule OUT-6)
    ├── references/            # Mirrored from skill root if present
    ├── assets/                # Mirrored from skill root if present
    ├── mapping_report.md      # Element-to-primitive mapping
    ├── melleafy.json          # Manifest consumed by mellea-skills run / certify
    ├── README.md
    ├── SETUP.md               # Backend and dependency setup instructions
    └── intermediate/          # Compiler IR + diagnostics
        ├── classification.json
        ├── inventory.json
        ├── element_mapping.json
        ├── dependency_plan.json
        ├── config_emission.json       # IR for the wrapper to render config.py
        ├── fixtures_emission.json     # IR for the wrapper to render fixtures/
        ├── runtime_directive.json     # BACKEND/MODEL_ID values injected by the wrapper
        ├── mellea_api_ref.json        # Live mellea introspection (from compile pipeline)
        ├── mellea_doc_index.json      # docs.mellea.ai page index (from compile pipeline)
        ├── step_7_report.json         # Static lint results
        └── step_7b_report.json        # Smoke check results (when --no-run not set)
```

## Architecture

Two parts of the compile output are **wrapper-rendered, not LLM-emitted**:

- `config.py` — rendered from `intermediate/config_emission.json` by [`src/mellea_skills_compiler/compile/claude/melleafy/writers/config_writer.py`](../src/mellea_skills_compiler/compile/claude/melleafy/writers/config_writer.py)
- `fixtures/` — rendered from `intermediate/fixtures_emission.json` by [`src/mellea_skills_compiler/compile/claude/melleafy/writers/fixtures_writer.py`](../src/mellea_skills_compiler/compile/claude/melleafy/writers/fixtures_writer.py)

`mellea-skills compile` enforces this by injecting Claude Code `--settings` deny rules that block the LLM from writing those paths during the slash-command phase. The LLM emits the typed JSON intermediate; the wrapper renders the source. This makes drift in those two artifacts structurally impossible.

All other generated files (`pipeline.py`, `tools.py`, `schemas.py`, etc.) are LLM-emitted within the slash command.

## Then Run or Certify

Once you have a compiled pipeline, use `mellea-skills` to run or certify it:

```bash
mellea-skills run skills/checklist/checklist_mellea --fixture <fixture_name>
mellea-skills certify skills/checklist/checklist_mellea
```

## The Skill Spec

The mellea-fy command spec lives at [`src/mellea_skills_compiler/compile/claude/commands/mellea-fy.md`](../src/mellea_skills_compiler/compile/claude/commands/mellea-fy.md) (orchestrator) and nine sub-command files (`mellea-fy-classify.md`, `mellea-fy-inventory.md`, `mellea-fy-map.md`, `mellea-fy-deps.md`, `mellea-fy-fixtures.md`, `mellea-fy-generate.md`, `mellea-fy-artifacts.md`, `mellea-fy-validate.md`, `mellea-fy-repair.md`) in the same directory. Together they define the eight-step decomposition methodology (Steps 0–7).

Supporting infrastructure used during code generation:

- [`src/mellea_skills_compiler/compile/claude/schemas/`](../src/mellea_skills_compiler/compile/claude/schemas/) — JSON Schema contracts for intermediate IR files (`classification`, `inventory`, `element_mapping`, `dependency_plan`, `melleafy`, `config_emission`, `fixtures_emission`, `runtime_defaults`)
- [`src/mellea_skills_compiler/compile/claude/melleafy/writers/`](../src/mellea_skills_compiler/compile/claude/melleafy/writers/) — deterministic Python writers (`config_writer`, `fixtures_writer`)
- [`src/mellea_skills_compiler/compile/claude/data/runtime_defaults.json`](../src/mellea_skills_compiler/compile/claude/data/runtime_defaults.json) — default backend and model_id baked into compiled skills (override per compile via `--backend` / `--model-id`)
