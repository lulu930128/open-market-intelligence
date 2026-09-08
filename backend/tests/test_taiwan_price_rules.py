from __future__ import annotations

import unittest

from app.market.taiwan_price_rules import (
    normalize_taiwan_stock_price,
    shift_taiwan_stock_price_by_ticks,
    taiwan_stock_tick_size,
)


class TaiwanPriceRulesTests(unittest.TestCase):
    def test_regular_stock_tick_bands(self) -> None:
        self.assertEqual(taiwan_stock_tick_size(9.99), 0.01)
        self.assertEqual(taiwan_stock_tick_size(10), 0.05)
        self.assertEqual(taiwan_stock_tick_size(50), 0.1)
        self.assertEqual(taiwan_stock_tick_size(100), 0.5)
        self.assertEqual(taiwan_stock_tick_size(500), 1.0)
        self.assertEqual(taiwan_stock_tick_size(1000), 5.0)

    def test_normalization_respects_band_boundaries(self) -> None:
        self.assertEqual(normalize_taiwan_stock_price(49.99, direction="up"), 50.0)
        self.assertEqual(normalize_taiwan_stock_price(50.04, direction="down"), 50.0)
        self.assertEqual(normalize_taiwan_stock_price(588.4), 588.0)
        self.assertEqual(normalize_taiwan_stock_price(588.6), 589.0)
        self.assertEqual(normalize_taiwan_stock_price(1002.6), 1005.0)

    def test_non_positive_price_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_taiwan_stock_price(0)

    def test_tick_shift_recomputes_tick_across_price_bands(self) -> None:
        self.assertEqual(shift_taiwan_stock_price_by_ticks(9.99, 2), 10.05)
        self.assertEqual(shift_taiwan_stock_price_by_ticks(10, -2), 9.98)
        self.assertEqual(shift_taiwan_stock_price_by_ticks(499.5, 2), 501.0)
        self.assertEqual(shift_taiwan_stock_price_by_ticks(500, -2), 499.0)
        self.assertEqual(shift_taiwan_stock_price_by_ticks(1000, -2), 998.0)
        self.assertEqual(shift_taiwan_stock_price_by_ticks(1000, 1), 1005.0)

    def test_tick_shift_does_not_cross_zero(self) -> None:
        self.assertEqual(shift_taiwan_stock_price_by_ticks(0.01, -10), 0.01)


if __name__ == "__main__":
    unittest.main()
