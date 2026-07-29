from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricQuarterly,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
    SourceRegistry,
)
from app.market.fundamental_metrics_backfill import ensure_fundamental_metrics
from app.observability.provider_health import record_provider_event


_CATEGORY_CONTRACTS = {
    "shareholding_distribution": {
        "dataset": "shareholding_distribution_weekly",
        "model": ShareholdingDistributionWeekly,
        "latest_column": ShareholdingDistributionWeekly.data_date,
        "provider": "tdcc",
    },
    "monthly_revenue": {
        "dataset": "monthly_revenue",
        "model": MonthlyRevenue,
        "latest_column": MonthlyRevenue.period,
        "provider": "twse+tpex",
    },
    "financial_metrics": {
        "dataset": "financial_metric_quarterly",
        "model": FinancialMetricQuarterly,
        "latest_column": FinancialMetricQuarterly.period,
        "provider": "twse+tpex",
    },
}


def _latest_key(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _source_coverage(
    db: Session,
    *,
    category: str,
    expected_key: str,
) -> dict[str, Any]:
    contract = _CATEGORY_CONTRACTS[category]
    model = contract["model"]
    latest_column = contract["latest_column"]
    sources = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.enabled.is_(True))
        .filter(SourceRegistry.category == category)
        .order_by(SourceRegistry.priority.asc(), SourceRegistry.id.asc())
        .all()
    )
    rows: list[dict[str, Any]] = []
    for source in sources:
        latest_value = (
            db.query(func.max(latest_column))
            .filter(model.source_id == source.id)
            .scalar()
        )
        latest = _latest_key(latest_value)
        rows.append(
            {
                "source_id": source.id,
                "source_name": source.source_name,
                "latest_key": latest,
                "expected_key": expected_key,
                "current": latest is not None and latest >= expected_key,
            }
        )
    return {
        "expected_key": expected_key,
        "source_count": len(rows),
        "current_source_count": sum(1 for row in rows if row["current"]),
        "complete": bool(rows) and all(row["current"] for row in rows),
        "sources": rows,
    }


def refresh_taiwan_fundamental_snapshot(
    db: Session,
    *,
    category: str,
    dataset: str,
    expected_key: str,
    completion_target: str,
    sleep_seconds: float = 0.2,
    job_run_id: int | None = None,
) -> dict[str, Any]:
    contract = _CATEGORY_CONTRACTS.get(category)
    if contract is None:
        raise ValueError(f"Unsupported Taiwan fundamental snapshot category: {category}.")
    if contract["dataset"] != dataset:
        raise ValueError(
            f"Dataset '{dataset}' does not match category '{category}'."
        )

    provider_result = ensure_fundamental_metrics(
        db=db,
        categories=[category],
        force=True,
        sleep_seconds=sleep_seconds,
    )
    coverage = _source_coverage(
        db,
        category=category,
        expected_key=expected_key,
    )
    provider_status = str(provider_result.get("status") or "unknown")
    if provider_status == "error":
        status = "failed"
        event_status = "error"
    elif coverage["complete"]:
        status = "completed"
        event_status = "success"
    else:
        status = "partial"
        event_status = "stale"

    error_messages = [
        str(row.get("error_message"))
        for row in provider_result.get("results") or []
        if row.get("error_message")
    ]
    record_provider_event(
        db,
        market="tw",
        provider=str(contract["provider"]),
        resource=dataset,
        target=completion_target,
        status=event_status,
        event_type="scheduled_collection",
        message=(
            "Taiwan scheduled fundamental snapshot reached the expected key."
            if coverage["complete"]
            else "Taiwan scheduled fundamental snapshot remains behind the expected key."
        ),
        error_message="; ".join(error_messages[:5]) or None,
        detail={
            "category": category,
            "expected_key": expected_key,
            "completion_target": completion_target,
            "provider_status": provider_status,
            "coverage": coverage,
        },
        job_run_id=job_run_id,
    )
    return {
        **provider_result,
        "status": status,
        "provider_status": provider_status,
        "dataset": dataset,
        "expected_key": expected_key,
        "completion_target": completion_target,
        "coverage": coverage,
    }


__all__ = ["refresh_taiwan_fundamental_snapshot"]
