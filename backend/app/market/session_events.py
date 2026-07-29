from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


# This registry contains bounded, date-specific session events. Entries may be
# inferred from cross-instrument market evidence before an official source is
# available, but must remain explicit about that lower source grade.
MARKET_SESSION_EVENTS: tuple[dict[str, Any], ...] = (
    {
        "event_id": "KR-KOSPI-20260728-INFERRED-HALT-01",
        "market": "KR",
        "venue": "KRX",
        "event_type": "inferred_market_halt",
        "level": None,
        "halt_start_at": "2026-07-28T10:14:00+09:00",
        "halt_end_at": "2026-07-28T10:42:59+09:00",
        "reopen_auction_start_at": "2026-07-28T10:43:00+09:00",
        "continuous_trading_resumed_at": "2026-07-28T10:44:00+09:00",
        "source": "cross_instrument_intraday_observation",
        "source_grade": "inferred",
        "confirmed": False,
        "evidence": (
            "KOSPI held a constant price with zero interval volume while "
            "005930.KS had no bars; both resumed around 10:44 Asia/Seoul."
        ),
    },
)


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def events_for_observations(
    *,
    market: str,
    observation_times: Iterable[Any],
) -> list[dict[str, Any]]:
    normalized_market = str(market or "").strip().upper()
    observation_dates = {
        parsed.date()
        for value in observation_times
        if (parsed := _datetime_value(value)) is not None
    }
    if not observation_dates:
        return []
    return [
        dict(event)
        for event in MARKET_SESSION_EVENTS
        if str(event.get("market") or "").strip().upper() == normalized_market
        and (
            event_time := _datetime_value(event.get("halt_start_at"))
        ) is not None
        and event_time.date() in observation_dates
    ]
