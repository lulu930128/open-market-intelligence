from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai import agentic_tools, decision_core, freshness, orchestrator, reports, scope_resolution, tools
from app.ai import ask_policy
from app.ai.schemas import AiAskRequest


_request_target_id = scope_resolution._request_target_id
_looks_like_stock_id = scope_resolution._looks_like_stock_id
_require_scope_id = ask_policy._require_scope_id
_require_group_id = ask_policy._require_group_id


def _include_tw_intraday(payload: AiAskRequest) -> bool:
    return decision_core.include_tw_intraday(
        question=payload.question,
        requested_horizon=payload.analysis_horizon,
        strategy_profile=payload.strategy_profile,
        allow_external_fetch=payload.allow_external_fetch,
    )


def _watchlist_radar_mode(question_intent: str) -> str:
    if question_intent in {"risk_check", "exit_decision"}:
        return "risk"
    if question_intent == "entry_decision":
        return "momentum"
    return "action"


def _read_data_only(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "market":
        return "omi.read_market_overview", tools.read_market_overview(
            db=db,
            limit=payload.market_limit,
        )

    if scope_type == "data_freshness":
        target_id = _request_target_id(payload)
        stock_id = target_id if _looks_like_stock_id(target_id) else None
        return "omi.read_data_freshness", tools.read_data_freshness(db=db, stock_id=stock_id)

    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.read_stock_context", tools.read_stock_context(
            db=db,
            stock_id=stock_id,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
        )

    if scope_type == "tw_index":
        index_id = _require_scope_id(payload, "tw_index")
        return "omi.read_tw_index_context", tools.read_tw_index_context(
            db=db,
            index_id=index_id,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
        )

    if scope_type == "tw_futures":
        symbol = _require_scope_id(payload, "tw_futures")
        return "omi.read_tw_futures_context", tools.read_tw_futures_context(
            db=db,
            symbol=symbol,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.read_us_stock_context", agentic_tools.read_us_stock_context(
            db=db,
            symbol=symbol,
            tool_runs=tool_runs,
        )

    group_id = _require_group_id(payload)
    return "omi.read_watchlist_context", tools.read_watchlist_context(
        db=db,
        group_id=group_id,
        include_children=payload.include_children,
        enabled_only=payload.enabled_only,
        rank_by=payload.rank_by,
        sort_order=payload.sort_order,
        limit=payload.context_limit,
        radar_mode=_watchlist_radar_mode(question_intent),
    )


def _build_brief(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_brief", reports.build_stock_brief(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
        )

    if scope_type == "watchlist":
        group_id = _require_group_id(payload)
        return "omi.generate_watchlist_brief", reports.build_watchlist_brief(
            db=db,
            group_id=group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=_watchlist_radar_mode(question_intent),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_brief", reports.build_us_stock_brief(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs)


def _generate_report(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_report", orchestrator.generate_stock_llm_report(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
        )

    if scope_type == "watchlist":
        group_id = _require_group_id(payload)
        return "omi.generate_watchlist_llm_report", orchestrator.generate_watchlist_llm_report(
            db=db,
            group_id=group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=_watchlist_radar_mode(question_intent),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_llm_report", orchestrator.generate_us_stock_llm_report(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs)


def _generate_analysis(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_analysis", orchestrator.generate_stock_llm_analysis(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
        )

    if scope_type == "watchlist":
        group_id = _require_group_id(payload)
        return "omi.generate_watchlist_llm_analysis", orchestrator.generate_watchlist_llm_analysis(
            db=db,
            group_id=group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
            radar_mode=_watchlist_radar_mode(question_intent),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_llm_analysis", orchestrator.generate_us_stock_llm_analysis(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs)


def _check_freshness(db: Session, payload: AiAskRequest, scope_type: str) -> dict[str, Any]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        stock_freshness = freshness.check_stock_data_freshness(
            db=db,
            stock_id=stock_id,
        )
        return agentic_tools.attach_us_overnight_gaps_to_tw_stock_freshness(
            db,
            stock_id=stock_id,
            stock_freshness=stock_freshness,
        )

    if scope_type == "watchlist":
        return freshness.check_watchlist_data_freshness(
            db=db,
            group_id=_require_group_id(payload),
            include_children=payload.include_children,
            enabled_only=payload.enabled_only,
        )

    if scope_type == "us_stock":
        return agentic_tools.scan_us_stock_gaps(
            db=db,
            symbol=_require_scope_id(payload, "us_stock"),
            question=payload.question,
        )

    return {}
