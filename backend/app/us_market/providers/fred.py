from __future__ import annotations

from datetime import date
from typing import Any

from app.us_market.errors import USMarketDataFetchError

from ._http import get as provider_get
from ._http import redact_url_params


PROVIDER_NAME = "fred"
FRED_SERIES_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred_series_observations_payload(
    *,
    series_id: str,
    api_key: str,
    timeout_seconds: int,
    observation_start: date | None = None,
    observation_end: date | None = None,
) -> tuple[dict[str, Any], str]:
    normalized_series_id = series_id.strip().upper()
    params: dict[str, str] = {
        "series_id": normalized_series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    if observation_start is not None:
        params["observation_start"] = observation_start.isoformat()
    if observation_end is not None:
        params["observation_end"] = observation_end.isoformat()

    response = provider_get(
        FRED_SERIES_OBSERVATIONS_URL,
        provider=PROVIDER_NAME,
        resource="macro_series",
        target=normalized_series_id,
        params=params,
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()

    if not isinstance(payload, dict):
        raise USMarketDataFetchError("FRED returned a non-object JSON payload.")
    if "error_code" in payload:
        raise USMarketDataFetchError(str(payload.get("error_message") or payload["error_code"]))

    return payload, redact_url_params(response.url)
