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
            patch.object(intraday, "_upsert_market_intraday_bars", return_value=1),
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: load_trend(), range(2)))

        self.assertEqual(fetch_nstock.call_count, 1)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["point_count"], 1)

    def test_legacy_mis_snapshot_bar_masquerading_helpers_are_removed(self):
        self.assertFalse(hasattr(intraday, "_fetch_mis_message"))
        self.assertFalse(hasattr(intraday, "_fetch_mis_snapshot"))
        self.assertFalse(hasattr(intraday, "_apply_mis_volume_adjustment"))


if __name__ == "__main__":
    unittest.main()
