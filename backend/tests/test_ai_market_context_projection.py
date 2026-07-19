from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.ai import agentic_tools, tools
from app.ai.market_context import common, us_context
from app.ai.market_context.crypto_context import (
    _crypto_core_source_health_status,
    _crypto_health_status,
    _crypto_market_cap_matches_asset,
)
from app.crypto_market.assets import get_crypto_asset


class AIMarketContextProjectionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
