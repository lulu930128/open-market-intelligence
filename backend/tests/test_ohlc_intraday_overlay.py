from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    USDailyPrice,
)
from app.market.ohlc_overlay import aggregate_ohlc_points
from app.market.schemas import MarketOhlcChartRead
from app.market.service import list_stock_ohlc_chart_data
from app.us_market.service import list_us_ohlc_chart_data
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


class OhlcIntradayOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        self.db.close()

    def test_chart_projection_sorts_and_dedupes_trading_dates(self) -> None:
        points = aggregate_ohlc_points(
            timeframe="daily",
            points=[
                {"time": date(2026, 7, 16), "close": 100, "volume": 10},
                {"time": date(2026, 7, 15), "close": 90, "volume": 5},
                {"time": date(2026, 7, 16), "close": 101, "volume": 12},
            ],
        )

        self.assertEqual([point["time"] for point in points], [
            date(2026, 7, 15),
            date(2026, 7, 16),
        ])
        self.assertEqual(points[-1]["close"], 101)

    def test_taiwan_daily_ohlc_appends_provisional_intraday_candle(self) -> None:
        source = SourceRegistry(
            source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
            source_type="official",
            category="market_data",
            priority=10,
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime(2026, 6, 26, 8, tzinfo=timezone.utc),
            method="GET",
            content_hash="overlay-canonical-daily",
        )
        self.db.add(raw)
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            )
        )
        self.db.flush()
        self.db.add(
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                trade_date=date(2026, 6, 26),
                stock_id="2330",
                stock_name="TSMC",
                open_price=100.0,
                high_price=103.0,
                low_price=99.0,
                close_price=101.0,
                trade_volume=1000,
            )
        )
        self.db.commit()

        intraday = {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "yahoo_finance_chart",
            "previous_close": 101.0,
            "point_count": 2,
            "points": [
                {
                    "time": "2026-06-29T09:00:00+08:00",
                    "price": 102.0,
                    "open": 101.5,
                    "high": 103.0,
                    "low": 101.0,
                    "volume": 10,
                },
                {
                    "time": "2026-06-29T13:30:00+08:00",
                    "price": 105.0,
                    "open": 104.0,
                    "high": 106.0,
                    "low": 103.5,
                    "volume": 20,
                },
            ],
        }

        with patch("app.market.service.get_intraday_trend", return_value=intraday):
            chart = list_stock_ohlc_chart_data(
                self.db,
                stock_id="2330",
                timeframe="daily",
                bars=5,
                include_intraday=True,
                to_date=date(2026, 6, 29),
            )

        self.assertEqual(chart["point_count"], 2)
        self.assertEqual(chart["points"][-1]["time"], date(2026, 6, 29))
        self.assertEqual(chart["points"][-1]["open"], 101.5)
        self.assertEqual(chart["points"][-1]["high"], 106.0)
        self.assertEqual(chart["points"][-1]["low"], 101.0)
        self.assertEqual(chart["points"][-1]["close"], 105.0)
        self.assertEqual(chart["points"][-1]["volume"], 30)
        self.assertEqual(chart["volume_unit"], "shares")
        self.assertEqual(chart["trade_value_unit"], "TWD")
        self.assertEqual(chart["currency"], "TWD")
        projected = MarketOhlcChartRead.model_validate(chart)
        self.assertEqual(projected.trade_value_unit, "TWD")
        self.assertEqual(projected.currency, "TWD")
        self.assertEqual(chart["intraday_overlay"]["trade_date"], date(2026, 6, 29))
        self.assertEqual(chart["intraday_overlay"]["previous_close"], 101.0)
        self.assertTrue(chart["intraday_overlay"]["provisional"])

    def test_taiwan_daily_ohlc_refreshes_when_full_window_is_stale(self) -> None:
        source = SourceRegistry(
            source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
            source_type="api",
            category="market_data",
            priority=10,
            parser_type="twse_stock_day_all.v2",
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        trade_dates = [date(2026, 7, 13), date(2026, 7, 14)]
        raw_results = []
        for index, trade_date in enumerate(trade_dates, start=1):
            raw = RawFetchResult(
                source_id=source.id,
                fetched_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
                raw_text="[]",
                content_hash=f"fixture-{index}",
                parser_version="twse_stock_day_all.v2",
            )
            self.db.add(raw)
            self.db.flush()
            raw_results.append(raw)
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            )
        )
        self.db.add_all(
            [
                MarketDailyPrice(
                    source_id=source.id,
                    raw_result_id=raw.id,
                    trade_date=trade_date,
                    stock_id="2330",
                    stock_name="TSMC",
                    open_price=100.0 + index,
                    high_price=103.0 + index,
                    low_price=99.0 + index,
                    close_price=101.0 + index,
                    trade_volume=1000 + index,
                )
                for index, (trade_date, raw) in enumerate(
                    zip(trade_dates, raw_results, strict=True),
                    start=1,
                )
            ]
        )
        self.db.commit()

        chart = list_stock_ohlc_chart_data(
            self.db,
            stock_id="2330",
            timeframe="daily",
            bars=2,
            ensure_history=True,
            to_date=date(2026, 7, 16),
        )

        self.assertEqual(chart["freshness_status"], "stale")
        self.assertIn("stale_latest_date", chart["backfill"]["refresh_reasons"])
        self.assertEqual(chart["backfill"]["status"], "not_attempted")
        self.assertIn("cache-only", chart["backfill"]["message"])

    def test_us_weekly_ohlc_merges_provisional_intraday_candle(self) -> None:
        self.db.add_all(
            [
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 6, 22),
                    open_price=100.0,
                    high_price=110.0,
                    low_price=98.0,
                    close_price=105.0,
                    trade_volume=1000,
                    source_url="https://example.test/chart",
                    raw_payload_hash="a",
                ),
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 6, 24),
                    open_price=106.0,
                    high_price=109.0,
                    low_price=102.0,
                    close_price=108.0,
                    trade_volume=2000,
                    source_url="https://example.test/chart",
                    raw_payload_hash="b",
                ),
            ]
        )
        self.db.commit()
        intraday = {
            "stock_id": "AAPL",
            "symbol": "AAPL",
            "source": "yahoo_finance_chart",
            "previous_close": 108.0,
            "point_count": 2,
            "points": [
                {
                    "time": "2026-06-26T09:30:00-04:00",
                    "price": 109.0,
                    "open": 108.5,
                    "high": 110.0,
                    "low": 107.0,
                    "volume": 100,
                },
                {
                    "time": "2026-06-26T16:00:00-04:00",
                    "price": 111.0,
                    "open": 110.0,
                    "high": 112.0,
                    "low": 109.5,
                    "volume": 200,
                },
            ],
        }

        with patch("app.us_market.service.get_us_intraday_trend", return_value=intraday):
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="AAPL",
                timeframe="weekly",
                bars=5,
                include_intraday=True,
                to_date=date(2026, 6, 26),
            )

        self.assertEqual(chart["point_count"], 1)
        self.assertEqual(chart["points"][0]["time"], date(2026, 6, 22))
        self.assertEqual(chart["points"][0]["open"], 100.0)
        self.assertEqual(chart["points"][0]["high"], 112.0)
        self.assertEqual(chart["points"][0]["low"], 98.0)
        self.assertEqual(chart["points"][0]["close"], 111.0)
        self.assertEqual(chart["points"][0]["volume"], 3300)
        self.assertEqual(chart["intraday_overlay"]["trade_date"], date(2026, 6, 26))
        self.assertEqual(chart["intraday_overlay"]["previous_close"], 108.0)
        self.assertTrue(chart["intraday_overlay"]["provisional"])


if __name__ == "__main__":
    unittest.main()
