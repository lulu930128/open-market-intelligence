from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.ai.question_capabilities import tool_capability


SOURCE_GRADE_ORDER = {
    "official": 0,
    "local_database": 1,
    "derived": 2,
    "open_data": 3,
    "user_input": 4,
    "third_party": 5,
    "unknown": 6,
}
SOURCE_GRADE_LABELS = {
    "official": "官方/交易所資料",
    "local_database": "本機資料庫快取",
    "derived": "OMI 衍生計算",
    "open_data": "公開資料",
    "user_input": "使用者資料",
    "third_party": "第三方資料",
    "mixed": "混合來源",
    "unknown": "來源未標記",
}
TABLE_SOURCE_GRADES = {
    "stock_master": "official",
    "market_daily_price": "official",
    "institutional_trade_daily": "official",
    "margin_trading_daily": "official",
    "shareholding_distribution_weekly": "official",
    "monthly_revenue": "official",
    "financial_metric_quarterly": "official",
    "market_index_daily": "official",
    "market_index_daily_stats": "official",
    "taiwan_market_minute_state": "derived",
    "broker_branch_trade_daily": "third_party",
    "watchlist_group": "user_input",
    "watchlist_item": "user_input",
    "us_daily_price": "third_party",
    "us_company_profile": "third_party",
    "us_sec_company_fact": "official",
    "us_corporate_action": "third_party",
    "us_short_volume_daily": "third_party",
    "jp_stock_master": "official",
    "jp_daily_price": "third_party",
    "jp_company_fundamental": "third_party",
    "jp_margin_interest": "third_party",
    "jp_investor_type": "third_party",
}
CRITICAL_MISSING_KEYS = {
    "stock_master",
    "market_daily_price",
    "market_daily_price.daily",
    "us_daily_price",
}
STALE_WARNING_HINTS = (
    "stale",
    "older than",
    "incomplete",
    "not direct",
    "does not fetch live",
    "資料少於",
    "過期",
    "未更新",
    "尚未取得",
    "等待",
    "缺漏",
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _compact_strings(values: list[Any] | None) -> list[str]:
    if not values:
        return []
    compacted: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        compacted.append(text)
        seen.add(text)
    return compacted


def _source_name(ref: dict[str, Any]) -> str:
    return str(ref.get("name") or ref.get("kind") or ref.get("provider") or ref.get("type") or "unknown")


def _source_grade(ref: dict[str, Any]) -> str:
    raw_grade = ref.get("reliability_level") or ref.get("reliability") or ref.get("source_grade")
    if isinstance(raw_grade, str):
        normalized = raw_grade.strip().lower()
        if normalized in SOURCE_GRADE_ORDER:
            return normalized

    ref_type = str(ref.get("type") or "").strip().lower()
    ref_kind = str(ref.get("kind") or "").strip().lower()
    name = str(ref.get("name") or "").strip()

    if name in TABLE_SOURCE_GRADES:
        return TABLE_SOURCE_GRADES[name]
    if ref_kind in TABLE_SOURCE_GRADES:
        return TABLE_SOURCE_GRADES[ref_kind]
    if ref_type == "derived" or name.startswith("app."):
        return "derived"
    if ref_type == "database":
        return "local_database"
    if ref_type == "table":
        return "unknown"
    if ref_type == "external_or_cache":
        return "third_party"
    if ref_type == "user_input":
        return "user_input"
    if ref_type in SOURCE_GRADE_ORDER:
        return ref_type
    if ref_kind.startswith("us_"):
        return TABLE_SOURCE_GRADES.get(ref_kind, "third_party")
    return "unknown"


def _source_breakdown(source_refs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    breakdown: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in source_refs or []:
        if not isinstance(ref, dict):
            continue
        name = _source_name(ref)
        grade = _source_grade(ref)
        key = (name, grade)
        if key in seen:
            continue
        seen.add(key)
        item = {
            "name": name,
            "type": ref.get("type") or ref.get("kind") or "source",
            "grade": grade,
            "label": SOURCE_GRADE_LABELS.get(grade, SOURCE_GRADE_LABELS["unknown"]),
        }
        provider = ref.get("provider")
        if provider:
            item["provider"] = provider
        url = ref.get("url")
        if url:
            item["url"] = url
        breakdown.append(item)
    return breakdown


def _combined_source_grade(breakdown: list[dict[str, Any]]) -> str:
    if not breakdown:
        return "unknown"
    grades = {str(item.get("grade") or "unknown") for item in breakdown}
    if len(grades) == 1:
        return next(iter(grades))
    if grades <= {"official", "local_database", "derived"}:
        return "official"
    return "mixed"


def _freshness_status(
    *,
    freshness: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
    as_of: Any,
) -> str:
    if missing and any(key in CRITICAL_MISSING_KEYS for key in missing):
        return "missing"
    if isinstance(freshness, dict):
        explicit_status = str(freshness.get("status") or "").strip().lower()
        if explicit_status in {"current", "unknown", "partial", "stale", "missing"}:
            return explicit_status
        if freshness.get("is_current") is False:
            return "stale"
        if freshness.get("refresh_recommended"):
            return "stale"
        if freshness.get("missing"):
            return "partial"
        if freshness.get("is_current") is True:
            return "current"
    if missing:
        return "partial"
    warning_text = " ".join(warnings).lower()
    if warning_text and any(hint.lower() in warning_text for hint in STALE_WARNING_HINTS):
        return "partial"
    if as_of:
        return "current"
    return "unknown"


def _tool_run_penalty(
    tool_runs: list[dict[str, Any]] | None,
    *,
    required_capabilities: set[str] | None = None,
) -> tuple[int, list[str]]:
    penalty = 0
    flags: list[str] = []
    for run in tool_runs or []:
        if not isinstance(run, dict):
            continue
        status = str(run.get("status") or "").lower()
        tool = str(run.get("tool") or run.get("name") or "tool")
        capability = tool_capability(tool)
        if required_capabilities is not None and capability not in required_capabilities:
            continue
        if status in {"failed", "error", "timeout"}:
            penalty += 10
            flags.append(f"{tool} 執行逾時" if status == "timeout" else f"{tool} 執行失敗")
        elif status in {"blocked", "skipped"}:
            penalty += 6
            flags.append(f"{tool} 未執行")
    return penalty, flags


def _analysis_confidence(analysis: dict[str, Any] | None, confidence: str | None) -> str | None:
    if confidence:
        return confidence.strip().lower()
    if isinstance(analysis, dict):
        value = analysis.get("selected_confidence") or analysis.get("confidence")
        if isinstance(value, str):
            return value.strip().lower()
    return None


def _score_to_level(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    if score >= 30:
        return "low"
    return "blocked"


def _summary(level: str) -> str:
    if level == "high":
        return "資料可信度高：主要來源完整，暫未偵測到重大缺漏。"
    if level == "medium":
        return "資料可信度中：可用於觀察，但需留意部分來源、缺漏或信心限制。"
    if level == "low":
        return "資料可信度低：資料缺漏、過期或第三方來源比例較高，結論應保守。"
    return "資料可信度不足：缺少關鍵資料，不應產生強結論。"


def _quality_flags(
    *,
    source_grade: str,
    freshness_status: str,
    missing: list[str],
    warnings: list[str],
    tool_flags: list[str],
    confidence: str | None,
) -> list[str]:
    flags: list[str] = []
    if source_grade in {"mixed", "third_party", "unknown"}:
        flags.append(f"來源等級：{SOURCE_GRADE_LABELS.get(source_grade, source_grade)}")
    if freshness_status != "current":
        flags.append(f"資料新鮮度：{freshness_status}")
    if missing:
        flags.append(f"缺少資料：{', '.join(missing[:5])}")
    if warnings:
        flags.append(f"警示：{warnings[0]}")
    if confidence in {"low", "medium"}:
        flags.append(f"分析信心：{confidence}")
    flags.extend(tool_flags[:3])
    return list(dict.fromkeys(flags))


def build_evidence_passport(
    *,
    kind: str,
    as_of: Any = None,
    source_refs: list[dict[str, Any]] | None = None,
    missing: list[Any] | None = None,
    warnings: list[Any] | None = None,
    freshness: dict[str, Any] | None = None,
    tool_runs: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    confidence: str | None = None,
    required_capabilities: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    all_missing = _compact_strings(missing)
    all_warnings = _compact_strings(warnings)
    required_set = (
        {str(value) for value in required_capabilities if str(value).strip()}
        if required_capabilities is not None
        else None
    )
    compact_missing = (
        [value for value in all_missing if value in required_set]
        if required_set is not None
        else all_missing
    )
    warning_hints = {
        "us_daily_price": ("daily price", "daily cache", "日線"),
        "us_intraday_trend": ("intraday", "minute", "即時", "盤中", "行情"),
        "us_company_profile": ("company profile", "公司資料"),
        "us_sec_company_fact": ("sec", "fundamental", "財報", "基本面"),
        "us_corporate_action": ("dividend", "split", "股利", "拆股", "除息"),
    }
    if required_set is None:
        compact_warnings = all_warnings
    else:
        relevant_hints = tuple(
            hint.casefold()
            for capability in required_set
            for hint in warning_hints.get(capability, ())
        )
        compact_warnings = [
            warning
            for warning in all_warnings
            if not warning.startswith("US fallback provider stale:")
            and any(hint in warning.casefold() for hint in relevant_hints)
        ]
    scoped_freshness = freshness
    if required_set is not None and isinstance(freshness, dict):
        scoped_freshness = dict(freshness)
        scoped_freshness["missing"] = compact_missing
        scoped_freshness["warnings"] = compact_warnings
        scoped_freshness["is_current"] = not compact_missing
        scoped_freshness["refresh_recommended"] = bool(compact_missing)
    breakdown = _source_breakdown(source_refs)
    source_grade = _combined_source_grade(breakdown)
    data_freshness = _freshness_status(
        freshness=scoped_freshness,
        missing=compact_missing,
        warnings=compact_warnings,
        as_of=as_of,
    )
    selected_confidence = _analysis_confidence(analysis, confidence)
    tool_penalty, tool_flags = _tool_run_penalty(
        tool_runs,
        required_capabilities=required_set,
    )

    score = 100
    score -= {
        "official": 0,
        "local_database": 5,
        "derived": 10,
        "open_data": 8,
        "user_input": 12,
        "mixed": 12,
        "third_party": 20,
        "unknown": 30,
    }.get(source_grade, 30)
    score -= {
        "current": 0,
        "unknown": 8,
        "partial": 18,
        "stale": 30,
        "missing": 45,
    }.get(data_freshness, 8)
    score -= min(35, len(compact_missing) * 8)
    score -= min(20, len(compact_warnings) * 5)
    score -= tool_penalty
    if selected_confidence == "low":
        score -= 18
    elif selected_confidence == "medium":
        score -= 8

    if any(key in CRITICAL_MISSING_KEYS for key in compact_missing):
        score = min(score, 35)

    score = max(0, min(100, score))
    trust_level = _score_to_level(score)
    quality_flags = _quality_flags(
        source_grade=source_grade,
        freshness_status=data_freshness,
        missing=compact_missing,
        warnings=compact_warnings,
        tool_flags=tool_flags,
        confidence=selected_confidence,
    )

    reasons = [
        f"source_grade={source_grade}",
        f"data_freshness={data_freshness}",
    ]
    if selected_confidence:
        reasons.append(f"analysis_confidence={selected_confidence}")
    if compact_missing:
        reasons.append(f"missing_count={len(compact_missing)}")
    if compact_warnings:
        reasons.append(f"warning_count={len(compact_warnings)}")

    return {
        "kind": "evidence_passport",
        "target_kind": kind,
        "trust_level": trust_level,
        "trust_score": score,
        "data_freshness": data_freshness,
        "source_grade": source_grade,
        "as_of": _json_value(as_of),
        "summary": _summary(trust_level),
        "reasons": reasons,
        "quality_flags": quality_flags,
        "source_breakdown": breakdown,
        "missing": compact_missing,
        "warnings": compact_warnings,
        "required_capabilities": sorted(required_set) if required_set is not None else None,
        "ignored_missing": [value for value in all_missing if value not in compact_missing],
        "ignored_warnings": [value for value in all_warnings if value not in compact_warnings],
    }
