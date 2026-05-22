import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    SourceRegistry,
    StockMaster,
)
from app.pipelines.fetch_pipeline import refresh_source


TAIWAN_TZ = ZoneInfo("Asia/Taipei")

SUPPORTED_PARSER_MODELS = {
    "twse_institutional_trade": InstitutionalTradeDaily,
    "tpex_institutional_trade": InstitutionalTradeDaily,
    "twse_margin_trading": MarginTradingDaily,
    "tpex_margin_trading": MarginTradingDaily,
}

DEFAULT_CATEGORIES = ("institutional_trade", "margin_trading")
MARKET_CATEGORY_PARSER_TYPES = {
    "TWSE": {
        "institutional_trade": ("twse_institutional_trade",),
        "margin_trading": ("twse_margin_trading",),
    },
    "TPEX": {
        "institutional_trade": ("tpex_institutional_trade",),
        "margin_trading": ("tpex_margin_trading",),
    },
}


def _taiwan_today() -> date:
    return datetime.now(TAIWAN_TZ).date()


def _normalize_categories(categories: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not categories:
        return DEFAULT_CATEGORIES

    normalized = tuple(dict.fromkeys(item.strip() for item in categories if item.strip()))
    invalid = [item for item in normalized if item not in DEFAULT_CATEGORIES]

    if invalid:
        raise ValueError(f"Unsupported daily metric categories: {', '.join(invalid)}.")

    return normalized


def _list_metric_sources(
    db: Session,
    categories: tuple[str, ...],
    parser_types: tuple[str, ...] | None = None,
) -> list[SourceRegistry]:
    query = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.enabled.is_(True))
        .filter(SourceRegistry.category.in_(categories))
        .filter(SourceRegistry.parser_type.in_(SUPPORTED_PARSER_MODELS.keys()))
    )

    if parser_types is not None:
        query = query.filter(SourceRegistry.parser_type.in_(parser_types))

    return query.order_by(SourceRegistry.priority.asc(), SourceRegistry.id.asc()).all()


def _metric_model_for_source(source: SourceRegistry):
    if source.parser_type not in SUPPORTED_PARSER_MODELS:
        raise ValueError(f"Source id={source.id} parser_type='{source.parser_type}' is unsupported.")

    return SUPPORTED_PARSER_MODELS[source.parser_type]


def _latest_market_trade_date(
    db: Session,
    to_date: date | None,
    include_today: bool,
) -> date | None:
    query = db.query(func.max(MarketDailyPrice.trade_date))

    if to_date is not None:
        query = query.filter(MarketDailyPrice.trade_date <= to_date)

    if not include_today:
        query = query.filter(MarketDailyPrice.trade_date < _taiwan_today())

    return query.scalar()


def _market_trade_dates(
    db: Session,
    start_date: date,
    end_date: date,
) -> list[date]:
    rows = (
        db.query(MarketDailyPrice.trade_date)
        .filter(MarketDailyPrice.trade_date >= start_date)
        .filter(MarketDailyPrice.trade_date <= end_date)
        .distinct()
        .order_by(MarketDailyPrice.trade_date.asc())
        .all()
    )

    return [row.trade_date for row in rows]


def _source_has_date_rows(
    db: Session,
    source: SourceRegistry,
    trade_date: date,
) -> bool:
    model = _metric_model_for_source(source)

    return (
        db.query(model.id)
        .filter(model.source_id == source.id)
        .filter(model.trade_date == trade_date)
        .first()
        is not None
    )


def _source_row_count(
    db: Session,
    source: SourceRegistry,
    trade_date: date,
) -> int:
    model = _metric_model_for_source(source)

    return (
        db.query(func.count(model.id))
        .filter(model.source_id == source.id)
        .filter(model.trade_date == trade_date)
        .scalar()
        or 0
    )


