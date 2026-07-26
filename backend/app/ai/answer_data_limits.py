from __future__ import annotations

from typing import Any

from app.ai.answer_localization import (
    append_unique_texts,
    confidence_label,
    consumer_text,
    response_is_english,
    response_is_japanese,
    response_locale,
    text_list,
    text_value,
)


SUMMARY_LIMIT_DEFAULT = 3
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
CRITICAL_SOURCE_HEALTH_RESOURCES = {
    "stock_master",
    "market_daily_price",
    "us_daily_price",
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
    "US fallback provider stale:",
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
SOURCE_HEALTH_PROBLEM_STATUSES = {
    "stale",
    "empty",
    "error",
    "unavailable",
    "partial",
}
SOURCE_HEALTH_STATUS_LABELS = {
    "stale": "落後",
    "empty": "無本地資料",
    "error": "讀取失敗",
    "unavailable": "不可用",
    "partial": "不完整",
}
SOURCE_HEALTH_STATUS_LABELS_EN = {
    "stale": "stale",
    "empty": "no local data",
    "error": "read failed",
    "unavailable": "unavailable",
    "partial": "partial",
}
SOURCE_HEALTH_STATUS_LABELS_JA = {
    "stale": "遅延",
    "empty": "ローカルデータなし",
    "error": "読み取り失敗",
    "unavailable": "利用不可",
    "partial": "不完全",
}
SOURCE_HEALTH_RESOURCE_LABELS = {
    "stock_master": "股票主檔",
    "market_daily_price": "日收盤",
    "market_daily_price.time": "日收盤時間",
    "institutional_trade_daily": "法人買賣超",
    "margin_trading_daily": "融資融券",
    "broker_branch_trade_daily": "券商分點",
    "shareholding_distribution_weekly": "股權分散",
    "monthly_revenue": "月營收",
    "financial_metric_quarterly": "季財務",
    "market_chip_daily": "大盤籌碼",
    "taifex_txo_option_chain": "臺指選擇權鏈與 Greeks",
    "taifex_large_trader_positions": "TAIFEX 大額交易人集中度",
    "taifex_txf_term_structure": "臺指期貨基差與期限結構",
    "taiwan_option_chain_daily": "臺指選擇權鏈與 Greeks",
    "taiwan_derivatives_large_trader_daily": "TAIFEX 大額交易人集中度",
    "taiwan_futures_term_structure_daily": "臺指期貨基差與期限結構",
    "intraday_trend": "盤中資料",
    "us_daily_price": "美股日線",
    "us_overnight_tw_impact": "美股隔夜影響",
}
SOURCE_HEALTH_RESOURCE_LABELS_EN = {
    "stock_master": "stock master",
    "market_daily_price": "daily price",
    "market_daily_price.time": "daily price timestamp",
    "institutional_trade_daily": "institutional trade",
    "margin_trading_daily": "margin trading",
    "broker_branch_trade_daily": "broker branch trade",
    "shareholding_distribution_weekly": "shareholding distribution",
    "monthly_revenue": "monthly revenue",
    "financial_metric_quarterly": "quarterly financial metrics",
    "market_chip_daily": "market chip flow",
    "taifex_txo_option_chain": "TAIEX options chain and Greeks",
    "taifex_large_trader_positions": "TAIFEX large-trader concentration",
    "taifex_txf_term_structure": "TAIEX futures basis and term structure",
    "taiwan_option_chain_daily": "TAIEX options chain and Greeks",
    "taiwan_derivatives_large_trader_daily": "TAIFEX large-trader concentration",
    "taiwan_futures_term_structure_daily": "TAIEX futures basis and term structure",
    "intraday_trend": "intraday data",
    "us_daily_price": "US daily price",
    "us_overnight_tw_impact": "US overnight impact",
}
SOURCE_HEALTH_RESOURCE_LABELS_JA = {
    "stock_master": "銘柄マスター",
    "market_daily_price": "日足価格",
    "market_daily_price.time": "日足価格の時刻",
    "institutional_trade_daily": "法人売買超",
    "margin_trading_daily": "信用取引",
    "broker_branch_trade_daily": "証券会社支店別売買",
    "shareholding_distribution_weekly": "株主分布",
    "monthly_revenue": "月次売上",
    "financial_metric_quarterly": "四半期財務指標",
    "market_chip_daily": "市場需給",
    "taifex_txo_option_chain": "台湾指数オプションチェーンと Greeks",
    "taifex_large_trader_positions": "TAIFEX 大口トレーダー集中度",
    "taifex_txf_term_structure": "台湾指数先物のベーシスと期間構造",
    "taiwan_option_chain_daily": "台湾指数オプションチェーンと Greeks",
    "taiwan_derivatives_large_trader_daily": "TAIFEX 大口トレーダー集中度",
    "taiwan_futures_term_structure_daily": "台湾指数先物のベーシスと期間構造",
    "intraday_trend": "日中データ",
    "us_daily_price": "米国日足価格",
    "us_overnight_tw_impact": "米国市場の一晩影響",
}


def warning_is_data_limit(value: Any) -> bool:
    text = text_value(value)
    if not text:
        return False
    if any(text.startswith(prefix) for prefix in NON_DATA_LIMIT_WARNING_PREFIXES):
        return False
    lowered = text.lower()
    return any(hint in lowered for hint in DATA_LIMIT_WARNING_HINTS)


def source_health_resource_label(
    value: Any,
    *,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    key = text_value(value) or ""
    base_key = key.split(".", 1)[0]
    locale = response_locale(response_preferences)
    labels = {
        "en-US": SOURCE_HEALTH_RESOURCE_LABELS_EN,
        "ja-JP": SOURCE_HEALTH_RESOURCE_LABELS_JA,
    }.get(locale, SOURCE_HEALTH_RESOURCE_LABELS)
    return labels.get(key) or labels.get(base_key) or key or (
        "data source"
        if locale == "en-US"
        else "データソース"
        if locale == "ja-JP"
        else "資料來源"
    )


def human_missing_data_limit(
    missing: list[Any],
    *,
    response_preferences: dict[str, Any] | None = None,
) -> str | None:
    labels = [
        source_health_resource_label(item, response_preferences=response_preferences)
        for item in missing
        if text_value(item)
    ]
    labels = list(dict.fromkeys(labels))
    if not labels:
        return None
    locale = response_locale(response_preferences)
    shown = labels[:4]
    remainder = len(labels) - len(shown)
    if locale == "en-US":
        detail = ", ".join(shown)
        if remainder > 0:
            detail += f", and {remainder} more"
        return f"Missing or stale data: {detail}. Keep the conclusion flexible."
    if locale == "ja-JP":
        detail = "、".join(shown)
        if remainder > 0:
            detail += f" ほか {remainder} 件"
        return f"不足または遅延データ：{detail}。結論は柔軟に扱ってください。"
    detail = "、".join(shown)
    if remainder > 0:
        detail += f" 等 {remainder} 項"
    return f"資料缺口或落後：{detail}；結論需保留彈性。"


def localized_data_limit_warning(
    value: Any,
    *,
    response_preferences: dict[str, Any] | None = None,
) -> str | None:
    text = text_value(value)
    if not text or not warning_is_data_limit(text):
        return None
    affected_marker = "affected datasets:"
    if text.startswith("Local OMI data is incomplete") and affected_marker in text:
        dataset_text = text.split(affected_marker, 1)[1].split(".", 1)[0]
        datasets = [item.strip() for item in dataset_text.split(",") if item.strip()]
        labels = [
            source_health_resource_label(item, response_preferences=response_preferences)
            for item in datasets
        ]
        labels = list(dict.fromkeys(labels))
        if labels:
            locale = response_locale(response_preferences)
            if locale == "en-US":
                return "Local OMI data is incomplete: " + ", ".join(labels) + ". Refresh before relying on the conclusion."
            if locale == "ja-JP":
                return "ローカル OMI データが未更新です：" + "、".join(labels) + "。結論に使う前に更新してください。"
            return "本地 OMI 資料尚未完整更新：" + "、".join(labels) + "；刷新後再依賴結論。"
    return text


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


def generic_data_limits(
    *,
    missing: list[Any],
    warnings: list[Any],
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    limits: list[str] = []
    if missing:
        missing_limit = human_missing_data_limit(missing, response_preferences=response_preferences)
        if missing_limit:
            limits.append(missing_limit)
    append_unique_texts(
        limits,
        [
            text
            for warning in text_list(warnings, limit=4)
            if (text := localized_data_limit_warning(warning, response_preferences=response_preferences))
        ],
        limit=3,
    )
    return limits


def source_health_data_limits(
    source_health: Any,
    *,
    limit: int = 3,
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(source_health, dict):
        return []
    locale = response_locale(response_preferences)
    english = locale == "en-US"
    japanese = locale == "ja-JP"
    entries = source_health.get("entries")
    if not isinstance(entries, list):
        return []
    limits: list[str] = []
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or entry.get("required") is False
            or entry.get("provider_role") == "fallback"
        ):
            continue
        status = text_value(entry.get("status"))
        if status not in SOURCE_HEALTH_PROBLEM_STATUSES:
            continue
        resource = text_value(entry.get("resource"))
        resource_labels = {
            "en-US": SOURCE_HEALTH_RESOURCE_LABELS_EN,
            "ja-JP": SOURCE_HEALTH_RESOURCE_LABELS_JA,
        }.get(locale, SOURCE_HEALTH_RESOURCE_LABELS)
        label = (
            resource_labels.get(resource or "")
            or text_value(entry.get("label"))
            or resource
            or ("data source" if english else "データソース" if japanese else "資料來源")
        )
        latest = text_value(entry.get("latest_data_date")) or text_value(entry.get("latest_data_key"))
        expected = text_value(entry.get("expected_data_date"))
        if status == "stale":
            if english:
                if latest and expected:
                    message = f"{label} data is stale: latest {latest}, expected {expected}."
                elif latest:
                    message = f"{label} data may be out of date: latest {latest}."
                else:
                    message = f"{label} data may be stale; refresh before relying on the conclusion."
            elif japanese:
                if latest and expected:
                    message = f"{label}データは遅延しています：最新 {latest}、想定 {expected}。"
                elif latest:
                    message = f"{label}データは古い可能性があります：最新 {latest}。"
                else:
                    message = f"{label}データは古い可能性があります。結論に使う前に更新を確認してください。"
            else:
                if latest and expected:
                    message = f"{label}資料落後：最新 {latest}，預期 {expected}。"
                elif latest:
                    message = f"{label}資料可能過期：最新 {latest}。"
                else:
                    message = f"{label}資料可能過期，需重新確認。"
        elif status == "empty":
            if english:
                message = f"{label} currently has no local data."
            elif japanese:
                message = f"{label}は現在ローカルデータがありません。"
            else:
                message = f"{label}目前沒有本地資料。"
        else:
            status_labels = {
                "en-US": SOURCE_HEALTH_STATUS_LABELS_EN,
                "ja-JP": SOURCE_HEALTH_STATUS_LABELS_JA,
            }.get(locale, SOURCE_HEALTH_STATUS_LABELS)
            status_label = status_labels.get(status, status)
            if english:
                message = f"{label} data status is {status_label}; keep the conclusion flexible."
            elif japanese:
                message = f"{label}データ状態は{status_label}です。結論は柔軟に扱ってください。"
            else:
                message = f"{label}資料狀態為{status_label}，結論需保留彈性。"
        if message not in limits:
            limits.append(message)
        if len(limits) >= limit:
            break
    return limits


def confidence_cap_from_evidence(
    *,
    analysis_digest: dict[str, Any],
    missing: list[Any] | None = None,
    warnings: list[Any] | None = None,
    response_preferences: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    caps: list[str] = []
    reasons: list[str] = []
    source_health = analysis_digest.get("source_health")
    if isinstance(source_health, dict):
        entries = source_health.get("entries")
        problem_entries = []
        critical_entries = []
        if isinstance(entries, list):
            for entry in entries:
                if (
                    not isinstance(entry, dict)
                    or entry.get("required") is False
                    or entry.get("provider_role") == "fallback"
                ):
                    continue
                status = text_value(entry.get("status"))
                if status not in SOURCE_HEALTH_PROBLEM_STATUSES:
                    continue
                problem_entries.append(entry)
                resource = text_value(entry.get("resource"))
                if resource in CRITICAL_SOURCE_HEALTH_RESOURCES or status in {"empty", "error", "unavailable"}:
                    critical_entries.append(entry)
        if critical_entries or len(problem_entries) >= 2:
            caps.append("low")
            if english:
                reasons.append("Critical source data has gaps, so confidence is capped at low.")
            elif japanese:
                reasons.append("重要なデータソースに不足があるため、信頼度の上限を低にします。")
            else:
                reasons.append("關鍵資料來源有缺口，信心上限降為低。")
        elif problem_entries:
            caps.append("medium")
            if english:
                reasons.append("Some source data is stale or incomplete, so confidence is capped at medium.")
            elif japanese:
                reasons.append("一部データソースが遅延または不完全なため、信頼度の上限を中にします。")
            else:
                reasons.append("部分資料來源落後或不完整，信心上限降為中。")
    clean_missing = text_list(missing or [], limit=6)
    if clean_missing:
        critical_missing = any(
            item in CRITICAL_SOURCE_HEALTH_RESOURCES or item.startswith("market_daily_price")
            for item in clean_missing
        )
        caps.append("low" if critical_missing else "medium")
        if english:
            reasons.append("Required data is still missing, so this cannot be marked as high confidence.")
        elif japanese:
            reasons.append("必要なデータがまだ不足しているため、高信頼とは表示できません。")
        else:
            reasons.append("仍有資料缺口，不能標示為高信心。")
    data_warning_count = sum(
        1
        for warning in text_list(warnings or [], limit=6)
        if warning_is_data_limit(warning)
    )
    if data_warning_count:
        caps.append("medium")
        if english:
            reasons.append("Data warnings are still present, so confidence is capped at medium.")
        elif japanese:
            reasons.append("データ警告が残っているため、信頼度の上限を中にします。")
        else:
            reasons.append("資料警示仍存在，信心上限降為中。")
    source_refs = analysis_digest.get("source_refs")
    if isinstance(source_refs, list) and not source_refs:
        caps.append("low" if clean_missing or data_warning_count else "medium")
        if english:
            reasons.append("No traceable source references were attached, so this cannot be marked as high confidence.")
        elif japanese:
            reasons.append("追跡可能なデータソースが添付されていないため、高信頼とは表示できません。")
        else:
            reasons.append("未取得可追溯資料來源，不能標示為高信心。")
    if not caps:
        return None, []
    cap = min(caps, key=lambda value: CONFIDENCE_ORDER[value])
    return cap, list(dict.fromkeys(reasons))[:2]


def apply_confidence_cap(
    answer: dict[str, Any],
    *,
    analysis_digest: dict[str, Any],
    missing: list[Any] | None = None,
    warnings: list[Any] | None = None,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    data_limit_cap: int = 3,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cap, reasons = confidence_cap_from_evidence(
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        response_preferences=response_preferences,
    )
    if cap is None:
        return answer
    current = text_value(answer.get("confidence"))
    if current not in CONFIDENCE_ORDER or CONFIDENCE_ORDER[current] <= CONFIDENCE_ORDER[cap]:
        return answer
    next_answer = dict(answer)
    next_answer["confidence"] = cap
    next_answer["confidence_label"] = confidence_label(cap, response_preferences)
    current_limits = text_list(next_answer.get("data_limits"))
    if response_is_english(response_preferences):
        reason_prefix = "Data reliability limit: "
    elif response_is_japanese(response_preferences):
        reason_prefix = "データ信頼度の制約："
    else:
        reason_prefix = "資料可信度限制："
    capped_reasons = [f"{reason_prefix}{reason}" for reason in reasons]
    next_answer["data_limits"] = list(dict.fromkeys(current_limits + capped_reasons))
    next_answer["text"] = consumer_text(
        next_answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return next_answer


def append_source_health_data_limits(
    answer: dict[str, Any],
    *,
    analysis_digest: dict[str, Any],
    missing: list[Any] | None = None,
    warnings: list[Any] | None = None,
    limit: int = 3,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_limits = source_health_data_limits(
        analysis_digest.get("source_health"),
        limit=limit,
        response_preferences=response_preferences,
    )
    next_answer = dict(answer)
    if source_limits:
        current_limits = text_list(next_answer.get("data_limits"))
        combined_limits = list(dict.fromkeys(source_limits[:limit] + current_limits))
        if combined_limits != current_limits:
            next_answer["data_limits"] = combined_limits
            next_answer["text"] = consumer_text(
                next_answer,
                response_preferences=response_preferences,
            )
    return apply_confidence_cap(
        next_answer,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        data_limit_cap=limit,
        response_preferences=response_preferences,
    )


__all__ = [
    "SOURCE_HEALTH_RESOURCE_LABELS_EN",
    "SOURCE_HEALTH_RESOURCE_LABELS_JA",
    "append_source_health_data_limits",
    "apply_confidence_cap",
    "confidence_cap_from_evidence",
    "filter_soft_data_gap_texts",
    "generic_data_limits",
    "human_missing_data_limit",
    "llm_text_is_soft_data_gap",
    "localized_data_limit_warning",
    "source_health_data_limits",
    "source_health_resource_label",
    "warning_is_data_limit",
]
