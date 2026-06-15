from __future__ import annotations

from app.us_market import sources


PROVIDER_NAME = "sec_edgar"


def fetch_sec_company_tickers_exchange_payload(**kwargs):
    return sources.fetch_sec_company_tickers_exchange_payload(**kwargs)


def fetch_sec_companyfacts_payload(**kwargs):
    return sources.fetch_sec_companyfacts_payload(**kwargs)
