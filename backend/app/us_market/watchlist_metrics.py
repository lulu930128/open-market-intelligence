from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.market_data.contracts import BarObservation
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_market_state import USInstrumentIdentityUnavailableError
from app.us_market.trading_calendar import US_MARKET_TIMEZONE


def _valid_number(value) -> bool:
    return isinstance(value, (int, float)) and value == value

def _close_value(row: BarObservation | None) -> float | None:
    if row is None:
        return None

    return float(row.close_price)


def _latest_distinct_us_daily_rows(
    db: Session,
    *,
    symbol: str,
    limit: int = 2,
    now: datetime | None = None,
) -> list[BarObservation]:
    with db.no_autoflush:
        try:
            read = USDailyOhlcvPlatform(db).read(symbol=symbol, bars=limit, now=now)
        except USInstrumentIdentityUnavailableError:
            return []
    if not read.temporal_postcondition_satisfied:
        return []
    return list(reversed(read.result.resolved.bars))


def _latest_us_daily_close_reference(
    db: Session,
    *,
    symbol: str,
    before_date: date | None = None,
    on_date: date | None = None,
) -> dict | None:
    for row in _latest_distinct_us_daily_rows(db=db, symbol=symbol, limit=10):
        trade_date = row.end_at.astimezone(US_MARKET_TIMEZONE).date()
        if on_date is not None and trade_date != on_date:
            continue

        if before_date is not None and trade_date >= before_date:
            continue

        close = _close_value(row)

        if _valid_number(close):
            return {
                "previous_close": float(close),
                "previous_close_source": row.lineage.source,
                "previous_close_trade_date": trade_date.isoformat(),
                "previous_close_provider": row.lineage.provider,
                "price_basis": row.price_basis,
            }

    return None


def _us_intraday_latest_trade_date(payload: dict) -> date | None:
    points = payload.get("points") or []

    for point in reversed(points):
        if isinstance(point, dict):
            trade_date = _us_row_trade_date(point)

            if trade_date is not None:
                return trade_date

    return None


def _us_regular_session_close_reference(payload: dict) -> dict | None:
    if payload.get("session_phase") != "after_hours":
        return None

    regular_close = payload.get("regular_session_close")

    if not _valid_number(regular_close):
        return None

    regular_close_date = _us_row_trade_date(
        {"time": payload.get("regular_session_close_time")}
    )

    return {
        "previous_close": float(regular_close),
        "previous_close_source": "yahoo_finance_chart_regular_session_close",
        "previous_close_trade_date": (
            regular_close_date.isoformat() if regular_close_date is not None else None
        ),
        "previous_close_provider": "yahoo_chart",
    }


def _us_reference_trade_date(reference: dict | None) -> date | None:
    if reference is None:
        return None

    return _parse_us_row_trade_date(reference.get("previous_close_trade_date"))


def _sum_us_intraday_volume(points: list[dict]) -> int | None:
    volumes = [
        int(point["volume"])
        for point in points
        if _valid_number(point.get("volume")) and int(point["volume"]) > 0
    ]

    if not volumes:
        return None

    return sum(volumes)


def _compact_us_intraday_points(points: list[dict], max_points: int = 72) -> list[dict]:
    valid_points = [
        {
            "time": point.get("time"),
            "session": point.get("session"),
            "price": float(point["price"]),
        }
        for point in points
        if point.get("time") and _valid_number(point.get("price"))
    ]

    if len(valid_points) <= max_points:
        return valid_points

    last_index = len(valid_points) - 1
    indexes = {
        round(index * last_index / (max_points - 1))
        for index in range(max_points)
    }

    return [valid_points[index] for index in sorted(indexes)]


def _parse_us_row_trade_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value or "").strip()

    if not text:
        return None

    normalized = text.replace("/", "-")

    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass

    try:
        return date.fromisoformat(normalized[:10])
    except ValueError:
        return None


def _us_row_trade_date(row: dict) -> date | None:
    return _parse_us_row_trade_date(row.get("time")) or _parse_us_row_trade_date(
        row.get("trade_date")
    )
