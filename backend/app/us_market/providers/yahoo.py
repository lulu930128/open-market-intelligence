from __future__ import annotations

from app.us_market import sources


PROVIDER_NAME = "yahoo_chart"


def fetch_yahoo_chart_payload(**kwargs):
    return sources.fetch_yahoo_chart_payload(**kwargs)
