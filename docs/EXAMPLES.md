#Examples

## Example Outputs

The [`examples/`](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples) directory contains pre-compiled, validated Mellea pipeline packages — runnable end-to-end against the project's Ollama + `granite3.3:8b` baseline. Each is a curated reference snapshot of what `mellea-skills compile` produces under the current architecture.

| Skill                                                                          | Tier    | Archetype                  | Description                                                                                                                                    |
| ------------------------------------------------------------------------------ | ------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| [weather](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples/weather/)                                                   | T1      | Fetch + summarise          | Public no-auth HTTP to `wttr.in`; intent classification dispatches to one of seven URL templates                                               |
| [sentry-find-bugs](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples/sentry-find-bugs/)                                 | T1 / T2 | Structured analysis        | Multi-phase OWASP review producing severity-classified findings; two stub helpers (`search_fn`, `read_file_fn`) for codebase-scanning fixtures |
| [superpowers-systematic-debugging](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples/superpowers-systematic-debugging/) | T1      | Constrained reasoning      | Four-phase debugging walk with hypothesis testing; `fix_attempts_count >= 3` triggers architectural-issue branch                               |
| [clawdefender](https://github.com/generative-computing/mellea-skills-compiler/tree/main/examples/clawdefender/)                                         | T3      | Adversarial classification | Prompt injection / SSRF / command injection / credential exfiltration detection; bundled scripts need `chmod +x` on Unix                       |

Each example includes the original `spec.md` (or `SKILL.md`), generated pipeline code, factory-shape fixtures, intermediate IR (`config_emission.json`, `fixtures_emission.json`, etc.), `mapping_report.md`, and `melleafy.json` manifest. See [`docs/TUTORIAL.md`](docs/TUTORIAL.md) for the runnable tutorial that walks through each one and [`docs/FROM_STUBS_TO_RUNNING.md`](docs/FROM_STUBS_TO_RUNNING.md) for the stub-implementation walkthrough.



The [`skills/`](skills/) directory contains 16 skill specifications drawn from multiple sources (Sentry, Anthropic, community contributions, and IBM Research). Four of these ship as pre-compiled examples (see above); the rest can be compiled locally via `mellea-skills compile skills/<name>/spec.md`.

Skills are classified into three tiers by what's needed to run a fixture against the compiled package:

- **T1** — Runs out of the box. No stubs, no external services, no credentials.
- **T2** — Runs after filling 1–2 stubs or supplying a small bundled artifact.
- **T3** — Requires external integration before any fixture completes (CLI tool, API key, OAuth, runtime helper).

See [`skills/README.md`](skills/README.md) for the full per-skill tier table and source attribution.