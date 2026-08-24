from collections.abc import Callable
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
    StockMaster,
    StockProfile,
    utc_now,
)
from app.parsers.financial_metrics import parse_financial_metrics_raw
from app.parsers.monthly_revenue import parse_monthly_revenue_raw
from app.parsers.shareholding_distribution import parse_shareholding_distribution_raw
from app.parsers.twse_company_profile import parse_twse_company_profile_raw
from app.parsers.twse_daily import parse_twse_daily_raw
from app.parsers.twse_institutional_trade import parse_twse_institutional_trade_raw
from app.parsers.twse_margin_trading import parse_twse_margin_trading_raw
from app.parsers.tpex_company_profile import parse_tpex_company_profile_raw
from app.parsers.tpex_daily_quotes import parse_tpex_daily_quotes_raw
from app.parsers.tpex_institutional_trade import parse_tpex_institutional_trade_raw
from app.parsers.tpex_margin_trading import parse_tpex_margin_trading_raw
from app.sources.service import get_raw_result


ParserFunction = Callable[[Session, int], dict]


def _market_from_source_name(source_name: str | None) -> str | None:
    if source_name is None:
        return None

    normalized = source_name.upper()

    if "TPEX" in normalized:
        return "TPEX"

    if "TWSE" in normalized:
        return "TWSE"

    return None


def _stock_names_by_id(db: Session, stock_ids: list[str]) -> dict[str, str | None]:
    if not stock_ids:
        return {}

    return {
        row.stock_id: row.stock_name
        for row in db.query(StockMaster).filter(StockMaster.stock_id.in_(stock_ids)).all()
    }


def _guard_market_daily_replacement(
    db: Session,
    *,
    source_id: int,
    parsed_rows: list[dict],
    minimum_existing_rows: int = 50,
    minimum_retained_ratio: float = 0.8,
) -> None:
    """Fail before delete when a same-day official payload regresses sharply."""

    incoming_by_date: dict[object, set[str]] = {}
    for row in parsed_rows:
        trade_date = row.get("trade_date")
        stock_id = str(row.get("stock_id") or "").strip()
        if trade_date is None or not stock_id:
            continue
        incoming_by_date.setdefault(trade_date, set()).add(stock_id)

    for trade_date, incoming_stock_ids in incoming_by_date.items():
        existing_count = (
            db.query(func.count(func.distinct(MarketDailyPrice.stock_id)))
            .filter(MarketDailyPrice.source_id == source_id)
            .filter(MarketDailyPrice.trade_date == trade_date)
            .scalar()
            or 0
        )
        incoming_count = len(incoming_stock_ids)
        if existing_count < minimum_existing_rows:
            continue
        minimum_count = int(existing_count * minimum_retained_ratio)
        if incoming_count < minimum_count:
            raise ValueError(
                "Refusing destructive market daily replacement: "
                f"source_id={source_id} trade_date={trade_date} "
                f"incoming_count={incoming_count} existing_count={existing_count} "
                f"minimum_count={minimum_count}."
            )


def parse_twse_daily_raw_result(
    db: Session,
    raw_result_id: int,
    trade_date_override: date | None = None,
) -> dict:
    raw_result = get_raw_result(db, raw_result_id)

    parsed_rows, skipped_count = parse_twse_daily_raw(
        raw_result,
        fallback_trade_date=trade_date_override,
    )

    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")

    trade_dates = sorted({row["trade_date"] for row in parsed_rows})
    _guard_market_daily_replacement(
        db,
        source_id=raw_result.source_id,
        parsed_rows=parsed_rows,
    )

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


def parse_tpex_daily_quotes_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)

    parsed_rows, skipped_count = parse_tpex_daily_quotes_raw(raw_result)

    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")

    trade_dates = sorted({row["trade_date"] for row in parsed_rows})
    _guard_market_daily_replacement(
        db,
        source_id=raw_result.source_id,
        parsed_rows=parsed_rows,
    )

    (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.raw_result_id == raw_result.id)
        .delete(synchronize_session=False)
    )

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
        "parser_type": "tpex_daily_quotes",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_trade_dates": trade_dates,
        "message": "TPEx daily quotes raw result parsed successfully.",
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


