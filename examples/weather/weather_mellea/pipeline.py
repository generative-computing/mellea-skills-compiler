from __future__ import annotations

from mellea import start_session
from mellea.backends.model_options import ModelOption
from mellea.stdlib.sampling import RepairTemplateStrategy
from pydantic import BaseModel
from weather_mellea.config import (
    BACKEND,
    LOOP_BUDGET,
    MODEL_ID,
    OUT_OF_SCOPE_CATEGORIES,
    PREFIX_TEXT,
    WEATHER_PRESET_FULL_CONDITIONS,
    WEATHER_PRESET_RAIN_CHECK,
    WEATHER_PRESET_WEEK_FORECAST,
)
from weather_mellea.schemas import WeatherIntent, WeatherQueryType
from weather_mellea.slots import extract_location
from weather_mellea.tools import fetch_weather


# ── KB1: parse helpers — call immediately after every m.instruct(format=Model) ──

def _parse_instruct_result(thunk, model_class: type[BaseModel]):
    """Parse m.instruct(format=Model) result. Raises ValidationError on failure."""
    return model_class.model_validate_json(thunk.value)


def _safe_parse_with_fallback(thunk, model_class: type[BaseModel], **fallback_kwargs):
    """Parse m.instruct result; return a default model instance on any parse failure."""
    try:
        return model_class.model_validate_json(thunk.value)
    except Exception:
        return model_class(**fallback_kwargs)


# ── Deterministic URL-param dispatch (P2 pattern) ────────────────────────────

_ENDPOINT_PARAMS: dict[WeatherQueryType, str] = {
    WeatherQueryType.current_summary: WEATHER_PRESET_FULL_CONDITIONS,
    WeatherQueryType.current_detailed: "?0",
    WeatherQueryType.forecast_3day: "",
    WeatherQueryType.forecast_week: WEATHER_PRESET_WEEK_FORECAST,
    WeatherQueryType.forecast_day0: "?0",
    WeatherQueryType.forecast_day1: "?1",
    WeatherQueryType.forecast_day2: "?2",
    WeatherQueryType.json_output: "?format=j1",
    WeatherQueryType.rain_check: WEATHER_PRESET_RAIN_CHECK,
}


def _build_endpoint_params(query_type: WeatherQueryType) -> str:
    """Deterministically map an intent to a wttr.in endpoint parameter string."""
    return _ENDPOINT_PARAMS.get(query_type, "?format=3")


def _url_encode_location(location: str) -> str:
    """Replace spaces with '+' for wttr.in URL compatibility."""
    return location.strip().replace(" ", "+")


# ── Pipeline entry point ──────────────────────────────────────────────────────

def run_pipeline(query: str) -> str:
    """Fetch weather data for the given natural-language query.

    Args:
        query: A natural-language weather request
               (e.g. "What's the weather in Dublin?").

    Returns:
        Weather data as a plain-text string from wttr.in, or an out-of-scope
        message when the query cannot be handled by this skill.
    """
    # ── Session 1: extract location (@generative) ────────────────────────────
    # KB5: separate session — @generative produces its own internal response schema.
    with start_session(BACKEND, MODEL_ID) as m:
        location_raw: str = extract_location(m, query=query)

    # ── Session 2: classify intent + scope check ─────────────────────────────
    # KB5: separate session from Session 1 (WeatherIntent ≠ ExtractLocationResponse).
    with start_session(BACKEND, MODEL_ID) as m:
        intent_thunk = m.instruct(
            "Classify this weather query and determine whether it is in scope.",
            model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},  # KB7
            grounding_context={
                "query": str(query),
                "extracted_location": str(location_raw),
                "out_of_scope_categories": str(OUT_OF_SCOPE_CATEGORIES),
            },
            format=WeatherIntent,
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),  # KB2
        )
        # KB1: parse immediately — thunk is NOT a Pydantic model
        intent = _safe_parse_with_fallback(
            intent_thunk,
            WeatherIntent,
            query_type=WeatherQueryType.out_of_scope,
            location=location_raw.strip() if location_raw.strip() else None,
        )

    # ── Scope gate (DECIDE element — deterministic Python) ───────────────────
    if intent.query_type == WeatherQueryType.out_of_scope:
        reason = intent.out_of_scope_reason or "not a supported weather query type"
        return (
            f"This query is outside the scope of the weather skill ({reason}). "
            "Please consult a specialized source for this type of request."
        )

    # ── Location resolution ──────────────────────────────────────────────────
    resolved = intent.location or (location_raw.strip() if location_raw.strip() else None)
    if not resolved:
        return (
            "Please include a city, region, or airport code in your weather query "
            "(e.g. 'What is the weather in Tokyo?')."
        )
    encoded_location = _url_encode_location(resolved)

    # ── Deterministic URL construction + tool dispatch ───────────────────────
    endpoint_params = _build_endpoint_params(intent.query_type)
    return fetch_weather(encoded_location, endpoint_params)
