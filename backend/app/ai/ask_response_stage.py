from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai import answer_composer, decision_contract, decision_core, decision_engine, pipeline_progress
from app.ai.ask_stage_models import ResponseAssembly
from app.ai.schemas import AiAskRequest


POSITION_DECISION_SCOPE_TYPES = {"stock", "us_stock", "jp_stock", "kr_stock"}
PRICE_LEVEL_DECISION_INTENTS = {"entry_decision", "position_risk_decision", "risk_check"}


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
    result_data = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact_evidence = (
        result_data.get("compact")
        if isinstance(result_data.get("compact"), dict)
        else {}
    )
    if compact_evidence:
        analysis_digest["compact_evidence"] = compact_evidence
    technical_levels = (
        analysis_digest.get("technical_levels")
        if isinstance(analysis_digest.get("technical_levels"), dict)
        else {}
    )
    price_level_validation = (
        technical_levels.get("validation")
        if isinstance(technical_levels.get("validation"), dict)
        else {}
    )
    requested_position_side = str(position_context.get("position_side") or "long").strip().lower()
    validation_position_side = str(price_level_validation.get("position_side") or "long").strip().lower()
    price_level_side_mismatch = bool(
        question_intent in PRICE_LEVEL_DECISION_INTENTS
        and price_level_validation
        and requested_position_side != validation_position_side
    )
    price_level_blocked = bool(
        question_intent in PRICE_LEVEL_DECISION_INTENTS
        and price_level_validation
        and (
            price_level_validation.get("decision_ready") is False
            or price_level_side_mismatch
        )
    )
    if price_level_blocked:
        result_missing = list(result_missing) + ["technical_price_level_safety"]
        warnings.append(
            "Technical price levels were withheld because the position side does not match the validated level model."
            if price_level_side_mismatch
            else "Technical price levels were withheld from executable decision output because entry and risk invariants did not both pass."
        )
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
    position_math = {}
    if (
        question_intent == "position_risk_decision"
        and scope_type in POSITION_DECISION_SCOPE_TYPES
    ):
        position_math = decision_engine.build_position_math(
            position_context=position_context,
            result=result,
        )
    position_decision = {}
    if (
        not price_level_blocked
        and question_intent == "position_risk_decision"
        and scope_type in POSITION_DECISION_SCOPE_TYPES
    ):
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

    response_preferences = (
        policy.get("response_preferences")
        if isinstance(policy.get("response_preferences"), dict)
        else {}
    )
    consumer_human_answer = build_consumer_human_answer(
        question_intent=question_intent,
        target=response_target,
        result=result,
        analysis_digest=analysis_digest,
        missing=combined_missing,
        warnings=combined_warnings,
        position_decision=position_decision,
        response_preferences=response_preferences,
    )
    blocked_sections: list[str] = []
    if price_level_blocked and consumer_human_answer:
        original_answer = dict(consumer_human_answer)
        safety_answer = answer_composer.build_price_level_safety_answer(
            target=response_target,
            validation=price_level_validation,
            missing=combined_missing,
            warnings=combined_warnings,
            position_math=position_math,
            analysis_digest=analysis_digest,
            response_preferences=response_preferences,
        )
        consumer_human_answer = {
            **original_answer,
            "source": safety_answer.get("source") or original_answer.get("source"),
            "headline": safety_answer.get("headline") or original_answer.get("headline"),
            "summary": safety_answer.get("summary") or original_answer.get("summary"),
            "risks": safety_answer.get("risks") or original_answer.get("risks"),
            "counter_evidence": safety_answer.get("counter_evidence") or [],
            "data_limits": safety_answer.get("data_limits") or original_answer.get("data_limits"),
            "position_math": position_math or None,
            "text": safety_answer.get("text") or original_answer.get("text"),
        }
        consumer_human_answer["action_plan"] = []
        for unsafe_key in (
            "entry_conditions",
            "entry_zone",
            "stop_loss",
            "take_profit",
            "position_sizing",
        ):
            consumer_human_answer.pop(unsafe_key, None)
        blocked_sections.extend(
            [
                "stop_loss",
                "technical_invalidation",
                "trade_recommendation",
            ]
        )
        consumer_human_answer["blocked_sections"] = list(blocked_sections)
    reasoning_steps = build_reasoning_steps(
        question_intent=question_intent,
        position_context=position_context,
        position_decision=position_decision,
        analysis_digest=analysis_digest,
    )
    response_analysis = dict(analysis_digest)
    if compact_evidence:
        response_analysis["compact_evidence"] = compact_evidence
    question_understanding_payload = question_understanding.as_policy_payload()
    question_understanding_payload["intent"] = question_intent
    question_understanding_payload["position_context"] = position_context
    response_analysis["question_intent"] = question_intent
    response_analysis["question_understanding"] = question_understanding_payload
    response_preferences = policy.get("response_preferences")
    if isinstance(response_preferences, dict):
        response_analysis["response_preferences"] = response_preferences
    if position_context.get("has_position_context"):
        response_analysis["position_context"] = position_context
    if position_decision:
        response_analysis["position_decision"] = position_decision
    if position_math:
        response_analysis["position_math"] = position_math
    if reasoning_steps:
        response_analysis["reasoning_steps"] = reasoning_steps
        progress.reasoning_steps(reasoning_steps)
    if consumer_human_answer:
        response_analysis["human_answer"] = consumer_human_answer
        response_analysis["decision_contract"] = decision_contract.build_decision_contract(
            question_intent=question_intent,
            target=response_target,
            human_answer=consumer_human_answer,
            freshness_result=freshness_result,
            missing=combined_missing,
            warnings=combined_warnings,
            answer_ready=answer_ready,
            decision_ready=(
                not price_level_blocked
                and question_intent
                in {
                    "entry_decision",
                    "exit_decision",
                    "position_risk_decision",
                    "risk_check",
                }
            ),
            blocked_sections=blocked_sections,
        )
    if price_level_validation:
        response_analysis["price_level_validation"] = price_level_validation

    analysis_ready = bool(consumer_human_answer) and not clarification.get("required")
    decision_ready = bool(
        analysis_ready
        and not price_level_blocked
        and question_intent
        in {
            "entry_decision",
            "exit_decision",
            "position_risk_decision",
            "risk_check",
        }
    )
    available_sections = ["evidence"]
    if analysis_ready:
        available_sections.append("human_answer")
    if position_math:
        available_sections.append("position_math")
    if decision_ready:
        available_sections.append("decision_contract")

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
        analysis_ready=analysis_ready,
        decision_ready=decision_ready,
        blocked_sections=blocked_sections,
        available_sections=available_sections,
        position_decision=position_decision,
        consumer_human_answer=consumer_human_answer,
    )
