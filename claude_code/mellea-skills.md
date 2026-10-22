# Mellea Skills CLI

Execute mellea-skills commands using a dedicated Python environment.

**Your input**: `$ARGUMENTS` — a mellea-skills CLI command with its arguments.

---

## Auto-Memory Setup

**IMPORTANT**: Before executing any command, ensure the feedback memory exists to prevent summarizing output.

Check if the memory file exists:
```bash
ls ~/.claude/projects/-Users-dhaval/memory/feedback_mellea_skills_no_summary.md 2>/dev/null && echo "EXISTS" || echo "CREATE_NEEDED"
```

If `CREATE_NEEDED`, create the memory file:

1. Write the feedback memory:
```
~/.claude/projects/-Users-dhaval/memory/feedback_mellea_skills_no_summary.md
```

With content:
```markdown
---
name: feedback_mellea_skills_no_summary
description: Never summarize mellea-skills CLI output - show raw stdout/stderr only
metadata:
  type: feedback
---

When running mellea-skills commands (compile, validate, run, ingest, certify, export), do NOT add any summary, interpretation, or commentary after the command output.

**Why:** The skill instructions explicitly state: "Never ever summarize results of any command yourself. Always show the output of entire stdout/stderr at the end. The user must see the exact output as produced by the CLI — no paraphrasing, no condensing, no interpretation."

**How to apply:** After a mellea-skills command completes, end the response immediately. No "Certification completed", no bullet points about what passed/failed, no mention of where artifacts were written — the CLI output already says all of that.
```

2. Add entry to `~/.claude/projects/-Users-dhaval/memory/MEMORY.md` (create if needed):
```markdown
- [No mellea-skills summaries](feedback_mellea_skills_no_summary.md) — show raw CLI output only, no interpretation
```

---

## Prerequisites

**IMPORTANT**: Never use the local or current Python environment. Always use the dedicated `mellea-skills` environment.

Before executing any command, ensure the environment is set up:

### 1. Check if the `mellea-skills` environment exists

```bash
ls ~/.claude/envs/mellea-skills/bin/python 2>/dev/null && echo "EXISTS" || echo "NOT_FOUND"
```

### 2. If NOT_FOUND, create the environment

```bash
# Create the envs directory if needed
mkdir -p ~/.claude/envs

# Create Python 3.14 virtual environment (use pyenv or system python)
python3.14 -m venv ~/.claude/envs/mellea-skills

# Activate and install mellea-skills-compiler from git
~/.claude/envs/mellea-skills/bin/pip install --upgrade pip
~/.claude/envs/mellea-skills/bin/pip install git+https://github.com/generative-computing/mellea-skills-compiler.git
```

### 3. Verify mellea-skills-compiler is installed

```bash
~/.claude/envs/mellea-skills/bin/python -c "import mellea_skills_compiler; print(mellea_skills_compiler.__version__)"
```

If not installed or outdated, install/upgrade:
```bash
~/.claude/envs/mellea-skills/bin/pip install git+https://github.com/generative-computing/mellea-skills-compiler.git
```

### Environment Path

All commands must use this Python:
```
~/.claude/envs/mellea-skills/bin/python
```

---

## Available Commands

### compile
Compile a Mellea skill specification into a Mellea pipeline.

```
mellea-skills compile <spec_path> [OPTIONS]
```

**Arguments:**
- `spec_path` (required): Path to the Mellea skill specification or folder containing skill specs

**Options:**
- `--model, -m`: Claude model for compiling (default: Sonnet)
- `--timeout, -t`: Compile session timeout in seconds (default: 4500 / 75min)
- `--repair-mode, -r`: Identify and correct errors in compilation
- `--skip-smoke-check`: Skip post-compile fixture smoke-check
- `--refresh-cache`: Force refresh of grounding caches
- `--skill-backend`: Override LLM backend for compiled skill runtime
- `--skill-model`: Override model id for compiled skill runtime
- `--backend, -b`: Compilation backend ['claude', 'bob'] (default: claude)

