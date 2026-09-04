from __future__ import annotations

from datetime import date, datetime
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster, WatchlistGroup, WatchlistItem
from app.main import app
from app.market import indices
from app.market.index_resolution import resolve_taiwan_index_truth
from app.market.trading_calendar import TAIWAN_TZ
from app.market.taiwan_industries import normalize_tw_industry_label
from app.market.tw_intraday_state import persist_taiwan_intraday_stock_states
from app.market.tw_market_dashboard import (
    _freshness_status,
    build_dashboard_moving_average_series,
    _dashboard_intraday_chart,
    _dashboard_previous_close,
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

    def test_freshness_respects_regular_session_producer_cadence(self) -> None:
        observed_at = datetime(2026, 8, 31, 10, 0, tzinfo=TAIWAN_TZ)

        within_cycle = _freshness_status(
            observed_at,
            now=datetime(2026, 8, 31, 10, 4, 59, tzinfo=TAIWAN_TZ),
            evidence_trade_date=date(2026, 8, 31),
            expected_trade_date=date(2026, 8, 31),
            presentation_state="observing",
            completed_session_evidence=False,
            producer_cadence_seconds=300,
        )
        outside_cycle = _freshness_status(
            observed_at,
            now=datetime(2026, 8, 31, 10, 6, 1, tzinfo=TAIWAN_TZ),
            evidence_trade_date=date(2026, 8, 31),
            expected_trade_date=date(2026, 8, 31),
            presentation_state="observing",
            completed_session_evidence=False,
            producer_cadence_seconds=300,
        )

        self.assertEqual(within_cycle, ("current", 299))
        self.assertEqual(outside_cycle, ("delayed", 361))

    def test_freshness_preserves_completed_session_and_rejects_wrong_date(self) -> None:
        close_at = datetime(2026, 8, 31, 13, 30, tzinfo=TAIWAN_TZ)
        checked_at = datetime(2026, 8, 31, 23, 40, tzinfo=TAIWAN_TZ)

        completed = _freshness_status(
            close_at,
            now=checked_at,
            evidence_trade_date=date(2026, 8, 31),
            expected_trade_date=date(2026, 8, 31),
            presentation_state="completed",
            completed_session_evidence=True,
            producer_cadence_seconds=300,
        )
        wrong_date = _freshness_status(
            close_at,
            now=datetime(2026, 9, 1, 10, 0, tzinfo=TAIWAN_TZ),
            evidence_trade_date=date(2026, 8, 31),
            expected_trade_date=date(2026, 9, 1),
            presentation_state="observing",
            completed_session_evidence=True,
            producer_cadence_seconds=300,
        )

        self.assertEqual(completed[0], "latest_completed_session")
        self.assertEqual(wrong_date[0], "stale")

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

    def test_post_close_dashboard_uses_completed_session_freshness(self) -> None:
        close_at = datetime(2026, 8, 31, 13, 30, tzinfo=TAIWAN_TZ)
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
                industry="24",
                is_active=True,
            )
        )
        self.db.commit()
        persist_taiwan_intraday_stock_states(
            self.db,
            rows=[
                {
                    "provider": "nstock",
                    "market": "TWSE",
                    "code": "2330",
                    "trade_date": date(2026, 8, 31),
                    "as_of": close_at,
                    "snapshot_as_of": close_at,
                    "previous_close": 1180.0,
                    "current_price": 1195.0,
                    "has_actual_trade": True,
                    "indicative_match_available": False,
                    "market_session": "post_close",
                    "price_semantics": "last_trade",
                }
            ],
            now=close_at,
        )

        payload = build_tw_market_dashboard(
            self.db,
            now=datetime(2026, 8, 31, 23, 40, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(payload["session"]["presentation_state"], "completed")
        self.assertEqual(payload["freshness"]["status"], "latest_completed_session")
        self.assertEqual(payload["freshness"]["basis"], "completed_session_date")
        self.assertNotIn(
            "Dashboard snapshot freshness is stale.",
            payload["warnings"],
        )

    def test_preopen_dashboard_is_cache_only_and_preserves_breadth_invariants(
        self,
    ) -> None:
        group_id = self._seed_preopen_state()
        now = datetime(2026, 8, 14, 8, 35, 30, tzinfo=TAIWAN_TZ)

        with patch(
            "app.market.providers.twse_mis_current_breadth."
            "read_twse_mis_current_breadth",
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
        self.assertEqual(payload["freshness"]["basis"], "producer_cadence")
        self.assertEqual(payload["freshness"]["producer_cadence_seconds"], 300)
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
        self.assertEqual(
            tpex["coverage_reason_counts"]["state_missing"],
            1,
        )
        self.assertIsNone(
            tpex["coverage_reason_counts"]["valid_no_trade"]
        )
        self.assertEqual(
            sum(
                int(tpex["coverage_reason_counts"][key] or 0)
                for key in (
                    "state_missing",
                    "state_not_observed",
                    "reason_unknown",
                )
            ),
            tpex["unknown"],
        )

        self.assertEqual(payload["hot_groups"], [])
        self.assertTrue(
            any(
                "none are classifiable for ranking" in warning
                for warning in payload["warnings"]
            )
        )
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

    def test_dashboard_uses_existing_resolved_index_projection_as_headline(
        self,
    ) -> None:
        self._seed_preopen_state()
        truth = resolve_taiwan_index_truth(
            intraday=None,
            index_snapshot={
                "index_id": "TAIEX",
                "close": 24_321.5,
                "previous_close": 24_100.0,
                "time": "2026-08-14",
                "as_of": "2026-08-14T13:30:00+08:00",
                "source": "fugle_indices_stream",
                "provider": "fugle_marketdata",
                "completed_daily_close": 24_280.0,
                "completed_daily_trade_date": "2026-08-14",
                "completed_daily_event_time": "2026-08-14T13:30:00+08:00",
                "completed_daily_source": "twse_indices_report_mi_5mins_hist",
                "completed_daily_provider": "twse",
                "completed_daily_authority": "exchange",
                "completed_daily_finalization": "final",
                "completed_daily_official": True,
                "completed_daily_release_status": "released",
                "completed_daily_reconciliation_status": "not_applicable",
                "completed_daily_qualified": True,
                "completed_daily_previous_close": 24_100.0,
                "completed_daily_previous_close_trade_date": "2026-08-13",
                "completed_daily_previous_close_source": "twse_indices_report_mi_5mins_hist",
                "completed_daily_previous_close_provider": "twse",
                "completed_daily_previous_close_authority": "exchange",
                "completed_daily_previous_close_finalization": "final",
            },
            calendar_status={
                "timezone": "Asia/Taipei",
                "checked_at": "2026-08-14T15:00:00+08:00",
                "date": "2026-08-14",
                "is_trading_day": True,
                "phase": "post_close",
                "previous_trading_day": "2026-08-13",
            },
            index_id="TAIEX",
            acquisition_policy="cache_only",
        )
        resolved_summary = {
            "resolution_version": truth.resolution_version,
            "acquisition_policy": "cache_only",
            "warnings": [],
            "indices": [
                {
                    "index_id": "TAIEX",
                    "market": "TWSE",
                    "change": 123.4,
                    "change_pct": 0.5,
                    "acquisition_policy": "cache_only",
                    "current_data_core": {
                        "index": {
                            "status": "selected",
                            "index_id": "TAIEX",
                            "provider": "twse",
                            "source": "twse_index_5s_intraday",
                            "close": 24_321.5,
                            "change": 123.4,
                            "as_of": "2026-08-14T09:59:59+08:00",
                            "trade_date": "2026-08-14",
                            "session": "regular",
                            "provisional": True,
                            "official": True,
                            "decision_usable": True,
                            "resolved_health": {
                                "contract_version": "omi.market.resolved_evidence_health.v1",
                                "status": "selected",
                                "selected_provider": "twse",
                                "selected_source": "twse_index_5s_intraday",
                                "selection_reason": "ACTIVE_SESSION_SELECTED",
                                "facts_usable": True,
                                "research_usable": True,
                                "limitations": [],
                            },
                            "limitations": [],
                        }
                    },
                    "breadth": {
                        "market": "TWSE",
                        "status": "partial",
                        "market_session": "regular",
                        "price_semantics": "actual_trade_only",
                        "is_provisional": True,
                        "decision_usable": True,
                        "scope": "registered_universe",
                        "source": "twse_mis_live_breadth_partial",
                        "trade_date": "2026-08-14",
                        "snapshot_as_of": "2026-08-14T09:59:59+08:00",
                        "advance_count": 50,
                        "decline_count": 35,
                        "unchanged_count": 5,
                        "classified_count": 90,
                        "total_count": 100,
                        "unknown_count": 4,
                        "received_unclassified_count": 4,
                        "not_received_count": 6,
                        "missing_count": 6,
                        "failed_batch_count": 1,
                        "warnings": ["One MIS batch failed."],
                    },
                    "resolution": truth.model_dump(mode="json"),
                }
            ],
        }

        with patch(
            "app.market.tw_market_dashboard.get_market_index_summary",
            return_value=resolved_summary,
        ) as summary_read:
            payload = build_tw_market_dashboard(
                self.db,
                now=datetime(2026, 8, 14, 10, 0, tzinfo=TAIWAN_TZ),
            )

        summary_read.assert_called_once_with(self.db)
        parsed = TaiwanMarketDashboardRead.model_validate(payload)
        self.assertEqual(parsed.headline_index_field, "resolved_indices")
        self.assertEqual(parsed.headline_breadth_field, "resolved_breadth")
        legacy_breadth = parsed.breadth["TWSE"]
        self.assertTrue(legacy_breadth.deprecated)
        self.assertEqual(
            legacy_breadth.canonical_ref,
            "resolved_breadth.TWSE",
        )
        self.assertFalse(legacy_breadth.decision_usable)
        self.assertEqual(len(parsed.resolved_indices), 1)
        self.assertEqual(parsed.resolved_indices[0].value, 24_280.0)
        self.assertEqual(
            parsed.resolved_indices[0].selected_candidate,
            "completed_daily_bar",
        )
        self.assertTrue(parsed.resolved_indices[0].official)
        self.assertEqual(parsed.resolved_indices[0].provider, "twse")
        self.assertEqual(
            parsed.resolved_indices[0].authority,
            "official_exchange",
        )
        self.assertEqual(parsed.resolved_indices[0].finalization, "final")
        self.assertTrue(parsed.resolved_indices[0].official_source)
        self.assertTrue(parsed.resolved_indices[0].official_close_confirmed)
        self.assertFalse(parsed.resolved_indices[0].provisional_estimate)
        self.assertTrue(parsed.resolved_indices[0].decision_usable)
        self.assertEqual(parsed.resolved_indices[0].resolution_id, truth.resolution_id)
        self.assertEqual(parsed.resolved_indices[0].previous_close, 24_100.0)
        self.assertEqual(parsed.resolved_indices[0].change, 180.0)
        self.assertFalse(parsed.resolved_indices[0].compatibility_fallback)
        resolved_breadth = parsed.resolved_breadth["TWSE"]
        self.assertFalse(resolved_breadth.deprecated)
        self.assertIsNone(resolved_breadth.canonical_ref)
        self.assertEqual(resolved_breadth.scope, "registered_universe")
        self.assertEqual(resolved_breadth.coverage, 90)
        self.assertEqual(resolved_breadth.unknown, 10)
        self.assertEqual(
            resolved_breadth.coverage_reason_counts["not_received"],
            6,
        )
        self.assertEqual(
            resolved_breadth.coverage_reason_counts["received_unclassified"],
            4,
        )
        self.assertIsNone(
            resolved_breadth.coverage_reason_counts["provider_missing"]
        )
        self.assertTrue(all(not item.official for item in parsed.indices))

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

        payload = build_tw_dashboard_stock_detail(
            self.db,
            stock_id="2330",
            timeframe="daily",
            bars=90,
        )
        TaiwanDashboardStockDetailRead.model_validate(payload)
        self.assertTrue(payload["cache_only"])
        self.assertEqual(payload["stock_id"], "2330")
        self.assertIsNone(payload["chart"]["backfill"])
        # A current quote/state is not an intraday bar and must not be
        # synthesized into the historical chart.  With no persisted OHLCV in
        # this fixture the cache-only chart is truthfully empty.
        self.assertEqual(payload["chart"]["point_count"], 0)
        self.assertIsNone(payload["chart"]["intraday_overlay"])
        self.assertEqual(payload["moving_averages"], [])
        self.assertEqual(payload["technical"]["stock_id"], "2330")

    def test_stock_detail_accepts_etf_through_the_same_instrument_owner(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="0050",
                stock_name="元大台灣50",
                market="TWSE",
                instrument_type="ETF",
                is_active=True,
            )
        )
        self.db.commit()

        payload = build_tw_dashboard_stock_detail(
            self.db,
            stock_id="0050",
            timeframe="daily",
            bars=90,
        )

        outward = TaiwanDashboardStockDetailRead.model_validate(payload)
        self.assertEqual(outward.stock_id, "0050")
        self.assertEqual(outward.instrument_type, "etf")
        self.assertTrue(outward.cache_only)

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

    def test_stock_detail_moving_average_excludes_close_marker(self) -> None:
        points = [
            {
                "time": datetime(2026, 8, 31, 13, minute, tzinfo=TAIWAN_TZ),
                "close": float(value),
                "indicator_eligible": True,
            }
            for minute, value in zip(range(20, 25), (576, 577, 578, 579, 580))
        ]
        points.append(
            {
                "time": datetime(2026, 8, 31, 13, 30, tzinfo=TAIWAN_TZ),
                "close": 584.0,
                "bar_type": "official_close_marker",
                "indicator_eligible": False,
            }
        )

        series = build_dashboard_moving_average_series(points)

        self.assertEqual(series[-2]["ma5"], 578.0)
        self.assertEqual(series[-1]["ma5"], 578.0)

    def test_today_chart_limits_display_but_keeps_full_technical_volume_scope(self) -> None:
        cached_history = {
            "source": "market_intraday_bar_cache",
            "effective_interval": "1m",
            "points": [
                {
                    "time": f"2026-08-31T09:{minute:02d}:00+08:00",
                    "close": 100.0 + minute,
                    "volume": 1000,
                }
                for minute in range(10)
            ],
        }
        with patch(
            "app.market.tw_market_dashboard.get_market_intraday_history",
            return_value=cached_history,
        ):
            chart, technical = _dashboard_intraday_chart(
                self.db,
                stock_id="2330",
                bars=3,
            )

        self.assertEqual(chart["point_count"], 3)
        self.assertEqual(len(chart["points"]), 3)
        self.assertEqual(technical["point_count"], 10)
        self.assertEqual(len(technical["points"]), 10)

    def test_today_chart_previous_close_excludes_the_current_trade_date(self) -> None:
        points = [
            {"time": date(2026, 8, 13), "close": 98.0},
            {"time": date(2026, 8, 14), "close": 101.0},
        ]

        previous_close = _dashboard_previous_close(
            points,
            trade_date=date(2026, 8, 14),
        )

        self.assertEqual(previous_close, 98.0)

    def test_today_stock_detail_uses_latest_persisted_intraday_session(self) -> None:
        self._seed_preopen_state()
        cached_history = {
            "source": "market_intraday_bar_cache",
            "effective_interval": "1m",
            "cache_status": "persisted_hit",
            "cache_hit": True,
            "canonical_volume_unit": "shares",
            "volume_semantics": "latest_trade_date_interval_bar_sum",
            "points": [
                {
                    "time": "2026-08-13T13:30:00+08:00",
                    "open": 99.0,
                    "high": 100.0,
                    "low": 98.0,
                    "close": 99.5,
                    "volume": 1000,
                },
                {
                    "time": "2026-08-14T09:00:00+08:00",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.5,
                    "close": 100.5,
                    "volume": 2000,
                },
                {
                    "time": "2026-08-14T09:01:00+08:00",
                    "open": 100.5,
                    "high": 102.0,
                    "low": 100.0,
                    "close": 101.5,
                    "volume": 3000,
                },
            ],
        }

        with patch(
            "app.market.tw_market_dashboard.get_market_intraday_history",
            return_value=cached_history,
        ) as read_history:
            payload = build_tw_dashboard_stock_detail(
                self.db,
                stock_id="2330",
                timeframe="today",
                bars=20,
            )

        read_history.assert_called_once_with(
            db=self.db,
            stock_id="2330",
            interval="1m",
            range_value="5d",
            refresh=False,
        )
        TaiwanDashboardStockDetailRead.model_validate(payload)
        self.assertEqual(payload["version"], "omi.tw_stock_dashboard_detail.v2")
        self.assertEqual(payload["timeframe"], "today")
        self.assertEqual(payload["intraday_chart"]["trade_date"], date(2026, 8, 14))
        self.assertEqual(payload["intraday_chart"]["point_count"], 2)
        self.assertEqual(len(payload["moving_averages"]), 2)
        self.assertTrue(payload["cache_only"])

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
