from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy.orm import Session

from app.ai import decision_core
from app.ai.schemas import AiAskRequest
from app.crypto_market.assets import crypto_asset_codes, get_crypto_asset
from app.db.models import JPStockMaster, KRStockMaster, StockMaster, USStockMaster, WatchlistGroup
from app.jp_market.sources import normalize_jp_symbol
from app.kr_market.sources import KR_INDEX_CONFIG_BY_ID, normalize_kr_index_id, normalize_kr_symbol
from app.resource_market.contract import list_resource_instruments, normalize_resource_symbol
from app.us_market.sources import normalize_us_symbol
from app.us_market.symbols import us_instrument_type


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
    "kr_stock",
    "kr_index",
    "crypto_market",
    "crypto_asset",
    "resource_asset",
    "portfolio",
    "us_macro",
    "us_watchlist",
    "jp_watchlist",
    "kr_watchlist",
    "source_health",
    "capability_status",
}
TAIWAN_INDEX_TARGET_IDS = {"TAIEX", "TPEX"}
TAIWAN_FUTURES_TARGET_IDS = {"TXF", "MXF", "TMF"}
JP_INDEX_TARGET_IDS = {"^N225", "1306.T"}
JP_INDEX_TARGET_ALIASES = {
    "N225": "^N225",
    "^N225": "^N225",
    "NIKKEI225": "^N225",
    "日經225": "^N225",
    "日経225": "^N225",
    "1306.T": "1306.T",
}
KR_INDEX_TARGET_IDS = set(KR_INDEX_CONFIG_BY_ID)
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
KR_MARKET_CONTEXT_HINTS = (
    "韓股",
    "韓國",
    "南韓",
    "korea",
    "korean",
    "kr",
    "krx",
    "kospi",
    "kosdaq",
    "kospi200",
    "^ks11",
    "^kq11",
    "^ks200",
)
DATA_FRESHNESS_MARKET_ALIASES: dict[str, tuple[str, ...]] = {
    "TW": ("tw", "taiwan", "台股", "台灣"),
    "US": ("us", "usa", "美股", "美國"),
    "JP": ("jp", "japan", "日股", "日本"),
    "KR": ("kr", "korea", "韓股", "韓國", "南韓"),
    "CRYPTO": ("crypto", "cryptocurrency", "加密", "幣圈", "虛擬貨幣"),
    "ALL": ("all", "global", "全部市場", "所有市場", "跨市場"),
}
SUPPORTED_DATA_FRESHNESS_MARKETS = set(DATA_FRESHNESS_MARKET_ALIASES)
CRYPTO_MARKET_CONTEXT_HINTS = (
    "crypto",
    "cryptocurrency",
    "bitcoin",
    "ethereum",
    "btc",
    "eth",
    "sol",
    "bnb",
    "xrp",
    "doge",
    "ton",
    "link",
    "幣圈",
    "加密",
    "虛擬貨幣",
    "比特幣",
    "以太坊",
)
PORTFOLIO_CONTEXT_HINTS = (
    "portfolio",
    "投資組合",
    "持倉總覽",
    "庫存總覽",
    "全部持倉",
)
SOURCE_HEALTH_CONTEXT_HINTS = (
    "source health",
    "provider health",
    "資料源健康",
    "資料來源健康",
    "資料源狀態",
    "provider 狀態",
)
CAPABILITY_STATUS_CONTEXT_HINTS = (
    "capability status",
    "provider contract",
    "能力清單",
    "資料能力",
    "哪些資料還沒接",
    "還沒接的資料",
    "provider 缺口",
)
RESOURCE_QUESTION_ALIASES = (
    (("usd/twd", "usd-twd", "美元台幣", "美元兌台幣"), "USD-TWD"),
    (("twd/usd", "twd-usd", "台幣美元", "台幣兌美元"), "TWD-USD"),
    (("usd/jpy", "usd-jpy", "美元日圓", "美元兌日圓"), "USD-JPY"),
    (("usd/krw", "usd-krw", "美元韓元", "美元兌韓元"), "USD-KRW"),
    (("gold", "黃金", "金價"), "GC"),
    (("wti", "原油", "油價"), "CL"),
    (("copper", "銅價"), "HG"),
)
US_MACRO_QUESTION_ALIASES = (
    (("dgs10", "10-year treasury", "10 year treasury", "美國十年債", "美國10年債"), "DGS10"),
    (("fedfunds", "federal funds rate", "聯邦基金利率"), "FEDFUNDS"),
    (("cpi", "美國消費者物價", "美國消費者價格"), "CPIAUCSL"),
    (("unrate", "u.s. unemployment", "us unemployment", "美國失業率"), "UNRATE"),
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
    "kr_stock": "kr_stock",
    "kr_index": "kr_index",
    "crypto_market": "crypto_market",
    "crypto_asset": "crypto_asset",
    "resource_asset": "resource_asset",
    "portfolio": "portfolio",
    "us_macro": "us_macro",
    "us_watchlist": "us_watchlist",
    "jp_watchlist": "jp_watchlist",
    "kr_watchlist": "kr_watchlist",
    "source_health": "source_health",
    "capability_status": "capability_status",
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
    "kr_stock": "kr_stock",
    "kr_index": "kr_index",
    "crypto_market": "crypto_market",
    "crypto_asset": "crypto_asset",
    "resource_asset": "resource_asset",
    "portfolio": "portfolio",
    "us_macro": "us_macro",
    "us_watchlist": "us_watchlist",
    "jp_watchlist": "jp_watchlist",
    "kr_watchlist": "kr_watchlist",
    "source_health": "source_health",
    "capability_status": "capability_status",
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
    selected_market: str | None = None
    display_name: str | None = None
    confidence: str = "low"
    assumption: str | None = None
    source: str = "default"
    candidates: tuple[dict[str, Any], ...] = ()
    clarification_required: bool = False
    clarification_question: str | None = None
    clarification_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def _contains_hint(question: str, hints: tuple[str, ...]) -> bool:
    return decision_core.contains_hint(question, hints)


def _alias_target(question: str, aliases: tuple[tuple[tuple[str, ...], str], ...]) -> str | None:
    lowered = question.casefold()
    for hints, target in aliases:
        if any(hint.casefold() in lowered for hint in hints):
            return target
    return None


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def normalize_jp_index_id(value: Any) -> str:
    normalized = str(value or "").strip().upper().replace(" ", "")
    return JP_INDEX_TARGET_ALIASES.get(normalized, normalize_jp_symbol(value))


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
        elif target_type.startswith("kr_"):
            market = "KR"
        elif target_type.startswith("crypto_"):
            market = "crypto"
        elif target_type == "resource_asset":
            market = "resource"
        elif target_type == "portfolio":
            market = "multi"
        elif target_type == "source_health":
            market = "all"
        elif target_type == "capability_status":
            market = "all"

    return {
        "type": target_type,
        "id": scope_id,
        "label": label,
        "market": market,
    }


def _resolution_target(resolution: ScopeResolution) -> dict[str, Any]:
    target = _target_dict(
        scope_type=resolution.selected_scope_type,
        scope_id=resolution.selected_scope_id,
        label=resolution.display_name,
        market=resolution.selected_market,
    )
    if resolution.selected_scope_type == "us_stock":
        target["instrument_type"] = us_instrument_type(resolution.selected_scope_id)
    return target


def _looks_like_stock_id(value: str | None) -> bool:
    if not value:
        return False

    return bool(re.fullmatch(r"\d{4,6}[A-Za-z0-9]?", value.strip()))


def _normalize_data_freshness_market(value: Any) -> str | None:
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return None
    for market, aliases in DATA_FRESHNESS_MARKET_ALIASES.items():
        normalized_aliases = {alias.casefold() for alias in aliases}
        if normalized == market.casefold() or normalized in normalized_aliases:
            return market
    return None


def _market_alias_in_text(text: str, alias: str) -> bool:
    normalized_alias = alias.casefold()
    if normalized_alias.isascii() and normalized_alias.isalpha() and len(normalized_alias) <= 3:
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])",
                text,
            )
        )
    return normalized_alias in text


