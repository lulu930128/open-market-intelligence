from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.us_market.daily_market_state import expected_us_completed_daily_state


EASTERN = ZoneInfo("America/New_York")


def test_expected_state_uses_released_completed_session_not_calendar_age() -> None:
    before_release = expected_us_completed_daily_state(
        now=datetime(2026, 8, 21, 16, 4, tzinfo=EASTERN)
    )
    after_release = expected_us_completed_daily_state(
        now=datetime(2026, 8, 21, 16, 5, tzinfo=EASTERN)
    )

    assert before_release.expected_trade_date == date(2026, 8, 20)
    assert after_release.expected_trade_date == date(2026, 8, 21)
    assert after_release.release_at.tzinfo is not None
    assert after_release.reason_code == "LATEST_RELEASED_COMPLETED_SESSION"
