from __future__ import annotations

from datetime import date

from ._http import get as provider_get


PROVIDER_NAME = "finra"
FINRA_SHORT_VOLUME_URL_TEMPLATE = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"


def fetch_finra_short_volume_payload(
    *,
    trade_date: date,
    timeout_seconds: int,
) -> tuple[str, str]:
    url = FINRA_SHORT_VOLUME_URL_TEMPLATE.format(date=trade_date.strftime("%Y%m%d"))
    response = provider_get(
        url,
        provider=PROVIDER_NAME,
        resource="short_volume",
        timeout_seconds=timeout_seconds,
    )
    return response.text, url
