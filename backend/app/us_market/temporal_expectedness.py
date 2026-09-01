"""US-owned capability expectedness and temporal evidence projection.

The primitive expectation axis is provider-neutral.  US calendar policy owns
when Quote and Intraday capabilities are expected; support, applicability,
availability, provider snapshot freshness, and trade recency stay independent.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Iterable, Literal

from pydantic import model_validator

from app.market_data.contracts import (
    CanonicalModel,
    CapabilityExpectation,
    EvidenceFreshness,
    InstrumentType,
    MarketSession,
    TradeObservationState,
)
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2
from app.us_market.market_data.descriptors import (
    US_INTRADAY_PROVIDER_DESCRIPTORS,
    US_QUOTE_PROVIDER_DESCRIPTORS,
)
from app.us_market.daily_market_state import expected_us_completed_daily_state
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, is_us_trading_day


USCapabilityId = Literal["quote.snapshot", "intraday.bars"]
USMarketPhase = Literal[
    "pre_market_pending",
    "pre_market",
    "regular",
    "after_hours",
    "post_close",
    "market_closed",
]
US_SESSION_DATE_RELATION_VERSION = "omi.us.session_date_relation.v1"


def _date_value(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.date()
        return value.astimezone(US_MARKET_TIMEZONE).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def build_us_session_date_relation(
    *,
    quote_date: date | datetime | str | None,
    completed_daily_date: date | datetime | str | None,
    now: datetime,
    market_phase: USMarketPhase,
) -> dict[str, object]:
    """Classify Quote versus completed Daily dates using US calendar policy."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    quote = _date_value(quote_date)
    daily = _date_value(completed_daily_date)
    local_date = now.astimezone(US_MARKET_TIMEZONE).date()
    expected_state = expected_us_completed_daily_state(now=now)
    expected_daily = expected_state.expected_trade_date

    relation = "unknown"
    status = "unknown"
    expected = False
    if quote is None or daily is None:
        relation = "insufficient_dates"
        status = "missing"
    elif quote == daily:
        relation = "same_observation_date"
        status = "aligned"
        expected = True
    elif (
        is_us_trading_day(local_date)
        and quote == local_date
        and daily == expected_daily
        and market_phase
        in {
            "pre_market",
            "regular",
            "after_hours",
            "post_close",
        }
    ):
        relation = (
            "current_session_daily_pending_release"
            if expected_daily < local_date
            else "expected_current_session_vs_completed_daily"
        )
        status = "aligned"
        expected = True
    elif daily < expected_daily:
        relation = "completed_daily_lagging_expected_session"
        status = "mismatch"
    else:
        relation = "unexpected_cross_date_relation"
        status = "mismatch"

    return {
        "kind": "session_date_relation",
        "version": US_SESSION_DATE_RELATION_VERSION,
        "relation": relation,
        "status": status,
        "expected": expected,
        "quote_date": quote.isoformat() if quote else None,
        "completed_daily_date": daily.isoformat() if daily else None,
        "expected_completed_daily_date": expected_daily.isoformat(),
        "current_session_date": local_date.isoformat(),
        "release_at": expected_state.release_at.isoformat(),
        "market_phase": market_phase,
    }


class USCapabilitySessionScope(str, Enum):
    NONE = "none"
    REGULAR = "regular"
    EXTENDED = "extended"
    ALL = "all"


