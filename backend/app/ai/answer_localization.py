from __future__ import annotations

from typing import Any

from app.ai import decision_engine


ANALYSIS_HORIZON_LABELS = {
    "intraday": "盤中",
    "short": "短線",
    "swing": "中短線",
    "long": "長線",
}
ANALYSIS_HORIZON_LABELS_EN = {
    "intraday": "Intraday",
    "short": "Short term",
    "swing": "Swing",
    "long": "Long term",
}
ANALYSIS_HORIZON_LABELS_JA = {
    "intraday": "ザラ場",
    "short": "短期",
    "swing": "スイング",
    "long": "長期",
}
STANCE_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "mixed": "多空分歧",
    "insufficient_data": "資料不足",
}
STANCE_LABELS_EN = {
    "bullish": "Bullish",
    "bearish": "Bearish",
    "neutral": "Neutral",
    "mixed": "Mixed",
    "insufficient_data": "Insufficient data",
}
STANCE_LABELS_JA = {
    "bullish": "強気寄り",
    "bearish": "弱気寄り",
    "neutral": "中立",
    "mixed": "強弱混在",
    "insufficient_data": "データ不足",
}
CONFIDENCE_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}
CONFIDENCE_LABELS_EN = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
}
CONFIDENCE_LABELS_JA = {
    "low": "低",
    "medium": "中",
    "high": "高",
}
CONSUMER_TEXT_LABELS = {
    "zh-TW": {
        "conclusion": "結論",
        "direction": "方向",
        "confidence": "信心",
        "summary": "重點",
        "actions": "怎麼做",
        "scenarios": "情境",
        "counter_evidence": "反證",
        "risks": "風險",
        "data_limits": "資料限制",
        "separator": "：",
        "joiner": " / ",
    },
    "en-US": {
        "conclusion": "Conclusion",
        "direction": "Direction",
        "confidence": "Confidence",
        "summary": "Key points",
        "actions": "What to do",
        "scenarios": "Scenarios",
        "counter_evidence": "Counter evidence",
        "risks": "Risks",
        "data_limits": "Data limits",
        "separator": ": ",
        "joiner": " / ",
    },
    "ja-JP": {
        "conclusion": "結論",
        "direction": "方向",
        "confidence": "信頼度",
        "summary": "要点",
        "actions": "対応",
        "scenarios": "シナリオ",
        "counter_evidence": "反証",
        "risks": "リスク",
        "data_limits": "データ制約",
        "separator": "：",
        "joiner": " / ",
    },
}
DETAIL_SECTION_LABELS = {
    "zh-TW": {
        "conclusion": "結論",
        "key_observations": "重點",
        "interpretation": "解讀",
        "risks": "風險",
        "missing_data": "資料限制",
        "next_checks": "下一步",
        "disclaimer": "限制",
    },
    "en-US": {
        "conclusion": "Conclusion",
        "key_observations": "Key points",
        "interpretation": "Interpretation",
        "risks": "Risks",
        "missing_data": "Data limits",
        "next_checks": "Next checks",
        "disclaimer": "Limit",
    },
    "ja-JP": {
        "conclusion": "結論",
        "key_observations": "要点",
        "interpretation": "解釈",
        "risks": "リスク",
        "missing_data": "データ制約",
        "next_checks": "次の確認",
        "disclaimer": "制約",
    },
}
UNDECIDED_LABELS = {
    "zh-TW": "未定",
    "en-US": "Undecided",
    "ja-JP": "未定",
}
TARGET_FALLBACK_LABELS = {
    "zh-TW": "目前標的",
    "en-US": "Current target",
    "ja-JP": "現在の対象",
}
SUMMARY_LIMIT_DEFAULT = 3


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
        if text is None or text in texts:
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


def response_locale(response_preferences: dict[str, Any] | None = None) -> str:
    if not isinstance(response_preferences, dict):
        return "zh-TW"
    locale = (
        text_value(response_preferences.get("effective_locale"))
        or text_value(response_preferences.get("requested_locale"))
        or text_value(response_preferences.get("locale"))
    )
    if locale in {"en-US", "ja-JP"}:
        return locale
    return "zh-TW"


def response_is_english(response_preferences: dict[str, Any] | None = None) -> bool:
    return response_locale(response_preferences) == "en-US"


def response_is_japanese(response_preferences: dict[str, Any] | None = None) -> bool:
    return response_locale(response_preferences) == "ja-JP"


def text_labels(response_preferences: dict[str, Any] | None = None) -> dict[str, str]:
    return CONSUMER_TEXT_LABELS[response_locale(response_preferences)]


def detail_labels(response_preferences: dict[str, Any] | None = None) -> dict[str, str]:
    return DETAIL_SECTION_LABELS[response_locale(response_preferences)]


def undecided_label(response_preferences: dict[str, Any] | None = None) -> str:
    return UNDECIDED_LABELS[response_locale(response_preferences)]


def target_fallback_label(response_preferences: dict[str, Any] | None = None) -> str:
    return TARGET_FALLBACK_LABELS[response_locale(response_preferences)]


