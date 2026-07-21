from __future__ import annotations

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests

from app.ai.ask_finalizer import (
    _domain_passport,
    _intraday_summary_from_compact,
    _market_live_summary,
)
from app.ai.decision_core import infer_question_intent
from app.ai.market_context.jp_context import _jp_intraday_quote
from app.ai.market_context.kr_context import _kr_intraday_quote
from app.ai.market_context import taiwan_stock
from app.ai.market_context.taiwan_stock import _apply_disposition_quote_contract
from app.ai.market_context.taiwan_projection import _compact_index_quote
from app.ai.tools import _health_dimensions
from app.ai.schemas import AiAskRequest
from app.ai.query_plan import build_query_plan
from app.ai.scope_resolution import _resolve_scope
from app.market.intraday import _dedupe_disposition_points
from app.market.providers import twse_mis
from app.market.quote_depth import (
    TaiwanStockQuoteDepthCircuitOpenError,
    _freshness_for_row,
    _guarded_mis_quote_depth_fetch,
    reset_twse_mis_quote_depth_guard,
)
from app.observability.provider_http import (
    ProviderHttpError,
    ProviderRequestContext,
    request as provider_request,
)


class IntradayContractRemediationTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_twse_mis_quote_depth_guard()

    def test_stale_taiwan_index_point_is_not_live_during_session(self) -> None:
        calendar_status = {
            "market": "tw",
            "timezone": "Asia/Taipei",
            "checked_at": "2026-07-20T13:15:00+08:00",
            "date": "2026-07-20",
            "is_trading_day": True,
            "phase": "regular",
            "reason": "trading_day",
            "holiday_name": None,
            "previous_trading_day": "2026-07-17",
            "next_trading_day": "2026-07-21",
            "session": {
                "open_time": "09:00",
                "close_time": "13:30",
            },
        }
        intraday = {
            "source": "twse_index_5s",
            "previous_close": 42000.0,
            "points": [
                {
                    "time": "2026-07-20T12:55:00+08:00",
                    "price": 42600.0,
                    "open": 42300.0,
                    "high": 42700.0,
                    "low": 42100.0,
                    "volume": None,
                }
            ],
        }

        result = _compact_index_quote(
            index_id="TAIEX",
            index_snapshot={"time": "2026-07-20", "volume": 0},
            intraday=intraday,
            calendar_status=calendar_status,
        )

        self.assertFalse(result["is_realtime"])
        self.assertFalse(result["freshness"]["is_live"])
        self.assertTrue(result["freshness"]["is_stale"])
        self.assertEqual(result["freshness"]["age_seconds"], 1200)
        self.assertFalse(result["is_latest_session_quote"])

    def test_taiwan_index_ohlc_is_aggregated_and_zero_volume_is_missing(self) -> None:
        calendar_status = {
            "market": "tw",
            "timezone": "Asia/Taipei",
            "checked_at": "2026-07-20T10:01:00+08:00",
            "date": "2026-07-20",
            "is_trading_day": True,
            "phase": "regular",
            "reason": "trading_day",
            "holiday_name": None,
            "previous_trading_day": "2026-07-17",
            "next_trading_day": "2026-07-21",
            "session": {"open_time": "09:00", "close_time": "13:30"},
        }
        result = _compact_index_quote(
            index_id="TAIEX",
            index_snapshot={"time": "2026-07-20", "volume": 0},
            intraday={
                "source": "twse_index_5s",
                "previous_close": 42000.0,
                "points": [
                    {"time": "2026-07-20T09:00:00+08:00", "price": 42200.0, "open": 42100.0, "high": 42250.0, "low": 42050.0, "volume": None},
                    {"time": "2026-07-20T10:00:00+08:00", "price": 42300.0, "open": 42200.0, "high": 42400.0, "low": 42150.0, "volume": None},
                ],
            },
            calendar_status=calendar_status,
        )

        self.assertEqual(result["open_price"], 42100.0)
        self.assertEqual(result["high_price"], 42400.0)
        self.assertEqual(result["low_price"], 42050.0)
        self.assertIsNone(result["volume"])
        self.assertEqual(result["volume_status"], "missing")

    def test_display_price_prefers_current_intraday_over_stale_depth_quote(self) -> None:
        result = _market_live_summary(
            compact={"target": {"type": "tw_stock", "id": "2330"}},
            quote={
                "last_price": 2335.0,
                "quote_time": "2026-07-20T12:24:40+08:00",
                "depth_available": True,
                "freshness": {"status": "cached", "is_live": False, "is_stale": True},
            },
            intraday={
                "status": "ok",
                "interval": "1m",
                "last_update": "2026-07-20T13:17:00+08:00",
                "freshness_status": "current",
                "latest_point": {"time": "2026-07-20T13:17:00+08:00", "close": 2325.0},
            },
        )

        self.assertEqual(result["display_price"], 2325.0)
        self.assertEqual(result["display_price_source"], "intraday")
        self.assertEqual(result["display_price_time"], "2026-07-20T13:17:00+08:00")
        self.assertEqual(result["display_price_freshness"], "current")
        self.assertFalse(result["quote_depth_available"])

    def test_intraday_compact_freshness_reaches_live_summary(self) -> None:
        summary = _intraday_summary_from_compact(
            {
                "enabled": True,
                "series": {
                    "1m": {
                        "interval": "1m",
                        "returned_point_count": 1,
                        "to_time": "2026-07-20T13:17:00+08:00",
                        "freshness_status": "live",
                        "age_seconds": 20,
                        "market_status": "open",
                        "latest": {
                            "time": "2026-07-20T13:17:00+08:00",
                            "close": 2325.0,
                        },
                        "points": [],
                    }
                },
            }
        )

        self.assertEqual(summary["freshness_status"], "live")
        self.assertEqual(summary["age_seconds"], 20)
        self.assertEqual(summary["market_status"], "open")

    def test_negated_broker_branch_term_does_not_select_broker_branch_intent(self) -> None:
        question = "只測即時報價與分K，不刷新法人、營收、分點。"

        self.assertEqual(infer_question_intent(question), "quote")

        plan = build_query_plan(
            payload=AiAskRequest(
                question=question,
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
                allow_external_fetch=True,
            ),
            scope_type="stock",
            question_intent="quote",
            effective_mode="data_only",
        )
        self.assertEqual(plan.requested_domains, ("quote", "intraday"))
        self.assertIn("live_intraday_bars", plan.required_capabilities)
        self.assertNotIn("live_intraday_bars", plan.excluded_capabilities)
        self.assertIn("get_market_intraday_history", plan.required_readers)
        self.assertNotIn("get_market_intraday_history", plan.excluded_readers)
        self.assertIn("broker_branch", plan.excluded_domains)
        self.assertIn("fundamentals", plan.excluded_domains)
        self.assertTrue(plan.matched_negative_terms)

    def test_query_plan_keeps_strict_provider_contract(self) -> None:
        plan = build_query_plan(
            payload=AiAskRequest(
                question="2330 即時報價",
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
                market_data_params={
                    "provider": "twse_mis",
                    "strict_provider": True,
                    "refresh_domains": ["quote"],
                },
            ),
            scope_type="stock",
            question_intent="quote",
            effective_mode="data_only",
        )

        self.assertEqual(plan.requested_provider, "twse_mis")
        self.assertTrue(plan.strict_provider)
        self.assertEqual(plan.requested_domains, ("quote",))

    @staticmethod
    def _quote_reader_dependencies(*, quote_depth, intraday_history):
        return taiwan_stock.TaiwanStockDependencies(
            market_service=SimpleNamespace(
                get_latest_stock_daily_price=lambda *_args, **_kwargs: SimpleNamespace(
                    trade_date=datetime.fromisoformat("2026-07-17T00:00:00+08:00").date(),
                    close_price=2330.0,
                    open_price=2320.0,
                    high_price=2340.0,
                    low_price=2310.0,
                    price_change=10.0,
                    trade_volume=1000,
                )
            ),
            stock_service=SimpleNamespace(
                get_stock=lambda **_kwargs: SimpleNamespace(
                    stock_id="2330",
                    stock_name="TSMC",
                    market="TWSE",
                ),
                StockNotFoundError=RuntimeError,
            ),
            build_stock_technical_report=lambda **_kwargs: {},
            build_taiwan_calendar_status=lambda: {
                "market": "tw",
                "timezone": "Asia/Taipei",
                "checked_at": "2026-07-20T13:17:20+08:00",
                "date": "2026-07-20",
                "is_trading_day": True,
                "phase": "regular_live",
                "reason": "trading_day",
                "holiday_name": None,
                "previous_trading_day": "2026-07-17",
                "next_trading_day": "2026-07-21",
                "session": {"open_time": "09:00", "close_time": "13:30"},
                "release_windows": {
                    "market_daily_price": {"expected_trade_date": "2026-07-17"}
                },
            },
            build_taiwan_source_health=lambda **_kwargs: {},
            build_us_overnight_impact_report=lambda **_kwargs: {},
            get_broker_branch_trade_summary=lambda **_kwargs: {},
            get_market_intraday_history=intraday_history,
            get_taiwan_stock_quote_depth=quote_depth,
            get_taiwan_disposition_status=lambda *_args, **_kwargs: {"is_active": False},
            now=lambda: datetime.fromisoformat("2026-07-20T13:17:20+08:00"),
        )

    def test_strict_twse_provider_failure_does_not_fallback_to_yahoo(self) -> None:
        intraday_history = unittest.mock.Mock(
            side_effect=AssertionError("strict provider must not use Yahoo intraday")
        )
        dependencies = self._quote_reader_dependencies(
            quote_depth=unittest.mock.Mock(side_effect=RuntimeError("MIS unavailable")),
            intraday_history=intraday_history,
        )

        result = taiwan_stock.read_stock_quote_context(
            db=SimpleNamespace(),
            stock_id="2330",
            market_data_params={
                "requested_domains": ["quote", "intraday"],
                "external_fetch_allowed": True,
                "provider": "twse_mis",
                "strict_provider": True,
            },
            dependencies=dependencies,
        )

        contract = result["data"]["provider_contract"]
        self.assertTrue(contract["strict_provider"])
        self.assertFalse(contract["provider_fallback_used"])
        self.assertEqual(contract["provider_fallback_reason"], "strict_provider_unavailable")
        self.assertEqual(result["data"]["quote"]["status"], "unavailable")
        self.assertEqual(result["data"]["compact"]["freshness_by_domain"]["intraday"], "unavailable")
        intraday_history.assert_not_called()

    def test_non_strict_provider_fallback_is_explicit_and_domain_scoped(self) -> None:
        def intraday_history(**kwargs):
            interval = kwargs["interval"]
            return {
                "interval": interval,
                "range": "1d",
                "provider": "yahoo_finance_chart",
                "source": "yahoo_finance_chart",
                "point_count": 1,
                "refreshed_count": 1,
                "points": [
                    {
                        "time": "2026-07-20T13:17:00+08:00",
                        "open": 2324.0,
                        "high": 2326.0,
                        "low": 2324.0,
                        "close": 2325.0,
                        "volume": 1000,
                    }
                ],
            }

        dependencies = self._quote_reader_dependencies(
            quote_depth=unittest.mock.Mock(
                return_value={
                    "provider": "twse_mis",
                    "source": "twse_mis_quote_depth",
                    "last_price": 2335.0,
                    "quote_time": "2026-07-20T12:24:40+08:00",
                    "depth_available": False,
                    "freshness": {
                        "status": "cached",
                        "is_live": False,
                        "is_stale": True,
                        "source_error": "MIS unavailable",
                    },
                }
            ),
            intraday_history=unittest.mock.Mock(side_effect=intraday_history),
        )

        result = taiwan_stock.read_stock_quote_context(
            db=SimpleNamespace(),
            stock_id="2330",
            market_data_params={
                "requested_domains": ["quote", "intraday"],
                "external_fetch_allowed": True,
                "providers": ["twse_mis"],
                "strict_provider": False,
            },
            dependencies=dependencies,
        )

        contract = result["data"]["provider_contract"]
        refresh = result["data"]["refresh_summary"]
        self.assertEqual(contract["requested_provider"], "twse_mis")
        self.assertTrue(contract["provider_fallback_used"])
        self.assertEqual(contract["provider_fallback_reason"], "requested_provider_unavailable")
        self.assertEqual(refresh["attempted_domains"], ["quote", "intraday"])
        self.assertEqual(refresh["attempted_dataset_count"], 2)
        self.assertNotIn("fundamentals", refresh["attempted_domains"])
        self.assertNotIn("broker_branch", refresh["attempted_domains"])

    def test_explicit_n225_alias_resolves_to_canonical_symbol(self) -> None:
        payload = AiAskRequest(
            question="日經 225 最新狀態",
            target={"type": "jp_index", "id": "N225"},
            mode="data_only",
            allow_llm=False,
            allow_write=False,
        )

        result = _resolve_scope(None, payload)

        self.assertEqual(result.selected_scope_type, "jp_index")
        self.assertEqual(result.selected_scope_id, "^N225")

    def test_jp_holiday_latest_close_is_not_realtime_or_stale(self) -> None:
        summary = {
            "source": "yahoo_finance_chart",
            "previous_close": 49800.0,
            "session_phase": "regular",
            "points": [{"time": "2026-07-17T15:30:00+09:00", "price": 50000.0, "volume": 1}],
        }
        calendar_status = {
            "market": "jp",
            "timezone": "Asia/Tokyo",
            "checked_at": "2026-07-20T13:00:00+09:00",
            "date": "2026-07-20",
            "is_trading_day": False,
            "phase": "market_closed",
            "reason": "holiday",
            "holiday_name": "Marine Day",
            "previous_trading_day": "2026-07-17",
            "next_trading_day": "2026-07-21",
            "session": {"open_time": "09:00", "close_time": "15:30"},
        }

        quote = _jp_intraday_quote(summary, calendar_status=calendar_status)

        self.assertFalse(quote["is_realtime"])
        self.assertFalse(quote["freshness"]["is_stale"])
        self.assertEqual(quote["market_status"], "closed_holiday")
        self.assertEqual(quote["quote_semantics"], "latest_completed_session")
        self.assertEqual(quote["session_phase"], "market_closed")

    def test_kr_stale_stock_quote_is_not_current_during_session(self) -> None:
        summary = {
            "source": "yahoo_finance_chart",
            "previous_close": 85000.0,
            "session_phase": "regular",
            "points": [{"time": "2026-07-20T13:56:37+09:00", "price": 85500.0, "volume": 10}],
        }
        calendar_status = {
            "market": "kr",
            "timezone": "Asia/Seoul",
            "checked_at": "2026-07-20T14:16:00+09:00",
            "date": "2026-07-20",
            "is_trading_day": True,
            "phase": "regular",
            "reason": "trading_day",
            "holiday_name": None,
            "previous_trading_day": "2026-07-17",
            "next_trading_day": "2026-07-21",
            "session": {"open_time": "09:00", "close_time": "15:30"},
        }

        quote = _kr_intraday_quote(summary, calendar_status=calendar_status)

        self.assertFalse(quote["is_realtime"])
        self.assertTrue(quote["freshness"]["is_stale"])
        self.assertEqual(quote["freshness"]["age_seconds"], 1163)
        self.assertEqual(quote["market_status"], "open")

    def test_quote_depth_age_uses_exchange_quote_time_not_fetch_time(self) -> None:
        row = SimpleNamespace(
            quote_time=datetime.fromisoformat("2026-07-20T12:24:40+08:00"),
            fetched_at=datetime.fromisoformat("2026-07-20T13:17:01+08:00"),
            trade_date=datetime.fromisoformat("2026-07-20T00:00:00+08:00").date(),
        )

        freshness = _freshness_for_row(
            row,
            phase="regular_live",
            now=datetime.fromisoformat("2026-07-20T13:17:41+08:00"),
        )

        self.assertEqual(freshness["age_seconds"], 3181)
        self.assertEqual(freshness["fetch_age_seconds"], 40)
        self.assertEqual(freshness["status"], "stale")

    def test_quote_depth_requests_for_same_stock_are_coalesced(self) -> None:
        reset_twse_mis_quote_depth_guard()
        result = ({"c": "2330"}, "https://example.test", {"msgArray": []})

        with patch(
            "app.market.quote_depth._fetch_mis_quote_depth",
            return_value=result,
        ) as fetch:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [
                    executor.submit(
                        _guarded_mis_quote_depth_fetch,
                        stock_id="2330",
                        market="TWSE",
                    )
                    for _ in range(4)
                ]
                values = [future.result() for future in futures]

        self.assertEqual(values, [result] * 4)
        self.assertEqual(fetch.call_count, 1)

    def test_quote_depth_circuit_opens_after_three_consecutive_failures(self) -> None:
        reset_twse_mis_quote_depth_guard()

        with patch(
            "app.market.quote_depth._fetch_mis_quote_depth",
            side_effect=RuntimeError("MIS down"),
        ) as fetch:
            for _ in range(3):
                with self.assertRaisesRegex(RuntimeError, "MIS down"):
                    _guarded_mis_quote_depth_fetch(stock_id="2330", market="TWSE")
            with self.assertRaises(TaiwanStockQuoteDepthCircuitOpenError):
                _guarded_mis_quote_depth_fetch(stock_id="2330", market="TWSE")

        self.assertEqual(fetch.call_count, 3)

    def test_provider_http_diagnostics_preserve_status_type_and_content_type(self) -> None:
        response = requests.Response()
        response.status_code = 429
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["Retry-After"] = "90"

        with self.assertRaises(ProviderHttpError) as caught:
            provider_request(
                ProviderRequestContext(
                    market="tw",
                    provider="twse_mis",
                    resource="quote_depth",
                    target="2330",
                ),
                "GET",
                "https://example.test/quote",
                timeout_seconds=(2, 5),
                request_callable=lambda *_args, **_kwargs: response,
            )

        diagnostics = caught.exception.failure.diagnostic_fields()
        self.assertEqual(diagnostics["http_status_code"], 429)
        self.assertEqual(diagnostics["exception_type"], "HTTPError")
        self.assertEqual(diagnostics["response_content_type"], "text/html; charset=utf-8")
        self.assertEqual(diagnostics["retry_after_seconds"], 90)
        self.assertEqual(diagnostics["retry_count"], 0)

    def test_quote_depth_provider_context_is_not_mislabeled_as_index_snapshot(self) -> None:
        sentinel = object()
        with patch.object(twse_mis, "get", return_value=sentinel) as get:
            result = twse_mis.get_response(
                "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
                params={"ex_ch": "tse_2330.tw"},
                omi_resource="quote_depth",
                omi_target="2330",
            )

        self.assertIs(result, sentinel)
        self.assertEqual(get.call_args.kwargs["resource"], "quote_depth")
        self.assertEqual(get.call_args.kwargs["target"], "2330")
        self.assertNotIn("omi_resource", get.call_args.kwargs)

    def test_domain_passport_does_not_let_fundamentals_pollute_quote_trust(self) -> None:
        passport = _domain_passport(
            compact={
                "freshness_by_domain": {
                    "quote": "live",
                    "intraday": "waiting",
                    "fundamentals": "stale",
                }
            },
            query_plan={"requested_domains": ["quote"]},
        )

        self.assertEqual(passport["quote_trust"]["trust_level"], "high")
        self.assertEqual(passport["fundamentals_trust"]["trust_level"], "low")
        self.assertEqual(passport["decision_readiness"]["status"], "ready")

    def test_holiday_live_feed_health_is_closed_not_missing(self) -> None:
        holiday_calendar = {
            "market": "jp",
            "timezone": "Asia/Tokyo",
            "checked_at": "2026-07-20T13:00:00+09:00",
            "date": "2026-07-20",
            "is_trading_day": False,
            "phase": "market_closed",
            "reason": "holiday",
            "holiday_name": "Marine Day",
            "session": {"open_time": "09:00", "close_time": "15:30"},
        }
        envelope = {
            "as_of": "2026-07-17",
            "missing": ["jp_fundamental"],
            "evidence_passport": {"data_freshness": "stale"},
        }

        with patch(
            "app.ai.tools.build_market_calendar_status",
            return_value={"markets": {"jp": holiday_calendar}},
        ):
            dimensions = _health_dimensions(envelope, market="JP")

        self.assertEqual(dimensions["live_feed_health"]["status"], "closed_holiday")
        self.assertEqual(dimensions["database_freshness"]["status"], "stale")
        self.assertEqual(dimensions["coverage_completeness"]["status"], "partial")

    def test_disposition_contract_marks_batch_auction_and_advances_next_batch(self) -> None:
        quote = {
            "last_price": 288.0,
            "best_bid_price": 287.5,
            "best_ask_price": 289.0,
            "quote_time": "2026-07-20T09:02:00+08:00",
            "market_status": "open",
        }
        _apply_disposition_quote_contract(
            quote,
            {
                "is_active": True,
                "matching_interval_minutes": 20,
                "start_date": "2026-07-20",
                "end_date": "2026-07-31",
            },
            now=datetime.fromisoformat("2026-07-20T09:25:00+08:00"),
        )

        self.assertEqual(quote["trading_mode"], "disposition_batch_auction")
        self.assertEqual(quote["market_status"], "disposition_batch_auction")
        self.assertEqual(quote["last_trade_price"], 288.0)
        self.assertEqual(quote["indicative_bid"], 287.5)
        self.assertEqual(quote["next_batch_time"], "2026-07-20T09:42:00+08:00")

    def test_disposition_points_drop_repeated_poll_snapshots(self) -> None:
        points = [
            {"time": "2026-07-20T09:02:00+08:00", "close": 288.0, "volume": 428000},
            {"time": "2026-07-20T09:13:00+08:00", "close": 288.0, "volume": 428000},
            {"time": "2026-07-20T09:22:00+08:00", "close": 289.0, "volume": 430000},
        ]

        deduped = _dedupe_disposition_points(points)

        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[-1]["volume"], 430000)

    def test_disposition_points_keep_a_new_official_trade_timestamp(self) -> None:
        points = [
            {
                "time": "2026-07-20T09:02:00+08:00",
                "close": 288.0,
                "volume": 428000,
                "official_trade_timestamp": "2026-07-20T09:00:00+08:00",
            },
            {
                "time": "2026-07-20T09:13:00+08:00",
                "close": 288.0,
                "volume": 428000,
                "official_trade_timestamp": "2026-07-20T09:10:00+08:00",
            },
        ]

        self.assertEqual(len(_dedupe_disposition_points(points)), 2)


if __name__ == "__main__":
    unittest.main()
