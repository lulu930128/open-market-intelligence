from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from app.db.models import JPDailyPrice, KRDailyPrice, KRIndexDailyPrice, USDailyPrice
from app.jp_market import chart_projection as jp_chart
from app.jp_market import service as jp_service
from app.kr_market import chart_projection as kr_chart
from app.kr_market import service as kr_service
from app.us_market import chart_projection as us_chart
from app.us_market import service as us_service


class MarketChartProjectionTests(unittest.TestCase):
    def test_service_facades_keep_projection_aliases(self) -> None:
        self.assertIs(us_service._aggregate_us_daily_rows, us_chart.aggregate_daily_rows)
        self.assertIs(
            us_service._dedupe_us_daily_rows_by_trade_date,
            us_chart.dedupe_daily_rows_by_trade_date,
        )
        self.assertIs(jp_service._aggregate_jp_daily_rows, jp_chart.aggregate_daily_rows)
        self.assertIs(kr_service._aggregate_kr_daily_rows, kr_chart.aggregate_daily_rows)
        self.assertIs(
            kr_service._aggregate_kr_index_daily_rows,
            kr_chart.aggregate_index_daily_rows,
        )

    def test_us_dedupe_prefers_more_complete_row(self) -> None:
        sparse = USDailyPrice(
            id=1,
            provider="alphavantage",
            symbol="AAPL",
            trade_date=date(2026, 7, 10),
            close_price=210.0,
            fetched_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )
        complete = USDailyPrice(
            id=2,
            provider="yahoo_chart",
            symbol="AAPL",
            trade_date=date(2026, 7, 10),
            open_price=208.0,
            high_price=212.0,
            low_price=207.0,
            close_price=211.0,
            trade_volume=100,
            fetched_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )

        rows = us_chart.dedupe_daily_rows_by_trade_date([sparse, complete])

        self.assertEqual(rows, [complete])

    def test_us_filter_excludes_daily_row_fetched_before_finalization(self) -> None:
        finalized = USDailyPrice(
            id=1,
            provider="yahoo_chart",
            symbol="AAPL",
            trade_date=date(2026, 7, 9),
            close_price=210.0,
            fetched_at=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
        )
        partial = USDailyPrice(
            id=2,
            provider="yahoo_chart",
            symbol="AAPL",
            trade_date=date(2026, 7, 10),
            close_price=211.0,
            fetched_at=datetime(2026, 7, 10, 14, 0, tzinfo=timezone.utc),
        )

        rows = us_chart.filter_ohlc_source_rows([finalized, partial])

        self.assertEqual(rows, [finalized])
        self.assertTrue(
            us_chart.has_newer_untrusted_rows(
                rows=[finalized, partial],
                trusted_rows=rows,
            )
        )

    def test_jp_weekly_projection_dedupes_and_aggregates(self) -> None:
        rows = [
            JPDailyPrice(
                id=1,
                provider="yahoo_chart",
                symbol="7203.T",
                trade_date=date(2026, 7, 6),
                open_price=2500,
                high_price=2550,
                low_price=2490,
                close_price=2530,
                trade_volume=100,
            ),
            JPDailyPrice(
                id=2,
                provider="yahoo_chart",
                symbol="7203.T",
                trade_date=date(2026, 7, 10),
                open_price=2540,
                high_price=2600,
                low_price=2520,
                close_price=2590,
                trade_volume=200,
            ),
        ]

        points = jp_chart.aggregate_daily_rows(rows, "weekly")

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["time"], date(2026, 7, 6))
        self.assertEqual(points[0]["open"], 2500)
        self.assertEqual(points[0]["close"], 2590)
        self.assertEqual(points[0]["volume"], 300)

    def test_kr_stock_and_index_projection_share_timeframe_contract(self) -> None:
        stock_rows = [
            KRDailyPrice(
                provider="krx_data",
                symbol="005930.KS",
                trade_date=date(2026, 7, 6),
                open_price=71000,
                high_price=73000,
                low_price=70500,
                close_price=72500,
                adjusted_close=72600,
                trade_volume=10,
            ),
            KRDailyPrice(
                provider="krx_data",
                symbol="005930.KS",
                trade_date=date(2026, 7, 10),
                open_price=72600,
                high_price=74000,
                low_price=72000,
                close_price=73800,
                trade_volume=20,
            ),
        ]
        index_rows = [
            KRIndexDailyPrice(
                provider="naver_sise_index",
                index_id="KOSPI",
                trade_date=date(2026, 7, 6),
                open_value=3100,
                high_value=3150,
                low_value=3090,
                close_value=3140,
                trade_volume=100,
            ),
            KRIndexDailyPrice(
                provider="naver_sise_index",
                index_id="KOSPI",
                trade_date=date(2026, 7, 10),
                open_value=3140,
                high_value=3200,
                low_value=3130,
                close_value=3190,
                trade_volume=200,
            ),
        ]

        stock_points = kr_chart.aggregate_daily_rows(stock_rows, "weekly")
        index_points = kr_chart.aggregate_index_daily_rows(index_rows, "weekly")

        self.assertEqual(stock_points[0]["close"], 73800)
        self.assertEqual(stock_points[0]["volume"], 30)
        self.assertEqual(index_points[0]["close"], 3190)
        self.assertEqual(index_points[0]["volume"], 300)


if __name__ == "__main__":
    unittest.main()
