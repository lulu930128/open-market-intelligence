from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta, timezone
import json
import logging
from os import getpid
from threading import Lock, get_ident
from time import monotonic

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import MarketDailyPrice, MarketIndexDailyStat, SourceRegistry, StockMaster
from app.market.index_parsers import as_float as _as_float
from app.market.index_parsers import as_int as _as_int
from app.market.index_parsers import count_with_limit as _count_with_limit
from app.market.index_parsers import list_value as _list_value
from app.market.index_parsers import (
    parse_tpex_market_highlight_rows as _parse_tpex_market_highlight_rows,
)
from app.market.index_parsers import parse_tpex_market_daily_rows as _parse_tpex_market_daily_rows
from app.market.index_parsers import parse_trade_date as _parse_trade_date
from app.market.index_parsers import (
    parse_twse_index_daily_ohlc_rows as _parse_twse_index_daily_ohlc_rows,
)
from app.market.index_parsers import (
    parse_twse_market_daily_history_rows as _parse_twse_market_daily_history_rows,
)
from app.market.index_parsers import regular_stock_code as _regular_stock_code
from app.market.index_parsers import signed_change as _signed_change
from app.market.providers import fetch_json as provider_fetch_json
from app.market.providers import http_get
from app.market.providers import tpex, twse, twse_mis, yahoo
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import is_taiwan_trading_day
from app.observability.provider_fallback import observe_provider_fallback
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)


logger = logging.getLogger(__name__)
YAHOO_CHART_URL = yahoo.CHART_URL
TWSE_MIS_STOCK_INFO_URL = twse_mis.STOCK_INFO_URL
TWSE_MIS_REFERER_URL = twse_mis.REFERER_URL
TWSE_INDEX_LIST_URL = twse.INDEX_LIST_URL
TWSE_DAILY_QUOTES_URL = twse.DAILY_QUOTES_URL
TWSE_RWD_MI_INDEX_URL = twse.RWD_MI_INDEX_URL
TWSE_INDEX_5S_URL = twse.INDEX_5S_URL
TWSE_INDEX_DAILY_OHLC_URL = twse.INDEX_DAILY_OHLC_URL
TWSE_MARKET_DAILY_URL = twse.MARKET_DAILY_URL
TWSE_MARKET_DAILY_HISTORY_URL = twse.MARKET_DAILY_HISTORY_URL
TWSE_COMPANY_BASIC_URL = twse.COMPANY_BASIC_URL
TPEX_DAILY_INDEX_URL = tpex.DAILY_INDEX_URL
TPEX_DAILY_QUOTES_URL = tpex.DAILY_QUOTES_URL
TPEX_INDEX_5S_URL = tpex.INDEX_5S_URL
TPEX_MARKET_HIGHLIGHT_URL = tpex.MARKET_HIGHLIGHT_URL
TAIPEI_TZ = timezone(timedelta(hours=8))
CACHE_TTL_SECONDS = 45
TWSE_MIS_LIVE_BREADTH_CACHE_TTL_SECONDS = 30
TWSE_MIS_LIVE_BREADTH_BATCH_SIZE = 100
TWSE_MIS_LIVE_BREADTH_MIN_CODES = 500
INDEX_LIST_CACHE_TTL_SECONDS = 300
MAX_INDEX_STAT_FETCH_WORKERS = 4
MAX_TWSE_INDEX_DAILY_OHLC_OVERLAY_MONTHS = 3
MAX_TPEX_HISTORY_FETCH_DATES = 3_000
TPEX_HISTORY_PERSIST_BATCH_SIZE = 50
TPEX_MARKET_HIGHLIGHT_START_DATE = date(2007, 1, 1)
MAX_TWSE_MIS_BREADTH_FETCH_WORKERS = 2
TWSE_MIS_BREADTH_CIRCUIT_FAILURE_THRESHOLD = 3
TWSE_MIS_BREADTH_CIRCUIT_COOLDOWN_SECONDS = 90
TAIWAN_INDEX_SESSION_CLOSE_TIME = time(13, 30)
TAIWAN_INDEX_LIVE_REFRESH_END_TIME = time(13, 40)
TAIWAN_INDEX_RECONCILIATION_END_TIME = time(16, 0)
TAIWAN_INDEX_RECONCILIATION_RETRY_SECONDS = 300

INDEX_CONFIGS = (
    {
        "index_id": "TAIEX",
        "label": "加權指數",
        "short_label": "加權",
        "market": "TWSE",
        "symbol": "^TWII",
        "mis_channel": "tse_t00.tw",
    },
    {
        "index_id": "TPEX",
        "label": "櫃買指數",
        "short_label": "櫃買",
        "market": "TPEX",
        "symbol": "^TWOII",
        "mis_channel": "otc_o00.tw",
    },
)
INDEX_CONFIG_BY_ID = {str(config["index_id"]).upper(): config for config in INDEX_CONFIGS}
INDEX_TIMEFRAME_INTERVALS = {
    "daily": "1d",
    "weekly": "1wk",
    "monthly": "1mo",
}
MAX_INDEX_BARS = 5000

_CACHE: dict[str, object] = {
    "expires_at": 0.0,
    "payload": None,
}
_SUMMARY_REFRESH_LOCK = Lock()
MARKET_INDEX_SUMMARY_CACHE_PATH = settings.runtime_lock_dir / "market-index-summary.json"
_QUOTE_STATS_CACHE: dict[str, dict[str, object]] = {}
_INDEX_LIST_CACHE: dict[str, dict[str, object]] = {}
_SHARES_CACHE: dict[str, dict[str, object]] = {}
_CONTRIBUTION_CACHE: dict[str, dict[str, object]] = {}
_TWSE_INDEX_5S_CACHE: dict[str, dict[str, object]] = {}
_TWSE_INDEX_DAILY_OHLC_CACHE: dict[str, dict[str, object]] = {}
_TWSE_MIS_LIVE_BREADTH_CACHE: dict[str, dict[str, object]] = {}
_TWSE_MIS_LIVE_BREADTH_LAST_GOOD: dict[str, dict] = {}
_TWSE_MIS_LIVE_STOCK_ROWS: dict[str, list[dict[str, object]]] = {}
_TWSE_MIS_BREADTH_REFRESH_LOCK = Lock()
_TWSE_MIS_BREADTH_CIRCUIT_FAILURES = 0
_TWSE_MIS_BREADTH_CIRCUIT_OPEN_UNTIL = 0.0
_TWSE_MIS_STOCK_STATE: dict[str, dict[str, object]] = {}
TWSE_INDEX_5S_FIELD_BY_INDEX_ID = {
    "TAIEX": "發行量加權股價指數",
    "TPEX": "櫃買指數",
}


def is_taiwan_index_live_refresh_window(now: datetime | None = None) -> bool:
    local_now = now or datetime.now(TAIPEI_TZ)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=TAIPEI_TZ)
    else:
        local_now = local_now.astimezone(TAIPEI_TZ)
    return (
        is_taiwan_trading_day(local_now.date())
        and time(8, 55) <= local_now.time() <= TAIWAN_INDEX_LIVE_REFRESH_END_TIME
    )


def _summary_cache_json_default(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    raise TypeError(f"Unsupported market index cache value: {type(value).__name__}")


def _persist_shared_market_index_summary(payload: dict) -> None:
    path = MARKET_INDEX_SUMMARY_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(
        f".{path.name}.{getpid()}.{get_ident()}.tmp"
    )
    try:
        temporary_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                default=_summary_cache_json_default,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _load_shared_market_index_summary() -> tuple[dict | None, str | None]:
    path = MARKET_INDEX_SUMMARY_CACHE_PATH
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Shared market index summary cache is unreadable: %s", exc)
        return None, f"Shared market index summary cache is unreadable: {exc}"
    if not isinstance(payload, dict) or not isinstance(payload.get("indices"), list):
        return None, "Shared market index summary cache has an invalid payload shape."
    return payload, None


def _summary_payload_as_of(payload: dict | None) -> datetime | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("as_of")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _sqlite_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _newer_summary_payload(
    memory_payload: dict | None,
    shared_payload: dict | None,
) -> tuple[dict | None, str]:
    if shared_payload is None:
        return memory_payload, "memory_cache"
    if memory_payload is None:
        return shared_payload, "shared_cache"
    memory_as_of = _summary_payload_as_of(memory_payload)
    shared_as_of = _summary_payload_as_of(shared_payload)
    if shared_as_of is not None and (
        memory_as_of is None or shared_as_of > memory_as_of
    ):
        return shared_payload, "shared_cache"
    return memory_payload, "memory_cache"


def market_index_summary_needs_reconciliation(
    payload: dict | None,
    *,
    now: datetime | None = None,
    allow_late: bool = False,
) -> bool:
    local_now = now or datetime.now(TAIPEI_TZ)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=TAIPEI_TZ)
    else:
        local_now = local_now.astimezone(TAIPEI_TZ)

    if not is_taiwan_trading_day(local_now.date()):
        return False
    if local_now.time() < TAIWAN_INDEX_LIVE_REFRESH_END_TIME:
        return False
    if not allow_late and local_now.time() > TAIWAN_INDEX_RECONCILIATION_END_TIME:
        return False
    if not isinstance(payload, dict):
        return True

    items_by_id = {
        str(item.get("index_id") or "").upper(): item
        for item in payload.get("indices") or []
        if isinstance(item, dict)
    }
    session_close = datetime.combine(
        local_now.date(),
        TAIWAN_INDEX_SESSION_CLOSE_TIME,
        tzinfo=TAIPEI_TZ,
    )

    for config in INDEX_CONFIGS:
        item = items_by_id.get(str(config["index_id"]).upper())
        if not isinstance(item, dict):
            return True
        if _parse_trade_date(item.get("time")) != local_now.date():
            return True

        item_as_of = _summary_payload_as_of(item)
        if item_as_of is None or item_as_of.astimezone(TAIPEI_TZ) < session_close:
            return True

        breadth = item.get("breadth")
        breadth_status = _breadth_status_contract(item)
        if (
            not isinstance(breadth, dict)
            or _breadth_trade_date(breadth) != local_now.date()
            or breadth_status.get("status") != "ready"
            or breadth_status.get("scope") != "full_market"
        ):
            return True

    return False


def _stale_market_index_ids(
    payload: dict,
    *,
    expected_date: date,
) -> list[str]:
    items_by_id = {
        str(item.get("index_id") or "").upper(): item
        for item in payload.get("indices") or []
        if isinstance(item, dict)
    }
    return [
        index_id
        for config in INDEX_CONFIGS
        for index_id in [str(config["index_id"]).upper()]
        for item in [items_by_id.get(index_id)]
        if (
            not isinstance(item, dict)
            or (_parse_trade_date(item.get("time")) or date.min) < expected_date
        )
    ]


def _stale_live_market_index_ids(
    payload: dict,
    *,
    now: datetime,
    stale_after_seconds: int,
) -> list[str]:
    if not is_taiwan_index_live_refresh_window(now):
        return []

    items_by_id = {
        str(item.get("index_id") or "").upper(): item
        for item in payload.get("indices") or []
        if isinstance(item, dict)
    }
    stale_ids: list[str] = []
    for config in INDEX_CONFIGS:
        index_id = str(config["index_id"]).upper()
        item = items_by_id.get(index_id)
        item_as_of = _summary_payload_as_of(item) if isinstance(item, dict) else None
        if item_as_of is None:
            stale_ids.append(index_id)
            continue
        age_seconds = max(
            (now - item_as_of.astimezone(TAIPEI_TZ)).total_seconds(),
            0,
        )
        if age_seconds > stale_after_seconds:
            stale_ids.append(index_id)
    return stale_ids


