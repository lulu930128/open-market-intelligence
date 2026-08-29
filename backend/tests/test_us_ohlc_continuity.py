from __future__ import annotations

from datetime import date

from app.us_market.ohlc_continuity import build_us_daily_continuity


def test_daily_continuity_reports_missing_completed_sessions_and_history_depth() -> None:
    result = build_us_daily_continuity(
        available_dates=(
            date(2026, 8, 17),
            date(2026, 8, 18),
            date(2026, 8, 19),
        ),
        expected_data_date=date(2026, 8, 21),
        available_bar_count=3,
        requested_bar_count=180,
    )

    assert result["coverage_status"] == "partial"
    assert result["continuity_status"] == "partial"
    assert result["history_status"] == "insufficient_history"
    assert result["latest_finalized_data_date"] == date(2026, 8, 19)
    assert result["contiguous_through_date"] == date(2026, 8, 19)
    assert result["missing_trade_dates"] == [date(2026, 8, 20), date(2026, 8, 21)]
    assert result["missing_trade_date_count"] == 2
    assert result["latest_expected_date_present"] is False


def test_daily_continuity_ignores_weekends_and_us_holidays() -> None:
    result = build_us_daily_continuity(
        available_dates=(date(2026, 7, 2), date(2026, 7, 6)),
        expected_data_date=date(2026, 7, 6),
        available_bar_count=2,
        requested_bar_count=2,
    )

    assert result["coverage_status"] == "complete"
    assert result["continuity_status"] == "complete"
    assert result["missing_trade_dates"] == []


def test_daily_continuity_separates_internal_gap_from_latest_date() -> None:
    result = build_us_daily_continuity(
        available_dates=(
            date(2026, 8, 18),
            date(2026, 8, 19),
            date(2026, 8, 21),
        ),
        expected_data_date=date(2026, 8, 21),
        available_bar_count=3,
        requested_bar_count=3,
    )

    assert result["latest_expected_date_present"] is True
    assert result["continuity_status"] == "partial"
    assert result["coverage_status"] == "partial"
    assert result["missing_trade_dates"] == [date(2026, 8, 20)]
    assert result["contiguous_through_date"] == date(2026, 8, 19)


def test_daily_continuity_marks_short_full_fetch_as_best_available() -> None:
    result = build_us_daily_continuity(
        available_dates=(date(2026, 8, 20), date(2026, 8, 21)),
        expected_data_date=date(2026, 8, 21),
        available_bar_count=2,
        requested_bar_count=180,
        history_fetch_scope="full",
    )

    assert result["continuity_status"] == "complete"
    assert result["history_status"] == "best_available"
    assert result["coverage_status"] == "best_available"
    assert result["history_fetch_scope"] == "full"


def test_daily_continuity_ignores_verified_special_exchange_closure() -> None:
    result = build_us_daily_continuity(
        available_dates=(date(2025, 1, 8), date(2025, 1, 10)),
        expected_data_date=date(2025, 1, 10),
        available_bar_count=2,
        requested_bar_count=2,
    )

    assert result["continuity_status"] == "complete"
    assert result["missing_trade_dates"] == []
