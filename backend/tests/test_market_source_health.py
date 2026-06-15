from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarketChipDaily,
    MarketDailyPrice,
    SourceHealthSnapshot,
    StockMaster,
)
from app.market.source_health import build_taiwan_source_health
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
        event = record_provider_event(
            self.db,
            market="tw",
            provider="twse",
            resource="market_daily_price",
            target="2330",
            status="error",
            event_time=datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc),
            error_message="TWSE daily source unavailable",
        )
        self.db.commit()

        health = build_taiwan_source_health(
            self.db,
            stock_id="2330",
            now=datetime(2026, 6, 15, 18, 31, tzinfo=ZoneInfo("Asia/Taipei")),
        )
        entries = {entry["resource"]: entry for entry in health["entries"]}

        self.assertEqual(health["filters"]["stock_id"], "2330")
        self.assertEqual(entries["market_daily_price"]["status"], "stale")
        self.assertEqual(entries["market_daily_price"]["latest_event_id"], event.id)
        self.assertEqual(entries["market_daily_price"]["latest_event_status"], "error")
        self.assertEqual(entries["market_daily_price"]["recent_error_count"], 1)
        self.assertEqual(entries["market_daily_price"]["expected_data_date"], "2026-06-15")
        self.assertEqual(entries["institutional_trade_daily"]["status"], "stale")
        self.assertEqual(entries["institutional_trade_daily"]["expected_data_date"], "2026-06-15")
        self.assertEqual(entries["margin_trading_daily"]["status"], "empty")
        self.assertEqual(entries["margin_trading_daily"]["expected_data_date"], "2026-06-12")
        self.assertEqual(entries["financial_metric_quarterly"]["status"], "available")
        self.assertEqual(entries["financial_metric_quarterly"]["latest_data_key"], "2026Q1")
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


if __name__ == "__main__":
    unittest.main()
