from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy.orm import Session

from app.ai import agentic_tools, freshness, orchestrator, reports, tools
from app.ai.schemas import AiAskRequest
from app.db.models import StockMaster, USStockMaster, WatchlistGroup


CONTRACT_VERSION = "omi.ai.ask.v2"
VALID_TARGET_TYPES = {"auto", "market", "data_freshness", "tw_stock", "tw_watchlist", "us_stock"}
INTERNAL_SCOPE_TO_TARGET_TYPE = {
    "market": "market",
    "data_freshness": "data_freshness",
    "stock": "tw_stock",
    "watchlist": "tw_watchlist",
    "us_stock": "us_stock",
}
TARGET_TYPE_TO_INTERNAL_SCOPE = {
    "market": "market",
    "data_freshness": "data_freshness",
    "tw_stock": "stock",
    "tw_watchlist": "watchlist",
    "us_stock": "us_stock",
}
VALID_MODES = {"auto", "data_only", "brief", "analysis", "report"}
VALID_RANK_BY = {"watchlist", "score", "change_pct", "volume"}
VALID_SORT_ORDER = {"asc", "desc"}


@dataclass(frozen=True)
class AiAskServerPolicy:
    can_call_llm: bool = False
    can_write: bool = False
    can_external_fetch: bool = False
    trust_source: str = "untrusted"


