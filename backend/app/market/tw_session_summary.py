"""Small, read-only Today projection over existing Taiwan evidence owners."""

from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any, Literal

from pydantic import Field
from sqlalchemy.orm import Session

from app.market.daily_ohlcv_platform import project_taiwan_daily_rows, read_taiwan_official_daily
from app.market.quote_depth import read_taiwan_quote_evidence_projection
from app.market.stock_volume_pace import build_tw_stock_volume_pace
from app.market.trading_calendar import previous_taiwan_trading_day
from app.market.tw_bar_contracts import TaiwanBarSeriesRead
from app.market.tw_bar_service import TaiwanBarService, taiwan_current_session_bar_window
from app.market.tw_technical_service import TaiwanTechnicalService
from app.market_data.contracts import CanonicalModel, QuantityUnit


MetricKey = Literal[
    "open", "high", "low", "reference", "average", "volume", "turnover",
    "last_volume", "previous_volume", "bid", "ask", "range_pct", "relative_volume",
    "vwap_distance_pct",
]


class TaiwanSessionMetric(CanonicalModel):
    value: float | None = None
    unit: str
    status: Literal["available", "partial", "unavailable"] = "unavailable"
    estimated: bool = False
    method: str
    trade_date: date
    as_of: datetime | str | None = None
    source: str
    scope: str
    freshness: str | None = None
    coverage: str | None = None
    sample_days: int | None = None
    limitations: tuple[str, ...] = ()


class TaiwanSessionSummaryRead(CanonicalModel):
    contract_version: Literal["tw.chart.session_summary.v1"] = "tw.chart.session_summary.v1"
    instrument_id: str
    trade_date: date
    base_interval: Literal["1m"] = "1m"
    series_revision: str
    presentation_session_state: str | None = None
    official_close_status: str | None = None
    reference_type: str | None = None
    metrics: dict[MetricKey, TaiwanSessionMetric] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()


