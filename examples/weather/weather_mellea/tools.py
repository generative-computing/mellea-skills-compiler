from __future__ import annotations

import subprocess

from weather_mellea.config import WTTR_BASE_URL


HTTP_TIMEOUT: int = 10
CURL_EXTRA_TIMEOUT: int = 5


def fetch_weather(location: str, endpoint_params: str) -> str:
    """Fetch weather data from wttr.in for the given location and endpoint parameters.

    Args:
        location: URL-encoded city name, region, or IATA airport code.
        endpoint_params: wttr.in query string or path suffix (e.g. '?format=3', '?1').

    Returns:
        Raw text response from wttr.in.

    Raises:
        ValueError: If the constructed URL targets a host other than WTTR_BASE_URL.
        RuntimeError: If curl exits with a non-zero code or times out.
    """
    url = f"https://{WTTR_BASE_URL}/{location}{endpoint_params}"

    # Domain guard — only WTTR_BASE_URL is permitted
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.hostname != WTTR_BASE_URL:
        raise ValueError(f"Constructed URL targets unexpected host '{parsed.hostname}'")

    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", str(HTTP_TIMEOUT), url],
            capture_output=True,
            text=True,
            timeout=HTTP_TIMEOUT + CURL_EXTRA_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Weather fetch timed out after {HTTP_TIMEOUT + CURL_EXTRA_TIMEOUT}s"
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"curl exited with code {result.returncode}: {result.stderr.strip()}"
        )

    return result.stdout.strip()
