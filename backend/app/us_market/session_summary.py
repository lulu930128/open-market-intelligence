"""Read-only Today metrics over one resolved US Market Truth generation."""

from __future__ import annotations

from datetime import date, datetime, time
import logging
from typing import Literal

from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.market_data.contracts import BarFinalization, CanonicalModel, InstrumentType, QuantityUnit, ResolvedBarSeries
from app.research.technical.intraday import enrich_intraday_technical_points
from app.us_market.intraday_platform import USIntradayMarketPlatform, build_us_resolved_volume_pace
from app.us_market.market_truth_contracts import USIntradaySeriesProjection, USMarketTruthSnapshot
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, previous_us_trading_day


logger = logging.getLogger(__name__)
MetricKey = Literal[
    "open", "high", "low", "reference", "average", "volume", "turnover",
    "last_volume", "previous_volume", "bid", "ask", "range_pct", "relative_volume",
    "vwap_distance_pct",
]


class USSessionMetric(CanonicalModel):
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str
    status: Literal["available", "partial", "unavailable"] = "unavailable"
    estimated: bool = False
    method: str
    trade_date: date | None
    as_of: datetime | None = None
    source: str
    scope: str
    freshness: str | None = None
    coverage: str | None = None
    sample_days: int | None = None
    limitations: tuple[str, ...] = ()


class USSessionSummaryRead(CanonicalModel):
    contract_version: Literal["us.chart.session_summary.v1"] = "us.chart.session_summary.v1"
    instrument_id: str
    trade_date: date | None
    base_interval: Literal["1m"] = "1m"
    series_revision: str
    session_scope: Literal["regular", "extended", "all"]
    reference_type: str = "prior_regular_close"
    metrics: dict[MetricKey, USSessionMetric]
    limitations: tuple[str, ...] = ()


def read_us_session_volume_pace(
    db: Session, *, series: USIntradaySeriesProjection,
    intraday: ResolvedBarSeries, daily: ResolvedBarSeries,
) -> dict | None:
    """Reuse the selected-source, 35-day/20-session cache-only volume owner."""
    if (series.requested_scope != "regular" or not series.regular_points
            or series.instrument.instrument_type is InstrumentType.INDEX):
        return None
    selected_times = {point.start_at for point in series.regular_points}
    bars = tuple(bar for bar in intraday.bars if bar.start_at in selected_times)
    if not bars or not intraday.health.selected_provider or not intraday.health.selected_source:
        return None
    if any(bar.volume is None or bar.volume.unit is not QuantityUnit.SHARE for bar in bars):
        return None
    try:
        historical = USIntradayMarketPlatform(db).read_volume_sessions(
            symbol=series.instrument.symbol,
            provider=intraday.health.selected_provider,
            source=intraday.health.selected_source,
            current_trade_date=series.trade_date,
            comparison_time=bars[-1].start_at.astimezone(US_MARKET_TIMEZONE).time(),
            max_sessions=20,
        )
        return build_us_resolved_volume_pace(
            symbol=series.instrument.symbol, intraday_bars=bars,
            daily_bars=daily.bars if daily.health.facts_usable else (),
            historical_sessions=historical,
        )
    except (LookupError, ValueError, SQLAlchemyError):
        logger.warning("US session volume baseline unavailable for %s", series.instrument.symbol, exc_info=True)
        return {"status": "unavailable", "warnings": ["US_VOLUME_BASELINE_READ_UNAVAILABLE"]}


