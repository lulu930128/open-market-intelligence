from __future__ import annotations

import json
import unittest
from datetime import date
from unittest.mock import patch

import requests

from app.market import (
    broker_branch,
    index_parsers,
    indices,
    institutional_holding_ratios,
    intraday,
    market_chips,
    quote_depth,
)
from app.market.providers import http_get as taiwan_http_get
from app.market.providers import taifex, tpex, twse, twse_mis, yahoo
from app.observability import provider_http


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


class TaiwanIndexProviderAdapterTests(unittest.TestCase):
    def test_twse_index_5s_uses_explicit_provider_context_and_timeout(self) -> None:
        response = _response({"stat": "OK", "fields": [], "data": []})
        with patch.object(provider_http.http_client, "request", return_value=response) as request:
            payload = twse.fetch_index_5s_payload(
                date(2026, 7, 10),
                timeout_seconds=7,
            )

        self.assertEqual(payload["stat"], "OK")
        args, kwargs = request.call_args
        self.assertEqual(args[:2], ("GET", twse.INDEX_5S_URL))
        self.assertEqual(kwargs["timeout"], 7)
        self.assertEqual(kwargs["params"]["date"], "20260710")

    def test_twse_index_5s_http_error_keeps_taiwan_context(self) -> None:
        response = _response({}, status_code=429)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            twse.fetch_index_5s_payload(date(2026, 7, 10), timeout_seconds=6)

        error = raised.exception
        self.assertEqual(error.context.market, "tw")
        self.assertEqual(error.context.provider, "twse_index_5s")
        self.assertEqual(error.context.resource, "index_intraday")
        self.assertEqual(error.context.target, "TAIEX")
        self.assertTrue(error.rate_limited)

    def test_twse_index_daily_ohlc_uses_explicit_provider_context_and_timeout(
        self,
    ) -> None:
        response = _response({"stat": "OK", "fields": [], "data": []})
        with patch.object(
            provider_http.http_client,
            "request",
            return_value=response,
        ) as request:
            payload = twse.fetch_index_daily_ohlc_payload(
                date(2026, 7, 30),
                timeout_seconds=9,
            )

        self.assertEqual(payload["stat"], "OK")
        args, kwargs = request.call_args
        self.assertEqual(args[:2], ("GET", twse.INDEX_DAILY_OHLC_URL))
        self.assertEqual(kwargs["timeout"], 9)
        self.assertEqual(kwargs["params"]["date"], "20260730")
        self.assertEqual(kwargs["params"]["response"], "json")

    def test_twse_index_daily_ohlc_http_error_keeps_taiwan_context(self) -> None:
        response = _response({}, status_code=429)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            twse.fetch_index_daily_ohlc_payload(
                date(2026, 7, 30),
                timeout_seconds=6,
            )

        error = raised.exception
        self.assertEqual(error.context.market, "tw")
        self.assertEqual(error.context.provider, "twse_index_daily_ohlc")
        self.assertEqual(error.context.resource, "index_daily_ohlc")
        self.assertEqual(error.context.target, "TAIEX")
        self.assertTrue(error.rate_limited)

    def test_tpex_index_5s_uses_official_date_contract(self) -> None:
        response = _response(
            {
                "stat": "ok",
                "date": "20260730",
                "tables": [],
            }
        )
        with patch.object(
            provider_http.http_client,
            "request",
            return_value=response,
        ) as request:
            payload = tpex.fetch_index_5s_payload(
                date(2026, 7, 30),
                timeout_seconds=8,
            )

        self.assertEqual(payload["stat"], "ok")
        args, kwargs = request.call_args
        self.assertEqual(args[:2], ("GET", tpex.INDEX_5S_URL))
        self.assertEqual(kwargs["timeout"], 8)
        self.assertEqual(kwargs["params"]["date"], "2026/07/30")
        self.assertEqual(kwargs["params"]["response"], "json")

    def test_tpex_index_5s_http_error_keeps_intraday_context(self) -> None:
        response = _response({}, status_code=429)
        with (
            patch.object(
                provider_http.http_client,
                "request",
                return_value=response,
            ),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            tpex.fetch_index_5s_payload(
                date(2026, 7, 30),
                timeout_seconds=6,
            )

        error = raised.exception
        self.assertEqual(error.context.market, "tw")
        self.assertEqual(error.context.provider, tpex.INDEX_5S_PROVIDER)
        self.assertEqual(error.context.resource, "index_intraday")
        self.assertEqual(error.context.target, "TPEX")
        self.assertTrue(error.rate_limited)

    def test_tpex_market_highlight_uses_official_date_contract(self) -> None:
        response = _response(
            {
                "stat": "ok",
                "date": "20260529",
                "tables": [],
            }
        )
        with patch.object(
            provider_http.http_client,
            "request",
            return_value=response,
        ) as request:
            payload = tpex.fetch_market_highlight_payload(
                date(2026, 5, 29),
                timeout_seconds=8,
            )

        self.assertEqual(payload["stat"], "ok")
        args, kwargs = request.call_args
        self.assertEqual(args[:2], ("GET", tpex.MARKET_HIGHLIGHT_URL))
        self.assertEqual(kwargs["timeout"], 8)
        self.assertEqual(kwargs["params"]["date"], "2026/05/29")
        self.assertEqual(kwargs["params"]["response"], "json")

    def test_tpex50_history_uses_explicit_provider_context(self) -> None:
        response = _response({}, status_code=429)
        with (
            patch.object(
                provider_http.http_client,
                "request",
                return_value=response,
            ) as request,
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            tpex.fetch_tpex50_index_history_payload(timeout_seconds=7)

        args, kwargs = request.call_args
        self.assertEqual(args[:2], ("GET", tpex.TPEX50_INDEX_URL))
        self.assertEqual(kwargs["timeout"], 7)
        self.assertEqual(raised.exception.context.provider, tpex.PROVIDER)
        self.assertEqual(raised.exception.context.resource, "index_daily_history")
        self.assertEqual(raised.exception.context.target, "TPEX50")
        self.assertTrue(raised.exception.rate_limited)

    def test_tpex200_close_uses_explicit_provider_context(self) -> None:
        response = _response({}, status_code=429)
        with (
            patch.object(
                provider_http.http_client,
                "request",
                return_value=response,
            ) as request,
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            tpex.fetch_tpex200_close_payload(timeout_seconds=9)

        args, kwargs = request.call_args
        self.assertEqual(args[:2], ("GET", tpex.TPEX200_CHANGE_URL))
        self.assertEqual(kwargs["timeout"], 9)
        self.assertEqual(raised.exception.context.provider, tpex.PROVIDER)
        self.assertEqual(raised.exception.context.resource, "index_close")
        self.assertEqual(raised.exception.context.target, "TPEX200")
        self.assertTrue(raised.exception.rate_limited)

    def test_tpex_json_adapter_classifies_daily_quote_resource(self) -> None:
        response = _response([])
        with patch.object(provider_http.http_client, "request", return_value=response):
            payload = tpex.fetch_json(tpex.DAILY_QUOTES_URL, timeout_seconds=5)

        self.assertEqual(payload, [])

        failing_response = _response({}, status_code=503)
        with (
            patch.object(
                provider_http.http_client,
                "request",
                return_value=failing_response,
            ),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            tpex.fetch_json(tpex.DAILY_QUOTES_URL, timeout_seconds=5)

        self.assertEqual(raised.exception.context.market, "tw")
        self.assertEqual(raised.exception.context.provider, "tpex_openapi")
        self.assertEqual(raised.exception.context.resource, "daily_quotes")
        self.assertEqual(raised.exception.context.target, "TPEX")

    def test_yahoo_index_adapter_normalizes_request_contract(self) -> None:
        response = _response({"chart": {"result": []}})
        with patch.object(provider_http.http_client, "request", return_value=response) as request:
            payload = yahoo.fetch_index_chart_payload(
                symbol="^TWII",
                range_value="1d",
                interval="1m",
                timeout_seconds=9,
            )

        self.assertEqual(payload, {"chart": {"result": []}})
        args, kwargs = request.call_args
        self.assertEqual(args[0], "GET")
        self.assertTrue(args[1].endswith("/%5ETWII"))
        self.assertEqual(kwargs["timeout"], 9)
        self.assertEqual(kwargs["params"]["includePrePost"], "false")

    def test_twse_mis_rejects_unavailable_payload(self) -> None:
        response = _response({"rtcode": "9999", "msgArray": []})
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaisesRegex(ValueError, "payload is unavailable"),
        ):
            twse_mis.fetch_stock_messages(["2330"], timeout_seconds=4)

    def test_taiwan_read_paths_share_provider_transport_boundary(self) -> None:
        for module in (
            indices,
            market_chips,
            institutional_holding_ratios,
            broker_branch,
        ):
            with self.subTest(module=module.__name__):
                self.assertIs(module.http_get, taiwan_http_get)

        self.assertFalse(hasattr(intraday, "http_get"))
        self.assertFalse(hasattr(quote_depth, "http_get"))

    def test_taifex_compatibility_get_keeps_provider_context(self) -> None:
        response = _response({}, status_code=503)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            taiwan_http_get(
                "https://www.taifex.com.tw/cht/3/futContractsDate",
                params={"queryDate": "2026/07/10"},
                timeout=8,
            )

        error = raised.exception
        self.assertEqual(error.context.market, "tw")
        self.assertEqual(error.context.provider, taifex.PROVIDER)
        self.assertEqual(error.context.resource, "futures_institutional_contracts")
        self.assertEqual(error.context.target, "2026/07/10")

    def test_indices_keeps_legacy_http_get_injection_seam(self) -> None:
        response = _response({"stat": "OK", "date": "20260710", "fields": [], "data": []})
        with (
            patch.object(indices, "http_get", return_value=response) as http_get,
            patch.object(twse, "fetch_index_5s_payload", return_value=response.json()) as fetch,
        ):
            with self.assertRaisesRegex(ValueError, "field .* not found"):
                indices._fetch_twse_index_5s_intraday(
                    {"index_id": "TAIEX", "symbol": "^TWII"},
                    trade_date=date(2026, 7, 10),
                )

        http_get.assert_not_called()
        fetch.assert_called_once_with(
            date(2026, 7, 10),
            timeout_seconds=20,
            request=http_get,
        )

    def test_pure_parsers_keep_empty_and_malformed_contracts(self) -> None:
        self.assertEqual(index_parsers.parse_twse_market_daily_history_rows({}), [])
        self.assertEqual(index_parsers.parse_tpex_market_daily_rows({"unexpected": []}), [])
        self.assertIsNone(index_parsers.parse_trade_date("not-a-date"))
        self.assertIsNone(index_parsers.as_float("--"))


if __name__ == "__main__":
    unittest.main()
