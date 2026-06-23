from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy.orm import Session

from app.ai import decision_core
from app.ai.schemas import AiAskRequest
from app.db.models import JPStockMaster, StockMaster, USStockMaster, WatchlistGroup
from app.jp_market.sources import normalize_jp_symbol
from app.us_market.sources import normalize_us_symbol


VALID_TARGET_TYPES = {
    "auto",
    "market",
    "data_freshness",
    "tw_stock",
    "tw_watchlist",
    "tw_index",
    "tw_futures",
    "us_stock",
    "jp_stock",
    "jp_index",
}
TAIWAN_INDEX_TARGET_IDS = {"TAIEX", "TPEX"}
TAIWAN_FUTURES_TARGET_IDS = {"TXF", "MXF", "TMF"}
JP_INDEX_TARGET_IDS = {"^N225", "1306.T"}
JP_MARKET_CONTEXT_HINTS = (
    "\u65e5\u80a1",
    "\u65e5\u672c",
    "\u65e5\u7d93",
    "\u65e5\u7d4c",
    "japan",
    "jp",
    "jpy",
    "nikkei",
    "n225",
    "topix",
)
INTERNAL_SCOPE_TO_TARGET_TYPE = {
    "market": "market",
    "data_freshness": "data_freshness",
    "stock": "tw_stock",
    "watchlist": "tw_watchlist",
    "tw_index": "tw_index",
    "tw_futures": "tw_futures",
    "us_stock": "us_stock",
    "jp_stock": "jp_stock",
    "jp_index": "jp_index",
}
TARGET_TYPE_TO_INTERNAL_SCOPE = {
    "market": "market",
    "data_freshness": "data_freshness",
    "tw_stock": "stock",
    "tw_watchlist": "watchlist",
    "tw_index": "tw_index",
    "tw_futures": "tw_futures",
    "us_stock": "us_stock",
    "jp_stock": "jp_stock",
    "jp_index": "jp_index",
}
REPORT_HINTS = decision_core.REPORT_HINTS
ANALYSIS_HINTS = decision_core.ANALYSIS_HINTS
FRESHNESS_HINTS = decision_core.FRESHNESS_HINTS
INTRADAY_HINTS = decision_core.INTRADAY_HINTS
SHORT_HORIZON_HINTS = decision_core.SHORT_HORIZON_HINTS
SWING_HORIZON_HINTS = decision_core.SWING_HORIZON_HINTS
LONG_HORIZON_HINTS = decision_core.LONG_HORIZON_HINTS
WATCHLIST_HINTS = decision_core.WATCHLIST_HINTS
MARKET_HINTS = decision_core.MARKET_HINTS
ADR_HINTS = decision_core.ADR_HINTS
US_SYMBOL_CONTEXT_HINTS = decision_core.US_SYMBOL_CONTEXT_HINTS
STOCK_REFERENCE_HINTS = decision_core.STOCK_REFERENCE_HINTS
TAIWAN_TSMC_ALIASES = decision_core.TAIWAN_TSMC_ALIASES
US_SYMBOL_STOPWORDS = decision_core.US_SYMBOL_STOPWORDS
US_EXCHANGE_SYMBOL_PATTERN = decision_core.US_EXCHANGE_SYMBOL_PATTERN
US_DOLLAR_SYMBOL_PATTERN = decision_core.US_DOLLAR_SYMBOL_PATTERN
US_PLAIN_SYMBOL_PATTERN = decision_core.US_PLAIN_SYMBOL_PATTERN


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


def _contains_hint(question: str, hints: tuple[str, ...]) -> bool:
    return decision_core.contains_hint(question, hints)


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
        elif target_type.startswith("jp_"):
            market = "JP"

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


def _looks_like_jp_symbol(value: str | None) -> bool:
    normalized = normalize_jp_symbol(value)
    if not normalized:
        return False

    return bool(re.fullmatch(r"(?:\^[A-Z0-9]+|[0-9]{3}[0-9A-Z](?:\.[A-Z]{1,4})?|[0-9]{5}(?:\.[A-Z]{1,4})?)", normalized))


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


def _jp_stock_display_name(db: Session | None, symbol: str | None, fallback: str | None = None) -> str | None:
    if db is None or not symbol:
        return fallback

    normalized_symbol = normalize_jp_symbol(symbol)
    if not normalized_symbol:
        return fallback

    stock = db.query(JPStockMaster).filter(JPStockMaster.symbol == normalized_symbol).first()
    if stock is None:
        return fallback

    return stock.security_name or fallback


def _get_jp_stock(db: Session | None, symbol: str | None) -> JPStockMaster | None:
    if db is None or not symbol:
        return None

    normalized_symbol = normalize_jp_symbol(symbol)
    if not normalized_symbol:
        return None

    return (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == normalized_symbol)
        .filter(JPStockMaster.is_active.is_(True))
        .first()
    )


def _jp_stock_label(stock: JPStockMaster | None, symbol: str) -> str:
    return stock.security_name if stock and stock.security_name else symbol


