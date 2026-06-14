from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy.orm import Session

from app.ai import agentic_tools, freshness, llm, orchestrator, reports, tools
from app.ai.evidence_passport import build_evidence_passport
from app.ai.schemas import AiAskRequest
from app.db.models import StockMaster, USStockMaster, WatchlistGroup
from app.us_market.sources import normalize_us_symbol


CONTRACT_VERSION = "omi.ai.ask.v2"
VALID_TARGET_TYPES = {
    "auto",
    "market",
    "data_freshness",
    "tw_stock",
    "tw_watchlist",
    "tw_index",
    "tw_futures",
    "us_stock",
}
TAIWAN_INDEX_TARGET_IDS = {"TAIEX", "TPEX"}
TAIWAN_FUTURES_TARGET_IDS = {"TXF", "MXF", "TMF"}
INTERNAL_SCOPE_TO_TARGET_TYPE = {
    "market": "market",
    "data_freshness": "data_freshness",
    "stock": "tw_stock",
    "watchlist": "tw_watchlist",
    "tw_index": "tw_index",
    "tw_futures": "tw_futures",
    "us_stock": "us_stock",
}
TARGET_TYPE_TO_INTERNAL_SCOPE = {
    "market": "market",
    "data_freshness": "data_freshness",
    "tw_stock": "stock",
    "tw_watchlist": "watchlist",
    "tw_index": "tw_index",
    "tw_futures": "tw_futures",
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
ENTRY_DECISION_HINTS = (
    "buy",
    "entry",
    "enter",
    "long",
    "accumulate",
    "買嗎",
    "該買",
    "可以買",
    "能買",
    "要買",
    "買入",
    "買進",
    "進場",
    "追嗎",
    "能追",
    "可以追",
    "該追",
    "加碼",
    "佈局",
    "布局",
    "值得買",
    "進嗎",
    "抄底",
    "低接",
    "買點",
    "哪裡買",
    "哪邊買",
    "哪裡接",
    "哪邊接",
    "接回",
    "回檔買",
    "回測買",
    "撿便宜",
)
EXIT_DECISION_HINTS = (
    "sell",
    "exit",
    "trim",
    "take profit",
    "stop loss",
    "賣嗎",
    "該賣",
    "要賣",
    "停利",
    "停損",
    "止盈",
    "止損",
    "出場",
    "減碼",
    "砍掉",
    "砍倉",
    "砍",
    "要不要賣",
    "該不該賣",
    "續抱",
    "抱嗎",
)
RISK_DECISION_HINTS = (
    "risk",
    "downside",
    "hedge",
    "short",
    "風險",
    "危險",
    "崩",
    "跌破",
    "避險",
    "空方",
    "轉弱",
    "失效",
)
TREND_VIEW_HINTS = (
    "trend",
    "view",
    "direction",
    "走勢",
    "趨勢",
    "怎麼看",
    "看法",
    "方向",
    "強弱",
    "短線",
    "波段",
)
POSITION_CONTEXT_HINTS = (
    "position",
    "holding",
    "entry price",
    "cost basis",
    "買在",
    "買進",
    "成本",
    "持有",
    "均價",
    "套牢",
    "停損",
    "止損",
    "停利",
    "止盈",
    "出場",
    "減碼",
    "續抱",
)
STOP_LOSS_HINTS = (
    "stop loss",
    "停損",
    "止損",
    "砍掉",
    "砍倉",
    "砍",
)
TAKE_PROFIT_HINTS = (
    "take profit",
    "停利",
    "止盈",
)
HOLD_DECISION_HINTS = (
    "hold",
    "續抱",
    "抱嗎",
    "還能抱",
    "該抱",
)
POSITION_ENTRY_PRICE_PATTERNS = (
    re.compile(
        r"(?:買在|買進(?:在|價)?|進場(?:在|價)?|成本(?:價)?(?:是|在|約|大概)?|"
        r"持有成本(?:是|在)?|均價(?:是|在)?|entry(?: price)?(?: at| is)?|"
        r"cost(?: basis)?(?: at| is)?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:元|塊)?\s*(?:買的|買進|進場|成本)",
        flags=re.IGNORECASE,
    ),
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


def _parse_number_token(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value.replace(",", ""))
    except ValueError:
        return None
    if number <= 0 or number != number:
        return None
    return number


def _extract_position_entry_price(question: str) -> tuple[float | None, str | None]:
    for pattern in POSITION_ENTRY_PRICE_PATTERNS:
        match = pattern.search(question)
        if not match:
            continue
        price = _parse_number_token(match.group(1))
        if price is not None:
            return price, match.group(0)
    return None, None


def _infer_position_context(question: str) -> dict[str, Any]:
    entry_price, entry_price_source = _extract_position_entry_price(question)
    has_position_context = entry_price is not None or _contains_hint(question, POSITION_CONTEXT_HINTS)

    if _contains_hint(question, STOP_LOSS_HINTS):
        decision_topic = "stop_loss"
    elif _contains_hint(question, TAKE_PROFIT_HINTS):
        decision_topic = "take_profit"
    elif _contains_hint(question, EXIT_DECISION_HINTS):
        decision_topic = "exit"
    elif _contains_hint(question, HOLD_DECISION_HINTS):
        decision_topic = "hold"
    elif _contains_hint(question, ENTRY_DECISION_HINTS):
        decision_topic = "entry"
    elif _contains_hint(question, RISK_DECISION_HINTS):
        decision_topic = "risk"
    else:
        decision_topic = "position" if has_position_context else "none"

    return {
        "kind": "position_context",
        "has_position_context": has_position_context,
        "entry_price": entry_price,
        "entry_price_source": entry_price_source,
        "decision_topic": decision_topic,
        "position_side": "long" if has_position_context else None,
    }


def _infer_question_intent(question: str) -> str:
    position_context = _infer_position_context(question)
    if (
        position_context.get("has_position_context")
        and position_context.get("decision_topic") in {"stop_loss", "take_profit", "exit", "hold", "risk"}
    ):
        return "position_risk_decision"
    if _contains_hint(question, ENTRY_DECISION_HINTS):
        return "entry_decision"
    if _contains_hint(question, EXIT_DECISION_HINTS):
        return "exit_decision"
    if _contains_hint(question, RISK_DECISION_HINTS):
        return "risk_check"
    if _contains_hint(question, TREND_VIEW_HINTS):
        return "trend_view"
    return "general"


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
    elif scope_type == "tw_index":
        clarification_question = "你想看哪一個台股指數？目前支援 TAIEX 或 TPEX。"
    elif scope_type == "tw_futures":
        clarification_question = "你想看哪一個台指期商品？目前支援 TXF、MXF 或 TMF。"
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
    requested_target = _request_target(payload)
    requested_label = _string_from_dict(requested_target, "label")
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

        if scope_type in {"stock", "watchlist", "us_stock", "tw_index", "tw_futures"} and target_id is None:
            return _clarify_scope(
                scope_type,
                question,
                f"target.id is required for target.type={requested_target_type}.",
            )

        if scope_type == "tw_index":
            normalized_index_id = str(target_id or "").strip().upper()
            if normalized_index_id not in TAIWAN_INDEX_TARGET_IDS:
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported Taiwan index target.id: {target_id}.",
                )
            target_id = normalized_index_id

        if scope_type == "tw_futures":
            normalized_futures_symbol = str(target_id or "").strip().upper()
            if normalized_futures_symbol not in TAIWAN_FUTURES_TARGET_IDS:
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported Taiwan futures target.id: {target_id}.",
                )
            target_id = normalized_futures_symbol

        display_name = (
            _stock_display_name(db, target_id)
            if scope_type == "stock" and target_id
            else _us_stock_display_name(db, target_id, fallback=target_id)
            if scope_type == "us_stock" and target_id
            else requested_label
        )
        return ScopeResolution(
            selected_scope_type=scope_type,
            selected_scope_id=target_id,
            display_name=display_name,
            confidence="high",
            source="explicit_request",
            candidates=(
                _resolution_candidate(
                    scope_type=scope_type,
                    scope_id=target_id,
                    label=display_name,
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
        normalized_target_id = target_id.upper()
        if normalized_target_id in TAIWAN_INDEX_TARGET_IDS:
            label = requested_label or normalized_target_id
            return ScopeResolution(
                selected_scope_type="tw_index",
                selected_scope_id=normalized_target_id,
                display_name=label,
                confidence="high",
                source="explicit_scope_id",
                candidates=(
                    _resolution_candidate(
                        scope_type="tw_index",
                        scope_id=normalized_target_id,
                        label=label,
                        confidence="high",
                        source="explicit_scope_id",
                    ),
                ),
            )

        if normalized_target_id in TAIWAN_FUTURES_TARGET_IDS:
            label = requested_label or f"{normalized_target_id} 台指期"
            return ScopeResolution(
                selected_scope_type="tw_futures",
                selected_scope_id=normalized_target_id,
                display_name=label,
                confidence="high",
                source="explicit_scope_id",
                candidates=(
                    _resolution_candidate(
                        scope_type="tw_futures",
                        scope_id=normalized_target_id,
                        label=label,
                        confidence="high",
                        source="explicit_scope_id",
                    ),
                ),
            )

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

    if policy["can_generate_analysis"] and policy.get("question_intent") in {"trend_view", "risk_check"}:
        return "analysis"

    return "brief"


def _effective_mode(
    requested_mode: str,
    scope_type: str,
    policy: dict[str, Any],
    warnings: list[str],
) -> str:
    answer_capable_scopes = {"stock", "watchlist", "us_stock", "tw_index", "tw_futures"}
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
        return "brief" if scope_type in answer_capable_scopes else "data_only"

    if requested_mode == "analysis" and not policy["can_generate_analysis"]:
        warnings.append(
            "Analysis mode requires allow_llm=true and a server-side trusted request; returned a brief instead."
        )
        return "brief" if scope_type in answer_capable_scopes else "data_only"

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

    if scope_type == "tw_index":
        index_id = _require_scope_id(payload, "tw_index")
        return "omi.read_tw_index_context", tools.read_tw_index_context(
            db=db,
            index_id=index_id,
            include_intraday=_include_tw_intraday(payload),
            analysis_horizon=payload.analysis_horizon,
        )

    if scope_type == "tw_futures":
        symbol = _require_scope_id(payload, "tw_futures")
        return "omi.read_tw_futures_context", tools.read_tw_futures_context(
            db=db,
            symbol=symbol,
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


def _consumer_detail_from_llm_report(
    report: dict[str, Any],
    *,
    missing_data_label: str = "資料限制",
) -> str:
    lines: list[str] = []
    headline = _text_value(report.get("headline"))
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


def _warning_is_data_limit(value: Any) -> bool:
    text = _text_value(value)
    if not text:
        return False
    if any(text.startswith(prefix) for prefix in NON_DATA_LIMIT_WARNING_PREFIXES):
        return False
    lowered = text.lower()
    return any(hint in lowered for hint in DATA_LIMIT_WARNING_HINTS)


def _llm_text_is_soft_data_gap(value: Any) -> bool:
    text = _text_value(value)
    if not text:
        return False
    lowered = text.lower()
    if any(hint in lowered for hint in LLM_SOFT_DATA_GAP_HINTS):
        return True
    if "無法確認" in text and any(hint in lowered for hint in LLM_INTRADAY_GAP_HINTS):
        return True
    return False


def _filter_soft_data_gap_texts(values: list[str], *, has_backend_missing: bool) -> list[str]:
    if has_backend_missing:
        return values
    return [value for value in values if not _llm_text_is_soft_data_gap(value)]


def _generic_data_limits(*, missing: list[Any], warnings: list[Any]) -> list[str]:
    limits: list[str] = []
    if missing:
        limits.append(f"仍有 {len(missing)} 項資料缺口，結論需保留彈性。")
    _append_unique_texts(
        limits,
        [text for text in _text_list(warnings, limit=4) if _warning_is_data_limit(text)],
        limit=3,
    )
    return limits


def _numeric_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value:
        return None
    return float(value)


def _stance_from_score(score: float | None) -> str:
    if score is None:
        return "insufficient_data"
    if score >= 2:
        return "bullish"
    if score <= -2:
        return "bearish"
    if score != 0:
        return "mixed"
    return "neutral"


def _numeric_data_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number != number:
        return None
    return number


def _format_price(value: float | None) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _format_signed_price(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{_format_price(value)}"


def _format_pct_value(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _level_price_text(level: Any) -> str | None:
    if not isinstance(level, dict):
        return None
    return _format_price(_numeric_data_value(level.get("price")))


def _zone_text(zone: Any) -> str | None:
    if not isinstance(zone, dict):
        return None
    low = _numeric_data_value(zone.get("low"))
    high = _numeric_data_value(zone.get("high"))
    if low is not None and high is not None:
        return f"{_format_price(low)}-{_format_price(high)}"
    if low is not None:
        return _format_price(low)
    if high is not None:
        return _format_price(high)
    return None


def _zone_bounds(zone: Any) -> tuple[float | None, float | None]:
    if not isinstance(zone, dict):
        return None, None
    low = _numeric_data_value(zone.get("low"))
    high = _numeric_data_value(zone.get("high"))
    if low is not None and high is not None and low > high:
        return high, low
    return low, high


def _technical_level_fields(levels: dict[str, Any]) -> dict[str, str]:
    if not isinstance(levels, dict) or levels.get("kind") != "technical_price_levels":
        return {}
    entry = levels.get("entry") if isinstance(levels.get("entry"), dict) else {}
    risk = levels.get("risk") if isinstance(levels.get("risk"), dict) else {}
    return {
        key: value
        for key, value in {
            "latest": _format_price(_numeric_data_value(levels.get("latest_price"))),
            "preferred": _zone_text(entry.get("preferred_zone")),
            "aggressive": _zone_text(entry.get("aggressive_zone")),
            "conservative": _zone_text(entry.get("conservative_zone")),
            "chase": _level_price_text(entry.get("do_not_chase_above")),
            "breakout": _level_price_text(entry.get("breakout_confirm_above")),
            "stop": _level_price_text(risk.get("short_stop")),
            "invalidation": _level_price_text(risk.get("technical_invalidation")),
        }.items()
        if value and value != "-"
    }


def _technical_level_numbers(levels: dict[str, Any]) -> dict[str, float | None]:
    if not isinstance(levels, dict) or levels.get("kind") != "technical_price_levels":
        return {}
    entry = levels.get("entry") if isinstance(levels.get("entry"), dict) else {}
    risk = levels.get("risk") if isinstance(levels.get("risk"), dict) else {}
    preferred_low, preferred_high = _zone_bounds(entry.get("preferred_zone"))
    aggressive_low, aggressive_high = _zone_bounds(entry.get("aggressive_zone"))
    conservative_low, conservative_high = _zone_bounds(entry.get("conservative_zone"))
    return {
        "latest": _numeric_data_value(levels.get("latest_price")),
        "preferred_low": preferred_low,
        "preferred_high": preferred_high,
        "aggressive_low": aggressive_low,
        "aggressive_high": aggressive_high,
        "conservative_low": conservative_low,
        "conservative_high": conservative_high,
        "chase": _numeric_data_value((entry.get("do_not_chase_above") or {}).get("price")),
        "breakout": _numeric_data_value((entry.get("breakout_confirm_above") or {}).get("price")),
        "stop": _numeric_data_value((risk.get("short_stop") or {}).get("price")),
        "invalidation": _numeric_data_value((risk.get("technical_invalidation") or {}).get("price")),
    }


def _entry_price_position(numbers: dict[str, float | None]) -> str:
    latest = numbers.get("latest")
    if latest is None:
        return "unknown"

    invalidation = numbers.get("invalidation")
    if invalidation is not None and latest < invalidation:
        return "below_invalidation"

    stop = numbers.get("stop")
    if stop is not None and latest < stop:
        return "below_stop"

    breakout = numbers.get("breakout")
    if breakout is not None and latest >= breakout:
        return "breakout_confirmed"

    preferred_low = numbers.get("preferred_low")
    preferred_high = numbers.get("preferred_high")
    if preferred_low is not None and latest < preferred_low:
        return "below_preferred"
    if (
        preferred_low is not None
        and preferred_high is not None
        and preferred_low <= latest <= preferred_high
    ):
        return "in_preferred"
    if preferred_low is not None and preferred_high is None and latest >= preferred_low:
        return "in_preferred"
    if preferred_high is not None and preferred_low is None and latest <= preferred_high:
        return "in_preferred"

    chase = numbers.get("chase")
    if chase is not None and latest > chase:
        return "above_chase"
    if preferred_high is not None and latest > preferred_high:
        return "above_preferred"
    if chase is not None and latest <= chase:
        return "below_chase"
    return "unknown"


def _entry_risk_text(fields: dict[str, str]) -> str:
    risk_parts = []
    if fields.get("stop"):
        risk_parts.append(f"跌破 {fields['stop']} 先停止低接")
    if fields.get("invalidation"):
        risk_parts.append(f"跌破 {fields['invalidation']} 波段假設失效")
    return "；".join(risk_parts) + "。" if risk_parts else "若量能放大轉弱或跌回關鍵均線下方，買進假設要降級。"


def _entry_confirmation_text(
    fields: dict[str, str],
    numbers: dict[str, float | None],
) -> str | None:
    latest = numbers.get("latest")
    conservative_low = numbers.get("conservative_low")
    confirmation_parts = []
    if fields.get("conservative") and latest is not None and conservative_low is not None and conservative_low > latest:
        confirmation_parts.append(f"{fields['conservative']} 視為重新轉強確認區，不是現在的低接買點")
    if fields.get("breakout"):
        confirmation_parts.append(f"突破確認 {fields['breakout']} 是趨勢轉強訊號，不是現價附近買點")
    if not confirmation_parts:
        return None
    return "；".join(confirmation_parts) + "。"


def _entry_decision_summary_lines(
    fields: dict[str, str],
    numbers: dict[str, float | None],
    price_position: str,
) -> list[str]:
    latest = fields.get("latest")
    preferred = fields.get("preferred")
    chase = fields.get("chase")
    lines: list[str] = []

    if price_position == "in_preferred" and latest and preferred:
        lines.append(
            f"現價 {latest} 已落在 {preferred} 回檔觀察區；這是可觀察位置，但要等守穩與量能轉強，不是自動買點。"
        )
    elif price_position == "above_chase" and latest and chase:
        breakout = fields.get("breakout")
        next_check = f"除非有效突破 {breakout}" if breakout else "除非重新轉強"
        lines.append(f"現價 {latest} 高於追價上限 {chase}；{next_check}，否則不適合追。")
    elif price_position == "breakout_confirmed" and latest:
        breakout = fields.get("breakout")
        lines.append(
            f"現價 {latest} 已到突破確認區"
            + (f" {breakout}" if breakout else "")
            + "；買點要改看突破後是否站穩。"
        )
    elif price_position == "below_preferred" and latest and preferred:
        lines.append(f"現價 {latest} 尚未進入偏好回檔區 {preferred}；等更接近區間並止跌再評估。")
    elif price_position == "above_preferred" and latest and preferred:
        chase_text = f"、仍低於追價上限 {chase}" if chase else ""
        lines.append(f"現價 {latest} 已高於回檔觀察區 {preferred}{chase_text}；可觀察但不是低接買點。")
    elif price_position in {"below_stop", "below_invalidation"} and latest:
        lines.append(f"現價 {latest} 已跌到風控區下方；先不要把低價當成便宜。")
    elif latest:
        lines.append(f"現價 {latest}；買點需要搭配價格位置、量能與動能確認。")

    risk_text = _entry_risk_text(fields)
    if risk_text:
        lines.append(risk_text)

    confirmation_text = _entry_confirmation_text(fields, numbers)
    if confirmation_text:
        lines.append(confirmation_text)

    return lines[:CONSUMER_SUMMARY_LIMIT]


def _entry_decision_with_levels(
    *,
    target_label: str,
    score: float | None,
    weak_evidence: bool,
    fields: dict[str, str],
    numbers: dict[str, float | None],
) -> tuple[str, list[str], list[dict[str, str]]]:
    price_position = _entry_price_position(numbers)
    latest = fields.get("latest") or "-"
    preferred = fields.get("preferred")
    chase = fields.get("chase")
    conservative = fields.get("conservative")
    score_bearish = score is not None and score <= -1
    score_bullish = score is not None and score >= 2

    if weak_evidence:
        headline = f"{target_label} 先不要直接買，資料或信心還不足"
    elif price_position == "in_preferred" and preferred:
        if score_bearish:
            headline = f"{target_label} 已在回檔觀察區，但短線偏弱，現在不是好買點"
        elif score_bullish:
            headline = f"{target_label} 已回到可觀察買點區，但仍要等守穩與量能確認"
        else:
            headline = f"{target_label} 已在回檔觀察區，先等守穩再分批評估"
    elif price_position == "above_chase" and chase:
        headline = f"{target_label} 已高於追價上限 {chase}，不建議追價"
    elif price_position == "breakout_confirmed" and fields.get("breakout"):
        headline = f"{target_label} 已到突破確認區，買點要改看突破後是否站穩"
    elif price_position == "below_preferred" and preferred:
        headline = f"{target_label} 還沒回到偏好買點區，先等回檔與止跌訊號"
    elif price_position == "above_preferred" and preferred:
        headline = f"{target_label} 已高於回檔觀察區，等回測 {preferred} 或突破確認，不建議直接追價"
    elif price_position in {"below_stop", "below_invalidation"}:
        headline = f"{target_label} 已跌到風控區，先不要低接"
    elif score_bullish:
        headline = f"{target_label} 可以列入偏多觀察，但不建議直接追價"
    elif score_bearish:
        headline = f"{target_label} 目前不建議直接買，先等價位與動能轉強"
    else:
        headline = f"{target_label} 先觀望，等方向與價位確認"

    if price_position == "in_preferred" and preferred:
        now_text = (
            f"現價 {latest} 已在 {preferred} 內，可以觀察，但短線分數偏弱，先不要直接買。"
            if score_bearish
            else f"現價 {latest} 已在 {preferred} 內，可列入買點觀察，但仍要等守穩。"
        )
        condition_parts = [f"{preferred} 守住", "量能或動能轉強"]
        if chase:
            condition_parts.append(f"若價格接近或高於 {chase}，視為追價，部位要降")
        if conservative and numbers.get("conservative_low") and numbers.get("latest"):
            if numbers["conservative_low"] > numbers["latest"]:
                condition_parts.append(f"{conservative} 改視為重新轉強確認區")
        entry_text = "；".join(condition_parts) + "。"
    elif price_position == "above_chase" and preferred:
        now_text = f"現價 {latest} 已偏離理想買點，不要把追高當成進場。"
        entry_text = (
            f"等回到 {preferred} 並止跌，或有效突破 {fields['breakout']} 後再重新評估。"
            if fields.get("breakout")
            else f"等回到 {preferred} 並止跌後再重新評估。"
        )
    elif price_position == "below_preferred" and preferred:
        now_text = f"現價 {latest} 還沒到偏好回檔區，先不用急著買。"
        entry_text = f"等價格接近 {preferred} 並出現止跌或量能回穩，再提高進場權重。"
    elif price_position == "above_preferred" and preferred:
        now_text = f"現價 {latest} 已離開 {preferred}，不要把它當低接買點。"
        entry_text = (
            f"等回測 {preferred} 守住，或有效突破 {fields['breakout']} 後再重新評估。"
            if fields.get("breakout")
            else f"等回測 {preferred} 守住後再重新評估。"
        )
        if chase:
            entry_text = entry_text.rstrip("。") + f"；若價格接近或高於 {chase}，視為追價，部位要降。"
    elif price_position in {"below_stop", "below_invalidation"}:
        now_text = f"現價 {latest} 已進風控區，低接風險高。"
        entry_text = "先等價格重新站回風控線上方，並確認量能沒有放大轉弱。"
    elif price_position == "breakout_confirmed":
        now_text = f"現價 {latest} 已接近或突破確認區，不是低接買點。"
        entry_text = "若要做，只能用突破後站穩與回測不破作條件，不能用回檔買點邏輯。"
    else:
        now_text = f"現價 {latest}；先不要只用單一分數做買進決策。"
        entry_text = "等價格、量能與主要均線或動能同向轉強後，再把進場權重提高。"

    action_plan = [
        {"label": "現在", "text": now_text},
        {"label": "進場條件", "text": entry_text},
        {"label": "風控", "text": _entry_risk_text(fields)},
    ]
    summary = _entry_decision_summary_lines(fields, numbers, price_position)
    return headline, summary, action_plan


def _technical_level_summary_lines(levels: dict[str, Any]) -> list[str]:
    fields = _technical_level_fields(levels)
    if not fields:
        return []

    lines: list[str] = []
    entry_parts = []
    if fields.get("latest"):
        entry_parts.append(f"現價 {fields['latest']}")
    if fields.get("preferred"):
        entry_parts.append(f"偏好回檔區 {fields['preferred']}")
    if fields.get("chase"):
        entry_parts.append(f"追價上限 {fields['chase']}")
    if fields.get("breakout"):
        entry_parts.append(f"突破確認 {fields['breakout']}")
    if entry_parts:
        lines.append("；".join(entry_parts) + "。")

    risk_parts = []
    if fields.get("stop"):
        risk_parts.append(f"短線停損 {fields['stop']}")
    if fields.get("invalidation"):
        risk_parts.append(f"波段/技術失效 {fields['invalidation']}")
    if risk_parts:
        lines.append("；".join(risk_parts) + "。")

    context = levels.get("context") if isinstance(levels.get("context"), dict) else {}
    if context.get("extended"):
        lines.append("目前位置偏熱，適合等回檔或突破確認，不把現價當成最佳買點。")
    return lines[:CONSUMER_SUMMARY_LIMIT]


def _result_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return data


def _latest_price_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    data = _result_data(result)
    latest_daily = data.get("latest_daily") if isinstance(data.get("latest_daily"), dict) else {}
    for key in ("close_price", "close", "last_price", "settlement_price"):
        value = _numeric_data_value(latest_daily.get(key))
        if value is not None:
            return {
                "value": value,
                "source": f"data.latest_daily.{key}",
                "as_of": latest_daily.get("trade_date"),
            }

    technical_reports = data.get("technical_reports") if isinstance(data.get("technical_reports"), dict) else {}
    for timeframe in ("today", "daily", "weekly"):
        report = technical_reports.get(timeframe) if isinstance(technical_reports.get(timeframe), dict) else {}
        value = _numeric_data_value(report.get("latest_close"))
        if value is not None:
            return {
                "value": value,
                "source": f"data.technical_reports.{timeframe}.latest_close",
                "as_of": report.get("as_of"),
            }

    for chart_key in ("chart", "daily_chart"):
        chart = data.get(chart_key) if isinstance(data.get(chart_key), dict) else {}
        points = chart.get("points") if isinstance(chart.get("points"), list) else []
        for point in reversed(points):
            if not isinstance(point, dict):
                continue
            value = _numeric_data_value(point.get("close") or point.get("close_price") or point.get("last_price"))
            if value is not None:
                return {
                    "value": value,
                    "source": f"data.{chart_key}.points[-1].close",
                    "as_of": point.get("time") or point.get("trade_date"),
                }

    return {}


def _chart_points(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = _result_data(result)
    for chart_key in ("chart", "daily_chart"):
        chart = data.get(chart_key) if isinstance(data.get(chart_key), dict) else {}
        points = chart.get("points") if isinstance(chart.get("points"), list) else []
        if points:
            return [point for point in points if isinstance(point, dict)]
    return []


def _position_support_levels(result: dict[str, Any]) -> dict[str, Any]:
    data = _result_data(result)
    levels: dict[str, Any] = {}
    technical_reports = data.get("technical_reports") if isinstance(data.get("technical_reports"), dict) else {}
    daily_report = technical_reports.get("daily") if isinstance(technical_reports.get("daily"), dict) else {}
    for key in ("ma5", "ma20", "ma60"):
        value = _numeric_data_value(daily_report.get(key))
        if value is not None:
            levels[key] = value

    lows: list[float] = []
    highs: list[float] = []
    for point in _chart_points(result)[-20:]:
        low = _numeric_data_value(point.get("low") or point.get("low_price") or point.get("close"))
        high = _numeric_data_value(point.get("high") or point.get("high_price") or point.get("close"))
        if low is not None:
            lows.append(low)
        if high is not None:
            highs.append(high)
    if lows:
        levels["recent_low_20"] = min(lows)
    if highs:
        levels["recent_high_20"] = max(highs)
    return levels


def _level_text(levels: dict[str, Any]) -> str:
    ordered = (
        ("ma20", "MA20"),
        ("recent_low_20", "20日低點"),
        ("ma60", "MA60"),
    )
    parts = [
        f"{label} {_format_price(_numeric_data_value(levels.get(key)))}"
        for key, label in ordered
        if _numeric_data_value(levels.get(key)) is not None
    ]
    return "、".join(parts) if parts else "主要均線或前低"


def _build_position_decision(
    *,
    question: str,
    position_context: dict[str, Any],
    target: dict[str, Any],
    result: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    if not position_context.get("has_position_context"):
        return {}

    entry_price = _numeric_data_value(position_context.get("entry_price"))
    latest_snapshot = _latest_price_snapshot(result)
    latest_price = _numeric_data_value(latest_snapshot.get("value"))
    pnl_pct = ((latest_price - entry_price) / entry_price) * 100 if entry_price and latest_price else None
    pnl_points = latest_price - entry_price if entry_price and latest_price else None
    score = _numeric_score(analysis_digest.get("selected_score"))
    confidence = _text_value(analysis_digest.get("selected_confidence"))
    stance = _stance_from_score(score)
    score_text = _score_display(score)
    target_label = _text_value(target.get("label")) or _text_value(target.get("id")) or "目前標的"
    topic = str(position_context.get("decision_topic") or "position")
    levels = _position_support_levels(result)
    technical_level_text = _level_text(levels)

    if pnl_pct is None:
        headline = f"{target_label} 可以討論停損，但目前缺少成本價或最新價格，不能直接判斷"
        direct_answer = "先不要把一般波段模板當作停損結論；請先補齊成本價、最新價與可承受虧損。"
    elif topic == "stop_loss":
        if pnl_pct <= -5:
            headline = (
                f"{target_label} 成本 {_format_price(entry_price)} 目前約 {_format_pct_value(pnl_pct)}，"
                "若你的停損規則是 -5% 已經觸發"
            )
            direct_answer = (
                "如果你的交易規則是固定百分比停損，現在應執行或至少減碼；"
                f"如果你採技術停損，則不要只看成本，改以 {technical_level_text} 是否失守作為條件。"
            )
        elif pnl_pct < 0:
            headline = (
                f"{target_label} 低於成本 {_format_price(entry_price)}，但尚未到常見 -5% 停損線"
            )
            direct_answer = (
                "目前比較適合設定明確失效條件，而不是因為單一浮虧就立刻全出；"
                f"若跌破 {technical_level_text} 或你的最大虧損線，才把停損升級成執行。"
            )
        else:
            headline = (
                f"{target_label} 仍高於成本 {_format_price(entry_price)}，停損題先轉成移動停利/防守條件"
            )
            direct_answer = (
                "目前不是成本停損情境，重點是把保護線上移；"
                f"若跌破 {technical_level_text}，再重新評估是否退出。"
            )
    elif topic in {"exit", "hold"}:
        headline = f"{target_label} 去留要分成部位風險與技術失效兩層判斷"
        direct_answer = (
            f"先看成本 {_format_price(entry_price)} 與最新價 {_format_price(latest_price)} 的距離，"
            f"再用 {technical_level_text} 當作技術失效線。"
        )
    else:
        headline = f"{target_label} 已辨識持倉問題，先用成本距離與技術分數分層判斷"
        direct_answer = (
            "不要直接套用一般多空模板；先確認你的成本、可承受虧損與技術失效條件。"
        )

    summary: list[str] = []
    if entry_price is not None and latest_price is not None:
        summary.append(
            f"成本 {_format_price(entry_price)} / 最新 {_format_price(latest_price)}，"
            f"價差 {_format_signed_price(pnl_points)}，浮動約 {_format_pct_value(pnl_pct)}。"
        )
    elif entry_price is not None:
        summary.append(f"已讀到成本 {_format_price(entry_price)}，但最新價不足。")
    else:
        summary.append("問題有持倉/停損意圖，但未解析到明確成本價。")

    if analysis_digest:
        technical_line = _text_value(analysis_digest.get("display"))
        if technical_line:
            summary.append(f"技術摘要：{technical_line}。")
    summary.append(f"停損判斷：{direct_answer}")

    action_plan = [
        {
            "label": "成本停損",
            "text": (
                f"若你的原始規則是 -5%，目前 {_format_pct_value(pnl_pct)} 已到需要執行或減碼的區間。"
                if pnl_pct is not None and pnl_pct <= -5
                else "先寫下可承受最大虧損百分比，達到就執行，不再用盤中情緒改規則。"
            ),
        },
        {
            "label": "技術停損",
            "text": f"若你採技術停損，觀察 {technical_level_text}；跌破且動能轉弱時，部位假設要降級。",
        },
        {
            "label": "現在",
            "text": "先不要只看波段評分；把部位大小、可承受虧損與是否跌破技術失效線一起判斷。",
        },
    ]

    data_limits = [
        "缺少你的部位大小、原始停損規則、可承受虧損與預計持有時間。",
    ]
    _append_unique_texts(data_limits, _generic_data_limits(missing=missing, warnings=warnings), limit=3)

    evidence_used = [
        "user_question.entry_price" if entry_price is not None else "user_question.position_intent",
        latest_snapshot.get("source") or "latest_price.missing",
        "result.data.analysis" if analysis_digest else "analysis.missing",
    ]

    return {
        "kind": "position_decision",
        "intent": "position_risk_decision",
        "question": question,
        "topic": topic,
        "target_label": target_label,
        "entry_price": entry_price,
        "latest_price": latest_price,
        "latest_price_source": latest_snapshot.get("source"),
        "latest_price_as_of": latest_snapshot.get("as_of"),
        "unrealized_return_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
        "unrealized_points": round(pnl_points, 4) if pnl_points is not None else None,
        "score": score,
        "score_display": score_text,
        "stance": stance,
        "confidence": confidence,
        "levels": levels,
        "headline": headline,
        "direct_answer": direct_answer,
        "summary": summary[:CONSUMER_SUMMARY_LIMIT],
        "action_plan": action_plan,
        "risks": data_limits[:2],
        "data_limits": data_limits,
        "evidence_used": evidence_used,
        "llm_status": "not_requested",
    }


def _try_attach_position_decision_llm(
    *,
    payload: AiAskRequest,
    policy: dict[str, Any],
    target: dict[str, Any],
    position_context: dict[str, Any],
    position_decision: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    if not position_decision:
        return {}

    if not policy.get("can_call_llm"):
        position_decision["llm_status"] = "skipped_policy"
        return position_decision

    decision_input = {
        "question": payload.question,
        "target": target,
        "position_context": position_context,
        "position_decision": {
            key: value
            for key, value in position_decision.items()
            if key not in {"llm", "text"}
        },
        "analysis_digest": analysis_digest,
        "missing": missing,
        "warnings": warnings,
        "rules": [
            "Answer the user's position-risk question directly.",
            "Use only the supplied evidence and calculations.",
            "Do not give a blanket buy/sell command; make conditions explicit.",
        ],
    }
    try:
        llm_result = llm.generate_decision_answer(decision_input)
    except llm.OpenAIConfigurationError:
        position_decision["llm_status"] = "skipped_not_configured"
        return position_decision
    except llm.OpenAILLMError as exc:
        position_decision["llm_status"] = "failed"
        position_decision["llm_error"] = str(exc)
        return position_decision

    position_decision["llm_status"] = "completed"
    position_decision["llm"] = llm_result
    return position_decision


def _build_position_decision_consumer_answer(
    *,
    position_decision: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    llm_payload = position_decision.get("llm") if isinstance(position_decision.get("llm"), dict) else {}
    llm_decision = llm_payload.get("decision") if isinstance(llm_payload.get("decision"), dict) else {}

    if llm_decision:
        summary = []
        _append_unique_texts(
            summary,
            _text_list(llm_decision.get("position_math"), limit=2),
            limit=CONSUMER_SUMMARY_LIMIT,
        )
        direct_answer = _text_value(llm_decision.get("direct_answer"))
        if direct_answer:
            _append_unique_texts(summary, [direct_answer], limit=CONSUMER_SUMMARY_LIMIT)
        if not summary:
            summary = _text_list(position_decision.get("summary"), limit=CONSUMER_SUMMARY_LIMIT)

        conditions = _text_list(llm_decision.get("decision_conditions"), limit=2)
        next_steps = _text_list(llm_decision.get("next_steps"), limit=2)
        action_texts = list(dict.fromkeys(conditions + next_steps))[:CONSUMER_SUMMARY_LIMIT]
        labels = ("條件", "執行", "追蹤")
        action_plan = [
            {"label": labels[index], "text": text}
            for index, text in enumerate(action_texts)
        ] or position_decision.get("action_plan", [])

        confidence = _text_value(llm_decision.get("confidence")) or _text_value(position_decision.get("confidence"))
        answer = {
            "kind": "consumer_market_answer",
            "style": "position_decision_summary",
            "source": "position_decision_llm",
            "intent": "position_risk_decision",
            "headline": _text_value(llm_decision.get("headline")) or _text_value(position_decision.get("headline")),
            "stance": position_decision.get("stance"),
            "stance_label": STANCE_LABELS.get(str(position_decision.get("stance")), "未定"),
            "confidence": confidence,
            "confidence_label": CONFIDENCE_LABELS.get(str(confidence), confidence or "未定"),
            "summary": summary[:CONSUMER_SUMMARY_LIMIT],
            "action_plan": action_plan[:CONSUMER_SUMMARY_LIMIT],
            "risks": _text_list(llm_decision.get("risk_notes"), limit=2) or position_decision.get("risks", []),
            "data_limits": (
                _text_list(llm_decision.get("missing_context"), limit=2)
                + _generic_data_limits(missing=missing, warnings=warnings)
            )[:3],
            "detail": _text_value(llm_decision.get("direct_answer")) or _text_value(position_decision.get("direct_answer")) or "",
            "position_decision": position_decision,
        }
    else:
        confidence = _text_value(position_decision.get("confidence"))
        answer = {
            "kind": "consumer_market_answer",
            "style": "position_decision_summary",
            "source": "position_decision",
            "intent": "position_risk_decision",
            "headline": _text_value(position_decision.get("headline")) or "已完成部位風險判斷",
            "stance": position_decision.get("stance"),
            "stance_label": STANCE_LABELS.get(str(position_decision.get("stance")), "未定"),
            "confidence": confidence,
            "confidence_label": CONFIDENCE_LABELS.get(str(confidence), confidence or "未定"),
            "summary": _text_list(position_decision.get("summary"), limit=CONSUMER_SUMMARY_LIMIT),
            "action_plan": position_decision.get("action_plan", [])[:CONSUMER_SUMMARY_LIMIT],
            "risks": position_decision.get("risks", []),
            "data_limits": position_decision.get("data_limits", []),
            "detail": _text_value(position_decision.get("direct_answer")) or "",
            "position_decision": position_decision,
        }

    answer["text"] = _consumer_text(answer)
    return answer


QUESTION_INTENT_STAGE_LABELS = {
    "entry_decision": "進場問題",
    "exit_decision": "出場問題",
    "risk_check": "風險檢查",
    "trend_view": "走勢解讀",
    "general": "一般問答",
}


def _build_reasoning_steps(
    *,
    question_intent: str,
    position_context: dict[str, Any],
    position_decision: dict[str, Any],
    analysis_digest: dict[str, Any],
) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    if question_intent == "position_risk_decision":
        entry_price = _numeric_data_value(position_context.get("entry_price"))
        entry_text = f"，成本價 {_format_price(entry_price)}" if entry_price is not None else ""
        steps.append(
            {
                "stage": "question_understanding",
                "message": f"已解析為持倉/停損問題{entry_text}。",
            }
        )
        latest_price = _numeric_data_value(position_decision.get("latest_price"))
        latest_text = f"最新價 {_format_price(latest_price)}" if latest_price is not None else "最新價不足"
        steps.append(
            {
                "stage": "evidence_read",
                "message": f"已讀取標的日線與技術摘要，{latest_text}。",
            }
        )
        pnl_pct = position_decision.get("unrealized_return_pct")
        pnl_number = None
        if not isinstance(pnl_pct, bool) and isinstance(pnl_pct, (int, float)):
            pnl_number = float(pnl_pct)
        pnl_text = _format_pct_value(pnl_number) if pnl_number is not None else "無法計算"
        steps.append(
            {
                "stage": "position_math",
                "message": f"已計算成本距離與浮動損益：{pnl_text}。",
            }
        )
        llm_status = position_decision.get("llm_status")
        synthesis = "已完成 LLM 決策綜合。" if llm_status == "completed" else "已完成規則化決策綜合。"
        steps.append({"stage": "decision_synthesis", "message": synthesis})
        return steps

    if analysis_digest:
        intent_label = QUESTION_INTENT_STAGE_LABELS.get(question_intent, "問題解析")
        selected_horizon = _text_value(analysis_digest.get("horizon_label")) or _text_value(
            analysis_digest.get("selected_horizon")
        )
        score_text = _score_display(_numeric_score(analysis_digest.get("selected_score")))
        confidence = _text_value(analysis_digest.get("selected_confidence"))
        digest_bits = []
        if selected_horizon:
            digest_bits.append(f"{selected_horizon}視角")
        if score_text:
            digest_bits.append(f"評分 {score_text}")
        if confidence:
            digest_bits.append(f"信心 {CONFIDENCE_LABELS.get(confidence, confidence)}")

        steps.append(
            {
                "stage": "question_understanding",
                "message": f"已判斷為{intent_label}，後續回答會依這個意圖組合。",
            }
        )
        steps.append(
            {
                "stage": "evidence_read",
                "message": "已讀取目前畫面標的的技術摘要與資料限制"
                + (f"：{'，'.join(digest_bits)}。" if digest_bits else "。"),
            }
        )
        score_model = analysis_digest.get("score_model") if isinstance(analysis_digest.get("score_model"), dict) else {}
        if score_model.get("version"):
            horizon_scores = (
                score_model.get("horizon_factor_scores")
                if isinstance(score_model.get("horizon_factor_scores"), dict)
                else {}
            )
            selected_key = _text_value(analysis_digest.get("selected_horizon"))
            factors = (
                horizon_scores.get(selected_key)
                if selected_key and isinstance(horizon_scores.get(selected_key), dict)
                else {}
            )
            factor_names = {
                "trend": "趨勢",
                "momentum": "動能",
                "volume": "量能",
                "volatility": "波動",
                "chips": "籌碼",
            }
            factor_text = "、".join(
                f"{factor_names.get(key, key)} {value:+.1f}"
                for key, value in factors.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            )
            steps.append(
                {
                    "stage": "score_model",
                    "message": (
                        f"已用五因子權重重算分數：{factor_text}。"
                        if factor_text
                        else "已用五因子權重重算技術分數。"
                    ),
                }
            )

        technical_levels = (
            analysis_digest.get("technical_levels")
            if isinstance(analysis_digest.get("technical_levels"), dict)
            else {}
        )
        level_fields = _technical_level_fields(technical_levels)
        if level_fields:
            level_parts = []
            if level_fields.get("preferred"):
                level_parts.append(f"回檔區 {level_fields['preferred']}")
            if level_fields.get("breakout"):
                level_parts.append(f"突破 {level_fields['breakout']}")
            if level_fields.get("stop"):
                level_parts.append(f"停損 {level_fields['stop']}")
            if level_fields.get("invalidation"):
                level_parts.append(f"失效 {level_fields['invalidation']}")
            steps.append(
                {
                    "stage": "price_levels",
                    "message": "已從 MA、ATR、Donchian 推導條件價位"
                    + (f"：{'，'.join(level_parts)}。" if level_parts else "。"),
                }
            )

        synthesis_message = {
            "entry_decision": "已將進場條件、追價上限與風控線組合成回答。",
            "exit_decision": "已將續抱、出場與失效條件組合成回答。",
            "risk_check": "已將主要風險與防守條件組合成回答。",
            "trend_view": "已將趨勢、分數與資料限制組合成回答。",
        }.get(question_intent, "已完成資料摘要與回答組裝。")
        steps.append({"stage": "decision_synthesis", "message": synthesis_message})
    return steps


def _digest_summary_lines(analysis_digest: dict[str, Any]) -> list[str]:
    summary: list[str] = []
    _append_unique_texts(
        summary,
        [
            text
            for text in (
                _text_value(analysis_digest.get("display")),
                _text_value(analysis_digest.get("selected_summary")),
            )
            if text
        ],
        limit=CONSUMER_SUMMARY_LIMIT,
    )
    scores = analysis_digest.get("scores") if isinstance(analysis_digest.get("scores"), dict) else {}
    if scores and len(summary) < CONSUMER_SUMMARY_LIMIT:
        score_parts = [
            f"{ANALYSIS_HORIZON_LABELS.get(str(key), str(key))} {_score_display(value) or '-'}"
            for key, value in scores.items()
            if value is not None
        ]
        if score_parts:
            summary.append("分數：" + "、".join(score_parts[:4]))
    return summary[:CONSUMER_SUMMARY_LIMIT]


def _decision_evidence_summary_lines(decision_evidence: dict[str, Any]) -> list[str]:
    if not isinstance(decision_evidence, dict):
        return []

    lines: list[str] = []
    market_session = (
        decision_evidence.get("market_session")
        if isinstance(decision_evidence.get("market_session"), dict)
        else {}
    )
    if market_session.get("is_trading_day") is False:
        text = _text_value(market_session.get("summary"))
        if text:
            lines.append(text)

    volatility = (
        decision_evidence.get("recent_volatility")
        if isinstance(decision_evidence.get("recent_volatility"), dict)
        else {}
    )
    if volatility.get("label") in {"high", "elevated"}:
        text = _text_value(volatility.get("summary"))
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
    revenue_summary = _text_value(revenue.get("summary"))
    if revenue_summary:
        lines.append(revenue_summary)

    indicator_quality = (
        decision_evidence.get("indicator_quality")
        if isinstance(decision_evidence.get("indicator_quality"), dict)
        else {}
    )
    warnings = _text_list(indicator_quality.get("warnings"), limit=1)
    lines.extend(warnings)
    return lines[:2]


def _decision_evidence_risk_lines(decision_evidence: dict[str, Any]) -> list[str]:
    if not isinstance(decision_evidence, dict):
        return []
    factors = (
        decision_evidence.get("confidence_factors")
        if isinstance(decision_evidence.get("confidence_factors"), dict)
        else {}
    )
    negatives = _text_list(factors.get("negative"), limit=3)
    return negatives[:2]


def _decision_evidence_data_lines(decision_evidence: dict[str, Any]) -> list[str]:
    if not isinstance(decision_evidence, dict):
        return []
    lines: list[str] = []
    market_session = (
        decision_evidence.get("market_session")
        if isinstance(decision_evidence.get("market_session"), dict)
        else {}
    )
    if market_session.get("is_trading_day") is False:
        session_date = _text_value(market_session.get("date")) or "今日"
        latest_daily_date = _text_value(market_session.get("latest_daily_date"))
        next_trading_day = _text_value(market_session.get("next_trading_day"))
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
    price_source = _text_value(price.get("source"))
    price_as_of = _text_value(price.get("as_of"))
    volume_source = _text_value(volume.get("source"))
    volume_display = _text_value(volume.get("display_value"))
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
    lines.extend(_text_list(factors.get("data_limits"), limit=2))
    return list(dict.fromkeys(lines))[:3]


def _build_question_aware_consumer_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
) -> dict[str, Any]:
    if question_intent == "general" or not analysis_digest:
        return {}

    score = _numeric_score(analysis_digest.get("selected_score"))
    score_text = _score_display(score)
    confidence = _text_value(analysis_digest.get("selected_confidence"))
    confidence_label = CONFIDENCE_LABELS.get(str(confidence), confidence or "未定")
    stance = _stance_from_score(score)
    summary = _digest_summary_lines(analysis_digest)
    target_label = _text_value(target.get("label")) or _text_value(target.get("id")) or "目前標的"
    data_limits = _generic_data_limits(missing=missing, warnings=warnings)
    decision_evidence = (
        analysis_digest.get("decision_evidence")
        if isinstance(analysis_digest.get("decision_evidence"), dict)
        else {}
    )
    evidence_summary = _decision_evidence_summary_lines(decision_evidence)
    evidence_risks = _decision_evidence_risk_lines(decision_evidence)
    data_limits = list(
        dict.fromkeys(data_limits + _decision_evidence_data_lines(decision_evidence))
    )
    weak_evidence = score is None or confidence == "low"
    technical_levels = (
        analysis_digest.get("technical_levels")
        if isinstance(analysis_digest.get("technical_levels"), dict)
        else {}
    )
    level_fields = _technical_level_fields(technical_levels)
    level_numbers = _technical_level_numbers(technical_levels)
    level_summary = (
        []
        if question_intent == "entry_decision" and level_fields
        else _technical_level_summary_lines(technical_levels)
    )
    if level_summary:
        summary = list(dict.fromkeys(level_summary + summary))[:CONSUMER_SUMMARY_LIMIT]

    if question_intent == "entry_decision":
        if level_fields:
            headline, entry_summary, action_plan = _entry_decision_with_levels(
                target_label=target_label,
                score=score,
                weak_evidence=weak_evidence,
                fields=level_fields,
                numbers=level_numbers,
            )
            if entry_summary:
                summary = list(
                    dict.fromkeys(entry_summary[:1] + evidence_summary + entry_summary[1:] + summary)
                )[:CONSUMER_SUMMARY_LIMIT]
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
            summary = list(dict.fromkeys(evidence_summary + summary))[:CONSUMER_SUMMARY_LIMIT]
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
            summary = list(dict.fromkeys(evidence_summary + summary))[:CONSUMER_SUMMARY_LIMIT]
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
            summary = list(dict.fromkeys(evidence_summary + summary))[:CONSUMER_SUMMARY_LIMIT]
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
        "detail": _text_value(analysis_digest.get("display")) or "",
        "decision_evidence": decision_evidence,
    }
    answer["text"] = _consumer_text(answer)
    return answer


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

    backend_data_limits = _generic_data_limits(missing=missing, warnings=warnings)
    has_backend_missing = bool(_text_list(missing))
    raw_observations = _text_list(report.get("key_observations"))
    raw_interpretations = _text_list(report.get("interpretation"))
    raw_next_checks = _text_list(report.get("next_checks"))
    raw_risks = _text_list(report.get("risks"))
    raw_missing_data = _text_list(report.get("missing_data"))

    observations = _filter_soft_data_gap_texts(raw_observations, has_backend_missing=has_backend_missing)
    interpretations = _filter_soft_data_gap_texts(raw_interpretations, has_backend_missing=has_backend_missing)
    next_checks = _filter_soft_data_gap_texts(raw_next_checks, has_backend_missing=has_backend_missing)
    risks = _filter_soft_data_gap_texts(raw_risks, has_backend_missing=has_backend_missing)
    missing_data = raw_missing_data if has_backend_missing else []

    summary: list[str] = []
    _append_unique_texts(summary, observations[:2], limit=CONSUMER_SUMMARY_LIMIT)
    _append_unique_texts(summary, interpretations[:2], limit=CONSUMER_SUMMARY_LIMIT)
    if not summary and analysis_digest.get("display"):
        summary.append(str(analysis_digest["display"]))

    follow_up_checks = list(
        dict.fromkeys(next_checks + ([] if has_backend_missing else _filter_soft_data_gap_texts(raw_missing_data, has_backend_missing=False)))
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
        "detail": _consumer_detail_from_llm_report(
            detail_report,
            missing_data_label="資料限制" if data_limits else "後續確認",
        ),
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
    question_intent: str,
    target: dict[str, Any],
    result: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    position_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if position_decision:
        return _build_position_decision_consumer_answer(
            position_decision=position_decision,
            missing=missing,
            warnings=warnings,
        )

    question_answer = _build_question_aware_consumer_answer(
        question_intent=question_intent,
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
    )
    if question_intent in {"entry_decision", "exit_decision"} and question_answer:
        return question_answer

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

    if question_answer:
        return question_answer

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
            "score_model": analysis.get("score_model") or {},
            "technical_levels": data.get("technical_levels") or {},
            "decision_evidence": data.get("decision_evidence") or {},
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
    position_context = _infer_position_context(payload.question)
    question_intent = _infer_question_intent(payload.question)
    policy["question_intent"] = question_intent
    if position_context.get("has_position_context"):
        policy["position_context"] = position_context
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
        effective_mode = (
            "brief"
            if scope_type in {"stock", "watchlist", "us_stock", "tw_index", "tw_futures"}
            else "data_only"
        )

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
    position_decision = {}
    if question_intent == "position_risk_decision" and scope_type == "stock":
        position_decision = _build_position_decision(
            question=payload.question,
            position_context=position_context,
            target=response_target,
            result=result,
            analysis_digest=analysis_digest,
            missing=combined_missing,
            warnings=combined_warnings,
        )
        position_decision = _try_attach_position_decision_llm(
            payload=payload,
            policy=policy,
            target=response_target,
            position_context=position_context,
            position_decision=position_decision,
            analysis_digest=analysis_digest,
            missing=combined_missing,
            warnings=combined_warnings,
        )

    consumer_human_answer = _build_consumer_human_answer(
        question_intent=question_intent,
        target=response_target,
        result=result,
        analysis_digest=analysis_digest,
        missing=combined_missing,
        warnings=combined_warnings,
        position_decision=position_decision,
    )
    reasoning_steps = _build_reasoning_steps(
        question_intent=question_intent,
        position_context=position_context,
        position_decision=position_decision,
        analysis_digest=analysis_digest,
    )
    response_analysis = dict(analysis_digest)
    response_analysis["question_intent"] = question_intent
    if position_context.get("has_position_context"):
        response_analysis["position_context"] = position_context
    if position_decision:
        response_analysis["position_decision"] = position_decision
    if reasoning_steps:
        response_analysis["reasoning_steps"] = reasoning_steps
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
        "reasoning_steps": reasoning_steps,
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
