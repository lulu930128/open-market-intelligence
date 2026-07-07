from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai import decision_core, pipeline_progress
from app.ai.ask_stage_models import ResponseAssembly
from app.ai.schemas import AiAskRequest


def assemble_response_analysis(
    *,
    result: dict[str, Any],
    freshness_result: dict[str, Any],
    warnings: list[str],
    resolution: Any,
    effective_mode: str,
    policy: dict[str, Any],
    requested_mode: str,
    question_understanding: decision_core.QuestionUnderstanding,
    question_intent: str,
    position_context: dict[str, Any],
    scope_type: str,
    response_target: dict[str, Any],
    progress: pipeline_progress.OmiPipelineProgress,
    extract_list: Callable[[dict[str, Any], str], list[Any]],
    extract_analysis_digest: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    clarification_dict: Callable[[Any], dict[str, Any]],
    build_next_actions: Callable[..., list[dict[str, Any]]],
    build_position_decision: Callable[..., dict[str, Any]],
    try_attach_position_decision_llm: Callable[..., dict[str, Any]],
    build_consumer_human_answer: Callable[..., dict[str, Any]],
    build_reasoning_steps: Callable[..., list[dict[str, str]]],
    payload: AiAskRequest,
) -> ResponseAssembly:
    result_warnings = extract_list(result, "warnings")
    result_missing = extract_list(result, "missing")
    result_source_refs = extract_list(result, "source_refs")
    analysis_digest = extract_analysis_digest(result, policy)
    freshness_warnings = extract_list(freshness_result, "warnings")
    freshness_missing = extract_list(freshness_result, "missing")
    clarification = clarification_dict(resolution)
    next_actions = build_next_actions(
        resolution=resolution,
        clarification=clarification,
        freshness_result=freshness_result,
        effective_mode=effective_mode,
        policy=policy,
        requested_mode=requested_mode,
    )
    answer_ready = not clarification.get("required")
    if any(action.get("type") == "connect_us_stock_context" for action in next_actions):
        warnings.append(
            "ADR-specific evidence is available through target.type=us_stock; answered from the resolved Taiwan stock context first."
        )

    combined_missing = list(dict.fromkeys(result_missing + freshness_missing))
    combined_warnings = list(dict.fromkeys(warnings + freshness_warnings + result_warnings))
    position_decision = {}
    if question_intent == "position_risk_decision" and scope_type == "stock":
        position_decision = build_position_decision(
            question=payload.question,
            position_context=position_context,
            target=response_target,
            result=result,
            analysis_digest=analysis_digest,
            missing=combined_missing,
            warnings=combined_warnings,
        )
        position_decision = try_attach_position_decision_llm(
            payload=payload,
            policy=policy,
            target=response_target,
            position_context=position_context,
            position_decision=position_decision,
            analysis_digest=analysis_digest,
            missing=combined_missing,
            warnings=combined_warnings,
        )

    consumer_human_answer = build_consumer_human_answer(
        question_intent=question_intent,
        target=response_target,
        result=result,
        analysis_digest=analysis_digest,
        missing=combined_missing,
        warnings=combined_warnings,
        position_decision=position_decision,
        response_preferences=(
            policy.get("response_preferences")
            if isinstance(policy.get("response_preferences"), dict)
            else {}
        ),
    )
    reasoning_steps = build_reasoning_steps(
        question_intent=question_intent,
        position_context=position_context,
        position_decision=position_decision,
        analysis_digest=analysis_digest,
    )
    response_analysis = dict(analysis_digest)
    result_data = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact_evidence = result_data.get("compact") if isinstance(result_data.get("compact"), dict) else {}
    if compact_evidence:
        response_analysis["compact_evidence"] = compact_evidence
    response_analysis["question_intent"] = question_intent
    response_analysis["question_understanding"] = question_understanding.as_policy_payload()
    response_preferences = policy.get("response_preferences")
    if isinstance(response_preferences, dict):
        response_analysis["response_preferences"] = response_preferences
    if position_context.get("has_position_context"):
        response_analysis["position_context"] = position_context
    if position_decision:
        response_analysis["position_decision"] = position_decision
    if reasoning_steps:
        response_analysis["reasoning_steps"] = reasoning_steps
        progress.reasoning_steps(reasoning_steps)
    if consumer_human_answer:
        response_analysis["human_answer"] = consumer_human_answer

    return ResponseAssembly(
        response_analysis=response_analysis,
        reasoning_steps=reasoning_steps,
        combined_missing=combined_missing,
        combined_warnings=combined_warnings,
        result_source_refs=result_source_refs,
        analysis_digest=analysis_digest,
        next_actions=next_actions,
        clarification=clarification,
        answer_ready=answer_ready,
        position_decision=position_decision,
        consumer_human_answer=consumer_human_answer,
    )
