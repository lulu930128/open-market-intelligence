from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from threading import Lock
import time as monotonic_time

from sqlalchemy.orm import Session

from app.db.models import MarketIntradayBar, StockMaster, utc_now
from app.market.providers import http_get
from app.market.tw_disposition import get_taiwan_disposition_status
from app.market.twse_mis_observation import resolve_twse_mis_actual_trade
from app.observability.provider_fallback import observe_provider_fallback


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NSTOCK_MINUTE_URL = "https://shop.nstock.tw/api/v2/minute-stock-data/data"
TWSE_MIS_STOCK_INFO_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TAIPEI_TZ = timezone(timedelta(hours=8))
INTRADAY_CACHE_TTL_SECONDS = 4.75
_INTRADAY_CACHE: dict[str, tuple[float, dict]] = {}
_INTRADAY_CACHE_LOCK = Lock()
_INTRADAY_FETCH_LOCKS: dict[str, Lock] = {}

INTRADAY_HISTORY_PROVIDER = "yahoo_finance_chart"
# Yahoo's `5d` minute range is trading-day based. Query the local DB with a
# wider calendar-day window so weekends and holidays do not hide persisted bars.
INTRADAY_HISTORY_FIVE_TRADING_DAY_QUERY_DAYS = 21
INTRADAY_HISTORY_INTERVAL_CONFIGS = {
    "1m": {
        "fetch_interval": "1m",
        "range": "5d",
        "days": INTRADAY_HISTORY_FIVE_TRADING_DAY_QUERY_DAYS,
    },
    "5m": {"fetch_interval": "5m", "range": "1mo", "days": 31},
    "15m": {"fetch_interval": "15m", "range": "1mo", "days": 31},
    "30m": {"fetch_interval": "30m", "range": "1mo", "days": 31},
    "1h": {"fetch_interval": "60m", "range": "3mo", "days": 93},
    "4h": {"fetch_interval": "60m", "range": "3mo", "days": 93},
}
INTRADAY_HISTORY_RANGE_DAYS = {
    "1d": 1,
    "5d": INTRADAY_HISTORY_FIVE_TRADING_DAY_QUERY_DAYS,
    "1mo": 31,
    "3mo": 93,
}


def _cache_get(cache_key: str) -> dict | None:
    with _INTRADAY_CACHE_LOCK:
        cached = _INTRADAY_CACHE.get(cache_key)
        if cached is None:
            return None

        cached_at, payload = cached
        if monotonic_time.monotonic() - cached_at > INTRADAY_CACHE_TTL_SECONDS:
            _INTRADAY_CACHE.pop(cache_key, None)
            return None

        return deepcopy(payload)


def _cache_set(cache_key: str, payload: dict) -> dict:
    with _INTRADAY_CACHE_LOCK:
        _INTRADAY_CACHE[cache_key] = (
            monotonic_time.monotonic(),
            deepcopy(payload),
        )
    return payload


def _get_intraday_fetch_lock(cache_key: str) -> Lock:
    with _INTRADAY_CACHE_LOCK:
        return _INTRADAY_FETCH_LOCKS.setdefault(cache_key, Lock())


def _as_float(value) -> float | None:
    if value is None:
        return None

    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _as_int(value) -> int | None:
    if value is None:
        return None

    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def _list_value(values, index: int):
    if not isinstance(values, list) or index >= len(values):
        return None

    return values[index]


def _get_stock(db: Session, stock_id: str) -> StockMaster | None:
    return db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()


def _yahoo_symbol(stock_id: str, market: str | None) -> str:
    if market == "TPEX":
        return f"{stock_id}.TWO"

    return f"{stock_id}.TW"


def _mis_exchange(market: str | None) -> str:
    if market == "TPEX":
        return "otc"

    return "tse"


