from __future__ import annotations

from datetime import date, timedelta
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.technical_report import build_stock_technical_report


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_raw_source(db: Session, category: str) -> tuple[int, int]:
    source = SourceRegistry(
        source_name=f"test-{category}",
        source_type="test",
        category=category,
    )
    db.add(source)
    db.flush()

    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
        url=f"https://example.test/{category}",
        status_code=200,
        content_hash=f"{category}-hash",
        raw_text="{}",
    )
    db.add(raw)
    db.flush()
    return source.id, raw.id


def add_stock(db: Session, stock_id: str = "2330") -> None:
    db.add(
        StockMaster(
            stock_id=stock_id,
            stock_name="TSMC",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.commit()


def add_daily_history(db: Session, stock_id: str = "2330", count: int = 80) -> None:
    source_id, raw_result_id = add_raw_source(db, "market_daily_price")
    start = date(2026, 1, 1)

    for index in range(count):
        close = 100.0 + index
        db.add(
            MarketDailyPrice(
                source_id=source_id,
                raw_result_id=raw_result_id,
                trade_date=start + timedelta(days=index),
                stock_id=stock_id,
                stock_name="TSMC",
                trade_volume=1_000_000 + index * 1000,
                open_price=close - 1,
                high_price=close + 2,
                low_price=close - 2,
                close_price=close,
                price_change=1.0,
            )
        )

    db.commit()


def add_chip_rows(db: Session, stock_id: str = "2330") -> None:
    institutional_source_id, institutional_raw_id = add_raw_source(db, "institutional_trade")
    margin_source_id, margin_raw_id = add_raw_source(db, "margin_trading")
    trade_date = date(2026, 3, 21)

    db.add(
        InstitutionalTradeDaily(
            source_id=institutional_source_id,
            raw_result_id=institutional_raw_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            total_institutional_net=2_000_000,
        )
    )
    db.add(
        MarginTradingDaily(
            source_id=margin_source_id,
            raw_result_id=margin_raw_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            margin_previous_balance=100_000,
            margin_today_balance=98_000,
        )
    )
    db.commit()


class TechnicalReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        add_stock(self.db)
        add_daily_history(self.db)
        add_chip_rows(self.db)

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def test_daily_report_returns_prompt_ready_rows(self) -> None:
        report = build_stock_technical_report(
            db=self.db,
            stock_id="2330",
            timeframe="daily",
            include_intraday=False,
        )

        self.assertEqual(report["kind"], "tw_stock_technical_report")
        self.assertEqual(report["timeframe"], "daily")
        self.assertEqual(report["phase"], "daily")
        self.assertEqual(report["value_label"], "vs MA20")
        self.assertTrue(report["rows"])
        self.assertIn("daily_indicator", report["data"])

    def test_today_report_waits_when_intraday_has_no_points(self) -> None:
        with patch(
            "app.market.technical_report.get_intraday_trend",
            return_value={
                "stock_id": "2330",
                "symbol": "2330",
                "source": "test_intraday",
                "previous_close": 180.0,
                "point_count": 0,
                "points": [],
            },
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        self.assertEqual(report["phase"], "waiting_intraday")
        self.assertEqual(report["confidence"], "low")
        self.assertIn("intraday_trend.points", report["missing"])

    def test_today_report_uses_opening_phase_for_sparse_intraday_points(self) -> None:
        with patch(
            "app.market.technical_report.get_intraday_trend",
            return_value={
                "stock_id": "2330",
                "symbol": "2330",
                "source": "test_intraday",
                "previous_close": 180.0,
                "point_count": 1,
                "points": [
                    {
                        "time": "2026-03-22T09:01:00+08:00",
                        "price": 183.0,
                        "volume": 3000,
                        "open": 182.0,
                        "high": 183.0,
                        "low": 182.0,
                    }
                ],
            },
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        self.assertEqual(report["phase"], "opening")
        self.assertEqual(report["confidence"], "low")
        self.assertEqual(report["value_label"], "vs 昨收")
        self.assertGreater(report["value"], 0)
        self.assertTrue(any(row["key"] == "daily_background" for row in report["rows"]))


if __name__ == "__main__":
    unittest.main()
