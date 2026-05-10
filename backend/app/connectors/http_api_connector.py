import requests

from app.connectors.base import BaseConnector, FetchResult, utc_now
from app.db.models import SourceRegistry


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

        headers = {
            "User-Agent": "OpenMarketIntelligence/0.2 (+local development)",
            "Accept": "application/json,text/plain,text/html,*/*",
        }

        try:
            response = requests.get(
                source.endpoint_url,
                headers=headers,
                timeout=30,
            )

            content_type = response.headers.get("content-type")

            return FetchResult(
                source_name=source.source_name,
                fetched_at=utc_now(),
                status="success" if response.ok else "error",
                url=source.endpoint_url,
                method="GET",
                status_code=response.status_code,
                content_type=content_type,
                raw_text=response.text,
                message="Fetch completed." if response.ok else "Fetch returned non-2xx status.",
                error_message=None if response.ok else f"HTTP {response.status_code}",
            )

        except requests.RequestException as exc:
            return FetchResult(
                source_name=source.source_name,
                fetched_at=utc_now(),
                status="error",
                url=source.endpoint_url,
                method="GET",
                error_message=str(exc),
            )