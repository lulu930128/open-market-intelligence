import time

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricQuarterly,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
    SourceRegistry,
    StockMaster,
)
from app.pipelines.fetch_pipeline import refresh_source


SUPPORTED_PARSER_MODELS = {
    "tdcc_shareholding_distribution": ShareholdingDistributionWeekly,
    "monthly_revenue": MonthlyRevenue,
    "financial_metrics": FinancialMetricQuarterly,
}

DEFAULT_CATEGORIES = (
    "shareholding_distribution",
    "monthly_revenue",
    "financial_metrics",
)


def _normalize_categories(categories: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not categories:
        return DEFAULT_CATEGORIES

    normalized = tuple(dict.fromkeys(item.strip() for item in categories if item.strip()))
    invalid = [item for item in normalized if item not in DEFAULT_CATEGORIES]

    if invalid:
        raise ValueError(f"Unsupported fundamental metric categories: {', '.join(invalid)}.")

    return normalized


def _list_metric_sources(
    db: Session,
    categories: tuple[str, ...],
) -> list[SourceRegistry]:
    return (
        db.query(SourceRegistry)
        .filter(SourceRegistry.enabled.is_(True))
        .filter(SourceRegistry.category.in_(categories))
        .filter(SourceRegistry.parser_type.in_(SUPPORTED_PARSER_MODELS.keys()))
        .order_by(SourceRegistry.priority.asc(), SourceRegistry.id.asc())
        .all()
    )


def _metric_model_for_source(source: SourceRegistry):
    if source.parser_type not in SUPPORTED_PARSER_MODELS:
        raise ValueError(f"Source id={source.id} parser_type='{source.parser_type}' is unsupported.")

    return SUPPORTED_PARSER_MODELS[source.parser_type]


def _source_row_count(db: Session, source: SourceRegistry) -> int:
    model = _metric_model_for_source(source)

    return (
        db.query(func.count(model.id))
        .filter(model.source_id == source.id)
        .scalar()
        or 0
    )


def _stock_category_row_count(db: Session, stock_id: str, category: str) -> int:
    if category == "shareholding_distribution":
        model = ShareholdingDistributionWeekly
    elif category == "monthly_revenue":
        model = MonthlyRevenue
    elif category == "financial_metrics":
        model = FinancialMetricQuarterly
    else:
        return 0

    return (
        db.query(func.count(model.id))
        .filter(model.stock_id == stock_id)
        .scalar()
        or 0
    )


def _stock_market(db: Session, stock_id: str) -> str | None:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

    if stock is None:
        return None

    return stock.market.upper()


def _source_matches_market(source: SourceRegistry, market: str | None) -> bool:
    if market is None or source.category == "shareholding_distribution":
        return True

    source_name = source.source_name.upper()

    if market == "TWSE":
        return "TWSE" in source_name

    if market == "TPEX":
        return "TPEX" in source_name

    return True


def _refresh_sources(
    db: Session,
    sources: list[SourceRegistry],
    force: bool,
    sleep_seconds: float,
) -> dict:
    results: list[dict] = []
    fetched_count = 0
    skipped_existing_count = 0
    error_count = 0
    inserted_count = 0

    for source in sources:
        existing_count = _source_row_count(db=db, source=source)

        if existing_count > 0 and not force:
            skipped_existing_count += 1
            results.append(
                {
                    "source_id": source.id,
                    "source_name": source.source_name,
                    "category": source.category,
                    "parser_type": source.parser_type,
                    "status": "skipped_existing",
                    "inserted_count": 0,
                    "existing_row_count": existing_count,
                    "message": f"Skipped because {existing_count} rows already exist.",
                    "error_message": None,
                }
            )
            continue

        try:
            refresh_result = refresh_source(db=db, source_id=source.id)
            fetched_count += 1
            result_inserted_count = refresh_result.get("inserted_count") or 0
            inserted_count += result_inserted_count

            status = refresh_result.get("parse_status") or refresh_result.get("fetch_status")

            if status != "success":
                error_count += 1

            results.append(
                {
                    "source_id": source.id,
                    "source_name": source.source_name,
                    "category": source.category,
                    "parser_type": source.parser_type,
                    "status": status,
                    "fetch_status": refresh_result.get("fetch_status"),
                    "parse_status": refresh_result.get("parse_status"),
                    "raw_result_id": refresh_result.get("raw_result_id"),
                    "inserted_count": result_inserted_count,
                    "existing_row_count": existing_count,
                    "message": refresh_result.get("message"),
                    "error_message": refresh_result.get("error_message"),
                }
            )
        except Exception as exc:
            error_count += 1
            results.append(
                {
                    "source_id": source.id,
                    "source_name": source.source_name,
                    "category": source.category,
                    "parser_type": source.parser_type,
                    "status": "error",
                    "fetch_status": "error",
                    "parse_status": None,
                    "raw_result_id": None,
                    "inserted_count": 0,
                    "existing_row_count": existing_count,
                    "message": "Fundamental metric refresh failed.",
                    "error_message": str(exc),
                }
            )

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    status = "success"

    if error_count:
        status = "partial_success" if inserted_count or skipped_existing_count else "error"

    return {
        "status": status,
        "requested_count": len(sources),
        "fetched_count": fetched_count,
        "skipped_existing_count": skipped_existing_count,
        "error_count": error_count,
        "inserted_count": inserted_count,
        "results": results,
    }


def ensure_fundamental_metrics(
    db: Session,
    categories: list[str] | tuple[str, ...] | None = None,
    force: bool = False,
    sleep_seconds: float = 0.2,
) -> dict:
    normalized_categories = _normalize_categories(categories)
    sources = _list_metric_sources(db=db, categories=normalized_categories)

    if not sources:
        return {
            "status": "skipped",
            "message": "No enabled fundamental metric sources found.",
            "categories": list(normalized_categories),
            "requested_count": 0,
            "fetched_count": 0,
            "skipped_existing_count": 0,
            "error_count": 0,
            "inserted_count": 0,
            "results": [],
        }

    result = _refresh_sources(
        db=db,
        sources=sources,
        force=force,
        sleep_seconds=sleep_seconds,
    )
    result["message"] = "Fundamental metric ensure completed."
    result["categories"] = list(normalized_categories)
    return result


def ensure_stock_fundamental_metrics(
    db: Session,
    stock_id: str,
    categories: list[str] | tuple[str, ...] | None = None,
    force: bool = False,
    sleep_seconds: float = 0.2,
) -> dict:
    normalized_categories = _normalize_categories(categories)
    market = _stock_market(db=db, stock_id=stock_id)
    sources = [
        source
        for source in _list_metric_sources(db=db, categories=normalized_categories)
        if _source_matches_market(source=source, market=market)
    ]

    needed_categories = [
        category
        for category in normalized_categories
        if force or _stock_category_row_count(db=db, stock_id=stock_id, category=category) == 0
    ]
    needed_sources = [source for source in sources if source.category in needed_categories]

    if not needed_sources:
        return {
            "status": "skipped",
            "message": "Stock already has requested fundamental metric rows.",
            "stock_id": stock_id,
            "market": market,
            "categories": list(normalized_categories),
            "requested_count": 0,
            "fetched_count": 0,
            "skipped_existing_count": len(sources),
            "error_count": 0,
            "inserted_count": 0,
            "results": [],
        }

    result = _refresh_sources(
        db=db,
        sources=needed_sources,
        force=True,
        sleep_seconds=sleep_seconds,
    )
    result["message"] = "Stock fundamental metric ensure completed."
    result["stock_id"] = stock_id
    result["market"] = market
    result["categories"] = list(normalized_categories)
    return result


__all__ = [
    "ensure_fundamental_metrics",
    "ensure_stock_fundamental_metrics",
]

