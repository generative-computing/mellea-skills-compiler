# Skills

Agent skill specifications for the Mellea Skills Compiler. Each directory contains a `spec.md` (or `SKILL.md` for non-Markdown source runtimes) — the natural-language specification that can be compiled, instrumented, and certified.

Pre-compiled, runnable examples for a curated subset of these skills live under [`examples/`](../examples/). The tutorial in [`docs/`](../docs/TUTORIAL.md) walks through running them.

## What you can do with a skill in this directory

1. **Run a pre-compiled example** if the skill is in [`examples/`](../examples/) — the package is already built and ships fixtures, lints, and a smoke check. See [`docs/TUTORIAL.md`](../docs/TUTORIAL.md).
2. **Compile your own** from the spec via `mellea-skills compile skills/<name>/spec.md`. The compile pipeline emits a `<name>_mellea/` package alongside the spec.
3. **Fill stubs** if the compile output uses `NotImplementedError` placeholders for tool integrations the spec couldn't pin down. See [`docs/FROM_STUBS_TO_RUNNING.md`](../docs/FROM_STUBS_TO_RUNNING.md).

## Tier overview

Each skill is classified by what's required to run a fixture against the compiled package:

- **T1** — Runs out of the box. No stubs to fill, no external services, no credentials. Only the project baseline (Ollama + `granite3.3:8b`) is required.
- **T2** — Runs after filling 1–2 stubs (`raise NotImplementedError(...)` in `constrained_slots.py`) or supplying a small bundled artifact. Other branches of the pipeline run unchanged.
- **T3** — Requires external integration before *any* fixture can complete: a service login, an API key, an installed CLI, or a runtime helper that ships outside the package.

| Skill | Tier | What's needed to run |
|---|---|---|
| [`weather`](weather/) | T1 | Nothing — public no-auth HTTP to `wttr.in` |
| [`superpowers-systematic-debugging`](superpowers-systematic-debugging/) | T1 | Nothing — pure reasoning |
| [`sentry-code-review`](sentry-code-review/) | T1 | Nothing — pure reasoning over user-supplied diffs |
| [`security-review`](security-review/) | T1 | Nothing — pure reasoning over user-supplied artifacts (bundled OWASP reference docs) |
| [`dstiliadis-security-review`](dstiliadis-security-review/) | T1 | Nothing — pure reasoning |
| [`security-engineer`](security-engineer/) | T1 | Nothing — pure reasoning |
| [`checklist`](checklist/) | T1 | A `scripts/bash/check-prerequisites.sh` (bundled with the skill) |
| [`sentry-find-bugs`](sentry-find-bugs/) | **T1 / T2** | Clean-diff fixtures run with no setup; codebase-scanning fixtures need two stubs filled (`search_fn`, `read_file_fn`) — see [`docs/FROM_STUBS_TO_RUNNING.md`](../docs/FROM_STUBS_TO_RUNNING.md) |
| [`anthropic-doc-coauthoring`](anthropic-doc-coauthoring/) | T2 / T3 | Multiple stubs depending on which integrations the user wires (Slack / Drive / MCP) |
| [`anthropic-webapp-testing`](anthropic-webapp-testing/) | T3 | Playwright + Chromium installed |
| [`1password`](1password/) | T3 | 1Password CLI signed in; tmux env vars set |
| [`appdeploy`](appdeploy/) | T3 | `APPDEPLOY_API_KEY` env var; HTTP access to `api-v2.appdeploy.ai` |
| [`coding-agent`](coding-agent/) | T3 | Each delegate tool (Codex / Claude Code / Pi) installed and on `PATH` |
| [`github`](github/) | T3 | `gh auth login` complete |
| [`slack`](slack/) | T3 | Slack OAuth token configured |
| [`clawdefender`](clawdefender/) | T3 | Bundled `scripts/*.sh` need `chmod +x` on Unix; full audit/sanitize/scan_skill modes additionally need `jq`, `npx`, and `clawhub` on `PATH`. The bundled `prompt_injection_critical` fixture exercises the pure-Python `check_prompt` mode and runs without externals. |

Tier is descriptive, not prescriptive — a T3 skill can still be useful as a learning example or as a starting point for your own integration work.

## Source attribution

### Sentry (Apache 2.0)

| Skill | Source |
|---|---|
| `sentry-code-review` | [getsentry/sentry-mcp](https://github.com/getsentry/sentry-mcp) |
| `sentry-find-bugs` | [getsentry/sentry-mcp](https://github.com/getsentry/sentry-mcp) |
| `security-review` | [getsentry/sentry-mcp](https://github.com/getsentry/sentry-mcp) |

### Anthropic (Apache 2.0)

| Skill | Source |
|---|---|
| `anthropic-doc-coauthoring` | [anthropics/skills](https://github.com/anthropics/skills) |
| `anthropic-webapp-testing` | [anthropics/skills](https://github.com/anthropics/skills) |

### Community (MIT)

| Skill | Source | Description |
|---|---|---|
| `dstiliadis-security-review` | [dstiliadis/security-review-skill](https://github.com/dstiliadis/security-review-skill) | Threat model → attack emulation → fix → pen test |
| `superpowers-systematic-debugging` | [obra/superpowers](https://github.com/obra/superpowers) | Hypothesis-driven debugging with phased investigation |

### OpenClaw skills

From the [OpenClaw](https://github.com/openclaw) project (MIT):

| Skill | Description |
|---|---|
| `weather` | Weather forecasts via `wttr.in` |
| `slack` | Slack messaging and reactions (11 actions) |
| `checklist` | Requirements quality checklist generator |
| `1password` | 1Password CLI secrets management |
| `github` | GitHub CLI operations |
| `appdeploy` | App deployment automation |
| `coding-agent` | Delegate to Codex / Claude Code / Pi |
| `security-engineer` | Multi-domain security assessment |
| `clawdefender` | Adversarial-input classification (prompt injection / SSRF / command injection / credential exfiltration) |

## Compiling a skill

```bash
# Fresh compile from the spec
mellea-skills compile skills/weather/spec.md
```

The compile pipeline runs `/mellea-fy` for specification decomposition, then chains into a deterministic writer pipeline that renders `config.py` and `fixtures/` from intermediate JSON. The structural lints (Step 7) and a fixture smoke check run automatically after compile; pass `--no-run` to skip the smoke check.

## Running a fixture

Once compiled (or against one of the pre-compiled examples in [`examples/`](../examples/)):

```bash
mellea-skills run <package_dir> --fixture <fixture_id>
```

Each compiled `<name>_mellea/` package ships a `fixtures/` subdirectory with several fixture inputs. The fixture id matches the filename in `fixtures/` (without the `.py` extension).

## Adding a new skill

1. Create a directory under `skills/` with a `spec.md` (single-file `.md` source). Support for other source formats — `agents.yaml` + `crew.py` for CrewAI, `.af` for Letta, LangGraph Python, etc. — is **experimental**; see [`mellea-fy-inventory.md`](../src/mellea_skills_compiler/compile/claude/commands/mellea-fy-inventory.md) for the dialect detection table.
2. Compile with `mellea-skills compile skills/<name>/<spec_file>` or directly via `/mellea-fy` in Claude Code.
3. The compile output emits `skills/<name>/<package>_mellea/` with the full pipeline + fixtures + lints + smoke check.
4. If you want the skill to ship as a canonical pre-compiled example, copy the resulting package to `examples/<name>/` and add it to the tier table above.
