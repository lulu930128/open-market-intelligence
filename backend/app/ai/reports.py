from typing import Any

from sqlalchemy.orm import Session

from app.ai import memory as ai_memory
from app.ai import prompts, tools


ANALYSIS_HORIZON_LABELS = {
    "intraday": "盤中",
    "short": "短線",
    "swing": "中短線",
    "long": "長線",
}
HUMAN_ANSWER_MAX_ITEMS = 3
WATCHLIST_PULLBACK_CHANGE_PCT = 5.0

DATASET_HUMAN_LABELS = {
    "stock_master": "股票基本資料",
    "market_daily_price": "日線",
    "institutional_trade_daily": "法人",
    "margin_trading_daily": "融資券",
    "broker_branch_trade_daily": "分點",
    "shareholding_distribution_weekly": "籌碼",
    "monthly_revenue": "營收",
    "financial_metric_quarterly": "財報",
    "watchlist_items_with_market_data": "部分自選股日線",
}


def _score_display(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    sign = "+" if value > 0 else ""
    return f"{sign}{int(round(value))}"


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value:
        return None
    return float(value)


def _pct_display(value: Any) -> str | None:
    number = _numeric(value)
    if number is None:
        return None
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}%"


def _row_label(row: dict[str, Any]) -> str:
    stock_id = str(row.get("stock_id") or "").strip()
    stock_name = str(row.get("stock_name") or "").strip()
    if stock_id and stock_name:
        return f"{stock_id} {stock_name}"
    return stock_id or stock_name or "-"


def _row_identity(row: dict[str, Any]) -> tuple[Any, Any]:
    return (row.get("stock_id"), row.get("time"))


