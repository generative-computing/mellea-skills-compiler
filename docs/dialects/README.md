# Mellea-fy Dialect Documentation

Per-runtime mapping rules consumed by Steps 0, 1, and 2 of the `mellea-fy` workflow:

- **Step 0** (classification): the source-runtime axis 4 selects which dialect applies.
- **Steps 1a/1b** (inventory): the dialect doc lists the files to read and the roles they play.
- **Step 2** (mapping): the dialect doc supplies overrides that take precedence over the general primitive-mapping table.

## Naming convention

Each file is `<runtime>.md` where `<runtime>` matches the value of `classification.json:source_runtime` (and the entries in the Step 0 axis-4 table in `mellea-fy-classify.md`).

## Supported runtimes (this directory)

| Runtime | File | Status |
|---|---|---|
| `agent_skills_std` | `agent-skills-std.md` | Mature |
| `claude_code` | `claude-code.md` | Mature |
| `openclaw` | `openclaw.md` | Mature |
| `crewai` | `crewai.md` | Mature |
| `langgraph` | `langgraph.md` | Mature |
| `letta` | `letta.md` | Mature |
| `hybrid` | `hybrid.md` | Mature (rules for ambiguous classifications) |

## Stubbed runtimes (not yet shipped here)

The following are recognised by the Step 0 classifier but do not yet have shipping dialect docs in this directory; the compiler falls back to the generic inventory and mapping rules for them, with a warning surfaced in the run's `mapping_report.md`:

- `autogen`
- `openai_agents_sdk`
- `smolagents`

## What if my runtime is not listed at all?

The Step 0 classifier returns `unknown`. The compiler proceeds with the generic inventory pass and the general mapping table; the package will be generated but without runtime-specific knowledge. Open a discussion if your runtime is widely used and you want a dedicated dialect doc.