def _fetch_yahoo_intraday(
    stock_id: str,
    market: str | None,
    *,
    range_value: str = "1d",
    interval: str = "1m",
) -> dict:
    symbol = _yahoo_symbol(stock_id=stock_id, market=market)
    url = YAHOO_CHART_URL.format(symbol=symbol)
    response = http_get(
        url,
        params={"range": range_value, "interval": interval, "includePrePost": "false"},
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
        return {
            "stock_id": stock_id,
            "symbol": symbol,
            "source": "yahoo_finance_chart",
            "previous_close": None,
            "point_count": 0,
            "points": [],
            "source_url": response.url,
        }

    meta = result.get("meta") or {}
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    timestamps = result.get("timestamp") or []
    offset = int(meta.get("gmtoffset") or 28800)
    tz = timezone(timedelta(seconds=offset))

    opens = quote.get("open")
    highs = quote.get("high")
    lows = quote.get("low")
    closes = quote.get("close")
    volumes = quote.get("volume")
    points: list[dict] = []

    for index, timestamp in enumerate(timestamps):
        price = _as_float(_list_value(closes, index))

        if price is None:
            continue

        points.append(
            {
                "time": datetime.fromtimestamp(timestamp, tz=tz).isoformat(),
                "price": price,
                "volume": _as_int(_list_value(volumes, index)),
                "open": _as_float(_list_value(opens, index)),
                "high": _as_float(_list_value(highs, index)),
                "low": _as_float(_list_value(lows, index)),
            }
        )

    previous_close = _as_float(meta.get("previousClose")) or _as_float(
        meta.get("chartPreviousClose")
    )

    return {
        "stock_id": stock_id,
        "symbol": symbol,
        "source": "yahoo_finance_chart",
        "previous_close": previous_close,
        "point_count": len(points),
        "points": points,
        "source_url": response.url,
    }


def _build_snapshot_time(date_text: str | None, time_text: str) -> str:
    if date_text and len(date_text) == 8 and date_text.isdigit():
        day = datetime(
            int(date_text[:4]),
            int(date_text[4:6]),
            int(date_text[6:8]),
            tzinfo=TAIPEI_TZ,
        )
    else:
        day = datetime.now(TAIPEI_TZ)

    parts = time_text.split(":")

    if len(parts) == 3:
        return datetime.combine(
            day.date(),
            time(int(parts[0]), int(parts[1]), int(parts[2])),
            tzinfo=TAIPEI_TZ,
        ).isoformat()

    return day.isoformat()


def _parse_nstock_time(date_text: str | None, time_text: str | None) -> datetime | None:
    if (
        not date_text
        or not time_text
        or len(date_text) != 8
        or len(time_text) != 6
        or not date_text.isdigit()
        or not time_text.isdigit()
    ):
        return None

    try:
        return datetime(
            int(date_text[:4]),
            int(date_text[4:6]),
            int(date_text[6:8]),
            int(time_text[:2]),
            int(time_text[2:4]),
            int(time_text[4:6]),
            tzinfo=TAIPEI_TZ,
        )
    except ValueError:
        return None


def _fetch_nstock_intraday(stock_id: str) -> dict:
    response = http_get(
        NSTOCK_MINUTE_URL,
        params={"stock_id": stock_id},
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    data = (payload.get("data") or [None])[0]

    if not data:
        return {
            "stock_id": stock_id,
            "symbol": stock_id,
            "source": "nstock_minute_stock_data",
            "previous_close": None,
            "point_count": 0,
            "points": [],
        }

    points: list[dict] = []
    for row in data.get("分K") or []:
        point_time = _parse_nstock_time(row.get("交易日"), row.get("交易時間"))
        close_price = _as_float(row.get("收盤價"))

        if point_time is None or close_price is None:
            continue

        points.append(
            {
                "time": point_time.isoformat(),
                "price": close_price,
                "volume": _volume_lots_to_shares(row.get("成交量")),
                "open": _as_float(row.get("開盤價")),
                "high": _as_float(row.get("最高價")),
                "low": _as_float(row.get("最低價")),
            }
        )

    points.sort(key=lambda item: item["time"])
    total_volume = _volume_lots_to_shares(data.get("總成交量"))
    if total_volume is not None and total_volume > 0:
        _fill_volume_gap(points, total_volume)

    return {
        "stock_id": stock_id,
        "symbol": stock_id,
        "source": "nstock_minute_stock_data",
        "previous_close": _as_float(data.get("參考價")),
        "point_count": len(points),
        "points": points,
    }


def _fetch_mis_message(stock_id: str, market: str | None) -> dict | None:
    exchange = _mis_exchange(market)
    response = http_get(
        TWSE_MIS_STOCK_INFO_URL,
        params={
            "ex_ch": f"{exchange}_{stock_id}.tw",
            "json": "1",
            "delay": "0",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    return (payload.get("msgArray") or [None])[0]


def _parse_snapshot_datetime(message: dict) -> datetime | None:
    trade_date = message.get("d")
    latest_time = message.get("t") or message.get("%")

    if not trade_date or not latest_time:
        return None

    try:
        return datetime.fromisoformat(_build_snapshot_time(trade_date, latest_time))
    except ValueError:
        return None


def _point_datetime(point: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(point["time"]))
    except (KeyError, ValueError):
        return None


def _point_time_key(point: dict) -> tuple[str, str] | None:
    point_time = _point_datetime(point)
    if point_time is None:
        return None

    return point_time.strftime("%Y%m%d"), point_time.strftime("%H:%M:%S")


def _normalize_bar_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIPEI_TZ)

    return value.astimezone(TAIPEI_TZ)


def _is_taiwan_regular_session_time(value: datetime) -> bool:
    local_time = _normalize_bar_time(value)
    minutes = local_time.hour * 60 + local_time.minute

    return 9 * 60 <= minutes <= 13 * 60 + 30


def _query_intraday_rows(
    db: Session,
    *,
    stock_id: str,
    interval: str,
    from_time: datetime,
) -> list[MarketIntradayBar]:
    return (
        db.query(MarketIntradayBar)
        .filter(MarketIntradayBar.stock_id == stock_id)
        .filter(MarketIntradayBar.interval == interval)
        .filter(MarketIntradayBar.bar_time >= from_time)
        .order_by(MarketIntradayBar.bar_time.asc())
        .limit(5000)
        .all()
    )


def _intraday_row_to_point(row: MarketIntradayBar) -> dict:
    return {
        "time": _normalize_bar_time(row.bar_time),
        "open": row.open_price,
        "high": row.high_price,
        "low": row.low_price,
        "close": row.close_price,
        "volume": row.trade_volume,
        "trade_value": row.trade_value,
        "transaction_count": None,
    }


def _interval_seconds(interval: str) -> int:
    normalized = str(interval or "1m").strip().lower()
    if normalized.endswith("s") and normalized[:-1].isdigit():
        return int(normalized[:-1])
    if normalized.endswith("m") and normalized[:-1].isdigit():
        return int(normalized[:-1]) * 60
    if normalized.endswith("h") and normalized[:-1].isdigit():
        return int(normalized[:-1]) * 3600
    return 60


def _provider_volume_unit(source: str) -> str:
    normalized = str(source or "").lower()
    if "twse_mis" in normalized or normalized.startswith("nstock"):
        return "lots"
    if "yahoo" in normalized:
        return "shares"
    return "unknown"


def _intraday_bar_semantics(
    point: dict,
    *,
    point_time: datetime | None,
    interval: str,
) -> dict:
    explicit_bar_type = str(point.get("bar_type") or "").strip().lower()
    known_bar_types = {
        "regular_interval",
        "closing_auction",
        "official_close_marker",
        "post_close_summary",
        "provider_irregular",
        "synthetic_fill",
    }
    synthetic = bool(point.get("synthetic")) or explicit_bar_type == "synthetic_fill"
    volume = _as_int(
        point.get("volume_shares")
        if point.get("volume_shares") is not None
        else point.get("volume")
    )

    if explicit_bar_type in known_bar_types:
        bar_type = explicit_bar_type
    elif synthetic:
        bar_type = "synthetic_fill"
    elif point_time is None:
        bar_type = "provider_irregular"
    else:
        local_time = point_time.astimezone(TAIPEI_TZ)
        interval_seconds = max(_interval_seconds(interval), 1)
        seconds_from_hour = local_time.minute * 60 + local_time.second
        interval_aligned = seconds_from_hour % interval_seconds == 0
        clock = local_time.time().replace(tzinfo=None)
        if not interval_aligned:
            bar_type = "provider_irregular"
        elif clock == time(13, 30) and (volume is None or volume == 0):
            bar_type = "official_close_marker"
        elif time(13, 25) <= clock <= time(13, 30):
            bar_type = "closing_auction"
        elif time(9, 0) <= clock < time(13, 25):
            bar_type = "regular_interval"
        else:
            bar_type = "provider_irregular"

    session_phase = {
        "regular_interval": "regular",
        "closing_auction": "closing_auction",
        "official_close_marker": "post_close",
        "post_close_summary": "post_close",
        "synthetic_fill": "synthetic",
        "provider_irregular": "provider_irregular",
    }[bar_type]
    market_event = {
        "regular_interval": "continuous_trading",
        "closing_auction": "closing_auction",
        "official_close_marker": "official_close",
        "post_close_summary": "post_close_confirmation",
        "synthetic_fill": "synthetic_fill",
        "provider_irregular": "provider_irregular",
    }[bar_type]
    source_event_type = (
        point.get("source_event_type")
        or ("synthetic" if synthetic else "provider_bar")
    )
    return {
        "bar_type": bar_type,
        "synthetic": synthetic,
        "session_phase": session_phase,
        "market_event": market_event,
        "source_event_type": source_event_type,
        "gap_reason": point.get("gap_reason"),
    }


def _latest_trade_date_points(
    points: list[dict],
) -> tuple[date | None, list[dict]]:
    dated_points: list[tuple[date, dict]] = []
    for point in points:
        point_time = _point_datetime(point)
        if point_time is None:
            continue
        dated_points.append((_normalize_bar_time(point_time).date(), point))

    if not dated_points:
        return None, []

    latest_trade_date = max(trade_date for trade_date, _ in dated_points)
    return latest_trade_date, [
        point
        for trade_date, point in dated_points
        if trade_date == latest_trade_date
    ]


def _intraday_bar_metrics(points: list[dict]) -> dict[str, int | float | None]:
    official_trade_value = 0
    estimated_trade_value = 0.0
    exact_value_points = 0
    volume_points = 0
    total_volume_shares = 0
    weighted_price_volume = 0.0

    for point in points:
        volume_shares = _as_int(point.get("volume_shares"))
        if volume_shares is not None:
            volume_points += 1
            total_volume_shares += max(volume_shares, 0)

        exact_trade_value = _as_int(point.get("trade_value"))
        approx_trade_value = _as_float(point.get("approx_trade_value"))
        if exact_trade_value is not None:
            exact_value_points += 1
            official_trade_value += exact_trade_value
            estimated_trade_value += exact_trade_value
        elif approx_trade_value is not None:
            estimated_trade_value += approx_trade_value

        close_price = _as_float(point.get("close") or point.get("price"))
        if close_price is not None and volume_shares is not None and volume_shares > 0:
            weighted_price_volume += close_price * volume_shares

    exact_complete = volume_points > 0 and exact_value_points == volume_points
    return {
        "volume_points": volume_points,
        "total_volume_shares": total_volume_shares,
        "official_trade_value": official_trade_value,
        "estimated_trade_value": estimated_trade_value,
        "exact_value_points": exact_value_points,
        "exact_complete": int(exact_complete),
        "approx_vwap": (
            weighted_price_volume / total_volume_shares
            if total_volume_shares > 0
            else None
        ),
        "official_vwap": (
            official_trade_value / total_volume_shares
            if exact_complete and total_volume_shares > 0
            else None
        ),
    }


def _enrich_intraday_contract(
    points: list[dict],
    *,
    interval: str,
    source: str,
    now: datetime | None = None,
) -> tuple[list[dict], dict]:
    checked_at = (now or datetime.now(TAIPEI_TZ)).astimezone(TAIPEI_TZ)
    provider_volume_unit = _provider_volume_unit(source)
    interval_delta = timedelta(seconds=_interval_seconds(interval))
    enriched: list[dict] = []

    for raw_point in points:
        point = dict(raw_point)
        point_time = _point_datetime(point)
        volume_shares = _as_int(point.get("volume"))
        exact_trade_value = _as_int(point.get("trade_value"))
        open_price = _as_float(point.get("open"))
        high_price = _as_float(point.get("high"))
        low_price = _as_float(point.get("low"))
        close_price = _as_float(point.get("close") or point.get("price"))
        typical_prices = [
            value
            for value in (high_price, low_price, close_price)
            if value is not None
        ]
        typical_price = (
            sum(typical_prices) / len(typical_prices)
            if typical_prices
            else open_price
        )
        approx_trade_value = (
            typical_price * volume_shares
            if typical_price is not None
            and volume_shares is not None
            and volume_shares >= 0
            else None
        )
        bar_close_time = point_time + interval_delta if point_time is not None else None
        is_partial = bool(
            bar_close_time is not None
            and point_time is not None
            and point_time.date() == checked_at.date()
            and checked_at < bar_close_time
        )
        elapsed_seconds = (
            max(int((checked_at - point_time).total_seconds()), 0)
            if point_time is not None
            else None
        )
        bar_semantics = _intraday_bar_semantics(
            point,
            point_time=point_time,
            interval=interval,
        )
        finalized = not is_partial if point_time is not None else False
        indicator_eligible = bool(
            finalized
            and not bar_semantics["synthetic"]
            and bar_semantics["bar_type"]
            in {"regular_interval", "closing_auction"}
        )
        point.update(
            {
                "close": close_price,
                "volume_shares": volume_shares,
                "volume_lots": (
                    volume_shares / 1000 if volume_shares is not None else None
                ),
                "canonical_volume_unit": "shares",
                "provider_volume_unit": provider_volume_unit,
                "volume_status": (
                    "available" if volume_shares is not None else "not_provided"
                ),
                "approx_trade_value": approx_trade_value,
                "trade_value_status": (
                    "official"
                    if exact_trade_value is not None
                    else "estimated"
                    if approx_trade_value is not None
                    else "not_provided"
                ),
                "bar_close_time": (
                    bar_close_time.isoformat() if bar_close_time is not None else None
                ),
                "elapsed_seconds": elapsed_seconds,
                "is_partial": is_partial,
                "finalized": finalized,
                "indicator_eligible": indicator_eligible,
                **bar_semantics,
            }
        )
        enriched.append(point)

    latest_trade_date, session_points = _latest_trade_date_points(enriched)
    session_metrics = _intraday_bar_metrics(session_points)
    window_metrics = _intraday_bar_metrics(enriched)
    volume_points = int(session_metrics["volume_points"] or 0)
    total_volume_shares = int(session_metrics["total_volume_shares"] or 0)
    exact_value_points = int(session_metrics["exact_value_points"] or 0)
    official_trade_value = int(session_metrics["official_trade_value"] or 0)
    estimated_trade_value = float(session_metrics["estimated_trade_value"] or 0.0)
    exact_complete = bool(session_metrics["exact_complete"])
    approximate_vwap = _as_float(session_metrics["approx_vwap"])
    official_vwap = _as_float(session_metrics["official_vwap"])
    bar_latest_time = (
        _point_datetime(session_points[-1]) if session_points else None
    )
    bar_volume_sum_shares = total_volume_shares if volume_points else None
    window_volume_points = int(window_metrics["volume_points"] or 0)
    window_volume_sum_shares = (
        int(window_metrics["total_volume_shares"] or 0)
        if window_volume_points
        else None
    )
    trade_dates = {
        _normalize_bar_time(point_time).date()
        for point in enriched
        if (point_time := _point_datetime(point)) is not None
    }
    trade_value_status = (
        "complete"
        if exact_complete
        else "partial"
        if exact_value_points > 0
        else "estimated"
        if estimated_trade_value > 0
        else "not_provided"
    )
    metadata = {
        "canonical_volume_unit": "shares",
        "provider_volume_unit": provider_volume_unit,
        "volume_conversion": (
            "provider_lots_x_1000_to_shares"
            if provider_volume_unit == "lots"
            else "identity"
            if provider_volume_unit == "shares"
            else "unknown"
        ),
        "volume_semantics": "latest_trade_date_interval_bar_sum_fallback",
        "volume_scope": "latest_trade_date_interval_bar_sum",
        "bar_volume_sum_shares": bar_volume_sum_shares,
        "bar_volume_sum_lots": (
            bar_volume_sum_shares / 1000
            if bar_volume_sum_shares is not None
            else None
        ),
        "bar_volume_trade_date": (
            latest_trade_date.isoformat() if latest_trade_date is not None else None
        ),
        "bar_volume_latest_time": (
            _normalize_bar_time(bar_latest_time).isoformat()
            if bar_latest_time is not None
            else None
        ),
        "bar_volume_scope": "latest_trade_date_interval_bar_sum",
        "bar_volume_provider": source or None,
        "window_volume_sum_shares": window_volume_sum_shares,
        "window_volume_sum_lots": (
            window_volume_sum_shares / 1000
            if window_volume_sum_shares is not None
            else None
        ),
        "window_volume_scope": "query_window_interval_bar_sum",
        "window_trade_date_count": len(trade_dates),
        "session_cumulative_volume_shares": None,
        "session_cumulative_volume_lots": None,
        "session_cumulative_volume_trade_date": None,
        "session_cumulative_volume_source": None,
        "session_cumulative_volume_source_field": None,
        "session_cumulative_volume_event_time": None,
        "session_cumulative_volume_status": (
            "fallback_bar_sum"
            if bar_volume_sum_shares is not None
            else "unavailable"
        ),
        "cumulative_volume_shares": (
            bar_volume_sum_shares
        ),
        "cumulative_volume_lots": (
            bar_volume_sum_shares / 1000
            if bar_volume_sum_shares is not None
            else None
        ),
        "cumulative_volume_trade_date": (
            latest_trade_date.isoformat() if latest_trade_date is not None else None
        ),
        "cumulative_volume_source": (
            "intraday_bar_sum" if bar_volume_sum_shares is not None else None
        ),
        "cumulative_volume_source_field": (
            "interval_bar.volume" if bar_volume_sum_shares is not None else None
        ),
        "cumulative_volume_event_time": (
            _normalize_bar_time(bar_latest_time).isoformat()
            if bar_latest_time is not None
            else None
        ),
        "cumulative_volume_status": (
            "fallback_bar_sum"
            if bar_volume_sum_shares is not None
            else "unavailable"
        ),
        "unallocated_volume_shares": None,
        "unallocated_volume_lots": None,
        "volume_reconciliation": {
            "status": "unavailable",
            "trade_date": (
                latest_trade_date.isoformat()
                if latest_trade_date is not None
                else None
            ),
            "exchange_cumulative_shares": None,
            "bar_volume_sum_shares": bar_volume_sum_shares,
            "difference_shares": None,
            "difference_lots": None,
            "difference_pct": None,
            "exchange_event_time": None,
            "bar_latest_time": (
                _normalize_bar_time(bar_latest_time).isoformat()
                if bar_latest_time is not None
                else None
            ),
            "time_skew_seconds": None,
            "reason": "exchange_cumulative_unavailable",
        },
        "cumulative_trade_value": (
            official_trade_value if exact_complete else None
        ),
        "available_cumulative_trade_value": (
            official_trade_value if exact_value_points else None
        ),
        "estimated_cumulative_trade_value": (
            int(round(estimated_trade_value))
            if estimated_trade_value > 0
            else None
        ),
        "trade_value_unit": "TWD",
        "trade_value_status": trade_value_status,
        "official_vwap": official_vwap,
        "approx_vwap": approximate_vwap,
        "vwap_method": (
            "official_trade_value_divided_by_volume_shares"
            if official_vwap is not None
            else "close_price_volume_weighted_approximation"
            if approximate_vwap is not None
            else "unavailable"
        ),
        "vwap_confidence": (
            "high"
            if official_vwap is not None
            else "medium"
            if approximate_vwap is not None
            else "unavailable"
        ),
        "vwap_volume_scope": "latest_trade_date_interval_bars",
        "partial_bar_count": sum(
            1 for point in enriched if point.get("is_partial") is True
        ),
        "indicator_eligible_point_count": sum(
            1 for point in enriched if point.get("indicator_eligible") is True
        ),
        "bar_classification_policy": "taiwan_cash_session_v1",
        "indicator_policy": (
            "finalized_regular_interval_or_closing_auction_only"
        ),
        "partial_bar_policy": "exclude_partial_bars_from_indicators",
        "aggregation_method": (
            "provider_interval_bars_with_explicit_market_event_markers"
        ),
    }
    return enriched, metadata


def _aggregate_intraday_points(points: list[dict], interval_minutes: int) -> list[dict]:
    buckets: dict[tuple[str, int], list[dict]] = {}

    for point in sorted(points, key=lambda item: str(item.get("time") or "")):
        point_time = _point_datetime(point)
        close_price = _as_float(point.get("price"))

        if point_time is None or close_price is None:
            continue

        point_time = _normalize_bar_time(point_time)
        if not _is_taiwan_regular_session_time(point_time):
            continue

        minutes = point_time.hour * 60 + point_time.minute
        bucket_minute = 9 * 60 + ((minutes - 9 * 60) // interval_minutes) * interval_minutes
        bucket_key = (point_time.strftime("%Y-%m-%d"), bucket_minute)
        buckets.setdefault(bucket_key, []).append(point)

    aggregated: list[dict] = []
    for (date_key, bucket_minute), bucket_points in sorted(buckets.items()):
        first = bucket_points[0]
        last = bucket_points[-1]
        first_time = _point_datetime(first)
        if first_time is None:
            continue
        bucket_time = datetime.combine(
            first_time.date(),
            time(bucket_minute // 60, bucket_minute % 60, 0),
            tzinfo=TAIPEI_TZ,
        )
        highs = [_as_float(point.get("high")) or _as_float(point.get("price")) for point in bucket_points]
        lows = [_as_float(point.get("low")) or _as_float(point.get("price")) for point in bucket_points]
        volumes = [_as_int(point.get("volume")) for point in bucket_points]
        volume_total = sum(volume for volume in volumes if volume is not None and volume > 0)
        trade_values = [_as_int(point.get("trade_value")) for point in bucket_points]
        trade_value_total = (
            sum(value for value in trade_values if value is not None)
            if any(value is not None for value in trade_values)
            else None
        )

        aggregated.append(
            {
                "time": bucket_time.isoformat(),
                "price": _as_float(last.get("price")),
                "volume": volume_total if volume_total > 0 else None,
                "trade_value": trade_value_total,
                "open": _as_float(first.get("open")) or _as_float(first.get("price")),
                "high": max((value for value in highs if value is not None), default=None),
                "low": min((value for value in lows if value is not None), default=None),
            }
        )

    return aggregated


def _upsert_market_intraday_bars(
    db: Session,
    *,
    stock_id: str,
    market: str | None,
    symbol: str | None,
    interval: str,
    source: str,
    source_url: str | None,
    points: list[dict],
) -> int:
    updated_at = utc_now()
    changed_count = 0

    for point in points:
        point_time = _point_datetime(point)
        close_price = _as_float(point.get("price"))

        if point_time is None or close_price is None:
            continue

        bar_time = _normalize_bar_time(point_time)
        if not _is_taiwan_regular_session_time(bar_time):
            continue

        values = {
            "provider": INTRADAY_HISTORY_PROVIDER,
            "stock_id": stock_id,
            "market": market,
            "symbol": symbol,
            "interval": interval,
            "bar_time": bar_time,
            "open_price": _as_float(point.get("open")) or close_price,
            "high_price": _as_float(point.get("high")) or close_price,
            "low_price": _as_float(point.get("low")) or close_price,
            "close_price": close_price,
            "trade_volume": _as_int(point.get("volume")),
            "trade_value": _as_int(point.get("trade_value")),
            "source": source,
            "source_url": source_url,
            "updated_at": updated_at,
        }
        existing = (
            db.query(MarketIntradayBar)
            .filter(MarketIntradayBar.provider == INTRADAY_HISTORY_PROVIDER)
            .filter(MarketIntradayBar.stock_id == stock_id)
            .filter(MarketIntradayBar.interval == interval)
            .filter(MarketIntradayBar.bar_time == bar_time)
            .first()
        )

        if existing is None:
            db.add(MarketIntradayBar(**values))
        else:
            changed = any(
                (
                    getattr(existing, key).replace(tzinfo=None)
                    if isinstance(getattr(existing, key), datetime)
                    else getattr(existing, key)
                )
                != (
                    value.astimezone(TAIPEI_TZ).replace(tzinfo=None)
                    if isinstance(value, datetime) and value.tzinfo is not None
                    else value.replace(tzinfo=None)
                    if isinstance(value, datetime)
                    else value
                )
                for key, value in values.items()
                if key != "updated_at"
            )
            if not changed:
                continue
            for key, value in values.items():
                setattr(existing, key, value)
        changed_count += 1

    if changed_count:
        db.commit()

    return changed_count


def _intraday_history_config(interval: str, range_value: str) -> dict:
    config = INTRADAY_HISTORY_INTERVAL_CONFIGS.get(interval)
    if config is None:
        raise ValueError("interval must be one of: 1m, 5m, 15m, 30m, 1h, 4h.")

    if range_value == "auto":
        return dict(config)

    days = INTRADAY_HISTORY_RANGE_DAYS.get(range_value)
    if days is None:
        raise ValueError("range must be one of: auto, 1d, 5d, 1mo, 3mo.")

    resolved = dict(config)
    resolved["range"] = range_value
    resolved["days"] = days
    return resolved


def _volume_lots_to_shares(value) -> int | None:
    lots = _as_int(value)
    if lots is None:
        return None

    return lots * 1000


def _upsert_intraday_point(
    points: list[dict],
    *,
    point_time: datetime,
    price: float | None,
    volume: int | None,
    volume_mode: str = "max",
    open_price: float | None,
    high_price: float | None,
    low_price: float | None,
) -> dict:
    date_key = point_time.strftime("%Y%m%d")
    time_key = point_time.strftime("%H:%M:%S")

    for point in points:
        key = _point_time_key(point)
        if key == (date_key, time_key):
            if price is not None:
                point["price"] = price
            if volume is not None:
                current_volume = _as_int(point.get("volume")) or 0
                if volume_mode == "add":
                    point["volume"] = current_volume + volume
                elif volume_mode == "set":
                    point["volume"] = volume
                else:
                    point["volume"] = max(current_volume, volume)
            point["open"] = _as_float(point.get("open")) or open_price or price
            point["high"] = max(
                [value for value in [_as_float(point.get("high")), high_price, price] if value is not None],
                default=None,
            )
            point["low"] = min(
                [value for value in [_as_float(point.get("low")), low_price, price] if value is not None],
                default=None,
            )
            return point

    point = {
        "time": point_time.isoformat(),
        "price": price,
        "volume": volume,
        "open": open_price or price,
        "high": high_price or price,
        "low": low_price or price,
    }
    points.append(point)
    points.sort(key=lambda item: item["time"])
    return point


def _fill_volume_gap(points: list[dict], total_volume: int) -> bool:
    current_total = sum(
        volume
        for volume in (_as_int(point.get("volume")) for point in points)
        if volume is not None and volume > 0
    )
    missing_volume = total_volume - current_total

    if missing_volume <= 0:
        return False

    candidates = [
        point
        for point in points
        if (point_time := _point_datetime(point)) is not None
        and (point_time.hour, point_time.minute) != (13, 30)
    ]
    target = candidates[-1] if candidates else (points[-1] if points else None)

    if target is None:
        return False

    target["volume"] = (_as_int(target.get("volume")) or 0) + missing_volume
    return True


def _dedupe_disposition_points(points: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    previous_state: tuple[float | None, int | None, str | None] | None = None
    for point in sorted(points, key=lambda item: str(item.get("time") or "")):
        state = (
            _as_float(point.get("price") if point.get("price") is not None else point.get("close")),
            _as_int(point.get("cumulative_volume") if point.get("cumulative_volume") is not None else point.get("volume")),
            str(
                point.get("official_trade_timestamp")
                or point.get("official_trade_time")
                or ""
            )
            or None,
        )
        if previous_state is not None and state == previous_state:
            continue
        deduped.append(point)
        previous_state = state
    return deduped


def _apply_disposition_intraday_contract(
    result: dict,
    disposition: dict,
) -> dict:
    if not disposition.get("is_active"):
        return {
            **result,
            "trading_mode": "continuous",
            "analysis_basis": "time_bars",
        }
    points = _dedupe_disposition_points(
        [point for point in result.get("points") or [] if isinstance(point, dict)]
    )
    return {
        **result,
        "points": points,
        "point_count": len(points),
        "trading_mode": "disposition_batch_auction",
        "analysis_basis": "effective_matches",
        "effective_match_count": len(points),
        "batch_interval_minutes": disposition.get("matching_interval_minutes"),
        "disposition_start_date": disposition.get("start_date"),
        "disposition_end_date": disposition.get("end_date"),
    }


def _apply_mis_volume_adjustment(result: dict, message: dict | None) -> dict:
    original_source = str(result.get("source") or "unknown")
    price_provider = (
        "nstock" if original_source.startswith("nstock") else "yahoo_finance_chart"
        if original_source.startswith("yahoo")
        else original_source
    )
    result["price_provider"] = price_provider
    result["volume_provider"] = price_provider
    result["provider"] = price_provider
    result["source_components"] = [
        {"domain": "price", "provider": price_provider, "source": original_source}
    ]
    points = [point for point in result.get("points") or [] if isinstance(point, dict)]
    result["points"] = points
    latest_history_point = max(
        points,
        key=lambda point: (
            _normalize_bar_time(point_time).timestamp()
            if (point_time := _point_datetime(point)) is not None
            else float("-inf")
        ),
        default=None,
    )
    latest_history_time = (
        _normalize_bar_time(point_time)
        if latest_history_point is not None
        and (point_time := _point_datetime(latest_history_point)) is not None
        else None
    )
    latest_history_price = (
        _as_float(
            latest_history_point.get("price")
            if latest_history_point.get("price") is not None
            else latest_history_point.get("close")
        )
        if latest_history_point is not None
        else None
    )
    expected_trade_date = latest_history_time.date() if latest_history_time else None
    result.update(
        {
            "history_price_source": price_provider,
            "latest_history_time": (
                latest_history_time.isoformat() if latest_history_time else None
            ),
            "latest_history_price": latest_history_price,
            "latest_actual_trade_time": None,
            "latest_actual_trade_price": None,
            "current_price_source": None,
            "lag_seconds": None,
            "current_trade_available": False,
            "current_trade_unavailable_reason": "MIS_SNAPSHOT_UNAVAILABLE",
            "current_price_applied_to_history": False,
            "capabilities": {
                "supports_volume": True,
                "supports_vwap": True,
                "supports_price_limit": True,
                "supports_quote_depth": True,
            },
            "current_observation": (
                {
                    "value": latest_history_price,
                    "observed_at": latest_history_time.isoformat(),
                    "confirmed_at": None,
                    "price_semantics": "intraday_bar_close",
                    "provider": price_provider,
                    "freshness_status": "history_latest",
                    "decision_usable": False,
                }
                if latest_history_price is not None and latest_history_time is not None
                else None
            ),
        }
    )
    if not message or not result.get("points"):
        return result

    snapshot_time = _parse_snapshot_datetime(message)
    trade_date = message.get("d")

    if snapshot_time is None or not trade_date:
        return result

    if not any((key := _point_time_key(point)) is not None and key[0] == trade_date for point in points):
        result["current_trade_unavailable_reason"] = "OBSERVATION_TRADE_DATE_MISMATCH"
        return result

    price = _as_float(message.get("z"))
    close_volume = _volume_lots_to_shares(message.get("tv") or message.get("s"))
    total_volume = _volume_lots_to_shares(message.get("v"))
    actual_trade = resolve_twse_mis_actual_trade(
        expected_trade_date=expected_trade_date,
        observation_trade_date=trade_date,
        provider_event_time=snapshot_time,
        trial_status=message.get("ts"),
        last_trade_price=price,
        last_trade_volume_lots=_as_int(message.get("tv") or message.get("s")),
        cumulative_volume_lots=_as_int(message.get("v")),
    )
    actual_trade_time = actual_trade.get("actual_trade_price_as_of")
    actual_trade_price = _as_float(actual_trade.get("actual_trade_price"))
    current_trade_available = bool(
        actual_trade.get("actual_trade_price_available")
        and actual_trade_time is not None
        and actual_trade_price is not None
    )
    lag_seconds = (
        (actual_trade_time - latest_history_time).total_seconds()
        if current_trade_available
        and latest_history_time is not None
        and actual_trade_time is not None
        else None
    )
    result.update(
        {
            "latest_actual_trade_time": (
                actual_trade_time.isoformat() if actual_trade_time is not None else None
            ),
            "latest_actual_trade_price": actual_trade_price,
            "current_price_source": actual_trade.get("actual_trade_price_source"),
            "lag_seconds": lag_seconds,
            "current_trade_available": current_trade_available,
            "current_trade_unavailable_reason": (
                None if current_trade_available else actual_trade.get("reason_code")
            ),
            "current_observation": (
                {
                    "value": actual_trade_price,
                    "observed_at": actual_trade_time.isoformat(),
                    "confirmed_at": actual_trade_time.isoformat(),
                    "price_semantics": "actual_trade",
                    "provider": "twse_mis",
                    "freshness_status": "current",
                    "decision_usable": True,
                }
                if current_trade_available
                and actual_trade_time is not None
                and actual_trade_price is not None
                else result.get("current_observation")
            ),
        }
    )
    adjusted = False
    price_adjusted = False
    volume_adjusted = False

    if (
        current_trade_available
        and actual_trade_time is not None
        and (latest_history_time is None or actual_trade_time >= latest_history_time)
    ):
        _upsert_intraday_point(
            points,
            point_time=actual_trade_time,
            price=actual_trade_price,
            volume=close_volume if close_volume is not None and close_volume > 0 else None,
            open_price=actual_trade_price,
            high_price=actual_trade_price,
            low_price=actual_trade_price,
        )
        adjusted = True
        price_adjusted = True
        volume_adjusted = bool(close_volume is not None and close_volume > 0)
        result["current_price_applied_to_history"] = True
    elif close_volume is not None and close_volume > 0:
        matching_point = next(
            (
                point
                for point in points
                if _point_time_key(point)
                == (snapshot_time.strftime("%Y%m%d"), snapshot_time.strftime("%H:%M:%S"))
            ),
            None,
        )
        if matching_point is not None:
            _upsert_intraday_point(
                points,
                point_time=snapshot_time,
                price=None,
                volume=close_volume,
                open_price=None,
                high_price=None,
                low_price=None,
            )
            adjusted = True
            volume_adjusted = True

    if (
        total_volume is not None
        and total_volume > 0
        and snapshot_time.hour == 13
        and snapshot_time.minute >= 30
    ):
        current_total = sum(
            volume
            for volume in (_as_int(point.get("volume")) for point in points)
            if volume is not None and volume > 0
        )
        missing_volume = total_volume - current_total

        if missing_volume > 0:
            open_time = datetime.combine(
                snapshot_time.date(),
                time(9, 0, 0),
                tzinfo=snapshot_time.tzinfo or TAIPEI_TZ,
            )
            _upsert_intraday_point(
                points,
                point_time=open_time,
                price=_as_float(message.get("o")),
                volume=missing_volume,
                volume_mode="add",
                open_price=_as_float(message.get("o")),
                high_price=_as_float(message.get("o")),
                low_price=_as_float(message.get("o")),
            )
            adjusted = True
            volume_adjusted = True

    result["point_count"] = len(points)
    if volume_adjusted:
        if result.get("source") == "nstock_minute_stock_data":
            result["source"] = "nstock_minute_stock_data_twse_mis_volume"
        else:
            result["source"] = "yahoo_finance_chart_twse_mis_volume"
        result["provider"] = "composite"
        result["volume_provider"] = "twse_mis"
        result["source_components"] = [
            {"domain": "price", "provider": price_provider, "source": original_source},
            {"domain": "volume", "provider": "twse_mis", "source": "twse_mis_snapshot"},
        ]
    elif adjusted:
        result["provider"] = "composite"
    if price_adjusted:
        result["source_components"].append(
            {
                "domain": "current_price",
                "provider": "twse_mis",
                "source": "twse_mis_snapshot_z",
            }
        )
    return result


def _fetch_mis_snapshot(stock_id: str, market: str | None) -> dict:
    exchange = _mis_exchange(market)
    message = _fetch_mis_message(stock_id=stock_id, market=market)

    if not message:
        return {
            "stock_id": stock_id,
            "symbol": f"{exchange}_{stock_id}.tw",
            "source": "twse_mis_snapshot",
            "previous_close": None,
            "point_count": 0,
            "points": [],
        }

    trade_date = message.get("d")
    previous_close = _as_float(message.get("y"))
    latest_time = message.get("t") or message.get("%") or "13:30:00"
    candidates = [
        ("09:00:00", _as_float(message.get("o"))),
        ("10:30:00", _as_float(message.get("h"))),
        ("12:00:00", _as_float(message.get("l"))),
        (latest_time, _as_float(message.get("z"))),
    ]
    points = [
        {
            "time": _build_snapshot_time(trade_date, point_time),
            "price": price,
            "volume": _as_int(message.get("v")),
            "open": _as_float(message.get("o")),
            "high": _as_float(message.get("h")),
            "low": _as_float(message.get("l")),
        }
        for point_time, price in candidates
        if price is not None
    ]

    return {
        "stock_id": stock_id,
        "symbol": f"{exchange}_{stock_id}.tw",
        "source": "twse_mis_snapshot",
        "previous_close": previous_close,
        "point_count": len(points),
        "points": points,
    }


def _load_intraday_trend_uncached(
    db: Session,
    *,
    stock_id: str,
    market: str | None,
    cache_key: str,
) -> dict:
    disposition = get_taiwan_disposition_status(
        stock_id,
        market=market,
    )
    try:
        nstock_result = _fetch_nstock_intraday(stock_id=stock_id)

        if nstock_result["points"]:
            try:
                message = _fetch_mis_message(stock_id=stock_id, market=market)
            except Exception as exc:
                observe_provider_fallback(
                    exc,
                    operation="intraday.nstock_volume_adjustment",
                )
                message = None
            result = _apply_disposition_intraday_contract(
                _apply_mis_volume_adjustment(nstock_result, message),
                disposition,
            )
            _upsert_market_intraday_bars(
                db,
                stock_id=stock_id,
                market=market,
                symbol=result.get("symbol"),
                interval="1m",
                source=str(result.get("source") or "nstock_minute_stock_data"),
                source_url=result.get("source_url"),
                points=result.get("points") or [],
            )
            return _cache_set(cache_key, result)
    except Exception as exc:
        observe_provider_fallback(exc, operation="intraday.nstock_primary")

    try:
        yahoo_result = _fetch_yahoo_intraday(stock_id=stock_id, market=market)

        if yahoo_result["points"]:
            try:
                message = _fetch_mis_message(stock_id=stock_id, market=market)
            except Exception as exc:
                observe_provider_fallback(
                    exc,
                    operation="intraday.yahoo_volume_adjustment",
                )
                message = None
            result = _apply_disposition_intraday_contract(
                _apply_mis_volume_adjustment(yahoo_result, message),
                disposition,
            )
            _upsert_market_intraday_bars(
                db,
                stock_id=stock_id,
                market=market,
                symbol=result.get("symbol"),
                interval="1m",
                source=str(result.get("source") or "yahoo_finance_chart"),
                source_url=result.get("source_url"),
                points=result.get("points") or [],
            )
            return _cache_set(cache_key, result)
    except Exception as exc:
        observe_provider_fallback(exc, operation="intraday.yahoo_secondary")

    try:
        return _cache_set(
            cache_key,
            _apply_disposition_intraday_contract(
                _fetch_mis_snapshot(stock_id=stock_id, market=market),
                disposition,
            ),
        )
    except Exception as exc:
        observe_provider_fallback(exc, operation="intraday.mis_snapshot_final")
        return _cache_set(cache_key, {
            "stock_id": stock_id,
            "symbol": _yahoo_symbol(stock_id=stock_id, market=market),
            "source": "unavailable",
            "previous_close": None,
            "point_count": 0,
            "points": [],
        })


def get_intraday_trend(db: Session, stock_id: str) -> dict:
    stock = _get_stock(db=db, stock_id=stock_id)
    market = stock.market.upper() if stock else None
    cache_key = f"{market or 'UNKNOWN'}:{stock_id}"
    cached = _cache_get(cache_key)

    if cached is not None:
        return cached

    # Ranking and radar requests can ask for the same stock concurrently. Only
    # one request should perform provider I/O; waiters reuse its fresh result.
    with _get_intraday_fetch_lock(cache_key):
        cached = _cache_get(cache_key)

        if cached is not None:
            return cached

        return _load_intraday_trend_uncached(
            db,
            stock_id=stock_id,
            market=market,
            cache_key=cache_key,
        )


def get_market_intraday_history(
    db: Session,
    *,
    stock_id: str,
    interval: str = "1m",
    range_value: str = "auto",
    refresh: bool = True,
) -> dict:
    stock = _get_stock(db=db, stock_id=stock_id)
    market = stock.market.upper() if stock else None
    disposition = get_taiwan_disposition_status(stock_id, market=market)
    symbol = _yahoo_symbol(stock_id=stock_id, market=market)
    config = _intraday_history_config(interval=interval, range_value=range_value)
    fetch_interval = str(config["fetch_interval"])
    fetch_range = str(config["range"])
    days = int(config["days"])
    from_time = datetime.now(TAIPEI_TZ) - timedelta(days=days)
    cached_rows = _query_intraday_rows(
        db,
        stock_id=stock_id,
        interval=interval,
        from_time=from_time,
    )
    refreshed_count = 0
    refresh_failed = False
    source = "market_intraday_bar_cache"
    source_url = None

    if refresh:
        try:
            fetched = _fetch_yahoo_intraday(
                stock_id=stock_id,
                market=market,
                range_value=fetch_range,
                interval=fetch_interval,
            )
            fetched_points = fetched.get("points") or []
            if interval == "4h":
                fetched_points = _aggregate_intraday_points(fetched_points, 240)
            if disposition.get("is_active"):
                fetched_points = _dedupe_disposition_points(fetched_points)
            refreshed_count = _upsert_market_intraday_bars(
                db,
                stock_id=stock_id,
                market=market,
                symbol=fetched.get("symbol") or symbol,
                interval=interval,
                source=str(fetched.get("source") or "yahoo_finance_chart"),
                source_url=fetched.get("source_url"),
                points=fetched_points,
            )
            source = str(fetched.get("source") or "yahoo_finance_chart")
            source_url = fetched.get("source_url")
        except Exception as exc:
            observe_provider_fallback(exc, operation="intraday.history_remote_refresh")
            source = "market_intraday_bar_cache"
            refresh_failed = True

    if interval == "5m":
        one_minute_rows = _query_intraday_rows(
            db,
            stock_id=stock_id,
            interval="1m",
            from_time=from_time,
        )
        one_minute_points = [
            {
                **_intraday_row_to_point(row),
                "price": row.close_price,
            }
            for row in one_minute_rows
        ]
        local_five_minute_points = _aggregate_intraday_points(
            one_minute_points,
            5,
        )
        if local_five_minute_points:
            refreshed_count += _upsert_market_intraday_bars(
                db,
                stock_id=stock_id,
                market=market,
                symbol=symbol,
                interval="5m",
                source="local_current_1m_aggregate",
                source_url=one_minute_rows[-1].source_url if one_minute_rows else None,
                points=local_five_minute_points,
            )
            source = "local_current_1m_aggregate"
            source_url = one_minute_rows[-1].source_url if one_minute_rows else source_url

    rows = _query_intraday_rows(
        db,
        stock_id=stock_id,
        interval=interval,
        from_time=from_time,
    )
    points = [_intraday_row_to_point(row) for row in rows]
    if disposition.get("is_active"):
        points = _dedupe_disposition_points(points)

    if rows and source_url is None:
        source_url = rows[-1].source_url
    if rows and source == "market_intraday_bar_cache":
        source = rows[-1].source
    points, contract_metadata = _enrich_intraday_contract(
        points,
        interval=interval,
        source=source,
    )

    return {
        "stock_id": stock_id,
        "symbol": symbol,
        "interval": interval,
        "requested_interval": interval,
        "source_interval": (
            "1m" if source == "local_current_1m_aggregate" else interval
        ),
        "effective_interval": interval,
        "interval_status": "ready",
        "range": fetch_range if range_value == "auto" else range_value,
        "provider": (
            "local_derived"
            if source == "local_current_1m_aggregate"
            else "composite"
            if "twse_mis_volume" in source
            else "nstock"
            if source.startswith("nstock")
            else INTRADAY_HISTORY_PROVIDER
        ),
        "source": source,
        "source_url": source_url,
        "from_time": _normalize_bar_time(rows[0].bar_time) if rows else None,
        "to_time": _normalize_bar_time(rows[-1].bar_time) if rows else None,
        "point_count": len(points),
        "cached_count": len(cached_rows),
        "refreshed_count": refreshed_count,
        "cache_status": (
            "refresh_fallback_hit"
            if refresh_failed and rows
            else "refresh_fallback_miss"
            if refresh_failed
            else "persisted_hit"
            if rows and not refresh
            else "persisted_miss"
            if not rows and not refresh
            else "refreshed"
        ),
        "cache_hit": bool(rows and (not refresh or refresh_failed)),
        "cache_trade_date": (
            _normalize_bar_time(rows[-1].bar_time).date().isoformat()
            if rows
            else None
        ),
        "cache_latest_time": (
            _normalize_bar_time(rows[-1].bar_time)
            if rows
            else None
        ),
        "fallback_used": refresh_failed and bool(rows),
        "trading_mode": "disposition_batch_auction"
        if disposition.get("is_active")
        else "continuous",
        "analysis_basis": "effective_matches"
        if disposition.get("is_active")
        else "time_bars",
        "effective_match_count": len(points)
        if disposition.get("is_active")
        else None,
        "batch_interval_minutes": disposition.get("matching_interval_minutes")
        if disposition.get("is_active")
        else None,
        "disposition_start_date": disposition.get("start_date")
        if disposition.get("is_active")
        else None,
        "disposition_end_date": disposition.get("end_date")
        if disposition.get("is_active")
        else None,
        **contract_metadata,
        "points": points,
    }