def _resolve_jp_stock_symbol(
    db: Session | None,
    symbol: str | None,
    *,
    source: str,
    confidence: str = "high",
    allow_unknown: bool = False,
) -> ScopeResolution | None:
    normalized_symbol = normalize_jp_symbol(symbol)
    if not _looks_like_jp_symbol(normalized_symbol):
        return None

    stock = _get_jp_stock(db, normalized_symbol)
    if stock is None and not allow_unknown:
        return None

    label = _jp_stock_label(stock, normalized_symbol)
    return ScopeResolution(
        selected_scope_type="jp_stock",
        selected_scope_id=normalized_symbol,
        display_name=label,
        confidence=confidence if stock is not None else "medium",
        assumption=None
        if stock is not None
        else "JP stock master is incomplete; using the normalized symbol and exposing data gaps.",
        source=source if stock is not None else f"{source}_unverified_symbol",
        candidates=(
            _resolution_candidate(
                scope_type="jp_stock",
                scope_id=normalized_symbol,
                label=label,
                confidence=confidence if stock is not None else "medium",
                source=source if stock is not None else f"{source}_unverified_symbol",
            ),
        ),
    )


def _question_has_jp_context(question: str) -> bool:
    return _contains_hint(question, JP_MARKET_CONTEXT_HINTS)


def _resolve_jp_index_from_question(question: str) -> ScopeResolution | None:
    lowered = question.lower()
    if "nikkei" in lowered or "n225" in lowered or "\u65e5\u7d93" in question or "\u65e5\u7d4c" in question:
        return ScopeResolution(
            selected_scope_type="jp_index",
            selected_scope_id="^N225",
            display_name="Nikkei 225",
            confidence="high",
            source="question_jp_index",
            candidates=(
                _resolution_candidate(
                    scope_type="jp_index",
                    scope_id="^N225",
                    label="Nikkei 225",
                    confidence="high",
                    source="question_jp_index",
                ),
            ),
        )

    if "topix" in lowered:
        return ScopeResolution(
            selected_scope_type="jp_index",
            selected_scope_id="1306.T",
            display_name="TOPIX ETF",
            confidence="medium",
            assumption="TOPIX is represented by the local 1306.T ETF proxy in OMI.",
            source="question_jp_index_proxy",
            candidates=(
                _resolution_candidate(
                    scope_type="jp_index",
                    scope_id="1306.T",
                    label="TOPIX ETF",
                    confidence="medium",
                    source="question_jp_index_proxy",
                ),
            ),
        )

    return None


def _resolve_jp_stock_symbol_from_question(db: Session | None, question: str) -> ScopeResolution | None:
    if not _question_has_jp_context(question):
        return None

    index_resolution = _resolve_jp_index_from_question(question)
    if index_resolution is not None:
        return index_resolution

    for match in re.finditer(r"(?<![0-9A-Z])([0-9]{3}[0-9A-Z](?:\.T)?|[0-9]{5}(?:\.T)?)(?![0-9A-Z])", question.upper()):
        raw_symbol = match.group(1)
        if (
            not raw_symbol.endswith(".T")
            and raw_symbol.isdigit()
            and 1900 <= int(raw_symbol) <= 2099
        ):
            continue
        resolution = _resolve_jp_stock_symbol(
            db,
            raw_symbol,
            source="question_jp_symbol",
            confidence="high",
            allow_unknown=True,
        )
        if resolution is not None:
            return resolution

    return None


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

        if scope_type in {"stock", "watchlist", "us_stock", "jp_stock", "jp_index", "tw_index", "tw_futures"} and target_id is None:
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

        if scope_type == "jp_stock":
            normalized_jp_symbol = normalize_jp_symbol(target_id)
            if not _looks_like_jp_symbol(normalized_jp_symbol):
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported Japan stock target.id: {target_id}.",
                )
            target_id = normalized_jp_symbol

        if scope_type == "jp_index":
            normalized_jp_index = normalize_jp_symbol(target_id)
            if normalized_jp_index not in JP_INDEX_TARGET_IDS:
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported Japan index target.id: {target_id}.",
                )
            target_id = normalized_jp_index

        display_name = (
            _stock_display_name(db, target_id)
            if scope_type == "stock" and target_id
            else _us_stock_display_name(db, target_id, fallback=target_id)
            if scope_type == "us_stock" and target_id
            else _jp_stock_display_name(db, target_id, fallback=requested_label or target_id)
            if scope_type == "jp_stock" and target_id
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

        if _question_has_jp_context(question):
            if normalized_target_id in JP_INDEX_TARGET_IDS:
                label = requested_label or normalized_target_id
                return ScopeResolution(
                    selected_scope_type="jp_index",
                    selected_scope_id=normalized_target_id,
                    display_name=label,
                    confidence="high",
                    source="explicit_scope_id",
                    candidates=(
                        _resolution_candidate(
                            scope_type="jp_index",
                            scope_id=normalized_target_id,
                            label=label,
                            confidence="high",
                            source="explicit_scope_id",
                        ),
                    ),
                )

            jp_symbol_resolution = _resolve_jp_stock_symbol(
                db,
                target_id,
                source="explicit_scope_id",
                confidence="high",
                allow_unknown=True,
            )
            if jp_symbol_resolution is not None:
                return jp_symbol_resolution

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

    jp_symbol_resolution = _resolve_jp_stock_symbol_from_question(db, question)
    if jp_symbol_resolution is not None:
        return jp_symbol_resolution

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
