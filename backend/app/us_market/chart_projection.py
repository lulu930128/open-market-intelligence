from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timezone

from app.db.models import USDailyPrice
from app.market.ohlc_overlay import aggregate_ohlc_points
from app.us_market.sources import USDailyPriceRecord
from app.us_market.trading_calendar import is_us_daily_price_finalized


US_DAILY_CANONICAL_PROVIDER_PRIORITY = {
    "yahoo_chart": 20,
    "alphavantage": 10,
}


def is_yahoo_range_max_url(source_url: str | None) -> bool:
    return bool(source_url and "range=max" in source_url.lower())


def is_yahoo_range_max_record(row: USDailyPrice) -> bool:
    return row.provider == "yahoo_chart" and is_yahoo_range_max_url(row.source_url)


def is_yahoo_range_max_price_record(record: USDailyPriceRecord) -> bool:
    return record.provider == "yahoo_chart" and is_yahoo_range_max_url(record.source_url)


def should_skip_daily_price_update(
    *,
    existing: USDailyPrice,
    record: USDailyPriceRecord,
) -> bool:
    if not is_yahoo_range_max_price_record(record):
        return False
    return not is_yahoo_range_max_record(existing)


def ohlc_point(row: USDailyPrice, time_value: date | None = None) -> dict:
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


def daily_row_completeness_score(row: USDailyPrice) -> int:
    values = (
        row.open_price,
        row.high_price,
        row.low_price,
        row.close_price,
        row.trade_volume,
    )
    return sum(1 for value in values if value is not None)


def daily_canonical_sort_key(row: USDailyPrice) -> tuple[int, float, int, int]:
    return (
        daily_row_completeness_score(row),
        datetime_sort_value(row.fetched_at),
        US_DAILY_CANONICAL_PROVIDER_PRIORITY.get(row.provider, 0),
        row.id or 0,
    )


def dedupe_daily_rows_by_trade_date(rows: list[USDailyPrice]) -> list[USDailyPrice]:
    canonical_by_date: OrderedDict[date, USDailyPrice] = OrderedDict()
    for row in rows:
        existing = canonical_by_date.get(row.trade_date)
        if existing is None or daily_canonical_sort_key(row) > daily_canonical_sort_key(existing):
            canonical_by_date[row.trade_date] = row
    return [canonical_by_date[trade_date] for trade_date in sorted(canonical_by_date)]


def aggregate_daily_rows(rows: list[USDailyPrice], timeframe: str) -> list[dict]:
    return aggregate_ohlc_points(
        points=[ohlc_point(row) for row in rows],
        timeframe=timeframe,
    )


def is_sparse_daily_ohlc_shape(points: list[dict]) -> bool:
    if len(points) < 12:
        return False
    dates = sorted(
        point["time"]
        for point in points
        if isinstance(point.get("time"), date)
    )
    if len(dates) < 12:
        return False
    month_count = len({(item.year, item.month) for item in dates})
    if month_count < 3:
        return False
    average_points_per_month = len(dates) / month_count
    distinct_month_days = len({item.day for item in dates})
    first_day_ratio = sum(1 for item in dates if item.day == 1) / len(dates)
    return (
        average_points_per_month < 6
        or first_day_ratio >= 0.55
        or distinct_month_days <= 4
    )


def filter_ohlc_source_rows(rows: list[USDailyPrice]) -> list[USDailyPrice]:
    filtered_rows = [
        row
        for row in rows
        if not is_yahoo_range_max_record(row)
        and is_us_daily_price_finalized(
            trade_date=row.trade_date,
            fetched_at=row.fetched_at,
        )
    ]
    return dedupe_daily_rows_by_trade_date(filtered_rows)


def has_newer_untrusted_rows(
    *,
    rows: list[USDailyPrice],
    trusted_rows: list[USDailyPrice],
) -> bool:
    trusted_latest_date = max((row.trade_date for row in trusted_rows), default=None)
    for row in rows:
        if (
            not is_yahoo_range_max_record(row)
            and is_us_daily_price_finalized(
                trade_date=row.trade_date,
                fetched_at=row.fetched_at,
            )
        ):
            continue
        if trusted_latest_date is None or row.trade_date > trusted_latest_date:
            return True
    return False
