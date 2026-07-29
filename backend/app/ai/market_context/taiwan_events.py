from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Mapping


STOCK_EVENT_CAPABILITIES = frozenset(
    {
        "events.upcoming",
        "events.history",
        "regulation.disposition",
        "regulation.trading_restrictions",
    }
)

_LIMITED_CACHE_STATUSES = frozenset({"degraded", "stale"})
_MISSING_CACHE_STATUSES = frozenset({"missing", "unavailable", "error"})


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _capability_parameters(
    market_data_params: Mapping[str, Any],
    capability_id: str,
) -> dict[str, Any]:
    values = market_data_params.get("capability_parameters")
    if not isinstance(values, Mapping):
        return {}
    selected = values.get(capability_id)
    return dict(selected) if isinstance(selected, Mapping) else {}


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _payload_status(cache_status: Any) -> str:
    normalized = str(cache_status or "missing").strip().lower()
    if normalized == "current":
        return "ready"
    if normalized in _LIMITED_CACHE_STATUSES:
        return "partial"
    return "missing"


def _freshness(
    *,
    capability_id: str,
    cache_status: Any,
    fetched_at: Any,
    event_time: Any,
    reason: Any = None,
) -> dict[str, Any]:
    normalized = str(cache_status or "missing").strip().lower()
    return {
        "status": normalized,
        "dataset": capability_id,
        "is_current": normalized == "current",
        "latest": _json_value(event_time),
        "fetched_at": _json_value(fetched_at),
        "event_time_basis": (
            "official_event_date"
            if capability_id.startswith("events.")
            else "official_disposition_effective_date"
        ),
        "refresh_recommended": normalized in _MISSING_CACHE_STATUSES,
        "reason": str(reason).strip() if reason else None,
    }


def _slot(
    *,
    capability_id: str,
    payload: Mapping[str, Any],
    freshness: Mapping[str, Any],
) -> dict[str, Any]:
    status = str(payload.get("status") or "missing")
    return {
        "status": status,
        "availability": (
            "available"
            if status == "ready"
            else "partial"
            if status == "partial"
            else "missing"
        ),
        "freshness": dict(freshness),
        "usability": (
            "usable"
            if status == "ready"
            else "limited"
            if status == "partial"
            else "blocked"
        ),
        "capability": capability_id,
    }


