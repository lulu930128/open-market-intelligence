from __future__ import annotations

from typing import Any

from app.ai import decision_engine


SUMMARY_LIMIT_DEFAULT = 3
ANALYSIS_HORIZON_LABELS = {
    "intraday": "盤中",
    "short": "短線",
    "swing": "中短線",
    "long": "長線",
}
STANCE_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "mixed": "多空分歧",
    "insufficient_data": "資料不足",
}
CONFIDENCE_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}
DATA_LIMIT_WARNING_HINTS = (
    "missing",
    "stale",
    "incomplete",
    "unavailable",
    "failed",
    "資料",
    "缺",
    "不足",
    "不完整",
    "過期",
    "失敗",
)
NON_DATA_LIMIT_WARNING_PREFIXES = (
    "LLM analysis was generated on demand",
    "Intraday analysis horizon was requested without live intraday access",
)
LLM_SOFT_DATA_GAP_HINTS = (
    "missing",
    "unavailable",
    "intraday_trend",
    "缺少",
    "缺乏",
    "未提供",
    "未取得",
    "不可用",
    "資料不足",
)
LLM_INTRADAY_GAP_HINTS = (
    "intraday",
    "盤中",
    "即時",
    "成交",
    "快照",
)


def text_value(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def text_list(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []

    texts: list[str] = []
    for item in value:
        text = text_value(item)
        if text is None:
            continue
        if text in texts:
            continue
        texts.append(text)
        if limit is not None and len(texts) >= limit:
            break
    return texts


def append_unique_texts(target: list[str], values: list[str], *, limit: int) -> None:
    for value in values:
        if value in target:
            continue
        target.append(value)
        if len(target) >= limit:
            return


def consumer_detail_from_llm_report(
    report: dict[str, Any],
    *,
    missing_data_label: str = "資料限制",
) -> str:
    lines: list[str] = []
    headline = text_value(report.get("headline"))
    if headline:
        lines.append(f"結論：{headline}")

    sections = (
        ("key_observations", "重點"),
        ("interpretation", "解讀"),
        ("risks", "風險"),
        ("missing_data", missing_data_label),
        ("next_checks", "下一步"),
    )
    for key, label in sections:
        items = text_list(report.get(key))
        if not items:
            continue
        lines.append(f"{label}：")
        lines.extend(f"- {item}" for item in items)

    disclaimer = text_value(report.get("disclaimer"))
    if disclaimer:
        lines.append(f"限制：{disclaimer}")
    return "\n".join(lines)


def consumer_text(
    answer: dict[str, Any],
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> str:
    lines: list[str] = []
    headline = text_value(answer.get("headline"))
    if headline:
        lines.append(f"結論：{headline}")

    stance = text_value(answer.get("stance_label"))
    confidence = text_value(answer.get("confidence_label"))
    if stance or confidence:
        parts = []
        if stance:
            parts.append(f"方向：{stance}")
        if confidence:
            parts.append(f"信心：{confidence}")
        lines.append(" / ".join(parts))

    summary = text_list(answer.get("summary"), limit=summary_limit)
    if summary:
        lines.append("重點：")
        lines.extend(f"- {item}" for item in summary)

    actions = answer.get("action_plan")
    if isinstance(actions, list) and actions:
        lines.append("怎麼做：")
        for item in actions[:summary_limit]:
            if not isinstance(item, dict):
                continue
            label = text_value(item.get("label"))
            text = text_value(item.get("text"))
            if text:
                lines.append(f"- {label + '：' if label else ''}{text}")

    risks = text_list(answer.get("risks"), limit=2)
    if risks:
        lines.append("風險：")
        lines.extend(f"- {item}" for item in risks)

    return "\n".join(lines)


def warning_is_data_limit(value: Any) -> bool:
    text = text_value(value)
    if not text:
        return False
    if any(text.startswith(prefix) for prefix in NON_DATA_LIMIT_WARNING_PREFIXES):
        return False
    lowered = text.lower()
    return any(hint in lowered for hint in DATA_LIMIT_WARNING_HINTS)


def llm_text_is_soft_data_gap(value: Any) -> bool:
    text = text_value(value)
    if not text:
        return False
    lowered = text.lower()
    if any(hint in lowered for hint in LLM_SOFT_DATA_GAP_HINTS):
        return True
    if "無法確認" in text and any(hint in lowered for hint in LLM_INTRADAY_GAP_HINTS):
        return True
    return False


def filter_soft_data_gap_texts(values: list[str], *, has_backend_missing: bool) -> list[str]:
    if has_backend_missing:
        return values
    return [value for value in values if not llm_text_is_soft_data_gap(value)]


def generic_data_limits(*, missing: list[Any], warnings: list[Any]) -> list[str]:
    limits: list[str] = []
    if missing:
        limits.append(f"仍有 {len(missing)} 項資料缺口，結論需保留彈性。")
    append_unique_texts(
        limits,
        [text for text in text_list(warnings, limit=4) if warning_is_data_limit(text)],
        limit=3,
    )
    return limits


def digest_summary_lines(
    analysis_digest: dict[str, Any],
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> list[str]:
    summary: list[str] = []
    append_unique_texts(
        summary,
        [
            text
            for text in (
                text_value(analysis_digest.get("display")),
                text_value(analysis_digest.get("selected_summary")),
            )
            if text
        ],
        limit=summary_limit,
    )
    scores = analysis_digest.get("scores") if isinstance(analysis_digest.get("scores"), dict) else {}
    if scores and len(summary) < summary_limit:
        score_parts = [
            f"{ANALYSIS_HORIZON_LABELS.get(str(key), str(key))} {decision_engine.score_display(value) or '-'}"
            for key, value in scores.items()
            if value is not None
        ]
        if score_parts:
            summary.append("分數：" + "、".join(score_parts[:4]))
    return summary[:summary_limit]


def decision_evidence_summary_lines(decision_evidence: dict[str, Any]) -> list[str]:
    if not isinstance(decision_evidence, dict):
        return []

    lines: list[str] = []
    market_session = (
        decision_evidence.get("market_session")
        if isinstance(decision_evidence.get("market_session"), dict)
        else {}
    )
    if market_session.get("is_trading_day") is False:
        text = text_value(market_session.get("summary"))
        if text:
            lines.append(text)

    volatility = (
        decision_evidence.get("recent_volatility")
        if isinstance(decision_evidence.get("recent_volatility"), dict)
        else {}
    )
    if volatility.get("label") in {"high", "elevated"}:
        text = text_value(volatility.get("summary"))
        if text:
            lines.append(text)

    fundamentals = (
        decision_evidence.get("fundamentals")
        if isinstance(decision_evidence.get("fundamentals"), dict)
        else {}
    )
    revenue = (
        fundamentals.get("monthly_revenue")
        if isinstance(fundamentals.get("monthly_revenue"), dict)
        else {}
    )
    revenue_summary = text_value(revenue.get("summary"))
    if revenue_summary:
        lines.append(revenue_summary)

    indicator_quality = (
        decision_evidence.get("indicator_quality")
        if isinstance(decision_evidence.get("indicator_quality"), dict)
        else {}
    )
    warnings = text_list(indicator_quality.get("warnings"), limit=1)
    lines.extend(warnings)
    return lines[:2]


def decision_evidence_risk_lines(decision_evidence: dict[str, Any]) -> list[str]:
    if not isinstance(decision_evidence, dict):
        return []
    factors = (
        decision_evidence.get("confidence_factors")
        if isinstance(decision_evidence.get("confidence_factors"), dict)
        else {}
    )
    negatives = text_list(factors.get("negative"), limit=3)
    return negatives[:2]


def decision_evidence_data_lines(decision_evidence: dict[str, Any]) -> list[str]:
    if not isinstance(decision_evidence, dict):
        return []
    lines: list[str] = []
    market_session = (
        decision_evidence.get("market_session")
        if isinstance(decision_evidence.get("market_session"), dict)
        else {}
    )
    if market_session.get("is_trading_day") is False:
        session_date = text_value(market_session.get("date")) or "今日"
        latest_daily_date = text_value(market_session.get("latest_daily_date"))
        next_trading_day = text_value(market_session.get("next_trading_day"))
        line = f"{session_date} 非台股交易日，不使用盤中資料"
        if latest_daily_date:
            line += f"；最新日線截至 {latest_daily_date}"
        if next_trading_day:
            line += f"，下一交易日 {next_trading_day} 再確認"
        lines.append(line + "。")

    data_quality = (
        decision_evidence.get("data_quality")
        if isinstance(decision_evidence.get("data_quality"), dict)
        else {}
    )
    price = data_quality.get("price") if isinstance(data_quality.get("price"), dict) else {}
    volume = data_quality.get("volume") if isinstance(data_quality.get("volume"), dict) else {}
    price_source = text_value(price.get("source"))
    price_as_of = text_value(price.get("as_of"))
    volume_source = text_value(volume.get("source"))
    volume_display = text_value(volume.get("display_value"))
    if price_source or price_as_of:
        lines.append(
            "價格來源 "
            + (price_source or "-")
            + (f"，截至 {price_as_of}" if price_as_of else "")
            + "。"
        )
    if volume_source or volume_display:
        lines.append(
            "成交量來源 "
            + (volume_source or "-")
            + (f"，折算約 {volume_display}" if volume_display else "")
            + "。"
        )

    factors = (
        decision_evidence.get("confidence_factors")
        if isinstance(decision_evidence.get("confidence_factors"), dict)
        else {}
    )
    lines.extend(text_list(factors.get("data_limits"), limit=2))
    return list(dict.fromkeys(lines))[:3]


def build_position_decision_consumer_answer(
    *,
    position_decision: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> dict[str, Any]:
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
        labels = ("條件", "執行", "追蹤")
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
            "stance_label": STANCE_LABELS.get(str(position_decision.get("stance")), "未定"),
            "confidence": confidence,
            "confidence_label": CONFIDENCE_LABELS.get(str(confidence), confidence or "未定"),
            "summary": summary[:summary_limit],
            "action_plan": action_plan[:summary_limit],
            "risks": text_list(llm_decision.get("risk_notes"), limit=2) or position_decision.get("risks", []),
            "data_limits": (
                text_list(llm_decision.get("missing_context"), limit=2)
                + generic_data_limits(missing=missing, warnings=warnings)
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
            "headline": text_value(position_decision.get("headline")) or "已完成部位風險判斷",
            "stance": position_decision.get("stance"),
            "stance_label": STANCE_LABELS.get(str(position_decision.get("stance")), "未定"),
            "confidence": confidence,
            "confidence_label": CONFIDENCE_LABELS.get(str(confidence), confidence or "未定"),
            "summary": text_list(position_decision.get("summary"), limit=summary_limit),
            "action_plan": position_decision.get("action_plan", [])[:summary_limit],
            "risks": position_decision.get("risks", []),
            "data_limits": position_decision.get("data_limits", []),
            "detail": text_value(position_decision.get("direct_answer")) or "",
            "position_decision": position_decision,
        }

    answer["text"] = consumer_text(answer, summary_limit=summary_limit)
    return answer


def build_question_aware_consumer_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> dict[str, Any]:
    if question_intent == "general" or not analysis_digest:
        return {}

    score = decision_engine.numeric_score(analysis_digest.get("selected_score"))
    score_text = decision_engine.score_display(score)
    confidence = text_value(analysis_digest.get("selected_confidence"))
    confidence_label = CONFIDENCE_LABELS.get(str(confidence), confidence or "未定")
    stance = decision_engine.stance_from_score(score)
    summary = digest_summary_lines(analysis_digest, summary_limit=summary_limit)
    target_label = text_value(target.get("label")) or text_value(target.get("id")) or "目前標的"
    data_limits = generic_data_limits(missing=missing, warnings=warnings)
    decision_evidence = (
        analysis_digest.get("decision_evidence")
        if isinstance(analysis_digest.get("decision_evidence"), dict)
        else {}
    )
    evidence_summary = decision_evidence_summary_lines(decision_evidence)
    evidence_risks = decision_evidence_risk_lines(decision_evidence)
    data_limits = list(
        dict.fromkeys(data_limits + decision_evidence_data_lines(decision_evidence))
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
        else decision_engine.technical_level_summary_lines(
            technical_levels,
            summary_limit=summary_limit,
        )
    )
    if level_summary:
        summary = list(dict.fromkeys(level_summary + summary))[:summary_limit]

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

    answer = {
        "kind": "consumer_market_answer",
        "style": "question_aware_summary",
        "source": "question_intent",
        "intent": question_intent,
        "headline": headline,
        "stance": stance,
        "stance_label": STANCE_LABELS.get(stance, "未定"),
        "confidence": confidence,
        "confidence_label": confidence_label,
        "summary": summary,
        "action_plan": action_plan,
        "risks": list(dict.fromkeys(evidence_risks + (data_limits[:2] if weak_evidence else [])))[:2],
        "data_limits": data_limits,
        "detail": text_value(analysis_digest.get("display")) or "",
        "decision_evidence": decision_evidence,
    }
    answer["text"] = consumer_text(answer, summary_limit=summary_limit)
    return answer


def build_llm_consumer_answer(
    *,
    report: dict[str, Any],
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> dict[str, Any]:
    stance = text_value(report.get("stance"))
    confidence = text_value(report.get("confidence"))
    headline = (
        text_value(report.get("headline"))
        or text_value(analysis_digest.get("selected_title"))
        or text_value(target.get("label"))
        or "OMI 已完成分析"
    )

    backend_data_limits = generic_data_limits(missing=missing, warnings=warnings)
    has_backend_missing = bool(text_list(missing))
    raw_observations = text_list(report.get("key_observations"))
    raw_interpretations = text_list(report.get("interpretation"))
    raw_next_checks = text_list(report.get("next_checks"))
    raw_risks = text_list(report.get("risks"))
    raw_missing_data = text_list(report.get("missing_data"))

    observations = filter_soft_data_gap_texts(raw_observations, has_backend_missing=has_backend_missing)
    interpretations = filter_soft_data_gap_texts(raw_interpretations, has_backend_missing=has_backend_missing)
    next_checks = filter_soft_data_gap_texts(raw_next_checks, has_backend_missing=has_backend_missing)
    risks = filter_soft_data_gap_texts(raw_risks, has_backend_missing=has_backend_missing)
    missing_data = raw_missing_data if has_backend_missing else []

    summary: list[str] = []
    append_unique_texts(summary, observations[:2], limit=summary_limit)
    append_unique_texts(summary, interpretations[:2], limit=summary_limit)
    if not summary and analysis_digest.get("display"):
        summary.append(str(analysis_digest["display"]))

    follow_up_checks = list(
        dict.fromkeys(next_checks + ([] if has_backend_missing else filter_soft_data_gap_texts(raw_missing_data, has_backend_missing=False)))
    )

    action_plan = [
        {
            "label": "已持有",
            "text": interpretations[0] if interpretations else "先依目前結論觀察，不把單一訊號當成確認。",
        },
        {
            "label": "想進場",
            "text": follow_up_checks[0] if follow_up_checks else "等下一筆價格、量能或關鍵均線確認後再判斷。",
        },
        {
            "label": "失效",
            "text": risks[0] if risks else "若價格或量能轉弱，原本結論需要降級。",
        },
    ]
    data_limits = list(dict.fromkeys(missing_data[:3] + backend_data_limits))[:3] if has_backend_missing else backend_data_limits
    detail_report = dict(report)
    if not has_backend_missing:
        detail_report["missing_data"] = []

    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "llm_report",
        "headline": headline,
        "stance": stance,
        "stance_label": STANCE_LABELS.get(str(stance), stance or "未定"),
        "confidence": confidence,
        "confidence_label": CONFIDENCE_LABELS.get(str(confidence), confidence or "未定"),
        "summary": summary,
        "action_plan": action_plan,
        "risks": risks[:2],
        "data_limits": data_limits,
        "detail": consumer_detail_from_llm_report(
            detail_report,
            missing_data_label="資料限制" if data_limits else "後續確認",
        ),
    }
    answer["text"] = consumer_text(answer, summary_limit=summary_limit)
    return answer


def build_watchlist_consumer_answer(
    *,
    human_answer: dict[str, Any],
    overview: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> dict[str, Any]:
    sections = human_answer.get("sections") if isinstance(human_answer.get("sections"), list) else []
    section_map: dict[str, str] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = text_value(section.get("label"))
        text = text_value(section.get("text"))
        if label and text:
            section_map[label] = text

    lines = text_list(human_answer.get("lines")) or text_list(overview.get("answer_outline"))
    headline = section_map.get("結論") or text_value(overview.get("display")) or (lines[0] if lines else "自選股整理完成")
    summary = [
        text
        for key in ("追蹤", "等回測", "保守")
        if (text := section_map.get(key))
    ]
    if not summary:
        summary = lines[1 : 1 + summary_limit]

    action_plan = [
        {"label": "優先看", "text": section_map.get("追蹤") or "先看排名與量價最明確的個股。"},
        {"label": "等回測", "text": section_map.get("等回測") or "漲幅過大的標的等回測後再確認。"},
        {"label": "保守", "text": section_map.get("保守") or "弱勢或資料不足標的先降低追蹤權重。"},
    ]
    data_limits = []
    if section_map.get("資料"):
        data_limits.append(section_map["資料"])
    data_limits.extend(generic_data_limits(missing=missing, warnings=warnings))

    confidence = text_value(overview.get("confidence"))
    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "watchlist_overview",
        "headline": headline,
        "stance": text_value(overview.get("stance")),
        "stance_label": text_value(overview.get("stance")) or "未定",
        "confidence": confidence,
        "confidence_label": CONFIDENCE_LABELS.get(str(confidence), confidence or "未定"),
        "summary": summary[:summary_limit],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": list(dict.fromkeys(data_limits))[:3],
        "detail": text_value(human_answer.get("text")) or "\n".join(lines),
        "source_human_answer": human_answer,
    }
    answer["text"] = consumer_text(answer, summary_limit=summary_limit)
    return answer


def build_digest_consumer_answer(
    *,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> dict[str, Any]:
    confidence = text_value(analysis_digest.get("selected_confidence"))
    headline = (
        text_value(analysis_digest.get("selected_title"))
        or text_value(analysis_digest.get("display"))
        or text_value(target.get("label"))
        or "OMI 已完成資料整理"
    )
    summary = [
        text
        for text in (
            text_value(analysis_digest.get("display")),
            text_value(analysis_digest.get("selected_summary")),
        )
        if text
    ]
    scores = analysis_digest.get("scores") if isinstance(analysis_digest.get("scores"), dict) else {}
    if scores:
        score_parts = [
            f"{ANALYSIS_HORIZON_LABELS.get(str(key), str(key))} {decision_engine.score_display(value) or '-'}"
            for key, value in scores.items()
            if value is not None
        ]
        if score_parts:
            summary.append("分數：" + "、".join(score_parts[:4]))

    action_plan = [
        {"label": "已持有", "text": "先依目前方向觀察，等待下一筆量價或指標確認。"},
        {"label": "想進場", "text": "不要只看單一評分，等價格、量能與市場相對強弱同向再提高權重。"},
        {"label": "失效", "text": "若主要均線或動能轉弱，這份短評需要重新計算。"},
    ]
    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "analysis_digest",
        "headline": headline,
        "stance": None,
        "stance_label": "未定",
        "confidence": confidence,
        "confidence_label": CONFIDENCE_LABELS.get(str(confidence), confidence or "未定"),
        "summary": list(dict.fromkeys(summary))[:summary_limit],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": generic_data_limits(missing=missing, warnings=warnings),
        "detail": text_value(analysis_digest.get("display")) or "",
    }
    answer["text"] = consumer_text(answer, summary_limit=summary_limit)
    return answer


def build_consumer_human_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    position_decision: dict[str, Any] | None = None,
    llm_report: dict[str, Any] | None = None,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> dict[str, Any]:
    if position_decision:
        return build_position_decision_consumer_answer(
            position_decision=position_decision,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
        )

    question_answer = build_question_aware_consumer_answer(
        question_intent=question_intent,
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        summary_limit=summary_limit,
    )
    if question_intent in {"entry_decision", "exit_decision"} and question_answer:
        return question_answer

    if llm_report:
        return build_llm_consumer_answer(
            report=llm_report,
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
        )

    human_answer = analysis_digest.get("human_answer") if isinstance(analysis_digest.get("human_answer"), dict) else {}
    if human_answer:
        return build_watchlist_consumer_answer(
            human_answer=human_answer,
            overview=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
        )

    if question_answer:
        return question_answer

    if analysis_digest:
        return build_digest_consumer_answer(
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
        )

    return {}
