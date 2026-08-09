from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import USDailyPrice
from app.market.cross_market.schemas import (
    CrossMarketContextSignalRead,
    CrossMarketRelationRead,
)


PROXY_METHODOLOGY_VERSION = "cross_market.simple_sector_residual.v1"
BENCHMARK_POLICY_VERSION = "cross_market.proxy_benchmark.v1"


@dataclass(frozen=True)
class ProxyBenchmarkRule:
    benchmark_symbol: str
    beta: float
    methodology: str


PROXY_BENCHMARK_RULES: dict[str, ProxyBenchmarkRule] = {
    "dram_memory_cycle_proxy": ProxyBenchmarkRule(
        benchmark_symbol="^SOX",
        beta=1.0,
        methodology="simple_sector_residual",
    ),
}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _price_rows(
    db: Session,
    symbol: str,
    *,
    expected_trade_date: date,
    data_available_at: datetime | None,
) -> list[USDailyPrice]:
    query = db.query(USDailyPrice).filter(
        USDailyPrice.symbol == symbol,
        USDailyPrice.trade_date <= expected_trade_date,
    )
    if data_available_at is not None:
        query = query.filter(USDailyPrice.fetched_at <= data_available_at)
    return (
        query.order_by(
            USDailyPrice.trade_date.desc(),
            USDailyPrice.fetched_at.desc(),
            USDailyPrice.id.desc(),
        )
        .limit(2)
        .all()
    )


def _return_snapshot(
    db: Session,
    symbol: str,
    *,
    expected_trade_date: date,
    data_available_at: datetime | None,
) -> dict[str, Any]:
    rows = _price_rows(
        db,
        symbol,
        expected_trade_date=expected_trade_date,
        data_available_at=data_available_at,
    )
    latest = rows[0] if rows else None
    previous = rows[1] if len(rows) > 1 else None
    latest_close = _finite(
        latest.adjusted_close if latest is not None else None
    ) or _finite(latest.close_price if latest is not None else None)
    previous_close = _finite(
        previous.adjusted_close if previous is not None else None
    ) or _finite(previous.close_price if previous is not None else None)
    return_pct = (
        round((latest_close / previous_close - 1.0) * 100.0, 6)
        if latest_close is not None
        and previous_close is not None
        and latest_close > 0
        and previous_close > 0
        else None
    )
    return {
        "symbol": symbol,
        "trade_date": latest.trade_date if latest is not None else None,
        "previous_trade_date": previous.trade_date if previous is not None else None,
        "close": latest_close,
        "previous_close": previous_close,
        "return_pct": return_pct,
        "provider": latest.provider if latest is not None else None,
        "fetched_at": latest.fetched_at if latest is not None else None,
        "is_expected_date": bool(
            latest is not None and latest.trade_date == expected_trade_date
        ),
    }


