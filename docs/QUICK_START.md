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

We recommend downloading the Ollama models `granite4.1:3b` and `ibm/granite3.3-guardian:8b` beforehand, as they are set as defaults.

For Risk Identification

```
ollama pull granite4.1:3b
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

The steps below take the weather skill from spec to certified pipeline. The [CLI reference](CLI.md) covers every command and flag.

**1. Compile** the spec into a typed Mellea pipeline. This creates `skills/weather/weather_mellea/`:

```bash
mellea-skills compile skills/weather/spec.md                  # Claude Code backend (default)
mellea-skills compile skills/weather/spec.md --backend bob    # or IBM Bob
mellea-skills compile skills/weather/spec.md --backend pi     # or pi, see Using with pi
```

To skip compiling, use the pre-compiled copy at `examples/weather/weather_mellea` in the steps below.

**2. Validate** the compiled pipeline (static lints + a fixture smoke-check):

```bash
mellea-skills validate skills/weather/weather_mellea
```

**3. Run** it against an input or a fixture:

```bash
mellea-skills run skills/weather/weather_mellea --input "What's the weather like in Dublin?"
mellea-skills run skills/weather/weather_mellea --fixture rain_check_city
```

**4. Certify** it: risk identification, Guardian instrumentation, fixture execution, and a compliance report:

```bash
mellea-skills certify skills/weather/weather_mellea
```

Certification artifacts are written to a timestamped directory under `skills/weather/audit/`. See [Output directories](CLI.md#output-directories).

You can also compile from inside an agent session with the `/mellea-fy` slash command (Claude Code, IBM Bob), or with `/mellea-compile` in pi. See [Using with pi](PI_SETUP.md).
