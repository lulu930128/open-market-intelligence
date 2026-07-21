from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import BrokerBranchTradeDaily, MarketDailyPrice, StockMaster
from app.market.taiwan_rules import (
    TAIWAN_DATASET_BROKER_BRANCH,
    TAIWAN_DATASET_DAILY_PRICE,
    TAIWAN_DATASET_FREQUENCIES,
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_LABELS,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_DATASET_SPECS,
    TAIWAN_STOCK_MASTER_DATASET,
    TaiwanDatasetSpec,
    expected_date_for_dataset as expected_taiwan_dataset_date,
    is_equity_only_dataset_required as _is_equity_only_dataset_required,
)
from app.market.calendar_status import expected_taiwan_trade_date
from app.watchlists import service as watchlist_service


MAX_STALE_STOCK_DETAILS = 20
MAX_STALE_STOCK_IDS = 500


@dataclass(frozen=True)
class StockCandidate:
    stock_id: str
    stock_name: str | None = None

DatasetSpec = TaiwanDatasetSpec
DATASET_SPECS = TAIWAN_DATASET_SPECS
STOCK_MASTER_DATASET = TAIWAN_STOCK_MASTER_DATASET
DATASET_LABELS = TAIWAN_DATASET_LABELS
DATASET_FREQUENCIES = TAIWAN_DATASET_FREQUENCIES


def expected_daily_price_date() -> date | None:
    return expected_taiwan_trade_date(TAIWAN_DATASET_DAILY_PRICE)


def expected_institutional_trade_date() -> date | None:
    return expected_taiwan_trade_date(TAIWAN_DATASET_INSTITUTIONAL_TRADE)


def expected_margin_trade_date() -> date | None:
    return expected_taiwan_trade_date(TAIWAN_DATASET_MARGIN_TRADING)


def expected_broker_branch_date() -> date | None:
    return expected_taiwan_trade_date(TAIWAN_DATASET_BROKER_BRANCH)


def _expected_date_for_dataset(key: str) -> date | None:
    if key == TAIWAN_DATASET_DAILY_PRICE:
        return expected_daily_price_date()

    if key == TAIWAN_DATASET_INSTITUTIONAL_TRADE:
        return expected_institutional_trade_date()

    if key == TAIWAN_DATASET_MARGIN_TRADING:
        return expected_margin_trade_date()

    if key == TAIWAN_DATASET_BROKER_BRANCH:
        return expected_broker_branch_date()

    return expected_taiwan_dataset_date(key)



def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def _latest_values_by_stock(
    db: Session,
    *,
    model: Any,
    column: Any,
    stock_ids: list[str],
) -> dict[str, Any]:
    if not stock_ids:
        return {}

    rows = (
        db.query(model.stock_id, func.max(column))
        .filter(model.stock_id.in_(stock_ids))
        .group_by(model.stock_id)
        .all()
    )
    return {str(stock_id): latest for stock_id, latest in rows}


def _stock_master_by_id(db: Session, stock_ids: list[str]) -> dict[str, StockMaster]:
    if not stock_ids:
        return {}

    rows = db.query(StockMaster).filter(StockMaster.stock_id.in_(stock_ids)).all()
    return {stock.stock_id: stock for stock in rows}


def _stock_master_check(
    candidate: StockCandidate,
    stock: StockMaster | None,
) -> dict[str, Any]:
    return {
        "key": STOCK_MASTER_DATASET["key"],
        "label": STOCK_MASTER_DATASET["label"],
        "frequency": STOCK_MASTER_DATASET["frequency"],
        "required": True,
        "status": "current" if stock is not None else "missing",
        "latest": _json_value(stock.updated_at) if stock is not None else None,
        "expected": None,
        "is_current": stock is not None,
        "stock_id": candidate.stock_id,
    }


def _dataset_check(
    *,
    spec: DatasetSpec,
    stock_id: str,
    latest_value: Any,
    expected_date: date | None,
    required: bool,
) -> dict[str, Any]:
    latest = _json_value(latest_value)
    expected = _json_value(expected_date)

    if not required:
        status = "skipped"
        is_current = True
    elif latest_value is None:
        status = "missing"
        is_current = False
    elif expected_date is not None and latest_value < expected_date:
        status = "stale"
        is_current = False
    else:
        status = "current"
        is_current = True

    return {
        "key": spec.key,
        "label": spec.label,
        "frequency": spec.frequency,
        "required": required,
        "status": status,
        "latest": latest,
        "expected": expected,
        "is_current": is_current,
        "stock_id": stock_id,
    }


