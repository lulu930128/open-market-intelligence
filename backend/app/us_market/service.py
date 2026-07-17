from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, timedelta
import time

import requests
from sqlalchemy import case, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    MacroSeriesObservation,
    USDailyPrice,
    USCompanyProfile,
    USCorporateAction,
    USSecCompanyFact,
    USShortVolumeDaily,
    USStockMaster,
    USWatchlistGroup,
    USWatchlistItem,
    utc_now,
)
from app.observability.provider_http import translate_provider_http_errors
from app.us_market.chart_projection import (
    US_DAILY_CANONICAL_PROVIDER_PRIORITY,
    aggregate_daily_rows as _aggregate_us_daily_rows,
    dedupe_daily_rows_by_trade_date as _dedupe_us_daily_rows_by_trade_date,
    filter_ohlc_source_rows as _filter_us_ohlc_source_rows,
    has_newer_untrusted_yahoo_rows as _has_newer_untrusted_yahoo_rows,
    is_sparse_daily_ohlc_shape as _is_sparse_daily_ohlc_shape,
    is_yahoo_range_max_price_record as _is_yahoo_range_max_price_record,
    is_yahoo_range_max_record as _is_yahoo_range_max_record,
    is_yahoo_range_max_url as _is_yahoo_range_max_url,
    ohlc_point as _us_ohlc_point,
    should_skip_daily_price_update as _should_skip_us_daily_price_update,
)
from app.us_market import catalog_store, fundamentals_store, price_store, watchlist_metrics, watchlist_store, watchlist_workflows
from app.us_market.errors import (
    USMarketConfigurationError,
    USMarketDataFetchError,
    USStockNotFoundError,
    USWatchlistDuplicateItemError,
    USWatchlistGroupNotEmptyError,
    USWatchlistGroupNotFoundError,
    USWatchlistInvalidTreeError,
    USWatchlistItemNotFoundError,
)
from app.us_market.schemas import (
    USWatchlistGroupCreate,
    USWatchlistGroupUpdate,
    USWatchlistItemCreate,
    USWatchlistItemUpdate,
)
from app.us_market.providers.alphavantage import (
    fetch_alphavantage_daily_payload,
    fetch_alphavantage_dividends_payload,
    fetch_alphavantage_overview_payload,
    fetch_alphavantage_splits_payload,
)
from app.us_market.providers.finra import fetch_finra_short_volume_payload
from app.us_market.providers.fred import fetch_fred_series_observations_payload
from app.us_market.providers.sec import (
    fetch_sec_company_tickers_exchange_payload,
    fetch_sec_companyfacts_payload,
)
from app.us_market.providers.yahoo import fetch_yahoo_chart_payload
from app.us_market.sources import (
    MacroSeriesObservationRecord,
    USDailyPriceRecord,
    USCompanyProfileRecord,
    USCorporateActionRecord,
    USSecFactRecord,
    USShortVolumeRecord,
    USSymbolRecord,
    fetch_symbol_directories,
    normalize_us_symbol,
    parse_alphavantage_company_profile,
    parse_alphavantage_daily_prices,
    parse_alphavantage_dividends,
    parse_alphavantage_splits,
    parse_finra_short_volume,
    parse_fred_series_observations,
    parse_sec_companyfacts,
    parse_sec_company_tickers_exchange,
    parse_yahoo_daily_prices,
    parse_yahoo_intraday_prices,
    parse_yahoo_symbol_record,
)
from app.us_market.source_health import build_us_source_health
from app.us_market.trading_calendar import previous_us_trading_day
from app.market.calendar_status import expected_us_trade_date
from app.market.ohlc_overlay import aggregate_ohlc_points, append_intraday_overlay
from app.market.technical_radar import (
    TechnicalRadarBar,
    build_technical_watchlist_radar,
)


_translate_us_provider_errors = translate_provider_http_errors(USMarketDataFetchError)


def expected_us_daily_price_date() -> date:
    expected_date = expected_us_trade_date("us_daily_price")
    if expected_date is None:
        return date.today()

    return expected_date


ProgressCallback = Callable[[int | None, int | None, str | None], None]
US_INTRADAY_CACHE_TTL_SECONDS = 4.75
_US_INTRADAY_CACHE: dict[str, tuple[float, dict]] = {}
US_CHART_LOOKBACK_MULTIPLIER = {
    "daily": 2,
    "weekly": 8,
    "monthly": 31,
}
MAX_US_CHART_BARS = 5000
YAHOO_CHART_COMPACT_RANGE = "1y"
# Yahoo can downsample range=max daily charts to monthly bars for some US symbols.
YAHOO_CHART_FULL_RANGE = "10y"
YAHOO_CHART_INDEX_FULL_RANGE = "10y"
SEC_FUNDAMENTAL_FORMS = ("10-K", "10-Q", "20-F", "40-F")
SEC_FUNDAMENTAL_METRIC_TAGS = OrderedDict(
    [
        (
            "revenue",
            ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
        ),
        ("gross_profit", ("GrossProfit",)),
        ("operating_income", ("OperatingIncomeLoss",)),
        ("net_income", ("NetIncomeLoss", "ProfitLoss")),
        ("eps_diluted", ("EarningsPerShareDiluted",)),
        ("eps_basic", ("EarningsPerShareBasic",)),
        ("assets", ("Assets",)),
        ("liabilities", ("Liabilities",)),
        (
            "equity",
            (
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ),
        ),
        (
            "cash",
            (
                "CashAndCashEquivalentsAtCarryingValue",
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            ),
        ),
        (
            "debt_current",
            ("DebtCurrent", "ShortTermDebt", "ShortTermBorrowings", "CurrentPortionOfLongTermDebt"),
        ),
        (
            "debt_long_term",
            ("LongTermDebtAndCapitalLeaseObligations", "LongTermDebtNoncurrent", "LongTermDebt"),
        ),
        ("debt_total", ("DebtAndCapitalLeaseObligations",)),
        ("operating_cash_flow", ("NetCashProvidedByUsedInOperatingActivities",)),
        ("capex", ("PaymentsToAcquirePropertyPlantAndEquipment",)),
        ("shares_outstanding", ("EntityCommonStockSharesOutstanding",)),
    ]
)


