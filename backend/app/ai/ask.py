from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy.orm import Session

from app.ai import agentic_tools, freshness, orchestrator, reports, tools
from app.ai.evidence_passport import build_evidence_passport
from app.ai.schemas import AiAskRequest
from app.db.models import StockMaster, USStockMaster, WatchlistGroup
from app.us_market.sources import normalize_us_symbol


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
VALID_ANALYSIS_HORIZONS = {"auto", "intraday", "short", "swing", "long"}
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
CONSUMER_SUMMARY_LIMIT = 3


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
SHORT_HORIZON_HINTS = (
    "short",
    "daily",
    "day trade",
    "next session",
    "日k",
    "日K",
    "短線",
    "明天",
    "隔日",
    "這幾天",
    "1到5天",
    "1-5天",
)
SWING_HORIZON_HINTS = (
    "swing",
    "weekly",
    "week",
    "週k",
    "週K",
    "周k",
    "周K",
    "波段",
    "中短線",
    "這幾週",
    "幾週",
)
LONG_HORIZON_HINTS = (
    "long",
    "monthly",
    "month",
    "valuation",
    "fundamental",
    "月k",
    "月K",
    "長線",
    "投資",
    "基本面",
    "估值",
    "營收",
    "財報",
    "配息",
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
US_SYMBOL_CONTEXT_HINTS = (
    "us stock",
    "u.s. stock",
    "american stock",
    "ticker",
    "symbol",
    "nasdaq",
    "nyse",
    "amex",
    "arca",
    "美股",
    "美國股票",
    "美國上市",
    "那斯達克",
    "納斯達克",
    "紐交所",
    "美國個股",
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
US_SYMBOL_STOPWORDS = {
    "A",
    "AI",
    "ALL",
    "AND",
    "ANALYZE",
    "ADR",
    "CAN",
    "CEO",
    "ETF",
    "FOR",
    "GENERATE",
    "HOW",
    "IT",
    "LATEST",
    "LLM",
    "LOOK",
    "MAKE",
    "NOW",
    "OK",
    "ON",
    "OR",
    "PLEASE",
    "REPORT",
    "RISK",
    "STOCK",
    "THAT",
    "THE",
    "THIS",
    "TODAY",
    "US",
    "USA",
    "VIEW",
    "WHAT",
    "YOU",
}
US_EXCHANGE_SYMBOL_PATTERN = re.compile(
    r"\b(?:NASDAQ|NYSE|AMEX|NYSEARCA|ARCA|CBOE|OTC|OTCMKTS)[:：]\s*([A-Za-z][A-Za-z0-9.$-]{0,15})\b",
    flags=re.IGNORECASE,
)
US_DOLLAR_SYMBOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_$.-])\$([A-Za-z][A-Za-z0-9.$-]{0,15})(?![A-Za-z0-9.$-])"
)
US_PLAIN_SYMBOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.$-])([A-Za-z][A-Za-z0-9.$-]{0,15})(?![A-Za-z0-9.$-])"
)


def _contains_hint(question: str, hints: tuple[str, ...]) -> bool:
    lowered = question.lower()
    return any(hint.lower() in lowered for hint in hints)


def _normalize_analysis_horizon(value: str | None) -> str:
    normalized = (value or "auto").strip().lower()
    if normalized in {"today", "live", "realtime", "real-time", "now"}:
        return "intraday"
    if normalized in {"daily", "day", "short_term", "short-term"}:
        return "short"
    if normalized in {"weekly", "medium", "medium_short", "medium-short"}:
        return "swing"
    if normalized in {"monthly", "fundamental", "investment"}:
        return "long"
    return normalized


def _infer_analysis_horizon(payload: AiAskRequest) -> str:
    requested = _normalize_analysis_horizon(payload.analysis_horizon)
    if requested != "auto":
        return requested

    question = payload.question
    if _contains_hint(question, INTRADAY_HINTS):
        return "intraday"
    if _contains_hint(question, LONG_HORIZON_HINTS):
        return "long"
    if _contains_hint(question, SWING_HORIZON_HINTS):
        return "swing"
    if _contains_hint(question, SHORT_HORIZON_HINTS):
        return "short"

    if payload.strategy_profile in {"fundamentals_growth", "dividend_value"}:
        return "long"
    if payload.strategy_profile == "technical_swing":
        return "swing"

    return "swing"