def _stock_freshness_rows(
    db: Session,
    *,
    candidates: list[StockCandidate],
) -> list[dict[str, Any]]:
    stock_ids = [candidate.stock_id for candidate in candidates]
    stock_master = _stock_master_by_id(db, stock_ids)
    latest_by_dataset = {
        spec.key: _latest_values_by_stock(
            db=db,
            model=spec.model,
            column=spec.latest_column,
            stock_ids=stock_ids,
        )
        for spec in DATASET_SPECS
    }
    expected_dates = {
        spec.key: _expected_date_for_dataset(spec.key)
        for spec in DATASET_SPECS
        if spec.has_expected_date
    }
    rows: list[dict[str, Any]] = []

    for candidate in candidates:
        stock = stock_master.get(candidate.stock_id)
        stock_name = candidate.stock_name or (stock.stock_name if stock else None)
        datasets = [_stock_master_check(candidate, stock)]

        for spec in DATASET_SPECS:
            required = _is_equity_only_dataset_required(spec, stock)
            datasets.append(
                _dataset_check(
                    spec=spec,
                    stock_id=candidate.stock_id,
                    latest_value=latest_by_dataset[spec.key].get(candidate.stock_id),
                    expected_date=expected_dates.get(spec.key),
                    required=required,
                )
            )

        issues = [
            {
                "key": dataset["key"],
                "label": dataset["label"],
                "frequency": dataset["frequency"],
                "status": dataset["status"],
                "latest": dataset["latest"],
                "expected": dataset["expected"],
            }
            for dataset in datasets
            if dataset["required"] and not dataset["is_current"]
        ]

        rows.append(
            {
                "stock_id": candidate.stock_id,
                "stock_name": stock_name,
                "market": stock.market if stock else None,
                "instrument_type": stock.instrument_type if stock else None,
                "is_current": not issues,
                "issue_count": len(issues),
                "issues": issues,
                "datasets": datasets,
            }
        )

    return rows


def _dataset_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered_keys = [STOCK_MASTER_DATASET["key"], *(spec.key for spec in DATASET_SPECS)]
    summaries: list[dict[str, Any]] = []

    for key in ordered_keys:
        checks = [
            dataset
            for row in rows
            for dataset in row["datasets"]
            if dataset["key"] == key
        ]
        required_checks = [check for check in checks if check["required"]]
        current_checks = [check for check in required_checks if check["is_current"]]
        stale_checks = [check for check in required_checks if check["status"] == "stale"]
        missing_checks = [check for check in required_checks if check["status"] == "missing"]
        skipped_checks = [check for check in checks if check["status"] == "skipped"]
        affected_stock_ids = [
            check["stock_id"]
            for check in required_checks
            if not check["is_current"]
        ][:MAX_STALE_STOCK_IDS]
        latest_values = [
            check["latest"]
            for check in required_checks
            if check["latest"] is not None
        ]
        expected_values = [
            check["expected"]
            for check in required_checks
            if check["expected"] is not None
        ]

        summaries.append(
            {
                "key": key,
                "label": DATASET_LABELS[key],
                "frequency": DATASET_FREQUENCIES[key],
                "is_current": len(current_checks) == len(required_checks),
                "checked_stock_count": len(required_checks),
                "current_stock_count": len(current_checks),
                "missing_stock_count": len(missing_checks),
                "stale_stock_count": len(stale_checks),
                "skipped_stock_count": len(skipped_checks),
                "affected_stock_ids": affected_stock_ids,
                "affected_stock_ids_truncated": len(affected_stock_ids)
                < len(stale_checks) + len(missing_checks),
                "latest": max(latest_values) if latest_values else None,
                "oldest_latest": min(latest_values) if latest_values else None,
                "expected": max(expected_values) if expected_values else None,
            }
        )

    return summaries


