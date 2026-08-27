from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


TAIPEI_TZ = ZoneInfo("Asia/Taipei")
_POST_CLOSE_PHASES = {
    "post_close",
    "daily_close",
    "latest_session_close",
    "completed",
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ)


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return _datetime(value).date()
    if isinstance(value, date):
        return value
    parsed = _datetime(value)
    if parsed is not None:
        return parsed.date()
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def _current_session_points(
    points: Sequence[Mapping[str, Any]],
    *,
    session_date: date,
) -> list[tuple[datetime, Mapping[str, Any]]]:
    selected: list[tuple[datetime, Mapping[str, Any]]] = []
    for point in points:
        event_at = _datetime(point.get("time"))
        close = _number(point.get("close", point.get("price")))
        if event_at is None or event_at.date() != session_date or close is None:
            continue
        selected.append((event_at, point))
    selected.sort(key=lambda item: item[0])
    return selected


def build_current_partial_daily_bar(
    *,
    completed_daily_points: Sequence[Mapping[str, Any]],
    intraday_points: Sequence[Mapping[str, Any]] | None,
    quote: Mapping[str, Any] | None,
    session_date: date,
    session_phase: str | None,
) -> dict[str, Any] | None:
    """Build a non-persisted Taiwan provisional daily bar from current-session facts.

    This function is intentionally pure: it performs no provider refresh and no
    database write. A current-session trade must be observable; yesterday's
    close is never promoted into a synthetic today bar.
    """

    if completed_daily_points:
        latest_completed_date = _date(completed_daily_points[-1].get("time"))
        if latest_completed_date is not None and latest_completed_date >= session_date:
            return None

    quote = quote if isinstance(quote, Mapping) else {}
    quote_trade_date = _date(quote.get("trade_date"))
    quote_event_at = _datetime(
        quote.get("event_time")
        or quote.get("provider_event_time")
        or quote.get("quote_time")
    )
    quote_current = bool(
        quote_trade_date == session_date
        and (
            quote.get("last_trade_is_current_session") is True
            or quote.get("actual_trade_occurred") is True
            or quote.get("facts_usable_for_current_session") is True
        )
    )
    selected = _current_session_points(
        intraday_points or [],
        session_date=session_date,
    )
    if not selected and not quote_current:
        return None

    bar_opens = [
        _number(point.get("open"))
        for _, point in selected
        if _number(point.get("open")) is not None
    ]
    bar_highs = [
        value
        for _, point in selected
        if (
            value := _number(
                point.get("high", point.get("close", point.get("price")))
            )
        ) is not None
    ]
    bar_lows = [
        value
        for _, point in selected
        if (
            value := _number(
                point.get("low", point.get("close", point.get("price")))
            )
        ) is not None
    ]
    bar_closes = [
        value
        for _, point in selected
        if (value := _number(point.get("close", point.get("price")))) is not None
    ]

    quote_open = _number(quote.get("open_price")) if quote_current else None
    quote_high = _number(quote.get("high_price")) if quote_current else None
    quote_low = _number(quote.get("low_price")) if quote_current else None
    quote_close = _number(
        quote.get("last_trade_price", quote.get("last_price", quote.get("latest_price")))
    ) if quote_current else None
    open_value = quote_open if quote_open is not None else (bar_opens[0] if bar_opens else bar_closes[0] if bar_closes else None)
    high_candidates = [value for value in [quote_high, *bar_highs, quote_close] if value is not None]
    low_candidates = [value for value in [quote_low, *bar_lows, quote_close] if value is not None]
    close_value = quote_close if quote_close is not None else (bar_closes[-1] if bar_closes else None)
    if open_value is None or close_value is None or not high_candidates or not low_candidates:
        return None

    cumulative_volume = None
    volume_source = None
    if quote_current:
        cumulative_volume = _number(quote.get("cumulative_volume_shares"))
        if cumulative_volume is None:
            lots = _number(quote.get("cumulative_volume_lots"))
            cumulative_volume = lots * 1000 if lots is not None else None
        if cumulative_volume is not None:
            volume_source = str(quote.get("volume_source") or quote.get("provider") or "quote")
    if cumulative_volume is None and selected:
        bar_volumes = [_number(point.get("volume")) for _, point in selected]
        if bar_volumes and all(value is not None and value >= 0 for value in bar_volumes):
            cumulative_volume = sum(value for value in bar_volumes if value is not None)
            volume_source = "intraday_bar_sum"

    event_at = max(
        [value for value in [quote_event_at, selected[-1][0] if selected else None] if value is not None],
        default=None,
    )
    phase = str(session_phase or quote.get("session_phase") or "unknown").strip().lower()
    components = (
        quote.get("components")
        if isinstance(quote.get("components"), Mapping)
        else {}
    )
    session_close = (
        components.get("session_close")
        if isinstance(components.get("session_close"), Mapping)
        else {}
    )
    session_close_final = bool(
        quote.get("session_close_available") is True
        or (
            session_close.get("available") is True
            and session_close.get("finalization")
            in {"session_final", "official_daily_confirmed"}
        )
    )
    bar_status = (
        "provisional_close"
        if phase in _POST_CLOSE_PHASES and session_close_final
        else "intraday_partial"
    )
    previous_close = (
        _number(completed_daily_points[-1].get("close"))
        if completed_daily_points
        else None
    )
    price_change = (
        close_value - previous_close
        if previous_close is not None
        else None
    )
    return {
        "time": session_date,
        "open": open_value,
        "high": max(high_candidates),
        "low": min(low_candidates),
        "close": close_value,
        "volume": cumulative_volume,
        "price_change": price_change,
        "bar_status": bar_status,
        "session_close_finalization": (
            (
                session_close.get("finalization")
                or quote.get("session_close_status")
            )
            if session_close_final
            else None
        ),
        "official_daily_confirmed": False,
        "decision_usable": False,
        "event_time": event_at.isoformat() if event_at is not None else None,
        "source": "+".join(
            value
            for value in (
                "intraday_bars" if selected else None,
                str(quote.get("provider") or quote.get("source") or "quote") if quote_current else None,
            )
            if value
        ),
        "volume_source": volume_source,
        "volume_semantics": "session_cumulative_partial",
    }


__all__ = ["build_current_partial_daily_bar"]
