from __future__ import annotations

from app.us_market import sources


PROVIDER_NAME = "fred"


def fetch_fred_series_observations_payload(**kwargs):
    return sources.fetch_fred_series_observations_payload(**kwargs)