**Examples:**
```bash
mellea-skills compile skills/weather/spec.md
mellea-skills compile skills/weather/ --model claude-sonnet-4-20250514 --timeout 6000
mellea-skills compile skills/myskill/spec.md --repair-mode --backend bob
```

---

### validate
Validate a compiled Mellea skill (Step 7 lints + fixture smoke-check).

```
mellea-skills validate <pipeline_dir> [OPTIONS]
```

**Arguments:**
- `pipeline_dir` (required): Compiled skill pipeline directory (e.g. `skills/<name>/<name>_mellea/`)

**Options:**
- `--no-run`: Skip post-lint fixture smoke-check
- `--all`: Run all fixtures (default: first only)

**Exit codes:**
- `0`: Lints passed, smoke-check passed or skipped
- `11`: At least one lint failed
- `12`: Smoke-check failed (lints passed, but fixture raised exception)

**Examples:**
```bash
mellea-skills validate skills/weather/weather_mellea/
mellea-skills validate skills/myskill/myskill_mellea/ --no-run
mellea-skills validate skills/myskill/myskill_mellea/ --all
```

---

### run
Run a Mellea Skill Pipeline.

```
mellea-skills run <pipeline_dir> [OPTIONS]
```

**Arguments:**
- `pipeline_dir` (required): Compiled skill pipeline directory

**Options (mutually exclusive input sources):**
- `--input, -i`: Raw input value; use `file://` to read from file, `-` for stdin
- `--fixture, -f`: Use a pre-canned fixture

**Guardian options:**
- `--enforce, -e`: Block execution when Guardian detects risks (default: audit-only)
- `--no-guardian, -ng`: Skip Guardian checks even if policy manifest exists
- `--guardian-model`: Model for Risk Assessment
- `--inference-engine`: Service for LLM inference ['ollama', 'vllm'] (default: ollama)

**Examples:**
```bash
mellea-skills run skills/weather/weather_mellea/ --fixture fixture_sunny_day
mellea-skills run skills/weather/weather_mellea/ --input "What's the weather in NYC?"
mellea-skills run skills/weather/weather_mellea/ --input "file://input.txt" --enforce
mellea-skills run skills/myskill/myskill_mellea/ --input - --no-guardian
```

---

### ingest
Run Risk Analysis and Policy Generation Pipeline for a Mellea skill.

```
mellea-skills ingest <spec_path> [OPTIONS]
```

**Arguments:**
- `spec_path` (required): Mellea Skill spec path

**Options:**
- `--dry-run`: Preview without making LLM calls
- `--risk-model`: Model for Risk and Action Identification
- `--inference-engine, -i`: Service for LLM inference ['ollama', 'vllm'] (default: ollama)

**Examples:**
```bash
mellea-skills ingest skills/weather/spec.md
mellea-skills ingest skills/myskill/spec.md --dry-run
mellea-skills ingest skills/myskill/spec.md --risk-model llama3.2 --inference-engine ollama
```

---

### certify
Run Full Certification Pipeline for a Mellea skill.

```
mellea-skills certify <pipeline_dir> [OPTIONS]
```

**Arguments:**
- `pipeline_dir` (required): Compiled skill pipeline directory

**Options:**
- `-n`: Number of fixtures to evaluate (default: 3)
- `--enforce, -e`: Run pipeline in enforce mode (block on risk detection)
- `--risk-model`: Model for Risk and Action Identification
- `--guardian-model`: Model for Risk Assessment
- `--inference-engine`: Service for LLM inference ['ollama', 'vllm'] (default: ollama)

**Examples:**
```bash
mellea-skills certify skills/weather/weather_mellea/
mellea-skills certify skills/weather/weather_mellea/ -n 5 --enforce
mellea-skills certify skills/myskill/myskill_mellea/ --risk-model llama3.2 --guardian-model llama3.2
```

---

### export
[EXPERIMENTAL] Export a compiled Mellea skill to a deployment target.

```
mellea-skills export <package_path> --target <target> [OPTIONS]
```

**Arguments:**
- `package_path` (required): Path to compiled skill directory (must contain `melleafy.json`)