def _data_freshness_market_from_question(question: str) -> str | None:
    lowered = question.casefold()
    if any(
        _market_alias_in_text(lowered, alias)
        for alias in DATA_FRESHNESS_MARKET_ALIASES["ALL"]
    ):
        return "ALL"
    markets = {
        market
        for market, aliases in DATA_FRESHNESS_MARKET_ALIASES.items()
        if market != "ALL"
        if any(_market_alias_in_text(lowered, alias) for alias in aliases)
    }
    if len(markets) > 1:
        return "ALL"
    return next(iter(markets), None)


def _looks_like_us_symbol(value: str | None) -> bool:
    normalized = normalize_us_symbol(value)
    if not normalized:
        return False

    return bool(re.fullmatch(r"(?:\^[A-Z0-9]+|[A-Z][A-Z0-9.$-]{0,15})", normalized))


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
        "error": (
            {
                "code": resolution.error_code,
                "message": resolution.error_message,
                "retryable": False,
            }
            if resolution.error_code
            else {}
        ),
    }


def _clarification_dict(resolution: ScopeResolution) -> dict[str, Any]:
    return {
        "required": resolution.clarification_required,
        "question": resolution.clarification_question,
        "reason": resolution.clarification_reason,
    }


def _next_conversation_context(resolution: ScopeResolution) -> dict[str, Any]:
    if resolution.clarification_required or resolution.error_code:
        return {}
    return {
        "last_target": _resolution_target(resolution),
        "last_resolution": _scope_resolution_dict(resolution),
    }


