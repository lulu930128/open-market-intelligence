from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta

from app.db.models import KRDailyPrice, KRIndexDailyPrice


def close_value(row: KRDailyPrice | None) -> float | None:
    if row is None:
        return None
    return row.adjusted_close if row.adjusted_close is not None else row.close_price


def chart_row(row: KRDailyPrice, time_value: date | None = None) -> dict:
    return {
        "time": time_value or row.trade_date,
        "open": row.open_price,
        "high": row.high_price,
        "low": row.low_price,
        "close": close_value(row),
        "volume": row.trade_volume,
    }


def aggregate_daily_rows(rows: list[KRDailyPrice], timeframe: str) -> list[dict]:
    if timeframe == "daily":
        return [chart_row(row) for row in rows]
    buckets: OrderedDict[date, list[KRDailyPrice]] = OrderedDict()
    for row in rows:
        if timeframe == "weekly":
            bucket_key = row.trade_date - timedelta(days=row.trade_date.weekday())
        elif timeframe == "monthly":
            bucket_key = row.trade_date.replace(day=1)
        else:
            raise ValueError("timeframe must be one of: daily, weekly, monthly.")
        buckets.setdefault(bucket_key, []).append(row)
    aggregated: list[dict] = []
    for bucket_key, bucket_rows in buckets.items():
        sorted_rows = sorted(bucket_rows, key=lambda item: item.trade_date)
        highs = [row.high_price for row in sorted_rows if row.high_price is not None]
        lows = [row.low_price for row in sorted_rows if row.low_price is not None]
        closes = [close_value(row) for row in sorted_rows if close_value(row) is not None]
        volumes = [row.trade_volume or 0 for row in sorted_rows]
        aggregated.append(
            {
                "time": bucket_key,
                "open": sorted_rows[0].open_price,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "close": closes[-1] if closes else None,
                "volume": sum(volumes) if volumes else None,
            }
        )
    return aggregated

def aggregate_index_daily_rows(rows: list[KRIndexDailyPrice], timeframe: str) -> list[dict]:
    if timeframe == "daily":
        return [
            {
                "time": row.trade_date,
                "open": row.open_value,
                "high": row.high_value,
                "low": row.low_value,
                "close": row.close_value,
                "volume": row.trade_volume,
            }
            for row in rows
        ]
    buckets: OrderedDict[date, list[KRIndexDailyPrice]] = OrderedDict()
    for row in rows:
        if timeframe == "weekly":
            bucket_key = row.trade_date - timedelta(days=row.trade_date.weekday())
        elif timeframe == "monthly":
            bucket_key = row.trade_date.replace(day=1)
        else:
            raise ValueError("timeframe must be one of: daily, weekly, monthly.")
        buckets.setdefault(bucket_key, []).append(row)
    aggregated: list[dict] = []
    for bucket_key, bucket_rows in buckets.items():
        sorted_rows = sorted(bucket_rows, key=lambda item: item.trade_date)
        highs = [row.high_value for row in sorted_rows if row.high_value is not None]
        lows = [row.low_value for row in sorted_rows if row.low_value is not None]
        closes = [row.close_value for row in sorted_rows if row.close_value is not None]
        volumes = [row.trade_volume or 0 for row in sorted_rows]
        aggregated.append(
            {
                "time": bucket_key,
                "open": sorted_rows[0].open_value,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "close": closes[-1] if closes else None,
                "volume": sum(volumes) if volumes else None,
            }
        )
    return aggregated
