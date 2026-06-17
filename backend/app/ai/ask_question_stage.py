from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai import decision_core, pipeline_progress
from app.ai.ask_stage_models import QuestionStage
from app.ai.schemas import AiAskRequest


def normalize_payload_for_resolution(
    *,
    payload: AiAskRequest,
    resolution: Any,
    request_target_id: Callable[[AiAskRequest], str | None],
    request_target_type: Callable[[AiAskRequest], str],
    resolution_target: Callable[[Any], dict[str, Any]],
) -> AiAskRequest:
    if (
        resolution.selected_scope_id != request_target_id(payload)
        or request_target_type(payload) == "auto"
    ):
        return payload.model_copy(update={"target": resolution_target(resolution)})
    return payload


def build_question_stage(
    *,
    payload: AiAskRequest,
    scope_type: str,
    server_policy: Any,
    progress: pipeline_progress.OmiPipelineProgress,
    build_policy: Callable[[AiAskRequest, Any], dict[str, Any]],
    infer_mode: Callable[[AiAskRequest, str, dict[str, Any]], str],
    normalize_analysis_horizon: Callable[[str], str],
) -> QuestionStage:
    requested_horizon = payload.analysis_horizon
    question_understanding = decision_core.understand_question(
        question=payload.question,
        requested_horizon=requested_horizon,
        strategy_profile=payload.strategy_profile,
        conversation_context=payload.conversation_context,
    )
    effective_horizon = question_understanding.analysis_horizon
    normalized_payload = payload.model_copy(update={"analysis_horizon": effective_horizon})
    policy = build_policy(normalized_payload, server_policy)
    position_context = question_understanding.position_context.as_dict()
    question_intent = question_understanding.intent
    progress.question_understood(
        question_intent=question_intent,
        effective_horizon=effective_horizon,
    )

    policy["question_intent"] = question_intent
    policy["question_understanding"] = question_understanding.as_policy_payload()
    if position_context.get("has_position_context"):
        policy["position_context"] = position_context
    policy["analysis_horizon"] = {
        "requested": requested_horizon,
        "effective": effective_horizon,
        "defaulted": normalize_analysis_horizon(requested_horizon) == "auto",
    }

    return QuestionStage(
        payload=normalized_payload,
        requested_horizon=requested_horizon,
        effective_horizon=effective_horizon,
        question_understanding=question_understanding,
        position_context=position_context,
        question_intent=question_intent,
        policy=policy,
        requested_mode=infer_mode(normalized_payload, scope_type, policy),
        auto_mode_requested=normalized_payload.mode == "auto",
    )
