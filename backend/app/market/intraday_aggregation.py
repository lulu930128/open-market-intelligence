from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta, tzinfo
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _point_time(value: Any, *, market_timezone: tzinfo) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=market_timezone)
    return parsed.astimezone(market_timezone)


def aggregate_regular_session_ohlcv(
    points: list[dict[str, Any]],
    *,
    interval_minutes: int,
    market_timezone: tzinfo,
    session_segments: tuple[tuple[time, time, str], ...],
    volume_additive: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate 1m observations without crossing market session boundaries."""
    if interval_minutes <= 1:
        raise ValueError("interval_minutes must be greater than one.")

    parsed_points: list[tuple[datetime, dict[str, Any]]] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        point_at = _point_time(
            point.get("event_time")
            or point.get("bar_time")
            or point.get("time"),
            market_timezone=market_timezone,
        )
        price = _number(point.get("price") or point.get("close"))
        if point_at is None or price is None:
            continue
        parsed_points.append((point_at, point))
    parsed_points.sort(key=lambda item: item[0])
    if not parsed_points:
        return [], {
            "aggregation_method": f"local_ohlcv_1m_to_{interval_minutes}m",
            "source_point_count": 0,
            "partial_bar_count": 0,
        }

    checked_at = parsed_points[-1][0]
    buckets: dict[
        tuple[str, str, datetime],
        list[tuple[datetime, dict[str, Any]]],
    ] = defaultdict(list)
    bucket_close_by_key: dict[tuple[str, str, datetime], datetime] = {}
    for point_at, point in parsed_points:
        for segment_start, segment_end, session_name in session_segments:
            segment_start_at = datetime.combine(
                point_at.date(),
                segment_start,
                tzinfo=market_timezone,
            )
            segment_end_at = datetime.combine(
                point_at.date(),
                segment_end,
                tzinfo=market_timezone,
            )
            if not segment_start_at <= point_at <= segment_end_at:
                continue
            elapsed_minutes = max(
                int((point_at - segment_start_at).total_seconds() // 60),
                0,
            )
            bucket_start = segment_start_at + timedelta(
                minutes=(elapsed_minutes // interval_minutes) * interval_minutes
            )
            bucket_close = min(
                bucket_start + timedelta(minutes=interval_minutes),
                segment_end_at,
            )
            key = (
                point_at.date().isoformat(),
                session_name,
                bucket_start,
            )
            buckets[key].append((point_at, point))
            bucket_close_by_key[key] = bucket_close
            break

    aggregated: list[dict[str, Any]] = []
    for key in sorted(buckets, key=lambda item: item[2]):
        bucket_points = sorted(buckets[key], key=lambda item: item[0])
        bucket_start = key[2]
        bucket_close = bucket_close_by_key[key]
        prices = [
            _number(point.get("price") or point.get("close"))
            for _, point in bucket_points
        ]
        opens = [
            _number(point.get("open")) or price
            for price, (_, point) in zip(prices, bucket_points)
        ]
        highs = [
            _number(point.get("high")) or price
            for price, (_, point) in zip(prices, bucket_points)
        ]
        lows = [
            _number(point.get("low")) or price
            for price, (_, point) in zip(prices, bucket_points)
        ]
        closes = [
            _number(point.get("close")) or price
            for price, (_, point) in zip(prices, bucket_points)
        ]
        volumes = [
            _number(point.get("volume"))
            for _, point in bucket_points
        ]
        trade_values = [
            _number(point.get("trade_value"))
            for _, point in bucket_points
        ]
        expected_point_count = max(
            int((bucket_close - bucket_start).total_seconds() // 60),
            1,
        )
        observed_minutes = {
            point_at.replace(second=0, microsecond=0)
            for point_at, _ in bucket_points
        }
        finalized = bool(
            checked_at >= bucket_close
            and len(observed_minutes) >= expected_point_count
        )
        close_price = closes[-1]
        aggregated.append(
            {
                "time": bucket_start.isoformat(),
                "bar_time": bucket_start.isoformat(),
                "event_time": bucket_points[-1][0].isoformat(),
                "bar_close_time": bucket_close.isoformat(),
                "session": key[1],
                "open": opens[0],
                "high": max(value for value in highs if value is not None),
                "low": min(value for value in lows if value is not None),
                "close": close_price,
                "price": close_price,
                "volume": (
                    int(sum(value for value in volumes if value is not None))
                    if volume_additive and any(value is not None for value in volumes)
                    else None
                ),
                "trade_value": (
                    int(sum(value for value in trade_values if value is not None))
                    if any(value is not None for value in trade_values)
                    else None
                ),
                "source_point_count": len(bucket_points),
                "expected_point_count": expected_point_count,
                "is_partial": not finalized,
                "finalized": finalized,
                "aggregation_method": (
                    f"local_ohlcv_1m_to_{interval_minutes}m"
                ),
            }
        )

    return aggregated, {
        "aggregation_method": f"local_ohlcv_1m_to_{interval_minutes}m",
        "source_point_count": len(parsed_points),
        "aggregated_point_count": len(aggregated),
        "partial_bar_count": sum(
            1 for point in aggregated if point.get("is_partial")
        ),
    }


__all__ = ["aggregate_regular_session_ohlcv"]
