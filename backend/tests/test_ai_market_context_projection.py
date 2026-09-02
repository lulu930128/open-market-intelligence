from __future__ import annotations

from datetime import datetime, timezone
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.ai import agentic_tools, realtime_contract, tools
from app.ai.market_context import common, us_context
from app.ai.market_context import taiwan_market, taiwan_projection
from app.ai.schemas import AiDataEnvelope
from app.ai.market_context.crypto_context import (
    _crypto_core_source_health_status,
    _crypto_health_status,
    _crypto_market_cap_matches_asset,
    _crypto_ohlcv_projection,
)
from app.crypto_market.assets import get_crypto_asset
from app.market.index_resolution import resolve_taiwan_index_truth


class AIMarketContextProjectionTests(unittest.TestCase):
    def test_crypto_ohlcv_projection_sorts_ascending_and_declares_units(self) -> None:
        rows = [
            SimpleNamespace(
                provider="binance",
                exchange="Binance",
                symbol="BTC-USDT",
                instrument_type="spot",
                interval="1m",
                bar_time="2026-07-28T02:13:00Z",
                open_price=101,
                high_price=102,
                low_price=100,
                close_price=101.5,
                base_volume=2.5,
                quote_volume=253.75,
                base_asset="BTC",
                quote_asset="USDT",
                fetched_at="2026-07-28T02:13:05Z",
            ),
            SimpleNamespace(
                provider="binance",
                exchange="Binance",
                symbol="BTC-USDT",
                instrument_type="spot",
                interval="1m",
                bar_time="2026-07-28T02:12:00Z",
                open_price=100,
                high_price=101,
                low_price=99,
                close_price=100.5,
                base_volume=2,
                quote_volume=201,
                base_asset="BTC",
                quote_asset="USDT",
                fetched_at="2026-07-28T02:12:05Z",
            ),
        ]

        projected = _crypto_ohlcv_projection(rows)

        self.assertEqual(
            [item["bar_time"] for item in projected],
            ["2026-07-28T02:12:00Z", "2026-07-28T02:13:00Z"],
        )
        self.assertEqual(projected[-1]["base_volume_unit"], "BTC")
        self.assertEqual(projected[-1]["quote_volume_unit"], "USDT")
        self.assertEqual(
            projected[-1]["volume_semantics"],
            "interval_base_and_quote_volume",
        )

    def test_taiwan_quote_compact_preserves_depth_contract(self) -> None:
        bid_levels = [
            {
                "level": 1,
                "price": 2325.0,
                "volume_lots": 100,
                "order_count": None,
                "order_count_status": "not_provided",
            }
        ]
        ask_levels = [
            {
                "level": 1,
                "price": 2330.0,
                "volume_lots": 80,
                "order_count": None,
                "order_count_status": "not_provided",
            }
        ]
        quote = taiwan_projection._compact_quote_snapshot(
            latest_daily=None,
            quote_depth={
                "source": "twse_mis_quote_depth",
                "provider": "twse_mis",
                "session_phase": "preopen_auction",
                "market_calendar_phase": "regular",
                "instrument_phase": "preopen_auction",
                "observation_reason_code": "PROVIDER_EVENT_PRECEDES_OPEN",
                "trade_date": "2026-07-27",
                "quote_time": "2026-07-27T11:00:00+08:00",
                "last_trade_price": 2325.0,
                "price_available": False,
                "depth_available": True,
                "bid_levels": bid_levels,
                "ask_levels": ask_levels,
                "bid_depth": bid_levels,
                "ask_depth": ask_levels,
                "best_bid_price": 2325.0,
                "best_ask_price": 2330.0,
                "top5_bid_volume_lots": 500,
                "top5_ask_volume_lots": 400,
                "top5_imbalance": 1 / 9,
                "depth_volume_unit": "lots",
                "depth_order_count_status": "not_provided",
                "data_core_components": {
                    "quote.snapshot": {
                        "lineage": {"authority": "exchange"},
                    }
                },
                "primary_provider": "twse_mis",
                "provider_attempts": [
                    {
                        "provider": "twse_mis",
                        "status": "selected",
                        "error": None,
                    }
                ],
                "acquisition_scope": {
                    "providers_attempted": ["twse_mis"],
                },
                "auction_book_available": True,
                "auction_book_status": "depth_and_indicative_match",
                "auction_indicative_available": True,
                "indicative_match_available": True,
                "indicative_match_price": 2327.5,
                "indicative_match_volume_lots": 2_046,
                "indicative_unmatched_buy_volume_lots": None,
                "indicative_unmatched_sell_volume_lots": None,
                "indicative_unmatched_status": "not_provided",
                "freshness": {
                    "status": "live",
                    "is_live": True,
                    "is_stale": False,
                },
            },
            quote_error=None,
        )

        self.assertEqual(quote["bid_levels"], bid_levels)
        self.assertEqual(quote["ask_levels"], ask_levels)
        self.assertEqual(quote["top5_bid_volume_lots"], 500)
        self.assertEqual(quote["top5_ask_volume_lots"], 400)
        self.assertAlmostEqual(quote["top5_imbalance"], 1 / 9)
        self.assertEqual(
            quote["depth_order_count_status"],
            "not_provided",
        )
        self.assertIsNone(
            quote["indicative_unmatched_buy_volume_lots"]
        )
        self.assertEqual(
            quote["indicative_unmatched_status"],
            "not_provided",
        )
        self.assertTrue(quote["indicative_match_available"])
        self.assertEqual(quote["market_calendar_phase"], "regular")
        self.assertEqual(quote["instrument_phase"], "preopen_auction")
        self.assertEqual(
            quote["components"]["auction"]["market_calendar_phase"],
            "regular",
        )
        self.assertEqual(
            quote["components"]["auction"]["instrument_phase"],
            "preopen_auction",
        )
        self.assertEqual(
            quote["components"]["auction"]["observation_reason_code"],
            "PROVIDER_EVENT_PRECEDES_OPEN",
        )
        self.assertEqual(quote["indicative_match_price"], 2327.5)
        self.assertEqual(quote["indicative_match_volume_lots"], 2_046)
        self.assertEqual(
            quote["components"]["auction"]["indicative_match_price"],
            2327.5,
        )
        self.assertEqual(
            quote["components"]["auction"]["indicative_match_volume_lots"],
            2_046,
        )
        self.assertEqual(quote["components"]["auction"]["status"], "current")
        self.assertEqual(
            quote["components"]["auction"]["applicability_status"],
            "applicable",
        )
        self.assertNotEqual(
            quote["components"]["auction"]["freshness"].get("reason_code"),
            "SESSION_NOT_AUCTION",
        )
        self.assertEqual(quote["primary_provider"], "twse_mis")
        self.assertEqual(quote["selected_provider"], "twse_mis")
        self.assertFalse(quote["fallback_used"])
        self.assertEqual(
            quote["provider_attempts"],
            [
                {
                    "provider": "twse_mis",
                    "status": "selected",
                    "error": None,
                }
            ],
        )
        self.assertEqual(quote["source_grade"], "official")

    def test_taiwan_cached_fugle_quote_ignores_bundle_level_mis_attempt(
        self,
    ) -> None:
        quote = taiwan_projection._compact_quote_snapshot(
            latest_daily=None,
            quote_depth={
                "source": "fugle_aggregates_stream",
                "provider": "fugle_marketdata",
                "freshness": {
                    "status": "live",
                    "is_live": True,
                    "is_stale": False,
                },
                "data_core_components": {
                    "quote.snapshot": {
                        "lineage": {"authority": "vendor"},
                    }
                },
                "primary_provider": "fugle_marketdata",
                "provider_attempts": [],
                "acquisition_scope": {
                    "providers_attempted": ["twse_mis"],
                },
            },
            quote_error=None,
            session_phase="regular_live",
            current_session_date="2026-07-27",
            is_trading_day=True,
        )

        self.assertEqual(quote["primary_provider"], "fugle_marketdata")
        self.assertEqual(quote["selected_provider"], "fugle_marketdata")
        self.assertEqual(quote["provider_attempts"], [])
        self.assertNotIn("twse_mis", str(quote["provider_attempts"]))
        self.assertEqual(quote["source_grade"], "third_party")

    def test_taiwan_cached_kgi_quote_does_not_fabricate_provider_attempts(self) -> None:
        quote = taiwan_projection._compact_quote_snapshot(
            latest_daily=None,
            quote_depth={
                "source": "kgi_quote_stream",
                "provider": "kgi_superpy",
                "freshness": {
                    "status": "live",
                    "is_live": True,
                    "is_stale": False,
                },
                "data_core_components": {
                    "quote.snapshot": {
                        "lineage": {"authority": "broker"},
                    }
                },
                "primary_provider": "kgi_superpy",
                "provider_attempts": [],
                "acquisition_scope": {
                    "providers_attempted": ["twse_mis"],
                },
            },
            quote_error=None,
            session_phase="regular_live",
            current_session_date="2026-07-27",
            is_trading_day=True,
        )

        self.assertEqual(quote["primary_provider"], "kgi_superpy")
        self.assertEqual(quote["provider_attempts"], [])
        self.assertEqual(quote["source_grade"], "third_party")

    def test_taiwan_quote_preserves_backend_owned_fallback_path(self) -> None:
        provider_attempts = [
            {
                "provider": "fugle_marketdata",
                "status": "attempted",
                "error": "upstream_timeout",
            },
            {
                "provider": "kgi_superpy",
                "status": "selected",
                "error": None,
            },
        ]
        quote = taiwan_projection._compact_quote_snapshot(
            latest_daily=None,
            quote_depth={
                "source": "kgi_quote_stream",
                "provider": "kgi_superpy",
                "primary_provider": "fugle_marketdata",
                "provider_attempts": provider_attempts,
                "fallback_used": True,
                "fallback_reason": "upstream_timeout",
                "freshness": {
                    "status": "live",
                    "is_live": True,
                    "is_stale": False,
                },
                "data_core_components": {
                    "quote.snapshot": {
                        "lineage": {"authority": "broker"},
                    }
                },
                "acquisition_scope": {
                    "providers_attempted": ["twse_mis"],
                },
            },
            quote_error=None,
            session_phase="regular_live",
            current_session_date="2026-07-27",
            is_trading_day=True,
        )

        self.assertEqual(quote["primary_provider"], "fugle_marketdata")
        self.assertEqual(quote["selected_provider"], "kgi_superpy")
        self.assertEqual(quote["provider_attempts"], provider_attempts)
        self.assertTrue(quote["fallback_used"])
        self.assertEqual(quote["fallback_provider"], "kgi_superpy")
        self.assertEqual(quote["fallback_reason"], "upstream_timeout")

    def test_taiwan_intraday_compact_declares_price_and_volume_units(self) -> None:
        projected = taiwan_projection._compact_intraday_history(
            {
                "provider": "twse_openapi",
                "source": "tw_stock_intraday",
                "points": [
                    {
                        "time": "2026-07-29T13:30:00+08:00",
                        "close": 1145.0,
                        "volume": 7_206_000,
                        "volume_shares": 7_206_000,
                        "volume_lots": 7_206.0,
                        "canonical_volume_unit": "shares",
                        "provider_volume_unit": "lots",
                        "trade_value_status": "estimated",
                    }
                ],
            }
        )

        self.assertEqual(projected["currency"], "TWD")
        self.assertEqual(projected["price_unit"], "TWD")
        self.assertEqual(projected["volume_unit"], "shares")
        self.assertEqual(projected["canonical_volume_unit"], "shares")
        self.assertEqual(projected["provider_volume_unit"], "lots")
        self.assertEqual(projected["trade_value_unit"], "TWD")
        self.assertEqual(projected["latest"]["price_unit"], "TWD")
        self.assertEqual(projected["latest"]["volume_unit"], "shares")
        self.assertEqual(projected["latest"]["trade_value_unit"], "TWD")

    def test_taiwan_market_breadth_combines_twse_and_tpex(self) -> None:
        summary = {
            "as_of": "2026-07-22T13:30:00+08:00",
            "indices": [
                {
                    "index_id": "TAIEX",
                    "breadth": {
                        "market": "TWSE",
                        "version": "tw.market.breadth.v2",
                        "state_contract_version": (
                            "tw.market_breadth.stock_state.v2"
                        ),
                        "market_session": "post_close",
                        "price_semantics": "official_session_close",
                        "decision_usable": True,
                        "is_provisional": False,
                        "snapshot_as_of": "2026-07-22T13:30:00+08:00",
                        "scope": "full_market",
                        "trade_date": "2026-07-22",
                        "advance_count": 530,
                        "decline_count": 464,
                        "unchanged_count": 68,
                        "total_count": 1062,
                        "limit_up_count": 30,
                        "limit_down_count": 2,
                        "trade_value": 1_025_958_396_323,
                        "source": "twse_rwd_mi_index",
                    },
                    "breadth_status": {"status": "ready"},
                },
                {
                    "index_id": "TPEX",
                    "breadth": {
                        "market": "TPEX",
                        "version": "tw.market.breadth.v2",
                        "state_contract_version": (
                            "tw.market_breadth.stock_state.v2"
                        ),
                        "market_session": "post_close",
                        "price_semantics": "official_session_close",
                        "decision_usable": True,
                        "is_provisional": False,
                        "snapshot_as_of": "2026-07-22T13:30:00+08:00",
                        "scope": "full_market",
                        "trade_date": "2026-07-22",
                        "advance_count": 535,
                        "decline_count": 257,
                        "unchanged_count": 74,
                        "total_count": 866,
                        "limit_up_count": 28,
                        "limit_down_count": 2,
                        "trade_value": 186_314_449_680,
                        "source": "tpex_openapi_mainboard_quotes",
                    },
                    "breadth_status": {"status": "ready"},
                },
            ],
        }
        refs: list[dict] = []
        breadth = taiwan_market._market_breadth_from_index_summary(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: summary
            ),
            warnings=[],
            source_refs=refs,
        )

        self.assertIsNotNone(breadth)
        self.assertEqual(breadth["status"], "ready")
        self.assertEqual(breadth["version"], "tw.market.breadth.v2")
        self.assertEqual(
            breadth["state_contract_version"],
            "tw.market_breadth.stock_state.v2",
        )
        self.assertEqual(breadth["market_session"], "post_close")
        self.assertEqual(breadth["price_semantics"], "official_session_close")
        self.assertTrue(breadth["decision_usable"])
        self.assertFalse(breadth["is_provisional"])
        self.assertEqual(breadth["included_markets"], ["TWSE", "TPEX"])
        self.assertEqual(breadth["advance_count"], 1065)
        self.assertEqual(breadth["decline_count"], 721)
        self.assertEqual(breadth["total_count"], 1928)
        self.assertEqual(breadth["trade_value"], 1_212_272_846_003)
        self.assertEqual(breadth["universe_count"], 1928)
        self.assertEqual(breadth["coverage_count"], 1928)
        self.assertEqual(breadth["coverage_ratio"], 1.0)
        self.assertEqual(breadth["classified_count"], 1928)
        self.assertEqual(breadth["unknown_count"], 0)
        self.assertEqual(breadth["reconciliation_status"], "balanced")
        self.assertTrue(breadth["trade_value_available"])
        self.assertTrue(breadth["trade_value_complete"])
        self.assertEqual(breadth["trade_value_coverage_status"], "complete")
        self.assertEqual(breadth["trade_value_authority_status"], "official")
        self.assertEqual(breadth["trade_value_status"], "official_complete")
        self.assertEqual(
            breadth["trade_value_included_markets"],
            ["TWSE", "TPEX"],
        )
        self.assertEqual(breadth["trade_value_missing_markets"], [])
        self.assertEqual(breadth["market_completion_ratio"], 1.0)
        self.assertEqual(
            breadth["close_reconciliation"]["status"],
            "confirmed",
        )
        self.assertEqual(breadth["markets"]["TWSE"]["total_count"], 1062)
        self.assertEqual(breadth["markets"]["TPEX"]["total_count"], 866)
        self.assertEqual(refs, [{"type": "derived", "name": "app.market.indices.summary"}])

    def test_taiwan_market_breadth_keeps_preopen_auction_separate(self) -> None:
        def component(index_id: str, market: str) -> dict:
            return {
                "index_id": index_id,
                "breadth": {
                    "market": market,
                    "version": "tw.market.breadth.v2",
                    "state_contract_version": (
                        "tw.market_breadth.stock_state.v2"
                    ),
                    "scope": "registered_universe",
                    "trade_date": "2026-08-04",
                    "market_session": "preopen",
                    "price_semantics": "actual_trade_only",
                    "decision_usable": False,
                    "is_provisional": True,
                    "snapshot_as_of": "2026-08-04T08:55:00+08:00",
                    "advance_count": 0,
                    "decline_count": 0,
                    "unchanged_count": 0,
                    "coverage_count": 0,
                    "unknown_count": 100,
                    "total_count": 100,
                    "auction_breadth": {
                        "market": market,
                        "status": "provisional",
                        "market_session": "preopen",
                        "as_of": "2026-08-04T08:55:00+08:00",
                        "advance_count": 20,
                        "decline_count": 10,
                        "unchanged_count": 5,
                        "coverage_count": 35,
                        "universe_count": 100,
                        "price_semantics": "auction_indicative",
                        "decision_usable": False,
                        "is_provisional": True,
                    },
                },
                "breadth_status": {
                    "status": "pending",
                    "decision_usable": False,
                },
            }

        breadth = taiwan_market._market_breadth_from_index_summary(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: {
                    "indices": [
                        component("TAIEX", "TWSE"),
                        component("TPEX", "TPEX"),
                    ]
                }
            ),
            warnings=[],
            source_refs=[],
        )

        self.assertEqual(breadth["status"], "pending")
        self.assertFalse(breadth["decision_usable"])
        self.assertEqual(breadth["advance_count"], 0)
        self.assertEqual(breadth["decline_count"], 0)
        auction = breadth["auction_breadth"]
        self.assertEqual(auction["status"], "provisional")
        self.assertEqual(auction["advance_count"], 40)
        self.assertEqual(auction["decline_count"], 20)
        self.assertEqual(auction["coverage_count"], 70)
        self.assertFalse(auction["decision_usable"])

    def test_taiwan_market_indices_use_latest_available_trade_date(self) -> None:
        summary = {
            "source": "market_index_summary",
            "indices": [
                {
                    "index_id": "TAIEX",
                    "market": "TWSE",
                    "close": 24123.45,
                    "change": 123.45,
                    "trade_date": "2026-07-28",
                },
                {
                    "index_id": "TPEX",
                    "market": "TPEX",
                    "close": 267.89,
                    "change": -0.11,
                    "trade_date": "2026-07-29",
                },
            ],
        }

        result = taiwan_market._market_indices_capability(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: summary
            ),
            generated_at=datetime.fromisoformat("2026-07-29T14:00:00+08:00"),
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["as_of"], "2026-07-29")
        self.assertTrue(result["is_complete"])
        self.assertTrue(result["mixed_trade_dates"])
        self.assertFalse(result["current_for_requested_session"])
        self.assertEqual(
            [item["index_id"] for item in result["items"]],
            ["TAIEX", "TPEX"],
        )

    def test_taiwan_market_indices_select_current_snapshot_without_losing_close(self) -> None:
        def current(index_id: str, value: float, previous_close: float) -> dict:
            return {
                "status": "selected",
                "index_id": index_id,
                "provider": "twse_mis",
                "source": "twse_mis_index_snapshot",
                "close": value,
                "change": value - previous_close,
                "previous_close": previous_close,
                "as_of": "2026-07-29T10:00:00+08:00",
                "trade_date": "2026-07-29",
                "session": "continuous",
                "provisional": True,
                "official": False,
                "decision_usable": True,
                "resolved_health": {
                    "contract_version": "omi.market.resolved_evidence_health.v1",
                    "status": "selected",
                    "selection_reason": "canonical_current_index",
                    "research_usable": True,
                },
            }

        summary = {
            "source": "market_index_summary",
            "indices": [
                {
                    "index_id": "TAIEX",
                    "market": "TWSE",
                    "close": 24_000.0,
                    "trade_date": "2026-07-28",
                    "current_data_core": {
                        "index": current("TAIEX", 24_100.0, 24_000.0)
                    },
                },
                {
                    "index_id": "TPEX",
                    "market": "TPEX",
                    "close": 267.0,
                    "trade_date": "2026-07-28",
                    "current_data_core": {
                        "index": current("TPEX", 268.0, 267.0)
                    },
                },
            ],
        }
        result = taiwan_market._market_indices_capability(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: summary
            ),
            generated_at=datetime.fromisoformat(
                "2026-07-29T10:01:00+08:00"
            ),
        )

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["current_for_requested_session"])
        self.assertTrue(result["is_complete"])
        self.assertEqual(result["observation_mix"], ["compatibility_current_data_core"])
        self.assertEqual(result["items"][0]["latest_value"], 24_100.0)
        self.assertEqual(result["items"][0]["close"], 24_100.0)
        self.assertEqual(result["items"][0]["official_close"]["value"], 24_000.0)
        self.assertTrue(result["items"][0]["live_snapshot"]["is_partial"])
        self.assertTrue(result["items"][0]["compatibility_fallback"])
        self.assertIn(
            "INDEX_HEADLINE_COMPATIBILITY_FALLBACK",
            result["items"][0]["limitations"],
        )
        self.assertEqual(
            result["items"][0]["resolution_version"],
            "compatibility.current_data_core.v1",
        )

    def test_taiwan_market_indices_keep_unconfirmed_post_close_summary_provisional(
        self,
    ) -> None:
        summary = {
            "source": "market_index_summary",
            "indices": [
                {
                    "index_id": "TAIEX",
                    "market": "TWSE",
                    "close": 43_360.66,
                    "as_of": "2026-08-04T13:30:00+08:00",
                },
                {
                    "index_id": "TPEX",
                    "market": "TPEX",
                    "close": 375.03,
                    "as_of": "2026-08-04T13:30:00+08:00",
                },
            ],
        }

        result = taiwan_market._market_indices_capability(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: summary
            ),
            generated_at=datetime.fromisoformat("2026-08-04T19:50:00+08:00"),
        )

        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["current_for_requested_session"])
        self.assertFalse(result["decision_usable"])
        self.assertEqual(result["oldest_as_of"], "2026-08-04T13:30:00+08:00")
        self.assertEqual(result["newest_as_of"], "2026-08-04T13:30:00+08:00")
        self.assertEqual(result["items"][0]["trade_date"], "2026-08-04")
        self.assertEqual(
            result["items"][0]["official_close"]["as_of"],
            "2026-08-04T13:30:00+08:00",
        )
        self.assertEqual(
            result["items"][0]["official_close_status"],
            "not_available_yet",
        )
        self.assertEqual(result["items"][0]["finalization"], "unknown")
        self.assertFalse(result["items"][0]["provisional"])
        self.assertFalse(result["items"][0]["decision_usable"])
        self.assertTrue(result["items"][0]["compatibility_fallback"])

    def test_taiwan_market_indices_prefer_embedded_truth_over_current_core(self) -> None:
        calendar_status = {
            "timezone": "Asia/Taipei",
            "checked_at": "2026-09-02T15:20:00+08:00",
            "date": "2026-09-02",
            "is_trading_day": True,
            "phase": "post_close",
            "previous_trading_day": "2026-09-01",
        }

        def item(
            index_id: str,
            market: str,
            completed_close: float,
            previous_close: float,
            current_close: float,
        ) -> dict:
            source = (
                "twse_indices_report_mi_5mins_hist"
                if index_id == "TAIEX"
                else "tpex_openapi_daily_index"
            )
            provider = "twse" if index_id == "TAIEX" else "tpex"
            snapshot = {
                "index_id": index_id,
                "close": current_close,
                "previous_close": previous_close,
                "time": "2026-09-02",
                "as_of": "2026-09-02T13:30:00+08:00",
                "source": "fugle_indices_stream",
                "provider": "fugle_marketdata",
                "completed_daily_close": completed_close,
                "completed_daily_trade_date": "2026-09-02",
                "completed_daily_event_time": "2026-09-02T13:30:00+08:00",
                "completed_daily_source": source,
                "completed_daily_provider": provider,
                "completed_daily_authority": "exchange",
                "completed_daily_finalization": "final",
                "completed_daily_official": True,
                "completed_daily_release_status": "released",
                "completed_daily_reconciliation_status": "not_applicable",
                "completed_daily_qualified": True,
                "completed_daily_previous_close": previous_close,
                "completed_daily_previous_close_trade_date": "2026-09-01",
                "completed_daily_previous_close_source": source,
                "completed_daily_previous_close_provider": provider,
                "completed_daily_previous_close_authority": "exchange",
                "completed_daily_previous_close_finalization": "final",
            }
            truth = resolve_taiwan_index_truth(
                intraday=None,
                index_snapshot=snapshot,
                calendar_status=calendar_status,
                index_id=index_id,
                acquisition_policy="cache_only",
            )
            return {
                **snapshot,
                "market": market,
                "resolution": truth.model_dump(mode="json"),
                "current_data_core": {
                    "index": {
                        "status": "stale",
                        "index_id": index_id,
                        "provider": "fugle_marketdata",
                        "source": "fugle_indices_stream",
                        "close": current_close,
                        "previous_close": previous_close,
                        "change": current_close - previous_close,
                        "as_of": "2026-09-02T13:30:00+08:00",
                        "trade_date": "2026-09-02",
                        "provisional": True,
                        "official": False,
                        "decision_usable": False,
                    }
                },
            }

        summary = {
            "source": "shared_market_data_core",
            "indices": [
                item("TAIEX", "TWSE", 46_164.72, 46_948.72, 46_221.63),
                item("TPEX", "TPEX", 406.96, 410.77, 406.88),
            ],
        }
        result = taiwan_market._market_indices_capability(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: summary
            ),
            generated_at=datetime.fromisoformat("2026-09-02T15:20:00+08:00"),
        )

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["decision_usable"])
        taiex, tpex = result["items"]
        self.assertEqual(taiex["value"], 46_164.72)
        self.assertEqual(taiex["change"], -784.0)
        self.assertEqual(taiex["provider"], "twse")
        self.assertEqual(
            taiex["source"], "twse_indices_report_mi_5mins_hist"
        )
        self.assertEqual(
            taiex["resolution_id"],
            summary["indices"][0]["resolution"]["resolution_id"],
        )
        self.assertEqual(tpex["value"], 406.96)
        self.assertAlmostEqual(tpex["change"], -3.81)
        self.assertEqual(tpex["provider"], "tpex")
        self.assertFalse(taiex["compatibility_fallback"])
        self.assertIsNotNone(taiex["current_observation"])

    def test_aggregate_freshness_separates_temporal_currentness_from_coverage(self) -> None:
        freshness = taiwan_market._aggregate_freshness(
            "market.indices",
            {
                "status": "partial",
                "market_session": "regular",
                "current_for_requested_session": True,
                "is_complete": False,
                "as_of": "2026-07-29T10:00:00+08:00",
            },
            dataset="market_index_summary",
        )

        self.assertTrue(freshness["is_current"])
        self.assertTrue(freshness["current_for_requested_session"])
        self.assertFalse(freshness["is_complete"])
        self.assertFalse(freshness["refresh_recommended"])

    def test_taiwan_market_breadth_keeps_partial_trade_value_visible(self) -> None:
        summary = {
            "as_of": "2026-07-22T13:30:00+08:00",
            "indices": [
                {
                    "index_id": "TAIEX",
                    "breadth": {
                        "market": "TWSE",
                        "scope": "full_market",
                        "trade_date": "2026-07-22",
                        "advance_count": 5,
                        "decline_count": 4,
                        "unchanged_count": 1,
                        "total_count": 10,
                        "trade_value": 1_000,
                        "source": "twse_official",
                    },
                    "breadth_status": {"status": "ready"},
                }
            ],
        }
        breadth = taiwan_market._market_breadth_from_index_summary(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: summary
            ),
            warnings=[],
            source_refs=[],
        )

        self.assertEqual(breadth["status"], "partial")
        self.assertEqual(breadth["included_markets"], ["TWSE"])
        self.assertEqual(breadth["missing_markets"], ["TPEX"])
        self.assertTrue(breadth["trade_value_available"])
        self.assertFalse(breadth["trade_value_complete"])
        self.assertEqual(breadth["trade_value_status"], "partial")
        self.assertEqual(breadth["trade_value"], 1_000)
        self.assertEqual(breadth["trade_value_missing_markets"], ["TPEX"])
        self.assertEqual(breadth["market_completion_ratio"], 0.5)

    def test_taiwan_market_breadth_bounds_mismatched_coverage_ratio(self) -> None:
        warnings: list[str] = []
        breadth = taiwan_market._market_breadth_from_index_summary(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: {
                    "as_of": "2026-07-22T13:30:00+08:00",
                    "indices": [
                        {
                            "index_id": "TAIEX",
                            "breadth": {
                                "market": "TWSE",
                                "scope": "registered_universe",
                                "trade_date": "2026-07-22",
                                "advance_count": 6,
                                "decline_count": 4,
                                "unchanged_count": 1,
                                "total_count": 11,
                                "universe_count": 10,
                                "source": "mixed_snapshot",
                            },
                            "breadth_status": {"status": "ready"},
                        }
                    ],
                }
            ),
            warnings=warnings,
            source_refs=[],
        )

        self.assertEqual(breadth["coverage_ratio"], 1.0)
        self.assertEqual(breadth["coverage_ratio_raw"], 1.1)
        self.assertTrue(breadth["coverage_overflow"])
        self.assertEqual(
            breadth["coverage_issue"],
            "coverage_count_exceeds_universe",
        )
        self.assertEqual(breadth["status"], "partial")
        self.assertEqual(
            breadth["markets"]["TWSE"]["reconciliation_status"],
            "inconsistent",
        )
        self.assertTrue(any("bounded to 1.0" in warning for warning in warnings))

    def test_taiwan_market_breadth_preserves_universe_and_quote_coverage(self) -> None:
        breadth = taiwan_market._market_breadth_from_index_summary(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: {
                    "as_of": "2026-07-31T10:00:00+08:00",
                    "indices": [
                        {
                            "index_id": "TPEX",
                            "breadth": {
                                "market": "TPEX",
                                "scope": "registered_universe",
                                "trade_date": "2026-07-31",
                                "advance_count": 40,
                                "decline_count": 45,
                                "unchanged_count": 5,
                                "total_count": 100,
                                "universe_count": 100,
                                "coverage_count": 90,
                                "unknown_count": 10,
                                "source": "tpex_registered_universe_quotes",
                            },
                            "breadth_status": {"status": "partial"},
                        }
                    ],
                }
            ),
            warnings=[],
            source_refs=[],
        )

        component = breadth["markets"]["TPEX"]
        self.assertEqual(component["total_count"], 100)
        self.assertEqual(component["universe_count"], 100)
        self.assertEqual(component["coverage_count"], 90)
        self.assertEqual(component["classified_count"], 90)
        self.assertEqual(component["unknown_count"], 10)
        self.assertEqual(component["coverage_ratio"], 0.9)
        self.assertEqual(component["reconciliation_status"], "balanced")
        self.assertEqual(breadth["universe_count"], 100)
        self.assertEqual(breadth["coverage_count"], 90)
        self.assertEqual(breadth["classified_count"], 90)
        self.assertEqual(breadth["unknown_count"], 10)

    def test_market_index_intraday_pack_aggregates_live_child_metadata(self) -> None:
        child_quotes = [
            {
                "latest_price": 24_100.0,
                "quote_time": "2026-07-31T09:00:40+08:00",
                "market_status": "open",
                "current_session_phase": "regular",
                "is_live": True,
                "is_realtime": True,
                "is_latest_session_quote": True,
                "last_trade_is_current_session": True,
                "freshness": {"status": "live", "is_live": True},
            },
            {
                "latest_price": 345.6,
                "quote_time": "2026-07-31T09:00:50+08:00",
                "market_status": "open",
                "current_session_phase": "regular",
                "is_live": True,
                "is_realtime": True,
                "is_latest_session_quote": True,
                "last_trade_is_current_session": True,
                "freshness": {"status": "live", "is_live": True},
            },
        ]
        with patch.object(
            taiwan_market,
            "_compact_index_quote",
            side_effect=child_quotes,
        ), patch.object(
            taiwan_market,
            "_compact_single_intraday_series",
            return_value={
                "series": {"1m": {"returned_point_count": 1}}
            },
        ), patch.object(
            taiwan_market,
            "project_taiwan_bar_series",
            return_value={"points": [{"price": 1.0}]},
        ):
            pack = taiwan_market._market_index_intraday_pack(
                db=None,
                dependencies=SimpleNamespace(
                    read_taiwan_bars=lambda **_kwargs: object()
                ),
                include_intraday=True,
                market_data_params={"index_ids": ["TAIEX", "TPEX"]},
                missing=[],
                warnings=[],
                source_refs=[],
            )

        self.assertEqual(pack["coverage_status"], "ready")
        self.assertEqual(pack["live_index_count"], 2)
        self.assertTrue(pack["is_live"])
        self.assertTrue(pack["is_current_session"])
        self.assertEqual(pack["market_status"], "open")
        self.assertEqual(pack["current_session_phase"], "regular")
        self.assertEqual(pack["event_time"], "2026-07-31T09:00:50+08:00")
        classified = realtime_contract.classify_observation(
            pack,
            market="TW",
            realtime_policy="require_live",
            now=datetime(2026, 7, 31, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(classified["state"], "live")
        self.assertTrue(classified["policy_satisfied"])

    def test_sample_derived_market_slots_are_partial_when_coverage_is_partial(self) -> None:
        slots = taiwan_projection._build_tw_market_slots(
            as_of="2026-07-22",
            payload_level="compact",
            breadth={"status": "ready", "total_count": 1928},
            sample_coverage={
                "status": "partial",
                "sample_count": 84,
                "universe_count": 1973,
                "coverage_ratio": 84 / 1973,
            },
            distribution={"mild_up_count": 75},
            industry_rows=[{"industry": "Semiconductor"}],
            index_intraday={"enabled": False},
            cross_market={"status": "ready"},
            market_chips={"status": "ready"},
            volume_state={"status": "partial", "warnings": ["history accumulating"]},
            missing=["market_daily_price.full_market_coverage"],
            warnings=["sample coverage is partial"],
        )

        self.assertEqual(slots["market_breadth"]["status"], "ready")
        self.assertEqual(slots["distribution"]["status"], "partial")
        self.assertEqual(slots["sector_industry"]["status"], "partial")

    def test_ai_data_envelope_preserves_top_level_freshness(self) -> None:
        envelope = AiDataEnvelope.model_validate(
            {
                "kind": "market_overview",
                "generated_at": "2026-07-22T13:30:00+08:00",
                "freshness": {"is_current": False, "missing": ["sample_coverage"]},
            }
        )

        self.assertEqual(
            envelope.model_dump(mode="json")["freshness"],
            {"is_current": False, "missing": ["sample_coverage"]},
        )

    def test_evidence_passport_projection_keeps_same_top_level_freshness(self) -> None:
        freshness = {
            "is_current": False,
            "missing": ["market_breadth.tpex"],
            "warnings": ["TPEX breadth is unavailable."],
        }

        envelope = taiwan_projection._with_evidence_passport(
            {
                "kind": "market_overview",
                "as_of": "2026-07-22",
                "missing": ["market_breadth.tpex"],
                "warnings": ["TPEX breadth is unavailable."],
                "source_refs": [],
                "data": {},
            },
            freshness=freshness,
        )

        self.assertEqual(envelope["freshness"], freshness)
        self.assertEqual(envelope["evidence_passport"]["data_freshness"], "stale")

    def test_us_intraday_quote_is_not_live_when_market_is_closed(self) -> None:
        quote = us_context._us_intraday_quote(
            {
                "source": "yahoo_finance_chart",
                "session_phase": "regular",
                "previous_close": 100.0,
                "latest_point": {
                    "time": "2026-07-17T16:00:00-04:00",
                    "session": "regular",
                    "price": 101.0,
                    "volume": 10,
                },
            },
            calendar_status={
                "checked_at": "2026-07-18T12:00:00-04:00",
                "date": "2026-07-18",
                "is_trading_day": False,
                "phase": "closed",
                "previous_trading_day": "2026-07-17",
            },
        )

        self.assertFalse(quote["is_realtime"])
        self.assertFalse(quote["is_live"])
        self.assertTrue(quote["is_latest_session_quote"])
        self.assertEqual(quote["market_status"], "closed")
        self.assertEqual(quote["last_quote_session"], "regular")
        self.assertEqual(quote["volume_unit"], "shares")
        self.assertEqual(quote["volume_semantics"], "interval_shares")

    def test_us_resolved_quote_preserves_provider_and_delayed_truth(self) -> None:
        quote = us_context._us_resolved_quote(
            {
                "facts_usable": True,
                "selected_provider": "yahoo_chart",
                "selected_source": "yahoo.chart.quote",
                "selected_session": "continuous",
                "limitations": ["DELAYED_VENDOR_EVIDENCE"],
                "market_phase": "regular",
                "source_status": {
                    "status": "degraded",
                    "freshness_status": "delayed",
                    "provider_snapshot_freshness": "fresh",
                    "trade_recency": "current",
                    "trade_state": "trade_observed",
                    "current_session_expected": True,
                    "current_session_satisfied": True,
                    "expected_trade_date": "2026-07-17",
                    "event_trade_date": "2026-07-17",
                    "decision_usable": True,
                    "lag_seconds": 60,
                },
                "session_date_relation": {
                    "kind": "session_date_relation",
                    "version": "omi.us.session_date_relation.v1",
                    "relation": "current_session_daily_pending_release",
                    "status": "aligned",
                    "expected": True,
                    "quote_date": "2026-07-17",
                    "completed_daily_date": "2026-07-16",
                    "current_session_date": "2026-07-17",
                    "market_phase": "regular",
                },
                "quote": {
                    "trade_date": "2026-07-17",
                    "currency": "USD",
                    "last_trade_price": "101.25",
                    "previous_close": "100.00",
                    "event_at": "2026-07-17T10:00:00-04:00",
                },
            },
            calendar_status={
                "checked_at": "2026-07-17T10:01:00-04:00",
                "phase": "regular",
                "previous_trading_day": "2026-07-17",
            },
            previous_close_reference={
                "previous_close": 99.5,
                "change_reference_price": 100.0,
                "change_reference_type": "prior_regular_close",
                "change_reference_trade_date": "2026-07-16",
                "previous_close_source": "yahoo.chart.1d",
                "previous_close_trade_date": "2026-07-16",
                "previous_close_provider": "yahoo_chart",
            },
        )

        self.assertEqual(quote["price"], 101.25)
        self.assertEqual(quote["provider"], "yahoo_chart")
        self.assertEqual(quote["source"], "yahoo.chart.quote")
        self.assertFalse(quote["is_live"])
        self.assertFalse(quote["is_realtime"])
        self.assertEqual(quote["volume_status"], "not_provided")
        self.assertEqual(quote["previous_close"], 99.5)
        self.assertEqual(quote["previous_close_source"], "yahoo.chart.1d")
        self.assertEqual(quote["previous_close_trade_date"], "2026-07-16")
        self.assertEqual(quote["change"], 1.25)
        self.assertEqual(quote["change_reference_price"], 100.0)
        self.assertEqual(quote["change_reference_type"], "prior_regular_close")
        self.assertEqual(quote["source_status"]["freshness_status"], "delayed")
        self.assertTrue(quote["current_session_satisfied"])
        self.assertEqual(
            quote["session_date_relation"]["status"],
            "aligned",
        )
        self.assertIn("DELAYED_VENDOR_EVIDENCE", quote["limitations"])

    def test_us_intraday_quote_uses_resolved_source_status_provider(self) -> None:
        quote = us_context._us_intraday_quote(
            {
                "source": "twelve_data.time_series",
                "source_status": {"provider": "quote-provider-must-not-leak"},
                "bar_source_status": {"provider": "twelve_data"},
                "previous_close": 100.0,
                "latest_point": {
                    "time": "2026-07-17T10:00:00-04:00",
                    "session": "regular",
                    "price": 101.0,
                    "volume": 10,
                },
            },
            calendar_status={
                "checked_at": "2026-07-17T10:01:00-04:00",
                "phase": "regular",
                "previous_trading_day": "2026-07-17",
            },
        )

        self.assertEqual(quote["provider"], "twelve_data")

    def test_us_intraday_compact_declares_share_volume_unit(self) -> None:
        compact = us_context._us_intraday_compact(
            {
                "source": "yahoo_finance_chart",
                "point_count": 2,
                "points": [
                    {
                        "time": "2026-07-24T09:30:00-04:00",
                        "price": 210.0,
                        "volume": 100,
                    },
                    {
                        "time": "2026-07-24T09:31:00-04:00",
                        "price": 210.5,
                        "volume": 120,
                    },
                ],
            },
            market_data_params={"intraday_limit": 2},
        )

        series = compact["series"]["1m"]
        self.assertEqual(series["volume_unit"], "shares")
        self.assertEqual(series["volume_semantics"], "interval_shares")

    def test_ai_tool_modules_keep_common_projection_facades(self) -> None:
        self.assertIs(agentic_tools._compact_market_context, common.compact_market_context)
        self.assertIs(agentic_tools._append_source_ref_once, common.append_source_ref_once)
        self.assertIs(tools._append_source_ref_once, common.append_source_ref_once)

    def test_compact_stock_context_exposes_missing_and_not_requested_slots(self) -> None:
        compact = common.compact_market_context(
            kind="us_stock_compact_evidence",
            target={"type": "us_stock", "symbol": "AAPL"},
            quote={},
            resources={"include_intraday": False, "daily_rows": 0},
            freshness={"price": {"status": "missing"}},
        )

        self.assertEqual(compact["version"], "market_compact_evidence.v1")
        self.assertEqual(compact["slots"]["identity"]["status"], "ready")
        self.assertEqual(compact["slots"]["quote"]["status"], "missing")
        self.assertEqual(compact["slots"]["intraday"]["status"], "not_requested")
        self.assertEqual(compact["slots"]["fundamentals"]["status"], "missing")
        self.assertEqual(compact["slots"]["data_quality"]["status"], "partial")

    def test_compact_crypto_context_requires_derivatives_when_missing(self) -> None:
        slots = common.compact_market_slots(
            target={"type": "crypto_asset", "asset": "BTC"},
            quote={"last_price": 100},
            resources={"ohlcv_rows": 2, "derivatives_rows": 0},
            freshness={"quote": {"status": "current"}},
            payload_level="compact",
        )

        self.assertEqual(slots["quote"]["status"], "ready")
        self.assertEqual(slots["daily_chart"]["status"], "ready")
        self.assertEqual(slots["derivatives"]["status"], "missing")

    def test_stale_or_failed_freshness_never_produces_ready_slots(self) -> None:
        stale_slots = common.compact_market_slots(
            target={"type": "crypto_asset", "asset": "BTC"},
            quote={"last_price": 100},
            resources={"ohlcv_rows": 2},
            freshness={"quote": "stale", "ohlcv": {"status": "delayed"}},
            payload_level="compact",
        )
        failed_slots = common.compact_market_slots(
            target={"type": "us_stock", "symbol": "TSM"},
            quote={"price": 100},
            resources={"daily_rows": 2},
            freshness={
                "price": {"status": "current"},
                "source_health": {"provider_error": "upstream timeout"},
            },
            payload_level="compact",
        )

        self.assertEqual(stale_slots["quote"]["status"], "stale")
        self.assertEqual(stale_slots["daily_chart"]["status"], "stale")
        self.assertEqual(stale_slots["data_quality"]["status"], "stale")
        self.assertEqual(failed_slots["quote"]["status"], "ready")
        self.assertEqual(failed_slots["data_quality"]["status"], "failed")
        self.assertIn("data_quality_and_freshness", failed_slots["data_quality"]["missing"])

    def test_empty_and_summary_health_counts_are_consumer_visible_problems(self) -> None:
        self.assertEqual(common.freshness_problem_status("empty"), "missing")
        self.assertEqual(
            common.freshness_problem_status({"summary": {"healthy": 2, "stale": 3, "empty": 1}}),
            "stale",
        )
        self.assertEqual(
            common.freshness_problem_status({"status": "blocked", "missing": ["api_key"]}),
            "blocked",
        )

    def test_crypto_health_uses_resource_status_not_row_existence(self) -> None:
        source_health = {
            "entries": [
                {
                    "resource": "crypto_ticker",
                    "status": "stale",
                    "ok": False,
                    "required": True,
                },
                {
                    "resource": "crypto_realtime_liquidation_event",
                    "status": "empty",
                    "ok": False,
                    "required": True,
                },
            ]
        }

        self.assertEqual(
            _crypto_health_status(
                source_health,
                resources={"crypto_ticker"},
                available=True,
            ),
            "stale",
        )
        self.assertEqual(_crypto_core_source_health_status(source_health), "stale")

    def test_optional_event_empty_does_not_make_crypto_core_unhealthy(self) -> None:
        source_health = {
            "entries": [
                {
                    "resource": "crypto_ticker",
                    "status": "live",
                    "ok": True,
                    "required": True,
                },
                {
                    "resource": "crypto_realtime_liquidation_event",
                    "status": "empty",
                    "ok": False,
                    "required": True,
                },
            ]
        }

        self.assertEqual(_crypto_core_source_health_status(source_health), "current")

    def test_source_refs_are_deduplicated_by_name_or_kind(self) -> None:
        refs: list[dict] = []
        common.append_source_ref_once(refs, {"type": "table", "name": "daily_price"})
        common.append_source_ref_once(refs, {"type": "table", "name": "daily_price"})
        common.append_source_ref_once(refs, {"type": "derived", "kind": "freshness"})

        self.assertEqual(len(refs), 2)

    def test_stock_capability_freshness_isolated_per_chip_dataset(self) -> None:
        source_health = {
            "entries": [
                {
                    "resource": "institutional_trade_daily",
                    "status": "current",
                    "ok": True,
                    "latest_data_date": "2026-07-24",
                    "expected_data_date": "2026-07-24",
                },
                {
                    "resource": "margin_trading_daily",
                    "status": "current",
                    "ok": True,
                    "latest_data_date": "2026-07-24",
                    "expected_data_date": "2026-07-24",
                },
                {
                    "resource": "shareholding_distribution_weekly",
                    "status": "stale",
                    "ok": False,
                    "latest_data_date": "2026-07-17",
                    "expected_data_date": "2026-07-24",
                },
            ]
        }

        freshness = taiwan_projection._build_freshness_by_capability(
            quote={},
            intraday_bars={"enabled": False},
            source_health=source_health,
            overnight_impact=None,
            missing=[],
        )

        self.assertEqual(freshness["chips.institutional"]["status"], "current")
        self.assertFalse(
            freshness["chips.institutional"]["refresh_recommended"]
        )
        self.assertEqual(freshness["chips.margin"]["status"], "current")
        self.assertFalse(freshness["chips.margin"]["refresh_recommended"])
        self.assertEqual(
            freshness["ownership.distribution"]["status"],
            "stale",
        )
        self.assertTrue(
            freshness["ownership.distribution"]["refresh_recommended"]
        )

    def test_canonical_daily_health_precedes_absent_source_health_row(self) -> None:
        canonical_evidence = SimpleNamespace(
            dataset_health=SimpleNamespace(
                dataset_id="tw.daily.ohlcv",
                status="healthy",
                latest_date="2026-08-28",
                expected_date="2026-08-28",
                refreshable=True,
                detail_code=None,
            ),
            resolved_health=SimpleNamespace(
                status="selected",
                selected_provider="twse_openapi",
                selected_source="twse_daily_trading",
            ),
        )

        freshness = taiwan_projection._build_freshness_by_capability(
            quote={},
            intraday_bars={"enabled": False},
            source_health={"entries": []},
            overnight_impact=None,
            missing=[],
            canonical_daily_evidence=canonical_evidence,
        )

        self.assertEqual(freshness["daily.ohlcv"]["status"], "current")
        self.assertTrue(freshness["technical.structure"]["is_current"])
        self.assertEqual(
            freshness["daily.ohlcv"]["canonical_status_ref"],
            "dataset_health",
        )
        self.assertEqual(
            freshness["daily.ohlcv"]["provider_diagnostic"]["status"],
            "unknown",
        )

    def test_canonical_missing_daily_health_is_not_masked_by_provider_row(self) -> None:
        canonical_evidence = SimpleNamespace(
            dataset_health=SimpleNamespace(
                dataset_id="tw.daily.ohlcv",
                status="missing",
                latest_date=None,
                expected_date="2026-08-28",
                refreshable=True,
                detail_code="DATASET_DATE_MISSING",
            ),
            resolved_health=SimpleNamespace(status="missing"),
        )

        freshness = taiwan_projection._build_freshness_by_capability(
            quote={},
            intraday_bars={"enabled": False},
            source_health={
                "entries": [
                    {
                        "resource": "market_daily_price",
                        "status": "current",
                        "ok": True,
                    }
                ]
            },
            overnight_impact=None,
            missing=[],
            canonical_daily_evidence=canonical_evidence,
        )

        self.assertEqual(freshness["daily.ohlcv"]["status"], "missing")
        self.assertTrue(freshness["daily.ohlcv"]["refresh_recommended"])
        self.assertEqual(
            freshness["daily.ohlcv"]["provider_diagnostic"]["status"],
            "current",
        )

    def test_missing_shareholding_remains_refreshable_during_release_window(
        self,
    ) -> None:
        freshness = taiwan_projection._freshness_for_resource(
            source_health={
                "entries": [
                    {
                        "resource": "shareholding_distribution_weekly",
                        "status": "empty",
                        "ok": False,
                        "row_count": 0,
                        "release_status": "pending",
                        "refresh_eligible": True,
                        "expected_data_date": "2026-07-17",
                    }
                ]
            },
            resource="shareholding_distribution_weekly",
            missing=["shareholding_distribution_weekly"],
        )

        self.assertEqual(freshness["status"], "empty")
        self.assertEqual(freshness["release_status"], "pending")
        self.assertFalse(freshness["is_current"])
        self.assertTrue(freshness["refresh_recommended"])

    def test_crypto_market_cap_identity_prefers_registry_coin_id(self) -> None:
        ton = get_crypto_asset("TON")

        self.assertIsNotNone(ton)
        self.assertTrue(
            _crypto_market_cap_matches_asset(
                SimpleNamespace(coin_id="the-open-network", symbol="gram"),
                ton,
            )
        )
        self.assertFalse(
            _crypto_market_cap_matches_asset(
                SimpleNamespace(coin_id="bitcoin", symbol="btc"),
                ton,
            )
        )

    def test_taiwan_technical_scores_declare_raw_and_composite_scales(
        self,
    ) -> None:
        technical = taiwan_projection._compact_technical_evidence(
            analysis={
                "selected_score": -4.2,
                "decision_usable": True,
                "score_model": {
                    "version": "technical_factor_weight_v1",
                    "score_range": "-7..+7",
                },
                "components": [
                    {
                        "timeframe": "daily",
                        "weight": 0.45,
                        "included": True,
                    }
                ],
            },
            technical_levels={},
            technical_reports={
                "daily": {
                    "kind": "tw_stock_technical_report",
                    "timeframe": "daily",
                    "score": -11,
                    "data": {},
                }
            },
        )

        composite = technical["score_contracts"][
            "selected_composite"
        ]
        daily = technical["reports"]["daily"]["score_contract"]
        self.assertEqual(
            (composite["score_min"], composite["score_max"]),
            (-7, 7),
        )
        self.assertEqual(
            composite["score_scale_id"],
            "technical_factor_composite_v1",
        )
        self.assertEqual(
            (daily["score_min"], daily["score_max"]),
            (-16, 16),
        )
        self.assertEqual(
            daily["score_scale_id"],
            "tw_technical_daily_raw_v1",
        )
        self.assertEqual(daily["weight_in_composite"], 0.45)

    def test_insufficient_technical_projection_removes_direction_and_action_levels(
        self,
    ) -> None:
        technical = taiwan_projection._compact_technical_evidence(
            analysis={
                "status": "partial",
                "decision_usable": False,
                "selected_score": None,
                "raw_selected_score": 7,
                "selected_title": "技術證據不足",
                "selected_summary": "日線歷史不足，無法形成正式技術方向。",
                "composite_state": "insufficient_evidence",
                "scores": {"swing": None},
                "sufficiency": {
                    "reason_codes": ["INSUFFICIENT_DAILY_BARS"],
                },
                "score_model": {"score_range": "-7..+7"},
            },
            technical_levels={
                "latest_price": 621,
                "entry": {"preferred": 610},
                "risk": {"short_term_stop": 598},
            },
            technical_reports={
                "daily": {
                    "kind": "tw_stock_technical_report",
                    "timeframe": "daily",
                    "title": "波段偏多",
                    "summary": "強勢向上",
                    "score": 11,
                    "confidence": "high",
                    "data": {
                        "decision_state": {
                            "headline": "偏多",
                            "position": "bullish",
                        }
                    },
                }
            },
        )

        self.assertFalse(technical["decision_usable"])
        self.assertNotIn("raw_selected_score", technical["analysis"])
        self.assertEqual(technical["analysis"]["composite_state"], "insufficient_evidence")
        self.assertEqual(technical["levels"]["status"], "unavailable")
        self.assertEqual(technical["levels"]["entry"], {})
        self.assertEqual(technical["levels"]["risk"], {})
        self.assertIsNone(technical["reports"]["daily"]["score"])
        self.assertEqual(
            technical["reports"]["daily"]["title"],
            "技術證據不足",
        )
        self.assertIsNone(
            technical["reports"]["daily"]["decision_state"]["headline"]
        )

    def test_taiwan_technical_projection_keeps_finalized_and_current_observation_separate(
        self,
    ) -> None:
        compact = taiwan_projection._compact_technical_report(
            {
                "timeframe": "daily",
                "phase": "daily_intraday",
                "title": "短線整理",
                "summary": "finalized",
                "score": 1,
                "confidence": "medium",
                "value": 2.0,
                "value_label": "vs MA20",
                "data": {
                    "daily_indicator": {"close": 592},
                    "decision_state_time": "2026-08-26",
                    "decision_state_status": "official_daily_finalized",
                    "decision_state": {
                        "headline": {"label": "短線整理"},
                        "qualifier": {"label": "量縮"},
                        "position": {"price": 592},
                    },
                    "current_observation": {
                        "status": "provisional_close",
                        "time": "2026-08-27",
                        "decision_usable": False,
                        "official_daily_confirmed": False,
                        "indicator": {
                            "close": 605,
                            "volume": 11_106_000,
                            "bar_status": "provisional_close",
                        },
                        "current_state": {
                            "headline": {"label": "今日暫估"},
                            "qualifier": {"label": "暫定"},
                            "position": {"price": 605},
                        },
                    },
                },
                "missing": [],
                "warnings": [],
            },
            timeframe="daily",
            analysis={"components": []},
        )

        self.assertEqual(compact["latest_finalized_close"], 592)
        self.assertEqual(compact["decision_state_time"], "2026-08-26")
        self.assertEqual(compact["decision_state"]["position"]["price"], 592)
        self.assertEqual(compact["current_observation"]["close"], 605)
        self.assertEqual(compact["current_observation"]["volume"], 11_106_000)
        self.assertFalse(compact["current_observation"]["decision_usable"])


if __name__ == "__main__":
    unittest.main()
