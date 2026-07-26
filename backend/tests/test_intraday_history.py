from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketIntradayBar, StockMaster
from app.market import intraday


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


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


def point(
    hour: int,
    minute: int,
    close: float,
    volume: int = 1000,
    *,
    days_ago: int = 0,
) -> dict:
    point_time = (datetime.now(intraday.TAIPEI_TZ) - timedelta(days=days_ago)).replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    return {
        "time": point_time.isoformat(),
        "price": close,
        "volume": volume,
        "open": close - 1,
        "high": close + 2,
        "low": close - 2,
    }


class MarketIntradayHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        add_stock(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_history_refresh_persists_interval_bars(self) -> None:
        payload = {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "yahoo_finance_chart",
            "source_url": "https://example.test/chart",
            "previous_close": 100,
            "point_count": 3,
            "points": [point(8, 59, 100), point(9, 0, 101), point(9, 1, 102)],
        }

        with patch.object(intraday, "_fetch_yahoo_intraday", return_value=payload) as fetch:
            result = intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval="1m",
                range_value="5d",
            )

        fetch.assert_called_once()
        self.assertEqual(result["point_count"], 2)
        self.assertEqual(result["refreshed_count"], 2)
        self.assertEqual(result["points"][-1]["close"], 102)
        self.assertEqual(
            self.db.query(MarketIntradayBar)
            .filter(MarketIntradayBar.stock_id == "2330")
            .filter(MarketIntradayBar.interval == "1m")
            .count(),
            2,
        )

    def test_four_hour_history_aggregates_hourly_points(self) -> None:
        payload = {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "yahoo_finance_chart",
            "source_url": "https://example.test/chart",
            "previous_close": 100,
            "point_count": 3,
            "points": [
                point(9, 0, 101, 1000),
                point(10, 0, 105, 2000),
                point(13, 30, 103, 3000),
            ],
        }

        with patch.object(intraday, "_fetch_yahoo_intraday", return_value=payload):
            result = intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval="4h",
                range_value="5d",
            )

        self.assertEqual(result["point_count"], 2)
        self.assertEqual(result["points"][0]["open"], 100)
        self.assertEqual(result["points"][0]["high"], 107)
        self.assertEqual(result["points"][0]["low"], 99)
        self.assertEqual(result["points"][0]["close"], 105)
        self.assertEqual(result["points"][0]["volume"], 3000)
        self.assertEqual(result["points"][1]["close"], 103)

    def test_one_minute_auto_keeps_recent_trading_days_across_calendar_gap(self) -> None:
        payload = {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "yahoo_finance_chart",
            "source_url": "https://example.test/chart",
            "previous_close": 100,
            "point_count": 1,
            "points": [point(9, 0, 101, days_ago=6)],
        }

        with patch.object(intraday, "_fetch_yahoo_intraday", return_value=payload):
            result = intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval="1m",
                range_value="auto",
            )

        self.assertEqual(result["point_count"], 1)
        self.assertEqual(result["points"][0]["close"], 101)

    def test_five_minute_history_overlays_current_local_one_minute_aggregate(self) -> None:
        one_minute_payload = {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "yahoo_finance_chart",
            "source_url": "https://example.test/one-minute",
            "points": [
                point(13, 15, 101, 1000),
                point(13, 16, 102, 2000),
                point(13, 17, 103, 3000),
            ],
        }
        stale_five_minute_payload = {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "yahoo_finance_chart",
            "source_url": "https://example.test/five-minute",
            "points": [point(12, 55, 99, 500)],
        }

        with (
            patch.object(
                intraday,
                "get_taiwan_disposition_status",
                return_value={"is_active": False},
            ),
            patch.object(
                intraday,
                "_fetch_yahoo_intraday",
                side_effect=[one_minute_payload, stale_five_minute_payload],
            ),
        ):
            intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval="1m",
                range_value="1d",
            )
            result = intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval="5m",
                range_value="1d",
            )

        self.assertEqual(result["source"], "local_current_1m_aggregate")
        self.assertEqual(result["provider"], "local_derived")
        self.assertEqual(result["points"][-1]["close"], 103)
        self.assertEqual(result["points"][-1]["volume"], 6000)

    def test_repeated_identical_intraday_refresh_reports_zero_updates(self) -> None:
        payload = {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "yahoo_finance_chart",
            "source_url": "https://example.test/chart",
            "points": [point(9, 0, 101, 1000)],
        }

        with (
            patch.object(
                intraday,
                "get_taiwan_disposition_status",
                return_value={"is_active": False},
            ),
            patch.object(intraday, "_fetch_yahoo_intraday", return_value=payload),
        ):
            first = intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval="1m",
                range_value="1d",
            )
            second = intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval="1m",
                range_value="1d",
            )

        self.assertEqual(first["refreshed_count"], 1)
        self.assertEqual(second["refreshed_count"], 0)


if __name__ == "__main__":
    unittest.main()
