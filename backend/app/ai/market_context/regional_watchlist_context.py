from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import bounded_int_param, payload_level, slot_envelope


@dataclass(frozen=True)
class RegionalWatchlistDependencies:
    us_market_service: Any
    jp_market_service: Any
    kr_market_service: Any
    now: Any


def _json_ready(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _ranking_status(ranking: dict[str, Any]) -> str:
    requested = int(ranking.get("requested_symbol_count") or 0)
    no_data = int(ranking.get("no_data_count") or 0)
    error_count = int(ranking.get("error_count") or 0)
    freshness = ranking.get("freshness") if isinstance(ranking.get("freshness"), dict) else ranking
    is_current = freshness.get("is_current")
    if requested == 0:
        return "ready"
    if no_data >= requested:
        return "missing"
    if error_count or no_data:
        return "partial"
    if is_current is False:
        return "stale"
    return "ready"


def read_regional_watchlist_context(
    db: Session,
    *,
    market: str,
    group_id: int,
    include_children: bool,
    enabled_only: bool,
    rank_by: str,
    sort_order: str,
    radar_mode: str,
    market_data_params: dict[str, Any] | None,
    context_limit: int,
    dependencies: RegionalWatchlistDependencies,
) -> dict[str, Any]:
    normalized_market = market.strip().lower()
    if normalized_market not in {"us", "jp", "kr"}:
        raise ValueError("regional watchlist market must be one of: us, jp, kr.")
    params = market_data_params if isinstance(market_data_params, dict) else {}
    level = payload_level(params)
    result_limit = max(1, min(int(context_limit or 100), 200))
    radar_limit = bounded_int_param(
        params,
        ("radar_limit", "limit"),
        default=min(result_limit, 30),
        minimum=1,
        maximum=100,
    )
    include_intraday = bool(params.get("include_intraday")) and normalized_market == "us"
    regional_rank_by = rank_by if rank_by in {"change_pct", "volume"} else "none"

    if normalized_market == "us":
        service = dependencies.us_market_service
        group = service.get_us_watchlist_group(db, group_id)
        ranking = service.get_us_watchlist_ranking(
            db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            rank_by=regional_rank_by,
            sort_order=sort_order,
            use_intraday=include_intraday,
            intraday_limit=bounded_int_param(
                params,
                ("intraday_limit",),
                default=30,
                minimum=1,
                maximum=120,
            ),
        )
        radar = service.get_us_watchlist_technical_radar(
            db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            mode=radar_mode,
            max_results=radar_limit,
            use_intraday=include_intraday,
        )
    elif normalized_market == "jp":
        service = dependencies.jp_market_service
        group = service.get_jp_watchlist_group(db, group_id)
        ranking = service.get_jp_watchlist_ranking(
            db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            rank_by=regional_rank_by,
            sort_order=sort_order,
        )
        radar = service.get_jp_watchlist_technical_radar(
            db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            mode=radar_mode,
            max_results=radar_limit,
        )
    else:
        service = dependencies.kr_market_service
        group = service.get_kr_watchlist_group(db, group_id)
        ranking = service.get_kr_watchlist_ranking(
            db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            rank_by=regional_rank_by,
            sort_order=sort_order,
        )
        radar = service.get_kr_watchlist_technical_radar(
            db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            mode=radar_mode,
            max_results=radar_limit,
        )

    ranking = _json_ready(ranking)
    radar = _json_ready(radar)
    ranking["results"] = list(ranking.get("results") or [])[:result_limit]
    ranking_status = _ranking_status(ranking)
    radar_results = list(radar.get("results") or [])
    radar_status = "ready" if radar_results or int(ranking.get("requested_symbol_count") or 0) == 0 else "partial"
    intraday_result_count = sum(
        1
        for row in ranking.get("results") or []
        if isinstance(row, dict) and row.get("status") in {"intraday", "extended_hours"}
    )
    requested_symbol_count = int(ranking.get("requested_symbol_count") or 0)
    intraday_status = (
        "not_requested"
        if not include_intraday and normalized_market == "us"
        else "planned"
        if normalized_market != "us"
        else "not_applicable"
        if requested_symbol_count == 0
        else "ready"
        if intraday_result_count >= requested_symbol_count
        else "partial"
        if intraday_result_count > 0
        else "missing"
    )
    missing: list[str] = []
    warnings = [
        f"{normalized_market.upper()} watchlist context is bounded to configured local watchlist members and is not full-market breadth."
    ]
    if ranking_status == "missing":
        missing.append(f"{normalized_market}_watchlist_prices")
    if ranking_status in {"stale", "partial"}:
        warnings.append(f"{normalized_market.upper()} watchlist ranking is stale or partially covered.")
    if normalized_market != "us" and params.get("include_intraday"):
        warnings.append(
            f"{normalized_market.upper()} watchlist intraday overlay is not enabled in this context; ranking uses cached daily data."
        )

    group_name = getattr(group, "name", None) or f"{normalized_market.upper()} watchlist {group_id}"
    target = {
        "type": f"{normalized_market}_watchlist",
        "id": str(group_id),
        "label": group_name,
        "market": normalized_market.upper(),
    }
    slots = {
        "identity": slot_envelope(
            status="ready",
            capability="regional_watchlist_identity",
            payload_ref="data.group",
            payload_level=level,
            priority="core",
        ),
        "ranking": slot_envelope(
            status=ranking_status,
            capability="regional_watchlist_ranking",
            payload_ref="data.ranking",
            payload_level=level,
            priority="core",
            as_of=str(ranking.get("trade_date") or ranking.get("target_trade_date") or "") or None,
            missing=missing,
        ),
        "radar": slot_envelope(
            status=radar_status,
            capability="regional_watchlist_technical_radar",
            payload_ref="data.radar",
            payload_level=level,
            priority="core",
        ),
        "intraday": slot_envelope(
            status=intraday_status,
            capability="regional_watchlist_intraday_overlay",
            payload_ref="data.ranking.results",
            payload_level=level,
            next_fill=(
                "Wire the market-specific bounded intraday reader into watchlist ranking."
                if normalized_market != "us"
                else None
            ),
        ),
        "data_quality": slot_envelope(
            status="partial" if missing or ranking_status in {"partial", "stale"} else "ready",
            capability="regional_watchlist_coverage",
            payload_ref="data.ranking",
            payload_level=level,
            priority="core",
            missing=missing,
            warnings=warnings,
        ),
    }
    as_of = ranking.get("trade_date") or ranking.get("target_trade_date")
    envelope = {
        "kind": f"{normalized_market}_watchlist_context",
        "generated_at": dependencies.now(),
        "as_of": as_of,
        "scope": {"target": target},
        "data": {
            "group": {"id": group_id, "name": group_name},
            "ranking": ranking,
            "radar": radar,
            "compact": {
                "kind": f"{normalized_market}_watchlist_compact_evidence",
                "version": "market_compact_evidence.v1",
                "payload_level": level,
                "target": target,
                "resources": {
                    "requested_symbol_count": ranking.get("requested_symbol_count"),
                    "ranked_count": ranking.get("ranked_count"),
                    "no_data_count": ranking.get("no_data_count"),
                    "radar_result_count": len(radar_results),
                    "include_intraday": include_intraday,
                    "intraday_result_count": intraday_result_count,
                },
                "freshness_by_domain": {
                    "ranking": ranking_status,
                    "radar": radar_status,
                },
                "slots": slots,
            },
            "slots": slots,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "user_input", "name": f"{normalized_market}_watchlist_item"},
            {"type": "table", "name": f"{normalized_market}_daily_price"},
            {"type": "derived", "name": "app.market.technical_radar"},
        ],
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=as_of,
        source_refs=envelope["source_refs"],
        missing=missing,
        warnings=warnings,
        freshness={
            "is_current": ranking_status == "ready",
            "missing": missing,
        },
    )
    return envelope
