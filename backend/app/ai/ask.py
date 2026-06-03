from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy.orm import Session

from app.ai import freshness, orchestrator, reports, tools
from app.ai.schemas import AiAskRequest


VALID_SCOPE_TYPES = {"auto", "market", "data_freshness", "stock", "watchlist"}
VALID_MODES = {"auto", "data_only", "brief", "analysis", "report"}
VALID_RANK_BY = {"watchlist", "score", "change_pct", "volume"}
VALID_SORT_ORDER = {"asc", "desc"}


@dataclass(frozen=True)
class AiAskServerPolicy:
    can_call_llm: bool = False
    can_write: bool = False
    trust_source: str = "untrusted"

REPORT_HINTS = (
    "ai report",
    "llm",
    "report",
    "generate report",
    "formal report",
    "正式報告",
    "產生報告",
    "生成報告",
    "研究報告",
    "AI報告",
)
ANALYSIS_HINTS = (
    "analysis",
    "analyze",
    "interpret",
    "llm brief",
    "分析",
    "短評",
    "怎麼看",
    "看法",
    "解讀",
    "重點",
    "風險",
)
FRESHNESS_HINTS = (
    "freshness",
    "coverage",
    "更新狀態",
    "資料日期",
    "資料新鮮",
    "資料更新",
    "更新到",
    "缺資料",
)
WATCHLIST_HINTS = (
    "watchlist",
    "group",
    "sector",
    "群體",
    "群組",
    "族群",
    "分組",
    "自選",
)
MARKET_HINTS = (
    "market",
    "breadth",
    "大盤",
    "盤面",
    "市場",
    "漲跌家數",
)


def _contains_hint(question: str, hints: tuple[str, ...]) -> bool:
    lowered = question.lower()
    return any(hint.lower() in lowered for hint in hints)


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def _looks_like_stock_id(value: str | None) -> bool:
    if not value:
        return False

    return bool(re.fullmatch(r"\d{4,6}[A-Za-z0-9]?", value.strip()))


def _validate_request(payload: AiAskRequest) -> None:
    if payload.scope_type not in VALID_SCOPE_TYPES:
        raise ValueError(f"scope_type must be one of: {', '.join(sorted(VALID_SCOPE_TYPES))}")

    if payload.mode not in VALID_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")

    if payload.rank_by not in VALID_RANK_BY:
        raise ValueError(f"rank_by must be one of: {', '.join(sorted(VALID_RANK_BY))}")

    if payload.sort_order not in VALID_SORT_ORDER:
        raise ValueError(f"sort_order must be one of: {', '.join(sorted(VALID_SORT_ORDER))}")


def _infer_scope_type(payload: AiAskRequest) -> str:
    if payload.scope_type != "auto":
        return payload.scope_type

    scope_id = _normalize_text(payload.scope_id)
    question = payload.question

    if _contains_hint(question, FRESHNESS_HINTS):
        return "data_freshness"

    if _contains_hint(question, WATCHLIST_HINTS):
        return "watchlist"

    if scope_id and _looks_like_stock_id(scope_id):
        return "stock"

    if scope_id and scope_id.isdecimal():
        return "watchlist"

    if _contains_hint(question, MARKET_HINTS):
        return "market"

    return "market"


def _policy(payload: AiAskRequest, server_policy: AiAskServerPolicy) -> dict[str, Any]:
    can_call_llm = bool(payload.allow_llm and server_policy.can_call_llm)
    can_write = bool(payload.allow_write and server_policy.can_write)
    return {
        "allow_llm": payload.allow_llm,
        "allow_write": payload.allow_write,
        "server_trust_source": server_policy.trust_source,
        "server_can_call_llm": server_policy.can_call_llm,
        "server_can_write": server_policy.can_write,
        "can_call_llm": can_call_llm,
        "can_write": can_write,
        "can_generate_analysis": can_call_llm,
        "can_generate_report": bool(can_call_llm and can_write),
    }


def _infer_mode(payload: AiAskRequest, scope_type: str, policy: dict[str, Any]) -> str:
    if payload.mode != "auto":
        return payload.mode

    if scope_type in {"market", "data_freshness"}:
        return "data_only"

    if policy["can_generate_report"] and _contains_hint(payload.question, REPORT_HINTS):
        return "report"

    if policy["can_generate_analysis"] and _contains_hint(payload.question, ANALYSIS_HINTS):
        return "analysis"

    return "brief"


def _effective_mode(
    requested_mode: str,
    scope_type: str,
    policy: dict[str, Any],
    warnings: list[str],
) -> str:
    if requested_mode == "report" and not policy["can_generate_report"]:
        if policy["can_generate_analysis"] and scope_type in {"stock", "watchlist"}:
            warnings.append(
                "Report mode requires allow_write=true and a server-side trusted request; returned non-persistent analysis instead."
            )
            return "analysis"

        warnings.append(
            "Report mode requires allow_llm=true, allow_write=true, and a server-side trusted request; returned a brief instead."
        )
        return "brief" if scope_type in {"stock", "watchlist"} else "data_only"

    if requested_mode == "analysis" and not policy["can_generate_analysis"]:
        warnings.append(
            "Analysis mode requires allow_llm=true and a server-side trusted request; returned a brief instead."
        )
        return "brief" if scope_type in {"stock", "watchlist"} else "data_only"

    if requested_mode in {"brief", "analysis", "report"} and scope_type in {"market", "data_freshness"}:
        warnings.append(f"{scope_type} does not have a brief/analysis/report path yet; returned data_only.")
        return "data_only"

    return requested_mode


def _require_scope_id(payload: AiAskRequest, scope_type: str) -> str:
    scope_id = _normalize_text(payload.scope_id)
    if scope_id is None:
        raise ValueError(f"scope_id is required for scope_type={scope_type}")

    return scope_id


