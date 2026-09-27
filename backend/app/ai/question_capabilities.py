from __future__ import annotations

import re
from typing import Any, Iterable


TW_HOT_GROUP_HINTS = (
    "熱門族群",
    "強弱族群",
    "族群強弱",
    "強勢族群",
    "族群排行",
    "熱門題材",
    "hot groups",
    "hot sectors",
    "sector strength",
)


def has_market_hot_group_intent(question: str) -> bool:
    """Shared market-group semantics; target/watchlist identity wins upstream."""
    lowered = question.casefold()
    if _has_hint(lowered, TW_HOT_GROUP_HINTS):
        return True
    if _has_hint(lowered, ("族群", "產業", "題材", "群組")):
        return _has_hint(lowered, (
            "最強", "最弱", "強弱", "偏強", "偏弱", "強勢", "弱勢",
            "排行", "熱門", "盤中", "表現", "試撮", "試搓", "盤前",
        ))
    return bool(
        re.search(r"\b(?:groups?|sectors?|industries)\b", lowered)
        and re.search(r"\b(?:market|hot|strongest|weakest|strong|weak|strength|performance|ranking|intraday)\b", lowered)
    )


def has_explicit_watchlist_intent(question: str) -> bool:
    return _has_hint(question, ("自選", "watchlist")) or bool(
        re.search(r"\b(?:my|our)\s+(?:groups?|sectors?)\b", question, re.IGNORECASE)
    )


US_INTRADAY_HINTS = (
    "intraday",
    "premarket",
    "pre-market",
    "after-hours",
    "latest",
    "live",
    "realtime",
    "盤中",
    "即時",
    "最新",
    "現在",
    "行情",
    "報價",
)
US_FUNDAMENTAL_HINTS = (
    "fundamental",
    "financial",
    "earnings",
    "sec",
    "財報",
    "基本面",
    "營收",
    "獲利",
)
US_INSIDER_HINTS = (
    "insider",
    "form 4",
    "form4",
    "內部人",
    "內部交易",
    "高管交易",
)
US_PROFILE_HINTS = (
    "company",
    "profile",
    "sector",
    "industry",
    "公司",
    "產業",
    "產業別",
)
US_CORPORATE_ACTION_HINTS = (
    "dividend",
    "split",
    "股利",
    "拆股",
    "除息",
)

US_TOOL_CAPABILITIES = {
    "us.read_intraday_trend": "us_intraday_trend",
    "us.refresh_quote": "us_intraday_trend",
    "us.refresh_intraday_bars": "us_intraday_trend",
    "us.refresh_daily_price": "us_daily_price",
    "us.refresh_company_profile": "us_company_profile",
    "us.refresh_sec_facts": "us_sec_company_fact",
    "us.read_sec_fundamentals": "us_sec_company_fact",
    "us.refresh_insider_transactions": "us_sec_insider_transactions",
    "us.refresh_corporate_actions": "us_corporate_action",
}


def _has_hint(question: str, hints: Iterable[str]) -> bool:
    lowered = question.casefold()
    return any(hint.casefold() in lowered for hint in hints)


def required_us_capabilities(
    question: str,
    *,
    instrument_type: str = "stock",
) -> tuple[str, ...]:
    required = ["us_daily_price"]
    if _has_hint(question, US_INTRADAY_HINTS):
        required.append("us_intraday_trend")
    if instrument_type != "index" and _has_hint(question, US_PROFILE_HINTS):
        required.append("us_company_profile")
    if instrument_type != "index" and _has_hint(question, US_FUNDAMENTAL_HINTS):
        required.extend(("us_company_profile", "us_sec_company_fact"))
    if instrument_type != "index" and _has_hint(question, US_INSIDER_HINTS):
        required.append("us_sec_insider_transactions")
    if instrument_type != "index" and _has_hint(question, US_CORPORATE_ACTION_HINTS):
        required.append("us_corporate_action")
    return tuple(dict.fromkeys(required))


def required_capabilities_for_question(
    question: str,
    target: dict[str, Any] | None,
) -> tuple[str, ...] | None:
    target = target or {}
    if target.get("type") != "us_stock":
        return None
    return required_us_capabilities(
        question,
        instrument_type=str(target.get("instrument_type") or "stock"),
    )


def tool_capability(tool_name: str | None) -> str | None:
    return US_TOOL_CAPABILITIES.get(str(tool_name or ""))


def capability_is_required(capability: str, required: set[str] | None) -> bool:
    if required is None:
        return True
    return capability in required