def project_us_session_summary(
    *, snapshot: USMarketTruthSnapshot, series: USIntradaySeriesProjection,
    daily: ResolvedBarSeries, pace: dict | None,
) -> USSessionSummaryRead:
    """No provider selection or IO; chart interval never changes the 1m basis."""
    if series.interval != "1m" or snapshot.instrument != series.instrument:
        raise ValueError("US_SESSION_SUMMARY_IDENTITY_MISMATCH")
    scope = series.requested_scope
    points = sorted((
        *(series.regular_points if scope != "extended" else ()),
        *(series.pre_market_points if scope != "regular" else ()),
        *(series.after_hours_points if scope != "regular" else ()),
    ), key=lambda point: point.start_at)
    index = series.instrument.instrument_type is InstrumentType.INDEX
    price_unit = "index_points" if index else "USD"
    coverage = series.continuity if scope == "regular" else "partial" if points else "missing"
    partial = coverage != "complete" or any(
        point.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED} for point in points
    )
    limits = tuple(series.limitations)
    partial_volume = "PARTIAL_US_MARKET_VOLUME" in limits
    source = snapshot.health.intraday.resolved_health.selected_source or "us.intraday.bars"
    freshness = snapshot.health.intraday.freshness.value
    metrics: dict[MetricKey, USSessionMetric] = {}

    def metric(key: MetricKey, value, unit: str, method: str, **overrides):
        amount = float(value) if value is not None else None
        values = dict(
            value=amount, unit=unit, status="unavailable" if amount is None else "partial" if partial else "available",
            method=method, trade_date=series.trade_date,
            as_of=points[-1].end_at if points else None, source=source,
            scope=f"{scope}_session_1m_bars", freshness=freshness, coverage=coverage, limitations=limits,
        )
        values.update(overrides)
        metrics[key] = USSessionMetric(**values)

    first = points[0] if points else None
    open_known = first is not None and (scope != "regular" or first.start_at.astimezone(US_MARKET_TIMEZONE).time() == time(9, 30))
    metric("open", first.open_price if open_known else None, price_unit, "session_open_1m" if scope == "regular" else "first_observed_open_1m")
    high = max((point.high_price for point in points), default=None)
    low = min((point.low_price for point in points), default=None)
    metric("high", high, price_unit, "selected_1m_high")
    metric("low", low, price_unit, "selected_1m_low")

    prior_date = previous_us_trading_day(series.trade_date, include_value=False) if series.trade_date else None
    # Headline references follow the live phase; Today needs the prior close
    # for the series date. Reuse the already resolved close roles, not hints.
    role_ids = {snapshot.close_roles.latest_completed_id, snapshot.close_roles.prior_completed_id}
    evidence = next((item for item in snapshot.close_evidence
                     if item.evidence_id in role_ids and item.trade_date == prior_date), None)
    reference_value = evidence.price if (evidence and evidence.display_usable
        and evidence.instrument == series.instrument
        and evidence.evidence_kind.value != "provider_previous_close_hint") else None
    metric("reference", reference_value, price_unit, "prior_regular_close",
           status="available" if reference_value is not None else "unavailable",
           trade_date=prior_date, as_of=evidence.event_at if evidence else None,
           source=evidence.source if evidence else "us.close_evidence", scope="comparison_reference",
           freshness=evidence.freshness.value if evidence else None, coverage=None,
           limitations=evidence.limitations if evidence else ("PRIOR_REGULAR_CLOSE_UNAVAILABLE",))

    observed = [point for point in points if point.volume is not None and point.volume >= 0] if not index else []
    volume = sum(point.volume for point in observed) if observed else None
    volume_limits = (*limits, "INDEX_VOLUME_NOT_APPLICABLE") if index else limits
    metric("volume", volume, "shares", "selected_1m_volume_sum", limitations=volume_limits,
           status="unavailable" if volume is None else "partial" if partial or partial_volume or len(observed) != len(points) else "available")
    turnover = sum(point.close_price * point.volume for point in observed) if observed else None
    metric("turnover", turnover, "USD", "bar_close_x_share_volume_1m", estimated=True,
           status=metrics["volume"].status, limitations=volume_limits)

    # Match the shared technical engine's reset at each trading segment.
    active = [point for point in points if point.session == points[-1].session] if points else []
    average = None
    if active and not index and all(point.volume is not None and point.volume >= 0 for point in active):
        enriched = enrich_intraday_technical_points([
            {"price": float(point.close_price), "volume": float(point.volume), "session": point.session.value}
            for point in active
        ])
        average = enriched[-1]["vwap_value"]
    average_scope = f"{active[-1].session.value}_session_1m_bars" if active else f"{scope}_session_1m_bars"
    metric("average", average, price_unit, "shared_technical:close_x_interval_volume", estimated=True,
           scope=average_scope, limitations=volume_limits,
           status="unavailable" if average is None else "partial" if partial or partial_volume else "available")

    for key in ("last_volume", "bid", "ask"):
        metric(key, None, "shares", "not_provided", scope="last_trade" if key == "last_volume" else "top5_price_levels",
               limitations=("US_LAST_TRADE_SIZE_NOT_PROVIDED" if key == "last_volume" else "US_TOP5_DEPTH_NOT_PROVIDED",))
    previous = next((bar for bar in daily.bars if daily.health.facts_usable and bar.end_at.astimezone(US_MARKET_TIMEZONE).date() == prior_date
                     and bar.volume is not None and bar.volume.unit is QuantityUnit.SHARE
                     and bar.finalization in {BarFinalization.FINAL, BarFinalization.CORRECTED}), None) if not index else None
    metric("previous_volume", previous.volume.value if previous else None, "shares", "resolved_daily_volume",
           status="available" if previous else "unavailable", trade_date=prior_date,
           as_of=previous.end_at if previous else None, source=previous.lineage.source if previous else "us.daily.ohlcv",
           scope="regular_session_daily_aggregate", freshness=None, coverage=None,
           limitations=("DAILY_VOLUME_SCOPE_MAY_DIFFER_FROM_INTRADAY",) if previous else ("PRIOR_SESSION_VOLUME_UNAVAILABLE",))
    amplitude = (high - low) / reference_value * 100 if (
        high is not None and low is not None and reference_value is not None and reference_value > 0
        and evidence and all(point.price_basis == evidence.price_basis
                             and point.price_unit == evidence.price_unit
                             and point.currency == evidence.currency for point in points)
    ) else None
    metric("range_pct", amplitude, "percent", "(high-low)/prior_regular_close*100")
    baseline = (pace or {}).get("same_time_baseline_5d") or {}
    ratio = baseline.get("pace_ratio") if (scope == "regular" and volume is not None
        and len(observed) == len(points) and (pace or {}).get("trade_date") == str(series.trade_date)) else None
    metric("relative_volume", ratio, "ratio", "same_time_5d_median",
           sample_days=baseline.get("sample_days"),
           status="unavailable" if ratio is None else "partial" if partial or partial_volume or baseline.get("sample_days", 0) < 5 else "available",
           limitations=(*volume_limits, *((pace or {}).get("warnings") or ()),
                        *(("REGULAR_SESSION_BASELINE_ONLY",) if scope != "regular" else ())))
    distance = (float(points[-1].close_price) / average - 1) * 100 if points and average is not None and average > 0 else None
    metric("vwap_distance_pct", distance, "percent", "latest_bar_close_vs_session_average", estimated=True,
           scope=average_scope, status=metrics["average"].status, limitations=volume_limits)
    return USSessionSummaryRead(
        instrument_id=series.instrument.symbol, trade_date=series.trade_date,
        series_revision=series.intraday_revision, session_scope=scope, metrics=metrics, limitations=limits,
    )
