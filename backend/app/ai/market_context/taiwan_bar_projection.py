"""Thin AI projections of Backend-owned Taiwan Bar/Technical contracts."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.market.tw_bar_contracts import TaiwanBarSeriesRead, TaiwanChartPresentationEvent
from app.market.tw_chart_service import TaiwanChartBundleRead
from app.market.technical_evidence import indicator_method_catalog
from app.market.technical_parameters import TechnicalAnalysisParameters
from app.market.tw_intraday_universe import intraday_materialization_policy
from app.market.tw_intraday_value import project_taiwan_intraday_values


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
    amount_projection = (project_taiwan_intraday_values(series)
        if series.requested_interval not in {"1d", "1w", "1mo"} else None)
    states = {item.start_at: item for item in series.bar_states}
    points: list[dict[str, Any]] = []
    for bar, amount in zip(series.bars, amount_projection.points if amount_projection else (None,) * len(series.bars)):
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
                "is_partial": state.quality_status == "partial" if state and state.quality_status else bar.finalization.value == "provisional",
                "source_interval": state.source_interval if state else series.base_interval,
                "source_point_count": state.source_point_count if state else None,
                "gap_reason": state.gap_reason if state else None,
                "missing_evidence_count": state.missing_evidence_count if state else None,
                "indicator_eligible": (
                    state.technical_eligible if state is not None else True
                ),
                "provider": bar.lineage.provider,
                "source": bar.lineage.source,
                "canonical_volume_unit": (
                    bar.volume.unit.value if bar.volume is not None else None
                ),
                "volume_status": bar.volume_status,
                "quality_status": state.quality_status if state and state.quality_status else (
                    "partial"
                    if bar.finalization.value == "provisional"
                    else "ok"
                ),
                **(amount.model_dump(mode="python") if amount else {}),
            }
        )
    latest = series.bars[-1] if series.bars else None
    observed_trade_dates = sorted({bar.start_at.date().isoformat() for bar in series.bars})
    payload = {
        **(amount_projection.metadata if amount_projection else {}),
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


def project_taiwan_index_indicators(
    bundles: dict[str, TaiwanChartBundleRead], *, index_id: str,
) -> dict[str, Any]:
    """Expose the chart owner's exact calculation, including its completed cut.

    No second calculation or period classification: the technical owner already
    separates daily observations and identifies the completed weekly/monthly cut.
    """
    timeframes: dict[str, Any] = {}
    for timeframe, bundle in bundles.items():
        technical = bundle.technical.model_dump(mode="json")
        points = technical.get("points") or []
        count = int(technical.get("decision_bar_count") or 0)
        completed = points[count - 1] if 0 < count <= len(points) else None
        observation = technical.get("current_partial") or {}
        partial = observation.get("point")
        if partial is None and 0 <= count < len(points):
            partial = points[-1]
        timeframes[timeframe] = {
            "timeframe": timeframe,
            "completed": {**completed, "bar_status": "completed"} if completed else None,
            "current_partial": {
                **partial, "bar_status": "current_partial", "decision_usable": False,
                **{key: value for key, value in observation.items() if key != "point"},
            } if partial else None,
            "decision_snapshot": "completed",
            "available_bars": technical.get("calculation_bar_count", 0),
            "completed_bars": count,
            "warmup": technical.get("warmup", {}),
            "input_quality": technical.get("input_quality", {}),
            "decision_usable": bool(completed and technical.get("decision_usable")),
            "bar_series_revision": technical.get("bar_series_revision"),
            "technical_revision": technical.get("technical_revision"),
            "parameter_contract": technical.get("parameter_contract", {}),
            "warnings": [*technical.get("warnings", []), *technical.get("limitations", [])],
        }
    daily = timeframes.get("daily", {})
    bundle = bundles.get("daily")
    technical = bundle.technical.model_dump(mode="json") if bundle else {}
    parameters = technical.get("parameter_contract", {})
    names = TechnicalAnalysisParameters.__dataclass_fields__
    methods = indicator_method_catalog(TechnicalAnalysisParameters(
        **{name: parameters[name] for name in names}
    )) if all(name in parameters for name in names) else {}
    completed = daily.get("completed") or {}
    return {
        "kind": "tw_technical_indicator_snapshot",
        "schema_version": technical.get("algorithm_version"),
        "algorithm_version": technical.get("algorithm_version"),
        "stock_id": index_id, "symbol": index_id, "market": "TW",
        "status": "ready" if daily.get("decision_usable") else "partial" if timeframes else "missing",
        "decision_usable": bool(daily.get("decision_usable")),
        "as_of": completed.get("time"), "price_basis": "raw_unadjusted",
        "price_unit": "index_points", "currency": None,
        "bar_series_fingerprint": technical.get("bar_series_fingerprint"),
        "bar_series_revision": technical.get("bar_series_revision"),
        "technical_revision": technical.get("technical_revision"),
        "input_quality": daily.get("input_quality", {}),
        "methods": methods, "timeframes": timeframes,
        "lineage": {
            "bar_lineage_digest": technical.get("bar_lineage_digest"),
            "bar_state_digest": technical.get("bar_state_digest"),
            "bar_series_revision": technical.get("bar_series_revision"),
        },
        "source_refs": [{"type": "resolved_market_data", "name": "tw.market_index.daily"}],
        "missing": [] if completed else ["technical.indicators.daily.completed"],
        "warnings": list(dict.fromkeys(warning for item in timeframes.values() for warning in item["warnings"])),
    }


__all__ = ["project_taiwan_bar_series", "project_taiwan_chart_bundle", "project_taiwan_index_indicators"]
