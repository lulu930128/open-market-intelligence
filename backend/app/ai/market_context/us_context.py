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
from app.ai.market_date_request import parse_market_trade_date
from app.ai.market_payload_contract import (
    intraday_point_limit as _market_intraday_point_limit,
    payload_level as _market_payload_level,
    requested_intraday_interval as _requested_intraday_interval,
)
from app.db.models import USDailyPrice, USSecCompanyFact, USStockMaster
from app.market.calendar_status import build_us_calendar_status
from app.observability.source_health_contract import summarize_source_health
from app.us_market.chart_projection import filter_ohlc_source_rows
from app.us_market.sources import normalize_us_symbol
from app.us_market.symbols import us_instrument_type
from app.us_market.trading_calendar import (
    US_MARKET_TIMEZONE,
    US_SESSION_CLOSE_TIME,
)


@dataclass(frozen=True)
class USContextDependencies:
    us_market_service: Any
    latest_profile: Callable[..., Any]
    scan_us_stock_gaps: Callable[..., dict[str, Any]]
    now: Callable[[], datetime]


def _select_latest_daily(rows: list[USDailyPrice]) -> USDailyPrice | None:
    canonical_rows = filter_ohlc_source_rows(rows)
    return canonical_rows[-1] if canonical_rows else None


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
    requested_interval = (
        _requested_intraday_interval(market_data_params, default="1m")
        or "1m"
    )
    if not isinstance(intraday_summary, dict) or not intraday_summary:
        interval_status = (
            "unavailable" if requested_interval == "1m" else "unsupported"
        )
        return {
            "enabled": False,
            "requested_interval": requested_interval,
            "source_interval": "1m",
            "effective_interval": None,
            "interval_status": interval_status,
            "sampling_mode": "not_available",
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "series": {},
            "warnings": [
                (
                    "US intraday trend was not requested or did not return data."
                    if interval_status == "unavailable"
                    else (
                        f"Requested US intraday interval {requested_interval} is "
                        "unsupported; the provider contract only exposes 1m bars."
                    )
                )
            ],
        }

    raw_points = intraday_summary.get("points") if isinstance(intraday_summary.get("points"), list) else []
    points = [point for point in raw_points if isinstance(point, dict)]
    compact_points = points[-point_limit:]
    volume_unit = (
        intraday_summary.get("volume_unit")
        or (
            "shares"
            if any(point.get("volume") is not None for point in compact_points)
            else None
        )
    )
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
    source_interval = str(
        intraday_summary.get("source_interval")
        or intraday_summary.get("interval")
        or "1m"
    )
    effective_interval = str(
        intraday_summary.get("effective_interval")
        or source_interval
    )
    if requested_interval != effective_interval:
        warnings = [
            *warnings,
            (
                f"Requested US intraday interval {requested_interval} is not available; "
                f"returned {effective_interval} source bars without relabeling."
            ),
        ]
    sampling_mode = str(
        intraday_summary.get("sampling_mode")
        or (
            "latest_n"
            if point_count > len(compact_points)
            else "complete"
        )
    )
    original_point_count = _safe_int(
        intraday_summary.get("original_point_count"),
        point_count,
        minimum=0,
        maximum=100000,
    )

    return {
        "enabled": True,
        "requested_interval": requested_interval,
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "series": {
            source_interval: {
                "interval": effective_interval,
                "requested_interval": requested_interval,
                "source_interval": source_interval,
                "effective_interval": effective_interval,
                "interval_status": (
                    "ready"
                    if requested_interval == effective_interval
                    else "unsupported"
                ),
                "sampling_mode": sampling_mode,
                "original_point_count": original_point_count,
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
                "volume_unit": volume_unit,
                "volume_semantics": (
                    intraday_summary.get("volume_semantics")
                    or ("interval_shares" if volume_unit else None)
                ),
                "volume_status": (
                    intraday_summary.get("volume_status")
                    or ("available" if volume_unit else "not_provided")
                ),
            }
        },
        "warnings": warnings,
    }


def _parse_market_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _market_trade_date(value: Any) -> str | None:
    parsed = _parse_market_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=US_MARKET_TIMEZONE)
    return parsed.astimezone(US_MARKET_TIMEZONE).date().isoformat()