def _include_tw_intraday(payload: AiAskRequest) -> bool:
    return bool(
        payload.allow_external_fetch
        and (
            _infer_analysis_horizon(payload) == "intraday"
            or _contains_hint(payload.question, INTRADAY_HINTS)
        )
    )


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


def _looks_like_us_symbol(value: str | None) -> bool:
    normalized = normalize_us_symbol(value)
    if not normalized:
        return False

    return bool(re.fullmatch(r"[A-Z][A-Z0-9.$-]{0,15}", normalized))


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


def _get_us_stock(db: Session | None, symbol: str | None) -> USStockMaster | None:
    if db is None or not symbol:
        return None

    normalized_symbol = normalize_us_symbol(symbol)
    if not normalized_symbol:
        return None

    return (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized_symbol)
        .filter(USStockMaster.is_active.is_(True))
        .first()
    )


def _us_stock_label(stock: USStockMaster | None, symbol: str) -> str:
    return (
        stock.security_name
        if stock and stock.security_name
        else stock.sec_company_name
        if stock and stock.sec_company_name
        else symbol
    )


def _resolve_us_stock_symbol(
    db: Session | None,
    symbol: str | None,
    *,
    source: str,
    confidence: str = "high",
    allow_unknown: bool = False,
) -> ScopeResolution | None:
    normalized_symbol = normalize_us_symbol(symbol)
    if not _looks_like_us_symbol(normalized_symbol):
        return None

    stock = _get_us_stock(db, normalized_symbol)
    if stock is None and not allow_unknown:
        return None

    label = _us_stock_label(stock, normalized_symbol)
    return ScopeResolution(
        selected_scope_type="us_stock",
        selected_scope_id=normalized_symbol,
        display_name=label,
        confidence=confidence if stock is not None else "medium",
        assumption=None if stock is not None else "未在 us_stock_master 找到完整主檔，先以 ticker 作為美股目標並回報資料缺口。",
        source=source if stock is not None else f"{source}_unverified_symbol",
        candidates=(
            _resolution_candidate(
                scope_type="us_stock",
                scope_id=normalized_symbol,
                label=label,
                confidence=confidence if stock is not None else "medium",
                source=source if stock is not None else f"{source}_unverified_symbol",
            ),
        ),
    )


def _question_has_us_symbol_context(question: str) -> bool:
    return (
        _contains_hint(question, US_SYMBOL_CONTEXT_HINTS)
        or _contains_hint(question, ADR_HINTS)
        or _contains_hint(question, STOCK_REFERENCE_HINTS)
        or _contains_hint(question, ANALYSIS_HINTS)
        or _contains_hint(question, INTRADAY_HINTS)
        or _contains_hint(question, SHORT_HORIZON_HINTS)
        or _contains_hint(question, SWING_HORIZON_HINTS)
        or _contains_hint(question, LONG_HORIZON_HINTS)
    )


def _iter_us_symbol_mentions(question: str) -> list[tuple[str, str, bool]]:
    mentions: list[tuple[str, str, bool]] = []
    seen: set[tuple[str, str]] = set()

    def add(raw_symbol: str, source: str, explicit_marker: bool) -> None:
        normalized_symbol = normalize_us_symbol(raw_symbol)
        if not _looks_like_us_symbol(normalized_symbol):
            return
        key = (normalized_symbol, source)
        if key in seen:
            return
        seen.add(key)
        mentions.append((normalized_symbol, source, explicit_marker))

    for match in US_EXCHANGE_SYMBOL_PATTERN.finditer(question):
        add(match.group(1), "question_us_exchange_symbol", True)

    for match in US_DOLLAR_SYMBOL_PATTERN.finditer(question):
        add(match.group(1), "question_dollar_symbol", True)

    for match in US_PLAIN_SYMBOL_PATTERN.finditer(question):
        raw_symbol = match.group(1)
        normalized_symbol = normalize_us_symbol(raw_symbol)
        if raw_symbol.upper() != raw_symbol and len(normalized_symbol) <= 2:
            continue
        add(raw_symbol, "question_us_symbol", False)

    return mentions


