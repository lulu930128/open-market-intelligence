from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.market import indices
from app.market.providers import tpex
from app.market.schemas import IntradayTrendRead


TAIPEI_TZ = timezone(timedelta(hours=8))


class TpexIndexIntradayTests(unittest.TestCase):
    def setUp(self) -> None:
        indices._TWSE_INDEX_5S_CACHE.clear()
        indices._FINAL_INDEX_DAILY_OHLC_CACHE.clear()

    def tearDown(self) -> None:
        indices._TWSE_INDEX_5S_CACHE.clear()
        indices._FINAL_INDEX_DAILY_OHLC_CACHE.clear()

    @staticmethod
    def _official_payload(*, payload_date: str = "20260730") -> dict:
        return {
            "stat": "ok",
            "date": payload_date,
            "tables": [
                {
                    "title": "每 5 秒盤後統計",
                    "fields": ["時 間", "櫃買指數", "成交金額(萬元)"],
                    "data": [
                        ["09:00:00", "334.24", "0"],
                        ["09:00:05", "334.10", "25"],
                        ["13:30:00", "326.02", "18,000,000"],
                        ["99:99:99", "326.23", "18,046,239"],
                    ],
                }
            ],
        }

    def test_tpex_official_series_parses_usable_points_and_closing_summary(
        self,
    ) -> None:
        with patch.object(
            tpex,
            "fetch_index_5s_payload",
            return_value=self._official_payload(),
        ) as fetch:
            result = indices._fetch_twse_index_5s_intraday(
                indices.INDEX_CONFIG_BY_ID["TPEX"],
                trade_date=date(2026, 7, 30),
            )

        fetch.assert_called_once_with(
            date(2026, 7, 30),
            timeout_seconds=20,
            request=indices.http_get,
        )
        self.assertEqual(result["source"], "tpex_index_5s")
        self.assertEqual(result["provider"], tpex.INDEX_5S_PROVIDER)
        self.assertEqual(result["trade_date"], "2026-07-30")
        self.assertEqual(result["coverage_status"], "post_close_final_series")
        self.assertFalse(result["is_partial"])
        self.assertEqual(result["previous_close"], 334.24)
        self.assertEqual(result["point_count"], 3)
        self.assertEqual(
            result["points"][-1]["time"],
            "2026-07-30T13:30:00+08:00",
        )
        self.assertEqual(result["points"][-1]["price"], 326.02)
        self.assertEqual(
            result["source_provenance"]["closing_summary_value"],
            326.23,
        )
        self.assertEqual(
            result["source_provenance"]["closing_summary_time"],
            "provider_sentinel_99:99:99",
        )

    def test_tpex_official_series_rejects_wrong_trade_date(self) -> None:
        with (
            patch.object(
                tpex,
                "fetch_index_5s_payload",
                return_value=self._official_payload(payload_date="20260729"),
            ),
            self.assertRaisesRegex(ValueError, "returned 2026-07-29"),
        ):
            indices._fetch_twse_index_5s_intraday(
                indices.INDEX_CONFIG_BY_ID["TPEX"],
                trade_date=date(2026, 7, 30),
            )

    def test_tpex_intraday_merges_official_series_and_current_snapshot(
        self,
    ) -> None:
        official = {
            "stock_id": "TPEX",
            "symbol": "^TWOII",
            "source": "tpex_index_5s",
            "source_provenance": {
                "provider": "tpex_index_5s",
                "official": True,
            },
            "interval": "5s",
            "trade_date": "2026-07-30",
            "previous_close": 334.24,
            "point_count": 2,
            "points": [
                {
                    "time": "2026-07-30T09:00:00+08:00",
                    "price": 334.24,
                },
                {
                    "time": "2026-07-30T09:00:05+08:00",
                    "price": 334.10,
                },
                {
                    "time": "2026-07-30T13:30:00+08:00",
                    "price": 326.02,
                },
            ],
        }
        mis = {
            "stock_id": "TPEX",
            "symbol": "^TWOII",
            "source": "twse_mis_index_snapshot",
            "previous_close": 334.24,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-07-30T13:33:00+08:00",
                    "price": 326.23,
                    "volume": 1_914_434,
                }
            ],
        }

        result = indices._finalize_index_intraday_contract(
            indices._merge_index_intraday_snapshot(official, mis)
        )
        self.assertEqual(
            result["source"],
            "tpex_index_5s_twse_mis_snapshot",
        )
        self.assertEqual(result["source_point_count"], 4)
        self.assertEqual(result["source_interval"], "5s")
        self.assertEqual(result["effective_interval"], "1m")
        self.assertEqual(result["point_count"], 2)
        self.assertEqual(result["points"][-1]["price"], 326.23)
        self.assertEqual(result["points"][-1]["time"], "2026-07-30T13:30:00+08:00")
        self.assertEqual(result["current_observation"]["value"], 326.23)
        self.assertEqual(
            result["current_observation"]["price_semantics"],
            "official_index_close",
        )
        self.assertFalse(result["capabilities"]["supports_volume"])
        self.assertFalse(result["capabilities"]["supports_vwap"])
        self.assertEqual(result["bar_contract_version"], "tw.intraday.bars.v2")
        self.assertTrue(
            all(point.get("bar_type") for point in result["points"])
        )
        self.assertTrue(
            all(point.get("close") is not None for point in result["points"])
        )
        self.assertEqual(result["points"][0]["bar_type"], "regular_interval")
        self.assertTrue(result["points"][0]["display_eligible"])
        self.assertEqual(
            result["points"][-1]["bar_type"],
            "official_close_marker",
        )
        self.assertTrue(result["points"][-1]["indicator_eligible"])
        self.assertEqual(result["post_close_summary_count"], 1)
        self.assertFalse(
            any(
                point["bar_type"] == "post_close_summary"
                for point in result["points"]
            )
        )
        self.assertEqual(
            result["observations"][0]["price_semantics"],
            "post_close_confirmation",
        )
        self.assertEqual(
            result["source_provenance"]["provider"],
            "tpex_index_5s",
        )

    def test_tpex_intraday_discards_previous_session_before_newer_mis_snapshot(
        self,
    ) -> None:
        previous_session = {
            "stock_id": "TPEX",
            "symbol": "^TWOII",
            "source": "taiwan_index_minute_snapshot",
            "trade_date": "2026-08-05",
            "coverage_status": "single_snapshot",
            "is_partial": True,
            "previous_close": 378.50,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-08-05T13:30:00+08:00",
                    "price": 383.75,
                }
            ],
        }
        current_snapshot = {
            "stock_id": "TPEX",
            "symbol": "^TWOII",
            "source": "twse_mis_index_snapshot",
            "trade_date": "2026-08-06",
            "coverage_status": "single_snapshot",
            "is_partial": True,
            "previous_close": 383.75,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-08-06T13:33:00+08:00",
                    "price": 391.37,
                }
            ],
        }

        result = indices._finalize_index_intraday_contract(
            indices._merge_index_intraday_snapshot(
                previous_session,
                current_snapshot,
            )
        )

        self.assertEqual(result["trade_date"], "2026-08-06")
        self.assertEqual(result["point_count"], 1)
        self.assertEqual(
            result["points"][0]["time"],
            "2026-08-06T13:30:00+08:00",
        )
        self.assertTrue(result["is_partial"])
        self.assertTrue(result["warnings"])
        public_payload = IntradayTrendRead.model_validate(result).model_dump(
            mode="json"
        )
        self.assertEqual(public_payload["trade_date"], "2026-08-06")
        self.assertEqual(public_payload["coverage_status"], "single_snapshot")
        self.assertTrue(public_payload["warnings"])
        self.assertEqual(
            public_payload["points"][0]["bar_type"],
            "official_close_marker",
        )
        self.assertEqual(public_payload["current_observation"]["value"], 391.37)

    def test_official_tpex_summary_projects_to_canonical_1330_close(self) -> None:
        with patch.object(
            tpex,
            "fetch_index_5s_payload",
            return_value=self._official_payload(),
        ):
            raw = indices._fetch_twse_index_5s_intraday(
                indices.INDEX_CONFIG_BY_ID["TPEX"],
                trade_date=date(2026, 7, 30),
            )

        result = indices._finalize_index_intraday_contract(raw)

        self.assertEqual(result["source_interval"], "5s")
        self.assertEqual(result["effective_interval"], "1m")
        self.assertEqual(result["source_point_count"], 3)
        self.assertEqual(result["point_count"], 2)
        self.assertEqual(result["points"][-1]["time"], "2026-07-30T13:30:00+08:00")
        self.assertEqual(result["points"][-1]["price"], 326.23)
        self.assertEqual(result["source_provenance"]["raw_1330_value"], 326.02)
        self.assertEqual(
            result["source_provenance"]["canonical_close_value"],
            326.23,
        )
        self.assertEqual(result["current_observation"]["value"], 326.23)

    def test_dense_index_series_projects_minutes_and_excludes_auction_from_indicators(
        self,
    ) -> None:
        payload = {
            "stock_id": "TAIEX",
            "symbol": "^TWII",
            "source": "twse_index_5s_twse_mis_snapshot",
            "provider": "twse_index_5s",
            "interval": "5s",
            "trade_date": "2026-07-30",
            "previous_close": 100.0,
            "points": [
                {"time": "2026-07-30T09:00:00+08:00", "price": 100.0},
                {"time": "2026-07-30T09:00:05+08:00", "price": 101.0},
                {"time": "2026-07-30T09:00:55+08:00", "price": 102.0},
                {"time": "2026-07-30T09:01:00+08:00", "price": 103.0},
                {"time": "2026-07-30T13:25:00+08:00", "price": 104.0},
                {"time": "2026-07-30T13:25:55+08:00", "price": 105.0},
                {"time": "2026-07-30T13:30:00+08:00", "price": 106.0},
                {"time": "2026-07-30T13:33:00+08:00", "price": 106.0},
            ],
        }

        result = indices._finalize_index_intraday_contract(payload)

        self.assertEqual(result["source_point_count"], 8)
        self.assertEqual(result["point_count"], 4)
        self.assertLessEqual(result["point_count"], 271)
        self.assertEqual(result["points"][0]["open"], 101.0)
        self.assertEqual(result["points"][0]["close"], 102.0)
        auction = next(
            point
            for point in result["points"]
            if point["bar_type"] == "closing_auction"
        )
        self.assertTrue(auction["display_eligible"])
        self.assertFalse(auction["finalized"])
        self.assertFalse(auction["indicator_eligible"])
        self.assertTrue(result["points"][-1]["indicator_eligible"])
        self.assertFalse(
            any(point["time"].endswith("13:33:00+08:00") for point in result["points"])
        )

    def test_tpex_official_default_date_uses_presentation_session(self) -> None:
        payload = self._official_payload(payload_date="20260806")
        with (
            patch.object(
                indices,
                "taiwan_presentation_session",
                return_value={"trade_date": date(2026, 8, 6)},
            ),
            patch.object(tpex, "fetch_index_5s_payload", return_value=payload) as fetch,
        ):
            result = indices._fetch_twse_index_5s_intraday(
                indices.INDEX_CONFIG_BY_ID["TPEX"]
            )

        fetch.assert_called_once_with(
            date(2026, 8, 6),
            timeout_seconds=20,
            request=indices.http_get,
        )
        self.assertEqual(result["trade_date"], "2026-08-06")

    def test_summary_cache_does_not_mask_stale_tpex_with_current_taiex(
        self,
    ) -> None:
        now = datetime(2026, 7, 30, 18, 0, tzinfo=TAIPEI_TZ)
        payload = {
            "as_of": now,
            "source": "market_index_daily_stat",
            "indices": [
                {
                    "index_id": "TAIEX",
                    "market": "TWSE",
                    "time": date(2026, 7, 30),
                    "as_of": now,
                    "breadth": None,
                },
                {
                    "index_id": "TPEX",
                    "market": "TPEX",
                    "time": date(2026, 7, 29),
                    "as_of": now,
                    "breadth": None,
                },
            ],
            "warnings": [],
        }

        with patch.object(
            indices,
            "expected_daily_price_date",
            return_value=date(2026, 7, 30),
        ):
            result = indices._summary_cache_view(
                payload,
                origin="shared_cache",
                now=now,
            )

        self.assertTrue(result["refresh_recommended"])
        self.assertEqual(result["cache_status"], "stale_shared_cache")
        self.assertTrue(
            any("TPEX" in warning for warning in result["warnings"])
        )


if __name__ == "__main__":
    unittest.main()
