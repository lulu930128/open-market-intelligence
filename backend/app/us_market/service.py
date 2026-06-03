from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from datetime import date, timedelta
import time

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
from app.us_market.schemas import (
    USWatchlistGroupCreate,
    USWatchlistGroupUpdate,
    USWatchlistItemCreate,
    USWatchlistItemUpdate,
)
from app.us_market.sources import (
    MacroSeriesObservationRecord,
    USDailyPriceRecord,
    USCompanyProfileRecord,
    USCorporateActionRecord,
    USMarketDataFetchError,
    USSecFactRecord,
    USShortVolumeRecord,
    USSymbolRecord,
    fetch_alphavantage_daily_payload,
    fetch_alphavantage_dividends_payload,
    fetch_alphavantage_overview_payload,
    fetch_alphavantage_splits_payload,
    fetch_finra_short_volume_payload,
    fetch_fred_series_observations_payload,
    fetch_sec_company_tickers_exchange_payload,
    fetch_sec_companyfacts_payload,
    fetch_symbol_directories,
    fetch_yahoo_chart_payload,
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
)


class USStockNotFoundError(Exception):
    pass


class USMarketConfigurationError(Exception):
    pass


class USWatchlistGroupNotFoundError(Exception):
    pass


class USWatchlistGroupNotEmptyError(Exception):
    pass


class USWatchlistInvalidTreeError(Exception):
    pass


class USWatchlistItemNotFoundError(Exception):
    pass


class USWatchlistDuplicateItemError(Exception):
    pass


ProgressCallback = Callable[[int | None, int | None, str | None], None]
US_CHART_LOOKBACK_MULTIPLIER = {
    "daily": 2,
    "weekly": 8,
    "monthly": 31,
}
MAX_US_CHART_BARS = 5000
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


def _apply_symbol_record(stock: USStockMaster, record: USSymbolRecord) -> None:
    stock.security_name = record.security_name or stock.security_name
    stock.exchange = record.exchange or stock.exchange
    stock.asset_type = record.asset_type
    stock.listing_source = record.listing_source
    stock.market_category = record.market_category
    stock.financial_status = record.financial_status
    stock.cqs_symbol = record.cqs_symbol
    stock.nasdaq_symbol = record.nasdaq_symbol
    stock.cik = record.cik or stock.cik
    stock.sec_company_name = record.sec_company_name or stock.sec_company_name
    stock.is_etf = record.is_etf
    stock.is_test_issue = record.is_test_issue
    stock.round_lot_size = record.round_lot_size
    stock.is_active = True
    stock.last_seen_at = utc_now()
    stock.updated_at = utc_now()