def _latest_source_trade_date(db: Session, source: SourceRegistry) -> date | None:
    model = _metric_model_for_source(source)

    return (
        db.query(func.max(model.trade_date))
        .filter(model.source_id == source.id)
        .scalar()
    )


def _default_start_date(
    db: Session,
    sources: list[SourceRegistry],
    end_date: date,
    lookback_days: int,
) -> date:
    latest_dates = [
        latest_date
        for source in sources
        if (latest_date := _latest_source_trade_date(db, source)) is not None
    ]

    if latest_dates:
        return min(latest_dates) + timedelta(days=1)

    return end_date - timedelta(days=lookback_days)


def ensure_daily_metrics(
    db: Session,
    start_date: date,
    end_date: date,
    categories: list[str] | tuple[str, ...] | None = None,
    sleep_seconds: float = 0.2,
    skip_existing: bool = True,
    parser_types: list[str] | tuple[str, ...] | None = None,
) -> dict:
    if end_date < start_date:
        raise ValueError("end_date must be greater than or equal to start_date.")

    normalized_categories = _normalize_categories(categories)
    normalized_parser_types = (
        tuple(dict.fromkeys(item.strip() for item in parser_types if item.strip()))
        if parser_types
        else None
    )
    sources = _list_metric_sources(
        db=db,
        categories=normalized_categories,
        parser_types=normalized_parser_types,
    )
    trade_dates = _market_trade_dates(db=db, start_date=start_date, end_date=end_date)

    if not sources:
        return {
            "status": "skipped",
            "message": "No enabled daily metric sources found.",
            "categories": list(normalized_categories),
            "parser_types": list(normalized_parser_types or []),
            "start_date": start_date,
            "end_date": end_date,
            "trade_dates": [],
            "requested_count": 0,
            "fetched_count": 0,
            "skipped_existing_count": 0,
            "error_count": 0,
            "inserted_count": 0,
            "results": [],
        }

    results: list[dict] = []
    fetched_count = 0
    skipped_existing_count = 0
    error_count = 0
    inserted_count = 0

    for trade_date in trade_dates:
        for source in sources:
            if skip_existing and _source_has_date_rows(db=db, source=source, trade_date=trade_date):
                row_count = _source_row_count(db=db, source=source, trade_date=trade_date)
                skipped_existing_count += 1
                results.append(
                    {
                        "trade_date": trade_date,
                        "source_id": source.id,
                        "source_name": source.source_name,
                        "category": source.category,
                        "parser_type": source.parser_type,
                        "status": "skipped_existing",
                        "fetch_status": None,
                        "parse_status": None,
                        "raw_result_id": None,
                        "inserted_count": 0,
                        "existing_row_count": row_count,
                        "message": f"Skipped because {row_count} rows already exist.",
                        "error_message": None,
                    }
                )
                continue

            try:
                refresh_result = refresh_source(
                    db=db,
                    source_id=source.id,
                    trade_date=trade_date,
                )
                fetched_count += 1
                result_inserted_count = refresh_result.get("inserted_count") or 0
                inserted_count += result_inserted_count

                status = refresh_result.get("parse_status") or refresh_result.get("fetch_status")
                if status != "success":
                    error_count += 1

                results.append(
                    {
                        "trade_date": trade_date,
                        "source_id": source.id,
                        "source_name": source.source_name,
                        "category": source.category,
                        "parser_type": source.parser_type,
                        "status": status,
                        "fetch_status": refresh_result.get("fetch_status"),
                        "parse_status": refresh_result.get("parse_status"),
                        "raw_result_id": refresh_result.get("raw_result_id"),
                        "inserted_count": result_inserted_count,
                        "existing_row_count": None,
                        "message": refresh_result.get("message"),
                        "error_message": refresh_result.get("error_message"),
                    }
                )
            except Exception as exc:
                error_count += 1
                results.append(
                    {
                        "trade_date": trade_date,
                        "source_id": source.id,
                        "source_name": source.source_name,
                        "category": source.category,
                        "parser_type": source.parser_type,
                        "status": "error",
                        "fetch_status": "error",
                        "parse_status": None,
                        "raw_result_id": None,
                        "inserted_count": 0,
                        "existing_row_count": None,
                        "message": "Daily metric refresh failed.",
                        "error_message": str(exc),
                    }
                )

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    requested_count = len(trade_dates) * len(sources)
    status = "success"

    if error_count:
        status = "partial_success" if inserted_count or skipped_existing_count else "error"

    return {
        "status": status,
        "message": "Daily metric ensure completed.",
        "categories": list(normalized_categories),
        "parser_types": list(normalized_parser_types or []),
        "start_date": start_date,
        "end_date": end_date,
        "trade_dates": trade_dates,
        "requested_count": requested_count,
        "fetched_count": fetched_count,
        "skipped_existing_count": skipped_existing_count,
        "error_count": error_count,
        "inserted_count": inserted_count,
        "results": results,
    }


