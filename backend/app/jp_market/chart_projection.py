from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone

from app.db.models import JPDailyPrice


def sum_nullable(values: list[int | None]) -> int | None:
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None
    return sum(valid_values)


def ohlc_point(row: JPDailyPrice, time_value: date | None = None) -> dict:
    return {
        "time": time_value or row.trade_date,
        "open": row.open_price,
        "high": row.high_price,
        "low": row.low_price,
        "close": row.close_price,
        "volume": row.trade_volume,
    }


def datetime_sort_value(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).timestamp()


def daily_row_completeness_score(row: JPDailyPrice) -> int:
    values = (
        row.open_price,
        row.high_price,
        row.low_price,
        row.close_price,
        row.trade_volume,
    )
    return sum(1 for value in values if value is not None)


def daily_canonical_sort_key(row: JPDailyPrice) -> tuple[int, float, int]:
    return (
        daily_row_completeness_score(row),
        datetime_sort_value(row.fetched_at),
        row.id or 0,
    )


def dedupe_daily_rows_by_trade_date(rows: list[JPDailyPrice]) -> list[JPDailyPrice]:
    canonical_by_date: OrderedDict[date, JPDailyPrice] = OrderedDict()
    for row in rows:
        existing = canonical_by_date.get(row.trade_date)
        if existing is None or daily_canonical_sort_key(row) > daily_canonical_sort_key(existing):
            canonical_by_date[row.trade_date] = row
    return [canonical_by_date[trade_date] for trade_date in sorted(canonical_by_date)]


def aggregate_daily_rows(rows: list[JPDailyPrice], timeframe: str) -> list[dict]:
    rows = dedupe_daily_rows_by_trade_date(rows)
    if timeframe == "daily":
        return [ohlc_point(row) for row in rows]
    groups: OrderedDict[date, list[JPDailyPrice]] = OrderedDict()
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
        highs = [row.high_price for row in grouped_rows if row.high_price is not None]
        lows = [row.low_price for row in grouped_rows if row.low_price is not None]
        results.append(
            {
                "time": key,
                "open": first.open_price,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "close": last.close_price,
                "volume": sum_nullable([row.trade_volume for row in grouped_rows]),
            }
        )
    return results
