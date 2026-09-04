"""Session-aware server-side aggregation of US intraday bars."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Mapping, Sequence

from app.us_market.trading_calendar import US_MARKET_TIMEZONE, us_session_close_time
from app.us_market.volume_semantics import summarize_intraday_volume
from app.research.technical.intraday import (
    INTRADAY_TECHNICAL_ALGORITHM_VERSION,
    INTRADAY_TECHNICAL_PARAMETER_CONTRACT,
    enrich_intraday_technical_points,
)


SUPPORTED_INTRADAY_INTERVALS = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
}
_SESSION_STARTS = {
    "pre_market": time(4, 0),
    "regular": time(9, 30),
    "after_hours": time(16, 0),
}


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=US_MARKET_TIMEZONE)
    return parsed.astimezone(US_MARKET_TIMEZONE)


def _point_number(point: Mapping[str, Any], *fields: str) -> float | None:
    for field in fields:
        value = point.get(field)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
    return None


def _session_allowed(session: str, session_scope: str) -> bool:
    if session_scope == "regular":
        return session == "regular"
    if session_scope == "extended":
        return session in {"pre_market", "after_hours"}
    return session in _SESSION_STARTS


def aggregate_intraday_points(
    points: Sequence[Mapping[str, Any]],
    *,
    interval: str,
    session_scope: str,
) -> list[dict[str, Any]]:
    if interval not in SUPPORTED_INTRADAY_INTERVALS:
        raise ValueError(
            "interval must be one of: " + ", ".join(SUPPORTED_INTRADAY_INTERVALS)
        )
    if session_scope not in {"regular", "extended", "all"}:
        raise ValueError("session_scope must be one of: regular, extended, all.")
    minutes = SUPPORTED_INTRADAY_INTERVALS[interval]
    prepared: list[tuple[datetime, str, Mapping[str, Any]]] = []
    for point in points:
        parsed = _parse_time(point.get("time"))
        session = str(point.get("session") or "regular")
        if parsed is None or not _session_allowed(session, session_scope):
            continue
        price = _point_number(point, "price", "close")
        if price is None:
            continue
        prepared.append((parsed, session, point))
    prepared.sort(key=lambda item: item[0])
    if interval == "1m":
        return [dict(point) for _, _, point in prepared]

    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for parsed, session, point in prepared:
        start_time = (
            us_session_close_time(parsed.date())
            if session == "after_hours"
            else _SESSION_STARTS[session]
        )
        anchor = datetime.combine(parsed.date(), start_time, tzinfo=US_MARKET_TIMEZONE)
        elapsed_minutes = max(0, int((parsed - anchor).total_seconds() // 60))
        bucket_start = anchor + timedelta(minutes=(elapsed_minutes // minutes) * minutes)
        key = (session, bucket_start.isoformat())
        price = _point_number(point, "price", "close")
        assert price is not None
        open_price = _point_number(point, "open") or price
        high_price = _point_number(point, "high") or price
        low_price = _point_number(point, "low") or price
        volume = _point_number(point, "volume")
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = {
                "time": bucket_start.isoformat(),
                "session": session,
                "price": price,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "volume": int(volume) if volume is not None else None,
                "_volume_available_count": 1 if volume is not None else 0,
                "_volume_unavailable_count": 0 if volume is not None else 1,
            }
            continue
        bucket["price"] = price
        bucket["high"] = max(float(bucket["high"]), high_price)
        bucket["low"] = min(float(bucket["low"]), low_price)
        if volume is not None:
            bucket["volume"] = int(bucket.get("volume") or 0) + int(volume)
            bucket["_volume_available_count"] += 1
        else:
            bucket["_volume_unavailable_count"] += 1

    output: list[dict[str, Any]] = []
    for bucket in sorted(buckets.values(), key=lambda item: item["time"]):
        available_count = int(bucket.pop("_volume_available_count"))
        unavailable_count = int(bucket.pop("_volume_unavailable_count"))
        if unavailable_count:
            bucket["volume"] = None
            bucket["volume_status"] = (
                "partial" if available_count else "provider_unavailable"
            )
        else:
            bucket["volume_status"] = "available"
        output.append(bucket)
    return output


def aggregate_intraday_payload(
    payload: Mapping[str, Any], *, interval: str, session_scope: str
) -> dict[str, Any]:
    source_points = payload.get("points") if isinstance(payload.get("points"), list) else []
    aggregated = aggregate_intraday_points(
        [point for point in source_points if isinstance(point, Mapping)],
        interval=interval,
        session_scope=session_scope,
    )
    source_status = (
        payload.get("source_status")
        if isinstance(payload.get("source_status"), Mapping)
        else {}
    )
    live_window = source_status.get("is_live_window") is True
    for index, point in enumerate(aggregated):
        is_partial = live_window and index == len(aggregated) - 1
        point["is_partial"] = is_partial
        point["finalized"] = not is_partial
    aggregated = enrich_intraday_technical_points(aggregated)
    result = dict(payload)
    result["source_interval"] = "1m"
    result["effective_interval"] = interval
    result["interval"] = interval
    result["source_point_count"] = len(source_points)
    result["points"] = aggregated
    result["point_count"] = len(aggregated)
    result["regular_point_count"] = sum(
        1 for point in aggregated if point.get("session") == "regular"
    )
    result["extended_point_count"] = sum(
        1 for point in aggregated if point.get("session") in {"pre_market", "after_hours"}
    )
    result["has_extended_hours"] = result["extended_point_count"] > 0
    result.update(summarize_intraday_volume(aggregated))
    result["sampling_mode"] = "server_aggregated" if interval != "1m" else "source"
    result["aggregation_method"] = "session_anchored_ohlcv.v1"
    result["bar_finalization_status"] = (
        "contains_current_partial" if live_window and aggregated else "completed"
    )
    result["partial_bar_count"] = 1 if live_window and aggregated else 0
    result["technical_algorithm_version"] = INTRADAY_TECHNICAL_ALGORITHM_VERSION
    result["technical_parameter_contract"] = dict(
        INTRADAY_TECHNICAL_PARAMETER_CONTRACT
    )
    return result


__all__ = [
    "SUPPORTED_INTRADAY_INTERVALS",
    "aggregate_intraday_payload",
    "aggregate_intraday_points",
]
