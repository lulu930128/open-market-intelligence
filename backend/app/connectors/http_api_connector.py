from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from app.connectors.base import BaseConnector, FetchResult, utc_now
from app.db.models import SourceRegistry
from app.http_client import get as http_get


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _render_endpoint_url(endpoint_url: str) -> str:
    today = datetime.now(TAIPEI_TZ).strftime("%Y%m%d")
    return (
        endpoint_url.replace("{today_yyyyMMdd}", today)
        .replace("{today_yyyymmdd}", today)
    )


TEXT_DECODING_CANDIDATES = (
    "utf-8-sig",
    "utf-8",
    "cp950",
    "big5",
)


def _decode_response_text(response: requests.Response) -> str:
    """
    Decode HTTP response body explicitly.

    Some TWSE/MOPS CSV endpoints are UTF-8 CSV files, but requests may guess
    the encoding incorrectly. If we store response.text directly, Chinese
    headers can become mojibake and downstream parsers cannot find fields such
    as "公司代號".
    """
    content = response.content or b""

    if not content:
        return ""

    content_type = response.headers.get("content-type", "").lower()
    url = response.url.lower()

    should_try_csv_decoding = (
        "text/csv" in content_type
        or "application/csv" in content_type
        or url.endswith(".csv")
    )

    if should_try_csv_decoding:
        for encoding in TEXT_DECODING_CANDIDATES:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue

    if response.encoding:
        try:
            return content.decode(response.encoding)
        except (LookupError, UnicodeDecodeError):
            pass

    return response.text


class HttpAPIConnector(BaseConnector):
    connector_name = "http_api"

    def fetch(self, source: SourceRegistry) -> FetchResult:
        if not source.endpoint_url:
            return FetchResult(
                source_name=source.source_name,
                fetched_at=utc_now(),
                status="error",
                error_message="endpoint_url is required for HTTP API source.",
            )

        endpoint_url = _render_endpoint_url(source.endpoint_url)

        headers = {
            "User-Agent": "OpenMarketIntelligence/0.4 (+local development)",
            "Accept": "application/json,text/csv,text/plain,text/html,*/*",
        }

        try:
            response = http_get(
                endpoint_url,
                headers=headers,
                timeout=30,
            )

            content_type = response.headers.get("content-type")
            raw_text = _decode_response_text(response)

            return FetchResult(
                source_name=source.source_name,
                fetched_at=utc_now(),
                status="success" if response.ok else "error",
                url=endpoint_url,
                method="GET",
                status_code=response.status_code,
                content_type=content_type,
                raw_text=raw_text,
                message="Fetch completed." if response.ok else "Fetch returned non-2xx status.",
                error_message=None if response.ok else f"HTTP {response.status_code}",
            )

        except requests.RequestException as exc:
            return FetchResult(
                source_name=source.source_name,
                fetched_at=utc_now(),
                status="error",
                url=endpoint_url,
                method="GET",
                error_message=str(exc),
            )
