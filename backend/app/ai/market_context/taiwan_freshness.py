from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import slot_envelope
from app.db.models import (
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
)
from app.market.taiwan_rules import expected_date_for_dataset
from app.market.tw_daily_freshness import read_taiwan_daily_freshness


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _latest_date_string(values: list[Any]) -> str | None:
    valid_values = [_json_value(value) for value in values if value is not None]
    if not valid_values:
        return None
    return str(max(valid_values))


def _latest_financial_period(row: FinancialMetricQuarterly | None) -> str | None:
    if row is None:
        return None
    return row.period or f"{row.fiscal_year}Q{row.quarter}"


def _table_state(
    *,
    latest: Any,
    row_count: int,
    expected: date | None,
) -> dict[str, Any]:
    availability = "available" if latest is not None and row_count > 0 else "missing"
    if availability == "missing":
        freshness = "missing"
    elif expected is None:
        freshness = "unknown"
    elif isinstance(latest, date) and latest >= expected:
        freshness = "current"
    else:
        freshness = "stale"
    return {
        "latest": _json_value(latest),
        "row_count": row_count,
        "availability": availability,
        "freshness": freshness,
        "expected": _json_value(expected),
    }


def _canonical_daily_table_state(evidence) -> dict[str, Any]:
    status = evidence.health.status.value
    freshness = {
        "healthy": "current",
        "stale": "stale",
        "missing": "missing",
        "partial": "partial",
        "not_applicable": "not_applicable",
        "unavailable": "unavailable",
        "unknown": "unknown",
    }.get(status, "unknown")
    return {
        "latest": _json_value(evidence.latest_date),
        "row_count": evidence.row_count,
        "availability": (
            "available"
            if evidence.latest_date is not None and evidence.row_count > 0
            else "missing"
        ),
        "freshness": freshness,
        "expected": _json_value(evidence.health.expected_date),
        "canonical_dataset_id": evidence.health.dataset_id,
        "dataset_health": evidence.health.model_dump(mode="json"),
        "limitations": list(evidence.limitations),
    }


def read_data_freshness(
    db: Session,
    stock_id: str | None = None,
    *,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    checked_at = now()

    def latest(model: Any, column: Any) -> Any:
        query = db.query(func.max(column))
        if stock_id and hasattr(model, "stock_id"):
            query = query.filter(model.stock_id == stock_id)
        return query.scalar()

    def count(model: Any) -> int:
        query = db.query(func.count(model.id))
        if stock_id and hasattr(model, "stock_id"):
            query = query.filter(model.stock_id == stock_id)
        return int(query.scalar() or 0)

    financial_latest = (
        db.query(FinancialMetricQuarterly)
        .filter(FinancialMetricQuarterly.stock_id == stock_id)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
        if stock_id
        else db.query(FinancialMetricQuarterly)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
    )
    daily_freshness = read_taiwan_daily_freshness(
        db,
        stock_id=stock_id,
        checked_at=checked_at,
    )

    table_values = {
        "institutional_trade_daily": (
            latest(InstitutionalTradeDaily, InstitutionalTradeDaily.trade_date),
            count(InstitutionalTradeDaily),
        ),
        "margin_trading_daily": (
            latest(MarginTradingDaily, MarginTradingDaily.trade_date),
            count(MarginTradingDaily),
        ),
        "broker_branch_trade_daily": (
            latest(BrokerBranchTradeDaily, BrokerBranchTradeDaily.trade_date),
            count(BrokerBranchTradeDaily),
        ),
        "shareholding_distribution_weekly": (
            latest(ShareholdingDistributionWeekly, ShareholdingDistributionWeekly.data_date),
            count(ShareholdingDistributionWeekly),
        ),
        "monthly_revenue": (
            latest(MonthlyRevenue, MonthlyRevenue.period),
            count(MonthlyRevenue),
        ),
        "financial_metric_quarterly": (
            _latest_financial_period(financial_latest),
            count(FinancialMetricQuarterly),
        ),
    }
    tables = {
        "market_daily_price": _canonical_daily_table_state(daily_freshness),
        **{
        name: _table_state(
            latest=latest_value,
            row_count=row_count,
            expected=expected_date_for_dataset(name, now=checked_at),
        )
        for name, (latest_value, row_count) in table_values.items()
        },
    }
    missing = [name for name, info in tables.items() if info["availability"] == "missing"]
    stale = [name for name, info in tables.items() if info["freshness"] == "stale"]
    partial = [
        name
        for name, info in tables.items()
        if info["freshness"] in {"partial", "unavailable"}
    ]
    unknown = [name for name, info in tables.items() if info["freshness"] == "unknown"]
    overall_freshness = (
        "missing"
        if missing
        else "stale"
        if stale
        else "partial"
        if partial
        else "unknown"
        if unknown
        else "current"
    )
    warnings = [
        "Freshness is based on the local OMI database, not direct exchange availability.",
    ]
    if stale:
        warnings.append(f"Stale local datasets: {', '.join(stale)}.")
    if partial:
        warnings.append(f"Partial or unavailable datasets: {', '.join(partial)}.")
    if unknown:
        warnings.append(f"Freshness calendar is not defined for: {', '.join(unknown)}.")
    slot_status = {
        "current": "ready",
        "stale": "stale",
        "unknown": "partial",
        "missing": "missing",
        "partial": "partial",
        "unavailable": "failed",
        "not_applicable": "not_applicable",
    }
    slots = {
        name: slot_envelope(
            status=slot_status[info["freshness"]],
            capability=f"local_table_{name}",
            payload_ref=f"tables.{name}",
            payload_level="compact",
            as_of=info["latest"],
            missing=[name] if info["availability"] == "missing" else None,
            warnings=(
                [f"availability={info['availability']}; freshness={info['freshness']}"]
                if info["freshness"] != "current"
                else None
            ),
        )
        for name, info in tables.items()
    }
    slots["data_quality"] = slot_envelope(
        status="partial" if missing or stale or partial or unknown else "ready",
        capability="local_database_coverage",
        payload_ref="tables",
        payload_level="compact",
        priority="core",
        missing=missing,
        warnings=["table availability does not prove exchange-current freshness", *warnings[1:]],
    )
    compact = {
        "kind": "data_freshness_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": "compact",
        "target": {"type": "data_freshness", "id": stock_id, "market": "TW"},
        "status": overall_freshness,
        "tables": tables,
        "freshness_by_domain": {
            name: info["freshness"]
            for name, info in tables.items()
        },
        "slots": slots,
    }
    envelope = {
        "kind": "data_freshness",
        "generated_at": checked_at,
        "as_of": _latest_date_string([info["latest"] for info in tables.values()]),
        "scope": {"stock_id": stock_id},
        "data": {
            "status": overall_freshness,
            "tables": tables,
            "compact": compact,
            "slots": slots,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [{"type": "database", "name": "open_market_intelligence.db"}],
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind="data_freshness",
        as_of=envelope["as_of"],
        source_refs=envelope["source_refs"],
        missing=missing,
        warnings=warnings,
        freshness={
            "status": overall_freshness,
            "is_current": (
                False
                if stale or partial
                else True
                if not missing and not unknown
                else None
            ),
            "missing": missing,
            "warnings": warnings,
        },
        analysis=None,
        confidence=None,
    )
    return envelope