def _intraday_quote_semantics(session: str | None) -> str:
    normalized = str(session or "").strip().lower()
    if normalized == "pre_market":
        return "pre_market_last_trade"
    if normalized == "after_hours":
        return "after_hours_last_trade"
    if normalized == "regular":
        return "regular_session_last_trade"
    return "intraday_last_trade"


def _us_intraday_quote(
    intraday_summary: dict[str, Any] | None,
    *,
    calendar_status: dict[str, Any] | None = None,
    instrument_type: str = "stock",
) -> dict[str, Any]:
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

    market_calendar = calendar_status or build_us_calendar_status()
    current_phase = str(market_calendar.get("phase") or "closed")
    checked_at = _parse_market_datetime(market_calendar.get("checked_at"))
    quote_time = _parse_market_datetime(latest.get("time"))
    quote_trade_date = _market_trade_date(quote_time)
    latest_session_date = str(market_calendar.get("previous_trading_day") or "") or None
    is_latest_session_quote = bool(
        quote_trade_date and latest_session_date and quote_trade_date == latest_session_date
    )
    last_quote_session = str(
        latest.get("session") or intraday_summary.get("session_phase") or ""
    ) or None
    open_phases = {"pre_market", "regular", "after_hours"}
    quote_age_seconds = None
    if checked_at is not None and quote_time is not None:
        quote_age_seconds = max(0.0, (checked_at - quote_time).total_seconds())
    is_live = bool(
        is_latest_session_quote
        and current_phase in open_phases
        and last_quote_session == current_phase
        and quote_age_seconds is not None
        and quote_age_seconds <= 300
    )

    volume = latest.get("volume")
    volume_status = "ready"
    if instrument_type == "index":
        volume = None
        volume_status = "provider_unavailable"

    regular_session_close_time = intraday_summary.get("regular_session_close_time")
    return {
        "source": intraday_summary.get("source") or "yahoo_finance_chart",
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "currency": "USD",
        "volume": volume,
        "volume_unit": "shares" if volume is not None else None,
        "volume_semantics": "interval_shares" if volume is not None else None,
        "volume_status": volume_status,
        "instrument_type": instrument_type,
        "trade_date": quote_trade_date,
        "quote_time": latest.get("time"),
        "timezone": str(US_MARKET_TIMEZONE),
        "quote_semantics": _intraday_quote_semantics(last_quote_session),
        "is_historical": False,
        # Compatibility alias.  It now means that this quote is live in the
        # current market session, not merely that it came from a minute source.
        "is_realtime": is_live,
        "is_live": is_live,
        "is_latest_session_quote": is_latest_session_quote,
        "market_status": "open" if current_phase in open_phases else "closed",
        "current_session_phase": current_phase,
        "last_quote_session": last_quote_session,
        "source_is_intraday": True,
        "quote_age_seconds": quote_age_seconds,
        "latency_ms": None,
        "session_phase": intraday_summary.get("session_phase") or latest.get("session"),
        "provider": "yahoo_chart",
        "previous_close": previous_close,
        "previous_close_source": intraday_summary.get("previous_close_source"),
        "previous_close_trade_date": intraday_summary.get("previous_close_trade_date"),
        "previous_close_provider": intraday_summary.get("previous_close_provider"),
        "regular_session_close": intraday_summary.get("regular_session_close"),
        "regular_session_close_time": regular_session_close_time,
        "regular_session_close_trade_date": _market_trade_date(
            regular_session_close_time
        ),
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


def _us_daily_quote(
    latest_daily: USDailyPrice | None,
    *,
    intraday_requested: bool,
    calendar_status: dict[str, Any] | None = None,
    requested_trade_date: str | None = None,
    instrument_type: str = "stock",
) -> dict[str, Any]:
    volume = latest_daily.trade_volume if latest_daily else None
    volume_status = "ready" if volume is not None else "missing"
    if instrument_type == "index":
        volume = None
        volume_status = "provider_unavailable"
    trade_date = latest_daily.trade_date.isoformat() if latest_daily else None
    close_time = (
        datetime.combine(
            latest_daily.trade_date,
            US_SESSION_CLOSE_TIME,
            tzinfo=US_MARKET_TIMEZONE,
        ).isoformat()
        if latest_daily
        else None
    )
    is_historical = requested_trade_date is not None
    latest_session_date = str(
        (calendar_status or {}).get("previous_trading_day") or ""
    ) or None
    is_latest_session_quote = bool(
        not is_historical
        and trade_date
        and latest_session_date
        and trade_date == latest_session_date
    )
    quote = {
        "source": "us_daily_price",
        "status": (
            "missing"
            if latest_daily is None
            else "historical"
            if is_historical
            else "daily_close"
        ),
        "price": latest_daily.close_price if latest_daily else None,
        "volume": volume,
        "volume_unit": "shares" if volume is not None else None,
        "volume_semantics": "daily_shares" if volume is not None else None,
        "volume_status": volume_status,
        "currency": latest_daily.currency if latest_daily else "USD",
        "instrument_type": instrument_type,
        "trade_date": trade_date,
        "quote_time": close_time,
        "quote_time_basis": "scheduled_regular_session_close",
        "timezone": str(US_MARKET_TIMEZONE),
        "is_realtime": False,
        "is_live": False,
        "is_latest_session_quote": is_latest_session_quote,
        "is_historical": is_historical,
        "latency_ms": None,
        "market_status": "historical" if is_historical else "closed",
        "current_session_phase": (calendar_status or {}).get("phase"),
        "session_phase": "regular_session_close" if latest_daily else None,
        "quote_semantics": (
            "historical_regular_session_close"
            if is_historical
            else "regular_session_close"
        ),
        "provider": latest_daily.provider if latest_daily else None,
        "regular_session_close": latest_daily.close_price if latest_daily else None,
        "regular_session_close_time": close_time,
        "regular_session_close_trade_date": trade_date,
    }
    if requested_trade_date is not None:
        quote["requested_trade_date"] = requested_trade_date
    if intraday_requested:
        quote["fallback_reason"] = "live_quote_not_available"
    return quote


def _project_source_health_for_instrument(
    source_health: dict[str, Any],
    *,
    instrument_type: str,
) -> dict[str, Any]:
    if instrument_type != "index":
        return source_health

    applicable_resources = {"symbol_master", "daily_price"}
    entries = [
        entry
        for entry in source_health.get("entries") or []
        if isinstance(entry, dict) and entry.get("resource") in applicable_resources
    ]
    projected = dict(source_health)
    projected["entries"] = entries
    projected["summary"] = summarize_source_health(
        entries,
        counted_statuses=("empty", "stale", "partial", "error"),
    )
    projected["not_applicable_resources"] = [
        "profile",
        "sec_facts",
        "corporate_actions",
        "short_volume",
        "macro_series",
    ]
    return projected


def _annotate_daily_provider_roles(
    source_health: dict[str, Any],
    *,
    selected_provider: str | None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    selected_entries: list[dict[str, Any]] = []
    fallback_entries: list[dict[str, Any]] = []
    for raw_entry in source_health.get("entries") or []:
        if not isinstance(raw_entry, dict):
            continue
        entry = dict(raw_entry)
        if entry.get("resource") == "daily_price":
            role = "selected" if entry.get("provider") == selected_provider else "fallback"
            entry["provider_role"] = role
            if role == "selected":
                selected_entries.append(entry)
            else:
                fallback_entries.append(entry)
        else:
            entry["provider_role"] = "supporting"
        entries.append(entry)

    annotated = dict(source_health)
    annotated["entries"] = entries
    annotated["selected_provider"] = selected_provider
    annotated["selected_provider_status"] = (
        selected_entries[0].get("status") if selected_entries else "missing"
    )
    annotated["selected_evidence_summary"] = summarize_source_health(
        selected_entries,
        counted_statuses=("empty", "stale", "partial", "error"),
    )
    annotated["fallback_provider_summary"] = summarize_source_health(
        fallback_entries,
        counted_statuses=("empty", "stale", "partial", "error"),
    )
    return annotated


def read_us_stock_context(
    db: Session,
    *,
    symbol: str,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    dependencies: USContextDependencies,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol)
    instrument_type = us_instrument_type(normalized_symbol)
    is_index = instrument_type == "index"
    tool_runs = tool_runs or []
    daily_limit = _market_data_int(market_data_params, "daily_limit", 10, minimum=1, maximum=200)
    timeframe = _market_data_str(market_data_params, "timeframe", "daily") or "daily"
    bars = _market_data_int(market_data_params, "bars", 90, minimum=1, maximum=5000)
    provider = _market_data_str(market_data_params, "provider", "auto") or "auto"
    include_intraday = _market_data_bool(market_data_params, "include_intraday", False)
    payload_level = _market_payload_level(market_data_params)
    session_scope = _market_data_str(market_data_params, "session_scope", "regular") or "regular"
    requested_trade_date_value = parse_market_trade_date(
        _market_data_str(market_data_params, "trade_date")
    )
    requested_trade_date = (
        requested_trade_date_value.isoformat()
        if requested_trade_date_value is not None
        else None
    )
    if requested_trade_date is not None:
        include_intraday = False
    intraday_summary = (
        None
        if requested_trade_date is not None
        else _latest_tool_result(tool_runs, "us.read_intraday_trend")
    )
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized_symbol)
        .first()
    )
    daily_rows = dependencies.us_market_service.list_us_daily_prices(
        db=db,
        symbol=normalized_symbol,
        from_date=requested_trade_date_value,
        to_date=requested_trade_date_value,
        limit=daily_limit,
    )
    latest_daily = _select_latest_daily(daily_rows)
    selected_daily_provider = latest_daily.provider if latest_daily else None
    profile = None if is_index else dependencies.latest_profile(db, normalized_symbol)
    sec_summary: dict[str, Any] | None = None
    sec_warning: str | None = None
    if not is_index:
        try:
            sec_summary = dependencies.us_market_service.get_us_sec_fundamental_summary(
                db=db,
                symbol=normalized_symbol,
            )
        except Exception as exc:
            sec_warning = str(exc)

    corporate_actions = [] if is_index else dependencies.us_market_service.list_us_corporate_actions(
        db=db,
        symbol=normalized_symbol,
        limit=10,
    )
    short_volume_rows = [] if is_index else dependencies.us_market_service.list_us_short_volumes(
        db=db,
        symbol=normalized_symbol,
        limit=10,
    )
    gaps = dependencies.scan_us_stock_gaps(db, normalized_symbol)
    source_health = dependencies.us_market_service.build_us_source_health(
        db=db,
        symbol=normalized_symbol,
    )
    source_health = _project_source_health_for_instrument(
        source_health,
        instrument_type=instrument_type,
    )
    source_health = _annotate_daily_provider_roles(
        source_health,
        selected_provider=selected_daily_provider,
    )
    warnings = list(gaps.get("warnings") or [])
    missing = list(gaps.get("missing") or [])
    if is_index:
        warnings.append(
            "Yahoo index volume is not a tradable-instrument volume series; volume is returned as unavailable."
        )
    if sec_warning and "us_sec_company_fact" not in missing:
        missing.append("us_sec_company_fact")
    if sec_warning:
        warnings.append(sec_warning)
    if requested_trade_date is not None and latest_daily is None:
        requested_missing = "us_daily_price_requested_trade_date"
        if requested_missing not in missing:
            missing.append(requested_missing)
        warnings.append(
            "No US regular-session close is available for requested trade date "
            f"{requested_trade_date}; OMI did not fall back to another date."
        )
    if requested_trade_date is not None and latest_daily is not None:
        warnings.append(
            "US daily close time is projected from the regular 16:00 "
            "America/New_York schedule; the local fallback calendar does not "
            "model special early-close sessions."
        )

    if include_intraday and intraday_summary is None:
        try:
            intraday_summary = dependencies.us_market_service.get_us_intraday_trend(
                symbol=normalized_symbol,
                session_scope=session_scope,
                db=db,
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
            to_date=requested_trade_date_value,
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
        provider_role = entry.get("provider_role")
        if entry.get("resource") == "daily_price" and provider_role == "fallback":
            warnings.append(
                f"US fallback provider stale: daily_price via {entry.get('provider')} - {entry.get('reason')}"
            )
        elif entry.get("resource") == "daily_price" and provider_role == "selected":
            warnings.append(
                f"US selected provider stale: daily_price via {entry.get('provider')} - {entry.get('reason')}"
            )
        else:
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
    if not is_index:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_company_profile"})
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_sec_company_fact"})
    if corporate_actions:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_corporate_action"})
    if short_volume_rows:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_short_volume_daily"})
    _append_source_ref_once(source_refs, {"type": "derived", "name": "app.us_market.source_health"})
    if intraday_summary:
        _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "yahoo_finance_chart"})

    context_now = dependencies.now()
    us_calendar_status = build_us_calendar_status(now=context_now)
    intraday_quote = _us_intraday_quote(
        intraday_summary,
        calendar_status=us_calendar_status,
        instrument_type=instrument_type,
    )
    quote = intraday_quote or _us_daily_quote(
        latest_daily,
        intraday_requested=intraday_requested,
        calendar_status=us_calendar_status,
        requested_trade_date=requested_trade_date,
        instrument_type=instrument_type,
    )
    intraday_bars = _us_intraday_compact(intraday_summary, market_data_params=market_data_params)
    intraday_as_of = _us_intraday_latest_time(intraday_summary)
    quote_as_of = quote.get("quote_time") if isinstance(quote, dict) else None
    envelope = {
        "kind": "us_stock_context",
        "generated_at": context_now.isoformat(),
        "as_of": quote_as_of
        or intraday_as_of
        or (latest_daily.trade_date.isoformat() if latest_daily else requested_trade_date),
        "scope": {
            "target": {
                "type": "us_stock",
                "id": normalized_symbol,
                "label": (profile.company_name if profile else None) or (stock.security_name if stock else None),
                "market": "US",
                "instrument_type": instrument_type,
            }
        },
        "summary": {
            "latest_close": latest_daily.close_price if latest_daily else None,
            "latest_trade_date": latest_daily.trade_date.isoformat() if latest_daily else None,
            "requested_trade_date": requested_trade_date,
            "quote_semantics": quote.get("quote_semantics"),
            "latest_volume": (
                None if is_index else latest_daily.trade_volume if latest_daily else None
            ),
            "latest_volume_status": (
                "provider_unavailable"
                if is_index
                else "ready"
                if latest_daily and latest_daily.trade_volume is not None
                else "missing"
            ),
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
            "selected_provider": selected_daily_provider,
            "selected_provider_status": source_health.get("selected_provider_status"),
            "fallback_provider_summary": source_health.get("fallback_provider_summary"),
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
        "data_limitations": (
            [
                "This target is an index; company profile, SEC company facts, corporate actions, and company short volume are not applicable.",
                "Yahoo index volume is unavailable and is not replaced with ETF proxy volume or zero.",
            ]
            if is_index
            else []
        ),
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    envelope["data"]["compact"] = _compact_market_context(
        kind="us_index_compact_evidence" if is_index else "us_stock_compact_evidence",
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
            "selected_provider": selected_daily_provider,
            "requested_trade_date": requested_trade_date,
            "intraday": intraday_summary or {},
            "include_intraday": intraday_requested,
            "intraday_available": bool(intraday_quote),
        },
        freshness={
            "price": (
                "historical"
                if requested_trade_date is not None and latest_daily
                else "current"
                if latest_daily or intraday_quote
                else "missing"
            ),
            "profile": "current" if profile else "missing",
            "chart": "current" if chart else "missing",
            "intraday": (
                "current"
                if intraday_quote
                else "missing"
                if intraday_requested
                else "not_requested"
            ),
            "source_health": source_health.get("selected_evidence_summary"),
        },
        payload_level=payload_level,
    )
    envelope["data"]["compact"]["provider_selection"] = {
        "selected_provider": {
            "name": selected_daily_provider,
            "status": source_health.get("selected_provider_status"),
        },
        "fallback_providers": source_health.get("fallback_provider_summary"),
        "provider_health": source_health.get("summary"),
    }
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
