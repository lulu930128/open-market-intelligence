from __future__ import annotations

from app.us_market import sources


PROVIDER_NAME = "finra"


def fetch_finra_short_volume_payload(**kwargs):
    return sources.fetch_finra_short_volume_payload(**kwargs)
