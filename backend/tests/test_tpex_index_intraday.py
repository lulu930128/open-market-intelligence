from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.market import indices
from app.market.providers import tpex


TAIPEI_TZ = timezone(timedelta(hours=8))


class TpexIndexIntradayTests(unittest.TestCase):
    def setUp(self) -> None:
        indices._TWSE_INDEX_5S_CACHE.clear()

    def tearDown(self) -> None:
        indices._TWSE_INDEX_5S_CACHE.clear()

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

    def test_tpex_intraday_prefers_official_series_and_merges_final_mis(
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
            "previous_close": 334.24,
            "point_count": 2,
            "points": [
                {
                    "time": "2026-07-30T09:00:00+08:00",
                    "price": 334.24,
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

        with (
            patch.object(
                indices,
                "_fetch_twse_index_5s_intraday",
                return_value=official,
            ),
            patch.object(
                indices,
                "_fetch_mis_index_intraday",
                return_value=mis,
            ),
            patch.object(indices, "_fetch_yahoo_index_intraday") as yahoo,
        ):
            result = indices.get_market_index_intraday("TPEX")

        yahoo.assert_not_called()
        self.assertEqual(
            result["source"],
            "tpex_index_5s_twse_mis_snapshot",
        )
        self.assertEqual(result["point_count"], 3)
        self.assertEqual(result["points"][-1]["price"], 326.23)
        self.assertEqual(result["bar_contract_version"], "tw.intraday.bars.v2")
        self.assertTrue(
            all(point.get("bar_type") for point in result["points"])
        )
        self.assertTrue(
            all(point.get("close") is not None for point in result["points"])
        )
        self.assertEqual(
            result["points"][1]["bar_type"],
            "official_close_marker",
        )
        self.assertEqual(
            result["points"][-1]["bar_type"],
            "post_close_summary",
        )
        self.assertEqual(
            result["points"][-1]["market_event"],
            "post_close_confirmation",
        )
        self.assertEqual(result["post_close_summary_count"], 1)
        self.assertFalse(result["points"][-1]["indicator_eligible"])
        self.assertEqual(
            result["source_provenance"]["provider"],
            "tpex_index_5s",
        )

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
