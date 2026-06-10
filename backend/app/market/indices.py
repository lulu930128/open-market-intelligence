from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from urllib.parse import quote

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import MarketDailyPrice, MarketIndexDailyStat, SourceRegistry
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
TWSE_INDEX_LIST_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
TWSE_DAILY_QUOTES_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_MARKET_DAILY_URL = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"
TWSE_MARKET_DAILY_HISTORY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TWSE_COMPANY_BASIC_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_DAILY_INDEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_daily_trading_index"
TPEX_DAILY_QUOTES_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
TAIPEI_TZ = timezone(timedelta(hours=8))
CACHE_TTL_SECONDS = 45
INDEX_LIST_CACHE_TTL_SECONDS = 300
MAX_INDEX_STAT_FETCH_WORKERS = 4

INDEX_CONFIGS = (
    {
        "index_id": "TAIEX",
        "label": "加權指數",
        "short_label": "加權",
        "market": "TWSE",
        "symbol": "^TWII",
    },
    {
        "index_id": "TPEX",
        "label": "櫃買指數",
        "short_label": "櫃買",
        "market": "TPEX",
        "symbol": "^TWOII",
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
_QUOTE_STATS_CACHE: dict[str, dict[str, object]] = {}
_INDEX_LIST_CACHE: dict[str, dict[str, object]] = {}
_SHARES_CACHE: dict[str, dict[str, object]] = {}
_CONTRIBUTION_CACHE: dict[str, dict[str, object]] = {}


def _as_float(value) -> float | None:
    if value is None:
        return None

    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _as_int(value) -> int | None:
    if value is None:
        return None

    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _list_value(values, index: int):
    if not isinstance(values, list) or index >= len(values):
        return None

    return values[index]


def _fetch_json(url: str):
    response = requests.get(
        url,
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=20,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.json()


def _parse_trade_date(value) -> date | None:
    if isinstance(value, date):
        return value

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    for separator in ("/", "-"):
        if separator not in text:
            continue

        parts = text.split(separator)

        if len(parts) == 3 and parts[0].isdigit() and len(parts[0]) <= 3:
            year = int(parts[0]) + 1911
            return date(year, int(parts[1]), int(parts[2]))

    normalized = text.replace("/", "").replace("-", "")

    if len(normalized) == 7 and normalized.isdigit():
        year = int(normalized[:3]) + 1911
        return date(year, int(normalized[3:5]), int(normalized[5:7]))

    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    return None


def _signed_change(sign_value, change_value) -> float | None:
    change = _as_float(change_value)

    if change is None:
        return None

    sign = str(sign_value or "").strip()

    if sign in {"-", "－"}:
        return -abs(change)

    if sign in {"+", "＋"}:
        return abs(change)

    return change


def _regular_stock_code(value) -> str | None:
    if value is None:
        return None

    code = str(value).strip()

    if len(code) == 4 and code.isdigit():
        return code

    return None


def _moving_average(values: list[float | None], window: int) -> float | None:
    valid_values = [value for value in values[-window:] if value is not None]

    if len(valid_values) < window:
        return None

    return sum(valid_values) / window


def _market_source_name(market: str) -> str:
    if market == "TPEX":
        return TPEX_DAILY_QUOTES_SOURCE_NAME

    return TWSE_DAILY_TRADING_SOURCE_NAME


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


def _resolve_market_breadth(db: Session, market: str) -> dict | None:
    try:
        quote_breadth = _fetch_market_quote_breadth(market)

        if quote_breadth is not None:
            return quote_breadth
    except Exception:
        pass

    return _latest_market_breadth(db=db, market=market)


def _fetch_recent_index_trade_values(market: str) -> dict[date, int]:
    index_id = "TPEX" if market == "TPEX" else "TAIEX"
    return {
        item["trade_date"]: item["trade_value"]
        for item in _fetch_recent_market_index_daily_stats(index_id=index_id, market=market)
        if item.get("trade_value") is not None
    }


def _twse_market_daily_history_url(month_start: date) -> str:
    return f"{TWSE_MARKET_DAILY_HISTORY_URL}?date={month_start:%Y%m%d}&response=json"


def _row_value(row, keys: Iterable[str], positions: Iterable[int]):
    if isinstance(row, dict):
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return None

    if isinstance(row, (list, tuple)):
        for position in positions:
            if position < len(row):
                value = row[position]
                if value not in (None, ""):
                    return value

    return None


def _market_index_stat_item(
    *,
    trade_date: date | None,
    trade_volume: int | None,
    trade_value: int | None,
    transaction_count: int | None,
    close_value: float | None,
    price_change: float | None,
) -> dict | None:
    if trade_date is None:
        return None

    if trade_volume is None and trade_value is None and close_value is None:
        return None

    return {
        "trade_date": trade_date,
        "trade_volume": trade_volume,
        "trade_value": trade_value,
        "transaction_count": transaction_count,
        "close_value": close_value,
        "price_change": price_change,
    }


def _parse_twse_market_daily_history_rows(payload) -> list[dict]:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []

    results: list[dict] = []

    for row in rows:
        item = _market_index_stat_item(
            trade_date=_parse_trade_date(
                _row_value(row, keys=("Date", "date", "日期"), positions=(0,))
            ),
            trade_volume=_as_int(
                _row_value(row, keys=("TradeVolume", "trade_volume", "成交股數"), positions=(1,))
            ),
            trade_value=_as_int(
                _row_value(row, keys=("TradeValue", "trade_value", "成交金額"), positions=(2,))
            ),
            transaction_count=_as_int(
                _row_value(row, keys=("Transaction", "transaction_count", "成交筆數"), positions=(3,))
            ),
            close_value=_as_float(
                _row_value(row, keys=("TAIEX", "close_value", "發行量加權股價指數"), positions=(4,))
            ),
            price_change=_as_float(
                _row_value(row, keys=("Change", "price_change", "漲跌點數"), positions=(5,))
            ),
        )
        if item is not None:
            results.append(item)

    return results


def _parse_tpex_market_daily_rows(payload) -> list[dict]:
    rows = payload if isinstance(payload, list) else []
    results: list[dict] = []

    for row in rows:
        item = _market_index_stat_item(
            trade_date=_parse_trade_date(_row_value(row, keys=("Date", "date"), positions=(0,))),
            trade_volume=_as_int(
                _row_value(
                    row,
                    keys=("TradeVolume", "Volume", "TransactionVolume"),
                    positions=(1,),
                )
            ),
            trade_value=_as_int(
                _row_value(row, keys=("TradeAmount", "TradeValue", "TransactionAmount"), positions=(2,))
            ),
            transaction_count=_as_int(
                _row_value(row, keys=("Transaction", "TransactionCount"), positions=(3,))
            ),
            close_value=_as_float(_row_value(row, keys=("Index", "Close", "TPEX"), positions=(4,))),
            price_change=_as_float(_row_value(row, keys=("Change",), positions=(5,))),
        )
        if item is not None:
            results.append(item)

    return results


def _fetch_twse_market_daily_stats_for_month(month_start: date) -> tuple[list[dict], str]:
    url = _twse_market_daily_history_url(month_start)
    payload = _fetch_json(url)
    return _parse_twse_market_daily_history_rows(payload), url


def _fetch_recent_market_index_daily_stats(index_id: str, market: str) -> list[dict]:
    if market == "TPEX":
        payload = _fetch_json(TPEX_DAILY_INDEX_URL)
        return _parse_tpex_market_daily_rows(payload)

    payload = _fetch_json(TWSE_MARKET_DAILY_URL)
    return _parse_twse_market_daily_history_rows(payload)


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


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

    db.commit()

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
    result = {
        "status": "success",
        "index_id": index_id,
        "market": market,
        "source": None,
        "requested_month_count": len(months),
        "fetched_month_count": 0,
        "skipped_existing_month_count": len(months) - len(missing_months),
        "inserted_count": 0,
        "updated_count": 0,
        "errors": [],
    }

    if index_id == "TAIEX" and missing_months:
        result["source"] = "twse_rwd_fmtqik"
        with ThreadPoolExecutor(max_workers=MAX_INDEX_STAT_FETCH_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_twse_market_daily_stats_for_month, month): month
                for month in missing_months
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
    response = requests.get(
        YAHOO_CHART_URL.format(symbol=quote(symbol, safe="")),
        params={
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
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

    response = requests.get(
        YAHOO_CHART_URL.format(symbol=quote(symbol, safe="")),
        params={
            "range": "1d",
            "interval": "1m",
            "includePrePost": "false",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
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
        "previous_close": _as_float(meta.get("chartPreviousClose"))
        or _as_float(meta.get("regularMarketPreviousClose")),
        "point_count": len(intraday_points),
        "points": intraday_points,
    }


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


def get_market_index_intraday(index_id: str) -> dict:
    normalized_index_id = index_id.upper()
    config = INDEX_CONFIG_BY_ID.get(normalized_index_id)

    if config is None:
        supported = ", ".join(sorted(INDEX_CONFIG_BY_ID))
        raise ValueError(f"index_id must be one of: {supported}.")

    yahoo_error: Exception | None = None

    try:
        payload = _fetch_yahoo_index_intraday(config)

        if payload["point_count"] > 0:
            return payload
    except Exception as exc:
        yahoo_error = exc

    fallback_payload = _index_intraday_fallback_from_list(config)

    if fallback_payload is not None:
        return fallback_payload

    if yahoo_error is not None:
        raise yahoo_error

    return {
        "stock_id": config["index_id"],
        "symbol": config["symbol"],
        "source": "unavailable",
        "previous_close": None,
        "point_count": 0,
        "points": [],
    }


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


def _contribution_quote_rows(market: str) -> tuple[list[dict], dict[str, int], str, dict[str, str]]:
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


def get_market_index_contributions(index_id: str, limit: int = 20) -> dict:
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

    if cached and monotonic() < float(cached["expires_at"]):
        payload = cached.get("payload")

        if isinstance(payload, dict):
            return payload

    market = str(config["market"])
    rows, shares_by_code, source, keys = _contribution_quote_rows(market)
    index_item = _market_index_item_for_contribution(market)
    index_close = _as_float(index_item.get("close")) if index_item else None
    index_change = _as_float(index_item.get("change")) if index_item else None
    trade_date = _parse_trade_date(rows[0].get(keys["date"])) if rows else None
    candidates: list[dict] = []
    total_market_value = 0.0

    for row in rows:
        if not isinstance(row, dict):
            continue

        code = _regular_stock_code(row.get(keys["code"]))

        if code is None:
            continue

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
            }
            for index, item in enumerate(items)
        ]

    payload = {
        "index_id": normalized_index_id,
        "market": market,
        "source": source,
        "method": "estimated_market_cap_weight",
        "as_of": datetime.now(TAIPEI_TZ),
        "trade_date": trade_date,
        "index_close": index_close,
        "index_change": index_change,
        "total_market_value": total_market_value if total_market_value > 0 else None,
        "positive": ranked(positive),
        "negative": ranked(negative),
    }
    _CONTRIBUTION_CACHE[cache_key] = {
        "expires_at": monotonic() + INDEX_LIST_CACHE_TTL_SECONDS,
        "payload": payload,
    }
    return payload


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
    backfill_result = None

    if db is not None and selected_points:
        try:
            backfill_result = _ensure_market_index_daily_stat_coverage(
                db=db,
                index_id=normalized_index_id,
                market=str(config["market"]),
                from_date=stat_from_date,
                to_date=stat_to_date,
            )
        except Exception as exc:
            db.rollback()
            backfill_result = {
                "status": "error",
                "index_id": normalized_index_id,
                "market": str(config["market"]),
                "message": f"Index daily stat refresh failed: {exc}",
            }

        values_by_period = _load_market_index_stat_values(
            db=db,
            index_id=normalized_index_id,
            timeframe=timeframe,
            from_date=stat_from_date,
            to_date=stat_to_date,
        )
        _apply_market_index_stat_values(
            selected_points,
            timeframe=timeframe,
            values_by_period=values_by_period,
        )
    else:
        try:
            trade_values_by_date = _fetch_recent_index_trade_values(str(config["market"]))

            for point in selected_points:
                point["trade_value"] = trade_values_by_date.get(point["time"])
        except Exception:
            pass

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
    }


def get_market_index_summary(db: Session, force_refresh: bool = False) -> dict:
    if not force_refresh and monotonic() < float(_CACHE["expires_at"]):
        cached_payload = _CACHE["payload"]

        if isinstance(cached_payload, dict):
            return cached_payload

    indices: list[dict] = []

    for config in INDEX_CONFIGS:
        try:
            index_payload = _fetch_yahoo_index(config)
        except Exception as exc:
            index_payload = _unavailable_index(config, exc)

        market_breadth = _resolve_market_breadth(
            db=db,
            market=str(config["market"]),
        )
        trade_value = (
            market_breadth.get("trade_value")
            if isinstance(market_breadth, dict)
            else None
        )
        try:
            official_trade_value = _fetch_recent_index_trade_values(str(config["market"])).get(
                index_payload.get("time")
            )

            if official_trade_value is not None:
                trade_value = official_trade_value
        except Exception:
            pass

        index_payload["breadth"] = market_breadth
        index_payload["trade_value"] = trade_value
        index_payload["estimated_trade_value"] = _estimate_session_volume(
            volume=trade_value,
            as_of=index_payload.get("as_of"),
        )
        indices.append(index_payload)

    payload = {
        "as_of": datetime.now(TAIPEI_TZ),
        "source": "yahoo_finance_chart",
        "indices": indices,
    }
    _CACHE["payload"] = payload
    _CACHE["expires_at"] = monotonic() + CACHE_TTL_SECONDS
    return payload
