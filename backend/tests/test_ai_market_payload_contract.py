from __future__ import annotations

import unittest

from app.ai.market_payload_contract import (
    bounded_int_param,
    has_payload_value,
    intraday_point_limit,
    payload_level,
    payload_slot_status,
    slot_envelope,
)


class MarketPayloadContractTests(unittest.TestCase):
    def test_payload_level_accepts_aliases_and_falls_back_to_compact(self) -> None:
        self.assertEqual(payload_level({"payload_level": "FULL"}), "full")
        self.assertEqual(payload_level({"detail_level": "summary"}), "summary")
        self.assertEqual(payload_level({"detail": "standard"}), "standard")
        self.assertEqual(payload_level({"payload_level": "huge"}), "compact")
        self.assertEqual(payload_level(None), "compact")

    def test_intraday_point_limit_uses_payload_defaults_and_bounds_overrides(self) -> None:
        self.assertEqual(intraday_point_limit({"payload_level": "summary"}), 1)
        self.assertEqual(intraday_point_limit({"payload_level": "standard"}), 160)
        self.assertEqual(intraday_point_limit({"payload_level": "full", "intraday_limit": 900}), 500)
        self.assertEqual(intraday_point_limit({"intraday_bar_limit": 0}), 1)
        self.assertEqual(intraday_point_limit({"point_limit": "12"}), 12)

    def test_bounded_int_param_skips_bad_values_and_preserves_default(self) -> None:
        self.assertEqual(
            bounded_int_param(
                {"limit": "bad", "fallback_limit": 7},
                ("limit", "fallback_limit"),
                default=3,
                minimum=1,
                maximum=10,
            ),
            7,
        )
        self.assertEqual(
            bounded_int_param({"limit": -5}, ("limit",), default=3, minimum=1, maximum=10),
            1,
        )

    def test_slot_envelope_deduplicates_optional_metadata(self) -> None:
        self.assertEqual(
            slot_envelope(
                status="partial",
                capability="quote",
                payload_ref="quote",
                payload_level="compact",
                as_of="2026-07-11",
                missing=["a", "a", "b"],
                warnings=["w", "w"],
            ),
            {
                "status": "partial",
                "capability": "quote",
                "priority": "support",
                "availability": "available",
                "freshness": {"status": "unknown"},
                "usability": "limited",
                "payload_ref": "quote",
                "payload_level": "compact",
                "as_of": "2026-07-11",
                "missing": ["a", "b"],
                "warnings": ["w"],
            },
        )

    def test_payload_presence_and_status_are_consistent(self) -> None:
        self.assertFalse(has_payload_value({"a": [], "b": {"c": ""}}))
        self.assertTrue(has_payload_value({"a": [None, {"b": 0}]}))
        self.assertEqual(payload_slot_status({}), "missing")
        self.assertEqual(payload_slot_status({"value": 1}, missing=["daily"]), "partial")
        self.assertEqual(payload_slot_status({"value": 1}, missing=["daily"], partial_if_missing=False), "ready")
        self.assertEqual(payload_slot_status({"value": 1}, not_applicable=True), "not_applicable")


if __name__ == "__main__":
    unittest.main()
