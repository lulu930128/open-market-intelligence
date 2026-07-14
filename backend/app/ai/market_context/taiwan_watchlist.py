from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai.market_context.taiwan_projection import (
    _latest_date_string,
    _with_evidence_passport,
)


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
    radar = dependencies.radar_service.build_watchlist_radar_from_ranking(
        ranking=ranking,
        include_children=include_children,
        mode=radar_mode,
        max_results=max(1, min(int(radar_limit or 12), 200)),
    )
    radar["group_id"] = group_id
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
