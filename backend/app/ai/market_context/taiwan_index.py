from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai import technical_analysis
from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.ai.market_context.taiwan_bar_projection import (
    project_taiwan_bar_series,
    project_taiwan_chart_bundle,
)
from app.ai.market_context.taiwan_projection import (
    _build_tw_index_compact_evidence,
    _json_value,
    _latest_date_string,
    _latest_intraday_point,
    _with_evidence_passport,
)
from app.ai.market_payload_contract import bounded_int_param as _bounded_int_param
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.market_chips import market_chip_daily_to_dict


normalize_analysis_horizon = technical_analysis.normalize_analysis_horizon
_technical_analysis_summary = technical_analysis._technical_analysis_summary
_serialized_chart = technical_analysis._serialized_chart


@dataclass(frozen=True)
class TaiwanIndexDependencies:
    get_latest_market_chip_daily: Callable[..., Any]
    get_market_index_contributions: Callable[..., list[Any]]
    read_taiwan_chart: Callable[..., Any]
    read_taiwan_index_intraday_bars: Callable[..., Any]
    calculate_taiwan_technical: Callable[..., Any]
    get_market_index_summary: Callable[..., Any]
    now: Callable[[], datetime]


def _json_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _json_value(value) for key, value in row.items()}


def read_tw_index_context(
    db: Session,
    index_id: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanIndexDependencies,
) -> dict[str, Any]:
    normalized_index_id = index_id.strip().upper()
    calendar_status = build_taiwan_calendar_status(now=dependencies.now())
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan index context uses market index evidence, not stock_master or individual stock daily tables.",
    ]
    charts: dict[str, Any] = {}
    technical_reports: dict[str, Any] = {}
    chart_bars = _bounded_int_param(
        market_data_params,
        ("daily_bars", "bars"),
        default=bars,
        minimum=20,
        maximum=500,
    )

    interval_by_timeframe = {"daily": "1d", "weekly": "1w", "monthly": "1mo"}
    for timeframe, interval in interval_by_timeframe.items():
        try:
            bundle = dependencies.read_taiwan_chart(
                db=db,
                instrument_id=normalized_index_id,
                interval=interval,
                limit=max(chart_bars, 1),
                include_partial=True,
            )
        except ValueError:
            raise
        except Exception as exc:
            warnings.append(f"{timeframe.title()} index chart unavailable: {exc}")
            missing.append(f"market_index_ohlc.{timeframe}")
            continue

        chart = project_taiwan_chart_bundle(bundle)
        serialized = _serialized_chart(chart)
        charts[timeframe] = serialized
        points = list(bundle.technical.points)
        technical_reports[timeframe] = {
            "kind": "tw_index_backend_technical_series",
            "timeframe": timeframe,
            "algorithm_version": bundle.technical.algorithm_version,
            "bar_series_revision": bundle.series_revision,
            "status": bundle.technical.status.value,
            "score": None,
            "confidence": None,
            "data": {"daily_indicator": points[-1] if points else None},
            "missing": [] if points else ["technical.series"],
            "warnings": list(bundle.technical.warnings),
        }
        if not points:
            missing.append(f"market_index_ohlc.{timeframe}")

    intraday: dict[str, Any] | None = None
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    if include_intraday or normalized_horizon == "intraday":
        try:
            intraday_series = dependencies.read_taiwan_index_intraday_bars(
                db=db,
                index_id=normalized_index_id,
                requested_at=dependencies.now(),
            )
            intraday = project_taiwan_bar_series(
                intraday_series,
                session_scope="current_session",
            )
            intraday_technical = dependencies.calculate_taiwan_technical(
                intraday_series
            )
            intraday_points = list(intraday_technical.points)
            technical_reports["today"] = {
                "kind": "tw_index_backend_technical_series",
                "timeframe": "today",
                "algorithm_version": intraday_technical.algorithm_version,
                "bar_series_revision": intraday_series.identity.series_revision,
                "status": intraday_technical.status.value,
                "score": None,
                "confidence": None,
                "data": {
                    "daily_indicator": intraday_points[-1]
                    if intraday_points
                    else None
                },
                "missing": [] if intraday_points else ["technical.series"],
                "warnings": list(intraday_technical.warnings),
            }
            if not intraday_points:
                missing.append("market_index_intraday")
        except Exception as exc:
            warnings.append(f"Index intraday unavailable: {exc}")
            missing.append("market_index_intraday")
    elif normalized_horizon == "intraday":
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily evidence is used as fallback context."
        )

    summary_payload: dict[str, Any] = {}
    index_snapshot: dict[str, Any] | None = None
    try:
        summary_payload = dependencies.get_market_index_summary(db, force_refresh=False)
        for item in summary_payload.get("indices", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("index_id") or item.get("stock_id") or "").upper() == normalized_index_id:
                index_snapshot = {key: _json_value(value) for key, value in item.items()}
                break
        if index_snapshot is None:
            missing.append("market_index_summary")
    except Exception as exc:
        warnings.append(f"Index summary unavailable: {exc}")
        missing.append("market_index_summary")

    market_chip: dict[str, Any] | None = None
    try:
        chip_row = dependencies.get_latest_market_chip_daily(db, index_id=normalized_index_id)
        market_chip = (
            _json_dict(
                market_chip_daily_to_dict(
                    chip_row,
                    db=db,
                    resolve_expected_margin=True,
                )
            )
            if chip_row is not None
            else None
        )
        if market_chip is None:
            missing.append("market_chip_daily")
    except Exception as exc:
        warnings.append(f"Market chip context unavailable: {exc}")
        missing.append("market_chip_daily")

    contributions: dict[str, Any] | None = None
    try:
        contributions_payload = dependencies.get_market_index_contributions(normalized_index_id, limit=10)
        contributions = {
            key: _json_value(value)
            for key, value in contributions_payload.items()
            if key not in {"positive", "negative"}
        }
        contributions["positive"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("positive", [])
            if isinstance(item, dict)
        ]
        contributions["negative"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("negative", [])
            if isinstance(item, dict)
        ]
    except Exception as exc:
        warnings.append(f"Index contribution context unavailable: {exc}")

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    intraday_latest_time = (_latest_intraday_point(intraday) or {}).get("time")
    as_of = _latest_date_string(
        [
            (charts.get("daily") or {}).get("to_date"),
            (index_snapshot or {}).get("time"),
            (index_snapshot or {}).get("as_of"),
            (market_chip or {}).get("trade_date"),
            intraday_latest_time,
        ]
    )
    source_refs: list[dict[str, str]] = []
    if charts:
        _append_source_ref_once(
            source_refs,
            {"type": "resolved_market_data", "name": "tw.market_index.daily"},
        )
    if index_snapshot is not None:
        _append_source_ref_once(
            source_refs,
            {"type": "resolved_market_data", "name": "tw.market_index.current"},
        )
    if market_chip is not None:
        _append_source_ref_once(
            source_refs,
            {"type": "table", "name": "market_chip_daily"},
        )
    if contributions is not None:
        _append_source_ref_once(
            source_refs,
            {"type": "derived", "name": "app.market.indices"},
        )
    if intraday is not None:
        _append_source_ref_once(
            source_refs,
            {"type": "external_or_cache", "name": "market_index_intraday"},
        )

    envelope = {
        "kind": "tw_index_context",
        "generated_at": dependencies.now(),
        "as_of": as_of,
        "scope": {"index_id": normalized_index_id},
        "data": {
            "index": index_snapshot,
            "charts": charts,
            "intraday": intraday,
            "market_chip": market_chip,
            "contributions": contributions,
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
            "compact": _build_tw_index_compact_evidence(
                index_id=normalized_index_id,
                as_of=as_of,
                index_snapshot=index_snapshot,
                daily_chart=charts.get("daily"),
                intraday=intraday,
                include_intraday=include_intraday or normalized_horizon == "intraday",
                market_data_params=market_data_params,
                market_chip=market_chip,
                contributions=contributions,
                technical_reports=technical_reports,
                technical_analysis=technical_analysis,
                missing=missing,
                warnings=warnings,
                source_refs=source_refs,
                calendar_status=calendar_status,
            ),
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )
