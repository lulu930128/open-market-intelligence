from __future__ import annotations

from datetime import date, datetime
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
    TaiwanMarketMinuteState,
    WatchlistGroup,
    WatchlistItem,
)
from app.market import indices
from app.market.providers import twse_mis
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
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        indices.reset_twse_mis_breadth_guard()

    def tearDown(self) -> None:
        indices.reset_twse_mis_breadth_guard()
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

        with (
            patch.object(
                indices,
                "_twse_mis_live_breadth_stock_codes",
                return_value=codes,
            ),
            patch.object(
                indices,
                "_fetch_twse_mis_stock_messages",
                return_value=(messages, 0),
            ) as fetch_messages,
        ):
            payload = indices._fetch_twse_mis_live_market_breadth_unguarded(
                self.db,
                "TPEX",
            )

        self.assertIsNotNone(payload)
        assert payload is not None
        fetch_messages.assert_called_once_with(codes, "TPEX")
        self.assertEqual(payload["market"], "TPEX")
        self.assertEqual(payload["scope"], "registered_universe")
        self.assertEqual(payload["advance_count"], 125)
        self.assertEqual(payload["decline_count"], 125)
        self.assertEqual(payload["unknown_count"], 0)
        self.assertTrue(payload["trade_value_is_estimate"])
        self.assertEqual(
            payload["trade_value_semantics"],
            "estimated_latest_price_x_cumulative_volume_lots",
        )
        cached = indices.get_cached_taiwan_intraday_stock_rows("TPEX")
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
                str(item["sector_id"]).startswith("industry:")
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

    def test_legacy_unknown_trade_value_quality_remains_backward_compatible(
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

        self.assertEqual(payload["current_cumulative_trade_value"], 1_300)
        self.assertEqual(payload["trade_value_coverage_status"], "complete")
        self.assertEqual(payload["trade_value_authority_status"], "official")
        self.assertEqual(payload["trade_value_status"], "official_complete")

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
        )


if __name__ == "__main__":
    unittest.main()