def _build_result(
    *,
    scope_type: str,
    scope_id: str | None,
    rows: list[dict[str, Any]],
    refresh_endpoint: str | None,
    refresh_params: dict[str, Any],
) -> dict[str, Any]:
    stale_rows = [row for row in rows if not row["is_current"]]
    stale_details = [
        {
            "stock_id": row["stock_id"],
            "stock_name": row["stock_name"],
            "market": row["market"],
            "instrument_type": row["instrument_type"],
            "issue_count": row["issue_count"],
            "issues": row["issues"],
        }
        for row in stale_rows[:MAX_STALE_STOCK_DETAILS]
    ]
    stale_stock_ids = [row["stock_id"] for row in stale_rows[:MAX_STALE_STOCK_IDS]]
    dataset_summaries = _dataset_summaries(rows)
    missing = [
        dataset["key"]
        for dataset in dataset_summaries
        if dataset["missing_stock_count"] or dataset["stale_stock_count"]
    ]
    expected_dates = {
        dataset["key"]: dataset["expected"]
        for dataset in dataset_summaries
        if dataset["expected"] is not None
    }
    warnings: list[str] = []

    if stale_rows:
        warnings.append(
            "Local OMI data is incomplete for "
            f"{len(stale_rows)} stock(s); affected datasets: {', '.join(missing)}. "
            "Refresh OMI before relying on AI conclusions."
        )

    if len(stale_rows) > len(stale_details):
        warnings.append(
            "Freshness details were truncated to "
            f"{MAX_STALE_STOCK_DETAILS} stale stock(s)."
        )

    if len(stale_rows) > len(stale_stock_ids):
        warnings.append(
            "Freshness stale stock id list was truncated to "
            f"{MAX_STALE_STOCK_IDS} stock(s)."
        )

    return {
        "kind": "ai_scope_freshness",
        "scope_type": scope_type,
        "scope_id": scope_id,
        "expected_trade_date": expected_dates.get("market_daily_price"),
        "expected_dates": expected_dates,
        "is_current": not stale_rows,
        "checked_stock_count": len(rows),
        "stale_stock_count": len(stale_rows),
        "stale_stock_ids": stale_stock_ids,
        "stale_stock_ids_truncated": len(stale_stock_ids) < len(stale_rows),
        "stale_stocks": stale_details,
        "datasets": dataset_summaries,
        "missing": missing,
        "warnings": warnings,
        "refresh_recommended": bool(stale_rows),
        "refresh_endpoint": refresh_endpoint,
        "refresh_params": refresh_params,
    }


def check_stock_data_freshness(db: Session, stock_id: str) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    rows = _stock_freshness_rows(
        db=db,
        candidates=[StockCandidate(stock_id=normalized_stock_id)],
    )
    return _build_result(
        scope_type="stock",
        scope_id=normalized_stock_id,
        rows=rows,
        refresh_endpoint=f"/api/market/selection-refresh/{normalized_stock_id}",
        refresh_params={
            "include_today": None,
            "profile": "full",
            "sleep_seconds": 0.05,
        },
    )


def check_watchlist_data_freshness(
    db: Session,
    group_id: int,
    *,
    include_children: bool = True,
    enabled_only: bool = True,
) -> dict[str, Any]:
    items = watchlist_service.list_items(
        db=db,
        group_id=group_id,
        enabled=True if enabled_only else None,
        include_children=include_children,
        limit=10000,
        offset=0,
    )
    seen_stock_ids: set[str] = set()
    candidates: list[StockCandidate] = []

    for item in items:
        stock_id = item["stock_id"]
        if stock_id in seen_stock_ids:
            continue

        seen_stock_ids.add(stock_id)
        candidates.append(
            StockCandidate(
                stock_id=stock_id,
                stock_name=item.get("stock_name"),
            )
        )

    result = _build_result(
        scope_type="watchlist",
        scope_id=str(group_id),
        rows=_stock_freshness_rows(db=db, candidates=candidates),
        refresh_endpoint=f"/api/watchlists/groups/{group_id}/refresh-latest",
        refresh_params={
            "lookback_days": 14,
            "include_today": False,
            "include_children": include_children,
            "enabled_only": enabled_only,
            "sleep_seconds": 0.3,
            "skip_existing_months": True,
            "full_refresh_endpoint_template": "/api/market/selection-refresh/{stock_id}",
            "full_refresh_params": {
                "include_today": None,
                "profile": "full",
                "sleep_seconds": 0.05,
            },
            "note": (
                "This group endpoint refreshes daily prices. "
                "Use /api/market/selection-refresh/{stock_id} per affected stock "
                "to refresh the full stock evidence pack."
            ),
        },
    )

    if not candidates:
        result["warnings"].append("Watchlist has no enabled stocks to check for data freshness.")

    return result


