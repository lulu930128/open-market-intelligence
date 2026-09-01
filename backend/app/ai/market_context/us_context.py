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
from app.db.models import USSecCompanyFact, USStockMaster
from app.market.calendar_status import build_us_calendar_status
from app.observability.source_health_contract import summarize_source_health
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.sources import normalize_us_symbol
from app.us_market.symbols import us_instrument_type
from app.us_market.trading_calendar import (
    US_MARKET_TIMEZONE,
    is_us_early_close_day,
    us_session_close_time,
)
from app.us_market.volume_semantics import summarize_intraday_volume


@dataclass(frozen=True)
class USContextDependencies:
    us_market_service: Any
    latest_profile: Callable[..., Any]
    scan_us_stock_gaps: Callable[..., dict[str, Any]]
    now: Callable[[], datetime]


@dataclass(frozen=True)
class _ResolvedDailyContextRow:
    provider: str
    symbol: str
    trade_date: Any
    currency: str
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    adjusted_close: float | None
    trade_volume: int | float | None
    fetched_at: datetime | None
    source: str | None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _resolved_daily_context_rows(
    projection: dict[str, Any],
    *,
    symbol: str,
    limit: int,
) -> list[_ResolvedDailyContextRow]:
    rows: list[_ResolvedDailyContextRow] = []
    for bar in projection.get("bars") or []:
        if not isinstance(bar, dict):
            continue
        end_at = _parse_market_datetime(bar.get("end_at"))
        if end_at is None:
            continue
        volume = _optional_float(bar.get("volume"))
        rows.append(
            _ResolvedDailyContextRow(
                provider=str(bar.get("provider") or "unresolved"),
                symbol=symbol,
                trade_date=end_at.astimezone(US_MARKET_TIMEZONE).date(),
                currency="USD",
                open_price=_optional_float(bar.get("open_price")),
                high_price=_optional_float(bar.get("high_price")),
                low_price=_optional_float(bar.get("low_price")),
                close_price=_optional_float(bar.get("close_price")),
                adjusted_close=None,
                trade_volume=(
                    int(volume) if volume is not None and volume.is_integer() else volume
                ),
                fetched_at=_parse_market_datetime(bar.get("fetched_at")),
                source=str(bar.get("source")) if bar.get("source") else None,
            )
        )
    return rows[-limit:]


