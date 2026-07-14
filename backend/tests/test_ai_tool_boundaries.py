from __future__ import annotations

import hashlib
import json
import unittest

from app.ai import tools


EXPECTED_INTERNAL_TOOL_NAMES = (
    "omi.ask",
    "omi.read_market_overview",
    "omi.read_stock_context",
    "omi.read_tw_index_context",
    "omi.read_tw_futures_context",
    "omi.read_us_stock_context",
    "omi.read_jp_stock_context",
    "omi.read_jp_index_context",
    "omi.read_kr_stock_context",
    "omi.read_kr_index_context",
    "omi.read_crypto_market_context",
    "omi.read_crypto_asset_context",
    "omi.read_watchlist_context",
    "omi.read_data_freshness",
    "omi.generate_stock_brief",
    "omi.generate_us_stock_brief",
    "omi.generate_watchlist_brief",
    "omi.generate_stock_llm_report",
    "omi.generate_us_stock_llm_report",
    "omi.generate_watchlist_llm_report",
    "omi.read_memories",
    "omi.write_memory",
    "omi.update_memory",
    "omi.archive_memory",
    "omi.read_reports",
    "omi.read_report",
    "omi.save_stock_brief",
    "omi.save_us_stock_brief",
    "omi.save_watchlist_brief",
)

EXPECTED_INTERNAL_TOOL_CATALOG_SHA256 = (
    "73e3d669e49105aa7a854f3b6df35cf4d5dcee8fd975e9d01236caf21d42d1be"
)


class AIToolBoundaryTests(unittest.TestCase):
    def test_public_tool_inventory_exposes_only_omi_ask(self) -> None:
        catalog = tools.list_ai_tools()

        self.assertEqual([item["name"] for item in catalog["tools"]], ["omi.ask"])

    def test_internal_tool_catalog_contract_remains_stable(self) -> None:
        catalog = tools.list_ai_tools(include_internal=True)
        encoded = json.dumps(
            catalog,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

        self.assertEqual(
            tuple(item["name"] for item in catalog["tools"]),
            EXPECTED_INTERNAL_TOOL_NAMES,
        )
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            EXPECTED_INTERNAL_TOOL_CATALOG_SHA256,
        )

    def test_tool_catalog_calls_do_not_share_mutable_state(self) -> None:
        first = tools.list_ai_tools(include_internal=True)
        first["tools"][0]["title"] = "mutated"

        second = tools.list_ai_tools(include_internal=True)

        self.assertEqual(second["tools"][0]["title"], "Ask OMI")


if __name__ == "__main__":
    unittest.main()
