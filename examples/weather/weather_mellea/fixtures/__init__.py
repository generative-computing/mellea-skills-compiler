"""
Fixture coverage:
  C1 Identity (persona applied, graceful edge handling): current_weather_city, out_of_scope_historical, query_no_location
  C2 Operating rules (scope gate, query-type routing): current_weather_city, rain_check_city, week_forecast, out_of_scope_historical, query_no_location, detailed_conditions_city
  C6 Tools (fetch_weather called with various endpoint params): current_weather_city, rain_check_city, week_forecast, airport_code_lookup, detailed_conditions_city
  C8 Runtime environment (airport code resolution, wttr.in features): airport_code_lookup
"""
from typing import Callable

from .airport_code_lookup import make_airport_code_lookup
from .current_weather_city import make_current_weather_city
from .detailed_conditions_city import make_detailed_conditions_city
from .out_of_scope_historical import make_out_of_scope_historical
from .query_no_location import make_query_no_location
from .rain_check_city import make_rain_check_city
from .week_forecast import make_week_forecast


ALL_FIXTURES: list[Callable] = [
    make_current_weather_city,
    make_rain_check_city,
    make_week_forecast,
    make_airport_code_lookup,
    make_out_of_scope_historical,
    make_query_no_location,
    make_detailed_conditions_city,
]