def _position_entry_price_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for pattern in decision_core.POSITION_ENTRY_PRICE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                spans.append(match.span(1))
            except IndexError:
                continue
    return tuple(spans)


def _stock_ids_in_text(text: str) -> tuple[str, ...]:
    position_price_spans = _position_entry_price_spans(text)
    stock_ids: list[str] = []
    for match in re.finditer(r"(?<!\d)(\d{4,6}[A-Za-z0-9]?)(?!\d)", text):
        value = match.group(1).strip()
        value_span = match.span(1)
        if any(value_span[0] < end and start < value_span[1] for start, end in position_price_spans):
            continue
        if _looks_like_stock_id(value) and value not in stock_ids:
            stock_ids.append(value)

    return tuple(stock_ids)


def _first_stock_id_in_text(text: str) -> str | None:
    stock_ids = _stock_ids_in_text(text)
    if stock_ids:
        return stock_ids[0]

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


def _get_tw_stock(db: Session | None, stock_id: str | None) -> StockMaster | None:
    if db is None or not stock_id:
        return None

    return (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == stock_id)
        .filter(StockMaster.is_active.is_(True))
        .first()
    )


def _target_not_found_scope(
    *,
    stock_id: str,
    source: str,
) -> ScopeResolution:
    return ScopeResolution(
        selected_scope_type="stock",
        selected_scope_id=stock_id,
        display_name=None,
        confidence="high",
        source=source,
        candidates=(),
        error_code="TARGET_NOT_FOUND",
        error_message=f"找不到台股代號 {stock_id}",
    )


def _resolve_tw_stock_id(
    db: Session | None,
    stock_id: str | None,
    *,
    source: str,
    confidence: str = "high",
    fallback_label: str | None = None,
) -> ScopeResolution | None:
    normalized_stock_id = str(stock_id or "").strip()
    if not _looks_like_stock_id(normalized_stock_id):
        return None

    stock = _get_tw_stock(db, normalized_stock_id)
    if db is not None and stock is None:
        return _target_not_found_scope(stock_id=normalized_stock_id, source=source)

    display_name = (stock.stock_name if stock is not None else None) or fallback_label
    return ScopeResolution(
        selected_scope_type="stock",
        selected_scope_id=normalized_stock_id,
        display_name=display_name,
        confidence=confidence,
        source=source,
        candidates=(
            _resolution_candidate(
                scope_type="stock",
                scope_id=normalized_stock_id,
                label=display_name,
                confidence=confidence,
                source=source,
            ),
        ),
    )


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


def _kr_stock_display_name(db: Session | None, symbol: str | None, fallback: str | None = None) -> str | None:
    if db is None or not symbol:
        return fallback

    normalized_symbol = normalize_kr_symbol(symbol)
    if not normalized_symbol:
        return fallback

    stock = db.query(KRStockMaster).filter(KRStockMaster.symbol == normalized_symbol).first()
    if stock is None:
        return fallback

    return stock.security_name or stock.security_name_kr or fallback


def _get_kr_stock(db: Session | None, symbol: str | None) -> KRStockMaster | None:
    if db is None or not symbol:
        return None

    normalized_symbol = normalize_kr_symbol(symbol)
    if not normalized_symbol:
        return None

    return (
        db.query(KRStockMaster)
        .filter(KRStockMaster.symbol == normalized_symbol)
        .filter(KRStockMaster.is_active.is_(True))
        .first()
    )


def _kr_stock_label(stock: KRStockMaster | None, symbol: str) -> str:
    if stock and stock.security_name:
        return stock.security_name
    if stock and stock.security_name_kr:
        return stock.security_name_kr
    return symbol


def _looks_like_kr_symbol(symbol: str | None) -> bool:
    normalized_symbol = normalize_kr_symbol(symbol)
    return bool(re.fullmatch(r"\d{6}\.(KS|KQ)", normalized_symbol))


def _kr_index_label(index_id: str) -> str:
    index_config = KR_INDEX_CONFIG_BY_ID.get(index_id)
    if index_config is None:
        return index_id
    return index_config.short_name or index_config.name or index_id


def _resolve_kr_index(index_id: str | None, *, source: str, confidence: str = "high") -> ScopeResolution | None:
    normalized_index_id = normalize_kr_index_id(index_id)
    if normalized_index_id not in KR_INDEX_TARGET_IDS:
        return None
    label = _kr_index_label(normalized_index_id)
    return ScopeResolution(
        selected_scope_type="kr_index",
        selected_scope_id=normalized_index_id,
        display_name=label,
        confidence=confidence,
        source=source,
        candidates=(
            _resolution_candidate(
                scope_type="kr_index",
                scope_id=normalized_index_id,
                label=label,
                confidence=confidence,
                source=source,
            ),
        ),
    )


