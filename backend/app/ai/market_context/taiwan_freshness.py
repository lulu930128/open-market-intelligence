from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.evidence_passport import build_evidence_passport
from app.db.models import (
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
)


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


def read_data_freshness(
    db: Session,
    stock_id: str | None = None,
    *,
    now: Callable[[], datetime],
) -> dict[str, Any]:
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

    tables = {
        "market_daily_price": {
            "latest": _json_value(latest(MarketDailyPrice, MarketDailyPrice.trade_date)),
            "row_count": count(MarketDailyPrice),
        },
        "institutional_trade_daily": {
            "latest": _json_value(latest(InstitutionalTradeDaily, InstitutionalTradeDaily.trade_date)),
            "row_count": count(InstitutionalTradeDaily),
        },
        "margin_trading_daily": {
            "latest": _json_value(latest(MarginTradingDaily, MarginTradingDaily.trade_date)),
            "row_count": count(MarginTradingDaily),
        },
        "broker_branch_trade_daily": {
            "latest": _json_value(latest(BrokerBranchTradeDaily, BrokerBranchTradeDaily.trade_date)),
            "row_count": count(BrokerBranchTradeDaily),
        },
        "shareholding_distribution_weekly": {
            "latest": _json_value(
                latest(ShareholdingDistributionWeekly, ShareholdingDistributionWeekly.data_date)
            ),
            "row_count": count(ShareholdingDistributionWeekly),
        },
        "monthly_revenue": {
            "latest": _json_value(latest(MonthlyRevenue, MonthlyRevenue.period)),
            "row_count": count(MonthlyRevenue),
        },
        "financial_metric_quarterly": {
            "latest": _latest_financial_period(financial_latest),
            "row_count": count(FinancialMetricQuarterly),
        },
    }
    missing = [name for name, info in tables.items() if not info["latest"] or info["row_count"] == 0]
    warnings = [
        "Freshness is based on the local OMI database, not direct exchange availability.",
    ]
    envelope = {
        "kind": "data_freshness",
        "generated_at": now(),
        "as_of": _latest_date_string([info["latest"] for info in tables.values()]),
        "scope": {"stock_id": stock_id},
        "data": {"tables": tables},
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
            "is_current": not missing,
            "missing": missing,
            "warnings": warnings,
        },
        analysis=None,
        confidence=None,
    )
    return envelope
