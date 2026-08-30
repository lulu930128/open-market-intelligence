from __future__ import annotations

from typing import Any, Iterable


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
