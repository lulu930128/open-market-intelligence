from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.ai import capability_contract
from app.ai.market_context.taiwan_projection import (
    _compact_index_quote,
    _compact_quote_snapshot,
)


class TaiwanQuoteComponentTests(unittest.TestCase):
    def test_post_close_session_close_owns_headline_while_official_daily_is_pending(
        self,
    ) -> None:
        quote = _compact_quote_snapshot(
            latest_daily=SimpleNamespace(
                trade_date="2026-08-26",
                close_price=592.0,
                trade_volume=10_000_000,
            ),
            quote_depth={
                "source": "twse_mis_quote_depth",
                "provider": "twse_mis",
                "session_phase": "post_close_snapshot",
                "market_calendar_phase": "post_close",
                "trade_date": "2026-08-27",
                "quote_time": "2026-08-27T13:30:00+08:00",
                "provider_event_time": "2026-08-27T13:30:00+08:00",
                "last_trade_available": True,
                "last_trade_price": 605.0,
                "last_trade_is_current_session": True,
                "price_available": True,
                "session_close_available": True,
                "session_close_status": "session_final",
                "session_close_price": 605.0,
                "session_close_trade_date": "2026-08-27",
                "official_close_available": False,
                "official_close_status": "pending",
                "quote_semantics": "completed_session_close",
                "delivery_status": "session_final",
                "data_core_components": {
                    "quote.session_close": {
                        "kind": "quote_session_close",
                        "status": "session_final",
                        "available": True,
                        "price": 605.0,
                        "trade_date": "2026-08-27",
                        "event_time": "2026-08-27T13:30:00+08:00",
                        "confirmed_at": "2026-08-27T13:34:00+08:00",
                        "provider": "twse_mis",
                        "source": "twse_mis_quote_depth",
                        "finalization": "session_final",
                        "official_daily": False,
                        "decision_usable": True,
                        "reconciliation_status": "pending",
                        "freshness": {
                            "status": "current",
                            "is_current": True,
                            "expected_trade_date": "2026-08-27",
                            "latest_trade_date": "2026-08-27",
                        },
                    }
                },
                "freshness": {
                    "status": "session_final",
                    "is_live": False,
                    "is_stale": False,
                    "expected_trade_date": "2026-08-27",
                },
            },
            quote_error=None,
        )

        self.assertEqual(quote["latest_price"], 605.0)
        self.assertEqual(quote["quote_semantics"], "completed_session_close")
        self.assertTrue(quote["price_decision_usable"])
        session_close = quote["components"]["session_close"]
        self.assertEqual(session_close["status"], "session_final")
        self.assertEqual(session_close["price"], 605.0)
        self.assertFalse(session_close["official_daily"])
        self.assertEqual(
            session_close["reconciliation_status"],
            "pending",
        )
        self.assertEqual(
            quote["components"]["official_close"]["status"],
            "pending",
        )

        selection = capability_contract.normalize_selection(
            selection={"required": ["quote.session_close"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            target_market="TW",
            question_intent="quote",
        )
        projected, unavailable = capability_contract.project_selected_data(
            response={
                "target": {"type": "tw_stock", "id": "3711", "market": "TW"},
                "result": {"data": {"compact": {"quote": quote}}},
                "freshness": {
                    "status": "current",
                    "is_current": True,
                    "datasets": ["tw.quote.snapshot"],
                    "missing": [],
                    "warnings": [],
                },
            },
            selection=selection,
        )
        self.assertEqual(unavailable, [])
        self.assertEqual(projected["quote.session_close"]["price"], 605.0)

    def test_quote_projection_preserves_backend_volume_contract(self) -> None:
        backend_reconciliation = {
            "reference_dataset": "market_daily_price",
            "reference_source": "TWSE OpenAPI Daily Trading",
            "reference_trade_date": "2026-07-30",
            "reference_volume_shares": 51_372_177,
            "snapshot_trade_date": "2026-07-30",
            "snapshot_volume_shares": 44_328_000,
            "difference_shares": -7_044_177,
            "difference_pct": -13.712,
            "tolerance_pct": 1.0,
            "status": "mismatch",
            "reason": (
                "provider_cumulative_volume_differs_from_official_daily_total"
            ),
            "decision_usable": False,
        }
        quote = _compact_quote_snapshot(
            latest_daily=SimpleNamespace(
                trade_date="2026-07-30",
                trade_volume=44_328_000,
            ),
            quote_depth={
                "source": "twse_mis_quote_depth",
                "provider": "twse_mis",
                "session_phase": "post_close_snapshot",
                "trade_date": "2026-07-30",
                "quote_time": "2026-07-30T13:30:00+08:00",
                "last_trade_available": True,
                "last_trade_price": 2205.0,
                "price_available": True,
                "total_volume_lots": 44_328,
                "cumulative_volume_lots": 44_328,
                "cumulative_volume_shares": 44_328_000,
                "last_trade_volume_lots": 5_494,
                "last_trade_volume_shares": 5_494_000,
                "official_daily_volume_shares": 51_372_177,
                "official_daily_volume_trade_date": "2026-07-30",
                "official_daily_volume_source": (
                    "TWSE OpenAPI Daily Trading"
                ),
                "volume_reconciliation": backend_reconciliation,
                "volume_decision_usable": False,
                "depth_available": False,
                "official_close_available": True,
                "official_close_status": "confirmed",
                "freshness": {
                    "status": "official_close",
                    "is_live": False,
                    "is_stale": False,
                },
            },
            quote_error=None,
        )

        self.assertEqual(quote["last_trade_volume_lots"], 5_494)
        self.assertEqual(quote["last_trade_volume_shares"], 5_494_000)
        self.assertEqual(
            quote["official_daily_volume_shares"],
            51_372_177,
        )
        self.assertEqual(
            quote["volume_reconciliation"],
            backend_reconciliation,
        )
        self.assertFalse(quote["volume_decision_usable"])

    def test_quote_volume_reconciliation_preserves_price_usability(self) -> None:
        quote = _compact_quote_snapshot(
            latest_daily=SimpleNamespace(
                trade_date="2026-07-29",
                trade_volume=68_139_691,
            ),
            quote_depth={
                "source": "twse_mis_quote_depth",
                "provider": "twse_mis",
                "session_phase": "post_close_snapshot",
                "trade_date": "2026-07-29",
                "quote_time": "2026-07-29T13:30:00+08:00",
                "snapshot_time": "2026-07-29T20:36:56+08:00",
                "provider_event_time": "2026-07-29T13:30:00+08:00",
                "last_trade_available": True,
                "last_trade_price": 1500.0,
                "price_available": True,
                "total_volume_lots": 55_171,
                "depth_available": False,
                "official_close_available": True,
                "official_close_status": "confirmed",
                "freshness": {
                    "status": "official_close",
                    "is_live": False,
                    "is_stale": False,
                },
            },
            quote_error=None,
        )

        reconciliation = quote["volume_reconciliation"]
        self.assertEqual(
            quote["cumulative_volume_shares"],
            55_171_000,
        )
        self.assertEqual(
            reconciliation["reference_volume_shares"],
            68_139_691,
        )
        self.assertEqual(
            reconciliation["difference_shares"],
            -12_968_691,
        )
        self.assertAlmostEqual(
            reconciliation["difference_pct"],
            -19.0325,
            places=3,
        )
        self.assertEqual(reconciliation["status"], "scope_different")
        self.assertEqual(
            reconciliation["reason"],
            "provider_and_official_volume_scopes_differ",
        )
        self.assertFalse(quote["volume_decision_usable"])
        self.assertTrue(quote["price_decision_usable"])

    def test_preopen_order_book_is_current_without_last_trade(self) -> None:
        quote = _compact_quote_snapshot(
            latest_daily=None,
            quote_depth={
                "source": "twse_mis_quote_depth",
                "provider": "twse_mis",
                "session_phase": "preopen",
                "trade_date": "2026-07-29",
                "snapshot_time": "2026-07-29T08:50:00+08:00",
                "provider_event_time": "2026-07-29T08:49:59+08:00",
                "last_trade_available": False,
                "price_available": False,
                "depth_available": True,
                "best_bid_price": 120.0,
                "best_bid_size_lots": 50,
                "best_ask_price": 120.5,
                "best_ask_size_lots": 40,
                "spread": 0.5,
                "spread_pct": 0.4167,
                "bid_levels": [{"price": 120.0, "volume_lots": 50}],
                "ask_levels": [{"price": 120.5, "volume_lots": 40}],
                "top5_bid_volume_lots": 100,
                "top5_ask_volume_lots": 80,
                "top5_imbalance": 0.1111,
                "depth_volume_unit": "lots",
                "auction_book_available": True,
                "auction_book_status": "available",
                "auction_book_time": "2026-07-29T08:49:59+08:00",
                "auction_best_bid": 120.0,
                "auction_best_ask": 120.5,
                "auction_indicative_available": True,
                "indicative_match_available": False,
                "official_close_available": False,
                "official_close_status": "not_available_yet",
                "freshness": {
                    "status": "live",
                    "is_live": True,
                    "is_stale": False,
                    "age_seconds": 1,
                },
            },
            quote_error=None,
            live_quote_requested=True,
        )

        self.assertFalse(quote["last_trade_available"])
        order_book = quote["components"]["order_book"]
        auction = quote["components"]["auction"]
        official_close = quote["components"]["official_close"]
        self.assertEqual(order_book["status"], "current")
        self.assertTrue(order_book["freshness"]["is_current"])
        self.assertEqual(order_book["best_bid_price"], 120.0)
        self.assertEqual(auction["status"], "current")
        self.assertTrue(auction["available"])
        self.assertEqual(official_close["status"], "pending")
        self.assertFalse(official_close["available"])

    def test_component_capabilities_project_independently(self) -> None:
        quote = _compact_quote_snapshot(
            latest_daily=None,
            quote_depth={
                "source": "twse_mis_quote_depth",
                "provider": "twse_mis",
                "session_phase": "regular_live",
                "trade_date": "2026-07-29",
                "quote_time": "2026-07-29T10:00:00+08:00",
                "provider_event_time": "2026-07-29T09:59:59+08:00",
                "last_trade_available": True,
                "last_trade_price": 121.0,
                "price_available": True,
                "depth_available": True,
                "best_bid_price": 120.5,
                "best_ask_price": 121.0,
                "bid_levels": [{"price": 120.5, "volume_lots": 10}],
                "ask_levels": [{"price": 121.0, "volume_lots": 11}],
                "official_close_available": False,
                "official_close_status": "not_available_yet",
                "freshness": {
                    "status": "live",
                    "is_live": True,
                    "is_stale": False,
                },
            },
            quote_error=None,
            live_quote_requested=True,
        )
        selection = capability_contract.normalize_selection(
            selection={
                "required": [
                    "target.identity",
                    "quote.order_book",
                    "quote.auction",
                    "quote.official_close",
                ]
            },
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            target_market="TW",
            question_intent="quote",
        )
        projected, unavailable = capability_contract.project_selected_data(
            response={
                "target": {
                    "type": "tw_stock",
                    "id": "2330",
                    "market": "TW",
                },
                "result": {
                    "data": {
                        "compact": {
                            "target": {
                                "type": "tw_stock",
                                "id": "2330",
                                "market": "TW",
                            },
                            "quote": quote,
                        }
                    }
                },
                "freshness": {
                    "status": "current",
                    "is_current": True,
                    "datasets": ["taiwan_quote_order_book"],
                    "missing": [],
                    "warnings": [],
                },
            },
            selection=selection,
        )

        self.assertEqual(unavailable, [])
        self.assertEqual(
            projected["quote.order_book"]["best_bid_price"],
            120.5,
        )
        self.assertEqual(
            projected["quote.auction"]["status"],
            "not_applicable",
        )
        self.assertEqual(
            projected["quote.official_close"]["status"],
            "pending",
        )
        self.assertNotIn(
            "last_trade_price",
            projected["quote.order_book"],
        )

    def test_index_official_close_component_preserves_close_semantics(
        self,
    ) -> None:
        quote = _compact_index_quote(
            index_id="TAIEX",
            index_snapshot={
                "index_id": "TAIEX",
                "close": 23000.12,
                "trade_date": "2026-07-28",
                "as_of": "2026-07-28T13:30:00+08:00",
                "official_close_status": "confirmed",
                "source": "market_index_daily_stat",
            },
            intraday=None,
            calendar_status={
                "market": "tw",
                "date": "2026-07-29",
                "is_trading_day": False,
                "phase": "closed",
                "previous_trading_day": "2026-07-28",
                "session": {},
                "timezone": "Asia/Taipei",
            },
        )

        official_close = quote["components"]["official_close"]
        self.assertTrue(official_close["available"])
        self.assertEqual(
            official_close["status"],
            "latest_completed_session",
        )
        self.assertEqual(official_close["price"], 23000.12)
        self.assertEqual(official_close["trade_date"], "2026-07-28")


if __name__ == "__main__":
    unittest.main()
