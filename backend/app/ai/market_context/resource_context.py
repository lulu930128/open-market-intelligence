from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import bounded_int_param, payload_level, slot_envelope
from app.resource_market.contract import normalize_resource_symbol


@dataclass(frozen=True)
class ResourceContextDependencies:
    resource_service: Any
    build_resource_source_health: Any
    now: Any


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _json_value(getattr(row, field, None)) for field in fields}


def _health_status(source_health: dict[str, Any], resource: str) -> str:
    entries = source_health.get("entries") if isinstance(source_health, dict) else []
    statuses = [
        str(entry.get("status") or "unknown")
        for entry in entries or []
        if isinstance(entry, dict) and entry.get("resource") == resource
    ]
    if any(status == "current" for status in statuses):
        return "ready"
    if any(status in {"stale", "delayed"} for status in statuses):
        return "stale"
    if any(status in {"error", "disabled", "blocked"} for status in statuses):
        return "blocked"
    return "missing"


def read_resource_asset_context(
    db: Session,
    *,
    symbol: str,
    market_data_params: dict[str, Any] | None,
    dependencies: ResourceContextDependencies,
) -> dict[str, Any]:
    normalized_symbol = normalize_resource_symbol(symbol)
    instruments = dependencies.resource_service.list_supported_resource_instruments(
        symbol=normalized_symbol
    )
    if not instruments:
        raise ValueError(f"Unsupported resource asset target.id: {symbol}.")

    instrument = instruments[0]
    requested_interval = str((market_data_params or {}).get("interval") or "1d").strip()
    bar_limit = bounded_int_param(
        market_data_params,
        ("bars", "limit", "ohlcv_limit"),
        default=120,
        minimum=1,
        maximum=500,
    )
    level = payload_level(market_data_params)
    quotes = dependencies.resource_service.list_latest_resource_quotes(
        db,
        symbols=normalized_symbol,
        limit=1,
    )
    bars = dependencies.resource_service.list_resource_ohlcv_bars(
        db,
        symbols=normalized_symbol,
        interval=requested_interval,
        limit=bar_limit,
    )
    source_health = dependencies.build_resource_source_health(
        db,
        symbols=normalized_symbol,
        intervals=requested_interval,
        include_events=True,
        max_entries=20,
    )
    quote = quotes[0] if quotes else None
    quote_payload = (
        dependencies.resource_service.resource_quote_to_public_dict(quote)
        if quote is not None
        else {}
    )
    chart = [
        dependencies.resource_service.resource_ohlcv_bar_to_public_dict(row)
        for row in reversed(bars)
    ]
    as_of_candidates = [
        getattr(quote, "event_time", None),
        *(getattr(row, "bar_time", None) for row in bars[:1]),
    ]
    as_of = max(
        (value for value in as_of_candidates if isinstance(value, datetime)),
        default=None,
    )

    quote_status = _health_status(source_health, "quote")
    chart_status = _health_status(source_health, "ohlcv")
    missing: list[str] = []
    warnings = [
        "Resource market data is watch-only and must not be used for order execution.",
        "Yahoo chart resource data is delayed/best-effort; freshness and provider status remain authoritative.",
    ]
    if not quote_payload:
        missing.append("resource_quote")
    if not chart:
        missing.append(f"resource_ohlcv.{requested_interval}")
    health_summary = source_health.get("summary") if isinstance(source_health, dict) else {}
    if quote_status == "stale" or chart_status == "stale":
        warnings.append("One or more resource cache entries are stale or delayed.")
    if quote_status == "blocked" or chart_status == "blocked":
        warnings.append("One or more resource provider entries are blocked or unavailable.")

    target = {
        "type": "resource_asset",
        "id": normalized_symbol,
        "label": instrument.get("display_name") or instrument.get("name") or normalized_symbol,
        "market": "resource",
    }
    slots = {
        "identity": slot_envelope(
            status="ready",
            capability="resource_instrument_identity",
            payload_ref="data.instrument",
            payload_level=level,
            priority="core",
        ),
        "quote": slot_envelope(
            status=quote_status,
            capability="resource_quote_snapshot",
            payload_ref="data.quote",
            payload_level=level,
            priority="core",
            as_of=_json_value(getattr(quote, "event_time", None)),
            missing=[] if quote_payload else ["resource_quote"],
        ),
        "daily_chart": slot_envelope(
            status=chart_status,
            capability="resource_ohlcv_chart",
            payload_ref="data.chart",
            payload_level=level,
            priority="core",
            as_of=_json_value(getattr(bars[0], "bar_time", None)) if bars else None,
            missing=[] if chart else [f"resource_ohlcv.{requested_interval}"],
        ),
        "trade_execution": slot_envelope(
            status="not_applicable",
            capability="trade_execution",
            payload_level=level,
            warnings=["Resource assets are research/watch-only in OMI."],
        ),
        "data_quality": slot_envelope(
            status=(
                "stale"
                if quote_status == "stale" or chart_status == "stale"
                else "partial"
                if missing or quote_status == "blocked" or chart_status == "blocked"
                else "ready"
            ),
            capability="resource_source_health",
            payload_ref="data.source_health",
            payload_level=level,
            priority="core",
            missing=missing,
            warnings=warnings,
        ),
    }
    envelope = {
        "kind": "resource_asset_context",
        "generated_at": dependencies.now(),
        "as_of": _json_value(as_of),
        "scope": {"target": target},
        "data": {
            "instrument": instrument,
            "quote": quote_payload,
            "chart": chart,
            "interval": requested_interval,
            "bar_limit": bar_limit,
            "source_health": source_health,
            "compact": {
                "kind": "resource_asset_compact_evidence",
                "version": "market_compact_evidence.v1",
                "payload_level": level,
                "target": target,
                "quote": quote_payload,
                "resources": {
                    "instrument": instrument,
                    "interval": requested_interval,
                    "ohlcv_rows": len(chart),
                    "watch_only": True,
                    "provider_status": instrument.get("provider_status"),
                },
                "freshness_by_domain": {
                    "quote": quote_status,
                    "chart": chart_status,
                    "summary": health_summary,
                },
                "slots": slots,
            },
            "slots": slots,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": [
            {"type": "table", "name": "resource_market_instrument"},
            {"type": "table", "name": "resource_quote_snapshot"},
            {"type": "table", "name": "resource_ohlcv_bar"},
            {
                "type": "external_or_cache",
                "name": "yahoo_chart",
                "provider": instrument.get("provider"),
            },
        ],
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=envelope["as_of"],
        source_refs=envelope["source_refs"],
        missing=envelope["missing"],
        warnings=envelope["warnings"],
        freshness={
            "is_current": quote_status == "ready" and chart_status == "ready",
            "missing": envelope["missing"],
        },
    )
    return envelope
