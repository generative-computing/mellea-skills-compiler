# weather-mellea Setup Guide

## §1 Prerequisites

### Runtime binary: curl

This skill uses `curl` to fetch weather data from wttr.in. Ensure `curl` is installed and available on `PATH` in the execution environment.

**macOS**:

```bash
curl --version   # likely pre-installed
brew install curl  # upgrade if needed
```

**Debian/Ubuntu**:

```bash
sudo apt-get install -y curl
```

**Alpine (Docker)**:

```bash
apk add --no-cache curl
```

**Verify**:

```bash
curl -s "wttr.in/London?format=3"
# Expected: London: ⛅  +14°C
```

## §2 Network access

The skill requires outbound HTTP/HTTPS access to `wttr.in` (port 443). This is a public service with no authentication.

- No API key required
- Rate-limited by wttr.in — do not issue more than ~1 request per second
- Most global cities and IATA airport codes are supported

## §3 Python environment

```bash
pip install -e ".[dev]"   # from skills/weather/
# or
pip install weather-mellea
```

Requires Python ≥ 3.11 and `mellea[hooks] ≥ 0.4.2`.

## §4 Backend configuration

The skill uses Ollama with `granite3.3:8b` by default. Ensure Ollama is running locally:

```bash
ollama serve &
ollama pull granite3.3:8b
```

Verify:

```bash
ollama list | grep granite
```

## §5 Verification

Run the test fixtures:

```bash
cd skills/weather
python -m pytest weather_mellea/fixtures/ -v
```

Run a quick end-to-end check:

```bash
weather-mellea "What's the weather in Dublin?"
```
