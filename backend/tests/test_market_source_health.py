from __future__ import annotations

from datetime import date, datetime, timezone
import json
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    JobRun,
    MarketChipDaily,
    MarketDailyPrice,
    MarketIntradayBar,
    ShareholdingDistributionWeekly,
    SourceHealthSnapshot,
    StockMaster,
    TaiwanMarketMinuteState,
    TaiwanQuoteContractSnapshot,
    TaiwanStockQuoteSnapshot,
)
from app.market.source_health import build_taiwan_source_health
from app.observability import provider_health
from app.observability.provider_health import record_provider_event


class TaiwanSourceHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_source_health_marks_released_daily_data_as_stale_or_empty(self) -> None:
        updated_at = datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc)
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="台積電",
                market="上市",
                instrument_type="stock",
                updated_at=updated_at,
            )
        )
        self.db.add(
            MarketDailyPrice(
                source_id=1,
                raw_result_id=1,
                trade_date=date(2026, 6, 12),
                stock_id="2330",
                stock_name="台積電",
                close_price=2310,
                updated_at=updated_at,
            )
        )
        self.db.add(
            InstitutionalTradeDaily(
                source_id=1,
                raw_result_id=2,
                trade_date=date(2026, 6, 11),
                stock_id="2330",
                stock_name="台積電",
                total_institutional_net=1000,
                updated_at=updated_at,
            )
        )
        self.db.add(
            FinancialMetricQuarterly(
                source_id=1,
                raw_result_id=3,
                stock_id="2330",
                stock_name="台積電",
                fiscal_year=2026,
                quarter=1,
                period="2026Q1",
                report_date=date(2026, 5, 15),
                eps=10.0,
                updated_at=updated_at,
            )
        )
        self.db.add(
            MarketChipDaily(
                index_id="TAIEX",
                market="TWSE",
                trade_date=date(2026, 6, 12),
                source_grade="complete",
                updated_at=updated_at,
            )
        )
        now = datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc)
        with patch.object(provider_health, "_now", return_value=now):
            event = record_provider_event(
                self.db,
                market="tw",
                provider="twse",
                resource="market_daily_price",
                target="2330",
                status="error",
                event_time=now,
                error_message="TWSE daily source unavailable",
            )
            self.db.commit()

            health = build_taiwan_source_health(
                self.db,
                stock_id="2330",
                now=datetime(2026, 6, 15, 18, 31, tzinfo=ZoneInfo("Asia/Taipei")),
                sync_snapshots=True,
            )
        entries = {entry["resource"]: entry for entry in health["entries"]}

        self.assertEqual(health["filters"]["stock_id"], "2330")
        self.assertEqual(entries["market_daily_price"]["status"], "stale")
        self.assertEqual(entries["market_daily_price"]["latest_event_id"], event.id)
        self.assertEqual(entries["market_daily_price"]["latest_event_status"], "error")
        self.assertEqual(
            entries["market_daily_price"]["latest_event_scope"],
            "historical_provider_event",
        )
        self.assertEqual(
            entries["market_daily_price"]["historical_latest_event_status"],
            "error",
        )
        self.assertEqual(entries["market_daily_price"]["recent_error_count"], 1)
        self.assertEqual(entries["market_daily_price"]["expected_data_date"], "2026-06-15")
        self.assertEqual(entries["institutional_trade_daily"]["status"], "stale")
        self.assertEqual(entries["institutional_trade_daily"]["expected_data_date"], "2026-06-12")
        self.assertEqual(entries["margin_trading_daily"]["status"], "empty")
        self.assertEqual(entries["margin_trading_daily"]["expected_data_date"], "2026-06-12")
        self.assertEqual(entries["financial_metric_quarterly"]["status"], "current")
        self.assertEqual(entries["financial_metric_quarterly"]["latest_data_key"], "2026Q1")
        self.assertEqual(entries["financial_metric_quarterly"]["expected_data_key"], "2026Q1")
        self.assertEqual(entries["market_chip_daily"]["status"], "stale")
        self.assertEqual(entries["market_chip_daily"]["expected_data_date"], "2026-06-15")
        self.assertGreaterEqual(health["summary"]["stale_count"], 3)
        self.assertGreaterEqual(health["summary"]["empty_count"], 1)

        snapshot = (
            self.db.query(SourceHealthSnapshot)
            .filter(SourceHealthSnapshot.market == "tw")
            .filter(SourceHealthSnapshot.resource == "market_daily_price")
            .filter(SourceHealthSnapshot.target == "2330")
            .one()
        )
        self.assertEqual(snapshot.latest_event_id, event.id)
        self.assertEqual(snapshot.status, "stale")

    def test_daily_metric_source_health_exposes_persisted_repair_state(self) -> None:
        self.db.add(
            InstitutionalTradeDaily(
                source_id=1,
                raw_result_id=1,
                trade_date=date(2026, 6, 12),
                stock_id="2330",
            )
        )
        self.db.add(
            JobRun(
                job_type="scheduler.market_daily_refresh",
                status="error",
                target="2026-06-15",
                request_json=json.dumps(
                    {
                        "repair": {
                            "repair_key": "institutional_trade_daily:2026-06-15",
                            "detected_at": "2026-06-15T12:00:00+00:00",
                            "attempt": 1,
                            "max_attempts": 4,
                            "next_retry_at": "2026-06-15T12:15:00+00:00",
                        }
                    }
                ),
                error_message="expected date missing",
            )
        )
        self.db.commit()
        calendar_status = {
            "phase": "post_close",
            "release_windows": {
                "institutional_trade_daily": {
                    "expected_trade_date": "2026-06-15",
                    "is_released": True,
                    "status": "released",
                }
            },
        }

        with patch(
            "app.market.source_health.build_taiwan_calendar_status",
            return_value=calendar_status,
        ):
            health = build_taiwan_source_health(
                self.db,
                dataset="institutional_trade_daily",
                now=datetime(2026, 6, 15, 21, 0, tzinfo=ZoneInfo("Asia/Taipei")),
            )

        repair_state = health["entries"][0]["health_dimensions"]["repair"]
        self.assertEqual(repair_state["status"], "retry_wait")
        self.assertEqual(repair_state["attempt"], 1)
        self.assertEqual(repair_state["job_status"], "error")
        self.assertEqual(repair_state["last_error"], "expected date missing")
        status_dimensions = health["entries"][0]["status_dimensions"]
        self.assertEqual(status_dimensions["service_status"], "available")
        self.assertEqual(status_dimensions["data_quality"], "stale")
        self.assertEqual(status_dimensions["decision_readiness"], "limited")
        self.assertEqual(
            health["summary"]["status_dimensions"]["data_quality"],
            "stale",
        )

    def test_weekly_shareholding_uses_latest_conservative_friday(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            )
        )
        self.db.add(
            ShareholdingDistributionWeekly(
                source_id=1,
                raw_result_id=1,
                data_date=date(2026, 7, 10),
                stock_id="2330",
                stock_name="TSMC",
                holding_level="1",
                holding_level_order=1,
            )
        )
        self.db.commit()

        health = build_taiwan_source_health(
            self.db,
            stock_id="2330",
            dataset="shareholding_distribution_weekly",
            now=datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        entry = health["entries"][0]
        self.assertEqual(entry["expected_data_date"], "2026-07-17")
        self.assertEqual(entry["latest_data_date"], "2026-07-10")
        self.assertEqual(entry["status"], "stale")

    def test_weekly_shareholding_stays_current_before_assumed_release(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            )
        )
        self.db.add(
            ShareholdingDistributionWeekly(
                source_id=1,
                raw_result_id=1,
                data_date=date(2026, 7, 17),
                stock_id="2330",
                stock_name="TSMC",
                holding_level="1",
                holding_level_order=1,
            )
        )
        self.db.commit()

        health = build_taiwan_source_health(
            self.db,
            stock_id="2330",
            dataset="shareholding_distribution_weekly",
            now=datetime(2026, 7, 25, 11, 59, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        entry = health["entries"][0]
        self.assertEqual(entry["expected_data_date"], "2026-07-17")
        self.assertEqual(entry["status"], "pending")
        self.assertTrue(entry["ok"])
        self.assertEqual(entry["release_status"], "pending")
        self.assertFalse(entry["release_is_released"])
        self.assertEqual(entry["next_release_at"], "2026-07-25T12:00:00+08:00")

    def test_source_health_marks_equity_only_resources_not_applicable_for_etf(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="0050",
                stock_name="元大台灣50",
                market="上市",
                instrument_type="etf",
            )
        )
        self.db.commit()

        health = build_taiwan_source_health(
            self.db,
            stock_id="0050",
            now=datetime(2026, 6, 15, 18, 31, tzinfo=ZoneInfo("Asia/Taipei")),
        )
        entries = {entry["resource"]: entry for entry in health["entries"]}

        for resource in (
            "shareholding_distribution_weekly",
            "monthly_revenue",
            "financial_metric_quarterly",
        ):
            self.assertEqual(entries[resource]["status"], "not_applicable")
            self.assertEqual(entries[resource]["data_quality"], "not_applicable")
            self.assertFalse(entries[resource]["required"])
            self.assertTrue(entries[resource]["ok"])

        self.assertEqual(health["summary"]["not_applicable_count"], 3)

    def test_default_source_health_read_does_not_persist_snapshots(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            )
        )
        self.db.commit()

        build_taiwan_source_health(
            self.db,
            stock_id="2330",
            dataset="market_daily_price",
            now=datetime(2026, 7, 22, 14, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        self.assertEqual(self.db.query(SourceHealthSnapshot).count(), 0)

    def test_realtime_source_health_restores_exchange_timezone_after_sqlite_round_trip(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            )
        )
        self.db.add(
            TaiwanStockQuoteSnapshot(
                provider="twse_mis",
                market="TWSE",
                stock_id="2330",
                stock_name="TSMC",
                session_phase="regular_live",
                trade_date=date(2026, 7, 22),
                quote_time=datetime(2026, 7, 22, 9, 9, 40, tzinfo=ZoneInfo("Asia/Taipei")),
                source="twse_mis_stock_info",
                fetched_at=datetime(2026, 7, 22, 1, 9, 45, tzinfo=timezone.utc),
            )
        )
        self.db.add(
            MarketIntradayBar(
                provider="yahoo_finance_chart",
                stock_id="2330",
                market="TWSE",
                interval="1m",
                bar_time=datetime(2026, 7, 22, 9, 9, tzinfo=ZoneInfo("Asia/Taipei")),
                close_price=1200.0,
                source="yahoo_finance_chart",
            )
        )
        self.db.commit()

        record_provider_event(
            self.db,
            market="tw",
            provider="twse_mis",
            resource="quote_depth",
            target="2330",
            status="timeout",
            event_time=datetime(
                2026,
                7,
                22,
                9,
                9,
                50,
                tzinfo=ZoneInfo("Asia/Taipei"),
            ),
            error_message="fixture timeout",
        )

        with patch(
            "app.market.source_health.get_market_index_summary",
            return_value={"as_of": "2026-07-22T09:10:00+08:00", "indices": []},
        ):
            health = build_taiwan_source_health(
                self.db,
                stock_id="2330",
                now=datetime(2026, 7, 22, 9, 10, tzinfo=ZoneInfo("Asia/Taipei")),
            )
        entries = {entry["resource"]: entry for entry in health["entries"]}

        self.assertEqual(entries["taiwan_stock_quote_snapshot"]["status"], "current")
        self.assertEqual(entries["taiwan_stock_quote_snapshot"]["age_seconds"], 20)
        self.assertEqual(
            entries["taiwan_stock_quote_snapshot"]["latest_observed_at"],
            "2026-07-22T09:09:40+08:00",
        )
        self.assertEqual(entries["market_intraday_bar_1m"]["status"], "current")
        self.assertEqual(entries["market_intraday_bar_1m"]["age_seconds"], 60)
        quote_dimensions = entries["taiwan_stock_quote_snapshot"][
            "health_dimensions"
        ]
        self.assertEqual(quote_dimensions["request_live"]["status"], "current")
        self.assertEqual(
            quote_dimensions["provider_availability"]["status"],
            "unavailable",
        )
        self.assertFalse(
            quote_dimensions["provider_availability"][
                "inferred_from_quote_row"
            ]
        )

    def test_global_quote_health_uses_bounded_scheduler_contract_not_random_row(
        self,
    ) -> None:
        observed_at = datetime(
            2026,
            7,
            22,
            8,
            30,
            10,
            tzinfo=ZoneInfo("Asia/Taipei"),
        )
        self.db.add_all(
            [
                StockMaster(
                    stock_id="2330",
                    stock_name="TSMC",
                    market="TWSE",
                    instrument_type="stock",
                ),
                StockMaster(
                    stock_id="2317",
                    stock_name="Hon Hai",
                    market="TWSE",
                    instrument_type="stock",
                ),
                TaiwanStockQuoteSnapshot(
                    provider="twse_mis",
                    market="TWSE",
                    stock_id="2330",
                    stock_name="TSMC",
                    session_phase="preopen_auction",
                    trade_date=date(2026, 7, 22),
                    quote_time=observed_at,
                    source="twse_mis_quote_depth",
                    fetched_at=observed_at,
                ),
                TaiwanQuoteContractSnapshot(
                    provider="twse_mis",
                    market="TWSE",
                    stock_id="2330",
                    trade_date=date(2026, 7, 22),
                    capture_slot="08:30",
                    scheduled_at=observed_at.replace(second=0),
                    captured_at=observed_at,
                    quote_time=observed_at,
                    session_phase="preopen_auction",
                    capture_status="captured",
                    refresh_outcome="updated",
                    freshness_status="live",
                    source="twse_mis_quote_depth",
                ),
            ]
        )
        self.db.commit()

        with (
            patch.object(
                provider_health,
                "_now",
                return_value=observed_at,
            ),
            patch(
                "app.market.source_health.get_market_index_summary",
                return_value={"as_of": observed_at.isoformat(), "indices": []},
            ),
            patch(
                "app.market.quote_contract_health.settings."
                "scheduler_taiwan_quote_contract_symbols",
                "2330,2317",
            ),
            patch(
                "app.market.quote_contract_health.settings."
                "scheduler_taiwan_quote_contract_max_symbols",
                2,
            ),
        ):
            health = build_taiwan_source_health(
                self.db,
                now=observed_at,
            )

        quote = next(
            entry
            for entry in health["entries"]
            if entry["resource"] == "taiwan_stock_quote_snapshot"
        )
        dimensions = quote["health_dimensions"]
        scheduler = dimensions["scheduler_contract"]

        self.assertNotEqual(quote["target"], "all")
        self.assertEqual(dimensions["request_live"]["status"], "not_requested")
        self.assertEqual(scheduler["target_scope"], "bounded_universe")
        self.assertEqual(scheduler["requested_symbol_count"], 2)
        self.assertEqual(scheduler["requested_count"], 2)
        self.assertEqual(scheduler["captured_count"], 1)
        self.assertEqual(scheduler["coverage_ratio"], 0.5)
        self.assertEqual(scheduler["status"], "partial")
        self.assertEqual(scheduler["missing_symbols"], ["2317"])
        self.assertEqual(
            dimensions["provider_availability"]["status"],
            "unknown",
        )

    def test_realtime_source_health_uses_presentation_session_before_open(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            )
        )
        self.db.add(
            TaiwanStockQuoteSnapshot(
                provider="twse_mis",
                market="TWSE",
                stock_id="2330",
                stock_name="TSMC",
                session_phase="post_close",
                trade_date=date(2026, 8, 6),
                quote_time=datetime(
                    2026,
                    8,
                    6,
                    13,
                    30,
                    tzinfo=ZoneInfo("Asia/Taipei"),
                ),
                source="twse_mis_stock_info",
                fetched_at=datetime(2026, 8, 6, 5, 31, tzinfo=timezone.utc),
            )
        )
        self.db.add(
            MarketIntradayBar(
                provider="yahoo_finance_chart",
                stock_id="2330",
                market="TWSE",
                interval="1m",
                bar_time=datetime(
                    2026,
                    8,
                    6,
                    13,
                    30,
                    tzinfo=ZoneInfo("Asia/Taipei"),
                ),
                close_price=1200.0,
                source="yahoo_finance_chart",
            )
        )
        self.db.commit()

        with patch(
            "app.market.source_health.get_market_index_summary",
            return_value={"as_of": "2026-08-06T13:30:00+08:00", "indices": []},
        ):
            before_rollover = build_taiwan_source_health(
                self.db,
                stock_id="2330",
                now=datetime(2026, 8, 7, 7, 59, tzinfo=ZoneInfo("Asia/Taipei")),
            )
            after_rollover = build_taiwan_source_health(
                self.db,
                stock_id="2330",
                now=datetime(2026, 8, 7, 8, 5, tzinfo=ZoneInfo("Asia/Taipei")),
            )

        before_entries = {
            entry["resource"]: entry for entry in before_rollover["entries"]
        }
        after_entries = {
            entry["resource"]: entry for entry in after_rollover["entries"]
        }
        self.assertEqual(
            before_entries["taiwan_stock_quote_snapshot"]["expected_data_date"],
            "2026-08-06",
        )
        self.assertEqual(
            before_entries["taiwan_stock_quote_snapshot"]["status"],
            "available",
        )
        self.assertEqual(
            after_entries["taiwan_stock_quote_snapshot"]["expected_data_date"],
            "2026-08-07",
        )
        self.assertEqual(
            after_entries["taiwan_stock_quote_snapshot"]["status"],
            "pending",
        )
        self.assertEqual(
            after_entries["market_intraday_bar_1m"]["status"],
            "pending",
        )

    def test_minute_state_health_is_partial_when_latest_minute_misses_tpex(self) -> None:
        minute_at = datetime(2026, 7, 22, 13, 30, tzinfo=ZoneInfo("Asia/Taipei"))
        self.db.add(
            TaiwanMarketMinuteState(
                market="TWSE",
                index_id="TAIEX",
                trade_date=date(2026, 7, 22),
                minute_at=minute_at,
                session_status="final",
                breadth_status="ready",
                breadth_scope="full_market",
                source="twse_rwd_mi_index",
                source_category="official",
                official_flag=True,
                derived_flag=False,
                quality_status="ready",
                advance_count=530,
                decline_count=464,
                unchanged_count=68,
                total_count=1062,
                cumulative_trade_value=1_025_958_396_323,
            )
        )
        self.db.commit()

        health = build_taiwan_source_health(
            self.db,
            dataset="taiwan_market_minute_state",
            now=datetime(2026, 7, 22, 20, 0, tzinfo=ZoneInfo("Asia/Taipei")),
        )

        entry = health["entries"][0]
        self.assertEqual(entry["status"], "partial")
        self.assertFalse(entry["ok"])
        self.assertIn("TPEX", entry["reason"])


if __name__ == "__main__":
    unittest.main()