def upsert_us_symbol_records(
    db: Session,
    records: list[USSymbolRecord],
    *,
    deactivate_missing: bool = False,
) -> dict:
    scanned_count = len(records)
    created_count = 0
    updated_count = 0
    now = utc_now()
    seen_symbols = {record.symbol for record in records}

    existing_by_symbol = {
        stock.symbol: stock
        for stock in db.query(USStockMaster).filter(USStockMaster.symbol.in_(seen_symbols)).all()
    } if seen_symbols else {}

    for record in records:
        existing = existing_by_symbol.get(record.symbol)

        if existing is None:
            stock = USStockMaster(
                symbol=record.symbol,
                security_name=record.security_name,
                exchange=record.exchange,
                asset_type=record.asset_type,
                listing_source=record.listing_source,
                market_category=record.market_category,
                financial_status=record.financial_status,
                cqs_symbol=record.cqs_symbol,
                nasdaq_symbol=record.nasdaq_symbol,
                cik=record.cik,
                sec_company_name=record.sec_company_name,
                is_etf=record.is_etf,
                is_test_issue=record.is_test_issue,
                round_lot_size=record.round_lot_size,
                is_active=True,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(stock)
            created_count += 1
            continue

        _apply_symbol_record(existing, record)
        updated_count += 1

    deactivated_count = 0
    if deactivate_missing and seen_symbols:
        missing_rows = (
            db.query(USStockMaster)
            .filter(USStockMaster.is_active.is_(True))
            .filter(~USStockMaster.symbol.in_(seen_symbols))
            .all()
        )
        for stock in missing_rows:
            stock.is_active = False
            stock.updated_at = utc_now()
            deactivated_count += 1

    db.commit()

    return {
        "status": "success",
        "scanned_count": scanned_count,
        "created_count": created_count,
        "updated_count": updated_count,
        "deactivated_count": deactivated_count,
        "message": "US stock master synced from Nasdaq Trader symbol directories.",
    }


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


def _apply_sec_company_data(stock: USStockMaster, item: dict[str, str | None]) -> bool:
    changed = False
    cik = item.get("cik")
    sec_company_name = item.get("sec_company_name")
    sec_exchange = item.get("sec_exchange")

    if cik and stock.cik != cik:
        stock.cik = cik
        changed = True
    if sec_company_name and stock.sec_company_name != sec_company_name:
        stock.sec_company_name = sec_company_name
        changed = True
    if sec_exchange and not stock.exchange:
        stock.exchange = sec_exchange
        changed = True

    if changed:
        stock.updated_at = utc_now()

    return changed


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


def list_us_stocks(
    db: Session,
    *,
    exchange: str | None = None,
    asset_type: str | None = None,
    is_active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[USStockMaster]:
    query = db.query(USStockMaster)

    if exchange is not None:
        query = query.filter(USStockMaster.exchange == exchange)

    if asset_type is not None:
        query = query.filter(USStockMaster.asset_type == asset_type)

    if is_active is not None:
        query = query.filter(USStockMaster.is_active.is_(is_active))

    return (
        query.order_by(USStockMaster.symbol.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def search_us_stocks(
    db: Session,
    *,
    keyword: str,
    limit: int = 50,
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

    return (
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


def get_us_stock(db: Session, *, symbol: str) -> USStockMaster:
    normalized_symbol = normalize_us_symbol(symbol)
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized_symbol)
        .first()
    )

    if stock is None:
        raise USStockNotFoundError(f"US symbol='{normalized_symbol}' not found.")

    return stock


def upsert_us_daily_price_records(
    db: Session,
    records: list[USDailyPriceRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(USDailyPrice)
            .filter(USDailyPrice.provider == record.provider)
            .filter(USDailyPrice.symbol == record.symbol)
            .filter(USDailyPrice.trade_date == record.trade_date)
            .first()
        )

        if existing is None:
            db.add(
                USDailyPrice(
                    provider=record.provider,
                    symbol=record.symbol,
                    trade_date=record.trade_date,
                    open_price=record.open_price,
                    high_price=record.high_price,
                    low_price=record.low_price,
                    close_price=record.close_price,
                    adjusted_close=record.adjusted_close,
                    trade_volume=record.trade_volume,
                    dividend_amount=record.dividend_amount,
                    split_coefficient=record.split_coefficient,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.open_price = record.open_price
        existing.high_price = record.high_price
        existing.low_price = record.low_price
        existing.close_price = record.close_price
        existing.adjusted_close = record.adjusted_close
        existing.trade_volume = record.trade_volume
        existing.dividend_amount = record.dividend_amount
        existing.split_coefficient = record.split_coefficient
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
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


def refresh_us_daily_prices_from_yahoo_chart(
    db: Session,
    *,
    symbol: str,
    outputsize: str = "compact",
) -> dict:
    normalized_symbol = normalize_us_symbol(symbol)
    range_value = "1y" if outputsize == "compact" else "max"
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
    if normalized_provider == "alphavantage" or (
        normalized_provider == "auto" and api_key
    ):
        return refresh_us_daily_prices_from_alphavantage(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
            adjusted=adjusted,
        )

    if normalized_provider == "auto" or normalized_provider == "yahoo_chart":
        return refresh_us_daily_prices_from_yahoo_chart(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
        )

    raise USMarketConfigurationError("ALPHAVANTAGE_API_KEY is not configured.")


def list_us_daily_prices(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[USDailyPrice]:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USDailyPrice).filter(USDailyPrice.symbol == normalized_symbol)

    if provider is not None:
        query = query.filter(USDailyPrice.provider == provider)

    if from_date is not None:
        query = query.filter(USDailyPrice.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(USDailyPrice.trade_date <= to_date)

    return (
        query.order_by(USDailyPrice.trade_date.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def _sum_nullable(values: list[int | None]) -> int | None:
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None

    return sum(valid_values)


def _us_ohlc_point(row: USDailyPrice, time_value: date | None = None) -> dict:
    return {
        "time": time_value or row.trade_date,
        "open": row.open_price,
        "high": row.high_price,
        "low": row.low_price,
        "close": row.close_price,
        "volume": row.trade_volume,
    }


def _aggregate_us_daily_rows(rows: list[USDailyPrice], timeframe: str) -> list[dict]:
    if timeframe == "daily":
        return [_us_ohlc_point(row) for row in rows]

    groups: "OrderedDict[date, list[USDailyPrice]]" = OrderedDict()

    for row in rows:
        if timeframe == "weekly":
            key = row.trade_date - timedelta(days=row.trade_date.weekday())
        else:
            key = date(row.trade_date.year, row.trade_date.month, 1)

        groups.setdefault(key, []).append(row)

    results: list[dict] = []

    for key, grouped_rows in groups.items():
        first = grouped_rows[0]
        last = grouped_rows[-1]
        highs = [
            row.high_price
            for row in grouped_rows
            if row.high_price is not None
        ]
        lows = [
            row.low_price
            for row in grouped_rows
            if row.low_price is not None
        ]

        results.append(
            {
                "time": key,
                "open": first.open_price,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "close": last.close_price,
                "volume": _sum_nullable([row.trade_volume for row in grouped_rows]),
            }
        )

    return results


def _list_us_ohlc_source_rows(
    db: Session,
    *,
    symbol: str,
    from_date: date,
    to_date: date,
) -> list[USDailyPrice]:
    rows = list_us_daily_prices(
        db=db,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        limit=5000,
        offset=0,
    )
    return sorted(rows, key=lambda row: row.trade_date)


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
) -> dict | None:
    if not ensure_history:
        return None

    refresh_outputsize = outputsize
    if timeframe == "monthly" and len(points) < bars:
        refresh_outputsize = "full"

    if timeframe == "monthly" and len(points) >= bars:
        return None

    return refresh_us_daily_prices(
        db=db,
        symbol=symbol,
        outputsize=refresh_outputsize,
        adjusted=adjusted,
    )


def list_us_ohlc_chart_data(
    db: Session,
    *,
    symbol: str,
    timeframe: str = "daily",
    bars: int = 90,
    ensure_history: bool = False,
    outputsize: str = "compact",
    adjusted: bool = False,
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
    lookback_days = bars * US_CHART_LOOKBACK_MULTIPLIER[timeframe]
    start_date = end_date - timedelta(days=lookback_days)
    backfill_result = None

    rows = _list_us_ohlc_source_rows(
        db=db,
        symbol=normalized_symbol,
        from_date=start_date,
        to_date=end_date,
    )
    points = _aggregate_us_daily_rows(rows=rows, timeframe=timeframe)[-bars:]
    backfill_result = _refresh_us_ohlc_history_if_needed(
        db=db,
        symbol=normalized_symbol,
        timeframe=timeframe,
        bars=bars,
        points=points,
        ensure_history=ensure_history,
        outputsize=outputsize,
        adjusted=adjusted,
    )

    if backfill_result is not None:
        rows = _list_us_ohlc_source_rows(
            db=db,
            symbol=normalized_symbol,
            from_date=start_date,
            to_date=end_date,
        )
        points = _aggregate_us_daily_rows(rows=rows, timeframe=timeframe)[-bars:]

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
    }


def get_us_intraday_trend(*, symbol: str) -> dict:
    normalized_symbol = normalize_us_symbol(symbol)

    try:
        payload, source_url = fetch_yahoo_chart_payload(
            symbol=normalized_symbol,
            range_value="1d",
            interval="1m",
            timeout_seconds=settings.us_market_http_timeout_seconds,
        )
        return parse_yahoo_intraday_prices(
            payload,
            symbol=normalized_symbol,
            source_url=source_url,
        )
    except Exception:
        return {
            "stock_id": normalized_symbol,
            "symbol": normalized_symbol,
            "source": "unavailable",
            "previous_close": None,
            "point_count": 0,
            "points": [],
        }


def _resolve_cik_for_symbol(db: Session, symbol: str) -> str:
    stock = _ensure_us_stock_cik(db, symbol=symbol)
    cik = _clean_setting(stock.cik)
    if not cik:
        raise USMarketConfigurationError(
            f"US symbol='{stock.symbol}' has no SEC CIK in SEC company ticker data."
        )

    return cik


def upsert_us_sec_fact_records(
    db: Session,
    records: list[USSecFactRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(USSecCompanyFact)
            .filter(USSecCompanyFact.fact_key == record.fact_key)
            .first()
        )

        if existing is None:
            db.add(
                USSecCompanyFact(
                    fact_key=record.fact_key,
                    cik=record.cik,
                    symbol=record.symbol,
                    entity_name=record.entity_name,
                    taxonomy=record.taxonomy,
                    tag=record.tag,
                    label=record.label,
                    description=record.description,
                    unit=record.unit,
                    fiscal_year=record.fiscal_year,
                    fiscal_period=record.fiscal_period,
                    form=record.form,
                    filed_date=record.filed_date,
                    period_start_date=record.period_start_date,
                    period_end_date=record.period_end_date,
                    accession_number=record.accession_number,
                    frame=record.frame,
                    value_numeric=record.value_numeric,
                    value_text=record.value_text,
                    source_url=record.source_url,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.symbol = record.symbol or existing.symbol
        existing.entity_name = record.entity_name or existing.entity_name
        existing.label = record.label
        existing.description = record.description
        existing.value_numeric = record.value_numeric
        existing.value_text = record.value_text
        existing.source_url = record.source_url
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


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


def list_us_sec_company_facts(
    db: Session,
    *,
    symbol: str,
    taxonomy: str | None = None,
    tag: str | None = None,
    form: str | None = None,
    fiscal_year: int | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[USSecCompanyFact]:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USSecCompanyFact).filter(USSecCompanyFact.symbol == normalized_symbol)

    if taxonomy is not None:
        query = query.filter(USSecCompanyFact.taxonomy == taxonomy)

    if tag is not None:
        query = query.filter(USSecCompanyFact.tag == tag)

    if form is not None:
        query = query.filter(USSecCompanyFact.form == form)

    if fiscal_year is not None:
        query = query.filter(USSecCompanyFact.fiscal_year == fiscal_year)

    return (
        query.order_by(
            USSecCompanyFact.period_end_date.desc(),
            USSecCompanyFact.filed_date.desc(),
            USSecCompanyFact.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def _latest_us_sec_fact_for_tag(
    db: Session,
    *,
    symbol: str,
    tag: str,
) -> USSecCompanyFact | None:
    base_query = (
        db.query(USSecCompanyFact)
        .filter(USSecCompanyFact.symbol == symbol)
        .filter(USSecCompanyFact.tag == tag)
        .filter(USSecCompanyFact.value_numeric.isnot(None))
    )
    ordering = (
        USSecCompanyFact.period_end_date.desc(),
        USSecCompanyFact.filed_date.desc(),
        USSecCompanyFact.id.desc(),
    )
    preferred = (
        base_query.filter(USSecCompanyFact.form.in_(SEC_FUNDAMENTAL_FORMS))
        .order_by(*ordering)
        .first()
    )
    if preferred is not None:
        return preferred

    return base_query.order_by(*ordering).first()


def _latest_us_sec_fact_for_tags(
    db: Session,
    *,
    symbol: str,
    tags: tuple[str, ...],
) -> USSecCompanyFact | None:
    candidates = [
        fact
        for tag in tags
        if (fact := _latest_us_sec_fact_for_tag(db, symbol=symbol, tag=tag)) is not None
    ]
    if not candidates:
        return None

    tag_priority = {tag: index for index, tag in enumerate(tags)}

    return max(
        candidates,
        key=lambda fact: (
            fact.period_end_date or date.min,
            fact.filed_date or date.min,
            -tag_priority.get(fact.tag, len(tags)),
            fact.id,
        ),
    )


def _us_sec_metric_to_dict(metric: str, fact: USSecCompanyFact) -> dict:
    return {
        "metric": metric,
        "tag": fact.tag,
        "label": fact.label,
        "unit": fact.unit,
        "value_numeric": fact.value_numeric,
        "value_text": fact.value_text,
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
        "form": fact.form,
        "filed_date": fact.filed_date,
        "period_start_date": fact.period_start_date,
        "period_end_date": fact.period_end_date,
        "accession_number": fact.accession_number,
        "source_url": fact.source_url,
    }


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


def upsert_us_company_profile_records(
    db: Session,
    records: list[USCompanyProfileRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(USCompanyProfile)
            .filter(USCompanyProfile.provider == record.provider)
            .filter(USCompanyProfile.symbol == record.symbol)
            .first()
        )

        if existing is None:
            db.add(
                USCompanyProfile(
                    provider=record.provider,
                    symbol=record.symbol,
                    company_name=record.company_name,
                    description=record.description,
                    exchange=record.exchange,
                    sector=record.sector,
                    industry=record.industry,
                    country=record.country,
                    currency=record.currency,
                    market_cap=record.market_cap,
                    ebitda=record.ebitda,
                    pe_ratio=record.pe_ratio,
                    peg_ratio=record.peg_ratio,
                    beta=record.beta,
                    dividend_yield=record.dividend_yield,
                    eps=record.eps,
                    revenue_ttm=record.revenue_ttm,
                    profit_margin=record.profit_margin,
                    fiscal_year_end=record.fiscal_year_end,
                    latest_quarter=record.latest_quarter,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.company_name = record.company_name
        existing.description = record.description
        existing.exchange = record.exchange
        existing.sector = record.sector
        existing.industry = record.industry
        existing.country = record.country
        existing.currency = record.currency
        existing.market_cap = record.market_cap
        existing.ebitda = record.ebitda
        existing.pe_ratio = record.pe_ratio
        existing.peg_ratio = record.peg_ratio
        existing.beta = record.beta
        existing.dividend_yield = record.dividend_yield
        existing.eps = record.eps
        existing.revenue_ttm = record.revenue_ttm
        existing.profit_margin = record.profit_margin
        existing.fiscal_year_end = record.fiscal_year_end
        existing.latest_quarter = record.latest_quarter
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


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


def get_us_company_profile(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
) -> USCompanyProfile | None:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USCompanyProfile).filter(USCompanyProfile.symbol == normalized_symbol)

    if provider is not None:
        query = query.filter(USCompanyProfile.provider == provider)

    return query.order_by(USCompanyProfile.fetched_at.desc(), USCompanyProfile.id.desc()).first()


def list_us_company_profiles(
    db: Session,
    *,
    sector: str | None = None,
    industry: str | None = None,
    provider: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[USCompanyProfile]:
    query = db.query(USCompanyProfile)

    if sector is not None:
        query = query.filter(USCompanyProfile.sector == sector)

    if industry is not None:
        query = query.filter(USCompanyProfile.industry == industry)

    if provider is not None:
        query = query.filter(USCompanyProfile.provider == provider)

    return (
        query.order_by(USCompanyProfile.symbol.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def upsert_us_corporate_action_records(
    db: Session,
    records: list[USCorporateActionRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(USCorporateAction)
            .filter(USCorporateAction.provider == record.provider)
            .filter(USCorporateAction.symbol == record.symbol)
            .filter(USCorporateAction.action_type == record.action_type)
            .filter(USCorporateAction.event_date == record.event_date)
            .first()
        )

        if existing is None:
            db.add(
                USCorporateAction(
                    provider=record.provider,
                    symbol=record.symbol,
                    action_type=record.action_type,
                    event_date=record.event_date,
                    declaration_date=record.declaration_date,
                    record_date=record.record_date,
                    payment_date=record.payment_date,
                    amount=record.amount,
                    split_from=record.split_from,
                    split_to=record.split_to,
                    split_ratio=record.split_ratio,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.declaration_date = record.declaration_date
        existing.record_date = record.record_date
        existing.payment_date = record.payment_date
        existing.amount = record.amount
        existing.split_from = record.split_from
        existing.split_to = record.split_to
        existing.split_ratio = record.split_ratio
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


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


def list_us_corporate_actions(
    db: Session,
    *,
    symbol: str,
    action_type: str | None = None,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[USCorporateAction]:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USCorporateAction).filter(USCorporateAction.symbol == normalized_symbol)

    if action_type is not None:
        query = query.filter(USCorporateAction.action_type == action_type)

    if provider is not None:
        query = query.filter(USCorporateAction.provider == provider)

    if from_date is not None:
        query = query.filter(USCorporateAction.event_date >= from_date)

    if to_date is not None:
        query = query.filter(USCorporateAction.event_date <= to_date)

    return (
        query.order_by(USCorporateAction.event_date.desc(), USCorporateAction.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def upsert_us_short_volume_records(
    db: Session,
    records: list[USShortVolumeRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0
    deduped_records = list(
        OrderedDict(
            (
                (record.provider, record.symbol, record.trade_date, record.market_center),
                record,
            )
            for record in records
        ).values()
    )

    for record in deduped_records:
        existing = (
            db.query(USShortVolumeDaily)
            .filter(USShortVolumeDaily.provider == record.provider)
            .filter(USShortVolumeDaily.symbol == record.symbol)
            .filter(USShortVolumeDaily.trade_date == record.trade_date)
            .filter(USShortVolumeDaily.market_center == record.market_center)
            .first()
        )

        if existing is None:
            db.add(
                USShortVolumeDaily(
                    provider=record.provider,
                    symbol=record.symbol,
                    trade_date=record.trade_date,
                    market_center=record.market_center,
                    short_volume=record.short_volume,
                    short_exempt_volume=record.short_exempt_volume,
                    total_volume=record.total_volume,
                    short_ratio=record.short_ratio,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.short_volume = record.short_volume
        existing.short_exempt_volume = record.short_exempt_volume
        existing.total_volume = record.total_volume
        existing.short_ratio = record.short_ratio
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


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


def list_us_short_volumes(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[USShortVolumeDaily]:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USShortVolumeDaily).filter(USShortVolumeDaily.symbol == normalized_symbol)

    if provider is not None:
        query = query.filter(USShortVolumeDaily.provider == provider)

    if from_date is not None:
        query = query.filter(USShortVolumeDaily.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(USShortVolumeDaily.trade_date <= to_date)

    return (
        query.order_by(USShortVolumeDaily.trade_date.desc(), USShortVolumeDaily.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def upsert_macro_series_observation_records(
    db: Session,
    records: list[MacroSeriesObservationRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(MacroSeriesObservation)
            .filter(MacroSeriesObservation.provider == record.provider)
            .filter(MacroSeriesObservation.series_id == record.series_id)
            .filter(MacroSeriesObservation.observation_date == record.observation_date)
            .first()
        )

        if existing is None:
            db.add(
                MacroSeriesObservation(
                    provider=record.provider,
                    series_id=record.series_id,
                    series_name=record.series_name,
                    observation_date=record.observation_date,
                    value=record.value,
                    unit=record.unit,
                    frequency=record.frequency,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.series_name = record.series_name or existing.series_name
        existing.value = record.value
        existing.unit = record.unit or existing.unit
        existing.frequency = record.frequency or existing.frequency
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


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


def list_macro_series_observations(
    db: Session,
    *,
    series_id: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[MacroSeriesObservation]:
    normalized_series_id = series_id.strip().upper()
    query = db.query(MacroSeriesObservation).filter(
        MacroSeriesObservation.series_id == normalized_series_id
    )

    if provider is not None:
        query = query.filter(MacroSeriesObservation.provider == provider)

    if from_date is not None:
        query = query.filter(MacroSeriesObservation.observation_date >= from_date)

    if to_date is not None:
        query = query.filter(MacroSeriesObservation.observation_date <= to_date)

    return (
        query.order_by(
            MacroSeriesObservation.observation_date.desc(),
            MacroSeriesObservation.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_us_watchlist_group(db: Session, group_id: int) -> USWatchlistGroup:
    group = (
        db.query(USWatchlistGroup)
        .filter(USWatchlistGroup.id == group_id)
        .first()
    )

    if group is None:
        raise USWatchlistGroupNotFoundError(f"US watchlist group id={group_id} not found.")

    return group


def _validate_us_watchlist_parent(
    db: Session,
    group_id: int | None,
    parent_id: int | None,
) -> None:
    if parent_id is None:
        return

    parent = (
        db.query(USWatchlistGroup)
        .filter(USWatchlistGroup.id == parent_id)
        .first()
    )

    if parent is None:
        raise USWatchlistGroupNotFoundError(f"Parent US watchlist group id={parent_id} not found.")

    if group_id is not None and parent_id == group_id:
        raise USWatchlistInvalidTreeError("A US watchlist group cannot be its own parent.")

    current = parent
    while current is not None:
        if group_id is not None and current.id == group_id:
            raise USWatchlistInvalidTreeError("Cannot move a US watchlist group under its descendant.")

        if current.parent_id is None:
            break

        current = (
            db.query(USWatchlistGroup)
            .filter(USWatchlistGroup.id == current.parent_id)
            .first()
        )


def create_us_watchlist_group(
    db: Session,
    payload: USWatchlistGroupCreate,
) -> USWatchlistGroup:
    _validate_us_watchlist_parent(db=db, group_id=None, parent_id=payload.parent_id)

    group = USWatchlistGroup(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def list_us_watchlist_groups(
    db: Session,
    *,
    is_active: bool | None = None,
) -> list[USWatchlistGroup]:
    query = db.query(USWatchlistGroup)

    if is_active is not None:
        query = query.filter(USWatchlistGroup.is_active.is_(is_active))

    return (
        query.order_by(
            USWatchlistGroup.parent_id.asc().nullsfirst(),
            USWatchlistGroup.sort_order.asc(),
            USWatchlistGroup.id.asc(),
        )
        .all()
    )


def _us_group_to_tree_node(
    group: USWatchlistGroup,
    children_by_parent: dict[int | None, list[USWatchlistGroup]],
) -> dict:
    children = [
        _us_group_to_tree_node(child, children_by_parent)
        for child in children_by_parent.get(group.id, [])
    ]

    return {
        "id": group.id,
        "parent_id": group.parent_id,
        "group_name": group.group_name,
        "description": group.description,
        "sort_order": group.sort_order,
        "is_active": group.is_active,
        "children": children,
    }


def get_us_watchlist_tree(
    db: Session,
    *,
    is_active: bool | None = True,
) -> list[dict]:
    groups = list_us_watchlist_groups(db=db, is_active=is_active)
    children_by_parent: dict[int | None, list[USWatchlistGroup]] = {}

    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group)

    return [
        _us_group_to_tree_node(group, children_by_parent)
        for group in children_by_parent.get(None, [])
    ]


def update_us_watchlist_group(
    db: Session,
    group_id: int,
    payload: USWatchlistGroupUpdate,
) -> USWatchlistGroup:
    group = get_us_watchlist_group(db, group_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "parent_id" in update_data:
        _validate_us_watchlist_parent(
            db=db,
            group_id=group_id,
            parent_id=update_data["parent_id"],
        )

    for key, value in update_data.items():
        setattr(group, key, value)

    db.commit()
    db.refresh(group)
    return group


def _get_us_descendant_group_ids(db: Session, group_id: int) -> list[int]:
    groups = db.query(USWatchlistGroup).all()
    children_by_parent: dict[int | None, list[USWatchlistGroup]] = {}

    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group)

    result: list[int] = []

    def walk(current_id: int) -> None:
        result.append(current_id)

        for child in children_by_parent.get(current_id, []):
            walk(child.id)

    walk(group_id)
    return result


def delete_us_watchlist_group(
    db: Session,
    group_id: int,
    *,
    recursive: bool = False,
) -> dict:
    get_us_watchlist_group(db, group_id)
    group_ids = _get_us_descendant_group_ids(db, group_id)

    if not recursive and len(group_ids) > 1:
        raise USWatchlistGroupNotEmptyError(
            f"US watchlist group id={group_id} has child groups."
        )

    item_count = (
        db.query(USWatchlistItem)
        .filter(USWatchlistItem.group_id.in_(group_ids))
        .count()
    )
    if not recursive and item_count > 0:
        raise USWatchlistGroupNotEmptyError(
            f"US watchlist group id={group_id} has watchlist items."
        )

    (
        db.query(USWatchlistItem)
        .filter(USWatchlistItem.group_id.in_(group_ids))
        .delete(synchronize_session=False)
    )
    (
        db.query(USWatchlistGroup)
        .filter(USWatchlistGroup.id.in_(group_ids))
        .delete(synchronize_session=False)
    )
    db.commit()

    return {
        "deleted_group_id": group_id,
        "deleted_item_count": item_count,
        "deleted_group_count": len(group_ids),
    }


def _ensure_us_stock_exists(db: Session, symbol: str) -> USStockMaster:
    normalized_symbol = normalize_us_symbol(symbol)
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == normalized_symbol)
        .first()
    )

    if stock is None:
        raise USStockNotFoundError(
            f"US symbol='{normalized_symbol}' not found in us_stock_master. "
            "Run /api/us-market/stocks/sync-symbols first or check symbol."
        )

    return stock


def _us_watchlist_item_to_dict(
    db: Session,
    item: USWatchlistItem,
) -> dict:
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == item.symbol)
        .first()
    )

    return {
        "id": item.id,
        "group_id": item.group_id,
        "symbol": item.symbol,
        "security_name": stock.security_name if stock else None,
        "exchange": stock.exchange if stock else None,
        "asset_type": stock.asset_type if stock else None,
        "note": item.note,
        "priority": item.priority,
        "tags": item.tags,
        "enabled": item.enabled,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


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


def get_us_watchlist_item(db: Session, item_id: int) -> USWatchlistItem:
    item = (
        db.query(USWatchlistItem)
        .filter(USWatchlistItem.id == item_id)
        .first()
    )

    if item is None:
        raise USWatchlistItemNotFoundError(f"US watchlist item id={item_id} not found.")

    return item


def list_us_watchlist_items(
    db: Session,
    *,
    group_id: int | None = None,
    symbol: str | None = None,
    enabled: bool | None = None,
    include_children: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    query = db.query(USWatchlistItem)

    if group_id is not None:
        get_us_watchlist_group(db, group_id)

        if include_children:
            group_ids = _get_us_descendant_group_ids(db, group_id)
            query = query.filter(USWatchlistItem.group_id.in_(group_ids))
        else:
            query = query.filter(USWatchlistItem.group_id == group_id)

    if symbol is not None:
        query = query.filter(USWatchlistItem.symbol == normalize_us_symbol(symbol))

    if enabled is not None:
        query = query.filter(USWatchlistItem.enabled.is_(enabled))

    items = (
        query.order_by(
            USWatchlistItem.priority.asc(),
            USWatchlistItem.id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [_us_watchlist_item_to_dict(db, item) for item in items]


def list_us_watchlist_symbols(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
) -> list[str]:
    query = db.query(USWatchlistItem)

    if group_id is not None:
        get_us_watchlist_group(db, group_id)

        if include_children:
            group_ids = _get_us_descendant_group_ids(db, group_id)
            query = query.filter(USWatchlistItem.group_id.in_(group_ids))
        else:
            query = query.filter(USWatchlistItem.group_id == group_id)

    if enabled_only:
        query = query.filter(USWatchlistItem.enabled.is_(True))

    rows = (
        query.order_by(
            USWatchlistItem.priority.asc(),
            USWatchlistItem.id.asc(),
        )
        .all()
    )
    symbols: list[str] = []
    seen: set[str] = set()

    for row in rows:
        symbol = normalize_us_symbol(row.symbol)
        if not symbol or symbol in seen:
            continue

        symbols.append(symbol)
        seen.add(symbol)

    return symbols


def _close_value(row: USDailyPrice | None) -> float | None:
    if row is None:
        return None

    return row.adjusted_close if row.adjusted_close is not None else row.close_price


def _latest_distinct_us_daily_rows(
    db: Session,
    *,
    symbol: str,
    limit: int = 2,
) -> list[USDailyPrice]:
    rows = (
        db.query(USDailyPrice)
        .filter(USDailyPrice.symbol == symbol)
        .order_by(
            USDailyPrice.trade_date.desc(),
            USDailyPrice.fetched_at.desc(),
            USDailyPrice.id.desc(),
        )
        .limit(max(limit * 4, limit))
        .all()
    )
    selected_rows: list[USDailyPrice] = []
    seen_dates: set[date] = set()

    for row in rows:
        if row.trade_date in seen_dates:
            continue

        selected_rows.append(row)
        seen_dates.add(row.trade_date)

        if len(selected_rows) >= limit:
            break

    return selected_rows


def get_us_watchlist_ranking(
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

    query = db.query(USWatchlistItem)

    if group_id is not None:
        get_us_watchlist_group(db, group_id)
        group_ids = (
            _get_us_descendant_group_ids(db, group_id)
            if include_children
            else [group_id]
        )
        query = query.filter(USWatchlistItem.group_id.in_(group_ids))

    if enabled_only:
        query = query.filter(USWatchlistItem.enabled.is_(True))

    items = (
        query.order_by(
            USWatchlistItem.priority.asc(),
            USWatchlistItem.id.asc(),
        )
        .all()
    )
    unique_items: list[USWatchlistItem] = []
    seen_symbols: set[str] = set()

    for item in items:
        symbol = normalize_us_symbol(item.symbol)
        if not symbol or symbol in seen_symbols:
            continue

        unique_items.append(item)
        seen_symbols.add(symbol)

    symbols = [normalize_us_symbol(item.symbol) for item in unique_items]
    stocks_by_symbol = {
        stock.symbol: stock
        for stock in db.query(USStockMaster)
        .filter(USStockMaster.symbol.in_(symbols))
        .all()
    } if symbols else {}
    rows: list[dict] = []

    for item in unique_items:
        symbol = normalize_us_symbol(item.symbol)
        stock = stocks_by_symbol.get(symbol)
        price_rows = _latest_distinct_us_daily_rows(db=db, symbol=symbol, limit=2)
        latest = price_rows[0] if price_rows else None
        previous = price_rows[1] if len(price_rows) > 1 else None
        close = _close_value(latest)
        previous_close = _close_value(previous)
        change = (
            close - previous_close
            if close is not None and previous_close is not None
            else None
        )
        change_pct = (
            (change / previous_close) * 100
            if change is not None and previous_close not in {None, 0}
            else None
        )

        rows.append(
            {
                "rank": 0,
                "symbol": symbol,
                "security_name": (
                    stock.security_name
                    if stock is not None
                    else None
                ),
                "exchange": stock.exchange if stock is not None else None,
                "asset_type": stock.asset_type if stock is not None else None,
                "group_id": item.group_id,
                "trade_date": latest.trade_date if latest is not None else None,
                "close": close,
                "previous_close": previous_close,
                "change": change,
                "change_pct": change_pct,
                "volume": latest.trade_volume if latest is not None else None,
                "status": "ready" if close is not None else "no_data",
                "error_message": None,
            }
        )

    if rank_by != "none":
        ranked_rows = [
            row
            for row in rows
            if row.get(rank_by) is not None
        ]
        no_value_rows = [
            row
            for row in rows
            if row.get(rank_by) is None
        ]
        ranked_rows.sort(
            key=lambda row: row[rank_by],
            reverse=sort_order == "desc",
        )
        rows = ranked_rows + no_value_rows

    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    no_data_count = sum(1 for row in rows if row["status"] == "no_data")

    return {
        "group_id": group_id,
        "include_children": include_children,
        "rank_by": rank_by,
        "sort_order": sort_order,
        "requested_symbol_count": len(rows),
        "ranked_count": len(rows) - no_data_count,
        "no_data_count": no_data_count,
        "error_count": 0,
        "results": rows,
    }


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
    symbols = list_us_watchlist_symbols(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )
    total = len(symbols)

    if progress_callback is not None:
        progress_callback(0, max(total, 1), "Refreshing US watchlist daily prices.")

    if not symbols:
        return {
            "status": "empty",
            "group_id": group_id,
            "symbol_count": 0,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "errors": [],
        }

    fetched_count = 0
    inserted_count = 0
    updated_count = 0
    errors: list[dict[str, str]] = []

    for index, symbol in enumerate(symbols, start=1):
        try:
            result = refresh_us_daily_prices(
                db=db,
                symbol=symbol,
                outputsize=outputsize,
                adjusted=adjusted,
            )
            fetched_count += result["fetched_count"]
            inserted_count += result["inserted_count"]
            updated_count += result["updated_count"]
        except USMarketConfigurationError:
            raise
        except Exception as exc:
            errors.append(
                {
                    "symbol": symbol,
                    "message": str(exc),
                }
            )

        if progress_callback is not None:
            progress_callback(index, total, f"Refreshed {index}/{total} US symbols.")

        if index < total and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return {
        "status": "partial_success" if errors else "success",
        "group_id": group_id,
        "symbol_count": total,
        "fetched_count": fetched_count,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "errors": errors,
    }


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


def delete_us_watchlist_item(db: Session, item_id: int) -> None:
    item = get_us_watchlist_item(db, item_id)
    db.delete(item)
    db.commit()


__all__ = [
    "USMarketConfigurationError",
    "USMarketDataFetchError",
    "USStockNotFoundError",
    "USWatchlistDuplicateItemError",
    "USWatchlistGroupNotEmptyError",
    "USWatchlistGroupNotFoundError",
    "USWatchlistInvalidTreeError",
    "USWatchlistItemNotFoundError",
    "create_us_watchlist_group",
    "create_us_watchlist_item",
    "delete_us_watchlist_group",
    "delete_us_watchlist_item",
    "get_us_company_profile",
    "get_us_intraday_trend",
    "get_us_sec_fundamental_summary",
    "get_us_stock",
    "get_us_watchlist_group",
    "get_us_watchlist_item",
    "get_us_watchlist_tree",
    "get_us_watchlist_ranking",
    "list_macro_series_observations",
    "list_us_company_profiles",
    "list_us_corporate_actions",
    "list_us_daily_prices",
    "list_us_ohlc_chart_data",
    "list_us_sec_company_facts",
    "list_us_short_volumes",
    "list_us_stocks",
    "list_us_watchlist_groups",
    "list_us_watchlist_items",
    "list_us_watchlist_symbols",
    "refresh_fred_macro_series",
    "refresh_us_company_profile_from_alphavantage",
    "refresh_us_corporate_actions_from_alphavantage",
    "refresh_us_daily_prices",
    "refresh_us_daily_prices_from_alphavantage",
    "refresh_us_daily_prices_from_yahoo_chart",
    "refresh_us_sec_companyfacts",
    "refresh_us_short_volume_from_finra",
    "refresh_us_watchlist_daily_prices",
    "search_us_stocks",
    "sync_us_sec_company_data",
    "sync_us_symbol_master",
    "update_us_watchlist_group",
    "update_us_watchlist_item",
    "upsert_macro_series_observation_records",
    "upsert_us_company_profile_records",
    "upsert_us_corporate_action_records",
    "upsert_us_daily_price_records",
    "upsert_us_sec_fact_records",
    "upsert_us_short_volume_records",
    "upsert_us_symbol_records",
]
