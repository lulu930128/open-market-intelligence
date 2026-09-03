"""Read-only cross-capability US Market Truth composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Iterable
from uuid import uuid4

from sqlalchemy.orm import Session

from app.market.calendar_status import build_us_calendar_status
from app.market_data.contracts import (
    BarFinalization,
    BarObservation,
    CapabilityExpectation,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    MarketSession,
    PriceUnit,
    QuoteObservation,
    ResolvedBarSeries,
    ResolvedEvidenceHealth,
    ResolvedEvidenceStatus,
    ResolvedQuote,
)
from app.us_market.close_resolution_policy import (
    USCloseCandidateDecision,
    USCloseResolutionPolicy,
    USProviderHintContext,
    evaluate_provider_previous_close_hint,
    reconcile_close_evidence,
)
from app.us_market.daily_market_state import expected_us_completed_daily_state
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_truth_contracts import (
    USChangeCalculationStatus,
    USChangeMetric,
    USCloseEvidence,
    USCloseEvidenceKind,
    USCloseRoles,
    USComparisonPurpose,
    USComparisonReference,
    USComponentRevisions,
    USEvidenceRelease,
    USMarketTruthAvailability,
    USMarketTruthComponentStatus,
    USMarketTruthHealth,
    USMarketTruthSnapshot,
    USIntradaySeriesPoint,
    USIntradaySeriesProjection,
    USObservation,
    USObservationKind,
    USOfficialCloseProof,
    build_evidence_revision,
    build_truth_revision,
    semantic_fingerprint,
)
from app.us_market.session_policy import us_session_for_timestamp
from app.us_market.temporal_expectedness import (
    USCapabilitySessionScope,
    USMarketPhase,
    USTradeRecency,
    evaluate_us_selected_evidence_temporal,
    select_us_intraday_trade_date,
)
from app.us_market.trading_calendar import (
    US_MARKET_TIMEZONE,
    expected_us_intraday_trade_date,
    previous_us_trading_day,
    us_session_close_time,
)


_VERIFIED_PREVIOUS_CLOSE_CONTRACTS = {
    "yahoo.chart.v8",
    "twelve_data.quote.v1",
}


@dataclass(frozen=True)
class _USMarketTruthComponents:
    quote_read: object
    bars_read: object
    daily_read: object
    latest_intraday_trade_date: date | None = None


@dataclass(frozen=True)
class USMarketTruthBundle:
    snapshot: USMarketTruthSnapshot
    series: USIntradaySeriesProjection


_INTERVAL_CLOSE_BLOCKING_LIMITATIONS = frozenset(
    {
        "NON_CANONICAL_MINUTE_IDENTITY",
        "DUPLICATE_MINUTE_BUCKET",
        "INTRADAY_BUCKET_CONFLICT",
    }
)


def _selected_freshness(value: ResolvedQuote | ResolvedBarSeries) -> EvidenceFreshness:
    health = value.health
    selected = next(
        (
            candidate
            for candidate in value.candidates
            if candidate.provider == health.selected_provider
            and candidate.source == health.selected_source
            and candidate.eligible
        ),
        None,
    )
    return selected.freshness if selected is not None else EvidenceFreshness.UNKNOWN


def _observation_temporal_limitations(
    *,
    trade_recency: USTradeRecency,
    current_session_expected: bool,
    current_session_satisfied: bool,
) -> tuple[str, ...]:
    limitations: list[str] = []
    if current_session_expected and not current_session_satisfied:
        limitations.append("LAST_TRADE_NOT_CURRENT_SESSION")
    if trade_recency is USTradeRecency.OLD:
        limitations.append("LAST_TRADE_OLD")
    return tuple(limitations)


def _event_at(lineage, *, fallback: datetime) -> datetime:
    return lineage.event_at or lineage.received_at or lineage.fetched_at or fallback


def _fetched_at(lineage, *, fallback: datetime) -> datetime:
    return lineage.fetched_at or lineage.received_at or lineage.event_at or fallback


def _immutable_observation_id(*, prefix: str, value: object, lineage) -> str:
    upstream = lineage.observation_id or lineage.content_hash
    revision = upstream or semantic_fingerprint(value)
    return f"{prefix}:{revision}"


def _price_semantics(
    instrument: InstrumentKey,
    *,
    currency: str | None,
) -> tuple[PriceUnit, str | None]:
    if instrument.instrument_type is InstrumentType.INDEX:
        return PriceUnit.INDEX_POINT, None
    return PriceUnit.CURRENCY, (currency or "USD").upper()


def _quote_observation(
    resolved: ResolvedQuote,
    *,
    evaluated_at: datetime,
    market_phase: USMarketPhase,
) -> USObservation | None:
    quote = resolved.quote
    if (
        quote is None
        or quote.last_trade_price is None
        or quote.trade_date is None
        or not resolved.health.facts_usable
    ):
        return None
    event_at = _event_at(quote.lineage, fallback=evaluated_at)
    price_unit, currency = _price_semantics(
        quote.instrument,
        currency=quote.currency,
    )
    temporal = evaluate_us_selected_evidence_temporal(
        now=evaluated_at,
        market_phase=market_phase,
        session_scope=USCapabilitySessionScope.ALL,
        event_at=event_at,
        fetched_at=quote.lineage.fetched_at or quote.lineage.received_at,
        selected_freshness=_selected_freshness(resolved),
    )
    research_usable = bool(
        resolved.health.research_usable
        and temporal.evidence_freshness
        not in {EvidenceFreshness.STALE, EvidenceFreshness.MISSING}
        and (
            not temporal.current_session_expected
            or (
                temporal.current_session_satisfied
                and temporal.trade_recency is not USTradeRecency.OLD
            )
        )
    )
    return USObservation(
        observation_id=_immutable_observation_id(
            prefix="quote",
            value=quote,
            lineage=quote.lineage,
        ),
        kind=USObservationKind.QUOTE,
        instrument=quote.instrument,
        trade_date=quote.trade_date,
        price=quote.last_trade_price,
        price_unit=price_unit,
        currency=currency,
        price_basis="raw",
        session=(
            resolved.health.selected_session
            or us_session_for_timestamp(event_at)
        ),
        event_at=event_at,
        fetched_at=_fetched_at(quote.lineage, fallback=evaluated_at),
        selected_provider=resolved.health.selected_provider or quote.lineage.provider,
        selected_source=resolved.health.selected_source or quote.lineage.source,
        selection_reason=resolved.health.selection_reason,
        fallback_used=resolved.health.fallback_used,
        availability=USMarketTruthAvailability.AVAILABLE,
        freshness=temporal.evidence_freshness,
        provider_snapshot_freshness=temporal.provider_snapshot_freshness,
        trade_recency=temporal.trade_recency,
        current_session_expected=temporal.current_session_expected,
        current_session_satisfied=temporal.current_session_satisfied,
        expectedness=CapabilityExpectation.EXPECTED,
        display_usable=resolved.health.facts_usable,
        research_usable=research_usable,
        limitations=tuple(
            dict.fromkeys(
                (
                    *resolved.health.limitations,
                    *_observation_temporal_limitations(
                        trade_recency=temporal.trade_recency,
                        current_session_expected=temporal.current_session_expected,
                        current_session_satisfied=temporal.current_session_satisfied,
                    ),
                )
            )
        ),
    )


def _bar_observation(
    resolved: ResolvedBarSeries,
    *,
    evaluated_at: datetime,
    market_phase: USMarketPhase,
) -> USObservation | None:
    if not resolved.bars or not resolved.health.facts_usable:
        return None
    bar = resolved.bars[-1]
    event_at = _event_at(bar.lineage, fallback=bar.end_at)
    price_unit, currency = _price_semantics(bar.instrument, currency="USD")
    temporal = evaluate_us_selected_evidence_temporal(
        now=evaluated_at,
        market_phase=market_phase,
        session_scope=USCapabilitySessionScope.ALL,
        event_at=event_at,
        fetched_at=bar.lineage.fetched_at or bar.lineage.received_at,
        selected_freshness=_selected_freshness(resolved),
    )
    research_usable = bool(
        resolved.health.research_usable
        and temporal.evidence_freshness
        not in {EvidenceFreshness.STALE, EvidenceFreshness.MISSING}
        and (
            not temporal.current_session_expected
            or (
                temporal.current_session_satisfied
                and temporal.trade_recency is not USTradeRecency.OLD
            )
        )
    )
    return USObservation(
        observation_id=_immutable_observation_id(
            prefix="bar",
            value=bar,
            lineage=bar.lineage,
        ),
        kind=USObservationKind.BAR,
        instrument=bar.instrument,
        trade_date=bar.start_at.astimezone(US_MARKET_TIMEZONE).date(),
        price=bar.close_price,
        price_unit=price_unit,
        currency=currency,
        price_basis=bar.price_basis or "provider_default",
        session=us_session_for_timestamp(bar.start_at),
        event_at=event_at,
        fetched_at=_fetched_at(bar.lineage, fallback=evaluated_at),
        selected_provider=resolved.health.selected_provider or bar.lineage.provider,
        selected_source=resolved.health.selected_source or bar.lineage.source,
        selection_reason=resolved.health.selection_reason,
        fallback_used=resolved.health.fallback_used,
        availability=USMarketTruthAvailability.AVAILABLE,
        freshness=temporal.evidence_freshness,
        provider_snapshot_freshness=temporal.provider_snapshot_freshness,
        trade_recency=temporal.trade_recency,
        current_session_expected=temporal.current_session_expected,
        current_session_satisfied=temporal.current_session_satisfied,
        expectedness=CapabilityExpectation.EXPECTED,
        display_usable=resolved.health.facts_usable,
        research_usable=research_usable,
        limitations=tuple(
            dict.fromkeys(
                (
                    *resolved.health.limitations,
                    *_observation_temporal_limitations(
                        trade_recency=temporal.trade_recency,
                        current_session_expected=temporal.current_session_expected,
                        current_session_satisfied=temporal.current_session_satisfied,
                    ),
                )
            )
        ),
    )


def _close_payload(
    *,
    evidence_key: str,
    observation_id: str,
    instrument: InstrumentKey,
    trade_date: date,
    price: Decimal,
    currency: str | None,
    price_basis: str,
    evidence_kind: USCloseEvidenceKind,
    provider: str,
    source: str,
    authority,
    session: MarketSession,
    event_at: datetime,
    fetched_at: datetime,
    finalization: BarFinalization,
    release: USEvidenceRelease,
    freshness: EvidenceFreshness,
    display_usable: bool,
    research_usable: bool,
    interval_start_at: datetime | None = None,
    interval_end_at: datetime | None = None,
    limitations: tuple[str, ...] = (),
) -> dict:
    price_unit, normalized_currency = _price_semantics(
        instrument,
        currency=currency,
    )
    semantic = {
        "evidence_key": evidence_key,
        "observation_id": observation_id,
        "instrument": instrument.model_dump(mode="json"),
        "trade_date": trade_date.isoformat(),
        "price": str(price),
        "price_unit": price_unit.value,
        "currency": normalized_currency,
        "price_basis": price_basis,
        "evidence_kind": evidence_kind.value,
        "provider": provider,
        "source": source,
        "authority": authority.value,
        "session": session.value,
        "event_at": event_at.isoformat(),
        "fetched_at": fetched_at.isoformat(),
        "finalization": finalization.value,
        "release": release.value,
        "freshness": freshness.value,
        "limitations": limitations,
    }
    fingerprint = semantic_fingerprint(semantic)
    return {
        **semantic,
        "instrument": instrument,
        "trade_date": trade_date,
        "price": price,
        "price_unit": price_unit,
        "authority": authority,
        "session": session,
        "event_at": event_at,
        "fetched_at": fetched_at,
        "finalization": finalization,
        "release": release,
        "freshness": freshness,
        "evidence_id": f"{evidence_key}:{fingerprint[:16]}",
        "semantic_fingerprint": fingerprint,
        "official_close_proof": USOfficialCloseProof.NONE,
        "expectedness": CapabilityExpectation.REQUIRED,
        "display_usable": display_usable,
        "research_usable": research_usable,
        "interval_start_at": interval_start_at,
        "interval_end_at": interval_end_at,
    }


def _daily_close_evidence(
    daily: ResolvedBarSeries,
    *,
    target_dates: set[date],
    evaluated_at: datetime,
) -> tuple[USCloseEvidence, ...]:
    result: list[USCloseEvidence] = []
    freshness = _selected_freshness(daily)
    for bar in daily.bars:
        trade_date = bar.end_at.astimezone(US_MARKET_TIMEZONE).date()
        if trade_date not in target_dates:
            continue
        observation_id = _immutable_observation_id(
            prefix="daily",
            value=bar,
            lineage=bar.lineage,
        )
        result.append(
            USCloseEvidence(
                **_close_payload(
                    evidence_key=(
                        f"daily:{bar.instrument.symbol}:{trade_date}:"
                        f"{bar.lineage.provider}"
                    ),
                    observation_id=observation_id,
                    instrument=bar.instrument,
                    trade_date=trade_date,
                    price=bar.close_price,
                    currency="USD",
                    price_basis=bar.price_basis or "provider_default",
                    evidence_kind=USCloseEvidenceKind.COMPLETED_DAILY,
                    provider=bar.lineage.provider,
                    source=bar.lineage.source,
                    authority=bar.lineage.authority,
                    session=MarketSession.CLOSED,
                    event_at=_event_at(bar.lineage, fallback=bar.end_at),
                    fetched_at=_fetched_at(bar.lineage, fallback=evaluated_at),
                    finalization=bar.finalization,
                    release=USEvidenceRelease.RELEASED,
                    freshness=freshness,
                    display_usable=daily.health.facts_usable,
                    research_usable=daily.health.research_usable,
                    limitations=daily.health.limitations,
                )
            )
        )
    return tuple(result)


def _intraday_close_evidence(
    bars: ResolvedBarSeries,
    *,
    target_dates: set[date],
    evaluated_at: datetime,
) -> tuple[USCloseEvidence, ...]:
    result: list[USCloseEvidence] = []
    freshness = _selected_freshness(bars)
    regular_buckets_by_date: dict[date, set[datetime]] = {}
    for candidate in bars.bars:
        local_start = candidate.start_at.astimezone(US_MARKET_TIMEZONE)
        if (
            us_session_for_timestamp(candidate.start_at)
            is MarketSession.CONTINUOUS
            and candidate.interval == "1m"
        ):
            regular_buckets_by_date.setdefault(local_start.date(), set()).add(
                local_start
            )
    for bar in bars.bars:
        local_start = bar.start_at.astimezone(US_MARKET_TIMEZONE)
        local_end = bar.end_at.astimezone(US_MARKET_TIMEZONE)
        trade_date = local_start.date()
        if trade_date not in target_dates:
            continue
        session = us_session_for_timestamp(bar.start_at)
        formal_close = datetime.combine(
            trade_date,
            us_session_close_time(trade_date),
            tzinfo=US_MARKET_TIMEZONE,
        )
        if (
            session is MarketSession.CONTINUOUS
            and local_end == formal_close
            and bar.finalization is not BarFinalization.PROVISIONAL
        ):
            kind = USCloseEvidenceKind.FINALIZED_REGULAR_INTERVAL_CLOSE
            session_open = datetime.combine(
                trade_date,
                time(hour=9, minute=30),
                tzinfo=US_MARKET_TIMEZONE,
            )
            scheduled_count = int(
                (formal_close - session_open).total_seconds() // 60
            )
            expected_buckets = {
                session_open + timedelta(minutes=index)
                for index in range(scheduled_count)
            }
            observed_buckets = regular_buckets_by_date.get(trade_date, set())
            blocking = tuple(
                item
                for item in bars.health.limitations
                if item in _INTERVAL_CLOSE_BLOCKING_LIMITATIONS
                or item.startswith("NON_CANONICAL_")
                or item.startswith("DUPLICATE_")
            )
            quality_limitations: list[str] = []
            if not bars.health.facts_usable:
                quality_limitations.append("PARENT_INTRADAY_FACTS_UNUSABLE")
            if blocking:
                quality_limitations.append("INTRADAY_INTEGRITY_GATE_FAILED")
            if bar.interval != "1m":
                quality_limitations.append("CLOSE_INTERVAL_NOT_ONE_MINUTE")
            if observed_buckets != expected_buckets:
                quality_limitations.append("REGULAR_SESSION_CONTINUITY_INCOMPLETE")
            display_usable = not quality_limitations
            research_usable = False
            limitations = tuple(
                dict.fromkeys(
                    (
                        *bars.health.limitations,
                        *quality_limitations,
                        "FINALIZED_INTERVAL_CLOSE_LIMITED",
                    )
                )
            )
        elif session is MarketSession.CLOSING_AUCTION:
            kind = USCloseEvidenceKind.UNVERIFIED_CLOSE_BOUNDARY_BAR
            display_usable = False
            research_usable = False
            limitations = tuple(
                dict.fromkeys(
                    (*bars.health.limitations, "CLOSE_BOUNDARY_NOT_OFFICIAL")
                )
            )
        else:
            continue
        observation_id = _immutable_observation_id(
            prefix="intraday",
            value=bar,
            lineage=bar.lineage,
        )
        result.append(
            USCloseEvidence(
                **_close_payload(
                    evidence_key=(
                        f"{kind.value}:{bar.instrument.symbol}:{trade_date}:"
                        f"{bar.start_at.isoformat()}:{bar.lineage.provider}"
                    ),
                    observation_id=observation_id,
                    instrument=bar.instrument,
                    trade_date=trade_date,
                    price=bar.close_price,
                    currency="USD",
                    price_basis=bar.price_basis or "provider_default",
                    evidence_kind=kind,
                    provider=bar.lineage.provider,
                    source=bar.lineage.source,
                    authority=bar.lineage.authority,
                    session=session,
                    event_at=_event_at(bar.lineage, fallback=bar.end_at),
                    fetched_at=_fetched_at(bar.lineage, fallback=evaluated_at),
                    finalization=bar.finalization,
                    release=USEvidenceRelease.NOT_APPLICABLE,
                    freshness=freshness,
                    display_usable=display_usable,
                    research_usable=research_usable,
                    interval_start_at=bar.start_at,
                    interval_end_at=bar.end_at,
                    limitations=limitations,
                )
            )
        )
    return tuple(result)


def _provider_hint_evidence(
    quote: QuoteObservation | None,
    *,
    expected_trade_date: date,
    stronger_conflict: bool,
    freshness: EvidenceFreshness,
    evaluated_at: datetime,
) -> USCloseEvidence | None:
    if (
        quote is None
        or quote.previous_close is None
        or quote.trade_date is None
        or quote.lineage.event_at is None
    ):
        return None
    observation_id = _immutable_observation_id(
        prefix="quote",
        value=quote,
        lineage=quote.lineage,
    )
    payload = _close_payload(
        evidence_key=(
            f"provider_hint:{quote.instrument.symbol}:{expected_trade_date}:"
            f"{quote.lineage.provider}"
        ),
        observation_id=observation_id,
        instrument=quote.instrument,
        trade_date=expected_trade_date,
        price=quote.previous_close,
        currency=quote.currency,
        price_basis="raw",
        evidence_kind=USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT,
        provider=quote.lineage.provider,
        source=quote.lineage.source,
        authority=quote.lineage.authority,
        session=MarketSession.CLOSED,
        event_at=quote.lineage.event_at,
        fetched_at=_fetched_at(quote.lineage, fallback=evaluated_at),
        finalization=BarFinalization.UNKNOWN,
        release=USEvidenceRelease.NOT_APPLICABLE,
        freshness=freshness,
        display_usable=False,
        research_usable=False,
    )
    provisional = USCloseEvidence(**payload)
    evaluation = evaluate_provider_previous_close_hint(
        provisional,
        context=USProviderHintContext(
            expected_trade_date=expected_trade_date,
            quote_trade_date=quote.trade_date,
            same_observation_provider=True,
            provider_semantics_verified=(
                quote.lineage.raw_contract_version
                in _VERIFIED_PREVIOUS_CLOSE_CONTRACTS
            ),
            stronger_conflict=stronger_conflict,
        ),
    )
    return USCloseEvidence(
        **{
            **payload,
            "display_usable": evaluation.display_usable,
            "research_usable": evaluation.research_usable,
            "limitations": tuple(
                dict.fromkeys((*provisional.limitations, evaluation.reason_code))
            ),
        }
    )


def _resolve_role(
    evidence: Iterable[USCloseEvidence],
    *,
    trade_date: date,
) -> USCloseEvidence | None:
    policy = USCloseResolutionPolicy()
    eligible = []
    for item in evidence:
        if item.trade_date != trade_date:
            continue
        decision = policy.evaluate(item)
        if (
            decision.decision is USCloseCandidateDecision.ELIGIBLE
            and decision.priority is not None
        ):
            eligible.append((decision.priority, item))
    return min(eligible, key=lambda pair: pair[0])[1] if eligible else None


def _close_observation(
    evidence: USCloseEvidence,
    *,
    health: ResolvedEvidenceHealth,
) -> USObservation:
    return USObservation(
        observation_id=evidence.observation_id,
        kind=USObservationKind.CLOSE,
        instrument=evidence.instrument,
        trade_date=evidence.trade_date,
        price=evidence.price,
        price_unit=evidence.price_unit,
        currency=evidence.currency,
        price_basis=evidence.price_basis,
        session=MarketSession.CLOSED,
        event_at=evidence.event_at,
        fetched_at=evidence.fetched_at,
        selected_provider=health.selected_provider or evidence.provider,
        selected_source=health.selected_source or evidence.source,
        selection_reason=health.selection_reason,
        fallback_used=health.fallback_used,
        availability=evidence.availability,
        freshness=evidence.freshness,
        expectedness=CapabilityExpectation.NOT_EXPECTED,
        display_usable=evidence.display_usable,
        research_usable=evidence.research_usable,
        limitations=evidence.limitations,
    )


def _phase_expected_session(phase: USMarketPhase) -> MarketSession | None:
    return {
        "pre_market": MarketSession.PRE_OPEN,
        "regular": MarketSession.CONTINUOUS,
        "after_hours": MarketSession.POST_CLOSE,
    }.get(phase)


def _select_current(
    observations: Iterable[USObservation],
    *,
    market_phase: USMarketPhase,
    expected_trade_date: date | None,
) -> USObservation | None:
    expected_session = _phase_expected_session(market_phase)
    if expected_session is None:
        return None
    candidates = [
        item
        for item in observations
        if item.session is expected_session
        and expected_trade_date is not None
        and item.trade_date == expected_trade_date
        and item.current_session_satisfied
        and item.availability is USMarketTruthAvailability.AVAILABLE
        and item.display_usable
    ]
    return max(candidates, key=lambda item: item.event_at, default=None)


def _comparison_evidence(
    *,
    purpose: USComparisonPurpose,
    headline: USObservation | None,
    market_phase: USMarketPhase,
    latest_close: USCloseEvidence | None,
    prior_close: USCloseEvidence | None,
    hint: USCloseEvidence | None,
) -> USCloseEvidence | None:
    if headline is None:
        return None
    if purpose is USComparisonPurpose.EXTENDED_SESSION_CHANGE:
        if (
            headline.session is MarketSession.POST_CLOSE
            and latest_close is not None
            and latest_close.trade_date == headline.trade_date
        ):
            return latest_close
        return None
    if headline.kind is USObservationKind.CLOSE:
        if purpose is USComparisonPurpose.RESEARCH_CHANGE:
            return prior_close if prior_close and prior_close.research_usable else None
        return prior_close
    if market_phase in {"after_hours", "post_close"}:
        if latest_close is not None and latest_close.trade_date == headline.trade_date:
            if (
                purpose is not USComparisonPurpose.RESEARCH_CHANGE
                or latest_close.research_usable
            ):
                return latest_close
        return None
    if latest_close is not None and latest_close.trade_date < headline.trade_date:
        if (
            purpose is not USComparisonPurpose.RESEARCH_CHANGE
            or latest_close.research_usable
        ):
            return latest_close
    if (
        purpose is not USComparisonPurpose.RESEARCH_CHANGE
        and hint is not None
        and hint.display_usable
        and hint.trade_date < headline.trade_date
    ):
        return hint
    return None


def _comparison_reference(
    *,
    instrument: InstrumentKey,
    purpose: USComparisonPurpose,
    evidence: USCloseEvidence | None,
) -> USComparisonReference:
    purpose_token = purpose.value
    if evidence is None:
        return USComparisonReference(
            reference_id=f"reference:{instrument.symbol}:{purpose_token}:missing",
            evidence_id=None,
            purpose=purpose,
            instrument=instrument,
            calculation_eligible=False,
            display_usable=False,
            research_usable=False,
            reason_code="COMPARISON_REFERENCE_UNAVAILABLE",
            limitations=("COMPARISON_REFERENCE_UNAVAILABLE",),
        )
    return USComparisonReference(
        reference_id=(
            f"reference:{instrument.symbol}:{purpose_token}:{evidence.evidence_id}"
        ),
        evidence_id=evidence.evidence_id,
        purpose=purpose,
        instrument=instrument,
        reference_trade_date=evidence.trade_date,
        price=evidence.price,
        price_unit=evidence.price_unit,
        currency=evidence.currency,
        price_basis=evidence.price_basis,
        calculation_eligible=evidence.display_usable,
        display_usable=evidence.display_usable,
        research_usable=evidence.research_usable,
        reason_code=(
            "PROVIDER_PREVIOUS_CLOSE_LIMITED"
            if evidence.evidence_kind
            is USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT
            else "RESOLVED_CLOSE_REFERENCE"
        ),
        limitations=evidence.limitations,
    )


def _change_metric(
    *,
    instrument: InstrumentKey,
    purpose: USComparisonPurpose,
    observation: USObservation | None,
    reference: USComparisonReference,
) -> USChangeMetric:
    metric_id = f"metric:{instrument.symbol}:{purpose.value}:{reference.reference_id}"
    if observation is None or not reference.calculation_eligible:
        return USChangeMetric(
            metric_id=metric_id,
            purpose=purpose,
            calculation_status=USChangeCalculationStatus.MISSING,
            reason_code="CHANGE_UNAVAILABLE",
            display_usable=False,
            research_usable=False,
        )
    compatible = (
        observation.instrument == reference.instrument
        and observation.price_unit == reference.price_unit
        and observation.currency == reference.currency
        and observation.price_basis == reference.price_basis
    )
    if not compatible or reference.price is None:
        return USChangeMetric(
            metric_id=metric_id,
            purpose=purpose,
            calculation_status=USChangeCalculationStatus.INCOMPATIBLE_EVIDENCE,
            reason_code="PRICE_SEMANTICS_MISMATCH",
            display_usable=False,
            research_usable=False,
        )
    absolute = observation.price - reference.price
    percent = absolute / reference.price * Decimal("100")
    limited = not reference.research_usable
    return USChangeMetric(
        metric_id=metric_id,
        purpose=purpose,
        observation_id=observation.observation_id,
        reference_id=reference.reference_id,
        absolute_change=absolute,
        percent_change=percent,
        calculation_status=(
            USChangeCalculationStatus.LIMITED
            if limited
            else USChangeCalculationStatus.CALCULATED
        ),
        reason_code=("LIMITED_REFERENCE" if limited else "CALCULATED"),
        display_usable=observation.display_usable and reference.display_usable,
        research_usable=(
            observation.research_usable and reference.research_usable
        ),
    )


def _component_status(
    health: ResolvedEvidenceHealth,
    *,
    materialized: bool,
    freshness: EvidenceFreshness,
) -> USMarketTruthComponentStatus:
    if materialized:
        availability = USMarketTruthAvailability.AVAILABLE
        reason_code = "COMPONENT_AVAILABLE"
    elif health.status is ResolvedEvidenceStatus.MISSING:
        availability = USMarketTruthAvailability.MISSING
        reason_code = "COMPONENT_EVIDENCE_MISSING"
    else:
        availability = USMarketTruthAvailability.UNAVAILABLE
        reason_code = f"COMPONENT_{health.status.value.upper()}"
    return USMarketTruthComponentStatus(
        availability=availability,
        reason_code=reason_code,
        resolved_health=health,
        freshness=freshness,
        limitations=health.limitations,
    )


def _ensure_sqlite_read_snapshot(db: Session) -> None:
    """Pin all component reads to one SQLite MVCC generation when applicable."""

    if not isinstance(db, Session) or db.in_transaction():
        return
    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN")


def _read_components(
    db: Session,
    *,
    symbol: str,
    evaluated_at: datetime,
) -> _USMarketTruthComponents:
    intraday_platform = USIntradayMarketPlatform(db)
    calendar = build_us_calendar_status(evaluated_at)
    market_phase: USMarketPhase = calendar.get("phase", "market_closed")
    expected_trade_date = expected_us_intraday_trade_date(
        market_phase=market_phase,
        now=evaluated_at,
    )
    latest_trade_date = intraday_platform.latest_intraday_trade_date(
        symbol=symbol,
    )
    target_trade_date = (
        expected_trade_date
        if expected_trade_date is not None
        else latest_trade_date
        if latest_trade_date is not None
        else evaluated_at.astimezone(US_MARKET_TIMEZONE).date()
    )
    quote_read = intraday_platform.read_quote(symbol=symbol, now=evaluated_at)
    bars_read = intraday_platform.read_intraday_bars_for_trade_date(
        symbol=symbol,
        trade_date=target_trade_date,
        bars=1000,
        now=evaluated_at,
    )
    if (
        expected_trade_date is not None
        and not bars_read.result.resolved.bars
        and latest_trade_date is not None
        and latest_trade_date != expected_trade_date
    ):
        # Preserve one bounded stale-status observation without projecting a
        # prior session as Today's series.
        bars_read = intraday_platform.read_intraday_bars_for_trade_date(
            symbol=symbol,
            trade_date=latest_trade_date,
            bars=1,
            now=evaluated_at,
        )
    return _USMarketTruthComponents(
        quote_read=quote_read,
        bars_read=bars_read,
        daily_read=USDailyOhlcvPlatform(db).read(
            symbol=symbol,
            bars=30,
            now=evaluated_at,
        ),
        latest_intraday_trade_date=latest_trade_date,
    )


def _compose_us_market_truth_snapshot(
    *,
    components: _USMarketTruthComponents,
    evaluated_at: datetime,
) -> USMarketTruthSnapshot:
    """Compose one deterministic snapshot from one read generation.

    The caller owns the SQLAlchemy Session and clock.  All platform reads use
    this same Session and the same ``evaluated_at``.  No refresh-capable method
    is reachable from this function.
    """

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")

    calendar = build_us_calendar_status(evaluated_at)
    market_phase: USMarketPhase = calendar.get("phase", "market_closed")
    expected_intraday_trade_date = expected_us_intraday_trade_date(
        market_phase=market_phase,
        now=evaluated_at,
    )
    quote_read = components.quote_read
    bars_read = components.bars_read
    daily_read = components.daily_read

    identity = quote_read.identity.instrument
    if bars_read.identity.instrument != identity or daily_read.identity.instrument != identity:
        raise ValueError("US Market Truth component identity mismatch")

    expected_daily = expected_us_completed_daily_state(now=evaluated_at)
    local_date = evaluated_at.astimezone(US_MARKET_TIMEZONE).date()
    latest_target = (
        local_date
        if market_phase in {"after_hours", "post_close"}
        else expected_daily.expected_trade_date
    )
    prior_target = previous_us_trading_day(latest_target, include_value=False)
    target_dates = {latest_target, prior_target, expected_daily.expected_trade_date}

    daily_evidence = _daily_close_evidence(
        daily_read.result.resolved,
        target_dates=target_dates,
        evaluated_at=evaluated_at,
    )
    interval_evidence = _intraday_close_evidence(
        bars_read.result.resolved,
        target_dates=target_dates,
        evaluated_at=evaluated_at,
    )
    evidence: tuple[USCloseEvidence, ...] = daily_evidence + interval_evidence
    close_policy = USCloseResolutionPolicy()
    exact_expected_exists = any(
        item.trade_date == expected_daily.expected_trade_date
        and item.evidence_kind is USCloseEvidenceKind.COMPLETED_DAILY
        and close_policy.evaluate(item).decision
        is USCloseCandidateDecision.ELIGIBLE
        for item in evidence
    )
    hint = _provider_hint_evidence(
        quote_read.result.resolved.quote,
        expected_trade_date=expected_daily.expected_trade_date,
        stronger_conflict=exact_expected_exists,
        freshness=_selected_freshness(quote_read.result.resolved),
        evaluated_at=evaluated_at,
    )
    if hint is not None:
        evidence += (hint,)

    latest_close = _resolve_role(evidence, trade_date=latest_target)
    prior_close = _resolve_role(evidence, trade_date=prior_target)
    close_roles = USCloseRoles(
        latest_completed_id=(latest_close.evidence_id if latest_close else None),
        prior_completed_id=(prior_close.evidence_id if prior_close else None),
    )
    reconciliation = None
    if latest_close is not None:
        secondary_close = next(
            (
                item
                for item in evidence
                if item.trade_date == latest_close.trade_date
                and item.evidence_id != latest_close.evidence_id
                and item.display_usable
                and item.price_unit == latest_close.price_unit
                and item.currency == latest_close.currency
                and item.price_basis == latest_close.price_basis
                and item.evidence_kind
                is not USCloseEvidenceKind.PROVIDER_PREVIOUS_CLOSE_HINT
            ),
            None,
        )
        if secondary_close is not None:
            reconciliation = reconcile_close_evidence(
                latest_close,
                secondary_close,
            )

    quote_observation = _quote_observation(
        quote_read.result.resolved,
        evaluated_at=evaluated_at,
        market_phase=market_phase,
    )
    bar_observation = _bar_observation(
        bars_read.result.resolved,
        evaluated_at=evaluated_at,
        market_phase=market_phase,
    )
    close_health = (
        daily_read.result.resolved.health
        if latest_close is not None
        and latest_close.evidence_kind is USCloseEvidenceKind.COMPLETED_DAILY
        else bars_read.result.resolved.health
    )
    close_observation = (
        _close_observation(latest_close, health=close_health)
        if latest_close
        else None
    )
    market_observations = tuple(
        item for item in (quote_observation, bar_observation) if item is not None
    )
    latest_observation = max(
        (*market_observations, *((close_observation,) if close_observation else ())),
        key=lambda item: item.event_at,
        default=None,
    )
    current_observation = _select_current(
        market_observations,
        market_phase=market_phase,
        expected_trade_date=expected_intraday_trade_date,
    )
    if market_phase in {"pre_market_pending", "market_closed"}:
        headline_observation = close_observation
    elif current_observation is not None:
        headline_observation = current_observation
    elif market_phase == "post_close" and latest_observation is not None:
        headline_observation = latest_observation
    else:
        # An older cached Quote/Intraday observation remains available through
        # ``latest_observation`` but must never become the active-session price.
        headline_observation = close_observation

    purpose_observations = {
        USComparisonPurpose.REGULAR_SESSION_CHANGE: (
            current_observation
            if current_observation is not None
            and current_observation.session is MarketSession.CONTINUOUS
            else close_observation
            if headline_observation is close_observation
            else None
        ),
        USComparisonPurpose.EXTENDED_SESSION_CHANGE: (
            current_observation
            if current_observation is not None
            and current_observation.session is MarketSession.POST_CLOSE
            else None
        ),
        USComparisonPurpose.HEADLINE_CHANGE: headline_observation,
        USComparisonPurpose.RESEARCH_CHANGE: (
            headline_observation
            if headline_observation is not None
            and headline_observation.research_usable
            else None
        ),
    }
    references: list[USComparisonReference] = []
    metrics: list[USChangeMetric] = []
    for purpose in USComparisonPurpose:
        purpose_observation = purpose_observations[purpose]
        comparison_evidence = _comparison_evidence(
            purpose=purpose,
            headline=purpose_observation,
            market_phase=market_phase,
            latest_close=latest_close,
            prior_close=prior_close,
            hint=hint,
        )
        reference = _comparison_reference(
            instrument=identity,
            purpose=purpose,
            evidence=comparison_evidence,
        )
        references.append(reference)
        metrics.append(
            _change_metric(
                instrument=identity,
                purpose=purpose,
                observation=purpose_observation,
                reference=reference,
            )
        )
    reference_tuple = tuple(references)
    metric_tuple = tuple(metrics)

    evidence_revision = build_evidence_revision(evidence)
    calendar_revision = semantic_fingerprint(
        {
            "phase": market_phase,
            "local_date": local_date.isoformat(),
            "expected_daily": expected_daily.expected_trade_date.isoformat(),
            "release_at": expected_daily.release_at.isoformat(),
            "session_close": us_session_close_time(local_date).isoformat(),
        }
    )
    component_revisions = USComponentRevisions(
        quote_revision=(
            semantic_fingerprint(quote_read.result.resolved.quote)
            if quote_read.result.resolved.quote is not None
            else None
        ),
        intraday_revision=semantic_fingerprint(
            bars_read.result.resolved.model_dump(mode="json")
        ),
        close_revision=evidence_revision,
        daily_revision=semantic_fingerprint(
            daily_read.result.resolved.model_dump(mode="json")
        ),
        calendar_revision=calendar_revision,
    )
    selected_ids = (
        latest_observation.observation_id if latest_observation else None,
        current_observation.observation_id if current_observation else None,
        headline_observation.observation_id if headline_observation else None,
    )
    truth_revision = build_truth_revision(
        contract_version="omi.market.us_truth_snapshot.v1",
        evidence_revision=evidence_revision,
        market_phase=market_phase,
        component_revisions=component_revisions,
        selected_observation_ids=selected_ids,
        references=reference_tuple,
        metrics=metric_tuple,
        reconciliation=reconciliation,
    )
    return USMarketTruthSnapshot(
        evaluated_at=evaluated_at,
        evaluation_id=str(uuid4()),
        evidence_revision=evidence_revision,
        truth_revision=truth_revision,
        component_revisions=component_revisions,
        instrument=identity,
        market_phase=market_phase,
        expectation=(
            CapabilityExpectation.NOT_EXPECTED
            if _phase_expected_session(market_phase) is None
            else CapabilityExpectation.EXPECTED
        ),
        quote_observation=quote_observation,
        intraday_observation=bar_observation,
        latest_observation=latest_observation,
        current_observation=current_observation,
        headline_observation=headline_observation,
        close_evidence=evidence,
        close_roles=close_roles,
        comparison_references=reference_tuple,
        change_metrics=metric_tuple,
        reconciliation=reconciliation,
        health=USMarketTruthHealth(
            quote=_component_status(
                quote_read.result.resolved.health,
                materialized=quote_read.result.resolved.quote is not None,
                freshness=_selected_freshness(quote_read.result.resolved),
            ),
            intraday=_component_status(
                bars_read.result.resolved.health,
                materialized=bool(bars_read.result.resolved.bars),
                freshness=_selected_freshness(bars_read.result.resolved),
            ),
            daily=_component_status(
                daily_read.result.resolved.health,
                materialized=bool(daily_read.result.resolved.bars),
                freshness=_selected_freshness(daily_read.result.resolved),
            ),
        ),
        limitations=tuple(
            dict.fromkeys(
                (
                    *quote_read.result.limitations,
                    *bars_read.result.limitations,
                    *daily_read.result.limitations,
                )
            )
        ),
    )


def _series_point(bar: BarObservation) -> USIntradaySeriesPoint:
    price_unit, currency = _price_semantics(bar.instrument, currency="USD")
    return USIntradaySeriesPoint(
        observation_id=_immutable_observation_id(
            prefix="bar",
            value=bar,
            lineage=bar.lineage,
        ),
        start_at=bar.start_at,
        end_at=bar.end_at,
        open_price=bar.open_price,
        high_price=bar.high_price,
        low_price=bar.low_price,
        close_price=bar.close_price,
        volume=(bar.volume.value if bar.volume is not None else None),
        volume_status=bar.volume_status,
        price_unit=price_unit,
        currency=currency,
        price_basis=bar.price_basis or "provider_default",
        session=us_session_for_timestamp(bar.start_at),
        finalization=bar.finalization,
        provider=bar.lineage.provider,
        source=bar.lineage.source,
    )


def _compose_us_intraday_series_projection(
    *,
    snapshot: USMarketTruthSnapshot,
    bars: ResolvedBarSeries,
    evaluated_at: datetime,
    requested_scope: str,
    latest_available_trade_date: date | None = None,
) -> USIntradaySeriesProjection:
    if requested_scope not in {"regular", "extended", "all"}:
        raise ValueError("requested_scope must be regular, extended, or all")
    points = tuple(_series_point(bar) for bar in bars.bars)
    date_selection = select_us_intraday_trade_date(
        tuple(
            point.start_at.astimezone(US_MARKET_TIMEZONE).date()
            for point in points
        )
        + ((latest_available_trade_date,) if latest_available_trade_date else ()),
        now=evaluated_at,
        market_phase=snapshot.market_phase,
    )
    trade_date = date_selection.selected_trade_date
    current_points = tuple(
        point
        for point in points
        if trade_date is not None
        and point.start_at.astimezone(US_MARKET_TIMEZONE).date() == trade_date
    )
    regular = tuple(
        point for point in current_points if point.session is MarketSession.CONTINUOUS
    )
    pre_market = tuple(
        point for point in current_points if point.session is MarketSession.PRE_OPEN
    )
    after_hours = tuple(
        point for point in current_points if point.session is MarketSession.POST_CLOSE
    )
    close_boundary = tuple(
        point
        for point in current_points
        if point.session is MarketSession.CLOSING_AUCTION
    )
    if trade_date is None:
        scheduled = 0
    else:
        session_open = datetime.combine(
            trade_date,
            time(hour=9, minute=30),
            tzinfo=US_MARKET_TIMEZONE,
        )
        session_close = datetime.combine(
            trade_date,
            us_session_close_time(trade_date),
            tzinfo=US_MARKET_TIMEZONE,
        )
        scheduled = int((session_close - session_open).total_seconds() // 60)
    observed = len(regular)
    missing = max(scheduled - observed, 0)
    continuity = (
        "not_applicable"
        if trade_date is None
        else "complete"
        if missing == 0
        else "missing"
        if observed == 0
        else "partial"
    )
    interval = bars.bars[0].interval if bars.bars else "1m"
    return USIntradaySeriesProjection(
        evaluated_at=evaluated_at,
        truth_revision=snapshot.truth_revision,
        intraday_revision=snapshot.component_revisions.intraday_revision
        or semantic_fingerprint(()),
        instrument=snapshot.instrument,
        trade_date=trade_date,
        expected_trade_date=date_selection.expected_trade_date,
        latest_available_trade_date=date_selection.latest_available_trade_date,
        current_session_expected=date_selection.current_session_expected,
        current_session_satisfied=date_selection.current_session_satisfied,
        selection_reason=date_selection.selection_reason,
        interval=interval,
        requested_scope=requested_scope,
        regular_points=regular,
        pre_market_points=pre_market,
        after_hours_points=after_hours,
        close_boundary_events=close_boundary,
        scheduled_interval_count=scheduled,
        observed_interval_count=observed,
        missing_interval_count=missing,
        explained_gap_count=0,
        continuity=continuity,
        limitations=bars.health.limitations,
    )


def read_us_market_truth_snapshot(
    db: Session,
    *,
    symbol: str,
    evaluated_at: datetime,
) -> USMarketTruthSnapshot:
    _ensure_sqlite_read_snapshot(db)
    components = _read_components(
        db,
        symbol=symbol,
        evaluated_at=evaluated_at,
    )
    return _compose_us_market_truth_snapshot(
        components=components,
        evaluated_at=evaluated_at,
    )


def read_us_intraday_series_projection(
    db: Session,
    *,
    symbol: str,
    evaluated_at: datetime,
    requested_scope: str = "regular",
) -> USIntradaySeriesProjection:
    """Read the large intraday payload separately from the truth snapshot."""

    return read_us_market_truth_bundle(
        db,
        symbol=symbol,
        evaluated_at=evaluated_at,
        requested_scope=requested_scope,
    ).series


def read_us_market_truth_bundle(
    db: Session,
    *,
    symbol: str,
    evaluated_at: datetime,
    requested_scope: str = "regular",
) -> USMarketTruthBundle:
    """Read Snapshot and Series from one component generation."""

    _ensure_sqlite_read_snapshot(db)
    components = _read_components(
        db,
        symbol=symbol,
        evaluated_at=evaluated_at,
    )
    snapshot = _compose_us_market_truth_snapshot(
        components=components,
        evaluated_at=evaluated_at,
    )
    series = _compose_us_intraday_series_projection(
        snapshot=snapshot,
        bars=components.bars_read.result.resolved,
        evaluated_at=evaluated_at,
        requested_scope=requested_scope,
        latest_available_trade_date=components.latest_intraday_trade_date,
    )
    return USMarketTruthBundle(snapshot=snapshot, series=series)


__all__ = [
    "USMarketTruthBundle",
    "read_us_intraday_series_projection",
    "read_us_market_truth_bundle",
    "read_us_market_truth_snapshot",
]
