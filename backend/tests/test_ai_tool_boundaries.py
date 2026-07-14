from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import agentic_tools, llm, tools
from app.ai.market_context import common as market_context_common
from app.db.models import Base
from app.market import stock_selection_refresh
from app.watchlists import backfill_service as watchlist_backfill_service


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
    def test_agentic_facade_keeps_runtime_patch_targets(self) -> None:
        self.assertIs(agentic_tools.llm, llm)
        self.assertIs(agentic_tools.stock_selection_refresh, stock_selection_refresh)
        self.assertIs(
            agentic_tools.watchlist_backfill_service,
            watchlist_backfill_service,
        )
        self.assertIs(
            agentic_tools._compact_market_context,
            market_context_common.compact_market_context,
        )
        self.assertIs(
            agentic_tools._append_source_ref_once,
            market_context_common.append_source_ref_once,
        )

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

    def test_data_freshness_facade_preserves_clock_patch_and_empty_contract(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        db = Session(engine)
        fixed_now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

        try:
            with patch.object(tools, "_now", return_value=fixed_now):
                envelope = tools.read_data_freshness(db=db, stock_id="2330")
        finally:
            db.close()

        expected_tables = (
            "market_daily_price",
            "institutional_trade_daily",
            "margin_trading_daily",
            "broker_branch_trade_daily",
            "shareholding_distribution_weekly",
            "monthly_revenue",
            "financial_metric_quarterly",
        )
        self.assertEqual(envelope["kind"], "data_freshness")
        self.assertEqual(envelope["generated_at"], fixed_now)
        self.assertIsNone(envelope["as_of"])
        self.assertEqual(tuple(envelope["data"]["tables"]), expected_tables)
        self.assertEqual(envelope["missing"], list(expected_tables))
        self.assertTrue(
            all(
                table["latest"] is None and table["row_count"] == 0
                for table in envelope["data"]["tables"].values()
            )
        )
        self.assertEqual(envelope["evidence_passport"]["kind"], "evidence_passport")
        self.assertEqual(envelope["evidence_passport"]["target_kind"], "data_freshness")

    def test_market_overview_facade_hands_off_runtime_dependencies(self) -> None:
        fixed_now = datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc)
        db = MagicMock(spec=Session)
        intraday_payload = {
            "index_id": "TAIEX",
            "points": [],
            "source": "test",
        }

        with (
            patch.object(tools, "_now", return_value=fixed_now),
            patch.object(tools.market_service, "get_latest_trade_date", return_value=None),
            patch.object(
                tools,
                "get_market_index_intraday",
                return_value=intraday_payload,
            ) as get_intraday,
        ):
            envelope = tools.read_market_overview(db=db, include_intraday=True)

        self.assertEqual(envelope["generated_at"], fixed_now)
        self.assertEqual(
            [call.args[0] for call in get_intraday.call_args_list],
            ["TAIEX", "TPEX"],
        )
        self.assertTrue(envelope["data"]["index_intraday"]["enabled"])
        self.assertIn("market_daily_price", envelope["missing"])

    def test_futures_facade_hands_off_runtime_dependencies(self) -> None:
        fixed_now = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
        db = MagicMock(spec=Session)

        with (
            patch.object(tools, "_now", return_value=fixed_now),
            patch.object(
                tools,
                "get_latest_taiwan_futures_quotes",
                return_value=[],
            ) as get_quotes,
            patch.object(
                tools,
                "list_taiwan_futures_daily_bars",
                return_value=[],
            ) as get_daily,
            patch.object(
                tools,
                "list_taiwan_futures_intraday_bars",
                return_value=[],
            ) as get_intraday,
        ):
            envelope = tools.read_tw_futures_context(
                db=db,
                symbol="TXF",
                include_intraday=True,
            )

        get_quotes.assert_called_once_with(db, symbols=["TXF"], refresh=False)
        get_daily.assert_called_once_with(
            db=db,
            symbol="TXF",
            limit=120,
            active_only=True,
        )
        get_intraday.assert_called_once_with(db=db, symbol="TXF", limit=390)
        self.assertEqual(envelope["kind"], "tw_futures_context")
        self.assertEqual(envelope["generated_at"], fixed_now)
        self.assertEqual(
            envelope["missing"],
            [
                "taiwan_futures_quote_snapshot",
                "taiwan_futures_daily_bar",
                "taiwan_futures_intraday_bar",
            ],
        )


if __name__ == "__main__":
    unittest.main()