def _require_group_id(payload: AiAskRequest) -> int:
    scope_id = _require_scope_id(payload, "watchlist")
    try:
        return int(scope_id)
    except ValueError as exc:
        raise ValueError("scope_id must be a numeric watchlist group id.") from exc


def _read_data_only(db: Session, payload: AiAskRequest, scope_type: str) -> tuple[str, dict[str, Any]]:
    if scope_type == "market":
        return "omi.read_market_overview", tools.read_market_overview(
            db=db,
            limit=payload.market_limit,
        )

    if scope_type == "data_freshness":
        stock_id = payload.scope_id if _looks_like_stock_id(payload.scope_id) else None
        return "omi.read_data_freshness", tools.read_data_freshness(db=db, stock_id=stock_id)

    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.read_stock_context", tools.read_stock_context(
            db=db,
            stock_id=stock_id,
            branch_days=payload.branch_days,
        )

    group_id = _require_group_id(payload)
    return "omi.read_watchlist_context", tools.read_watchlist_context(
        db=db,
        group_id=group_id,
        include_children=payload.include_children,
        enabled_only=payload.enabled_only,
        rank_by=payload.rank_by,
        sort_order=payload.sort_order,
        limit=payload.context_limit,
    )


def _build_brief(db: Session, payload: AiAskRequest, scope_type: str) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_brief", reports.build_stock_brief(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
        )

    if scope_type == "watchlist":
        group_id = _require_group_id(payload)
        return "omi.generate_watchlist_brief", reports.build_watchlist_brief(
            db=db,
            group_id=group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
        )

    return _read_data_only(db, payload, scope_type)


def _generate_report(db: Session, payload: AiAskRequest, scope_type: str) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_report", orchestrator.generate_stock_llm_report(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
        )

    if scope_type == "watchlist":
        group_id = _require_group_id(payload)
        return "omi.generate_watchlist_llm_report", orchestrator.generate_watchlist_llm_report(
            db=db,
            group_id=group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
        )

    return _read_data_only(db, payload, scope_type)


def _generate_analysis(db: Session, payload: AiAskRequest, scope_type: str) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_analysis", orchestrator.generate_stock_llm_analysis(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
        )

    if scope_type == "watchlist":
        group_id = _require_group_id(payload)
        return "omi.generate_watchlist_llm_analysis", orchestrator.generate_watchlist_llm_analysis(
            db=db,
            group_id=group_id,
            strategy_profile=payload.strategy_profile,
            rank_by=payload.rank_by,
            sort_order=payload.sort_order,
        )

    return _read_data_only(db, payload, scope_type)


def _extract_list(result: dict[str, Any], key: str) -> list[Any]:
    value = result.get(key)
    return value if isinstance(value, list) else []


def _check_freshness(db: Session, payload: AiAskRequest, scope_type: str) -> dict[str, Any]:
    if scope_type == "stock":
        return freshness.check_stock_data_freshness(
            db=db,
            stock_id=_require_scope_id(payload, "stock"),
        )

    if scope_type == "watchlist":
        return freshness.check_watchlist_data_freshness(
            db=db,
            group_id=_require_group_id(payload),
            include_children=payload.include_children,
            enabled_only=payload.enabled_only,
        )

    return {}


def ask(
    db: Session,
    payload: AiAskRequest,
    *,
    server_policy: AiAskServerPolicy | None = None,
) -> dict[str, Any]:
    _validate_request(payload)

    scope_type = _infer_scope_type(payload)
    warnings: list[str] = []
    policy = _policy(payload, server_policy or AiAskServerPolicy())
    requested_mode = _infer_mode(payload, scope_type, policy)
    effective_mode = _effective_mode(requested_mode, scope_type, policy, warnings)
    freshness_result = _check_freshness(db, payload, scope_type)

    if freshness_result:
        policy["freshness_guard"] = {
            "is_current": freshness_result.get("is_current"),
            "stale_stock_count": freshness_result.get("stale_stock_count"),
            "missing": freshness_result.get("missing", []),
            "expected_dates": freshness_result.get("expected_dates", {}),
        }

    if freshness_result and not freshness_result.get("is_current", True) and effective_mode == "report":
        warnings.append(
            "Report mode skipped because local OMI data is incomplete; returned a brief instead."
        )
        effective_mode = "brief" if scope_type in {"stock", "watchlist"} else "data_only"

    if effective_mode == "data_only":
        action, result = _read_data_only(db, payload, scope_type)
    elif effective_mode == "brief":
        action, result = _build_brief(db, payload, scope_type)
    elif effective_mode == "analysis":
        action, result = _generate_analysis(db, payload, scope_type)
    elif effective_mode == "report":
        action, result = _generate_report(db, payload, scope_type)
    else:
        raise ValueError(f"Unsupported mode: {effective_mode}")

    result_warnings = _extract_list(result, "warnings")
    result_missing = _extract_list(result, "missing")
    result_source_refs = _extract_list(result, "source_refs")
    freshness_warnings = _extract_list(freshness_result, "warnings")
    freshness_missing = _extract_list(freshness_result, "missing")

    return {
        "kind": "ai_ask",
        "question": payload.question,
        "scope_type": scope_type,
        "scope_id": _normalize_text(payload.scope_id),
        "mode_requested": requested_mode,
        "mode_effective": effective_mode,
        "action": action,
        "strategy_profile": result.get("strategy_profile") or payload.strategy_profile,
        "caller_profile": payload.caller_profile,
        "policy": policy,
        "result": result,
        "freshness": freshness_result,
        "missing": list(dict.fromkeys(result_missing + freshness_missing)),
        "warnings": list(dict.fromkeys(warnings + freshness_warnings + result_warnings)),
        "source_refs": result_source_refs,
    }