def _unique_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = _row_identity(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _row_labels(rows: list[dict[str, Any]], *, limit: int = HUMAN_ANSWER_MAX_ITEMS) -> str:
    labels = [_row_label(row) for row in rows[:limit]]
    return "、".join(labels) if labels else "暫無明確名單"


def _dataset_human_labels(missing: list[Any]) -> list[str]:
    labels: list[str] = []
    for key in missing:
        label = DATASET_HUMAN_LABELS.get(str(key), "部分資料")
        if label not in labels:
            labels.append(label)
    return labels


def _human_data_limit_line(
    *,
    missing: list[Any],
    requested_count: int,
    no_data_count: int,
    error_count: int,
    stale_stock_count: int,
) -> str:
    if not missing and no_data_count == 0 and error_count == 0 and stale_stock_count == 0:
        return "資料覆蓋正常，可用資料足以做短線觀察。"

    details: list[str] = []
    if no_data_count:
        details.append(f"{no_data_count} 檔缺日線")
    if error_count:
        details.append(f"{error_count} 檔讀取異常")
    if stale_stock_count:
        details.append(f"{stale_stock_count} 檔資料日期偏舊")

    dataset_labels = _dataset_human_labels(missing)
    dataset_text = "、".join(dataset_labels[:4])
    if dataset_text:
        details.append(f"{dataset_text}不足")

    prefix = f"{requested_count} 檔中 " if requested_count > 0 and details else ""
    detail_text = "、".join(details) if details else "部分資料不足"
    return f"資料限制：{prefix}{detail_text}，短線結論信心降低。"


def _compact_analysis_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(analysis, dict) or not analysis:
        return {}

    selected_horizon = analysis.get("selected_horizon") or "swing"
    horizon_label = ANALYSIS_HORIZON_LABELS.get(str(selected_horizon), str(selected_horizon))
    score_text = _score_display(analysis.get("selected_score"))
    display_parts = [
        f"{horizon_label}評分 {score_text}" if score_text is not None else f"{horizon_label}評分 -"
    ]
    if analysis.get("selected_title"):
        display_parts.append(str(analysis["selected_title"]))
    if analysis.get("selected_summary"):
        display_parts.append(str(analysis["selected_summary"]))

    return {
        "selected_horizon": selected_horizon,
        "horizon_label": horizon_label,
        "selected_timeframe": analysis.get("selected_timeframe"),
        "selected_score": analysis.get("selected_score"),
        "score_display": score_text,
        "selected_title": analysis.get("selected_title"),
        "selected_summary": analysis.get("selected_summary"),
        "selected_confidence": analysis.get("selected_confidence"),
        "display": "｜".join(display_parts),
        "scores": analysis.get("scores") or {},
    }


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
    analysis = data.get("analysis") or {}

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

    analysis_summary = _compact_analysis_summary(analysis)
    if analysis_summary:
        highlights.append(
            "Selected analysis horizon "
            f"{analysis_summary.get('selected_horizon')} score={analysis_summary.get('selected_score')} "
            f"confidence={analysis_summary.get('selected_confidence')}."
        )

    checks.extend(context.get("missing", []))

    return {
        "highlights": highlights,
        "analysis": analysis_summary,
        "next_checks": list(dict.fromkeys(checks)),
    }


def _compact_watchlist_summary(
    context: dict[str, Any],
    *,
    overview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ranking = (context.get("data") or {}).get("ranking") or {}
    results = ranking.get("results") or []
    top_rows = [_compact_watchlist_row(row) for row in results[:5]]
    bottom_rows = [_compact_watchlist_row(row) for row in results[-5:]] if len(results) > 5 else []

    return {
        "overview": overview or {},
        "ranking": {
            "rank_by": ranking.get("rank_by"),
            "sort_order": ranking.get("sort_order"),
            "requested_stock_count": ranking.get("requested_stock_count"),
            "ranked_count": ranking.get("ranked_count"),
            "no_data_count": ranking.get("no_data_count"),
            "error_count": ranking.get("error_count"),
            "is_current": ranking.get("is_current"),
            "trade_date": ranking.get("trade_date"),
            "target_trade_date": ranking.get("target_trade_date"),
            "stale_stock_count": ranking.get("stale_stock_count"),
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
    change_pct_text = _pct_display(row.get("change_pct"))
    score_text = _score_display(row.get("score"))
    display_parts = [_row_label(row)]
    if change_pct_text is not None:
        display_parts.append(change_pct_text)
    if score_text is not None:
        display_parts.append(f"score {score_text}")
    if row.get("primary_signal_label"):
        display_parts.append(str(row["primary_signal_label"]))

    return {
        "rank": row.get("rank"),
        "stock_id": row.get("stock_id"),
        "stock_name": row.get("stock_name"),
        "label": _row_label(row),
        "time": row.get("time"),
        "close": row.get("close"),
        "volume": row.get("volume"),
        "change": row.get("change"),
        "change_pct": row.get("change_pct"),
        "change_pct_text": change_pct_text,
        "limit_status": row.get("limit_status"),
        "score": row.get("score"),
        "score_text": score_text,
        "status": row.get("status"),
        "signal_count": row.get("signal_count"),
        "signal_keys": row.get("signal_keys") or [],
        "primary_signal_key": row.get("primary_signal_key"),
        "primary_signal_label": row.get("primary_signal_label"),
        "error_message": row.get("error_message"),
        "display": " / ".join(display_parts),
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
            "trade_date": ranking.get("trade_date"),
            "target_trade_date": ranking.get("target_trade_date"),
            "is_current": ranking.get("is_current"),
            "current_stock_count": ranking.get("current_stock_count"),
            "stale_stock_count": ranking.get("stale_stock_count"),
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


def _watchlist_overview_stance(
    *,
    ranked_count: int,
    positive_ratio: float | None,
    average_change_pct: float | None,
    average_score: float | None,
) -> str:
    if ranked_count <= 0:
        return "資料不足"

    positive_ratio = positive_ratio if positive_ratio is not None else 0.0
    average_change_pct = average_change_pct if average_change_pct is not None else 0.0
    average_score = average_score if average_score is not None else 0.0

    if average_change_pct >= 1.0 and positive_ratio >= 0.55:
        return "偏多"
    if average_change_pct <= -1.0 and positive_ratio <= 0.45:
        return "偏空"
    if positive_ratio >= 0.55 and average_score > 0:
        return "結構偏多"
    if positive_ratio <= 0.45 and average_score < 0:
        return "結構偏弱"
    return "多空分歧"


def _watchlist_overview_confidence(
    *,
    requested_count: int,
    ranked_count: int,
    no_data_count: int,
    error_count: int,
    stale_stock_count: int,
) -> str:
    if requested_count <= 0 or ranked_count <= 0:
        return "low"
    if no_data_count or error_count or stale_stock_count:
        return "low"
    if ranked_count < requested_count:
        return "medium"
    return "high"


def _build_watchlist_overview(context: dict[str, Any], scan_data: dict[str, Any]) -> dict[str, Any]:
    ranking = (context.get("data") or {}).get("ranking") or {}
    results = ranking.get("results") or []
    scope = context.get("scope") or {}
    group_name = scope.get("group_name") or f"Watchlist #{scope.get('group_id') or '-'}"
    valid_rows = [
        row
        for row in results
        if row.get("status") not in {"error", "no_data"}
        and (_numeric(row.get("change_pct")) is not None or _numeric(row.get("score")) is not None)
    ]

    changes = [value for row in valid_rows if (value := _numeric(row.get("change_pct"))) is not None]
    scores = [value for row in valid_rows if (value := _numeric(row.get("score"))) is not None]
    up_count = sum(1 for value in changes if value > 0)
    down_count = sum(1 for value in changes if value < 0)
    flat_count = sum(1 for value in changes if value == 0)
    average_change_pct = sum(changes) / len(changes) if changes else None
    average_score = sum(scores) / len(scores) if scores else None
    positive_ratio = up_count / len(changes) if changes else None
    requested_count = int(ranking.get("requested_stock_count") or len(results) or 0)
    ranked_count = int(ranking.get("ranked_count") or len(valid_rows) or 0)
    no_data_count = int(ranking.get("no_data_count") or 0)
    error_count = int(ranking.get("error_count") or 0)
    stale_stock_count = int(ranking.get("stale_stock_count") or 0)
    stance = _watchlist_overview_stance(
        ranked_count=ranked_count,
        positive_ratio=positive_ratio,
        average_change_pct=average_change_pct,
        average_score=average_score,
    )
    confidence = _watchlist_overview_confidence(
        requested_count=requested_count,
        ranked_count=ranked_count,
        no_data_count=no_data_count,
        error_count=error_count,
        stale_stock_count=stale_stock_count,
    )

    positive_rows = [
        row
        for row in valid_rows
        if (_numeric(row.get("score")) or 0.0) > 0 or (_numeric(row.get("change_pct")) or 0.0) > 0
    ]
    negative_rows = [
        row
        for row in valid_rows
        if (_numeric(row.get("score")) or 0.0) < 0 or (_numeric(row.get("change_pct")) or 0.0) < 0
    ]
    strong_rows = sorted(
        positive_rows or valid_rows,
        key=lambda row: (
            _numeric(row.get("score")) or 0.0,
            _numeric(row.get("change_pct")) or 0.0,
        ),
        reverse=True,
    )[:5]
    weak_rows = sorted(
        negative_rows or valid_rows,
        key=lambda row: (
            _numeric(row.get("change_pct")) or 0.0,
            _numeric(row.get("score")) or 0.0,
        ),
    )[:5]
    watch_rows = [
        row
        for row in valid_rows
        if row.get("limit_status")
        or (_numeric(row.get("change_pct")) is not None and abs(_numeric(row.get("change_pct")) or 0.0) >= 5)
        or row.get("primary_signal_key") in _ATTENTION_SIGNAL_KEYS
    ][:5]
    pullback_rows = _unique_rows(
        [
            row
            for row in [*strong_rows, *watch_rows]
            if row.get("limit_status") == "limit_up"
            or (
                _numeric(row.get("change_pct")) is not None
                and (_numeric(row.get("change_pct")) or 0.0) >= WATCHLIST_PULLBACK_CHANGE_PCT
            )
        ]
    )
    follow_rows = [
        row
        for row in strong_rows
        if _row_identity(row) not in {_row_identity(pullback_row) for pullback_row in pullback_rows}
    ]
    if not follow_rows:
        follow_rows = strong_rows
    defensive_rows = _unique_rows(weak_rows)

    missing = list(context.get("missing") or [])
    as_of = context.get("as_of") or ranking.get("trade_date")
    data_line = _human_data_limit_line(
        missing=missing,
        requested_count=requested_count,
        no_data_count=no_data_count,
        error_count=error_count,
        stale_stock_count=stale_stock_count,
    )

    breadth_line = (
        f"{group_name} {stance}；"
        f"上漲 {up_count}、下跌 {down_count}"
    )
    if average_change_pct is not None:
        breadth_line += f"，平均漲跌 {_pct_display(average_change_pct)}"
    breadth_line += "。"

    human_sections = [
        {"label": "結論", "text": breadth_line},
        {"label": "追蹤", "text": _row_labels(follow_rows)},
        {"label": "等回測", "text": _row_labels(pullback_rows)},
        {"label": "保守", "text": _row_labels(defensive_rows)},
        {"label": "資料", "text": data_line},
    ]
    human_lines = [f"{section['label']}：{section['text']}" for section in human_sections]

    return {
        "kind": "watchlist_sector_overview",
        "group_id": scope.get("group_id"),
        "group_name": group_name,
        "stance": stance,
        "confidence": confidence,
        "as_of": as_of,
        "display": breadth_line,
        "answer_outline": human_lines,
        "human_answer": {
            "kind": "watchlist_sector_human_answer",
            "style": "concise_watchlist_brief",
            "max_items_per_section": HUMAN_ANSWER_MAX_ITEMS,
            "sections": human_sections,
            "lines": human_lines,
            "text": "\n".join(human_lines),
            "guidance": (
                "Use this field for user-facing answers. Keep raw dataset keys and freshness internals hidden "
                "unless the user explicitly asks for debugging details."
            ),
        },
        "breadth": {
            "requested_stock_count": requested_count,
            "ranked_count": ranked_count,
            "up_count": up_count,
            "down_count": down_count,
            "flat_count": flat_count,
            "no_data_count": no_data_count,
            "error_count": error_count,
            "stale_stock_count": stale_stock_count,
            "positive_ratio": positive_ratio,
            "average_change_pct": average_change_pct,
            "average_change_pct_text": _pct_display(average_change_pct),
            "average_score": average_score,
        },
        "strong_rows": [_compact_watchlist_row(row) for row in strong_rows],
        "weak_rows": [_compact_watchlist_row(row) for row in weak_rows],
        "watch_rows": [_compact_watchlist_row(row) for row in watch_rows],
        "follow_rows": [_compact_watchlist_row(row) for row in follow_rows[:HUMAN_ANSWER_MAX_ITEMS]],
        "pullback_rows": [_compact_watchlist_row(row) for row in pullback_rows[:HUMAN_ANSWER_MAX_ITEMS]],
        "defensive_rows": [_compact_watchlist_row(row) for row in defensive_rows[:HUMAN_ANSWER_MAX_ITEMS]],
        "data_status": {
            "is_complete": not (missing or no_data_count or error_count or stale_stock_count),
            "line": data_line,
            "missing": missing,
            "human_missing": _dataset_human_labels(missing),
            "ranking": scan_data.get("ranking") or {},
        },
    }


def build_stock_brief(
    db: Session,
    stock_id: str,
    *,
    strategy_profile: str = "short_term_momentum",
    branch_days: int = 5,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    context = tools.read_stock_context(
        db=db,
        stock_id=stock_id,
        branch_days=branch_days,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
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
    strategy_profile: str = "short_term_momentum",
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
    overview = _build_watchlist_overview(context, scan_data)
    scan_data["overview"] = overview
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
        "summary": _compact_watchlist_summary(context, overview=overview),
    }
