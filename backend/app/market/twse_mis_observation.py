from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.market.trading_calendar import (
    TAIWAN_CLOSE_RESOLUTION_TIME,
    TAIWAN_SESSION_OPEN_TIME,
    taiwan_now,
)


AUCTION_INSTRUMENT_PHASES = {
    "preopen_auction",
    "opening_auction_delayed",
    "closing_auction",
    "closing_auction_delayed",
}


def _positive(value: Any) -> bool:
    if value is None:
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _trial_status(value: Any) -> bool:
    return str(value or "").strip() not in {"", "0"}


def _trade_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    normalized = str(value or "").strip()
    if not normalized:
        return None
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


def resolve_twse_mis_actual_trade(
    *,
    expected_trade_date: date | str | None,
    observation_trade_date: date | str | None,
    provider_event_time: datetime | None,
    trial_status: Any,
    last_trade_price: float | None,
    last_trade_volume_lots: int | None,
    cumulative_volume_lots: int | None,
) -> dict[str, Any]:
    """Resolve whether one MIS message carries a canonical actual-trade price.

    A positive ``z`` alone is not sufficient. The observation must belong to
    the requested trade date, be outside trial-auction state, fall inside the
    exchange's trade/close-resolution window, and carry positive trade-volume
    evidence. This helper is pure so quote, intraday and contract tests can
    share the same boundary without consumer-side inference.
    """

    expected_date = _trade_date(expected_trade_date)
    observed_date = _trade_date(observation_trade_date)
    event_time = taiwan_now(provider_event_time) if provider_event_time else None
    trial = _trial_status(trial_status)
    volume_evidence_fields = [
        field
        for field, value in (
            ("tv", last_trade_volume_lots),
            ("v", cumulative_volume_lots),
        )
        if _positive(value)
    ]
    trade_date_matches = bool(
        expected_date is not None
        and observed_date is not None
        and expected_date == observed_date
    )
    event_in_trade_window = bool(
        event_time is not None
        and TAIWAN_SESSION_OPEN_TIME
        <= event_time.time()
        <= TAIWAN_CLOSE_RESOLUTION_TIME
    )
    actual_trade_occurred = bool(
        trade_date_matches
        and not trial
        and event_in_trade_window
        and volume_evidence_fields
    )
    actual_trade_price_available = bool(
        actual_trade_occurred and _positive(last_trade_price)
    )

    if expected_date is None:
        reason_code = "EXPECTED_TRADE_DATE_MISSING"
    elif observed_date is None:
        reason_code = "OBSERVATION_TRADE_DATE_MISSING"
    elif not trade_date_matches:
        reason_code = "OBSERVATION_TRADE_DATE_MISMATCH"
    elif event_time is None:
        reason_code = "PROVIDER_EVENT_TIME_MISSING"
    elif trial:
        reason_code = "AUCTION_INDICATIVE_ONLY"
    elif not event_in_trade_window:
        reason_code = "OUTSIDE_ACTUAL_TRADE_WINDOW"
    elif not volume_evidence_fields:
        reason_code = "ACTUAL_TRADE_EVIDENCE_MISSING"
    elif not actual_trade_price_available:
        reason_code = "ACTUAL_TRADE_PRICE_MISSING"
    else:
        reason_code = "ACTUAL_TRADE_PRICE_AVAILABLE"

    return {
        "expected_trade_date": expected_date,
        "observation_trade_date": observed_date,
        "trade_date_matches": trade_date_matches,
        "provider_event_time": event_time,
        "trial_evidence": trial,
        "event_in_trade_window": event_in_trade_window,
        "actual_trade_occurred": actual_trade_occurred,
        "actual_trade_price_available": actual_trade_price_available,
        "actual_trade_price": (
            float(last_trade_price)
            if actual_trade_price_available and last_trade_price is not None
            else None
        ),
        "actual_trade_price_as_of": (
            event_time if actual_trade_price_available else None
        ),
        "actual_trade_price_source": (
            "twse_mis_snapshot_z" if actual_trade_price_available else None
        ),
        "volume_evidence_fields": volume_evidence_fields,
        "reason_code": reason_code,
    }


