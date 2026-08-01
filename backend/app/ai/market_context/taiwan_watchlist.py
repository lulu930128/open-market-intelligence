from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai.market_payload_contract import payload_level, slot_envelope
from app.ai.market_context.taiwan_projection import (
    _latest_date_string,
    _with_evidence_passport,
)
from app.watchlists import radar_active_v2_service


_WATCHLIST_CONTEXT_RESOURCES = ("institutional", "margin", "revenue", "financial")


def _compact_watchlist_context_snapshot(value: Any) -> dict[str, Any]:
    snapshot = value if isinstance(value, dict) else {}
    output: dict[str, Any] = {}
    fields = {
        "institutional": ("trade_date", "total_net", "foreign_net", "investment_trust_net", "dealer_net"),
        "margin": (
            "trade_date",
            "margin_balance_change",
            "margin_today_balance",
            "short_balance_change",
            "short_today_balance",
            "offset",
        ),
        "revenue": ("period", "month_over_month_pct", "year_over_year_pct", "cumulative_year_over_year_pct"),
        "financial": ("period", "fiscal_year", "quarter", "eps", "roe", "roa"),
    }
    for key, keys in fields.items():
        resource = snapshot.get(key) if isinstance(snapshot.get(key), dict) else {}
        output[key] = {field: resource.get(field) for field in keys if field in resource} or None
    return output


def _compact_watchlist_row(row: dict[str, Any]) -> dict[str, Any]:
    context_snapshot = _compact_watchlist_context_snapshot(row.get("context_snapshot"))
    return {
        "rank": row.get("rank"),
        "stock_id": row.get("stock_id"),
        "stock_name": row.get("stock_name"),
        "time": row.get("time"),
        "close": row.get("close"),
        "volume": row.get("volume"),
        "change": row.get("change"),
        "change_pct": row.get("change_pct"),
        "limit_status": row.get("limit_status"),
        "score": row.get("score"),
        "status": row.get("status"),
        "signal_count": row.get("signal_count"),
        "signal_keys": list(row.get("signal_keys") or [])[:8],
        "primary_signal_key": row.get("primary_signal_key"),
        "primary_signal_label": row.get("primary_signal_label"),
        "context": context_snapshot,
        "evidence_status": {
            key: "ready" if context_snapshot.get(key) else "missing"
            for key in _WATCHLIST_CONTEXT_RESOURCES
        },
        "error_message": row.get("error_message"),
    }


def _compact_radar_v2(value: Any) -> dict[str, Any] | None:
    evaluation = value if isinstance(value, dict) else None
    if evaluation is None:
        return None
    compact = {
        key: evaluation.get(key)
        for key in (
            "rule_version",
            "rule_config_hash",
            "direction",
            "direction_score",
            "evidence_score",
            "confidence_score",
            "conflict_score",
            "risk_score",
            "priority_score",
            "primary_bucket",
            "urgency",
            "evidence_grade",
            "instrument_regime",
            "market_regime",
            "data_status",
            "freshness_status",
            "data_quality_score",
        )
        if key in evaluation
    }
    compact["limitations"] = list(evaluation.get("limitations") or [])[:8]
    return compact


def _compact_radar_item(row: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: row.get(key)
        for key in (
            "rank",
            "stock_id",
            "stock_name",
            "bucket",
            "bucket_label",
            "urgency",
            "action_label",
            "reason",
            "trade_date",
            "close",
            "change_pct",
            "score",
            "status",
            "signal_labels",
            "matched_signal_keys",
            "primary_signal_label",
            "stale",
            "priority_score",
            "technical_evidence_score",
            "technical_grade",
            "direction",
            "risk_label",
        )
        if key in row
    }
    radar_v2 = _compact_radar_v2(row.get("radar_v2"))
    if radar_v2 is not None:
        compact["radar_v2"] = radar_v2
    return compact


def _compact_radar(radar: dict[str, Any], *, limit: int) -> dict[str, Any]:
    return {
        key: radar.get(key)
        for key in (
            "mode",
            "requested_stock_count",
            "ranked_count",
            "matched_count",
            "radar_count",
            "no_data_count",
            "error_count",
            "trade_date",
            "target_trade_date",
            "is_current",
            "current_stock_count",
            "stale_stock_count",
            "cache_status",
            "snapshot_id",
            "snapshot_date",
            "calculated_at",
            "data_limitations",
            "buckets",
            "radar_engine",
            "radar_v2_summary",
        )
        if key in radar
    } | {
        "results": [
            _compact_radar_item(row)
            for row in (radar.get("results") or [])[:limit]
            if isinstance(row, dict)
        ]
    }


