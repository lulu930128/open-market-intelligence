"""Thin AI projections of Backend-owned Taiwan Bar/Technical contracts."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.market.tw_bar_contracts import TaiwanBarSeriesRead, TaiwanChartPresentationEvent
from app.market.tw_chart_service import TaiwanChartBundleRead
from app.market.tw_intraday_universe import intraday_materialization_policy


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
    expected_trade_date: date | None = None,
    presentation_events: tuple[TaiwanChartPresentationEvent, ...] = (),
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
        "market_phase": series.market_phase,
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
        "cached_count": len(points),
        "cache_hit": bool(points),
        "cache_status": "persisted_hit" if points else "persisted_miss",
        "read_diagnostics": series.read_diagnostics.model_dump(mode="json") if series.read_diagnostics else None,
        "presentation_events": [event.model_dump(mode="json") for event in presentation_events],
        "display_event_count": len(presentation_events),
        "points": points,
        "is_partial": not series.history.requested_coverage_satisfied,
        "coverage_status": series.history.history_status.value,
        "series_coverage": series.history.model_dump(mode="json"),
        "materialization_policy": intraday_materialization_policy(),
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
        trade_date = expected_trade_date or _single_session_trade_date(series)
        expected_trade_date = trade_date.isoformat() if trade_date is not None else None
        unexpected_trade_dates = sorted(
            set(observed_trade_dates)
            - ({expected_trade_date} if expected_trade_date is not None else set())
        )
        current_session_coverage = getattr(series, "current_session_coverage", None)
        if current_session_coverage is not None:
            payload["series_coverage"] = current_session_coverage.model_dump(mode="json")
            payload["coverage_status"] = current_session_coverage.status.value
            payload["is_partial"] = current_session_coverage.status.value not in {"complete_prefix", "complete_session"}
            # The Bar owner evaluates the full snapshot before applying the
            # consumer's point limit. Keep that count through AI projection.
            payload["point_count"] = current_session_coverage.snapshot_bar_count
            payload["returned_point_count"] = len(points)
            payload["truncated"] = current_session_coverage.snapshot_bar_count > len(points)
        snapshot_phase = (
            current_session_coverage.snapshot_phase.value
            if current_session_coverage is not None
            else None
        )
        freshness_status = (
            "missing"
            if not points
            else "historical"
            if session_scope == "history" and not unexpected_trade_dates
            else "current"
            if expected_trade_date is not None
            and not unexpected_trade_dates
            and snapshot_phase == "ready"
            and current_session_coverage.status.value in {"complete_prefix", "complete_session"}
            else "partial"
        )
        payload.update(
            {
                "session_scope": session_scope,
                "is_historical": session_scope == "history",
                "expected_trade_date": expected_trade_date,
                "trade_date": expected_trade_date,
                "freshness_status": freshness_status,
                "materialization_state": "materialized" if points else "not_materialized",
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