def _latest_tool_result(tool_runs: list[dict[str, Any]], tool_name: str) -> dict[str, Any] | None:
    for run in reversed(tool_runs):
        if run.get("tool") == tool_name and run.get("status") == "success":
            summary = run.get("result_summary")
            if isinstance(summary, dict):
                result = dict(summary)
                resolved_market_data = summary.pop("_resolved_market_data", None)
                if isinstance(resolved_market_data, dict):
                    result["_resolved_market_data"] = resolved_market_data
                return result
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
    compact_volume = summarize_intraday_volume(compact_points)
    volume_unit = intraday_summary.get("volume_unit") or compact_volume["volume_unit"]
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
                "market_phase": intraday_summary.get("market_phase"),
                "capability_expectation": intraday_summary.get(
                    "capability_expectation"
                ),
                "point_count": point_count,
                "returned_point_count": len(compact_points),
                "latest": latest,
                "points": compact_points,
                "to_time": latest.get("time") if isinstance(latest, dict) else None,
                "previous_close": intraday_summary.get("previous_close"),
                "previous_close_source": intraday_summary.get("previous_close_source"),
                "previous_close_trade_date": intraday_summary.get("previous_close_trade_date"),
                "change_reference_price": intraday_summary.get(
                    "change_reference_price"
                ),
                "change_reference_type": intraday_summary.get(
                    "change_reference_type"
                ),
                "change_reference_trade_date": intraday_summary.get(
                    "change_reference_trade_date"
                ),
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
                    or compact_volume["volume_status"]
                ),
                "volume_coverage": (
                    intraday_summary.get("volume_coverage")
                    if isinstance(intraday_summary.get("volume_coverage"), dict)
                    else compact_volume["volume_coverage"]
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
    change_reference = intraday_summary.get("change_reference_price")
    change = None
    change_pct = None
    if (
        isinstance(price, (int, float))
        and isinstance(change_reference, (int, float))
        and change_reference
    ):
        change = float(price) - float(change_reference)
        change_pct = change / float(change_reference) * 100

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
    bar_source_status = (
        intraday_summary.get("bar_source_status")
        if isinstance(intraday_summary.get("bar_source_status"), dict)
        else intraday_summary.get("source_status")
        if isinstance(intraday_summary.get("source_status"), dict)
        else {}
    )
    current_source_status = (
        intraday_summary.get("current_source_status")
        if isinstance(intraday_summary.get("current_source_status"), dict)
        else {}
    )
    quote_expectation = (
        intraday_summary.get("capability_expectation", {}).get("quote.snapshot")
        if isinstance(intraday_summary.get("capability_expectation"), dict)
        else None
    )
    if current_source_status:
        is_live = bool(
            current_source_status.get("status") == "current"
            and current_source_status.get("decision_usable") is True
        )
        quote_age_seconds = current_source_status.get("lag_seconds")
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
        "provider": bar_source_status.get("provider") or intraday_summary.get("provider"),
        "previous_close": previous_close,
        "previous_close_source": intraday_summary.get("previous_close_source"),
        "previous_close_trade_date": intraday_summary.get("previous_close_trade_date"),
        "previous_close_provider": intraday_summary.get("previous_close_provider"),
        "change_reference_price": change_reference,
        "change_reference_type": intraday_summary.get("change_reference_type"),
        "change_reference_trade_date": intraday_summary.get(
            "change_reference_trade_date"
        ),
        "change_reference_source": intraday_summary.get(
            "change_reference_source"
        ),
        "market_phase": intraday_summary.get("market_phase") or current_phase,
        "capability_expectation": quote_expectation,
        "provider_snapshot_freshness": current_source_status.get(
            "provider_snapshot_freshness"
        ),
        "trade_recency": current_source_status.get("trade_recency"),
        "trade_state": current_source_status.get("trade_state"),
        "regular_session_close": intraday_summary.get("regular_session_close"),
        "regular_session_close_time": regular_session_close_time,
        "regular_session_close_trade_date": _market_trade_date(
            regular_session_close_time
        ),
        "point_count": intraday_summary.get("point_count"),
    }


