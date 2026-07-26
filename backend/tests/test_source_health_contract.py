from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import date, timezone

from app.observability.source_health_contract import (
    daily_row_status,
    freshness_lag_days,
    generated_at,
    summarize_source_health,
)


@dataclass(frozen=True)
class _Entry:
    status: str
    ok: bool
    recent_error_count: int = 0


class SourceHealthContractTests(unittest.TestCase):
    def test_generated_at_is_timezone_aware_utc(self) -> None:
        value = generated_at()
        self.assertEqual(value.tzinfo, timezone.utc)

    def test_freshness_lag_is_bounded_at_zero(self) -> None:
        self.assertEqual(
            freshness_lag_days(date(2026, 7, 10), date(2026, 7, 8)),
            2,
        )
        self.assertEqual(
            freshness_lag_days(date(2026, 7, 10), date(2026, 7, 11)),
            0,
        )
        self.assertIsNone(freshness_lag_days(None, date(2026, 7, 11)))

    def test_daily_row_status_preserves_empty_stale_and_current_contract(self) -> None:
        common = {
            "empty_reason": "empty",
            "current_reason": "current",
            "available_reason": "available",
        }
        self.assertEqual(
            daily_row_status(
                row_count=0,
                latest_data_date=None,
                **common,
            ),
            ("empty", False, "empty", "empty"),
        )
        stale = daily_row_status(
            row_count=1,
            latest_data_date=date(2026, 7, 9),
            expected_data_date=date(2026, 7, 10),
            freshness_required=True,
            **common,
        )
        self.assertEqual(stale[:3], ("stale", False, "stale"))
        self.assertIn("2026-07-09", stale[3])
        self.assertEqual(
            daily_row_status(
                row_count=1,
                latest_data_date=date(2026, 7, 10),
                expected_data_date=date(2026, 7, 10),
                freshness_required=True,
                **common,
            ),
            ("current", True, "ok", "current"),
        )

    def test_summary_supports_dataclass_and_mapping_entries(self) -> None:
        summary = summarize_source_health(
            [
                _Entry(status="current", ok=True),
                _Entry(status="stale", ok=False),
                {"status": "disabled", "ok": False},
            ],
            counted_statuses=("empty", "stale", "error", "disabled"),
        )
        self.assertEqual(
            summary,
            {
                "entry_count": 3,
                "ok_count": 1,
                "empty_count": 0,
                "stale_count": 1,
                "error_count": 0,
                "disabled_count": 1,
            },
        )

    def test_summary_can_count_error_status_family_and_recent_errors(self) -> None:
        summary = summarize_source_health(
            [
                _Entry(status="rate_limited", ok=False),
                _Entry(status="current", ok=True, recent_error_count=2),
                _Entry(status="current", ok=True),
            ],
            counted_statuses=("error",),
            error_statuses={"error", "rate_limited"},
            count_recent_errors=True,
        )
        self.assertEqual(summary["error_count"], 2)


if __name__ == "__main__":
    unittest.main()
