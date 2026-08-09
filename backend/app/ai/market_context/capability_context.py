from __future__ import annotations

from datetime import datetime
from typing import Any

from app.ai import capability_contract
from app.ai.evidence_passport import build_evidence_passport


CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "id": "tw_full_market_breadth",
        "market": "tw",
        "status": "connected",
        "provider": "TWSE/TPEX market index sources",
        "cadence": "intraday_or_daily_by_source",
        "outward_target": "market",
        "payload_ref": "data.breadth",
        "notes": "Official full-market breadth is distinct from OMI sample movers and watchlists.",
    },
    {
        "id": "tw_market_chips_rankings",
        "market": "tw",
        "status": "connected",
        "provider": "TWSE/TPEX local cache",
        "cadence": "daily_post_close",
        "outward_target": "market",
        "payload_ref": "data.market_chips",
        "notes": "Official aggregate and per-stock database coverage are exposed separately.",
    },
    {
        "id": "tw_futures_institutional_oi_pcr",
        "market": "tw",
        "status": "connected",
        "provider": "TAIFEX official daily",
        "cadence": "daily_post_close",
        "outward_target": "tw_futures",
        "payload_ref": "data.institutional_position,data.options_sentiment,data.market_chip_trend",
        "notes": "Not a live night-session institutional-position feed.",
    },
    {
        "id": "kr_intraday",
        "market": "kr",
        "status": "connected",
        "provider": "Yahoo chart/Naver cache",
        "cadence": "bounded_intraday",
        "outward_target": "kr_stock,kr_index",
        "payload_ref": "data.compact.intraday_bars",
        "notes": "External refresh remains server-trust gated.",
    },
    {
        "id": "resource_quotes_ohlcv",
        "market": "resource",
        "status": "connected",
        "provider": "Yahoo chart best effort",
        "cadence": "bounded_cache_refresh",
        "outward_target": "resource_asset",
        "payload_ref": "data.quote,data.chart",
        "notes": "Watch-only and delayed/best-effort; no execution capability.",
    },
    {
        "id": "portfolio_context",
        "market": "multi",
        "status": "connected_private",
        "provider": "OMI local portfolio",
        "cadence": "on_read_local_cache",
        "outward_target": "portfolio",
        "payload_ref": "data.holdings,data.valuation",
        "notes": "Private holdings require a server-trusted caller; currencies are not silently combined.",
    },
    {
        "id": "fred_macro",
        "market": "us",
        "status": "connected_key_required_for_refresh",
        "provider": "FRED",
        "cadence": "series_release_schedule",
        "outward_target": "us_macro",
        "payload_ref": "data.observations",
        "notes": "Read path uses local cache; refresh requires configured FRED_API_KEY.",
    },
    {
        "id": "news_events",
        "market": "multi",
        "status": "provider_not_connected",
        "provider": None,
        "cadence": None,
        "outward_target": None,
        "payload_ref": "slots.news_events",
        "blocking_reason": "No source attribution, licensing, deduplication, entity mapping, or quota policy is configured.",
        "next_fill": "Select a news/events provider and define attribution, retention, deduplication, and bounded refresh policy.",
    },
    {
        "id": "tw_options_chain_iv_greeks",
        "market": "tw",
        "status": "connected_derived",
        "provider": "TAIFEX OpenAPI",
        "cadence": "daily_post_close",
        "outward_target": "tw_futures",
        "payload_ref": "data.derivatives.options_chain",
        "notes": "Chain and Delta are official; IV/Gamma/Vega/Theta are derived with explicit zero-rate/zero-dividend assumptions and are not live night-session Greeks.",
    },
    {
        "id": "tw_large_trader_positions",
        "market": "tw",
        "status": "connected",
        "provider": "TAIFEX OpenAPI",
        "cadence": "daily_post_close",
        "outward_target": "tw_futures",
        "payload_ref": "data.derivatives.large_traders",
        "notes": "Top-five/top-ten concentration includes all traders and the specific-institution subset; it is not foreign-investor direction.",
    },
    {
        "id": "tw_futures_basis_term_structure",
        "market": "tw",
        "status": "connected_derived",
        "provider": "TAIFEX OpenAPI + TAIEX local cache",
        "cadence": "daily_post_close",
        "outward_target": "tw_futures",
        "payload_ref": "data.derivatives.term_structure",
        "notes": "Regular-session monthly settlements are official; basis, annualized basis, and curve shape are derived against same-date TAIEX close.",
    },
    {
        "id": "us_options_flow_earnings",
        "market": "us",
        "status": "provider_not_connected",
        "provider": None,
        "cadence": None,
        "outward_target": "us_stock",
        "payload_ref": "slots.options_flow,slots.earnings_events",
        "blocking_reason": "No licensed options-flow/earnings provider and quota contract is configured.",
        "next_fill": "Choose providers independently for options chain/flow and earnings calendar; do not infer one from the other.",
    },
    {
        "id": "jp_tdnet_disclosures",
        "market": "jp",
        "status": "provider_not_connected",
        "provider": "TDnet candidate",
        "cadence": "event_driven",
        "outward_target": "jp_stock,jp_watchlist",
        "payload_ref": "slots.disclosures",
        "blocking_reason": "No TDnet document identity, issuer mapping, attachment storage, or language policy is configured.",
        "next_fill": "Add issuer-code mapping, disclosure metadata, document provenance, and bounded event polling.",
    },
    {
        "id": "kr_opendart_disclosures",
        "market": "kr",
        "status": "provider_not_connected",
        "provider": "OpenDART candidate",
        "cadence": "event_driven",
        "outward_target": "kr_stock,kr_watchlist",
        "payload_ref": "slots.disclosures",
        "blocking_reason": "OpenDART key/policy and disclosure normalization are not configured.",
        "next_fill": "Configure key handling, corp-code mapping, report identity, and bounded polling/backfill.",
    },
    {
        "id": "hk_market",
        "market": "hk",
        "status": "provider_not_connected",
        "provider": None,
        "cadence": None,
        "outward_target": None,
        "payload_ref": None,
        "blocking_reason": "HK symbol master, trading calendar, quote/daily provider, freshness rules, and watchlist contract do not exist.",
        "next_fill": "Start with backend symbol/calendar/daily/intraday contracts aligned to Taiwan patterns before adding UI.",
    },
)


