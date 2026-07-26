from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai import answer_evidence, decision_engine
from app.ai.answer_localization import consumer_text, stance_label, text_value
from app.ai.answer_scenarios import counter_evidence_from_levels, scenario_plan_from_levels


english_entry_decision_with_levels = answer_evidence.english_entry_decision_with_levels
japanese_entry_decision_with_levels = answer_evidence.japanese_entry_decision_with_levels
english_trend_view_with_levels = answer_evidence.english_trend_view_with_levels


@dataclass(frozen=True)
class QuestionAnswerContext:
    question_intent: str
    target_label: str
    score: Any
    score_text: str | None
    confidence: str | None
    confidence_display: str
    stance: str
    summary: list[str]
    data_limits: list[str]
    decision_evidence: dict[str, Any]
    evidence_summary: list[str]
    evidence_risks: list[str]
    answer_risks: list[str]
    weak_evidence: bool
    level_fields: dict[str, Any]
    level_numbers: dict[str, Any]
    analysis_digest: dict[str, Any]
    summary_limit: int
    response_preferences: dict[str, Any] | None

def build_english_question_answer(context: QuestionAnswerContext) -> dict[str, Any]:
    question_intent = context.question_intent
    target_label = context.target_label
    score = context.score
    score_text = context.score_text
    confidence = context.confidence
    confidence_display = context.confidence_display
    stance = context.stance
    summary = list(context.summary)
    data_limits = context.data_limits
    decision_evidence = context.decision_evidence
    evidence_summary = context.evidence_summary
    evidence_risks = context.evidence_risks
    answer_risks = list(context.answer_risks)
    weak_evidence = context.weak_evidence
    level_fields = context.level_fields
    level_numbers = context.level_numbers
    analysis_digest = context.analysis_digest
    summary_limit = context.summary_limit
    response_preferences = context.response_preferences
    if question_intent == "entry_decision":
        if level_fields:
            headline, entry_summary, action_plan = english_entry_decision_with_levels(
                target_label=target_label,
                score=score,
                weak_evidence=weak_evidence,
                fields=level_fields,
                numbers=level_numbers,
                summary_limit=summary_limit,
            )
            if entry_summary:
                summary = list(
                    dict.fromkeys(entry_summary[:1] + evidence_summary + entry_summary[1:] + summary)
                )[:summary_limit]
        elif weak_evidence:
            headline = f"{target_label} is not a direct buy yet; data or confidence is not strong enough"
            action_plan = [
                {"label": "Now", "text": "Do not chase; wait for the next price, volume, or indicator confirmation."},
                {
                    "label": "Entry condition",
                    "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                },
                {
                    "label": "Risk control",
                    "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                },
            ]
        elif score is not None and score >= 4:
            headline = f"{target_label} can stay on the bullish watchlist, but avoid chasing"
            action_plan = [
                {"label": "Now", "text": "Treat it as a bullish watchlist candidate, not an automatic buy signal."},
                {
                    "label": "Entry condition",
                    "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                },
                {
                    "label": "Risk control",
                    "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                },
            ]
        elif score is not None and score >= 1:
            headline = f"{target_label} is worth watching; wait for price and volume confirmation"
            action_plan = [
                {"label": "Now", "text": "Treat it as a watchlist candidate, not an automatic buy signal."},
                {
                    "label": "Entry condition",
                    "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                },
                {
                    "label": "Risk control",
                    "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                },
            ]
        elif score is not None and score <= -1:
            headline = f"{target_label} is not a direct buy setup right now"
            action_plan = [
                {"label": "Now", "text": "Do not chase; wait for the next price, volume, or indicator confirmation."},
                {
                    "label": "Entry condition",
                    "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                },
                {
                    "label": "Risk control",
                    "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                },
            ]
        else:
            headline = f"{target_label} is a wait-and-see setup until direction confirms"
            action_plan = [
                {"label": "Now", "text": "Do not chase; wait for the next price, volume, or indicator confirmation."},
                {
                    "label": "Entry condition",
                    "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                },
                {
                    "label": "Risk control",
                    "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                },
            ]
    elif question_intent == "exit_decision":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if level_fields and not weak_evidence and (level_fields.get("stop") or level_fields.get("invalidation")):
            guardrails = " / ".join(
                value
                for value in (level_fields.get("stop"), level_fields.get("invalidation"))
                if value
            )
            headline = f"{target_label} can be held conditionally, but keep guardrails at {guardrails}"
        elif weak_evidence:
            headline = f"{target_label} needs a lower-conviction decision until data confirms the hold or exit case"
        elif score is not None and score >= 2:
            headline = f"{target_label} can still be held and watched, but only while weakness conditions stay inactive"
        elif score is not None and score <= -2:
            headline = f"{target_label} is weak; check trim or exit conditions first"
        else:
            headline = f"{target_label} direction is unclear; use conditional holding rules"

        action_plan = [
            {"label": "Now", "text": "Check cost basis and position size first; do not use one score for the whole exit decision."},
            {
                "label": "Hold condition",
                "text": (
                    f"Holding is more reasonable while price stays above {level_fields['stop']} and volume does not expand into weakness."
                    if level_fields.get("stop")
                    else "Holding is more reasonable while key moving averages or prior lows hold and volume does not expand into weakness."
                ),
            },
            {
                "label": "Exit condition",
                "text": (
                    f"If price breaks {level_fields['invalidation']}, the technical thesis fails; reduce exposure or reassess."
                    if level_fields.get("invalidation")
                    else "If major support breaks, momentum turns down, or a rebound fails, reduce exposure or reassess."
                ),
            },
        ]
    elif question_intent == "risk_check":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        guardrail = level_fields.get("stop") or level_fields.get("invalidation")
        if level_fields and not weak_evidence and guardrail:
            headline = f"{target_label} risk line is {guardrail}; defend first if it breaks"
        elif weak_evidence:
            headline = f"{target_label} risk confidence is limited; use conservative guardrails first"
        elif score is not None and score <= -2:
            headline = f"{target_label} risk is elevated; prioritize defense short term"
        elif score is not None and score >= 2:
            headline = f"{target_label} risk is not clearly elevated, but invalidation still matters"
        else:
            headline = f"{target_label} is mixed; confirm risk one condition at a time"

        action_plan = [
            {
                "label": "Main risk",
                "text": (
                    f"If price breaks the short-term stop {level_fields['stop']}, the short-term view downgrades quickly."
                    if level_fields.get("stop")
                    else "If price breaks key moving averages or prior lows, the short-term view downgrades quickly."
                ),
            },
            {
                "label": "Watch",
                "text": (
                    f"Watch whether {level_fields['invalidation']} breaks, while confirming volume, institutional flow, or relative market strength."
                    if level_fields.get("invalidation")
                    else "Watch whether the next price, volume, institutional flow, or relative market strength signal turns weak at the same time."
                ),
            },
            {"label": "Risk control", "text": "Do not wait for every data point to confirm before controlling risk; shrink exposure when conditions fail."},
        ]
    elif question_intent == "trend_view":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if level_fields:
            headline, trend_summary, action_plan, trend_risks = english_trend_view_with_levels(
                target_label=target_label,
                score=score,
                weak_evidence=weak_evidence,
                fields=level_fields,
                numbers=level_numbers,
                summary_limit=summary_limit,
            )
            summary = list(dict.fromkeys(trend_summary + summary))[:summary_limit]
            answer_risks = list(dict.fromkeys(trend_risks + evidence_risks))
        elif weak_evidence:
            headline = f"{target_label} direction confidence is limited; wait for the next confirmation"
            action_plan = [
                {"label": "Trend", "text": "Treat this as directional context first, not a final conclusion from a single score or close."},
                {"label": "Support/resistance", "text": "Check key moving averages, prior lows, and volume to confirm whether support and resistance agree."},
                {"label": "Watch", "text": "Raise conviction only after price, volume, and relative market strength align."},
            ]
        elif score is not None and score >= 2:
            headline = f"{target_label} trend leans bullish; watch support and breakout continuation"
            action_plan = [
                {"label": "Trend", "text": "Use the multi-timeframe score for direction, then confirm continuation with support, resistance, and volume."},
                {"label": "Support/resistance", "text": "Watch whether pullbacks hold support and whether upper resistance is broken and held."},
                {"label": "Watch", "text": "Confirm that price, volume, moving averages, and relative market strength remain aligned."},
            ]
        elif score is not None and score <= -2:
            headline = f"{target_label} trend leans weak; watch whether support fails"
            action_plan = [
                {"label": "Trend", "text": "Downgrade the directional view first; do not force the old bullish thesis from one close."},
                {"label": "Support/resistance", "text": "Confirm whether major support has failed and whether rebound resistance is effective."},
                {"label": "Watch", "text": "If volume and momentum both weaken, recalculate the swing view."},
            ]
        else:
            headline = f"{target_label} is undecided; watch which side of support or resistance resolves first"
            action_plan = [
                {"label": "Trend", "text": f"Current score is {score_text or '-'}; use it as a direction clue, not a trade signal."},
                {"label": "Support/resistance", "text": "Check whether key moving averages, prior lows, and upper resistance converge into one signal."},
                {"label": "Watch", "text": "Raise conviction only after price, volume, and relative market strength align."},
            ]
    else:
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if weak_evidence:
            headline = f"{target_label} direction confidence is limited; wait for the next confirmation"
        elif score is not None and score >= 2:
            headline = f"{target_label} trend leans bullish, but confirmation still matters"
        elif score is not None and score <= -2:
            headline = f"{target_label} trend leans weak; do not chase against the move"
        else:
            headline = f"{target_label} direction is undecided; watch key price and volume confirmation"

        action_plan = [
            {"label": "Direction", "text": f"Current score is {score_text or '-'}; use it for directional strength, not as a direct trade signal."},
            {"label": "Confirm", "text": "Wait for price, volume, moving averages, or relative market strength to align."},
            {"label": "Invalidation", "text": "If key moving averages or momentum weaken, recalculate the trend view."},
        ]

    scenarios = scenario_plan_from_levels(
        question_intent=question_intent,
        fields=level_fields,
        numbers=level_numbers,
        score=score,
        weak_evidence=weak_evidence,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    counter_evidence = counter_evidence_from_levels(
        question_intent=question_intent,
        fields=level_fields,
        score=score,
        weak_evidence=weak_evidence,
        evidence_risks=answer_risks,
        response_preferences=response_preferences,
    )
    answer = {
        "kind": "consumer_market_answer",
        "style": "question_aware_summary",
        "source": "question_intent",
        "intent": question_intent,
        "headline": headline,
        "stance": stance,
        "stance_label": stance_label(stance, response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_display,
        "summary": summary,
        "action_plan": action_plan,
        "scenarios": scenarios,
        "counter_evidence": counter_evidence,
        "risks": list(dict.fromkeys(answer_risks + (data_limits[:2] if weak_evidence else [])))[:2],
        "data_limits": data_limits,
        "detail": text_value(analysis_digest.get("display")) or "",
        "decision_evidence": decision_evidence,
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer

def build_japanese_question_answer(context: QuestionAnswerContext) -> dict[str, Any]:
    question_intent = context.question_intent
    target_label = context.target_label
    score = context.score
    score_text = context.score_text
    confidence = context.confidence
    confidence_display = context.confidence_display
    stance = context.stance
    summary = list(context.summary)
    data_limits = context.data_limits
    decision_evidence = context.decision_evidence
    evidence_summary = context.evidence_summary
    evidence_risks = context.evidence_risks
    answer_risks = list(context.answer_risks)
    weak_evidence = context.weak_evidence
    level_fields = context.level_fields
    level_numbers = context.level_numbers
    analysis_digest = context.analysis_digest
    summary_limit = context.summary_limit
    response_preferences = context.response_preferences
    if question_intent == "entry_decision":
        if level_fields:
            headline, entry_summary, action_plan = japanese_entry_decision_with_levels(
                target_label=target_label,
                score=score,
                weak_evidence=weak_evidence,
                fields=level_fields,
                numbers=level_numbers,
                summary_limit=summary_limit,
            )
            if entry_summary:
                summary = list(
                    dict.fromkeys(entry_summary[:1] + evidence_summary + entry_summary[1:] + summary)
                )[:summary_limit]
        elif weak_evidence:
            headline = f"{target_label} はまだ直接買いではありません。データまたは信頼度が不足しています"
            action_plan = [
                {"label": "今", "text": "追いかけ買いは避け、次の価格・出来高・指標確認を待ってください。"},
                {
                    "label": "エントリー条件",
                    "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                },
                {
                    "label": "リスク管理",
                    "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                },
            ]
        elif score is not None and score >= 4:
            headline = f"{target_label} は強気候補として監視できますが、追いかけ買いは避けてください"
            action_plan = [
                {"label": "今", "text": "強気監視候補として扱い、自動的な買いシグナルとは見なさないでください。"},
                {
                    "label": "エントリー条件",
                    "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                },
                {
                    "label": "リスク管理",
                    "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                },
            ]
        elif score is not None and score >= 1:
            headline = f"{target_label} は監視候補です。価格と出来高の確認を待ってください"
            action_plan = [
                {"label": "今", "text": "監視候補として扱い、自動的な買いシグナルとは見なさないでください。"},
                {
                    "label": "エントリー条件",
                    "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                },
                {
                    "label": "リスク管理",
                    "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                },
            ]
        elif score is not None and score <= -1:
            headline = f"{target_label} は現時点で直接買いの形ではありません"
            action_plan = [
                {"label": "今", "text": "追いかけ買いは避け、次の価格・出来高・指標確認を待ってください。"},
                {
                    "label": "エントリー条件",
                    "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                },
                {
                    "label": "リスク管理",
                    "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                },
            ]
        else:
            headline = f"{target_label} は方向確認まで様子見です"
            action_plan = [
                {"label": "今", "text": "追いかけ買いは避け、次の価格・出来高・指標確認を待ってください。"},
                {
                    "label": "エントリー条件",
                    "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                },
                {
                    "label": "リスク管理",
                    "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                },
            ]
    elif question_intent == "exit_decision":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        guardrails = " / ".join(
            value
            for value in (level_fields.get("stop"), level_fields.get("invalidation"))
            if value
        )
        if level_fields and not weak_evidence and guardrails:
            headline = f"{target_label} は条件付きで保有継続できますが、{guardrails} を守る必要があります"
        elif weak_evidence:
            headline = f"{target_label} はデータ確認まで判断の強さを下げてください"
        elif score is not None and score >= 2:
            headline = f"{target_label} はまだ保有監視できますが、弱化条件が出ないことが前提です"
        elif score is not None and score <= -2:
            headline = f"{target_label} は弱めです。減らす条件または退出条件を先に確認してください"
        else:
            headline = f"{target_label} は方向が不明確です。条件付き保有ルールで判断してください"

        action_plan = [
            {"label": "今", "text": "まず取得単価とポジションサイズを確認し、単一スコアだけで退出判断をしないでください。"},
            {
                "label": "保有条件",
                "text": (
                    f"価格が {level_fields['stop']} を維持し、出来高を伴う弱さが出ない間は保有監視が比較的合理的です。"
                    if level_fields.get("stop")
                    else "主要移動平均または前回安値を維持し、出来高を伴う弱さが出ない間は保有監視が比較的合理的です。"
                ),
            },
            {
                "label": "退出条件",
                "text": (
                    f"{level_fields['invalidation']} を割る場合、テクニカル仮説は失効します。ポジションを減らすか再評価してください。"
                    if level_fields.get("invalidation")
                    else "主要サポート割れ、モメンタム低下、または反発失敗が出る場合は、ポジションを減らすか再評価してください。"
                ),
            },
        ]
    elif question_intent == "risk_check":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        guardrail = level_fields.get("stop") or level_fields.get("invalidation")
        if level_fields and not weak_evidence and guardrail:
            headline = f"{target_label} のリスクラインは {guardrail} です。割れたら防御を優先してください"
        elif weak_evidence:
            headline = f"{target_label} のリスク判断は信頼度が限られます。まず保守的なラインで管理してください"
        elif score is not None and score <= -2:
            headline = f"{target_label} はリスクが高めです。短期は防御を優先してください"
        elif score is not None and score >= 2:
            headline = f"{target_label} のリスクは明確に拡大していませんが、失効条件は重要です"
        else:
            headline = f"{target_label} は強弱混在です。リスク条件を一つずつ確認してください"

        action_plan = [
            {
                "label": "主なリスク",
                "text": (
                    f"短期損切り {level_fields['stop']} を割る場合、短期見通しはすぐ下方修正です。"
                    if level_fields.get("stop")
                    else "主要移動平均または前回安値を割る場合、短期見通しはすぐ下方修正です。"
                ),
            },
            {
                "label": "監視",
                "text": (
                    f"{level_fields['invalidation']} を割るかを見ながら、出来高、法人フロー、相対的な市場強度も確認してください。"
                    if level_fields.get("invalidation")
                    else "次の価格、出来高、法人フロー、相対的な市場強度が同時に弱くなるか確認してください。"
                ),
            },
            {"label": "リスク管理", "text": "すべてのデータ確認を待たず、条件が崩れたら先にエクスポージャーを小さくしてください。"},
        ]
    elif question_intent == "trend_view":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if weak_evidence:
            headline = f"{target_label} は方向判断の信頼度が限られます。次の確認を待ってください"
        elif score is not None and score >= 2:
            headline = f"{target_label} のトレンドは強気寄りです。サポート維持とブレイク継続を確認してください"
        elif score is not None and score <= -2:
            headline = f"{target_label} のトレンドは弱気寄りです。サポート割れを確認してください"
        else:
            headline = f"{target_label} は方向未定です。サポートか抵抗線のどちらが先に決まるか確認してください"

        action_plan = [
            {"label": "トレンド", "text": f"現在のスコアは {score_text or '-'} です。方向の手掛かりとして使い、直接の売買シグナルにはしないでください。"},
            {"label": "サポート/抵抗", "text": "主要移動平均、前回安値、上値抵抗が一つのシグナルに収束するか確認してください。"},
            {"label": "監視", "text": "価格、出来高、相対的な市場強度が同じ方向にそろってから判断を強めてください。"},
        ]
    else:
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if weak_evidence:
            headline = f"{target_label} は方向判断の信頼度が限られます。次の確認を待ってください"
        elif score is not None and score >= 2:
            headline = f"{target_label} のトレンドは強気寄りですが、確認はまだ必要です"
        elif score is not None and score <= -2:
            headline = f"{target_label} のトレンドは弱気寄りです。流れに逆らう追いかけ買いは避けてください"
        else:
            headline = f"{target_label} は方向未定です。重要な価格と出来高の確認を待ってください"

        action_plan = [
            {"label": "方向", "text": f"現在のスコアは {score_text or '-'} です。方向の強さを見る材料であり、直接の売買シグナルではありません。"},
            {"label": "確認", "text": "価格、出来高、移動平均、または相対的な市場強度が同じ方向にそろうまで待ってください。"},
            {"label": "失効", "text": "主要移動平均またはモメンタムが弱まる場合、トレンド見通しを再計算してください。"},
        ]

    scenarios = scenario_plan_from_levels(
        question_intent=question_intent,
        fields=level_fields,
        numbers=level_numbers,
        score=score,
        weak_evidence=weak_evidence,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    counter_evidence = counter_evidence_from_levels(
        question_intent=question_intent,
        fields=level_fields,
        score=score,
        weak_evidence=weak_evidence,
        evidence_risks=answer_risks,
        response_preferences=response_preferences,
    )
    answer = {
        "kind": "consumer_market_answer",
        "style": "question_aware_summary",
        "source": "question_intent",
        "intent": question_intent,
        "headline": headline,
        "stance": stance,
        "stance_label": stance_label(stance, response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_display,
        "summary": summary,
        "action_plan": action_plan,
        "scenarios": scenarios,
        "counter_evidence": counter_evidence,
        "risks": list(dict.fromkeys(answer_risks + (data_limits[:2] if weak_evidence else [])))[:2],
        "data_limits": data_limits,
        "detail": text_value(analysis_digest.get("display")) or "",
        "decision_evidence": decision_evidence,
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_chinese_question_answer(context: QuestionAnswerContext) -> dict[str, Any]:
    question_intent = context.question_intent
    target_label = context.target_label
    score = context.score
    score_text = context.score_text
    confidence = context.confidence
    confidence_display = context.confidence_display
    stance = context.stance
    summary = list(context.summary)
    data_limits = context.data_limits
    decision_evidence = context.decision_evidence
    evidence_summary = context.evidence_summary
    evidence_risks = context.evidence_risks
    answer_risks = list(context.answer_risks)
    weak_evidence = context.weak_evidence
    level_fields = context.level_fields
    level_numbers = context.level_numbers
    analysis_digest = context.analysis_digest
    summary_limit = context.summary_limit
    response_preferences = context.response_preferences
    if question_intent == "entry_decision":
        if level_fields:
            headline, entry_summary, action_plan = decision_engine.entry_decision_with_levels(
                target_label=target_label,
                score=score,
                weak_evidence=weak_evidence,
                fields=level_fields,
                numbers=level_numbers,
                summary_limit=summary_limit,
            )
            if entry_summary:
                summary = list(
                    dict.fromkeys(entry_summary[:1] + evidence_summary + entry_summary[1:] + summary)
                )[:summary_limit]
        elif weak_evidence:
            headline = f"{target_label} 先不要直接買，資料或信心還不足"
            action_plan = [
                {"label": "現在", "text": "先不要追價，等下一筆價格、量能或指標確認。"},
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
        elif score is not None and score >= 4:
            headline = f"{target_label} 可以列入偏多觀察，但不建議直接追價"
            action_plan = [
                {
                    "label": "現在",
                    "text": "先把它當作偏多觀察標的，不把單一評分當成直接買進訊號。",
                },
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
        elif score is not None and score >= 1:
            headline = f"{target_label} 可以觀察，買點要等價格與量能確認"
            action_plan = [
                {
                    "label": "現在",
                    "text": "先把它當作觀察標的，不把單一評分當成直接買進訊號。",
                },
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
        elif score is not None and score <= -1:
            headline = f"{target_label} 目前不建議直接買"
            action_plan = [
                {"label": "現在", "text": "先不要追價，等下一筆價格、量能或指標確認。"},
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
        else:
            headline = f"{target_label} 先觀望，等方向確認"
            action_plan = [
                {"label": "現在", "text": "先不要追價，等下一筆價格、量能或指標確認。"},
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
    elif question_intent == "exit_decision":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if level_fields and not weak_evidence and (level_fields.get("stop") or level_fields.get("invalidation")):
            guardrails = " / ".join(
                value
                for value in (level_fields.get("stop"), level_fields.get("invalidation"))
                if value
            )
            headline = f"{target_label} 還可條件式續抱，但要守住 {guardrails}"
        elif weak_evidence:
            headline = f"{target_label} 先降低判斷強度，等資料確認再決定去留"
        elif score >= 2:
            headline = f"{target_label} 還可續抱觀察，但要守住轉弱條件"
        elif score <= -2:
            headline = f"{target_label} 偏弱，應優先檢查減碼或出場條件"
        else:
            headline = f"{target_label} 方向未明，先用條件式續抱"

        action_plan = [
            {"label": "現在", "text": "先看持有成本與部位大小，不用單一分數做全部出場決策。"},
            {
                "label": "續抱條件",
                "text": (
                    f"價格守住 {level_fields['stop']} 以上，且量能沒有放大轉弱時，續抱觀察較合理。"
                    if level_fields.get("stop")
                    else "價格守住關鍵均線或前低，且量能沒有放大轉弱時，續抱觀察較合理。"
                ),
            },
            {
                "label": "出場條件",
                "text": (
                    f"若跌破 {level_fields['invalidation']}，技術假設失效，應降低部位或重新評估。"
                    if level_fields.get("invalidation")
                    else "若跌破主要支撐、動能轉空或反彈失敗，應降低部位或重新評估。"
                ),
            },
        ]
    elif question_intent == "risk_check":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if level_fields and not weak_evidence and (level_fields.get("stop") or level_fields.get("invalidation")):
            headline = (
                f"{target_label} 風險線在 {level_fields.get('stop') or level_fields.get('invalidation')}，"
                "跌破要先防守"
            )
        elif weak_evidence:
            headline = f"{target_label} 風險判斷信心不足，先用保守條件控管"
        elif score <= -2:
            headline = f"{target_label} 風險偏高，短線要優先防守"
        elif score >= 2:
            headline = f"{target_label} 目前風險未明顯放大，但仍要看失效條件"
        else:
            headline = f"{target_label} 多空拉扯，風險需要逐筆確認"

        action_plan = [
            {
                "label": "主要風險",
                "text": (
                    f"若跌破短線停損 {level_fields['stop']}，短線方向會快速降級。"
                    if level_fields.get("stop")
                    else "若價格跌破主要均線或前低，短線方向會快速降級。"
                ),
            },
            {
                "label": "觀察",
                "text": (
                    f"看 {level_fields['invalidation']} 是否被跌破，並同步確認量能、法人或市場相對強弱。"
                    if level_fields.get("invalidation")
                    else "看下一筆價格、量能、法人或市場相對強弱是否同步轉弱。"
                ),
            },
            {"label": "風控", "text": "不要等到資料完全確認才控風險；條件失效時先縮小部位。"},
        ]
    elif question_intent == "trend_view":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if level_fields:
            headline, trend_summary, action_plan, trend_risks = decision_engine.trend_view_with_levels(
                target_label=target_label,
                score=score,
                weak_evidence=weak_evidence,
                fields=level_fields,
                numbers=level_numbers,
                summary_limit=summary_limit,
            )
            summary = list(dict.fromkeys(trend_summary + summary))[:summary_limit]
            answer_risks = list(dict.fromkeys(trend_risks + evidence_risks))
        elif weak_evidence:
            headline = f"{target_label} 目前方向信心不足，先看下一筆確認"
            action_plan = [
                {
                    "label": "趨勢",
                    "text": "先把這次解讀當方向參考，不把單一分數或單日收盤價當成最後結論。",
                },
                {"label": "支撐壓力", "text": "先看主要均線、前低與量能，確認支撐壓力是否一致。"},
                {"label": "觀察", "text": "等價格、量能與市場相對強弱出現同向訊號後，再提高判斷強度。"},
            ]
        elif score >= 2:
            headline = f"{target_label} 走勢偏多，先看支撐承接與突破延續"
            action_plan = [
                {"label": "趨勢", "text": "先用多週期分數判斷大方向，再用支撐壓力與量能確認延續性。"},
                {"label": "支撐壓力", "text": "先看回測支撐是否守住，再看上方壓力是否突破站穩。"},
                {"label": "觀察", "text": "觀察價格、量能、均線與相對市場是否持續同向。"},
            ]
        elif score <= -2:
            headline = f"{target_label} 走勢偏弱，先看支撐是否失守"
            action_plan = [
                {"label": "趨勢", "text": "先把方向降級，不用單一收盤價硬撐原本的多方假設。"},
                {"label": "支撐壓力", "text": "優先確認主要支撐是否失守，以及反彈壓力是否有效。"},
                {"label": "觀察", "text": "若量能與動能都轉弱，原本的波段判斷要重新計算。"},
            ]
        else:
            headline = f"{target_label} 方向未定，先看支撐壓力哪邊先表態"
            action_plan = [
                {"label": "趨勢", "text": f"目前評分為 {score_text or '-'}，先把它當方向線索，不直接等同買賣訊號。"},
                {"label": "支撐壓力", "text": "先看關鍵均線、前低與上方壓力是否收斂成一致訊號。"},
                {"label": "觀察", "text": "等價格、量能與市場相對強弱同向後，再提高結論強度。"},
            ]
    else:
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if weak_evidence:
            headline = f"{target_label} 目前方向信心不足，先看下一筆確認"
        elif score >= 2:
            headline = f"{target_label} 走勢偏多，但仍要等確認"
        elif score <= -2:
            headline = f"{target_label} 走勢偏弱，先不要逆勢追高"
        else:
            headline = f"{target_label} 方向未定，先看關鍵價量是否突破"

        action_plan = [
            {"label": "方向", "text": f"目前評分為 {score_text or '-'}，先用它判斷方向強弱，不直接等同買賣訊號。"},
            {"label": "確認", "text": "等價格、量能、均線或市場相對強弱出現同向訊號。"},
            {"label": "失效", "text": "若主要均線或動能轉弱，原本走勢判斷要重新計算。"},
        ]

    scenarios = scenario_plan_from_levels(
        question_intent=question_intent,
        fields=level_fields,
        numbers=level_numbers,
        score=score,
        weak_evidence=weak_evidence,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    counter_evidence = counter_evidence_from_levels(
        question_intent=question_intent,
        fields=level_fields,
        score=score,
        weak_evidence=weak_evidence,
        evidence_risks=answer_risks,
        response_preferences=response_preferences,
    )

    answer = {
        "kind": "consumer_market_answer",
        "style": "question_aware_summary",
        "source": "question_intent",
        "intent": question_intent,
        "headline": headline,
        "stance": stance,
        "stance_label": stance_label(stance, response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_display,
        "summary": summary,
        "action_plan": action_plan,
        "scenarios": scenarios,
        "counter_evidence": counter_evidence,
        "risks": list(dict.fromkeys(answer_risks + (data_limits[:2] if weak_evidence else [])))[:2],
        "data_limits": data_limits,
        "detail": text_value(analysis_digest.get("display")) or "",
        "decision_evidence": decision_evidence,
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer
