from __future__ import annotations

import unittest

from app.ai import agentic_tools, tools
from app.ai.market_context import common


class AIMarketContextProjectionTests(unittest.TestCase):
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

    def test_source_refs_are_deduplicated_by_name_or_kind(self) -> None:
        refs: list[dict] = []
        common.append_source_ref_once(refs, {"type": "table", "name": "daily_price"})
        common.append_source_ref_once(refs, {"type": "table", "name": "daily_price"})
        common.append_source_ref_once(refs, {"type": "derived", "kind": "freshness"})

        self.assertEqual(len(refs), 2)


if __name__ == "__main__":
    unittest.main()