def _event_payload(
    *,
    kind: str,
    result: Mapping[str, Any],
    requested_window: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cache_status = str(result.get("cache_status") or "missing").strip().lower()
    rows = [
        _json_value(item)
        for item in result.get("results") or []
        if isinstance(item, Mapping)
    ]
    event_dates = [
        row.get("start_date")
        for row in rows
        if isinstance(row, Mapping) and row.get("start_date")
    ]
    warning = str(result.get("warning") or "").strip() or None
    payload = {
        "kind": kind,
        "status": _payload_status(cache_status),
        "stock_id": str(result.get("stock_id") or "").strip() or None,
        "as_of": _json_value(result.get("checked_at")),
        **requested_window,
        "result_count": len(rows),
        "total_count": result.get("total_count", len(rows)),
        "events": rows,
        "source": "taiwan_corporate_event_cache",
        "cache_policy": "cache_only",
        "cache_status": cache_status,
        "cache_fetched_at": _json_value(result.get("cache_fetched_at")),
        "empty_result_is_valid": cache_status == "current" and not rows,
        "missing": (
            ["taiwan_corporate_event_cache"]
            if cache_status in _MISSING_CACHE_STATUSES
            else []
        ),
        "warnings": [warning] if warning else [],
    }
    event_time = (
        max(event_dates)
        if kind == "tw_stock_event_history" and event_dates
        else min(event_dates)
        if event_dates
        else result.get("checked_at")
    )
    freshness = _freshness(
        capability_id=(
            "events.history"
            if kind == "tw_stock_event_history"
            else "events.upcoming"
        ),
        cache_status=cache_status,
        fetched_at=result.get("cache_fetched_at"),
        event_time=event_time,
        reason=warning,
    )
    return payload, freshness


def _regulation_payloads(
    result: Mapping[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    cache_status = str(result.get("cache_status") or "missing").strip().lower()
    status = _payload_status(cache_status)
    warning = str(result.get("warning") or "").strip() or None
    public_result = _json_value(result)
    disposition = {
        "kind": "tw_stock_disposition",
        "status": status,
        "stock_id": str(result.get("stock_id") or "").strip() or None,
        "as_of": _json_value(result.get("checked_at")),
        "is_disposition": result.get("is_disposition"),
        "is_active": result.get("is_active"),
        "disposition_status": result.get("status"),
        "announced_date": _json_value(result.get("announced_date")),
        "start_date": _json_value(result.get("start_date")),
        "end_date": _json_value(result.get("end_date")),
        "reason": result.get("reason"),
        "measure": result.get("measure"),
        "matching_interval_minutes": result.get("matching_interval_minutes"),
        "requires_full_precollection": result.get(
            "requires_full_precollection"
        ),
        "margin_trading_suspended": result.get("margin_trading_suspended"),
        "provider": result.get("provider"),
        "source": result.get("source_name")
        or "taiwan_disposition_cache",
        "source_url": result.get("source_url"),
        "cache_policy": "cache_only",
        "cache_status": cache_status,
        "cache_fetched_at": _json_value(result.get("cache_fetched_at")),
        "raw": public_result,
        "missing": (
            ["taiwan_disposition_cache"]
            if cache_status in _MISSING_CACHE_STATUSES
            else []
        ),
        "warnings": [warning] if warning else [],
    }
    trustworthy = cache_status not in _MISSING_CACHE_STATUSES
    active = result.get("is_active") is True
    restrictions = {
        "kind": "tw_stock_trading_restrictions",
        "status": status,
        "stock_id": disposition["stock_id"],
        "as_of": disposition["as_of"],
        "trading_mode": (
            "disposition_batch_auction"
            if trustworthy and active
            else "continuous"
            if trustworthy
            else "unknown"
        ),
        "analysis_basis": (
            "effective_matches"
            if trustworthy and active
            else "time_bars"
            if trustworthy
            else "unknown"
        ),
        "matching_interval_minutes": (
            result.get("matching_interval_minutes")
            if trustworthy and active
            else None
        ),
        "requires_full_precollection": (
            result.get("requires_full_precollection")
            if trustworthy and active
            else False
            if trustworthy
            else None
        ),
        "margin_trading_suspended": (
            result.get("margin_trading_suspended")
            if trustworthy and active
            else False
            if trustworthy
            else None
        ),
        "effective_start_date": (
            _json_value(result.get("start_date")) if active else None
        ),
        "effective_end_date": (
            _json_value(result.get("end_date")) if active else None
        ),
        "upcoming_disposition": bool(
            trustworthy and result.get("status") == "upcoming"
        ),
        "source": disposition["source"],
        "provider": disposition["provider"],
        "cache_policy": "cache_only",
        "cache_status": cache_status,
        "missing": list(disposition["missing"]),
        "warnings": list(disposition["warnings"]),
    }
    event_time = (
        result.get("start_date")
        or result.get("announced_date")
        or result.get("checked_at")
    )
    disposition_freshness = _freshness(
        capability_id="regulation.disposition",
        cache_status=cache_status,
        fetched_at=result.get("cache_fetched_at"),
        event_time=event_time,
        reason=warning,
    )
    restrictions_freshness = {
        **disposition_freshness,
        "dataset": "regulation.trading_restrictions",
    }
    return (
        disposition,
        restrictions,
        disposition_freshness,
        restrictions_freshness,
    )


def build_tw_stock_event_context(
    *,
    stock_id: str,
    market: str | None,
    market_data_params: Mapping[str, Any] | None,
    now: datetime,
    get_event_summary: Callable[..., dict[str, Any]],
    get_event_history: Callable[..., dict[str, Any]],
    get_disposition_status: Callable[..., dict[str, Any]],
    disposition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    params = dict(market_data_params or {})
    requested = {
        str(value)
        for value in params.get("requested_capabilities") or []
        if str(value) in STOCK_EVENT_CAPABILITIES
    }
    data: dict[str, Any] = {}
    freshness_by_capability: dict[str, Any] = {}
    slots: dict[str, Any] = {}
    missing: list[str] = []
    warnings: list[str] = []
    source_refs: list[dict[str, str]] = []

    if "events.upcoming" in requested:
        capability_params = _capability_parameters(params, "events.upcoming")
        days = _bounded_int(
            capability_params.get("days"),
            default=30,
            minimum=1,
            maximum=365,
        )
        limit = _bounded_int(
            capability_params.get("limit"),
            default=10,
            minimum=1,
            maximum=50,
        )
        result = get_event_summary(
            stock_id,
            market=market,
            reminder_days=days,
            max_results=limit,
            now=now,
        )
        payload, freshness = _event_payload(
            kind="tw_stock_event_upcoming",
            result=result,
            requested_window={"days": days, "limit": limit},
        )
        data["events.upcoming"] = payload
        freshness_by_capability["events.upcoming"] = freshness
        slots["events_upcoming"] = _slot(
            capability_id="events.upcoming",
            payload=payload,
            freshness=freshness,
        )
        missing.extend(payload["missing"])
        warnings.extend(payload["warnings"])
        source_refs.append(
            {"type": "external_or_cache", "name": "taiwan_corporate_events"}
        )

    if "events.history" in requested:
        capability_params = _capability_parameters(params, "events.history")
        years = _bounded_int(
            capability_params.get("years"),
            default=5,
            minimum=1,
            maximum=10,
        )
        limit = _bounded_int(
            capability_params.get("limit"),
            default=20,
            minimum=1,
            maximum=200,
        )
        result = get_event_history(
            stock_id,
            market=market,
            years=years,
            max_results=limit,
            now=now,
        )
        payload, freshness = _event_payload(
            kind="tw_stock_event_history",
            result=result,
            requested_window={"years": years, "limit": limit},
        )
        data["events.history"] = payload
        freshness_by_capability["events.history"] = freshness
        slots["events_history"] = _slot(
            capability_id="events.history",
            payload=payload,
            freshness=freshness,
        )
        missing.extend(payload["missing"])
        warnings.extend(payload["warnings"])
        source_refs.append(
            {
                "type": "external_or_cache",
                "name": "taiwan_corporate_event_history",
            }
        )

    regulation_requested = bool(
        requested
        & {"regulation.disposition", "regulation.trading_restrictions"}
    )
    if regulation_requested:
        result = (
            dict(disposition)
            if isinstance(disposition, Mapping)
            else get_disposition_status(
                stock_id,
                market=market,
                now=now,
            )
        )
        (
            disposition_payload,
            restrictions_payload,
            disposition_freshness,
            restrictions_freshness,
        ) = _regulation_payloads(result)
        if "regulation.disposition" in requested:
            data["regulation.disposition"] = disposition_payload
            freshness_by_capability[
                "regulation.disposition"
            ] = disposition_freshness
            slots["regulation_disposition"] = _slot(
                capability_id="regulation.disposition",
                payload=disposition_payload,
                freshness=disposition_freshness,
            )
        if "regulation.trading_restrictions" in requested:
            data[
                "regulation.trading_restrictions"
            ] = restrictions_payload
            freshness_by_capability[
                "regulation.trading_restrictions"
            ] = restrictions_freshness
            slots["regulation_trading_restrictions"] = _slot(
                capability_id="regulation.trading_restrictions",
                payload=restrictions_payload,
                freshness=restrictions_freshness,
            )
        missing.extend(disposition_payload["missing"])
        warnings.extend(disposition_payload["warnings"])
        source_refs.append(
            {"type": "external_or_cache", "name": "taiwan_disposition"}
        )

    return {
        "kind": "tw_stock_event_context",
        "status": (
            "not_requested"
            if not requested
            else "missing"
            if data
            and all(
                str(value.get("status")) == "missing"
                for value in data.values()
                if isinstance(value, Mapping)
            )
            else "partial"
            if any(
                str(value.get("status")) == "partial"
                for value in data.values()
                if isinstance(value, Mapping)
            )
            else "ready"
        ),
        "data": data,
        "freshness_by_capability": freshness_by_capability,
        "slots": slots,
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
