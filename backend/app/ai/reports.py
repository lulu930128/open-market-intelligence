from typing import Any

from sqlalchemy.orm import Session

from app.ai import agentic_tools
from app.ai import memory as ai_memory
from app.ai import prompts, tools
from app.ai.us_decision_adapter import build_us_stock_decision_adapter


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


def _price_display(value: Any) -> str | None:
    number = _numeric(value)
    if number is None:
        return None
    if float(number).is_integer():
        return f"{number:,.0f}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _level_price_display(level: Any) -> str | None:
    if not isinstance(level, dict):
        return None
    return _price_display(level.get("price"))


def _zone_display(zone: Any) -> str | None:
    if not isinstance(zone, dict):
        return None
    low = _price_display(zone.get("low"))
    high = _price_display(zone.get("high"))
    if low and high:
        return f"{low}-{high}"
    return low or high


def _compact_technical_levels(levels: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(levels, dict) or levels.get("kind") != "technical_price_levels":
        return {}
    entry = levels.get("entry") if isinstance(levels.get("entry"), dict) else {}
    risk = levels.get("risk") if isinstance(levels.get("risk"), dict) else {}
    compact = {
        "kind": levels.get("kind"),
        "version": levels.get("version"),
        "latest": _price_display(levels.get("latest_price")),
        "preferred_entry": _zone_display(entry.get("preferred_zone")),
        "aggressive_entry": _zone_display(entry.get("aggressive_zone")),
        "conservative_entry": _zone_display(entry.get("conservative_zone")),
        "do_not_chase_above": _level_price_display(entry.get("do_not_chase_above")),
        "breakout_confirm_above": _level_price_display(entry.get("breakout_confirm_above")),
        "short_stop": _level_price_display(risk.get("short_stop")),
        "technical_invalidation": _level_price_display(risk.get("technical_invalidation")),
        "context": levels.get("context") if isinstance(levels.get("context"), dict) else {},
        "validation": levels.get("validation") if isinstance(levels.get("validation"), dict) else {},
        "resistance": levels.get("resistance") if isinstance(levels.get("resistance"), dict) else {},
    }
    return {key: value for key, value in compact.items() if value not in (None, "", {})}


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
    technical_levels = data.get("technical_levels") if isinstance(data.get("technical_levels"), dict) else {}
    decision_evidence = data.get("decision_evidence") if isinstance(data.get("decision_evidence"), dict) else {}

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

    levels_summary = _compact_technical_levels(technical_levels)
    if levels_summary:
        level_parts = []
        if levels_summary.get("preferred_entry"):
            level_parts.append(f"preferred_entry={levels_summary['preferred_entry']}")
        if levels_summary.get("do_not_chase_above"):
            level_parts.append(f"do_not_chase_above={levels_summary['do_not_chase_above']}")
        if levels_summary.get("breakout_confirm_above"):
            level_parts.append(f"breakout_confirm_above={levels_summary['breakout_confirm_above']}")
        if levels_summary.get("short_stop"):
            level_parts.append(f"short_stop={levels_summary['short_stop']}")
        if levels_summary.get("technical_invalidation"):
            level_parts.append(f"invalidation={levels_summary['technical_invalidation']}")
        if level_parts:
            highlights.append("Technical levels: " + ", ".join(level_parts) + ".")

    market_session = decision_evidence.get("market_session") if isinstance(decision_evidence.get("market_session"), dict) else {}
    if market_session.get("is_trading_day") is False and market_session.get("summary"):
        highlights.append(f"Market session: {market_session['summary']}")

    volatility = decision_evidence.get("recent_volatility") if isinstance(decision_evidence.get("recent_volatility"), dict) else {}
    if volatility.get("summary"):
        highlights.append(f"Recent volatility: {volatility['summary']}")

    fundamentals = decision_evidence.get("fundamentals") if isinstance(decision_evidence.get("fundamentals"), dict) else {}
    revenue = fundamentals.get("monthly_revenue") if isinstance(fundamentals.get("monthly_revenue"), dict) else {}
    if revenue.get("summary"):
        highlights.append(f"Fundamental revenue: {revenue['summary']}")

    indicator_quality = decision_evidence.get("indicator_quality") if isinstance(decision_evidence.get("indicator_quality"), dict) else {}
    indicator_warnings = indicator_quality.get("warnings") if isinstance(indicator_quality.get("warnings"), list) else []
    for warning in indicator_warnings[:2]:
        checks.append(str(warning))

    checks.extend(context.get("missing", []))

    return {
        "highlights": highlights,
        "analysis": analysis_summary,
        "technical_levels": levels_summary,
        "decision_evidence": decision_evidence,
        "next_checks": list(dict.fromkeys(checks)),
    }


def _compact_watchlist_summary(
    context: dict[str, Any],
    *,
    overview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ranking = (context.get("data") or {}).get("ranking") or {}
    radar = (context.get("data") or {}).get("radar") or {}
    results = ranking.get("results") or []
    top_rows = [_compact_watchlist_row(row) for row in results[:5]]
    bottom_rows = [_compact_watchlist_row(row) for row in results[-5:]] if len(results) > 5 else []

    return {
        "overview": overview or {},
        "radar": _compact_watchlist_radar(radar),
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


def _compact_us_stock_summary(context: dict[str, Any]) -> dict[str, Any]:
    summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
    data = context.get("data") if isinstance(context.get("data"), dict) else {}
    daily_rows = data.get("daily_prices") if isinstance(data.get("daily_prices"), list) else []
    sec_fundamentals = (
        data.get("sec_fundamentals") if isinstance(data.get("sec_fundamentals"), dict) else {}
    )
    corporate_actions = (
        data.get("corporate_actions") if isinstance(data.get("corporate_actions"), list) else []
    )
    short_volume = data.get("short_volume") if isinstance(data.get("short_volume"), list) else []
    profile = summary.get("profile") if isinstance(summary.get("profile"), dict) else {}

    latest_daily = daily_rows[0] if daily_rows else {}
    previous_daily = daily_rows[1] if len(daily_rows) > 1 else {}
    latest_close = _numeric(latest_daily.get("close_price"))
    previous_close = _numeric(previous_daily.get("close_price"))
    change_pct = None
    if latest_close is not None and previous_close not in {None, 0.0}:
        change_pct = ((latest_close - float(previous_close)) / float(previous_close)) * 100.0

    highlights: list[str] = []
    checks: list[str] = []
    if latest_close is not None:
        change_text = f" change={_pct_display(change_pct)}" if change_pct is not None else ""
        highlights.append(
            "Latest US close "
            f"{latest_close} on {latest_daily.get('trade_date')}.{change_text}"
        )
    else:
        checks.append("US daily price data is missing.")

    if profile:
        highlights.append(
            "Profile "
            f"{profile.get('company_name') or '-'} / {profile.get('sector') or '-'} / "
            f"{profile.get('industry') or '-'}."
        )
    else:
        checks.append("US company profile is missing.")

    metric_count = sec_fundamentals.get("metric_count")
    if metric_count:
        highlights.append(
            "SEC fundamentals "
            f"{metric_count} metrics, latest filed {sec_fundamentals.get('latest_filed_date') or '-'}."
        )
    else:
        checks.append("SEC company facts are missing.")

    if short_volume:
        latest_short = short_volume[0]
        highlights.append(
            "FINRA short volume "
            f"{_pct_display(latest_short.get('short_ratio'))} on {latest_short.get('trade_date')}."
        )
    else:
        checks.append("FINRA short volume is missing.")

    if corporate_actions:
        highlights.append(f"Corporate actions rows={len(corporate_actions)}.")

    checks.extend(context.get("missing") or [])
    return {
        "highlights": highlights,
        "intraday": summary.get("intraday"),
        "latest": {
            "trade_date": latest_daily.get("trade_date"),
            "close": latest_close,
            "previous_close": previous_close,
            "change_pct": change_pct,
            "change_pct_text": _pct_display(change_pct),
            "volume": latest_daily.get("trade_volume"),
        },
        "coverage": {
            "daily_rows": len(daily_rows),
            "has_profile": bool(profile),
            "sec_metric_count": metric_count or 0,
            "corporate_action_count": len(corporate_actions),
            "short_volume_rows": len(short_volume),
        },
        "next_checks": list(dict.fromkeys(checks)),
    }


def _compact_market_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "stock_id": row.get("stock_id"),
        "stock_name": row.get("stock_name"),
        "industry": row.get("industry"),
        "close_price": row.get("close_price"),
        "price_change": row.get("price_change"),
        "change_pct": row.get("change_pct"),
        "trade_value": row.get("trade_value"),
        "trade_volume": row.get("trade_volume"),
    }


def _compact_market_industry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "industry": row.get("industry"),
        "count": row.get("count"),
        "advance_count": row.get("advance_count"),
        "decline_count": row.get("decline_count"),
        "average_change_pct": row.get("average_change_pct"),
        "trade_value": row.get("trade_value"),
        "top_stock_id": row.get("top_stock_id"),
        "top_stock_name": row.get("top_stock_name"),
    }


def _market_row_labels(rows: list[dict[str, Any]], *, include_pct: bool = True) -> str:
    labels: list[str] = []
    for row in rows[:HUMAN_ANSWER_MAX_ITEMS]:
        label = _row_label(row)
        pct = _pct_display(row.get("change_pct")) if include_pct else None
        labels.append(f"{label} {pct}" if pct else label)
    return "、".join(labels) if labels else "無可用資料"


def _compact_market_summary(overview: dict[str, Any]) -> dict[str, Any]:
    data = overview.get("data") if isinstance(overview.get("data"), dict) else {}
    breadth = data.get("breadth") if isinstance(data.get("breadth"), dict) else {}
    sample_breadth = data.get("sample_breadth") if isinstance(data.get("sample_breadth"), dict) else {}
    distribution = data.get("distribution") if isinstance(data.get("distribution"), dict) else {}
    index_intraday = data.get("index_intraday") if isinstance(data.get("index_intraday"), dict) else {}
    slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    top_gainers = [
        _compact_market_row(row)
        for row in data.get("top_gainers", [])
        if isinstance(row, dict)
    ]
    top_losers = [
        _compact_market_row(row)
        for row in data.get("top_losers", [])
        if isinstance(row, dict)
    ]
    value_leaders = [
        _compact_market_row(row)
        for row in data.get("value_leaders", [])
        if isinstance(row, dict)
    ]
    top_industries = [
        _compact_market_industry(row)
        for row in data.get("top_industries", [])
        if isinstance(row, dict)
    ]
    weak_industries = [
        _compact_market_industry(row)
        for row in data.get("weak_industries", [])
        if isinstance(row, dict)
    ]
    industry_strength_label = str(
        data.get("industry_strength_label") or "產業相對表現"
    )
    sample_count = sample_breadth.get("total_count")
    sample_scope_label = (
        f"OMI {sample_count} 檔追蹤樣本"
        if isinstance(sample_count, int)
        else "OMI 追蹤樣本"
    )

    advance_count = breadth.get("advance_count")
    decline_count = breadth.get("decline_count")
    unchanged_count = breadth.get("unchanged_count")
    positive_ratio_text = _pct_display(
        (breadth.get("positive_ratio") or 0) * 100
        if breadth.get("positive_ratio") is not None
        else None
    )
    average_change_text = _pct_display(breadth.get("average_change_pct"))
    breadth_label = str(breadth.get("label") or "市場廣度")
    breadth_line = (
        f"上漲 {advance_count}、下跌 {decline_count}、持平 {unchanged_count}"
        if advance_count is not None and decline_count is not None
        else "市場廣度資料不足"
    )
    if positive_ratio_text:
        breadth_line += f"，上漲比 {positive_ratio_text}"
    if average_change_text:
        breadth_line += f"，平均漲跌 {average_change_text}"

    industry_labels = [
        str(row.get("industry"))
        for row in top_industries[:HUMAN_ANSWER_MAX_ITEMS]
        if row.get("industry")
    ]
    human_sections = [
        {"label": breadth_label, "text": breadth_line},
        {"label": f"{sample_scope_label}上漲股", "text": _market_row_labels(top_gainers)},
        {"label": f"{sample_scope_label}弱勢股", "text": _market_row_labels(top_losers)},
        {
            "label": f"{sample_scope_label}成交值",
            "text": _market_row_labels(value_leaders, include_pct=False),
        },
        {
            "label": f"{sample_scope_label}{industry_strength_label}",
            "text": "、".join(industry_labels) or "無可用資料",
        },
    ]
    if index_intraday.get("enabled"):
        index_labels = []
        for item in index_intraday.get("indices", [])[:2]:
            if not isinstance(item, dict):
                continue
            quote = item.get("quote") if isinstance(item.get("quote"), dict) else {}
            index_id = item.get("index_id") or quote.get("index_id")
            price = quote.get("price")
            change_pct = _pct_display(quote.get("change_pct"))
            if index_id and price is not None:
                index_labels.append(f"{index_id} {price}{' ' + change_pct if change_pct else ''}")
        human_sections.insert(
            1,
            {
                "label": "指數盤中",
                "text": "、".join(index_labels) if index_labels else "盤中指數資料不足",
            },
        )
    human_lines = [f"{section['label']}：{section['text']}" for section in human_sections]

    return {
        "kind": "market_brief_summary",
        "as_of": overview.get("as_of"),
        "highlights": human_lines,
        "human_answer": {
            "kind": "market_brief_human_answer",
            "style": "concise_market_brief",
            "sections": human_sections,
            "lines": human_lines,
            "text": "\n".join(human_lines),
        },
        "breadth": breadth,
        "sample_breadth": sample_breadth,
        "distribution": distribution,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "value_leaders": value_leaders,
        "top_industries": top_industries,
        "weak_industries": weak_industries,
        "sample_top_gainers": top_gainers,
        "sample_top_losers": top_losers,
        "sample_value_leaders": value_leaders,
        "sample_top_industries": top_industries,
        "sample_weak_industries": weak_industries,
        "industry_strength_label": industry_strength_label,
        "index_intraday": index_intraday,
        "slots": slots,
        "next_checks": overview.get("missing", []),
    }


def build_market_brief(
    db: Session,
    *,
    limit: int = 10,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
    market_data_params: dict[str, Any] | None = None,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overview = tools.read_market_overview(
        db=db,
        limit=limit,
        include_intraday=include_intraday or analysis_horizon == "intraday",
        market_data_params=market_data_params,
    )
    summary = _compact_market_summary(overview)
    overview_data = overview.get("data") if isinstance(overview.get("data"), dict) else {}
    return {
        **overview,
        "kind": "market_brief",
        "data": {
            "summary": summary,
            "breadth": summary["breadth"],
            "distribution": summary["distribution"],
            "top_gainers": summary["top_gainers"],
            "top_losers": summary["top_losers"],
            "value_leaders": summary["value_leaders"],
            "top_industries": summary["top_industries"],
            "weak_industries": summary["weak_industries"],
            "index_intraday": summary["index_intraday"],
            "slots": summary["slots"],
            "compact": overview_data.get("compact") or {},
        },
        "summary": summary,
        "response_preferences": response_preferences or {},
    }


def _build_us_stock_analysis(context: dict[str, Any], requested_horizon: str) -> dict[str, Any]:
    compact = _compact_us_stock_summary(context)
    latest = compact.get("latest") if isinstance(compact.get("latest"), dict) else {}
    coverage = compact.get("coverage") if isinstance(compact.get("coverage"), dict) else {}
    missing = context.get("missing") or []
    adapter = build_us_stock_decision_adapter(context, requested_horizon)
    score = int(adapter["selected_score"])
    title = str(adapter["selected_title"])
    confidence = str(adapter["selected_confidence"])
    horizon = str(adapter["selected_horizon"])
    summary_parts = []
    if latest.get("close") is not None:
        summary_parts.append(
            f"收盤 {latest.get('close')}，漲跌幅 {latest.get('change_pct_text') or '-'}"
        )
    summary_parts.append(
        "覆蓋："
        f"日線 {coverage.get('daily_rows') or 0} 筆、"
        f"SEC {coverage.get('sec_metric_count') or 0} 指標、"
        f"short volume {coverage.get('short_volume_rows') or 0} 筆"
    )
    if missing:
        summary_parts.append(f"缺口 {len(missing)} 項")

    return {
        "requested_horizon": requested_horizon,
        "selected_horizon": horizon,
        "selected_timeframe": "us_daily",
        "selected_score": score,
        "selected_title": title,
        "selected_summary": "；".join(summary_parts),
        "selected_confidence": confidence,
        "decision_adapter": adapter,
        "scores": {
            "intraday": score if horizon == "intraday" else None,
            "short": score,
            "swing": score,
            "long": score if coverage.get("sec_metric_count") else None,
        },
        "components": adapter["components"],
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


def _compact_watchlist_radar_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row.get("rank"),
        "stock_id": row.get("stock_id"),
        "stock_name": row.get("stock_name"),
        "label": _row_label(row),
        "bucket": row.get("bucket"),
        "bucket_label": row.get("bucket_label"),
        "urgency": row.get("urgency"),
        "action_label": row.get("action_label"),
        "reason": row.get("reason"),
        "trade_date": row.get("trade_date"),
        "time": row.get("time"),
        "close": row.get("close"),
        "change_pct": row.get("change_pct"),
        "change_pct_text": _pct_display(row.get("change_pct")),
        "score": row.get("score"),
        "status": row.get("status"),
        "signal_labels": list(row.get("signal_labels") or [])[:5],
        "matched_signal_keys": list(row.get("matched_signal_keys") or [])[:5],
        "primary_signal_label": row.get("primary_signal_label"),
        "stale": bool(row.get("stale")),
    }


def _compact_watchlist_radar(radar: dict[str, Any], *, item_limit: int = 8) -> dict[str, Any]:
    if not isinstance(radar, dict) or not radar:
        return {}

    buckets = [
        {
            "key": bucket.get("key"),
            "label": bucket.get("label"),
            "count": bucket.get("count"),
        }
        for bucket in (radar.get("buckets") or [])
        if isinstance(bucket, dict) and int(bucket.get("count") or 0) > 0
    ]
    results = [
        _compact_watchlist_radar_item(row)
        for row in (radar.get("results") or [])[:item_limit]
        if isinstance(row, dict)
    ]

    return {
        "mode": radar.get("mode"),
        "requested_stock_count": radar.get("requested_stock_count"),
        "matched_count": radar.get("matched_count"),
        "radar_count": radar.get("radar_count"),
        "trade_date": radar.get("trade_date"),
        "target_trade_date": radar.get("target_trade_date"),
        "is_current": radar.get("is_current"),
        "stale_stock_count": radar.get("stale_stock_count"),
        "buckets": buckets,
        "results": results,
    }


def _radar_item_labels(rows: list[dict[str, Any]], *, limit: int = HUMAN_ANSWER_MAX_ITEMS) -> str:
    labels: list[str] = []

    for row in rows[:limit]:
        label = _row_label(row)
        action = str(row.get("action_label") or "").strip()
        urgency = str(row.get("urgency") or "").strip()
        suffix_parts = []

        if urgency == "high":
            suffix_parts.append("高")
        if action:
            suffix_parts.append(action)

        labels.append(
            f"{label}（{'，'.join(suffix_parts)}）" if suffix_parts else label
        )

    return "、".join(labels) if labels else "暫無明確名單"


def _build_watchlist_radar_sections(radar: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(radar, dict) or not radar:
        return []

    rows = [row for row in (radar.get("results") or []) if isinstance(row, dict)]
    buckets = [bucket for bucket in (radar.get("buckets") or []) if isinstance(bucket, dict)]
    matched_count = int(radar.get("matched_count") or 0)

    if not rows and matched_count <= 0:
        return [{"label": "雷達", "text": "目前沒有符合條件的雷達項目。"}]

    bucket_text = "、".join(
        f"{bucket.get('label')} {bucket.get('count')}"
        for bucket in buckets[:3]
        if bucket.get("label") and int(bucket.get("count") or 0) > 0
    )
    radar_text = f"{matched_count} 檔命中"
    if bucket_text:
        radar_text += f"；{bucket_text}"
    if rows:
        radar_text += f"；優先看 {_radar_item_labels(rows)}"
    radar_text += "。"

    return [{"label": "雷達", "text": radar_text}]


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


def _build_watchlist_scan_data(
    context: dict[str, Any],
    *,
    radar_limit: int = 8,
) -> dict[str, Any]:
    ranking = (context.get("data") or {}).get("ranking") or {}
    radar = (context.get("data") or {}).get("radar") or {}
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
        "radar": _compact_watchlist_radar(radar, item_limit=max(1, radar_limit)),
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
    radar = (context.get("data") or {}).get("radar") or {}
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
    radar_summary = _compact_watchlist_radar(radar)
    radar_rows = radar_summary.get("results") or []
    radar_sections = _build_watchlist_radar_sections(radar_summary)

    breadth_line = (
        f"{group_name} {stance}；"
        f"上漲 {up_count}、下跌 {down_count}"
    )
    if average_change_pct is not None:
        breadth_line += f"，平均漲跌 {_pct_display(average_change_pct)}"
    breadth_line += "。"

    human_sections = [
        {"label": "結論", "text": breadth_line},
        *radar_sections,
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
        "radar": radar_summary,
        "radar_rows": radar_rows,
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
    market_data_params: dict[str, Any] | None = None,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = tools.read_stock_context(
        db=db,
        stock_id=stock_id,
        branch_days=branch_days,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
        market_data_params=market_data_params,
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
        "response_preferences": response_preferences or {},
        "prompt": {
            "system": prompts.build_system_prompt(
                profile.key,
                response_preferences=response_preferences,
            ),
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


def build_us_stock_brief(
    db: Session,
    symbol: str,
    *,
    strategy_profile: str = "short_term_momentum",
    analysis_horizon: str = "swing",
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = agentic_tools.read_us_stock_context(
        db=db,
        symbol=symbol,
        tool_runs=tool_runs,
        market_data_params=market_data_params,
    )
    profile = prompts.get_strategy_profile(strategy_profile)
    normalized_symbol = ((context.get("scope") or {}).get("target") or {}).get("id") or symbol
    memories = _memory_context(
        db=db,
        scope_type="us_stock",
        scope_id=str(normalized_symbol),
        strategy_profile=profile.key,
    )
    data = dict(context.get("data") or {})
    data["analysis"] = _build_us_stock_analysis(context, analysis_horizon)

    return {
        **context,
        "kind": "us_stock_brief",
        "data": data,
        "strategy_profile": profile.key,
        "response_preferences": response_preferences or {},
        "prompt": {
            "system": prompts.build_system_prompt(
                profile.key,
                response_preferences=response_preferences,
            ),
            "profile": {
                "key": profile.key,
                "label": profile.label,
                "description": profile.description,
                "focus_points": list(profile.focus_points),
                "risk_notes": list(profile.risk_notes),
            },
            "memories": memories,
        },
        "summary": _compact_us_stock_summary({**context, "data": data}),
    }


def _compact_cross_market_summary(context: dict[str, Any]) -> dict[str, Any]:
    data = context.get("data") if isinstance(context.get("data"), dict) else {}
    compact = data.get("compact") if isinstance(data.get("compact"), dict) else {}
    target = compact.get("target") if isinstance(compact.get("target"), dict) else (
        (context.get("scope") or {}).get("target") if isinstance(context.get("scope"), dict) else {}
    )
    quote = compact.get("quote") if isinstance(compact.get("quote"), dict) else {}
    resources = compact.get("resources") if isinstance(compact.get("resources"), dict) else {}
    freshness = compact.get("freshness_by_domain") if isinstance(compact.get("freshness_by_domain"), dict) else {}
    summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
    missing = list(context.get("missing") or [])
    warnings = list(context.get("warnings") or [])
    price = quote.get("price") if quote else summary.get("latest_close") or summary.get("latest_price")
    change_pct = quote.get("change_pct_24h") if quote else None
    label = (target or {}).get("label") or (target or {}).get("id") or "-"
    title = "local-cache evidence"
    if missing:
        title = "local-cache evidence with gaps"
    display_parts = [str(label)]
    if price is not None:
        display_parts.append(f"price {price}")
    pct_text = _pct_display(change_pct)
    if pct_text:
        display_parts.append(f"24h {pct_text}")
    if missing:
        display_parts.append(f"missing {len(missing)} dataset(s)")

    human_lines = [
        " / ".join(display_parts),
        f"resources: {resources}",
        "read path: local cache only; use bounded refresh endpoints before relying on missing/stale data.",
    ]
    if warnings:
        human_lines.append(f"warnings: {warnings[:3]}")

    return {
        "kind": "cross_market_brief_summary",
        "target": target or {},
        "quote": quote,
        "resources": resources,
        "freshness": freshness,
        "title": title,
        "display": " / ".join(display_parts),
        "missing": missing,
        "warning_count": len(warnings),
        "human_answer": {
            "kind": "cross_market_human_answer",
            "style": "concise_evidence_brief",
            "lines": human_lines,
            "text": "\n".join(str(item) for item in human_lines),
        },
    }


def build_jp_stock_brief(
    db: Session,
    symbol: str,
    *,
    is_index: bool = False,
    strategy_profile: str = "short_term_momentum",
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = agentic_tools.read_jp_stock_context(
        db=db,
        symbol=symbol,
        is_index=is_index,
        tool_runs=tool_runs,
        market_data_params=market_data_params,
    )
    profile = prompts.get_strategy_profile(strategy_profile)
    target = (context.get("scope") or {}).get("target") or {}
    scope_type = "jp_index" if is_index else "jp_stock"
    scope_id = str(target.get("id") or symbol)
    memories = _memory_context(
        db=db,
        scope_type=scope_type,
        scope_id=scope_id,
        strategy_profile=profile.key,
    )

    return {
        **context,
        "kind": "jp_index_brief" if is_index else "jp_stock_brief",
        "strategy_profile": profile.key,
        "response_preferences": response_preferences or {},
        "prompt": {
            "system": prompts.build_system_prompt(
                profile.key,
                response_preferences=response_preferences,
            ),
            "profile": {
                "key": profile.key,
                "label": profile.label,
                "description": profile.description,
                "focus_points": list(profile.focus_points),
                "risk_notes": list(profile.risk_notes),
            },
            "memories": memories,
        },
        "summary": _compact_cross_market_summary(context),
    }


def build_kr_stock_brief(
    db: Session,
    symbol: str,
    *,
    is_index: bool = False,
    strategy_profile: str = "short_term_momentum",
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = agentic_tools.read_kr_stock_context(
        db=db,
        symbol=symbol,
        is_index=is_index,
        tool_runs=tool_runs,
        market_data_params=market_data_params,
    )
    profile = prompts.get_strategy_profile(strategy_profile)
    target = (context.get("scope") or {}).get("target") or {}
    scope_type = "kr_index" if is_index else "kr_stock"
    scope_id = str(target.get("id") or symbol)
    memories = _memory_context(
        db=db,
        scope_type=scope_type,
        scope_id=scope_id,
        strategy_profile=profile.key,
    )

    return {
        **context,
        "kind": "kr_index_brief" if is_index else "kr_stock_brief",
        "strategy_profile": profile.key,
        "response_preferences": response_preferences or {},
        "prompt": {
            "system": prompts.build_system_prompt(
                profile.key,
                response_preferences=response_preferences,
            ),
            "profile": {
                "key": profile.key,
                "label": profile.label,
                "description": profile.description,
                "focus_points": list(profile.focus_points),
                "risk_notes": list(profile.risk_notes),
            },
            "memories": memories,
        },
        "summary": _compact_cross_market_summary(context),
    }


def build_crypto_brief(
    db: Session,
    *,
    asset: str | None = None,
    strategy_profile: str = "short_term_momentum",
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    context_limit: int = 100,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = agentic_tools.read_crypto_context(
        db=db,
        asset=asset,
        tool_runs=tool_runs,
        market_data_params=market_data_params,
        context_limit=context_limit,
    )
    profile = prompts.get_strategy_profile(strategy_profile)
    target = (context.get("scope") or {}).get("target") or {}
    scope_type = str(target.get("type") or ("crypto_asset" if asset else "crypto_market"))
    scope_id = str(target.get("id") or asset or "market")
    memories = _memory_context(
        db=db,
        scope_type=scope_type,
        scope_id=scope_id,
        strategy_profile=profile.key,
    )

    return {
        **context,
        "kind": "crypto_asset_brief" if asset else "crypto_market_brief",
        "strategy_profile": profile.key,
        "response_preferences": response_preferences or {},
        "prompt": {
            "system": prompts.build_system_prompt(
                profile.key,
                response_preferences=response_preferences,
            ),
            "profile": {
                "key": profile.key,
                "label": profile.label,
                "description": profile.description,
                "focus_points": list(profile.focus_points),
                "risk_notes": list(profile.risk_notes),
            },
            "memories": memories,
        },
        "summary": _compact_cross_market_summary(context),
    }


def build_watchlist_brief(
    db: Session,
    group_id: int,
    *,
    strategy_profile: str = "short_term_momentum",
    rank_by: str = "score",
    sort_order: str = "desc",
    radar_mode: str = "action",
    radar_limit: int = 8,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_radar_limit = max(1, min(int(radar_limit or 8), 24))
    context = tools.read_watchlist_context(
        db=db,
        group_id=group_id,
        rank_by=rank_by,
        sort_order=sort_order,
        radar_mode=radar_mode,
        radar_limit=max(12, normalized_radar_limit),
    )
    scan_data = _build_watchlist_scan_data(
        context,
        radar_limit=normalized_radar_limit,
    )
    context_data = context.get("data") if isinstance(context.get("data"), dict) else {}
    if isinstance(context_data.get("compact"), dict):
        scan_data["compact"] = context_data["compact"]
    if isinstance(context_data.get("slots"), dict):
        scan_data["slots"] = context_data["slots"]
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
        "response_preferences": response_preferences or {},
        "prompt": {
            "system": prompts.build_system_prompt(
                profile.key,
                response_preferences=response_preferences,
            ),
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
