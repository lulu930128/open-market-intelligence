from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import agentic_tools, ask_execution, contract_manifest, llm, tools
from app.ai.schemas import AiAskRequest
from app.ai.market_context import common as market_context_common
from app.ai.market_context import taiwan_market
from app.ai.market_context.taiwan_futures import _build_tw_futures_compact
from app.db.models import Base
from app.market import stock_selection_refresh
from app.watchlists import backfill_service as watchlist_backfill_service


EXPECTED_INTERNAL_TOOL_NAMES = (
    "omi.ask",
    "omi.read_refresh_status",
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
    "beb515030bdb178be959c267d3776a129a182157b069f6ae752619b6429b6eee"
)


class AIToolBoundaryTests(unittest.TestCase):
    def test_explicit_tw_daily_execution_uses_only_bounded_daily_reader(
        self,
    ) -> None:
        payload = AiAskRequest(
            question="只讀 3711 最近 20 根正式日 K",
            target={"type": "tw_stock", "id": "3711"},
            mode="data_only",
            market_data_params={
                "reader_profile": "daily_only",
                "trade_date": "2026-08-27",
            },
        )
        policy = {
            "query_plan": {
                "reader_profile": "daily_only",
                "trade_date": "2026-08-27",
                "include_intraday": False,
                "selection": {"limits": {"daily.ohlcv": 20}},
            }
        }
        expected = {"kind": "stock_daily_context"}

        with (
            patch.object(
                ask_execution.tools,
                "read_stock_daily_context",
                return_value=expected,
            ) as daily_reader,
            patch.object(
                ask_execution.tools,
                "read_stock_context",
            ) as broad_reader,
        ):
            action, result = ask_execution._read_data_only(
                db=object(),
                payload=payload,
                scope_type="stock",
                policy=policy,
            )

        self.assertEqual(action, "omi.read_stock_daily")
        self.assertIs(result, expected)
        daily_reader.assert_called_once_with(
            db=ANY,
            stock_id="3711",
            bars=20,
            market_data_params={
                "reader_profile": "daily_only",
                "trade_date": "2026-08-27",
                "realtime_policy": "prefer_live",
                "external_fetch_allowed": False,
                "fallback_to_cached": True,
                "include_intraday": False,
            },
        )
        broad_reader.assert_not_called()

    def test_explicit_tw_technical_execution_uses_bounded_technical_reader(
        self,
    ) -> None:
        payload = AiAskRequest(
            question="只讀 3711 技術結構",
            target={"type": "tw_stock", "id": "3711"},
            mode="data_only",
            analysis_horizon="swing",
            market_data_params={"reader_profile": "technical_only"},
        )
        policy = {
            "query_plan": {
                "reader_profile": "technical_only",
                "selection": {"limits": {"daily.ohlcv": 60}},
            }
        }
        expected = {"kind": "stock_technical_context"}

        with (
            patch.object(
                ask_execution.tools,
                "read_stock_technical_context",
                return_value=expected,
            ) as technical_reader,
            patch.object(
                ask_execution.tools,
                "read_stock_context",
            ) as broad_reader,
        ):
            action, result = ask_execution._read_data_only(
                db=object(),
                payload=payload,
                scope_type="stock",
                question_intent="trend_view",
                policy=policy,
            )

        self.assertEqual(action, "omi.read_stock_technical")
        self.assertIs(result, expected)
        technical_reader.assert_called_once_with(
            db=ANY,
            stock_id="3711",
            bars=60,
            analysis_horizon="swing",
            market_data_params=ANY,
        )
        broad_reader.assert_not_called()

    def test_explicit_us_market_uses_supplemental_index_without_tw_reader(
        self,
    ) -> None:
        payload = AiAskRequest(
            question="美國整體市場狀況",
            target={"type": "market", "id": "US", "market": "US"},
            output="evidence_only",
        )
        regional_result = {
            "target": {
                "type": "us_stock",
                "id": "^GSPC",
                "market": "US",
            },
            "data": {
                "compact": {
                    "target": {
                        "type": "us_stock",
                        "id": "^GSPC",
                        "market": "US",
                    }
                }
            },
        }
        indices_result = {
            "contract_version": "omi.market.us_indices.v1",
            "kind": "us_market_indices",
            "market": "US",
            "status": "missing",
        }

        with (
            patch.object(
                ask_execution.agentic_tools,
                "read_us_stock_context",
                return_value=regional_result,
            ) as read_us,
            patch.object(
                ask_execution,
                "read_us_market_indices",
                return_value=SimpleNamespace(
                    model_dump=lambda **_kwargs: indices_result
                ),
            ) as read_indices,
            patch.object(
                ask_execution.tools,
                "read_market_overview",
            ) as read_tw,
        ):
            action, result = ask_execution._read_data_only(
                db=object(),
                payload=payload,
                scope_type="market",
            )

        self.assertEqual(action, "omi.read_market_overview")
        read_us.assert_called_once()
        self.assertEqual(read_us.call_args.kwargs["symbol"], "^GSPC")
        read_indices.assert_called_once()
        read_tw.assert_not_called()
        self.assertEqual(result["target"]["type"], "market")
        self.assertEqual(result["target"]["id"], "US")
        reference = result["data"]["compact"]["representative_index"]
        self.assertEqual(reference["id"], "^GSPC")
        self.assertFalse(reference["scope_replacement"])
        self.assertEqual(
            result["data"]["compact"]["market"]["indices"],
            indices_result,
        )

    def test_market_volume_uses_same_date_official_breadth_when_minute_cache_is_empty(
        self,
    ) -> None:
        volume_state = taiwan_market._volume_state_with_breadth_current_value(
            {
                "kind": "taiwan_market_volume_state",
                "status": "partial",
                "currency": "TWD",
                "trade_value_unit": "TWD",
                "current_cumulative_trade_value": None,
                "markets": [],
                "warnings": ["minute history is still accumulating"],
            },
            breadth={
                "status": "ready",
                "as_of": "2026-07-24T13:30:00+08:00",
                "markets": {
                    "TWSE": {
                        "market": "TWSE",
                        "index_id": "TAIEX",
                        "scope": "full_market",
                        "status": "ready",
                        "trade_date": "2026-07-24",
                        "trade_value": 5_000_000_000_000,
                        "source": "twse_rwd_mi_index",
                    },
                    "TPEX": {
                        "market": "TPEX",
                        "index_id": "TPEX",
                        "scope": "full_market",
                        "status": "ready",
                        "trade_date": "2026-07-24",
                        "trade_value": 500_000_000_000,
                        "source": "tpex_openapi_mainboard_quotes",
                    },
                },
            },
        )

        self.assertEqual(
            volume_state["current_cumulative_trade_value"],
            5_500_000_000_000,
        )
        self.assertEqual(
            volume_state["current_value_source"],
            "official_market_breadth_summary",
        )
        self.assertEqual(
            volume_state["field_status"]["current_cumulative_trade_value"][
                "status"
            ],
            "available",
        )
        self.assertEqual(volume_state["status"], "partial")

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

        self.assertEqual(
            [item["name"] for item in catalog["tools"]],
            ["omi.ask", "omi.read_refresh_status"],
        )
        schema = catalog["tools"][0]["input_schema"]
        self.assertEqual(
            schema["x-omi-capability-registry-version"],
            "omi.capability.registry.v3",
        )
        self.assertEqual(
            schema["x-omi-capability-selection-version"],
            "omi.capability.selection.v2",
        )
        self.assertEqual(
            schema["x-omi-public-contract-digest"],
            contract_manifest.public_contract_manifest()["digest"],
        )
        self.assertEqual(
            schema["x-omi-targets"],
            contract_manifest.public_contract_manifest()["targets"],
        )
        self.assertIn(
            "parameters",
            schema["properties"]["selection"]["properties"],
        )
        quote = next(
            item
            for item in schema["x-omi-capabilities"]
            if item["capability_id"] == "quote.snapshot"
        )
        self.assertIn("quote_time", quote["fields"])
        intraday = next(
            item
            for item in schema["x-omi-capabilities"]
            if item["capability_id"] == "intraday.bars"
        )
        self.assertTrue(
            {
                "requested_interval",
                "source_interval",
                "effective_interval",
                "sampling_mode",
                "original_point_count",
            }
            <= set(intraday["fields"])
        )
        self.assertIn("selection", schema["properties"])
        self.assertIn("position_context", schema["properties"])
        self.assertEqual(
            schema["properties"]["contract_version"]["enum"],
            ["omi.decision.v4"],
        )
        market_data_params = schema["properties"]["market_data_params"][
            "properties"
        ]
        self.assertIn("problems_only", market_data_params)
        self.assertIn("include_healthy", market_data_params)
        self.assertIn("status_filter", market_data_params)
        self.assertIn("provider", market_data_params)
        self.assertEqual(
            market_data_params["intraday_interval"]["enum"],
            ["1m", "5m", "15m", "30m", "1h", "4h"],
        )
        self.assertIn("interval", market_data_params)

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
                "_read_taiwan_bars",
                side_effect=lambda **kwargs: SimpleNamespace(
                    instrument_id=kwargs["instrument_id"]
                ),
            ) as get_intraday,
            patch.object(
                taiwan_market,
                "project_taiwan_bar_series",
                return_value=intraday_payload,
            ),
            patch.object(
                tools,
                "get_market_index_summary",
                return_value={
                    "indices": [
                        {
                            "index_id": "TAIEX",
                            "breadth": {
                                "market": "TWSE",
                                "scope": "full_market",
                                "trade_date": date(2026, 7, 14),
                                "advance_count": 700,
                                "decline_count": 300,
                                "unchanged_count": 50,
                                "total_count": 1050,
                                "source": "test_full_market",
                            },
                        }
                    ]
                },
            ) as get_summary,
            patch.object(
                tools.tw_cross_market,
                "read_tw_cross_market_context",
                return_value={
                    "kind": "tw_cross_market_context",
                    "status": "partial",
                    "as_of": "2026-07-14",
                    "markets": {},
                    "missing": ["us.^GSPC"],
                    "warnings": [],
                    "source_refs": [],
                },
            ) as read_cross_market,
            patch.object(
                tools.tw_market_chips,
                "read_tw_market_chips_context",
                return_value={
                    "kind": "tw_market_chips_context",
                    "status": "partial",
                    "official_market_aggregate": {"trade_dates": ["2026-07-14"]},
                    "institutional_per_stock": {},
                    "margin_per_stock": {},
                    "missing": [],
                    "warnings": [],
                    "source_refs": [],
                },
            ) as read_market_chips,
            patch.object(
                tools,
                "read_taiwan_market_volume_state",
                return_value={
                    "kind": "taiwan_market_volume_state",
                    "status": "partial",
                    "as_of": None,
                    "warnings": ["history accumulating"],
                    "source_refs": [
                        {"type": "table", "name": "taiwan_market_minute_state"}
                    ],
                },
            ) as read_volume_state,
            patch.object(
                tools,
                "build_taiwan_source_health",
                return_value={
                    "kind": "taiwan_source_health",
                    "generated_at": fixed_now.isoformat(),
                    "summary": {
                        "entry_count": 3,
                        "ok_count": 2,
                        "stale_count": 1,
                    },
                    "entries": [],
                },
            ) as build_source_health,
        ):
            envelope = tools.read_market_overview(
                db=db,
                include_intraday=True,
                market_data_params={
                    "requested_capabilities": ["source.health"],
                },
            )

        self.assertEqual(envelope["generated_at"], fixed_now)
        self.assertEqual(
            [call.kwargs["instrument_id"] for call in get_intraday.call_args_list],
            ["TAIEX", "TPEX"],
        )
        self.assertTrue(envelope["data"]["index_intraday"]["enabled"])
        get_summary.assert_called_once_with(db, force_refresh=False)
        self.assertEqual(envelope["data"]["breadth"]["scope"], "full_market")
        self.assertEqual(envelope["data"]["breadth"]["total_count"], 1050)
        read_cross_market.assert_called_once_with(db=db, now=fixed_now)
        read_market_chips.assert_called_once_with(db=db, limit=10)
        read_volume_state.assert_called_once_with(db=db)
        build_source_health.assert_called_once_with(
            db,
            now=fixed_now,
            sync_snapshots=False,
        )
        self.assertEqual(
            envelope["data"]["compact"]["source_health"]["status"],
            "partial",
        )
        self.assertEqual(
            envelope["data"]["source_health"]["summary"]["stale_count"],
            1,
        )
        self.assertEqual(envelope["data"]["slots"]["cross_market"]["status"], "partial")
        self.assertEqual(envelope["data"]["slots"]["market_chips"]["status"], "partial")
        self.assertEqual(envelope["data"]["slots"]["market_volume"]["status"], "partial")
        self.assertIn("market_daily_price", envelope["missing"])
        self.assertIn("market_breadth.tpex", envelope["missing"])
        self.assertEqual(envelope["freshness"]["missing"], envelope["missing"])

    def test_futures_facade_hands_off_runtime_dependencies(self) -> None:
        fixed_now = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
        db = MagicMock(spec=Session)
        market_chip_row = object()

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
            patch.object(
                tools,
                "get_latest_market_chip_daily",
                return_value=market_chip_row,
            ) as get_market_chip,
            patch.object(
                tools,
                "list_market_chip_daily",
                return_value=[market_chip_row],
            ) as list_market_chips,
            patch.object(
                tools,
                "build_taiwan_derivatives_summary",
                return_value={
                    "status": "ready",
                    "as_of": date(2026, 7, 14),
                    "missing": [],
                    "warnings": [],
                    "options_chain": {"status": "ready"},
                    "large_traders": {"status": "ready"},
                    "term_structure": {"status": "ready"},
                },
            ) as build_derivatives,
            patch.object(
                tools.taiwan_futures,
                "market_chip_daily_to_dict",
                return_value={
                    "trade_date": date(2026, 7, 14),
                    "foreign_futures_net_oi": -86_189,
                    "foreign_futures_net_oi_change": -1_736,
                    "retail_futures_net_oi": 11_776,
                    "retail_futures_net_oi_change": 828,
                    "put_volume": 377_448,
                    "call_volume": 451_306,
                    "put_call_volume_ratio_pct": 83.63,
                    "put_open_interest": 42_516,
                    "call_open_interest": 45_745,
                    "put_call_open_interest_ratio_pct": 92.94,
                },
            ),
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
        get_market_chip.assert_called_once_with(db, index_id="TAIEX")
        list_market_chips.assert_called_once_with(db, index_id="TAIEX", limit=20)
        build_derivatives.assert_called_once_with(
            db,
            option_contract_month=None,
            option_strike_limit=11,
        )
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
        self.assertEqual(
            envelope["data"]["institutional_position"]["foreign_futures_net_oi"],
            -86_189,
        )
        self.assertEqual(
            envelope["data"]["options_sentiment"]["put_call_open_interest_ratio_pct"],
            92.94,
        )
        self.assertEqual(envelope["data"]["market_chip_trend"]["status"], "partial")
        self.assertEqual(envelope["data"]["derivatives"]["status"], "ready")
        self.assertEqual(
            envelope["data"]["market_chip_trend"]["coverage"]["available_days"],
            1,
        )
        self.assertEqual(
            envelope["data"]["slots"]["institutional_position"]["status"],
            "ready",
        )
        self.assertEqual(
            envelope["data"]["slots"]["options_sentiment"]["status"],
            "ready",
        )

    def test_futures_compact_separates_night_quote_daily_close_and_post_close_chips(self) -> None:
        compact = _build_tw_futures_compact(
            symbol="TXF",
            latest_quote={
                "symbol": "TXF",
                "session": "after_hours",
                "quote_time": "2026-07-18T04:59:58+08:00",
                "last_price": 43_481,
                "reference_price": 42_604,
                "settlement_price": 0,
                "open_interest": 0,
                "freshness": {"status": "live", "is_stale": False},
            },
            latest_daily={
                "trade_date": "2026-07-17",
                "close_price": 42_725,
                "source": "taifex_daily_market",
            },
            daily_chart={"points": [{"date": "2026-07-17", "close": 42_725}]},
            intraday_chart=None,
            analysis={"selected_title": "波段偏空"},
            institutional_position={
                "trade_date": "2026-07-17",
                "foreign_futures_net_oi": -86_189,
                "foreign_futures_net_oi_change": -1_736,
            },
            options_sentiment={
                "trade_date": "2026-07-17",
                "put_call_volume_ratio_pct": 83.63,
                "put_call_open_interest_ratio_pct": 92.94,
            },
            market_chip_trend={
                "status": "partial",
                "as_of": "2026-07-17",
                "latest": {"foreign_futures_net_oi": -86_189},
                "coverage": {"available_days": 20, "complete_days": 1},
                "windows": {},
            },
            derivatives={"status": "partial", "as_of": "2026-07-17"},
            payload_level_value="compact",
        )

        self.assertEqual(compact["quote"]["last_price"], 43_481)
        self.assertEqual(compact["daily_close"]["close_price"], 42_725)
        self.assertIsNone(compact["quote"]["settlement_price"])
        self.assertIsNone(compact["quote"]["open_interest"])
        self.assertEqual(compact["quote"]["field_status"]["open_interest"], "missing")
        self.assertEqual(compact["slots"]["latest_session_quote"]["status"], "ready")
        self.assertEqual(
            compact["freshness_by_domain"]["quote"]["status"],
            "live",
        )
        self.assertTrue(compact["freshness_by_domain"]["quote"]["is_current"])
        self.assertEqual(
            compact["freshness_by_domain"]["quote"]["capability"],
            "quote.snapshot",
        )
        self.assertEqual(compact["freshness_by_domain"]["chart"], "ready")
        self.assertEqual(compact["slots"]["institutional_position"]["status"], "ready")
        self.assertIn(
            "official_daily_post_close_not_live_night_session",
            compact["slots"]["options_sentiment"]["warnings"],
        )
        self.assertEqual(compact["slots"]["data_quality"]["status"], "partial")
        self.assertEqual(compact["source_health"]["status"], "ready")
        self.assertEqual(compact["source_health"]["summary"]["entry_count"], 2)
        self.assertEqual(
            {entry["resource"] for entry in compact["source_health"]["entries"]},
            {"futures_quote", "futures_daily_bar"},
        )
        self.assertEqual(compact["slots"]["source_health"]["status"], "ready")
        self.assertTrue(
            compact["freshness_by_domain"]["source_health"]["is_current"]
        )

    def test_futures_compact_preserves_intraday_contract_volume(self) -> None:
        compact = _build_tw_futures_compact(
            symbol="TXF",
            latest_quote={
                "symbol": "TXF",
                "session": "regular",
                "quote_time": "2026-07-28T10:00:00+08:00",
                "last_price": 23_500,
                "total_volume": 12_345,
                "freshness": {"status": "live", "is_stale": False},
            },
            latest_daily={
                "trade_date": "2026-07-27",
                "close_price": 23_400,
                "source": "taifex_daily_market",
            },
            daily_chart={"points": [{"date": "2026-07-27", "close": 23_400}]},
            intraday_chart={
                "timeframe": "today",
                "interval": "1m",
                "point_count": 1,
                "from_date": "2026-07-28T10:00:00",
                "to_date": "2026-07-28T10:00:00",
                "source": "TAIFEX MIS 1-minute chart",
                "provider": "taifex_mis",
                "points": [
                    {
                        "time": "2026-07-28T10:00:00",
                        "open": 23_490,
                        "high": 23_510,
                        "low": 23_480,
                        "close": 23_500,
                        "volume": 321,
                        "session": "regular",
                    }
                ],
            },
            analysis={"selected_title": "盤中"},
            institutional_position=None,
            options_sentiment=None,
            market_chip_trend={
                "status": "missing",
                "as_of": None,
                "latest": None,
                "coverage": {"available_days": 0},
                "windows": {},
            },
            derivatives={"status": "partial", "as_of": "2026-07-27"},
            payload_level_value="compact",
        )

        self.assertEqual(compact["quote"]["total_volume_contracts"], 12_345)
        self.assertEqual(compact["quote"]["volume_unit"], "contracts")
        intraday = compact["intraday_chart"]
        self.assertEqual(intraday["volume_unit"], "contracts")
        self.assertEqual(intraday["volume_semantics"], "interval_contracts")
        self.assertEqual(intraday["volume_contracts"], 321)
        self.assertEqual(
            intraday["volume_event_time"],
            "2026-07-28T10:00:00+08:00",
        )
        self.assertEqual(intraday["source"], "TAIFEX MIS 1-minute chart")
        self.assertEqual(intraday["provider"], "taifex_mis")
        self.assertEqual(
            intraday["points"][0]["time"],
            "2026-07-28T10:00:00+08:00",
        )
        self.assertEqual(intraday["points"][0]["volume_contracts"], 321)
        self.assertEqual(intraday["points"][0]["session"], "regular")


if __name__ == "__main__":
    unittest.main()