def _resolve_kr_stock_symbol(
    db: Session | None,
    symbol: str | None,
    *,
    source: str,
    confidence: str = "high",
    allow_unknown: bool = False,
) -> ScopeResolution | None:
    normalized_symbol = normalize_kr_symbol(symbol)
    if not _looks_like_kr_symbol(normalized_symbol):
        return None

    stock = _get_kr_stock(db, normalized_symbol)
    if stock is None and not allow_unknown:
        return None

    label = _kr_stock_label(stock, normalized_symbol)
    return ScopeResolution(
        selected_scope_type="kr_stock",
        selected_scope_id=normalized_symbol,
        display_name=label,
        confidence=confidence if stock is not None else "medium",
        assumption=None
        if stock is not None
        else "KR stock master is incomplete; using the normalized symbol and exposing data gaps.",
        source=source if stock is not None else f"{source}_unverified_symbol",
        candidates=(
            _resolution_candidate(
                scope_type="kr_stock",
                scope_id=normalized_symbol,
                label=label,
                confidence=confidence if stock is not None else "medium",
                source=source if stock is not None else f"{source}_unverified_symbol",
            ),
        ),
    )


def _question_has_kr_context(question: str) -> bool:
    return _contains_hint(question, KR_MARKET_CONTEXT_HINTS)


def _resolve_kr_index_from_question(question: str) -> ScopeResolution | None:
    normalized_question = question.upper().replace("-", "").replace("_", "")
    for alias in ("KOSPI200", "KPI200", "^KS200"):
        if alias in normalized_question:
            return _resolve_kr_index("KOSPI200", source="question_kr_index", confidence="high")
    if "KOSDAQ" in normalized_question or "^KQ11" in normalized_question:
        return _resolve_kr_index("KOSDAQ", source="question_kr_index", confidence="high")
    if "KOSPI" in normalized_question or "^KS11" in normalized_question:
        return _resolve_kr_index("KOSPI", source="question_kr_index", confidence="high")
    return None


def _resolve_kr_stock_symbol_from_question(db: Session | None, question: str) -> ScopeResolution | None:
    if not _question_has_kr_context(question):
        return None

    index_resolution = _resolve_kr_index_from_question(question)
    if index_resolution is not None:
        return index_resolution

    for match in re.finditer(r"(?<!\d)(\d{4,6}(?:\.(?:KS|KQ))?)(?!\d)", question.upper()):
        resolution = _resolve_kr_stock_symbol(
            db,
            match.group(1),
            source="question_kr_symbol",
            confidence="high",
            allow_unknown=True,
        )
        if resolution is not None:
            return resolution

    return None


def _crypto_asset_label(asset_code: str) -> str:
    asset = get_crypto_asset(asset_code)
    if asset is None:
        return asset_code
    return asset.name or asset.asset


def _resolve_crypto_asset(asset_code: str | None, *, source: str, confidence: str = "high") -> ScopeResolution | None:
    normalized_asset = str(asset_code or "").strip().upper()
    asset = get_crypto_asset(normalized_asset)
    if asset is None:
        return None
    label = asset.name or asset.asset
    return ScopeResolution(
        selected_scope_type="crypto_asset",
        selected_scope_id=asset.asset,
        display_name=label,
        confidence=confidence,
        source=source,
        candidates=(
            _resolution_candidate(
                scope_type="crypto_asset",
                scope_id=asset.asset,
                label=label,
                confidence=confidence,
                source=source,
            ),
        ),
    )


def _question_has_crypto_context(question: str) -> bool:
    return _contains_hint(question, CRYPTO_MARKET_CONTEXT_HINTS)


