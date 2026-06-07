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
    technical_reports = data.get("technical_reports") or {}
    daily_technical = technical_reports.get("daily") or {}
    today_technical = technical_reports.get("today") or {}

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

    if daily_technical:
        highlights.append(
            "Daily technical report "
            f"{daily_technical.get('title')} ({daily_technical.get('summary')})."
        )

    if today_technical:
        highlights.append(
            "Today technical report "
            f"{today_technical.get('title')} phase={today_technical.get('phase')} "
            f"confidence={today_technical.get('confidence')}."
        )

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


WATCHLIST_SCAN_TOP_LIMIT = 20
WATCHLIST_SCAN_BOTTOM_LIMIT = 5
WATCHLIST_SCAN_ATTENTION_LIMIT = 20

_ATTENTION_SIGNAL_KEYS = {
    "donchian_breakout",
    "volume_price_up",
    "volume_above_ma5",
    "rsi_overheated",
    "macd_negative",
    "roc_negative",
    "mfi_inflow",
}


def _watchlist_row_key(row: dict[str, Any]) -> tuple[Any, Any]:
    return (row.get("stock_id"), row.get("time"))


def _compact_watchlist_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row.get("rank"),
        "stock_id": row.get("stock_id"),
        "stock_name": row.get("stock_name"),
        "time": row.get("time"),
        "close": row.get("close"),
        "volume": row.get("volume"),
        "change_pct": row.get("change_pct"),
        "score": row.get("score"),
        "status": row.get("status"),
        "signal_count": row.get("signal_count"),
        "signal_keys": row.get("signal_keys") or [],
        "primary_signal_key": row.get("primary_signal_key"),
        "primary_signal_label": row.get("primary_signal_label"),
        "error_message": row.get("error_message"),
    }


def _is_watchlist_attention_row(row: dict[str, Any]) -> bool:
    signal_keys = set(row.get("signal_keys") or [])
    status = row.get("status")
    change_pct = row.get("change_pct")

    if signal_keys & _ATTENTION_SIGNAL_KEYS:
        return True

    if status in {"strong_bearish", "bearish", "error", "no_data"}:
        return True

    if isinstance(change_pct, (int, float)) and abs(change_pct) >= 5:
        return True

    return False


def _append_unique_watchlist_rows(
    target: list[dict[str, Any]],
    seen: set[tuple[Any, Any]],
    rows: list[dict[str, Any]],
    *,
    limit: int,
) -> None:
    for row in rows:
        key = _watchlist_row_key(row)
        if key in seen:
            continue

        seen.add(key)
        target.append(_compact_watchlist_row(row))

        if len(target) >= limit:
            return


def _build_watchlist_scan_data(context: dict[str, Any]) -> dict[str, Any]:
    ranking = (context.get("data") or {}).get("ranking") or {}
    results = ranking.get("results") or []
    seen: set[tuple[Any, Any]] = set()

    top_candidates: list[dict[str, Any]] = []
    bottom_watchlist: list[dict[str, Any]] = []
    attention_rows: list[dict[str, Any]] = []

    _append_unique_watchlist_rows(
        top_candidates,
        seen,
        results[:WATCHLIST_SCAN_TOP_LIMIT],
        limit=WATCHLIST_SCAN_TOP_LIMIT,
    )

    if len(results) > WATCHLIST_SCAN_TOP_LIMIT:
        _append_unique_watchlist_rows(
            bottom_watchlist,
            seen,
            results[-WATCHLIST_SCAN_BOTTOM_LIMIT:],
            limit=WATCHLIST_SCAN_BOTTOM_LIMIT,
        )

    attention_source = [
        row
        for row in results
        if _watchlist_row_key(row) not in seen and _is_watchlist_attention_row(row)
    ]
    _append_unique_watchlist_rows(
        attention_rows,
        seen,
        attention_source,
        limit=WATCHLIST_SCAN_ATTENTION_LIMIT,
    )

    return {
        "ranking": {
            "rank_by": ranking.get("rank_by"),
            "sort_order": ranking.get("sort_order"),
            "requested_stock_count": ranking.get("requested_stock_count"),
            "ranked_count": ranking.get("ranked_count"),
            "no_data_count": ranking.get("no_data_count"),
            "error_count": ranking.get("error_count"),
            "results_count": len(results),
            "included_count": len(seen),
            "omitted_count": max(len(results) - len(seen), 0),
            "scan_top_limit": WATCHLIST_SCAN_TOP_LIMIT,
            "scan_bottom_limit": WATCHLIST_SCAN_BOTTOM_LIMIT,
            "scan_attention_limit": WATCHLIST_SCAN_ATTENTION_LIMIT,
        },
        "scan": {
            "top_candidates": top_candidates,
            "bottom_watchlist": bottom_watchlist,
            "attention_rows": attention_rows,
        },
    }


def build_stock_brief(
    db: Session,
    stock_id: str,
    *,
    strategy_profile: str = "balanced",
    branch_days: int = 5,
    include_intraday: bool = False,
) -> dict[str, Any]:
    context = tools.read_stock_context(
        db=db,
        stock_id=stock_id,
        branch_days=branch_days,
        include_intraday=include_intraday,
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
    scan_data = _build_watchlist_scan_data(context)
    warnings = list(context.get("warnings") or [])
    if scan_data["ranking"]["omitted_count"]:
        warnings.append(
            "Watchlist brief uses compressed scan mode for LLM cost control; "
            "read the watchlist context endpoint for the full ranking rows."
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
        "data": scan_data,
        "warnings": warnings,
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