def _watchlist_status(ranking: dict[str, Any]) -> str:
    ranked_count = int(ranking.get("ranked_count") or 0)
    error_count = int(ranking.get("error_count") or 0)
    no_data_count = int(ranking.get("no_data_count") or 0)
    stale_count = int(ranking.get("stale_stock_count") or 0)
    if error_count and not ranked_count:
        return "failed"
    if stale_count or ranking.get("is_current") is False:
        return "stale"
    if error_count or no_data_count:
        return "partial"
    return "ready" if ranked_count else "missing"


def _watchlist_resource_coverage(results: list[dict[str, Any]], resource: str) -> dict[str, Any]:
    available_rows = [
        row
        for row in results
        if isinstance(row.get("context_snapshot"), dict)
        and isinstance(row["context_snapshot"].get(resource), dict)
        and bool(row["context_snapshot"][resource])
    ]
    available_count = len(available_rows)
    total_count = len(results)
    status = "missing" if available_count == 0 else "partial" if available_count < total_count else "ready"
    as_of_values = [
        row["context_snapshot"][resource].get("trade_date")
        or row["context_snapshot"][resource].get("period")
        for row in available_rows
    ]
    return {
        "status": status,
        "available_count": available_count,
        "missing_count": max(total_count - available_count, 0),
        "total_count": total_count,
        "as_of": _latest_date_string(as_of_values),
    }


def _build_watchlist_compact(
    *,
    group_id: int,
    group_name: str,
    ranking: dict[str, Any],
    radar: dict[str, Any],
    payload_level_value: str,
) -> dict[str, Any]:
    results = [row for row in (ranking.get("results") or []) if isinstance(row, dict)]
    row_limit = {"summary": 5, "compact": 20, "standard": 50, "full": 100}.get(payload_level_value, 20)
    radar_limit = {"summary": 3, "compact": 12, "standard": 24, "full": 50}.get(payload_level_value, 12)
    ranking_status = _watchlist_status(ranking)
    radar_status = _watchlist_status(radar)
    coverage = {
        resource: _watchlist_resource_coverage(results, resource)
        for resource in _WATCHLIST_CONTEXT_RESOURCES
    }
    coverage["broker_branch"] = {
        "status": "missing",
        "available_count": 0,
        "missing_count": len(results),
        "total_count": len(results),
        "as_of": None,
        "reason": "broker_branch_not_projected_by_watchlist_ranking",
    }
    slots = {
        "identity": slot_envelope(
            status="ready",
            capability="watchlist_identity",
            payload_ref="target",
            payload_level=payload_level_value,
            priority="core",
        ),
        "ranking": slot_envelope(
            status=ranking_status,
            capability="watchlist_ranking",
            payload_ref="ranking",
            payload_level=payload_level_value,
            priority="core",
            as_of=str(ranking.get("trade_date")) if ranking.get("trade_date") is not None else None,
            missing=["watchlist_ranking"] if ranking_status in {"missing", "failed"} else None,
            warnings=[f"freshness_status={ranking_status}"] if ranking_status in {"partial", "stale", "failed"} else None,
        ),
        "radar": slot_envelope(
            status=radar_status,
            capability="watchlist_radar",
            payload_ref="radar",
            payload_level=payload_level_value,
            as_of=str(radar.get("trade_date")) if radar.get("trade_date") is not None else None,
            missing=["watchlist_radar"] if radar_status in {"missing", "failed"} else None,
            warnings=[f"freshness_status={radar_status}"] if radar_status in {"partial", "stale", "failed"} else None,
        ),
    }
    for resource, resource_coverage in coverage.items():
        status = str(resource_coverage["status"])
        slots[resource] = slot_envelope(
            status=status,
            capability=f"watchlist_{resource}_coverage",
            payload_ref=f"evidence_coverage.{resource}",
            payload_level=payload_level_value,
            as_of=resource_coverage.get("as_of"),
            missing=[f"watchlist_{resource}"] if status == "missing" else None,
            warnings=[f"partial_coverage={resource_coverage['available_count']}/{resource_coverage['total_count']}"]
            if status == "partial"
            else None,
            next_fill="Project broker-branch coverage through the backend ranking contract."
            if resource == "broker_branch"
            else None,
        )
    coverage_statuses = [str(item["status"]) for item in coverage.values()]
    data_quality_status = (
        "failed"
        if "failed" in {ranking_status, radar_status}
        else "stale"
        if "stale" in {ranking_status, radar_status}
        else "partial"
        if any(status in {"missing", "partial"} for status in coverage_statuses)
        or "partial" in {ranking_status, radar_status}
        else "ready"
    )
    slots["data_quality"] = slot_envelope(
        status=data_quality_status,
        capability="watchlist_data_quality",
        payload_ref="freshness_by_domain,evidence_coverage",
        payload_level=payload_level_value,
        priority="core",
        warnings=[f"freshness_status={data_quality_status}"] if data_quality_status != "ready" else None,
    )
    return {
        "kind": "tw_watchlist_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": payload_level_value,
        "target": {
            "type": "tw_watchlist",
            "id": group_id,
            "label": group_name,
            "market": "TW",
        },
        "ranking": {
            key: ranking.get(key)
            for key in (
                "rank_by",
                "sort_order",
                "requested_stock_count",
                "ranked_count",
                "no_data_count",
                "error_count",
                "trade_date",
                "target_trade_date",
                "is_current",
                "current_stock_count",
                "stale_stock_count",
            )
            if key in ranking
        } | {
            "result_count": len(results),
            "returned_count": min(len(results), row_limit),
            "results": [_compact_watchlist_row(row) for row in results[:row_limit]],
        },
        "radar": _compact_radar(radar, limit=radar_limit),
        "evidence_coverage": coverage,
        "freshness_by_domain": {"ranking": ranking_status, "radar": radar_status},
        "slots": slots,
    }


