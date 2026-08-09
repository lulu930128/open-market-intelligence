from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.market import intraday


class IntradayTrendTests(unittest.TestCase):
    def setUp(self):
        with intraday._INTRADAY_CACHE_LOCK:
            intraday._INTRADAY_CACHE.clear()
            intraday._INTRADAY_FETCH_LOCKS.clear()

    def test_concurrent_requests_share_one_provider_fetch(self):
        start_barrier = Barrier(2)
        provider_result = {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "nstock_minute_stock_data",
            "previous_close": 100.0,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-07-13T13:30:00+08:00",
                    "price": 101.0,
                    "volume": 1000,
                }
            ],
        }

        def fetch_provider(*, stock_id: str):
            self.assertEqual(stock_id, "2330")
            time.sleep(0.1)
            return provider_result

        def load_trend():
            start_barrier.wait(timeout=2)
            return intraday.get_intraday_trend(db=object(), stock_id="2330")

        with (
            patch.object(
                intraday,
                "_get_stock",
                return_value=SimpleNamespace(market="TWSE"),
            ),
            patch.object(
                intraday,
                "_fetch_nstock_intraday",
                side_effect=fetch_provider,
            ) as fetch_nstock,
            patch.object(intraday, "_fetch_mis_message", return_value=None),
            patch.object(intraday, "_upsert_market_intraday_bars", return_value=1),
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: load_trend(), range(2)))

        self.assertEqual(fetch_nstock.call_count, 1)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["point_count"], 1)

    def test_mis_actual_trade_can_advance_history_without_tv(self):
        result = {
            "stock_id": "2330",
            "source": "nstock_minute_stock_data",
            "point_count": 1,
            "points": [
                {
                    "time": "2026-08-05T09:04:00+08:00",
                    "price": 2395.0,
                    "volume": 1000,
                }
            ],
        }

        adjusted = intraday._apply_mis_volume_adjustment(
            result,
            {
                "d": "20260805",
                "t": "09:05:00",
                "ts": "0",
                "z": "2400",
                "tv": "-",
                "v": "3141",
            },
        )

        self.assertTrue(adjusted["current_trade_available"])
        self.assertTrue(adjusted["current_price_applied_to_history"])
        self.assertEqual(adjusted["latest_history_price"], 2395.0)
        self.assertEqual(adjusted["latest_actual_trade_price"], 2400.0)
        self.assertEqual(adjusted["lag_seconds"], 60.0)
        self.assertEqual(adjusted["points"][-1]["price"], 2400.0)
        self.assertIsNone(adjusted["points"][-1]["volume"])
        self.assertEqual(adjusted["current_observation"]["value"], 2400.0)
        self.assertEqual(
            adjusted["current_observation"]["price_semantics"],
            "actual_trade",
        )
        self.assertTrue(adjusted["capabilities"]["supports_volume"])

    def test_mis_volume_without_z_does_not_create_null_price_point(self):
        result = {
            "stock_id": "2330",
            "source": "nstock_minute_stock_data",
            "point_count": 1,
            "points": [
                {
                    "time": "2026-08-05T09:04:00+08:00",
                    "price": 2395.0,
                    "volume": 1000,
                }
            ],
        }

        adjusted = intraday._apply_mis_volume_adjustment(
            result,
            {
                "d": "20260805",
                "t": "09:05:00",
                "ts": "0",
                "z": "-",
                "tv": "5",
                "v": "3141",
                "pz": "2400",
            },
        )

        self.assertFalse(adjusted["current_trade_available"])
        self.assertEqual(
            adjusted["current_trade_unavailable_reason"],
            "ACTUAL_TRADE_PRICE_MISSING",
        )
        self.assertEqual(adjusted["point_count"], 1)
        self.assertEqual(adjusted["points"][-1]["price"], 2395.0)
        self.assertEqual(adjusted["current_observation"]["value"], 2395.0)
        self.assertEqual(
            adjusted["current_observation"]["price_semantics"],
            "intraday_bar_close",
        )

    def test_mis_trial_price_does_not_replace_history(self):
        result = {
            "stock_id": "2330",
            "source": "nstock_minute_stock_data",
            "point_count": 1,
            "points": [
                {
                    "time": "2026-08-05T08:59:00+08:00",
                    "price": 2390.0,
                    "volume": 0,
                }
            ],
        }

        adjusted = intraday._apply_mis_volume_adjustment(
            result,
            {
                "d": "20260805",
                "t": "08:59:55",
                "ts": "1",
                "z": "2395",
                "pz": "2400",
                "tv": "5",
                "v": "3141",
            },
        )

        self.assertFalse(adjusted["current_trade_available"])
        self.assertEqual(
            adjusted["current_trade_unavailable_reason"],
            "AUCTION_INDICATIVE_ONLY",
        )
        self.assertEqual(adjusted["points"][-1]["price"], 2390.0)


if __name__ == "__main__":
    unittest.main()
