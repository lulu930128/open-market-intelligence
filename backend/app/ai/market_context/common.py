from __future__ import annotations

from datetime import datetime
from typing import Any

from app.ai.market_payload_contract import has_payload_value, slot_envelope


_FRESHNESS_POSITIVE_STATUSES = {
    "available",
    "current",
    "daily_close",
    "fresh",
    "healthy",
    "live",
    "ok",
    "ready",
}
_FRESHNESS_PROBLEM_SEVERITY = {
    "partial": 1,
    "missing": 2,
    "stale": 3,
    "blocked": 4,
    "failed": 5,
}
_FRESHNESS_STATUS_ALIASES = {
    "degraded": "partial",
    "unknown": "partial",
    "empty": "missing",
    "not_available": "missing",
    "unavailable": "missing",
    "delayed": "stale",
    "expired": "stale",
    "credential_required": "blocked",
    "disabled": "blocked",
    "not_connected": "blocked",
    "provider_not_connected": "blocked",
    "rate_limited": "blocked",
    "error": "failed",
    "exception": "failed",
    "failure": "failed",
    "provider_error": "failed",
    "provider_failure": "failed",
    "timeout": "failed",
}
_FRESHNESS_DIAGNOSTIC_KEYS = {
    "error": "failed",
    "errors": "failed",
    "failure": "failed",
    "failures": "failed",
    "provider_error": "failed",
    "provider_errors": "failed",
    "source_error": "failed",
    "missing": "missing",
}


def append_source_ref_once(source_refs: list[dict[str, Any]], ref: dict[str, Any]) -> None:
    ref_key = ref.get("name") or ref.get("kind")
    if any((item.get("name") or item.get("kind")) == ref_key for item in source_refs):
        return
    source_refs.append(ref)


def latest_timestamp_from_rows(rows: list[Any], fields: tuple[str, ...]) -> str | None:
    values: list[datetime] = []
    for row in rows:
        for field in fields:
            value = getattr(row, field, None)
            if isinstance(value, datetime):
                values.append(value)
    if not values:
        return None
    return max(values).isoformat()


def _normalized_freshness_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower().replace("-", "_").replace(" ", "_")
    if not token:
        return None
    return _FRESHNESS_STATUS_ALIASES.get(token, token)


def _worst_freshness_status(statuses: list[str]) -> str | None:
    problem_statuses = [status for status in statuses if status in _FRESHNESS_PROBLEM_SEVERITY]
    if not problem_statuses:
        return None
    return max(problem_statuses, key=lambda status: _FRESHNESS_PROBLEM_SEVERITY[status])


def freshness_problem_status(value: Any) -> str | None:
    """Return the most severe consumer-visible freshness problem in a payload."""

    if isinstance(value, str):
        token = _normalized_freshness_token(value)
        return token if token in _FRESHNESS_PROBLEM_SEVERITY else None
    if isinstance(value, list):
        return _worst_freshness_status(
            [status for item in value if (status := freshness_problem_status(item))]
        )
    if not isinstance(value, dict):
        return None

    statuses: list[str] = []
    if value.get("is_stale") is True:
        statuses.append("stale")
    if value.get("is_blocked") is True or value.get("blocked") is True:
        statuses.append("blocked")

    for key, item in value.items():
        normalized_key = str(key).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized_key in _FRESHNESS_DIAGNOSTIC_KEYS and has_payload_value(item):
            statuses.append(_FRESHNESS_DIAGNOSTIC_KEYS[normalized_key])
        key_status = _normalized_freshness_token(normalized_key)
        if key_status in _FRESHNESS_PROBLEM_SEVERITY and has_payload_value(item):
            statuses.append(key_status)
        nested_status = freshness_problem_status(item)
        if nested_status:
            statuses.append(nested_status)
    return _worst_freshness_status(statuses)


def freshness_effective_status(value: Any) -> str | None:
    problem_status = freshness_problem_status(value)
    if problem_status:
        return problem_status
    if isinstance(value, str):
        token = _normalized_freshness_token(value)
        if token in _FRESHNESS_POSITIVE_STATUSES or token in {"not_applicable", "not_requested"}:
            return token
        return "partial" if token else None
    if isinstance(value, list):
        positive = [freshness_effective_status(item) for item in value]
        positive = [status for status in positive if status]
        if not positive:
            return None
        return "current" if any(status in _FRESHNESS_POSITIVE_STATUSES for status in positive) else positive[0]
    if isinstance(value, dict):
        for key in ("status", "state", "health", "summary"):
            status = freshness_effective_status(value.get(key))
            if status:
                return status
        if value.get("is_current") is True:
            return "current"
        if value.get("is_current") is False:
            return "partial"
    return None


def freshness_status(freshness: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        status = freshness_effective_status(freshness.get(key))
        if status:
            return status
    return None


def market_resource_count(resources: dict[str, Any], *keys: str) -> int:
    total = 0
    for key in keys:
        value = resources.get(key)
        if isinstance(value, bool):
            total += 1 if value else 0
        elif isinstance(value, int):
            total += max(0, value)
        elif isinstance(value, dict):
            total += sum(item for item in value.values() if isinstance(item, int) and item > 0)
    return total


def freshness_has_missing(value: Any) -> bool:
    """Compatibility name: true for any consumer-visible freshness problem."""

    return freshness_problem_status(value) is not None


def _payload_slot_status(*, available: bool, freshness_value: Any) -> str:
    status = freshness_effective_status(freshness_value)
    if status in _FRESHNESS_PROBLEM_SEVERITY:
        return status
    if not available:
        return "missing"
    return "ready" if status in _FRESHNESS_POSITIVE_STATUSES or status is None else "partial"


def _slot_diagnostics(status: str, capability: str) -> dict[str, list[str]]:
    diagnostics: dict[str, list[str]] = {}
    if status in {"missing", "blocked", "failed"}:
        diagnostics["missing"] = [capability]
    if status in {"partial", "stale", "blocked", "failed"}:
        diagnostics["warnings"] = [f"freshness_status={status}"]
    return diagnostics


def compact_market_slots(
    *,
    target: dict[str, Any],
    quote: dict[str, Any],
    resources: dict[str, Any],
    freshness: dict[str, Any],
    payload_level: str,
) -> dict[str, Any]:
    target_type = str(target.get("type") or "")
    is_index = (
        target_type.endswith("_index")
        or target_type == "index"
        or target.get("instrument_type") == "index"
    )
    is_crypto = target_type.startswith("crypto")
    quote_freshness = freshness.get("quote", freshness.get("price"))
    has_quote = has_payload_value(quote)
    quote_slot_status = _payload_slot_status(
        available=has_quote,
        freshness_value=quote_freshness,
    )
    include_intraday = resources.get("include_intraday")
    intraday_freshness = freshness.get("intraday")
    intraday_status = freshness_effective_status(intraday_freshness)
    if include_intraday is False:
        intraday_slot_status = "not_requested"
    elif intraday_status in _FRESHNESS_PROBLEM_SEVERITY:
        intraday_slot_status = intraday_status
    elif resources.get("intraday_available") or intraday_status in _FRESHNESS_POSITIVE_STATUSES:
        intraday_slot_status = "ready" if intraday_status in _FRESHNESS_POSITIVE_STATUSES else "partial"
    else:
        intraday_slot_status = "planned"
    chart_count = market_resource_count(resources, "chart_points", "daily_rows", "ohlcv_rows")
    fundamental_count = market_resource_count(
        resources,
        "profile_available",
        "fundamental_available",
        "fundamental_rows",
        "sec_metric_count",
        "market_cap_rows",
    )
    flow_count = market_resource_count(
        resources,
        "investor_trade_rows",
        "short_volume_rows",
        "order_book_rows",
        "spread_rows",
    )
    derivative_count = market_resource_count(
        resources,
        "derivatives_rows",
        "long_short_ratio",
        "liquidation_heatmap",
    )
    chart_status = _payload_slot_status(
        available=chart_count > 0,
        freshness_value=freshness.get("daily", freshness.get("chart", freshness.get("ohlcv"))),
    )
    fundamental_status = _payload_slot_status(
        available=fundamental_count > 0,
        freshness_value=freshness.get("fundamentals", freshness.get("fundamental", freshness.get("profile"))),
    )
    flow_status = _payload_slot_status(
        available=flow_count > 0,
        freshness_value=freshness.get(
            "flows",
            freshness.get("investor_trading", freshness.get("order_book")),
        ),
    )
    derivative_status = _payload_slot_status(
        available=derivative_count > 0,
        freshness_value=freshness.get("derivatives"),
    )
    freshness_problem = freshness_problem_status(freshness)
    if freshness_problem in {"failed", "blocked", "stale"}:
        data_quality_status = freshness_problem
    elif freshness_problem or not has_payload_value(freshness):
        data_quality_status = "partial"
    else:
        data_quality_status = "ready"
    return {
        "identity": slot_envelope(
            status="ready" if target else "partial",
            capability="target_identity",
            payload_ref="target",
            payload_level=payload_level,
            priority="core",
        ),
        "quote": slot_envelope(
            status=quote_slot_status,
            capability="quote_snapshot",
            payload_ref="quote",
            payload_level=payload_level,
            priority="core",
            **_slot_diagnostics(quote_slot_status, "quote_snapshot"),
        ),
        "intraday": slot_envelope(
            status=intraday_slot_status,
            capability="live_intraday_bars",
            payload_ref="intraday_bars",
            payload_level=payload_level,
            priority="core",
            **_slot_diagnostics(intraday_slot_status, "live_intraday_bars"),
            next_fill="Route through bounded backend refresh/tool policy before exposing as default."
            if intraday_slot_status == "planned"
            else None,
        ),
        "daily_chart": slot_envelope(
            status=chart_status,
            capability="daily_ohlc_chart",
            payload_ref="full.data.chart",
            payload_level=payload_level,
            priority="core",
            **_slot_diagnostics(chart_status, "daily_ohlc_chart"),
        ),
        "fundamentals": slot_envelope(
            status="not_applicable" if is_index else fundamental_status,
            capability="fundamentals",
            payload_ref="resources",
            payload_level=payload_level,
            **({} if is_index else _slot_diagnostics(fundamental_status, "fundamentals")),
        ),
        "flows_liquidity": slot_envelope(
            status="not_applicable"
            if is_index
            else flow_status
            if flow_count > 0 or flow_status in _FRESHNESS_PROBLEM_SEVERITY
            else "planned",
            capability="flows_and_liquidity",
            payload_ref="resources",
            payload_level=payload_level,
            **(
                {}
                if is_index
                else _slot_diagnostics(
                    flow_status
                    if flow_count > 0 or flow_status in _FRESHNESS_PROBLEM_SEVERITY
                    else "planned",
                    "flows_and_liquidity",
                )
            ),
            next_fill=None
            if is_index
            else "Normalize market-specific flow/liquidity evidence into a shared compact payload.",
        ),
        "derivatives": slot_envelope(
            status=derivative_status
            if derivative_count > 0 or derivative_status in _FRESHNESS_PROBLEM_SEVERITY
            else "missing"
            if is_crypto
            else "planned",
            capability="derivatives_context",
            payload_ref="resources",
            payload_level=payload_level,
            **_slot_diagnostics(
                derivative_status
                if derivative_count > 0 or derivative_status in _FRESHNESS_PROBLEM_SEVERITY
                else "missing"
                if is_crypto
                else "planned",
                "derivatives_context",
            ),
            next_fill="Keep derivatives as auxiliary risk context unless the target market has a native derivatives workflow.",
        ),
        "data_quality": slot_envelope(
            status=data_quality_status,
            capability="data_quality_and_freshness",
            payload_ref="freshness_by_domain",
            payload_level=payload_level,
            priority="core",
            **_slot_diagnostics(data_quality_status, "data_quality_and_freshness"),
        ),
    }

def compact_market_context(
    *,
    kind: str,
    target: dict[str, Any],
    quote: dict[str, Any] | None,
    resources: dict[str, Any],
    freshness: dict[str, Any],
    payload_level: str = "compact",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "version": "market_compact_evidence.v1",
        "payload_level": payload_level,
        "target": target,
        "quote": quote or {},
        "resources": resources,
        "freshness_by_domain": freshness,
        "slots": compact_market_slots(
            target=target,
            quote=quote or {},
            resources=resources,
            freshness=freshness,
            payload_level=payload_level,
        ),
    }
