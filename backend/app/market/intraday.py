from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
import time as monotonic_time

from sqlalchemy.orm import Session

from app.db.models import MarketIntradayBar, StockMaster, utc_now
from app.market.providers import http_get


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NSTOCK_MINUTE_URL = "https://shop.nstock.tw/api/v2/minute-stock-data/data"
TWSE_MIS_STOCK_INFO_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TAIPEI_TZ = timezone(timedelta(hours=8))
INTRADAY_CACHE_TTL_SECONDS = 4.75
_INTRADAY_CACHE: dict[str, tuple[float, dict]] = {}

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
    cached = _INTRADAY_CACHE.get(cache_key)
    if cached is None:
        return None

    cached_at, payload = cached
    if monotonic_time.monotonic() - cached_at > INTRADAY_CACHE_TTL_SECONDS:
        _INTRADAY_CACHE.pop(cache_key, None)
        return None

    return deepcopy(payload)


def _cache_set(cache_key: str, payload: dict) -> dict:
    _INTRADAY_CACHE[cache_key] = (monotonic_time.monotonic(), deepcopy(payload))
    return payload


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
        "time": row.bar_time,
        "open": row.open_price,
        "high": row.high_price,
        "low": row.low_price,
        "close": row.close_price,
        "volume": row.trade_volume,
        "trade_value": row.trade_value,
        "transaction_count": None,
    }


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

        aggregated.append(
            {
                "time": bucket_time.isoformat(),
                "price": _as_float(last.get("price")),
                "volume": volume_total if volume_total > 0 else None,
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
            "trade_value": None,
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


def _apply_mis_volume_adjustment(result: dict, message: dict | None) -> dict:
    if not message or not result.get("points"):
        return result

    snapshot_time = _parse_snapshot_datetime(message)
    trade_date = message.get("d")

    if snapshot_time is None or not trade_date:
        return result

    points = result["points"]
    if not any((key := _point_time_key(point)) is not None and key[0] == trade_date for point in points):
        return result

    price = _as_float(message.get("z"))
    close_volume = _volume_lots_to_shares(message.get("tv") or message.get("s"))
    total_volume = _volume_lots_to_shares(message.get("v"))
    adjusted = False

    if close_volume is not None and close_volume > 0:
        _upsert_intraday_point(
            points,
            point_time=snapshot_time,
            price=price,
            volume=close_volume,
            open_price=price,
            high_price=price,
            low_price=price,
        )
        adjusted = True

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

    result["point_count"] = len(points)
    if adjusted:
        if result.get("source") == "nstock_minute_stock_data":
            result["source"] = "nstock_minute_stock_data_twse_mis_volume"
        else:
            result["source"] = "yahoo_finance_chart_twse_mis_volume"
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


def get_intraday_trend(db: Session, stock_id: str) -> dict:
    stock = _get_stock(db=db, stock_id=stock_id)
    market = stock.market.upper() if stock else None
    cache_key = f"{market or 'UNKNOWN'}:{stock_id}"
    cached = _cache_get(cache_key)

    if cached is not None:
        return cached

    try:
        nstock_result = _fetch_nstock_intraday(stock_id=stock_id)

        if nstock_result["points"]:
            try:
                message = _fetch_mis_message(stock_id=stock_id, market=market)
            except Exception:
                message = None
            result = _apply_mis_volume_adjustment(nstock_result, message)
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
    except Exception:
        pass

    try:
        yahoo_result = _fetch_yahoo_intraday(stock_id=stock_id, market=market)

        if yahoo_result["points"]:
            try:
                message = _fetch_mis_message(stock_id=stock_id, market=market)
            except Exception:
                message = None
            result = _apply_mis_volume_adjustment(yahoo_result, message)
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
    except Exception:
        pass

    try:
        return _cache_set(cache_key, _fetch_mis_snapshot(stock_id=stock_id, market=market))
    except Exception:
        return _cache_set(cache_key, {
            "stock_id": stock_id,
            "symbol": _yahoo_symbol(stock_id=stock_id, market=market),
            "source": "unavailable",
            "previous_close": None,
            "point_count": 0,
            "points": [],
        })


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
        except Exception:
            source = "market_intraday_bar_cache"

    rows = _query_intraday_rows(
        db,
        stock_id=stock_id,
        interval=interval,
        from_time=from_time,
    )
    points = [_intraday_row_to_point(row) for row in rows]

    if rows and source_url is None:
        source_url = rows[-1].source_url
    if rows and source == "market_intraday_bar_cache":
        source = rows[-1].source

    return {
        "stock_id": stock_id,
        "symbol": symbol,
        "interval": interval,
        "range": fetch_range if range_value == "auto" else range_value,
        "provider": INTRADAY_HISTORY_PROVIDER,
        "source": source,
        "source_url": source_url,
        "from_time": rows[0].bar_time if rows else None,
        "to_time": rows[-1].bar_time if rows else None,
        "point_count": len(points),
        "cached_count": len(cached_rows),
        "refreshed_count": refreshed_count,
        "points": points,
    }