def resolve_twse_mis_observation(
    *,
    request_now: datetime,
    market_calendar_phase: str,
    legacy_clock_phase: str,
    provider_event_time: datetime | None,
    trial_status: Any,
    indicative_price: float | None,
    indicative_volume_lots: int | None,
    last_trade_price: float | None,
    cumulative_volume_lots: int | None,
) -> dict[str, Any]:
    """Classify one TWSE MIS observation without IO or persistence.

    Market clock, individual-security phase and observation evidence are kept
    separate.  In particular, a 09:00 request does not erase an 08:59:55
    trial observation, and positive cumulative volume never manufactures a
    missing last-trade price.
    """

    local_now = taiwan_now(request_now)
    event_time = taiwan_now(provider_event_time) if provider_event_time else None
    market_phase = str(market_calendar_phase or "unknown")
    legacy_phase = str(legacy_clock_phase or "unknown")
    trial = _trial_status(trial_status)
    indicative_available = bool(
        trial and (indicative_price is not None or indicative_volume_lots is not None)
    )
    actual_trade_price_available = last_trade_price is not None
    actual_trade_occurred = bool(
        actual_trade_price_available or _positive(cumulative_volume_lots)
    )

    if market_phase == "market_closed":
        instrument_phase = "closed"
        projected_legacy_phase = "market_closed"
        reason_code = "MARKET_CLOSED"
    elif market_phase == "preopen_pending":
        instrument_phase = "awaiting_preopen"
        projected_legacy_phase = legacy_phase
        reason_code = "CURRENT_SESSION_PENDING"
    elif market_phase == "preopen":
        instrument_phase = "preopen_auction"
        projected_legacy_phase = "preopen_auction"
        reason_code = (
            "AUCTION_INDICATIVE_OBSERVED"
            if trial or indicative_available
            else "PREOPEN_AUCTION_AWAITING_INDICATIVE"
        )
    elif market_phase == "regular" and trial:
        event_before_open = bool(
            event_time is not None and event_time.time() < TAIWAN_SESSION_OPEN_TIME
        )
        instrument_phase = (
            "preopen_auction" if event_before_open else "opening_auction_delayed"
        )
        projected_legacy_phase = "preopen_auction"
        reason_code = (
            "PROVIDER_EVENT_PRECEDES_OPEN"
            if event_before_open
            else "OPENING_AUCTION_DELAYED"
        )
    elif market_phase == "regular":
        instrument_phase = (
            "regular_traded" if actual_trade_occurred else "awaiting_first_trade"
        )
        projected_legacy_phase = "regular_live"
        reason_code = (
            "ACTUAL_TRADE_PRICE_AVAILABLE"
            if actual_trade_price_available
            else "ACTUAL_TRADE_PRICE_MISSING"
            if actual_trade_occurred
            else "AWAITING_FIRST_TRADE"
        )
    elif market_phase == "closing_auction":
        instrument_phase = "closing_auction"
        projected_legacy_phase = "closing_auction"
        reason_code = (
            "CLOSING_AUCTION_INDICATIVE_OBSERVED"
            if trial or indicative_available
            else "CLOSING_AUCTION_ACTIVE"
        )
    elif (
        market_phase == "post_close"
        and trial
        and local_now.time() <= TAIWAN_CLOSE_RESOLUTION_TIME
    ):
        instrument_phase = "closing_auction_delayed"
        projected_legacy_phase = "closing_auction"
        reason_code = "CLOSING_AUCTION_DELAYED"
    elif market_phase == "post_close":
        instrument_phase = (
            "closing_pending"
            if local_now.time() <= TAIWAN_CLOSE_RESOLUTION_TIME
            else "closed"
        )
        projected_legacy_phase = "post_close_snapshot"
        reason_code = (
            "OFFICIAL_CLOSE_PENDING"
            if instrument_phase == "closing_pending"
            else "SESSION_COMPLETED"
        )
    else:
        instrument_phase = "unknown"
        projected_legacy_phase = legacy_phase
        reason_code = "UNKNOWN_SESSION_STATE"

    return {
        "market_calendar_phase": market_phase,
        "instrument_phase": instrument_phase,
        "legacy_session_phase": projected_legacy_phase,
        "auction_applicable": instrument_phase in AUCTION_INSTRUMENT_PHASES,
        "trial_status": str(trial_status or "").strip() or None,
        "trial_evidence": trial,
        "indicative_available": indicative_available,
        "actual_trade_occurred": actual_trade_occurred,
        "actual_trade_price_available": actual_trade_price_available,
        "reason_code": reason_code,
    }


__all__ = [
    "AUCTION_INSTRUMENT_PHASES",
    "resolve_twse_mis_actual_trade",
    "resolve_twse_mis_observation",
]
