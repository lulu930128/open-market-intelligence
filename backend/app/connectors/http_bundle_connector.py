import json

import requests

from app.connectors.base import BaseConnector, FetchResult, utc_now
from app.connectors.http_api_connector import _decode_response_text
from app.db.models import SourceRegistry


class HttpBundleConnector(BaseConnector):
    connector_name = "http_bundle"

    def fetch(self, source: SourceRegistry) -> FetchResult:
        if not source.endpoint_url:
            return FetchResult(
                source_name=source.source_name,
                fetched_at=utc_now(),
                status="error",
                error_message="endpoint_url is required for HTTP bundle source.",
            )

        try:
            endpoints = json.loads(source.endpoint_url)
        except json.JSONDecodeError as exc:
            return FetchResult(
                source_name=source.source_name,
                fetched_at=utc_now(),
                status="error",
                error_message=f"endpoint_url should be a JSON object: {exc}",
            )

        if not isinstance(endpoints, dict) or not endpoints:
            return FetchResult(
                source_name=source.source_name,
                fetched_at=utc_now(),
                status="error",
                error_message="endpoint_url should be a non-empty JSON object.",
            )

        headers = {
            "User-Agent": "OpenMarketIntelligence/0.4 (+local development)",
            "Accept": "application/json,text/csv,text/plain,text/html,*/*",
        }

        bundle: dict[str, dict] = {}
        had_error = False
        error_messages: list[str] = []

        for name, endpoint_url in endpoints.items():
            if not isinstance(endpoint_url, str) or not endpoint_url:
                had_error = True
                error_messages.append(f"{name}: endpoint URL is empty.")
                continue

            try:
                response = requests.get(endpoint_url, headers=headers, timeout=30)
                raw_text = _decode_response_text(response)

                bundle[name] = {
                    "url": endpoint_url,
                    "method": "GET",
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "raw_text": raw_text,
                }

                if not response.ok:
                    had_error = True
                    error_messages.append(f"{name}: HTTP {response.status_code}")

            except requests.RequestException as exc:
                had_error = True
                error_messages.append(f"{name}: {exc}")
                bundle[name] = {
                    "url": endpoint_url,
                    "method": "GET",
                    "status_code": None,
                    "content_type": None,
                    "raw_text": None,
                    "error_message": str(exc),
                }

        raw_text = json.dumps(bundle, ensure_ascii=False, sort_keys=True)

        return FetchResult(
            source_name=source.source_name,
            fetched_at=utc_now(),
            status="error" if had_error else "success",
            url=source.endpoint_url,
            method="GET_BUNDLE",
            status_code=502 if had_error else 200,
            content_type="application/json",
            raw_text=raw_text,
            message="Bundle fetch completed." if not had_error else "Bundle fetch completed with errors.",
            error_message="; ".join(error_messages) if error_messages else None,
        )