def parse_tpex_company_profile_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)

    parsed_rows, skipped_count = parse_tpex_company_profile_raw(raw_result)

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
                market="TPEX",
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
        stock.market = "TPEX"
        stock.instrument_type = "stock"
        stock.industry = industry or stock.industry
        stock.is_active = True
        stock.last_seen_at = utc_now()
        updated_master_count += 1

    db.commit()

    return {
        "raw_result_id": raw_result.id,
        "source_id": raw_result.source_id,
        "parser_type": "tpex_company_profile",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_stock_count": len(stock_ids),
        "created_master_count": created_master_count,
        "updated_master_count": updated_master_count,
        "message": "TPEx company profile raw result parsed successfully.",
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


def parse_tpex_institutional_trade_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)
    parsed_rows, skipped_count = parse_tpex_institutional_trade_raw(raw_result)

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
        "parser_type": "tpex_institutional_trade",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_trade_dates": trade_dates,
        "message": "TPEx institutional trade raw result parsed successfully.",
    }


def parse_twse_margin_trading_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)
    parsed_rows, skipped_count = parse_twse_margin_trading_raw(raw_result)

    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")

    trade_dates = sorted({row["trade_date"] for row in parsed_rows})

    (
        db.query(MarginTradingDaily)
        .filter(MarginTradingDaily.raw_result_id == raw_result.id)
        .delete(synchronize_session=False)
    )

    for trade_date in trade_dates:
        (
            db.query(MarginTradingDaily)
            .filter(MarginTradingDaily.source_id == raw_result.source_id)
            .filter(MarginTradingDaily.trade_date == trade_date)
            .delete(synchronize_session=False)
        )

    db.add_all([MarginTradingDaily(**row) for row in parsed_rows])
    db.commit()

    return {
        "raw_result_id": raw_result.id,
        "source_id": raw_result.source_id,
        "parser_type": "twse_margin_trading",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_trade_dates": trade_dates,
        "message": "TWSE margin trading raw result parsed successfully.",
    }


def parse_tpex_margin_trading_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)
    parsed_rows, skipped_count = parse_tpex_margin_trading_raw(raw_result)

    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")

    trade_dates = sorted({row["trade_date"] for row in parsed_rows})

    (
        db.query(MarginTradingDaily)
        .filter(MarginTradingDaily.raw_result_id == raw_result.id)
        .delete(synchronize_session=False)
    )

    for trade_date in trade_dates:
        (
            db.query(MarginTradingDaily)
            .filter(MarginTradingDaily.source_id == raw_result.source_id)
            .filter(MarginTradingDaily.trade_date == trade_date)
            .delete(synchronize_session=False)
        )

    db.add_all([MarginTradingDaily(**row) for row in parsed_rows])
    db.commit()

    return {
        "raw_result_id": raw_result.id,
        "source_id": raw_result.source_id,
        "parser_type": "tpex_margin_trading",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_trade_dates": trade_dates,
        "message": "TPEx margin trading raw result parsed successfully.",
    }


def parse_shareholding_distribution_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)
    parsed_rows, skipped_count = parse_shareholding_distribution_raw(raw_result)

    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")

    data_dates = sorted({row["data_date"] for row in parsed_rows})
    stock_ids = sorted({row["stock_id"] for row in parsed_rows})
    stock_names = _stock_names_by_id(db=db, stock_ids=stock_ids)

    for row in parsed_rows:
        row["stock_name"] = stock_names.get(row["stock_id"])

    (
        db.query(ShareholdingDistributionWeekly)
        .filter(ShareholdingDistributionWeekly.raw_result_id == raw_result.id)
        .delete(synchronize_session=False)
    )

    for data_date in data_dates:
        (
            db.query(ShareholdingDistributionWeekly)
            .filter(ShareholdingDistributionWeekly.source_id == raw_result.source_id)
            .filter(ShareholdingDistributionWeekly.data_date == data_date)
            .delete(synchronize_session=False)
        )

    db.add_all([ShareholdingDistributionWeekly(**row) for row in parsed_rows])
    db.commit()

    return {
        "raw_result_id": raw_result.id,
        "source_id": raw_result.source_id,
        "parser_type": "tdcc_shareholding_distribution",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_data_dates": data_dates,
        "message": "TDCC shareholding distribution raw result parsed successfully.",
    }


