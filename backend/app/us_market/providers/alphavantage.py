from __future__ import annotations

from app.us_market import sources


PROVIDER_NAME = "alphavantage"


def fetch_alphavantage_daily_payload(**kwargs):
    return sources.fetch_alphavantage_daily_payload(**kwargs)


def fetch_alphavantage_overview_payload(**kwargs):
    return sources.fetch_alphavantage_overview_payload(**kwargs)


def fetch_alphavantage_dividends_payload(**kwargs):
    return sources.fetch_alphavantage_dividends_payload(**kwargs)


def fetch_alphavantage_splits_payload(**kwargs):
    return sources.fetch_alphavantage_splits_payload(**kwargs)
