from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Any


def point_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if value is None:
        return None

    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _positive_int(value: Any) -> int | None:
    if value is None:
        return None

    try:
        parsed = int(float(str(value).replace(",", "")))
    except ValueError:
        return None

    return parsed if parsed > 0 else None


def _sum_nullable(values: list[Any]) -> int | float | None:
    valid_values = [value for value in values if value is not None]

    if not valid_values:
        return None

    return sum(valid_values)


def intraday_overlay_point(
    intraday: dict,
    *,
    null_fields: tuple[str, ...] = (),
) -> tuple[dict, dict] | None:
    source_points = intraday.get("points") or []
    valid_points: list[tuple[datetime, dict]] = []

    for point in source_points:
        if not isinstance(point, dict):
            continue

        point_time = point.get("time")
        close = _number(point.get("price"))
        if point_time is None or close is None:
            continue

        try:
            parsed_time = datetime.fromisoformat(str(point_time))
        except ValueError:
            continue

        valid_points.append((parsed_time, point))

    if not valid_points:
        return None

    latest_date = max(point_time.date() for point_time, _ in valid_points)
    session_points = [
        (point_time, point)
        for point_time, point in valid_points
        if point_time.date() == latest_date
    ]
    session_points.sort(key=lambda item: item[0])

    first_point = session_points[0][1]
    last_point = session_points[-1][1]
    open_price = _number(first_point.get("open")) or _number(first_point.get("price"))
    close_price = _number(last_point.get("price"))
    high_values = [
        value
        for _, point in session_points
        for value in (_number(point.get("high")), _number(point.get("price")))
        if value is not None
    ]
    low_values = [
        value
        for _, point in session_points
        for value in (_number(point.get("low")), _number(point.get("price")))
        if value is not None
    ]
    volumes = [
        value
        for _, point in session_points
        if (value := _positive_int(point.get("volume"))) is not None
    ]

    overlay = {
        "time": latest_date,
        "open": open_price,
        "high": max(high_values) if high_values else close_price,
        "low": min(low_values) if low_values else close_price,
        "close": close_price,
        "volume": sum(volumes) if volumes else None,
        **{field: None for field in null_fields},
    }
    metadata = {
        "source": intraday.get("source"),
        "trade_date": latest_date,
        "point_count": len(session_points),
        "latest_time": session_points[-1][0],
        "provisional": True,
    }

    return overlay, metadata


def append_intraday_overlay(
    *,
    points: list[dict],
    intraday: dict,
    end_date: date,
    null_fields: tuple[str, ...] = (),
) -> tuple[list[dict], dict | None]:
    overlay_result = intraday_overlay_point(intraday, null_fields=null_fields)
    if overlay_result is None:
        return points, None

    overlay, metadata = overlay_result
    overlay_date = point_date(overlay["time"])
    if overlay_date is None or overlay_date > end_date:
        return points, None

    next_points = [
        point
        for point in points
        if point_date(point.get("time")) != overlay_date
    ]
    next_points.append(overlay)
    next_points.sort(key=lambda point: point_date(point.get("time")) or date.min)

    return next_points, metadata


def aggregate_ohlc_points(
    *,
    points: list[dict],
    timeframe: str,
    sum_fields: tuple[str, ...] = ("volume",),
) -> list[dict]:
    sorted_points = sorted(
        points,
        key=lambda point: point_date(point.get("time")) or date.min,
    )

    if timeframe == "daily":
        return sorted_points

    groups: "OrderedDict[date, list[dict]]" = OrderedDict()

    for point in sorted_points:
        point_time = point_date(point.get("time"))
        if point_time is None:
            continue

        if timeframe == "weekly":
            key = point_time - timedelta(days=point_time.weekday())
        else:
            key = date(point_time.year, point_time.month, 1)

        groups.setdefault(key, []).append(point)

    results: list[dict] = []

    for key, grouped_points in groups.items():
        first = grouped_points[0]
        last = grouped_points[-1]
        highs = [
            point.get("high")
            for point in grouped_points
            if point.get("high") is not None
        ]
        lows = [
            point.get("low")
            for point in grouped_points
            if point.get("low") is not None
        ]
        result = {
            "time": key,
            "open": first.get("open"),
            "high": max(highs) if highs else None,
            "low": min(lows) if lows else None,
            "close": last.get("close"),
        }

        for field in sum_fields:
            result[field] = _sum_nullable([point.get(field) for point in grouped_points])

        results.append(result)

    return results