@dataclass(frozen=True)
class ScopeResolution:
    selected_scope_type: str
    selected_scope_id: str | None = None
    display_name: str | None = None
    confidence: str = "low"
    assumption: str | None = None
    source: str = "default"
    candidates: tuple[dict[str, Any], ...] = ()
    clarification_required: bool = False
    clarification_question: str | None = None
    clarification_reason: str | None = None


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
INTRADAY_HINTS = (
    "intraday",
    "live",
    "realtime",
    "real-time",
    "today",
    "now",
    "opening",
    "盤中",
    "即時",
    "今日",
    "今天",
    "現在",
    "開盤",
    "最新",
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
ADR_HINTS = (
    "adr",
    "nyse",
    "tsm adr",
    "美股台積電",
    "美股台積",
)
STOCK_REFERENCE_HINTS = (
    "stock",
    "company",
    "ticker",
    "個股",
    "股票",
    "這檔",
    "這支",
    "這家公司",
)
TAIWAN_TSMC_ALIASES = (
    "台積電",
    "台積",
    "tsmc",
)


def _contains_hint(question: str, hints: tuple[str, ...]) -> bool:
    lowered = question.lower()
    return any(hint.lower() in lowered for hint in hints)


def _include_tw_intraday(payload: AiAskRequest) -> bool:
    return bool(payload.allow_external_fetch and _contains_hint(payload.question, INTRADAY_HINTS))


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def _string_from_dict(value: dict[str, Any], key: str) -> str | None:
    raw_value = value.get(key)
    if raw_value is None:
        return None
    return _normalize_text(str(raw_value))


def _request_target(payload: AiAskRequest) -> dict[str, Any]:
    return payload.target if isinstance(payload.target, dict) else {"type": "auto"}


def _request_target_type(payload: AiAskRequest) -> str:
    target_type = _string_from_dict(_request_target(payload), "type") or "auto"
    return target_type.lower()


def _request_target_id(payload: AiAskRequest) -> str | None:
    target = _request_target(payload)
    return _string_from_dict(target, "id") or _string_from_dict(target, "symbol")


def _target_dict(
    *,
    scope_type: str,
    scope_id: str | None = None,
    label: str | None = None,
    market: str | None = None,
) -> dict[str, Any]:
    target_type = INTERNAL_SCOPE_TO_TARGET_TYPE.get(scope_type, scope_type)
    if market is None:
        if target_type.startswith("tw_"):
            market = "TW"
        elif target_type.startswith("us_"):
            market = "US"

    return {
        "type": target_type,
        "id": scope_id,
        "label": label,
        "market": market,
    }


def _resolution_target(resolution: ScopeResolution) -> dict[str, Any]:
    return _target_dict(
        scope_type=resolution.selected_scope_type,
        scope_id=resolution.selected_scope_id,
        label=resolution.display_name,
    )


def _looks_like_stock_id(value: str | None) -> bool:
    if not value:
        return False

    return bool(re.fullmatch(r"\d{4,6}[A-Za-z0-9]?", value.strip()))


def _resolution_candidate(
    *,
    scope_type: str,
    scope_id: str | None,
    label: str | None = None,
    confidence: str = "medium",
    source: str = "resolver",
) -> dict[str, Any]:
    return {
        "target": _target_dict(scope_type=scope_type, scope_id=scope_id, label=label),
        "confidence": confidence,
        "source": source,
    }


def _scope_resolution_dict(resolution: ScopeResolution) -> dict[str, Any]:
    return {
        "target": _resolution_target(resolution),
        "confidence": resolution.confidence,
        "assumption": resolution.assumption,
        "source": resolution.source,
        "candidates": list(resolution.candidates),
    }


def _clarification_dict(resolution: ScopeResolution) -> dict[str, Any]:
    return {
        "required": resolution.clarification_required,
        "question": resolution.clarification_question,
        "reason": resolution.clarification_reason,
    }


def _first_stock_id_in_text(text: str) -> str | None:
    for match in re.finditer(r"(?<!\d)(\d{4,6}[A-Za-z0-9]?)(?!\d)", text):
        value = match.group(1).strip()
        if _looks_like_stock_id(value):
            return value

    return None


def _first_watchlist_group_id_in_text(text: str) -> str | None:
    patterns = (
        r"\bwatchlist\s+group\s*#?\s*(\d+)\b",
        r"\bgroup\s*#?\s*(\d+)\b",
        r"(?:自選群組|自選|群組|分組)\s*#?\s*(\d+)",
    )

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def _stock_display_name(db: Session | None, stock_id: str, fallback: str | None = None) -> str | None:
    if db is None:
        return fallback

    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
    if stock is None:
        return fallback

    return stock.stock_name or fallback


def _us_stock_display_name(db: Session | None, symbol: str | None, fallback: str | None = None) -> str | None:
    if db is None or not symbol:
        return fallback

    normalized_symbol = symbol.strip().upper()
    stock = db.query(USStockMaster).filter(USStockMaster.symbol == normalized_symbol).first()
    if stock is None:
        return fallback

    return stock.security_name or stock.sec_company_name or fallback


def _target_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    target = candidate.get("target")
    return target if isinstance(target, dict) else {}


def _last_omi_resolution(payload: AiAskRequest) -> dict[str, Any]:
    context = payload.conversation_context if isinstance(payload.conversation_context, dict) else {}
    resolution = context.get("last_resolution")
    return resolution if isinstance(resolution, dict) else {}


def _last_resolution_us_candidate(payload: AiAskRequest) -> dict[str, Any] | None:
    resolution = _last_omi_resolution(payload)
    for candidate in resolution.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        target = _target_from_candidate(candidate)
        if target.get("type") == "us_stock" and target.get("id"):
            return target

    target = resolution.get("target") if isinstance(resolution.get("target"), dict) else {}
    if target.get("type") == "tw_stock" and str(target.get("id") or "") == "2330":
        return {
            "type": "us_stock",
            "id": "TSM",
            "label": "TSM ADR",
            "market": "US",
        }

    return None


def _resolve_stock_name_from_db(db: Session | None, question: str) -> ScopeResolution | None:
    if db is None:
        return None

    rows = (
        db.query(StockMaster.stock_id, StockMaster.stock_name)
        .filter(StockMaster.stock_name.isnot(None))
        .filter(StockMaster.is_active.is_(True))
        .all()
    )
    matches: list[tuple[str, str]] = []
    lowered_question = question.lower()

    for stock_id, stock_name in rows:
        name = (stock_name or "").strip()
        if len(name) < 2:
            continue

        if name in question or name.lower() in lowered_question:
            matches.append((str(stock_id), name))

    if not matches:
        return None

    matches.sort(key=lambda item: len(item[1]), reverse=True)
    stock_id, stock_name = matches[0]
    candidates = tuple(
        _resolution_candidate(
            scope_type="stock",
            scope_id=matched_stock_id,
            label=matched_name,
            confidence="high" if index == 0 else "medium",
            source="stock_master_name",
        )
        for index, (matched_stock_id, matched_name) in enumerate(matches[:5])
    )
    return ScopeResolution(
        selected_scope_type="stock",
        selected_scope_id=stock_id,
        display_name=stock_name,
        confidence="high",
        source="stock_master_name",
        candidates=candidates,
    )


def _resolve_tsmc_alias(db: Session | None, question: str) -> ScopeResolution | None:
    lowered_question = question.lower()
    has_adr_hint = _contains_hint(question, ADR_HINTS)
    has_tsm_adr = has_adr_hint and (
        bool(re.search(r"\btsm\b", lowered_question))
        or any(alias.lower() in lowered_question for alias in TAIWAN_TSMC_ALIASES)
    )

    if not has_tsm_adr and not any(alias.lower() in lowered_question for alias in TAIWAN_TSMC_ALIASES):
        return None

    display_name = _stock_display_name(db, "2330", fallback="台積電")
    adr_candidate = _resolution_candidate(
        scope_type="us_stock",
        scope_id="TSM",
        label="TSM ADR",
        confidence="medium" if has_tsm_adr else "low",
        source="tsmc_adr_alias",
    )
    tw_candidate = _resolution_candidate(
        scope_type="stock",
        scope_id="2330",
        label=display_name,
        confidence="medium" if has_tsm_adr else "high",
        source="canonical_alias",
    )
    assumption = "以台股 2330 台積電為主；TSM ADR 先列為候選 scope。"
    if not has_tsm_adr:
        assumption = "以台股 2330 台積電為主。"

    if has_tsm_adr:
        return ScopeResolution(
            selected_scope_type="us_stock",
            selected_scope_id="TSM",
            display_name="TSM ADR",
            confidence="high",
            assumption="問題明確指向 TSM ADR，優先使用美股 ADR context；台股 2330 作為關聯候選。",
            source="tsmc_adr_alias",
            candidates=(adr_candidate, tw_candidate),
        )

    return ScopeResolution(
        selected_scope_type="stock",
        selected_scope_id="2330",
        display_name=display_name,
        confidence="medium" if has_tsm_adr else "high",
        assumption=assumption,
        source="canonical_alias",
        candidates=(tw_candidate, adr_candidate),
    )


def _resolve_watchlist_group_name_from_db(db: Session | None, question: str) -> ScopeResolution | None:
    if db is None:
        return None

    rows = (
        db.query(WatchlistGroup.id, WatchlistGroup.group_name)
        .filter(WatchlistGroup.is_active.is_(True))
        .all()
    )
    matches: list[tuple[int, str]] = []
    lowered_question = question.lower()

    for group_id, group_name in rows:
        name = (group_name or "").strip()
        if len(name) < 2:
            continue

        if name in question or name.lower() in lowered_question:
            matches.append((int(group_id), name))

    if not matches:
        return None

    matches.sort(key=lambda item: len(item[1]), reverse=True)
    group_id, group_name = matches[0]
    candidates = tuple(
        _resolution_candidate(
            scope_type="watchlist",
            scope_id=str(matched_group_id),
            label=matched_name,
            confidence="high" if index == 0 else "medium",
            source="watchlist_group_name",
        )
        for index, (matched_group_id, matched_name) in enumerate(matches[:5])
    )
    return ScopeResolution(
        selected_scope_type="watchlist",
        selected_scope_id=str(group_id),
        display_name=group_name,
        confidence="high",
        source="watchlist_group_name",
        candidates=candidates,
    )


def _clarify_scope(scope_type: str, question: str, reason: str) -> ScopeResolution:
    if scope_type == "watchlist":
        clarification_question = "你想看哪一個自選群組？請提供群組 id 或群組名稱。"
    elif scope_type == "us_stock":
        clarification_question = "你想看哪一檔美股或 ADR？請提供 ticker，例如 TSM。"
    elif scope_type == "stock":
        clarification_question = "你想看哪一檔股票？請提供股票代號或股票名稱。"
    else:
        clarification_question = "你想查的是個股、族群、自選群組，還是整體市場？"

    return ScopeResolution(
        selected_scope_type=scope_type,
        confidence="low",
        source="clarification",
        clarification_required=True,
        clarification_question=clarification_question,
        clarification_reason=reason,
        candidates=(),
    )


def _resolve_scope(db: Session | None, payload: AiAskRequest) -> ScopeResolution:
    requested_target_type = _request_target_type(payload)
    target_id = _request_target_id(payload)
    question = payload.question

    if requested_target_type != "auto":
        scope_type = TARGET_TYPE_TO_INTERNAL_SCOPE.get(requested_target_type)
        if scope_type is None:
            return _clarify_scope(
                "market",
                question,
                f"target.type is not supported yet: {requested_target_type}.",
            )

        if scope_type in {"stock", "watchlist", "us_stock"} and target_id is None:
            return _clarify_scope(
                scope_type,
                question,
                f"target.id is required for target.type={requested_target_type}.",
            )

        return ScopeResolution(
            selected_scope_type=scope_type,
            selected_scope_id=target_id,
            display_name=(
                _stock_display_name(db, target_id)
                if scope_type == "stock" and target_id
                else _us_stock_display_name(db, target_id, fallback=target_id)
                if scope_type == "us_stock" and target_id
                else None
            ),
            confidence="high",
            source="explicit_request",
            candidates=(
                _resolution_candidate(
                    scope_type=scope_type,
                    scope_id=target_id,
                    label=None,
                    confidence="high",
                    source="explicit_request",
                ),
            ),
        )

    if _contains_hint(question, ADR_HINTS):
        us_candidate = _last_resolution_us_candidate(payload)
        if us_candidate is not None:
            symbol = str(us_candidate.get("id") or "").strip().upper()
            label = str(us_candidate.get("label") or "").strip() or _us_stock_display_name(db, symbol, fallback=symbol)
            return ScopeResolution(
                selected_scope_type="us_stock",
                selected_scope_id=symbol,
                display_name=label,
                confidence="high",
                assumption="根據上一輪 OMI resolution 的 ADR 候選，將追問解析為美股 ADR context。",
                source="conversation_resolution",
                candidates=(
                    _resolution_candidate(
                        scope_type="us_stock",
                        scope_id=symbol,
                        label=label,
                        confidence="high",
                        source="conversation_resolution",
                    ),
                ),
            )

    if target_id is not None:
        if _contains_hint(question, FRESHNESS_HINTS):
            stock_id = target_id if _looks_like_stock_id(target_id) else None
            return ScopeResolution(
                selected_scope_type="data_freshness",
                selected_scope_id=stock_id,
                display_name=_stock_display_name(db, stock_id) if stock_id else None,
                confidence="high",
                source="explicit_scope_id",
                candidates=(),
            )

        if _looks_like_stock_id(target_id):
            display_name = _stock_display_name(db, target_id)
            return ScopeResolution(
                selected_scope_type="stock",
                selected_scope_id=target_id,
                display_name=display_name,
                confidence="high",
                source="explicit_scope_id",
                candidates=(
                    _resolution_candidate(
                        scope_type="stock",
                        scope_id=target_id,
                        label=display_name,
                        confidence="high",
                        source="explicit_scope_id",
                    ),
                ),
            )

        if target_id.isdecimal():
            return ScopeResolution(
                selected_scope_type="watchlist",
                selected_scope_id=target_id,
                confidence="high",
                source="explicit_scope_id",
                candidates=(
                    _resolution_candidate(
                        scope_type="watchlist",
                        scope_id=target_id,
                        confidence="high",
                        source="explicit_scope_id",
                    ),
                ),
            )

    if _contains_hint(question, FRESHNESS_HINTS):
        stock_id = _first_stock_id_in_text(question)
        tsmc_resolution = _resolve_tsmc_alias(db, question)
        if stock_id is None and tsmc_resolution is not None:
            stock_id = tsmc_resolution.selected_scope_id

        return ScopeResolution(
            selected_scope_type="data_freshness",
            selected_scope_id=stock_id,
            display_name=_stock_display_name(db, stock_id) if stock_id else None,
            confidence="high" if stock_id else "medium",
            source="freshness_hint",
            candidates=(
                _resolution_candidate(
                    scope_type="stock",
                    scope_id=stock_id,
                    label=_stock_display_name(db, stock_id),
                    confidence="high",
                    source="question_stock_id",
                ),
            ) if stock_id else (),
        )

    if _contains_hint(question, WATCHLIST_HINTS):
        group_id = _first_watchlist_group_id_in_text(question)
        if group_id is not None:
            return ScopeResolution(
                selected_scope_type="watchlist",
                selected_scope_id=group_id,
                confidence="high",
                source="question_watchlist_group_id",
                candidates=(
                    _resolution_candidate(
                        scope_type="watchlist",
                        scope_id=group_id,
                        confidence="high",
                        source="question_watchlist_group_id",
                    ),
                ),
            )

        group_resolution = _resolve_watchlist_group_name_from_db(db, question)
        if group_resolution is not None:
            return group_resolution

        return _clarify_scope(
            "watchlist",
            question,
            "Question looks like a watchlist request but no group id or group name was resolved.",
        )

    stock_id = _first_stock_id_in_text(question)
    if stock_id is not None:
        display_name = _stock_display_name(db, stock_id)
        return ScopeResolution(
            selected_scope_type="stock",
            selected_scope_id=stock_id,
            display_name=display_name,
            confidence="high",
            source="question_stock_id",
            candidates=(
                _resolution_candidate(
                    scope_type="stock",
                    scope_id=stock_id,
                    label=display_name,
                    confidence="high",
                    source="question_stock_id",
                ),
            ),
        )

    tsmc_resolution = _resolve_tsmc_alias(db, question)
    if tsmc_resolution is not None:
        return tsmc_resolution

    stock_name_resolution = _resolve_stock_name_from_db(db, question)
    if stock_name_resolution is not None:
        return stock_name_resolution

    if _contains_hint(question, MARKET_HINTS):
        return ScopeResolution(
            selected_scope_type="market",
            confidence="medium",
            source="market_hint",
            candidates=(),
        )

    if _contains_hint(question, STOCK_REFERENCE_HINTS) or _contains_hint(question, ANALYSIS_HINTS):
        return _clarify_scope(
            "stock",
            question,
            "Question looks like a stock analysis request but no stock id or stock name was resolved.",
        )

    return ScopeResolution(
        selected_scope_type="market",
        confidence="low",
        assumption="未解析到明確個股或自選群組，先回傳本機市場概況。",
        source="default_market",
        candidates=(),
    )


def _validate_request(payload: AiAskRequest) -> None:
    target = _request_target(payload)
    target_type = _request_target_type(payload)
    if target_type not in VALID_TARGET_TYPES:
        raise ValueError(f"target.type must be one of: {', '.join(sorted(VALID_TARGET_TYPES))}")

    target_id = _request_target_id(payload)
    if target_id is not None and len(target_id) > 120:
        raise ValueError("target.id must be less than or equal to 120 characters.")

    if any(key in target for key in {"scope_type", "scope_id"}):
        raise ValueError("target must use v2 fields: type and id.")

    if payload.mode not in VALID_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")

    if payload.rank_by not in VALID_RANK_BY:
        raise ValueError(f"rank_by must be one of: {', '.join(sorted(VALID_RANK_BY))}")

    if payload.sort_order not in VALID_SORT_ORDER:
        raise ValueError(f"sort_order must be one of: {', '.join(sorted(VALID_SORT_ORDER))}")

    if not isinstance(payload.tool_budget, dict):
        raise ValueError("tool_budget must be an object.")

    if not isinstance(payload.refresh_policy, dict):
        raise ValueError("refresh_policy must be an object.")


def _infer_scope_type(payload: AiAskRequest) -> str:
    return _resolve_scope(db=None, payload=payload).selected_scope_type


def _policy(payload: AiAskRequest, server_policy: AiAskServerPolicy) -> dict[str, Any]:
    can_call_llm = bool(payload.allow_llm and server_policy.can_call_llm)
    can_write = bool(payload.allow_write and server_policy.can_write)
    can_external_fetch = bool(payload.allow_external_fetch and server_policy.can_external_fetch)
    tool_budget = agentic_tools.normalize_tool_budget(payload.tool_budget)
    return {
        "allow_llm": payload.allow_llm,
        "allow_write": payload.allow_write,
        "allow_external_fetch": payload.allow_external_fetch,
        "server_trust_source": server_policy.trust_source,
        "server_can_call_llm": server_policy.can_call_llm,
        "server_can_write": server_policy.can_write,
        "server_can_external_fetch": server_policy.can_external_fetch,
        "can_call_llm": can_call_llm,
        "can_write": can_write,
        "can_plan_tools": can_call_llm,
        "can_external_fetch": can_external_fetch,
        "can_generate_analysis": can_call_llm,
        "can_generate_report": bool(can_call_llm and can_write),
        "tool_budget": tool_budget,
        "refresh_policy": payload.refresh_policy,
    }


def _refresh_before_answer_enabled(payload: AiAskRequest) -> bool:
    policy = payload.refresh_policy if isinstance(payload.refresh_policy, dict) else {}
    mode = str(policy.get("mode") or "stale_first").strip().lower()
    if mode in {"off", "disabled", "none"}:
        return False
    return bool(policy.get("before_answer", True))


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

    if requested_mode in {"analysis", "report"} and scope_type == "us_stock":
        warnings.append("US stock LLM analysis/report is not persisted yet; returned a tool-augmented brief.")
        return "brief"

    if requested_mode in {"brief", "analysis", "report"} and scope_type in {"market", "data_freshness"}:
        warnings.append(f"{scope_type} does not have a brief/analysis/report path yet; returned data_only.")
        return "data_only"

    return requested_mode


def _require_scope_id(payload: AiAskRequest, scope_type: str) -> str:
    scope_id = _request_target_id(payload)
    if scope_id is None:
        raise ValueError(f"target.id is required for target.type={INTERNAL_SCOPE_TO_TARGET_TYPE.get(scope_type, scope_type)}")

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
        target_id = _request_target_id(payload)
        stock_id = target_id if _looks_like_stock_id(target_id) else None
        return "omi.read_data_freshness", tools.read_data_freshness(db=db, stock_id=stock_id)

    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.read_stock_context", tools.read_stock_context(
            db=db,
            stock_id=stock_id,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload),
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.read_us_stock_context", agentic_tools.read_us_stock_context(
            db=db,
            symbol=symbol,
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
            include_intraday=_include_tw_intraday(payload),
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

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        context = agentic_tools.read_us_stock_context(db=db, symbol=symbol)
        context["kind"] = "us_stock_brief"
        context["strategy_profile"] = payload.strategy_profile
        return "omi.generate_us_stock_brief", context

    return _read_data_only(db, payload, scope_type)


