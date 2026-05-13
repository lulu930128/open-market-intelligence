from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.models import InstitutionalTradeDaily, MarketDailyPrice, StockMaster, StockProfile, utc_now
from app.parsers.twse_company_profile import parse_twse_company_profile_raw
from app.parsers.twse_daily import parse_twse_daily_raw
from app.parsers.twse_institutional_trade import parse_twse_institutional_trade_raw
from app.sources.service import get_raw_result


ParserFunction = Callable[[Session, int], dict]


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
        "parser_type": "twse_daily_trading",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_trade_dates": trade_dates,
        "message": "TWSE daily raw result parsed successfully.",
    }


def parse_twse_company_profile_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)

    parsed_rows, skipped_count = parse_twse_company_profile_raw(raw_result)

    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")

    stock_ids = sorted({row["stock_id"] for row in parsed_rows})

    (
        db.query(StockProfile)
        .filter(StockProfile.raw_result_id == raw_result.id)
        .delete(synchronize_session=False)
    )

    (
        db.query(StockProfile)
        .filter(StockProfile.stock_id.in_(stock_ids))
        .delete(synchronize_session=False)
    )

    db.add_all([StockProfile(**row) for row in parsed_rows])

    existing_stocks = {
        stock.stock_id: stock
        for stock in db.query(StockMaster).filter(StockMaster.stock_id.in_(stock_ids)).all()
    }

    created_master_count = 0
    updated_master_count = 0

    for row in parsed_rows:
        stock_id = row["stock_id"]
        stock_name = row.get("short_name") or row.get("company_name")
        industry = row.get("industry")

        stock = existing_stocks.get(stock_id)

        if stock is None:
            stock = StockMaster(
                stock_id=stock_id,
                stock_name=stock_name,
                market="TWSE",
                instrument_type="stock",
                industry=industry,
                is_active=True,
                last_seen_at=utc_now(),
            )
            db.add(stock)
            existing_stocks[stock_id] = stock
            created_master_count += 1
            continue

        stock.stock_name = stock_name or stock.stock_name
        stock.market = "TWSE"
        stock.instrument_type = "stock"
        stock.industry = industry or stock.industry
        stock.is_active = True
        stock.last_seen_at = utc_now()
        updated_master_count += 1

    db.commit()

    return {
        "raw_result_id": raw_result.id,
        "source_id": raw_result.source_id,
        "parser_type": "twse_company_profile",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_stock_count": len(stock_ids),
        "created_master_count": created_master_count,
        "updated_master_count": updated_master_count,
        "message": "TWSE company profile raw result parsed successfully.",
    }



def parse_twse_institutional_trade_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)
    parsed_rows, skipped_count = parse_twse_institutional_trade_raw(raw_result)
    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")
    trade_dates = sorted({row["trade_date"] for row in parsed_rows})
    (
        db.query(InstitutionalTradeDaily)
        .filter(InstitutionalTradeDaily.raw_result_id == raw_result.id)
        .delete(synchronize_session=False)
    )
    for trade_date in trade_dates:
        (
            db.query(InstitutionalTradeDaily)
            .filter(InstitutionalTradeDaily.source_id == raw_result.source_id)
            .filter(InstitutionalTradeDaily.trade_date == trade_date)
            .delete(synchronize_session=False)
        )
    db.add_all([InstitutionalTradeDaily(**row) for row in parsed_rows])
    db.commit()
    return {
        "raw_result_id": raw_result.id,
        "source_id": raw_result.source_id,
        "parser_type": "twse_institutional_trade",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_trade_dates": trade_dates,
        "message": "TWSE institutional trade raw result parsed successfully.",
    }



PARSER_REGISTRY: dict[str, ParserFunction] = {
    "twse_daily_trading": parse_twse_daily_raw_result,
    "twse_company_profile": parse_twse_company_profile_raw_result,
    "twse_institutional_trade": parse_twse_institutional_trade_raw_result,
}


def has_parser(parser_type: str | None) -> bool:
    if parser_type is None:
        return False

    return parser_type in PARSER_REGISTRY


def parse_raw_result_by_parser_type(
    db: Session,
    raw_result_id: int,
    parser_type: str | None,
) -> dict:
    if parser_type is None:
        raise ValueError("parser_type is required.")

    parser = PARSER_REGISTRY.get(parser_type)

    if parser is None:
        raise ValueError(f"No parser registered for parser_type='{parser_type}'.")

    return parser(db, raw_result_id)
