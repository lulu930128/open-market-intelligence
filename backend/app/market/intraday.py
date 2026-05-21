from datetime import datetime, time, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from app.db.models import StockMaster


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
TWSE_MIS_STOCK_INFO_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TAIPEI_TZ = timezone(timedelta(hours=8))


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


def _fetch_yahoo_intraday(stock_id: str, market: str | None) -> dict:
    symbol = _yahoo_symbol(stock_id=stock_id, market=market)
    url = YAHOO_CHART_URL.format(symbol=symbol)
    response = requests.get(
        url,
        params={"range": "1d", "interval": "1m", "includePrePost": "false"},
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


def _fetch_mis_snapshot(stock_id: str, market: str | None) -> dict:
    exchange = _mis_exchange(market)
    response = requests.get(
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
    message = (payload.get("msgArray") or [None])[0]

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

    try:
        yahoo_result = _fetch_yahoo_intraday(stock_id=stock_id, market=market)

        if yahoo_result["points"]:
            return yahoo_result
    except Exception:
        pass

    try:
        return _fetch_mis_snapshot(stock_id=stock_id, market=market)
    except Exception:
        return {
            "stock_id": stock_id,
            "symbol": _yahoo_symbol(stock_id=stock_id, market=market),
            "source": "unavailable",
            "previous_close": None,
            "point_count": 0,
            "points": [],
        }