MARKET_SCOPE_TYPES: dict[str, frozenset[str]] = {
    "tw": frozenset({"stock", "market", "watchlist", "tw_index", "tw_futures"}),
    "us": frozenset({"us_stock", "us_watchlist", "us_macro"}),
    "jp": frozenset({"jp_stock", "jp_index", "jp_watchlist"}),
    "kr": frozenset({"kr_stock", "kr_index", "kr_watchlist"}),
    "crypto": frozenset({"crypto_asset", "crypto_market"}),
    "resource": frozenset({"resource_asset"}),
    "multi": frozenset({"portfolio"}),
}


def _capability_registry_rows(
    resolutions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries_by_capability: dict[str, list[dict[str, Any]]] = {}
    for entry in resolutions:
        entries_by_capability.setdefault(
            str(entry.get("capability_id") or ""),
            [],
        ).append(entry)
    specs = {
        spec.capability_id: spec
        for spec in capability_contract.CAPABILITY_SPECS
    }
    rows: list[dict[str, Any]] = []
    for capability_id, entries in sorted(entries_by_capability.items()):
        spec = specs.get(capability_id)
        rows.append(
            {
                "id": capability_id,
                "title": spec.title if spec else "",
                "description": spec.description if spec else "",
                "scopes": sorted(
                    {
                        str(entry.get("scope_type"))
                        for entry in entries
                        if entry.get("scope_type")
                    }
                ),
                "implementation_statuses": sorted(
                    {
                        str(entry.get("implementation_status"))
                        for entry in entries
                        if entry.get("implementation_status")
                    }
                ),
                "resolution_modes": sorted(
                    {
                        str(entry.get("resolution_mode"))
                        for entry in entries
                        if entry.get("resolution_mode")
                    }
                ),
                "operations": sorted(
                    {
                        str(entry.get("operation"))
                        for entry in entries
                        if entry.get("operation")
                    }
                ),
                "provider_contract_ids": sorted(
                    {
                        str(provider_id)
                        for entry in entries
                        for provider_id in entry.get("provider_contract_ids") or []
                        if str(provider_id).strip()
                    }
                ),
                "deprecated": bool(spec and spec.deprecated),
                "replacement_capabilities": list(
                    spec.replacement_capabilities if spec else ()
                ),
                "blocking_reasons": list(
                    dict.fromkeys(
                        str(entry.get("blocking_reason"))
                        for entry in entries
                        if entry.get("blocking_reason")
                    )
                ),
                "next_fills": list(
                    dict.fromkeys(
                        str(entry.get("next_fill"))
                        for entry in entries
                        if entry.get("next_fill")
                    )
                ),
            }
        )
    return rows


def read_capability_status(
    *,
    capability_id: str | None = None,
    market_data_params: dict[str, Any] | None = None,
    now: datetime,
) -> dict[str, Any]:
    params = market_data_params if isinstance(market_data_params, dict) else {}
    requested_id = str(capability_id or params.get("capability_id") or "").strip().lower()
    market_filter = str(params.get("market") or "").strip().lower()
    status_filter = str(params.get("status") or "").strip().lower()
    scope_filter = str(
        params.get("scope_type") or params.get("target_type") or ""
    ).strip().lower()
    rows = [dict(item) for item in CAPABILITIES]
    if requested_id:
        rows = [row for row in rows if row["id"].lower() == requested_id]
    if market_filter:
        rows = [row for row in rows if str(row.get("market") or "").lower() == market_filter]
    if status_filter:
        rows = [row for row in rows if str(row.get("status") or "").lower() == status_filter]

    resolutions = capability_contract.capability_resolution_catalog()
    if requested_id:
        resolutions = [
            row
            for row in resolutions
            if str(row.get("capability_id") or "").lower() == requested_id
        ]
    if scope_filter:
        resolutions = [
            row
            for row in resolutions
            if str(row.get("scope_type") or "").lower() == scope_filter
        ]
    elif market_filter in MARKET_SCOPE_TYPES:
        allowed_scopes = MARKET_SCOPE_TYPES[market_filter]
        resolutions = [
            row
            for row in resolutions
            if str(row.get("scope_type") or "") in allowed_scopes
        ]
    if status_filter:
        resolutions = [
            row
            for row in resolutions
            if str(row.get("implementation_status") or "").lower()
            == status_filter
        ]
    registry_rows = _capability_registry_rows(resolutions)

    status_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("status") or "unknown")
        status_counts[key] = status_counts.get(key, 0) + 1
    connected = [row for row in rows if str(row.get("status") or "").startswith("connected")]
    blocked = [row for row in rows if row.get("status") == "provider_not_connected"]
    missing = (
        [f"capability.{requested_id}"]
        if requested_id and not rows and not registry_rows
        else []
    )
    warnings = [
        "Capability status describes implementation/provider readiness; use source_health for current runtime freshness and provider incidents.",
        "provider_not_connected entries are explicit blocked contracts and must not be treated as empty market data.",
        "capability_registry is backend-owned implementation metadata; resolutions are scope-specific and do not describe live source health.",
    ]
    slots = {
        "connected": {
            "status": "ready" if connected else "missing",
            "capability": "connected_market_capabilities",
            "payload_ref": "connected",
        },
        "blocked": {
            "status": "ready" if blocked else "not_applicable",
            "capability": "provider_gap_contracts",
            "payload_ref": "blocked",
        },
        "data_quality": {
            "status": "partial" if missing else "ready",
            "capability": "data_quality_and_freshness",
            "payload_ref": "missing,warnings",
            "missing": missing,
            "warnings": warnings,
        },
    }
    summary = {
        "capability_count": len(rows),
        "connected_count": len(connected),
        "blocked_count": len(blocked),
        "status_counts": status_counts,
        "provider_contract_count": len(rows),
        "registry_capability_count": len(registry_rows),
        "registry_resolution_count": len(resolutions),
        "registry_total_capability_count": len(
            capability_contract.CAPABILITY_SPECS
        ),
        "registry_total_resolution_count": len(
            capability_contract.CAPABILITY_RESOLUTION_REGISTRY
        ),
    }
    compact_capabilities = [
        {
            key: row.get(key)
            for key in (
                "id",
                "market",
                "status",
                "provider",
                "cadence",
                "outward_target",
                "payload_ref",
                "blocking_reason",
                "next_fill",
            )
            if row.get(key) is not None
        }
        for row in rows
    ]
    compact_registry_rows = [
        {
            "id": row["id"],
            "implementation_status": (
                row["implementation_statuses"][0]
                if len(row["implementation_statuses"]) == 1
                else "scope_specific"
            ),
            "resolution_mode": (
                row["resolution_modes"][0]
                if len(row["resolution_modes"]) == 1
                else "scope_specific"
            ),
            **({"deprecated": True} if row["deprecated"] else {}),
            **(
                {
                    "replacement_capabilities": row[
                        "replacement_capabilities"
                    ]
                }
                if row["replacement_capabilities"]
                else {}
            ),
            **(
                {"blocking_reasons": row["blocking_reasons"]}
                if row["blocking_reasons"]
                else {}
            ),
            **({"next_fills": row["next_fills"]} if row["next_fills"] else {}),
        }
        for row in registry_rows
    ]
    envelope = {
        "kind": "capability_status",
        "generated_at": now.isoformat(),
        "as_of": now.isoformat(),
        "scope": {
            "target": {
                "type": "capability_status",
                "id": requested_id or None,
                "market": market_filter or "all",
            }
        },
        "summary": summary,
        "data": {
            "capabilities": rows,
            "provider_contracts": rows,
            "capability_registry": registry_rows,
            "resolutions": resolutions,
            "connected": connected,
            "blocked": blocked,
            "slots": slots,
            "compact": {
                "kind": "capability_status_compact",
                "version": "market_compact_evidence.v1",
                "payload_level": "compact",
                "target": {
                    "type": "capability_status",
                    "id": requested_id or None,
                    "market": market_filter or "all",
                },
                "summary": summary,
                "capabilities": compact_capabilities,
                "provider_contracts": compact_capabilities,
                "capability_registry": compact_registry_rows,
                "resolutions": resolutions,
                "slots": slots,
                "missing": missing,
                "warnings": warnings,
            },
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "contract", "name": "app.ai.market_context.capability_context"},
            {"type": "contract", "name": "app.ai.capability_resolution_registry"},
        ],
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=envelope["as_of"],
        source_refs=envelope["source_refs"],
        missing=missing,
        warnings=warnings,
        freshness={
            "kind": "capability_contract_freshness",
            "is_current": True,
            "refresh_recommended": False,
        },
    )
    return envelope
