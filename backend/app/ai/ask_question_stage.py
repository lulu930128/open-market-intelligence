from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.ai import decision_core, pipeline_progress, response_preferences
from app.ai.ask_stage_models import QuestionStage
from app.ai.schemas import AiAskRequest


POSITION_CONTEXT_PROMOTABLE_INTENTS = {"general", "trend_view", "risk_check"}
POSITION_CONTEXT_TOPIC_INTENTS = {"position", "risk", "stop_loss", "take_profit", "exit", "hold"}
EVIDENCE_ONLY_HINTS = (
    "只回資料",
    "只要資料",
    "只看資料",
    "只回狀態",
    "資料狀態即可",
    "不要投資建議",
    "不要投資判斷",
    "不要操作建議",
    "不要進場",
    "不要停損",
    "data only",
    "no investment advice",
    "without investment advice",
)


def _requests_evidence_only(payload: AiAskRequest) -> bool:
    if payload.output is not None:
        return payload.output == "evidence_only"
    question = payload.question.casefold()
    return any(hint.casefold() in question for hint in EVIDENCE_ONLY_HINTS)


def _positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if number <= 0 or number != number:
        return None
    return number


def _normalized_explicit_position_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}

    quantity = _positive_float(value.get("quantity"))
    cost_amount = _positive_float(value.get("cost_amount"))
    entry_price = (
        _positive_float(value.get("entry_price"))
        or _positive_float(value.get("average_cost"))
    )
    if entry_price is None and quantity is not None and cost_amount is not None:
        entry_price = cost_amount / quantity

    has_context = bool(value.get("has_position_context")) or entry_price is not None
    if not has_context:
        return {}

    result: dict[str, Any] = {
        "kind": "position_context",
        "has_position_context": True,
        "entry_price": entry_price,
        "entry_price_source": value.get("entry_price_source") or "explicit_position_context",
        "decision_topic": value.get("decision_topic") or "position",
        "position_side": value.get("position_side") or "long",
    }
    for key in (
        "source",
        "holding_id",
        "market",
        "symbol",
        "symbol_name",
        "quantity",
        "cost_amount",
        "currency",
        "strategy_horizon",
        "opened_at",
    ):
        if value.get(key) is not None:
            result[key] = value[key]
    return result


def _merge_position_context(
    inferred_context: dict[str, Any],
    explicit_context_payload: Any,
) -> dict[str, Any]:
    explicit_context = _normalized_explicit_position_context(explicit_context_payload)
    if not explicit_context:
        return inferred_context

    inferred_topic = inferred_context.get("decision_topic")
    explicit_topic = explicit_context.get("decision_topic")
    merged = {**inferred_context, **explicit_context}
    merged["has_position_context"] = True
    if inferred_topic in POSITION_CONTEXT_TOPIC_INTENTS and inferred_topic != "position":
        merged["decision_topic"] = inferred_topic
    else:
        merged["decision_topic"] = explicit_topic or "position"
    return merged


def normalize_payload_for_resolution(
    *,
    payload: AiAskRequest,
    resolution: Any,
    request_target_id: Callable[[AiAskRequest], str | None],
    request_target_type: Callable[[AiAskRequest], str],
    resolution_target: Callable[[Any], dict[str, Any]],
) -> AiAskRequest:
    resolved_target = resolution_target(resolution)
    requested_target = payload.target if isinstance(payload.target, dict) else {}
    if (
        resolution.selected_scope_id != request_target_id(payload)
        or request_target_type(payload) == "auto"
        or (
            resolution.selected_scope_type == "data_freshness"
            and str(requested_target.get("market") or "").strip().upper()
            != str(resolved_target.get("market") or "").strip().upper()
        )
    ):
        return payload.model_copy(update={"target": resolved_target})
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
    position_context = _merge_position_context(
        question_understanding.position_context.as_dict(),
        payload.position_context,
    )
    question_intent = question_understanding.intent
    if scope_type == "data_freshness":
        question_intent = "data_freshness"
    raw_selection = (
        payload.selection if isinstance(payload.selection, dict) else {}
    )
    explicit_data_only_selection = bool(
        payload.mode == "data_only"
        and any(
            key in raw_selection
            for key in ("required", "include", "optional", "exclude")
        )
    )
    if (
        not explicit_data_only_selection
        and position_context.get("has_position_context")
        and question_intent in POSITION_CONTEXT_PROMOTABLE_INTENTS
    ):
        question_intent = "position_risk_decision"
    detected_intents = list(question_understanding.intents)
    requested_intents = [
        str(intent).strip().lower()
        for intent in payload.intents
        if str(intent).strip()
    ]
    merged_intents = list(
        dict.fromkeys([question_intent, *requested_intents, *detected_intents])
    )
    normalized_payload = payload.model_copy(
        update={
            "analysis_horizon": effective_horizon,
            "intents": merged_intents,
            "output": (
                "evidence_only"
                if _requests_evidence_only(payload)
                else payload.output
            ),
        }
    )
    policy = build_policy(normalized_payload, server_policy)
    response_preference_payload = response_preferences.build_response_preferences(
        normalized_payload.conversation_context
    )
    progress.question_understood(
        question_intent=question_intent,
        effective_horizon=effective_horizon,
    )

    question_understanding_payload = question_understanding.as_policy_payload()
    question_understanding_payload["intent"] = question_intent
    question_understanding_payload["intents"] = merged_intents
    question_understanding_payload["position_context"] = position_context
    policy["question_intent"] = question_intent
    policy["explicit_data_only_intent_lock"] = explicit_data_only_selection
    policy["question_understanding"] = question_understanding_payload
    policy["response_preferences"] = response_preference_payload
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