def check_stock_daily_price_freshness(db: Session, stock_id: str) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized_stock_id)
        .first()
    )
    latest = (
        db.query(func.max(MarketDailyPrice.trade_date))
        .filter(MarketDailyPrice.stock_id == normalized_stock_id)
        .scalar()
    )
    expected = expected_daily_price_date()
    daily_spec = next(
        spec for spec in DATASET_SPECS if spec.key == TAIWAN_DATASET_DAILY_PRICE
    )
    candidate = StockCandidate(
        stock_id=normalized_stock_id,
        stock_name=stock.stock_name if stock is not None else None,
    )
    datasets = [
        _stock_master_check(candidate, stock),
        _dataset_check(
            spec=daily_spec,
            stock_id=normalized_stock_id,
            latest_value=latest,
            expected_date=expected,
            required=True,
        ),
    ]
    issues = [dataset for dataset in datasets if not dataset["is_current"]]
    missing = [dataset["key"] for dataset in issues]
    warnings = (
        [
            "Latest quote evidence is unavailable or stale for "
            f"{normalized_stock_id}: {', '.join(missing)}."
        ]
        if issues
        else []
    )
    return {
        "kind": "ai_scope_freshness",
        "scope_type": "stock",
        "scope_id": normalized_stock_id,
        "scope_profile": "quote_only",
        "expected_trade_date": _json_value(expected),
        "expected_dates": {
            TAIWAN_DATASET_DAILY_PRICE: _json_value(expected),
        },
        "is_current": not issues,
        "checked_stock_count": 1,
        "stale_stock_count": 1 if issues else 0,
        "stale_stock_ids": [normalized_stock_id] if issues else [],
        "stale_stock_ids_truncated": False,
        "stale_stocks": (
            [
                {
                    "stock_id": normalized_stock_id,
                    "stock_name": candidate.stock_name,
                    "market": stock.market if stock is not None else None,
                    "instrument_type": stock.instrument_type if stock is not None else None,
                    "issue_count": len(issues),
                    "issues": issues,
                }
            ]
            if issues
            else []
        ),
        "datasets": datasets,
        "missing": missing,
        "warnings": warnings,
        "refresh_recommended": False,
        "refresh_endpoint": None,
        "refresh_params": {},
    }


def check_stock_broker_branch_freshness(db: Session, stock_id: str) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized_stock_id)
        .first()
    )
    latest = (
        db.query(func.max(BrokerBranchTradeDaily.trade_date))
        .filter(BrokerBranchTradeDaily.stock_id == normalized_stock_id)
        .scalar()
    )
    expected = expected_broker_branch_date()
    branch_spec = next(
        spec for spec in DATASET_SPECS if spec.key == TAIWAN_DATASET_BROKER_BRANCH
    )
    candidate = StockCandidate(
        stock_id=normalized_stock_id,
        stock_name=stock.stock_name if stock is not None else None,
    )
    datasets = [
        _stock_master_check(candidate, stock),
        _dataset_check(
            spec=branch_spec,
            stock_id=normalized_stock_id,
            latest_value=latest,
            expected_date=expected,
            required=True,
        ),
    ]
    issues = [dataset for dataset in datasets if not dataset["is_current"]]
    missing = [dataset["key"] for dataset in issues]
    warnings = (
        [
            "Broker branch evidence is unavailable or stale for "
            f"{normalized_stock_id}: {', '.join(missing)}."
        ]
        if issues
        else []
    )
    return {
        "kind": "ai_scope_freshness",
        "scope_type": "stock",
        "scope_id": normalized_stock_id,
        "scope_profile": "broker_branch_only",
        "expected_trade_date": _json_value(expected),
        "expected_dates": {
            TAIWAN_DATASET_BROKER_BRANCH: _json_value(expected),
        },
        "is_current": not issues,
        "checked_stock_count": 1,
        "stale_stock_count": 1 if issues else 0,
        "stale_stock_ids": [normalized_stock_id] if issues else [],
        "stale_stock_ids_truncated": False,
        "stale_stocks": [],
        "datasets": datasets,
        "missing": missing,
        "warnings": warnings,
        "refresh_recommended": False,
        "refresh_endpoint": None,
        "refresh_params": {},
    }


def check_watchlist_daily_price_freshness(
    db: Session,
    group_id: int,
    *,
    include_children: bool = True,
    enabled_only: bool = True,
) -> dict[str, Any]:
    return check_watchlist_data_freshness(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )
