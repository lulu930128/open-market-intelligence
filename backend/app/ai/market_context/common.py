from __future__ import annotations

from datetime import datetime
from typing import Any

from app.ai.market_payload_contract import has_payload_value, slot_envelope


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


def freshness_status(freshness: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = freshness.get(key)
        if isinstance(value, dict):
            status = value.get("status") or value.get("summary")
            if status:
                return str(status)
        elif value is not None:
            return str(value)
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
    if isinstance(value, str):
        return value == "missing"
    if isinstance(value, dict):
        return any(freshness_has_missing(item) for item in value.values())
    if isinstance(value, list):
        return any(freshness_has_missing(item) for item in value)
    return False


def compact_market_slots(
    *,
    target: dict[str, Any],
    quote: dict[str, Any],
    resources: dict[str, Any],
    freshness: dict[str, Any],
    payload_level: str,
) -> dict[str, Any]:
    target_type = str(target.get("type") or "")
    is_index = target_type.endswith("_index") or target_type == "index"
    is_crypto = target_type.startswith("crypto")
    quote_status = freshness_status(freshness, "quote", "price")
    has_quote = has_payload_value(quote)
    include_intraday = resources.get("include_intraday")
    intraday_status = freshness_status(freshness, "intraday")
    if include_intraday is False:
        intraday_slot_status = "not_requested"
    elif resources.get("intraday_available") or intraday_status == "current":
        intraday_slot_status = "ready"
    elif intraday_status == "missing":
        intraday_slot_status = "missing"
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
    return {
        "identity": slot_envelope(
            status="ready" if target else "partial",
            capability="target_identity",
            payload_ref="target",
            payload_level=payload_level,
            priority="core",
        ),
        "quote": slot_envelope(
            status="ready" if has_quote and quote_status != "missing" else "missing",
            capability="quote_snapshot",
            payload_ref="quote",
            payload_level=payload_level,
            priority="core",
        ),
        "intraday": slot_envelope(
            status=intraday_slot_status,
            capability="live_intraday_bars",
            payload_ref="intraday_bars",
            payload_level=payload_level,
            priority="core",
            next_fill="Route through bounded backend refresh/tool policy before exposing as default."
            if intraday_slot_status == "planned"
            else None,
        ),
        "daily_chart": slot_envelope(
            status="ready" if chart_count > 0 else "missing",
            capability="daily_ohlc_chart",
            payload_ref="full.data.chart",
            payload_level=payload_level,
            priority="core",
        ),
        "fundamentals": slot_envelope(
            status="not_applicable" if is_index else "ready" if fundamental_count > 0 else "missing",
            capability="fundamentals",
            payload_ref="resources",
            payload_level=payload_level,
        ),
        "flows_liquidity": slot_envelope(
            status="ready" if flow_count > 0 else "planned",
            capability="flows_and_liquidity",
            payload_ref="resources",
            payload_level=payload_level,
            next_fill="Normalize market-specific flow/liquidity evidence into a shared compact payload.",
        ),
        "derivatives": slot_envelope(
            status="ready" if derivative_count > 0 else "missing" if is_crypto else "planned",
            capability="derivatives_context",
            payload_ref="resources",
            payload_level=payload_level,
            next_fill="Keep derivatives as auxiliary risk context unless the target market has a native derivatives workflow.",
        ),
        "data_quality": slot_envelope(
            status="partial" if freshness_has_missing(freshness) else "ready",
            capability="data_quality_and_freshness",
            payload_ref="freshness_by_domain",
            payload_level=payload_level,
            priority="core",
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
