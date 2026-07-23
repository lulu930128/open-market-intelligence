from __future__ import annotations

from collections.abc import Callable
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import time

import requests
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    KRCompanyFundamental,
    KRDailyPrice,
    KRIndexDailyPrice,
    KRInvestorTradeDaily,
    KRMarketIndex,
    KRStockMaster,
    KRWatchlistGroup,
    KRWatchlistItem,
    utc_now,
)
from app.observability.provider_http import translate_provider_http_errors
from app.kr_market.chart_projection import (
    aggregate_daily_rows as _aggregate_kr_daily_rows,
    aggregate_index_daily_rows as _aggregate_kr_index_daily_rows,
    chart_row as _chart_row,
    close_value as _kr_close_value,
)
from app.kr_market.errors import KRMarketDataFetchError
from app.kr_market.schemas import (
    KRWatchlistGroupCreate,
    KRWatchlistGroupUpdate,
    KRWatchlistItemCreate,
    KRWatchlistItemUpdate,
)
from app.kr_market.providers.krx import (
    fetch_krx_daily_price_payload,
    fetch_krx_investor_trade_payload,
    fetch_krx_stock_master_payload,
)
from app.kr_market.providers.naver import (
    fetch_naver_index_chart_payload,
    fetch_naver_index_intraday_page_payload,
    fetch_naver_index_realtime_payload,
)
from app.kr_market.providers.opendart import fetch_opendart_financial_statement_payload
from app.kr_market.providers.yahoo import fetch_yahoo_chart_payload
from app.kr_market.source_health import build_kr_source_health
from app.kr_market.sources import (
    KRCompanyFundamentalRecord,
    KRDailyPriceRecord,
    KRIndexIntradayPointRecord,
    KRIndexDailyPriceRecord,
    KR_INDEX_CONFIG_BY_ID,
    KR_INDEX_RECORDS,
    KRInvestorTradeRecord,
    KRIndexRecord,
    KRStockRecord,
    local_code_from_symbol,
    normalize_kr_index_id,
    normalize_kr_symbol,
    parse_naver_index_daily_prices,
    parse_naver_index_intraday_last_page,
    parse_naver_index_intraday_points,
    parse_naver_index_realtime_quote,
    parse_krx_daily_price_records,
    parse_krx_investor_trade_records,
    parse_krx_stock_records,
    parse_opendart_company_fundamental_records,
    parse_yahoo_daily_prices,
    parse_yahoo_intraday_prices,
    parse_yahoo_stock_record,
)
from app.kr_market.trading_calendar import (
    KR_MARKET_TIMEZONE,
    expected_kr_daily_price_date,
    previous_kr_trading_day,
)
from app.market.stock_volume_pace import (
    build_stock_volume_pace,
    intraday_history_needs_bootstrap,
    latest_market_trade_date_points,
    mutate_market_intraday_history,
    previous_regular_close_from_history,
)
from app.market.technical_radar import (
    TechnicalRadarBar,
    build_technical_watchlist_radar,
)


_translate_kr_provider_errors = translate_provider_http_errors(KRMarketDataFetchError)


class KRStockNotFoundError(Exception):
    pass


class KRIndexNotFoundError(Exception):
    pass


class KRWatchlistGroupNotFoundError(Exception):
    pass


class KRWatchlistGroupNotEmptyError(Exception):
    pass


class KRWatchlistInvalidTreeError(Exception):
    pass


class KRWatchlistItemNotFoundError(Exception):
    pass


class KRWatchlistDuplicateItemError(Exception):
    pass


KR_CHART_LOOKBACK_MULTIPLIER = {
    "daily": 2,
    "weekly": 8,
    "monthly": 31,
}
KR_PLANNED_RESOURCE_KEYS = ("disclosures",)
KR_DAILY_PROVIDER_SET = {"auto", "krx_data", "yahoo_chart"}
KR_INDEX_PROVIDER_SET = {"naver_sise_index"}
KR_YAHOO_CHART_COMPACT_RANGE = "1y"
KR_YAHOO_CHART_FULL_RANGE = "10y"
KR_INDEX_COMPACT_LOOKBACK_DAYS = 370
KR_INDEX_FULL_LOOKBACK_DAYS = 3650
KR_INDEX_INTRADAY_CACHE_TTL_SECONDS = 60
KR_STOCK_INTRADAY_CACHE_TTL_SECONDS = 60
KR_DAILY_REFRESH_ATTEMPT_COOLDOWN_SECONDS = 300
KR_INDEX_INTRADAY_FULL_MAX_PAGES = 80
KR_INDEX_INTRADAY_INCREMENTAL_PAGES = 1
KR_INDEX_INTRADAY_PAGE_TIMEOUT_SECONDS = 5
KR_INDEX_INTRADAY_PAGE_WORKERS = 6
KR_INDEX_INTRADAY_PROVIDER = "naver_index_time"
MAX_KR_CHART_BARS = 5000
ProgressCallback = Callable[[int | None, int | None, str | None], None]
KR_DAILY_PROVIDER_PRIORITY = {"krx_data": 0, "yahoo_chart": 1}
_KR_INDEX_INTRADAY_CACHE: dict[str, tuple[float, dict]] = {}
_KR_STOCK_INTRADAY_CACHE: dict[str, tuple[float, dict]] = {}
_KR_DAILY_REFRESH_ATTEMPTS: dict[str, float] = {}


def _valid_symbol(symbol: str) -> str:
    normalized_symbol = normalize_kr_symbol(symbol)
    if not normalized_symbol:
        raise ValueError("symbol is required.")
    return normalized_symbol


def _valid_provider(provider: str) -> str:
    normalized_provider = (provider or "auto").strip().lower()
    if normalized_provider not in KR_DAILY_PROVIDER_SET:
        raise ValueError("provider must be one of: auto, krx_data, yahoo_chart.")
    return normalized_provider


def _valid_index_id(index_id: str) -> str:
    normalized_index_id = normalize_kr_index_id(index_id)
    if normalized_index_id not in KR_INDEX_CONFIG_BY_ID:
        supported = ", ".join(sorted(KR_INDEX_CONFIG_BY_ID))
        raise ValueError(f"index_id must be one of: {supported}.")
    return normalized_index_id


def _copy_payload(payload: dict) -> dict:
    return deepcopy(payload)


def _get_kr_index_intraday_cache(cache_key: str) -> dict | None:
    cached = _KR_INDEX_INTRADAY_CACHE.get(cache_key)
    if cached is None:
        return None

    cached_at, payload = cached
    if time.monotonic() - cached_at > KR_INDEX_INTRADAY_CACHE_TTL_SECONDS:
        return _copy_payload(payload)

    return _copy_payload(payload)


def _get_fresh_kr_index_intraday_cache(cache_key: str) -> dict | None:
    cached = _KR_INDEX_INTRADAY_CACHE.get(cache_key)
    if cached is None:
        return None

    cached_at, payload = cached
    if time.monotonic() - cached_at > KR_INDEX_INTRADAY_CACHE_TTL_SECONDS:
        return None

    return _copy_payload(payload)


def _set_kr_index_intraday_cache(cache_key: str, payload: dict) -> dict:
    _KR_INDEX_INTRADAY_CACHE[cache_key] = (time.monotonic(), _copy_payload(payload))
    return payload


def _get_fresh_kr_stock_intraday_cache(cache_key: str) -> dict | None:
    cached = _KR_STOCK_INTRADAY_CACHE.get(cache_key)
    if cached is None:
        return None

    cached_at, payload = cached
    if time.monotonic() - cached_at > KR_STOCK_INTRADAY_CACHE_TTL_SECONDS:
        _KR_STOCK_INTRADAY_CACHE.pop(cache_key, None)
        return None

    return _copy_payload(payload)


def _set_kr_stock_intraday_cache(cache_key: str, payload: dict) -> dict:
    _KR_STOCK_INTRADAY_CACHE[cache_key] = (time.monotonic(), _copy_payload(payload))
    return payload


def _minimal_stock_record(symbol: str, *, listing_source: str = "manual") -> KRStockRecord:
    normalized_symbol = _valid_symbol(symbol)
    return KRStockRecord(
        symbol=normalized_symbol,
        local_code=local_code_from_symbol(normalized_symbol),
        security_name=normalized_symbol,
        security_name_kr=None,
        exchange="Korea Exchange",
        market_segment=None,
        sector=None,
        industry=None,
        asset_type="stock",
        listing_source=listing_source,
        currency="KRW",
        exchange_timezone_name="Asia/Seoul",
    )


def get_kr_stock(db: Session, *, symbol: str) -> KRStockMaster:
    normalized_symbol = _valid_symbol(symbol)
    stock = (
        db.query(KRStockMaster)
        .filter(KRStockMaster.symbol == normalized_symbol)
        .first()
    )
    if stock is None:
        raise KRStockNotFoundError(f"KR symbol='{normalized_symbol}' was not found.")
    return stock


