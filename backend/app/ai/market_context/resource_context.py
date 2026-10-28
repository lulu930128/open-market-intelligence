from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import bounded_int_param, payload_level, slot_envelope
from app.resource_market.contract import normalize_resource_symbol
from app.resource_market.sources import normalize_resource_interval


@dataclass(frozen=True)
class ResourceContextDependencies:
    resource_service: Any
    build_resource_source_health: Any
    now: Any


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _event_clock(value: datetime | None) -> datetime | None:
    # Resource persistence stores UTC; SQLite returns timezone-naive datetimes.
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)) if value else None


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
    params = market_data_params or {}
    requested_interval = normalize_resource_interval(str(params.get("interval") or "1d"))
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
    selected = set(params.get("requested_capabilities") or [])
    limits = params.get("capability_limits") or {}
    intraday_interval = normalize_resource_interval(str(params.get("intraday_interval") or (
        requested_interval if requested_interval in {"1m", "5m", "15m", "30m", "1h"} else "1m"
    )))
    if "intraday.bars" in selected and intraday_interval not in {"1m", "5m", "15m", "30m", "1h"}:
        raise ValueError("Resource intraday.bars requires an intraday interval.")
    interval_limits = {}
    for capability, interval in (("daily.ohlcv", "1d"), ("intraday.bars", intraday_interval)):
        if capability in selected:
            interval_limits[interval] = bounded_int_param(
                limits, (capability,), default=bar_limit, minimum=1, maximum=500,
            )
    if not selected:
        interval_limits[requested_interval] = bar_limit
    bars_by_interval = {
        interval: dependencies.resource_service.list_resource_ohlcv_bars(
            db, symbols=normalized_symbol, interval=interval, limit=limit,
        ) for interval, limit in interval_limits.items()
    }
    bars_by_interval = {
        interval: sorted(rows, key=lambda row: _event_clock(row.bar_time), reverse=True)
        for interval, rows in bars_by_interval.items()
    }
    bars = bars_by_interval.get(requested_interval, [])
    source_health = dependencies.build_resource_source_health(
        db,
        symbols=normalized_symbol,
        intervals=",".join(interval_limits) or requested_interval,
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
    def interval_payload(interval):
        rows = bars_by_interval.get(interval, [])
        health = {**source_health, "entries": [entry for entry in source_health.get("entries", [])
                  if entry.get("target") == f"{normalized_symbol}:{interval}"]}
        status = _health_status(health, "ohlcv")
        if instrument.get("root_folder") == "commodity" and any(entry.get("ok") for entry in health["entries"]):
            status = "partial"
        return {
            "interval": interval, "sort_order": "asc",
            "bars": [dependencies.resource_service.resource_ohlcv_bar_to_public_dict(row) for row in reversed(rows)],
            "point_count": len(rows), "returned_point_count": len(rows),
            "as_of": _json_value(_event_clock(rows[0].bar_time)) if rows else None,
            "event_time": _json_value(_event_clock(rows[0].bar_time)) if rows else None,
            "provider": instrument.get("provider"), "source": instrument.get("provider"),
            "freshness": {"status": status if rows else "missing"},
            "decision_usable": False, "limitations": ["watch_only", "best_effort_delayed"],
        }

    daily_chart = interval_payload("1d")
    intraday_chart = interval_payload(intraday_interval)
    as_of_candidates = [
        _event_clock(getattr(quote, "event_time", None)),
        *(_event_clock(rows[0].bar_time) for rows in bars_by_interval.values() if rows),
    ]
    as_of = max(
        (value for value in as_of_candidates if isinstance(value, datetime)),
        default=None,
    )

    quote_status = _health_status(source_health, "quote")
    chart_status = _health_status(source_health, "ohlcv")
    if instrument.get("root_folder") == "commodity":
        quote_health = next((entry for entry in source_health.get("entries", [])
                             if entry.get("resource") == "quote"), {})
        # Provider delay is not cache staleness. Keep the two axes separate.
        quote_status = "partial" if quote_health.get("ok") else quote_status
        chart_statuses = [interval_payload(interval)["freshness"]["status"]
                          for interval in bars_by_interval]
        chart_status = ("stale" if "stale" in chart_statuses else "blocked" if "blocked" in chart_statuses
                        else "missing" if "missing" in chart_statuses else "partial")
        if quote_payload:
            for field in ("event_time", "fetched_at"):
                value = quote_payload.get(field)
                if isinstance(value, datetime):
                    quote_payload[field] = (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
            quote_payload.update({
                "status": (quote_health.get("freshness") or {}).get("status", "unknown"),
                "freshness": quote_health.get("freshness") or {},
                "source_status": {
                    "owner": "resource_market.source_health",
                    "provider_status": instrument.get("provider_status"),
                    "freshness_status": (quote_health.get("freshness") or {}).get("status", "unknown"),
                    "decision_usable": False,
                },
                "source": instrument.get("provider"),
                "quote_time": quote_payload.get("event_time"),
                "quote_time_basis": "source_event_time",
                "market_status": (quote_health.get("freshness") or {}).get("session_status", "unknown"),
                "is_live": False, "is_realtime": False, "decision_usable": False,
                "price_decision_usable": False,
                "volume_unit": None, "volume_status": "unit_unverified",
                "volume_decision_usable": False,
                "limitations": ["watch_only", "front_month", "best_effort_delayed",
                                "volume_unit_missing", "commodity_holiday_and_halt_calendar_unverified"],
            })
    missing: list[str] = []
    warnings = [
        "Resource market data is watch-only and must not be used for order execution.",
        "Yahoo chart resource data is delayed/best-effort; freshness and provider status remain authoritative.",
    ]
    if not quote_payload:
        missing.append("resource_quote")
    for interval, rows in bars_by_interval.items():
        if not rows:
            missing.append(f"resource_ohlcv.{interval}")
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
            status=daily_chart["freshness"]["status"], capability="resource_ohlcv_chart",
            payload_ref="data.resolved_market_data.daily_ohlcv", payload_level=level, priority="core",
            as_of=daily_chart["as_of"], missing=[] if daily_chart["bars"] else ["resource_ohlcv.1d"],
        ),
        "intraday": slot_envelope(
            status=intraday_chart["freshness"]["status"], capability="resource_intraday_bars",
            payload_ref="data.resolved_market_data.intraday_bars", payload_level=level, priority="core",
            as_of=intraday_chart["as_of"], missing=[] if intraday_chart["bars"] else [f"resource_ohlcv.{intraday_interval}"],
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
            "resolved_market_data": {"daily_ohlcv": daily_chart, "intraday_bars": intraday_chart},
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
                "freshness_by_capability": {
                    capability: {**payload["freshness"], "latest": payload["as_of"],
                                 "source": "resource_interval_health"}
                    for capability, interval, payload in (
                        ("daily.ohlcv", "1d", daily_chart),
                        ("intraday.bars", intraday_interval, intraday_chart),
                    ) if interval in bars_by_interval
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
