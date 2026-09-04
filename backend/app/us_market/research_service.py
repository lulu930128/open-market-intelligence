"""Cache-only US research projections built from resolved market evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    USCompanyProfile,
    USCorporateAction,
    USStockMaster,
)
from app.market_data.contracts import InstrumentType
from app.research.coverage import build_market_coverage_gate
from app.research.technical import (
    US_DAILY_PROFILE,
    US_INDEX_DAILY_PROFILE,
    build_technical_indicators,
    build_technical_structure,
)
from app.us_market.daily_market_state import resolve_us_instrument_identity
from app.us_market.daily_ohlcv_chart import read_us_daily_ohlcv_chart
from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
from app.us_market.resolved_reads import (
    US_RESOLVED_DAILY_MAX_BARS,
    read_resolved_us_daily_bars_for_symbol,
)
from app.us_market.sources import normalize_us_symbol
from app.us_market.trading_calendar import (
    expected_us_daily_price_date,
)


US_RESEARCH_SCHEMA_VERSION = "omi.us_market.research.v1"


def _coverage_gate(db: Session, *, expected_trade_date, now: datetime) -> dict[str, Any]:
    coverage = US_FULL_MARKET_EOD_LIFECYCLE.compute_coverage(
        db,
        expected_trade_date=expected_trade_date,
    )
    observed_count = len(coverage.members)
    fresh_count = len(coverage.current_symbols)
    latest_master_update = db.query(func.max(USStockMaster.updated_at)).scalar()
    version_suffix = (
        latest_master_update.isoformat()
        if isinstance(latest_master_update, datetime)
        else "empty"
    )
    gate = build_market_coverage_gate(
        market="US",
        universe_id="us_stock_master.active",
        universe_version=f"us_stock_master.active.v1@{version_suffix}",
        as_of=expected_trade_date.isoformat(),
        expected_count=None,
        observed_count=observed_count,
        fresh_count=fresh_count,
        universe_complete=False,
    )
    classified_count = int(
        db.query(func.count(func.distinct(USCompanyProfile.symbol)))
        .filter(USCompanyProfile.sector.isnot(None))
        .filter(USCompanyProfile.industry.isnot(None))
        .scalar()
        or 0
    )
    latest_classification_update = db.query(
        func.max(USCompanyProfile.fetched_at)
    ).scalar()
    gate["classification_coverage"] = {
        "taxonomy_id": "us_company_profile.provider_reported",
        "taxonomy_version": (
            "us_company_profile.provider_reported.v1@"
            + (
                latest_classification_update.isoformat()
                if isinstance(latest_classification_update, datetime)
                else "empty"
            )
        ),
        "source_scope": "provider_reported_company_profile",
        "mapped_count": classified_count,
        "observed_universe_count": observed_count,
        "coverage_ratio": (
            classified_count / observed_count if observed_count > 0 else None
        ),
        "effective_date": None,
        "universe_complete": False,
        "decision_usable": False,
        "reason_codes": [
            "STANDARD_TAXONOMY_NOT_CONFIGURED",
            "EFFECTIVE_MEMBERSHIP_DATE_UNKNOWN",
        ],
    }
    return gate


def build_us_market_research(
    db: Session,
    *,
    symbol: str,
    bars: int = 260,
    now: datetime | None = None,
    include_market_coverage: bool = True,
    include_daily_ohlcv: bool = True,
    timeframe: str = "daily",
) -> dict[str, Any]:
    """Build bounded research from cache only; never fetch or persist provider data."""

    if bars < 1 or bars > US_RESOLVED_DAILY_MAX_BARS:
        raise ValueError(
            f"bars must be between 1 and {US_RESOLVED_DAILY_MAX_BARS}"
        )
    normalized_symbol = normalize_us_symbol(symbol)
    resolved_now = now or datetime.now(timezone.utc)
    if resolved_now.tzinfo is None or resolved_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    expected_trade_date = expected_us_daily_price_date(now=resolved_now)
    if timeframe not in {"daily", "weekly", "monthly"}:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")
    coverage_gate = (
        _coverage_gate(
            db,
            expected_trade_date=expected_trade_date,
            now=resolved_now,
        )
        if include_market_coverage
        else {
            "kind": "market_coverage_reference",
            "schema_version": "omi.us_market.coverage_reference.v1",
            "status": "unavailable",
            "snapshot_id": None,
            "as_of": None,
            "reason_codes": ["US_MARKET_COVERAGE_SNAPSHOT_UNAVAILABLE"],
        }
    )
    missing: list[str] = []
    warnings: list[str] = []
    daily_ohlcv: dict[str, Any] = {}
    identity = None
    try:
        identity = resolve_us_instrument_identity(db, normalized_symbol)
        daily_ohlcv = (
            read_resolved_us_daily_bars_for_symbol(
                db=db,
                symbol=normalized_symbol,
                expected_trade_date=expected_trade_date,
                now=resolved_now,
                bars=bars,
            )
            if timeframe == "daily"
            else read_us_daily_ohlcv_chart(
                db,
                symbol=normalized_symbol,
                timeframe=timeframe,
                bars=bars,
                now=resolved_now,
            )
        )
        if not daily_ohlcv:
            missing.append("resolved_daily_ohlcv")
    except LookupError as exc:
        missing.append("instrument_identity")
        warnings.append(str(exc))

    is_index = bool(
        identity is not None
        and identity.instrument.instrument_type is InstrumentType.INDEX
    )
    corporate_action_count = (
        0
        if is_index
        else int(
            db.query(func.count(USCorporateAction.id))
            .filter(USCorporateAction.symbol == normalized_symbol)
            .scalar()
            or 0
        )
    )
    # Company corporate actions are not applicable to index observations. For
    # stocks/ETFs, event rows prove observations but not complete coverage.
    corporate_action_coverage = "not_applicable" if is_index else "unknown"
    technical_profile = US_INDEX_DAILY_PROFILE if is_index else US_DAILY_PROFILE
    if timeframe != "daily":
        technical_profile = replace(
            technical_profile,
            profile_id=f"{technical_profile.profile_id}.{timeframe}",
            profile_version=f"{technical_profile.profile_version}.{timeframe}.v1",
            timeframe={"weekly": "1w", "monthly": "1mo"}[timeframe],
        )
    resolved_bars = next(
        (
            daily_ohlcv.get(key)
            for key in ("bars", "points")
            if isinstance(daily_ohlcv.get(key), list)
        ),
        [],
    )
    lineage = {
        "selected_provider": daily_ohlcv.get("selected_provider"),
        "selected_source": daily_ohlcv.get("selected_source"),
        "selected_event_at": daily_ohlcv.get("selected_event_at"),
        "fallback_used": daily_ohlcv.get("fallback_used"),
        "selection_reason": daily_ohlcv.get("selection_reason"),
    }
    indicators = build_technical_indicators(
        market="US",
        symbol=normalized_symbol,
        bars=resolved_bars,
        profile=technical_profile,
        freshness_status=(
            "fresh"
            if daily_ohlcv.get("research_usable") is True
            and daily_ohlcv.get("selected_event_at")
            else "missing"
        ),
        resolved_facts_usable=daily_ohlcv.get("facts_usable") is True,
        corporate_action_coverage=corporate_action_coverage,
        lineage=lineage,
    )
    structure = build_technical_structure(
        indicators=indicators,
        bars=resolved_bars,
        profile=technical_profile,
    )
    if indicators["quality"]["decision_usable"] is not True:
        warnings.append(
            "US technical evidence is not decision-usable; quality reason codes remain visible."
        )
    return {
        "kind": "us_market_research",
        "schema_version": US_RESEARCH_SCHEMA_VERSION,
        "market": "US",
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "status": indicators["status"],
        "as_of": indicators.get("as_of"),
        "daily_ohlcv": daily_ohlcv if include_daily_ohlcv else {},
        "technical_indicators": indicators,
        "technical_structure": structure,
        "corporate_action_coverage": {
            "applicability": "not_applicable" if is_index else "required",
            "status": corporate_action_coverage,
            "observed_event_count": corporate_action_count,
            "completeness_checkpoint": None,
        },
        "market_coverage": coverage_gate,
        "missing": missing,
        "warnings": warnings,
    }


__all__ = ["US_RESEARCH_SCHEMA_VERSION", "build_us_market_research"]
