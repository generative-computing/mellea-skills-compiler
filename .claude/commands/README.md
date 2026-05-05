# Shared Claude Code Commands

Custom slash commands available to all team members working in this repo.

## Melleafy v4.3.2

`/mellea-fy` is a 10-step workflow that converts an agent skill spec (`.md`) into a fully typed Mellea Python package. The main command orchestrates all steps; sub-commands can be run individually to resume or re-run a specific step.

| Command                 | File                      | Step          | Description                                                                                                       |
| ----------------------- | ------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------- |
| `/mellea-fy`            | `mellea-fy.md`            | All           | Orchestrator — runs the full 10-step workflow end to end                                                          |
| `/mellea-fy-classify`   | `mellea-fy-classify.md`   | Step 0        | Five-axis classification of the source spec (runtime, modality, archetype, tool disposition, C1–C9)               |
| `/mellea-fy-inventory`  | `mellea-fy-inventory.md`  | Steps 1a + 1b | File inventory and element tagging — produces `inventory.json`                                                    |
| `/mellea-fy-map`        | `mellea-fy-map.md`        | Step 2        | Element-to-primitive mapping — routes each tagged element to a Mellea primitive and target file                   |
| `/mellea-fy-deps`       | `mellea-fy-deps.md`       | Step 2.5      | Dependency audit and elicitation — resolves tool dispositions and produces `dependency_plan.json`                 |
| `/mellea-fy-fixtures`   | `mellea-fy-fixtures.md`   | Step 4        | Fixture generation — produces the `fixtures/` subpackage (5–8 test cases)                                         |
| `/mellea-fy-generate`   | `mellea-fy-generate.md`   | Steps 3 + 5   | Skeleton emission and body generation — produces the populated Python package                                     |
| `/mellea-fy-artifacts`  | `mellea-fy-artifacts.md`  | Step 6        | Supporting artifact generation — produces `mapping_report.md`, `melleafy.json`, `SETUP.md`, `README.md`           |
| `/mellea-fy-validate`   | `mellea-fy-validate.md`   | Step 7        | Static validation — 14 formal lint checks; produces `intermediate/step_7_report.json`                             |
| `/mellea-fy-behaviours` | `mellea-fy-behaviours.md` | Reference     | Known Mellea behaviours and workarounds (KB3–KB9, KB11) — read before generating any code                         |
| `/mellea-fy-repair`     | `mellea-fy-repair.md`     | Repair        | Inspect a partial or failed run, audit every step's artifacts, and resume the pipeline from the first broken step |
