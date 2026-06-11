# Quick Start

## Introduction
In this section you will:

    1. choose a skill
    2. choose an Ollama model
    3. choose your CLI and run the commands!

## Choose a skill to work with.
Download one of the skill specifications from GitHub or use your own specification file.

- Example skills: https://github.com/generative-computing/mellea-skills-compiler/tree/main/skills

## Choose your Ollama models

We recommend downloading the Ollama models `granite3.3:8b` and `ibm/granite3.3-guardian:8b` beforehand, as they are set as defaults.

For Risk Identification

```
ollama pull granite3.3:8b
```

For Risk Assessment

```
ollama pull ibm/granite3.3-guardian:8b
```

### Node.js Interactive CLI

Begin operation by using the Mellea Skills Compiler Node.js Interactive CLI or skip to the next step to use command-based CLI.

```
./mellea-skills-ui.sh
```

### Command-based CLI

### Compile Agent Skill - Option 1 (Recommended)

Compile a skill into a typed Mellea pipeline via the CLI:

```bash
mellea-skills compile <Your-local-path>/skills/weather/spec.md  # if skill is a single spec file.
mellea-skills compile <Your-local-path>/skills/weather          # if skill is a directory containing spec files
```

Compile uses Sonnet as the default claude model. To use different claude model,

```bash
mellea-skills compile <Your-local-path>/skills/weather/spec.md --model aws/claude-opus-4-5
mellea-skills compile <Your-local-path>/skills/weather --model aws/claude-opus-4-5
```

Melleafy Repair: Identify and correct any errors effectively in Mellea skill compilation

```bash
mellea-skills compile --repair-mode <Your-local-path>/skills/weather --model aws/claude-opus-4-5
```

### Compile Agent Skill - Option 2 (Using Claude Code)

Run `/mellea-fy` directly inside Claude Code:

```bash
./mellea-fy <Your-local-path>/skills/weather/spec.md
```

See [`mellea-fy/README.md`](https://github.com/generative-computing/mellea-skills-compiler/blob/main/mellea-fy/README.md) for detailed usage of the Claude Code command.

### Run Skill Pipeline

Run skill pipeline for a given fixture

```bash
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --fixture rain_check   # provide path to the compiled skill directory and the fixture name
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --enforce              # Block execution when Guardian detects risks (default: audit-only)
mellea-skills run <Your-local-path>/skills/weather/weather_mellea --no_guardian          # Skip Guardian checks even if a policy manifest exists.
```

### Run Full Certification Pipeline for Mellea skill

Run end-to-end certification — risk identification via AI Atlas Nexus, Guardian hook instrumentation, fixture execution, and compliance report — in a single command:

```bash
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea                      # provide path to the compiled skill directory
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea --enforce            # Block on risk detection
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea --fixture rain_check # Run specific fixture - rain_check
mellea-skills certify <Your-local-path>/skills/weather/weather_mellea --model granite3.3:8b --guardian-model ibm/granite3.3-guardian:8b --inference-engine ollama    # Using different risk model, guardian model and inference engine
```

### Export Compiled Mellea Skill

Export a compiled Mellea skill to a deployment target - langgraph, claude-code, or mcp

**Note**: This command is experimental. Output structure and CLI interface may change in future releases without a deprecation period.

```bash
mellea-skills export --target mcp <Your-local-path>/skills/weather/weather_mellea         # Supported deployment target: mcp, langgraph, claude-code
mellea-skills export --target mcp --force <Your-local-path>/skills/weather/weather_mellea # '--force' overwrites output directory if it already exists.
```

### Certification artifacts

All outputs are written to `audit/` adjacent to the compiled directory:

```
skills/weather/audit/
├── policy_manifest.json        # Policy manifest (risks + governance actions)
├── POLICY.md                   # Human-readable policy document
├── CERTIFICATION.md            # Certification report with coverage summary
├── audit_trail.jsonl           # Runtime Guardian verdicts
└── pipeline_report.json        # Pipeline execution output
```