from typing import Final


# === C1: Identity & Behavioral Context ===
SKILL_NAME: Final[str] = 'weather'
# PROVENANCE: spec.md:2-3

SKILL_DESCRIPTION: Final[str] = 'Get current weather and forecasts via wttr.in'
# PROVENANCE: spec.md:2-3

PREFIX_TEXT: Final[str] = 'You are a weather assistant. You help users get current weather conditions and forecasts using wttr.in. Be concise, factual, and only respond to weather-related queries.'
# PROVENANCE: spec.md:1-6

USE_WHEN_EXAMPLES: Final[str] = """What's the weather?
Will it rain today/tomorrow?
Temperature in [city]
Weather forecast for the week
Travel planning weather checks"""
# PROVENANCE: spec.md:14-20

# === C2: Operating Rules ===
OUT_OF_SCOPE_CATEGORIES: Final[str] = 'historical weather data, climate analysis or trends, hyper-local microclimate data, severe weather alerts, aviation/marine weather'
# PROVENANCE: spec.md:24-30

# === C6: Tools ===
WEATHER_PRESET_FULL_CONDITIONS: Final[str] = '?format=%l:+%c+%t+(feels+like+%f),+%w+wind,+%h+humidity'
# PROVENANCE: spec.md:89-93

WEATHER_PRESET_RAIN_CHECK: Final[str] = '?format=%l:+%c+%p'
# PROVENANCE: spec.md:95-99

WEATHER_PRESET_WEEK_FORECAST: Final[str] = '?format=v2'
# PROVENANCE: spec.md:101-105

# === C8: Runtime Environment ===
BACKEND: Final[str] = 'ollama'
# PROVENANCE: intermediate/runtime_directive.json:1-6

MODEL_ID: Final[str] = 'granite3.3:8b'
# PROVENANCE: intermediate/runtime_directive.json:1-6

WTTR_BASE_URL: Final[str] = 'wttr.in'
# PROVENANCE: spec.md:109-112

WTTR_REQUIRES_API_KEY: Final[bool] = False
# PROVENANCE: spec.md:109

REQUIRED_BINS: Final[str] = 'curl'
# PROVENANCE: spec.md:5-6

LOOP_BUDGET: Final[int] = 3
