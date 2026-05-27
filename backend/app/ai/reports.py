from typing import Any

from sqlalchemy.orm import Session

from app.ai import memory as ai_memory
from app.ai import prompts, tools


def _memory_context(
    db: Session,
    *,
    scope_type: str,
    scope_id: str,
    strategy_profile: str,
) -> list[dict[str, Any]]:
    memories = ai_memory.list_relevant_memories(
        db=db,
        scope_type=scope_type,
        scope_id=scope_id,
        strategy_profile=strategy_profile,
    )
    return [ai_memory.serialize_memory(memory) for memory in memories]


def _compact_stock_summary(context: dict[str, Any]) -> dict[str, Any]:
    data = context.get("data", {})
    latest_daily = data.get("latest_daily") or {}
    latest_revenue = data.get("latest_revenue") or {}
    latest_financial = data.get("latest_financial") or {}
    broker_branch = data.get("broker_branch") or {}

    highlights: list[str] = []
    checks: list[str] = []

    close_price = latest_daily.get("close_price")
    price_change = latest_daily.get("price_change")
    trade_date = latest_daily.get("trade_date")

    if close_price is not None:
        highlights.append(
            f"Latest close is {close_price} on {trade_date}; price_change={price_change}."
        )
    else:
        checks.append("No latest daily close is available.")

    if latest_revenue:
        highlights.append(
            "Latest revenue period "
            f"{latest_revenue.get('period')} YoY={latest_revenue.get('year_over_year_pct')}."
        )
    else:
        checks.append("Monthly revenue data is missing.")

    if latest_financial:
        highlights.append(
            "Latest financial period "
            f"{latest_financial.get('period')} EPS={latest_financial.get('eps')} ROE={latest_financial.get('roe')}."
        )
    else:
        checks.append("Quarterly financial metrics are missing.")

    if broker_branch.get("row_count"):
        highlights.append(
            "Broker branch coverage "
            f"{broker_branch.get('available_days')} / {broker_branch.get('requested_days')} days."
        )
    else:
        checks.append("Broker branch data is missing.")

    checks.extend(context.get("missing", []))

    return {
        "highlights": highlights,
        "next_checks": list(dict.fromkeys(checks)),
    }


def _compact_watchlist_summary(context: dict[str, Any]) -> dict[str, Any]:
    ranking = (context.get("data") or {}).get("ranking") or {}
    results = ranking.get("results") or []
    top_rows = results[:5]
    bottom_rows = results[-5:] if len(results) > 5 else []

    return {
        "ranking": {
            "rank_by": ranking.get("rank_by"),
            "sort_order": ranking.get("sort_order"),
            "requested_stock_count": ranking.get("requested_stock_count"),
            "ranked_count": ranking.get("ranked_count"),
            "no_data_count": ranking.get("no_data_count"),
            "error_count": ranking.get("error_count"),
        },
        "top_rows": top_rows,
        "bottom_rows": bottom_rows,
        "next_checks": context.get("missing", []),
    }


def build_stock_brief(
    db: Session,
    stock_id: str,
    *,
    strategy_profile: str = "balanced",
    branch_days: int = 5,
) -> dict[str, Any]:
    context = tools.read_stock_context(
        db=db,
        stock_id=stock_id,
        branch_days=branch_days,
    )
    profile = prompts.get_strategy_profile(strategy_profile)
    memories = _memory_context(
        db=db,
        scope_type="stock",
        scope_id=stock_id,
        strategy_profile=profile.key,
    )

    return {
        **context,
        "kind": "stock_brief",
        "strategy_profile": profile.key,
        "prompt": {
            "system": prompts.build_system_prompt(profile.key),
            "profile": {
                "key": profile.key,
                "label": profile.label,
                "description": profile.description,
                "focus_points": list(profile.focus_points),
                "risk_notes": list(profile.risk_notes),
            },
            "memories": memories,
        },
        "summary": _compact_stock_summary(context),
    }


def build_watchlist_brief(
    db: Session,
    group_id: int,
    *,
    strategy_profile: str = "balanced",
    rank_by: str = "score",
    sort_order: str = "desc",
) -> dict[str, Any]:
    context = tools.read_watchlist_context(
        db=db,
        group_id=group_id,
        rank_by=rank_by,
        sort_order=sort_order,
    )
    profile = prompts.get_strategy_profile(strategy_profile)
    memories = _memory_context(
        db=db,
        scope_type="watchlist",
        scope_id=str(group_id),
        strategy_profile=profile.key,
    )

    return {
        **context,
        "kind": "watchlist_brief",
        "strategy_profile": profile.key,
        "prompt": {
            "system": prompts.build_system_prompt(profile.key),
            "profile": {
                "key": profile.key,
                "label": profile.label,
                "description": profile.description,
                "focus_points": list(profile.focus_points),
                "risk_notes": list(profile.risk_notes),
            },
            "memories": memories,
        },
        "summary": _compact_watchlist_summary(context),
    }