def list_kr_stocks(
    db: Session,
    *,
    exchange: str | None = None,
    asset_type: str | None = None,
    is_active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[KRStockMaster]:
    query = db.query(KRStockMaster)
    if exchange is not None:
        query = query.filter(KRStockMaster.exchange == exchange)
    if asset_type is not None:
        query = query.filter(KRStockMaster.asset_type == asset_type)
    if is_active is not None:
        query = query.filter(KRStockMaster.is_active.is_(is_active))
    return query.order_by(KRStockMaster.symbol.asc()).offset(offset).limit(limit).all()


def search_kr_stocks(db: Session, *, keyword: str, limit: int = 50) -> list[KRStockMaster]:
    normalized_keyword = (keyword or "").strip()
    if not normalized_keyword:
        return []

    normalized_symbol = normalize_kr_symbol(normalized_keyword)
    local_code = local_code_from_symbol(normalized_symbol) if normalized_symbol else normalized_keyword
    pattern = f"%{normalized_keyword}%"

    return (
        db.query(KRStockMaster)
        .filter(
            or_(
                KRStockMaster.symbol == normalized_symbol,
                KRStockMaster.local_code == local_code,
                KRStockMaster.security_name.ilike(pattern),
                KRStockMaster.security_name_kr.ilike(pattern),
                KRStockMaster.market_segment.ilike(pattern),
                KRStockMaster.sector.ilike(pattern),
                KRStockMaster.industry.ilike(pattern),
            )
        )
        .order_by(KRStockMaster.symbol.asc())
        .limit(limit)
        .all()
    )


def upsert_kr_stock_record(db: Session, record: KRStockRecord) -> KRStockMaster:
    existing = (
        db.query(KRStockMaster)
        .filter(KRStockMaster.symbol == record.symbol)
        .first()
    )
    now = utc_now()

    if existing is None:
        existing = KRStockMaster(
            symbol=record.symbol,
            local_code=record.local_code,
            security_name=record.security_name,
            security_name_kr=record.security_name_kr,
            exchange=record.exchange,
            market_segment=record.market_segment,
            sector=record.sector,
            industry=record.industry,
            asset_type=record.asset_type,
            listing_source=record.listing_source,
            currency=record.currency,
            exchange_timezone_name=record.exchange_timezone_name,
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(existing)
        return existing

    existing.local_code = record.local_code or existing.local_code
    existing.security_name = record.security_name or existing.security_name
    existing.security_name_kr = record.security_name_kr or existing.security_name_kr
    existing.exchange = record.exchange or existing.exchange
    existing.market_segment = record.market_segment or existing.market_segment
    existing.sector = record.sector or existing.sector
    existing.industry = record.industry or existing.industry
    existing.asset_type = record.asset_type or existing.asset_type
    existing.listing_source = record.listing_source or existing.listing_source
    existing.currency = record.currency or existing.currency
    existing.exchange_timezone_name = record.exchange_timezone_name or existing.exchange_timezone_name
    existing.is_active = True
    existing.last_seen_at = now
    existing.updated_at = now
    return existing


def upsert_kr_stock_records(db: Session, records: list[KRStockRecord]) -> dict:
    created_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(KRStockMaster)
            .filter(KRStockMaster.symbol == record.symbol)
            .first()
        )
        upsert_kr_stock_record(db, record)
        if existing is None:
            created_count += 1
        else:
            updated_count += 1

    db.commit()
    return {"created_count": created_count, "updated_count": updated_count}


@_translate_kr_provider_errors
def sync_kr_symbol_master(db: Session, *, deactivate_missing: bool = False) -> dict:
    payload, source_url = fetch_krx_stock_master_payload(
        timeout_seconds=settings.kr_market_http_timeout_seconds,
    )
    records = parse_krx_stock_records(payload)
    result = upsert_kr_stock_records(db, records)
    scanned_symbols = {record.symbol for record in records}
    deactivated_count = 0

    if deactivate_missing and scanned_symbols:
        stale_rows = (
            db.query(KRStockMaster)
            .filter(KRStockMaster.is_active.is_(True))
            .filter(~KRStockMaster.symbol.in_(scanned_symbols))
            .all()
        )
        for row in stale_rows:
            row.is_active = False
            row.updated_at = utc_now()
            deactivated_count += 1
        db.commit()

    return {
        "status": "success",
        "provider": "krx_data",
        "source_url": source_url,
        "scanned_count": len(records),
        "created_count": result["created_count"],
        "updated_count": result["updated_count"],
        "deactivated_count": deactivated_count,
        "message": "KR stock master synced from KRX Data.",
    }


def _kr_index_record_dict(record: KRIndexRecord, *, row_id: int | None = None, is_active: bool = True) -> dict:
    return {
        "id": row_id,
        "index_id": record.index_id,
        "provider_symbol": record.provider_symbol,
        "name": record.name,
        "short_name": record.short_name,
        "name_kr": record.name_kr,
        "market_segment": record.market_segment,
        "index_family": record.index_family,
        "provider": record.provider,
        "currency": record.currency,
        "source_url": record.source_url,
        "exchange_timezone_name": record.exchange_timezone_name,
        "sort_order": record.sort_order,
        "is_active": is_active,
    }


def _kr_index_row_dict(row: KRMarketIndex) -> dict:
    return {
        "id": row.id,
        "index_id": row.index_id,
        "provider_symbol": row.provider_symbol,
        "name": row.name,
        "short_name": row.short_name,
        "name_kr": row.name_kr,
        "market_segment": row.market_segment,
        "index_family": row.index_family,
        "provider": row.provider,
        "currency": row.currency,
        "source_url": row.source_url,
        "exchange_timezone_name": row.exchange_timezone_name,
        "sort_order": row.sort_order,
        "is_active": row.is_active,
    }


def upsert_kr_index_records(db: Session, records: list[KRIndexRecord]) -> dict:
    created_count = 0
    updated_count = 0
    now = utc_now()

    for record in records:
        existing = (
            db.query(KRMarketIndex)
            .filter(KRMarketIndex.index_id == record.index_id)
            .first()
        )
        if existing is None:
            db.add(
                KRMarketIndex(
                    index_id=record.index_id,
                    provider_symbol=record.provider_symbol,
                    name=record.name,
                    short_name=record.short_name,
                    name_kr=record.name_kr,
                    market_segment=record.market_segment,
                    index_family=record.index_family,
                    provider=record.provider,
                    currency=record.currency,
                    source_url=record.source_url,
                    exchange_timezone_name=record.exchange_timezone_name,
                    sort_order=record.sort_order,
                    is_active=True,
                )
            )
            created_count += 1
            continue

        existing.provider_symbol = record.provider_symbol
        existing.name = record.name
        existing.short_name = record.short_name
        existing.name_kr = record.name_kr
        existing.market_segment = record.market_segment
        existing.index_family = record.index_family
        existing.provider = record.provider
        existing.currency = record.currency
        existing.source_url = record.source_url
        existing.exchange_timezone_name = record.exchange_timezone_name
        existing.sort_order = record.sort_order
        existing.is_active = True
        existing.updated_at = now
        updated_count += 1

    db.commit()
    return {"created_count": created_count, "updated_count": updated_count}


def sync_kr_index_master(db: Session) -> dict:
    result = upsert_kr_index_records(db, list(KR_INDEX_RECORDS))
    return {
        "status": "success",
        "provider": "static_config",
        "scanned_count": len(KR_INDEX_RECORDS),
        "created_count": result["created_count"],
        "updated_count": result["updated_count"],
        "message": "KR market index master synced from local config.",
    }


def list_kr_market_indices(db: Session, *, is_active: bool | None = True) -> list[dict]:
    configured = {
        record.index_id: _kr_index_record_dict(record)
        for record in KR_INDEX_RECORDS
    }
    query = db.query(KRMarketIndex)
    if is_active is not None:
        query = query.filter(KRMarketIndex.is_active.is_(is_active))

    for row in query.all():
        configured[row.index_id] = _kr_index_row_dict(row)

    rows = list(configured.values())
    if is_active is not None:
        rows = [row for row in rows if bool(row["is_active"]) is is_active]
    return sorted(rows, key=lambda row: (int(row["sort_order"]), str(row["index_id"])))


def get_kr_market_index_config(db: Session, *, index_id: str) -> dict:
    normalized_index_id = _valid_index_id(index_id)
    row = (
        db.query(KRMarketIndex)
        .filter(KRMarketIndex.index_id == normalized_index_id)
        .first()
    )
    if row is not None:
        return _kr_index_row_dict(row)

    record = KR_INDEX_CONFIG_BY_ID.get(normalized_index_id)
    if record is None:
        raise KRIndexNotFoundError(f"KR index_id='{normalized_index_id}' was not found.")
    return _kr_index_record_dict(record)


def upsert_kr_index_daily_price_records(
    db: Session,
    records: list[KRIndexDailyPriceRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(KRIndexDailyPrice)
            .filter(KRIndexDailyPrice.provider == record.provider)
            .filter(KRIndexDailyPrice.index_id == record.index_id)
            .filter(KRIndexDailyPrice.trade_date == record.trade_date)
            .first()
        )

        if existing is None:
            db.add(
                KRIndexDailyPrice(
                    provider=record.provider,
                    index_id=record.index_id,
                    trade_date=record.trade_date,
                    currency=record.currency,
                    open_value=record.open_value,
                    high_value=record.high_value,
                    low_value=record.low_value,
                    close_value=record.close_value,
                    price_change=record.price_change,
                    change_pct=record.change_pct,
                    trade_volume=record.trade_volume,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.currency = record.currency
        existing.open_value = record.open_value
        existing.high_value = record.high_value
        existing.low_value = record.low_value
        existing.close_value = record.close_value
        existing.price_change = record.price_change
        existing.change_pct = record.change_pct
        existing.trade_volume = record.trade_volume
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()
    return {"inserted_count": inserted_count, "updated_count": updated_count}


def _kr_index_refresh_window(
    *,
    outputsize: str,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    if outputsize not in {"compact", "full"}:
        raise ValueError("outputsize must be one of: compact, full.")

    resolved_end_date = end_date or date.today()
    if start_date is not None:
        return start_date, resolved_end_date

    lookback_days = (
        KR_INDEX_COMPACT_LOOKBACK_DAYS
        if outputsize == "compact"
        else KR_INDEX_FULL_LOOKBACK_DAYS
    )
    return resolved_end_date - timedelta(days=lookback_days), resolved_end_date


@_translate_kr_provider_errors
def refresh_kr_index_daily_prices(
    db: Session,
    *,
    index_id: str,
    outputsize: str = "compact",
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    normalized_index_id = _valid_index_id(index_id)
    index_config = KR_INDEX_CONFIG_BY_ID[normalized_index_id]
    resolved_start_date, resolved_end_date = _kr_index_refresh_window(
        outputsize=outputsize,
        start_date=start_date,
        end_date=end_date,
    )
    if resolved_start_date > resolved_end_date:
        raise ValueError("start_date must be before or equal to end_date.")

    upsert_kr_index_records(db, [index_config])
    payload_text, source_url = fetch_naver_index_chart_payload(
        provider_symbol=index_config.provider_symbol,
        start_date=resolved_start_date,
        end_date=resolved_end_date,
        timeout_seconds=settings.kr_market_http_timeout_seconds,
    )
    records = parse_naver_index_daily_prices(
        payload_text,
        index_id=normalized_index_id,
        source_url=source_url,
    )
    result = upsert_kr_index_daily_price_records(db, records)

    return {
        "status": "success",
        "provider": "naver_sise_index",
        "index_id": normalized_index_id,
        "provider_symbol": index_config.provider_symbol,
        "from_date": resolved_start_date,
        "to_date": resolved_end_date,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "KR index daily prices refreshed from Naver Finance.",
    }


@_translate_kr_provider_errors
def refresh_kr_market_indices(
    db: Session,
    *,
    index_ids: list[str] | None = None,
    outputsize: str = "compact",
    start_date: date | None = None,
    end_date: date | None = None,
    progress: ProgressCallback | None = None,
) -> dict:
    requested_ids = index_ids or [record.index_id for record in KR_INDEX_RECORDS]
    normalized_ids = [_valid_index_id(index_id) for index_id in requested_ids]
    total = len(normalized_ids)
    results: list[dict] = []
    success_count = 0
    error_count = 0

    sync_kr_index_master(db)
    for current, normalized_index_id in enumerate(normalized_ids, start=1):
        if progress:
            progress(current - 1, total, f"Refreshing KR index {normalized_index_id}.")
        try:
            result = refresh_kr_index_daily_prices(
                db=db,
                index_id=normalized_index_id,
                outputsize=outputsize,
                start_date=start_date,
                end_date=end_date,
            )
            success_count += 1
        except Exception as exc:
            db.rollback()
            result = {
                "status": "error",
                "provider": "naver_sise_index",
                "index_id": normalized_index_id,
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": str(exc),
            }
            error_count += 1
        results.append(result)

    if progress:
        progress(total, total, "KR index refresh completed.")

    return {
        "status": "success" if error_count == 0 else ("error" if success_count == 0 else "partial_success"),
        "provider": "naver_sise_index",
        "requested_index_count": total,
        "success_count": success_count,
        "error_count": error_count,
        "fetched_count": sum(int(result.get("fetched_count") or 0) for result in results),
        "inserted_count": sum(int(result.get("inserted_count") or 0) for result in results),
        "updated_count": sum(int(result.get("updated_count") or 0) for result in results),
        "results": results,
        "message": "KR market index refresh completed.",
    }


def _kr_index_breadth_segment(index_id: str) -> tuple[str, str, str | None]:
    normalized_index_id = _valid_index_id(index_id)
    index_config = KR_INDEX_CONFIG_BY_ID[normalized_index_id]
    segment = index_config.market_segment.upper()
    suffix = ".KQ" if segment == "KOSDAQ" else ".KS"
    note = None
    if normalized_index_id == "KOSPI200":
        note = "KOSPI 200 成分股廣度尚未接入；目前使用 KOSPI 公開市場廣度作為 proxy。"
    else:
        note = "KRX 公開日報市場廣度。"
    return segment, suffix, note


@_translate_kr_provider_errors
def refresh_kr_market_breadth_daily_prices(
    db: Session,
    *,
    trade_date: date | None = None,
    market_id: str = "ALL",
) -> dict:
    normalized_market_id = (market_id or "ALL").strip().upper()
    try:
        payload, source_url = fetch_krx_daily_price_payload(
            local_code=None,
            market_id=normalized_market_id,
            trade_date=trade_date,
            timeout_seconds=settings.kr_market_http_timeout_seconds,
        )
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None and response.status_code == 400:
            raise KRMarketDataFetchError(
                "KRX daily price endpoint rejected the all-market breadth request. "
                "The current KRX bld accepts per-symbol daily quotes but not blank isuCd market-wide breadth."
            ) from exc
        raise
    records = parse_krx_daily_price_records(
        payload,
        trade_date=trade_date,
        source_url=source_url,
    )
    if not records:
        raise KRMarketDataFetchError("KRX daily price returned no market breadth rows.")

    result = upsert_kr_daily_price_records(db, records)
    resolved_trade_date = max(record.trade_date for record in records)

    return {
        "status": "success",
        "provider": "krx_data",
        "market_id": normalized_market_id,
        "trade_date": resolved_trade_date,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "KR market breadth daily prices refreshed from KRX Data.",
    }


def get_kr_market_breadth(
    db: Session,
    *,
    index_id: str,
    trade_date: date | None = None,
) -> dict:
    normalized_index_id = _valid_index_id(index_id)
    segment, suffix, coverage_note = _kr_index_breadth_segment(normalized_index_id)
    query = db.query(KRDailyPrice).filter(KRDailyPrice.symbol.like(f"%{suffix}"))
    target_trade_date = trade_date

    if target_trade_date is None:
        latest_date_row = (
            query.with_entities(KRDailyPrice.trade_date)
            .order_by(KRDailyPrice.trade_date.desc())
            .first()
        )
        target_trade_date = latest_date_row[0] if latest_date_row else None

    if target_trade_date is None:
        return {
            "index_id": normalized_index_id,
            "market_segment": segment,
            "trade_date": None,
            "advance_count": 0,
            "decline_count": 0,
            "unchanged_count": 0,
            "total_count": 0,
            "positive_ratio": None,
            "advance_decline_ratio": None,
            "average_change_pct": None,
            "trade_value": None,
            "source": None,
            "status": "empty",
            "coverage_note": coverage_note,
        }

    rows = (
        query.filter(KRDailyPrice.trade_date == target_trade_date)
        .order_by(KRDailyPrice.symbol.asc(), KRDailyPrice.provider.asc(), KRDailyPrice.id.desc())
        .all()
    )
    latest_by_symbol: OrderedDict[str, KRDailyPrice] = OrderedDict()
    for row in rows:
        current = latest_by_symbol.get(row.symbol)
        current_priority = KR_DAILY_PROVIDER_PRIORITY.get(current.provider, 99) if current else 99
        row_priority = KR_DAILY_PROVIDER_PRIORITY.get(row.provider, 99)
        if current is None or row_priority < current_priority or (
            row_priority == current_priority and row.id > current.id
        ):
            latest_by_symbol[row.symbol] = row

    advance_count = 0
    decline_count = 0
    unchanged_count = 0
    change_pct_values: list[float] = []
    trade_value = 0
    has_trade_value = False
    excluded_change_count = 0
    sources: set[str] = set()

    for row in latest_by_symbol.values():
        if row.provider:
            sources.add(row.provider)
        if row.trade_value is not None:
            trade_value += row.trade_value
            has_trade_value = True

        change_value = row.price_change
        if change_value is None and row.change_pct is not None:
            change_value = row.change_pct
        if change_value is None:
            excluded_change_count += 1
            continue

        if change_value > 0:
            advance_count += 1
        elif change_value < 0:
            decline_count += 1
        else:
            unchanged_count += 1
        if row.change_pct is not None:
            change_pct_values.append(row.change_pct)

    total_count = advance_count + decline_count + unchanged_count
    positive_ratio = advance_count / total_count if total_count else None
    advance_decline_ratio = advance_count / decline_count if decline_count else None
    average_change_pct = (
        sum(change_pct_values) / len(change_pct_values)
        if change_pct_values
        else None
    )
    source = "+".join(sorted(sources)) if sources else None
    status = "empty" if not latest_by_symbol else ("partial" if excluded_change_count else "current")
    if excluded_change_count:
        coverage_note = (
            f"{coverage_note} 已排除 {excluded_change_count} 筆缺少漲跌欄位的資料。"
            if coverage_note
            else f"已排除 {excluded_change_count} 筆缺少漲跌欄位的資料。"
        )

    return {
        "index_id": normalized_index_id,
        "market_segment": segment,
        "trade_date": target_trade_date,
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "positive_ratio": positive_ratio,
        "advance_decline_ratio": advance_decline_ratio,
        "average_change_pct": average_change_pct,
        "trade_value": trade_value if has_trade_value else None,
        "source": source,
        "status": status,
        "coverage_note": coverage_note,
    }


def upsert_kr_daily_price_records(db: Session, records: list[KRDailyPriceRecord]) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(KRDailyPrice)
            .filter(KRDailyPrice.provider == record.provider)
            .filter(KRDailyPrice.symbol == record.symbol)
            .filter(KRDailyPrice.trade_date == record.trade_date)
            .first()
        )

        if existing is None:
            db.add(
                KRDailyPrice(
                    provider=record.provider,
                    symbol=record.symbol,
                    trade_date=record.trade_date,
                    currency=record.currency,
                    open_price=record.open_price,
                    high_price=record.high_price,
                    low_price=record.low_price,
                    close_price=record.close_price,
                    adjusted_close=record.adjusted_close,
                    price_change=record.price_change,
                    change_pct=record.change_pct,
                    trade_volume=record.trade_volume,
                    trade_value=record.trade_value,
                    market_cap=record.market_cap,
                    listed_shares=record.listed_shares,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.currency = record.currency
        existing.open_price = record.open_price
        existing.high_price = record.high_price
        existing.low_price = record.low_price
        existing.close_price = record.close_price
        existing.adjusted_close = record.adjusted_close
        existing.price_change = record.price_change
        existing.change_pct = record.change_pct
        existing.trade_volume = record.trade_volume
        existing.trade_value = record.trade_value
        existing.market_cap = record.market_cap
        existing.listed_shares = record.listed_shares
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"inserted_count": inserted_count, "updated_count": updated_count}


def _yahoo_daily_range_for_outputsize(outputsize: str) -> str:
    if outputsize == "compact":
        return KR_YAHOO_CHART_COMPACT_RANGE
    return KR_YAHOO_CHART_FULL_RANGE


def refresh_kr_daily_prices_from_yahoo_chart(
    db: Session,
    *,
    symbol: str,
    outputsize: str = "compact",
) -> dict:
    if outputsize not in {"compact", "full"}:
        raise ValueError("outputsize must be one of: compact, full.")

    normalized_symbol = _valid_symbol(symbol)
    payload, source_url = fetch_yahoo_chart_payload(
        symbol=normalized_symbol,
        range_value=_yahoo_daily_range_for_outputsize(outputsize),
        interval="1d",
        timeout_seconds=settings.kr_market_http_timeout_seconds,
    )
    upsert_kr_stock_record(db, parse_yahoo_stock_record(payload, symbol=normalized_symbol))
    records = parse_yahoo_daily_prices(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
    )
    result = upsert_kr_daily_price_records(db, records)

    return {
        "status": "success",
        "provider": "yahoo_chart",
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "KR daily prices refreshed from Yahoo chart fallback.",
    }


def refresh_kr_daily_prices_from_krx_data(
    db: Session,
    *,
    symbol: str,
    trade_date: date | None = None,
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    local_code = local_code_from_symbol(normalized_symbol)
    payload, source_url = fetch_krx_daily_price_payload(
        local_code=local_code,
        trade_date=trade_date,
        timeout_seconds=settings.kr_market_http_timeout_seconds,
    )
    records = parse_krx_daily_price_records(
        payload,
        symbol=normalized_symbol,
        trade_date=trade_date,
        source_url=source_url,
    )
    if not records:
        raise KRMarketDataFetchError(f"KRX daily price returned no rows for symbol='{normalized_symbol}'.")

    upsert_kr_stock_record(db, _minimal_stock_record(normalized_symbol, listing_source="krx_data_daily"))
    result = upsert_kr_daily_price_records(db, records)

    return {
        "status": "success",
        "provider": "krx_data",
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "KR daily prices refreshed from KRX Data.",
    }


@_translate_kr_provider_errors
def refresh_kr_daily_prices(
    db: Session,
    *,
    symbol: str,
    outputsize: str = "compact",
    provider: str = "auto",
    trade_date: date | None = None,
) -> dict:
    normalized_provider = _valid_provider(provider)

    if normalized_provider == "yahoo_chart":
        return refresh_kr_daily_prices_from_yahoo_chart(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
        )

    if normalized_provider == "krx_data":
        return refresh_kr_daily_prices_from_krx_data(
            db=db,
            symbol=symbol,
            trade_date=trade_date,
        )

    try:
        return refresh_kr_daily_prices_from_krx_data(
            db=db,
            symbol=symbol,
            trade_date=trade_date,
        )
    except (KRMarketDataFetchError, requests.RequestException) as exc:
        fallback = refresh_kr_daily_prices_from_yahoo_chart(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
        )
        fallback["status"] = "partial_success"
        fallback["message"] = (
            "KRX daily price refresh failed or returned no data; "
            f"used Yahoo chart fallback. krx_error={exc}"
        )
        return fallback


def list_kr_daily_prices(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[KRDailyPrice]:
    normalized_symbol = _valid_symbol(symbol)
    query = db.query(KRDailyPrice).filter(KRDailyPrice.symbol == normalized_symbol)

    if provider is not None:
        query = query.filter(KRDailyPrice.provider == provider)
    if from_date is not None:
        query = query.filter(KRDailyPrice.trade_date >= from_date)
    if to_date is not None:
        query = query.filter(KRDailyPrice.trade_date <= to_date)

    return (
        query.order_by(KRDailyPrice.trade_date.desc(), KRDailyPrice.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def _latest_distinct_kr_daily_rows(
    *,
    db: Session,
    symbol: str,
    limit: int,
) -> list[KRDailyPrice]:
    rows = (
        db.query(KRDailyPrice)
        .filter(KRDailyPrice.symbol == symbol)
        .order_by(
            KRDailyPrice.trade_date.desc(),
            KRDailyPrice.provider.asc(),
            KRDailyPrice.id.desc(),
        )
        .limit(limit * 3)
        .all()
    )
    distinct: list[KRDailyPrice] = []
    seen_dates: set[date] = set()
    provider_priority = {"krx_data": 0, "yahoo_chart": 1}

    grouped: OrderedDict[date, list[KRDailyPrice]] = OrderedDict()
    for row in rows:
        grouped.setdefault(row.trade_date, []).append(row)

    for row_date, date_rows in grouped.items():
        if row_date in seen_dates:
            continue
        date_rows.sort(key=lambda row: (provider_priority.get(row.provider, 99), -row.id))
        distinct.append(date_rows[0])
        seen_dates.add(row_date)
        if len(distinct) >= limit:
            break

    return distinct


def upsert_kr_company_fundamental_records(
    db: Session,
    records: list[KRCompanyFundamentalRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(KRCompanyFundamental)
            .filter(KRCompanyFundamental.provider == record.provider)
            .filter(KRCompanyFundamental.symbol == record.symbol)
            .filter(KRCompanyFundamental.fiscal_year == record.fiscal_year)
            .filter(KRCompanyFundamental.report_code == record.report_code)
            .filter(KRCompanyFundamental.statement_name == record.statement_name)
            .filter(KRCompanyFundamental.account_name == record.account_name)
            .first()
        )

        if existing is None:
            db.add(KRCompanyFundamental(**record.__dict__, fetched_at=utc_now()))
            inserted_count += 1
            continue

        for key, value in record.__dict__.items():
            setattr(existing, key, value)
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()
    return {"inserted_count": inserted_count, "updated_count": updated_count}


def _latest_kr_corp_code(db: Session, *, symbol: str) -> str | None:
    latest = (
        db.query(KRCompanyFundamental)
        .filter(KRCompanyFundamental.symbol == symbol)
        .filter(KRCompanyFundamental.corp_code.isnot(None))
        .order_by(KRCompanyFundamental.fetched_at.desc(), KRCompanyFundamental.id.desc())
        .first()
    )
    return latest.corp_code if latest else None


@_translate_kr_provider_errors
def refresh_kr_company_fundamental(
    db: Session,
    *,
    symbol: str,
    corp_code: str | None = None,
    fiscal_year: int | None = None,
    report_code: str = "11011",
    fs_div: str = "CFS",
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    api_key = settings.opendart_api_key
    if not api_key:
        return {
            "status": "skipped",
            "provider": "opendart_fnltt_singl_acnt_all",
            "symbol": normalized_symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "OpenDART API key is not configured; KR fundamentals refresh skipped.",
        }

    resolved_corp_code = (corp_code or _latest_kr_corp_code(db, symbol=normalized_symbol) or "").strip()
    if not resolved_corp_code:
        return {
            "status": "skipped",
            "provider": "opendart_fnltt_singl_acnt_all",
            "symbol": normalized_symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "OpenDART corp_code is required for KR fundamentals refresh.",
        }

    resolved_fiscal_year = fiscal_year or date.today().year - 1
    payload, source_url = fetch_opendart_financial_statement_payload(
        base_url=settings.opendart_api_base_url,
        api_key=api_key,
        corp_code=resolved_corp_code,
        fiscal_year=resolved_fiscal_year,
        report_code=report_code,
        fs_div=fs_div,
        timeout_seconds=settings.kr_market_http_timeout_seconds,
    )
    records = parse_opendart_company_fundamental_records(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
    )
    result = upsert_kr_company_fundamental_records(db, records)

    return {
        "status": "success" if records else "empty",
        "provider": "opendart_fnltt_singl_acnt_all",
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "KR fundamentals refreshed from OpenDART."
        if records
        else "OpenDART returned no fundamentals rows for the requested company/year/report.",
    }


def list_kr_company_fundamentals(
    db: Session,
    *,
    symbol: str | None = None,
    provider: str | None = None,
    fiscal_year: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[KRCompanyFundamental]:
    query = db.query(KRCompanyFundamental)
    if symbol is not None:
        query = query.filter(KRCompanyFundamental.symbol == _valid_symbol(symbol))
    if provider is not None:
        query = query.filter(KRCompanyFundamental.provider == provider)
    if fiscal_year is not None:
        query = query.filter(KRCompanyFundamental.fiscal_year == fiscal_year)
    return (
        query.order_by(
            KRCompanyFundamental.fiscal_year.desc().nullslast(),
            KRCompanyFundamental.disclosed_date.desc().nullslast(),
            KRCompanyFundamental.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def upsert_kr_investor_trade_records(
    db: Session,
    records: list[KRInvestorTradeRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(KRInvestorTradeDaily)
            .filter(KRInvestorTradeDaily.provider == record.provider)
            .filter(KRInvestorTradeDaily.symbol == record.symbol)
            .filter(KRInvestorTradeDaily.trade_date == record.trade_date)
            .filter(KRInvestorTradeDaily.investor_type == record.investor_type)
            .first()
        )

        if existing is None:
            db.add(KRInvestorTradeDaily(**record.__dict__, fetched_at=utc_now()))
            inserted_count += 1
            continue

        for key, value in record.__dict__.items():
            setattr(existing, key, value)
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()
    return {"inserted_count": inserted_count, "updated_count": updated_count}


def refresh_kr_investor_trades_from_krx(
    db: Session,
    *,
    symbol: str,
    trade_date: date | None = None,
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    payload, source_url = fetch_krx_investor_trade_payload(
        local_code=local_code_from_symbol(normalized_symbol),
        trade_date=trade_date,
        timeout_seconds=settings.kr_market_http_timeout_seconds,
    )
    records = parse_krx_investor_trade_records(
        payload,
        symbol=normalized_symbol,
        trade_date=trade_date,
        source_url=source_url,
    )
    result = upsert_kr_investor_trade_records(db, records)

    return {
        "status": "success" if records else "empty",
        "provider": "krx_investor_trading",
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "KR investor trading refreshed from KRX Data."
        if records
        else "KRX investor trading returned no rows for the requested symbol/date.",
    }


def list_kr_investor_trades(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[KRInvestorTradeDaily]:
    normalized_symbol = _valid_symbol(symbol)
    query = db.query(KRInvestorTradeDaily).filter(KRInvestorTradeDaily.symbol == normalized_symbol)
    if provider is not None:
        query = query.filter(KRInvestorTradeDaily.provider == provider)
    if from_date is not None:
        query = query.filter(KRInvestorTradeDaily.trade_date >= from_date)
    if to_date is not None:
        query = query.filter(KRInvestorTradeDaily.trade_date <= to_date)
    return (
        query.order_by(KRInvestorTradeDaily.trade_date.desc(), KRInvestorTradeDaily.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_kr_watchlist_group(db: Session, group_id: int) -> KRWatchlistGroup:
    group = db.query(KRWatchlistGroup).filter(KRWatchlistGroup.id == group_id).first()
    if group is None:
        raise KRWatchlistGroupNotFoundError(f"KR watchlist group id={group_id} not found.")
    return group


def _validate_kr_watchlist_parent(
    db: Session,
    group_id: int | None,
    parent_id: int | None,
) -> None:
    if parent_id is None:
        return

    parent = db.query(KRWatchlistGroup).filter(KRWatchlistGroup.id == parent_id).first()
    if parent is None:
        raise KRWatchlistGroupNotFoundError(f"Parent KR watchlist group id={parent_id} not found.")
    if group_id is not None and parent_id == group_id:
        raise KRWatchlistInvalidTreeError("A KR watchlist group cannot be its own parent.")

    current = parent
    while current is not None:
        if group_id is not None and current.id == group_id:
            raise KRWatchlistInvalidTreeError("Cannot move a KR watchlist group under its descendant.")
        if current.parent_id is None:
            break
        current = db.query(KRWatchlistGroup).filter(KRWatchlistGroup.id == current.parent_id).first()


def create_kr_watchlist_group(db: Session, payload: KRWatchlistGroupCreate) -> KRWatchlistGroup:
    _validate_kr_watchlist_parent(db=db, group_id=None, parent_id=payload.parent_id)
    group = KRWatchlistGroup(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def list_kr_watchlist_groups(
    db: Session,
    *,
    is_active: bool | None = None,
) -> list[KRWatchlistGroup]:
    query = db.query(KRWatchlistGroup)
    if is_active is not None:
        query = query.filter(KRWatchlistGroup.is_active.is_(is_active))
    return (
        query.order_by(
            KRWatchlistGroup.parent_id.asc().nullsfirst(),
            KRWatchlistGroup.sort_order.asc(),
            KRWatchlistGroup.id.asc(),
        )
        .all()
    )


def _kr_group_to_tree_node(
    group: KRWatchlistGroup,
    children_by_parent: dict[int | None, list[KRWatchlistGroup]],
) -> dict:
    return {
        "id": group.id,
        "parent_id": group.parent_id,
        "group_name": group.group_name,
        "description": group.description,
        "sort_order": group.sort_order,
        "is_active": group.is_active,
        "children": [
            _kr_group_to_tree_node(child, children_by_parent)
            for child in children_by_parent.get(group.id, [])
        ],
    }


def get_kr_watchlist_tree(db: Session, *, is_active: bool | None = True) -> list[dict]:
    groups = list_kr_watchlist_groups(db=db, is_active=is_active)
    children_by_parent: dict[int | None, list[KRWatchlistGroup]] = {}
    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group)
    return [
        _kr_group_to_tree_node(group, children_by_parent)
        for group in children_by_parent.get(None, [])
    ]


def update_kr_watchlist_group(
    db: Session,
    group_id: int,
    payload: KRWatchlistGroupUpdate,
) -> KRWatchlistGroup:
    group = get_kr_watchlist_group(db, group_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "parent_id" in update_data:
        _validate_kr_watchlist_parent(db=db, group_id=group_id, parent_id=update_data["parent_id"])
    for key, value in update_data.items():
        setattr(group, key, value)
    db.commit()
    db.refresh(group)
    return group


def _get_kr_descendant_group_ids(db: Session, group_id: int) -> list[int]:
    get_kr_watchlist_group(db, group_id)
    groups = db.query(KRWatchlistGroup).all()
    children_by_parent: dict[int | None, list[int]] = {}
    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group.id)

    result: list[int] = []
    stack = [group_id]
    while stack:
        current_id = stack.pop()
        result.append(current_id)
        stack.extend(children_by_parent.get(current_id, []))
    return result


def delete_kr_watchlist_group(
    db: Session,
    group_id: int,
    *,
    recursive: bool = False,
) -> dict:
    get_kr_watchlist_group(db, group_id)
    descendant_ids = _get_kr_descendant_group_ids(db, group_id)
    child_count = len(descendant_ids) - 1
    item_count = (
        db.query(KRWatchlistItem)
        .filter(KRWatchlistItem.group_id.in_(descendant_ids))
        .count()
    )
    if not recursive and (child_count > 0 or item_count > 0):
        raise KRWatchlistGroupNotEmptyError(
            "KR watchlist group is not empty. Use recursive=true to delete children and items."
        )

    db.query(KRWatchlistItem).filter(KRWatchlistItem.group_id.in_(descendant_ids)).delete(
        synchronize_session=False
    )
    db.query(KRWatchlistGroup).filter(KRWatchlistGroup.id.in_(descendant_ids)).delete(
        synchronize_session=False
    )
    db.commit()
    return {
        "deleted_group_id": group_id,
        "deleted_item_count": item_count,
        "deleted_group_count": len(descendant_ids),
    }


def _kr_watchlist_item_to_dict(db: Session, item: KRWatchlistItem) -> dict:
    stock = (
        db.query(KRStockMaster)
        .filter(KRStockMaster.symbol == item.symbol)
        .first()
    )
    return {
        "id": item.id,
        "group_id": item.group_id,
        "symbol": item.symbol,
        "local_code": stock.local_code if stock else None,
        "security_name": stock.security_name if stock else None,
        "security_name_kr": stock.security_name_kr if stock else None,
        "exchange": stock.exchange if stock else None,
        "market_segment": stock.market_segment if stock else None,
        "sector": stock.sector if stock else None,
        "industry": stock.industry if stock else None,
        "asset_type": stock.asset_type if stock else None,
        "note": item.note,
        "priority": item.priority,
        "tags": item.tags,
        "enabled": item.enabled,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def create_kr_watchlist_item(db: Session, payload: KRWatchlistItemCreate) -> dict:
    get_kr_watchlist_group(db, payload.group_id)
    stock = get_kr_stock(db=db, symbol=payload.symbol)
    payload_data = payload.model_dump()
    payload_data["symbol"] = stock.symbol
    item = KRWatchlistItem(**payload_data)
    db.add(item)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise KRWatchlistDuplicateItemError(
            f"KR symbol='{stock.symbol}' already exists in group id={payload.group_id}."
        ) from exc

    db.refresh(item)
    return _kr_watchlist_item_to_dict(db, item)


def get_kr_watchlist_item(db: Session, item_id: int) -> KRWatchlistItem:
    item = db.query(KRWatchlistItem).filter(KRWatchlistItem.id == item_id).first()
    if item is None:
        raise KRWatchlistItemNotFoundError(f"KR watchlist item id={item_id} not found.")
    return item


def list_kr_watchlist_items(
    db: Session,
    *,
    group_id: int | None = None,
    symbol: str | None = None,
    enabled: bool | None = None,
    include_children: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    query = db.query(KRWatchlistItem)
    if group_id is not None:
        get_kr_watchlist_group(db, group_id)
        if include_children:
            query = query.filter(KRWatchlistItem.group_id.in_(_get_kr_descendant_group_ids(db, group_id)))
        else:
            query = query.filter(KRWatchlistItem.group_id == group_id)
    if symbol is not None:
        query = query.filter(KRWatchlistItem.symbol == _valid_symbol(symbol))
    if enabled is not None:
        query = query.filter(KRWatchlistItem.enabled.is_(enabled))
    items = (
        query.order_by(KRWatchlistItem.priority.asc(), KRWatchlistItem.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_kr_watchlist_item_to_dict(db, item) for item in items]


def update_kr_watchlist_item(
    db: Session,
    item_id: int,
    payload: KRWatchlistItemUpdate,
) -> dict:
    item = get_kr_watchlist_item(db, item_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "group_id" in update_data and update_data["group_id"] is not None:
        get_kr_watchlist_group(db, update_data["group_id"])
    if "symbol" in update_data and update_data["symbol"] is not None:
        stock = get_kr_stock(db=db, symbol=update_data["symbol"])
        update_data["symbol"] = stock.symbol
    for key, value in update_data.items():
        setattr(item, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise KRWatchlistDuplicateItemError(
            f"KR symbol='{item.symbol}' already exists in group id={item.group_id}."
        ) from exc
    db.refresh(item)
    return _kr_watchlist_item_to_dict(db, item)


def delete_kr_watchlist_item(db: Session, item_id: int) -> None:
    item = get_kr_watchlist_item(db, item_id)
    db.delete(item)
    db.commit()


def list_kr_watchlist_symbols(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
) -> list[str]:
    query = db.query(KRWatchlistItem)
    if group_id is not None:
        get_kr_watchlist_group(db, group_id)
        group_ids = _get_kr_descendant_group_ids(db, group_id) if include_children else [group_id]
        query = query.filter(KRWatchlistItem.group_id.in_(group_ids))
    if enabled_only:
        query = query.filter(KRWatchlistItem.enabled.is_(True))
    rows = query.order_by(KRWatchlistItem.priority.asc(), KRWatchlistItem.id.asc()).all()
    symbols: list[str] = []
    seen: set[str] = set()
    for row in rows:
        symbol = normalize_kr_symbol(row.symbol)
        if not symbol or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)
    return symbols


def _latest_kr_daily_row(db: Session, *, symbol: str) -> KRDailyPrice | None:
    rows = _latest_distinct_kr_daily_rows(db=db, symbol=symbol, limit=1)
    return rows[0] if rows else None


def _daily_readiness_status(
    *,
    latest_date: date | None,
    expected_date: date | None,
    row_count: int,
) -> str:
    if row_count <= 0 or latest_date is None:
        return "empty"
    if expected_date is not None and latest_date < expected_date:
        return "stale"
    return "current"


def get_kr_watchlist_readiness(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    expected_daily_date: date | None = None,
) -> dict:
    query = db.query(KRWatchlistItem)
    if group_id is not None:
        get_kr_watchlist_group(db, group_id)
        group_ids = _get_kr_descendant_group_ids(db, group_id) if include_children else [group_id]
        query = query.filter(KRWatchlistItem.group_id.in_(group_ids))
    if enabled_only:
        query = query.filter(KRWatchlistItem.enabled.is_(True))

    items = query.order_by(KRWatchlistItem.priority.asc(), KRWatchlistItem.id.asc()).all()
    unique_items: list[KRWatchlistItem] = []
    seen_symbols: set[str] = set()
    for item in items:
        symbol = normalize_kr_symbol(item.symbol)
        if not symbol or symbol in seen_symbols:
            continue
        unique_items.append(item)
        seen_symbols.add(symbol)

    symbols = [normalize_kr_symbol(item.symbol) for item in unique_items]
    stocks_by_symbol = {
        stock.symbol: stock
        for stock in db.query(KRStockMaster).filter(KRStockMaster.symbol.in_(symbols)).all()
    } if symbols else {}
    expected_date = expected_daily_date or expected_kr_daily_price_date()
    rows: list[dict] = []

    for item in unique_items:
        symbol = normalize_kr_symbol(item.symbol)
        stock = stocks_by_symbol.get(symbol)
        latest_daily = _latest_kr_daily_row(db, symbol=symbol)
        daily_count = db.query(KRDailyPrice).filter(KRDailyPrice.symbol == symbol).count()
        latest_investor = (
            db.query(KRInvestorTradeDaily)
            .filter(KRInvestorTradeDaily.symbol == symbol)
            .order_by(KRInvestorTradeDaily.trade_date.desc(), KRInvestorTradeDaily.id.desc())
            .first()
        )
        investor_count = db.query(KRInvestorTradeDaily).filter(KRInvestorTradeDaily.symbol == symbol).count()
        latest_fundamental = (
            db.query(KRCompanyFundamental)
            .filter(KRCompanyFundamental.symbol == symbol)
            .order_by(
                KRCompanyFundamental.disclosed_date.desc().nullslast(),
                KRCompanyFundamental.fetched_at.desc(),
                KRCompanyFundamental.id.desc(),
            )
            .first()
        )
        fundamental_count = db.query(KRCompanyFundamental).filter(KRCompanyFundamental.symbol == symbol).count()
        daily_status = _daily_readiness_status(
            latest_date=latest_daily.trade_date if latest_daily else None,
            expected_date=expected_date,
            row_count=daily_count,
        )
        missing_resources: list[str] = []
        if daily_status == "empty":
            missing_resources.append("daily_price")
        elif daily_status == "stale":
            missing_resources.append("daily_price_stale")
        if investor_count <= 0:
            missing_resources.append("investor_trading")
        if fundamental_count <= 0:
            missing_resources.append("financials")

        if daily_status == "current" and investor_count > 0:
            readiness_status = "ready"
        elif daily_count > 0 or investor_count > 0 or fundamental_count > 0:
            readiness_status = "partial"
        else:
            readiness_status = "no_data"

        rows.append(
            {
                "symbol": symbol,
                "security_name": stock.security_name if stock else None,
                "group_id": item.group_id,
                "market_segment": stock.market_segment if stock else None,
                "latest_daily_date": latest_daily.trade_date if latest_daily else None,
                "latest_daily_provider": latest_daily.provider if latest_daily else None,
                "daily_row_count": daily_count,
                "daily_status": daily_status,
                "latest_investor_date": latest_investor.trade_date if latest_investor else None,
                "investor_row_count": investor_count,
                "latest_fundamental_date": latest_fundamental.disclosed_date if latest_fundamental else None,
                "fundamental_row_count": fundamental_count,
                "readiness_status": readiness_status,
                "missing_resources": missing_resources,
            }
        )

    summary = {
        "requested_symbol_count": len(rows),
        "ready_count": sum(1 for row in rows if row["readiness_status"] == "ready"),
        "partial_count": sum(1 for row in rows if row["readiness_status"] == "partial"),
        "no_data_count": sum(1 for row in rows if row["readiness_status"] == "no_data"),
        "daily_current_count": sum(1 for row in rows if row["daily_status"] == "current"),
        "daily_stale_count": sum(1 for row in rows if row["daily_status"] == "stale"),
        "daily_empty_count": sum(1 for row in rows if row["daily_status"] == "empty"),
        "investor_available_count": sum(1 for row in rows if row["investor_row_count"] > 0),
        "fundamental_available_count": sum(1 for row in rows if row["fundamental_row_count"] > 0),
    }

    return {
        "kind": "kr_watchlist_readiness",
        "group_id": group_id,
        "include_children": include_children,
        "enabled_only": enabled_only,
        "expected_daily_price_date": expected_date,
        "summary": summary,
        "results": rows,
    }


def _kr_ranking_freshness(
    rows: list[dict],
    *,
    requested_symbol_count: int,
    expected_trade_date: date | None = None,
) -> dict:
    target_trade_date = expected_trade_date or expected_kr_daily_price_date()
    row_dates = [
        row.get("trade_date")
        for row in rows
        if isinstance(row.get("trade_date"), date)
    ]
    latest_trade_date = max(row_dates, default=None)
    current_symbol_count = sum(
        1 for row_date in row_dates if row_date >= target_trade_date
    )
    stale_symbol_count = max(requested_symbol_count - current_symbol_count, 0)
    return {
        "trade_date": latest_trade_date,
        "target_trade_date": target_trade_date,
        "is_current": requested_symbol_count == 0 or stale_symbol_count == 0,
        "current_symbol_count": current_symbol_count,
        "stale_symbol_count": stale_symbol_count,
    }


def get_kr_watchlist_ranking(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "none",
    sort_order: str = "asc",
) -> dict:
    if rank_by not in {"none", "change_pct", "volume", "close"}:
        raise ValueError("rank_by must be one of: none, change_pct, volume, close.")
    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be one of: asc, desc.")

    query = db.query(KRWatchlistItem)
    if group_id is not None:
        get_kr_watchlist_group(db, group_id)
        group_ids = _get_kr_descendant_group_ids(db, group_id) if include_children else [group_id]
        query = query.filter(KRWatchlistItem.group_id.in_(group_ids))
    if enabled_only:
        query = query.filter(KRWatchlistItem.enabled.is_(True))

    items = query.order_by(KRWatchlistItem.priority.asc(), KRWatchlistItem.id.asc()).all()
    unique_items: list[KRWatchlistItem] = []
    seen_symbols: set[str] = set()
    for item in items:
        symbol = normalize_kr_symbol(item.symbol)
        if not symbol or symbol in seen_symbols:
            continue
        unique_items.append(item)
        seen_symbols.add(symbol)

    symbols = [normalize_kr_symbol(item.symbol) for item in unique_items]
    stocks_by_symbol = {
        stock.symbol: stock
        for stock in db.query(KRStockMaster).filter(KRStockMaster.symbol.in_(symbols)).all()
    } if symbols else {}
    rows: list[dict] = []

    for item in unique_items:
        symbol = normalize_kr_symbol(item.symbol)
        stock = stocks_by_symbol.get(symbol)
        price_rows = _latest_distinct_kr_daily_rows(db=db, symbol=symbol, limit=2)
        latest = price_rows[0] if price_rows else None
        previous = price_rows[1] if len(price_rows) > 1 else None
        close = _kr_close_value(latest)
        previous_close = _kr_close_value(previous)
        change = close - previous_close if close is not None and previous_close is not None else None
        change_pct = (change / previous_close) * 100 if change is not None and previous_close not in {None, 0} else None
        rows.append(
            {
                "rank": 0,
                "symbol": symbol,
                "security_name": stock.security_name if stock else None,
                "exchange": stock.exchange if stock else None,
                "market_segment": stock.market_segment if stock else None,
                "sector": stock.sector if stock else None,
                "industry": stock.industry if stock else None,
                "asset_type": stock.asset_type if stock else None,
                "group_id": item.group_id,
                "trade_date": latest.trade_date if latest else None,
                "close": close,
                "previous_close": previous_close,
                "change": change,
                "change_pct": change_pct,
                "volume": latest.trade_volume if latest else None,
                "status": "ready" if close is not None else "no_data",
                "source": latest.provider if latest else None,
                "error_message": None,
            }
        )

    if rank_by != "none":
        ranked_rows = [row for row in rows if row.get(rank_by) is not None]
        no_value_rows = [row for row in rows if row.get(rank_by) is None]
        ranked_rows.sort(key=lambda row: row[rank_by], reverse=sort_order == "desc")
        rows = ranked_rows + no_value_rows

    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    no_data_count = sum(1 for row in rows if row["status"] == "no_data")
    freshness = _kr_ranking_freshness(rows, requested_symbol_count=len(unique_items))
    return {
        "group_id": group_id,
        "include_children": include_children,
        "rank_by": rank_by,
        "sort_order": sort_order,
        "requested_symbol_count": len(rows),
        "ranked_count": len(rows) - no_data_count,
        "no_data_count": no_data_count,
        "error_count": 0,
        **freshness,
        "results": rows,
    }


def get_kr_watchlist_technical_radar(
    db: Session,
    *,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = "action",
    max_results: int = 30,
    calculation_limit: int = 100,
) -> dict:
    ranking = get_kr_watchlist_ranking(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by="none",
        sort_order="asc",
    )
    symbols = [
        normalize_kr_symbol(row.get("symbol"))
        for row in ranking.get("results", [])
        if normalize_kr_symbol(row.get("symbol"))
    ]
    histories: dict[str, list[TechnicalRadarBar]] = {}
    for symbol in symbols:
        daily_rows = _latest_distinct_kr_daily_rows(db=db, symbol=symbol, limit=calculation_limit)
        histories[symbol] = [
            TechnicalRadarBar(
                trade_date=row.trade_date,
                open=row.open_price,
                high=row.high_price,
                low=row.low_price,
                close=_kr_close_value(row),
                volume=row.trade_volume,
            )
            for row in reversed(daily_rows)
        ]
    return build_technical_watchlist_radar(
        ranking=ranking,
        histories=histories,
        market="KR",
        include_children=include_children,
        mode=mode,
        max_results=max_results,
    )


def refresh_kr_watchlist_resources(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_investors: bool = True,
    include_fundamentals: bool = False,
    outputsize: str = "compact",
    provider: str = "auto",
    sleep_seconds: float = 1.0,
    max_symbols: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    all_symbols = list_kr_watchlist_symbols(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )
    symbols = all_symbols[:max_symbols] if max_symbols is not None else all_symbols
    total = len(symbols)
    results: list[dict] = []
    symbol_error_count = 0
    resource_error_count = 0
    resource_attempt_count = 0
    resource_success_count = 0
    complete_symbol_count = 0
    partial_symbol_count = 0
    failed_symbol_count = 0

    if progress_callback:
        progress_callback(0, total or 1, "Starting KR watchlist resource refresh.")

    for index, symbol in enumerate(symbols, start=1):
        symbol_results: dict[str, dict] = {"symbol": symbol}
        symbol_had_error = False

        def capture_resource_error(resource_name: str, exc: Exception) -> None:
            nonlocal resource_error_count, symbol_had_error
            db.rollback()
            resource_error_count += 1
            symbol_had_error = True
            symbol_results[resource_name] = {
                "status": "error",
                "provider": "unknown",
                "symbol": symbol,
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": str(exc),
            }

        if include_daily:
            try:
                symbol_results["daily"] = refresh_kr_daily_prices(
                    db=db,
                    symbol=symbol,
                    outputsize=outputsize,
                    provider=provider,
                )
            except Exception as exc:
                capture_resource_error("daily", exc)

        if include_investors:
            try:
                symbol_results["investors"] = refresh_kr_investor_trades_from_krx(
                    db=db,
                    symbol=symbol,
                )
            except Exception as exc:
                capture_resource_error("investors", exc)

        if include_fundamentals:
            try:
                symbol_results["fundamentals"] = refresh_kr_company_fundamental(
                    db=db,
                    symbol=symbol,
                )
            except Exception as exc:
                capture_resource_error("fundamentals", exc)

        attempted_resources = [
            value
            for key, value in symbol_results.items()
            if key != "symbol" and isinstance(value, dict)
        ]
        successful_resources = [
            value
            for value in attempted_resources
            if value.get("status") != "error"
        ]
        resource_attempt_count += len(attempted_resources)
        resource_success_count += len(successful_resources)
        if symbol_had_error:
            symbol_error_count += 1
        if not attempted_resources:
            failed_symbol_count += 1
        elif len(successful_resources) == len(attempted_resources):
            complete_symbol_count += 1
        elif successful_resources:
            partial_symbol_count += 1
        else:
            failed_symbol_count += 1
        results.append(symbol_results)
        if progress_callback:
            progress_callback(index, total or 1, f"Refreshed KR resources for {symbol}.")
        if sleep_seconds > 0 and index < total:
            time.sleep(sleep_seconds)

    refreshed_count = complete_symbol_count + partial_symbol_count
    if resource_error_count == 0:
        status = "success"
    elif refreshed_count > 0:
        status = "partial_success"
    else:
        status = "error"
    return {
        "status": status,
        "group_id": group_id,
        "total_symbol_count": len(all_symbols),
        "requested_symbol_count": total,
        "refreshed_symbol_count": refreshed_count,
        "complete_symbol_count": complete_symbol_count,
        "partial_symbol_count": partial_symbol_count,
        "failed_symbol_count": failed_symbol_count,
        "error_count": symbol_error_count,
        "resource_attempt_count": resource_attempt_count,
        "resource_success_count": resource_success_count,
        "resource_error_count": resource_error_count,
        "include_daily": include_daily,
        "include_investors": include_investors,
        "include_fundamentals": include_fundamentals,
        "max_symbols": max_symbols,
        "provider": provider,
        "results": results,
        "message": (
            "KR watchlist resource refresh completed: "
            f"{refreshed_count}/{total} refreshed, "
            f"{complete_symbol_count} complete, {partial_symbol_count} partial, "
            f"{failed_symbol_count} failed."
        ),
    }


@_translate_kr_provider_errors
def refresh_kr_market_resource(
    db: Session,
    *,
    symbol: str,
    resource: str,
) -> dict:
    normalized_resource = resource.strip().lower()
    if normalized_resource in {"performance", "daily_price"}:
        return refresh_kr_daily_prices(db=db, symbol=symbol, provider="auto")
    if normalized_resource in {"financials", "fundamentals"}:
        return refresh_kr_company_fundamental(db=db, symbol=symbol)
    if normalized_resource in {"investors", "investor_trading", "demand"}:
        return refresh_kr_investor_trades_from_krx(db=db, symbol=symbol)
    if normalized_resource in KR_PLANNED_RESOURCE_KEYS:
        normalized_symbol = _valid_symbol(symbol)
        return {
            "status": "planned",
            "provider": "not_configured",
            "symbol": normalized_symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": f"KR resource '{normalized_resource}' is planned but not implemented in backend v1.",
        }
    raise ValueError("resource must be one of: demand, investors, disclosures, performance, financials.")


def _resource_slot(
    *,
    key: str,
    row_count: int,
    latest_date: date | None,
    source: str | None,
    metrics: dict | None = None,
) -> dict:
    available = row_count > 0
    return {
        "key": key,
        "status": "available" if available else "empty",
        "available": available,
        "source": source,
        "latest_date": latest_date,
        "row_count": row_count,
        "metrics": metrics or {},
    }


def get_kr_resource_summary(db: Session, *, symbol: str) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    latest_daily = (
        db.query(KRDailyPrice)
        .filter(KRDailyPrice.symbol == normalized_symbol)
        .order_by(KRDailyPrice.trade_date.desc(), KRDailyPrice.id.desc())
        .first()
    )
    daily_count = db.query(KRDailyPrice).filter(KRDailyPrice.symbol == normalized_symbol).count()
    latest_financial = (
        db.query(KRCompanyFundamental)
        .filter(KRCompanyFundamental.symbol == normalized_symbol)
        .order_by(
            KRCompanyFundamental.fiscal_year.desc().nullslast(),
            KRCompanyFundamental.disclosed_date.desc().nullslast(),
            KRCompanyFundamental.id.desc(),
        )
        .first()
    )
    financial_count = db.query(KRCompanyFundamental).filter(KRCompanyFundamental.symbol == normalized_symbol).count()
    latest_investor = (
        db.query(KRInvestorTradeDaily)
        .filter(KRInvestorTradeDaily.symbol == normalized_symbol)
        .order_by(KRInvestorTradeDaily.trade_date.desc(), KRInvestorTradeDaily.id.desc())
        .first()
    )
    investor_count = db.query(KRInvestorTradeDaily).filter(KRInvestorTradeDaily.symbol == normalized_symbol).count()

    return {
        "symbol": normalized_symbol,
        "slots": [
            _resource_slot(
                key="daily_price",
                row_count=daily_count,
                latest_date=latest_daily.trade_date if latest_daily else None,
                source=latest_daily.provider if latest_daily else None,
                metrics={
                    "close_price": _kr_close_value(latest_daily),
                    "trade_volume": latest_daily.trade_volume if latest_daily else None,
                },
            ),
            _resource_slot(
                key="investor_trading",
                row_count=investor_count,
                latest_date=latest_investor.trade_date if latest_investor else None,
                source=latest_investor.provider if latest_investor else None,
            ),
            _resource_slot(
                key="financials",
                row_count=financial_count,
                latest_date=latest_financial.disclosed_date if latest_financial else None,
                source=latest_financial.provider if latest_financial else None,
                metrics={
                    "fiscal_year": latest_financial.fiscal_year if latest_financial else None,
                    "report_code": latest_financial.report_code if latest_financial else None,
                },
            ),
            {
                "key": "disclosures",
                "status": "planned",
                "available": False,
                "source": "OpenDART",
                "latest_date": None,
                "row_count": 0,
                "metrics": {},
            },
        ],
    }


def _latest_kr_index_daily_row(db: Session, *, index_id: str) -> KRIndexDailyPrice | None:
    return (
        db.query(KRIndexDailyPrice)
        .filter(KRIndexDailyPrice.index_id == index_id)
        .order_by(
            KRIndexDailyPrice.trade_date.desc(),
            KRIndexDailyPrice.provider.asc(),
            KRIndexDailyPrice.id.desc(),
        )
        .first()
    )


def _kr_stock_daily_close_reference(
    db: Session,
    *,
    symbol: str,
    before_date: date,
) -> dict | None:
    rows = (
        db.query(KRDailyPrice)
        .filter(KRDailyPrice.symbol == symbol)
        .filter(KRDailyPrice.trade_date < before_date)
        .filter(KRDailyPrice.close_price.isnot(None))
        .order_by(KRDailyPrice.trade_date.desc(), KRDailyPrice.id.desc())
        .limit(10)
        .all()
    )
    if not rows:
        return None

    latest_date = rows[0].trade_date
    latest_rows = [row for row in rows if row.trade_date == latest_date]
    latest_rows.sort(key=lambda row: (KR_DAILY_PROVIDER_PRIORITY.get(row.provider, 99), -row.id))
    row = latest_rows[0]
    return {
        "previous_close": row.close_price,
        "previous_close_source": "kr_daily_price",
        "previous_close_trade_date": row.trade_date.isoformat(),
        "previous_close_provider": row.provider,
    }


def _apply_kr_stock_previous_close_reference(
    payload: dict,
    *,
    db: Session,
    symbol: str,
) -> dict:
    result = _copy_payload(payload)
    previous_close = result.get("previous_close")
    if isinstance(previous_close, (int, float)) and previous_close == previous_close:
        return result

    points = result.get("points") if isinstance(result.get("points"), list) else []
    latest_time = points[-1].get("time") if points and isinstance(points[-1], dict) else None
    if not isinstance(latest_time, str):
        return result

    try:
        latest_trade_date = datetime.fromisoformat(latest_time).date()
    except ValueError:
        return result

    reference = _kr_stock_daily_close_reference(
        db,
        symbol=symbol,
        before_date=latest_trade_date,
    )
    if reference is not None:
        result.update(reference)
    return result


def _kr_stock_daily_close_on_date(
    db: Session,
    *,
    symbol: str,
    trade_date: date,
) -> KRDailyPrice | None:
    rows = (
        db.query(KRDailyPrice)
        .filter(KRDailyPrice.symbol == symbol)
        .filter(KRDailyPrice.trade_date == trade_date)
        .filter(KRDailyPrice.close_price.isnot(None))
        .order_by(KRDailyPrice.id.desc())
        .limit(10)
        .all()
    )
    if not rows:
        return None

    rows.sort(key=lambda row: (KR_DAILY_PROVIDER_PRIORITY.get(row.provider, 99), -row.id))
    return rows[0]


def _reconcile_kr_stock_intraday_close(
    payload: dict,
    *,
    db: Session,
    symbol: str,
) -> dict:
    result = _copy_payload(payload)
    points = result.get("points") if isinstance(result.get("points"), list) else []
    latest_point = points[-1] if points and isinstance(points[-1], dict) else None
    latest_time_value = latest_point.get("time") if latest_point is not None else None
    if not isinstance(latest_time_value, str):
        return result

    try:
        latest_time = datetime.fromisoformat(latest_time_value)
    except ValueError:
        return result

    seoul_tz = timezone(timedelta(hours=9))
    if latest_time.tzinfo is None:
        latest_time = latest_time.replace(tzinfo=seoul_tz)
    latest_time = latest_time.astimezone(seoul_tz)
    session_close = latest_time.replace(hour=15, minute=30, second=0, microsecond=0)
    now = _seoul_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=seoul_tz)
    now = now.astimezone(seoul_tz)
    if latest_time.date() > now.date() or (
        latest_time.date() == now.date() and now < session_close
    ):
        return result

    daily_row = _kr_stock_daily_close_on_date(
        db,
        symbol=symbol,
        trade_date=latest_time.date(),
    )
    if daily_row is None or daily_row.close_price is None:
        return result

    current_cumulative = next(
        (
            point.get("cumulative_volume")
            for point in reversed(points)
            if isinstance(point, dict)
            and isinstance(point.get("cumulative_volume"), int)
            and point.get("cumulative_volume") >= 0
        ),
        None,
    )
    daily_volume = daily_row.trade_volume if daily_row.trade_volume is not None else None
    reconciled_total_volume = current_cumulative
    closing_interval_volume = None
    if daily_volume is not None and daily_volume >= 0:
        reconciled_total_volume = max(daily_volume, current_cumulative or 0)
        if current_cumulative is not None and daily_volume >= current_cumulative:
            closing_interval_volume = daily_volume - current_cumulative

    close_price = float(daily_row.close_price)
    latest_price = latest_point.get("price")
    open_price = float(latest_price) if isinstance(latest_price, (int, float)) else close_price
    closing_point = {
        "time": session_close.isoformat(),
        "session": "regular",
        "price": close_price,
        "volume": closing_interval_volume,
        "open": open_price,
        "high": max(open_price, close_price),
        "low": min(open_price, close_price),
        "cumulative_volume": reconciled_total_volume,
        "trade_value": None,
    }

    if latest_time < session_close:
        points = [*points, closing_point]
    elif latest_time == session_close:
        points = [*points[:-1], closing_point]
    else:
        return result

    result.update(
        {
            "regular_point_count": len(points),
            "point_count": len(points),
            "points": points,
            "as_of": session_close.isoformat(),
            "total_volume": reconciled_total_volume,
            "regular_session_close": close_price,
            "regular_session_close_time": session_close.isoformat(),
            "regular_session_close_source": "kr_daily_price",
            "regular_session_close_provider": daily_row.provider,
        }
    )
    return result


def _kr_daily_volume_totals(db: Session, *, symbol: str) -> dict[date, int]:
    rows = (
        db.query(KRDailyPrice)
        .filter(KRDailyPrice.symbol == symbol)
        .filter(KRDailyPrice.trade_volume.isnot(None))
        .order_by(KRDailyPrice.trade_date.desc(), KRDailyPrice.id.desc())
        .limit(90)
        .all()
    )
    totals: dict[date, int] = {}
    for row in rows:
        if row.trade_volume is None or row.trade_volume <= 0:
            continue
        totals[row.trade_date] = max(totals.get(row.trade_date, 0), int(row.trade_volume))
    return totals


def _persist_kr_stock_intraday_history(
    db: Session,
    *,
    symbol: str,
    payload: dict,
) -> dict:
    result = _copy_payload(payload)
    if not result.get("points"):
        return result
    try:
        changed_count = mutate_market_intraday_history(
            db,
            provider="yahoo_finance_chart",
            stock_id=symbol,
            market="KR",
            symbol=symbol,
            interval="1m",
            source=str(result.get("source") or "yahoo_finance_chart"),
            source_url=result.get("source_url"),
            points=result.get("points") or [],
            market_timezone=KR_MARKET_TIMEZONE,
        )
        if changed_count:
            db.commit()
    except SQLAlchemyError:
        db.rollback()
        result.setdefault("warnings", []).append(
            "KR intraday history persistence failed; same-time volume coverage may be partial."
        )
    return result


def _project_kr_stock_intraday_payload(payload: dict) -> dict:
    result = _copy_payload(payload)
    history_points = [
        point for point in result.get("points") or [] if isinstance(point, dict)
    ]
    current_points = latest_market_trade_date_points(
        history_points,
        market_timezone=KR_MARKET_TIMEZONE,
    )
    result["points"] = current_points
    result["point_count"] = len(current_points)
    result["regular_point_count"] = len(current_points)
    result["extended_point_count"] = 0
    result["has_extended_hours"] = False
    result["session_phase"] = "regular" if current_points else None
    if current_points:
        latest_point = current_points[-1]
        result["regular_session_close"] = latest_point.get("price")
        result["regular_session_close_time"] = latest_point.get("time")
        result["as_of"] = latest_point.get("time")
        result["total_volume"] = latest_point.get("cumulative_volume")
        current_trade_date = datetime.fromisoformat(str(latest_point["time"])).date()
        previous_reference = previous_regular_close_from_history(
            history_points,
            market_timezone=KR_MARKET_TIMEZONE,
            current_trade_date=current_trade_date,
        )
        if previous_reference is not None:
            result.update(previous_reference)
    return result


def _finalize_kr_stock_intraday_payload(
    payload: dict,
    *,
    db: Session,
    symbol: str,
) -> dict:
    projected = _project_kr_stock_intraday_payload(payload)
    referenced = _apply_kr_stock_previous_close_reference(
        projected,
        db=db,
        symbol=symbol,
    )
    reconciled = _reconcile_kr_stock_intraday_close(
        referenced,
        db=db,
        symbol=symbol,
    )
    reconciled["volume_pace"] = build_stock_volume_pace(
        db,
        stock_id=symbol,
        market="KR",
        current_points=reconciled.get("points") or [],
        market_timezone=KR_MARKET_TIMEZONE,
        daily_totals=_kr_daily_volume_totals(db, symbol=symbol),
        daily_source_name="kr_daily_price",
        history_market="KR",
        complete_day_min_ratio=0.7,
        minimum_history_points_per_day=340,
    )
    return reconciled


def get_kr_stock_intraday_trend(
    db: Session,
    *,
    symbol: str,
    refresh: bool = False,
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    cache_key = f"KR_STOCK:{normalized_symbol}"

    if not refresh:
        cached = _get_fresh_kr_stock_intraday_cache(cache_key)
        if cached is not None:
            return _finalize_kr_stock_intraday_payload(
                cached,
                db=db,
                symbol=normalized_symbol,
            )

    try:
        range_value = (
            "5d"
            if intraday_history_needs_bootstrap(
                db,
                stock_id=normalized_symbol,
                market="KR",
                market_timezone=KR_MARKET_TIMEZONE,
            )
            else "1d"
        )
        yahoo_payload, source_url = fetch_yahoo_chart_payload(
            symbol=normalized_symbol,
            range_value=range_value,
            interval="1m",
            timeout_seconds=min(settings.kr_market_http_timeout_seconds, 8),
            resource="intraday",
        )
        payload = parse_yahoo_intraday_prices(
            yahoo_payload,
            symbol=normalized_symbol,
            source_url=source_url,
        )
        payload = _persist_kr_stock_intraday_history(
            db,
            symbol=normalized_symbol,
            payload=payload,
        )
    except Exception as exc:
        payload = {
            "stock_id": normalized_symbol,
            "symbol": normalized_symbol,
            "source": "unavailable",
            "session_scope": "regular",
            "session_phase": None,
            "has_extended_hours": False,
            "regular_point_count": 0,
            "extended_point_count": 0,
            "previous_close": None,
            "previous_close_source": None,
            "previous_close_trade_date": None,
            "previous_close_provider": None,
            "regular_session_close": None,
            "regular_session_close_time": None,
            "point_count": 0,
            "points": [],
            "as_of": None,
            "total_volume": None,
            "volume_unit": "shares",
            "volume_semantics": "interval_with_cumulative_total",
            "trade_value_unit": "krw",
            "is_partial": True,
            "source_url": None,
            "warnings": [f"KR stock intraday source is unavailable: {exc}"],
            "fetched_pages": 0,
            "polling_interval_seconds": 60,
        }

    cached_payload = _set_kr_stock_intraday_cache(cache_key, payload)
    return _finalize_kr_stock_intraday_payload(
        cached_payload,
        db=db,
        symbol=normalized_symbol,
    )


def _seoul_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=9)))


def _kr_index_intraday_thistime(now: datetime | None = None) -> str:
    value = now or _seoul_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone(timedelta(hours=9)))
    return value.astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d%H%M%S")


def _kr_index_intraday_session(value: datetime) -> str:
    local = value.astimezone(timezone(timedelta(hours=9)))
    minutes = local.hour * 60 + local.minute + local.second / 60
    if 9 * 60 <= minutes <= 15 * 60 + 30:
        return "regular"
    if minutes < 9 * 60:
        return "pre_market"
    return "post_close"


def _kr_index_intraday_minute(value: datetime) -> datetime:
    local = value
    if local.tzinfo is None:
        local = local.replace(tzinfo=timezone(timedelta(hours=9)))
    return local.astimezone(timezone(timedelta(hours=9))).replace(second=0, microsecond=0)


def _parse_kr_index_intraday_point_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _kr_index_intraday_minute(parsed)


def _kr_index_realtime_interval_volume(
    points: list[dict],
    *,
    quote_time: datetime,
    cumulative_volume: int | None,
) -> int | None:
    if cumulative_volume is None or cumulative_volume < 0:
        return None

    quote_minute = _kr_index_intraday_minute(quote_time)
    previous_cumulative: int | None = None
    same_minute_baseline: int | None = None

    for point in points:
        point_time = _parse_kr_index_intraday_point_time(point.get("time"))
        point_cumulative = point.get("cumulative_volume")
        if point_time is None or not isinstance(point_cumulative, int) or point_cumulative < 0:
            continue

        if point_time < quote_minute:
            previous_cumulative = point_cumulative
            continue

        if point_time == quote_minute:
            point_volume = point.get("volume")
            if isinstance(point_volume, int) and point_volume >= 0:
                same_minute_baseline = max(point_cumulative - point_volume, 0)

    baseline = previous_cumulative if previous_cumulative is not None else same_minute_baseline
    if baseline is None or cumulative_volume < baseline:
        return None
    return cumulative_volume - baseline


def _kr_index_intraday_point_dict(point: KRIndexIntradayPointRecord) -> dict:
    return {
        "time": point.time.isoformat(),
        "session": _kr_index_intraday_session(point.time),
        "price": point.price,
        "volume": point.volume,
        "open": point.price,
        "high": point.price,
        "low": point.price,
        "cumulative_volume": point.cumulative_volume,
        "trade_value": point.trade_value,
    }


def _merge_intraday_points(existing: list[dict], updates: list[dict]) -> list[dict]:
    by_time: dict[str, dict] = {}
    for point in existing + updates:
        point_time = _parse_kr_index_intraday_point_time(point.get("time"))
        time_key = point_time.isoformat() if point_time is not None else ""
        price = point.get("price")
        if not time_key or not isinstance(price, (int, float)):
            continue
        by_time[time_key] = {**point, "time": time_key}
    return [by_time[key] for key in sorted(by_time)]


def _previous_close_from_realtime_or_daily(
    db: Session,
    *,
    index_id: str,
    realtime_price: float | None,
    realtime_change: float | None,
) -> tuple[float | None, str | None, str | None, str | None]:
    if realtime_price is not None and realtime_change is not None:
        reference = realtime_price - realtime_change
        return reference, "naver_index_realtime", None, "naver_polling"

    latest_daily = _latest_kr_index_daily_row(db, index_id=index_id)
    if latest_daily is None:
        return None, None, None, None
    return (
        latest_daily.close_value,
        "kr_index_daily",
        latest_daily.trade_date.isoformat(),
        latest_daily.provider,
    )


def _fetch_kr_index_intraday_pages(
    *,
    index_id: str,
    provider_symbol: str,
    thistime: str,
    max_pages: int,
) -> tuple[list[dict], int, str | None, list[str], bool]:
    points_by_time: OrderedDict[str, dict] = OrderedDict()
    warnings: list[str] = []
    source_url: str | None = None
    fetched_pages = 0
    page_limit_reached = False
    timeout_seconds = min(
        settings.kr_market_http_timeout_seconds,
        KR_INDEX_INTRADAY_PAGE_TIMEOUT_SECONDS,
    )

    def fetch_page(
        page: int,
    ) -> tuple[int, list[KRIndexIntradayPointRecord], str | None, Exception | None, str | None]:
        try:
            payload_text, page_source_url = fetch_naver_index_intraday_page_payload(
                provider_symbol=provider_symbol,
                thistime=thistime,
                page=page,
                timeout_seconds=timeout_seconds,
            )
            records = parse_naver_index_intraday_points(
                payload_text,
                index_id=index_id,
                thistime=thistime,
            )
        except Exception as exc:
            return page, [], None, exc, None

        return page, records, page_source_url, None, payload_text

    def merge_page(records: list[KRIndexIntradayPointRecord]) -> bool:
        before_count = len(points_by_time)
        for record in records:
            points_by_time[record.time.isoformat()] = _kr_index_intraday_point_dict(record)
        return len(points_by_time) > before_count

    first_page, first_records, first_source_url, first_error, first_payload_text = fetch_page(1)
    if first_error is not None:
        warnings.append(f"Naver index intraday page {first_page} failed: {first_error}")
        return [], 0, None, warnings, False

    fetched_pages = 1
    source_url = first_source_url
    if not first_records:
        return [], fetched_pages, source_url, warnings, False
    merge_page(first_records)

    advertised_last_page = parse_naver_index_intraday_last_page(first_payload_text or "")
    if advertised_last_page is not None:
        page_count = min(max_pages, advertised_last_page)
        page_limit_reached = advertised_last_page > page_count
        remaining_pages = list(range(2, page_count + 1))
        if remaining_pages:
            worker_count = min(KR_INDEX_INTRADAY_PAGE_WORKERS, len(remaining_pages))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                page_results = list(executor.map(fetch_page, remaining_pages))

            for page, records, page_source_url, error, _ in sorted(page_results):
                if error is not None:
                    warnings.append(f"Naver index intraday page {page} failed: {error}")
                    continue
                fetched_pages += 1
                source_url = source_url or page_source_url
                merge_page(records)

        return (
            [points_by_time[key] for key in sorted(points_by_time)],
            fetched_pages,
            source_url,
            warnings,
            page_limit_reached,
        )

    for page in range(2, max_pages + 1):
        _, records, page_source_url, error, _ = fetch_page(page)
        if error is not None:
            warnings.append(f"Naver index intraday page {page} failed: {error}")
            break
        fetched_pages += 1
        source_url = source_url or page_source_url
        if not records:
            break
        if not merge_page(records):
            break
    else:
        page_limit_reached = True

    return (
        [points_by_time[key] for key in sorted(points_by_time)],
        fetched_pages,
        source_url,
        warnings,
        page_limit_reached,
    )


@_translate_kr_provider_errors
def get_kr_index_intraday_trend(
    db: Session,
    *,
    index_id: str,
    refresh: bool = False,
    reload_all: bool = False,
    max_pages: int = KR_INDEX_INTRADAY_FULL_MAX_PAGES,
) -> dict:
    normalized_index_id = _valid_index_id(index_id)
    index_config = KR_INDEX_CONFIG_BY_ID[normalized_index_id]
    cache_key = f"KR_INDEX:{normalized_index_id}"

    if not refresh and not reload_all:
        fresh = _get_fresh_kr_index_intraday_cache(cache_key)
        if fresh is not None:
            return fresh

    stale = None if reload_all else _get_kr_index_intraday_cache(cache_key)
    thistime = _kr_index_intraday_thistime()
    trade_date_key = f"{thistime[0:4]}-{thistime[4:6]}-{thistime[6:8]}" if len(thistime) >= 8 else ""
    if stale is not None:
        cached_points = stale.get("points") if isinstance(stale.get("points"), list) else []
        cached_latest = cached_points[-1] if cached_points else None
        cached_latest_time = cached_latest.get("time") if isinstance(cached_latest, dict) else None
        if trade_date_key and isinstance(cached_latest_time, str) and not cached_latest_time.startswith(trade_date_key):
            stale = None
    needs_full_history = stale is None or bool(stale.get("is_partial"))
    page_count = (
        max(1, min(max_pages, KR_INDEX_INTRADAY_FULL_MAX_PAGES))
        if needs_full_history
        else KR_INDEX_INTRADAY_INCREMENTAL_PAGES
    )
    points, fetched_pages, source_url, warnings, page_limit_reached = _fetch_kr_index_intraday_pages(
        index_id=normalized_index_id,
        provider_symbol=index_config.provider_symbol,
        thistime=thistime,
        max_pages=page_count,
    )

    realtime_quote = None
    realtime_source_url = None
    try:
        realtime_payload, realtime_source_url = fetch_naver_index_realtime_payload(
            provider_symbol=index_config.provider_symbol,
            timeout_seconds=min(settings.kr_market_http_timeout_seconds, 5),
        )
        realtime_quote = parse_naver_index_realtime_quote(
            realtime_payload,
            index_id=normalized_index_id,
        )
    except Exception as exc:
        warnings.append(f"Naver realtime index quote failed: {exc}")

    merged_points = points
    if stale is not None:
        merged_points = _merge_intraday_points(stale.get("points") or [], points)

    if realtime_quote is not None and realtime_quote.time is not None and realtime_quote.price is not None:
        realtime_time = _kr_index_intraday_minute(realtime_quote.time)
        realtime_volume = _kr_index_realtime_interval_volume(
            merged_points,
            quote_time=realtime_time,
            cumulative_volume=realtime_quote.cumulative_volume,
        )
        realtime_point = {
            "time": realtime_time.isoformat(),
            "session": _kr_index_intraday_session(realtime_time),
            "price": realtime_quote.price,
            "volume": realtime_volume,
            "open": realtime_quote.open_value,
            "high": realtime_quote.high_value,
            "low": realtime_quote.low_value,
            "cumulative_volume": realtime_quote.cumulative_volume,
            "trade_value": realtime_quote.trade_value,
        }
        merged_points = _merge_intraday_points(merged_points, [realtime_point])

    previous_close, previous_source, previous_trade_date, previous_provider = (
        _previous_close_from_realtime_or_daily(
            db,
            index_id=normalized_index_id,
            realtime_price=realtime_quote.price if realtime_quote is not None else None,
            realtime_change=realtime_quote.change if realtime_quote is not None else None,
        )
    )
    latest_point = merged_points[-1] if merged_points else None
    session_phase = latest_point.get("session") if isinstance(latest_point, dict) else None
    source = KR_INDEX_INTRADAY_PROVIDER if merged_points else "unavailable"
    if not merged_points:
        warnings.append("Naver index intraday source returned no points.")

    latest_cumulative_volume = next(
        (
            point.get("cumulative_volume")
            for point in reversed(merged_points)
            if isinstance(point.get("cumulative_volume"), int)
            and point.get("cumulative_volume") >= 0
        ),
        None,
    )
    payload = {
        "stock_id": normalized_index_id,
        "symbol": index_config.provider_symbol,
        "source": source,
        "session_scope": "regular",
        "session_phase": session_phase,
        "has_extended_hours": False,
        "regular_point_count": sum(1 for point in merged_points if point.get("session") == "regular"),
        "extended_point_count": 0,
        "previous_close": previous_close,
        "previous_close_source": previous_source,
        "previous_close_trade_date": previous_trade_date,
        "previous_close_provider": previous_provider,
        "regular_session_close": (
            next((point.get("price") for point in reversed(merged_points) if point.get("session") == "regular"), None)
        ),
        "regular_session_close_time": (
            next((point.get("time") for point in reversed(merged_points) if point.get("session") == "regular"), None)
        ),
        "point_count": len(merged_points),
        "points": merged_points,
        "as_of": latest_point.get("time") if isinstance(latest_point, dict) else None,
        "total_volume": latest_cumulative_volume,
        "volume_unit": "thousand_shares",
        "volume_semantics": "interval_with_cumulative_total",
        "trade_value_unit": "million_krw",
        "is_partial": bool(warnings) or (needs_full_history and page_limit_reached),
        "source_url": source_url or realtime_source_url,
        "warnings": warnings,
        "fetched_pages": fetched_pages,
        "polling_interval_seconds": (
            realtime_quote.polling_interval_seconds if realtime_quote is not None else None
        ),
    }
    return _set_kr_index_intraday_cache(cache_key, payload)


def get_kr_index_summary(
    db: Session,
    *,
    expected_daily_date: date | None = None,
) -> dict:
    expected_date = expected_daily_date or expected_kr_daily_price_date()
    index_rows = list_kr_market_indices(db=db, is_active=True)
    snapshots = []

    for index_row in index_rows:
        latest = _latest_kr_index_daily_row(db, index_id=str(index_row["index_id"]))
        if latest is None:
            status = "empty"
        elif expected_date is not None and latest.trade_date < expected_date:
            status = "stale"
        else:
            status = "current"

        snapshots.append(
            {
                **index_row,
                "latest_date": latest.trade_date if latest else None,
                "close": latest.close_value if latest else None,
                "change": latest.price_change if latest else None,
                "change_pct": latest.change_pct if latest else None,
                "volume": latest.trade_volume if latest else None,
                "latest_provider": latest.provider if latest else None,
                "latest_source_url": latest.source_url if latest else None,
                "status": status,
                "breadth": get_kr_market_breadth(
                    db=db,
                    index_id=str(index_row["index_id"]),
                    trade_date=latest.trade_date if latest else None,
                ),
            }
        )

    return {
        "kind": "kr_index_summary",
        "generated_at": utc_now(),
        "expected_daily_price_date": expected_date,
        "summary": {
            "index_count": len(snapshots),
            "current_count": sum(1 for row in snapshots if row["status"] == "current"),
            "stale_count": sum(1 for row in snapshots if row["status"] == "stale"),
            "empty_count": sum(1 for row in snapshots if row["status"] == "empty"),
        },
        "indices": snapshots,
    }


def list_kr_index_ohlc_chart_data(
    db: Session,
    *,
    index_id: str,
    timeframe: str = "daily",
    bars: int = 90,
    ensure_history: bool = False,
    outputsize: str = "compact",
    to_date: date | None = None,
) -> dict:
    if timeframe not in KR_CHART_LOOKBACK_MULTIPLIER:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")
    if bars < 1 or bars > MAX_KR_CHART_BARS:
        raise ValueError(f"bars must be between 1 and {MAX_KR_CHART_BARS}.")

    normalized_index_id = _valid_index_id(index_id)
    index_config = get_kr_market_index_config(db, index_id=normalized_index_id)
    end_date = to_date or date.today()
    resolved_expected_data_date = (
        previous_kr_trading_day(end_date, include_value=True)
        if to_date is not None
        else expected_kr_daily_price_date()
    )
    lookback_days = max(bars * KR_CHART_LOOKBACK_MULTIPLIER[timeframe], bars)
    start_date = end_date - timedelta(days=lookback_days)
    backfill_result = None

    def load_points() -> tuple[list[dict], date | None]:
        rows = (
            db.query(KRIndexDailyPrice)
            .filter(KRIndexDailyPrice.index_id == normalized_index_id)
            .filter(KRIndexDailyPrice.trade_date >= start_date)
            .filter(KRIndexDailyPrice.trade_date <= end_date)
            .order_by(
                KRIndexDailyPrice.trade_date.asc(),
                KRIndexDailyPrice.provider.asc(),
                KRIndexDailyPrice.id.asc(),
            )
            .all()
        )
        latest_by_date: OrderedDict[date, KRIndexDailyPrice] = OrderedDict()
        provider_priority = {"naver_sise_index": 0, "krx_data": 1, "yahoo_chart": 2}
        for row in rows:
            current = latest_by_date.get(row.trade_date)
            if current is None or provider_priority.get(row.provider, 99) < provider_priority.get(current.provider, 99):
                latest_by_date[row.trade_date] = row
        selected = _aggregate_kr_index_daily_rows(list(latest_by_date.values()), timeframe)[-bars:]
        return selected, next(reversed(latest_by_date), None)

    points, latest_data_date = load_points()
    refresh_reasons: list[str] = []
    if len(points) < bars:
        refresh_reasons.append("insufficient_history")
    if latest_data_date is None or (
        resolved_expected_data_date is not None
        and latest_data_date < resolved_expected_data_date
    ):
        refresh_reasons.append("stale_latest_date")

    cooldown_active = False
    if ensure_history and refresh_reasons:
        refresh_key = f"index:{normalized_index_id}"
        attempted_at = _KR_DAILY_REFRESH_ATTEMPTS.get(refresh_key)
        now_monotonic = time.monotonic()
        cooldown_active = (
            attempted_at is not None
            and now_monotonic - attempted_at < KR_DAILY_REFRESH_ATTEMPT_COOLDOWN_SECONDS
        )
        if cooldown_active:
            backfill_result = {
                "status": "skipped",
                "provider": "naver_sise_index",
                "index_id": normalized_index_id,
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "refresh_reasons": refresh_reasons,
                "message": "KR index daily refresh skipped during the per-index cooldown window.",
            }
        else:
            _KR_DAILY_REFRESH_ATTEMPTS[refresh_key] = now_monotonic

    if ensure_history and refresh_reasons and not cooldown_active:
        refresh_outputsize = "full" if timeframe in {"weekly", "monthly"} else outputsize
        try:
            result = refresh_kr_index_daily_prices(
                db=db,
                index_id=normalized_index_id,
                outputsize=refresh_outputsize,
                end_date=resolved_expected_data_date,
            )
            backfill_result = {**result, "refresh_reasons": refresh_reasons}
        except (KRMarketDataFetchError, requests.RequestException, ValueError) as exc:
            if not points:
                raise
            backfill_result = {
                "status": "error",
                "provider": "naver_sise_index",
                "index_id": normalized_index_id,
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "refresh_reasons": refresh_reasons,
                "message": f"KR index daily refresh failed; using cached rows: {exc}",
            }
        points, latest_data_date = load_points()

    freshness_status = (
        "missing"
        if latest_data_date is None
        else "stale"
        if resolved_expected_data_date is not None and latest_data_date < resolved_expected_data_date
        else "future"
        if resolved_expected_data_date is not None and latest_data_date > resolved_expected_data_date
        else "current"
    )

    return {
        "index_id": normalized_index_id,
        "provider_symbol": index_config["provider_symbol"],
        "name": index_config["name"],
        "short_name": index_config["short_name"],
        "timeframe": timeframe,
        "bars": bars,
        "lookback_days": lookback_days,
        "from_date": start_date,
        "to_date": end_date,
        "point_count": len(points),
        "points": points,
        "backfill": backfill_result,
        "latest_data_date": latest_data_date,
        "expected_data_date": resolved_expected_data_date,
        "freshness_status": freshness_status,
        "is_current": freshness_status in {"current", "future"},
        "refresh_recommended": freshness_status in {"missing", "stale"},
    }


@_translate_kr_provider_errors
def list_kr_ohlc_chart_data(
    db: Session,
    *,
    symbol: str,
    timeframe: str = "daily",
    bars: int = 90,
    ensure_history: bool = False,
    outputsize: str = "compact",
    provider: str = "auto",
    to_date: date | None = None,
) -> dict:
    if timeframe not in KR_CHART_LOOKBACK_MULTIPLIER:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")
    if bars < 1 or bars > MAX_KR_CHART_BARS:
        raise ValueError(f"bars must be between 1 and {MAX_KR_CHART_BARS}.")

    normalized_symbol = _valid_symbol(symbol)
    end_date = to_date or date.today()
    resolved_expected_data_date = (
        previous_kr_trading_day(end_date, include_value=True)
        if to_date is not None
        else expected_kr_daily_price_date()
    )
    lookback_days = max(bars * KR_CHART_LOOKBACK_MULTIPLIER[timeframe], bars)
    start_date = end_date - timedelta(days=lookback_days)
    backfill_result = None

    def load_points() -> tuple[list[dict], date | None]:
        rows = (
            db.query(KRDailyPrice)
            .filter(KRDailyPrice.symbol == normalized_symbol)
            .filter(KRDailyPrice.trade_date >= start_date)
            .filter(KRDailyPrice.trade_date <= end_date)
            .order_by(
                KRDailyPrice.trade_date.asc(),
                KRDailyPrice.provider.asc(),
                KRDailyPrice.id.asc(),
            )
            .all()
        )
        latest_by_date: OrderedDict[date, KRDailyPrice] = OrderedDict()
        provider_priority = {"krx_data": 0, "yahoo_chart": 1}
        for row in rows:
            current = latest_by_date.get(row.trade_date)
            if current is None or provider_priority.get(row.provider, 99) < provider_priority.get(current.provider, 99):
                latest_by_date[row.trade_date] = row
        selected = _aggregate_kr_daily_rows(list(latest_by_date.values()), timeframe)[-bars:]
        return selected, next(reversed(latest_by_date), None)

    points, latest_data_date = load_points()
    refresh_reasons: list[str] = []
    if len(points) < bars:
        refresh_reasons.append("insufficient_history")
    if latest_data_date is None or (
        resolved_expected_data_date is not None
        and latest_data_date < resolved_expected_data_date
    ):
        refresh_reasons.append("stale_latest_date")

    cooldown_active = False
    if ensure_history and refresh_reasons:
        refresh_key = f"stock:{normalized_symbol}"
        attempted_at = _KR_DAILY_REFRESH_ATTEMPTS.get(refresh_key)
        now_monotonic = time.monotonic()
        cooldown_active = (
            attempted_at is not None
            and now_monotonic - attempted_at < KR_DAILY_REFRESH_ATTEMPT_COOLDOWN_SECONDS
        )
        if cooldown_active:
            backfill_result = {
                "status": "skipped",
                "provider": provider,
                "symbol": normalized_symbol,
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "refresh_reasons": refresh_reasons,
                "message": "KR daily refresh skipped during the per-symbol cooldown window.",
            }
        else:
            _KR_DAILY_REFRESH_ATTEMPTS[refresh_key] = now_monotonic

    if ensure_history and refresh_reasons and not cooldown_active:
        refresh_outputsize = "full" if timeframe in {"weekly", "monthly"} else outputsize
        if provider == "auto" and "stale_latest_date" in refresh_reasons:
            step_results: list[dict] = []
            step_errors: list[str] = []
            try:
                step_results.append(
                    refresh_kr_daily_prices(
                        db=db,
                        symbol=normalized_symbol,
                        outputsize=refresh_outputsize,
                        provider="yahoo_chart",
                    )
                )
            except (KRMarketDataFetchError, requests.RequestException, ValueError) as exc:
                step_errors.append(f"yahoo_chart: {exc}")

            points, latest_data_date = load_points()
            if latest_data_date is None or (
                resolved_expected_data_date is not None
                and latest_data_date < resolved_expected_data_date
            ):
                try:
                    step_results.append(
                        refresh_kr_daily_prices(
                            db=db,
                            symbol=normalized_symbol,
                            outputsize="compact",
                            provider="krx_data",
                            trade_date=resolved_expected_data_date,
                        )
                    )
                except (KRMarketDataFetchError, requests.RequestException, ValueError) as exc:
                    step_errors.append(f"krx_data: {exc}")

            points, latest_data_date = load_points()
            if not points and not step_results:
                raise KRMarketDataFetchError("; ".join(step_errors))

            backfill_status = (
                "success"
                if step_results and not step_errors
                else "partial_success"
                if step_results
                else "error"
            )
            backfill_result = {
                "status": backfill_status,
                "provider": "auto",
                "symbol": normalized_symbol,
                "fetched_count": sum(int(result.get("fetched_count") or 0) for result in step_results),
                "inserted_count": sum(int(result.get("inserted_count") or 0) for result in step_results),
                "updated_count": sum(int(result.get("updated_count") or 0) for result in step_results),
                "refresh_reasons": refresh_reasons,
                "steps": step_results,
                "errors": step_errors,
                "message": (
                    "KR daily history catch-up completed with Yahoo range history and KRX latest-day fallback."
                    if not step_errors
                    else "KR daily history catch-up was partial; using the best available cached rows."
                ),
            }
        else:
            try:
                result = refresh_kr_daily_prices(
                    db=db,
                    symbol=normalized_symbol,
                    outputsize=refresh_outputsize,
                    provider=provider,
                )
                backfill_result = {**result, "refresh_reasons": refresh_reasons}
            except (KRMarketDataFetchError, requests.RequestException, ValueError) as exc:
                if not points:
                    raise
                backfill_result = {
                    "status": "error",
                    "provider": provider,
                    "symbol": normalized_symbol,
                    "fetched_count": 0,
                    "inserted_count": 0,
                    "updated_count": 0,
                    "refresh_reasons": refresh_reasons,
                    "message": f"KR daily refresh failed; using cached rows: {exc}",
                }
            points, latest_data_date = load_points()

    freshness_status = (
        "missing"
        if latest_data_date is None
        else "stale"
        if resolved_expected_data_date is not None and latest_data_date < resolved_expected_data_date
        else "future"
        if resolved_expected_data_date is not None and latest_data_date > resolved_expected_data_date
        else "current"
    )

    return {
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "bars": bars,
        "lookback_days": lookback_days,
        "from_date": start_date,
        "to_date": end_date,
        "point_count": len(points),
        "points": points,
        "backfill": backfill_result,
        "latest_data_date": latest_data_date,
        "expected_data_date": resolved_expected_data_date,
        "freshness_status": freshness_status,
        "is_current": freshness_status in {"current", "future"},
        "refresh_recommended": freshness_status in {"missing", "stale"}
        or (backfill_result or {}).get("status") in {"error", "partial_success"},
    }