class USCapabilityApplicability(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class USCapabilitySupportStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class USCapabilityAvailability(str, Enum):
    AVAILABLE = "available"
    VALID_EMPTY = "valid_empty"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class USTradeRecency(str, Enum):
    CURRENT = "current"
    DELAYED = "delayed"
    OLD = "old"
    HISTORICAL = "historical"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class USCapabilityExpectationOutcome(str, Enum):
    READY = "ready"
    STALE = "stale"
    EXPECTED_BUT_MISSING = "expected_but_missing"
    VALID_EMPTY = "valid_empty"
    HISTORICAL = "historical"
    NOT_EXPECTED = "not_expected"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class USCapabilityExpectationProjection(CanonicalModel):
    """Additive outward projection that preserves every constituent axis."""

    contract_version: str = "omi.us.capability_expectation.v1"
    capability_id: USCapabilityId
    market_phase: USMarketPhase
    expectation: CapabilityExpectation
    expected_now: bool
    required_now: bool
    expected_session_scope: USCapabilitySessionScope
    requested_session_scope: USCapabilitySessionScope
    applicability: USCapabilityApplicability
    support_status: USCapabilitySupportStatus
    live_support_status: USCapabilitySupportStatus
    availability: USCapabilityAvailability
    evidence_freshness: EvidenceFreshness
    provider_snapshot_freshness: EvidenceFreshness
    trade_state: TradeObservationState
    trade_recency: USTradeRecency
    requirement_satisfied: bool | None
    outcome: USCapabilityExpectationOutcome
    reason_code: str

    @model_validator(mode="after")
    def _validate_axes(self) -> "USCapabilityExpectationProjection":
        expected_now = self.expectation is not CapabilityExpectation.NOT_EXPECTED
        if self.expected_now is not expected_now:
            raise ValueError("expected_now must match expectation")
        if self.required_now is not (
            self.expectation is CapabilityExpectation.REQUIRED
        ):
            raise ValueError("required_now must match expectation")
        if (
            self.outcome is USCapabilityExpectationOutcome.EXPECTED_BUT_MISSING
            and (
                not self.expected_now
                or self.availability
                not in {
                    USCapabilityAvailability.MISSING,
                    USCapabilityAvailability.UNAVAILABLE,
                }
            )
        ):
            raise ValueError("expected_but_missing requires expected missing evidence")
        if (
            self.outcome is USCapabilityExpectationOutcome.VALID_EMPTY
            and self.availability is not USCapabilityAvailability.VALID_EMPTY
        ):
            raise ValueError("valid_empty outcome requires valid_empty availability")
        return self


def _phase_session(phase: USMarketPhase) -> MarketSession:
    return {
        "pre_market": MarketSession.PRE_OPEN,
        "regular": MarketSession.CONTINUOUS,
        "after_hours": MarketSession.POST_CLOSE,
    }.get(phase, MarketSession.CLOSED)


def _expectation_policy(
    capability_id: USCapabilityId,
    phase: USMarketPhase,
) -> tuple[CapabilityExpectation, USCapabilitySessionScope]:
    if phase == "pre_market":
        return CapabilityExpectation.EXPECTED, USCapabilitySessionScope.EXTENDED
    if phase == "regular":
        return CapabilityExpectation.REQUIRED, USCapabilitySessionScope.REGULAR
    if phase == "after_hours":
        return CapabilityExpectation.EXPECTED, USCapabilitySessionScope.EXTENDED
    return CapabilityExpectation.NOT_EXPECTED, USCapabilitySessionScope.NONE


def _descriptors_for(
    capability_id: USCapabilityId,
) -> tuple[ProviderCapabilityDescriptorV2, ...]:
    if capability_id == "quote.snapshot":
        return US_QUOTE_PROVIDER_DESCRIPTORS
    return US_INTRADAY_PROVIDER_DESCRIPTORS


def _support_axes(
    *,
    descriptors: Iterable[ProviderCapabilityDescriptorV2],
    instrument_type: InstrumentType | None,
    session: MarketSession,
) -> tuple[
    USCapabilityApplicability,
    USCapabilitySupportStatus,
    USCapabilitySupportStatus,
]:
    candidates = tuple(descriptors)
    if instrument_type is None:
        return (
            USCapabilityApplicability.UNKNOWN,
            USCapabilitySupportStatus.UNKNOWN,
            USCapabilitySupportStatus.UNKNOWN,
        )
    applicable = tuple(
        item for item in candidates if instrument_type in item.instrument_types
    )
    if not applicable:
        return (
            USCapabilityApplicability.NOT_APPLICABLE,
            USCapabilitySupportStatus.UNSUPPORTED,
            USCapabilitySupportStatus.UNSUPPORTED,
        )
    session_supported = tuple(
        item
        for item in applicable
        if not item.supported_sessions or session in item.supported_sessions
    )
    support = (
        USCapabilitySupportStatus.SUPPORTED
        if session_supported
        else USCapabilitySupportStatus.UNSUPPORTED
    )
    live_support = (
        USCapabilitySupportStatus.SUPPORTED
        if any(item.can_produce_live for item in session_supported)
        else USCapabilitySupportStatus.UNSUPPORTED
    )
    return USCapabilityApplicability.APPLICABLE, support, live_support


def _not_expected_reason(phase: USMarketPhase) -> str:
    if phase == "pre_market_pending":
        return "PREMARKET_NOT_STARTED"
    if phase == "market_closed":
        return "MARKET_CLOSED"
    return "NOT_IN_TRADING_WINDOW"


def _derive_outcome(
    *,
    capability_id: USCapabilityId,
    phase: USMarketPhase,
    expectation: CapabilityExpectation,
    applicability: USCapabilityApplicability,
    support_status: USCapabilitySupportStatus,
    availability: USCapabilityAvailability,
    evidence_freshness: EvidenceFreshness,
    provider_snapshot_freshness: EvidenceFreshness,
    trade_state: TradeObservationState,
    trade_recency: USTradeRecency,
) -> tuple[USCapabilityExpectationOutcome, bool | None, str]:
    if applicability is USCapabilityApplicability.NOT_APPLICABLE:
        return (
            USCapabilityExpectationOutcome.NOT_APPLICABLE,
            None,
            "CAPABILITY_NOT_APPLICABLE",
        )
    if expectation is CapabilityExpectation.NOT_EXPECTED:
        if availability is USCapabilityAvailability.AVAILABLE:
            return (
                USCapabilityExpectationOutcome.HISTORICAL,
                None,
                _not_expected_reason(phase),
            )
        return (
            USCapabilityExpectationOutcome.NOT_EXPECTED,
            None,
            _not_expected_reason(phase),
        )
    if support_status is USCapabilitySupportStatus.UNSUPPORTED:
        return (
            USCapabilityExpectationOutcome.UNSUPPORTED,
            None,
            "EXTENDED_HOURS_UNSUPPORTED"
            if phase in {"pre_market", "after_hours"}
            else "CAPABILITY_UNSUPPORTED",
        )
    if availability is USCapabilityAvailability.VALID_EMPTY:
        return (
            USCapabilityExpectationOutcome.VALID_EMPTY,
            True,
            "NO_TRADE_OBSERVED",
        )
    if availability is USCapabilityAvailability.AVAILABLE:
        if (
            capability_id == "quote.snapshot"
            and provider_snapshot_freshness
            in {EvidenceFreshness.FRESH, EvidenceFreshness.LIVE}
            and trade_recency is USTradeRecency.OLD
        ):
            return (
                USCapabilityExpectationOutcome.READY,
                True,
                "LAST_TRADE_OLD_BUT_PROVIDER_CURRENT",
            )
        if evidence_freshness is EvidenceFreshness.STALE:
            return (
                USCapabilityExpectationOutcome.STALE,
                False,
                "PROVIDER_SNAPSHOT_STALE",
            )
        if trade_state is TradeObservationState.AWAITING_FIRST_TRADE:
            return (
                USCapabilityExpectationOutcome.VALID_EMPTY,
                True,
                "NO_TRADE_OBSERVED",
            )
        return (
            USCapabilityExpectationOutcome.READY,
            True,
            "CURRENT_QUOTE_AVAILABLE"
            if capability_id == "quote.snapshot"
            else "CURRENT_INTRADAY_BARS_AVAILABLE",
        )
    if availability in {
        USCapabilityAvailability.MISSING,
        USCapabilityAvailability.UNAVAILABLE,
    }:
        return (
            USCapabilityExpectationOutcome.EXPECTED_BUT_MISSING,
            False,
            "EXPECTED_CURRENT_QUOTE_MISSING"
            if capability_id == "quote.snapshot"
            else "EXPECTED_INTRADAY_BARS_MISSING",
        )
    return USCapabilityExpectationOutcome.UNKNOWN, None, "CAPABILITY_STATE_UNKNOWN"


def build_us_capability_expectation(
    *,
    capability_id: USCapabilityId,
    market_phase: USMarketPhase,
    requested_session_scope: USCapabilitySessionScope,
    instrument_type: InstrumentType | None,
    availability: USCapabilityAvailability,
    evidence_freshness: EvidenceFreshness = EvidenceFreshness.UNKNOWN,
    provider_snapshot_freshness: EvidenceFreshness = EvidenceFreshness.UNKNOWN,
    trade_state: TradeObservationState = TradeObservationState.UNKNOWN,
    trade_recency: USTradeRecency = USTradeRecency.UNKNOWN,
    descriptors: Iterable[ProviderCapabilityDescriptorV2] | None = None,
) -> USCapabilityExpectationProjection:
    """Build one US capability projection without reading provider/runtime state."""

    expectation, expected_scope = _expectation_policy(capability_id, market_phase)
    descriptor_set = (
        _descriptors_for(capability_id)
        if descriptors is None
        else tuple(descriptors)
    )
    applicability, support, live_support = _support_axes(
        descriptors=descriptor_set,
        instrument_type=instrument_type,
        session=_phase_session(market_phase),
    )
    outcome, satisfied, reason_code = _derive_outcome(
        capability_id=capability_id,
        phase=market_phase,
        expectation=expectation,
        applicability=applicability,
        support_status=support,
        availability=availability,
        evidence_freshness=evidence_freshness,
        provider_snapshot_freshness=provider_snapshot_freshness,
        trade_state=trade_state,
        trade_recency=trade_recency,
    )
    return USCapabilityExpectationProjection(
        capability_id=capability_id,
        market_phase=market_phase,
        expectation=expectation,
        expected_now=expectation is not CapabilityExpectation.NOT_EXPECTED,
        required_now=expectation is CapabilityExpectation.REQUIRED,
        expected_session_scope=expected_scope,
        requested_session_scope=requested_session_scope,
        applicability=applicability,
        support_status=support,
        live_support_status=live_support,
        availability=availability,
        evidence_freshness=evidence_freshness,
        provider_snapshot_freshness=provider_snapshot_freshness,
        trade_state=trade_state,
        trade_recency=trade_recency,
        requirement_satisfied=satisfied,
        outcome=outcome,
        reason_code=reason_code,
    )


__all__ = [
    "US_SESSION_DATE_RELATION_VERSION",
    "USCapabilityApplicability",
    "USCapabilityAvailability",
    "USCapabilityExpectationOutcome",
    "USCapabilityExpectationProjection",
    "USCapabilitySessionScope",
    "USCapabilitySupportStatus",
    "USTradeRecency",
    "build_us_capability_expectation",
    "build_us_session_date_relation",
]