def _resolve_crypto_asset_from_question(question: str) -> ScopeResolution | None:
    normalized_question = question.upper()
    for asset_code in crypto_asset_codes():
        if re.search(rf"(?<![A-Z0-9]){re.escape(asset_code)}(?![A-Z0-9])", normalized_question):
            return _resolve_crypto_asset(asset_code, source="question_crypto_asset", confidence="high")

    aliases = {
        "BITCOIN": "BTC",
        "比特幣": "BTC",
        "ETHEREUM": "ETH",
        "以太坊": "ETH",
        "TETHER": "USDT",
        "SOLANA": "SOL",
        "DOGECOIN": "DOGE",
        "CHAINLINK": "LINK",
    }
    lowered = question.lower()
    for alias, asset_code in aliases.items():
        if alias.lower() in lowered or alias in question:
            return _resolve_crypto_asset(asset_code, source="question_crypto_asset_alias", confidence="high")
    return None


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
    is_known_index = us_instrument_type(normalized_symbol) == "index"
    if stock is None and not allow_unknown and not is_known_index:
        return None

    is_verified_target = stock is not None or is_known_index
    label = _us_stock_label(stock, normalized_symbol)
    return ScopeResolution(
        selected_scope_type="us_stock",
        selected_scope_id=normalized_symbol,
        display_name=label,
        confidence=confidence if is_verified_target else "medium",
        assumption=None if is_verified_target else "未在 us_stock_master 找到完整主檔，先以 ticker 作為美股目標並回報資料缺口。",
        source=source if is_verified_target else f"{source}_unverified_symbol",
        candidates=(
            _resolution_candidate(
                scope_type="us_stock",
                scope_id=normalized_symbol,
                label=label,
                confidence=confidence if is_verified_target else "medium",
                source=source if is_verified_target else f"{source}_unverified_symbol",
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
        is_known_index = us_instrument_type(symbol) == "index"
        if (
            not explicit_marker
            and not is_known_index
            and symbol in US_SYMBOL_STOPWORDS
            and not _contains_hint(question, US_SYMBOL_CONTEXT_HINTS)
        ):
            continue

        allow_unknown = explicit_marker or is_known_index or (
            has_context and _contains_hint(question, US_SYMBOL_CONTEXT_HINTS)
        )
        resolution = _resolve_us_stock_symbol(
            db,
            symbol,
            source=source,
            confidence="high" if explicit_marker or is_known_index else "medium",
            allow_unknown=allow_unknown,
        )
        if resolution is None:
            continue

        if explicit_marker or has_context or is_known_index:
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
    for key in ("last_resolution", "previous_resolution", "resolution"):
        resolution = context.get(key)
        if isinstance(resolution, dict):
            return resolution
    return {}


def _last_omi_target(payload: AiAskRequest) -> dict[str, Any]:
    context = payload.conversation_context if isinstance(payload.conversation_context, dict) else {}
    for key in ("last_target", "previous_target", "target"):
        target = context.get(key)
        if isinstance(target, dict) and target.get("type"):
            return target

    resolution = _last_omi_resolution(payload)
    target = resolution.get("target")
    return target if isinstance(target, dict) else {}


def _conversation_target_resolution(
    db: Session | None,
    payload: AiAskRequest,
) -> ScopeResolution | None:
    target = _last_omi_target(payload)
    target_type = str(target.get("type") or "").strip().lower()
    if not target_type or target_type == "auto" or target_type not in VALID_TARGET_TYPES:
        return None

    inherited_payload = payload.model_copy(update={"target": target})
    inherited = _resolve_scope(db, inherited_payload)
    if inherited.clarification_required or inherited.error_code:
        return None

    return ScopeResolution(
        selected_scope_type=inherited.selected_scope_type,
        selected_scope_id=inherited.selected_scope_id,
        display_name=inherited.display_name,
        confidence="high",
        assumption="沿用上一輪 OMI 標的；本句未指定新的 target。",
        source="conversation_target",
        candidates=inherited.candidates,
    )


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


def _stock_target_conflict(
    *,
    named_resolution: ScopeResolution | None,
    stock_ids: tuple[str, ...],
    db: Session | None,
) -> ScopeResolution:
    candidates = (
        [
            _resolution_candidate(
                scope_type=named_resolution.selected_scope_type,
                scope_id=named_resolution.selected_scope_id,
                label=named_resolution.display_name,
                confidence="high",
                source=named_resolution.source,
            )
        ]
        if named_resolution is not None
        else []
    )
    for stock_id in stock_ids:
        if any(str((candidate.get("target") or {}).get("id") or "") == stock_id for candidate in candidates):
            continue
        candidates.append(
            _resolution_candidate(
                scope_type="stock",
                scope_id=stock_id,
                label=_stock_display_name(db, stock_id, fallback=stock_id),
                confidence="medium",
                source="question_stock_id",
            )
        )

    labels = [
        str((candidate.get("target") or {}).get("label") or (candidate.get("target") or {}).get("id") or "")
        for candidate in candidates
    ]
    labels = [label for label in labels if label]
    label_text = "、".join(labels[:3]) or "多個台股標的"
    return ScopeResolution(
        selected_scope_type="stock",
        confidence="low",
        source="target_conflict",
        candidates=tuple(candidates[:5]),
        clarification_required=True,
        clarification_question=f"偵測到不同標的（{label_text}），請明確指定要分析哪一檔。",
        clarification_reason="Multiple explicit Taiwan stock targets conflict in the same question.",
    )


def _resolve_tw_stock_from_question(
    db: Session | None,
    question: str,
) -> ScopeResolution | None:
    named_resolution = _resolve_tsmc_alias(db, question) or _resolve_stock_name_from_db(db, question)
    stock_ids = _stock_ids_in_text(question)
    named_stock_id = named_resolution.selected_scope_id if named_resolution is not None else None
    conflicting_ids = tuple(stock_id for stock_id in stock_ids if stock_id != named_stock_id)

    if named_resolution is not None and conflicting_ids:
        return _stock_target_conflict(
            named_resolution=named_resolution,
            stock_ids=conflicting_ids,
            db=db,
        )
    if named_resolution is not None:
        return named_resolution
    if len(stock_ids) > 1:
        return _stock_target_conflict(
            named_resolution=None,
            stock_ids=stock_ids,
            db=db,
        )
    if stock_ids:
        return _resolve_tw_stock_id(
            db,
            stock_ids[0],
            source="question_stock_id",
            confidence="high",
        )
    return None


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
    target_market = str(requested_target.get("market") or "").strip().lower()
    question = payload.question

    if requested_target_type != "auto":
        scope_type = TARGET_TYPE_TO_INTERNAL_SCOPE.get(requested_target_type)
        if scope_type is None:
            return _clarify_scope(
                "market",
                question,
                f"target.type is not supported yet: {requested_target_type}.",
            )

        if (
            scope_type
            in {
                "stock",
                "watchlist",
                "us_stock",
                "jp_stock",
                "jp_index",
                "kr_stock",
                "kr_index",
                "crypto_asset",
                "resource_asset",
                "us_macro",
                "us_watchlist",
                "jp_watchlist",
                "kr_watchlist",
                "tw_index",
                "tw_futures",
            }
            and target_id is None
        ):
            return _clarify_scope(
                scope_type,
                question,
                f"target.id is required for target.type={requested_target_type}.",
            )

        if scope_type == "data_freshness":
            requested_market = (
                target_market
                or _data_freshness_market_from_question(question)
                or "TW"
            )
            normalized_market = _normalize_data_freshness_market(requested_market)
            if normalized_market is None:
                return ScopeResolution(
                    selected_scope_type="data_freshness",
                    selected_scope_id=target_id,
                    selected_market=str(requested_market).upper(),
                    display_name="Data freshness",
                    confidence="high",
                    source="explicit_request",
                    error_code="UNSUPPORTED_MARKET",
                    error_message=f"尚未支援 {requested_market} 市場的 data freshness。",
                )
            return ScopeResolution(
                selected_scope_type="data_freshness",
                selected_scope_id=target_id,
                selected_market=normalized_market,
                display_name=f"{normalized_market} data freshness",
                confidence="high",
                source="explicit_request",
                candidates=(),
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

        if scope_type == "us_stock":
            normalized_us_symbol = normalize_us_symbol(target_id)
            if not _looks_like_us_symbol(normalized_us_symbol):
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported US stock/index target.id: {target_id}.",
                )
            target_id = normalized_us_symbol

        if scope_type == "jp_index":
            normalized_jp_index = normalize_jp_index_id(target_id)
            if normalized_jp_index not in JP_INDEX_TARGET_IDS:
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported Japan index target.id: {target_id}.",
            )
            target_id = normalized_jp_index

        if scope_type == "kr_stock":
            normalized_kr_symbol = normalize_kr_symbol(target_id)
            if not _looks_like_kr_symbol(normalized_kr_symbol):
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported Korea stock target.id: {target_id}.",
                )
            target_id = normalized_kr_symbol

        if scope_type == "kr_index":
            normalized_kr_index = normalize_kr_index_id(target_id)
            if normalized_kr_index not in KR_INDEX_TARGET_IDS:
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported Korea index target.id: {target_id}.",
                )
            target_id = normalized_kr_index

        if scope_type == "crypto_asset":
            normalized_crypto_asset = str(target_id or "").strip().upper()
            if get_crypto_asset(normalized_crypto_asset) is None:
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported crypto asset target.id: {target_id}.",
                )
            target_id = normalized_crypto_asset

        if scope_type == "resource_asset":
            normalized_resource_symbol = normalize_resource_symbol(target_id)
            if not list_resource_instruments(symbol=normalized_resource_symbol):
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported resource asset target.id: {target_id}.",
                )
            target_id = normalized_resource_symbol

        if scope_type == "us_macro":
            normalized_series_id = str(target_id or "").strip().upper()
            if not re.fullmatch(r"[A-Z0-9._-]{1,80}", normalized_series_id):
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Unsupported FRED series target.id: {target_id}.",
                )
            target_id = normalized_series_id

        if scope_type in {"us_watchlist", "jp_watchlist", "kr_watchlist"}:
            try:
                normalized_group_id = int(str(target_id or "").strip())
            except (TypeError, ValueError):
                normalized_group_id = 0
            if normalized_group_id <= 0:
                return _clarify_scope(
                    scope_type,
                    question,
                    f"Regional watchlist target.id must be a positive integer: {target_id}.",
                )
            target_id = str(normalized_group_id)

        if scope_type == "stock":
            stock_resolution = _resolve_tw_stock_id(
                db,
                target_id,
                source="explicit_request",
                confidence="high",
                fallback_label=requested_label,
            )
            if stock_resolution is not None:
                return stock_resolution
            return _clarify_scope(
                scope_type,
                question,
                f"Unsupported Taiwan stock target.id: {target_id}.",
            )

        display_name = (
            _stock_display_name(db, target_id)
            if scope_type == "stock" and target_id
            else _us_stock_display_name(db, target_id, fallback=target_id)
            if scope_type == "us_stock" and target_id
            else _jp_stock_display_name(db, target_id, fallback=requested_label or target_id)
            if scope_type == "jp_stock" and target_id
            else _kr_stock_display_name(db, target_id, fallback=requested_label or target_id)
            if scope_type == "kr_stock" and target_id
            else _kr_index_label(target_id)
            if scope_type == "kr_index" and target_id
            else _crypto_asset_label(target_id)
            if scope_type == "crypto_asset" and target_id
            else (
                list_resource_instruments(symbol=target_id)[0].display_name
                or list_resource_instruments(symbol=target_id)[0].name
            )
            if scope_type == "resource_asset" and target_id
            else requested_label or target_id
            if scope_type == "us_macro" and target_id
            else requested_label or f"{scope_type.removesuffix('_watchlist').upper()} watchlist {target_id}"
            if scope_type in {"us_watchlist", "jp_watchlist", "kr_watchlist"} and target_id
            else requested_label or "Active portfolio"
            if scope_type == "portfolio"
            else requested_label or "Unified source health"
            if scope_type == "source_health"
            else requested_label or "Market capability status"
            if scope_type == "capability_status"
            else requested_label or "Crypto Market"
            if scope_type == "crypto_market"
            else requested_label
        )
        return ScopeResolution(
            selected_scope_type=scope_type,
            selected_scope_id=target_id,
            selected_market=(
                str(target_market).upper()
                if target_market
                else "TW"
                if scope_type == "market"
                else None
            ),
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
        crypto_market_requested = target_market in {"crypto", "cryptocurrency"} or _question_has_crypto_context(question)
        if crypto_market_requested:
            crypto_resolution = _resolve_crypto_asset(
                target_id,
                source="explicit_scope_id",
                confidence="high",
            )
            if crypto_resolution is not None:
                return crypto_resolution

        kr_market_requested = target_market in {"kr", "korea", "krx"} or _question_has_kr_context(question)
        if kr_market_requested:
            kr_index_resolution = _resolve_kr_index(
                target_id,
                source="explicit_scope_id",
                confidence="high",
            )
            if kr_index_resolution is not None:
                return kr_index_resolution

            kr_stock_resolution = _resolve_kr_stock_symbol(
                db,
                target_id,
                source="explicit_scope_id",
                confidence="high",
                allow_unknown=True,
            )
            if kr_stock_resolution is not None:
                return kr_stock_resolution

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

        if _contains_hint(question, FRESHNESS_HINTS) and (
            _looks_like_stock_id(target_id)
            or normalized_target_id in {"ALL", "GLOBAL", "MARKET", "TW"}
        ):
            stock_id = target_id if _looks_like_stock_id(target_id) else None
            return ScopeResolution(
                selected_scope_type="data_freshness",
                selected_scope_id=stock_id,
                selected_market=_data_freshness_market_from_question(question) or "TW",
                display_name=_stock_display_name(db, stock_id) if stock_id else None,
                confidence="high",
                source="explicit_scope_id",
                candidates=(),
            )

        if _question_has_jp_context(question):
            normalized_jp_index = normalize_jp_index_id(target_id)
            if normalized_jp_index in JP_INDEX_TARGET_IDS:
                label = requested_label or normalized_target_id
                return ScopeResolution(
                    selected_scope_type="jp_index",
                    selected_scope_id=normalized_jp_index,
                    display_name=label,
                    confidence="high",
                    source="explicit_scope_id",
                    candidates=(
                        _resolution_candidate(
                            scope_type="jp_index",
                            scope_id=normalized_jp_index,
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
            stock_resolution = _resolve_tw_stock_id(
                db,
                target_id,
                source="explicit_scope_id",
                confidence="high",
            )
            if stock_resolution is not None:
                return stock_resolution

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
            allow_unknown=(
                _contains_hint(question, US_SYMBOL_CONTEXT_HINTS)
                or normalize_us_symbol(target_id).startswith("^")
            ),
        )
        if us_symbol_resolution is not None:
            return us_symbol_resolution

    jp_symbol_resolution = _resolve_jp_stock_symbol_from_question(db, question)
    if jp_symbol_resolution is not None:
        return jp_symbol_resolution

    kr_symbol_resolution = _resolve_kr_stock_symbol_from_question(db, question)
    if kr_symbol_resolution is not None:
        return kr_symbol_resolution

    if _contains_hint(question, SOURCE_HEALTH_CONTEXT_HINTS):
        return ScopeResolution(
            selected_scope_type="source_health",
            display_name="Unified source health",
            confidence="high",
            source="question_source_health",
            candidates=(),
        )

    if _contains_hint(question, CAPABILITY_STATUS_CONTEXT_HINTS):
        return ScopeResolution(
            selected_scope_type="capability_status",
            display_name="Market capability status",
            confidence="high",
            source="question_capability_status",
            candidates=(),
        )

    if _contains_hint(question, PORTFOLIO_CONTEXT_HINTS):
        return ScopeResolution(
            selected_scope_type="portfolio",
            display_name="Active portfolio",
            confidence="high",
            source="question_portfolio",
            candidates=(),
        )

    resource_target = _alias_target(question, RESOURCE_QUESTION_ALIASES)
    if resource_target is not None:
        instrument = list_resource_instruments(symbol=resource_target)[0]
        return ScopeResolution(
            selected_scope_type="resource_asset",
            selected_scope_id=resource_target,
            display_name=instrument.display_name or instrument.name,
            confidence="high",
            source="question_resource_alias",
            candidates=(),
        )

    macro_target = _alias_target(question, US_MACRO_QUESTION_ALIASES)
    if macro_target is not None:
        return ScopeResolution(
            selected_scope_type="us_macro",
            selected_scope_id=macro_target,
            display_name=macro_target,
            confidence="high",
            source="question_us_macro_alias",
            candidates=(),
        )

    if _question_has_crypto_context(question):
        crypto_asset_resolution = _resolve_crypto_asset_from_question(question)
        if crypto_asset_resolution is not None:
            return crypto_asset_resolution

        return ScopeResolution(
            selected_scope_type="crypto_market",
            display_name="Crypto Market",
            confidence="medium",
            source="question_crypto_market",
            candidates=(),
        )

    us_entity_resolution = _resolve_us_stock_symbol_from_question(db, question)
    if us_entity_resolution is not None:
        return us_entity_resolution

    if _contains_hint(question, FRESHNESS_HINTS):
        stock_id = _first_stock_id_in_text(question)
        tsmc_resolution = _resolve_tsmc_alias(db, question)
        if stock_id is None and tsmc_resolution is not None:
            stock_id = tsmc_resolution.selected_scope_id

        return ScopeResolution(
            selected_scope_type="data_freshness",
            selected_scope_id=stock_id,
            selected_market=_data_freshness_market_from_question(question) or "TW",
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
        if group_id is None:
            regional_group_match = re.search(
                r"(?:watchlist|group|群組|自選群組)\s*#?\s*(\d+)",
                question,
                flags=re.IGNORECASE,
            )
            if regional_group_match is not None:
                group_id = regional_group_match.group(1)
        if group_id is not None:
            lowered_question = question.casefold()
            regional_scope = (
                "jp_watchlist"
                if _question_has_jp_context(question)
                or any(hint in lowered_question for hint in ("日股", "日本", "japan", "jp watchlist"))
                else "kr_watchlist"
                if _question_has_kr_context(question)
                or any(hint in lowered_question for hint in ("韓股", "韓國", "korea", "krx", "kospi", "kosdaq"))
                else "us_watchlist"
                if any(hint in lowered_question for hint in ("美股", "美國", "us watchlist", "u.s. watchlist"))
                else None
            )
            if regional_scope is not None:
                return ScopeResolution(
                    selected_scope_type=regional_scope,
                    selected_scope_id=group_id,
                    display_name=f"{regional_scope.removesuffix('_watchlist').upper()} watchlist {group_id}",
                    confidence="high",
                    source="question_regional_watchlist_group_id",
                    candidates=(),
                )
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

    tw_stock_resolution = _resolve_tw_stock_from_question(db, question)
    if tw_stock_resolution is not None:
        return tw_stock_resolution

    us_symbol_resolution = _resolve_us_stock_symbol_from_question(db, question)
    if us_symbol_resolution is not None:
        return us_symbol_resolution

    if _contains_hint(question, MARKET_HINTS):
        return ScopeResolution(
            selected_scope_type="market",
            confidence="medium",
            source="market_hint",
            candidates=(),
        )

    conversation_resolution = _conversation_target_resolution(db, payload)
    if conversation_resolution is not None:
        return conversation_resolution

    if (
        _contains_hint(question, STOCK_REFERENCE_HINTS)
        or _contains_hint(question, ANALYSIS_HINTS)
        or _contains_hint(question, ("分點", "券商分點", "主力買賣", "主要買賣方"))
    ):
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
