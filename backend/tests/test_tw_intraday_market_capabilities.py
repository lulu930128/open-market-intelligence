from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import capability_contract, query_plan, scope_resolution
from app.ai.market_context.taiwan_screening import read_tw_screening_context
from app.ai.schemas import AiAskRequest
from app.db.models import (
    Base,
    StockMaster,
    TaiwanIntradayStockState,
    TaiwanMarketMinuteState,
    WatchlistGroup,
    WatchlistItem,
)
from app.market.providers import twse_mis, twse_mis_current_breadth
from app.market.taiwan_index_minute import (
    persist_taiwan_index_minute_snapshots,
    read_taiwan_index_minute_series,
)
from app.market.taiwan_market_state import read_taiwan_market_volume_state
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_state import (
    build_tw_intraday_group_snapshots,
    build_tw_intraday_screening_snapshot,
    persist_taiwan_intraday_stock_states,
)


class _FakeResponse:
    encoding = "utf-8"

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class TaiwanIntradayMarketCapabilityTests(unittest.TestCase):
    def test_recent_observation_with_old_trade_remains_factually_rankable(self) -> None:
        now = datetime(2026, 9, 8, 10, 5, tzinfo=TAIWAN_TZ)
        self.db.add(StockMaster(stock_id="2454", stock_name="MediaTek", market="TWSE",
                                instrument_type="stock", industry="半導體業", is_active=True))
        self.db.commit()
        row = self._stock_state_row("2454", "TWSE", 110, 100, now)
        row.update(price_as_of=now - timedelta(minutes=8), has_actual_trade=True, price_source="session_cache")
        persist_taiwan_intraday_stock_states(self.db, rows=[row], now=now)
        result = build_tw_intraday_screening_snapshot(self.db, generated_at=now)
        self.assertEqual([row["stock_id"] for row in result["rows"]], ["2454"])
        self.assertEqual(result["observation_received_freshness"], "current")
        self.assertEqual(result["last_trade_recency"], "delayed")
        self.assertTrue(result["facts_usable"])
        self.assertTrue(result["facts_usable_for_ranking"])
        self.assertFalse(result["decision_usable"])
        self.assertEqual(result["coverage"]["ranking_excluded_count"], 0)
        tomorrow_preopen = now.replace(day=9, hour=8, minute=55)
        preopen = build_tw_intraday_screening_snapshot(self.db, generated_at=tomorrow_preopen)
        self.assertEqual(preopen["status"], "not_applicable")
        self.assertEqual(preopen["rows"], [])
        self.assertEqual(preopen["expected_trade_date"], "2026-09-09")
        self.assertFalse(preopen["decision_usable"])

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        twse_mis_current_breadth.reset_twse_mis_current_breadth_provider()

    def tearDown(self) -> None:
        twse_mis_current_breadth.reset_twse_mis_current_breadth_provider()
        self.db.close()
        self.engine.dispose()

    def test_tpex_mis_uses_otc_channel(self) -> None:
        captured: dict = {}

        def request(url: str, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return _FakeResponse({"rtcode": "0000", "msgArray": [{"c": "6488"}]})

        rows = twse_mis.fetch_stock_messages(
            ["6488", "8299"],
            exchange="otc",
            request=request,
        )

        self.assertEqual([row["c"] for row in rows], ["6488"])
        self.assertEqual(
            captured["params"]["ex_ch"],
            "otc_6488.tw|otc_8299.tw",
        )

    def test_tpex_registered_universe_breadth_is_cached_with_estimate_semantics(
        self,
    ) -> None:
        codes = [str(6000 + index) for index in range(250)]
        messages = [
            {
                "c": code,
                "d": "20260730",
                "t": "10:00:00",
                "y": "100",
                "z": "101" if index % 2 == 0 else "99",
                "o": "100",
                "h": "102",
                "l": "98",
                "v": "10",
            }
            for index, code in enumerate(codes)
        ]

        with patch.object(
            twse_mis_current_breadth,
            "_fetch_messages",
            return_value=(messages, 0, 3),
        ) as fetch_messages:
            result = twse_mis_current_breadth.read_twse_mis_current_breadth(
                "TPEX",
                10,
                universe_reader=lambda _market: codes,
            )
        payload = result.payload

        self.assertIsNotNone(payload)
        assert payload is not None
        call = fetch_messages.call_args
        self.assertEqual(call.args, (codes, "TPEX", 10))
        self.assertTrue(call.kwargs["initial_decision"].allowed)
        self.assertEqual(result.external_calls, 3)
        self.assertEqual(payload["market"], "TPEX")
        self.assertEqual(
            payload["scope"],
            "full_market_registered_stock_universe",
        )
        self.assertEqual(payload["advance_count"], 125)
        self.assertEqual(payload["decline_count"], 125)
        self.assertEqual(payload["unknown_count"], 0)
        self.assertTrue(payload["trade_value_is_estimate"])
        self.assertEqual(
            payload["trade_value_semantics"],
            "estimated_latest_price_x_cumulative_volume_lots",
        )
        cached = twse_mis_current_breadth.get_cached_current_breadth_stock_rows(
            "TPEX"
        )
        self.assertEqual(len(cached), 250)
        self.assertTrue(all(row["market"] == "TPEX" for row in cached))

    def test_intraday_state_supports_ranking_and_provenance_bound_groups(
        self,
    ) -> None:
        self.db.add_all(
            [
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    instrument_type="stock",
                    industry="半導體業",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="6488",
                    stock_name="環球晶",
                    market="TPEx",
                    instrument_type="stock",
                    industry="半導體業",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="1101",
                    stock_name="台泥",
                    market="TWSE",
                    instrument_type="stock",
                    industry="水泥工業",
                    is_active=True,
                ),
            ]
        )
        group = WatchlistGroup(
            group_name="核心持股",
            sort_order=1,
            is_active=True,
        )
        self.db.add(group)
        self.db.flush()
        self.db.add_all(
            [
                WatchlistItem(group_id=group.id, stock_id="2330", enabled=True),
                WatchlistItem(group_id=group.id, stock_id="6488", enabled=True),
            ]
        )
        self.db.commit()

        first_time = datetime(2026, 7, 30, 10, 0, tzinfo=TAIWAN_TZ)
        second_time = datetime(2026, 7, 30, 10, 5, tzinfo=TAIWAN_TZ)
        first_rows = [
            self._stock_state_row("2330", "TWSE", 105, 100, first_time),
            self._stock_state_row("6488", "TPEX", 198, 200, first_time),
            self._stock_state_row("1101", "TWSE", 51, 50, first_time),
        ]
        second_rows = [
            self._stock_state_row("2330", "TWSE", 110, 100, second_time),
            self._stock_state_row("6488", "TPEX", 190, 200, second_time),
            self._stock_state_row("1101", "TWSE", 52, 50, second_time),
        ]

        persist_taiwan_intraday_stock_states(
            self.db,
            rows=first_rows,
            now=first_time,
        )
        persist_taiwan_intraday_stock_states(
            self.db,
            rows=second_rows,
            now=second_time,
        )
        ranking = build_tw_intraday_screening_snapshot(
            self.db,
            parameters={
                "metric": "five_minute_return",
                "limit": 3,
            },
            generated_at=second_time,
        )
        group_snapshots = build_tw_intraday_group_snapshots(
            self.db,
            generated_at=second_time,
        )
        groups = group_snapshots["hot_groups"]
        sectors = group_snapshots["sectors"]

        self.assertEqual(ranking["status"], "ready")
        self.assertEqual(ranking["coverage"]["universe_count"], 3)
        self.assertEqual(ranking["coverage"]["coverage_count"], 3)
        self.assertEqual(ranking["rows"][0]["stock_id"], "2330")
        self.assertGreater(ranking["rows"][0]["value"], 4.7)
        self.assertEqual(
            ranking["rows"][0]["five_minute_return_status"],
            "calculated",
        )
        self.assertEqual(
            ranking["rows"][0]["five_minute_reference_time"],
            first_time.isoformat(),
        )
        self.assertEqual(ranking["rows"][0]["price_invariant_status"], "balanced")
        self.assertEqual(ranking["rows"][0]["estimated_trade_value_unit"], "TWD")
        self.assertFalse(groups["membership_provenance"]["inferred_by_llm"])
        self.assertEqual(
            set(groups["membership_provenance"]["allowed_sources"]),
            {
                "stock_master.industry",
                "watchlist_group+watchlist_item",
            },
        )
        self.assertTrue(
            any(
                row["group_id"] == f"watchlist:{group.id}"
                and row["membership_source"]
                == "watchlist_group+watchlist_item"
                for row in groups["groups"]
            )
        )
        self.assertEqual(groups["snapshot_id"], sectors["snapshot_id"])
        self.assertEqual(
            groups["observed_trade_date"],
            sectors["observed_trade_date"],
        )
        self.assertTrue(sectors["is_intraday"])
        self.assertEqual(
            sectors["ranking_basis"],
            "taiwan_intraday_stock_state_by_exchange_industry",
        )
        self.assertTrue(
            all(
                str(item["sector_id"]).startswith("tw.sector.")
                for item in sectors["items"]
            )
        )
        self.assertFalse(
            any(
                str(item["sector_id"]).startswith("watchlist:")
                for item in sectors["items"]
            )
        )
        semiconductor = next(
            item
            for item in sectors["items"]
            if item["name"] == "半導體業"
        )
        self.assertIn("median_return_pct", semiconductor)
        self.assertIn("return_dispersion_pct", semiconductor)
        self.assertIn("leader_concentration", semiconductor)
        self.assertEqual(semiconductor["trade_value_unit"], "TWD")
        self.assertTrue(semiconductor["trade_value_is_estimate"])

    def test_group_membership_and_observation_coverage_are_independent(self) -> None:
        self.db.add_all(
            [
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    instrument_type="stock",
                    industry="半導體業",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="3711",
                    stock_name="日月光投控",
                    market="TWSE",
                    instrument_type="stock",
                    industry="半導體業",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="6488",
                    stock_name="環球晶",
                    market="TPEX",
                    instrument_type="stock",
                    industry="半導體業",
                    is_active=True,
                ),
            ]
        )
        group = WatchlistGroup(
            group_name="被動元件",
            sort_order=1,
            is_active=True,
        )
        self.db.add(group)
        self.db.flush()
        self.db.add_all(
            [
                WatchlistItem(group_id=group.id, stock_id="2330", enabled=True),
                WatchlistItem(group_id=group.id, stock_id="3711", enabled=True),
                WatchlistItem(group_id=group.id, stock_id="6488", enabled=True),
            ]
        )
        self.db.commit()
        observed_at = datetime(2026, 7, 30, 10, 0, tzinfo=TAIWAN_TZ)
        persist_taiwan_intraday_stock_states(
            self.db,
            rows=[self._stock_state_row("2330", "TWSE", 105, 100, observed_at)],
            now=observed_at,
        )

        snapshots = build_tw_intraday_group_snapshots(
            self.db,
            generated_at=observed_at,
        )
        hot_groups = snapshots["hot_groups"]
        semiconductor = next(
            item
            for item in hot_groups["groups"]
            if item["group_id"] == "tw.sector.24"
        )
        passive = next(
            item
            for item in hot_groups["groups"]
            if item["group_id"] == f"watchlist:{group.id}"
        )

        for item in (semiconductor, passive):
            self.assertEqual(item["member_count"], 3)
            self.assertEqual(item["received_count"], 1)
            self.assertEqual(item["classified_count"], 1)
            self.assertEqual(item["observed_count"], 1)
            self.assertEqual(item["unknown_count"], 2)
            self.assertAlmostEqual(item["coverage_ratio"], 1 / 3)
            self.assertFalse(item["ranking_eligible"])
            self.assertIn(
                "OBSERVED_COUNT_BELOW_MINIMUM",
                item["ranking_ineligibility_reasons"],
            )
        sector = next(
            item
            for item in snapshots["sectors"]["items"]
            if item["sector_id"] == "tw.sector.24"
        )
        self.assertEqual(sector["member_count"], semiconductor["member_count"])
        self.assertEqual(sector["observed_count"], semiconductor["observed_count"])

    def test_hot_groups_distinguishes_weekend_completion_from_open_stale(
        self,
    ) -> None:
        self.db.add_all(
            [
                StockMaster(
                    stock_id=stock_id,
                    stock_name=stock_id,
                    market=market,
                    instrument_type="stock",
                    industry="半導體業",
                    is_active=True,
                )
                for stock_id, market in (
                    ("2330", "TWSE"),
                    ("3711", "TWSE"),
                    ("6488", "TPEX"),
                )
            ]
        )
        self.db.commit()
        friday_close = datetime(2026, 9, 4, 13, 30, tzinfo=TAIWAN_TZ)
        persist_taiwan_intraday_stock_states(
            self.db,
            rows=[
                self._stock_state_row("2330", "TWSE", 101, 100, friday_close),
                self._stock_state_row("3711", "TWSE", 99, 100, friday_close),
                self._stock_state_row("6488", "TPEX", 100, 100, friday_close),
            ],
            now=friday_close,
        )

        weekend = build_tw_intraday_group_snapshots(
            self.db,
            generated_at=datetime(2026, 9, 6, 10, 0, tzinfo=TAIWAN_TZ),
            include_watchlist_groups=False,
        )["hot_groups"]
        monday_open = build_tw_intraday_group_snapshots(
            self.db,
            generated_at=datetime(2026, 9, 7, 10, 0, tzinfo=TAIWAN_TZ),
            include_watchlist_groups=False,
        )["hot_groups"]

        self.assertEqual(weekend["status"], "partial")
        self.assertEqual(
            weekend["freshness_status"],
            "latest_completed_session",
        )
        self.assertFalse(weekend["facts_usable"])
        self.assertFalse(weekend["facts_usable_for_ranking"])
        self.assertIsNone(weekend["groups"][0]["mean_return_pct"])
        self.assertFalse(weekend["decision_usable"])
        self.assertTrue(weekend["current_for_requested_session"])
        self.assertEqual(
            weekend["expected_observation_date"],
            "2026-09-04",
        )
        self.assertEqual(monday_open["status"], "partial")
        self.assertEqual(
            monday_open["freshness_status"],
            "stale_for_expected_session",
        )
        self.assertFalse(monday_open["facts_usable"])
        self.assertFalse(monday_open["decision_usable"])
        self.assertFalse(monday_open["current_for_requested_session"])
        self.assertEqual(
            monday_open["expected_observation_date"],
            "2026-09-07",
        )

    def test_screening_reconciles_price_extremes_across_provider_switch(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="3701",
                stock_name="大眾控",
                market="TWSE",
                instrument_type="stock",
                industry="電子工業",
                is_active=True,
            )
        )
        self.db.commit()
        first_time = datetime(2026, 7, 30, 10, 0, tzinfo=TAIWAN_TZ)
        second_time = first_time.replace(minute=1)
        first = self._stock_state_row("3701", "TWSE", 36, 35, first_time)
        first.update(
            {
                "provider": "provider_a",
                "source": "provider_a_snapshot",
                "high_price": 40,
                "low_price": 30,
            }
        )
        second = self._stock_state_row("3701", "TWSE", 37, 35, second_time)
        second.update(
            {
                "provider": "provider_b",
                "source": "provider_b_snapshot",
                "high_price": 39,
                "low_price": 31,
            }
        )

        persist_taiwan_intraday_stock_states(self.db, rows=[first], now=first_time)
        persist_taiwan_intraday_stock_states(self.db, rows=[second], now=second_time)
        ranking = build_tw_intraday_screening_snapshot(
            self.db,
            parameters={"metric": "distance_from_high_pct", "limit": 5},
            generated_at=second_time,
        )

        self.assertEqual(ranking["coverage"]["coverage_count"], 1)
        self.assertEqual(len(ranking["rows"]), 1)
        row = ranking["rows"][0]
        self.assertEqual(row["current_price"], 37)
        self.assertEqual(row["high_price"], 40)
        self.assertEqual(row["low_price"], 30)
        self.assertAlmostEqual(row["distance_from_high_pct"], 7.5)
        self.assertAlmostEqual(row["rebound_from_low_pct"], (37 - 30) / 30 * 100)
        self.assertAlmostEqual(row["intraday_range_pct"], (40 - 30) / 35 * 100)
        self.assertEqual(row["price_invariant_status"], "balanced")
        self.assertEqual(row["price_snapshot_source"], "provider_b_snapshot")
        self.assertEqual(row["five_minute_return_status"], "insufficient_data")
        self.assertIsNone(row["five_minute_reference_time"])

    def test_volume_state_keeps_trade_value_usable_when_breadth_is_missing(
        self,
    ) -> None:
        minute_at = datetime(2026, 7, 30, 10, 0, tzinfo=TAIWAN_TZ)
        self.db.add_all(
            [
                self._market_minute_row(
                    market="TWSE",
                    index_id="TAIEX",
                    minute_at=minute_at,
                    trade_value=1_000,
                    trade_value_quality="ready",
                    estimated=False,
                ),
                self._market_minute_row(
                    market="TPEX",
                    index_id="TPEX",
                    minute_at=minute_at,
                    trade_value=300,
                    trade_value_quality="estimated",
                    estimated=True,
                ),
            ]
        )
        self.db.commit()

        payload = read_taiwan_market_volume_state(self.db)

        self.assertEqual(payload["current_cumulative_trade_value"], 1_300)
        self.assertEqual(payload["estimated_cumulative_trade_value"], 1_300)
        self.assertIsNone(payload["official_cumulative_trade_value"])
        self.assertTrue(payload["trade_value_complete"])
        self.assertEqual(payload["trade_value_coverage_status"], "complete")
        self.assertEqual(payload["trade_value_authority_status"], "mixed")
        self.assertEqual(payload["trade_value_status"], "mixed_complete")
        self.assertEqual(payload["missing_markets"], [])
        self.assertEqual(payload["status"], "partial")
        self.assertTrue(
            any("provider-derived estimates" in warning for warning in payload["warnings"])
        )

    def test_legacy_unknown_trade_value_quality_stays_unusable(
        self,
    ) -> None:
        minute_at = datetime(2026, 7, 30, 10, 0, tzinfo=TAIWAN_TZ)
        self.db.add_all(
            [
                self._market_minute_row(
                    market="TWSE",
                    index_id="TAIEX",
                    minute_at=minute_at,
                    trade_value=1_000,
                    trade_value_quality="unknown",
                    estimated=False,
                ),
                self._market_minute_row(
                    market="TPEX",
                    index_id="TPEX",
                    minute_at=minute_at,
                    trade_value=300,
                    trade_value_quality="unknown",
                    estimated=False,
                ),
            ]
        )
        self.db.commit()

        payload = read_taiwan_market_volume_state(self.db)

        self.assertIsNone(payload["current_cumulative_trade_value"])
        self.assertFalse(payload["trade_value_complete"])
        self.assertEqual(set(payload["missing_markets"]), {"TWSE", "TPEX"})

    def test_index_snapshots_form_synthetic_non_indicator_minute_series(
        self,
    ) -> None:
        first = datetime(2026, 7, 30, 9, 1, 5, tzinfo=TAIWAN_TZ)
        same_minute = first.replace(second=40)
        next_minute = first.replace(minute=2, second=5)
        for event_time, close in (
            (first, 23_000),
            (same_minute, 23_010),
            (next_minute, 23_005),
        ):
            persist_taiwan_index_minute_snapshots(
                self.db,
                payload={
                    "as_of": event_time,
                    "indices": [
                        {
                            "index_id": "TAIEX",
                            "market": "TWSE",
                            "close": close,
                            "previous_close": 22_900,
                            "source": "twse_mis",
                            "as_of": event_time,
                        }
                    ],
                },
                now=event_time,
            )

        payload = read_taiwan_index_minute_series(
            self.db,
            index_id="TAIEX",
        )

        self.assertEqual(payload["point_count"], 2)
        self.assertTrue(payload["synthetic"])
        self.assertFalse(payload["indicator_eligible"])
        self.assertEqual(payload["interval_status"], "synthetic_partial")
        self.assertEqual(payload["points"][0]["open"], 23_000)
        self.assertEqual(payload["points"][0]["high"], 23_010)
        self.assertEqual(payload["points"][0]["close"], 23_010)
        self.assertEqual(payload["points"][0]["source_point_count"], 2)

    def test_query_plan_infers_intraday_ranking_and_hot_groups(self) -> None:
        ranking_plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question="台股盤中 5 分鐘急拉排行前 12 名",
                contract_version="omi.decision.v4",
                target={"type": "market", "market": "TW"},
                mode="data_only",
                output="evidence_only",
            ),
            scope_type="market",
            question_intent="general",
            effective_mode="data_only",
            target_market="TW",
        )
        group_plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question="現在台股熱門族群前 8 名",
                contract_version="omi.decision.v4",
                target={"type": "market", "market": "TW"},
                mode="data_only",
                output="evidence_only",
            ),
            scope_type="market",
            question_intent="general",
            effective_mode="data_only",
            target_market="TW",
        )

        self.assertIn("screening.intraday", ranking_plan.selected_capabilities)
        self.assertEqual(
            ranking_plan.selection["parameters"]["screening.intraday"],
            {
                "metric": "five_minute_return",
                "sort_order": "desc",
                "limit": 12,
                "offset": 0,
            },
        )
        self.assertIn("market.hot_groups", group_plan.selected_capabilities)
        self.assertEqual(
            group_plan.selection["parameters"]["market.hot_groups"]["limit"],
            8,
        )

    def test_public_capability_projection_exposes_intraday_and_hot_groups(
        self,
    ) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="台積電",
                market="TWSE",
                instrument_type="stock",
                industry="半導體業",
                is_active=True,
            )
        )
        self.db.commit()
        event_time = datetime(2026, 7, 30, 10, 5, tzinfo=TAIWAN_TZ)
        persist_taiwan_intraday_stock_states(
            self.db,
            rows=[
                self._stock_state_row(
                    "2330",
                    "TWSE",
                    1_200,
                    1_180,
                    event_time,
                )
            ],
            now=event_time,
        )
        context = read_tw_screening_context(
            self.db,
            market_data_params={
                "requested_capabilities": [
                    "screening.intraday",
                    "market.hot_groups",
                    "market.sectors",
                ],
                "capability_parameters": {
                    "screening.intraday": {
                        "metric": "change_pct",
                        "limit": 10,
                    },
                    "market.hot_groups": {"limit": 10},
                },
            },
            now=lambda: event_time,
        )
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "screening.intraday",
                    "market.hot_groups",
                    "market.sectors",
                ]
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="market",
            target_market="TW",
            question_intent="general",
        )

        projected, unavailable = capability_contract.project_selected_data(
            response={
                "target": {"type": "market", "market": "TW"},
                "result": {"data": context["data"]},
                "freshness": context["freshness"],
            },
            selection=selection,
        )

        self.assertEqual(unavailable, [])
        self.assertEqual(
            projected["screening.intraday"]["rows"][0]["stock_id"],
            "2330",
        )
        self.assertEqual(
            projected["market.hot_groups"]["groups"][0]["group_name"],
            "半導體業",
        )
        self.assertFalse(
            projected["market.hot_groups"]["membership_provenance"][
                "inferred_by_llm"
            ]
        )
        sector = projected["market.sectors"]
        hot_groups = projected["market.hot_groups"]
        self.assertTrue(
            {
                "expected_observation_date",
                "latest_completed_trade_date",
                "session_phase",
                "session_semantics",
                "freshness_status",
                "facts_usable",
                "decision_usable",
                "current_for_requested_session",
                "is_complete",
            }.issubset(hot_groups)
        )
        self.assertEqual(sector["data_mode"], "intraday_rolling_state")
        self.assertTrue(sector["is_intraday"])
        self.assertEqual(sector["items"][0]["name"], "半導體業")
        self.assertEqual(sector["snapshot_id"], hot_groups["snapshot_id"])
        self.assertEqual(
            sector["observed_trade_date"],
            hot_groups["observed_trade_date"],
        )

    def test_explicit_watchlist_name_and_default_alias_resolve_to_group_id(
        self,
    ) -> None:
        default_group = WatchlistGroup(
            group_name="核心持股",
            sort_order=1,
            is_active=True,
        )
        second_group = WatchlistGroup(
            group_name="觀察名單",
            sort_order=2,
            is_active=True,
        )
        self.db.add_all([default_group, second_group])
        self.db.commit()

        named = scope_resolution._resolve_scope(
            self.db,
            AiAskRequest(
                question="分析核心持股",
                target={"type": "tw_watchlist", "id": "核心持股"},
            ),
        )
        defaulted = scope_resolution._resolve_scope(
            self.db,
            AiAskRequest(
                question="分析預設群組",
                target={"type": "tw_watchlist", "id": "預設群組"},
            ),
        )

        self.assertEqual(named.selected_scope_id, str(default_group.id))
        self.assertEqual(named.display_name, "核心持股")
        self.assertEqual(defaulted.selected_scope_id, str(default_group.id))
        self.assertEqual(defaulted.source, "default_watchlist_group_alias")

    def test_stale_intraday_state_remains_factual_but_not_decision_usable(
        self,
    ) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
                is_active=True,
            )
        )
        self.db.commit()
        event_time = datetime(2026, 8, 28, 12, 6, tzinfo=TAIWAN_TZ)
        checked_at = datetime(2026, 8, 28, 12, 11, tzinfo=TAIWAN_TZ)

        persist_taiwan_intraday_stock_states(
            self.db,
            rows=[
                self._stock_state_row(
                    "2330",
                    "TWSE",
                    605,
                    600,
                    event_time,
                )
            ],
            now=checked_at,
        )
        ranking = build_tw_intraday_screening_snapshot(
            self.db,
            parameters={"metric": "change_pct", "limit": 20},
            generated_at=checked_at,
        )

        self.assertEqual([row["stock_id"] for row in ranking["rows"]], ["2330"])
        self.assertEqual(ranking["freshness_status"], "delayed")
        self.assertTrue(ranking["facts_usable"])
        self.assertFalse(ranking["decision_usable"])
        self.assertEqual(ranking["pagination"]["total_eligible_count"], 1)

    def _persist_ranking_universe(self, prices: dict[str, float], now: datetime) -> None:
        self.db.add_all([
            StockMaster(stock_id=stock_id, stock_name=stock_id, market="TWSE",
                        instrument_type="stock", industry="半導體業", is_active=True)
            for stock_id in prices
        ])
        self.db.commit()
        persist_taiwan_intraday_stock_states(
            self.db, now=now,
            rows=[self._stock_state_row(stock_id, "TWSE", price, 100, now)
                  for stock_id, price in prices.items()],
        )

    def test_ranking_eligibility_precedes_sort_and_pagination(self) -> None:
        now = datetime(2026, 9, 15, 10, 14, tzinfo=TAIWAN_TZ)
        self._persist_ranking_universe({"2330": 140, "2454": 130, "3711": 102, "2303": 101}, now)
        for stock_id, minutes in (("2330", 60), ("2454", 8)):
            state = self.db.query(TaiwanIntradayStockState).filter_by(stock_id=stock_id).one()
            state.price_as_of = now - timedelta(minutes=minutes)
            state.decision_usable = True  # Old persisted readiness must be rechecked on read.
        self.db.commit()
        with patch.object(self.db, "commit", side_effect=AssertionError("read wrote")):
            first = build_tw_intraday_screening_snapshot(self.db, parameters={"limit": 1}, generated_at=now)
            second = build_tw_intraday_screening_snapshot(self.db, parameters={"limit": 1, "offset": 1}, generated_at=now)
        self.assertEqual(first["rows"][0]["stock_id"], "2330")
        self.assertEqual(second["rows"][0]["stock_id"], "2454")
        self.assertEqual(second["rows"][0]["rank"], 2)
        self.assertEqual(first["pagination"]["total_eligible_count"], 4)
        self.assertEqual(first["coverage"]["ranking_excluded_count"], 0)
        self.assertFalse(first["rows"][0]["decision_usable"])
        self.assertFalse(second["rows"][0]["intraday_research_usable"])

    def test_groups_keep_stale_day_facts_but_exclude_stale_rolling_metrics(self) -> None:
        now = datetime(2026, 9, 15, 10, 14, tzinfo=TAIWAN_TZ)
        self._persist_ranking_universe({"2330": 190, "2454": 101, "3711": 102, "2303": 103}, now)
        stale = self.db.query(TaiwanIntradayStockState).filter_by(stock_id="2330").one()
        stale.price_as_of = now - timedelta(hours=1)
        stale.five_minute_return = stale.fifteen_minute_return = 999
        stale.estimated_trade_value = 999_000_000
        self.db.commit()
        result = build_tw_intraday_group_snapshots(self.db, generated_at=now)
        group = result["hot_groups"]["groups"][0]
        sector = result["sectors"]["items"][0]
        self.assertEqual(group["member_count"], 4)
        self.assertEqual(group["factual_count"], 4)
        self.assertEqual(group["observed_count"], 4)
        self.assertEqual(group["ranking_excluded_count"], 0)
        self.assertTrue(group["ranking_eligible"])
        self.assertAlmostEqual(group["mean_return_pct"], 24)
        self.assertAlmostEqual(group["median_return_pct"], 2.5)
        self.assertAlmostEqual(sector["change_pct"], 24)
        self.assertEqual(group["estimated_trade_value"], 1_029_600_000)
        self.assertEqual(group["stale_member_count"], 1)
        self.assertEqual(group["observation_freshness"], "stale")
        self.assertFalse(group["intraday_research_usable"])
        self.assertFalse(group["decision_usable"])
        self.assertIsNone(group["median_five_minute_return"])
        self.assertIsNone(group["median_fifteen_minute_return"])
        stale.price_as_of = now
        stale.lineage_complete = False
        self.db.commit()
        self.assertEqual(build_tw_intraday_group_snapshots(self.db, generated_at=now)["hot_groups"]["groups"][0]["observed_count"], 3)

    def test_sparse_reference_is_null_on_read_even_for_old_persisted_metrics(self) -> None:
        now = datetime(2026, 9, 15, 10, 14, tzinfo=TAIWAN_TZ)
        self._persist_ranking_universe({"2330": 110}, now)
        state = self.db.query(TaiwanIntradayStockState).one()
        state.samples_json = json.dumps([{"time": (now - timedelta(minutes=60)).isoformat(), "price": 100}])
        state.five_minute_return = state.fifteen_minute_return = 10
        self.db.commit()
        for metric in ("five_minute_return", "fifteen_minute_return"):
            ranked = build_tw_intraday_screening_snapshot(self.db, parameters={"metric": metric}, generated_at=now)
            self.assertEqual(ranked["rows"], [])
            self.assertEqual(ranked["reason_code"], "INTRADAY_METRIC_INSUFFICIENT_DATA")
        row = build_tw_intraday_screening_snapshot(self.db, generated_at=now)["rows"][0]
        self.assertIsNone(row["five_minute_return"])
        self.assertIsNone(row["fifteen_minute_return"])
        self.assertEqual(row["five_minute_return_status"], "insufficient_data")

    def test_rolling_reference_tolerance_and_actual_trade_clock(self) -> None:
        from app.market.tw_intraday_state import _rolling_reference
        now = datetime(2026, 9, 15, 10, 14, tzinfo=TAIWAN_TZ)
        for minutes in (5, 15):
            target = now - timedelta(minutes=minutes)
            for seconds, accepted in ((0, True), (90, True), (91, False), (1200, False)):
                with self.subTest(minutes=minutes, gap=seconds):
                    stamp = target - timedelta(seconds=seconds)
                    samples = [{"time": target.isoformat(), "price_as_of": stamp.isoformat(), "price": 100}]
                    self.assertEqual(_rolling_reference(samples, current_time=now, minutes=minutes) is not None, accepted)
            self.assertIsNone(_rolling_reference(
                [{"time": (target + timedelta(seconds=1)).isoformat(), "price": 100}],
                current_time=now, minutes=minutes,
            ))

    def test_vwap_is_unavailable_and_depth_metric_is_unsupported(self) -> None:
        from app.market.tw_intraday_state import SUPPORTED_INTRADAY_METRICS
        now = datetime(2026, 9, 15, 10, 14, tzinfo=TAIWAN_TZ)
        self._persist_ranking_universe({"2330": 110}, now)
        state = self.db.query(TaiwanIntradayStockState).one()
        self.assertIsNone(state.vwap_estimate)
        self.assertIsNone(state.vwap_deviation_pct)
        state.vwap_estimate, state.vwap_deviation_pct, state.order_book_imbalance = 105, 4.76, 0.8
        state.calculation_version = "tw.stock.intraday.state.derived.v2"
        self.db.commit()
        row = build_tw_intraday_screening_snapshot(self.db, generated_at=now)["rows"][0]
        self.assertIsNone(row["vwap_deviation_pct"])
        self.assertIsNone(row["order_book_imbalance"])
        for metric, status in (("vwap_deviation_pct", "unavailable"), ("order_book_imbalance", "unsupported")):
            result = build_tw_intraday_screening_snapshot(self.db, parameters={"metric": metric}, generated_at=now)
            self.assertEqual(result["status"], status)
            self.assertEqual(result["rows"], [])
            self.assertIsNotNone(result["reason_code"])
            self.assertFalse(result["facts_usable_for_ranking"])
        self.assertNotIn("order_book_imbalance", SUPPORTED_INTRADAY_METRICS)
        self.assertEqual(result["missing"], [])
        context = read_tw_screening_context(
            self.db, now=lambda: now,
            market_data_params={
                "requested_capabilities": ["screening.intraday"],
                "capability_parameters": {"screening.intraday": {"metric": "order_book_imbalance"}},
            },
        )
        selection = capability_contract.normalize_selection(
            selection={"include": ["screening.intraday"]}, output="evidence_only",
            realtime_policy="cache_only", payload_level="compact", scope_type="market",
            target_market="TW", question_intent="general",
        )
        projected, _ = capability_contract.project_selected_data(
            response={"target": {"type": "market", "market": "TW"},
                      "result": {"data": context["data"]}, "freshness": context["freshness"]},
            selection=selection,
        )
        self.assertEqual(projected["screening.intraday"]["status"], "unsupported")
        self.assertEqual(projected["screening.intraday"]["reason_code"], "FULL_MARKET_DEPTH_PRODUCER_UNSUPPORTED")
        self.assertFalse(projected["screening.intraday"].get("facts_usable", False))
        persist_taiwan_intraday_stock_states(self.db, rows=[self._stock_state_row("2330", "TWSE", 110, 100, now)], now=now)
        self.assertIsNone(state.vwap_estimate)
        self.assertIsNone(state.vwap_deviation_pct)

    def test_ordinary_universe_and_bounded_denominator_share_breadth_owner(self) -> None:
        from app.market.tw_current_market_operations import TaiwanRegisteredStockUniverseReader
        from app.market.tw_universe import list_taiwan_stock_ids
        now = datetime(2026, 9, 15, 10, 14, tzinfo=TAIWAN_TZ)
        self._persist_ranking_universe({"2330": 110, "2454": 101, "020001": 102, "2881A": 103}, now)
        self.assertEqual(TaiwanRegisteredStockUniverseReader(self.db)("TWSE"), ["2330", "2454"])
        self.assertEqual(list_taiwan_stock_ids(self.db), ["2330", "2454"])
        bounded = build_tw_intraday_screening_snapshot(self.db, parameters={"universe": {"stock_ids": ["2330", "2330"], "markets": ["TWSE"]}}, generated_at=now)
        self.assertEqual(bounded["coverage"]["universe_count"], 1)
        self.assertEqual(bounded["coverage"]["coverage_ratio"], 1)
        self.assertEqual(bounded["coverage"]["requested_stock_count"], 1)
        full = build_tw_intraday_screening_snapshot(self.db, generated_at=now)
        groups = build_tw_intraday_group_snapshots(self.db, generated_at=now)
        self.assertEqual(full["coverage"]["universe_count"], 2)
        self.assertEqual(groups["hot_groups"]["coverage"]["universe_count"], 2)
        self.assertEqual(groups["sectors"]["items"][0]["member_count"], 2)

    def test_future_or_missing_trade_clock_and_incomplete_lineage_cannot_rank(self) -> None:
        now = datetime(2026, 9, 15, 10, 14, tzinfo=TAIWAN_TZ)
        self._persist_ranking_universe({"2330": 110}, now)
        state = self.db.query(TaiwanIntradayStockState).one()
        for price_at, receipt_at, lineage in (
            (now + timedelta(seconds=1), now, True),
            (now, now + timedelta(seconds=1), True),
            (None, now, True),
            (now, now, False),
        ):
            state.price_as_of, state.snapshot_as_of, state.lineage_complete = price_at, receipt_at, lineage
            state.decision_usable = True
            self.db.commit()
            self.assertEqual(build_tw_intraday_screening_snapshot(self.db, generated_at=now)["rows"], [])
            group = build_tw_intraday_group_snapshots(self.db, generated_at=now)["hot_groups"]["groups"][0]
            self.assertIsNone(group["mean_return_pct"])
            self.assertIsNone(group["estimated_trade_value"])
            self.assertFalse(group["ranking_eligible"])

    def test_latest_unclassified_state_does_not_resurrect_an_older_provider_for_ranking(self) -> None:
        now = datetime(2026, 9, 15, 10, 14, tzinfo=TAIWAN_TZ)
        self._persist_ranking_universe({"2330": 110}, now - timedelta(seconds=30))
        latest = self._stock_state_row("2330", "TWSE", 110, 100, now)
        latest.update(provider="other_provider", has_actual_trade=False, current_price=None)
        persist_taiwan_intraday_stock_states(self.db, rows=[latest], now=now)
        self.assertEqual(build_tw_intraday_screening_snapshot(self.db, generated_at=now)["rows"], [])
        group = build_tw_intraday_group_snapshots(self.db, generated_at=now)["hot_groups"]["groups"][0]
        self.assertEqual(group["observed_count"], 0)

    @staticmethod
    def _stock_state_row(
        stock_id: str,
        market: str,
        current_price: float,
        previous_close: float,
        event_time: datetime,
    ) -> dict:
        return {
            "code": stock_id,
            "market": market,
            "trade_date": event_time.date(),
            "as_of": event_time,
            "current_price": current_price,
            "previous_close": previous_close,
            "open_price": previous_close,
            "high_price": max(current_price, previous_close),
            "low_price": min(current_price, previous_close),
            "cumulative_volume_lots": 100,
            "estimated_trade_value": int(current_price * 100 * 1_000),
            "provider": "twse_mis",
            "source": f"twse_mis_{market.lower()}_registered_universe",
            "raw_result_id": f"raw_fetch_result:{market}:{stock_id}",
            "component_raw_result_ids": [
                f"raw_fetch_result:{market}:{stock_id}"
            ],
            "component_sources": [
                {
                    "domain": "stock_quote_snapshot",
                    "provider": "twse_mis",
                    "source": f"twse_mis_{market.lower()}_registered_universe",
                    "raw_result_id": f"raw_fetch_result:{market}:{stock_id}",
                    "event_at": event_time.isoformat(),
                }
            ],
        }

    @staticmethod
    def _market_minute_row(
        *,
        market: str,
        index_id: str,
        minute_at: datetime,
        trade_value: int,
        trade_value_quality: str,
        estimated: bool,
    ) -> TaiwanMarketMinuteState:
        return TaiwanMarketMinuteState(
            market=market,
            index_id=index_id,
            trade_date=minute_at.date(),
            minute_at=minute_at,
            session_status="open",
            quote_quality_status="ready",
            breadth_status="missing",
            breadth_scope="registered_universe",
            trade_value_quality_status=trade_value_quality,
            quality_status="partial",
            index_value=23_000 if market == "TWSE" else 250,
            cumulative_trade_value=trade_value,
            trade_value_semantics=(
                "estimated_latest_price_x_cumulative_volume_lots"
                if estimated
                else "official_exchange_cumulative_trade_value"
            ),
            trade_value_confidence="medium" if estimated else "high",
            trade_value_is_estimate=estimated,
            source="test",
            source_category="test",
            official_flag=not estimated,
            derived_flag=estimated,
            component_raw_result_ids_json='["raw_fetch_result:test"]',
            component_sources_json=(
                '[{"domain":"index_snapshot","owns_trade_value":true,"provider":"test",'
                '"source":"test","raw_result_id":"raw_fetch_result:test",'
                f'"event_at":"{minute_at.isoformat()}"}}]'
            ),
            component_event_times_json=f'["{minute_at.isoformat()}"]',
            component_time_skew_seconds=0,
            calculation_version="tw.market.minute_state.derived.v2",
            lineage_complete=True,
        )


if __name__ == "__main__":
    unittest.main()