def _us_resolved_quote(
    quote_snapshot: dict[str, Any] | None,
    *,
    calendar_status: dict[str, Any] | None = None,
    instrument_type: str = "stock",
    previous_close_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project canonical persisted Quote evidence into the AI quote contract."""

    if not isinstance(quote_snapshot, dict) or quote_snapshot.get("facts_usable") is not True:
        return {}
    value = quote_snapshot.get("quote")
    if not isinstance(value, dict):
        return {}
    price = _optional_float(value.get("last_trade_price"))
    if price is None:
        return {}

    previous_close = _optional_float(
        (previous_close_reference or {}).get("previous_close")
    )
    change_reference = _optional_float(
        (previous_close_reference or {}).get("change_reference_price")
    )
    if change_reference is None:
        change_reference = previous_close
    change = price - change_reference if change_reference not in {None, 0} else None
    change_pct = (
        change / change_reference * 100
        if change is not None and change_reference not in {None, 0}
        else None
    )
    market_calendar = calendar_status or build_us_calendar_status()
    current_phase = str(market_calendar.get("phase") or "closed")
    checked_at = _parse_market_datetime(market_calendar.get("checked_at"))
    quote_time = _parse_market_datetime(value.get("event_at"))
    quote_trade_date = str(value.get("trade_date") or "") or _market_trade_date(quote_time)
    latest_session_date = str(market_calendar.get("previous_trading_day") or "") or None
    is_latest_session_quote = bool(
        quote_trade_date and latest_session_date and quote_trade_date == latest_session_date
    )
    selected_session = str(quote_snapshot.get("selected_session") or "") or None
    session_phase = {
        "pre_open": "pre_market",
        "continuous": "regular",
        "closing_auction": "regular",
        "post_close": "after_hours",
    }.get(selected_session, selected_session)
    quote_age_seconds = None
    if checked_at is not None and quote_time is not None:
        quote_age_seconds = max(0.0, (checked_at - quote_time).total_seconds())
    limitations = {
        str(item) for item in quote_snapshot.get("limitations") or [] if str(item)
    }
    if previous_close is None:
        limitations.add("CANONICAL_US_DAILY_PREVIOUS_CLOSE_MISSING")
    delayed_vendor = "DELAYED_VENDOR_EVIDENCE" in limitations
    open_phases = {"pre_market", "regular", "after_hours"}
    is_live = bool(
        not delayed_vendor
        and is_latest_session_quote
        and current_phase in open_phases
        and session_phase == current_phase
        and quote_age_seconds is not None
        and quote_age_seconds <= 300
    )
    source_status = (
        quote_snapshot.get("source_status")
        if isinstance(quote_snapshot.get("source_status"), dict)
        else {}
    )
    if source_status:
        is_live = bool(
            source_status.get("status") == "current"
            and source_status.get("decision_usable") is True
        )
        quote_age_seconds = source_status.get("lag_seconds")
    return {
        "source": quote_snapshot.get("selected_source") or "canonical_quote_cache",
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "currency": value.get("currency") or "USD",
        "volume": None,
        "volume_unit": None,
        "volume_semantics": None,
        "volume_status": "provider_unavailable" if instrument_type == "index" else "not_provided",
        "instrument_type": instrument_type,
        "trade_date": quote_trade_date,
        "quote_time": value.get("event_at"),
        "timezone": str(US_MARKET_TIMEZONE),
        "quote_semantics": _intraday_quote_semantics(session_phase),
        "is_historical": False,
        "is_realtime": is_live,
        "is_live": is_live,
        "is_latest_session_quote": is_latest_session_quote,
        "market_status": "open" if current_phase in open_phases else "closed",
        "current_session_phase": current_phase,
        "last_quote_session": session_phase,
        "source_is_intraday": True,
        "quote_age_seconds": quote_age_seconds,
        "latency_ms": None,
        "session_phase": session_phase,
        "provider": quote_snapshot.get("selected_provider"),
        "previous_close": previous_close,
        "previous_close_source": (previous_close_reference or {}).get(
            "previous_close_source"
        ),
        "previous_close_trade_date": (previous_close_reference or {}).get(
            "previous_close_trade_date"
        ),
        "previous_close_provider": (previous_close_reference or {}).get(
            "previous_close_provider"
        ),
        "change_reference_price": change_reference,
        "change_reference_type": (previous_close_reference or {}).get(
            "change_reference_type"
        ),
        "change_reference_trade_date": (previous_close_reference or {}).get(
            "change_reference_trade_date"
        ),
        "change_reference_source": (previous_close_reference or {}).get(
            "change_reference_source"
        ),
        "market_phase": quote_snapshot.get("market_phase") or current_phase,
        "capability_expectation": quote_snapshot.get(
            "capability_expectation"
        ),
        "provider_snapshot_freshness": source_status.get(
            "provider_snapshot_freshness"
        ),
        "trade_recency": source_status.get("trade_recency"),
        "trade_state": source_status.get("trade_state") or value.get("trade_state"),
        "regular_session_close": None,
        "regular_session_close_time": None,
        "regular_session_close_trade_date": None,
        "point_count": 1,
        "limitations": sorted(limitations),
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
    latest_daily: _ResolvedDailyContextRow | None,
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
            us_session_close_time(latest_daily.trade_date),
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
    requested_capability_values = (
        market_data_params.get("requested_capabilities")
        if isinstance(market_data_params, dict)
        else None
    )
    requested_capabilities = (
        tuple(
            dict.fromkeys(
                str(value)
                for value in requested_capability_values
                if str(value).strip()
            )
        )
        if isinstance(requested_capability_values, list)
        else None
    )
    requested_capability_set = frozenset(requested_capabilities or ())
    selection_bounded = requested_capabilities is not None

    def wants(*capabilities: str) -> bool:
        return not selection_bounded or bool(
            requested_capability_set.intersection(capabilities)
        )

    needs_daily = wants("quote.snapshot", "daily.ohlcv", "technical.structure")
    needs_profile = wants("company.profile")
    needs_sec = wants("fundamentals.financials")
    needs_insider = wants("ownership.insider_transactions")
    needs_institutional = wants("ownership.distribution")
    needs_corporate_actions = wants("corporate.actions")
    needs_short_volume = wants("market.short_volume")
    needs_chart = wants("daily.ohlcv", "technical.structure")
    needs_research = wants("technical.structure")
    daily_limit = _market_data_int(market_data_params, "daily_limit", 10, minimum=1, maximum=200)
    timeframe = _market_data_str(market_data_params, "timeframe", "daily") or "daily"
    bars = _market_data_int(market_data_params, "bars", 90, minimum=1, maximum=5000)
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
        else (
            _latest_tool_result(tool_runs, "us.refresh_intraday_bars")
            or _latest_tool_result(tool_runs, "us.read_intraday_trend")
        )
    )
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized_symbol)
        .first()
    )
    context_now = dependencies.now()
    quote_snapshot = (
        None
        if requested_trade_date is not None
        else _latest_tool_result(tool_runs, "us.refresh_quote")
    )
    if not isinstance(quote_snapshot, dict) and isinstance(intraday_summary, dict):
        nested_quote = intraday_summary.get("quote_snapshot")
        quote_snapshot = nested_quote if isinstance(nested_quote, dict) else None
    quote_reader = getattr(dependencies.us_market_service, "get_us_quote_snapshot", None)
    if (
        quote_snapshot is None
        and requested_trade_date is None
        and wants("quote.snapshot")
        and callable(quote_reader)
    ):
        try:
            candidate = quote_reader(db, symbol=normalized_symbol, now=context_now)
            quote_snapshot = candidate if isinstance(candidate, dict) else None
        except (LookupError, ValueError):
            quote_snapshot = None
    daily_rows: list[_ResolvedDailyContextRow] = []
    daily_platform_result = None
    daily_projection: dict[str, Any] = {}
    if needs_daily:
        try:
            daily_platform_result = USDailyOhlcvPlatform(db).read(
                symbol=normalized_symbol,
                bars=bars,
                now=context_now,
                to_date=requested_trade_date_value,
            )
            daily_projection = daily_platform_result.projection
            daily_rows = _resolved_daily_context_rows(
                daily_projection,
                symbol=normalized_symbol,
                limit=daily_limit,
            )
        except (LookupError, ValueError) as exc:
            daily_projection = {"limitations": [str(exc)]}
    selected_daily_provider = daily_projection.get("selected_provider")
    selected_daily_date = daily_projection.get("latest_trade_date")
    latest_daily = next(
        (
            row
            for row in reversed(daily_rows)
            if row.provider == selected_daily_provider
            and row.trade_date.isoformat() == selected_daily_date
        ),
        None,
    )
    profile = (
        None
        if is_index or not needs_profile
        else dependencies.latest_profile(db, normalized_symbol)
    )
    sec_summary: dict[str, Any] | None = None
    financial_contract: dict[str, Any] | None = None
    insider_transactions: dict[str, Any] | None = None
    institutional_holdings: dict[str, Any] | None = None
    sec_warning: str | None = None
    insider_warning: str | None = None
    institutional_warning: str | None = None
    if not is_index and needs_sec:
        try:
            sec_summary = dependencies.us_market_service.get_us_sec_fundamental_summary(
                db=db,
                symbol=normalized_symbol,
            )
        except Exception as exc:
            sec_warning = str(exc)
        try:
            financial_contract = dependencies.us_market_service.get_us_sec_financial_contract(
                db=db,
                symbol=normalized_symbol,
                periods=8,
            )
        except Exception as exc:
            contract_warning = f"US SEC financial contract unavailable: {exc}"
            sec_warning = f"{sec_warning}; {contract_warning}" if sec_warning else contract_warning
    if not is_index and needs_insider:
        try:
            insider_transactions = (
                dependencies.us_market_service.get_us_sec_insider_transactions(
                    db,
                    symbol=normalized_symbol,
                    limit=20,
                )
            )
        except Exception as exc:
            insider_warning = f"US SEC Form 4 contract unavailable: {exc}"
    if not is_index and needs_institutional:
        try:
            candidate = dependencies.us_market_service.get_us_sec_institutional_holdings(
                db,
                symbol=normalized_symbol,
                manager_limit=20,
            )
            institutional_holdings = candidate if isinstance(candidate, dict) else None
        except Exception as exc:
            institutional_warning = f"US SEC Form 13F contract unavailable: {exc}"

    corporate_actions = (
        []
        if is_index or not needs_corporate_actions
        else dependencies.us_market_service.list_us_corporate_actions(
            db=db,
            symbol=normalized_symbol,
            limit=10,
        )
    )
    short_volume_rows = (
        []
        if is_index or not needs_short_volume
        else dependencies.us_market_service.list_us_short_volumes(
            db=db,
            symbol=normalized_symbol,
            limit=10,
        )
    )
    if selection_bounded:
        try:
            gaps = dependencies.scan_us_stock_gaps(
                db,
                normalized_symbol,
                requested_capabilities=requested_capabilities,
            )
        except TypeError:
            gaps = dependencies.scan_us_stock_gaps(db, normalized_symbol)
    else:
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
    if insider_warning:
        warnings.append(insider_warning)
    insider_status = str((insider_transactions or {}).get("status") or "missing")
    if insider_status in {"stale", "partial", "blocked"}:
        warnings.append(
            f"US SEC Form 4 evidence status is {insider_status}; limitations remain visible."
        )
    institutional_status = str((institutional_holdings or {}).get("status") or "missing")
    financial_quality = (
        financial_contract.get("quality")
        if isinstance(financial_contract, dict)
        and isinstance(financial_contract.get("quality"), dict)
        else {}
    )
    if financial_contract and financial_quality.get("decision_usable") is not True:
        issue_codes = [
            str(issue)
            for issue in financial_quality.get("issues") or []
            if str(issue).strip()
        ]
        warnings.append(
            "US SEC financial contract is not decision-usable"
            + (f": {', '.join(issue_codes[:6])}" if issue_codes else ".")
        )
    if requested_trade_date is not None and latest_daily is None:
        requested_missing = "us_daily_price_requested_trade_date"
        if requested_missing not in missing:
            missing.append(requested_missing)
        warnings.append(
            "No US regular-session close is available for requested trade date "
            f"{requested_trade_date}; OMI did not fall back to another date."
        )
    if requested_trade_date is not None and latest_daily is not None:
        if is_us_early_close_day(latest_daily.trade_date):
            warnings.append(
                "US daily close time uses the verified NYSE 13:00 "
                "America/New_York early-close schedule for this trade date."
            )

    if include_intraday and intraday_summary is None:
        try:
            requested_interval = (
                _requested_intraday_interval(market_data_params, default="1m")
                or "1m"
            )
            intraday_summary = dependencies.us_market_service.get_us_intraday_trend(
                symbol=normalized_symbol,
                session_scope=session_scope,
                interval=requested_interval,
                db=db,
                persist_history=False,
            )
        except Exception as exc:
            if "us_intraday_trend" not in missing:
                missing.append("us_intraday_trend")
            warnings.append(f"US intraday trend unavailable: {exc}")

    resolved_market_data: dict[str, Any] = {}
    if isinstance(intraday_summary, dict):
        intraday_summary = dict(intraday_summary)
        resolved_candidate = intraday_summary.pop("_resolved_market_data", None)
        if isinstance(resolved_candidate, dict):
            resolved_market_data = resolved_candidate

    intraday_requested = include_intraday or intraday_summary is not None

    chart: dict[str, Any] = {}
    if needs_chart:
        try:
            chart = dependencies.us_market_service.read_us_daily_ohlcv_chart(
                db=db,
                symbol=normalized_symbol,
                timeframe=timeframe,
                bars=bars,
                to_date=requested_trade_date_value,
            )
            if intraday_requested and session_scope != "regular":
                chart["requested_session_scope"] = session_scope
            if not chart.get("point_count") and "us_ohlc_chart" not in missing:
                missing.append("us_ohlc_chart")
        except Exception as exc:
            missing.append("us_ohlc_chart")
            warnings.append(f"US OHLC chart unavailable: {exc}")

    if daily_projection:
        resolved_market_data["daily_ohlcv"] = daily_projection
    if isinstance(quote_snapshot, dict):
        resolved_market_data["quote_snapshot"] = quote_snapshot

    resolved_research: dict[str, Any] = {}
    research_builder = getattr(
        dependencies.us_market_service,
        "build_us_market_research",
        None,
    )
    if callable(research_builder) and requested_trade_date is None and needs_research:
        try:
            research_candidate = research_builder(
                db,
                symbol=normalized_symbol,
                bars=min(max(bars, 260), 500),
                now=dependencies.now(),
                include_market_coverage=not selection_bounded,
            )
            if isinstance(research_candidate, dict):
                resolved_daily = research_candidate.get("daily_ohlcv")
                if isinstance(resolved_daily, dict) and resolved_daily:
                    resolved_market_data["daily_ohlcv"] = resolved_daily
                indicators = research_candidate.get("technical_indicators")
                structure = research_candidate.get("technical_structure")
                coverage = research_candidate.get("market_coverage")
                if isinstance(indicators, dict):
                    resolved_research["technical_indicators"] = indicators
                if isinstance(structure, dict):
                    resolved_research["technical_structure"] = structure
                if isinstance(coverage, dict):
                    resolved_research["market_coverage"] = coverage
                for warning in research_candidate.get("warnings") or []:
                    warnings.append(str(warning))
        except Exception as exc:
            warnings.append(f"US technical research unavailable: {exc}")

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
        source_refs.append(
            {
                "kind": "us_daily_price",
                "provider": row.provider,
                "source": row.source,
                "symbol": row.symbol,
                "date": row.trade_date.isoformat(),
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

    if daily_rows:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_daily_price"})
    if not is_index and needs_profile:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_company_profile"})
    if not is_index and needs_sec:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_sec_company_fact"})
    if not is_index and needs_insider:
        _append_source_ref_once(
            source_refs,
            {"type": "table", "name": "us_sec_ownership_transaction"},
        )
    if not is_index and needs_institutional:
        _append_source_ref_once(
            source_refs,
            {"type": "table", "name": "us_sec_13f_symbol_quarter"},
        )
        for source_ref in (insider_transactions or {}).get("source_refs") or []:
            if isinstance(source_ref, dict):
                _append_source_ref_once(source_refs, source_ref)
        for source_ref in (institutional_holdings or {}).get("source_refs") or []:
            if isinstance(source_ref, dict):
                _append_source_ref_once(source_refs, source_ref)
    if corporate_actions:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_corporate_action"})
    if short_volume_rows:
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_short_volume_daily"})
    _append_source_ref_once(source_refs, {"type": "derived", "name": "app.us_market.source_health"})
    if intraday_summary:
        _append_source_ref_once(source_refs, {"type": "table", "name": "market_intraday_bar"})
    if isinstance(quote_snapshot, dict):
        _append_source_ref_once(source_refs, {"type": "table", "name": "us_quote_snapshot"})

    us_calendar_status = build_us_calendar_status(now=context_now)
    daily_previous_close_reference = (
        {
            "previous_close": latest_daily.close_price,
            "previous_close_source": latest_daily.source or "us_daily_price",
            "previous_close_trade_date": latest_daily.trade_date.isoformat(),
            "previous_close_provider": latest_daily.provider,
        }
        if latest_daily is not None and latest_daily.close_price is not None
        else None
    )
    temporal_change_reference = (
        {
            **(daily_previous_close_reference or {}),
            "change_reference_price": intraday_summary.get(
                "change_reference_price"
            ),
            "change_reference_type": intraday_summary.get(
                "change_reference_type"
            ),
            "change_reference_trade_date": intraday_summary.get(
                "change_reference_trade_date"
            ),
            "change_reference_source": intraday_summary.get(
                "change_reference_source"
            ),
            "change_reference_provider": intraday_summary.get(
                "change_reference_provider"
            ),
        }
        if isinstance(intraday_summary, dict)
        else daily_previous_close_reference
    )
    resolved_quote = _us_resolved_quote(
        quote_snapshot,
        calendar_status=us_calendar_status,
        instrument_type=instrument_type,
        previous_close_reference=temporal_change_reference,
    )
    intraday_quote = _us_intraday_quote(
        intraday_summary,
        calendar_status=us_calendar_status,
        instrument_type=instrument_type,
    )
    current_price_semantics = (
        (intraday_summary.get("current_observation") or {}).get("price_semantics")
        if isinstance(intraday_summary, dict)
        else None
    )
    selected_resolved_quote = (
        resolved_quote
        if resolved_quote
        and (
            not intraday_quote
            or current_price_semantics == "resolved_quote_last_trade"
        )
        else {}
    )
    quote = selected_resolved_quote or intraday_quote or _us_daily_quote(
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
            "financials": {
                "financial_contract": financial_contract,
                "sec_fundamentals": sec_summary,
                "currency": "USD",
                "source_amount_unit": "USD",
                "normalized_amount_unit": "USD",
                "amount_scale": 1,
                "ratio_unit": "percent",
                "per_share_unit": "USD/share",
            },
            "insider_transactions": insider_transactions,
            "institutional_holdings": institutional_holdings,
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
            "fundamental_available": bool(financial_contract),
            "insider_transaction_rows": len(
                (insider_transactions or {}).get("transactions") or []
            ),
            "institutional_holding_quarters": len(
                (institutional_holdings or {}).get("quarters") or []
            ),
            "institutional_manager_rows": len(
                (institutional_holdings or {}).get("managers") or []
            ),
            "corporate_action_rows": len(corporate_actions),
            "short_volume_rows": len(short_volume_rows),
            "chart_points": chart.get("point_count") if chart else 0,
            "timeframe": timeframe,
            "bars": bars,
            "payload_level": payload_level,
            "requested_provider": None,
            "selected_provider": selected_daily_provider,
            "requested_trade_date": requested_trade_date,
            "intraday": intraday_summary or {},
            "include_intraday": intraday_requested,
            "intraday_available": bool(selected_resolved_quote or intraday_quote),
            "quote_snapshot_available": bool(selected_resolved_quote),
        },
        freshness={
            "price": (
                "historical"
                if requested_trade_date is not None
                and daily_platform_result is not None
                and daily_platform_result.postcondition_satisfied
                else "current"
                if (
                    daily_platform_result is not None
                    and daily_platform_result.postcondition_satisfied
                )
                or selected_resolved_quote
                or intraday_quote
                else "missing"
            ),
            "profile": "current" if profile else "missing",
            "fundamentals": financial_quality.get("freshness") or (
                "current" if financial_contract else "missing"
            ),
            "insider_transactions": insider_status,
            "institutional_holdings": institutional_status,
            "chart": (
                "current"
                if daily_platform_result is not None
                and daily_platform_result.postcondition_satisfied
                else "missing"
            ),
            "intraday": (
                "current"
                if selected_resolved_quote or intraday_quote
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
    envelope["data"]["compact"]["fundamentals"] = {
        "financial_contract": financial_contract,
        "sec_fundamentals": sec_summary,
        "currency": "USD",
        "source_amount_unit": "USD",
        "normalized_amount_unit": "USD",
        "amount_scale": 1,
        "ratio_unit": "percent",
        "per_share_unit": "USD/share",
    }
    envelope["data"]["compact"]["ownership"] = {
        "insider_transactions": insider_transactions,
        "institutional_holdings": institutional_holdings,
        "institutional_evidence_role": "delayed_quarterly_context_only",
    }
    if not is_index:
        envelope["data_limitations"] = list(
            dict.fromkeys(
                [
                    *envelope["data_limitations"],
                    "SEC Form 13F is delayed quarterly disclosure, not real-time institutional flow or a standalone trading signal.",
                    "CUSIP-to-symbol mapping coverage may be partial; unresolved holdings remain excluded from symbol projections and visible in quality metadata.",
                    *([institutional_warning] if institutional_warning else []),
                ]
            )
        )
    envelope["data"]["compact"]["intraday_bars"] = intraday_bars
    if resolved_research:
        envelope["data"]["resolved_research"] = resolved_research
        envelope["data"]["compact"]["technical_indicators"] = (
            resolved_research.get("technical_indicators")
        )
        envelope["data"]["compact"]["technical"] = (
            resolved_research.get("technical_structure")
        )
    if resolved_market_data:
        envelope["data"]["resolved_market_data"] = resolved_market_data
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
