from sqlalchemy.orm import Session

from app.db.models import MarketDailyPrice
from app.parsers.twse_daily import parse_twse_daily_raw
from app.sources.service import get_raw_result


def parse_twse_daily_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)

    parsed_rows, skipped_count = parse_twse_daily_raw(raw_result)

    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")

    trade_dates = sorted({row["trade_date"] for row in parsed_rows})

    # Remove old parsed rows from the same raw result to prevent stale data
    # when parser logic changes.
    (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.raw_result_id == raw_result.id)
        .delete(synchronize_session=False)
    )

    # Also replace rows from the same source and trade dates.
    for trade_date in trade_dates:
        (
            db.query(MarketDailyPrice)
            .filter(MarketDailyPrice.source_id == raw_result.source_id)
            .filter(MarketDailyPrice.trade_date == trade_date)
            .delete(synchronize_session=False)
        )

    db.add_all([MarketDailyPrice(**row) for row in parsed_rows])
    db.commit()

    return {
        "raw_result_id": raw_result.id,
        "source_id": raw_result.source_id,
        "parser_type": "twse_daily",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_trade_dates": trade_dates,
        "message": "TWSE daily raw result parsed successfully.",
    }