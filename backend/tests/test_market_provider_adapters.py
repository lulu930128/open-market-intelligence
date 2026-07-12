from __future__ import annotations

import inspect
import json
import unittest
from datetime import date
from unittest.mock import patch

import requests

from app.jp_market import service as jp_service
from app.jp_market import sources as jp_sources
from app.jp_market.errors import JPMarketDataFetchError
from app.jp_market.providers import jpx as jp_jpx
from app.jp_market.providers import jquants as jp_jquants
from app.jp_market.providers import yahoo as jp_yahoo
from app.kr_market import service as kr_service
from app.kr_market import sources as kr_sources
from app.kr_market.errors import KRMarketDataFetchError
from app.kr_market.providers import krx, naver, opendart
from app.kr_market.providers import yahoo as kr_yahoo
from app.observability import provider_http
from app.us_market import service as us_service
from app.us_market import sources as us_sources
from app.us_market.errors import USMarketDataFetchError
from app.us_market.providers import alphavantage as us_alphavantage
from app.us_market.providers import finra as us_finra
from app.us_market.providers import fred as us_fred
from app.us_market.providers import nasdaq as us_nasdaq
from app.us_market.providers import sec as us_sec
from app.us_market.providers import yahoo as us_yahoo


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


class MarketProviderAdapterTests(unittest.TestCase):
    def test_legacy_source_exports_keep_error_and_symbol_contracts(self) -> None:
        self.assertIs(us_sources.USMarketDataFetchError, USMarketDataFetchError)
        self.assertIs(jp_sources.JPMarketDataFetchError, JPMarketDataFetchError)
        self.assertIs(kr_sources.KRMarketDataFetchError, KRMarketDataFetchError)
        self.assertEqual(us_sources.normalize_us_symbol("nasdaq:mu"), "MU")
        self.assertEqual(jp_sources.normalize_jp_symbol("7203"), "7203.T")
        self.assertEqual(kr_sources.normalize_kr_symbol("5930"), "005930.KS")

    def test_services_bind_fetchers_from_provider_modules(self) -> None:
        bindings = (
            (
                us_service.fetch_alphavantage_daily_payload,
                us_alphavantage.fetch_alphavantage_daily_payload,
            ),
            (
                us_service.fetch_alphavantage_overview_payload,
                us_alphavantage.fetch_alphavantage_overview_payload,
            ),
            (
                us_service.fetch_alphavantage_dividends_payload,
                us_alphavantage.fetch_alphavantage_dividends_payload,
            ),
            (
                us_service.fetch_alphavantage_splits_payload,
                us_alphavantage.fetch_alphavantage_splits_payload,
            ),
            (
                us_service.fetch_finra_short_volume_payload,
                us_finra.fetch_finra_short_volume_payload,
            ),
            (
                us_service.fetch_fred_series_observations_payload,
                us_fred.fetch_fred_series_observations_payload,
            ),
            (
                us_service.fetch_sec_company_tickers_exchange_payload,
                us_sec.fetch_sec_company_tickers_exchange_payload,
            ),
            (
                us_service.fetch_sec_companyfacts_payload,
                us_sec.fetch_sec_companyfacts_payload,
            ),
            (us_service.fetch_yahoo_chart_payload, us_yahoo.fetch_yahoo_chart_payload),
            (jp_service.fetch_jpx_listed_issues_workbook, jp_jpx.fetch_jpx_listed_issues_workbook),
            (jp_service.fetch_jquants_refresh_token, jp_jquants.fetch_jquants_refresh_token),
            (jp_service.fetch_jquants_id_token, jp_jquants.fetch_jquants_id_token),
            (jp_service.fetch_jquants_statements_payload, jp_jquants.fetch_jquants_statements_payload),
            (jp_service.fetch_jquants_summary_payload, jp_jquants.fetch_jquants_summary_payload),
            (
                jp_service.fetch_jquants_margin_interest_payload,
                jp_jquants.fetch_jquants_margin_interest_payload,
            ),
            (
                jp_service.fetch_jquants_investor_types_payload,
                jp_jquants.fetch_jquants_investor_types_payload,
            ),
            (jp_service.fetch_yahoo_chart_payload, jp_yahoo.fetch_yahoo_chart_payload),
            (
                jp_service.fetch_yahoo_quote_summary_payload,
                jp_yahoo.fetch_yahoo_quote_summary_payload,
            ),
            (kr_service.fetch_naver_index_chart_payload, naver.fetch_naver_index_chart_payload),
            (
                kr_service.fetch_naver_index_intraday_page_payload,
                naver.fetch_naver_index_intraday_page_payload,
            ),
            (
                kr_service.fetch_naver_index_realtime_payload,
                naver.fetch_naver_index_realtime_payload,
            ),
            (kr_service.fetch_krx_stock_master_payload, krx.fetch_krx_stock_master_payload),
            (kr_service.fetch_krx_daily_price_payload, krx.fetch_krx_daily_price_payload),
            (
                kr_service.fetch_krx_investor_trade_payload,
                krx.fetch_krx_investor_trade_payload,
            ),
            (
                kr_service.fetch_opendart_financial_statement_payload,
                opendart.fetch_opendart_financial_statement_payload,
            ),
            (kr_service.fetch_yahoo_chart_payload, kr_yahoo.fetch_yahoo_chart_payload),
        )

        for service_fetcher, provider_fetcher in bindings:
            with self.subTest(fetcher=provider_fetcher.__name__):
                self.assertIs(service_fetcher, provider_fetcher)

    def test_legacy_us_source_fetch_signatures_match_provider_modules(self) -> None:
        bindings = (
            (
                us_sources.fetch_alphavantage_daily_payload,
                us_alphavantage.fetch_alphavantage_daily_payload,
            ),
            (
                us_sources.fetch_alphavantage_overview_payload,
                us_alphavantage.fetch_alphavantage_overview_payload,
            ),
            (
                us_sources.fetch_alphavantage_dividends_payload,
                us_alphavantage.fetch_alphavantage_dividends_payload,
            ),
            (
                us_sources.fetch_alphavantage_splits_payload,
                us_alphavantage.fetch_alphavantage_splits_payload,
            ),
            (
                us_sources.fetch_finra_short_volume_payload,
                us_finra.fetch_finra_short_volume_payload,
            ),
            (
                us_sources.fetch_fred_series_observations_payload,
                us_fred.fetch_fred_series_observations_payload,
            ),
            (
                us_sources.fetch_sec_company_tickers_exchange_payload,
                us_sec.fetch_sec_company_tickers_exchange_payload,
            ),
            (us_sources.fetch_sec_companyfacts_payload, us_sec.fetch_sec_companyfacts_payload),
            (us_sources.fetch_yahoo_chart_payload, us_yahoo.fetch_yahoo_chart_payload),
        )

        for source_fetcher, provider_fetcher in bindings:
            with self.subTest(fetcher=provider_fetcher.__name__):
                self.assertEqual(
                    inspect.signature(source_fetcher),
                    inspect.signature(provider_fetcher),
                )

    def test_legacy_source_fetchers_forward_to_provider_modules(self) -> None:
        us_result = ({"chart": {}}, "https://provider.test/us")
        with patch.object(us_sources.yahoo, "fetch_yahoo_chart_payload", return_value=us_result) as fetch:
            result = us_sources.fetch_yahoo_chart_payload(
                symbol="AAPL",
                range_value="1y",
                interval="1d",
                timeout_seconds=8,
                include_prepost=True,
            )

        self.assertEqual(result, us_result)
        fetch.assert_called_once_with(
            symbol="AAPL",
            range_value="1y",
            interval="1d",
            include_prepost=True,
            timeout_seconds=8,
        )

        jp_result = ({"chart": {}}, "https://provider.test/jp")
        with patch.object(jp_sources.yahoo, "fetch_yahoo_chart_payload", return_value=jp_result) as fetch:
            result = jp_sources.fetch_yahoo_chart_payload(
                symbol="7203",
                range_value="1y",
                interval="1d",
                timeout_seconds=9,
            )

        self.assertEqual(result, jp_result)
        fetch.assert_called_once_with(
            symbol="7203",
            range_value="1y",
            interval="1d",
            timeout_seconds=9,
        )

        kr_result = ({"output": []}, "https://provider.test/kr")
        with patch.object(kr_sources.krx, "fetch_krx_daily_price_payload", return_value=kr_result) as fetch:
            result = kr_sources.fetch_krx_daily_price_payload(
                local_code="005930",
                market_id="STK",
                trade_date=date(2026, 7, 10),
                timeout_seconds=11,
            )

        self.assertEqual(result, kr_result)
        fetch.assert_called_once_with(
            local_code="005930",
            market_id="STK",
            trade_date=date(2026, 7, 10),
            timeout_seconds=11,
        )

    def test_us_alphavantage_redacts_api_key_from_success_source_url(self) -> None:
        response = _response(
            {"Meta Data": {}},
            url=(
                "https://www.alphavantage.co/query?function=OVERVIEW&"
                "symbol=AAPL&apikey=private-key"
            ),
        )
        with patch.object(provider_http.http_client, "request", return_value=response):
            payload, source_url = us_alphavantage.fetch_alphavantage_overview_payload(
                symbol="nasdaq:aapl",
                api_key="private-key",
                timeout_seconds=6,
            )

        self.assertEqual(payload, {"Meta Data": {}})
        self.assertNotIn("private-key", source_url)
        self.assertIn("apikey=REDACTED", source_url)

    def test_us_yahoo_http_error_has_market_provider_context(self) -> None:
        response = _response({}, status_code=429)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            us_yahoo.fetch_yahoo_chart_payload(
                symbol="nasdaq:aapl",
                range_value="1y",
                interval="1d",
                timeout_seconds=8,
            )

        error = raised.exception
        self.assertEqual(error.context.market, "us")
        self.assertEqual(error.context.provider, "yahoo_chart")
        self.assertEqual(error.context.resource, "daily_price")
        self.assertEqual(error.context.target, "AAPL")

    def test_us_symbol_directory_wrapper_uses_nasdaq_provider_payloads(self) -> None:
        listed_text = (
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
            "Round Lot Size|ETF|NextShares\n"
            "AAPL|Apple Inc.|Q|N|N|100|N|N\n"
        )
        other_text = (
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
            "Test Issue|NASDAQ Symbol\n"
            "IBM|International Business Machines|N|IBM|N|100|N|IBM\n"
        )
        with patch.object(
            us_sources.nasdaq,
            "fetch_symbol_directory_payloads",
            return_value=(listed_text, other_text),
        ) as fetch:
            records = us_sources.fetch_symbol_directories(
                include_sec_company_data=False,
                sec_user_agent="",
                timeout_seconds=12,
            )

        self.assertEqual([record.symbol for record in records], ["AAPL", "IBM"])
        fetch.assert_called_once_with(timeout_seconds=12)

    def test_us_sec_rejects_invalid_cik_before_http_request(self) -> None:
        with (
            patch.object(provider_http.http_client, "request") as request,
            self.assertRaisesRegex(USMarketDataFetchError, r"Invalid CIK value: not-a-cik"),
        ):
            us_sec.fetch_sec_companyfacts_payload(
                cik="not-a-cik",
                sec_user_agent="omi-test test@example.com",
                timeout_seconds=8,
            )

        request.assert_not_called()

    def test_jp_yahoo_http_error_has_market_provider_context(self) -> None:
        response = _response({}, status_code=429)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            jp_yahoo.fetch_yahoo_chart_payload(
                symbol="7203",
                range_value="1y",
                interval="1d",
                timeout_seconds=8,
            )

        error = raised.exception
        self.assertEqual(error.context.market, "jp")
        self.assertEqual(error.context.provider, "yahoo_chart")
        self.assertEqual(error.context.resource, "daily_price")
        self.assertEqual(error.context.target, "7203.T")

    def test_jquants_keeps_http_status_fallback_message(self) -> None:
        response = _response({}, status_code=403)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaisesRegex(
                JPMarketDataFetchError,
                r"J-Quants margin-interest failed: HTTP 403\.",
            ) as raised,
        ):
            jp_jquants.fetch_jquants_margin_interest_payload(
                base_url="https://api.jquants.com/v1/",
                api_key="test-key",
                local_code="7203",
                timeout_seconds=7,
            )

        self.assertIsInstance(raised.exception.__cause__, provider_http.ProviderHttpError)

    def test_krx_uses_post_contract_and_keeps_payload_error_message(self) -> None:
        response = _response([], url="https://data.krx.co.kr/response")
        with (
            patch.object(provider_http.http_client, "request", return_value=response) as request,
            self.assertRaisesRegex(
                KRMarketDataFetchError,
                r"KRX stock master returned a non-object JSON payload\.",
            ),
        ):
            krx.fetch_krx_stock_master_payload(timeout_seconds=13)

        args, kwargs = request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(kwargs["timeout"], 13)
        self.assertEqual(kwargs["data"]["bld"], krx.KRX_STOCK_MASTER_BLD)

    def test_kr_opendart_http_error_has_market_provider_context(self) -> None:
        response = _response({}, status_code=503)
        with (
            patch.object(provider_http.http_client, "request", return_value=response),
            self.assertRaises(provider_http.ProviderHttpError) as raised,
        ):
            opendart.fetch_opendart_financial_statement_payload(
                base_url="https://opendart.fss.or.kr/api/",
                api_key="test-key",
                corp_code="00126380",
                fiscal_year=2025,
                report_code="11011",
                timeout_seconds=14,
            )

        error = raised.exception
        self.assertEqual(error.context.market, "kr")
        self.assertEqual(error.context.provider, "opendart_fnltt_singl_acnt_all")
        self.assertEqual(error.context.resource, "financials")
        self.assertEqual(error.context.target, "00126380")


if __name__ == "__main__":
    unittest.main()
