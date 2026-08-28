from __future__ import annotations

from datetime import date, datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    MarketIntradayBar,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.stock_volume_pace import (
    build_stock_volume_pace,
    build_tw_stock_volume_pace,
    intraday_history_needs_bootstrap,
    mutate_market_intraday_history,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
from app.us_market.trading_calendar import US_MARKET_TIMEZONE


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


class TaiwanStockVolumePaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        source = SourceRegistry(
            source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
            source_type="official",
            category="market_daily_price",
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
                is_active=True,
            )
        )
        raw = RawFetchResult(
            source_id=source.id,
            method="GET",
            url="https://example.test/volume-pace",
            status_code=200,
            content_hash="volume-pace",
            raw_text="{}",
        )
        self.db.add(raw)
        self.db.flush()
        self.source_id = source.id
        self.raw_result_id = raw.id

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def add_complete_session(
        self,
        trade_date: date,
        *,
        cumulative_at_1030: int,
        daily_total: int = 1_000,
        intraday_total: int | None = None,
    ) -> None:
        self.db.add(
            MarketDailyPrice(
                source_id=self.source_id,
                raw_result_id=self.raw_result_id,
                trade_date=trade_date,
                stock_id="2330",
                stock_name="TSMC",
                trade_volume=daily_total,
                open_price=100,
                high_price=100,
                low_price=100,
                close_price=100,
            )
        )
        effective_total = intraday_total if intraday_total is not None else daily_total
        opening_volume = min(cumulative_at_1030, effective_total) // 2
        middle_volume = min(cumulative_at_1030, effective_total) - opening_volume
        close_volume = max(effective_total - opening_volume - middle_volume, 0)
        for hour, minute, volume in (
            (9, 0, opening_volume),
            (10, 30, middle_volume),
            (13, 30, close_volume),
        ):
            self.db.add(
                MarketIntradayBar(
                    provider="yahoo_finance_chart",
                    stock_id="2330",
                    market="TWSE",
                    symbol="2330.TW",
                    interval="1m",
                    bar_time=datetime(
                        trade_date.year,
                        trade_date.month,
                        trade_date.day,
                        hour,
                        minute,
                        tzinfo=TAIWAN_TZ,
                    ),
                    close_price=100,
                    trade_volume=volume,
                    source="test_intraday",
                )
            )
        self.db.commit()

    def test_uses_complete_prior_sessions_at_the_same_minute(self) -> None:
        for day, cumulative in zip(
            (13, 14, 15, 16, 17),
            (100, 200, 300, 400, 500),
            strict=True,
        ):
            self.add_complete_session(
                date(2026, 7, day),
                cumulative_at_1030=cumulative,
            )
        self.add_complete_session(
            date(2026, 7, 20),
            cumulative_at_1030=100,
            intraday_total=100,
        )

        result = build_tw_stock_volume_pace(
            self.db,
            stock_id="2330",
            current_points=[
                {
                    "time": "2026-07-22T09:00:00+08:00",
                    "price": 100,
                    "volume": 250,
                },
                {
                    "time": "2026-07-22T10:30:00+08:00",
                    "price": 101,
                    "volume": 350,
                },
            ],
        )

        baseline = result["same_time_baseline_5d"]
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["comparison_minute"], "10:30")
        self.assertEqual(result["current_cumulative_volume"], 600)
        self.assertEqual(baseline["sample_days"], 5)
        self.assertEqual(baseline["median_cumulative_volume"], 300)
        self.assertEqual(baseline["pace_ratio"], 2.0)
        self.assertEqual(result["excluded_incomplete_trade_dates"], ["2026-07-20"])

    def test_withholds_ratio_until_minimum_sample_is_available(self) -> None:
        self.add_complete_session(date(2026, 7, 20), cumulative_at_1030=200)
        self.add_complete_session(date(2026, 7, 21), cumulative_at_1030=400)

        result = build_tw_stock_volume_pace(
            self.db,
            stock_id="2330",
            current_points=[
                {
                    "time": "2026-07-22T10:30:00+08:00",
                    "price": 101,
                    "volume": 600,
                    "cumulative_volume": 600,
                }
            ],
        )

        baseline = result["same_time_baseline_5d"]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(baseline["sample_days"], 2)
        self.assertEqual(baseline["median_cumulative_volume"], 300)
        self.assertIsNone(baseline["pace_ratio"])

    def test_cross_market_history_bootstrap_is_idempotent_and_builds_pace(self) -> None:
        history_points: list[dict] = []
        daily_totals: dict[date, int] = {}
        for day, cumulative in zip(
            (13, 14, 15, 16, 17),
            (100, 200, 300, 400, 500),
            strict=True,
        ):
            trade_date = date(2026, 7, day)
            daily_totals[trade_date] = 1_000
            first_volume = cumulative // 2
            second_volume = cumulative - first_volume
            history_points.extend(
                [
                    {
                        "time": datetime(
                            2026,
                            7,
                            day,
                            9,
                            30,
                            tzinfo=US_MARKET_TIMEZONE,
                        ).isoformat(),
                        "session": "regular",
                        "price": 100,
                        "volume": first_volume,
                    },
                    {
                        "time": datetime(
                            2026,
                            7,
                            day,
                            10,
                            30,
                            tzinfo=US_MARKET_TIMEZONE,
                        ).isoformat(),
                        "session": "regular",
                        "price": 101,
                        "volume": second_volume,
                    },
                    {
                        "time": datetime(
                            2026,
                            7,
                            day,
                            16,
                            0,
                            tzinfo=US_MARKET_TIMEZONE,
                        ).isoformat(),
                        "session": "regular",
                        "price": 102,
                        "volume": 1_000 - cumulative,
                    },
                ]
            )

        self.assertTrue(
            intraday_history_needs_bootstrap(
                self.db,
                stock_id="TSM",
                market="US",
                market_timezone=US_MARKET_TIMEZONE,
            )
        )
        changed = mutate_market_intraday_history(
            self.db,
            provider="yahoo_finance_chart",
            stock_id="TSM",
            market="US",
            symbol="TSM",
            interval="1m",
            source="yahoo_finance_chart",
            source_url="https://example.test/chart/TSM?range=5d&interval=1m",
            points=history_points,
            market_timezone=US_MARKET_TIMEZONE,
        )
        self.db.commit()
        unchanged = mutate_market_intraday_history(
            self.db,
            provider="yahoo_finance_chart",
            stock_id="TSM",
            market="US",
            symbol="TSM",
            interval="1m",
            source="yahoo_finance_chart",
            source_url="https://example.test/chart/TSM?range=5d&interval=1m",
            points=history_points,
            market_timezone=US_MARKET_TIMEZONE,
        )

        self.assertEqual(changed, 15)
        self.assertEqual(unchanged, 0)
        self.assertFalse(
            intraday_history_needs_bootstrap(
                self.db,
                stock_id="TSM",
                market="US",
                market_timezone=US_MARKET_TIMEZONE,
            )
        )

        result = build_stock_volume_pace(
            self.db,
            stock_id="TSM",
            market="US",
            current_points=[
                {
                    "time": "2026-07-20T09:30:00-04:00",
                    "session": "regular",
                    "price": 100,
                    "volume": 250,
                },
                {
                    "time": "2026-07-20T10:30:00-04:00",
                    "session": "regular",
                    "price": 101,
                    "volume": 350,
                },
            ],
            market_timezone=US_MARKET_TIMEZONE,
            daily_totals=daily_totals,
            daily_source_name="us_daily_price",
            history_market="US",
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["current_cumulative_volume"], 600)
        self.assertEqual(result["same_time_baseline_5d"]["median_cumulative_volume"], 300)
        self.assertEqual(result["same_time_baseline_5d"]["pace_ratio"], 2.0)


if __name__ == "__main__":
    unittest.main()
