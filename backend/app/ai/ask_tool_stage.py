from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai import capability_contract, pipeline_progress
from app.ai.ask_stage_models import ToolStageState
from app.ai.schemas import AiAskRequest


def apply_freshness_guard(
    *,
    policy: dict[str, Any],
    freshness_result: dict[str, Any],
) -> None:
    if not freshness_result:
        return
    policy["freshness_guard"] = {
        "is_current": freshness_result.get("is_current"),
        "stale_stock_count": freshness_result.get("stale_stock_count"),
        "missing": freshness_result.get("missing", []),
        "expected_dates": freshness_result.get("expected_dates", {}),
    }


def execute_tool_stages(
    *,
    scope_type: str,
    payload: AiAskRequest,
    resolution: Any,
    policy: dict[str, Any],
    query_plan: dict[str, Any] | None = None,
    freshness_result: dict[str, Any],
    progress: pipeline_progress.OmiPipelineProgress,
    progress_callback: pipeline_progress.ProgressCallback | None,
    resolution_target: Callable[[Any], dict[str, Any]],
    require_scope_id: Callable[[AiAskRequest, str], str],
    require_group_id: Callable[[AiAskRequest], int],
    refresh_before_answer_enabled: Callable[[AiAskRequest], bool],
    run_us_stock_tool_session: Callable[..., dict[str, Any]],
    run_tw_stock_tool_session: Callable[..., dict[str, Any]],
    run_tw_watchlist_tool_session: Callable[..., dict[str, Any]],
    run_crypto_asset_tool_session: Callable[..., dict[str, Any]] | None = None,
    run_regional_market_tool_session: Callable[..., dict[str, Any]] | None = None,
) -> ToolStageState:
    query_plan = query_plan or {}
    tool_plan: dict[str, Any] = {}
    tool_runs: list[dict[str, Any]] = []
    current_freshness = freshness_result
    warnings: list[Any] = []
    selected_v4_capabilities = (
        tuple(
            dict.fromkeys(
                [
                    *(
                        str(value)
                        for value in query_plan.get("selected_capabilities") or []
                    ),
                    *(
                        str(value)
                        for value in query_plan.get(
                            "optional_selected_capabilities"
                        )
                        or []
                    ),
                ]
            )
        )
        if payload.contract_version == "omi.decision.v4"
        else None
    )
    if (
        selected_v4_capabilities is not None
        and payload.continuation.get("selected_action_ids")
    ):
        selected_v4_capabilities = capability_contract.selected_fill_capabilities(
            continuation=payload.continuation,
            selection=(
                query_plan.get("selection")
                if isinstance(query_plan.get("selection"), dict)
                else {}
            ),
            target=resolution_target(resolution),
            scope_type=scope_type,
        )

    if (
        scope_type == "us_stock"
        and query_plan.get("realtime_policy") != "cache_only"
        and (payload.allow_external_fetch or policy.get("can_plan_tools"))
    ):
        tool_session = progress.run_tool_session(
            scope_type=scope_type,
            operation=lambda: run_us_stock_tool_session(
                question=payload.question,
                symbol=require_scope_id(payload, "us_stock"),
                target=resolution_target(resolution),
                policy=policy,
                raw_budget=payload.tool_budget,
                requested_capabilities=selected_v4_capabilities,
                progress_callback=progress_callback,
            ),
        )
        tool_plan = tool_session["tool_plan"]
        tool_runs = tool_session["tool_runs"]
        warnings.extend(tool_session.get("warnings") or [])
        current_freshness = tool_session.get("freshness") or current_freshness

    if (
        scope_type == "crypto_asset"
        and run_crypto_asset_tool_session is not None
        and selected_v4_capabilities is not None
        and query_plan.get("realtime_policy") != "cache_only"
        and payload.allow_external_fetch
        and query_plan.get("external_refresh_allowed", True)
    ):
        tool_session = progress.run_tool_session(
            scope_type=scope_type,
            operation=lambda: run_crypto_asset_tool_session(
                asset=require_scope_id(payload, "crypto_asset"),
                target=resolution_target(resolution),
                policy=policy,
                raw_budget=payload.tool_budget,
                requested_capabilities=selected_v4_capabilities,
                selection=(
                    query_plan.get("selection")
                    if isinstance(query_plan.get("selection"), dict)
                    else {}
                ),
                progress_callback=progress_callback,
            ),
        )
        tool_plan = tool_session["tool_plan"]
        tool_runs = tool_session["tool_runs"]
        warnings.extend(tool_session.get("warnings") or [])
        current_freshness = tool_session.get("freshness") or current_freshness

    regional_params = (
        payload.market_data_params
        if isinstance(payload.market_data_params, dict)
        else {}
    )
    regional_intraday_requested = (
        bool(regional_params.get("include_intraday"))
        if "include_intraday" in regional_params
        else payload.analysis_horizon == "intraday"
    )
    continuation_selected = bool(
        payload.continuation.get("selected_action_ids")
    )
    if (
        scope_type in {"jp_stock", "jp_index", "kr_stock", "kr_index"}
        and run_regional_market_tool_session is not None
        and refresh_before_answer_enabled(payload)
        and payload.allow_external_fetch
        and query_plan.get("realtime_policy") != "cache_only"
        and query_plan.get("external_refresh_allowed", True)
        and current_freshness
        and (
            current_freshness.get("refresh_recommended")
            or regional_intraday_requested
            or continuation_selected
        )
    ):
        market = "JP" if scope_type.startswith("jp_") else "KR"
        is_index = scope_type.endswith("_index")
        tool_session = progress.run_tool_session(
            scope_type=scope_type,
            operation=lambda: run_regional_market_tool_session(
                market=market,
                target_id=require_scope_id(payload, scope_type),
                is_index=is_index,
                target=resolution_target(resolution),
                policy=policy,
                raw_budget=payload.tool_budget,
                existing_freshness=current_freshness,
                requested_capabilities=selected_v4_capabilities,
                include_intraday=regional_intraday_requested,
                force_selected_capabilities=continuation_selected,
                progress_callback=progress_callback,
            ),
        )
        tool_plan = tool_session["tool_plan"]
        tool_runs = tool_session["tool_runs"]
        warnings.extend(tool_session.get("warnings") or [])
        current_freshness = tool_session.get("freshness") or current_freshness

    if (
        scope_type == "stock"
        and refresh_before_answer_enabled(payload)
        and payload.allow_external_fetch
        and query_plan.get("realtime_policy") != "cache_only"
        and current_freshness
        and current_freshness.get("refresh_recommended")
        and query_plan.get("external_refresh_allowed", True)
    ):
        tool_session = progress.run_tool_session(
            scope_type=scope_type,
            operation=lambda: run_tw_stock_tool_session(
                question=payload.question,
                stock_id=require_scope_id(payload, "stock"),
                target=resolution_target(resolution),
                policy=policy,
                raw_budget=payload.tool_budget,
                existing_freshness=current_freshness,
                requested_capabilities=selected_v4_capabilities,
                progress_callback=progress_callback,
            ),
        )
        tool_plan = tool_session["tool_plan"]
        tool_runs = tool_session["tool_runs"]
        warnings.extend(tool_session.get("warnings") or [])
        current_freshness = tool_session.get("freshness") or current_freshness

    if (
        scope_type == "watchlist"
        and refresh_before_answer_enabled(payload)
        and payload.allow_external_fetch
        and current_freshness
        and current_freshness.get("refresh_recommended")
    ):
        tool_session = progress.run_tool_session(
            scope_type=scope_type,
            operation=lambda: run_tw_watchlist_tool_session(
                group_id=require_group_id(payload),
                target=resolution_target(resolution),
                policy=policy,
                raw_budget=payload.tool_budget,
                existing_freshness=current_freshness,
                include_children=payload.include_children,
                enabled_only=payload.enabled_only,
                progress_callback=progress_callback,
            ),
        )
        tool_plan = tool_session["tool_plan"]
        tool_runs = tool_session["tool_runs"]
        warnings.extend(tool_session.get("warnings") or [])
        current_freshness = tool_session.get("freshness") or current_freshness

    return ToolStageState(
        tool_plan=tool_plan,
        tool_runs=tool_runs,
        freshness_result=current_freshness,
        warnings=warnings,
    )
