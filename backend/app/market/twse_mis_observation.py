from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Mapping

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
    if value is None or isinstance(value, bool):
        return False
    try:
        parsed = float(value)
        return isfinite(parsed) and parsed > 0
    except (TypeError, ValueError, OverflowError):
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
    last_trade_price: Decimal | float | None,
    last_trade_volume_lots: int | None,
    cumulative_volume_lots: Any,
    nested_trade: Any = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Resolve whether one MIS message carries a canonical actual-trade price.

    A positive ``z`` alone is not sufficient. The observation must belong to
    the requested trade date, be outside trial-auction state, fall inside the
    exchange's trade/close-resolution window, and carry positive trade-volume
    evidence. This helper is pure so quote, intraday and contract tests can
    share the same boundary without consumer-side inference. A nested execution
    additionally requires explicit ts=0, integral compatible volume and its own
    time at or before the snapshot (and the receipt when supplied).
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
        # Existing adapters use whole board lots for execution evidence.
        if _positive(value) and float(value) >= 1
    ]
    trade_date_matches = bool(
        expected_date is not None
        and observed_date is not None
        and expected_date == observed_date
    )
    event_in_trade_window = bool(
        event_time is not None
        and event_time.date() == observed_date
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
    price_source = "twse_mis_snapshot_z"
    price_event_time = event_time
    normalized_volume = last_trade_volume_lots
    # Nested trade is a separate last-execution observation, never a snapshot
    # timestamp refresh or an auction-price fallback. Keep legacy top-z rules.
    if not _positive(last_trade_price) and isinstance(nested_trade, Mapping):
        try:
            nested_price = Decimal(str(nested_trade.get("z")))
            nested_volume = Decimal(str(nested_trade.get("v")))
            total_volume = Decimal(str(cumulative_volume_lots))
            time_text = nested_trade.get("t")
            nested_time = (
                datetime.strptime(time_text, "%H:%M:%S").time()
                if isinstance(time_text, str) and len(time_text) == 8 else None
            )
            nested_event = (
                datetime.combine(observed_date, nested_time, tzinfo=event_time.tzinfo)
                if observed_date and nested_time and event_time else None
            )
            receipt_time = taiwan_now(observed_at) if observed_at else None
            valid_nested = bool(
                trade_date_matches
                and str(trial_status).strip() == "0"
                and event_in_trade_window
                and nested_event is not None
                and TAIWAN_SESSION_OPEN_TIME <= nested_event.time() <= TAIWAN_CLOSE_RESOLUTION_TIME
                and nested_event <= event_time
                and (receipt_time is None or (
                    receipt_time.date() == observed_date and event_time <= receipt_time
                ))
                and ("d" not in nested_trade or _trade_date(nested_trade["d"]) == observed_date)
                and nested_price.is_finite() and _positive(nested_price)
                and nested_volume.is_finite() and nested_volume > 0
                and nested_volume == nested_volume.to_integral_value()
                and total_volume.is_finite() and total_volume >= nested_volume
                and total_volume == total_volume.to_integral_value()
            )
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            valid_nested = False
        if valid_nested:
            actual_trade_occurred = actual_trade_price_available = True
            last_trade_price = nested_price
            normalized_volume = int(nested_volume)
            price_event_time = nested_event
            price_source = "twse_mis_nested_trade_z"
            volume_evidence_fields = ["trade.v", "v"]

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
            price_event_time if actual_trade_price_available else None
        ),
        "actual_trade_price_source": (
            price_source if actual_trade_price_available else None
        ),
        "actual_trade_price_decimal": (
            Decimal(str(last_trade_price)) if actual_trade_price_available else None
        ),
        "actual_trade_volume_lots": normalized_volume if actual_trade_price_available else None,
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
    confirmed_trade_occurred: bool = False,
    confirmed_trade_price_available: bool = False,
    observation_available: bool = True,
    actual_trade_reason_code: str | None = None,
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
        or confirmed_trade_occurred
    )

    if not observation_available:
        instrument_phase = "unknown"
        projected_legacy_phase = legacy_phase
        reason_code = "NO_SNAPSHOT"
    elif market_phase == "market_closed":
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
        known_no_trade = (
            cumulative_volume_lots == 0
            and not isinstance(cumulative_volume_lots, bool)
            and event_time is not None and event_time.date() == local_now.date()
            and event_time.time() >= TAIWAN_SESSION_OPEN_TIME
            and actual_trade_reason_code in {None, "ACTUAL_TRADE_EVIDENCE_MISSING"}
        )
        instrument_phase = (
            "regular_traded" if actual_trade_occurred else "awaiting_first_trade"
            if known_no_trade else "unknown"
        )
        projected_legacy_phase = "regular_live"
        reason_code = (
            "ACTUAL_TRADE_PRICE_AVAILABLE"
            if actual_trade_price_available or confirmed_trade_price_available
            else "ACTUAL_TRADE_PRICE_MISSING"
            if actual_trade_occurred
            else "AWAITING_FIRST_TRADE" if known_no_trade
            else actual_trade_reason_code or "ACTUAL_TRADE_EVIDENCE_MISSING"
        )
    elif market_phase == "closing_auction":
        instrument_phase = "closing_auction"
        projected_legacy_phase = "closing_auction"
        reason_code = (
            "CLOSING_AUCTION_INDICATIVE_OBSERVED"
            if trial or indicative_available
            else "CLOSING_AUCTION_ACTIVE"
        )
    elif market_phase == "close_resolution":
        instrument_phase = "close_resolution"
        projected_legacy_phase = "close_resolution"
        reason_code = (
            "CLOSE_RESOLUTION_TRIAL_REJECTED"
            if trial
            else "SESSION_CLOSE_CANDIDATE"
            if actual_trade_price_available
            else "CLOSE_RESOLUTION_AWAITING_VALID_TRADE"
        )
    elif market_phase == "post_close":
        instrument_phase = "closed"
        projected_legacy_phase = "post_close_snapshot"
        reason_code = "SESSION_COMPLETED"
    else:
        instrument_phase = "unknown"
        projected_legacy_phase = legacy_phase
        reason_code = "UNKNOWN_SESSION_STATE"

    session_final_candidate = bool(
        observation_available
        and market_phase in {"close_resolution", "post_close"}
        and not trial
        and actual_trade_price_available
        and event_time is not None
        and event_time.date() == local_now.date()
        and event_time.time() <= TAIWAN_CLOSE_RESOLUTION_TIME
    )
    session_final_reason_code = (
        "NO_SNAPSHOT" if not observation_available
        else "VALID_CURRENT_SESSION_ACTUAL_TRADE"
        if session_final_candidate
        else "TRIAL_OBSERVATION"
        if trial
        else "CURRENT_SESSION_EVENT_MISSING"
        if event_time is None or event_time.date() != local_now.date()
        else "ACTUAL_TRADE_PRICE_MISSING"
        if not actual_trade_price_available
        else "SESSION_PHASE_NOT_ELIGIBLE"
    )

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
        "session_final_candidate": session_final_candidate,
        "session_final_reason_code": session_final_reason_code,
        "reason_code": reason_code,
    }


__all__ = [
    "AUCTION_INSTRUMENT_PHASES",
    "resolve_twse_mis_actual_trade",
    "resolve_twse_mis_observation",
]
