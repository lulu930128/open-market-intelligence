from __future__ import annotations

from datetime import date, datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from app.market.technical_evidence import (
    _snapshot_for_timeframe,
    indicator_method_catalog,
)
from app.market.technical_intraday_projection import build_current_partial_daily_bar
from app.market.technical_parameters import get_technical_analysis_parameters


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _daily_points(count: int, *, end: date = date(2026, 8, 12)) -> list[dict]:
    start = end - timedelta(days=count - 1)
    return [
        {
            "time": start + timedelta(days=index),
            "open": 100 + index,
            "high": 102 + index,
            "low": 98 + index,
            "close": 101 + index,
            "volume": 1_000_000 + index * 10_000,
        }
        for index in range(count)
    ]


def _quote(*, phase: str = "regular") -> dict:
    return {
        "trade_date": "2026-08-13",
        "event_time": "2026-08-13T10:31:00+08:00",
        "provider": "twse_mis",
        "session_phase": phase,
        "last_trade_is_current_session": True,
        "actual_trade_occurred": True,
        "open_price": 151.0,
        "high_price": 158.0,
        "low_price": 149.0,
        "last_trade_price": 156.0,
        "cumulative_volume_shares": 12_000_000,
        "volume_source": "twse_mis",
    }


class TechnicalIntradayProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.completed = _daily_points(50)
        self.intraday = [
            {
                "time": datetime(2026, 8, 13, 9, 1, tzinfo=TAIPEI_TZ),
                "open": 151.0,
                "high": 153.0,
                "low": 150.0,
                "close": 152.0,
                "volume": 1_000_000,
            },
            {
                "time": datetime(2026, 8, 13, 10, 30, tzinfo=TAIPEI_TZ),
                "open": 152.0,
                "high": 157.0,
                "low": 151.0,
                "close": 155.0,
                "volume": 2_000_000,
            },
        ]

    def test_current_session_quote_and_bars_build_non_persisted_partial(self) -> None:
        partial = build_current_partial_daily_bar(
            completed_daily_points=self.completed,
            intraday_points=self.intraday,
            quote=_quote(),
            session_date=date(2026, 8, 13),
            session_phase="regular",
        )

        self.assertIsNotNone(partial)
        assert partial is not None
        self.assertEqual(partial["bar_status"], "intraday_partial")
        self.assertEqual(partial["open"], 151.0)
        self.assertEqual(partial["high"], 158.0)
        self.assertEqual(partial["low"], 149.0)
        self.assertEqual(partial["close"], 156.0)
        self.assertEqual(partial["volume"], 12_000_000)
        self.assertEqual(partial["volume_semantics"], "session_cumulative_partial")

    def test_no_current_session_trade_does_not_promote_previous_close(self) -> None:
        partial = build_current_partial_daily_bar(
            completed_daily_points=self.completed,
            intraday_points=[],
            quote={"trade_date": "2026-08-13", "last_trade_price": 156.0},
            session_date=date(2026, 8, 13),
            session_phase="regular",
        )

        self.assertIsNone(partial)

    def test_post_close_before_official_row_is_provisional_close(self) -> None:
        partial = build_current_partial_daily_bar(
            completed_daily_points=self.completed,
            intraday_points=self.intraday,
            quote=_quote(phase="post_close"),
            session_date=date(2026, 8, 13),
            session_phase="post_close",
        )

        self.assertEqual(partial["bar_status"], "provisional_close")

    def test_official_daily_row_suppresses_partial(self) -> None:
        completed = _daily_points(50, end=date(2026, 8, 13))
        partial = build_current_partial_daily_bar(
            completed_daily_points=completed,
            intraday_points=self.intraday,
            quote=_quote(),
            session_date=date(2026, 8, 13),
            session_phase="regular",
        )

        self.assertIsNone(partial)

    def test_daily_snapshot_keeps_completed_and_labels_volume_partial(self) -> None:
        parameters = get_technical_analysis_parameters(persisted_settings={})
        partial_bar = build_current_partial_daily_bar(
            completed_daily_points=self.completed,
            intraday_points=self.intraday,
            quote=_quote(),
            session_date=date(2026, 8, 13),
            session_phase="regular",
        )
        snapshot = _snapshot_for_timeframe(
            self.completed,
            timeframe="daily",
            parameters=parameters,
            method_catalog=indicator_method_catalog(parameters),
            latest_observation_date=date(2026, 8, 12),
            current_partial_point=partial_bar,
        )

        self.assertEqual(snapshot["completed"]["time"], date(2026, 8, 12))
        self.assertEqual(snapshot["completed"]["bar_status"], "completed")
        self.assertEqual(snapshot["current_partial"]["time"], date(2026, 8, 13))
        self.assertEqual(snapshot["current_partial"]["bar_status"], "intraday_partial")
        self.assertEqual(
            snapshot["current_partial"]["indicator_semantics"]["volume_based"],
            "partial_cumulative_volume",
        )
        self.assertFalse(snapshot["current_partial"]["volume_based_decision_usable"])
        self.assertEqual(snapshot["decision_snapshot"], "completed")


if __name__ == "__main__":
    unittest.main()
