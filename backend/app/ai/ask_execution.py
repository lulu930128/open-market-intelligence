from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai import (
    agentic_tools,
    decision_core,
    freshness,
    orchestrator,
    reports,
    response_preferences,
    scope_resolution,
    tools,
)
from app.ai import ask_policy
from app.ai.schemas import AiAskRequest


_request_target_id = scope_resolution._request_target_id
_looks_like_stock_id = scope_resolution._looks_like_stock_id
_require_scope_id = ask_policy._require_scope_id
_require_group_id = ask_policy._require_group_id


def _include_tw_intraday(payload: AiAskRequest, *, policy: dict[str, Any] | None = None) -> bool:
    can_external_fetch = (
        bool(policy.get("can_external_fetch"))
        if isinstance(policy, dict)
        else bool(payload.allow_external_fetch)
    )
    market_data_params = payload.market_data_params if isinstance(payload.market_data_params, dict) else {}
    if "include_intraday" in market_data_params:
        return bool(market_data_params.get("include_intraday")) and can_external_fetch

    return decision_core.include_tw_intraday(
        question=payload.question,
        requested_horizon=payload.analysis_horizon,
        strategy_profile=payload.strategy_profile,
        allow_external_fetch=can_external_fetch,
    )


def _watchlist_radar_mode(question_intent: str) -> str:
    if question_intent in {"risk_check", "exit_decision"}:
        return "risk"
    if question_intent == "entry_decision":
        return "momentum"
    return "action"


def _response_preferences(payload: AiAskRequest) -> dict[str, Any]:
    return response_preferences.build_response_preferences(payload.conversation_context)


def _read_data_only(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "market":
        return "omi.read_market_overview", tools.read_market_overview(
            db=db,
            limit=payload.market_limit,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            market_data_params=payload.market_data_params,
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
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            market_data_params=payload.market_data_params,
        )

    if scope_type == "tw_index":
        index_id = _require_scope_id(payload, "tw_index")
        return "omi.read_tw_index_context", tools.read_tw_index_context(
            db=db,
            index_id=index_id,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            market_data_params=payload.market_data_params,
        )

    if scope_type == "tw_futures":
        symbol = _require_scope_id(payload, "tw_futures")
        return "omi.read_tw_futures_context", tools.read_tw_futures_context(
            db=db,
            symbol=symbol,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.read_us_stock_context", agentic_tools.read_us_stock_context(
            db=db,
            symbol=symbol,
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
        )

    if scope_type in {"jp_stock", "jp_index"}:
        symbol = _require_scope_id(payload, scope_type)
        return (
            "omi.read_jp_index_context" if scope_type == "jp_index" else "omi.read_jp_stock_context"
        ), agentic_tools.read_jp_stock_context(
            db=db,
            symbol=symbol,
            is_index=scope_type == "jp_index",
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
        )

    if scope_type in {"kr_stock", "kr_index"}:
        symbol = _require_scope_id(payload, scope_type)
        return (
            "omi.read_kr_index_context" if scope_type == "kr_index" else "omi.read_kr_stock_context"
        ), agentic_tools.read_kr_stock_context(
            db=db,
            symbol=symbol,
            is_index=scope_type == "kr_index",
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
        )

    if scope_type in {"crypto_market", "crypto_asset"}:
        asset = _require_scope_id(payload, "crypto_asset") if scope_type == "crypto_asset" else None
        return (
            "omi.read_crypto_asset_context" if scope_type == "crypto_asset" else "omi.read_crypto_market_context"
        ), agentic_tools.read_crypto_context(
            db=db,
            asset=asset,
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
            context_limit=payload.context_limit,
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
    policy: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "market":
        return "omi.generate_market_brief", reports.build_market_brief(
            db=db,
            limit=payload.market_limit,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            market_data_params=payload.market_data_params,
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_brief", reports.build_stock_brief(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            market_data_params=payload.market_data_params,
            response_preferences=_response_preferences(payload),
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
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_brief", reports.build_us_stock_brief(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
            response_preferences=_response_preferences(payload),
        )

    if scope_type in {"jp_stock", "jp_index"}:
        symbol = _require_scope_id(payload, scope_type)
        return (
            "omi.generate_jp_index_brief" if scope_type == "jp_index" else "omi.generate_jp_stock_brief"
        ), reports.build_jp_stock_brief(
            db=db,
            symbol=symbol,
            is_index=scope_type == "jp_index",
            strategy_profile=payload.strategy_profile,
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
            response_preferences=_response_preferences(payload),
        )

    if scope_type in {"kr_stock", "kr_index"}:
        symbol = _require_scope_id(payload, scope_type)
        return (
            "omi.generate_kr_index_brief" if scope_type == "kr_index" else "omi.generate_kr_stock_brief"
        ), reports.build_kr_stock_brief(
            db=db,
            symbol=symbol,
            is_index=scope_type == "kr_index",
            strategy_profile=payload.strategy_profile,
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
            response_preferences=_response_preferences(payload),
        )

    if scope_type in {"crypto_market", "crypto_asset"}:
        asset = _require_scope_id(payload, "crypto_asset") if scope_type == "crypto_asset" else None
        return (
            "omi.generate_crypto_asset_brief" if scope_type == "crypto_asset" else "omi.generate_crypto_market_brief"
        ), reports.build_crypto_brief(
            db=db,
            asset=asset,
            strategy_profile=payload.strategy_profile,
            tool_runs=tool_runs,
            market_data_params=payload.market_data_params,
            context_limit=payload.context_limit,
            response_preferences=_response_preferences(payload),
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs, policy=policy)


def _generate_report(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_report", orchestrator.generate_stock_llm_report(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            response_preferences=_response_preferences(payload),
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
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_llm_report", orchestrator.generate_us_stock_llm_report(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
            response_preferences=_response_preferences(payload),
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs, policy=policy)


def _generate_analysis(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_analysis", orchestrator.generate_stock_llm_analysis(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload, policy=policy),
            analysis_horizon=payload.analysis_horizon,
            response_preferences=_response_preferences(payload),
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
            response_preferences=_response_preferences(payload),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_llm_analysis", orchestrator.generate_us_stock_llm_analysis(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
            response_preferences=_response_preferences(payload),
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs, policy=policy)


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