def analysis_horizon_label(
    key: Any,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    text = str(key)
    locale = response_locale(response_preferences)
    labels = {
        "en-US": ANALYSIS_HORIZON_LABELS_EN,
        "ja-JP": ANALYSIS_HORIZON_LABELS_JA,
    }.get(locale, ANALYSIS_HORIZON_LABELS)
    return labels.get(text, text)


def stance_label(
    stance: Any,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    text = text_value(stance)
    if not text:
        return undecided_label(response_preferences)
    locale = response_locale(response_preferences)
    labels = {
        "en-US": STANCE_LABELS_EN,
        "ja-JP": STANCE_LABELS_JA,
    }.get(locale, STANCE_LABELS)
    return labels.get(text, text)


def confidence_label(
    confidence: Any,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    text = text_value(confidence)
    if not text:
        return undecided_label(response_preferences)
    locale = response_locale(response_preferences)
    labels = {
        "en-US": CONFIDENCE_LABELS_EN,
        "ja-JP": CONFIDENCE_LABELS_JA,
    }.get(locale, CONFIDENCE_LABELS)
    return labels.get(text, text)


def pct_text(value: Any) -> str | None:
    number = decision_engine.numeric_score(value)
    if number is None:
        return None
    return decision_engine.format_pct_value(number)


def consumer_detail_from_llm_report(
    report: dict[str, Any],
    *,
    missing_data_label: str | None = None,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    labels = detail_labels(response_preferences)
    separator = ": " if response_is_english(response_preferences) else "："
    heading_separator = separator.rstrip()
    missing_label = missing_data_label or labels["missing_data"]
    lines: list[str] = []
    headline = text_value(report.get("headline"))
    if headline:
        lines.append(f"{labels['conclusion']}{separator}{headline}")
    sections = (
        ("key_observations", labels["key_observations"]),
        ("interpretation", labels["interpretation"]),
        ("risks", labels["risks"]),
        ("missing_data", missing_label),
        ("next_checks", labels["next_checks"]),
    )
    for key, label in sections:
        items = text_list(report.get(key))
        if not items:
            continue
        lines.append(f"{label}{heading_separator}")
        lines.extend(f"- {item}" for item in items)
    disclaimer = text_value(report.get("disclaimer"))
    if disclaimer:
        lines.append(f"{labels['disclaimer']}{separator}{disclaimer}")
    return "\n".join(lines)


def consumer_text(
    answer: dict[str, Any],
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    labels = text_labels(response_preferences)
    separator = labels["separator"]
    heading_separator = separator.rstrip()
    lines: list[str] = []
    headline = text_value(answer.get("headline"))
    if headline:
        lines.append(f"{labels['conclusion']}{separator}{headline}")
    stance = text_value(answer.get("stance_label"))
    confidence = text_value(answer.get("confidence_label"))
    if stance or confidence:
        parts = []
        if stance:
            parts.append(f"{labels['direction']}{separator}{stance}")
        if confidence:
            parts.append(f"{labels['confidence']}{separator}{confidence}")
        lines.append(labels["joiner"].join(parts))
    summary = text_list(answer.get("summary"), limit=summary_limit)
    if summary:
        lines.append(f"{labels['summary']}{heading_separator}")
        lines.extend(f"- {item}" for item in summary)
    actions = answer.get("action_plan")
    if isinstance(actions, list) and actions:
        lines.append(f"{labels['actions']}{heading_separator}")
        for item in actions[:summary_limit]:
            if not isinstance(item, dict):
                continue
            label = text_value(item.get("label"))
            text = text_value(item.get("text"))
            if text:
                lines.append(f"- {label + separator if label else ''}{text}")
    scenarios = answer.get("scenarios")
    if isinstance(scenarios, list) and scenarios:
        lines.append(f"{labels['scenarios']}{heading_separator}")
        for item in scenarios[:summary_limit]:
            if not isinstance(item, dict):
                continue
            label = text_value(item.get("label"))
            text = text_value(item.get("text"))
            if text:
                lines.append(f"- {label + separator if label else ''}{text}")
    counter_evidence = text_list(answer.get("counter_evidence"), limit=2)
    if counter_evidence:
        lines.append(f"{labels['counter_evidence']}{heading_separator}")
        lines.extend(f"- {item}" for item in counter_evidence)
    risks = text_list(answer.get("risks"), limit=2)
    if risks:
        lines.append(f"{labels['risks']}{heading_separator}")
        lines.extend(f"- {item}" for item in risks)
    data_limits = text_list(answer.get("data_limits"), limit=2)
    if data_limits:
        lines.append(f"{labels['data_limits']}{heading_separator}")
        lines.extend(f"- {item}" for item in data_limits)
    return "\n".join(lines)


__all__ = [
    "analysis_horizon_label",
    "append_unique_texts",
    "confidence_label",
    "consumer_detail_from_llm_report",
    "consumer_text",
    "detail_labels",
    "pct_text",
    "response_is_english",
    "response_is_japanese",
    "response_locale",
    "stance_label",
    "target_fallback_label",
    "text_labels",
    "text_list",
    "text_value",
    "undecided_label",
]
