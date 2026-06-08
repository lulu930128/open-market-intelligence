from __future__ import annotations

from datetime import date, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketIndexDailyStat
from app.market import indices


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def yahoo_point(trade_date: date, close: float) -> dict:
    return {
        "time": trade_date,
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 1,
        "trade_value": None,
        "transaction_count": None,
    }


class MarketIndexDailyStatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        self.db.close()

    def test_taiex_daily_ohlc_uses_persisted_official_trade_value(self) -> None:
        yahoo_points = [
            yahoo_point(date(2026, 1, 5), 23000),
            yahoo_point(date(2026, 1, 6), 23100),
        ]
        official_rows = [
            {
                "trade_date": date(2026, 1, 5),
                "trade_volume": 10,
                "trade_value": 1000,
                "transaction_count": 100,
                "close_value": 23000,
                "price_change": 10,
            },
            {
                "trade_date": date(2026, 1, 6),
                "trade_volume": 20,
                "trade_value": 2000,
                "transaction_count": 200,
                "close_value": 23100,
                "price_change": 20,
            },
        ]

        with (
            patch.object(
                indices,
                "_fetch_yahoo_index_points",
                return_value=(yahoo_points, {}, timezone(timedelta(hours=8))),
            ),
            patch.object(
                indices,
                "_fetch_twse_market_daily_stats_for_month",
                return_value=(official_rows, "https://example.test/fmtqik"),
            ),
            patch.object(indices, "_fetch_recent_market_index_daily_stats", return_value=[]),
        ):
            payload = indices.get_market_index_ohlc_chart_data(
                index_id="TAIEX",
                timeframe="daily",
                bars=2,
                db=self.db,
            )

        self.assertEqual([point["trade_value"] for point in payload["points"]], [1000, 2000])
        self.assertEqual([point["volume"] for point in payload["points"]], [10, 20])
        self.assertEqual(self.db.query(MarketIndexDailyStat).count(), 2)

    def test_weekly_ohlc_sums_daily_official_trade_value_by_week(self) -> None:
        yahoo_points = [yahoo_point(date(2026, 1, 5), 23000)]
        official_rows = [
            {
                "trade_date": date(2026, 1, 5),
                "trade_volume": 10,
                "trade_value": 1000,
                "transaction_count": 100,
                "close_value": 23000,
                "price_change": 10,
            },
            {
                "trade_date": date(2026, 1, 6),
                "trade_volume": 20,
                "trade_value": 2000,
                "transaction_count": 200,
                "close_value": 23100,
                "price_change": 20,
            },
        ]

        with (
            patch.object(
                indices,
                "_fetch_yahoo_index_points",
                return_value=(yahoo_points, {}, timezone(timedelta(hours=8))),
            ),
            patch.object(
                indices,
                "_fetch_twse_market_daily_stats_for_month",
                return_value=(official_rows, "https://example.test/fmtqik"),
            ),
            patch.object(indices, "_fetch_recent_market_index_daily_stats", return_value=[]),
        ):
            payload = indices.get_market_index_ohlc_chart_data(
                index_id="TAIEX",
                timeframe="weekly",
                bars=1,
                db=self.db,
            )

        self.assertEqual(payload["points"][0]["trade_value"], 3000)
        self.assertEqual(payload["points"][0]["volume"], 30)
        self.assertEqual(payload["points"][0]["transaction_count"], 300)


if __name__ == "__main__":
    unittest.main()
