from datetime import date
from unittest.mock import Mock, patch

from app.watchlists import backfill_service


def test_refresh_result_reports_latest_trade_date_after_backfill() -> None:
    db = Mock()
    target_date = date(2026, 7, 21)

    with (
        patch.object(backfill_service, "_expected_latest_trade_date", return_value=target_date),
        patch.object(
            backfill_service,
            "_list_unique_watchlist_items",
            return_value=[{"stock_id": "2330", "stock_name": "TSMC"}],
        ),
        patch.object(backfill_service, "_get_stock_market", return_value="TWSE"),
        patch.object(
            backfill_service,
            "_get_latest_trade_date",
            side_effect=[date(2026, 7, 17), target_date],
        ),
        patch.object(
            backfill_service,
            "_backfill_stock_by_market",
            return_value={
                "status": "success",
                "parsed_count": 2,
                "inserted_count": 2,
                "skipped_count": 0,
                "message": "completed",
                "error_message": None,
            },
        ),
    ):
        result = backfill_service.refresh_watchlist_group_daily_prices(
            db=db,
            group_id=3,
            to_date=target_date,
        )

    assert result["status"] == "success"
    assert result["results"][0]["latest_trade_date"] == target_date
