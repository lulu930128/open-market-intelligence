from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai import pipeline_progress
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
) -> ToolStageState:
    tool_plan: dict[str, Any] = {}
    tool_runs: list[dict[str, Any]] = []
    current_freshness = freshness_result
    warnings: list[Any] = []

    if scope_type == "us_stock" and (payload.allow_external_fetch or policy.get("can_plan_tools")):
        tool_session = progress.run_tool_session(
            scope_type=scope_type,
            operation=lambda: run_us_stock_tool_session(
                question=payload.question,
                symbol=require_scope_id(payload, "us_stock"),
                target=resolution_target(resolution),
                policy=policy,
                raw_budget=payload.tool_budget,
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
        and current_freshness
        and current_freshness.get("refresh_recommended")
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