def _generate_report(db: Session, payload: AiAskRequest, scope_type: str) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_report", orchestrator.generate_stock_llm_report(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload),
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
            include_intraday=_include_tw_intraday(payload),
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

    if scope_type == "us_stock":
        return agentic_tools.scan_us_stock_gaps(
            db=db,
            symbol=_require_scope_id(payload, "us_stock"),
            question=payload.question,
        )

    return {}


def _report_level(effective_mode: str, freshness_result: dict[str, Any]) -> str:
    if effective_mode == "clarification":
        return "clarification"

    if effective_mode == "report":
        return "full_report"

    if effective_mode == "analysis":
        return "analysis"

    if effective_mode == "brief":
        if freshness_result and not freshness_result.get("is_current", True):
            return "brief_with_gaps"
        return "brief"

    return "data_only"


def _build_next_actions(
    *,
    resolution: ScopeResolution,
    clarification: dict[str, Any],
    freshness_result: dict[str, Any],
    effective_mode: str,
    policy: dict[str, Any],
    requested_mode: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    if clarification.get("required"):
        actions.append(
            {
                "type": "ask_clarification",
                "label": "Ask user to clarify the OMI target scope.",
                "question": clarification.get("question"),
                "reason": clarification.get("reason"),
            }
        )
        return actions

    if freshness_result and freshness_result.get("refresh_recommended"):
        actions.append(
            {
                "type": "refresh_data",
                "label": "Refresh local OMI evidence before relying on a full AI report.",
                "endpoint": freshness_result.get("refresh_endpoint"),
                "params": freshness_result.get("refresh_params") or {},
                "missing": freshness_result.get("missing") or [],
            }
        )

    if resolution.selected_scope_type != "us_stock" and any(
        (candidate.get("target") or {}).get("type") == "us_stock"
        for candidate in resolution.candidates
    ):
        actions.append(
            {
                "type": "connect_us_stock_context",
                "label": "Use US/ADR evidence before making ADR-specific conclusions.",
                "target": {
                    "type": "us_stock",
                    "id": "TSM",
                    "label": "TSM ADR",
                    "market": "US",
                },
            }
        )

    if (
        effective_mode == "brief"
        and requested_mode != "report"
        and policy.get("can_generate_report")
        and not (freshness_result and freshness_result.get("refresh_recommended"))
    ):
        actions.append(
            {
                "type": "generate_report",
                "label": "Generate a persisted OMI AI report for this resolved scope.",
                "target": _resolution_target(resolution),
            }
        )

    return actions


def _clarification_response(
    *,
    payload: AiAskRequest,
    resolution: ScopeResolution,
    requested_mode: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    clarification = _clarification_dict(resolution)
    next_actions = _build_next_actions(
        resolution=resolution,
        clarification=clarification,
        freshness_result={},
        effective_mode="clarification",
        policy=policy,
        requested_mode=requested_mode,
    )
    result = {
        "kind": "clarification_required",
        "message": clarification.get("question"),
        "reason": clarification.get("reason"),
    }

    return {
        "kind": "ai_ask",
        "contract_version": CONTRACT_VERSION,
        "question": payload.question,
        "target": _resolution_target(resolution),
        "mode": {
            "requested": requested_mode,
            "effective": "clarification",
        },
        "action": "omi.ask.clarify",
        "strategy_profile": payload.strategy_profile,
        "caller_profile": payload.caller_profile,
        "resolution": _scope_resolution_dict(resolution),
        "clarification": clarification,
        "next_actions": next_actions,
        "answer_ready": False,
        "report_level": "clarification",
        "policy": policy,
        "tool_plan": {},
        "tool_runs": [],
        "result": result,
        "freshness": {},
        "missing": [],
        "warnings": [clarification["reason"]] if clarification.get("reason") else [],
        "source_refs": [],
    }


def ask(
    db: Session,
    payload: AiAskRequest,
    *,
    server_policy: AiAskServerPolicy | None = None,
) -> dict[str, Any]:
    _validate_request(payload)

    resolution = _resolve_scope(db=db, payload=payload)
    scope_type = resolution.selected_scope_type
    if resolution.selected_scope_id != _request_target_id(payload) or _request_target_type(payload) == "auto":
        payload = payload.model_copy(
            update={"target": _resolution_target(resolution)}
        )

    warnings: list[str] = []
    policy = _policy(payload, server_policy or AiAskServerPolicy())
    requested_mode = _infer_mode(payload, scope_type, policy)
    if resolution.clarification_required:
        return _clarification_response(
            payload=payload,
            resolution=resolution,
            requested_mode=requested_mode,
            policy=policy,
        )

    effective_mode = _effective_mode(requested_mode, scope_type, policy, warnings)
    freshness_result = _check_freshness(db, payload, scope_type)
    tool_plan: dict[str, Any] = {}
    tool_runs: list[dict[str, Any]] = []

    if scope_type == "us_stock" and (payload.allow_external_fetch or policy.get("can_plan_tools")):
        tool_session = agentic_tools.run_us_stock_tool_session(
            db=db,
            question=payload.question,
            symbol=_require_scope_id(payload, "us_stock"),
            target=_resolution_target(resolution),
            policy=policy,
            raw_budget=payload.tool_budget,
        )
        tool_plan = tool_session["tool_plan"]
        tool_runs = tool_session["tool_runs"]
        warnings.extend(tool_session.get("warnings") or [])
        freshness_result = tool_session.get("freshness") or freshness_result

    if (
        scope_type == "stock"
        and _refresh_before_answer_enabled(payload)
        and payload.allow_external_fetch
        and freshness_result
        and freshness_result.get("refresh_recommended")
    ):
        tool_session = agentic_tools.run_tw_stock_tool_session(
            db=db,
            question=payload.question,
            stock_id=_require_scope_id(payload, "stock"),
            target=_resolution_target(resolution),
            policy=policy,
            raw_budget=payload.tool_budget,
            existing_freshness=freshness_result,
        )
        tool_plan = tool_session["tool_plan"]
        tool_runs = tool_session["tool_runs"]
        warnings.extend(tool_session.get("warnings") or [])
        freshness_result = tool_session.get("freshness") or freshness_result

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

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        result = agentic_tools.read_us_stock_context(
            db=db,
            symbol=symbol,
            tool_runs=tool_runs,
        )
        if effective_mode == "brief":
            result["kind"] = "us_stock_brief"
            result["strategy_profile"] = payload.strategy_profile
            action = "omi.generate_us_stock_brief"
        else:
            action = "omi.read_us_stock_context"
    elif effective_mode == "data_only":
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
    clarification = _clarification_dict(resolution)
    next_actions = _build_next_actions(
        resolution=resolution,
        clarification=clarification,
        freshness_result=freshness_result,
        effective_mode=effective_mode,
        policy=policy,
        requested_mode=requested_mode,
    )
    answer_ready = not clarification.get("required")
    if any(action.get("type") == "connect_us_stock_context" for action in next_actions):
        warnings.append(
            "ADR-specific evidence is not connected to omi.ask yet; answered from the Taiwan stock context first."
        )

    return {
        "kind": "ai_ask",
        "contract_version": CONTRACT_VERSION,
        "question": payload.question,
        "target": _resolution_target(resolution),
        "mode": {
            "requested": requested_mode,
            "effective": effective_mode,
        },
        "action": action,
        "strategy_profile": result.get("strategy_profile") or payload.strategy_profile,
        "caller_profile": payload.caller_profile,
        "resolution": _scope_resolution_dict(resolution),
        "clarification": clarification,
        "next_actions": next_actions,
        "answer_ready": answer_ready,
        "report_level": _report_level(effective_mode, freshness_result),
        "policy": policy,
        "tool_plan": tool_plan,
        "tool_runs": tool_runs,
        "result": result,
        "freshness": freshness_result,
        "missing": list(dict.fromkeys(result_missing + freshness_missing)),
        "warnings": list(dict.fromkeys(warnings + freshness_warnings + result_warnings)),
        "source_refs": result_source_refs,
    }