@dataclass(frozen=True)
class TaiwanWatchlistDependencies:
    watchlist_service: Any
    ranking_service: Any
    radar_service: Any
    now: Callable[[], datetime]


def read_watchlist_context(
    db: Session,
    group_id: int,
    *,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "score",
    sort_order: str = "desc",
    limit: int = 100,
    radar_mode: str = "action",
    radar_limit: int = 12,
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanWatchlistDependencies,
) -> dict[str, Any]:
    group = dependencies.watchlist_service.get_group(db=db, group_id=group_id)
    ranking = dependencies.ranking_service.get_watchlist_group_latest_ranking(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by=rank_by,
        sort_order=sort_order,
        limit=limit,
        use_intraday=False,
    )
    base_radar, calculation_universe = (
        dependencies.radar_service.build_watchlist_radar_bundle_from_ranking(
            ranking=ranking,
            include_children=include_children,
            mode=radar_mode,
            max_results=max(1, min(int(radar_limit or 12), 200)),
        )
    )
    base_radar["group_id"] = group_id
    radar = radar_active_v2_service.build_radar_v2_active_projection_from_db(
        db=db,
        radar=base_radar,
        universe_items=calculation_universe,
    )
    results = ranking.get("results", [])
    missing = []
    warnings = [
        "Watchlist context and radar use local daily indicator data and do not fetch live quotes.",
    ]

    if ranking.get("no_data_count"):
        missing.append("watchlist_items_with_market_data")
    if radar.get("error_count"):
        missing.append("watchlist_radar_error_items")

    ranked_as_of = _latest_date_string([row.get("time") for row in results])
    radar_as_of = _latest_date_string(
        [item.get("time") or item.get("trade_date") for item in radar.get("results", [])]
    )
    compact = _build_watchlist_compact(
        group_id=group_id,
        group_name=group.group_name,
        ranking=ranking,
        radar=radar,
        payload_level_value=payload_level(market_data_params),
    )
    for resource, coverage in compact["evidence_coverage"].items():
        if coverage["status"] == "missing":
            missing.append(f"watchlist_{resource}")
        elif coverage["status"] == "partial":
            warnings.append(
                f"Watchlist {resource} coverage is partial: {coverage['available_count']}/{coverage['total_count']}."
            )

    envelope = {
        "kind": "watchlist_context",
        "generated_at": dependencies.now(),
        "as_of": ranked_as_of or radar_as_of,
        "scope": {
            "group_id": group_id,
            "group_name": group.group_name,
            "include_children": include_children,
            "enabled_only": enabled_only,
            "radar_mode": radar.get("mode") or radar_mode,
        },
        "data": {
            "ranking": ranking,
            "radar": radar,
            "compact": compact,
            "slots": compact["slots"],
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "table", "name": "watchlist_group"},
            {"type": "table", "name": "watchlist_item"},
            {"type": "table", "name": "market_daily_price"},
            {"type": "service", "name": "watchlist_radar"},
        ],
    }
    return _with_evidence_passport(envelope)
