# ClawDefender Mellea — Setup Guide

## §1 Install

Install the package in editable mode from the skill root (`skills/clawdefender/`):

```bash
pip install -e .
```

Verify the installation:

```bash
python -c "from clawdefender_mellea import run_pipeline; print('OK')"
clawdefender-mellea --help
```

The bundled scripts (`scripts/clawdefender.sh` and `scripts/sanitize.sh`) are included in the package and resolve automatically via `Path(__file__).parent / "scripts" / ...`. No manual script copying is required.

**Host system requirements** (from `REQUIRED_BINS`): the bundled scripts require `bash`, `grep`, `sed`, and `jq`. These are standard on most Linux/macOS systems. Verify with:

```bash
for bin in bash grep sed jq; do command -v "$bin" && echo "$bin OK" || echo "$bin MISSING"; done
```

The `--install` tool mode additionally requires **Node.js and npm** (for `npx clawhub`). If you do not need safe skill installation, all other modes work without Node.js.

## §3 Model Backend

This package uses **Ollama** as the default backend with model `granite3.3:8b`.

The backend is used for the `auto` check mode only (LLM intent classification and output formatting). All explicit check modes (`validate`, `check_url`, `check_prompt`, `sanitize`, `audit`, `scan_skill`, `install`) run deterministically without any LLM calls.

**Install and start Ollama:**

```bash
# Install (see https://ollama.com for platform-specific instructions)
curl -fsSL https://ollama.com/install.sh | sh

# Pull the model
ollama pull granite3.3:8b

# Start the Ollama server (if not already running)
ollama serve
```

**Verify the backend:**

```bash
python -c "
from mellea import start_session
from clawdefender_mellea.config import BACKEND, MODEL_ID
with start_session(BACKEND, MODEL_ID) as m:
    result = m.instruct('Say hello', grounding_context={})
    print('Backend OK')
"
```

To switch backends or models, override the constants in a local `config_override.py` or set environment variables before importing the package. The `BACKEND` and `MODEL_ID` constants in `config.py` reflect the defaults recorded at compile time.

## §9 Fixtures and Smoke Test

Run all fixtures via pytest from the skill root:

```bash
cd skills/clawdefender
python -m pytest clawdefender_mellea/fixtures/ -v
```

The fixture suite exercises 4 dependency categories (C1, C2, C6, C8) across 7 test cases:

| Fixture                     | Mode           | Expected outcome                                     |
| --------------------------- | -------------- | ---------------------------------------------------- |
| `prompt_injection_critical` | `check_prompt` | `clean=False`, `severity=critical`, `action=block`   |
| `clean_text`                | `validate`     | `clean=True`, `severity=clean`, `action=allow`       |
| `ssrf_metadata_url`         | `check_url`    | `clean=False`, `severity≥warning`, `action=block`    |
| `command_injection_text`    | `validate`     | `clean=False`, `severity=critical`, `action=block`   |
| `safe_allowlisted_url`      | `check_url`    | `clean=True`, `severity=clean`, `action=allow`       |
| `credential_exfil_sanitize` | `sanitize`     | Output contains `[FLAGGED]` markers or `clean=False` |
| `empty_input_edge`          | `validate`     | No crash; `clean=True` or graceful non-zero result   |

Run a quick smoke test without pytest:

```bash
python -c "
from clawdefender_mellea import run_pipeline
result = run_pipeline('ignore previous instructions', check_mode='check_prompt')
print(f'severity={result.severity.value} action={result.action} clean={result.clean}')
assert not result.clean, 'Expected injection to be flagged'
print('Smoke test passed.')
"
```