def ensure_latest_daily_metrics(
    db: Session,
    categories: list[str] | tuple[str, ...] | None = None,
    to_date: date | None = None,
    lookback_days: int = 30,
    include_today: bool = False,
    sleep_seconds: float = 0.2,
    skip_existing: bool = True,
) -> dict:
    normalized_categories = _normalize_categories(categories)
    sources = _list_metric_sources(db=db, categories=normalized_categories)
    latest_trade_date = _latest_market_trade_date(
        db=db,
        to_date=to_date,
        include_today=include_today,
    )

    if latest_trade_date is None:
        return {
            "status": "skipped",
            "message": "No market daily trade date is available for daily metric ensure.",
            "categories": list(normalized_categories),
            "start_date": None,
            "end_date": None,
            "trade_dates": [],
            "requested_count": 0,
            "fetched_count": 0,
            "skipped_existing_count": 0,
            "error_count": 0,
            "inserted_count": 0,
            "results": [],
        }

    start_date = _default_start_date(
        db=db,
        sources=sources,
        end_date=latest_trade_date,
        lookback_days=lookback_days,
    )

    if start_date > latest_trade_date:
        start_date = latest_trade_date

    return ensure_daily_metrics(
        db=db,
        start_date=start_date,
        end_date=latest_trade_date,
        categories=normalized_categories,
        sleep_seconds=sleep_seconds,
        skip_existing=skip_existing,
    )


def ensure_stock_daily_metrics(
    db: Session,
    stock_id: str,
    start_date: date,
    end_date: date,
    categories: list[str] | tuple[str, ...] | None = None,
    sleep_seconds: float = 0.2,
    skip_existing: bool = True,
) -> dict:
    normalized_categories = _normalize_categories(categories)
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
    market = stock.market.upper() if stock and stock.market else None
    market_parser_types = MARKET_CATEGORY_PARSER_TYPES.get(market or "")

    if market_parser_types is None:
        return {
            "status": "skipped",
            "message": f"Daily metric ensure is not configured for stock_id='{stock_id}' market='{market}'.",
            "stock_id": stock_id,
            "market": market,
            "categories": list(normalized_categories),
            "parser_types": [],
            "start_date": start_date,
            "end_date": end_date,
            "trade_dates": [],
            "requested_count": 0,
            "fetched_count": 0,
            "skipped_existing_count": 0,
            "error_count": 0,
            "inserted_count": 0,
            "results": [],
        }

    parser_types = tuple(
        parser_type
        for category in normalized_categories
        for parser_type in market_parser_types.get(category, ())
    )

    return ensure_daily_metrics(
        db=db,
        start_date=start_date,
        end_date=end_date,
        categories=normalized_categories,
        sleep_seconds=sleep_seconds,
        skip_existing=skip_existing,
        parser_types=parser_types,
    )


__all__ = [
    "ensure_daily_metrics",
    "ensure_latest_daily_metrics",
    "ensure_stock_daily_metrics",
]