def _valid_number(value) -> bool:
    return isinstance(value, (int, float)) and value == value


def _get_us_intraday_cache(cache_key: str) -> dict | None:
    cached = _US_INTRADAY_CACHE.get(cache_key)
    if cached is None:
        return None

    cached_at, payload = cached
    if time.monotonic() - cached_at > US_INTRADAY_CACHE_TTL_SECONDS:
        _US_INTRADAY_CACHE.pop(cache_key, None)
        return None

    return deepcopy(payload)


def _set_us_intraday_cache(cache_key: str, payload: dict) -> dict:
    _US_INTRADAY_CACHE[cache_key] = (time.monotonic(), deepcopy(payload))
    return payload


def _copy_us_intraday_payload(payload: dict) -> dict:
    return deepcopy(payload)


def _clean_setting(value: str | None) -> str:
    return (value or "").strip().strip('"').strip("'")


def _require_alphavantage_api_key() -> str:
    api_key = _clean_setting(settings.alphavantage_api_key)
    if not api_key:
        raise USMarketConfigurationError("ALPHAVANTAGE_API_KEY is not configured.")

    return api_key


def _require_fred_api_key() -> str:
    api_key = _clean_setting(settings.fred_api_key)
    if not api_key:
        raise USMarketConfigurationError("FRED_API_KEY is not configured.")

    return api_key


def _require_sec_user_agent() -> str:
    user_agent = _clean_setting(settings.us_sec_user_agent)
    if not user_agent or "set US_SEC_USER_AGENT" in user_agent:
        raise USMarketConfigurationError(
            "US_SEC_USER_AGENT is not configured. Set a descriptive User-Agent before calling SEC EDGAR APIs."
        )

    return user_agent


_apply_symbol_record = catalog_store._apply_symbol_record
upsert_us_symbol_records = catalog_store.upsert_us_symbol_records


