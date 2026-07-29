from __future__ import annotations

import unittest

from app.ai import capability_contract
from app.ai.market_context.taiwan_projection import (
    _compact_index_quote,
    _compact_quote_snapshot,
)


class TaiwanQuoteComponentTests(unittest.TestCase):
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
