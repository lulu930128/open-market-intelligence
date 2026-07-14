from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai.agentic_common import _json_ready, _list_rows, _row_dict, _safe_int
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_context.common import (
    append_source_ref_once as _append_source_ref_once,
    compact_market_context as _compact_market_context,
)
from app.ai.market_context.regional_params import (
    _market_data_bool,
    _market_data_int,
    _market_data_str,
)
from app.ai.market_payload_contract import (
    intraday_point_limit as _market_intraday_point_limit,
    payload_level as _market_payload_level,
)
from app.db.models import USDailyPrice, USSecCompanyFact, USStockMaster
from app.us_market.sources import normalize_us_symbol


@dataclass(frozen=True)
class USContextDependencies:
    us_market_service: Any
    latest_profile: Callable[..., Any]
    scan_us_stock_gaps: Callable[..., dict[str, Any]]
    now: Callable[[], datetime]


def _latest_tool_result(tool_runs: list[dict[str, Any]], tool_name: str) -> dict[str, Any] | None:
    for run in reversed(tool_runs):
        if run.get("tool") == tool_name and run.get("status") == "success":
            summary = run.get("result_summary")
            if isinstance(summary, dict):
                return summary
    return None



def _us_intraday_compact(
    intraday_summary: dict[str, Any] | None,
    *,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload_level = _market_payload_level(market_data_params)
    point_limit = _market_intraday_point_limit(market_data_params)
    if not isinstance(intraday_summary, dict) or not intraday_summary:
        return {
            "enabled": False,
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "series": {},
            "warnings": ["US intraday trend was not requested or did not return data."],
        }

    raw_points = intraday_summary.get("points") if isinstance(intraday_summary.get("points"), list) else []
    points = [point for point in raw_points if isinstance(point, dict)]
    compact_points = points[-point_limit:]
    latest = intraday_summary.get("latest_point") if isinstance(intraday_summary.get("latest_point"), dict) else None
    if latest is None and points:
        latest = points[-1]

    point_count = _safe_int(
        intraday_summary.get("point_count"),
        len(points),
        minimum=0,
        maximum=100000,
    )
    raw_warnings = intraday_summary.get("warnings")
    warnings = raw_warnings if isinstance(raw_warnings, list) else []
    status = "ok" if latest or point_count > 0 else "missing"
    source = intraday_summary.get("source") or ("yahoo_finance_chart" if status == "ok" else "not_available")

    return {
        "enabled": True,
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "series": {
            "1m": {
                "interval": "1m",
                "source": source,
                "provider": "yahoo_chart" if source == "yahoo_finance_chart" else source,
                "session_scope": intraday_summary.get("session_scope") or "regular",
                "session_phase": intraday_summary.get("session_phase"),
                "point_count": point_count,
                "returned_point_count": len(compact_points),
                "latest": latest,
                "points": compact_points,
                "to_time": latest.get("time") if isinstance(latest, dict) else None,
                "previous_close": intraday_summary.get("previous_close"),
                "previous_close_source": intraday_summary.get("previous_close_source"),
                "previous_close_trade_date": intraday_summary.get("previous_close_trade_date"),
                "regular_session_close": intraday_summary.get("regular_session_close"),
                "regular_session_close_time": intraday_summary.get("regular_session_close_time"),
                "has_extended_hours": intraday_summary.get("has_extended_hours"),
                "source_url": intraday_summary.get("source_url"),
            }
        },
        "warnings": warnings,
    }


def _us_intraday_quote(intraday_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(intraday_summary, dict) or not intraday_summary:
        return {}

    latest = intraday_summary.get("latest_point") if isinstance(intraday_summary.get("latest_point"), dict) else None
    points = intraday_summary.get("points") if isinstance(intraday_summary.get("points"), list) else []
    if latest is None and points:
        latest = points[-1]
    if not isinstance(latest, dict):
        return {}

    price = latest.get("price")
    previous_close = intraday_summary.get("previous_close")
    change = None
    change_pct = None
    if isinstance(price, (int, float)) and isinstance(previous_close, (int, float)) and previous_close:
        change = float(price) - float(previous_close)
        change_pct = change / float(previous_close) * 100

    return {
        "source": intraday_summary.get("source") or "yahoo_finance_chart",
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "volume": latest.get("volume"),
        "quote_time": latest.get("time"),
        "is_realtime": True,
        "latency_ms": None,
        "session_phase": intraday_summary.get("session_phase") or latest.get("session"),
        "provider": "yahoo_chart",
        "previous_close": previous_close,
        "previous_close_source": intraday_summary.get("previous_close_source"),
        "point_count": intraday_summary.get("point_count"),
    }


def _us_intraday_latest_time(intraday_summary: dict[str, Any] | None) -> str | None:
    if not isinstance(intraday_summary, dict) or not intraday_summary:
        return None

    latest = intraday_summary.get("latest_point") if isinstance(intraday_summary.get("latest_point"), dict) else None
    points = intraday_summary.get("points") if isinstance(intraday_summary.get("points"), list) else []
    if latest is None and points:
        last_point = points[-1]
        latest = last_point if isinstance(last_point, dict) else None
    if not isinstance(latest, dict):
        return None

    time_value = latest.get("time")
    return str(time_value) if time_value else None


def _us_daily_quote(latest_daily: USDailyPrice | None, *, intraday_requested: bool) -> dict[str, Any]:
    quote = {
        "source": "us_daily_price",
        "price": latest_daily.close_price if latest_daily else None,
        "volume": latest_daily.trade_volume if latest_daily else None,
        "quote_time": latest_daily.trade_date.isoformat() if latest_daily else None,
        "is_realtime": False,
        "latency_ms": None,
        "session_phase": "daily_close" if latest_daily else None,
        "provider": latest_daily.provider if latest_daily else None,
    }
    if intraday_requested:
        quote["fallback_reason"] = "live_quote_not_available"
    return quote


def read_us_stock_context(
    db: Session,
    *,
    symbol: str,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    dependencies: USContextDependencies,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    tool_runs = tool_runs or []
    daily_limit = _market_data_int(market_data_params, "daily_limit", 10, minimum=1, maximum=200)
    timeframe = _market_data_str(market_data_params, "timeframe", "daily") or "daily"
    bars = _market_data_int(market_data_params, "bars", 90, minimum=1, maximum=5000)
    provider = _market_data_str(market_data_params, "provider", "auto") or "auto"
    include_intraday = _market_data_bool(market_data_params, "include_intraday", False)
    payload_level = _market_payload_level(market_data_params)
    session_scope = _market_data_str(market_data_params, "session_scope", "regular") or "regular"
    intraday_summary = _latest_tool_result(tool_runs, "us.read_intraday_trend")
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized_symbol)
        .first()
    )
    daily_rows = dependencies.us_market_service.list_us_daily_prices(
        db=db,
        symbol=normalized_symbol,
        limit=daily_limit,
    )
    profile = dependencies.latest_profile(db, normalized_symbol)
    sec_summary: dict[str, Any] | None = None
    sec_warning: str | None = None
    try:
        sec_summary = dependencies.us_market_service.get_us_sec_fundamental_summary(
            db=db,
            symbol=normalized_symbol,
        )
    except Exception as exc:
        sec_warning = str(exc)

    corporate_actions = dependencies.us_market_service.list_us_corporate_actions(
        db=db,
        symbol=normalized_symbol,
        limit=10,
    )
    short_volume_rows = dependencies.us_market_service.list_us_short_volumes(
        db=db,
        symbol=normalized_symbol,
        limit=10,
    )
    gaps = dependencies.scan_us_stock_gaps(db, normalized_symbol)
    source_health = dependencies.us_market_service.build_us_source_health(
        db=db,
        symbol=normalized_symbol,
    )
    latest_daily = daily_rows[0] if daily_rows else None
    warnings = list(gaps.get("warnings") or [])
    missing = list(gaps.get("missing") or [])
    if sec_warning and "us_sec_company_fact" not in missing:
        missing.append("us_sec_company_fact")
    if sec_warning:
        warnings.append(sec_warning)

    if include_intraday and intraday_summary is None:
        try:
            intraday_summary = dependencies.us_market_service.get_us_intraday_trend(
                symbol=normalized_symbol,
                session_scope=session_scope,
            )
        except Exception as exc:
            if "us_intraday_trend" not in missing:
                missing.append("us_intraday_trend")
            warnings.append(f"US intraday trend unavailable: {exc}")

    intraday_requested = include_intraday or intraday_summary is not None

    chart: dict[str, Any] = {}
    try:
        chart = dependencies.us_market_service.list_us_ohlc_chart_data(
            db=db,
            symbol=normalized_symbol,
            timeframe=timeframe,
            bars=bars,
            ensure_history=False,
            include_intraday=False,
            outputsize="compact",
            adjusted=False,
            provider=provider,
        )
        if intraday_requested and session_scope != "regular":
            chart["requested_session_scope"] = session_scope
        if not chart.get("point_count") and "us_ohlc_chart" not in missing:
            missing.append("us_ohlc_chart")
    except Exception as exc:
        missing.append("us_ohlc_chart")
        warnings.append(f"US OHLC chart unavailable: {exc}")

    for entry in source_health.get("entries") or []:
        if not isinstance(entry, dict) or entry.get("status") != "stale":
            continue
        warnings.append(
            f"US source health stale: {entry.get('resource')} via {entry.get('provider')} - {entry.get('reason')}"
        )

    source_refs: list[dict[str, Any]] = []
    for row in daily_rows[:3]:
        if row.source_url:
            source_refs.append(
                {
                    "kind": "us_daily_price",
                    "provider": row.provider,
                    "symbol": row.symbol,
                    "date": row.trade_date.isoformat(),
                    "url": row.source_url,
                }
            )
    if profile and profile.source_url:
        source_refs.append(
            {
                "kind": "us_company_profile",
                "provider": profile.provider,
                "symbol": profile.symbol,
                "fetched_at": profile.fetched_at.isoformat(),
                "url": profile.source_url,
            }
        )

    _append_source_ref_once(source_refs, {"type": "table", "name": "us_daily_price"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "us_company_profile"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "us_sec_company_fact"})
    if corporate_actions:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_corporate_action"})
    if short_volume_rows:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_short_volume_daily"})
    _append_source_ref_once(source_refs, {"type": "derived", "name": "app.us_market.source_health"})
    if intraday_summary:
        _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "yahoo_finance_chart"})

    intraday_quote = _us_intraday_quote(intraday_summary)
    quote = intraday_quote or _us_daily_quote(latest_daily, intraday_requested=intraday_requested)
    intraday_bars = _us_intraday_compact(intraday_summary, market_data_params=market_data_params)
    intraday_as_of = _us_intraday_latest_time(intraday_summary)
    envelope = {
        "kind": "us_stock_context",
        "generated_at": dependencies.now().isoformat(),
        "as_of": intraday_as_of or (latest_daily.trade_date.isoformat() if latest_daily else None),
        "scope": {
            "target": {
                "type": "us_stock",
                "id": normalized_symbol,
                "label": (profile.company_name if profile else None) or (stock.security_name if stock else None),
                "market": "US",
            }
        },
        "summary": {
            "latest_close": latest_daily.close_price if latest_daily else None,
            "latest_trade_date": latest_daily.trade_date.isoformat() if latest_daily else None,
            "latest_volume": latest_daily.trade_volume if latest_daily else None,
            "intraday": intraday_summary,
            "profile": _row_dict(
                profile,
                (
                    "provider",
                    "symbol",
                    "company_name",
                    "exchange",
                    "sector",
                    "industry",
                    "market_cap",
                    "pe_ratio",
                    "eps",
                    "revenue_ttm",
                    "profit_margin",
                    "latest_quarter",
                    "fetched_at",
                ),
            ),
            "sec_metric_count": (sec_summary or {}).get("metric_count") if sec_summary else 0,
            "chart": {
                "timeframe": chart.get("timeframe"),
                "bars": chart.get("bars"),
                "point_count": chart.get("point_count"),
                "include_intraday": False,
                "requested_include_intraday": intraday_requested,
            } if chart else {},
            "source_health": source_health.get("summary"),
        },
        "data": {
            "stock": _row_dict(
                stock,
                (
                    "symbol",
                    "security_name",
                    "exchange",
                    "asset_type",
                    "cik",
                    "sec_company_name",
                    "is_active",
                    "last_seen_at",
                    "updated_at",
                ),
            ),
            "daily_prices": _list_rows(
                daily_rows,
                (
                    "provider",
                    "symbol",
                    "trade_date",
                    "currency",
                    "open_price",
                    "high_price",
                    "low_price",
                    "close_price",
                    "adjusted_close",
                    "trade_volume",
                    "fetched_at",
                ),
            ),
            "chart": _json_ready(chart),
            "sec_fundamentals": sec_summary,
            "corporate_actions": _list_rows(
                corporate_actions,
                (
                    "provider",
                    "symbol",
                    "action_type",
                    "event_date",
                    "amount",
                    "split_ratio",
                    "fetched_at",
                ),
            ),
            "short_volume": _list_rows(
                short_volume_rows,
                (
                    "provider",
                    "symbol",
                    "trade_date",
                    "market_center",
                    "short_volume",
                    "total_volume",
                    "short_ratio",
                    "fetched_at",
                ),
            ),
            "source_health": source_health,
            "tool_runs": tool_runs,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    envelope["data"]["compact"] = _compact_market_context(
        kind="us_stock_compact_evidence",
        target=envelope["scope"]["target"],
        quote=quote,
        resources={
            "daily_rows": len(daily_rows),
            "profile_available": profile is not None,
            "sec_metric_count": (sec_summary or {}).get("metric_count") if sec_summary else 0,
            "corporate_action_rows": len(corporate_actions),
            "short_volume_rows": len(short_volume_rows),
            "chart_points": chart.get("point_count") if chart else 0,
            "timeframe": timeframe,
            "bars": bars,
            "payload_level": payload_level,
            "requested_provider": provider,
            "intraday": intraday_summary or {},
            "include_intraday": intraday_requested,
            "intraday_available": bool(intraday_quote),
        },
        freshness={
            "price": "current" if latest_daily or intraday_quote else "missing",
            "profile": "current" if profile else "missing",
            "chart": "current" if chart else "missing",
            "intraday": (
                "current"
                if intraday_quote
                else "missing"
                if intraday_requested
                else "not_requested"
            ),
            "source_health": source_health.get("summary"),
        },
        payload_level=payload_level,
    )
    envelope["data"]["compact"]["intraday_bars"] = intraday_bars
    envelope["evidence_passport"] = build_evidence_passport(
        kind="us_stock_context",
        as_of=envelope["as_of"],
        source_refs=source_refs,
        missing=envelope["missing"],
        warnings=envelope["warnings"],
        freshness=gaps,
        tool_runs=tool_runs,
    )
    return envelope
