# JSON Schemas for Melleafy Intermediate Artifacts

This directory holds JSON Schemas (draft 2020-12) that formalise the contracts between
melleafy steps and between the model and the deterministic writers. The schemas are the
**source of truth** for the on-disk shape of every JSON artifact melleafy produces.

## Two categories

### Emission contracts

The model emits JSON conforming to the schema; a deterministic Python writer reads that
JSON and renders the final artifact (Python source, multiple files, etc.). The schema
prevents shape drift in the LLM's output before any rendering happens.

| Schema                          | Writer                                        | Renders                                  |
| ------------------------------- | --------------------------------------------- | ---------------------------------------- |
| `config_emission.schema.json`   | `.claude/melleafy/writers/config_writer.py`   | `config.py`                              |
| `fixtures_emission.schema.json` | `.claude/melleafy/writers/fixtures_writer.py` | `fixtures/*.py` + `fixtures/__init__.py` |

### Intermediate contracts

The model emits JSON conforming to the schema; the next melleafy step reads the JSON.
These schemas formalise the contracts between Steps 0 → 1b → 2 → 2.5 → 6.

| Schema                        | Source doc                                         | Documents                                               |
| ----------------------------- | -------------------------------------------------- | ------------------------------------------------------- |
| `classification.schema.json`  | `mellea-fy-classify.md`                            | `intermediate/classification.json` (Step 0)             |
| `inventory.schema.json`       | `mellea-fy-inventory.md`                           | `intermediate/inventory.json` (Step 1b)                 |
| `element_mapping.schema.json` | `mellea-fy-map.md`                                 | `intermediate/element_mapping.json` (Step 2)            |
| `dependency_plan.schema.json` | `mellea-fy-deps.md`                                | `intermediate/dependency_plan.json` (Step 2.5c)         |
| `melleafy.schema.json`        | `mellea-fy-artifacts.md` + `mellea-fy-generate.md` | `melleafy.json` (Step 3 skeleton + Step 6 finalisation) |

## Conventions

- `$schema`: always `https://json-schema.org/draft/2020-12/schema`.
- `additionalProperties: false` on every object — no silent acceptance of unknown keys.
- `required` arrays for every mandatory field; optional fields stay out of `required`.
- `pattern` for identifier shapes (`^elem_[0-9]{3,}$`, `^[A-Z][A-Z0-9_]*$`, etc.).
- `enum` for closed-set fields (categories, dispositions, runtimes, modalities).
- `description` strings on every property — these double as inline documentation.
- `$defs` for shapes reused across two or more properties.
- Top-level `description` names the source doc and the consuming Steps.

## Adding a new schema

1. Author the schema in this directory using the file naming convention
   `<artifact-name>.schema.json` (matches the artifact's filename stem).
2. Match the style of an existing schema exactly — start by copying the closest
   neighbour (`config_emission.schema.json` for emission contracts,
   `inventory.schema.json` for intermediate contracts).
3. Add a `> **Schema**: Output ... MUST conform to ../schemas/<name>.schema.json.`
   blockquote immediately after the `**Produces**:` line in the source command file
   (`../commands/mellea-fy-*.md`, sibling to this directory).
4. Add a row to the appropriate table above.

## Validation status (Phase 1)

Today these schemas are **reference-only**: melleafy steps do not import them at runtime
and there is no automated validate-on-write boundary check. The LLM is expected to
conform to the schema (and the schemas are short, declarative, and intended to be quoted
in step-prompt grounding contexts when needed). Phase 2 will introduce Python validation
at boundaries — most likely a single `_validate_or_halt(schema_path, payload)` helper
called by each step before writing, paired with explicit halt codes for malformed
intermediate files. Until then, JSON-parseability and visual conformance are the only
checks.
