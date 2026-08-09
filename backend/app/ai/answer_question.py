from __future__ import annotations

from typing import Any

from app.ai import answer_evidence, answer_question_locales, decision_engine
from app.ai.answer_data_limits import generic_data_limits
from app.ai.answer_localization import (
    append_unique_texts,
    confidence_label,
    consumer_text,
    response_is_english,
    response_is_japanese,
    stance_label,
    target_fallback_label,
    text_list,
    text_value,
)
from app.ai.answer_scenarios import position_scenarios_from_decision


SUMMARY_LIMIT_DEFAULT = 3
digest_summary_lines = answer_evidence.digest_summary_lines
technical_level_summary_lines = answer_evidence.technical_level_summary_lines
english_entry_decision_with_levels = answer_evidence.english_entry_decision_with_levels
japanese_entry_decision_with_levels = answer_evidence.japanese_entry_decision_with_levels
english_trend_view_with_levels = answer_evidence.english_trend_view_with_levels
decision_evidence_summary_lines = answer_evidence.decision_evidence_summary_lines
decision_evidence_risk_lines = answer_evidence.decision_evidence_risk_lines
decision_evidence_data_lines = answer_evidence.decision_evidence_data_lines

def build_position_decision_consumer_answer(
    *,
    position_decision: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    llm_payload = position_decision.get("llm") if isinstance(position_decision.get("llm"), dict) else {}
    llm_decision = llm_payload.get("decision") if isinstance(llm_payload.get("decision"), dict) else {}

    if llm_decision:
        summary = []
        append_unique_texts(
            summary,
            text_list(llm_decision.get("position_math"), limit=2),
            limit=summary_limit,
        )
        direct_answer = text_value(llm_decision.get("direct_answer"))
        if direct_answer:
            append_unique_texts(summary, [direct_answer], limit=summary_limit)
        if not summary:
            summary = text_list(position_decision.get("summary"), limit=summary_limit)

        conditions = text_list(llm_decision.get("decision_conditions"), limit=2)
        next_steps = text_list(llm_decision.get("next_steps"), limit=2)
        action_texts = list(dict.fromkeys(conditions + next_steps))[:summary_limit]
        labels = (
            ("Condition", "Action", "Follow-up")
            if english
            else ("条件", "実行", "フォロー")
            if japanese
            else ("條件", "執行", "追蹤")
        )
        action_plan = [
            {"label": labels[index], "text": text}
            for index, text in enumerate(action_texts)
        ] or position_decision.get("action_plan", [])

        confidence = text_value(llm_decision.get("confidence")) or text_value(position_decision.get("confidence"))
        answer = {
            "kind": "consumer_market_answer",
            "style": "position_decision_summary",
            "source": "position_decision_llm",
            "intent": "position_risk_decision",
            "headline": text_value(llm_decision.get("headline")) or text_value(position_decision.get("headline")),
            "stance": position_decision.get("stance"),
            "stance_label": stance_label(position_decision.get("stance"), response_preferences),
            "confidence": confidence,
            "confidence_label": confidence_label(confidence, response_preferences),
            "summary": summary[:summary_limit],
            "action_plan": action_plan[:summary_limit],
            "risks": text_list(llm_decision.get("risk_notes"), limit=2) or position_decision.get("risks", []),
            "data_limits": (
                text_list(llm_decision.get("missing_context"), limit=2)
                + generic_data_limits(
                    missing=missing,
                    warnings=warnings,
                    response_preferences=response_preferences,
                )
            )[:3],
            "detail": text_value(llm_decision.get("direct_answer")) or text_value(position_decision.get("direct_answer")) or "",
            "position_decision": position_decision,
        }
    else:
        confidence = text_value(position_decision.get("confidence"))
        answer = {
            "kind": "consumer_market_answer",
            "style": "position_decision_summary",
            "source": "position_decision",
            "intent": "position_risk_decision",
            "headline": text_value(position_decision.get("headline")) or (
                "Position risk decision is ready"
                if english
                else "ポジションリスク判断が完了しました"
                if japanese
                else "已完成部位風險判斷"
            ),
            "stance": position_decision.get("stance"),
            "stance_label": stance_label(position_decision.get("stance"), response_preferences),
            "confidence": confidence,
            "confidence_label": confidence_label(confidence, response_preferences),
            "summary": text_list(position_decision.get("summary"), limit=summary_limit),
            "action_plan": position_decision.get("action_plan", [])[:summary_limit],
            "risks": position_decision.get("risks", []),
            "data_limits": position_decision.get("data_limits", []),
            "detail": text_value(position_decision.get("direct_answer")) or "",
            "position_decision": position_decision,
        }

    scenarios, counter_evidence = position_scenarios_from_decision(
        position_decision,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    answer["scenarios"] = scenarios
    answer["counter_evidence"] = counter_evidence
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_cross_market_consumer_answer(
    *,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision_evidence = (
        analysis_digest.get("decision_evidence")
        if isinstance(analysis_digest.get("decision_evidence"), dict)
        else {}
    )
    context = (
        decision_evidence.get("cross_market")
        if isinstance(decision_evidence.get("cross_market"), dict)
        else {}
    )
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    target_label = (
        text_value(target.get("label"))
        or text_value(target.get("id"))
        or target_fallback_label(response_preferences)
    )
    status = text_value(context.get("status")) or "missing"
    usable = context.get("decision_usable") is True and status == "ready"
    context_stance = text_value(context.get("stance")) or "unknown"
    stance = context_stance if usable else "insufficient_data"
    confidence = text_value(context.get("confidence")) or "low"
    if not usable:
        confidence = "low"

    if english:
        direction = {
            "supportive": "supportive",
            "adverse": "adverse",
            "neutral": "near neutral",
            "unknown": "unresolved",
        }.get(context_stance, context_stance)
        headline = (
            f"{target_label} cross-market context is {direction}; technical ranking is unchanged"
            if usable
            else f"{target_label} cross-market context is {status} and cannot support a directional call"
        )
        policy_line = (
            "Use this as confirmation or counter-evidence only; it does not change the technical score, Radar rank, or trade action."
        )
    elif japanese:
        direction = {
            "supportive": "支援的",
            "adverse": "逆風",
            "neutral": "中立付近",
            "unknown": "未確定",
        }.get(context_stance, context_stance)
        headline = (
            f"{target_label} のクロスマーケット情報は{direction}。テクニカル順位は変更しません"
            if usable
            else f"{target_label} のクロスマーケット情報は {status} で、方向判断には利用できません"
        )
        policy_line = (
            "確認または反証としてのみ使用し、テクニカルスコア、Radar 順位、売買行動は変更しません。"
        )
    else:
        direction = {
            "supportive": "偏支撐",
            "adverse": "偏逆風",
            "neutral": "接近中性",
            "unknown": "方向未定",
        }.get(context_stance, context_stance)
        headline = (
            f"{target_label} 跨市場脈絡{direction}；技術排名維持不變"
            if usable
            else f"{target_label} 跨市場脈絡目前為 {status}，不足以判斷方向"
        )
        policy_line = (
            "僅作確認或反證，不改變技術分數、Radar 排名或直接形成買賣動作。"
        )

    summary: list[str] = []
    title = text_value(context.get("title"))
    if title:
        summary.append(title)
    coverage = context.get("coverage") if isinstance(context.get("coverage"), dict) else {}
    usable_count = coverage.get("decision_usable_signal_count")
    configured_count = coverage.get("configured_signal_count")
    as_of = text_value(context.get("as_of"))
    if usable_count is not None or configured_count is not None or as_of:
        if english:
            summary.append(
                f"Coverage {usable_count if usable_count is not None else '-'}/{configured_count if configured_count is not None else '-'}"
                + (f"; data through {as_of}" if as_of else "")
                + "."
            )
        elif japanese:
            summary.append(
                f"利用可能 {usable_count if usable_count is not None else '-'}/{configured_count if configured_count is not None else '-'}"
                + (f"、データ日 {as_of}" if as_of else "")
                + "。"
            )
        else:
            summary.append(
                f"可用訊號 {usable_count if usable_count is not None else '-'}/{configured_count if configured_count is not None else '-'}"
                + (f"；資料日 {as_of}" if as_of else "")
                + "。"
            )
    summary.append(policy_line)

    context_warnings = list(context.get("warnings") or [])
    context_missing = list(context.get("missing") or [])
    context_limitations = list(context.get("limitations") or [])
    data_limits = generic_data_limits(
        missing=[*missing, *context_missing],
        warnings=[*warnings, *context_warnings],
        response_preferences=response_preferences,
    )
    if not usable:
        if english:
            data_limits.insert(0, f"Cross-market status is {status}; direction is withheld.")
        elif japanese:
            data_limits.insert(0, f"クロスマーケット状態は {status} のため、方向判断を保留します。")
        else:
            data_limits.insert(0, f"跨市場狀態為 {status}，暫不形成方向判斷。")

    counter_evidence = []
    if usable and context_stance == "adverse" and title:
        counter_evidence.append(title)
    answer = {
        "kind": "consumer_market_answer",
        "style": "cross_market_context_summary",
        "source": "decision_evidence.cross_market",
        "intent": "cross_market",
        "headline": headline,
        "stance": stance,
        "stance_label": stance_label(stance, response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_label(confidence, response_preferences),
        "summary": list(dict.fromkeys(summary))[:summary_limit],
        "action_plan": [],
        "scenarios": [],
        "counter_evidence": counter_evidence,
        "risks": [],
        "data_limits": list(dict.fromkeys(data_limits))[:3],
        "detail": "\n".join(summary),
        "cross_market_context": context or None,
        "context_role": "confirmation_or_counter_evidence",
        "ranking_effect": "none",
        "technical_score_effect": "none",
        "limitations": context_limitations,
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_question_aware_consumer_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if question_intent == "general" or not analysis_digest:
        return {}

    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    score = decision_engine.numeric_score(analysis_digest.get("selected_score"))
    score_text = decision_engine.score_display(score)
    confidence = text_value(analysis_digest.get("selected_confidence"))
    confidence_display = confidence_label(confidence, response_preferences)
    stance = decision_engine.stance_from_score(score)
    summary = digest_summary_lines(
        analysis_digest,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    target_label = text_value(target.get("label")) or text_value(target.get("id")) or target_fallback_label(response_preferences)
    data_limits = generic_data_limits(
        missing=missing,
        warnings=warnings,
        response_preferences=response_preferences,
    )
    decision_evidence = (
        analysis_digest.get("decision_evidence")
        if isinstance(analysis_digest.get("decision_evidence"), dict)
        else {}
    )
    evidence_summary = decision_evidence_summary_lines(
        decision_evidence,
        response_preferences=response_preferences,
    )
    evidence_risks = decision_evidence_risk_lines(
        decision_evidence,
        response_preferences=response_preferences,
    )
    answer_risks = list(evidence_risks)
    data_limits = list(
        dict.fromkeys(
            data_limits
            + decision_evidence_data_lines(
                decision_evidence,
                response_preferences=response_preferences,
            )
        )
    )
    weak_evidence = score is None or confidence == "low"
    technical_levels = (
        analysis_digest.get("technical_levels")
        if isinstance(analysis_digest.get("technical_levels"), dict)
        else {}
    )
    level_fields = decision_engine.technical_level_fields(technical_levels)
    level_numbers = decision_engine.technical_level_numbers(technical_levels)
    level_summary = (
        []
        if question_intent == "entry_decision" and level_fields
        else technical_level_summary_lines(
            technical_levels,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
    )
    if level_summary:
        summary = list(dict.fromkeys(level_summary + summary))[:summary_limit]

    context = answer_question_locales.QuestionAnswerContext(
        question_intent=question_intent,
        target_label=target_label,
        score=score,
        score_text=score_text,
        confidence=confidence,
        confidence_display=confidence_display,
        stance=stance,
        summary=summary,
        data_limits=data_limits,
        decision_evidence=decision_evidence,
        evidence_summary=evidence_summary,
        evidence_risks=evidence_risks,
        answer_risks=answer_risks,
        weak_evidence=weak_evidence,
        level_fields=level_fields,
        level_numbers=level_numbers,
        analysis_digest=analysis_digest,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    if english:
        answer = answer_question_locales.build_english_question_answer(context)
    elif japanese:
        answer = answer_question_locales.build_japanese_question_answer(context)
    else:
        answer = answer_question_locales.build_chinese_question_answer(context)
    cross_market = decision_evidence.get("cross_market")
    if isinstance(cross_market, dict) and cross_market:
        answer["cross_market_context"] = cross_market
        answer["context_role"] = "confirmation_or_counter_evidence"
        answer["ranking_effect"] = "none"
        answer["technical_score_effect"] = "none"
    return answer