@_translate_us_provider_errors
def sync_us_symbol_master(
    db: Session,
    *,
    include_sec_company_data: bool = True,
    deactivate_missing: bool = False,
) -> dict:
    records = fetch_symbol_directories(
        include_sec_company_data=include_sec_company_data,
        sec_user_agent=_require_sec_user_agent() if include_sec_company_data else settings.us_sec_user_agent,
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    return upsert_us_symbol_records(
        db=db,
        records=records,
        deactivate_missing=deactivate_missing,
    )


@_translate_us_provider_errors
def sync_us_sec_company_data(db: Session) -> dict:
    payload, _source_url = fetch_sec_company_tickers_exchange_payload(
        sec_user_agent=_require_sec_user_agent(),
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    sec_mapping = parse_sec_company_tickers_exchange(payload)

    updated_count = 0
    missing_count = 0

    for symbol, item in sec_mapping.items():
        stock = db.query(USStockMaster).filter(USStockMaster.symbol == symbol).first()
        if stock is None:
            missing_count += 1
            continue

        if _apply_sec_company_data(stock, item):
            updated_count += 1

    db.commit()

    return {
        "status": "success",
        "scanned_count": len(sec_mapping),
        "created_count": 0,
        "updated_count": updated_count,
        "deactivated_count": 0,
        "missing_count": missing_count,
        "message": "US stock master SEC CIK data synced from SEC company tickers.",
    }


_apply_sec_company_data = catalog_store._apply_sec_company_data


def _ensure_us_stock_cik(db: Session, *, symbol: str) -> USStockMaster:
    stock = get_us_stock(db, symbol=symbol)
    if _clean_setting(stock.cik):
        return stock

    payload, _source_url = fetch_sec_company_tickers_exchange_payload(
        sec_user_agent=_require_sec_user_agent(),
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    sec_mapping = parse_sec_company_tickers_exchange(payload)
    sec_item = sec_mapping.get(stock.symbol)
    if sec_item is None or not _clean_setting(sec_item.get("cik")):
        raise USMarketConfigurationError(
            f"US symbol='{stock.symbol}' has no SEC CIK in SEC company ticker data."
        )

    if _apply_sec_company_data(stock, sec_item):
        db.commit()
        db.refresh(stock)

    return stock


list_us_stocks = catalog_store.list_us_stocks


def search_us_stocks(
    db: Session,
    *,
    keyword: str,
    limit: int = 50,
    discover_missing_exact_symbol: bool = False,
) -> list[USStockMaster]:
    keyword = keyword.strip()
    if not keyword:
        return list_us_stocks(db, is_active=True, limit=limit)

    normalized_keyword = normalize_us_symbol(keyword)
    pattern = f"%{keyword}%"
    symbol_prefix_pattern = f"{normalized_keyword}%"
    ranking = case(
        (USStockMaster.symbol == normalized_keyword, 0),
        (USStockMaster.symbol.ilike(symbol_prefix_pattern), 1),
        (USStockMaster.security_name.ilike(pattern), 2),
        (USStockMaster.sec_company_name.ilike(pattern), 3),
        else_=4,
    )

    results = (
        db.query(USStockMaster)
        .filter(
            or_(
                USStockMaster.symbol == normalized_keyword,
                USStockMaster.symbol.ilike(pattern),
                USStockMaster.security_name.ilike(pattern),
                USStockMaster.sec_company_name.ilike(pattern),
                USStockMaster.exchange.ilike(pattern),
                USStockMaster.asset_type.ilike(pattern),
            )
        )
        .order_by(ranking.asc(), USStockMaster.symbol.asc())
        .limit(limit)
        .all()
    )
    has_exact_match = any(stock.symbol == normalized_keyword for stock in results)

    if discover_missing_exact_symbol and normalized_keyword and not has_exact_match:
        is_exact_symbol_lookup = keyword.upper() == normalized_keyword
        if is_exact_symbol_lookup:
            try:
                discovered = ensure_us_stock_master(db=db, symbol=normalized_keyword)
            except USStockNotFoundError:
                return results

            return [
                discovered,
                *[stock for stock in results if stock.symbol != discovered.symbol],
            ][:limit]

    return results


get_us_stock = catalog_store.get_us_stock


def discover_us_stock_master_from_yahoo_chart(db: Session, *, symbol: str) -> USStockMaster:
    normalized_symbol = normalize_us_symbol(symbol)
    if not normalized_symbol:
        raise USStockNotFoundError("US symbol is required.")

    payload, _source_url = fetch_yahoo_chart_payload(
        symbol=normalized_symbol,
        range_value="5d",
        interval="1d",
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    record = parse_yahoo_symbol_record(payload, symbol=normalized_symbol)
    upsert_us_symbol_records(db=db, records=[record])
    return get_us_stock(db=db, symbol=record.symbol)


def ensure_us_stock_master(db: Session, *, symbol: str) -> USStockMaster:
    normalized_symbol = normalize_us_symbol(symbol)
    try:
        return get_us_stock(db=db, symbol=normalized_symbol)
    except USStockNotFoundError:
        pass

    try:
        return discover_us_stock_master_from_yahoo_chart(db=db, symbol=normalized_symbol)
    except (requests.RequestException, USMarketDataFetchError) as exc:
        raise USStockNotFoundError(
            f"US symbol='{normalized_symbol}' not found in us_stock_master and Yahoo discovery failed: {exc}"
        ) from exc


upsert_us_daily_price_records = price_store.upsert_us_daily_price_records
_us_daily_price_sample = price_store._us_daily_price_sample

def repair_us_daily_price_quality(
    db: Session,
    *,
    symbol: str | None = None,
    dry_run: bool = True,
    limit: int = 1000,
    refresh: bool = False,
    outputsize: str = "compact",
    adjusted: bool = False,
    sleep_seconds: float = 0.0,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    if limit <= 0:
        raise ValueError("limit must be greater than 0.")

    if outputsize not in {"compact", "full"}:
        raise ValueError("outputsize must be one of: compact, full.")

    normalized_symbol = normalize_us_symbol(symbol) if symbol else None
    query = (
        db.query(USDailyPrice)
        .filter(USDailyPrice.provider == "yahoo_chart")
        .filter(USDailyPrice.source_url.ilike("%range=max%"))
    )

    if normalized_symbol is not None:
        query = query.filter(USDailyPrice.symbol == normalized_symbol)

    total_dirty_count = query.count()
    candidates = (
        query.order_by(
            USDailyPrice.symbol.asc(),
            USDailyPrice.trade_date.asc(),
            USDailyPrice.id.asc(),
        )
        .limit(limit)
        .all()
    )
    affected_symbols = sorted({row.symbol for row in candidates})
    sample_rows = [_us_daily_price_sample(row) for row in candidates[:25]]
    deleted_count = 0
    refresh_results: list[dict] = []
    errors: list[dict] = []

    if candidates and not dry_run:
        for row in candidates:
            db.delete(row)

        db.commit()
        deleted_count = len(candidates)

    if refresh and not dry_run and affected_symbols:
        total = len(affected_symbols)

        if progress_callback is not None:
            progress_callback(0, total, "Repairing US daily price quality.")

        for index, affected_symbol in enumerate(affected_symbols, start=1):
            try:
                result = refresh_us_daily_prices(
                    db=db,
                    symbol=affected_symbol,
                    outputsize=outputsize,
                    adjusted=adjusted,
                    provider="yahoo_chart",
                )
                refresh_results.append(result)
            except Exception as exc:
                db.rollback()
                errors.append(
                    {
                        "symbol": affected_symbol,
                        "message": str(exc),
                    }
                )

            if progress_callback is not None:
                progress_callback(index, total, f"Repaired {index}/{total} US symbols.")

            if index < total and sleep_seconds > 0:
                time.sleep(sleep_seconds)

    if total_dirty_count == 0:
        status_value = "empty"
    elif dry_run:
        status_value = "dry_run"
    elif errors and deleted_count == 0:
        status_value = "error"
    elif errors:
        status_value = "partial_success"
    else:
        status_value = "success"

    if dry_run:
        message = "US daily price quality repair dry-run completed."
    elif deleted_count:
        message = "US daily price quality repair completed."
    else:
        message = "No matching US daily price rows required repair."

    remaining_dirty_count = (
        total_dirty_count
        if dry_run
        else max(total_dirty_count - deleted_count, 0)
    )

    return {
        "status": status_value,
        "dry_run": dry_run,
        "symbol": normalized_symbol,
        "provider": "yahoo_chart",
        "limit": limit,
        "total_dirty_count": total_dirty_count,
        "candidate_count": len(candidates),
        "remaining_dirty_count": remaining_dirty_count,
        "affected_symbol_count": len(affected_symbols),
        "deleted_count": deleted_count,
        "refreshed_symbol_count": len(refresh_results),
        "refresh_error_count": len(errors),
        "affected_symbols": affected_symbols,
        "sample_rows": sample_rows,
        "refresh_results": refresh_results,
        "errors": errors,
        "message": message,
    }


def refresh_us_daily_prices_from_alphavantage(
    db: Session,
    *,
    symbol: str,
    outputsize: str = "compact",
    adjusted: bool = False,
) -> dict:
    api_key = _require_alphavantage_api_key()
    normalized_symbol = normalize_us_symbol(symbol)
    payload, source_url = fetch_alphavantage_daily_payload(
        symbol=normalized_symbol,
        api_key=api_key,
        outputsize=outputsize,
        adjusted=adjusted,
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    records = parse_alphavantage_daily_prices(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
    )
    result = upsert_us_daily_price_records(db, records)

    return {
        "status": "success",
        "provider": "alphavantage",
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "US daily prices refreshed from Alpha Vantage.",
    }


def _yahoo_daily_range_for_symbol(*, symbol: str, outputsize: str) -> str:
    if outputsize == "compact":
        return YAHOO_CHART_COMPACT_RANGE

    normalized_symbol = normalize_us_symbol(symbol)
    if normalized_symbol.startswith("^"):
        # Yahoo may downsample range=max index charts to quarterly bars.
        return YAHOO_CHART_INDEX_FULL_RANGE

    return YAHOO_CHART_FULL_RANGE


def refresh_us_daily_prices_from_yahoo_chart(
    db: Session,
    *,
    symbol: str,
    outputsize: str = "compact",
) -> dict:
    normalized_symbol = normalize_us_symbol(symbol)
    range_value = _yahoo_daily_range_for_symbol(
        symbol=normalized_symbol,
        outputsize=outputsize,
    )
    payload, source_url = fetch_yahoo_chart_payload(
        symbol=normalized_symbol,
        range_value=range_value,
        interval="1d",
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    records = parse_yahoo_daily_prices(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
    )
    result = upsert_us_daily_price_records(db, records)

    return {
        "status": "success",
        "provider": "yahoo_chart",
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "US daily prices refreshed from Yahoo chart.",
    }


@_translate_us_provider_errors
def refresh_us_daily_prices(
    db: Session,
    *,
    symbol: str,
    outputsize: str = "compact",
    adjusted: bool = False,
    provider: str = "auto",
) -> dict:
    normalized_provider = provider.strip().lower()

    if normalized_provider not in {"auto", "alphavantage", "yahoo_chart"}:
        raise ValueError("provider must be one of: auto, alphavantage, yahoo_chart.")

    api_key = _clean_setting(settings.alphavantage_api_key)

    if normalized_provider == "alphavantage":
        return refresh_us_daily_prices_from_alphavantage(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
            adjusted=adjusted,
        )

    if normalized_provider == "auto" and api_key and outputsize == "compact":
        try:
            return refresh_us_daily_prices_from_alphavantage(
                db=db,
                symbol=symbol,
                outputsize=outputsize,
                adjusted=adjusted,
            )
        except (USMarketConfigurationError, USMarketDataFetchError, requests.RequestException):
            fallback_result = refresh_us_daily_prices_from_yahoo_chart(
                db=db,
                symbol=symbol,
                outputsize=outputsize,
            )
            fallback_result["message"] = (
                f"{fallback_result['message']} Alpha Vantage auto refresh failed first; "
                "used Yahoo chart fallback."
            )
            return fallback_result

    if normalized_provider == "auto" or normalized_provider == "yahoo_chart":
        return refresh_us_daily_prices_from_yahoo_chart(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
        )

    raise USMarketConfigurationError("ALPHAVANTAGE_API_KEY is not configured.")


list_us_daily_prices = price_store.list_us_daily_prices
_list_us_ohlc_source_rows = price_store._list_us_ohlc_source_rows

def _refresh_us_ohlc_history_if_needed(
    db: Session,
    *,
    symbol: str,
    timeframe: str,
    bars: int,
    points: list[dict],
    ensure_history: bool,
    outputsize: str,
    adjusted: bool,
    provider: str,
    has_newer_untrusted_yahoo_rows: bool,
    latest_data_date: date | None,
    expected_data_date: date | None,
) -> dict | None:
    if not ensure_history:
        return None

    refresh_outputsize = outputsize
    has_sparse_daily_shape = (
        timeframe == "daily" and _is_sparse_daily_ohlc_shape(points)
    )
    refresh_reasons: list[str] = []
    if len(points) < bars:
        refresh_reasons.append("insufficient_history")
    if has_sparse_daily_shape:
        refresh_reasons.append("sparse_daily_shape")
    if has_newer_untrusted_yahoo_rows:
        refresh_reasons.append("untrusted_newer_rows")
    if expected_data_date is not None and (
        latest_data_date is None or latest_data_date < expected_data_date
    ):
        refresh_reasons.append("stale_latest_date")
    if not refresh_reasons:
        return None

    if timeframe in {"weekly", "monthly"}:
        refresh_outputsize = "full"
    elif has_sparse_daily_shape or has_newer_untrusted_yahoo_rows:
        refresh_outputsize = "compact"

    try:
        result = refresh_us_daily_prices(
            db=db,
            symbol=symbol,
            outputsize=refresh_outputsize,
            adjusted=adjusted,
            provider=provider,
        )
        return {**result, "refresh_reasons": refresh_reasons}
    except (USMarketConfigurationError, USMarketDataFetchError, requests.RequestException) as exc:
        if not points:
            raise

        return {
            "status": "error",
            "provider": provider,
            "symbol": symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "refresh_reasons": refresh_reasons,
            "message": f"US daily quality refresh failed; using cached clean rows: {exc}",
        }


@_translate_us_provider_errors
def list_us_ohlc_chart_data(
    db: Session,
    *,
    symbol: str,
    timeframe: str = "daily",
    bars: int = 90,
    ensure_history: bool = False,
    include_intraday: bool = False,
    outputsize: str = "compact",
    adjusted: bool = False,
    provider: str = "auto",
    to_date: date | None = None,
) -> dict:
    if timeframe not in US_CHART_LOOKBACK_MULTIPLIER:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")

    if bars <= 0:
        raise ValueError("bars must be greater than 0.")

    if bars > MAX_US_CHART_BARS:
        raise ValueError(f"bars must be less than or equal to {MAX_US_CHART_BARS}.")

    normalized_symbol = normalize_us_symbol(symbol)
    end_date = to_date or date.today()
    resolved_expected_data_date = (
        previous_us_trading_day(end_date, include_value=True)
        if to_date is not None
        else expected_us_daily_price_date()
    )
    lookback_days = bars * US_CHART_LOOKBACK_MULTIPLIER[timeframe]
    start_date = end_date - timedelta(days=lookback_days)
    backfill_result = None

    source_rows = _list_us_ohlc_source_rows(
        db=db,
        symbol=normalized_symbol,
        from_date=start_date,
        to_date=end_date,
    )
    rows = _filter_us_ohlc_source_rows(source_rows)
    daily_points = [_us_ohlc_point(row) for row in rows]
    latest_data_date = rows[-1].trade_date if rows else None
    base_points = aggregate_ohlc_points(points=daily_points, timeframe=timeframe)[-bars:]
    intraday_overlay = None
    points = base_points
    if include_intraday:
        daily_points, intraday_overlay = append_intraday_overlay(
            points=daily_points,
            intraday=get_us_intraday_trend(symbol=normalized_symbol, db=db),
            end_date=end_date,
        )
        points = aggregate_ohlc_points(points=daily_points, timeframe=timeframe)[-bars:]
    backfill_result = _refresh_us_ohlc_history_if_needed(
        db=db,
        symbol=normalized_symbol,
        timeframe=timeframe,
        bars=bars,
        points=base_points,
        ensure_history=ensure_history,
        outputsize=outputsize,
        adjusted=adjusted,
        provider=provider,
        has_newer_untrusted_yahoo_rows=_has_newer_untrusted_yahoo_rows(
            rows=source_rows,
            trusted_rows=rows,
        ),
        latest_data_date=latest_data_date,
        expected_data_date=resolved_expected_data_date,
    )

    if backfill_result is not None:
        source_rows = _list_us_ohlc_source_rows(
            db=db,
            symbol=normalized_symbol,
            from_date=start_date,
            to_date=end_date,
        )
        rows = _filter_us_ohlc_source_rows(source_rows)
        daily_points = [_us_ohlc_point(row) for row in rows]
        latest_data_date = rows[-1].trade_date if rows else None
        base_points = aggregate_ohlc_points(points=daily_points, timeframe=timeframe)[-bars:]
        intraday_overlay = None
        points = base_points
        if include_intraday:
            daily_points, intraday_overlay = append_intraday_overlay(
                points=daily_points,
                intraday=get_us_intraday_trend(symbol=normalized_symbol, db=db),
                end_date=end_date,
            )
            points = aggregate_ohlc_points(points=daily_points, timeframe=timeframe)[-bars:]

    freshness_status = (
        "missing"
        if latest_data_date is None
        else "stale"
        if latest_data_date < resolved_expected_data_date
        else "future"
        if latest_data_date > resolved_expected_data_date
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
        "intraday_overlay": intraday_overlay,
        "latest_data_date": latest_data_date,
        "expected_data_date": resolved_expected_data_date,
        "freshness_status": freshness_status,
        "is_current": freshness_status in {"current", "future"},
        "refresh_recommended": freshness_status in {"missing", "stale"},
    }


def get_us_intraday_trend(
    *,
    symbol: str,
    session_scope: str = "regular",
    db: Session | None = None,
) -> dict:
    if session_scope not in {"regular", "extended", "all"}:
        raise ValueError("session_scope must be one of: regular, extended, all.")

    normalized_symbol = normalize_us_symbol(symbol)
    cache_key = f"US:{normalized_symbol}:{session_scope}"
    cached = _get_us_intraday_cache(cache_key)

    if cached is not None:
        return _apply_us_intraday_previous_close_reference(
            cached,
            db=db,
            symbol=normalized_symbol,
        )

    try:
        yahoo_payload, source_url = fetch_yahoo_chart_payload(
            symbol=normalized_symbol,
            range_value="1d",
            interval="1m",
            timeout_seconds=settings.us_market_http_timeout_seconds,
            include_prepost=session_scope != "regular",
        )
        payload = _set_us_intraday_cache(
            cache_key,
            parse_yahoo_intraday_prices(
                yahoo_payload,
                symbol=normalized_symbol,
                source_url=source_url,
                session_scope=session_scope,
            ),
        )
    except Exception:
        payload = _set_us_intraday_cache(
            cache_key,
            {
                "stock_id": normalized_symbol,
                "symbol": normalized_symbol,
                "source": "unavailable",
                "session_scope": session_scope,
                "session_phase": None,
                "has_extended_hours": False,
                "regular_point_count": 0,
                "extended_point_count": 0,
                "previous_close": None,
                "previous_close_source": None,
                "previous_close_trade_date": None,
                "previous_close_provider": None,
                "point_count": 0,
                "points": [],
                "warnings": ["US intraday source is unavailable."],
            },
        )

    return _apply_us_intraday_previous_close_reference(
        payload,
        db=db,
        symbol=normalized_symbol,
    )


def _resolve_cik_for_symbol(db: Session, symbol: str) -> str:
    stock = _ensure_us_stock_cik(db, symbol=symbol)
    cik = _clean_setting(stock.cik)
    if not cik:
        raise USMarketConfigurationError(
            f"US symbol='{stock.symbol}' has no SEC CIK in SEC company ticker data."
        )

    return cik


upsert_us_sec_fact_records = fundamentals_store.upsert_us_sec_fact_records


@_translate_us_provider_errors
def refresh_us_sec_companyfacts(
    db: Session,
    *,
    symbol: str,
) -> dict:
    normalized_symbol = normalize_us_symbol(symbol)
    cik = _resolve_cik_for_symbol(db, normalized_symbol)
    payload, source_url = fetch_sec_companyfacts_payload(
        cik=cik,
        sec_user_agent=_require_sec_user_agent(),
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    records = parse_sec_companyfacts(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
    )
    result = upsert_us_sec_fact_records(db, records)

    return {
        "status": "success",
        "symbol": normalized_symbol,
        "cik": cik,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "US SEC company facts refreshed from EDGAR.",
    }


list_us_sec_company_facts = fundamentals_store.list_us_sec_company_facts
_latest_us_sec_fact_for_tag = fundamentals_store._latest_us_sec_fact_for_tag
_latest_us_sec_fact_for_tags = fundamentals_store._latest_us_sec_fact_for_tags
_us_sec_metric_to_dict = fundamentals_store._us_sec_metric_to_dict

def get_us_sec_fundamental_summary(db: Session, *, symbol: str) -> dict:
    stock = get_us_stock(db, symbol=symbol)
    metrics: list[dict] = []
    entity_name = stock.sec_company_name

    for metric, tags in SEC_FUNDAMENTAL_METRIC_TAGS.items():
        selected_fact = _latest_us_sec_fact_for_tags(
            db,
            symbol=stock.symbol,
            tags=tags,
        )
        if selected_fact is None:
            continue

        entity_name = selected_fact.entity_name or entity_name
        metrics.append(_us_sec_metric_to_dict(metric, selected_fact))

    return {
        "symbol": stock.symbol,
        "cik": stock.cik,
        "entity_name": entity_name,
        "metric_count": len(metrics),
        "metrics": metrics,
    }


upsert_us_company_profile_records = fundamentals_store.upsert_us_company_profile_records


@_translate_us_provider_errors
def refresh_us_company_profile_from_alphavantage(
    db: Session,
    *,
    symbol: str,
) -> dict:
    api_key = _require_alphavantage_api_key()
    normalized_symbol = normalize_us_symbol(symbol)
    payload, source_url = fetch_alphavantage_overview_payload(
        symbol=normalized_symbol,
        api_key=api_key,
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    record = parse_alphavantage_company_profile(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
    )
    result = upsert_us_company_profile_records(db, [record])

    return {
        "status": "success",
        "provider": "alphavantage",
        "symbol": record.symbol,
        "fetched_count": 1,
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "US company profile refreshed from Alpha Vantage overview.",
    }


get_us_company_profile = fundamentals_store.get_us_company_profile
list_us_company_profiles = fundamentals_store.list_us_company_profiles

upsert_us_corporate_action_records = fundamentals_store.upsert_us_corporate_action_records


@_translate_us_provider_errors
def refresh_us_corporate_actions_from_alphavantage(
    db: Session,
    *,
    symbol: str,
) -> dict:
    api_key = _require_alphavantage_api_key()
    normalized_symbol = normalize_us_symbol(symbol)

    dividend_payload, dividend_source_url = fetch_alphavantage_dividends_payload(
        symbol=normalized_symbol,
        api_key=api_key,
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    split_payload, split_source_url = fetch_alphavantage_splits_payload(
        symbol=normalized_symbol,
        api_key=api_key,
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )

    records = [
        *parse_alphavantage_dividends(
            dividend_payload,
            symbol=normalized_symbol,
            source_url=dividend_source_url,
        ),
        *parse_alphavantage_splits(
            split_payload,
            symbol=normalized_symbol,
            source_url=split_source_url,
        ),
    ]
    result = upsert_us_corporate_action_records(db, records)

    return {
        "status": "success",
        "provider": "alphavantage",
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "US corporate actions refreshed from Alpha Vantage.",
    }


list_us_corporate_actions = fundamentals_store.list_us_corporate_actions

upsert_us_short_volume_records = fundamentals_store.upsert_us_short_volume_records


@_translate_us_provider_errors
def refresh_us_short_volume_from_finra(
    db: Session,
    *,
    trade_date: date,
) -> dict:
    text, source_url = fetch_finra_short_volume_payload(
        trade_date=trade_date,
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    records = parse_finra_short_volume(
        text,
        trade_date=trade_date,
        source_url=source_url,
    )
    result = upsert_us_short_volume_records(db, records)

    return {
        "status": "success",
        "provider": "finra",
        "trade_date": trade_date,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "US short volume refreshed from FINRA daily short sale volume.",
    }


list_us_short_volumes = fundamentals_store.list_us_short_volumes

upsert_macro_series_observation_records = fundamentals_store.upsert_macro_series_observation_records


@_translate_us_provider_errors
def refresh_fred_macro_series(
    db: Session,
    *,
    series_id: str,
    observation_start: date | None = None,
    observation_end: date | None = None,
) -> dict:
    api_key = _require_fred_api_key()
    normalized_series_id = series_id.strip().upper()
    payload, source_url = fetch_fred_series_observations_payload(
        series_id=normalized_series_id,
        api_key=api_key,
        observation_start=observation_start,
        observation_end=observation_end,
        timeout_seconds=settings.us_market_http_timeout_seconds,
    )
    records = parse_fred_series_observations(
        payload,
        series_id=normalized_series_id,
        source_url=source_url,
    )
    result = upsert_macro_series_observation_records(db, records)

    return {
        "status": "success",
        "provider": "fred",
        "series_id": normalized_series_id,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "Macro series observations refreshed from FRED.",
    }


list_macro_series_observations = fundamentals_store.list_macro_series_observations

get_us_watchlist_group = watchlist_store.get_us_watchlist_group
_validate_us_watchlist_parent = watchlist_store._validate_us_watchlist_parent
create_us_watchlist_group = watchlist_store.create_us_watchlist_group
list_us_watchlist_groups = watchlist_store.list_us_watchlist_groups
_us_group_to_tree_node = watchlist_store._us_group_to_tree_node
get_us_watchlist_tree = watchlist_store.get_us_watchlist_tree
update_us_watchlist_group = watchlist_store.update_us_watchlist_group
_get_us_descendant_group_ids = watchlist_store._get_us_descendant_group_ids
delete_us_watchlist_group = watchlist_store.delete_us_watchlist_group

def _ensure_us_stock_exists(db: Session, symbol: str) -> USStockMaster:
    return ensure_us_stock_master(db=db, symbol=symbol)


_us_watchlist_item_to_dict = watchlist_store._us_watchlist_item_to_dict

def create_us_watchlist_item(
    db: Session,
    payload: USWatchlistItemCreate,
) -> dict:
    get_us_watchlist_group(db, payload.group_id)
    stock = _ensure_us_stock_exists(db, payload.symbol)
    payload_data = payload.model_dump()
    payload_data["symbol"] = stock.symbol

    item = USWatchlistItem(**payload_data)
    db.add(item)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise USWatchlistDuplicateItemError(
            f"US symbol='{stock.symbol}' already exists in group id={payload.group_id}."
        ) from exc

    db.refresh(item)
    return _us_watchlist_item_to_dict(db, item)


get_us_watchlist_item = watchlist_store.get_us_watchlist_item
list_us_watchlist_items = watchlist_store.list_us_watchlist_items
list_us_watchlist_symbols = watchlist_store.list_us_watchlist_symbols

_close_value = watchlist_metrics._close_value
_latest_distinct_us_daily_rows = watchlist_metrics._latest_distinct_us_daily_rows
_latest_us_daily_close_reference = watchlist_metrics._latest_us_daily_close_reference
_us_intraday_latest_trade_date = watchlist_metrics._us_intraday_latest_trade_date
_us_regular_session_close_reference = watchlist_metrics._us_regular_session_close_reference
_us_reference_trade_date = watchlist_metrics._us_reference_trade_date

def _us_previous_regular_intraday_close_reference(
    *,
    symbol: str,
    expected_trade_date: date,
) -> dict | None:
    intraday = get_us_intraday_trend(
        symbol=symbol,
        session_scope="regular",
        db=None,
    )
    points = intraday.get("points") or []

    for point in reversed(points):
        if not isinstance(point, dict):
            continue

        if point.get("session") != "regular":
            continue

        trade_date = _us_row_trade_date(point)

        if trade_date != expected_trade_date:
            continue

        price = point.get("price")

        if not _valid_number(price):
            continue

        return {
            "previous_close": float(price),
            "previous_close_source": "yahoo_finance_chart_regular_session_close",
            "previous_close_trade_date": trade_date.isoformat(),
            "previous_close_provider": "yahoo_chart",
        }

    return None


def _apply_us_intraday_previous_close_reference(
    payload: dict,
    *,
    db: Session | None,
    symbol: str,
) -> dict:
    result = _copy_us_intraday_payload(payload)
    result.setdefault(
        "previous_close_source",
        "yahoo_finance_chart" if _valid_number(result.get("previous_close")) else None,
    )
    result.setdefault("previous_close_trade_date", None)
    result.setdefault("previous_close_provider", None)

    if db is None:
        return result

    latest_trade_date = _us_intraday_latest_trade_date(result)
    reference = None

    if result.get("session_phase") == "after_hours" and latest_trade_date is not None:
        reference = _latest_us_daily_close_reference(
            db=db,
            symbol=symbol,
            on_date=latest_trade_date,
        )

    if reference is None:
        reference = _us_regular_session_close_reference(result)

    if reference is None:
        reference = _latest_us_daily_close_reference(
            db=db,
            symbol=symbol,
            before_date=latest_trade_date,
        )

    if result.get("session_phase") == "pre_market" and latest_trade_date is not None:
        expected_reference_date = previous_us_trading_day(
            latest_trade_date,
            include_value=False,
        )

        if _us_reference_trade_date(reference) != expected_reference_date:
            intraday_reference = _us_previous_regular_intraday_close_reference(
                symbol=symbol,
                expected_trade_date=expected_reference_date,
            )

            if intraday_reference is not None:
                reference = intraday_reference

    if reference is None:
        return result

    result.update(reference)
    return result


_sum_us_intraday_volume = watchlist_metrics._sum_us_intraday_volume
_compact_us_intraday_points = watchlist_metrics._compact_us_intraday_points
_parse_us_row_trade_date = watchlist_metrics._parse_us_row_trade_date
_us_row_trade_date = watchlist_metrics._us_row_trade_date

def _us_watchlist_workflow_dependencies() -> watchlist_workflows.USWatchlistWorkflowDependencies:
    return watchlist_workflows.USWatchlistWorkflowDependencies(
        expected_daily_price_date=expected_us_daily_price_date,
        intraday_overlay_loader=_get_us_intraday_overlay,
        refresh_daily_prices=refresh_us_daily_prices,
        ensure_stock=_ensure_us_stock_exists,
        refresh_sec_facts=refresh_us_sec_companyfacts,
        refresh_company_profile=refresh_us_company_profile_from_alphavantage,
        refresh_corporate_actions=refresh_us_corporate_actions_from_alphavantage,
    )


def _us_ranking_freshness(rows: list[dict], requested_symbol_count: int) -> dict:
    return watchlist_workflows._us_ranking_freshness(
        rows,
        requested_symbol_count,
        dependencies=_us_watchlist_workflow_dependencies(),
    )

def _get_us_intraday_overlay(
    symbol: str,
    *,
    db: Session | None = None,
    session_scope: str = "regular",
) -> dict | None:
    intraday = get_us_intraday_trend(
        symbol=symbol,
        session_scope=session_scope,
        db=db,
    )
    points = intraday.get("points") or []

    if not points:
        return None

    latest = points[-1]
    latest_price = latest.get("price")
    previous_close = intraday.get("previous_close")

    if not _valid_number(latest_price):
        return None

    change = None
    change_pct = None

    if _valid_number(previous_close) and previous_close != 0:
        change = float(latest_price) - float(previous_close)
        change_pct = (change / float(previous_close)) * 100

    volume = _sum_us_intraday_volume(points)

    if volume is None and _valid_number(latest.get("volume")):
        volume = int(latest["volume"])

    return {
        "time": latest.get("time"),
        "session": latest.get("session"),
        "close": float(latest_price),
        "previous_close": float(previous_close) if _valid_number(previous_close) else None,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
        "source": intraday.get("source"),
        "session_scope": intraday.get("session_scope"),
        "has_extended_hours": bool(intraday.get("has_extended_hours")),
        "points": _compact_us_intraday_points(points),
    }


def get_us_watchlist_ranking(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "none",
    sort_order: str = "asc",
    use_intraday: bool = False,
    intraday_limit: int = 30,
    intraday_session_scope: str = "regular",
) -> dict:
    return watchlist_workflows.get_us_watchlist_ranking(
        db,
        dependencies=_us_watchlist_workflow_dependencies(),
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by=rank_by,
        sort_order=sort_order,
        use_intraday=use_intraday,
        intraday_limit=intraday_limit,
        intraday_session_scope=intraday_session_scope,
    )

def get_us_watchlist_technical_radar(
    db: Session,
    *,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = "action",
    max_results: int = 30,
    calculation_limit: int = 100,
    use_intraday: bool = False,
    intraday_limit: int = 30,
) -> dict:
    ranking = get_us_watchlist_ranking(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by="none",
        sort_order="asc",
        use_intraday=use_intraday,
        intraday_limit=intraday_limit,
    )
    symbols = [
        normalize_us_symbol(row.get("symbol"))
        for row in ranking.get("results", [])
        if normalize_us_symbol(row.get("symbol"))
    ]
    histories: dict[str, list[TechnicalRadarBar]] = {}

    for symbol in symbols:
        daily_rows = _latest_distinct_us_daily_rows(
            db=db,
            symbol=symbol,
            limit=calculation_limit,
        )
        histories[symbol] = [
            TechnicalRadarBar(
                trade_date=row.trade_date,
                open=row.open_price,
                high=row.high_price,
                low=row.low_price,
                close=_close_value(row),
                volume=row.trade_volume,
            )
            for row in daily_rows
        ]

    radar = build_technical_watchlist_radar(
        ranking=ranking,
        histories=histories,
        market="US",
        include_children=include_children,
        mode=mode,
        max_results=max_results,
    )
    radar["group_id"] = radar.get("group_id") or group_id
    return radar


def refresh_us_watchlist_daily_prices(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    outputsize: str = "compact",
    adjusted: bool = False,
    sleep_seconds: float = 12.0,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    return watchlist_workflows.refresh_us_watchlist_daily_prices(
        db,
        dependencies=_us_watchlist_workflow_dependencies(),
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        outputsize=outputsize,
        adjusted=adjusted,
        sleep_seconds=sleep_seconds,
        progress_callback=progress_callback,
    )


_compact_us_resource_result = watchlist_workflows._compact_us_resource_result


def _refresh_us_symbol_resources(
    db: Session,
    *,
    symbol: str,
    include_daily: bool,
    include_sec_facts: bool,
    include_profile: bool,
    include_actions: bool,
    outputsize: str,
    adjusted: bool,
) -> dict:
    return watchlist_workflows._refresh_us_symbol_resources(
        db,
        dependencies=_us_watchlist_workflow_dependencies(),
        symbol=symbol,
        include_daily=include_daily,
        include_sec_facts=include_sec_facts,
        include_profile=include_profile,
        include_actions=include_actions,
        outputsize=outputsize,
        adjusted=adjusted,
    )


def refresh_us_watchlist_resources(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_sec_facts: bool = True,
    include_profile: bool = True,
    include_actions: bool = False,
    outputsize: str = "compact",
    adjusted: bool = False,
    sleep_seconds: float = 12.0,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    return watchlist_workflows.refresh_us_watchlist_resources(
        db,
        dependencies=_us_watchlist_workflow_dependencies(),
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        include_daily=include_daily,
        include_sec_facts=include_sec_facts,
        include_profile=include_profile,
        include_actions=include_actions,
        outputsize=outputsize,
        adjusted=adjusted,
        sleep_seconds=sleep_seconds,
        progress_callback=progress_callback,
    )

def update_us_watchlist_item(
    db: Session,
    item_id: int,
    payload: USWatchlistItemUpdate,
) -> dict:
    item = get_us_watchlist_item(db, item_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "group_id" in update_data:
        get_us_watchlist_group(db, update_data["group_id"])

    if "symbol" in update_data:
        stock = _ensure_us_stock_exists(db, update_data["symbol"])
        update_data["symbol"] = stock.symbol

    for key, value in update_data.items():
        setattr(item, key, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise USWatchlistDuplicateItemError(
            "Duplicate US symbol in the same watchlist group."
        ) from exc

    db.refresh(item)
    return _us_watchlist_item_to_dict(db, item)


delete_us_watchlist_item = watchlist_store.delete_us_watchlist_item