def _number(value: Any) -> float | None:
    try:
        result = float(value) if value is not None and not isinstance(value, bool) else None
        return result if result is not None and isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def project_session_summary(
    *, instrument_id: str, trade_date: date, bars: TaiwanBarSeriesRead,
    quote: dict[str, Any], technical_point: dict[str, Any],
    previous_daily: Any, pace: dict[str, Any],
) -> TaiwanSessionSummaryRead:
    """No IO or source selection. Every value retains its evidence scope."""
    if bars.requested_interval != "1m" or any(bar.start_at.date() != trade_date for bar in bars.bars):
        raise ValueError("SESSION_SUMMARY_BAR_IDENTITY_MISMATCH")
    metrics: dict[MetricKey, TaiwanSessionMetric] = {}
    same_quote = str(quote.get("trade_date")) == trade_date.isoformat()
    freshness = (quote.get("freshness") or {}).get("status")
    quote_scope = quote.get("volume_scope") or "quote_snapshot"

    def quote_metric(key: MetricKey, field: str, unit: str, *, usable: bool = True):
        value = _number(quote.get(field)) if same_quote and usable else None
        metrics[key] = TaiwanSessionMetric(
            value=value, unit=unit, status="available" if value is not None else "unavailable",
            method=field, trade_date=trade_date, as_of=quote.get("quote_time"),
            source=quote.get("source") or "quote.snapshot", scope=quote_scope,
            freshness=freshness,
        )

    for key in ("open", "high", "low"):
        quote_metric(key, f"{key}_price", "TWD")
    quote_metric("volume", "total_volume_lots", "lots", usable=quote.get("volume_status") == "available")
    quote_metric("last_volume", "last_trade_volume_lots", "lots", usable=(
        quote.get("actual_trade_occurred") is True and quote.get("last_trade_volume_status") == "available"
    ))
    reference = quote.get("change_reference") or {}
    reference_value = _number(reference.get("price")) if (
        str(reference.get("applies_to_trade_date")) == trade_date.isoformat()
        and reference.get("display_usable") is True
    ) else None
    metrics["reference"] = TaiwanSessionMetric(
        value=reference_value, unit="TWD", status="available" if reference_value is not None else "unavailable",
        method=reference.get("type") or "unknown", trade_date=trade_date,
        as_of=(reference.get("lineage") or {}).get("event_at"), source=reference.get("source") or "change_reference",
        scope="comparison_reference", freshness=reference.get("status"),
    )
    for key, field in (("bid", "bid_total_size_lots"), ("ask", "ask_total_size_lots")):
        quote_metric(key, field, "lots", usable=quote.get(f"{key}_depth_status") == "available")
        metrics[key] = metrics[key].model_copy(update={
            "scope": "top5_price_levels",
            "limitations": (str(quote.get(f"{key}_depth_status") or "unavailable"),),
        })

    coverage = bars.current_session_coverage
    coverage_status = coverage.status if coverage else "missing"
    covered = coverage_status in {"complete_prefix", "complete_session"}
    provisional = any(not state.technical_eligible for state in bars.bar_states)
    bar_time = bars.bars[-1].end_at.isoformat() if bars.bars else None
    bar_scope = "regular_session_1m_bars_excluding_close_marker"
    # Preserve missing versus explicit zero, and require normalized shares.
    full_volume_basis = bool(bars.bars) and all(
        bar.volume is not None and _number(bar.volume.value) is not None
        and bar.volume.unit is QuantityUnit.SHARE and bar.volume.value >= 0 for bar in bars.bars
    )
    average = _number(technical_point.get("vwap")) if full_volume_basis else None

    def bar_metric(key: MetricKey, value: float | None, unit: str, method: str, *, estimated=False, partial=False):
        metrics[key] = TaiwanSessionMetric(
            value=value, unit=unit, status="unavailable" if value is None else "partial" if partial or provisional or not covered else "available",
            estimated=estimated, method=method, trade_date=trade_date, as_of=bar_time,
            source="tw.intraday.bars", scope=bar_scope, coverage=coverage_status,
            limitations=tuple(bars.limitations),
        )

    bar_metric("average", average, "TWD", "TaiwanTechnicalService:hlc3_volume_weighted_1m", estimated=True)
    values = [_number(bar.turnover_value) for bar in bars.bars]
    valid_values = [value for value in values if value is not None and value >= 0]
    if valid_values:
        bar_metric("turnover", sum(valid_values), "TWD", "canonical_bar_turnover_sum", partial=len(valid_values) != len(values))
    else:
        # A close-volume sum is an estimate of the covered bars, never the
        # quote's full-day turnover or an exchange tick VWAP denominator.
        estimate = sum(float(bar.close_price * bar.volume.value) for bar in bars.bars) if full_volume_basis else None
        bar_metric("turnover", estimate, "TWD", "bar_close_x_share_volume_1m", estimated=True)
    prior_date = previous_taiwan_trading_day(trade_date, include_value=False)
    previous_value = _number(previous_daily.trade_volume) if previous_daily is not None and previous_daily.trade_date == prior_date else None
    metrics["previous_volume"] = TaiwanSessionMetric(
        value=previous_value / 1000 if previous_value is not None else None, unit="lots",
        status="available" if previous_value is not None else "unavailable",
        method="official_daily_trade_volume", trade_date=prior_date,
        as_of=str(previous_daily.trade_date) if previous_daily else None,
        source=getattr(previous_daily, "source", "tw.daily.ohlcv"), scope="official_daily_aggregate",
        limitations=("VOLUME_SCOPE_DIFFERS_FROM_QUOTE_CUMULATIVE",) if quote_scope != "official_daily_aggregate" else (),
    )
    high, low = metrics["high"].value, metrics["low"].value
    amplitude = (high - low) / reference_value * 100 if (
        high is not None and low is not None and high >= low and reference_value is not None
        and reference_value > 0 and reference.get("calculation_eligible") is True
    ) else None
    metrics["range_pct"] = metrics["high"].model_copy(update={"value": amplitude, "unit": "percent", "method": "(high-low)/change_reference*100", "status": "available" if amplitude is not None else "unavailable"})
    baseline = pace.get("same_time_baseline_5d") or {}
    ratio = _number(baseline.get("pace_ratio")) if full_volume_basis and str(pace.get("trade_date")) == trade_date.isoformat() else None
    bar_metric("relative_volume", ratio, "ratio", "same_time_5d_median", partial=pace.get("status") != "ready")
    metrics["relative_volume"] = metrics["relative_volume"].model_copy(update={
        "sample_days": baseline.get("sample_days"),
        "as_of": str(pace.get("as_of")) if pace.get("as_of") else bar_time,
        "limitations": metrics["relative_volume"].limitations + tuple(pace.get("warnings") or ()),
    })
    last = _number(quote.get("headline_price")) if str(quote.get("headline_trade_date")) == trade_date.isoformat() else None
    distance = (last / average - 1) * 100 if last is not None and average is not None and average > 0 else None
    bar_metric("vwap_distance_pct", distance, "percent", "headline_vs_session_average", estimated=True)
    metrics["vwap_distance_pct"] = metrics["vwap_distance_pct"].model_copy(update={"freshness": freshness})
    return TaiwanSessionSummaryRead(
        instrument_id=instrument_id, trade_date=trade_date, series_revision=bars.identity.series_revision,
        presentation_session_state=quote.get("presentation_session_state"),
        official_close_status=quote.get("official_close_status"), reference_type=reference.get("type"),
        metrics=metrics, limitations=tuple(bars.limitations),
    )


def read_taiwan_session_summary(
    db: Session, *, instrument_id: str, expected_trade_date: date,
    requested_at: datetime | None = None,
) -> TaiwanSessionSummaryRead:
    now, trade_date, _, _ = taiwan_current_session_bar_window(requested_at)
    if trade_date != expected_trade_date:
        raise ValueError("SESSION_SUMMARY_TRADE_DATE_MISMATCH")
    bars = TaiwanBarService(db).read_current_session_bars(
        instrument_id=instrument_id, interval="1m", limit=5000, include_partial=True, requested_at=now,
    )
    quote = read_taiwan_quote_evidence_projection(db=db, stock_id=instrument_id, requested_at=now)
    point = TaiwanTechnicalService().session_average(bars)
    prior_date = previous_taiwan_trading_day(trade_date, include_value=False)
    daily = project_taiwan_daily_rows(db, read_taiwan_official_daily(
        db, stock_id=instrument_id, from_date=prior_date, to_date=prior_date, limit=1, requested_at=now,
    ))
    points = [{"time": bar.start_at.isoformat(), "volume": float(bar.volume.value) if bar.volume else None} for bar in bars.bars]
    pace = build_tw_stock_volume_pace(db, stock_id=instrument_id, current_points=points)
    return project_session_summary(
        instrument_id=instrument_id, trade_date=trade_date, bars=bars, quote=quote,
        technical_point=point, previous_daily=daily[0] if daily else None, pace=pace,
    )
