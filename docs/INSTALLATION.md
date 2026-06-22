# Installation 

## Prerequisites
!!! note "Claude Setup"
    Claude Code is required to compile a Mellea skill. Please ensure that the Claude Code is installed by following the guide here: https://code.claude.com/docs/en/quickstart

### Claude configuration
Set relevant platform-specific environment variables to communicate with your Claude platform.
For example, Claude via LiteLLM Gateway requires following env variables:

```
export ANTHROPIC_BASE_URL = ""
export ANTHROPIC_AUTH_TOKEN = ""
```

or if you have an ANTHROPIC_API_KEY

```
export ANTHROPIC_API_KEY = ""
export ANTHROPIC_BASE_URL = ""
```

### Install project code

Clone code repository

```
git clone https://github.com/generative-computing/mellea-skills-compiler
```

Create Python environment and install library

```bash
# Requires Python >=3.11, <3.14.4
python3 -m venv .venv
source .venv/bin/activate

pip install -e .
```

Set Ollama API URL in the environment variables:

```bash
export OLLAMA_API_URL=<ollama-api-url>
```