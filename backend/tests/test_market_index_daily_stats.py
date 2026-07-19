from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketDailyPrice, MarketIndexDailyStat, RawFetchResult, SourceRegistry
from app.jobs import scheduler as job_scheduler
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
            indices.refresh_market_index_daily_stats(
                db=self.db,
                index_id="TAIEX",
                from_date=date(2026, 1, 5),
                to_date=date(2026, 1, 6),
            )
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
            indices.refresh_market_index_daily_stats(
                db=self.db,
                index_id="TAIEX",
                from_date=date(2026, 1, 5),
                to_date=date(2026, 1, 11),
            )
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
            indices.refresh_market_index_daily_stats(
                db=self.db,
                index_id="TAIEX",
                from_date=date(2026, 6, 11),
                to_date=date(2026, 6, 15),
            )
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
            patch.object(indices, "_fetch_market_quote_breadth", return_value=stale_breadth),
            patch.object(indices, "_fetch_recent_index_trade_values", return_value={}),
            patch.object(indices, "_persist_shared_market_index_summary"),
        ):
            payload = indices.refresh_market_index_summary(
                db=self.db,
                refresh_daily_stats=True,
            )

        taiex = next(item for item in payload["indices"] if item["index_id"] == "TAIEX")
        self.assertIsNone(taiex["breadth"])
        self.assertEqual(taiex["breadth_status"]["status"], "failed")
        self.assertTrue(payload["warnings"])
        self.assertEqual(taiex["trade_value"], 1_045_439_448_015)
        self.assertEqual(taiex["close"], 44999.90)

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
        self.assertEqual(payload["cache_status"], "local_cache")
        self.assertTrue(payload["refresh_recommended"])

    def test_summary_cache_naive_timestamp_is_interpreted_as_utc(self) -> None:
        parsed = indices._summary_payload_as_of(
            {"as_of": "2026-07-18T15:10:58.728395"}
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset(), timedelta(0))

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
            payload = indices.get_market_index_ohlc_chart_data(
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
            patch.object(job_scheduler.settings, "scheduler_taiwan_market_index_interval_seconds", 5),
        ):
            enabled = job_scheduler._add_taiwan_market_index_collector_job(scheduler)

        self.assertTrue(enabled)
        scheduler.add_job.assert_called_once()
        self.assertEqual(scheduler.add_job.call_args.kwargs["seconds"], 5)
        self.assertEqual(
            scheduler.add_job.call_args.kwargs["id"],
            "taiwan_market_index_summary_collector",
        )

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

    def test_twse_mis_live_breadth_counts_classified_and_unknown_quotes(self) -> None:
        indices._TWSE_MIS_LIVE_BREADTH_CACHE.clear()
        indices._TWSE_MIS_STOCK_STATE.clear()
        codes = [f"{1000 + index:04d}" for index in range(1, 502)]
        messages = [
            {
                "c": "1001",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "101.00",
                "u": "110.00",
                "w": "90.00",
            },
            {
                "c": "1002",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "90.00",
                "u": "110.00",
                "w": "90.00",
            },
            {
                "c": "1003",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "100.00",
                "u": "110.00",
                "w": "90.00",
            },
            {
                "c": "1004",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "-",
                "h": "99.00",
                "l": "95.00",
            },
            {
                "c": "1005",
                "d": "20260709",
                "t": "09:05:00",
                "y": "100.00",
                "z": "-",
                "h": "105.00",
                "l": "95.00",
            },
        ]

        with (
            patch.object(indices, "_twse_mis_live_breadth_stock_codes", return_value=codes),
            patch.object(indices, "_fetch_twse_mis_stock_messages", return_value=(messages, 0)),
        ):
            payload = indices._fetch_twse_mis_live_market_breadth(self.db, "TWSE")

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["source"], "twse_mis_live_breadth_partial")
        self.assertEqual(payload["scope"], "registered_universe")
        self.assertEqual(payload["label"], "上市即時廣度（註冊範圍）")
        self.assertEqual(payload["trade_date"], date(2026, 7, 9))
        self.assertEqual(payload["advance_count"], 1)
        self.assertEqual(payload["decline_count"], 2)
        self.assertEqual(payload["unchanged_count"], 1)
        self.assertEqual(payload["limit_up_count"], 0)
        self.assertEqual(payload["limit_down_count"], 1)
        self.assertEqual(payload["coverage_count"], 4)
        self.assertEqual(payload["message_count"], 5)
        self.assertEqual(payload["missing_count"], 496)
        self.assertEqual(payload["unknown_count"], 497)
        self.assertIsNone(payload["trade_value"])
        self.assertTrue(payload["warnings"])

    def test_resolve_market_breadth_prefers_live_when_daily_source_is_stale(self) -> None:
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
        live_breadth = {
            "market": "TWSE",
            "trade_date": target_date,
            "advance_count": 300,
            "decline_count": 250,
            "unchanged_count": 50,
            "total_count": 1086,
            "limit_up_count": 3,
            "limit_down_count": 4,
            "trade_value": None,
            "coverage_count": 600,
            "unknown_count": 486,
            "source": "twse_mis_live_breadth_partial",
        }

        with (
            patch.object(indices, "_fetch_market_quote_breadth", return_value=stale_daily),
            patch.object(
                indices,
                "_fetch_twse_mis_live_market_breadth",
                return_value=live_breadth,
            ),
            patch.object(indices, "_latest_market_breadth", return_value=None),
        ):
            payload = indices._resolve_market_breadth(
                db=self.db,
                market="TWSE",
                target_trade_date=target_date,
            )

        self.assertEqual(payload, live_breadth)

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
            patch.object(
                indices,
                "_fetch_twse_index_5s_intraday",
                side_effect=ValueError("official unavailable"),
            ),
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
            patch.object(
                indices,
                "_fetch_twse_index_5s_intraday",
                side_effect=ValueError("official unavailable"),
            ),
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
            patch.object(
                indices,
                "_fetch_twse_index_5s_intraday",
                side_effect=ValueError("official unavailable"),
            ),
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
            patch.object(
                indices,
                "_fetch_twse_index_5s_intraday",
                side_effect=ValueError("official unavailable"),
            ),
            patch.object(indices, "_fetch_yahoo_index_intraday", return_value=yahoo_payload),
            patch.object(indices, "_fetch_mis_index_message", return_value=mis_message),
        ):
            payload = indices.get_market_index_intraday("TAIEX")

        self.assertEqual(payload, yahoo_payload)


if __name__ == "__main__":
    unittest.main()
