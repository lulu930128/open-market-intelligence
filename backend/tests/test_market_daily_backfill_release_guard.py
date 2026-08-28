from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.market import backfill


def test_twse_backfill_does_not_fetch_an_unreleased_official_session() -> None:
    with (
        patch.object(
            backfill,
            "expected_daily_price_date",
            return_value=date(2026, 8, 27),
        ),
        patch.object(backfill, "http_get") as http_get,
    ):
        result = backfill.backfill_twse_stock_day(
            db=SimpleNamespace(),
            stock_id="3711",
            start_date=date(2026, 8, 28),
            end_date=date(2026, 8, 28),
        )

    http_get.assert_not_called()
    assert result["status"] == "skipped_unreleased"
    assert result["inserted_count"] == 0
    assert result["effective_end_date"] is None
    assert result["release_limited"] is True


def test_tpex_backfill_does_not_fetch_an_unreleased_official_session() -> None:
    with (
        patch.object(
            backfill,
            "expected_daily_price_date",
            return_value=date(2026, 8, 27),
        ),
        patch.object(backfill, "http_post") as http_post,
    ):
        result = backfill.backfill_tpex_trading_stock(
            db=SimpleNamespace(),
            stock_id="1240",
            start_date=date(2026, 8, 28),
            end_date=date(2026, 8, 28),
        )

    http_post.assert_not_called()
    assert result["status"] == "skipped_unreleased"
    assert result["inserted_count"] == 0
    assert result["effective_end_date"] is None
    assert result["release_limited"] is True


def test_daily_backfill_caps_a_history_request_at_the_released_session() -> None:
    with patch.object(
        backfill,
        "expected_daily_price_date",
        return_value=date(2026, 8, 27),
    ):
        effective_end_date, release_limited = backfill._official_daily_backfill_window(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 28),
        )

    assert effective_end_date == date(2026, 8, 27)
    assert release_limited is True
