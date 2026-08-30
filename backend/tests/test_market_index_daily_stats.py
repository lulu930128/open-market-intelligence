from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketDailyPrice, MarketIndexDailyStat, RawFetchResult, SourceRegistry, StockMaster
from app.jobs import scheduler as job_scheduler
from app.market import index_parsers, indices
from app.market.official_index_contract import TWSE_INDEX_SOURCE_NAME
from app.market.providers import twse_mis_current_breadth, twse_mis_current_index


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


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class MarketIndexDailyStatTests(unittest.TestCase):
    def setUp(self) -> None:
        twse_mis_current_breadth.reset_twse_mis_current_breadth_provider()
        indices._FINAL_INDEX_DAILY_OHLC_CACHE.clear()
        self.db = make_session()

    def tearDown(self) -> None:
        twse_mis_current_breadth.reset_twse_mis_current_breadth_provider()
        indices._FINAL_INDEX_DAILY_OHLC_CACHE.clear()
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
            indices.refresh_market_index_daily_stats(
                db=self.db,
                index_id="TAIEX",
                from_date=date(2026, 1, 5),
                to_date=date(2026, 1, 6),
            )
            payload = indices.refresh_market_index_ohlc_chart_data(
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
            indices.refresh_market_index_daily_stats(
                db=self.db,
                index_id="TAIEX",
                from_date=date(2026, 1, 5),
                to_date=date(2026, 1, 11),
            )
            payload = indices.refresh_market_index_ohlc_chart_data(
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

    def test_tpex_post_close_index_list_parses_official_index_columns(self) -> None:
        rows = index_parsers.parse_tpex_post_close_index_list(
            {
                "stat": "ok",
                "date": "20260811",
                "tables": [
                    {
                        "fields": [
                            "時 間",
                            "紡纖纖維",
                            "半導體業",
                            "櫃買指數",
                            "成交金額(萬元)",
                        ],
                        "data": [
                            ["09:00:00", "107.37", "264.43", "391.61", "0"],
                            ["13:30:00", "108.20", "262.70", "391.09", "1"],
                            ["99:99:99", "108.29", "262.83", "391.68", "2"],
                        ],
                    }
                ],
            },
            expected_trade_date=date(2026, 8, 11),
        )

        self.assertEqual(
            [item["name"] for item in rows],
            ["櫃買指數", "紡織纖維", "半導體"],
        )
        self.assertEqual(rows[0]["close"], 391.68)
        self.assertAlmostEqual(rows[0]["change"], 0.07)
        self.assertAlmostEqual(rows[1]["change"], 0.92)
        self.assertAlmostEqual(rows[2]["change_pct"], (-1.60 / 264.43) * 100)
        self.assertEqual(rows[2]["trade_date"], date(2026, 8, 11))

    def test_tpex_post_close_index_list_rejects_non_final_or_wrong_date(self) -> None:
        payload = {
            "stat": "ok",
            "date": "20260811",
            "tables": [
                {
                    "fields": ["時 間", "櫃買指數"],
                    "data": [["09:00:00", "391.61"], ["13:30:00", "391.09"]],
                }
            ],
        }

        self.assertEqual(
            index_parsers.parse_tpex_post_close_index_list(payload),
            [],
        )
        payload["tables"][0]["data"].append(["99:99:99", "391.68"])
        self.assertEqual(
            index_parsers.parse_tpex_post_close_index_list(
                payload,
                expected_trade_date=date(2026, 8, 8),
            ),
            [],
        )

    def test_tpex_special_index_list_parsers_keep_native_change_semantics(self) -> None:
        tpex50 = index_parsers.parse_tpex50_index_list_item(
            [
                {"Date": "1150810", "TPEx50Index": "577.30"},
                {"Date": "1150811", "TPEx50Index": "579.83"},
            ]
        )
        tpex200 = index_parsers.parse_tpex200_index_list_item(
            [
                {
                    "資料日期": "1150811",
                    "指數": "富櫃200報酬指數",
                    "收盤指數": "22,906.73",
                    "漲跌": "+",
                    "漲跌點數": "44.04",
                    "漲跌百分比": "0.19",
                },
                {
                    "資料日期": "1150811",
                    "指數": "富櫃200指數",
                    "收盤指數": "18,135.88",
                    "漲跌": "-",
                    "漲跌點數": "34.87",
                    "漲跌百分比": "0.19",
                },
            ]
        )

        self.assertIsNotNone(tpex50)
        self.assertEqual(tpex50["name"], "富櫃五十指數")
        self.assertAlmostEqual(tpex50["change"], 2.53)
        self.assertAlmostEqual(tpex50["change_pct"], (2.53 / 577.30) * 100)
        self.assertEqual(tpex200["name"], "富櫃200指數")
        self.assertEqual(tpex200["change"], -34.87)
        self.assertEqual(tpex200["change_pct"], -0.19)

    def test_tpex_index_list_isolates_single_provider_failure(self) -> None:
        post_close_payload = {
            "stat": "ok",
            "date": "20260811",
            "tables": [
                {
                    "fields": ["時 間", "紡織纖維", "櫃買指數"],
                    "data": [
                        ["09:00:00", "107.37", "391.61"],
                        ["99:99:99", "108.29", "391.68"],
                    ],
                }
            ],
        }
        with (
            patch.object(
                indices,
                "latest_released_trading_day",
                return_value=date(2026, 8, 11),
            ),
            patch.object(
                indices.tpex,
                "fetch_json",
                return_value=[
                    {"Date": "1150811", "TPExIndex": "391.68", "Change": "0.07"}
                ],
            ),
            patch.object(
                indices.tpex,
                "fetch_index_5s_payload",
                return_value=post_close_payload,
            ),
            patch.object(
                indices.tpex,
                "fetch_tpex50_index_history_payload",
                return_value=[
                    {"Date": "1150810", "TPEx50Index": "577.30"},
                    {"Date": "1150811", "TPEx50Index": "579.83"},
                ],
            ),
            patch.object(
                indices.tpex,
                "fetch_tpex200_close_payload",
                side_effect=RuntimeError("provider unavailable"),
            ),
        ):
            items = indices._fetch_tpex_index_list()

        self.assertEqual(len(items), 25)
        self.assertEqual(items[0]["name"], "櫃買指數")
        self.assertEqual(items[0]["close"], 391.68)
        self.assertEqual(items[1]["name"], "富櫃200指數")
        self.assertIsNone(items[1]["close"])
        self.assertEqual(items[2]["name"], "富櫃五十指數")
        self.assertEqual(items[2]["close"], 579.83)
        self.assertEqual(items[3]["name"], "紡織纖維")
        self.assertEqual(items[3]["close"], 108.29)

    def test_twse_index_daily_ohlc_rows_parse_official_values(self) -> None:
        rows = indices._parse_twse_index_daily_ohlc_rows(
            {
                "stat": "OK",
                "fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"],
                "data": [
                    [
                        "115/07/30",
                        "40,048.94",
                        "41,155.42",
                        "39,404.65",
                        "39,933.30",
                    ],
                    ["115/07/31", "invalid", "1", "1", "1"],
                ],
            }
        )

        self.assertEqual(
            rows,
            [
                {
                    "trade_date": date(2026, 7, 30),
                    "open": 40048.94,
                    "high": 41155.42,
                    "low": 39404.65,
                    "close": 39933.3,
                }
            ],
        )

    def test_tpex_market_highlight_rows_normalize_official_units(self) -> None:
        rows = indices._parse_tpex_market_highlight_rows(
            {
                "stat": "ok",
                "date": "20260529",
                "tables": [
                    {
                        "fields": [
                            "上櫃家數",
                            "本日總成交值(佰萬元)",
                            "本日總成交股數(張數)",
                            "收市指數",
                            "指數漲跌",
                        ],
                        "data": [
                            ["888", "385,397", "1,570,935", "443.64", "11.16"]
                        ],
                    }
                ],
            },
            expected_trade_date=date(2026, 5, 29),
        )

        self.assertEqual(
            rows,
            [
                {
                    "trade_date": date(2026, 5, 29),
                    "trade_volume": 1_570_935_000,
                    "trade_value": 385_397_000_000,
                    "transaction_count": None,
                    "close_value": 443.64,
                    "price_change": 11.16,
                }
            ],
        )

    def test_tpex_history_refresh_fetches_only_missing_trading_dates(self) -> None:
        self.db.add(
            MarketIndexDailyStat(
                index_id="TPEX",
                market="TPEX",
                trade_date=date(2026, 5, 28),
                trade_volume=1,
                trade_value=1,
                source="existing",
            )
        )
        self.db.commit()

        def historical_row(trade_date: date):
            return (
                [
                    {
                        "trade_date": trade_date,
                        "trade_volume": 2_000,
                        "trade_value": 3_000,
                        "transaction_count": None,
                        "close_value": 400.0,
                        "price_change": 1.0,
                    }
                ],
                f"https://example.test/highlight?date={trade_date.isoformat()}",
            )

        with (
            patch.object(
                indices,
                "_fetch_tpex_market_daily_stat_for_date",
                side_effect=historical_row,
            ) as fetch,
            patch.object(
                indices,
                "_fetch_recent_market_index_daily_stats",
                return_value=[],
            ),
        ):
            result = indices.refresh_market_index_daily_stats(
                db=self.db,
                index_id="TPEX",
                from_date=date(2026, 5, 28),
                to_date=date(2026, 5, 30),
            )

        self.assertEqual(
            [call.args[0] for call in fetch.call_args_list],
            [date(2026, 5, 29)],
        )
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(result["source"], "tpex_after_trading_highlight")
        stored = (
            self.db.query(MarketIndexDailyStat)
            .filter(MarketIndexDailyStat.index_id == "TPEX")
            .order_by(MarketIndexDailyStat.trade_date.asc())
            .all()
        )
        self.assertEqual(
            [row.trade_date for row in stored],
            [date(2026, 5, 28), date(2026, 5, 29)],
        )
        self.assertEqual(stored[-1].trade_value, 3_000)

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
        official_ohlc = {
            date(2026, 6, 12): {
                "trade_date": date(2026, 6, 12),
                "open": 43_500.0,
                "high": 44_500.0,
                "low": 43_200.0,
                "close": 44_169.04,
            },
            date(2026, 6, 15): {
                "trade_date": date(2026, 6, 15),
                "open": 44_800.0,
                "high": 45_500.0,
                "low": 44_700.0,
                "close": 45_396.99,
            },
        }

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
            patch.object(
                indices,
                "_fetch_twse_index_daily_ohlc_for_month",
                return_value=official_ohlc,
            ),
        ):
            indices.refresh_market_index_daily_stats(
                db=self.db,
                index_id="TAIEX",
                from_date=date(2026, 6, 11),
                to_date=date(2026, 6, 15),
            )
            payload = indices.refresh_market_index_ohlc_chart_data(
                index_id="TAIEX",
                timeframe="daily",
                bars=2,
                db=self.db,
            )

        self.assertEqual([point["time"] for point in payload["points"]], [date(2026, 6, 12), date(2026, 6, 15)])
        self.assertEqual(payload["to_date"], date(2026, 6, 15))
        self.assertEqual(payload["points"][-1]["open"], 44_800.0)
        self.assertEqual(payload["points"][-1]["high"], 45_500.0)
        self.assertEqual(payload["points"][-1]["low"], 44_700.0)
        self.assertEqual(payload["points"][-1]["close"], 45396.99)
        self.assertEqual(payload["points"][-1]["trade_value"], 1_115_744_351_199)
        self.assertEqual(payload["latest_data_date"], date(2026, 6, 15))
        self.assertEqual(payload["expected_data_date"], date(2026, 6, 15))
        self.assertEqual(payload["freshness_status"], "current")
        self.assertTrue(payload["is_current"])
        self.assertFalse(payload["refresh_recommended"])
        self.assertEqual(
            payload["backfill"]["official_ohlc_overlay"]["status"],
            "success",
        )

    def test_daily_ohlc_does_not_synthesize_taiex_bar_when_official_ohlc_fails(
        self,
    ) -> None:
        self.db.add(
            MarketIndexDailyStat(
                index_id="TAIEX",
                market="TWSE",
                trade_date=date(2026, 6, 15),
                trade_volume=12_695_045_659,
                trade_value=1_115_744_351_199,
                transaction_count=900_000,
                close_value=45_396.99,
                price_change=1_227.95,
                source="twse_openapi_fmtqik",
            )
        )
        self.db.commit()
        yahoo_points = [
            yahoo_point(date(2026, 6, 11), 43_000.0),
            yahoo_point(date(2026, 6, 12), 44_169.04),
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
                "_fetch_twse_index_daily_ohlc_for_month",
                side_effect=RuntimeError("provider unavailable"),
            ),
            patch.object(indices, "observe_provider_fallback"),
        ):
            payload = indices.refresh_market_index_ohlc_chart_data(
                index_id="TAIEX",
                timeframe="daily",
                bars=2,
                db=self.db,
            )

        self.assertEqual(
            [point["time"] for point in payload["points"]],
            [date(2026, 6, 11), date(2026, 6, 12)],
        )
        self.assertEqual(payload["to_date"], date(2026, 6, 12))
        self.assertEqual(payload["freshness_status"], "stale")
        self.assertFalse(payload["is_current"])
        self.assertTrue(payload["refresh_recommended"])
        overlay = payload["backfill"]["official_ohlc_overlay"]
        self.assertEqual(overlay["status"], "unavailable")
        self.assertEqual(overlay["merged_date_count"], 0)
        self.assertEqual(overlay["missing_dates"], ["2026-06-15"])

    def test_tpex_daily_ohlc_uses_official_5s_values_when_yahoo_is_stale(
        self,
    ) -> None:
        self.db.add(
            MarketIndexDailyStat(
                index_id="TPEX",
                market="TPEX",
                trade_date=date(2026, 6, 15),
                trade_volume=100,
                trade_value=200,
                transaction_count=300,
                close_value=391.37,
                price_change=7.62,
                source="tpex_openapi_daily_trading_index",
            )
        )
        self.db.commit()
        yahoo_points = [
            yahoo_point(date(2026, 6, 11), 380.0),
            yahoo_point(date(2026, 6, 12), 383.75),
        ]
        official_ohlc = {
            "open": 383.72,
            "high": 391.96,
            "low": 378.50,
            "close": 391.37,
        }

        with (
            patch.object(
                indices,
                "_fetch_yahoo_index_points",
                return_value=(yahoo_points, {}, timezone(timedelta(hours=8))),
            ),
            patch.object(indices, "datetime", FixedDateTime),
            patch.object(
                indices,
                "_fetch_twse_index_5s_ohlc",
                return_value=official_ohlc,
            ),
        ):
            payload = indices.refresh_market_index_ohlc_chart_data(
                index_id="TPEX",
                timeframe="daily",
                bars=3,
                db=self.db,
            )

        latest = payload["points"][-1]
        self.assertEqual(latest["time"], date(2026, 6, 15))
        self.assertEqual(latest["open"], 383.72)
        self.assertEqual(latest["high"], 391.96)
        self.assertEqual(latest["low"], 378.50)
        self.assertEqual(latest["close"], 391.37)
        self.assertEqual(payload["data_quality"], "ok")
        self.assertEqual(
            payload["backfill"]["official_ohlc_overlay"]["status"],
            "success",
        )

    def test_tpex_daily_ohlc_omits_missing_official_bar_instead_of_synthesizing(
        self,
    ) -> None:
        self.db.add(
            MarketIndexDailyStat(
                index_id="TPEX",
                market="TPEX",
                trade_date=date(2026, 6, 15),
                trade_volume=100,
                trade_value=200,
                transaction_count=300,
                close_value=391.37,
                price_change=7.62,
                source="tpex_openapi_daily_trading_index",
            )
        )
        self.db.commit()
        yahoo_points = [
            yahoo_point(date(2026, 6, 11), 380.0),
            yahoo_point(date(2026, 6, 12), 383.75),
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
                "_fetch_twse_index_5s_ohlc",
                side_effect=RuntimeError("provider unavailable"),
            ),
            patch.object(indices, "observe_provider_fallback"),
        ):
            payload = indices.refresh_market_index_ohlc_chart_data(
                index_id="TPEX",
                timeframe="daily",
                bars=3,
                db=self.db,
            )

        self.assertEqual(payload["to_date"], date(2026, 6, 12))
        self.assertNotIn(date(2026, 6, 15), [point["time"] for point in payload["points"]])
        self.assertEqual(payload["data_quality"], "unavailable")
        self.assertTrue(payload["warnings"])
        self.assertEqual(
            payload["backfill"]["official_ohlc_overlay"]["missing_dates"],
            ["2026-06-15"],
        )

    def test_current_month_index_stat_refresh_updates_existing_same_day_row(self) -> None:
        self.db.add(
            MarketIndexDailyStat(
                index_id="TAIEX",
                market="TWSE",
                trade_date=date(2026, 6, 15),
                trade_volume=1,
                trade_value=1,
                transaction_count=1,
                close_value=100.0,
                price_change=1.0,
                source="twse_rwd_fmtqik",
            )
        )
        self.db.commit()

        official_rows = [
            {
                "trade_date": date(2026, 6, 15),
                "trade_volume": 12_695_045_659,
                "trade_value": 1_115_744_351_199,
                "transaction_count": 5_460_270,
                "close_value": 45396.99,
                "price_change": 1227.95,
            }
        ]

        with (
            patch.object(indices, "datetime", FixedDateTime),
            patch.object(
                indices,
                "_fetch_twse_market_daily_stats_for_month",
                return_value=(official_rows, "https://example.test/fmtqik"),
            ),
            patch.object(indices, "_fetch_recent_market_index_daily_stats", return_value=[]),
        ):
            result = indices.ensure_market_index_daily_stat_coverage(
                db=self.db,
                index_id="TAIEX",
                market="TWSE",
                from_date=date(2026, 6, 15),
                to_date=date(2026, 6, 15),
            )

        row = self.db.query(MarketIndexDailyStat).filter_by(index_id="TAIEX").one()
        self.assertIsNotNone(result)
        self.assertEqual(result["fetched_month_count"], 1)
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(row.trade_value, 1_115_744_351_199)
        self.assertEqual(row.close_value, 45396.99)

    def test_legacy_refresh_does_not_overwrite_platform_owned_index_row(self) -> None:
        source = SourceRegistry(
            source_name="TPEx Official Market Index Daily",
            source_type="api",
            category="market_data",
            parser_type="tpex.daily_trading_index.v1",
        )
        self.db.add(source)
        self.db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc),
            status_code=200,
            content_hash="canonical-tpex-index",
            parser_version="tpex.daily_trading_index.v1",
        )
        self.db.add(raw)
        self.db.flush()
        self.db.add(
            MarketIndexDailyStat(
                index_id="TPEX",
                market="TPEX",
                trade_date=date(2026, 8, 25),
                trade_volume=701_017_083,
                trade_value=168_782_272_071,
                transaction_count=809_034,
                close_value=389.41,
                price_change=3.31,
                source="tpex_openapi",
                source_url="https://example.test/canonical",
                source_id=source.id,
                raw_result_id=raw.id,
            )
        )
        self.db.commit()

        result = indices._persist_market_index_daily_stats(
            self.db,
            index_id="TPEX",
            market="TPEX",
            rows=[
                {
                    "trade_date": date(2026, 8, 25),
                    "trade_volume": 701_017_083,
                    "trade_value": 168_782_272_071,
                    "transaction_count": None,
                    "close_value": 389.41,
                    "price_change": 3.31,
                }
            ],
            source="tpex_openapi_daily_trading_index",
            source_url="https://example.test/legacy",
        )

        row = self.db.query(MarketIndexDailyStat).one()
        self.assertEqual(result["updated_count"], 0)
        self.assertEqual(result["skipped_platform_owned_count"], 1)
        self.assertEqual(row.transaction_count, 809_034)
        self.assertEqual(row.source, "tpex_openapi")
        self.assertEqual(row.raw_result_id, raw.id)

    def test_twse_rwd_market_breadth_parses_current_stock_counts_and_total_value(self) -> None:
        payload = {
            "stat": "OK",
            "date": "20260629",
            "tables": [
                {
                    "title": "115年06月29日 大盤統計資訊",
                    "fields": ["成交統計", "成交金額(元)", "成交股數(股)", "成交筆數"],
                    "data": [["總計(1~15)", "1,045,439,448,015", "11,210,546,174", "4,895,013"]],
                },
                {
                    "title": "漲跌證券數合計",
                    "fields": ["類型", "整體市場", "股票"],
                    "data": [
                        ["上漲(漲停)", "5,443(54)", "659(20)"],
                        ["下跌(跌停)", "5,296(321)", "322(5)"],
                        ["持平", "759", "74"],
                    ],
                },
            ],
        }

        with patch.object(indices, "_fetch_json", return_value=payload):
            breadth = indices._fetch_twse_rwd_market_quote_breadth(date(2026, 6, 29))

        self.assertEqual(breadth["trade_date"], date(2026, 6, 29))
        self.assertEqual(breadth["advance_count"], 659)
        self.assertEqual(breadth["decline_count"], 322)
        self.assertEqual(breadth["unchanged_count"], 74)
        self.assertEqual(breadth["limit_up_count"], 20)
        self.assertEqual(breadth["limit_down_count"], 5)
        self.assertEqual(breadth["total_count"], 1055)
        self.assertEqual(breadth["trade_value"], 1_045_439_448_015)
        self.assertEqual(breadth["scope"], "full_market")
        self.assertEqual(breadth["label"], "上市全市場廣度")

    def test_market_breadth_does_not_use_stale_quote_for_current_index_date(self) -> None:
        stale_breadth = {
            "market": "TWSE",
            "trade_date": date(2026, 6, 26),
            "advance_count": 75,
            "decline_count": 980,
            "unchanged_count": 34,
            "total_count": 1089,
            "limit_up_count": 7,
            "limit_down_count": 29,
            "trade_value": 1_669_027_830_690,
            "source": "twse_openapi_stock_day_all",
        }

        with patch.object(indices, "_fetch_market_quote_breadth", return_value=stale_breadth):
            breadth = indices._resolve_market_breadth(
                db=self.db,
                market="TWSE",
                target_trade_date=date(2026, 6, 29),
            )

        self.assertIsNone(breadth)

    def test_market_index_summary_keeps_official_stat_value_when_breadth_is_stale(self) -> None:
        self.db.add(
            MarketIndexDailyStat(
                index_id="TAIEX",
                market="TWSE",
                trade_date=date(2026, 6, 29),
                trade_volume=11_210_546_174,
                trade_value=1_045_439_448_015,
                transaction_count=4_895_013,
                close_value=44999.90,
                price_change=428.14,
                source="twse_rwd_fmtqik",
            )
        )
        self.db.commit()

        stale_breadth = {
            "market": "TWSE",
            "trade_date": date(2026, 6, 26),
            "advance_count": 75,
            "decline_count": 980,
            "unchanged_count": 34,
            "total_count": 1089,
            "trade_value": 1_669_027_830_690,
            "source": "twse_openapi_stock_day_all",
        }

        def fake_yahoo_index(config: dict) -> dict:
            return {
                "index_id": config["index_id"],
                "label": config["label"],
                "short_label": config["short_label"],
                "market": config["market"],
                "symbol": config["symbol"],
                "source": "yahoo_finance_chart",
                "as_of": datetime(2026, 6, 29, 13, 30, tzinfo=timezone(timedelta(hours=8))),
                "time": date(2026, 6, 29),
                "open": 44594.81,
                "high": 45521.63,
                "low": 44594.81,
                "close": 44999.90,
                "previous_close": 44571.76,
                "change": 428.14,
                "change_pct": 0.96,
                "volume": None,
                "estimated_volume": None,
                "trade_value": None,
                "estimated_trade_value": None,
                "ma20": None,
                "price_vs_ma20": None,
                "point_count": 0,
                "points": [],
                "error_message": None,
            }

        with (
            patch.object(indices, "_fetch_yahoo_index", side_effect=fake_yahoo_index),
            patch.object(indices, "_ensure_market_index_daily_stat_coverage", return_value=None),
            patch.object(indices, "_fetch_twse_index_5s_ohlc", return_value=None),
            patch.object(indices, "_apply_latest_official_index_snapshot", return_value=False),
            patch.object(indices, "_fetch_market_quote_breadth", return_value=stale_breadth),
            patch.object(indices, "_fetch_recent_index_trade_values", return_value={}),
            patch.object(indices, "_persist_shared_market_index_summary"),
        ):
            payload = indices._market_index_summary(
                db=self.db,
                force_refresh=True,
                refresh_daily_stats=True,
            )

        taiex = next(item for item in payload["indices"] if item["index_id"] == "TAIEX")
        self.assertIsNone(taiex["breadth"])
        self.assertEqual(taiex["breadth_status"]["status"], "failed")
        self.assertTrue(payload["warnings"])
        self.assertEqual(taiex["trade_value"], 1_045_439_448_015)
        self.assertEqual(taiex["close"], 44999.90)

    def test_legacy_summary_does_not_relabel_current_breadth_as_completed(self) -> None:
        target_date = date(2026, 7, 22)
        stale_index_date = date(2026, 7, 17)
        resolved_targets: list[tuple[str, date | None]] = []

        def fake_yahoo_index(config: dict) -> dict:
            return {
                "index_id": config["index_id"],
                "label": config["label"],
                "short_label": config["short_label"],
                "market": config["market"],
                "symbol": config["symbol"],
                "source": "yahoo_finance_chart",
                "as_of": datetime(2026, 7, 17, 13, 30, tzinfo=timezone(timedelta(hours=8))),
                "time": stale_index_date,
                "close": 378.44,
                "trade_value": None,
                "points": [],
            }

        def fake_resolve(*, db, market: str, target_trade_date: date | None):
            del db
            resolved_targets.append((market, target_trade_date))
            return {
                "market": market,
                "scope": "full_market",
                "trade_date": target_date,
                "advance_count": 535,
                "decline_count": 257,
                "unchanged_count": 74,
                "total_count": 866,
                "trade_value": 186_314_449_680,
                "source": "official_market_breadth",
            }

        with (
            patch.object(indices, "_fetch_yahoo_index", side_effect=fake_yahoo_index),
            patch.object(indices, "_apply_latest_official_market_index_stat"),
            patch.object(indices, "_apply_latest_official_index_snapshot", return_value=False),
            patch.object(indices, "_market_breadth_target_date", return_value=target_date),
            patch.object(indices, "_resolve_market_breadth", side_effect=fake_resolve),
            patch.object(indices, "_fetch_recent_index_trade_values", return_value={}),
            patch.object(indices, "_persist_shared_market_index_summary"),
        ):
            payload = indices._market_index_summary(
                db=self.db,
                force_refresh=True,
            )

        self.assertEqual(
            resolved_targets,
            [("TWSE", target_date), ("TPEX", target_date)],
        )
        tpex = next(item for item in payload["indices"] if item["index_id"] == "TPEX")
        self.assertEqual(tpex["time"], stale_index_date)
        self.assertEqual(tpex["breadth"]["trade_date"], target_date)
        self.assertEqual(tpex["breadth_status"]["status"], "ready")
        self.assertNotIn("data_core_projection_scope", tpex)

    def test_get_index_summary_never_refreshes_provider_even_with_legacy_flag(self) -> None:
        original_cache = dict(indices._CACHE)
        indices._CACHE["payload"] = None
        indices._CACHE["expires_at"] = 0.0
        try:
            with (
                patch.object(indices, "_load_shared_market_index_summary", return_value=(None, None)),
                patch.object(indices, "_fetch_yahoo_index") as fetch_yahoo,
                patch.object(indices, "_fetch_market_quote_breadth") as fetch_breadth,
            ):
                payload = indices.get_market_index_summary(
                    db=self.db,
                    force_refresh=True,
                )
        finally:
            indices._CACHE.clear()
            indices._CACHE.update(original_cache)

        fetch_yahoo.assert_not_called()
        fetch_breadth.assert_not_called()
        self.assertEqual(payload["cache_status"], "canonical_cache")
        self.assertTrue(payload["refresh_recommended"])

    def test_summary_cache_naive_timestamp_is_interpreted_as_utc(self) -> None:
        parsed = indices._summary_payload_as_of(
            {"as_of": "2026-07-18T15:10:58.728395"}
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_summary_cache_recommends_bounded_post_close_reconciliation(self) -> None:
        taipei = timezone(timedelta(hours=8))
        trade_date = date(2026, 7, 20)
        payload = {
            "as_of": datetime(2026, 7, 20, 13, 40, tzinfo=taipei),
            "source": "yahoo_finance_chart",
            "warnings": [],
            "indices": [
                {
                    "index_id": config["index_id"],
                    "market": config["market"],
                    "time": trade_date,
                    "as_of": datetime(2026, 7, 20, 13, 30, tzinfo=taipei),
                    "breadth": {
                        "market": config["market"],
                        "scope": "full_market",
                        "trade_date": trade_date,
                        "source": "official_market_breadth",
                    },
                }
                for config in indices.INDEX_CONFIGS
            ],
        }
        payload["indices"][0]["as_of"] = datetime(
            2026,
            7,
            20,
            13,
            19,
            tzinfo=taipei,
        )
        payload["indices"][0]["breadth"] = None

        waiting_view = indices._summary_cache_view(
            payload,
            origin="shared_cache",
            now=datetime(2026, 7, 20, 13, 42, tzinfo=taipei),
        )
        due_view = indices._summary_cache_view(
            payload,
            origin="shared_cache",
            now=datetime(2026, 7, 20, 13, 46, tzinfo=taipei),
        )

        self.assertFalse(waiting_view["refresh_recommended"])
        self.assertTrue(due_view["refresh_recommended"])
        self.assertEqual(due_view["cache_status"], "stale_shared_cache")
        self.assertTrue(
            any("post-close reconciliation" in item for item in due_view["warnings"])
        )

        payload["indices"][0]["as_of"] = datetime(
            2026,
            7,
            20,
            13,
            30,
            tzinfo=taipei,
        )
        payload["indices"][0]["breadth"] = {
            "market": "TWSE",
            "scope": "full_market",
            "trade_date": trade_date,
            "source": "twse_rwd_mi_index",
        }
        complete_view = indices._summary_cache_view(
            payload,
            origin="shared_cache",
            now=datetime(2026, 7, 20, 13, 46, tzinfo=taipei),
        )

        self.assertFalse(complete_view["refresh_recommended"])

    def test_breadth_status_contract_marks_partial_coverage(self) -> None:
        payload = indices._with_breadth_status_contract(
            {
                "indices": [
                    {
                        "index_id": "TAIEX",
                        "market": "TWSE",
                        "breadth": {
                            "scope": "registered_universe",
                            "source": "twse_mis_live_breadth_partial",
                            "unknown_count": 3,
                            "warnings": ["Three quotes were unavailable."],
                        },
                    }
                ],
                "warnings": [],
            }
        )

        self.assertEqual(payload["indices"][0]["breadth_status"]["status"], "partial")
        self.assertIn("TAIEX market breadth is partial.", payload["warnings"])

    def test_ohlc_read_path_does_not_write_daily_stat_coverage(self) -> None:
        points = [
            yahoo_point(date(2026, 6, day), 100.0 + day)
            for day in range(1, 21)
        ]
        with (
            patch.object(
                indices,
                "_fetch_yahoo_index_points",
                return_value=(points, {}, timezone(timedelta(hours=8))),
            ),
            patch.object(indices, "_ensure_market_index_daily_stat_coverage") as ensure_coverage,
        ):
            payload = indices.refresh_market_index_ohlc_chart_data(
                index_id="TAIEX",
                timeframe="daily",
                bars=20,
                db=self.db,
            )

        ensure_coverage.assert_not_called()
        self.assertEqual(payload["backfill"]["status"], "not_requested")
        self.assertEqual(
            payload["backfill"]["reason"],
            "read_path_is_side_effect_free",
        )

    def test_market_index_scheduler_registers_five_second_collector(self) -> None:
        scheduler = Mock()
        with (
            patch.object(job_scheduler.settings, "enable_taiwan_market_index_scheduler", True),
            patch.object(job_scheduler.settings, "enable_taiwan_market_breadth_scheduler", True),
            patch.object(job_scheduler.settings, "scheduler_taiwan_market_index_interval_seconds", 5),
            patch.object(job_scheduler.settings, "scheduler_taiwan_market_breadth_interval_seconds", 60),
        ):
            enabled = job_scheduler._add_taiwan_market_index_collector_job(scheduler)

        self.assertTrue(enabled)
        self.assertEqual(scheduler.add_job.call_count, 4)
        collector_call, breadth_call, reconciliation_call, startup_call = scheduler.add_job.call_args_list
        self.assertEqual(collector_call.kwargs["seconds"], 5)
        self.assertEqual(
            collector_call.kwargs["id"],
            "taiwan_market_index_summary_collector",
        )
        self.assertEqual(breadth_call.kwargs["seconds"], 60)
        self.assertEqual(
            breadth_call.kwargs["id"],
            "taiwan_market_breadth_summary_collector",
        )
        self.assertEqual(reconciliation_call.kwargs["minutes"], 5)
        self.assertEqual(
            reconciliation_call.kwargs["id"],
            "taiwan_market_index_summary_reconcile",
        )
        self.assertEqual(startup_call.kwargs["trigger"], "date")
        self.assertEqual(
            startup_call.kwargs["id"],
            "taiwan_market_index_summary_startup_catchup",
        )

    def test_market_index_reconciliation_refreshes_only_incomplete_cache(self) -> None:
        db = Mock()
        cached_payload = {"indices": []}
        refreshed_payload = {
            "as_of": "2026-07-20T13:45:00+08:00",
            "indices": [{"index_id": "TAIEX"}, {"index_id": "TPEX"}],
        }
        with (
            patch.object(job_scheduler, "SessionLocal", return_value=db),
            patch.object(
                job_scheduler,
                "get_market_index_summary",
                return_value=cached_payload,
            ),
            patch.object(
                job_scheduler,
                "market_index_summary_needs_reconciliation",
                return_value=True,
            ),
            patch.object(
                job_scheduler,
                "refresh_market_index_summary",
                return_value=refreshed_payload,
            ) as refresh_summary,
            patch.object(
                job_scheduler,
                "_reconcile_taiwan_official_index_rows",
                return_value=[],
            ),
        ):
            job_scheduler.reconcile_taiwan_market_index_summary(
                now=datetime(
                    2026,
                    7,
                    20,
                    13,
                    45,
                    tzinfo=timezone(timedelta(hours=8)),
                )
            )

        refresh_summary.assert_called_once_with(
            db=db,
            refresh_daily_stats=True,
        )
        db.close.assert_called_once()

    def test_official_index_reconciliation_repairs_only_missing_lineage_rows(
        self,
    ) -> None:
        db = Mock()
        requested_at = datetime(
            2026,
            8,
            28,
            15,
            20,
            tzinfo=timezone(timedelta(hours=8)),
        )
        missing = Mock()
        missing.resolved.market_index = None
        refreshed = Mock()
        refreshed.postcondition_satisfied = True
        refreshed.persistence.raw_result_ids = (101,)
        with (
            patch.object(
                job_scheduler,
                "expected_daily_price_date",
                return_value=date(2026, 8, 28),
            ),
            patch.object(
                job_scheduler,
                "read_taiwan_official_index",
                side_effect=(missing, missing),
            ),
            patch.object(
                job_scheduler,
                "refresh_taiwan_official_index",
                side_effect=(refreshed, refreshed),
            ) as refresh_official,
        ):
            result = job_scheduler._reconcile_taiwan_official_index_rows(
                db,
                requested_at=requested_at,
            )

        self.assertEqual(refresh_official.call_count, 2)
        self.assertEqual(
            [item["index_id"] for item in result],
            ["TAIEX", "TPEX"],
        )
        self.assertTrue(all(item["status"] == "refreshed" for item in result))
        self.assertTrue(all(item["raw_result_ids"] == [101] for item in result))

    def test_twse_index_5s_intraday_parses_official_index_series(self) -> None:
        indices._TWSE_INDEX_5S_CACHE.clear()
        payload = {
            "stat": "OK",
            "date": "20260629",
            "fields": ["時間", "發行量加權股價指數"],
            "data": [
                ["09:00:00", "44,571.76"],
                ["09:00:05", "44,594.81"],
                ["13:30:00", "44,999.90"],
            ],
        }

        with patch.object(indices, "http_get", return_value=FakeResponse(payload)):
            result = indices._fetch_twse_index_5s_intraday(
                {
                    "index_id": "TAIEX",
                    "symbol": "^TWII",
                },
                trade_date=date(2026, 6, 29),
            )

        self.assertEqual(result["source"], "twse_index_5s")
        self.assertEqual(result["previous_close"], 44571.76)
        self.assertEqual(result["point_count"], 3)
        self.assertEqual(result["points"][0]["time"], "2026-06-29T09:00:00+08:00")
        self.assertEqual(result["points"][0]["price"], 44571.76)
        self.assertEqual(result["points"][-1]["price"], 44999.90)
        self.assertTrue(result["is_partial"])
        self.assertEqual(result["coverage_status"], "current_session_partial")

    def test_official_index_ohlc_excludes_opening_reference_and_uses_closing_summary(
        self,
    ) -> None:
        official = {
            "previous_close": 383.75,
            "is_partial": False,
            "source_provenance": {"closing_summary_value": 391.37},
            "points": [
                {"time": "2026-08-06T09:00:00+08:00", "price": 383.75},
                {"time": "2026-08-06T09:00:05+08:00", "price": 383.72},
                {"time": "2026-08-06T10:00:00+08:00", "price": 391.96},
                {"time": "2026-08-06T11:00:00+08:00", "price": 378.50},
                {"time": "2026-08-06T13:30:00+08:00", "price": 391.27},
            ],
        }

        with patch.object(
            indices,
            "_fetch_twse_index_5s_intraday",
            return_value=official,
        ) as fetch_intraday:
            result = indices._fetch_twse_index_5s_ohlc(
                indices.INDEX_CONFIG_BY_ID["TPEX"],
                date(2026, 8, 6),
            )
            cached_result = indices._fetch_twse_index_5s_ohlc(
                indices.INDEX_CONFIG_BY_ID["TPEX"],
                date(2026, 8, 6),
            )

        self.assertEqual(
            result,
            {
                "open": 383.72,
                "high": 391.96,
                "low": 378.50,
                "close": 391.37,
            },
        )
        self.assertEqual(cached_result, result)
        fetch_intraday.assert_called_once()

    def test_summary_overlay_uses_newer_official_index_snapshot(self) -> None:
        taipei = timezone(timedelta(hours=8))
        trade_date = date(2026, 7, 20)
        payload = {
            "source": "yahoo_finance_chart",
            "as_of": datetime(2026, 7, 20, 13, 19, 50, tzinfo=taipei),
            "time": trade_date,
            "open": 42793.15,
            "high": 43084.51,
            "low": 41967.75,
            "close": 42793.15,
            "previous_close": 42671.27,
            "change": 121.88,
            "change_pct": 0.29,
            "volume": None,
            "trade_value": 1_041_457_434_398,
            "ma20": None,
            "point_count": 1,
            "points": [
                yahoo_point(trade_date, 42793.15),
            ],
        }
        official = {
            "source": "twse_index_5s",
            "previous_close": 42671.27,
            "coverage_status": "current_session_series",
            "is_partial": False,
            "points": [
                {"time": "2026-07-20T09:00:00+08:00", "price": 42671.27},
                {"time": "2026-07-20T09:00:05+08:00", "price": 42793.15},
                {"time": "2026-07-20T10:00:00+08:00", "price": 43084.51},
                {"time": "2026-07-20T11:00:00+08:00", "price": 41967.75},
                {"time": "2026-07-20T13:30:00+08:00", "price": 42449.70},
            ],
        }

        with patch.object(
            indices,
            "_fetch_twse_index_5s_intraday",
            return_value=official,
        ):
            applied = indices._apply_latest_official_index_snapshot(
                config=indices.INDEX_CONFIG_BY_ID["TAIEX"],
                payload=payload,
                now=datetime(2026, 7, 20, 13, 45, tzinfo=taipei),
            )

        self.assertTrue(applied)
        self.assertEqual(payload["as_of"], datetime(2026, 7, 20, 13, 30, tzinfo=taipei))
        self.assertEqual(payload["close"], 42449.70)
        self.assertEqual(payload["open"], 42793.15)
        self.assertEqual(payload["high"], 43084.51)
        self.assertEqual(payload["low"], 41967.75)
        self.assertAlmostEqual(payload["change"], -221.57)
        self.assertIn("twse_index_5s_snapshot", payload["source"])
        self.assertEqual(payload["points"][-1]["close"], 42449.70)

    def test_twse_mis_live_breadth_counts_classified_and_unknown_quotes(self) -> None:
        codes = [f"{1000 + index:04d}" for index in range(1, 502)]
        messages = [
            {
                "c": "1001",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "101.00",
                "v": "1",
                "u": "110.00",
                "w": "90.00",
            },
            {
                "c": "1002",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "90.00",
                "v": "1",
                "u": "110.00",
                "w": "90.00",
            },
            {
                "c": "1003",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "100.00",
                "v": "1",
                "u": "110.00",
                "w": "90.00",
            },
            {
                "c": "1004",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "-",
                "v": "0",
                "h": "99.00",
                "l": "95.00",
            },
            {
                "c": "1005",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "-",
                "v": "0",
                "h": "105.00",
                "l": "95.00",
            },
        ]

        with patch.object(
            twse_mis_current_breadth,
            "_fetch_messages",
            return_value=(messages, 0),
        ):
            result = twse_mis_current_breadth.read_twse_mis_current_breadth(
                "TWSE",
                10,
                universe_reader=lambda _market: codes,
            )
        payload = result.payload

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["source"], "twse_mis_live_breadth_partial")
        self.assertEqual(
            payload["scope"],
            "full_market_registered_stock_universe",
        )
        self.assertEqual(payload["label"], "上市即時廣度（註冊範圍）")
        self.assertEqual(payload["trade_date"], date(2026, 7, 9))
        self.assertEqual(payload["advance_count"], 1)
        self.assertEqual(payload["decline_count"], 1)
        self.assertEqual(payload["unchanged_count"], 1)
        self.assertEqual(payload["limit_up_count"], 0)
        self.assertEqual(payload["limit_down_count"], 1)
        self.assertEqual(payload["coverage_count"], 3)
        self.assertEqual(payload["message_count"], 5)
        self.assertEqual(payload["missing_count"], 496)
        self.assertEqual(payload["unknown_count"], 498)
        self.assertEqual(
            payload["universe_definition"]["missing_quote_policy"],
            "unknown_not_unchanged",
        )
        self.assertFalse(
            payload["universe_definition"]["official_full_market"]
        )
        self.assertEqual(payload["trade_value"], 291_000)
        self.assertTrue(payload["trade_value_is_estimate"])
        self.assertTrue(payload["warnings"])

    def test_completed_breadth_does_not_fallback_to_current_provider(self) -> None:
        target_date = date(2026, 7, 9)
        stale_daily = {
            "market": "TWSE",
            "trade_date": date(2026, 7, 8),
            "advance_count": 100,
            "decline_count": 200,
            "unchanged_count": 10,
            "total_count": 1086,
            "limit_up_count": 1,
            "limit_down_count": 2,
            "trade_value": 123,
            "source": "twse_rwd_mi_index",
        }
        with (
            patch.object(indices, "_fetch_market_quote_breadth", return_value=stale_daily),
            patch.object(indices, "_latest_market_breadth", return_value=None),
        ):
            payload = indices._resolve_market_breadth(
                db=self.db,
                market="TWSE",
                target_trade_date=target_date,
            )

        self.assertIsNone(payload)

    def test_index_contributions_prefer_newer_local_daily_prices(self) -> None:
        source = SourceRegistry(
            source_name="TWSE OpenAPI Daily Trading",
            source_type="openapi",
            category="market",
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        raw_result = RawFetchResult(source_id=source.id, status_code=200)
        self.db.add(raw_result)
        self.db.flush()
        self.db.add_all(
            [
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="2383",
                    stock_name="台光電",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                ),
                MarketDailyPrice(
                    source_id=source.id,
                    raw_result_id=raw_result.id,
                    trade_date=date(2026, 6, 15),
                    stock_id="2330",
                    stock_name="台積電",
                    open_price=90.0,
                    high_price=105.0,
                    low_price=89.0,
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
                    open_price=55.0,
                    high_price=56.0,
                    low_price=49.0,
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
            payload = indices.refresh_market_index_contributions(
                "TAIEX",
                limit=5,
                db=self.db,
            )

        self.assertEqual(payload["source"], "tw.daily.ohlcv:TWSE")
        self.assertEqual(payload["trade_date"], date(2026, 6, 15))
        self.assertEqual(payload["index_close"], 120.0)
        self.assertEqual(payload["positive"][0]["stock_id"], "2330")
        self.assertEqual(payload["negative"][0]["stock_id"], "2383")
        self.assertFalse(payload["is_official"])
        self.assertEqual(payload["method_version"], "v1")
        self.assertEqual(payload["contribution_unit"], "index_points")
        self.assertEqual(payload["trade_value_unit"], "TWD")
        self.assertEqual(
            payload["positive"][0]["trade_value_unit"],
            "TWD",
        )
        self.assertGreater(payload["component_universe_count"], 0)
        self.assertGreater(payload["covered_component_count"], 0)
        self.assertIn(
            payload["reconciliation_status"],
            {"within_tolerance", "outside_tolerance", "unavailable"},
        )

    def test_index_get_surfaces_do_not_call_provider_acquisition(self) -> None:
        indices._INDEX_LIST_CACHE.clear()
        indices._INDEX_OHLC_CACHE.clear()
        indices._CONTRIBUTION_CACHE.clear()

        with (
            patch.object(
                indices,
                "_fetch_twse_index_list",
                side_effect=AssertionError("GET index list called provider"),
            ),
            patch.object(
                indices,
                "_fetch_yahoo_index_points",
                side_effect=AssertionError("GET index OHLC called provider"),
            ),
            patch.object(
                indices,
                "_source_contribution_quote_rows",
                side_effect=AssertionError("GET contribution called provider"),
            ),
            patch.object(
                indices,
                "_market_index_item_for_contribution",
                side_effect=AssertionError("GET contribution called index provider"),
            ),
        ):
            index_list = indices.get_market_index_list("TWSE")
            chart = indices.get_market_index_ohlc_chart_data(
                "TAIEX",
                db=self.db,
            )
            contributions = indices.get_market_index_contributions(
                "TAIEX",
                db=self.db,
            )

        self.assertEqual(index_list["source"], "cache_miss")
        self.assertEqual(chart["data_quality"], "missing")
        self.assertEqual(contributions["source"], "tw.daily.ohlcv:TWSE")

    def test_index_chart_uses_only_release_qualified_canonical_rows(self) -> None:
        source = SourceRegistry(
            source_name=TWSE_INDEX_SOURCE_NAME,
            source_type="official",
            category="market_index_daily",
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc),
            method="GET",
            content_hash="canonical-index-chart",
            parser_version="index-chart-test-v1",
        )
        self.db.add(raw)
        self.db.flush()
        self.db.add_all(
            [
                MarketIndexDailyStat(
                    source_id=source.id,
                    raw_result_id=raw.id,
                    index_id="TAIEX",
                    market="TWSE",
                    trade_date=date(2026, 6, 15),
                    close_value=22_000,
                    price_change=100,
                    trade_volume=1_000,
                    trade_value=2_000,
                    transaction_count=30,
                    source=TWSE_INDEX_SOURCE_NAME,
                ),
                MarketIndexDailyStat(
                    index_id="TAIEX",
                    market="TWSE",
                    trade_date=date(2026, 6, 16),
                    close_value=99_999,
                    price_change=77_999,
                    source="unqualified-storage-row",
                ),
            ]
        )
        self.db.commit()
        indices._INDEX_OHLC_CACHE.clear()

        chart = indices.get_market_index_ohlc_chart_data(
            "TAIEX",
            bars=20,
            db=self.db,
        )

        self.assertEqual(chart["point_count"], 1)
        self.assertEqual(chart["latest_data_date"], date(2026, 6, 15))
        self.assertEqual(chart["points"][0]["close"], 22_000)
        self.assertNotEqual(chart["points"][0]["close"], 99_999)

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

        with patch.object(
            twse_mis_current_index.twse_mis,
            "fetch_index_message",
            return_value=mis_message,
        ):
            mis_result = twse_mis_current_index.read_twse_mis_current_index(
                "TAIEX",
                10,
            )
        assert mis_result.payload is not None
        payload = indices._finalize_index_intraday_contract(
            indices._merge_index_intraday_snapshot(
                yahoo_payload,
                mis_result.payload,
            )
        )

        self.assertEqual(payload["source"], "yahoo_finance_chart_twse_mis_snapshot")
        self.assertEqual(payload["previous_close"], 46255.26)
        self.assertEqual(payload["point_count"], 2)
        self.assertEqual(payload["points"][-1]["time"], "2026-06-26T09:48:00+08:00")
        self.assertEqual(payload["points"][-1]["price"], 45430.31)
        self.assertIsNone(payload["points"][-1]["volume"])
        self.assertEqual(payload["source_point_count"], 2)
        self.assertEqual(payload["effective_interval"], "1m")
        self.assertFalse(payload["capabilities"]["supports_volume"])

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

        with patch.object(
            twse_mis_current_index.twse_mis,
            "fetch_index_message",
            return_value=mis_message,
        ):
            mis_result = twse_mis_current_index.read_twse_mis_current_index(
                "TAIEX",
                10,
            )
        assert mis_result.payload is not None
        payload = indices._finalize_index_intraday_contract(
            indices._merge_index_intraday_snapshot(
                yahoo_payload,
                mis_result.payload,
            )
        )

        self.assertEqual(payload["source"], "twse_mis_index_snapshot")
        self.assertEqual(payload["point_count"], 1)
        self.assertEqual(payload["points"][0]["price"], 45430.31)

    def test_index_intraday_keeps_yahoo_data_when_mis_is_unavailable(self) -> None:
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

        with patch.object(
            twse_mis_current_index.twse_mis,
            "fetch_index_message",
            side_effect=ConnectionError("mis offline"),
        ):
            mis_result = twse_mis_current_index.read_twse_mis_current_index(
                "TAIEX",
                10,
            )
        self.assertEqual(mis_result.status, "failed")
        payload = indices._finalize_index_intraday_contract(yahoo_payload)

        self.assertEqual(payload["source"], yahoo_payload["source"])
        self.assertEqual(payload["previous_close"], yahoo_payload["previous_close"])
        self.assertEqual(payload["point_count"], 1)
        self.assertEqual(payload["points"][0]["time"], "2026-06-26T09:40:00+08:00")
        self.assertEqual(payload["points"][0]["price"], 45605.52)
        self.assertEqual(payload["bar_contract_version"], "tw.intraday.bars.v2")
        self.assertEqual(payload["points"][0]["volume_status"], "not_provided")

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

        with patch.object(
            twse_mis_current_index.twse_mis,
            "fetch_index_message",
            return_value=mis_message,
        ):
            mis_result = twse_mis_current_index.read_twse_mis_current_index(
                "TAIEX",
                10,
            )
        assert mis_result.payload is not None
        payload = indices._finalize_index_intraday_contract(
            indices._merge_index_intraday_snapshot(
                yahoo_payload,
                mis_result.payload,
            )
        )

        self.assertEqual(payload["source"], yahoo_payload["source"])
        self.assertEqual(payload["previous_close"], yahoo_payload["previous_close"])
        self.assertEqual(payload["point_count"], 1)
        self.assertEqual(payload["points"][0]["time"], "2026-06-26T09:50:00+08:00")
        self.assertEqual(payload["points"][0]["price"], 45500.0)
        self.assertEqual(payload["bar_contract_version"], "tw.intraday.bars.v2")
        self.assertEqual(payload["points"][0]["volume_status"], "not_provided")


if __name__ == "__main__":
    unittest.main()