def _resolve_us_stock_symbol_from_question(db: Session | None, question: str) -> ScopeResolution | None:
    has_context = _question_has_us_symbol_context(question)
    candidates: list[tuple[ScopeResolution, bool]] = []

    for symbol, source, explicit_marker in _iter_us_symbol_mentions(question):
        if (
            not explicit_marker
            and symbol in US_SYMBOL_STOPWORDS
            and not _contains_hint(question, US_SYMBOL_CONTEXT_HINTS)
        ):
            continue

        allow_unknown = explicit_marker or (
            has_context and _contains_hint(question, US_SYMBOL_CONTEXT_HINTS)
        )
        resolution = _resolve_us_stock_symbol(
            db,
            symbol,
            source=source,
            confidence="high" if explicit_marker else "medium",
            allow_unknown=allow_unknown,
        )
        if resolution is None:
            continue

        if explicit_marker or has_context:
            candidates.append((resolution, explicit_marker))

    if not candidates:
        return None

    selected, selected_explicit = candidates[0]
    all_candidates = tuple(
        _resolution_candidate(
            scope_type="us_stock",
            scope_id=resolution.selected_scope_id,
            label=resolution.display_name,
            confidence="high" if explicit_marker else resolution.confidence,
            source=resolution.source,
        )
        for resolution, explicit_marker in candidates[:5]
    )
    return ScopeResolution(
        selected_scope_type="us_stock",
        selected_scope_id=selected.selected_scope_id,
        display_name=selected.display_name,
        confidence="high" if selected_explicit else selected.confidence,
        assumption=selected.assumption,
        source=selected.source,
        candidates=all_candidates,
    )


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

        us_symbol_resolution = _resolve_us_stock_symbol(
            db,
            target_id,
            source="explicit_scope_id",
            confidence="high",
            allow_unknown=_contains_hint(question, US_SYMBOL_CONTEXT_HINTS),
        )
        if us_symbol_resolution is not None:
            return us_symbol_resolution

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

    us_symbol_resolution = _resolve_us_stock_symbol_from_question(db, question)
    if us_symbol_resolution is not None:
        return us_symbol_resolution

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

    if _normalize_analysis_horizon(payload.analysis_horizon) not in VALID_ANALYSIS_HORIZONS:
        raise ValueError(
            f"analysis_horizon must be one of: {', '.join(sorted(VALID_ANALYSIS_HORIZONS))}"
        )

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
    report_capable_scopes = {"stock", "watchlist", "us_stock"}

    if requested_mode == "report" and not policy["can_generate_report"]:
        if policy["can_generate_analysis"] and scope_type in report_capable_scopes:
            warnings.append(
                "Report mode requires allow_write=true and a server-side trusted request; returned non-persistent analysis instead."
            )
            return "analysis"

        warnings.append(
            "Report mode requires allow_llm=true, allow_write=true, and a server-side trusted request; returned a brief instead."
        )
        return "brief" if scope_type in report_capable_scopes else "data_only"

    if requested_mode == "analysis" and not policy["can_generate_analysis"]:
        warnings.append(
            "Analysis mode requires allow_llm=true and a server-side trusted request; returned a brief instead."
        )
        return "brief" if scope_type in report_capable_scopes else "data_only"

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


def _read_data_only(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    tool_runs: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
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
            analysis_horizon=payload.analysis_horizon,
        )

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.read_us_stock_context", agentic_tools.read_us_stock_context(
            db=db,
            symbol=symbol,
            tool_runs=tool_runs,
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