def parse_monthly_revenue_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)
    parsed_rows, skipped_count = parse_monthly_revenue_raw(raw_result)

    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")

    periods = sorted({row["period"] for row in parsed_rows})
    source_market = _market_from_source_name(raw_result.source.source_name)

    for row in parsed_rows:
        row["market"] = source_market

    (
        db.query(MonthlyRevenue)
        .filter(MonthlyRevenue.raw_result_id == raw_result.id)
        .delete(synchronize_session=False)
    )

    for period in periods:
        (
            db.query(MonthlyRevenue)
            .filter(MonthlyRevenue.source_id == raw_result.source_id)
            .filter(MonthlyRevenue.period == period)
            .delete(synchronize_session=False)
        )

    db.add_all([MonthlyRevenue(**row) for row in parsed_rows])
    db.commit()

    return {
        "raw_result_id": raw_result.id,
        "source_id": raw_result.source_id,
        "parser_type": "monthly_revenue",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_periods": periods,
        "message": "Monthly revenue raw result parsed successfully.",
    }


def parse_financial_metrics_raw_result(db: Session, raw_result_id: int) -> dict:
    raw_result = get_raw_result(db, raw_result_id)
    parsed_rows, skipped_count = parse_financial_metrics_raw(raw_result)

    if not parsed_rows:
        raise ValueError("No valid rows parsed from raw result.")

    source_market = _market_from_source_name(raw_result.source.source_name)
    period_keys = sorted({(row["fiscal_year"], row["quarter"]) for row in parsed_rows})

    for row in parsed_rows:
        row["market"] = source_market
        released_at = row.get("released_at") or row.get("report_date")
        row["released_at"] = released_at
        if released_at is not None:
            row["report_date"] = released_at
        row.setdefault("filed_at", None)

    (
        db.query(FinancialMetricQuarterly)
        .filter(FinancialMetricQuarterly.raw_result_id == raw_result.id)
        .delete(synchronize_session=False)
    )

    for fiscal_year, quarter in period_keys:
        (
            db.query(FinancialMetricQuarterly)
            .filter(FinancialMetricQuarterly.source_id == raw_result.source_id)
            .filter(FinancialMetricQuarterly.fiscal_year == fiscal_year)
            .filter(FinancialMetricQuarterly.quarter == quarter)
            .delete(synchronize_session=False)
        )

    db.add_all([FinancialMetricQuarterly(**row) for row in parsed_rows])
    db.commit()

    return {
        "raw_result_id": raw_result.id,
        "source_id": raw_result.source_id,
        "parser_type": "financial_metrics",
        "status": "success",
        "parsed_count": len(parsed_rows),
        "skipped_count": skipped_count,
        "inserted_count": len(parsed_rows),
        "replaced_periods": [f"{year}Q{quarter}" for year, quarter in period_keys],
        "message": "Financial metrics raw result parsed successfully.",
    }



PARSER_REGISTRY: dict[str, ParserFunction] = {
    "twse_daily_trading": parse_twse_daily_raw_result,
    "twse_company_profile": parse_twse_company_profile_raw_result,
    "twse_institutional_trade": parse_twse_institutional_trade_raw_result,
    "twse_margin_trading": parse_twse_margin_trading_raw_result,
    "tpex_daily_quotes": parse_tpex_daily_quotes_raw_result,
    "tpex_company_profile": parse_tpex_company_profile_raw_result,
    "tpex_institutional_trade": parse_tpex_institutional_trade_raw_result,
    "tpex_margin_trading": parse_tpex_margin_trading_raw_result,
    "tdcc_shareholding_distribution": parse_shareholding_distribution_raw_result,
    "monthly_revenue": parse_monthly_revenue_raw_result,
    "financial_metrics": parse_financial_metrics_raw_result,
}


def has_parser(parser_type: str | None) -> bool:
    if parser_type is None:
        return False

    return parser_type in PARSER_REGISTRY


def parse_raw_result_by_parser_type(
    db: Session,
    raw_result_id: int,
    parser_type: str | None,
    trade_date_override: date | None = None,
) -> dict:
    if parser_type is None:
        raise ValueError("parser_type is required.")

    parser = PARSER_REGISTRY.get(parser_type)

    if parser is None:
        raise ValueError(f"No parser registered for parser_type='{parser_type}'.")

    if parser_type == "twse_daily_trading":
        return parse_twse_daily_raw_result(
            db,
            raw_result_id,
            trade_date_override=trade_date_override,
        )
    return parser(db, raw_result_id)
