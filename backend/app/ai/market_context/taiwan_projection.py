from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import (
    COMPACT_INTRADAY_BAR_LIMIT,
    PAYLOAD_LEVELS,
    has_payload_value as _has_payload_value,
    intraday_point_limit as _intraday_point_limit,
    payload_level as _payload_level,
    payload_slot_status as _payload_slot_status,
    slot_envelope as _slot_envelope,
)
from app.db.models import FinancialMetricQuarterly, StockMaster


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if row is None:
        return None

    return {field: _json_value(getattr(row, field, None)) for field in fields}


def _stock_dict(stock: StockMaster | None) -> dict[str, Any] | None:
    return _row_dict(
        stock,
        (
            "stock_id",
            "stock_name",
            "market",
            "instrument_type",
            "industry",
            "category",
            "is_active",
            "notes",
            "last_seen_at",
            "updated_at",
        ),
    )


def _latest_financial_period(row: FinancialMetricQuarterly | None) -> str | None:
    if row is None:
        return None

    return row.period or f"{row.fiscal_year}Q{row.quarter}"


def _latest_date_string(values: list[Any]) -> str | None:
    valid_values = [_json_value(value) for value in values if value is not None]

    if not valid_values:
        return None

    return str(max(valid_values))


def _broker_branch_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return {key: _json_value(value) for key, value in row.items()}

    return _row_dict(
        row,
        (
            "trade_date",
            "stock_id",
            "stock_name",
            "branch_code",
            "branch_name",
            "buy_lots",
            "sell_lots",
            "net_lots",
            "buy_avg_price",
            "sell_avg_price",
            "buy_rank",
            "sell_rank",
            "source_label",
        ),
    ) or {}


def _add_missing(missing: list[str], key: str, value: Any) -> None:
    if value is None or value == []:
        missing.append(key)


COMPACT_INTRADAY_INTERVALS = ("1m", "5m")
FRESHNESS_DOMAIN_RESOURCES = {
    "technical": {"market_daily_price"},
    "chips": {
        "institutional_trade_daily",
        "margin_trading_daily",
        "broker_branch_trade_daily",
        "shareholding_distribution_weekly",
        "market_chip_daily",
    },
    "fundamentals": {"monthly_revenue", "financial_metric_quarterly"},
}


def _quote_slot_status(quote: dict[str, Any]) -> str:
    if not quote or not _has_payload_value(quote):
        return "missing"
    freshness = quote.get("freshness") if isinstance(quote.get("freshness"), dict) else {}
    if quote.get("status") == "unavailable" or freshness.get("status") == "missing":
        return "missing"
    if bool(quote.get("is_realtime")) and not bool(freshness.get("is_stale")):
        return "ready"
    return "partial"


def _intraday_slot_status(intraday_bars: dict[str, Any]) -> str:
    if not intraday_bars:
        return "missing"
    if not intraday_bars.get("enabled"):
        return "not_requested"
    series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
    for item in series.values():
        if isinstance(item, dict) and (item.get("latest") or item.get("returned_point_count")):
            return "ready"
    return "missing"


