"""Thin AI projections of Backend-owned Taiwan Bar/Technical contracts."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.market.tw_bar_contracts import TaiwanBarSeriesRead
from app.market.tw_chart_service import TaiwanChartBundleRead


def _single_session_trade_date(series: TaiwanBarSeriesRead) -> date | None:
    current_session_coverage = getattr(series, "current_session_coverage", None)
    if current_session_coverage is not None:
        return current_session_coverage.trade_date
    trade_dates = tuple(
        item.trade_date for item in getattr(series, "session_resolution", ())
    )
    return trade_dates[0] if len(trade_dates) == 1 else None


def project_taiwan_bar_series(
    series: TaiwanBarSeriesRead,
    *,
    session_scope: str | None = None,
) -> dict[str, Any]:
    states = {item.start_at: item for item in series.bar_states}
    points: list[dict[str, Any]] = []
    for bar in series.bars:
        state = states.get(bar.start_at)
        volume = float(bar.volume.value) if bar.volume is not None else None
        close = float(bar.close_price)
        points.append(
            {
                "time": bar.start_at,
                "bar_close_time": bar.end_at,
                "open": float(bar.open_price),
                "high": float(bar.high_price),
                "low": float(bar.low_price),
                "close": close,
                "price": close,
                "volume": volume,
                "volume_shares": volume,
                "trade_value": (
                    float(bar.turnover_value)
                    if bar.turnover_value is not None
                    else None
                ),
                "transaction_count": bar.trade_count,
                "finalization": bar.finalization.value,
                "finalized": bar.finalization.value != "provisional",
                "is_partial": bar.finalization.value == "provisional",
                "source_interval": state.source_interval if state else series.base_interval,
                "indicator_eligible": (
                    state.technical_eligible if state is not None else True
                ),
                "provider": bar.lineage.provider,
                "source": bar.lineage.source,
                "canonical_volume_unit": (
                    bar.volume.unit.value if bar.volume is not None else None
                ),
                "volume_status": bar.volume_status,
                "quality_status": (
                    "partial"
                    if bar.finalization.value == "provisional"
                    else "ok"
                ),
            }
        )
    latest = series.bars[-1] if series.bars else None
    observed_trade_dates = sorted({bar.start_at.date().isoformat() for bar in series.bars})
    payload = {
        "kind": "taiwan_bar_series",
        "stock_id": series.instrument.symbol,
        "instrument": series.instrument.model_dump(mode="json"),
        "interval": series.requested_interval,
        "requested_interval": series.requested_interval,
        "effective_interval": series.requested_interval,
        "source_interval": series.base_interval,
        "interval_status": "ready",
        "range": "canonical",
        "provider": latest.lineage.provider if latest is not None else None,
        "source": latest.lineage.source if latest is not None else None,
        "from_time": series.history.available_from,
        "to_time": series.history.available_to,
        "point_count": len(points),
        "points": points,
        "is_partial": not series.history.requested_coverage_satisfied,
        "coverage_status": series.history.history_status.value,
        "series_coverage": series.history.model_dump(mode="json"),
        "canonical_volume_unit": (
            latest.volume.unit.value
            if latest is not None and latest.volume is not None
            else None
        ),
        "series_fingerprint": series.identity.series_fingerprint,
        "lineage_digest": series.identity.lineage_digest,
        "state_digest": series.identity.state_digest,
        "series_revision": series.identity.series_revision,
        "observed_trade_dates": observed_trade_dates,
        "warnings": [*series.warnings, *series.limitations],
    }
    if session_scope is not None:
        trade_date = _single_session_trade_date(series)
        expected_trade_date = trade_date.isoformat() if trade_date is not None else None
        unexpected_trade_dates = sorted(
            set(observed_trade_dates)
            - ({expected_trade_date} if expected_trade_date is not None else set())
        )
        current_session_coverage = getattr(series, "current_session_coverage", None)
        snapshot_phase = (
            current_session_coverage.snapshot_phase.value
            if current_session_coverage is not None
            else None
        )
        freshness_status = (
            "missing"
            if not points
            else "current"
            if expected_trade_date is not None
            and not unexpected_trade_dates
            and snapshot_phase == "ready"
            else "partial"
        )
        payload.update(
            {
                "session_scope": session_scope,
                "expected_trade_date": expected_trade_date,
                "trade_date": expected_trade_date,
                "freshness_status": freshness_status,
                "freshness": {
                    "status": freshness_status,
                    "is_current": freshness_status == "current",
                    "expected_trade_date": expected_trade_date,
                    "latest_trade_date": observed_trade_dates[-1] if observed_trade_dates else None,
                    "observed_trade_dates": observed_trade_dates,
                    "unexpected_trade_dates": unexpected_trade_dates,
                    "snapshot_phase": snapshot_phase,
                    "coverage_status": (
                        current_session_coverage.status.value
                        if current_session_coverage is not None
                        else series.history.history_status.value
                    ),
                },
            }
        )
    return payload


def project_taiwan_chart_bundle(bundle: TaiwanChartBundleRead) -> dict[str, Any]:
    bars = project_taiwan_bar_series(bundle.bars)
    return {
        **bars,
        "technical": bundle.technical.model_dump(mode="json"),
        "technical_points": list(bundle.technical.points),
        "algorithm_version": bundle.technical.algorithm_version,
        "parameter_contract": bundle.technical.parameter_contract,
    }


__all__ = ["project_taiwan_bar_series", "project_taiwan_chart_bundle"]
