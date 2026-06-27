from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketDailyPrice, MarketIndexDailyStat, RawFetchResult, SourceRegistry
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


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 6, 15, 18, 0, tzinfo=tz or timezone.utc)


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

    def test_tpex_daily_rows_parse_tpex_index_close(self) -> None:
        rows = indices._parse_tpex_market_daily_rows(
            [
                {
                    "Date": "2026/06/15",
                    "TradeVolume": "1,188,371,725",
                    "TradeAmount": "225,151,077,847",
                    "Transaction": "668,067",
                    "TPExIndex": "429.37",
                    "Change": "9.65",
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trade_date"], date(2026, 6, 15))
        self.assertEqual(rows[0]["close_value"], 429.37)
        self.assertEqual(rows[0]["price_change"], 9.65)

    def test_daily_ohlc_appends_newer_official_index_stat_when_yahoo_is_stale(self) -> None:
        yahoo_points = [
            yahoo_point(date(2026, 6, 11), 43000),
            yahoo_point(date(2026, 6, 12), 44169.04),
        ]
        official_rows = [
            {
                "trade_date": date(2026, 6, 12),
                "trade_volume": 12_336_471_343,
                "trade_value": 1_169_186_958_350,
                "transaction_count": 1_000_000,
                "close_value": 44169.04,
                "price_change": 1019.58,
            },
            {
                "trade_date": date(2026, 6, 15),
                "trade_volume": 12_695_045_659,
                "trade_value": 1_115_744_351_199,
                "transaction_count": 900_000,
                "close_value": 45396.99,
                "price_change": 1227.95,
            },
        ]

        with (
            patch.object(
                indices,
                "_fetch_yahoo_index_points",
                return_value=(yahoo_points, {}, timezone(timedelta(hours=8))),
            ),
            patch.object(indices, "datetime", FixedDateTime),
            patch.object(
                indices,
                "_fetch_twse_market_daily_stats_for_month",
                return_value=([], "https://example.test/fmtqik"),
            ),
            patch.object(indices, "_fetch_recent_market_index_daily_stats", return_value=official_rows),
        ):
            payload = indices.get_market_index_ohlc_chart_data(
                index_id="TAIEX",
                timeframe="daily",
                bars=2,
                db=self.db,
            )

        self.assertEqual([point["time"] for point in payload["points"]], [date(2026, 6, 12), date(2026, 6, 15)])
        self.assertEqual(payload["to_date"], date(2026, 6, 15))
        self.assertEqual(payload["points"][-1]["close"], 45396.99)
        self.assertEqual(payload["points"][-1]["trade_value"], 1_115_744_351_199)

    def test_index_contributions_prefer_newer_local_daily_prices(self) -> None:
        source = SourceRegistry(
            source_name="TWSE OpenAPI Daily Trading",
            source_type="openapi",
            category="market",
        )
        self.db.add(source)
        self.db.flush()
        raw_result = RawFetchResult(source_id=source.id, status_code=200)
        self.db.add(raw_result)
        self.db.flush()
        self.db.add_all(
            [
                MarketDailyPrice(
                    source_id=source.id,
                    raw_result_id=raw_result.id,
                    trade_date=date(2026, 6, 15),
                    stock_id="2330",
                    stock_name="台積電",
                    close_price=100.0,
                    price_change=10.0,
                    trade_value=1000,
                ),
                MarketDailyPrice(
                    source_id=source.id,
                    raw_result_id=raw_result.id,
                    trade_date=date(2026, 6, 15),
                    stock_id="2383",
                    stock_name="台光電",
                    close_price=50.0,
                    price_change=-5.0,
                    trade_value=800,
                ),
                MarketIndexDailyStat(
                    index_id="TAIEX",
                    market="TWSE",
                    trade_date=date(2026, 6, 15),
                    close_value=120.0,
                    price_change=12.0,
                    source="twse_openapi_fmtqik",
                ),
            ]
        )
        self.db.commit()

        stale_rows = [
            {
                "Code": "2330",
                "Name": "台積電",
                "ClosingPrice": "90",
                "Change": "1",
                "TradeValue": "100",
                "Date": "2026-06-12",
            }
        ]

        with (
            patch.object(
                indices,
                "_source_contribution_quote_rows",
                return_value=(
                    stale_rows,
                    {"2330": 1000, "2383": 1000},
                    "twse_openapi_stock_day_all+t187ap03_L",
                    {
                        "code": "Code",
                        "name": "Name",
                        "close": "ClosingPrice",
                        "change": "Change",
                        "trade_value": "TradeValue",
                        "date": "Date",
                    },
                ),
            ),
            patch.object(
                indices,
                "_market_index_item_for_contribution",
                return_value={
                    "close": 90.0,
                    "change": 1.0,
                    "trade_date": date(2026, 6, 12),
                },
            ),
        ):
            payload = indices.get_market_index_contributions("TAIEX", limit=5, db=self.db)

        self.assertEqual(payload["source"], "market_daily_price:TWSE OpenAPI Daily Trading")
        self.assertEqual(payload["trade_date"], date(2026, 6, 15))
        self.assertEqual(payload["index_close"], 120.0)
        self.assertEqual(payload["positive"][0]["stock_id"], "2330")
        self.assertEqual(payload["negative"][0]["stock_id"], "2383")

    def test_index_intraday_overlays_mis_snapshot_on_yahoo_history(self) -> None:
        yahoo_payload = {
            "stock_id": "TAIEX",
            "symbol": "^TWII",
            "source": "yahoo_finance_chart",
            "previous_close": 46255.26,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-06-26T09:40:10+08:00",
                    "price": 45605.52,
                    "volume": None,
                    "open": 46188.60,
                    "high": 46188.60,
                    "low": 45332.22,
                }
            ],
        }
        mis_message = {
            "d": "20260626",
            "t": "09:48:25",
            "z": "45430.31",
            "y": "46255.26",
            "o": "46188.60",
            "h": "46188.60",
            "l": "45332.22",
            "m": "4911549",
        }

        with (
            patch.object(indices, "_fetch_yahoo_index_intraday", return_value=yahoo_payload),
            patch.object(indices, "_fetch_mis_index_message", return_value=mis_message),
        ):
            payload = indices.get_market_index_intraday("TAIEX")

        self.assertEqual(payload["source"], "yahoo_finance_chart_twse_mis_snapshot")
        self.assertEqual(payload["previous_close"], 46255.26)
        self.assertEqual(payload["point_count"], 2)
        self.assertEqual(payload["points"][-1]["time"], "2026-06-26T09:48:25+08:00")
        self.assertEqual(payload["points"][-1]["price"], 45430.31)
        self.assertEqual(payload["points"][-1]["volume"], 4_911_549)

    def test_index_intraday_returns_mis_snapshot_when_yahoo_has_no_points(self) -> None:
        yahoo_payload = {
            "stock_id": "TAIEX",
            "symbol": "^TWII",
            "source": "yahoo_finance_chart",
            "previous_close": None,
            "point_count": 0,
            "points": [],
        }
        mis_message = {
            "d": "20260626",
            "t": "09:48:25",
            "z": "45430.31",
            "y": "46255.26",
            "o": "46188.60",
            "h": "46188.60",
            "l": "45332.22",
        }

        with (
            patch.object(indices, "_fetch_yahoo_index_intraday", return_value=yahoo_payload),
            patch.object(indices, "_fetch_mis_index_message", return_value=mis_message),
        ):
            payload = indices.get_market_index_intraday("TAIEX")

        self.assertEqual(payload["source"], "twse_mis_index_snapshot")
        self.assertEqual(payload["point_count"], 1)
        self.assertEqual(payload["points"][0]["price"], 45430.31)

    def test_index_intraday_keeps_yahoo_payload_when_mis_is_unavailable(self) -> None:
        yahoo_payload = {
            "stock_id": "TAIEX",
            "symbol": "^TWII",
            "source": "yahoo_finance_chart",
            "previous_close": 46255.26,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-06-26T09:40:10+08:00",
                    "price": 45605.52,
                    "volume": None,
                    "open": 46188.60,
                    "high": 46188.60,
                    "low": 45332.22,
                }
            ],
        }

        with (
            patch.object(indices, "_fetch_yahoo_index_intraday", return_value=yahoo_payload),
            patch.object(indices, "_fetch_mis_index_message", side_effect=ConnectionError("mis offline")),
        ):
            payload = indices.get_market_index_intraday("TAIEX")

        self.assertEqual(payload, yahoo_payload)

    def test_index_intraday_ignores_older_mis_snapshot(self) -> None:
        yahoo_payload = {
            "stock_id": "TAIEX",
            "symbol": "^TWII",
            "source": "yahoo_finance_chart",
            "previous_close": 46255.26,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-06-26T09:50:00+08:00",
                    "price": 45500.0,
                    "volume": None,
                    "open": 46188.60,
                    "high": 46188.60,
                    "low": 45332.22,
                }
            ],
        }
        mis_message = {
            "d": "20260626",
            "t": "09:48:25",
            "z": "45430.31",
            "y": "46255.26",
            "o": "46188.60",
            "h": "46188.60",
            "l": "45332.22",
        }

        with (
            patch.object(indices, "_fetch_yahoo_index_intraday", return_value=yahoo_payload),
            patch.object(indices, "_fetch_mis_index_message", return_value=mis_message),
        ):
            payload = indices.get_market_index_intraday("TAIEX")

        self.assertEqual(payload, yahoo_payload)


if __name__ == "__main__":
    unittest.main()
