from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import requests

from app.crypto_market import sources as crypto_sources
from app.crypto_market.contract import BINANCE_PROVIDER
from app.crypto_market.providers import request_json as crypto_request_json
from app.observability import provider_http
from app.resource_market import sources as resource_sources
from app.resource_market.providers import yahoo as resource_yahoo


def _response(
    payload: object,
    *,
    url: str = "https://provider.test/data",
    status_code: int = 200,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response._content = json.dumps(payload).encode("utf-8")
    response.encoding = "utf-8"
    return response


class CryptoResourceProviderAdapterTests(unittest.TestCase):
    def test_crypto_rest_adapter_classifies_provider_resource_and_target(self) -> None:
        response = _response({}, status_code=429)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            crypto_request_json(
                "https://api.binance.com/api/v3/depth",
                params={"symbol": "BTCUSDT", "limit": 20},
                timeout_seconds=7,
            )

        error = raised.exception
        self.assertEqual(error.context.market, "crypto")
        self.assertEqual(error.context.provider, BINANCE_PROVIDER)
        self.assertEqual(error.context.resource, "order_book")
        self.assertEqual(error.context.target, "BTCUSDT")
        self.assertTrue(error.rate_limited)

    def test_crypto_source_wrapper_preserves_provider_failure_as_cause(self) -> None:
        response = _response({}, status_code=503)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(crypto_sources.CryptoMarketDataFetchError) as raised,
        ):
            crypto_sources._request_json(
                "https://api.binance.com/api/v3/ticker/24hr",
                params={"symbol": "BTCUSDT"},
            )

        failure = provider_http.provider_http_failure(raised.exception)
        self.assertIsNotNone(failure)
        self.assertEqual(failure.context.resource, "ticker")

    def test_resource_yahoo_adapter_uses_resource_market_context(self) -> None:
        response = _response({}, status_code=429)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            resource_yahoo.fetch_chart_payload(
                provider_symbol="GC=F",
                range_value="1mo",
                interval="1d",
                timeout_seconds=8,
            )

        error = raised.exception
        self.assertEqual(error.context.market, "resource")
        self.assertEqual(error.context.provider, "yahoo_chart")
        self.assertEqual(error.context.resource, "ohlcv")
        self.assertEqual(error.context.target, "GC=F")

    def test_resource_source_wrapper_keeps_public_payload_contract(self) -> None:
        result = ({"chart": {"result": []}}, "https://provider.test/resource")
        with patch.object(resource_sources.yahoo, "fetch_chart_payload", return_value=result) as fetch:
            payload, source_url = resource_sources.fetch_yahoo_chart_payload(
                provider_symbol="GC=F",
                range_value="1mo",
                interval="1d",
                timeout_seconds=6,
            )

        self.assertEqual(payload, result[0])
        self.assertEqual(source_url, result[1])
        fetch.assert_called_once_with(
            provider_symbol="GC=F",
            range_value="1mo",
            interval="1d",
            timeout_seconds=6,
        )


if __name__ == "__main__":
    unittest.main()