def _build_brief(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    tool_runs: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_brief", reports.build_stock_brief(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
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
        return "omi.generate_us_stock_brief", reports.build_us_stock_brief(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs)


def _generate_report(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    tool_runs: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_report", orchestrator.generate_stock_llm_report(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
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

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_llm_report", orchestrator.generate_us_stock_llm_report(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs)


def _generate_analysis(
    db: Session,
    payload: AiAskRequest,
    scope_type: str,
    *,
    tool_runs: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        return "omi.generate_stock_llm_analysis", orchestrator.generate_stock_llm_analysis(
            db=db,
            stock_id=stock_id,
            strategy_profile=payload.strategy_profile,
            branch_days=payload.branch_days,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
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

    if scope_type == "us_stock":
        symbol = _require_scope_id(payload, "us_stock")
        return "omi.generate_us_stock_llm_analysis", orchestrator.generate_us_stock_llm_analysis(
            db=db,
            symbol=symbol,
            strategy_profile=payload.strategy_profile,
            analysis_horizon=payload.analysis_horizon,
            tool_runs=tool_runs,
        )

    return _read_data_only(db, payload, scope_type, tool_runs=tool_runs)


def _extract_list(result: dict[str, Any], key: str) -> list[Any]:
    value = result.get(key)
    return value if isinstance(value, list) else []


def _result_as_of(result: dict[str, Any], analysis: dict[str, Any]) -> Any:
    if result.get("as_of"):
        return result.get("as_of")
    if analysis.get("as_of"):
        return analysis.get("as_of")
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if summary.get("latest_trade_date"):
        return summary.get("latest_trade_date")
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
    if overview.get("as_of"):
        return overview.get("as_of")
    return None


def _score_display(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    sign = "+" if value > 0 else ""
    return f"{sign}{int(round(value))}"


def _text_value(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _text_list(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []

    texts: list[str] = []
    for item in value:
        text = _text_value(item)
        if text is None:
            continue
        if text in texts:
            continue
        texts.append(text)
        if limit is not None and len(texts) >= limit:
            break
    return texts


def _append_unique_texts(target: list[str], values: list[str], *, limit: int) -> None:
    for value in values:
        if value in target:
            continue
        target.append(value)
        if len(target) >= limit:
            return


def _llm_report_from_result(result: dict[str, Any]) -> dict[str, Any]:
    llm = result.get("llm") if isinstance(result.get("llm"), dict) else {}
    report = llm.get("report") if isinstance(llm.get("report"), dict) else None
    if isinstance(report, dict):
        return report

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    report = summary.get("llm") if isinstance(summary.get("llm"), dict) else None
    return report if isinstance(report, dict) else {}


def _consumer_detail_from_llm_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    headline = _text_value(report.get("headline"))
    if headline:
        lines.append(f"結論：{headline}")

    sections = (
        ("key_observations", "重點"),
        ("interpretation", "解讀"),
        ("risks", "風險"),
        ("missing_data", "資料限制"),
        ("next_checks", "下一步"),
    )
    for key, label in sections:
        items = _text_list(report.get(key))
        if not items:
            continue
        lines.append(f"{label}：")
        lines.extend(f"- {item}" for item in items)

    disclaimer = _text_value(report.get("disclaimer"))
    if disclaimer:
        lines.append(f"限制：{disclaimer}")
    return "\n".join(lines)


def _consumer_text(answer: dict[str, Any]) -> str:
    lines: list[str] = []
    headline = _text_value(answer.get("headline"))
    if headline:
        lines.append(f"結論：{headline}")

    stance = _text_value(answer.get("stance_label"))
    confidence = _text_value(answer.get("confidence_label"))
    if stance or confidence:
        parts = []
        if stance:
            parts.append(f"方向：{stance}")
        if confidence:
            parts.append(f"信心：{confidence}")
        lines.append(" / ".join(parts))

    summary = _text_list(answer.get("summary"), limit=CONSUMER_SUMMARY_LIMIT)
    if summary:
        lines.append("重點：")
        lines.extend(f"- {item}" for item in summary)

    actions = answer.get("action_plan")
    if isinstance(actions, list) and actions:
        lines.append("怎麼做：")
        for item in actions[:CONSUMER_SUMMARY_LIMIT]:
            if not isinstance(item, dict):
                continue
            label = _text_value(item.get("label"))
            text = _text_value(item.get("text"))
            if text:
                lines.append(f"- {label + '：' if label else ''}{text}")

    risks = _text_list(answer.get("risks"), limit=2)
    if risks:
        lines.append("風險：")
        lines.extend(f"- {item}" for item in risks)

    return "\n".join(lines)


def _generic_data_limits(*, missing: list[Any], warnings: list[Any]) -> list[str]:
    limits: list[str] = []
    if missing:
        limits.append(f"仍有 {len(missing)} 項資料缺口，結論需保留彈性。")
    _append_unique_texts(limits, _text_list(warnings, limit=2), limit=3)
    return limits


def _build_llm_consumer_answer(
    *,
    report: dict[str, Any],
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    stance = _text_value(report.get("stance"))
    confidence = _text_value(report.get("confidence"))
    headline = (
        _text_value(report.get("headline"))
        or _text_value(analysis_digest.get("selected_title"))
        or _text_value(target.get("label"))
        or "OMI 已完成分析"
    )

    summary: list[str] = []
    _append_unique_texts(summary, _text_list(report.get("key_observations"), limit=2), limit=CONSUMER_SUMMARY_LIMIT)
    _append_unique_texts(summary, _text_list(report.get("interpretation"), limit=2), limit=CONSUMER_SUMMARY_LIMIT)
    if not summary and analysis_digest.get("display"):
        summary.append(str(analysis_digest["display"]))

    interpretations = _text_list(report.get("interpretation"))
    next_checks = _text_list(report.get("next_checks"))
    risks = _text_list(report.get("risks"))
    missing_data = _text_list(report.get("missing_data"))

    action_plan = [
        {
            "label": "已持有",
            "text": interpretations[0] if interpretations else "先依目前結論觀察，不把單一訊號當成確認。",
        },
        {
            "label": "想進場",
            "text": next_checks[0] if next_checks else "等下一筆價格、量能或關鍵均線確認後再判斷。",
        },
        {
            "label": "失效",
            "text": risks[0] if risks else "若價格或量能轉弱，原本結論需要降級。",
        },
    ]
    data_limits = missing_data[:3] or _generic_data_limits(missing=missing, warnings=warnings)

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
        "detail": _consumer_detail_from_llm_report(report),
    }
    answer["text"] = _consumer_text(answer)
    return answer


def _build_watchlist_consumer_answer(
    *,
    human_answer: dict[str, Any],
    overview: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    sections = human_answer.get("sections") if isinstance(human_answer.get("sections"), list) else []
    section_map: dict[str, str] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = _text_value(section.get("label"))
        text = _text_value(section.get("text"))
        if label and text:
            section_map[label] = text

    lines = _text_list(human_answer.get("lines")) or _text_list(overview.get("answer_outline"))
    headline = section_map.get("結論") or _text_value(overview.get("display")) or (lines[0] if lines else "自選股整理完成")
    summary = [
        text
        for key in ("追蹤", "等回測", "保守")
        if (text := section_map.get(key))
    ]
    if not summary:
        summary = lines[1 : 1 + CONSUMER_SUMMARY_LIMIT]

    action_plan = [
        {"label": "優先看", "text": section_map.get("追蹤") or "先看排名與量價最明確的個股。"},
        {"label": "等回測", "text": section_map.get("等回測") or "漲幅過大的標的等回測後再確認。"},
        {"label": "保守", "text": section_map.get("保守") or "弱勢或資料不足標的先降低追蹤權重。"},
    ]
    data_limits = []
    if section_map.get("資料"):
        data_limits.append(section_map["資料"])
    data_limits.extend(_generic_data_limits(missing=missing, warnings=warnings))

    confidence = _text_value(overview.get("confidence"))
    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "watchlist_overview",
        "headline": headline,
        "stance": _text_value(overview.get("stance")),
        "stance_label": _text_value(overview.get("stance")) or "未定",
        "confidence": confidence,
        "confidence_label": CONFIDENCE_LABELS.get(str(confidence), confidence or "未定"),
        "summary": summary[:CONSUMER_SUMMARY_LIMIT],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": list(dict.fromkeys(data_limits))[:3],
        "detail": _text_value(human_answer.get("text")) or "\n".join(lines),
        "source_human_answer": human_answer,
    }
    answer["text"] = _consumer_text(answer)
    return answer


def _build_digest_consumer_answer(
    *,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    confidence = _text_value(analysis_digest.get("selected_confidence"))
    headline = (
        _text_value(analysis_digest.get("selected_title"))
        or _text_value(analysis_digest.get("display"))
        or _text_value(target.get("label"))
        or "OMI 已完成資料整理"
    )
    summary = [
        text
        for text in (
            _text_value(analysis_digest.get("display")),
            _text_value(analysis_digest.get("selected_summary")),
        )
        if text
    ]
    scores = analysis_digest.get("scores") if isinstance(analysis_digest.get("scores"), dict) else {}
    if scores:
        score_parts = [
            f"{ANALYSIS_HORIZON_LABELS.get(str(key), str(key))} {_score_display(value) or '-'}"
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
        "summary": list(dict.fromkeys(summary))[:CONSUMER_SUMMARY_LIMIT],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": _generic_data_limits(missing=missing, warnings=warnings),
        "detail": _text_value(analysis_digest.get("display")) or "",
    }
    answer["text"] = _consumer_text(answer)
    return answer


def _build_consumer_human_answer(
    *,
    target: dict[str, Any],
    result: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    report = _llm_report_from_result(result)
    if report:
        return _build_llm_consumer_answer(
            report=report,
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
        )

    human_answer = analysis_digest.get("human_answer") if isinstance(analysis_digest.get("human_answer"), dict) else {}
    if human_answer:
        return _build_watchlist_consumer_answer(
            human_answer=human_answer,
            overview=analysis_digest,
            missing=missing,
            warnings=warnings,
        )

    if analysis_digest:
        return _build_digest_consumer_answer(
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
        )

    return {}


def _extract_analysis_digest(result: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    analysis = (data or {}).get("analysis") if isinstance(data, dict) else None
    if isinstance(analysis, dict) and analysis:
        policy_horizon = policy.get("analysis_horizon") if isinstance(policy, dict) else {}
        selected_horizon = (
            analysis.get("selected_horizon")
            or (policy_horizon or {}).get("effective")
            or "swing"
        )
        horizon_label = ANALYSIS_HORIZON_LABELS.get(str(selected_horizon), str(selected_horizon))
        selected_score = analysis.get("selected_score")
        score_text = _score_display(selected_score)
        title = analysis.get("selected_title")
        summary = analysis.get("selected_summary")
        display_parts = [f"{horizon_label}評分 {score_text}" if score_text is not None else f"{horizon_label}評分 -"]
        if title:
            display_parts.append(str(title))
        if summary:
            display_parts.append(str(summary))

        return {
            "kind": "stock_analysis_digest",
            "requested_horizon": analysis.get("requested_horizon") or (policy_horizon or {}).get("requested"),
            "selected_horizon": selected_horizon,
            "horizon_label": horizon_label,
            "selected_timeframe": analysis.get("selected_timeframe"),
            "selected_score": selected_score,
            "score_display": score_text,
            "selected_title": title,
            "selected_summary": summary,
            "selected_confidence": analysis.get("selected_confidence"),
            "display": "｜".join(display_parts),
            "scores": analysis.get("scores") or {},
            "components": analysis.get("components") or [],
            "source": "result.data.analysis",
        }

    overview = (data or {}).get("overview") if isinstance(data, dict) else None
    if isinstance(overview, dict) and overview.get("kind") == "watchlist_sector_overview":
        human_answer = overview.get("human_answer") if isinstance(overview.get("human_answer"), dict) else {}
        answer_outline = human_answer.get("lines") or overview.get("answer_outline") or []
        return {
            "kind": "watchlist_sector_digest",
            "group_id": overview.get("group_id"),
            "group_name": overview.get("group_name"),
            "stance": overview.get("stance"),
            "confidence": overview.get("confidence"),
            "as_of": overview.get("as_of"),
            "display": overview.get("display"),
            "answer_outline": answer_outline,
            "human_answer": human_answer,
            "breadth": overview.get("breadth") or {},
            "strong_rows": overview.get("strong_rows") or [],
            "weak_rows": overview.get("weak_rows") or [],
            "watch_rows": overview.get("watch_rows") or [],
            "follow_rows": overview.get("follow_rows") or [],
            "pullback_rows": overview.get("pullback_rows") or [],
            "defensive_rows": overview.get("defensive_rows") or [],
            "data_status": overview.get("data_status") or {},
            "guidance": (
                "Prefer analysis.human_answer for the user-facing reply; avoid exposing raw missing dataset keys "
                "unless the user explicitly asks for debugging detail."
            ),
            "source": "result.data.overview",
        }

    return {}


def _check_freshness(db: Session, payload: AiAskRequest, scope_type: str) -> dict[str, Any]:
    if scope_type == "stock":
        stock_id = _require_scope_id(payload, "stock")
        stock_freshness = freshness.check_stock_data_freshness(
            db=db,
            stock_id=stock_id,
        )
        return agentic_tools.attach_us_overnight_gaps_to_tw_stock_freshness(
            db,
            stock_id=stock_id,
            stock_freshness=stock_freshness,
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
    response_warnings = [clarification["reason"]] if clarification.get("reason") else []
    evidence_passport = build_evidence_passport(
        kind="ai_ask",
        missing=["target_scope"],
        warnings=response_warnings,
        confidence="low",
    )

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
        "analysis": {},
        "policy": policy,
        "tool_plan": {},
        "tool_runs": [],
        "result": result,
        "freshness": {},
        "missing": [],
        "warnings": response_warnings,
        "source_refs": [],
        "evidence_passport": evidence_passport,
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

    requested_horizon = payload.analysis_horizon
    effective_horizon = _infer_analysis_horizon(payload)
    payload = payload.model_copy(update={"analysis_horizon": effective_horizon})

    warnings: list[str] = []
    policy = _policy(payload, server_policy or AiAskServerPolicy())
    policy["analysis_horizon"] = {
        "requested": requested_horizon,
        "effective": effective_horizon,
        "defaulted": _normalize_analysis_horizon(requested_horizon) == "auto",
    }
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

    if (
        scope_type == "watchlist"
        and _refresh_before_answer_enabled(payload)
        and payload.allow_external_fetch
        and freshness_result
        and freshness_result.get("refresh_recommended")
    ):
        tool_session = agentic_tools.run_tw_watchlist_tool_session(
            db=db,
            group_id=_require_group_id(payload),
            target=_resolution_target(resolution),
            policy=policy,
            raw_budget=payload.tool_budget,
            existing_freshness=freshness_result,
            include_children=payload.include_children,
            enabled_only=payload.enabled_only,
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
        effective_mode = "brief" if scope_type in {"stock", "watchlist", "us_stock"} else "data_only"

    if effective_mode == "data_only":
        action, result = _read_data_only(db, payload, scope_type, tool_runs=tool_runs)
    elif effective_mode == "brief":
        action, result = _build_brief(db, payload, scope_type, tool_runs=tool_runs)
    elif effective_mode == "analysis":
        action, result = _generate_analysis(db, payload, scope_type, tool_runs=tool_runs)
    elif effective_mode == "report":
        action, result = _generate_report(db, payload, scope_type, tool_runs=tool_runs)
    else:
        raise ValueError(f"Unsupported mode: {effective_mode}")

    result_warnings = _extract_list(result, "warnings")
    result_missing = _extract_list(result, "missing")
    result_source_refs = _extract_list(result, "source_refs")
    analysis_digest = _extract_analysis_digest(result, policy)
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
            "ADR-specific evidence is available through target.type=us_stock; answered from the resolved Taiwan stock context first."
        )

    combined_missing = list(dict.fromkeys(result_missing + freshness_missing))
    combined_warnings = list(dict.fromkeys(warnings + freshness_warnings + result_warnings))
    response_target = _resolution_target(resolution)
    consumer_human_answer = _build_consumer_human_answer(
        target=response_target,
        result=result,
        analysis_digest=analysis_digest,
        missing=combined_missing,
        warnings=combined_warnings,
    )
    response_analysis = dict(analysis_digest)
    if consumer_human_answer:
        response_analysis["human_answer"] = consumer_human_answer

    evidence_passport = build_evidence_passport(
        kind="ai_ask",
        as_of=_result_as_of(result, analysis_digest),
        source_refs=result_source_refs,
        missing=combined_missing,
        warnings=combined_warnings,
        freshness=freshness_result,
        tool_runs=tool_runs,
        analysis=analysis_digest,
    )

    return {
        "kind": "ai_ask",
        "contract_version": CONTRACT_VERSION,
        "question": payload.question,
        "target": response_target,
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
        "analysis": response_analysis,
        "policy": policy,
        "tool_plan": tool_plan,
        "tool_runs": tool_runs,
        "result": result,
        "freshness": freshness_result,
        "missing": combined_missing,
        "warnings": combined_warnings,
        "source_refs": result_source_refs,
        "evidence_passport": evidence_passport,
    }