def _build_tw_stock_slots(
    *,
    target: dict[str, Any],
    as_of: str | None,
    payload_level: str,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    technical: dict[str, Any],
    chips: dict[str, Any],
    fundamentals: dict[str, Any],
    missing: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "identity": _slot_envelope(
            status="ready" if target.get("id") else "partial",
            capability="target_identity",
            payload_ref="target",
            priority="core",
            as_of=as_of,
        ),
        "quote": _slot_envelope(
            status=_quote_slot_status(quote),
            capability="quote_snapshot",
            payload_ref="quote",
            payload_level=payload_level,
            priority="core",
            as_of=quote.get("quote_time") or quote.get("trade_date") or as_of,
            missing=[key for key in missing if key in {"quote_depth", "market_daily_price"}],
        ),
        "intraday": _slot_envelope(
            status=_intraday_slot_status(intraday_bars),
            capability="live_intraday_bars",
            payload_ref="intraday_bars",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=[key for key in missing if key == "intraday_bars"],
            warnings=intraday_bars.get("warnings") if isinstance(intraday_bars.get("warnings"), list) else [],
            next_fill="Request market_data_params.include_intraday=true with trusted external fetch policy.",
        ),
        "daily_chart": _slot_envelope(
            status="ready" if "market_daily_price" not in missing else "partial",
            capability="daily_ohlc_chart",
            payload_ref="full.data.chart",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=[key for key in missing if key == "market_daily_price"],
        ),
        "technical": _slot_envelope(
            status=_payload_slot_status(
                technical,
                missing=[key for key in missing if key == "market_daily_price"],
            ),
            capability="technical_decision_evidence",
            payload_ref="technical",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
        ),
        "chips_flows": _slot_envelope(
            status=_payload_slot_status(
                chips,
                missing=[key for key in missing if key in FRESHNESS_DOMAIN_RESOURCES["chips"]],
            ),
            capability="tw_chips_and_flows",
            payload_ref="chips",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "fundamentals": _slot_envelope(
            status=_payload_slot_status(
                fundamentals,
                missing=[key for key in missing if key in FRESHNESS_DOMAIN_RESOURCES["fundamentals"]],
            ),
            capability="tw_fundamentals",
            payload_ref="fundamentals",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "cross_market": _slot_envelope(
            status="planned",
            capability="cross_market_context",
            payload_level=payload_level,
            next_fill="Attach US/JP/KR/crypto context as bounded auxiliary evidence, not as Taiwan-core replacement.",
        ),
        "news_events": _slot_envelope(
            status="planned",
            capability="news_and_event_context",
            payload_level=payload_level,
            next_fill="Requires provider policy, quota boundary, and source attribution before default use.",
        ),
        "data_quality": _slot_envelope(
            status="ready" if not missing and not warnings else "partial",
            capability="data_quality_and_freshness",
            payload_ref="data_quality",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=missing,
            warnings=warnings,
        ),
    }


def _build_tw_index_slots(
    *,
    target: dict[str, Any],
    as_of: str | None,
    payload_level: str,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    technical: dict[str, Any],
    market_chip: dict[str, Any] | None,
    contributions: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "identity": _slot_envelope(
            status="ready" if target.get("id") else "partial",
            capability="target_identity",
            payload_ref="target",
            priority="core",
            as_of=as_of,
        ),
        "quote": _slot_envelope(
            status=_quote_slot_status(quote),
            capability="index_quote_snapshot",
            payload_ref="quote",
            payload_level=payload_level,
            priority="core",
            as_of=quote.get("quote_time") or quote.get("trade_date") or as_of,
        ),
        "intraday": _slot_envelope(
            status=_intraday_slot_status(intraday_bars),
            capability="index_live_intraday_bars",
            payload_ref="intraday_bars",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=[key for key in missing if key.startswith("market_index_intraday")],
        ),
        "daily_chart": _slot_envelope(
            status="ready" if "market_index_ohlc.daily" not in missing else "partial",
            capability="index_daily_ohlc_chart",
            payload_ref="full.data.charts.daily",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=[key for key in missing if key == "market_index_ohlc.daily"],
        ),
        "technical": _slot_envelope(
            status=_payload_slot_status(
                technical,
                missing=[key for key in missing if key.startswith("market_index_ohlc")],
            ),
            capability="index_technical_decision_evidence",
            payload_ref="technical",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
        ),
        "chips_flows": _slot_envelope(
            status="ready" if market_chip else "missing",
            capability="index_market_chip_daily",
            payload_ref="chips.market_chip",
            payload_level=payload_level,
            as_of=(market_chip or {}).get("trade_date") or as_of,
            missing=[] if market_chip else ["market_chip_daily"],
        ),
        "index_contributions": _slot_envelope(
            status="ready" if _has_payload_value(contributions) else "missing",
            capability="index_contribution_leaders",
            payload_ref="contributions",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "data_quality": _slot_envelope(
            status="ready" if not missing and not warnings else "partial",
            capability="data_quality_and_freshness",
            payload_ref="data_quality",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=missing,
            warnings=warnings,
        ),
    }


def _build_tw_market_slots(
    *,
    as_of: str | None,
    payload_level: str,
    breadth: dict[str, Any],
    distribution: dict[str, Any],
    industry_rows: list[dict[str, Any]],
    index_intraday: dict[str, Any],
    missing: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    intraday_missing = [
        key for key in missing if key.startswith("market_index_intraday")
    ]
    return {
        "identity": _slot_envelope(
            status="ready",
            capability="target_identity",
            payload_ref="scope",
            priority="core",
            as_of=as_of,
        ),
        "market_breadth": _slot_envelope(
            status=_payload_slot_status(
                breadth,
                missing=[key for key in missing if key.startswith("market_daily_price")],
            ),
            capability="tw_market_breadth",
            payload_ref="breadth",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
        ),
        "distribution": _slot_envelope(
            status=_payload_slot_status(distribution),
            capability="tw_market_distribution",
            payload_ref="distribution",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "sector_industry": _slot_envelope(
            status="ready" if industry_rows else "missing",
            capability="tw_industry_strength",
            payload_ref="top_industries,weak_industries",
            payload_level=payload_level,
            as_of=as_of,
        ),
        "index_intraday": _slot_envelope(
            status=(
                "not_requested"
                if not index_intraday.get("enabled")
                else "ready"
                if _has_payload_value(index_intraday.get("indices"))
                else "missing"
            ),
            capability="tw_market_index_intraday",
            payload_ref="index_intraday",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=intraday_missing,
            warnings=index_intraday.get("warnings") if isinstance(index_intraday.get("warnings"), list) else [],
        ),
        "cross_market": _slot_envelope(
            status="planned",
            capability="cross_market_context",
            payload_level=payload_level,
            next_fill="Attach overseas index and crypto risk context as auxiliary evidence after provider boundaries are finalized.",
        ),
        "news_events": _slot_envelope(
            status="planned",
            capability="news_and_event_context",
            payload_level=payload_level,
            next_fill="Requires provider policy, quota boundary, and source attribution before default use.",
        ),
        "data_quality": _slot_envelope(
            status="ready" if not missing and not warnings else "partial",
            capability="data_quality_and_freshness",
            payload_ref="missing,warnings,source_refs,evidence_passport",
            payload_level=payload_level,
            priority="core",
            as_of=as_of,
            missing=missing,
            warnings=warnings,
        ),
    }


def _compact_row(row: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    return _row_dict(row, fields)


def _compact_latest_daily_quote(
    latest_daily: Any,
    *,
    quote_error: str | None = None,
    session_phase: str | None = None,
) -> dict[str, Any]:
    if latest_daily is None:
        return {
            "kind": "quote_snapshot",
            "source": "market_daily_price",
            "provider": "local_daily_close",
            "status": "unavailable",
            "session_phase": session_phase,
            "trade_date": None,
            "quote_time": None,
            "latest_price": None,
            "price": None,
            "last_price": None,
            "is_realtime": False,
            "latency_ms": None,
            "freshness": {
                "status": "missing",
                "is_live": False,
                "is_stale": True,
                "message": quote_error or "No local daily close is available.",
            },
        }

    close_price = _json_value(getattr(latest_daily, "close_price", None))
    previous_close = (
        close_price - _json_value(getattr(latest_daily, "price_change", 0))
        if close_price is not None and getattr(latest_daily, "price_change", None) is not None
        else None
    )
    change_pct = (
        (_json_value(getattr(latest_daily, "price_change", None)) / previous_close) * 100
        if previous_close not in {None, 0}
        else None
    )

    return {
        "kind": "quote_snapshot",
        "source": "market_daily_price",
        "provider": "local_daily_close",
        "status": "delayed_daily_close",
        "session_phase": session_phase,
        "trade_date": _json_value(getattr(latest_daily, "trade_date", None)),
        "quote_time": None,
        "latest_price": close_price,
        "price": close_price,
        "last_price": close_price,
        "previous_close": previous_close,
        "open_price": _json_value(getattr(latest_daily, "open_price", None)),
        "high_price": _json_value(getattr(latest_daily, "high_price", None)),
        "low_price": _json_value(getattr(latest_daily, "low_price", None)),
        "change": _json_value(getattr(latest_daily, "price_change", None)),
        "change_pct": change_pct,
        "total_volume_lots": (
            int(getattr(latest_daily, "trade_volume", 0) / 1000)
            if getattr(latest_daily, "trade_volume", None) is not None
            else None
        ),
        "is_realtime": False,
        "latency_ms": None,
        "freshness": {
            "status": "daily_close",
            "is_live": False,
            "is_stale": False,
            "message": quote_error or "Live quote was not requested; using latest local daily close.",
        },
    }


def _compact_quote_snapshot(
    *,
    latest_daily: Any,
    quote_depth: dict[str, Any] | None,
    quote_error: str | None,
    session_phase: str | None = None,
) -> dict[str, Any]:
    if not quote_depth:
        return _compact_latest_daily_quote(
            latest_daily,
            quote_error=quote_error,
            session_phase=session_phase,
        )

    freshness = quote_depth.get("freshness") if isinstance(quote_depth.get("freshness"), dict) else {}
    age_seconds = freshness.get("age_seconds")
    latency_ms = int(age_seconds * 1000) if isinstance(age_seconds, (int, float)) else None
    is_realtime = bool(freshness.get("is_live")) and not bool(freshness.get("is_stale"))
    latest_price = quote_depth.get("last_price")
    return {
        "kind": "quote_snapshot",
        "source": quote_depth.get("source"),
        "provider": quote_depth.get("provider"),
        "status": freshness.get("status") or quote_depth.get("session_phase") or "quote",
        "session_phase": quote_depth.get("session_phase"),
        "phase_label": quote_depth.get("phase_label"),
        "trade_date": _json_value(quote_depth.get("trade_date")),
        "quote_time": _json_value(quote_depth.get("quote_time")),
        "fetched_at": _json_value(quote_depth.get("fetched_at")),
        "latest_price": latest_price,
        "price": latest_price,
        "last_price": latest_price,
        "previous_close": quote_depth.get("previous_close"),
        "open_price": quote_depth.get("open_price"),
        "high_price": quote_depth.get("high_price"),
        "low_price": quote_depth.get("low_price"),
        "change": quote_depth.get("change"),
        "change_pct": quote_depth.get("change_pct"),
        "total_volume_lots": quote_depth.get("total_volume_lots"),
        "best_bid_price": quote_depth.get("best_bid_price"),
        "best_bid_size_lots": quote_depth.get("best_bid_size_lots"),
        "best_ask_price": quote_depth.get("best_ask_price"),
        "best_ask_size_lots": quote_depth.get("best_ask_size_lots"),
        "spread": quote_depth.get("spread"),
        "spread_pct": quote_depth.get("spread_pct"),
        "depth_available": bool(quote_depth.get("depth_available")),
        "is_realtime": is_realtime,
        "latency_ms": latency_ms,
        "freshness": {
            "status": freshness.get("status"),
            "is_live": bool(freshness.get("is_live")),
            "is_stale": bool(freshness.get("is_stale")),
            "age_seconds": freshness.get("age_seconds"),
            "expected_trade_date": _json_value(freshness.get("expected_trade_date")),
            "message": freshness.get("message"),
            "source_error": freshness.get("source_error"),
        },
    }


def _compact_intraday_point(point: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": _json_value(point.get("time")),
        "price": point.get("price") if point.get("price") is not None else point.get("close"),
        "open": point.get("open"),
        "high": point.get("high"),
        "low": point.get("low"),
        "close": point.get("close"),
        "volume": point.get("volume"),
        "trade_value": point.get("trade_value"),
        "transaction_count": point.get("transaction_count"),
    }


def _compact_intraday_history(
    history: dict[str, Any],
    *,
    point_limit: int = COMPACT_INTRADAY_BAR_LIMIT,
) -> dict[str, Any]:
    raw_points = history.get("points") if isinstance(history.get("points"), list) else []
    points = [point for point in raw_points if isinstance(point, dict)]
    compact_points = [_compact_intraday_point(point) for point in points[-point_limit:]]
    first_point = points[0] if points else {}
    latest_point = compact_points[-1] if compact_points else None
    return {
        "interval": history.get("interval"),
        "range": history.get("range"),
        "provider": history.get("provider"),
        "source": history.get("source"),
        "from_time": _json_value(history.get("from_time") or first_point.get("time")),
        "to_time": _json_value(history.get("to_time") or (latest_point or {}).get("time")),
        "point_count": history.get("point_count") if history.get("point_count") is not None else len(points),
        "returned_point_count": len(compact_points),
        "cached_count": history.get("cached_count"),
        "refreshed_count": history.get("refreshed_count"),
        "latest": latest_point,
        "points": compact_points,
    }

def _compact_single_intraday_series(
    *,
    raw_payload: dict[str, Any] | None,
    interval: str,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload_level = _payload_level(market_data_params)
    point_limit = _intraday_point_limit(market_data_params)
    if not include_intraday:
        return {
            "kind": "intraday_bars",
            "enabled": False,
            "intervals": [interval],
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "series": {},
            "warnings": [],
        }

    payload = raw_payload if isinstance(raw_payload, dict) else {}
    points = payload.get("points") if isinstance(payload.get("points"), list) else []
    history = {
        "interval": interval,
        "range": payload.get("range") or "1d",
        "provider": payload.get("provider"),
        "source": payload.get("source"),
        "point_count": payload.get("point_count") if payload.get("point_count") is not None else len(points),
        "points": points,
    }
    return {
        "kind": "intraday_bars",
        "enabled": True,
        "intervals": [interval],
        "range": "1d",
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "series": {interval: _compact_intraday_history(history, point_limit=point_limit)},
        "warnings": [],
    }


def _compact_technical_report(report: dict[str, Any]) -> dict[str, Any]:
    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    daily_indicator = data.get("daily_indicator") if isinstance(data.get("daily_indicator"), dict) else {}
    intraday = data.get("intraday") if isinstance(data.get("intraday"), dict) else {}
    return {
        "timeframe": report.get("timeframe"),
        "phase": report.get("phase"),
        "title": report.get("title"),
        "summary": report.get("summary"),
        "score": report.get("score"),
        "confidence": report.get("confidence"),
        "value": report.get("value"),
        "value_label": report.get("value_label"),
        "latest_close": daily_indicator.get("close") or (intraday.get("latest_point") or {}).get("close"),
        "missing": report.get("missing") or [],
        "warnings": report.get("warnings") or [],
    }


def _compact_technical_evidence(
    *,
    analysis: dict[str, Any],
    technical_levels: dict[str, Any],
    technical_reports: dict[str, Any],
) -> dict[str, Any]:
    return {
        "analysis": {
            "requested_horizon": analysis.get("requested_horizon"),
            "selected_horizon": analysis.get("selected_horizon"),
            "selected_timeframe": analysis.get("selected_timeframe"),
            "selected_score": analysis.get("selected_score"),
            "selected_title": analysis.get("selected_title"),
            "selected_summary": analysis.get("selected_summary"),
            "selected_confidence": analysis.get("selected_confidence"),
            "scores": analysis.get("scores") or {},
            "score_range": (analysis.get("score_model") or {}).get("score_range"),
        },
        "levels": {
            "latest_price": technical_levels.get("latest_price"),
            "basis_timeframe": technical_levels.get("basis_timeframe"),
            "context": technical_levels.get("context") or {},
            "entry": technical_levels.get("entry") or {},
            "risk": technical_levels.get("risk") or {},
        },
        "reports": {
            timeframe: _compact_technical_report(report)
            for timeframe, report in technical_reports.items()
            if isinstance(report, dict)
        },
    }


def _source_health_entries(source_health: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(source_health, dict):
        return []
    entries = source_health.get("entries")
    return entries if isinstance(entries, list) else []


def _compact_source_health_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource": entry.get("resource"),
        "label": entry.get("label"),
        "status": entry.get("status"),
        "ok": bool(entry.get("ok")),
        "row_count": entry.get("row_count"),
        "latest": _json_value(entry.get("latest_data_date") or entry.get("latest_data_key")),
        "expected": _json_value(entry.get("expected_data_date")),
        "release_status": entry.get("release_status"),
        "freshness_lag_days": entry.get("freshness_lag_days"),
        "reason": entry.get("reason"),
    }


def _status_from_resources(resources: list[dict[str, Any]], *, extra_missing: list[str] | None = None) -> str:
    if extra_missing:
        return "partial"
    if not resources:
        return "unknown"
    statuses = {str(resource.get("status") or "") for resource in resources}
    if any(status in {"error", "missing", "empty"} for status in statuses):
        return "missing"
    if "stale" in statuses:
        return "stale"
    if all(resource.get("ok") for resource in resources):
        return "current"
    return "partial"


def _freshness_domain_from_resources(
    *,
    source_health: dict[str, Any] | None,
    resources: set[str],
    missing: list[str],
) -> dict[str, Any]:
    domain_resources = [
        _compact_source_health_entry(entry)
        for entry in _source_health_entries(source_health)
        if entry.get("resource") in resources
    ]
    missing_resources = [key for key in missing if key in resources]
    status = _status_from_resources(domain_resources, extra_missing=missing_resources)
    latest_values = [item.get("latest") for item in domain_resources if item.get("latest")]
    expected_values = [item.get("expected") for item in domain_resources if item.get("expected")]
    return {
        "status": status,
        "is_current": status == "current" and not missing_resources,
        "latest": str(max(latest_values)) if latest_values else None,
        "expected": str(max(expected_values)) if expected_values else None,
        "missing": missing_resources,
        "resources": domain_resources,
    }


def _quote_freshness_domain(quote: dict[str, Any]) -> dict[str, Any]:
    freshness = quote.get("freshness") if isinstance(quote.get("freshness"), dict) else {}
    status = str(freshness.get("status") or quote.get("status") or "unknown")
    is_current = status not in {"missing", "unavailable"} and not bool(freshness.get("is_stale"))
    return {
        "status": status,
        "is_current": is_current,
        "latest": quote.get("quote_time") or quote.get("trade_date"),
        "expected": freshness.get("expected_trade_date"),
        "resources": [
            {
                "resource": "quote",
                "label": "Quote",
                "status": status,
                "ok": is_current,
                "latest": quote.get("quote_time") or quote.get("trade_date"),
                "expected": freshness.get("expected_trade_date"),
                "reason": freshness.get("message"),
            }
        ],
    }


def _intraday_bar_freshness_resource(intraday_bars: dict[str, Any]) -> dict[str, Any]:
    if not intraday_bars.get("enabled"):
        return {
            "resource": "intraday_bars",
            "label": "Intraday bars",
            "status": "not_requested",
            "ok": True,
            "latest": None,
            "expected": None,
            "reason": "Intraday bars were not requested or not allowed by policy.",
        }
    series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
    latest_values = [
        item.get("to_time")
        for item in series.values()
        if isinstance(item, dict) and item.get("to_time")
    ]
    missing_intervals = [
        interval
        for interval, item in series.items()
        if not isinstance(item, dict) or not item.get("returned_point_count")
    ]
    status = "current" if series and not missing_intervals else "missing"
    return {
        "resource": "intraday_bars",
        "label": "Intraday bars",
        "status": status,
        "ok": status == "current",
        "latest": str(max(latest_values)) if latest_values else None,
        "expected": None,
        "reason": (
            "Intraday bar cache has 1m and 5m data."
            if status == "current"
            else "Missing intraday bars for: " + ", ".join(missing_intervals)
        ),
    }


def _cross_market_freshness_domain(overnight_impact: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(overnight_impact, dict):
        return {
            "status": "unavailable",
            "is_current": False,
            "latest": None,
            "expected": None,
            "missing": ["us_overnight_tw_impact"],
            "resources": [],
        }
    missing = overnight_impact.get("missing") if isinstance(overnight_impact.get("missing"), list) else []
    warnings = overnight_impact.get("warnings") if isinstance(overnight_impact.get("warnings"), list) else []
    status = "current" if not missing else "partial"
    return {
        "status": status,
        "is_current": status == "current",
        "latest": overnight_impact.get("as_of"),
        "expected": None,
        "missing": missing,
        "warnings": warnings,
        "resources": [
            {
                "resource": "us_overnight_tw_impact",
                "label": "US overnight impact",
                "status": status,
                "ok": status == "current",
                "latest": overnight_impact.get("as_of"),
                "expected": None,
                "reason": "Cross-market context derived from mapped US/ADR/index evidence.",
            }
        ],
    }


def _build_freshness_by_domain(
    *,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    source_health: dict[str, Any] | None,
    overnight_impact: dict[str, Any] | None,
    missing: list[str],
) -> dict[str, Any]:
    technical = _freshness_domain_from_resources(
        source_health=source_health,
        resources=FRESHNESS_DOMAIN_RESOURCES["technical"],
        missing=missing,
    )
    technical["resources"] = [
        *technical.get("resources", []),
        _intraday_bar_freshness_resource(intraday_bars),
    ]
    if intraday_bars.get("enabled") and any(not item.get("ok") for item in technical["resources"]):
        technical["status"] = "partial"
        technical["is_current"] = False

    return {
        "quote": _quote_freshness_domain(quote),
        "technical": technical,
        "chips": _freshness_domain_from_resources(
            source_health=source_health,
            resources=FRESHNESS_DOMAIN_RESOURCES["chips"],
            missing=missing,
        ),
        "fundamentals": _freshness_domain_from_resources(
            source_health=source_health,
            resources=FRESHNESS_DOMAIN_RESOURCES["fundamentals"],
            missing=missing,
        ),
        "cross_market": _cross_market_freshness_domain(overnight_impact),
    }


def _latest_intraday_point(intraday: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(intraday, dict):
        return None
    points = intraday.get("points") if isinstance(intraday.get("points"), list) else []
    for point in reversed(points):
        if isinstance(point, dict):
            return point
    return None


def _intraday_source_is_live(source: str | None) -> bool:
    source_text = str(source or "")
    if not source_text:
        return False
    if source_text in {"twse_openapi_mi_index", "tpex_openapi_daily_trading_index"}:
        return False
    return any(key in source_text for key in ("intraday", "twse_index_5s", "twse_mis", "yahoo_finance_chart"))


def _compact_index_quote(
    *,
    index_id: str,
    index_snapshot: dict[str, Any] | None,
    intraday: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = index_snapshot if isinstance(index_snapshot, dict) else {}
    latest_point = _latest_intraday_point(intraday)
    source = (
        str(intraday.get("source"))
        if isinstance(intraday, dict) and intraday.get("source")
        else str(snapshot.get("source") or "market_index_summary")
    )
    latest_price = (
        latest_point.get("price")
        if latest_point and latest_point.get("price") is not None
        else snapshot.get("close")
    )
    previous_close = (
        intraday.get("previous_close")
        if isinstance(intraday, dict) and intraday.get("previous_close") is not None
        else snapshot.get("previous_close")
    )
    change = (
        latest_price - previous_close
        if isinstance(latest_price, (int, float)) and isinstance(previous_close, (int, float))
        else snapshot.get("change")
    )
    change_pct = (
        (change / previous_close) * 100
        if isinstance(change, (int, float)) and isinstance(previous_close, (int, float)) and previous_close != 0
        else snapshot.get("change_pct")
    )
    is_live = bool(latest_point) and _intraday_source_is_live(source)
    quote_time = latest_point.get("time") if latest_point else snapshot.get("as_of") or snapshot.get("time")

    return {
        "kind": "quote_snapshot",
        "source": source,
        "provider": source,
        "status": "live_intraday" if is_live else "delayed_index_summary",
        "index_id": index_id,
        "trade_date": snapshot.get("time"),
        "quote_time": _json_value(quote_time),
        "latest_price": latest_price,
        "price": latest_price,
        "last_price": latest_price,
        "previous_close": previous_close,
        "open_price": (latest_point or {}).get("open") or snapshot.get("open"),
        "high_price": (latest_point or {}).get("high") or snapshot.get("high"),
        "low_price": (latest_point or {}).get("low") or snapshot.get("low"),
        "change": change,
        "change_pct": change_pct,
        "volume": (latest_point or {}).get("volume") or snapshot.get("volume"),
        "trade_value": snapshot.get("trade_value") or snapshot.get("estimated_trade_value"),
        "is_realtime": is_live,
        "latency_ms": None,
        "freshness": {
            "status": "live" if is_live else "delayed",
            "is_live": is_live,
            "is_stale": False,
            "message": (
                "Index intraday point is included."
                if latest_point
                else "Index intraday was not requested or not available; using latest index summary."
            ),
        },
    }


def _index_freshness_by_domain(
    *,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    market_chip: dict[str, Any] | None,
    missing: list[str],
) -> dict[str, Any]:
    chip_status = "current" if market_chip else "missing"
    return {
        "quote": _quote_freshness_domain(quote),
        "technical": {
            "status": "current" if "market_index_ohlc.daily" not in missing else "partial",
            "is_current": "market_index_ohlc.daily" not in missing,
            "resources": [_intraday_bar_freshness_resource(intraday_bars)],
        },
        "chips": {
            "status": chip_status,
            "is_current": market_chip is not None,
            "latest": (market_chip or {}).get("trade_date"),
            "missing": [] if market_chip else ["market_chip_daily"],
            "resources": [
                {
                    "resource": "market_chip_daily",
                    "label": "Market chip daily",
                    "status": chip_status,
                    "ok": market_chip is not None,
                    "latest": (market_chip or {}).get("trade_date"),
                    "expected": None,
                    "reason": "Latest market chip row is available." if market_chip else "No market chip row is available.",
                }
            ],
        },
    }


def _build_tw_index_compact_evidence(
    *,
    index_id: str,
    as_of: str | None,
    index_snapshot: dict[str, Any] | None,
    intraday: dict[str, Any] | None,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None,
    market_chip: dict[str, Any] | None,
    contributions: dict[str, Any] | None,
    technical_reports: dict[str, Any],
    technical_analysis: dict[str, Any],
    missing: list[str],
    warnings: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    intraday_bars = _compact_single_intraday_series(
        raw_payload=intraday,
        interval="1m",
        include_intraday=include_intraday,
        market_data_params=market_data_params,
    )
    quote = _compact_index_quote(
        index_id=index_id,
        index_snapshot=index_snapshot,
        intraday=intraday if include_intraday else None,
    )
    payload_level = _payload_level(market_data_params)
    target = {
        "type": "tw_index",
        "id": index_id,
        "label": (index_snapshot or {}).get("label") or index_id,
        "market": (index_snapshot or {}).get("market") or "TW",
    }
    technical = _compact_technical_evidence(
        analysis=technical_analysis,
        technical_levels={},
        technical_reports=technical_reports,
    )
    chips = {"market_chip": market_chip}
    data_quality = {
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
    }
    return {
        "kind": "tw_index_compact_evidence",
        "version": "tw_index_compact_evidence.v1",
        "payload_level": payload_level,
        "target": target,
        "as_of": as_of,
        "quote": quote,
        "intraday_bars": intraday_bars,
        "technical": technical,
        "chips": chips,
        "contributions": contributions,
        "freshness_by_domain": _index_freshness_by_domain(
            quote=quote,
            intraday_bars=intraday_bars,
            market_chip=market_chip,
            missing=missing,
        ),
        "data_quality": data_quality,
        "slots": _build_tw_index_slots(
            target=target,
            as_of=as_of,
            payload_level=payload_level,
            quote=quote,
            intraday_bars=intraday_bars,
            technical=technical,
            market_chip=market_chip,
            contributions=contributions,
            missing=data_quality["missing"],
            warnings=data_quality["warnings"],
        ),
        "source_refs": source_refs,
    }


def _build_stock_compact_evidence(
    *,
    stock: StockMaster | None,
    stock_id: str,
    as_of: str | None,
    latest_daily: Any,
    latest_institutional: Any,
    latest_margin: Any,
    shareholding: list[Any],
    branch_summary: dict[str, Any],
    latest_revenue: Any,
    revenue_history: list[Any],
    latest_financial: Any,
    financial_history: list[Any],
    technical_reports: dict[str, Any],
    technical_analysis: dict[str, Any],
    technical_levels: dict[str, Any],
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    source_health: dict[str, Any],
    overnight_impact: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    target = {
        "type": "tw_stock",
        "id": stock_id,
        "label": stock.stock_name if stock else None,
        "market": stock.market if stock else "TW",
    }
    technical = _compact_technical_evidence(
        analysis=technical_analysis,
        technical_levels=technical_levels,
        technical_reports=technical_reports,
    )
    chips = {
        "institutional": _compact_row(
            latest_institutional,
            (
                "trade_date",
                "foreign_investor_net",
                "investment_trust_net",
                "dealer_net",
                "total_institutional_net",
            ),
        ),
        "margin": _compact_row(
            latest_margin,
            (
                "trade_date",
                "margin_buy",
                "margin_sell",
                "margin_today_balance",
                "short_sale",
                "short_covering",
                "short_today_balance",
            ),
        ),
        "shareholding": [
            _compact_row(
                row,
                (
                    "data_date",
                    "holding_level",
                    "holder_count",
                    "share_count",
                    "share_ratio",
                ),
            )
            for row in shareholding[:5]
        ],
        "broker_branch": {
            "trade_date": _json_value(branch_summary.get("trade_date")),
            "requested_days": branch_summary.get("requested_days"),
            "available_days": branch_summary.get("available_days"),
            "is_partial": branch_summary.get("is_partial"),
            "buy_top": [_broker_branch_row(row) for row in branch_summary.get("buy_top", [])[:5]],
            "sell_top": [_broker_branch_row(row) for row in branch_summary.get("sell_top", [])[:5]],
        },
    }
    fundamentals = {
        "latest_revenue": _compact_row(
            latest_revenue,
            (
                "period",
                "monthly_revenue",
                "month_over_month_pct",
                "year_over_year_pct",
                "cumulative_revenue",
                "cumulative_year_over_year_pct",
            ),
        ),
        "latest_financial": _compact_row(
            latest_financial,
            (
                "period",
                "report_date",
                "revenue",
                "gross_profit",
                "operating_income",
                "net_income",
                "eps",
                "book_value_per_share",
                "roe",
                "roa",
            ),
        ),
        "revenue_history": [
            _compact_row(
                row,
                (
                    "period",
                    "monthly_revenue",
                    "month_over_month_pct",
                    "year_over_year_pct",
                    "cumulative_revenue",
                    "cumulative_year_over_year_pct",
                ),
            )
            for row in revenue_history[-6:]
        ],
        "financial_history": [
            _compact_row(
                row,
                (
                    "period",
                    "report_date",
                    "eps",
                    "book_value_per_share",
                    "roe",
                    "roa",
                ),
            )
            for row in financial_history[-4:]
        ],
    }
    data_quality = {
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
    }
    raw_payload_level = intraday_bars.get("payload_level") if isinstance(intraday_bars, dict) else None
    payload_level = str(raw_payload_level) if raw_payload_level in PAYLOAD_LEVELS else "compact"
    return {
        "kind": "stock_compact_evidence",
        "version": "stock_compact_evidence.v1",
        "payload_level": payload_level,
        "target": target,
        "as_of": as_of,
        "quote": quote,
        "intraday_bars": intraday_bars,
        "technical": technical,
        "chips": chips,
        "fundamentals": fundamentals,
        "freshness_by_domain": _build_freshness_by_domain(
            quote=quote,
            intraday_bars=intraday_bars,
            source_health=source_health,
            overnight_impact=overnight_impact,
            missing=missing,
        ),
        "data_quality": data_quality,
        "slots": _build_tw_stock_slots(
            target=target,
            as_of=as_of,
            payload_level=payload_level,
            quote=quote,
            intraday_bars=intraday_bars,
            technical=technical,
            chips=chips,
            fundamentals=fundamentals,
            missing=data_quality["missing"],
            warnings=data_quality["warnings"],
        ),
        "source_refs": source_refs,
    }


def _with_evidence_passport(
    envelope: dict[str, Any],
    *,
    freshness: dict[str, Any] | None = None,
    tool_runs: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    envelope["evidence_passport"] = build_evidence_passport(
        kind=str(envelope.get("kind") or "ai_data"),
        as_of=envelope.get("as_of"),
        source_refs=envelope.get("source_refs") or [],
        missing=envelope.get("missing") or [],
        warnings=envelope.get("warnings") or [],
        freshness=freshness,
        tool_runs=tool_runs,
        analysis=analysis or data.get("analysis"),
        confidence=confidence,
    )
    return envelope
