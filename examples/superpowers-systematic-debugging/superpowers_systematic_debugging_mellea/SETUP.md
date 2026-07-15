# Setup: Superpowers Systematic Debugging

## §1 Install

```bash
# From the skill directory
pip install -e .

# Verify
python -c "from superpowers_systematic_debugging_mellea import run_pipeline; print('OK')"
```

Requires Python 3.11 or later.

## §3 Model backend

This skill uses the **Ollama** backend with the **granite4.1:3B** model.

### Install Ollama

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Pull the model
ollama pull granite4.1:3B

# Verify Ollama is running
ollama list
```

### Start Ollama (if not running as a service)

```bash
ollama serve
```

The skill connects to `http://localhost:11434` by default. Ollama must be running before invoking the skill.

### Using a different model or backend

The backend and model are configured in `config.py` as `BACKEND` and `MODEL_ID` constants. To switch, edit those constants and ensure the target model is available in your Ollama installation.

For other supported backends (OpenAI, Bedrock, WatsonX, etc.), refer to the [Mellea backend guide](https://docs.mellea.ai/guide/backends-and-configuration).

## §9 Fixtures and smoke test

Six test fixtures are bundled in `fixtures/`. They exercise the four major input scenarios plus edge cases.

```bash
# Run all fixtures
python -m pytest superpowers_systematic_debugging_mellea/fixtures/ -v
```

Expected output: each fixture's `make_<id>()` factory returns `(inputs, fixture_id, description)` without errors. The fixtures are input factories — they do not invoke the pipeline or require Ollama.

To run the pipeline end-to-end against a fixture:

```python
from superpowers_systematic_debugging_mellea.fixtures import ALL_FIXTURES

for make_fixture in ALL_FIXTURES:
    inputs, fixture_id, description = make_fixture()
    print(f"Running fixture: {fixture_id}")
    # inputs is a dict matching run_pipeline keyword arguments
    from superpowers_systematic_debugging_mellea import run_pipeline
    report = run_pipeline(**inputs)
    print(f"  summary: {report.summary[:80]}")
```

This requires Ollama running with `granite4.1:3B` pulled.