**Options:**
- `--target, -t` (required): Deployment target ['langgraph', 'claude-code', 'mcp', 'pi']
- `--force, -f`: Overwrite output directory if it exists
- `--enforce, -e`: Register Guardian in enforce mode (default: audit-only)

**Output:** Written to `<package_name>/<package_name>-<target>` inside the skill directory.

**Examples:**
```bash
mellea-skills export skills/weather/weather_mellea/ --target mcp
mellea-skills export skills/weather/weather_mellea/ --target langgraph --force
mellea-skills export skills/myskill/myskill_mellea/ --target claude-code --enforce
```

---

### version
Print the installed mellea-skills-compiler package version.

```
mellea-skills version
```

---

## Execution

When the user provides a command via `$ARGUMENTS`:

1. **Ensure environment exists**: First, check if the `mellea-skills` environment exists and has the compiler installed:
   ```bash
   ~/.claude/envs/mellea-skills/bin/python -c "import mellea_skills_compiler" 2>/dev/null && echo "READY" || echo "SETUP_NEEDED"
   ```

   If `SETUP_NEEDED`, run the setup steps from the Prerequisites section before proceeding.

2. **Parse the command**: Extract the subcommand (compile, validate, run, ingest, certify, export, version) and its arguments.

3. **Validate the command**: Check that:
   - The subcommand is one of the valid commands listed above
   - Required arguments are provided
   - Options use the correct flags and formats
   - Mutually exclusive options are not combined (e.g., `--input` and `--fixture` for `run`)

4. **Report errors clearly**: If validation fails, output a clear error message:
   ```
   Error: <specific issue>

   Usage: mellea-skills <command> [OPTIONS]

   <show correct usage for the attempted command>
   ```

5. **Execute the command**:

   **IMPORTANT**: Always use the dedicated environment Python, never the system or local Python.

   Run the command using the **Bash tool**:
   ```bash
   ~/.claude/envs/mellea-skills/bin/python -u -m mellea_skills_compiler.cli <parsed_command>
   ```

   Set appropriate timeouts for long-running commands:
   - `compile`: 1800000ms (30 minutes)
   - `certify`: 1800000ms (30 minutes)
   - Other commands: 300000ms (5 minutes, default)

6. **Report results**: After the command completes, output the **entire stdout/stderr** directly to the user in a code block. Do not summarize or truncate — show the complete output exactly as produced. On failure, also include the exit code.

   **CRITICAL**: Never ever summarize results of any command yourself. Always show the output of entire stdout/stderr at the end. The user must see the exact output as produced by the CLI — no paraphrasing, no condensing, no interpretation.

---

## Error Handling

### Unknown command
```
Error: Unknown command '<command>'

Available commands: compile, validate, run, ingest, certify, export, version

Run 'mellea-skills --help' for more information.
```

### Missing required argument
```
Error: Missing required argument '<argument>' for command '<command>'

Usage: mellea-skills <command> <required_args> [OPTIONS]

Example: mellea-skills <command> <example_usage>
```

### Invalid option
```
Error: Unknown option '<option>' for command '<command>'

Valid options for '<command>':
<list of valid options>
```

### Mutually exclusive options
```
Error: Options '<option1>' and '<option2>' are mutually exclusive for command '<command>'

Use one or the other, not both.
```

### Invalid option value
```
Error: Invalid value '<value>' for option '<option>'

Expected: <expected_format_or_values>
```

---

## Quick Reference

| Command   | Required Args      | Key Options                                    |
|-----------|--------------------|------------------------------------------------|
| compile   | spec_path          | --model, --timeout, --repair-mode, --backend   |
| validate  | pipeline_dir       | --no-run, --all                                |
| run       | pipeline_dir       | --input OR --fixture, --enforce, --no-guardian |
| ingest    | spec_path          | --dry-run, --risk-model, --inference-engine    |
| certify   | pipeline_dir       | -n, --enforce, --risk-model, --guardian-model  |
| export    | package_path       | --target (required), --force, --enforce        |
| version   | (none)             | (none)                                         |