def build_proxy_signal(
    db: Session,
    relation: CrossMarketRelationRead,
    *,
    expected_trade_date: date,
    data_available_at: datetime | None = None,
) -> CrossMarketContextSignalRead:
    source_symbol = str(relation.source.provider_symbol or "").strip().upper()
    rule = PROXY_BENCHMARK_RULES.get(str(relation.relation_subtype or ""))
    source_snapshot = _return_snapshot(
        db,
        source_symbol,
        expected_trade_date=expected_trade_date,
        data_available_at=data_available_at,
    )
    benchmark_snapshot = (
        _return_snapshot(
            db,
            rule.benchmark_symbol,
            expected_trade_date=expected_trade_date,
            data_available_at=data_available_at,
        )
        if rule is not None
        else None
    )
    raw_return = source_snapshot.get("return_pct")
    benchmark_return = (
        benchmark_snapshot.get("return_pct")
        if isinstance(benchmark_snapshot, dict)
        else None
    )
    excess_return = (
        round(raw_return - rule.beta * benchmark_return, 6)
        if raw_return is not None
        and benchmark_return is not None
        and rule is not None
        else None
    )

    missing = [
        key
        for key, value in (
            (f"us_daily_price.{source_symbol}", raw_return),
            (
                f"us_daily_price.{rule.benchmark_symbol}"
                if rule is not None
                else "proxy_benchmark_policy",
                benchmark_return,
            ),
        )
        if value is None
    ]
    stale = bool(
        raw_return is not None
        and not source_snapshot.get("is_expected_date")
    ) or bool(
        benchmark_return is not None
        and isinstance(benchmark_snapshot, dict)
        and not benchmark_snapshot.get("is_expected_date")
    )
    date_mismatch = bool(
        raw_return is not None
        and benchmark_return is not None
        and source_snapshot.get("trade_date")
        != benchmark_snapshot.get("trade_date")
    )
    if not relation.decision_usable:
        status = "blocked"
        excluded_reason = "relation_not_decision_usable"
    elif rule is None:
        status = "blocked"
        excluded_reason = "benchmark_policy_missing"
    elif missing:
        status = "blocked"
        excluded_reason = "benchmark_or_return_missing"
    elif date_mismatch:
        status = "blocked"
        excluded_reason = "date_alignment_failed"
    elif stale:
        status = "stale"
        excluded_reason = "provider_data_stale"
    else:
        status = "ready"
        excluded_reason = None
    decision_usable = status == "ready" and excess_return is not None
    direction = (
        "supportive"
        if excess_return is not None and excess_return > 0.35
        else "adverse"
        if excess_return is not None and excess_return < -0.35
        else "neutral"
        if excess_return is not None
        else "unknown"
    )
    confidence_multiplier = 0.6 if relation.confidence_tier == "C" else 0.0
    freshness_multiplier = 1.0 if decision_usable else 0.0
    event_relevance = 1.0
    liquidity_multiplier = 1.0
    quality_multiplier = round(
        confidence_multiplier
        * freshness_multiplier
        * event_relevance
        * liquidity_multiplier,
        6,
    )
    effective_weight = round(relation.base_weight * quality_multiplier, 6)
    contribution = (
        round(excess_return * effective_weight, 6)
        if decision_usable and excess_return is not None
        else None
    )
    evidence_refs = [
        f"cross_market_relation_evidence:{item.evidence_id}"
        for item in relation.evidence
    ]
    limitations = list(
        dict.fromkeys(
            [
                *relation.limitations,
                "industry_proxy_not_company_causality",
                "event_context_unresolved",
                "liquidity_adjustment_not_available",
            ]
        )
    )
    warnings = list(
        dict.fromkeys(
            [
                *relation.warnings,
                "event_context_unresolved",
                *(missing or []),
                *(["date_alignment_failed"] if date_mismatch else []),
                *(["provider_data_stale"] if stale else []),
            ]
        )
    )
    return CrossMarketContextSignalRead(
        signal_id=(
            f"proxy_residual:{relation.target.canonical_symbol}:"
            f"{relation.relation_id}:v{relation.relation_version}"
        ),
        relation_id=relation.relation_id,
        relation_version=relation.relation_version,
        source=relation.source,
        target=relation.target,
        bucket=relation.bucket,
        relation_type=relation.relation_type,
        relation_subtype=relation.relation_subtype,
        event_context="unresolved",
        calculation={
            "kind": "benchmark_residual",
            "methodology": rule.methodology if rule is not None else None,
            "methodology_version": PROXY_METHODOLOGY_VERSION,
            "benchmark_policy_version": BENCHMARK_POLICY_VERSION,
            "benchmark": (
                f"US:{rule.benchmark_symbol}" if rule is not None else None
            ),
            "beta": rule.beta if rule is not None else None,
            "raw_return_pct": raw_return,
            "benchmark_return_pct": benchmark_return,
            "excess_return_pct": excess_return,
            "source_trade_date": source_snapshot.get("trade_date"),
            "benchmark_trade_date": (
                benchmark_snapshot.get("trade_date")
                if isinstance(benchmark_snapshot, dict)
                else None
            ),
            "event_context": "unresolved",
            "event_relevance": event_relevance,
            "confidence_multiplier": confidence_multiplier,
            "freshness_multiplier": freshness_multiplier,
            "liquidity_multiplier": liquidity_multiplier,
        },
        direction=direction,
        configured_weight=relation.base_weight,
        quality_multiplier=quality_multiplier,
        effective_weight=effective_weight,
        contribution=contribution,
        status=status,
        decision_usable=decision_usable,
        confidence_tier=relation.confidence_tier,
        freshness={
            "status": "current" if decision_usable else status,
            "expected_trade_date": expected_trade_date,
            "source": source_snapshot,
            "benchmark": benchmark_snapshot or {},
            "data_available_at": data_available_at,
        },
        evidence_refs=evidence_refs,
        source_refs=[
            {
                "type": "table",
                "name": "us_daily_price",
                "provider": str(source_snapshot.get("provider") or "unknown"),
            },
            {"type": "derived", "name": "app.market.cross_market.proxy_signal_engine"},
        ],
        warnings=warnings,
        limitations=limitations,
        excluded_reason=excluded_reason,
    )


__all__ = [
    "BENCHMARK_POLICY_VERSION",
    "PROXY_BENCHMARK_RULES",
    "PROXY_METHODOLOGY_VERSION",
    "build_proxy_signal",
]
