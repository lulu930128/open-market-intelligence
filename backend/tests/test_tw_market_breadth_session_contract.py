from __future__ import annotations

from datetime import date, datetime
import unittest
from app.market.providers import twse_mis_current_breadth
from app.market.trading_calendar import TAIWAN_TZ


class TaiwanMarketBreadthSessionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        twse_mis_current_breadth.reset_twse_mis_current_breadth_provider()

    def tearDown(self) -> None:
        twse_mis_current_breadth.reset_twse_mis_current_breadth_provider()

    @staticmethod
    def _message(**overrides: object) -> dict[str, object]:
        message: dict[str, object] = {
            "c": "2330",
            "d": "20260803",
            "t": "08:59:00",
            "y": "100",
            "z": "-",
            "pz": "110",
            "ts": "1",
            "v": "0",
            "u": "110",
            "w": "90",
            "o": "-",
            "h": "-",
            "l": "-",
        }
        message.update(overrides)
        return message

    def test_preopen_pz_is_indicative_and_not_formal_breadth(self) -> None:
        row = twse_mis_current_breadth._classify_message(
            self._message(),
            "TWSE",
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["market_session"], "preopen")
        self.assertEqual(row["price_semantics"], "unavailable")
        self.assertIsNone(row["price_source"])
        self.assertFalse(row["has_actual_trade"])
        self.assertIsNone(row["current_price"])
        self.assertIsNone(row["price_as_of"])
        self.assertIsNone(row["direction"])
        self.assertFalse(row["is_limit_up"])
        self.assertFalse(row["is_limit_down"])
        self.assertIsNone(row["estimated_trade_value"])
        self.assertTrue(row["indicative_match_available"])
        self.assertEqual(row["indicative_match_price"], 110)
        self.assertEqual(row["indicative_price_source"], "pz")
        self.assertEqual(
            row["state_contract_version"],
            "tw.market_breadth.stock_state.v2",
        )

    def test_regular_price_requires_actual_trade_and_preserves_price_time(self) -> None:
        actual_time = datetime(2026, 8, 3, 9, 0, tzinfo=TAIWAN_TZ)
        first = twse_mis_current_breadth._classify_message(
            self._message(t="09:00:00", z="101", pz="-", ts="0", v="5"),
            "TWSE",
        )
        cached = twse_mis_current_breadth._classify_message(
            self._message(t="09:01:00", z="-", pz="-", ts="0", v="5"),
            "TWSE",
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(cached)
        assert first is not None and cached is not None
        self.assertEqual(first["price_semantics"], "actual_trade")
        self.assertEqual(first["price_source"], "z")
        self.assertTrue(first["has_actual_trade"])
        self.assertEqual(first["price_as_of"], actual_time)
        self.assertEqual(first["direction"], "advance")
        self.assertEqual(first["estimated_trade_value"], 505_000)
        self.assertEqual(cached["current_price"], 101)
        self.assertEqual(cached["price_semantics"], "actual_trade")
        self.assertEqual(cached["price_source"], "session_cache")
        self.assertTrue(cached["has_actual_trade"])
        self.assertEqual(cached["price_as_of"], actual_time)
        self.assertEqual(
            cached["snapshot_as_of"],
            datetime(2026, 8, 3, 9, 1, tzinfo=TAIWAN_TZ),
        )

    def test_regular_z_without_positive_volume_is_not_actual_trade(self) -> None:
        row = twse_mis_current_breadth._classify_message(
            self._message(t="09:05:00", z="101", pz="-", ts="0", v="0"),
            "TWSE",
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertFalse(row["has_actual_trade"])
        self.assertIsNone(row["current_price"])
        self.assertIsNone(row["direction"])

    def test_ohlc_without_actual_trade_does_not_infer_direction(self) -> None:
        row = twse_mis_current_breadth._classify_message(
            self._message(
                t="09:05:00",
                z="-",
                pz="-",
                ts="0",
                v="0",
                o="99",
                h="99",
                l="95",
            ),
            "TWSE",
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertIsNone(row["direction"])

    def test_actual_trade_cache_does_not_cross_trade_date(self) -> None:
        twse_mis_current_breadth._classify_message(
            self._message(t="09:00:00", z="101", pz="-", ts="0", v="5"),
            "TWSE",
        )
        next_day = twse_mis_current_breadth._classify_message(
            self._message(
                d="20260804",
                t="08:59:00",
                z="-",
                pz="109",
                ts="1",
                v="0",
            ),
            "TWSE",
        )

        self.assertIsNotNone(next_day)
        assert next_day is not None
        self.assertFalse(next_day["has_actual_trade"])
        self.assertIsNone(next_day["current_price"])
        self.assertIsNone(next_day["price_as_of"])

    def test_reset_clears_actual_trade_state(self) -> None:
        twse_mis_current_breadth._classify_message(
            self._message(t="09:00:00", z="101", pz="-", ts="0", v="5"),
            "TWSE",
        )
        self.assertTrue(twse_mis_current_breadth._STOCK_STATE)

        twse_mis_current_breadth.reset_twse_mis_current_breadth_provider()

        self.assertFalse(twse_mis_current_breadth._STOCK_STATE)

    def test_preopen_aggregate_is_pending_with_separate_auction_contract(self) -> None:
        codes = [f"{1000 + index:04d}" for index in range(1, 502)]
        messages = [
            self._message(c=code, pz="101" if index % 2 == 0 else "99")
            for index, code in enumerate(codes)
        ]

        payload = twse_mis_current_breadth._build_payload(
            "TWSE",
            codes,
            messages,
            0,
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["status"], "pending_regular_session")
        self.assertEqual(payload["market_session"], "preopen")
        self.assertEqual(payload["coverage_count"], 0)
        self.assertEqual(payload["unknown_count"], len(codes))
        self.assertEqual(payload["advance_count"], 0)
        self.assertEqual(payload["decline_count"], 0)
        self.assertEqual(payload["unchanged_count"], 0)
        auction = payload["auction_breadth"]
        self.assertEqual(auction["status"], "provisional")
        self.assertFalse(auction["decision_usable"])
        self.assertEqual(auction["coverage_count"], len(codes))
        self.assertEqual(
            auction["advance_count"] + auction["decline_count"],
            len(codes),
        )
        self.assertEqual(payload["trade_date"], date(2026, 8, 3))


if __name__ == "__main__":
    unittest.main()