def _summary_cache_view(
    payload: dict,
    *,
    origin: str,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(TAIPEI_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TAIPEI_TZ)
    else:
        now = now.astimezone(TAIPEI_TZ)
    expected_date = expected_daily_price_date(now=now)
    as_of = _summary_payload_as_of(payload)
    live_age_seconds = (
        max((now - as_of.astimezone(TAIPEI_TZ)).total_seconds(), 0)
        if as_of is not None
        else None
    )
    live_stale_after = max(
        int(settings.scheduler_taiwan_market_index_interval_seconds) * 3,
        15,
    )
    stale_index_ids = _stale_market_index_ids(
        payload,
        expected_date=expected_date,
    )
    stale_live_index_ids = _stale_live_market_index_ids(
        payload,
        now=now,
        stale_after_seconds=live_stale_after,
    )
    date_is_stale = bool(stale_index_ids)
    live_is_stale = bool(stale_live_index_ids)
    reconciliation_is_needed = market_index_summary_needs_reconciliation(
        payload,
        now=now,
    )
    reconciliation_is_due = reconciliation_is_needed and (
        live_age_seconds is None
        or live_age_seconds >= TAIWAN_INDEX_RECONCILIATION_RETRY_SECONDS
    )
    refresh_recommended = date_is_stale or live_is_stale or reconciliation_is_due
    warnings = list(payload.get("warnings") or [])
    if date_is_stale:
        warnings.append(
            "Index summary cache is missing or older than the expected Taiwan "
            f"trading date for: {', '.join(stale_index_ids)}."
        )
    if live_is_stale:
        warnings.append(
            "Index summary shared cache is stale during the Taiwan live polling "
            f"window for: {', '.join(stale_live_index_ids)}."
        )
    if reconciliation_is_needed:
        warnings.append(
            "Index summary is awaiting bounded post-close reconciliation for the current Taiwan trading date."
        )
    return _with_breadth_status_contract({
        **payload,
        "cache_status": f"stale_{origin}" if refresh_recommended else origin,
        "refresh_recommended": refresh_recommended,
        "warnings": list(dict.fromkeys(str(item) for item in warnings if item)),
    })


def _fetch_json(url: str):
    return provider_fetch_json(url, timeout_seconds=20, request=http_get)


def _moving_average(values: list[float | None], window: int) -> float | None:
    valid_values = [value for value in values[-window:] if value is not None]

    if len(valid_values) < window:
        return None

    return sum(valid_values) / window


def _market_source_name(market: str) -> str:
    if market == "TPEX":
        return TPEX_DAILY_QUOTES_SOURCE_NAME

    return TWSE_DAILY_TRADING_SOURCE_NAME


def _market_breadth_label(market: str, scope: str | None) -> str:
    normalized_market = str(market or "").upper()
    normalized_scope = str(scope or "local_dataset")
    market_label = "上市" if normalized_market == "TWSE" else "上櫃" if normalized_market == "TPEX" else normalized_market

    if normalized_scope == "full_market":
        return f"{market_label}全市場廣度"
    if normalized_scope == "registered_universe":
        return f"{market_label}即時廣度（註冊範圍）"
    if normalized_scope == "omi_sample":
        return "OMI 樣本股廣度"
    return f"{market_label}本機資料集廣度"


def _market_breadth_universe_definition(
    scope: str | None,
    market: str | None = None,
) -> dict[str, object]:
    normalized_scope = str(scope or "local_dataset")
    normalized_market = str(market or "TWSE").upper()
    if normalized_scope == "registered_universe":
        return {
            "authority": "omi_stock_master",
            "inclusion_rule": (
                f"market={normalized_market}, is_active=true, instrument_type=stock, "
                "four_digit_numeric_security_code"
            ),
            "instrument_type_policy": (
                "Non-stock instruments are excluded when StockMaster classifies "
                "them separately; ETF/ETN treatment therefore depends on registry classification."
            ),
            "missing_quote_policy": "unknown_not_unchanged",
            "official_full_market": False,
        }
    if normalized_scope == "full_market":
        return {
            "authority": "exchange_published_market_rows",
            "inclusion_rule": (
                "provider rows with a four-digit numeric security code; the exchange "
                "provider's instrument classification is not redefined by OMI"
            ),
            "instrument_type_policy": "provider_defined",
            "missing_quote_policy": (
                "excluded_from_classified_counts_and_reported_as_coverage_gap"
            ),
            "official_full_market": True,
        }
    return {
        "authority": "local_cached_dataset",
        "inclusion_rule": "rows present in the named local source dataset",
        "instrument_type_policy": "source_defined",
        "missing_quote_policy": "reported_by_available_coverage_fields",
        "official_full_market": False,
    }


def _breadth_status_contract(index_payload: dict) -> dict:
    market = str(index_payload.get("market") or "unknown")
    breadth = index_payload.get("breadth")
    if not isinstance(breadth, dict):
        return {
            "slot": "market_breadth",
            "status": "failed",
            "scope": None,
            "source": None,
            "reason": (
                f"Current {market} market breadth is unavailable; "
                "OMI sample movers must not be substituted for this slot."
            ),
            "warnings": [],
        }

    warnings = [str(item) for item in breadth.get("warnings") or [] if item]
    source = str(breadth.get("source") or "") or None
    unknown_count = _as_int(breadth.get("unknown_count")) or 0
    missing_count = _as_int(breadth.get("missing_count")) or 0
    is_partial = bool(
        warnings
        or unknown_count > 0
        or missing_count > 0
        or (source and "partial" in source)
    )
    return {
        "slot": "market_breadth",
        "status": "partial" if is_partial else "ready",
        "scope": breadth.get("scope"),
        "source": source,
        "reason": (
            "Market breadth has incomplete quote coverage; inspect warnings and coverage fields."
            if is_partial
            else None
        ),
        "warnings": warnings,
    }


def _with_breadth_status_contract(payload: dict) -> dict:
    warnings = [str(item) for item in payload.get("warnings") or [] if item]
    contract_indices: list[dict] = []
    for raw_item in payload.get("indices") or []:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        if isinstance(item.get("breadth"), dict):
            item["breadth"] = {
                **item["breadth"],
                "universe_definition": item["breadth"].get(
                    "universe_definition"
                )
                or _market_breadth_universe_definition(
                    item["breadth"].get("scope"),
                    item["breadth"].get("market") or item.get("market"),
                ),
            }
        breadth_status = _breadth_status_contract(item)
        item["breadth_status"] = breadth_status
        identity = item.get("index_id") or item.get("market") or "Index"
        if breadth_status["status"] == "failed":
            warnings.append(
                f"{identity} market breadth failed: {breadth_status['reason']}"
            )
        elif breadth_status["status"] == "partial":
            warnings.append(f"{identity} market breadth is partial.")
        contract_indices.append(item)
    return {
        **payload,
        "indices": contract_indices,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _latest_market_breadth(db: Session, market: str) -> dict | None:
    source_name = _market_source_name(market)
    latest_trade_date = (
        db.query(func.max(MarketDailyPrice.trade_date))
        .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
        .filter(SourceRegistry.source_name == source_name)
        .scalar()
    )

    if latest_trade_date is None:
        return None

    rows = (
        db.query(MarketDailyPrice.price_change)
        .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
        .filter(SourceRegistry.source_name == source_name)
        .filter(MarketDailyPrice.trade_date == latest_trade_date)
        .all()
    )
    changes = [row.price_change for row in rows]

    return {
        "market": market,
        "scope": "local_dataset",
        "universe_definition": _market_breadth_universe_definition(
            "local_dataset",
            market,
        ),
        "label": _market_breadth_label(market, "local_dataset"),
        "trade_date": latest_trade_date,
        "advance_count": sum(1 for value in changes if value is not None and value > 0),
        "decline_count": sum(1 for value in changes if value is not None and value < 0),
        "unchanged_count": sum(1 for value in changes if value == 0),
        "total_count": len(changes),
        "limit_up_count": None,
        "limit_down_count": None,
        "trade_value": None,
        "source": source_name,
    }


def _quote_limit_counts(close: float | None, change: float | None) -> tuple[int, int]:
    if close is None or change is None:
        return 0, 0

    previous_close = close - change

    if previous_close <= 0:
        return 0, 0

    change_pct = (change / previous_close) * 100

    if change_pct >= 9.5:
        return 1, 0

    if change_pct <= -9.5:
        return 0, 1

    return 0, 0


def _prices_equal(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False

    return abs(left - right) < 0.000001


def _twse_mis_live_breadth_stock_codes(
    db: Session,
    market: str = "TWSE",
) -> list[str]:
    normalized_market = str(market or "").strip().upper()
    rows = (
        db.query(StockMaster.stock_id)
        .filter(func.upper(StockMaster.market) == normalized_market)
        .filter(StockMaster.instrument_type == "stock")
        .filter(StockMaster.is_active.is_(True))
        .order_by(StockMaster.stock_id.asc())
        .all()
    )
    codes = [
        code
        for row in rows
        for code in [_regular_stock_code(row.stock_id)]
        if code is not None
    ]
    return list(dict.fromkeys(codes))


def _chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _fetch_twse_mis_stock_message_batch(
    codes: list[str],
    market: str = "TWSE",
) -> list[dict]:
    return twse_mis.fetch_stock_messages(
        codes,
        exchange="otc" if str(market).upper() == "TPEX" else "tse",
        timeout_seconds=20,
        request=http_get,
    )


def _fetch_twse_mis_stock_messages(
    codes: list[str],
    market: str = "TWSE",
) -> tuple[list[dict], int]:
    batches = list(_chunked(codes, TWSE_MIS_LIVE_BREADTH_BATCH_SIZE))

    if not batches:
        return [], 0

    messages: list[dict] = []
    failed_batches = 0
    first_error: Exception | None = None

    with ThreadPoolExecutor(max_workers=MAX_TWSE_MIS_BREADTH_FETCH_WORKERS) as executor:
        futures = [
            executor.submit(
                _fetch_twse_mis_stock_message_batch,
                batch,
                market,
            )
            for batch in batches
        ]

        for future in as_completed(futures):
            try:
                messages.extend(future.result())
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                failed_batches += 1

    if first_error is not None:
        observe_provider_fallback(
            first_error,
            operation="indices.twse_mis_breadth_refresh",
        )

    return messages, failed_batches


def _cache_twse_mis_live_breadth(market: str, payload: dict | None) -> dict | None:
    _TWSE_MIS_LIVE_BREADTH_CACHE[market] = {
        "expires_at": monotonic() + TWSE_MIS_LIVE_BREADTH_CACHE_TTL_SECONDS,
        "payload": payload,
    }
    if isinstance(payload, dict):
        _TWSE_MIS_LIVE_BREADTH_LAST_GOOD[market] = payload
    return payload


def _twse_mis_message_datetime(message: dict) -> datetime | None:
    snapshot = _build_mis_snapshot_time(
        str(message.get("d") or message.get("^") or ""),
        str(message.get("t") or message.get("%") or ""),
    )

    if not snapshot:
        return None

    try:
        return datetime.fromisoformat(snapshot)
    except ValueError:
        return None


def _classify_twse_mis_live_breadth_message(
    message: dict,
    market: str = "TWSE",
) -> dict | None:
    code = _regular_stock_code(message.get("c"))

    if code is None:
        return None

    trade_date = _parse_trade_date(message.get("d") or message.get("^"))
    previous_close = _as_float(message.get("y"))
    latest_price = _as_float(message.get("z")) or _as_float(message.get("pz"))
    normalized_market = str(market or "TWSE").strip().upper()
    state_key = f"{normalized_market}:{code}"
    cached_state = _TWSE_MIS_STOCK_STATE.get(state_key)

    if (
        latest_price is None
        and isinstance(cached_state, dict)
        and cached_state.get("trade_date") == trade_date
    ):
        latest_price = _as_float(cached_state.get("price"))

    if latest_price is not None:
        _TWSE_MIS_STOCK_STATE[state_key] = {
            "trade_date": trade_date,
            "price": latest_price,
            "as_of": _twse_mis_message_datetime(message),
        }

    direction: str | None = None

    if latest_price is not None and previous_close is not None:
        if latest_price > previous_close:
            direction = "advance"
        elif latest_price < previous_close:
            direction = "decline"
        else:
            direction = "unchanged"
    elif previous_close is not None:
        high = _as_float(message.get("h"))
        low = _as_float(message.get("l"))
        open_price = _as_float(message.get("o"))

        if high is not None and high < previous_close:
            direction = "decline"
        elif low is not None and low > previous_close:
            direction = "advance"
        elif (
            _prices_equal(open_price, previous_close)
            and _prices_equal(high, previous_close)
            and _prices_equal(low, previous_close)
        ):
            direction = "unchanged"

    limit_up_price = _as_float(message.get("u"))
    limit_down_price = _as_float(message.get("w"))
    is_limit_up = (
        latest_price is not None
        and limit_up_price is not None
        and latest_price >= limit_up_price
    )
    is_limit_down = (
        latest_price is not None
        and limit_down_price is not None
        and latest_price <= limit_down_price
    )
    cumulative_volume_lots = _as_int(message.get("v"))
    estimated_trade_value = (
        int(latest_price * cumulative_volume_lots * 1000)
        if latest_price is not None
        and cumulative_volume_lots is not None
        and cumulative_volume_lots >= 0
        else None
    )

    return {
        "code": code,
        "market": normalized_market,
        "trade_date": trade_date,
        "as_of": _twse_mis_message_datetime(message),
        "current_price": latest_price,
        "previous_close": previous_close,
        "open_price": _as_float(message.get("o")),
        "high_price": _as_float(message.get("h")),
        "low_price": _as_float(message.get("l")),
        "cumulative_volume_lots": cumulative_volume_lots,
        "estimated_trade_value": estimated_trade_value,
        "direction": direction,
        "is_limit_up": is_limit_up,
        "is_limit_down": is_limit_down,
    }


def _fetch_twse_mis_live_market_breadth_unguarded(db: Session, market: str) -> dict | None:
    normalized_market = str(market or "").strip().upper()
    if normalized_market not in {"TWSE", "TPEX"}:
        return None

    cached = _TWSE_MIS_LIVE_BREADTH_CACHE.get(normalized_market)

    if cached and monotonic() < float(cached["expires_at"]):
        payload = cached.get("payload")

        if isinstance(payload, dict):
            return payload

        return None

    codes = _twse_mis_live_breadth_stock_codes(
        db,
        normalized_market,
    )

    minimum_codes = (
        TWSE_MIS_LIVE_BREADTH_MIN_CODES
        if normalized_market == "TWSE"
        else 250
    )
    if len(codes) < minimum_codes:
        return _cache_twse_mis_live_breadth(normalized_market, None)

    messages, failed_batches = _fetch_twse_mis_stock_messages(
        codes,
        normalized_market,
    )

    if not messages:
        return _cache_twse_mis_live_breadth(normalized_market, None)

    code_set = set(codes)
    classified_rows = [
        row
        for message in messages
        for row in [
            _classify_twse_mis_live_breadth_message(
                message,
                normalized_market,
            )
        ]
        if row is not None and row["code"] in code_set
    ]

    if not classified_rows:
        return _cache_twse_mis_live_breadth(normalized_market, None)
    _TWSE_MIS_LIVE_STOCK_ROWS[normalized_market] = [
        dict(row) for row in classified_rows
    ]

    received_codes = {str(row["code"]) for row in classified_rows}
    advance_count = sum(1 for row in classified_rows if row.get("direction") == "advance")
    decline_count = sum(1 for row in classified_rows if row.get("direction") == "decline")
    unchanged_count = sum(1 for row in classified_rows if row.get("direction") == "unchanged")
    coverage_count = advance_count + decline_count + unchanged_count
    total_count = len(codes)
    unknown_count = max(total_count - coverage_count, 0)
    missing_count = max(total_count - len(received_codes), 0)
    as_of_values = [row.get("as_of") for row in classified_rows if row.get("as_of") is not None]
    trade_dates = [
        row.get("trade_date")
        for row in classified_rows
        if isinstance(row.get("trade_date"), date)
    ]
    source_prefix = (
        "twse_mis_tpex_live_breadth"
        if normalized_market == "TPEX"
        else "twse_mis_live_breadth"
    )
    source = (
        source_prefix
        if unknown_count == 0 and failed_batches == 0
        else f"{source_prefix}_partial"
    )
    warnings: list[str] = []

    if unknown_count > 0:
        warnings.append(
            f"Some {normalized_market} MIS quotes did not expose a current "
            "or inferable price."
        )

    if failed_batches > 0:
        warnings.append(
            f"{failed_batches} {normalized_market} MIS quote batch(es) failed."
        )
    estimated_trade_values = [
        int(row["estimated_trade_value"])
        for row in classified_rows
        if row.get("estimated_trade_value") is not None
    ]
    estimated_trade_value = (
        sum(estimated_trade_values)
        if estimated_trade_values
        else None
    )

    payload = {
        "market": normalized_market,
        "scope": "registered_universe",
        "universe_definition": _market_breadth_universe_definition(
            "registered_universe",
            normalized_market,
        ),
        "label": _market_breadth_label(
            normalized_market,
            "registered_universe",
        ),
        "trade_date": max(trade_dates) if trade_dates else None,
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "limit_up_count": sum(1 for row in classified_rows if row.get("is_limit_up")),
        "limit_down_count": sum(1 for row in classified_rows if row.get("is_limit_down")),
        "trade_value": estimated_trade_value,
        "trade_value_is_estimate": estimated_trade_value is not None,
        "trade_value_semantics": (
            "estimated_latest_price_x_cumulative_volume_lots"
            if estimated_trade_value is not None
            else "unavailable"
        ),
        "trade_value_confidence": (
            "medium" if estimated_trade_value is not None else None
        ),
        "source": source,
        "as_of": max(as_of_values) if as_of_values else datetime.now(TAIPEI_TZ),
        "coverage_count": coverage_count,
        "unknown_count": unknown_count,
        "message_count": len(received_codes),
        "missing_count": missing_count,
        "failed_batch_count": failed_batches,
        "warnings": warnings,
    }
    return _cache_twse_mis_live_breadth(normalized_market, payload)


def reset_twse_mis_breadth_guard() -> None:
    global _TWSE_MIS_BREADTH_CIRCUIT_FAILURES
    global _TWSE_MIS_BREADTH_CIRCUIT_OPEN_UNTIL
    _TWSE_MIS_LIVE_BREADTH_CACHE.clear()
    _TWSE_MIS_LIVE_BREADTH_LAST_GOOD.clear()
    _TWSE_MIS_LIVE_STOCK_ROWS.clear()
    _TWSE_MIS_BREADTH_CIRCUIT_FAILURES = 0
    _TWSE_MIS_BREADTH_CIRCUIT_OPEN_UNTIL = 0.0


def get_cached_taiwan_intraday_stock_rows(
    market: str | None = None,
) -> list[dict[str, object]]:
    markets = (
        [str(market).strip().upper()]
        if market is not None
        else ["TWSE", "TPEX"]
    )
    return [
        dict(row)
        for normalized_market in markets
        for row in _TWSE_MIS_LIVE_STOCK_ROWS.get(
            normalized_market,
            [],
        )
    ]


def _stale_twse_mis_breadth(market: str, *, circuit_open: bool) -> dict | None:
    payload = _TWSE_MIS_LIVE_BREADTH_LAST_GOOD.get(market)
    if not isinstance(payload, dict):
        return None
    return {
        **payload,
        "source": "twse_mis_live_breadth_stale",
        "warnings": [
            *(payload.get("warnings") or []),
            "TWSE MIS breadth refresh is temporarily suspended by the provider circuit breaker."
            if circuit_open
            else "TWSE MIS breadth refresh failed; returning the last successful snapshot.",
        ],
        "provider_guard": {
            "status": "circuit_open" if circuit_open else "degraded",
            "retry_after_seconds": max(
                int(_TWSE_MIS_BREADTH_CIRCUIT_OPEN_UNTIL - monotonic()),
                0,
            )
            if circuit_open
            else None,
        },
    }


def _fetch_twse_mis_live_market_breadth(db: Session, market: str) -> dict | None:
    global _TWSE_MIS_BREADTH_CIRCUIT_FAILURES
    global _TWSE_MIS_BREADTH_CIRCUIT_OPEN_UNTIL

    normalized_market = str(market or "").strip().upper()
    if normalized_market not in {"TWSE", "TPEX"}:
        return None
    cached = _TWSE_MIS_LIVE_BREADTH_CACHE.get(normalized_market)
    if cached and monotonic() < float(cached["expires_at"]):
        payload = cached.get("payload")
        return payload if isinstance(payload, dict) else None

    with _TWSE_MIS_BREADTH_REFRESH_LOCK:
        cached = _TWSE_MIS_LIVE_BREADTH_CACHE.get(normalized_market)
        if cached and monotonic() < float(cached["expires_at"]):
            payload = cached.get("payload")
            return payload if isinstance(payload, dict) else None
        if monotonic() < _TWSE_MIS_BREADTH_CIRCUIT_OPEN_UNTIL:
            return _stale_twse_mis_breadth(
                normalized_market,
                circuit_open=True,
            )

        payload = _fetch_twse_mis_live_market_breadth_unguarded(
            db,
            normalized_market,
        )
        failed_batch_count = (
            int(payload.get("failed_batch_count") or 0)
            if isinstance(payload, dict)
            else 1
        )
        if payload is None or failed_batch_count > 0:
            _TWSE_MIS_BREADTH_CIRCUIT_FAILURES += 1
            if _TWSE_MIS_BREADTH_CIRCUIT_FAILURES >= TWSE_MIS_BREADTH_CIRCUIT_FAILURE_THRESHOLD:
                _TWSE_MIS_BREADTH_CIRCUIT_OPEN_UNTIL = (
                    monotonic() + TWSE_MIS_BREADTH_CIRCUIT_COOLDOWN_SECONDS
                )
            if payload is None:
                return _stale_twse_mis_breadth(
                    normalized_market,
                    circuit_open=monotonic() < _TWSE_MIS_BREADTH_CIRCUIT_OPEN_UNTIL,
                )
        else:
            _TWSE_MIS_BREADTH_CIRCUIT_FAILURES = 0
            _TWSE_MIS_BREADTH_CIRCUIT_OPEN_UNTIL = 0.0
        return payload


def _market_index_summary_cache_ttl(indices: list[dict]) -> int:
    for item in indices:
        breadth = item.get("breadth") if isinstance(item, dict) else None

        if not isinstance(breadth, dict):
            continue

        source = str(breadth.get("source") or "")

        if source.startswith("twse_mis"):
            return TWSE_MIS_LIVE_BREADTH_CACHE_TTL_SECONDS

    return CACHE_TTL_SECONDS


def _market_quote_breadth_from_rows(
    *,
    market: str,
    rows: list[dict],
    code_key: str,
    close_key: str,
    change_key: str,
    trade_value_key: str,
    date_key: str,
    source: str,
) -> dict | None:
    trade_date = _parse_trade_date(rows[0].get(date_key)) if rows else None
    advance_count = 0
    decline_count = 0
    unchanged_count = 0
    limit_up_count = 0
    limit_down_count = 0
    total_count = 0
    trade_value = sum(
        value
        for row in rows
        if isinstance(row, dict)
        for value in [_as_int(row.get(trade_value_key))]
        if value is not None
    )

    for row in rows:
        if _regular_stock_code(row.get(code_key)) is None:
            continue

        close = _as_float(row.get(close_key))
        change = _as_float(row.get(change_key))

        if change is None:
            continue

        total_count += 1

        if change > 0:
            advance_count += 1
        elif change < 0:
            decline_count += 1
        else:
            unchanged_count += 1

        limit_up, limit_down = _quote_limit_counts(close=close, change=change)
        limit_up_count += limit_up
        limit_down_count += limit_down

    if total_count == 0:
        return None

    return {
        "market": market,
        "scope": "full_market",
        "universe_definition": _market_breadth_universe_definition(
            "full_market",
            market,
        ),
        "label": _market_breadth_label(market, "full_market"),
        "trade_date": trade_date,
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "trade_value": trade_value,
        "source": source,
    }


def _twse_rwd_mi_index_url(trade_date: date) -> str:
    return (
        f"{TWSE_RWD_MI_INDEX_URL}?date={trade_date:%Y%m%d}"
        "&type=ALLBUT0999&response=json"
    )


def _find_twse_rwd_table(payload: dict, title_fragment: str) -> dict | None:
    tables = payload.get("tables") if isinstance(payload, dict) else None
    if not isinstance(tables, list):
        return None

    for table in tables:
        if not isinstance(table, dict):
            continue
        title = str(table.get("title") or "")
        if title_fragment in title:
            return table

    return None


def _fetch_twse_rwd_market_quote_breadth(trade_date: date | None = None) -> dict | None:
    requested_date = trade_date or datetime.now(TAIPEI_TZ).date()
    payload = _fetch_json(_twse_rwd_mi_index_url(requested_date))

    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return None

    payload_date = _parse_trade_date(payload.get("date")) or requested_date
    breadth_table = _find_twse_rwd_table(payload, "漲跌證券數合計")
    stats_table = _find_twse_rwd_table(payload, "大盤統計資訊")
    advance_count = decline_count = unchanged_count = None
    limit_up_count = limit_down_count = None
    trade_value = None

    if isinstance(breadth_table, dict):
        fields = breadth_table.get("fields") or []
        rows = breadth_table.get("data") or []
        stock_column = fields.index("股票") if "股票" in fields else 2

        for row in rows:
            if not isinstance(row, list) or len(row) <= stock_column:
                continue

            label = str(row[0] or "")
            count, limit_count = _count_with_limit(row[stock_column])
            if "上漲" in label:
                advance_count = count
                limit_up_count = limit_count
            elif "下跌" in label:
                decline_count = count
                limit_down_count = limit_count
            elif "持平" in label:
                unchanged_count = count

    if isinstance(stats_table, dict):
        for row in stats_table.get("data") or []:
            if not isinstance(row, list) or len(row) < 2:
                continue
            if str(row[0]).startswith("總計"):
                trade_value = _as_int(row[1])
                break

    if advance_count is None and decline_count is None and unchanged_count is None:
        return None

    total_count = sum(
        value
        for value in (advance_count, decline_count, unchanged_count)
        if value is not None
    )

    return {
        "market": "TWSE",
        "scope": "full_market",
        "universe_definition": _market_breadth_universe_definition(
            "full_market",
            "TWSE",
        ),
        "label": _market_breadth_label("TWSE", "full_market"),
        "trade_date": payload_date,
        "advance_count": advance_count or 0,
        "decline_count": decline_count or 0,
        "unchanged_count": unchanged_count or 0,
        "total_count": total_count,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "trade_value": trade_value,
        "source": "twse_rwd_mi_index",
    }


def _fetch_market_quote_breadth(market: str) -> dict | None:
    cached = _QUOTE_STATS_CACHE.get(market)

    if cached and monotonic() < float(cached["expires_at"]):
        payload = cached.get("payload")

        if isinstance(payload, dict):
            return payload

    if market == "TPEX":
        payload = _fetch_json(TPEX_DAILY_QUOTES_URL)
        rows = payload if isinstance(payload, list) else []
        result = _market_quote_breadth_from_rows(
            market=market,
            rows=rows,
            code_key="SecuritiesCompanyCode",
            close_key="Close",
            change_key="Change",
            trade_value_key="TransactionAmount",
            date_key="Date",
            source="tpex_openapi_mainboard_quotes",
        )
    else:
        try:
            result = _fetch_twse_rwd_market_quote_breadth()
        except Exception as exc:
            observe_provider_fallback(
                exc,
                operation="indices.twse_rwd_breadth_primary",
            )
            result = None

        if result is None:
            payload = _fetch_json(TWSE_DAILY_QUOTES_URL)
            rows = payload if isinstance(payload, list) else []
            result = _market_quote_breadth_from_rows(
                market=market,
                rows=rows,
                code_key="Code",
                close_key="ClosingPrice",
                change_key="Change",
                trade_value_key="TradeValue",
                date_key="Date",
                source="twse_openapi_stock_day_all",
            )

    if result is not None:
        _QUOTE_STATS_CACHE[market] = {
            "expires_at": monotonic() + CACHE_TTL_SECONDS,
            "payload": result,
        }

    return result


def _breadth_trade_date(payload: dict | None) -> date | None:
    if not isinstance(payload, dict):
        return None

    value = payload.get("trade_date")
    return value if isinstance(value, date) else _parse_trade_date(value)


def _is_plausible_market_breadth(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False

    market = str(payload.get("market") or "")
    minimum_count = 500 if market == "TWSE" else 250 if market == "TPEX" else 1
    total_count = _as_int(payload.get("total_count"))
    return total_count is not None and total_count >= minimum_count


def _resolve_market_breadth(
    db: Session,
    market: str,
    *,
    target_trade_date: date | None = None,
) -> dict | None:
    quote_breadth: dict | None = None

    try:
        quote_breadth = _fetch_market_quote_breadth(market)
    except Exception as exc:
        observe_provider_fallback(exc, operation="indices.market_quote_breadth")

    if (
        target_trade_date is not None
        and _breadth_trade_date(quote_breadth) == target_trade_date
        and _is_plausible_market_breadth(quote_breadth)
    ):
        return quote_breadth

    live_breadth: dict | None = None

    try:
        live_breadth = _fetch_twse_mis_live_market_breadth(db=db, market=market)
    except Exception as exc:
        observe_provider_fallback(exc, operation="indices.twse_mis_live_breadth")
        live_breadth = None

    if (
        target_trade_date is not None
        and _breadth_trade_date(live_breadth) == target_trade_date
        and _is_plausible_market_breadth(live_breadth)
    ):
        return live_breadth

    local_breadth = _latest_market_breadth(db=db, market=market)

    if target_trade_date is not None:
        if (
            _breadth_trade_date(local_breadth) == target_trade_date
            and _is_plausible_market_breadth(local_breadth)
        ):
            return local_breadth
        return None

    quote_date = _breadth_trade_date(quote_breadth)
    local_date = _breadth_trade_date(local_breadth)

    if quote_date is not None and (
        local_date is None or quote_date >= local_date
    ) and _is_plausible_market_breadth(quote_breadth):
        return quote_breadth

    if _is_plausible_market_breadth(live_breadth):
        return live_breadth

    if _is_plausible_market_breadth(local_breadth):
        return local_breadth

    return None


def _market_breadth_target_date(now: datetime | None = None) -> date:
    local_now = now or datetime.now(TAIPEI_TZ)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=TAIPEI_TZ)
    else:
        local_now = local_now.astimezone(TAIPEI_TZ)
    if is_taiwan_trading_day(local_now.date()) and local_now.time() >= time(8, 55):
        return local_now.date()
    return expected_daily_price_date(now=local_now)


def _fetch_recent_index_trade_values(market: str) -> dict[date, int]:
    index_id = "TPEX" if market == "TPEX" else "TAIEX"
    return {
        item["trade_date"]: item["trade_value"]
        for item in _fetch_recent_market_index_daily_stats(index_id=index_id, market=market)
        if item.get("trade_value") is not None
    }


def _twse_market_daily_history_url(month_start: date) -> str:
    return f"{TWSE_MARKET_DAILY_HISTORY_URL}?date={month_start:%Y%m%d}&response=json"


def _fetch_twse_market_daily_stats_for_month(month_start: date) -> tuple[list[dict], str]:
    url = _twse_market_daily_history_url(month_start)
    payload = _fetch_json(url)
    return _parse_twse_market_daily_history_rows(payload), url


def _tpex_market_highlight_url(trade_date: date) -> str:
    return (
        f"{TPEX_MARKET_HIGHLIGHT_URL}"
        f"?date={trade_date:%Y/%m/%d}&response=json"
    )


def _fetch_tpex_market_daily_stat_for_date(
    trade_date: date,
) -> tuple[list[dict], str]:
    payload = tpex.fetch_market_highlight_payload(
        trade_date,
        timeout_seconds=20,
    )
    return (
        _parse_tpex_market_highlight_rows(
            payload,
            expected_trade_date=trade_date,
        ),
        _tpex_market_highlight_url(trade_date),
    )


def _fetch_recent_market_index_daily_stats(index_id: str, market: str) -> list[dict]:
    if market == "TPEX":
        payload = _fetch_json(TPEX_DAILY_INDEX_URL)
        return _parse_tpex_market_daily_rows(payload)

    payload = _fetch_json(TWSE_MARKET_DAILY_URL)
    return _parse_twse_market_daily_history_rows(payload)


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _fetch_twse_index_daily_ohlc_for_month(
    month_start: date,
) -> dict[date, dict]:
    normalized_month = _month_start(month_start)
    cache_key = normalized_month.isoformat()
    cached = _TWSE_INDEX_DAILY_OHLC_CACHE.get(cache_key)

    if cached and monotonic() < float(cached["expires_at"]):
        cached_rows = cached.get("rows")
        if isinstance(cached_rows, dict):
            return {
                trade_date: dict(values)
                for trade_date, values in cached_rows.items()
                if isinstance(trade_date, date) and isinstance(values, dict)
            }

    payload = twse.fetch_index_daily_ohlc_payload(
        normalized_month,
        timeout_seconds=20,
        request=http_get,
    )
    rows = {
        row["trade_date"]: row
        for row in _parse_twse_index_daily_ohlc_rows(payload)
        if (
            isinstance(row.get("trade_date"), date)
            and _month_start(row["trade_date"]) == normalized_month
        )
    }
    if not rows:
        raise ValueError(
            "TWSE official daily index OHLC payload has no rows for "
            f"{normalized_month:%Y-%m}."
        )

    _TWSE_INDEX_DAILY_OHLC_CACHE[cache_key] = {
        "expires_at": monotonic() + INDEX_LIST_CACHE_TTL_SECONDS,
        "rows": rows,
    }
    return {trade_date: dict(values) for trade_date, values in rows.items()}


def _month_starts_between(from_date: date, to_date: date) -> list[date]:
    current = _month_start(from_date)
    end_month = _month_start(to_date)
    months: list[date] = []

    while current <= end_month:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return months


def _persist_market_index_daily_stats(
    db: Session,
    *,
    index_id: str,
    market: str,
    rows: list[dict],
    source: str,
    source_url: str | None,
) -> dict:
    inserted_count = 0
    updated_count = 0

    for row in rows:
        trade_date = row.get("trade_date")
        if not isinstance(trade_date, date):
            continue

        values = {
            "market": market,
            "trade_volume": row.get("trade_volume"),
            "trade_value": row.get("trade_value"),
            "transaction_count": row.get("transaction_count"),
            "close_value": row.get("close_value"),
            "price_change": row.get("price_change"),
            "source": source,
            "source_url": source_url,
        }
        existing = (
            db.query(MarketIndexDailyStat)
            .filter(MarketIndexDailyStat.index_id == index_id)
            .filter(MarketIndexDailyStat.trade_date == trade_date)
            .first()
        )

        if existing is None:
            db.add(
                MarketIndexDailyStat(
                    index_id=index_id,
                    trade_date=trade_date,
                    **values,
                )
            )
            inserted_count += 1
            continue

        changed = False
        for key, value in values.items():
            if getattr(existing, key) != value:
                setattr(existing, key, value)
                changed = True

        if changed:
            updated_count += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def _existing_index_stat_months(
    db: Session,
    *,
    index_id: str,
    from_date: date,
    to_date: date,
) -> set[date]:
    rows = (
        db.query(MarketIndexDailyStat.trade_date)
        .filter(MarketIndexDailyStat.index_id == index_id)
        .filter(MarketIndexDailyStat.trade_date >= from_date)
        .filter(MarketIndexDailyStat.trade_date <= to_date)
        .all()
    )
    return {_month_start(row.trade_date) for row in rows}


def _existing_index_stat_dates(
    db: Session,
    *,
    index_id: str,
    from_date: date,
    to_date: date,
) -> set[date]:
    rows = (
        db.query(MarketIndexDailyStat.trade_date)
        .filter(MarketIndexDailyStat.index_id == index_id)
        .filter(MarketIndexDailyStat.trade_date >= from_date)
        .filter(MarketIndexDailyStat.trade_date <= to_date)
        .all()
    )
    return {row.trade_date for row in rows}


def _tpex_market_highlight_candidate_dates(
    *,
    from_date: date,
    to_date: date,
) -> list[date]:
    current = max(from_date, TPEX_MARKET_HIGHLIGHT_START_DATE)
    dates: list[date] = []
    while current <= to_date:
        if is_taiwan_trading_day(current):
            dates.append(current)
        current += timedelta(days=1)
    return dates


def _fetch_and_persist_tpex_market_daily_history(
    db: Session,
    *,
    index_id: str,
    market: str,
    from_date: date,
    to_date: date,
) -> dict:
    candidates = _tpex_market_highlight_candidate_dates(
        from_date=from_date,
        to_date=to_date,
    )
    if len(candidates) > MAX_TPEX_HISTORY_FETCH_DATES:
        raise ValueError(
            "TPEX historical daily-stat refresh exceeds the bounded limit of "
            f"{MAX_TPEX_HISTORY_FETCH_DATES} candidate trading dates."
        )

    existing_dates = _existing_index_stat_dates(
        db=db,
        index_id=index_id,
        from_date=from_date,
        to_date=to_date,
    )
    fetch_dates = [value for value in candidates if value not in existing_dates]
    pending_rows: list[dict] = []
    errors: list[dict] = []
    successful_months: set[date] = set()
    inserted_count = 0
    updated_count = 0
    completed_count = 0

    with ThreadPoolExecutor(max_workers=MAX_INDEX_STAT_FETCH_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_tpex_market_daily_stat_for_date, value): value
            for value in fetch_dates
        }
        for future in as_completed(futures):
            trade_date = futures[future]
            try:
                rows, _source_url = future.result()
                successful_months.add(_month_start(trade_date))
                if rows:
                    pending_rows.extend(rows)
                    if len(pending_rows) >= TPEX_HISTORY_PERSIST_BATCH_SIZE:
                        counts = _persist_market_index_daily_stats(
                            db=db,
                            index_id=index_id,
                            market=market,
                            rows=pending_rows,
                            source="tpex_after_trading_highlight",
                            source_url=TPEX_MARKET_HIGHLIGHT_URL,
                        )
                        inserted_count += counts["inserted_count"]
                        updated_count += counts["updated_count"]
                        pending_rows = []
            except Exception as exc:
                errors.append(
                    {
                        "date": trade_date.isoformat(),
                        "error_message": str(exc),
                    }
                )
            finally:
                completed_count += 1
                if (
                    completed_count % TPEX_HISTORY_PERSIST_BATCH_SIZE == 0
                    or completed_count == len(fetch_dates)
                ):
                    logger.info(
                        "TPEX daily-stat backfill progress completed=%s/%s "
                        "inserted=%s updated=%s errors=%s",
                        completed_count,
                        len(fetch_dates),
                        inserted_count,
                        updated_count,
                        len(errors),
                    )

    if pending_rows:
        counts = _persist_market_index_daily_stats(
            db=db,
            index_id=index_id,
            market=market,
            rows=pending_rows,
            source="tpex_after_trading_highlight",
            source_url=TPEX_MARKET_HIGHLIGHT_URL,
        )
        inserted_count += counts["inserted_count"]
        updated_count += counts["updated_count"]

    requested_months = set(
        _month_starts_between(from_date=from_date, to_date=to_date)
    )
    fetch_months = {_month_start(value) for value in fetch_dates}
    return {
        "source": "tpex_after_trading_highlight",
        "fetched_month_count": len(successful_months),
        "skipped_existing_month_count": len(requested_months - fetch_months),
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "errors": errors,
    }


def _ensure_market_index_daily_stat_coverage(
    db: Session,
    *,
    index_id: str,
    market: str,
    from_date: date,
    to_date: date,
) -> dict | None:
    months = _month_starts_between(from_date=from_date, to_date=to_date)
    existing_months = _existing_index_stat_months(
        db=db,
        index_id=index_id,
        from_date=from_date,
        to_date=to_date,
    )
    missing_months = [month for month in months if month not in existing_months]
    fetch_months = list(missing_months)
    current_month = _month_start(datetime.now(TAIPEI_TZ).date())
    latest_requested_month = _month_start(to_date)
    if (
        index_id == "TAIEX"
        and latest_requested_month == current_month
        and latest_requested_month in months
        and latest_requested_month not in fetch_months
    ):
        fetch_months.append(latest_requested_month)

    result = {
        "status": "success",
        "index_id": index_id,
        "market": market,
        "source": None,
        "requested_month_count": len(months),
        "fetched_month_count": 0,
        "skipped_existing_month_count": len(months) - len(fetch_months),
        "inserted_count": 0,
        "updated_count": 0,
        "errors": [],
    }

    if index_id == "TPEX":
        history = _fetch_and_persist_tpex_market_daily_history(
            db=db,
            index_id=index_id,
            market=market,
            from_date=from_date,
            to_date=to_date,
        )
        result["source"] = history["source"]
        result["fetched_month_count"] += history["fetched_month_count"]
        result["skipped_existing_month_count"] = history[
            "skipped_existing_month_count"
        ]
        result["inserted_count"] += history["inserted_count"]
        result["updated_count"] += history["updated_count"]
        result["errors"].extend(history["errors"])

    if index_id == "TAIEX" and fetch_months:
        result["source"] = "twse_rwd_fmtqik"
        with ThreadPoolExecutor(max_workers=MAX_INDEX_STAT_FETCH_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_twse_market_daily_stats_for_month, month): month
                for month in fetch_months
            }

            for future in as_completed(futures):
                month = futures[future]
                try:
                    rows, source_url = future.result()
                    counts = _persist_market_index_daily_stats(
                        db=db,
                        index_id=index_id,
                        market=market,
                        rows=rows,
                        source="twse_rwd_fmtqik",
                        source_url=source_url,
                    )
                    result["fetched_month_count"] += 1
                    result["inserted_count"] += counts["inserted_count"]
                    result["updated_count"] += counts["updated_count"]
                except Exception as exc:
                    db.rollback()
                    result["errors"].append(
                        {
                            "month": month.strftime("%Y-%m"),
                            "error_message": str(exc),
                        }
                    )

    try:
        recent_rows = _fetch_recent_market_index_daily_stats(index_id=index_id, market=market)
        if recent_rows:
            recent_source = (
                "tpex_openapi_daily_trading_index"
                if market == "TPEX"
                else "twse_openapi_fmtqik"
            )
            counts = _persist_market_index_daily_stats(
                db=db,
                index_id=index_id,
                market=market,
                rows=recent_rows,
                source=recent_source,
                source_url=TPEX_DAILY_INDEX_URL if market == "TPEX" else TWSE_MARKET_DAILY_URL,
            )
            result["source"] = result["source"] or recent_source
            result["inserted_count"] += counts["inserted_count"]
            result["updated_count"] += counts["updated_count"]
    except Exception as exc:
        db.rollback()
        result["errors"].append(
            {
                "source": "recent_market_index_daily_stats",
                "error_message": str(exc),
            }
        )

    if result["errors"]:
        result["status"] = "partial_success" if result["fetched_month_count"] else "error"

    if (
        result["fetched_month_count"] == 0
        and result["inserted_count"] == 0
        and result["updated_count"] == 0
        and not result["errors"]
    ):
        return None

    result["message"] = (
        f"Index daily stats refreshed: fetched {result['fetched_month_count']} month(s), "
        f"inserted {result['inserted_count']}, updated {result['updated_count']}."
    )
    return result


def ensure_market_index_daily_stat_coverage(
    db: Session,
    *,
    index_id: str,
    market: str,
    from_date: date,
    to_date: date,
) -> dict | None:
    return _ensure_market_index_daily_stat_coverage(
        db=db,
        index_id=index_id,
        market=market,
        from_date=from_date,
        to_date=to_date,
    )


def _index_stat_period_key(value: date, timeframe: str) -> date:
    if timeframe == "weekly":
        return value - timedelta(days=value.weekday())

    if timeframe == "monthly":
        return _month_start(value)

    return value


def _index_stat_query_range(timeframe: str, from_date: date, to_date: date) -> tuple[date, date]:
    if timeframe == "weekly":
        return (
            _index_stat_period_key(from_date, timeframe),
            _index_stat_period_key(to_date, timeframe) + timedelta(days=6),
        )

    if timeframe == "monthly":
        start = _month_start(from_date)
        end_month = _month_start(to_date)
        if end_month.month == 12:
            next_month = date(end_month.year + 1, 1, 1)
        else:
            next_month = date(end_month.year, end_month.month + 1, 1)
        return start, next_month - timedelta(days=1)

    return from_date, to_date


def _add_nullable_sum(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current

    return value if current is None else current + value


def _load_market_index_stat_values(
    db: Session,
    *,
    index_id: str,
    timeframe: str,
    from_date: date,
    to_date: date,
) -> dict[date, dict]:
    rows = (
        db.query(MarketIndexDailyStat)
        .filter(MarketIndexDailyStat.index_id == index_id)
        .filter(MarketIndexDailyStat.trade_date >= from_date)
        .filter(MarketIndexDailyStat.trade_date <= to_date)
        .order_by(MarketIndexDailyStat.trade_date.asc())
        .all()
    )
    values_by_period: defaultdict[date, dict] = defaultdict(
        lambda: {
            "trade_volume": None,
            "trade_value": None,
            "transaction_count": None,
        }
    )

    for row in rows:
        key = _index_stat_period_key(row.trade_date, timeframe)
        values = values_by_period[key]
        values["trade_volume"] = _add_nullable_sum(values["trade_volume"], row.trade_volume)
        values["trade_value"] = _add_nullable_sum(values["trade_value"], row.trade_value)
        values["transaction_count"] = _add_nullable_sum(
            values["transaction_count"],
            row.transaction_count,
        )

    return dict(values_by_period)


def _apply_market_index_stat_values(
    points: list[dict],
    *,
    timeframe: str,
    values_by_period: dict[date, dict],
) -> None:
    for point in points:
        point_time = point.get("time")
        if not isinstance(point_time, date):
            continue

        values = values_by_period.get(_index_stat_period_key(point_time, timeframe))
        if values is None:
            continue

        if values.get("trade_volume") is not None:
            point["volume"] = values["trade_volume"]
        point["trade_value"] = values.get("trade_value")
        point["transaction_count"] = values.get("transaction_count")


def _latest_market_index_daily_stat(
    db: Session,
    *,
    index_id: str,
) -> MarketIndexDailyStat | None:
    return (
        db.query(MarketIndexDailyStat)
        .filter(MarketIndexDailyStat.index_id == index_id)
        .order_by(MarketIndexDailyStat.trade_date.desc())
        .first()
    )


def _market_index_daily_stats_after(
    db: Session,
    *,
    index_id: str,
    after_date: date | None,
    to_date: date,
) -> list[MarketIndexDailyStat]:
    query = (
        db.query(MarketIndexDailyStat)
        .filter(MarketIndexDailyStat.index_id == index_id)
        .filter(MarketIndexDailyStat.trade_date <= to_date)
        .filter(MarketIndexDailyStat.close_value.isnot(None))
        .order_by(MarketIndexDailyStat.trade_date.asc())
    )

    if after_date is not None:
        query = query.filter(MarketIndexDailyStat.trade_date > after_date)

    return query.all()


def _market_index_point_from_daily_stat(
    row: MarketIndexDailyStat,
    *,
    previous_close: float | None,
) -> dict | None:
    close = row.close_value

    if close is None:
        return None

    reference_close = previous_close
    if row.price_change is not None:
        reference_close = close - row.price_change

    open_value = reference_close if reference_close is not None else close
    high_candidates = [value for value in (open_value, close) if value is not None]
    high = max(high_candidates) if high_candidates else close
    low = min(high_candidates) if high_candidates else close

    return {
        "time": row.trade_date,
        "open": open_value,
        "high": high,
        "low": low,
        "close": close,
        "volume": row.trade_volume,
        "trade_value": row.trade_value,
        "transaction_count": row.transaction_count,
    }


def _market_index_point_from_daily_ohlc(
    row: MarketIndexDailyStat,
    ohlc: dict,
) -> dict | None:
    open_value = _as_float(ohlc.get("open"))
    high_value = _as_float(ohlc.get("high"))
    low_value = _as_float(ohlc.get("low"))
    close_value = _as_float(ohlc.get("close"))
    if (
        open_value is None
        or high_value is None
        or low_value is None
        or close_value is None
    ):
        return None
    if high_value < max(open_value, close_value):
        return None
    if low_value > min(open_value, close_value):
        return None

    return {
        "time": row.trade_date,
        "open": open_value,
        "high": high_value,
        "low": low_value,
        "close": close_value,
        "volume": row.trade_volume,
        "trade_value": row.trade_value,
        "transaction_count": row.transaction_count,
    }


def _append_official_market_index_daily_points(
    db: Session,
    points: list[dict],
    *,
    index_id: str,
    to_date: date,
) -> dict | None:
    latest_point_date = points[-1].get("time") if points else None
    latest_point_date = latest_point_date if isinstance(latest_point_date, date) else None
    previous_close = _as_float(points[-1].get("close")) if points else None
    existing_dates = {
        point["time"]
        for point in points
        if isinstance(point.get("time"), date)
    }

    rows = _market_index_daily_stats_after(
        db=db,
        index_id=index_id,
        after_date=latest_point_date,
        to_date=to_date,
    )
    if not rows:
        return None

    official_ohlc_by_date: dict[date, dict] = {}
    overlay_errors: list[str] = []
    bounded_months: set[date] = set()
    if index_id == "TAIEX":
        requested_months = sorted({_month_start(row.trade_date) for row in rows})
        bounded_months = set(
            requested_months[-MAX_TWSE_INDEX_DAILY_OHLC_OVERLAY_MONTHS:]
        )
        for month in sorted(bounded_months):
            try:
                official_ohlc_by_date.update(
                    _fetch_twse_index_daily_ohlc_for_month(month)
                )
            except Exception as exc:
                observe_provider_fallback(
                    exc,
                    operation="indices.official_daily_ohlc_overlay",
                )
                overlay_errors.append(f"{month:%Y-%m}: {exc}")

    merged_dates: list[date] = []
    missing_dates: list[date] = []
    for row in rows:
        if row.trade_date in existing_dates:
            continue

        if index_id == "TAIEX":
            point = _market_index_point_from_daily_ohlc(
                row,
                official_ohlc_by_date.get(row.trade_date) or {},
            )
        else:
            point = _market_index_point_from_daily_stat(
                row,
                previous_close=previous_close,
            )
        if point is None:
            missing_dates.append(row.trade_date)
            continue

        points.append(point)
        previous_close = point["close"]
        existing_dates.add(row.trade_date)
        merged_dates.append(row.trade_date)

    if index_id != "TAIEX":
        return None

    requested_dates = [row.trade_date for row in rows]
    status = (
        "success"
        if len(merged_dates) == len(requested_dates)
        else "partial"
        if merged_dates
        else "unavailable"
    )
    return {
        "status": status,
        "provider": twse.INDEX_DAILY_OHLC_PROVIDER,
        "source": "twse_indices_report_mi_5mins_hist",
        "source_url": TWSE_INDEX_DAILY_OHLC_URL,
        "requested_date_count": len(requested_dates),
        "merged_date_count": len(merged_dates),
        "merged_dates": [value.isoformat() for value in merged_dates],
        "missing_dates": [value.isoformat() for value in missing_dates],
        "bounded_months": [value.isoformat() for value in sorted(bounded_months)],
        "errors": overlay_errors,
    }


def _apply_latest_official_market_index_stat(
    db: Session,
    *,
    config: dict,
    payload: dict,
) -> None:
    index_id = str(config["index_id"])
    latest_stat = _latest_market_index_daily_stat(db, index_id=index_id)

    if latest_stat is None or latest_stat.close_value is None:
        return

    payload_time = payload.get("time")
    if isinstance(payload_time, date) and latest_stat.trade_date < payload_time:
        return

    previous_close = payload.get("previous_close")
    point = _market_index_point_from_daily_stat(
        latest_stat,
        previous_close=_as_float(previous_close),
    )

    if point is None:
        return

    try:
        official_ohlc = _fetch_twse_index_5s_ohlc(config, latest_stat.trade_date)
    except Exception as exc:
        observe_provider_fallback(exc, operation="indices.official_ohlc_overlay")
        official_ohlc = None

    if official_ohlc is not None:
        point.update(
            {
                "open": official_ohlc.get("open"),
                "high": official_ohlc.get("high"),
                "low": official_ohlc.get("low"),
                "close": latest_stat.close_value or official_ohlc.get("close"),
            }
        )

    points = payload.get("points")
    if isinstance(points, list):
        matching_point = next(
            (
                existing
                for existing in points
                if isinstance(existing, dict) and existing.get("time") == latest_stat.trade_date
            ),
            None,
        )
        if isinstance(matching_point, dict):
            matching_point.update(point)
        else:
            points.append(point)
            del points[:-90]

    close = point["close"]
    official_previous_close = (
        close - latest_stat.price_change
        if latest_stat.price_change is not None
        else _as_float(previous_close)
    )
    change = (
        close - official_previous_close
        if official_previous_close not in (None, 0)
        else latest_stat.price_change
    )
    change_pct = (
        (change / official_previous_close) * 100
        if change is not None and official_previous_close not in (None, 0)
        else None
    )
    ma20 = _moving_average(
        [
            _as_float(item.get("close"))
            for item in points
            if isinstance(points, list) and isinstance(item, dict)
        ],
        20,
    ) if isinstance(points, list) else payload.get("ma20")
    price_vs_ma20 = (
        ((close - ma20) / ma20) * 100
        if close is not None and ma20 not in (None, 0)
        else None
    )
    as_of = datetime.combine(latest_stat.trade_date, time(13, 30), tzinfo=TAIPEI_TZ)

    payload.update(
        {
            "source": f"{payload.get('source') or 'index_chart'}+market_index_daily_stat",
            "as_of": as_of,
            "time": latest_stat.trade_date,
            "open": point["open"],
            "high": point["high"],
            "low": point["low"],
            "close": close,
            "previous_close": official_previous_close,
            "change": change,
            "change_pct": change_pct,
            "volume": point["volume"],
            "estimated_volume": _estimate_session_volume(
                volume=point["volume"],
                as_of=as_of,
            ),
            "trade_value": point["trade_value"],
            "estimated_trade_value": _estimate_session_volume(
                volume=point["trade_value"],
                as_of=as_of,
            ),
            "ma20": ma20,
            "price_vs_ma20": price_vs_ma20,
        }
    )


def _index_range_for(timeframe: str, bars: int) -> str:
    if timeframe == "monthly":
        return "max"

    if timeframe == "weekly":
        return "10y" if bars <= 520 else "max"

    if bars <= 180:
        return "1y"
    if bars <= 520:
        return "2y"
    if bars <= 1300:
        return "5y"
    if bars <= 2600:
        return "10y"
    return "max"


def _estimate_session_volume(
    volume: int | None,
    as_of: datetime | None,
) -> int | None:
    if volume is None or as_of is None:
        return volume

    current_time = as_of.astimezone(TAIPEI_TZ)
    session_start = datetime.combine(current_time.date(), time(9, 0), tzinfo=TAIPEI_TZ)
    session_end = datetime.combine(current_time.date(), time(13, 30), tzinfo=TAIPEI_TZ)

    if current_time <= session_start or current_time >= session_end:
        return volume

    elapsed_seconds = max((current_time - session_start).total_seconds(), 60)
    session_seconds = (session_end - session_start).total_seconds()

    return int(volume * session_seconds / elapsed_seconds)


def _fetch_yahoo_index_points(
    config: dict,
    range_value: str,
    interval: str,
) -> tuple[list[dict], dict, timezone]:
    symbol = str(config["symbol"])
    payload = yahoo.fetch_index_chart_payload(
        symbol=symbol,
        range_value=range_value,
        interval=interval,
        timeout_seconds=20,
        request=http_get,
    )
    result = (payload.get("chart", {}).get("result") or [None])[0]

    if not result:
        raise ValueError("Yahoo chart payload has no result.")

    meta = result.get("meta") or {}
    quote_values = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    timestamps = result.get("timestamp") or []
    offset = int(meta.get("gmtoffset") or 28800)
    tz = timezone(timedelta(seconds=offset))
    opens = quote_values.get("open") or []
    highs = quote_values.get("high") or []
    lows = quote_values.get("low") or []
    closes = quote_values.get("close") or []
    volumes = quote_values.get("volume") or []
    points: list[dict] = []

    for index, timestamp in enumerate(timestamps):
        close = _as_float(_list_value(closes, index))

        if close is None:
            continue

        point_date = datetime.fromtimestamp(int(timestamp), tz=tz).date()
        points.append(
            {
                "time": point_date,
                "open": _as_float(_list_value(opens, index)),
                "high": _as_float(_list_value(highs, index)),
                "low": _as_float(_list_value(lows, index)),
                "close": close,
                "volume": _as_int(_list_value(volumes, index)),
                "trade_value": None,
                "transaction_count": None,
            }
        )

    return points, meta, tz


def _aggregate_monthly_points(points: list[dict]) -> list[dict]:
    monthly_points: list[dict] = []
    current_key: tuple[int, int] | None = None
    current_points: list[dict] = []

    def append_current_month() -> None:
        if not current_points:
            return

        first_point = current_points[0]
        last_point = current_points[-1]
        highs = [
            point["high"]
            for point in current_points
            if point.get("high") is not None
        ]
        lows = [
            point["low"]
            for point in current_points
            if point.get("low") is not None
        ]
        volumes = [
            point["volume"]
            for point in current_points
            if point.get("volume") is not None
        ]

        monthly_points.append(
            {
                "time": last_point["time"],
                "open": first_point["open"] or first_point["close"],
                "high": max(highs) if highs else last_point["close"],
                "low": min(lows) if lows else last_point["close"],
                "close": last_point["close"],
                "volume": sum(volumes) if volumes else None,
                "trade_value": None,
                "transaction_count": None,
            }
        )

    for point in points:
        point_time = point["time"]
        month_key = (point_time.year, point_time.month)

        if current_key is not None and month_key != current_key:
            append_current_month()
            current_points = []

        current_key = month_key
        current_points.append(point)

    append_current_month()
    return monthly_points


def _merge_monthly_points(point_sets: list[list[dict]]) -> list[dict]:
    merged: dict[tuple[int, int], dict] = {}

    for points in point_sets:
        for point in points:
            point_time = point["time"]
            merged[(point_time.year, point_time.month)] = point

    return [merged[key] for key in sorted(merged)]


def _fetch_yahoo_monthly_index_points(config: dict) -> list[dict]:
    monthly_point_sets: list[list[dict]] = []
    errors: list[Exception] = []

    # Yahoo's max-range payload for ^TWOII can stop at 2024. Merge it with a
    # recent 10-year daily payload so long monthly views keep older history
    # without losing current bars.
    for range_value in ("max", "10y"):
        try:
            daily_points, _meta, _tz = _fetch_yahoo_index_points(
                config=config,
                range_value=range_value,
                interval="1d",
            )
        except Exception as exc:
            errors.append(exc)
            continue

        monthly_point_sets.append(_aggregate_monthly_points(daily_points))

    if monthly_point_sets:
        return _merge_monthly_points(monthly_point_sets)

    raise errors[-1] if errors else ValueError("Yahoo chart payload has no monthly points.")


def _fetch_yahoo_index(config: dict) -> dict:
    symbol = str(config["symbol"])
    points, meta, tz = _fetch_yahoo_index_points(
        config=config,
        range_value="6mo",
        interval="1d",
    )
    closes_for_average = [point["close"] for point in points]
    latest_point = points[-1] if points else None
    previous_close = None

    if len(points) >= 2:
        previous_close = points[-2]["close"]
    else:
        previous_close = _as_float(meta.get("chartPreviousClose"))

    close = latest_point["close"] if latest_point else None
    change = (
        close - previous_close
        if close is not None and previous_close is not None
        else None
    )
    change_pct = (
        (change / previous_close) * 100
        if change is not None and previous_close not in (None, 0)
        else None
    )
    ma20 = _moving_average(closes_for_average, 20)
    price_vs_ma20 = (
        ((close - ma20) / ma20) * 100
        if close is not None and ma20 not in (None, 0)
        else None
    )
    regular_market_time = _as_int(meta.get("regularMarketTime"))
    as_of = (
        datetime.fromtimestamp(regular_market_time, tz=tz)
        if regular_market_time is not None
        else datetime.combine(latest_point["time"], datetime.min.time(), tzinfo=tz)
        if latest_point
        else None
    )
    latest_volume = latest_point["volume"] if latest_point else None

    return {
        "index_id": config["index_id"],
        "label": config["label"],
        "short_label": config["short_label"],
        "market": config["market"],
        "symbol": symbol,
        "source": "yahoo_finance_chart",
        "as_of": as_of,
        "time": latest_point["time"] if latest_point else None,
        "open": latest_point["open"] if latest_point else None,
        "high": latest_point["high"] if latest_point else None,
        "low": latest_point["low"] if latest_point else None,
        "close": close,
        "previous_close": previous_close,
        "change": change,
        "change_pct": change_pct,
        "volume": latest_volume,
        "estimated_volume": _estimate_session_volume(
            volume=latest_volume,
            as_of=as_of,
        ),
        "trade_value": None,
        "estimated_trade_value": None,
        "ma20": ma20,
        "price_vs_ma20": price_vs_ma20,
        "point_count": len(points),
        "points": points[-90:],
        "error_message": None,
    }


def _fetch_yahoo_index_intraday(config: dict) -> dict:
    symbol = str(config["symbol"])
    intraday_points: list[dict] = []
    payload = yahoo.fetch_index_chart_payload(
        symbol=symbol,
        range_value="1d",
        interval="1m",
        timeout_seconds=20,
        request=http_get,
    )
    result = (payload.get("chart", {}).get("result") or [None])[0]

    if not result:
        raise ValueError("Yahoo chart payload has no intraday result.")

    meta = result.get("meta") or {}
    quote_values = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    timestamps = result.get("timestamp") or []
    offset = int(meta.get("gmtoffset") or 28800)
    tz = timezone(timedelta(seconds=offset))
    opens = quote_values.get("open") or []
    highs = quote_values.get("high") or []
    lows = quote_values.get("low") or []
    closes = quote_values.get("close") or []
    volumes = quote_values.get("volume") or []

    for index, timestamp in enumerate(timestamps):
        close = _as_float(_list_value(closes, index))

        if close is None:
            continue

        intraday_points.append(
            {
                "time": datetime.fromtimestamp(int(timestamp), tz=tz).isoformat(),
                "price": close,
                "volume": _as_int(_list_value(volumes, index)),
                "open": _as_float(_list_value(opens, index)),
                "high": _as_float(_list_value(highs, index)),
                "low": _as_float(_list_value(lows, index)),
            }
        )

    return {
        "stock_id": config["index_id"],
        "symbol": symbol,
        "source": "yahoo_finance_chart",
        "provider": "yahoo_chart",
        "interval": "1m",
        "trade_date": (
            intraday_points[-1]["time"][:10] if intraday_points else None
        ),
        "coverage_status": "available" if len(intraday_points) > 1 else "partial",
        "is_partial": len(intraday_points) <= 1,
        "volume_unit": None,
        "volume_semantics": "provider_index_volume_not_market_trade_value",
        "previous_close": _as_float(meta.get("chartPreviousClose"))
        or _as_float(meta.get("regularMarketPreviousClose")),
        "point_count": len(intraday_points),
        "points": intraday_points,
    }


def _fetch_twse_index_5s_intraday(
    config: dict,
    *,
    trade_date: date | None = None,
) -> dict:
    index_id = str(config["index_id"]).upper()
    field_name = TWSE_INDEX_5S_FIELD_BY_INDEX_ID.get(index_id)

    if not field_name:
        raise ValueError(f"Official 5-second index series is not configured for {index_id}.")

    requested_date = trade_date or datetime.now(TAIPEI_TZ).date()
    cache_key = f"{index_id}:{requested_date.isoformat()}"
    cached = _TWSE_INDEX_5S_CACHE.get(cache_key)

    if cached and monotonic() < float(cached["expires_at"]):
        payload = cached.get("payload")

        if isinstance(payload, dict):
            return payload

    if index_id == "TAIEX":
        raw_payload = twse.fetch_index_5s_payload(
            requested_date,
            timeout_seconds=20,
            request=http_get,
        )
        if not isinstance(raw_payload, dict) or raw_payload.get("stat") != "OK":
            raise ValueError("TWSE 5-second index payload is unavailable.")
        fields = raw_payload.get("fields") or []
        rows = raw_payload.get("data") or []
        source = "twse_index_5s"
        provider = twse.INDEX_5S_PROVIDER
        release_timing = "session"
    else:
        raw_payload = tpex.fetch_index_5s_payload(
            requested_date,
            timeout_seconds=20,
            request=http_get,
        )
        if (
            not isinstance(raw_payload, dict)
            or str(raw_payload.get("stat") or "").lower() != "ok"
        ):
            raise ValueError("TPEX 5-second post-close index payload is unavailable.")
        table = next(
            (
                item
                for item in raw_payload.get("tables") or []
                if isinstance(item, dict)
                and field_name in (item.get("fields") or [])
                and isinstance(item.get("data"), list)
            ),
            None,
        )
        if table is None:
            raise ValueError("TPEX 5-second post-close index table is unavailable.")
        fields = table.get("fields") or []
        rows = table.get("data") or []
        source = "tpex_index_5s"
        provider = tpex.INDEX_5S_PROVIDER
        release_timing = "post_close"

    if field_name not in fields:
        raise ValueError(f"Official 5-second index field '{field_name}' not found.")

    value_index = fields.index(field_name)
    parsed_payload_date = _parse_trade_date(raw_payload.get("date"))
    if parsed_payload_date is not None and parsed_payload_date != requested_date:
        raise ValueError(
            "Official 5-second index payload returned "
            f"{parsed_payload_date.isoformat()} for requested "
            f"{requested_date.isoformat()}."
        )
    payload_date = parsed_payload_date or requested_date
    points: list[dict] = []
    closing_summary_value: float | None = None

    for row in rows:
        if not isinstance(row, list) or len(row) <= value_index:
            continue

        raw_time = str(row[0]).strip()
        if raw_time == "99:99:99":
            closing_summary_value = _as_float(row[value_index])
            continue

        parts = raw_time.split(":")
        if len(parts) != 3:
            continue

        try:
            point_time = datetime.combine(
                payload_date,
                time(int(parts[0]), int(parts[1]), int(parts[2])),
                tzinfo=TAIPEI_TZ,
            )
        except ValueError:
            continue

        price = _as_float(row[value_index])
        if price is None:
            continue

        points.append(
            {
                "time": point_time.isoformat(),
                "price": price,
                "volume": None,
                "open": price,
                "high": price,
                "low": price,
            }
        )

    if not points:
        raise ValueError("Official 5-second index payload has no usable points.")

    latest_point_time = _point_datetime(points[-1])
    session_finalized = (
        closing_summary_value is not None
        if index_id == "TPEX"
        else (
            latest_point_time is not None
            and latest_point_time.astimezone(TAIPEI_TZ).time()
            >= TAIWAN_INDEX_SESSION_CLOSE_TIME
        )
    )

    payload = {
        "stock_id": config["index_id"],
        "symbol": config["symbol"],
        "source": source,
        "source_provenance": {
            "provider": provider,
            "resource": "index_intraday",
            "official": True,
            "release_timing": release_timing,
            "trade_date": payload_date.isoformat(),
            "raw_row_count": len(rows),
            "usable_point_count": len(points),
            "closing_summary_value": closing_summary_value,
            "closing_summary_time": (
                "provider_sentinel_99:99:99"
                if closing_summary_value is not None
                else None
            ),
        },
        "provider": provider,
        "interval": "5s",
        "trade_date": payload_date.isoformat(),
        "coverage_status": (
            "post_close_final_series"
            if index_id == "TPEX" and session_finalized
            else "current_session_series"
            if session_finalized
            else "current_session_partial"
        ),
        "is_partial": not session_finalized,
        "volume_unit": None,
        "volume_semantics": "not_provided_for_cash_index",
        "previous_close": points[0]["price"],
        "point_count": len(points),
        "points": points,
    }
    _TWSE_INDEX_5S_CACHE[cache_key] = {
        "expires_at": monotonic() + CACHE_TTL_SECONDS,
        "payload": payload,
    }
    return payload


def _fetch_twse_index_5s_ohlc(config: dict, trade_date: date) -> dict | None:
    payload = _fetch_twse_index_5s_intraday(config, trade_date=trade_date)
    points = payload.get("points") if isinstance(payload, dict) else None

    if not isinstance(points, list) or not points:
        return None

    prices = [
        _as_float(point.get("price"))
        for point in points
        if isinstance(point, dict) and point.get("price") is not None
    ]

    if not prices:
        return None

    return {
        "open": prices[0],
        "high": max(prices),
        "low": min(prices),
        "close": prices[-1],
    }


def _build_mis_snapshot_time(date_text: str | None, time_text: str | None) -> str | None:
    if not date_text or not time_text:
        return None

    try:
        if len(date_text) == 8 and date_text.isdigit():
            snapshot_date = date(
                int(date_text[:4]),
                int(date_text[4:6]),
                int(date_text[6:8]),
            )
        else:
            parsed_date = _parse_trade_date(date_text)
            if parsed_date is None:
                return None
            snapshot_date = parsed_date

        parts = [int(part) for part in str(time_text).split(":")]
        if len(parts) != 3:
            return None
        return datetime.combine(
            snapshot_date,
            time(parts[0], parts[1], parts[2]),
            tzinfo=TAIPEI_TZ,
        ).isoformat()
    except (TypeError, ValueError):
        return None


def _point_datetime(point: dict) -> datetime | None:
    point_time = point.get("time")
    if not point_time:
        return None

    try:
        return datetime.fromisoformat(str(point_time))
    except ValueError:
        return None


def _apply_latest_official_index_snapshot(
    *,
    config: dict,
    payload: dict,
    now: datetime | None = None,
) -> bool:
    index_id = str(config.get("index_id") or "").upper()
    if index_id not in TWSE_INDEX_5S_FIELD_BY_INDEX_ID:
        return False

    local_now = now or datetime.now(TAIPEI_TZ)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=TAIPEI_TZ)
    else:
        local_now = local_now.astimezone(TAIPEI_TZ)
    payload_trade_date = _parse_trade_date(payload.get("time"))
    target_trade_date = (
        local_now.date()
        if is_taiwan_trading_day(local_now.date()) and local_now.time() >= time(8, 55)
        else payload_trade_date
    )
    if target_trade_date is None:
        return False

    official = _fetch_twse_index_5s_intraday(
        config,
        trade_date=target_trade_date,
    )
    raw_points = official.get("points") if isinstance(official, dict) else None
    timestamped_points = sorted(
        (
            (point_time, point)
            for point in raw_points or []
            if isinstance(point, dict)
            for point_time in [_point_datetime(point)]
            if point_time is not None and _as_float(point.get("price")) is not None
        ),
        key=lambda item: item[0],
    )
    if not timestamped_points:
        return False

    latest_as_of, latest_point = timestamped_points[-1]
    if latest_as_of.tzinfo is None:
        latest_as_of = latest_as_of.replace(tzinfo=TAIPEI_TZ)
    else:
        latest_as_of = latest_as_of.astimezone(TAIPEI_TZ)
    if latest_as_of.date() != target_trade_date:
        return False

    current_as_of = _summary_payload_as_of(payload)
    if current_as_of is not None and latest_as_of <= current_as_of.astimezone(TAIPEI_TZ):
        return False

    session_points = timestamped_points[1:] if len(timestamped_points) > 1 else timestamped_points
    session_prices = [
        price
        for _, point in session_points
        for price in [_as_float(point.get("price"))]
        if price is not None
    ]
    if not session_prices:
        return False

    close = _as_float(latest_point.get("price"))
    if close is None:
        return False
    previous_close = _as_float(official.get("previous_close")) or _as_float(
        payload.get("previous_close")
    )
    high_candidates = [
        value
        for value in (_as_float(payload.get("high")), max(session_prices))
        if value is not None
    ]
    low_candidates = [
        value
        for value in (_as_float(payload.get("low")), min(session_prices))
        if value is not None
    ]
    high = max(high_candidates) if high_candidates else close
    low = min(low_candidates) if low_candidates else close
    change = close - previous_close if previous_close is not None else _as_float(payload.get("change"))
    change_pct = (
        (change / previous_close) * 100
        if change is not None and previous_close not in (None, 0)
        else None
    )

    points = payload.get("points")
    if isinstance(points, list):
        daily_point = next(
            (
                point
                for point in points
                if isinstance(point, dict)
                and _parse_trade_date(point.get("time")) == target_trade_date
            ),
            None,
        )
        snapshot_point = {
            "time": target_trade_date,
            "open": _as_float(payload.get("open")) or session_prices[0],
            "high": high,
            "low": low,
            "close": close,
            "volume": payload.get("volume"),
            "trade_value": payload.get("trade_value"),
            "transaction_count": (
                daily_point.get("transaction_count")
                if isinstance(daily_point, dict)
                else None
            ),
        }
        if isinstance(daily_point, dict):
            daily_point.update(snapshot_point)
        else:
            points.append(snapshot_point)
            del points[:-90]

    ma20 = (
        _moving_average(
            [
                _as_float(point.get("close"))
                for point in points
                if isinstance(point, dict)
            ],
            20,
        )
        if isinstance(points, list)
        else payload.get("ma20")
    )
    price_vs_ma20 = (
        ((close - ma20) / ma20) * 100
        if ma20 not in (None, 0)
        else None
    )
    source = str(payload.get("source") or "index_chart")
    official_snapshot_source = (
        f"{str(official.get('source') or 'official_index_5s')}_snapshot"
    )
    if official_snapshot_source not in source:
        source = f"{source}+{official_snapshot_source}"

    payload.update(
        {
            "source": source,
            "as_of": latest_as_of,
            "time": target_trade_date,
            "high": high,
            "low": low,
            "close": close,
            "previous_close": previous_close,
            "change": change,
            "change_pct": change_pct,
            "estimated_volume": _estimate_session_volume(
                volume=payload.get("volume"),
                as_of=latest_as_of,
            ),
            "ma20": ma20,
            "price_vs_ma20": price_vs_ma20,
            "point_count": len(points) if isinstance(points, list) else payload.get("point_count"),
        }
    )
    return True


def _point_time_key(point: dict) -> tuple[str, str] | None:
    parsed = _point_datetime(point)
    if parsed is None:
        return None

    return parsed.strftime("%Y%m%d"), parsed.strftime("%H:%M:%S")


def _fetch_mis_index_message(config: dict) -> dict | None:
    channel = str(config.get("mis_channel") or "").strip()
    if not channel:
        return None

    return twse_mis.fetch_index_message(
        channel,
        target=str(config.get("index_id") or config.get("symbol") or channel),
        timeout_seconds=20,
        request=http_get,
    )


def _fetch_mis_index_intraday(config: dict) -> dict:
    message = _fetch_mis_index_message(config)
    symbol = str(config["symbol"])

    if not message:
        return {
            "stock_id": config["index_id"],
            "symbol": symbol,
            "source": "twse_mis_index_snapshot",
            "provider": "twse_mis",
            "interval": "snapshot",
            "coverage_status": "missing",
            "is_partial": True,
            "volume_unit": None,
            "volume_semantics": "not_provided_for_cash_index",
            "previous_close": None,
            "point_count": 0,
            "points": [],
        }

    latest_time = _build_mis_snapshot_time(message.get("d"), message.get("t") or message.get("%"))
    price = _as_float(message.get("z"))
    if latest_time is None or price is None:
        return {
            "stock_id": config["index_id"],
            "symbol": symbol,
            "source": "twse_mis_index_snapshot",
            "provider": "twse_mis",
            "interval": "snapshot",
            "coverage_status": "missing",
            "is_partial": True,
            "volume_unit": None,
            "volume_semantics": "not_provided_for_cash_index",
            "previous_close": _as_float(message.get("y")),
            "point_count": 0,
            "points": [],
        }

    point = {
        "time": latest_time,
        "price": price,
        "volume": _as_int(message.get("v") or message.get("m")),
        "open": _as_float(message.get("o")) or price,
        "high": _as_float(message.get("h")) or price,
        "low": _as_float(message.get("l")) or price,
    }

    return {
        "stock_id": config["index_id"],
        "symbol": symbol,
        "source": "twse_mis_index_snapshot",
        "provider": "twse_mis",
        "interval": "snapshot",
        "trade_date": latest_time[:10],
        "coverage_status": "single_snapshot",
        "is_partial": True,
        "volume_unit": None,
        "volume_semantics": "snapshot_provider_value_not_market_trade_value",
        "previous_close": _as_float(message.get("y")),
        "point_count": 1,
        "points": [point],
    }


def _merge_index_intraday_snapshot(base: dict, snapshot: dict) -> dict:
    snapshot_points = snapshot.get("points") or []
    if not snapshot_points:
        return base

    merged = {
        **base,
        "previous_close": snapshot.get("previous_close") or base.get("previous_close"),
        "points": [dict(point) for point in base.get("points") or []],
    }
    snapshot_point = dict(snapshot_points[-1])
    snapshot_time = _point_datetime(snapshot_point)
    base_times = [
        point_time
        for point in merged["points"]
        for point_time in [_point_datetime(point)]
        if point_time is not None
    ]
    latest_base_time = max(base_times, default=None)
    if (
        snapshot_time is not None
        and latest_base_time is not None
        and snapshot_time < latest_base_time
    ):
        return base

    snapshot_key = _point_time_key(snapshot_point)
    replaced = False

    if snapshot_key is not None:
        for index, point in enumerate(merged["points"]):
            if _point_time_key(point) == snapshot_key:
                merged["points"][index] = snapshot_point
                replaced = True
                break

    if not replaced:
        merged["points"].append(snapshot_point)
        merged["points"].sort(key=lambda item: str(item.get("time") or ""))

    if snapshot_point.get("volume") is not None:
        snapshot_point["provider_volume_unit"] = "provider_units"
        snapshot_point["volume_status"] = "provider_specific"
        merged["volume_unit"] = "provider_units"
        merged["provider_volume_unit"] = "provider_units"
        merged["canonical_volume_unit"] = None
        merged["volume_status"] = "provider_specific"
        merged["volume_semantics"] = (
            "snapshot_provider_value_not_market_trade_value"
        )

    merged["point_count"] = len(merged["points"])
    merged["source"] = (
        "yahoo_finance_chart_twse_mis_snapshot"
        if base.get("source") == "yahoo_finance_chart"
        else f"{base.get('source') or 'intraday'}_twse_mis_snapshot"
    )
    return merged


def _index_intraday_fallback_from_list(config: dict) -> dict | None:
    if config["market"] == "TPEX":
        items = _fetch_tpex_index_list()
        source = "tpex_openapi_daily_trading_index"
    else:
        items = _fetch_twse_index_list()
        source = "twse_openapi_mi_index"

    item = items[0] if items else None

    if item is None or item.get("close") is None:
        return None

    close = item["close"]
    change = item.get("change")
    previous_close = (
        close - change
        if close is not None and change is not None
        else None
    )
    trade_date = item.get("trade_date") or date.today()
    point_time = datetime.combine(trade_date, time(13, 30), tzinfo=TAIPEI_TZ)

    return {
        "stock_id": config["index_id"],
        "symbol": config["symbol"],
        "source": source,
        "provider": source,
        "interval": "snapshot",
        "trade_date": trade_date.isoformat(),
        "coverage_status": "single_official_close_snapshot",
        "is_partial": True,
        "volume_unit": None,
        "volume_semantics": "not_provided_for_cash_index",
        "previous_close": previous_close,
        "point_count": 1,
        "points": [
            {
                "time": point_time.isoformat(),
                "price": close,
                "volume": None,
                "open": close,
                "high": close,
                "low": close,
            }
        ],
    }


def _unavailable_index(config: dict, error: Exception) -> dict:
    return {
        "index_id": config["index_id"],
        "label": config["label"],
        "short_label": config["short_label"],
        "market": config["market"],
        "symbol": config["symbol"],
        "source": "unavailable",
        "as_of": None,
        "time": None,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "previous_close": None,
        "change": None,
        "change_pct": None,
        "volume": None,
        "estimated_volume": None,
        "trade_value": None,
        "estimated_trade_value": None,
        "ma20": None,
        "price_vs_ma20": None,
        "point_count": 0,
        "points": [],
        "error_message": str(error),
    }


def _twse_index_display_name(name: str) -> str:
    if name == "發行量加權股價指數":
        return "加權指數"

    if name.endswith("類指數"):
        return name.removesuffix("類指數")

    return name


def _include_twse_index_name(name: str) -> bool:
    if not name or "報酬" in name:
        return False

    return name == "發行量加權股價指數" or name.endswith("類指數")


def _fetch_twse_index_list() -> list[dict]:
    payload = _fetch_json(TWSE_INDEX_LIST_URL)
    rows = payload if isinstance(payload, list) else []
    items: list[dict] = []

    for row in rows:
        name = str(row.get("指數") or "").strip()

        if not _include_twse_index_name(name):
            continue

        change = _signed_change(row.get("漲跌"), row.get("漲跌點數"))
        change_pct = _signed_change(row.get("漲跌"), row.get("漲跌百分比"))
        items.append(
            {
                "market": "TWSE",
                "name": _twse_index_display_name(name),
                "close": _as_float(row.get("收盤指數")),
                "change": change,
                "change_pct": change_pct,
                "trade_date": _parse_trade_date(row.get("日期")),
            }
        )

    return items


def _fetch_tpex_index_list() -> list[dict]:
    payload = _fetch_json(TPEX_DAILY_INDEX_URL)
    rows = payload if isinstance(payload, list) else []
    dated_rows = [
        (_parse_trade_date(row.get("Date")), row)
        for row in rows
        if isinstance(row, dict)
    ]
    dated_rows = [(trade_date, row) for trade_date, row in dated_rows if trade_date]
    latest_row = max(dated_rows, key=lambda item: item[0])[1] if dated_rows else None

    if latest_row is None:
        return []

    close = _as_float(latest_row.get("TPExIndex"))
    change = _as_float(latest_row.get("Change"))
    change_pct = None

    if close is not None and change is not None:
        previous_close = close - change

        if previous_close != 0:
            change_pct = (change / previous_close) * 100

    return [
        {
            "market": "TPEX",
            "name": "櫃買指數",
            "close": close,
            "change": change,
            "change_pct": change_pct,
            "trade_date": _parse_trade_date(latest_row.get("Date")),
        }
    ]


def get_market_index_list(market: str = "TWSE", limit: int = 80) -> dict:
    normalized_market = market.upper()

    if normalized_market not in {"TWSE", "TPEX"}:
        raise ValueError("market must be one of: TWSE, TPEX.")

    if limit <= 0:
        raise ValueError("limit must be greater than 0.")

    cache_key = normalized_market
    cached = _INDEX_LIST_CACHE.get(cache_key)

    if cached and monotonic() < float(cached["expires_at"]):
        cached_items = cached.get("items")

        if isinstance(cached_items, list):
            items = cached_items[:limit]
            return {
                "market": normalized_market,
                "source": str(cached["source"]),
                "as_of": cached["as_of"],
                "count": len(items),
                "items": items,
            }

    if normalized_market == "TPEX":
        source = "tpex_openapi_daily_trading_index"
        items = _fetch_tpex_index_list()
    else:
        source = "twse_openapi_mi_index"
        items = _fetch_twse_index_list()

    ranked_items = [
        {
            "rank": index + 1,
            **item,
        }
        for index, item in enumerate(items)
    ]
    _INDEX_LIST_CACHE[cache_key] = {
        "expires_at": monotonic() + INDEX_LIST_CACHE_TTL_SECONDS,
        "source": source,
        "as_of": datetime.now(TAIPEI_TZ),
        "items": ranked_items,
    }
    selected_items = ranked_items[:limit]

    return {
        "market": normalized_market,
        "source": source,
        "as_of": datetime.now(TAIPEI_TZ),
        "count": len(selected_items),
        "items": selected_items,
    }


def _finalize_index_intraday_contract(payload: dict) -> dict:
    points = [
        dict(point)
        for point in payload.get("points") or []
        if isinstance(point, dict)
    ]
    if not points:
        return {
            **payload,
            "bar_contract_version": "tw.intraday.bars.v2",
            "point_count": 0,
            "points": [],
            "bar_type_counts": {},
            "partial_bar_count": 0,
            "finalized_bar_count": 0,
            "indicator_eligible_count": 0,
            "post_close_summary_count": 0,
        }

    # Keep bar classification aligned with stock intraday semantics while
    # preserving the index provider's explicit no-volume contract.
    from app.market.intraday import _enrich_intraday_contract

    for point in points:
        point_time = _point_datetime(point)
        if point_time is None:
            continue
        local_clock = point_time.astimezone(TAIPEI_TZ).time().replace(
            tzinfo=None
        )
        if local_clock > time(13, 30):
            point["bar_type"] = "post_close_summary"
            point["source_event_type"] = "post_close_confirmation"

    enriched, _ = _enrich_intraday_contract(
        points,
        interval=str(payload.get("interval") or "1m"),
        source=str(payload.get("source") or "market_index_intraday"),
    )
    bar_type_counts: dict[str, int] = {}
    for raw_point, point in zip(points, enriched, strict=False):
        bar_type = str(point.get("bar_type") or "provider_irregular")
        bar_type_counts[bar_type] = bar_type_counts.get(bar_type, 0) + 1
        if raw_point.get("volume") is None:
            for key in (
                "volume_shares",
                "volume_lots",
                "canonical_volume_unit",
                "provider_volume_unit",
                "approx_trade_value",
            ):
                point.pop(key, None)
            point["volume_status"] = "not_provided"
            point["trade_value_status"] = "not_provided"

    return {
        **payload,
        "bar_contract_version": "tw.intraday.bars.v2",
        "point_count": len(enriched),
        "points": enriched,
        "bar_type_counts": bar_type_counts,
        "partial_bar_count": sum(
            1 for point in enriched if point.get("is_partial") is True
        ),
        "finalized_bar_count": sum(
            1 for point in enriched if point.get("finalized") is True
        ),
        "indicator_eligible_count": sum(
            1
            for point in enriched
            if point.get("indicator_eligible") is True
        ),
        "post_close_summary_count": sum(
            1
            for point in enriched
            if point.get("bar_type") == "post_close_summary"
        ),
    }


def get_market_index_intraday(index_id: str) -> dict:
    normalized_index_id = index_id.upper()
    config = INDEX_CONFIG_BY_ID.get(normalized_index_id)

    if config is None:
        supported = ", ".join(sorted(INDEX_CONFIG_BY_ID))
        raise ValueError(f"index_id must be one of: {supported}.")

    try:
        official_payload = _fetch_twse_index_5s_intraday(config)
        if official_payload.get("point_count", 0) > 0:
            try:
                mis_payload = _fetch_mis_index_intraday(config)
                if mis_payload["point_count"] > 0:
                    return _finalize_index_intraday_contract(
                        _merge_index_intraday_snapshot(
                            official_payload,
                            mis_payload,
                        )
                    )
            except Exception as exc:
                observe_provider_fallback(
                    exc,
                    operation="indices.official_intraday_mis_merge",
                )

            return _finalize_index_intraday_contract(official_payload)
    except Exception as exc:
        observe_provider_fallback(exc, operation="indices.official_intraday")

    yahoo_error: Exception | None = None
    yahoo_payload: dict | None = None

    try:
        yahoo_payload = _fetch_yahoo_index_intraday(config)
    except Exception as exc:
        observe_provider_fallback(exc, operation="indices.yahoo_intraday")
        yahoo_error = exc

    try:
        mis_payload = _fetch_mis_index_intraday(config)
        if mis_payload["point_count"] > 0:
            if yahoo_payload is not None and yahoo_payload.get("point_count", 0) > 0:
                return _finalize_index_intraday_contract(
                    _merge_index_intraday_snapshot(
                        yahoo_payload,
                        mis_payload,
                    )
                )
            if normalized_index_id == "TPEX":
                try:
                    from app.market.taiwan_index_minute import (
                        read_persisted_taiwan_index_minute_series,
                    )

                    persisted_payload = (
                        read_persisted_taiwan_index_minute_series(
                            normalized_index_id
                        )
                    )
                    if persisted_payload.get("point_count", 0) > 0:
                        return _finalize_index_intraday_contract(
                            _merge_index_intraday_snapshot(
                                persisted_payload,
                                mis_payload,
                            )
                        )
                except Exception as exc:
                    observe_provider_fallback(
                        exc,
                        operation=(
                            "indices.persisted_synthetic_intraday_merge"
                        ),
                    )
            return _finalize_index_intraday_contract(mis_payload)
    except Exception as exc:
        observe_provider_fallback(exc, operation="indices.mis_intraday")
        if yahoo_error is None:
            yahoo_error = exc

    if yahoo_payload is not None and yahoo_payload.get("point_count", 0) > 0:
        return _finalize_index_intraday_contract(yahoo_payload)

    if normalized_index_id == "TPEX":
        try:
            from app.market.taiwan_index_minute import (
                read_persisted_taiwan_index_minute_series,
            )

            persisted_payload = read_persisted_taiwan_index_minute_series(
                normalized_index_id
            )
            if persisted_payload.get("point_count", 0) > 0:
                return _finalize_index_intraday_contract(
                    persisted_payload
                )
        except Exception as exc:
            observe_provider_fallback(
                exc,
                operation="indices.persisted_synthetic_intraday",
            )

    try:
        fallback_payload = _index_intraday_fallback_from_list(config)
    except Exception as exc:
        if yahoo_error is not None:
            raise yahoo_error from exc
        raise

    if fallback_payload is not None:
        return _finalize_index_intraday_contract(fallback_payload)

    if yahoo_error is not None:
        raise yahoo_error

    return _finalize_index_intraday_contract({
        "stock_id": config["index_id"],
        "symbol": config["symbol"],
        "source": "unavailable",
        "provider": None,
        "interval": None,
        "trade_date": None,
        "coverage_status": "missing",
        "is_partial": True,
        "volume_unit": None,
        "volume_semantics": "not_available",
        "previous_close": None,
        "point_count": 0,
        "points": [],
    })


def _fetch_twse_shares_by_code() -> dict[str, int]:
    cached = _SHARES_CACHE.get("TWSE")

    if cached and monotonic() < float(cached["expires_at"]):
        shares = cached.get("shares")

        if isinstance(shares, dict):
            return shares

    payload = _fetch_json(TWSE_COMPANY_BASIC_URL)
    rows = payload if isinstance(payload, list) else []
    shares_by_code: dict[str, int] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        code = _regular_stock_code(row.get("公司代號"))

        if code is None:
            continue

        shares = _as_int(row.get("已發行普通股數或TDR原股發行股數"))

        if shares is None:
            paid_in_capital = _as_int(row.get("實收資本額"))
            shares = int(paid_in_capital / 10) if paid_in_capital else None

        if shares is not None and shares > 0:
            shares_by_code[code] = shares

    _SHARES_CACHE["TWSE"] = {
        "expires_at": monotonic() + INDEX_LIST_CACHE_TTL_SECONDS,
        "shares": shares_by_code,
    }
    return shares_by_code


def _quote_row_change_pct(close: float | None, change: float | None) -> float | None:
    if close is None or change is None:
        return None

    previous_close = close - change

    if previous_close == 0:
        return None

    return (change / previous_close) * 100


def _market_index_item_for_contribution(market: str) -> dict | None:
    items = _fetch_tpex_index_list() if market == "TPEX" else _fetch_twse_index_list()
    return items[0] if items else None


def _source_contribution_quote_rows(market: str) -> tuple[list[dict], dict[str, int], str, dict[str, str]]:
    if market == "TPEX":
        payload = _fetch_json(TPEX_DAILY_QUOTES_URL)
        rows = payload if isinstance(payload, list) else []
        shares_by_code = {
            code: shares
            for row in rows
            if isinstance(row, dict)
            for code in [_regular_stock_code(row.get("SecuritiesCompanyCode"))]
            for shares in [_as_int(row.get("Capitals"))]
            if code is not None and shares is not None and shares > 0
        }
        return rows, shares_by_code, "tpex_openapi_mainboard_quotes", {
            "code": "SecuritiesCompanyCode",
            "name": "CompanyName",
            "close": "Close",
            "change": "Change",
            "trade_value": "TransactionAmount",
            "date": "Date",
        }

    payload = _fetch_json(TWSE_DAILY_QUOTES_URL)
    rows = payload if isinstance(payload, list) else []
    return rows, _fetch_twse_shares_by_code(), "twse_openapi_stock_day_all+t187ap03_L", {
        "code": "Code",
        "name": "Name",
        "close": "ClosingPrice",
        "change": "Change",
        "trade_value": "TradeValue",
        "date": "Date",
    }


def _latest_market_daily_price_date(
    db: Session,
    *,
    market: str,
) -> date | None:
    source_name = _market_source_name(market)
    return (
        db.query(func.max(MarketDailyPrice.trade_date))
        .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
        .filter(SourceRegistry.source_name == source_name)
        .scalar()
    )


def _local_contribution_quote_rows(
    db: Session,
    *,
    market: str,
    shares_by_code: dict[str, int],
) -> tuple[list[dict], dict[str, int], str, dict[str, str]]:
    source_name = _market_source_name(market)
    latest_trade_date = _latest_market_daily_price_date(db, market=market)

    if latest_trade_date is None:
        return [], shares_by_code, f"market_daily_price:{source_name}", {
            "code": "stock_id",
            "name": "stock_name",
            "close": "close_price",
            "change": "price_change",
            "trade_value": "trade_value",
            "date": "trade_date",
        }

    rows = (
        db.query(MarketDailyPrice)
        .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
        .filter(SourceRegistry.source_name == source_name)
        .filter(MarketDailyPrice.trade_date == latest_trade_date)
        .order_by(MarketDailyPrice.stock_id.asc())
        .all()
    )
    payload_rows = [
        {
            "stock_id": row.stock_id,
            "stock_name": row.stock_name,
            "close_price": row.close_price,
            "price_change": row.price_change,
            "trade_value": row.trade_value,
            "trade_date": row.trade_date,
        }
        for row in rows
    ]
    return payload_rows, shares_by_code, f"market_daily_price:{source_name}", {
        "code": "stock_id",
        "name": "stock_name",
        "close": "close_price",
        "change": "price_change",
        "trade_value": "trade_value",
        "date": "trade_date",
    }


def _contribution_quote_rows(
    market: str,
    db: Session | None = None,
) -> tuple[list[dict], dict[str, int], str, dict[str, str]]:
    source_rows: list[dict] = []
    source_shares_by_code: dict[str, int] = {}
    source = ""
    source_keys: dict[str, str] = {
        "code": "stock_id",
        "name": "stock_name",
        "close": "close_price",
        "change": "price_change",
        "trade_value": "trade_value",
        "date": "trade_date",
    }
    source_trade_date: date | None = None

    try:
        source_rows, source_shares_by_code, source, source_keys = _source_contribution_quote_rows(
            market
        )
        source_trade_date = (
            _parse_trade_date(source_rows[0].get(source_keys["date"]))
            if source_rows
            else None
        )
    except Exception as exc:
        observe_provider_fallback(exc, operation="indices.contribution_source_rows")
        source_rows = []

    if db is not None:
        local_rows, local_shares_by_code, local_source, local_keys = _local_contribution_quote_rows(
            db,
            market=market,
            shares_by_code=source_shares_by_code,
        )
        local_trade_date = (
            _parse_trade_date(local_rows[0].get(local_keys["date"]))
            if local_rows
            else None
        )

        if local_rows and (
            source_trade_date is None
            or local_trade_date is None
            or local_trade_date >= source_trade_date
        ):
            return local_rows, local_shares_by_code, local_source, local_keys

    if source_rows:
        return source_rows, source_shares_by_code, source, source_keys

    if db is not None:
        return _local_contribution_quote_rows(
            db,
            market=market,
            shares_by_code=source_shares_by_code,
        )

    return source_rows, source_shares_by_code, source or "unavailable", source_keys


def get_market_index_contributions(
    index_id: str,
    limit: int = 20,
    db: Session | None = None,
) -> dict:
    normalized_index_id = index_id.upper()
    config = INDEX_CONFIG_BY_ID.get(normalized_index_id)

    if config is None:
        supported = ", ".join(sorted(INDEX_CONFIG_BY_ID))
        raise ValueError(f"index_id must be one of: {supported}.")

    if limit <= 0:
        raise ValueError("limit must be greater than 0.")

    normalized_limit = min(limit, 100)
    cache_key = f"{normalized_index_id}:{normalized_limit}"
    cached = _CONTRIBUTION_CACHE.get(cache_key)

    if db is None and cached and monotonic() < float(cached["expires_at"]):
        payload = cached.get("payload")

        if isinstance(payload, dict):
            return payload

    market = str(config["market"])
    rows, shares_by_code, source, keys = _contribution_quote_rows(market, db=db)
    try:
        index_item = _market_index_item_for_contribution(market)
    except Exception as exc:
        observe_provider_fallback(exc, operation="indices.contribution_index_quote")
        index_item = None
    index_close = _as_float(index_item.get("close")) if index_item else None
    index_change = _as_float(index_item.get("change")) if index_item else None
    trade_date = _parse_trade_date(rows[0].get(keys["date"])) if rows else None
    if db is not None:
        latest_stat = _latest_market_index_daily_stat(db, index_id=normalized_index_id)
        if (
            latest_stat is not None
            and latest_stat.trade_date == trade_date
            and latest_stat.close_value is not None
        ):
            index_close = latest_stat.close_value
            index_change = latest_stat.price_change
    candidates: list[dict] = []
    component_universe_count = 0
    total_market_value = 0.0

    for row in rows:
        if not isinstance(row, dict):
            continue

        code = _regular_stock_code(row.get(keys["code"]))

        if code is None:
            continue
        component_universe_count += 1

        shares = shares_by_code.get(code)
        close = _as_float(row.get(keys["close"]))
        change = _as_float(row.get(keys["change"]))

        if shares is None or close is None or change is None or shares <= 0:
            continue

        market_value = close * shares
        market_value_change = change * shares
        total_market_value += market_value
        candidates.append(
            {
                "stock_id": code,
                "stock_name": row.get(keys["name"]),
                "close": close,
                "change": change,
                "change_pct": _quote_row_change_pct(close=close, change=change),
                "market_value": market_value,
                "market_value_change": market_value_change,
                "trade_value": _as_int(row.get(keys["trade_value"])),
                "currency": "TWD",
                "price_unit": "TWD",
                "market_value_unit": "TWD",
                "trade_value_unit": "TWD",
                "contribution_unit": "index_points",
            }
        )

    for candidate in candidates:
        candidate["contribution_points"] = (
            candidate["market_value_change"] * index_close / total_market_value
            if index_close is not None and total_market_value > 0
            else None
        )

    positive = sorted(
        [item for item in candidates if (item.get("contribution_points") or 0) > 0],
        key=lambda item: item["contribution_points"] or 0,
        reverse=True,
    )[:normalized_limit]
    negative = sorted(
        [item for item in candidates if (item.get("contribution_points") or 0) < 0],
        key=lambda item: item["contribution_points"] or 0,
    )[:normalized_limit]
    estimated_total_contribution_points = sum(
        float(item["contribution_points"])
        for item in candidates
        if item.get("contribution_points") is not None
    )
    residual_points = (
        float(index_change) - estimated_total_contribution_points
        if index_change is not None
        else None
    )
    residual_pct = (
        abs(residual_points) / abs(float(index_change)) * 100
        if residual_points is not None and float(index_change) != 0
        else None
    )
    coverage_ratio = (
        len(candidates) / component_universe_count
        if component_universe_count
        else None
    )
    reconciliation_status = (
        "unavailable"
        if residual_pct is None
        else "within_tolerance"
        if residual_pct <= 5
        else "outside_tolerance"
    )
    confidence = (
        "high"
        if coverage_ratio is not None
        and coverage_ratio >= 0.95
        and reconciliation_status == "within_tolerance"
        else "medium"
        if coverage_ratio is not None and coverage_ratio >= 0.8
        else "low"
    )

    def ranked(items: list[dict]) -> list[dict]:
        return [
            {
                "rank": index + 1,
                "stock_id": item["stock_id"],
                "stock_name": item["stock_name"],
                "close": item["close"],
                "change": item["change"],
                "change_pct": item["change_pct"],
                "contribution_points": item["contribution_points"],
                "market_value_change": item["market_value_change"],
                "trade_value": item["trade_value"],
                "currency": item["currency"],
                "price_unit": item["price_unit"],
                "market_value_unit": item["market_value_unit"],
                "trade_value_unit": item["trade_value_unit"],
                "contribution_unit": item["contribution_unit"],
            }
            for index, item in enumerate(items)
        ]

    payload = {
        "index_id": normalized_index_id,
        "market": market,
        "source": source,
        "method": "estimated_market_cap_weight",
        "method_version": "v1",
        "is_official": False,
        "currency": "TWD",
        "price_unit": "TWD",
        "market_value_unit": "TWD",
        "trade_value_unit": "TWD",
        "contribution_unit": "index_points",
        "as_of": datetime.now(TAIPEI_TZ),
        "trade_date": trade_date,
        "index_close": index_close,
        "index_change": index_change,
        "total_market_value": total_market_value if total_market_value > 0 else None,
        "component_universe_count": component_universe_count,
        "covered_component_count": len(candidates),
        "coverage_ratio": coverage_ratio,
        "estimated_total_contribution_points": (
            estimated_total_contribution_points
            if candidates and index_close is not None
            else None
        ),
        "actual_index_change_points": index_change,
        "residual_points": residual_points,
        "residual_pct": residual_pct,
        "reconciliation_status": reconciliation_status,
        "confidence": confidence,
        "component_policy": "regular_four_digit_cash_equities_only",
        "corporate_action_adjustment": "not_applied",
        "positive": ranked(positive),
        "negative": ranked(negative),
    }
    if db is None:
        _CONTRIBUTION_CACHE[cache_key] = {
            "expires_at": monotonic() + INDEX_LIST_CACHE_TTL_SECONDS,
            "payload": payload,
        }
    return payload


def _market_index_chart_freshness(
    points: list[dict],
    *,
    timeframe: str,
    now: datetime | None = None,
) -> dict:
    latest_value = points[-1].get("time") if points else None
    if isinstance(latest_value, datetime):
        latest_data_date = latest_value.date()
    else:
        latest_data_date = latest_value if isinstance(latest_value, date) else None

    local_now = now or datetime.now(TAIPEI_TZ)
    expected_data_date = expected_daily_price_date(now=local_now)
    if latest_data_date is None:
        return {
            "latest_data_date": None,
            "expected_data_date": expected_data_date,
            "freshness_status": "missing",
            "is_current": False,
            "refresh_recommended": True,
        }

    is_current = (
        _index_stat_period_key(latest_data_date, timeframe)
        >= _index_stat_period_key(expected_data_date, timeframe)
    )
    return {
        "latest_data_date": latest_data_date,
        "expected_data_date": expected_data_date,
        "freshness_status": "current" if is_current else "stale",
        "is_current": is_current,
        "refresh_recommended": not is_current,
    }


def get_market_index_ohlc_chart_data(
    index_id: str,
    timeframe: str = "daily",
    bars: int = 90,
    db: Session | None = None,
) -> dict:
    normalized_index_id = index_id.upper()
    config = INDEX_CONFIG_BY_ID.get(normalized_index_id)

    if config is None:
        supported = ", ".join(sorted(INDEX_CONFIG_BY_ID))
        raise ValueError(f"index_id must be one of: {supported}.")

    if timeframe not in INDEX_TIMEFRAME_INTERVALS:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")

    if bars <= 0:
        raise ValueError("bars must be greater than 0.")

    if bars > MAX_INDEX_BARS:
        raise ValueError(f"bars must be less than or equal to {MAX_INDEX_BARS}.")

    if timeframe == "monthly":
        points = _fetch_yahoo_monthly_index_points(config)
    else:
        points, _meta, _tz = _fetch_yahoo_index_points(
            config=config,
            range_value=_index_range_for(timeframe=timeframe, bars=bars),
            interval=INDEX_TIMEFRAME_INTERVALS[timeframe],
        )

    selected_points = [dict(point) for point in points[-bars:]]
    fallback_date = date.today()
    from_date = selected_points[0]["time"] if selected_points else fallback_date
    to_date = selected_points[-1]["time"] if selected_points else fallback_date
    stat_from_date, stat_to_date = _index_stat_query_range(
        timeframe=timeframe,
        from_date=from_date,
        to_date=to_date,
    )
    coverage_to_date = max(stat_to_date, datetime.now(TAIPEI_TZ).date())
    backfill_result = None
    official_ohlc_overlay = None

    if db is not None and selected_points:
        backfill_result = {
            "status": "not_requested",
            "reason": "read_path_is_side_effect_free",
            "refresh_route": f"POST /api/market/indices/{normalized_index_id}/daily-stats/refresh",
        }

        values_by_period = _load_market_index_stat_values(
            db=db,
            index_id=normalized_index_id,
            timeframe=timeframe,
            from_date=stat_from_date,
            to_date=coverage_to_date,
        )
        _apply_market_index_stat_values(
            selected_points,
            timeframe=timeframe,
            values_by_period=values_by_period,
        )
        if timeframe == "daily":
            official_ohlc_overlay = _append_official_market_index_daily_points(
                db=db,
                points=selected_points,
                index_id=normalized_index_id,
                to_date=coverage_to_date,
            )
            selected_points = selected_points[-bars:]
    else:
        try:
            trade_values_by_date = _fetch_recent_index_trade_values(str(config["market"]))

            for point in selected_points:
                point["trade_value"] = trade_values_by_date.get(point["time"])
        except Exception as exc:
            observe_provider_fallback(exc, operation="indices.trade_value_enrichment")

    if selected_points:
        from_date = selected_points[0]["time"]
        to_date = selected_points[-1]["time"]

    if backfill_result is not None and official_ohlc_overlay is not None:
        backfill_result["official_ohlc_overlay"] = official_ohlc_overlay

    freshness = _market_index_chart_freshness(
        selected_points,
        timeframe=timeframe,
    )
    return {
        "stock_id": normalized_index_id,
        "timeframe": timeframe,
        "bars": bars,
        "lookback_days": max((to_date - from_date).days, 0),
        "from_date": from_date,
        "to_date": to_date,
        "point_count": len(selected_points),
        "points": selected_points,
        "backfill": backfill_result,
        **freshness,
    }


def _market_index_summary(
    db: Session,
    *,
    force_refresh: bool,
    refresh_daily_stats: bool = False,
) -> dict:
    if not force_refresh:
        memory_payload = _CACHE["payload"]
        memory_payload = memory_payload if isinstance(memory_payload, dict) else None
        shared_payload, shared_cache_error = _load_shared_market_index_summary()
        cached_payload, cache_origin = _newer_summary_payload(
            memory_payload,
            shared_payload,
        )

        if isinstance(cached_payload, dict):
            _CACHE["payload"] = cached_payload
            _CACHE["expires_at"] = monotonic() + _market_index_summary_cache_ttl(
                cached_payload.get("indices") or []
            )
            view = _summary_cache_view(cached_payload, origin=cache_origin)
            if shared_cache_error:
                view["warnings"] = list(
                    dict.fromkeys([*view.get("warnings", []), shared_cache_error])
                )
            return view

        expected_date = expected_daily_price_date()
        local_indices: list[dict] = []
        local_updated_at: list[datetime] = []

        for config in INDEX_CONFIGS:
            rows = (
                db.query(MarketIndexDailyStat)
                .filter(MarketIndexDailyStat.index_id == str(config["index_id"]))
                .filter(MarketIndexDailyStat.close_value.isnot(None))
                .order_by(MarketIndexDailyStat.trade_date.desc())
                .limit(90)
                .all()
            )
            rows.reverse()
            points: list[dict] = []
            previous_close: float | None = None
            for row in rows:
                point = _market_index_point_from_daily_stat(
                    row,
                    previous_close=previous_close,
                )
                if point is None:
                    continue
                points.append(point)
                previous_close = _as_float(point.get("close"))

            if not rows or not points:
                local_indices.append(
                    _unavailable_index(
                        config,
                        ValueError("No cached index summary is available."),
                    )
                )
                continue

            latest_row = rows[-1]
            latest_point = points[-1]
            close = _as_float(latest_point.get("close"))
            change = _as_float(latest_row.price_change)
            prior_close = close - change if close is not None and change is not None else None
            change_pct = (
                (change / prior_close) * 100
                if change is not None and prior_close not in (None, 0)
                else None
            )
            ma20 = _moving_average([_as_float(point.get("close")) for point in points], 20)
            price_vs_ma20 = (
                ((close - ma20) / ma20) * 100
                if close is not None and ma20 not in (None, 0)
                else None
            )
            breadth = _latest_market_breadth(db=db, market=str(config["market"]))
            if _breadth_trade_date(breadth) != latest_row.trade_date:
                breadth = None

            aware_updated_at = _sqlite_utc_datetime(latest_row.updated_at)
            if aware_updated_at is not None:
                local_updated_at.append(aware_updated_at)
            local_indices.append(
                {
                    "index_id": config["index_id"],
                    "label": config["label"],
                    "short_label": config["short_label"],
                    "market": config["market"],
                    "symbol": config["symbol"],
                    "source": latest_row.source or "market_index_daily_stat",
                    "as_of": aware_updated_at,
                    "time": latest_row.trade_date,
                    "open": latest_point.get("open"),
                    "high": latest_point.get("high"),
                    "low": latest_point.get("low"),
                    "close": close,
                    "previous_close": prior_close,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": latest_row.trade_volume,
                    "estimated_volume": None,
                    "trade_value": latest_row.trade_value,
                    "estimated_trade_value": None,
                    "ma20": ma20,
                    "price_vs_ma20": price_vs_ma20,
                    "point_count": len(points),
                    "points": points,
                    "breadth": breadth,
                    "error_message": None,
                }
            )

        local_payload = {"indices": local_indices}
        stale_index_ids = _stale_market_index_ids(
            local_payload,
            expected_date=expected_date,
        )
        refresh_recommended = bool(stale_index_ids)
        warnings = [shared_cache_error] if shared_cache_error else []
        if refresh_recommended:
            warnings.append(
                "Local index cache is missing or older than the expected Taiwan "
                f"trading date for: {', '.join(stale_index_ids)}."
            )
        return _with_breadth_status_contract({
            "as_of": max(local_updated_at, default=datetime.now(TAIPEI_TZ)),
            "source": "market_index_daily_stat",
            "indices": local_indices,
            "cache_status": "local_cache",
            "refresh_recommended": refresh_recommended,
            "warnings": warnings,
        })

    indices: list[dict] = []
    breadth_target_date = _market_breadth_target_date()

    for config in INDEX_CONFIGS:
        try:
            index_payload = _fetch_yahoo_index(config)
        except Exception as exc:
            observe_provider_fallback(exc, operation="indices.summary_yahoo")
            index_payload = _unavailable_index(config, exc)

        try:
            latest_yahoo_date = index_payload.get("time")
            coverage_start = (
                latest_yahoo_date
                if isinstance(latest_yahoo_date, date)
                else datetime.now(TAIPEI_TZ).date() - timedelta(days=14)
            )
            if refresh_daily_stats:
                _ensure_market_index_daily_stat_coverage(
                    db=db,
                    index_id=str(config["index_id"]),
                    market=str(config["market"]),
                    from_date=coverage_start,
                    to_date=datetime.now(TAIPEI_TZ).date(),
                )
            _apply_latest_official_market_index_stat(
                db=db,
                config=config,
                payload=index_payload,
            )
        except Exception:
            logger.exception(
                "Market index coverage refresh failed index_id=%s market=%s",
                config["index_id"],
                config["market"],
            )
            db.rollback()

        try:
            _apply_latest_official_index_snapshot(
                config=config,
                payload=index_payload,
            )
        except Exception as exc:
            observe_provider_fallback(
                exc,
                operation="indices.official_index_snapshot_overlay",
            )

        index_trade_date = index_payload.get("time")
        index_trade_date = index_trade_date if isinstance(index_trade_date, date) else None
        market_breadth = _resolve_market_breadth(
            db=db,
            market=str(config["market"]),
            target_trade_date=breadth_target_date,
        )
        trade_value = index_payload.get("trade_value")
        if (
            isinstance(market_breadth, dict)
            and _breadth_trade_date(market_breadth) == index_trade_date
            and market_breadth.get("trade_value") is not None
        ):
            trade_value = market_breadth.get("trade_value")
        try:
            official_trade_value = _fetch_recent_index_trade_values(str(config["market"])).get(
                index_payload.get("time")
            )

            if official_trade_value is not None:
                trade_value = official_trade_value
        except Exception as exc:
            observe_provider_fallback(exc, operation="indices.summary_trade_value")

        index_payload["breadth"] = market_breadth
        index_payload["trade_value"] = trade_value
        index_payload["estimated_trade_value"] = _estimate_session_volume(
            volume=trade_value,
            as_of=index_payload.get("as_of"),
        )
        indices.append(index_payload)

    expected_date = expected_daily_price_date()
    stale_index_ids = _stale_market_index_ids(
        {"indices": indices},
        expected_date=expected_date,
    )
    warnings = (
        [
            "Refreshed index summary is still missing or older than the expected "
            f"Taiwan trading date for: {', '.join(stale_index_ids)}."
        ]
        if stale_index_ids
        else []
    )
    payload = _with_breadth_status_contract({
        "as_of": datetime.now(TAIPEI_TZ),
        "source": "yahoo_finance_chart",
        "indices": indices,
        "cache_status": "live",
        "refresh_recommended": bool(stale_index_ids),
        "warnings": warnings,
    })
    _CACHE["payload"] = payload
    _CACHE["expires_at"] = monotonic() + _market_index_summary_cache_ttl(indices)
    try:
        _persist_shared_market_index_summary(payload)
    except Exception as exc:
        logger.warning("Failed to persist shared market index summary cache: %s", exc)
        payload["warnings"] = [
            *payload["warnings"],
            f"Shared market index summary cache persistence failed: {exc}",
        ]
    return payload


def get_market_index_summary(db: Session, force_refresh: bool = False) -> dict:
    if force_refresh:
        logger.warning(
            "Deprecated force_refresh on GET market index summary was ignored; use the explicit POST refresh route."
        )
    return _market_index_summary(db=db, force_refresh=False)


def refresh_market_index_summary(
    db: Session,
    *,
    refresh_daily_stats: bool = False,
) -> dict:
    with _SUMMARY_REFRESH_LOCK:
        return _market_index_summary(
            db=db,
            force_refresh=True,
            refresh_daily_stats=refresh_daily_stats,
        )


def refresh_market_index_daily_stats(
    db: Session,
    *,
    index_id: str,
    from_date: date,
    to_date: date,
) -> dict:
    normalized_index_id = index_id.upper()
    config = INDEX_CONFIG_BY_ID.get(normalized_index_id)
    if config is None:
        supported = ", ".join(sorted(INDEX_CONFIG_BY_ID))
        raise ValueError(f"index_id must be one of: {supported}.")
    if from_date > to_date:
        raise ValueError("from_date must be on or before to_date.")
    result = ensure_market_index_daily_stat_coverage(
        db=db,
        index_id=normalized_index_id,
        market=str(config["market"]),
        from_date=from_date,
        to_date=to_date,
    )
    if result is not None:
        return result
    return {
        "status": "no_changes",
        "index_id": normalized_index_id,
        "market": str(config["market"]),
        "source": None,
        "requested_month_count": len(
            _month_starts_between(from_date=from_date, to_date=to_date)
        ),
        "fetched_month_count": 0,
        "skipped_existing_month_count": len(
            _month_starts_between(from_date=from_date, to_date=to_date)
        ),
        "inserted_count": 0,
        "updated_count": 0,
        "errors": [],
        "message": "Index daily stats are already current for the requested range.",
    }
