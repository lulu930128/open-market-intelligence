from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai import llm, pipeline_progress
from app.ai.ask_stage_models import ModeExecutionResult
from app.ai.schemas import AiAskRequest


def effective_mode_after_freshness(
    *,
    effective_mode: str,
    freshness_result: dict[str, Any],
    scope_type: str,
    warnings: list[str],
) -> str:
    if freshness_result and not freshness_result.get("is_current", True) and effective_mode == "report":
        warnings.append(
            "Report mode skipped because local OMI data is incomplete; returned a brief instead."
        )
        return (
            "brief"
            if scope_type in {"stock", "watchlist", "us_stock", "jp_stock", "jp_index", "tw_index", "tw_futures"}
            else "data_only"
        )
    return effective_mode


def execute_mode_stage(
    *,
    db: Any,
    payload: AiAskRequest,
    scope_type: str,
    effective_mode: str,
    auto_mode_requested: bool,
    question_intent: str = "general",
    tool_runs: list[dict[str, Any]],
    warnings: list[str],
    policy: dict[str, Any] | None = None,
    progress: pipeline_progress.OmiPipelineProgress,
    read_data_only: Callable[..., tuple[str, dict[str, Any]]],
    build_brief: Callable[..., tuple[str, dict[str, Any]]],
    generate_analysis: Callable[..., tuple[str, dict[str, Any]]],
    generate_report: Callable[..., tuple[str, dict[str, Any]]],
) -> ModeExecutionResult:
    mode = effective_mode
    if mode in {"data_only", "full"}:
        action, result = progress.run_read_mode(
            mode=mode,
            operation=lambda: read_data_only(
                db,
                payload,
                scope_type,
                question_intent=question_intent,
                tool_runs=tool_runs,
                policy=policy,
            ),
        )
    elif mode == "brief":
        action, result = progress.run_read_mode(
            mode=mode,
            operation=lambda: build_brief(
                db,
                payload,
                scope_type,
                question_intent=question_intent,
                tool_runs=tool_runs,
                policy=policy,
            ),
        )
    elif mode == "analysis":
        try:
            action, result = progress.run_read_mode(
                mode=mode,
                operation=lambda: generate_analysis(
                    db,
                    payload,
                    scope_type,
                    question_intent=question_intent,
                    tool_runs=tool_runs,
                    policy=policy,
                ),
            )
        except llm.OpenAILLMError as exc:
            if not auto_mode_requested:
                raise
            warnings.append(
                f"Auto analysis skipped because LLM generation failed; returned a brief instead: {exc}"
            )
            mode = "brief"
            progress.llm_fallback_to_brief()
            action, result = progress.run_read_mode(
                mode=mode,
                operation=lambda: build_brief(
                    db,
                    payload,
                    scope_type,
                    question_intent=question_intent,
                    tool_runs=tool_runs,
                    policy=policy,
                ),
            )
    elif mode == "report":
        action, result = progress.run_read_mode(
            mode=mode,
            operation=lambda: generate_report(
                db,
                payload,
                scope_type,
                question_intent=question_intent,
                tool_runs=tool_runs,
                policy=policy,
            ),
        )
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    return ModeExecutionResult(
        effective_mode=mode,
        action=action,
        result=result,
        warnings=warnings,
    )
