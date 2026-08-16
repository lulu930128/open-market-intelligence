from __future__ import annotations

from datetime import date, datetime
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster, WatchlistGroup, WatchlistItem
from app.main import app
from app.market import indices
from app.market.trading_calendar import TAIWAN_TZ
from app.market.taiwan_industries import normalize_tw_industry_label
from app.market.tw_intraday_state import persist_taiwan_intraday_stock_states
from app.market.tw_market_dashboard import (
    build_dashboard_moving_average_series,
    build_tw_dashboard_stock_detail,
    build_tw_market_dashboard,
    estimate_cap_weighted_index,
    search_tw_dashboard_symbols,
)
from app.market.tw_market_dashboard_schemas import (
    TaiwanDashboardStockDetailRead,
    TaiwanMarketDashboardRead,
)


class TaiwanMarketDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _seed_preopen_state(self) -> int:
        stocks = [
            StockMaster(
                stock_id="1101",
                stock_name="Cement A",
                market="TWSE",
                instrument_type="stock",
                industry="24",
                is_active=True,
            ),
            StockMaster(
                stock_id="2303",
                stock_name="Chip B",
                market="TWSE",
                instrument_type="stock",
                industry="24",
                is_active=True,
            ),
            StockMaster(
                stock_id="2330",
                stock_name="Chip C",
                market="TWSE",
                instrument_type="stock",
                industry="24",
                is_active=True,
            ),
            StockMaster(
                stock_id="6488",
                stock_name="OTC A",
                market="TPEX",
                instrument_type="stock",
                industry="Electronics",
                is_active=True,
            ),
            StockMaster(
                stock_id="8299",
                stock_name="OTC B",
                market="TPEX",
                instrument_type="stock",
                industry="Electronics",
                is_active=True,
            ),
        ]
        self.db.add_all(stocks)
        group = WatchlistGroup(
            group_name="Core",
            sort_order=1,
            is_active=True,
        )
        self.db.add(group)
        self.db.flush()
        self.db.add_all(
            [
                WatchlistItem(
                    group_id=group.id,
                    stock_id="2330",
                    priority=1,
                    enabled=True,
                ),
                WatchlistItem(
                    group_id=group.id,
                    stock_id="6488",
                    priority=2,
                    enabled=True,
                ),
            ]
        )
        self.db.commit()

        observed_at = datetime(2026, 8, 14, 8, 35, tzinfo=TAIWAN_TZ)
        rows = [
            ("TWSE", "1101", 100.0, 101.0),
            ("TWSE", "2303", 100.0, 102.0),
            ("TWSE", "2330", 100.0, 99.0),
            ("TPEX", "6488", 50.0, 51.0),
        ]
        persist_taiwan_intraday_stock_states(
            self.db,
            rows=[
                {
                    "provider": "twse_mis",
                    "market": market,
                    "code": stock_id,
                    "trade_date": date(2026, 8, 14),
                    "as_of": observed_at,
                    "snapshot_as_of": observed_at,
                    "previous_close": previous_close,
                    "current_price": None,
                    "has_actual_trade": False,
                    "indicative_match_available": True,
                    "indicative_match_price": indicative_price,
                    "indicative_match_volume_lots": 10,
                    "market_session": "preopen",
                    "price_semantics": "auction_indicative",
                }
                for market, stock_id, previous_close, indicative_price in rows
            ],
            now=observed_at,
        )
        return int(group.id)

    def test_preopen_dashboard_is_cache_only_and_preserves_breadth_invariants(
        self,
    ) -> None:
        group_id = self._seed_preopen_state()
        now = datetime(2026, 8, 14, 8, 35, 30, tzinfo=TAIWAN_TZ)

        with patch.object(
            indices,
            "_fetch_twse_mis_live_market_breadth",
        ) as provider_fetch:
            payload = build_tw_market_dashboard(
                self.db,
                watchlist_group_id=group_id,
                now=now,
            )

        provider_fetch.assert_not_called()
        TaiwanMarketDashboardRead.model_validate(payload)
        self.assertEqual(payload["version"], "omi.tw_market_dashboard.v1")
        self.assertEqual(payload["session"]["phase"], "preopen")
        self.assertTrue(payload["freshness"]["cache_only"])
        self.assertGreater(payload["state_version"], 0)

        twse = payload["breadth"]["TWSE"]
        self.assertEqual(twse["universe"], 3)
        self.assertEqual(twse["coverage"], 3)
        self.assertEqual(twse["advance"], 2)
        self.assertEqual(twse["decline"], 1)
        self.assertEqual(
            twse["advance"] + twse["decline"] + twse["unchanged"],
            twse["coverage"],
        )
        self.assertEqual(twse["coverage"] + twse["unknown"], twse["universe"])
        self.assertFalse(twse["decision_usable"])

        tpex = payload["breadth"]["TPEX"]
        self.assertEqual(tpex["coverage"], 1)
        self.assertEqual(tpex["unknown"], 1)
        self.assertEqual(tpex["status"], "partial")

        self.assertEqual(payload["hot_groups"][0]["group_id"], "TWSE:24")
        self.assertEqual(payload["hot_groups"][0]["group_key"], "24")
        self.assertEqual(payload["hot_groups"][0]["label"], "半導體業")
        self.assertEqual(payload["hot_groups"][0]["coverage"], 3)
        self.assertFalse(payload["hot_groups"][0]["decision_usable"])
        self.assertEqual(
            payload["watchlist"]["selection"]["selection_policy"],
            "explicit_group_id",
        )
        self.assertEqual(len(payload["watchlist"]["items"]), 2)
        self.assertEqual(
            payload["watchlist"]["groups"],
            [
                {
                    "group_id": group_id,
                    "group_name": "Core",
                    "parent_id": None,
                    "sort_order": 1,
                }
            ],
        )
        self.assertTrue(all(not item["official"] for item in payload["indices"]))
        self.assertTrue(
            all(not item["decision_usable"] for item in payload["indices"])
        )

    def test_preopen_pending_does_not_reuse_indicative_rows_as_observed(self) -> None:
        self._seed_preopen_state()
        payload = build_tw_market_dashboard(
            self.db,
            now=datetime(2026, 8, 14, 8, 0, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(payload["session"]["phase"], "preopen_pending")
        self.assertGreater(payload["state_version"], 0)
        self.assertEqual(payload["breadth"]["TWSE"]["status"], "not_observed")
        self.assertEqual(payload["breadth"]["TWSE"]["coverage"], 0)
        self.assertEqual(payload["breadth"]["TWSE"]["unknown"], 3)

    def test_watchlist_group_metadata_is_active_and_hierarchy_aware(self) -> None:
        selected_group_id = self._seed_preopen_state()
        secondary = WatchlistGroup(
            group_name="Secondary",
            sort_order=2,
            is_active=True,
        )
        hidden = WatchlistGroup(
            group_name="Hidden",
            sort_order=3,
            is_active=False,
        )
        self.db.add_all([secondary, hidden])
        self.db.flush()
        child = WatchlistGroup(
            group_name="Child",
            parent_id=secondary.id,
            sort_order=1,
            is_active=True,
        )
        self.db.add(child)
        self.db.commit()

        payload = build_tw_market_dashboard(
            self.db,
            watchlist_group_id=selected_group_id,
            now=datetime(2026, 8, 14, 8, 35, 30, tzinfo=TAIWAN_TZ),
        )

        groups = payload["watchlist"]["groups"]
        self.assertEqual(
            [group["group_name"] for group in groups],
            ["Core", "Secondary", "Child"],
        )
        self.assertEqual(groups[-1]["parent_id"], secondary.id)
        self.assertNotIn("Hidden", {group["group_name"] for group in groups})

    def test_unknown_industry_code_has_truthful_display_fallback(self) -> None:
        self.assertEqual(normalize_tw_industry_label("99"), "產業代碼 99")
        self.assertEqual(
            normalize_tw_industry_label("Semiconductor"),
            "Semiconductor",
        )

    def test_index_estimate_keeps_unobserved_weight_in_denominator(self) -> None:
        result = estimate_cap_weighted_index(
            baseline_close=100.0,
            components=[
                {
                    "shares": 100.0,
                    "reference_price": 100.0,
                    "observed_price": 110.0,
                },
                {
                    "shares": 100.0,
                    "reference_price": 100.0,
                    "observed_price": None,
                },
            ],
        )

        self.assertTrue(result["estimate_available"])
        self.assertAlmostEqual(result["estimate"], 105.0)
        self.assertAlmostEqual(result["change_pct"], 5.0)
        self.assertAlmostEqual(result["observed_weight"], 0.5)
        self.assertAlmostEqual(result["uncovered_weight"], 0.5)

    def test_index_estimate_fails_closed_when_component_data_is_too_sparse(
        self,
    ) -> None:
        result = estimate_cap_weighted_index(
            baseline_close=100.0,
            components=[
                {"shares": 100, "reference_price": 100, "observed_price": 101},
                {"shares": 100, "reference_price": 100, "observed_price": 101},
                {"shares": 100, "reference_price": 100, "observed_price": 101},
                {"shares": None, "reference_price": 100, "observed_price": 101},
            ],
        )

        self.assertFalse(result["estimate_available"])
        self.assertIsNone(result["estimate"])
        self.assertAlmostEqual(result["component_data_coverage_ratio"], 0.75)

    def test_symbol_search_is_bounded_and_prefers_exact_symbol(self) -> None:
        self._seed_preopen_state()

        payload = search_tw_dashboard_symbols(
            self.db,
            keyword="2330",
            limit=2,
        )

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["stock_id"], "2330")
        self.assertLessEqual(payload["count"], payload["limit"])

    def test_stock_detail_is_cache_only_and_does_not_backfill(self) -> None:
        self._seed_preopen_state()

        with patch(
            "app.market.service._ensure_stock_history"
        ) as ensure_history:
            payload = build_tw_dashboard_stock_detail(
                self.db,
                stock_id="2330",
                timeframe="daily",
                bars=90,
            )

        ensure_history.assert_not_called()
        TaiwanDashboardStockDetailRead.model_validate(payload)
        self.assertTrue(payload["cache_only"])
        self.assertEqual(payload["stock_id"], "2330")
        self.assertIsNone(payload["chart"]["backfill"])
        self.assertEqual(payload["chart"]["point_count"], 1)
        self.assertIsNotNone(payload["chart"]["intraday_overlay"])
        self.assertEqual(len(payload["moving_averages"]), 1)
        self.assertIsNone(payload["moving_averages"][0]["ma5"])
        self.assertEqual(payload["technical"]["stock_id"], "2330")

    def test_stock_detail_moving_averages_are_backend_computed(self) -> None:
        points = [
            {"time": date(2026, 8, day), "close": float(day)}
            for day in range(1, 21)
        ]

        series = build_dashboard_moving_average_series(points)

        self.assertIsNone(series[3]["ma5"])
        self.assertEqual(series[4]["ma5"], 3.0)
        self.assertEqual(series[-1]["ma5"], 18.0)
        self.assertEqual(series[-1]["ma20"], 10.5)
        self.assertIsNone(series[-1]["ma60"])

    def test_routes_are_registered_under_focused_market_prefix(self) -> None:
        paths = {route.path for route in app.routes}

        self.assertIn("/api/market/tw-dashboard/snapshot", paths)
        self.assertIn("/api/market/tw-dashboard/symbols/search", paths)
        self.assertIn("/api/market/tw-dashboard/stocks/{stock_id}", paths)

    def test_live_refresh_window_starts_at_canonical_preopen_time(self) -> None:
        before = datetime(2026, 8, 14, 8, 29, 59, tzinfo=TAIWAN_TZ)
        start = datetime(2026, 8, 14, 8, 30, tzinfo=TAIWAN_TZ)

        self.assertFalse(indices.is_taiwan_index_live_refresh_window(before))
        self.assertTrue(indices.is_taiwan_index_live_refresh_window(start))
        self.assertEqual(indices._market_breadth_target_date(start), start.date())


if __name__ == "__main__":
    unittest.main()
