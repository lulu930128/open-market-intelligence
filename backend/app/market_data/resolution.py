"""Pure candidate resolution for provider-neutral market observations.

Callers acquire observations before invoking this module. The resolver imports
no provider, network, database, scheduler, AI, or presentation code and cannot
create subscriptions or other side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Generic, Sequence, TypeVar

from app.market_data.contracts import (
    AuthorityClass,
    AuctionObservation,
    BarFinalization,
    BarObservation,
    BarSeriesComposition,
    BarSeriesCompositionStatus,
    CandidateSummary,
    DepthObservation,
    EvidenceFreshness,
    MarketBreadthObservation,
    MarketIndexObservation,
    MarketSession,
    ObservationState,
    QuoteObservation,
    ResolvedBarSeries,
    ResolvedAuction,
    ResolvedDepth,
    ResolvedEvidenceHealth,
    ResolvedEvidenceStatus,
    ResolvedMarketBreadth,
    ResolvedMarketIndex,
    ResolvedQuote,
    ResolvedTradingStatus,
    TradingStatusObservation,
)
from app.market_data.errors import MarketDataContractError
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    BarSeriesResolutionMode,
    DataRequirementV2,
    FreshnessBasis,
    InstrumentTarget,
)
from app.market_data.policies import RealtimePolicy, parse_realtime_policy
from app.market_data.quality_policy import (
    QualityEvaluation,
    QualityReasonCode,
    combine_quality_evaluations,
    evaluate_candidate_quality,
)


ObservationT = TypeVar(
    "ObservationT",
    QuoteObservation,
    DepthObservation,
    AuctionObservation,
    MarketBreadthObservation,
    MarketIndexObservation,
    TradingStatusObservation,
)
MAX_CANDIDATE_SUMMARIES = 8
FUTURE_TOLERANCE = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class ResolutionCandidate(Generic[ObservationT]):
    observation: ObservationT
    freshness: EvidenceFreshness
    provider_priority: int = 100
    session: MarketSession = MarketSession.UNKNOWN
    quality: QualityEvaluation | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.provider_priority < 0:
            raise ValueError("provider_priority must be non-negative")


@dataclass(frozen=True, slots=True)
class BarSeriesCandidate:
    bars: tuple[BarObservation, ...]
    freshness: EvidenceFreshness
    provider_priority: int = 100
    session: MarketSession = MarketSession.UNKNOWN
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.bars:
            raise MarketDataContractError("bar series candidates require at least one bar")
        if self.provider_priority < 0:
            raise MarketDataContractError("provider_priority must be non-negative")
        instrument = self.bars[0].instrument
        interval = self.bars[0].interval
        if any(bar.instrument != instrument for bar in self.bars):
            raise MarketDataContractError("candidate bars must share one instrument key")
        if any(bar.interval != interval for bar in self.bars):
            raise MarketDataContractError("candidate bars must share one interval")
        provider = self.bars[0].lineage.provider
        source = self.bars[0].lineage.source
        authority = self.bars[0].lineage.authority
        if any(bar.lineage.provider != provider for bar in self.bars):
            raise MarketDataContractError("candidate bars must share one provider lineage")
        if any(bar.lineage.source != source for bar in self.bars):
            raise MarketDataContractError("candidate bars must share one source lineage")
        if any(bar.lineage.authority is not authority for bar in self.bars):
            raise MarketDataContractError("candidate bars must share one authority lineage")
        if any(
            current.start_at >= following.start_at
            for current, following in zip(self.bars, self.bars[1:])
        ):
            raise MarketDataContractError("candidate bars must be strictly ordered")


@dataclass(frozen=True, slots=True)
class _EvaluatedCandidate(Generic[ObservationT]):
    candidate: ResolutionCandidate[ObservationT]
    freshness: EvidenceFreshness
    eligible: bool
    reason_code: str
    quality: QualityEvaluation | None = None


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _observation_time(observation: ObservationT) -> datetime | None:
    lineage = observation.lineage
    return lineage.event_at or lineage.received_at or lineage.fetched_at


def _effective_freshness(
    freshness: EvidenceFreshness,
    *,
    observed_at: datetime | None,
    now: datetime,
    max_age: timedelta,
    completed_session: bool,
) -> tuple[EvidenceFreshness, str | None]:
    if observed_at is not None and observed_at > now + FUTURE_TOLERANCE:
        return EvidenceFreshness.UNKNOWN, "FUTURE_TIMESTAMP"
    if (
        not completed_session
        and observed_at is not None
        and freshness in {EvidenceFreshness.LIVE, EvidenceFreshness.FRESH}
        and now - observed_at > max_age
    ):
        return EvidenceFreshness.STALE, None
    return freshness, None


def _evaluate(
    candidate: ResolutionCandidate[ObservationT],
    *,
    policy: RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2 | None = None,
) -> _EvaluatedCandidate[ObservationT]:
    observation = candidate.observation
    quality = candidate.quality
    if quality is None and requirement is not None:
        quality = evaluate_candidate_quality(
            observation,
            requirement=requirement,
            freshness=candidate.freshness,
            now=now,
        )
    if quality is not None and candidate.limitations:
        quality = quality.model_copy(
            update={
                "limitations": tuple(
                    dict.fromkeys((*quality.limitations, *candidate.limitations))
                )
            }
        )
    if quality is not None and not quality.eligible:
        return _EvaluatedCandidate(
            candidate,
            candidate.freshness,
            False,
            quality.reason_code.value,
            quality,
        )
    observed_at = _observation_time(observation)
    freshness, temporal_rejection = _effective_freshness(
        candidate.freshness,
        observed_at=observed_at,
        now=now,
        max_age=max_age,
        completed_session=(
            policy is RealtimePolicy.COMPLETED_SESSION
            or (
                requirement is not None
                and requirement.freshness.basis
                is FreshnessBasis.COMPLETED_SESSION_DATE
            )
        ),
    )
    if temporal_rejection:
        return _EvaluatedCandidate(
            candidate, freshness, False, temporal_rejection, quality
        )
    state = getattr(observation, "state", ObservationState.AVAILABLE)
    if state is ObservationState.MISSING:
        return _EvaluatedCandidate(
            candidate, freshness, False, "OBSERVATION_MISSING", quality
        )
    if policy is RealtimePolicy.CACHE_ONLY:
        is_cache = (
            observation.lineage.cache_hit
            or observation.lineage.authority is AuthorityClass.CACHE
        )
        if not is_cache:
            return _EvaluatedCandidate(
                candidate, freshness, False, "NOT_CACHE_EVIDENCE", quality
            )
    elif policy is RealtimePolicy.REQUIRE_LIVE:
        if freshness is not EvidenceFreshness.LIVE:
            return _EvaluatedCandidate(
                candidate, freshness, False, "LIVE_REQUIRED", quality
            )
    elif policy is RealtimePolicy.COMPLETED_SESSION:
        if candidate.session not in {MarketSession.POST_CLOSE, MarketSession.CLOSED}:
            return _EvaluatedCandidate(
                candidate, freshness, False, "SESSION_NOT_COMPLETED", quality
            )
    if freshness in {
        EvidenceFreshness.MISSING,
        EvidenceFreshness.NOT_APPLICABLE,
        EvidenceFreshness.UNKNOWN,
    }:
        return _EvaluatedCandidate(
            candidate, freshness, False, "FRESHNESS_UNUSABLE", quality
        )
    reason_code = (
        quality.reason_code.value
        if quality is not None
        and quality.reason_code is not QualityReasonCode.ELIGIBLE
        else "ELIGIBLE"
    )
    return _EvaluatedCandidate(candidate, freshness, True, reason_code, quality)


def _freshness_rank(value: EvidenceFreshness) -> int:
    return {
        EvidenceFreshness.LIVE: 0,
        EvidenceFreshness.FRESH: 1,
        EvidenceFreshness.STALE: 2,
        EvidenceFreshness.NOT_APPLICABLE: 3,
        EvidenceFreshness.MISSING: 4,
        EvidenceFreshness.UNKNOWN: 5,
    }[value]


def _summaries(
    evaluated: Sequence[_EvaluatedCandidate[ObservationT]],
) -> tuple[CandidateSummary, ...]:
    summaries: list[CandidateSummary] = []
    for item in evaluated[:MAX_CANDIDATE_SUMMARIES]:
        lineage = item.candidate.observation.lineage
        summaries.append(
            CandidateSummary(
                provider=lineage.provider,
                source=lineage.source,
                freshness=item.freshness,
                authority=lineage.authority,
                session=item.candidate.session,
                event_at=_observation_time(item.candidate.observation),
                eligible=item.eligible,
                reason_code=item.reason_code,
            )
        )
    return tuple(summaries)


def _resolve(
    candidates: Sequence[ResolutionCandidate[ObservationT]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    official_first: bool = False,
    requirement: DataRequirementV2 | None = None,
) -> tuple[
    ObservationT | None,
    ResolvedEvidenceHealth,
    tuple[CandidateSummary, ...],
]:
    _require_aware(now, "now")
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")
    parsed_policy = parse_realtime_policy(policy, allow_internal=True)
    evaluated = [
        _evaluate(
            candidate,
            policy=parsed_policy,
            now=now,
            max_age=max_age,
            requirement=requirement,
        )
        for candidate in candidates
    ]
    eligible = [item for item in evaluated if item.eligible]

    def rank(item: _EvaluatedCandidate[ObservationT]) -> tuple[int, int, int, int]:
        currentness_rank = 0
        official_rank = 0
        if official_first:
            currentness_rank = (
                0
                if item.freshness
                in {EvidenceFreshness.LIVE, EvidenceFreshness.FRESH}
                else 1
            )
            official_rank = 0 if getattr(item.candidate.observation, "official", False) else 1
        return (
            currentness_rank,
            official_rank,
            _freshness_rank(item.freshness),
            item.candidate.provider_priority,
        )

    eligible.sort(key=rank)
    selected_item = eligible[0] if eligible else None
    summaries = _summaries(evaluated)
    if selected_item is None:
        policy_unsatisfied = parsed_policy in {
            RealtimePolicy.CACHE_ONLY,
            RealtimePolicy.REQUIRE_LIVE,
            RealtimePolicy.COMPLETED_SESSION,
        }
        quality_limitations = tuple(
            dict.fromkeys(
                limitation
                for item in evaluated
                if item.quality is not None
                for limitation in item.quality.limitations
            )
        )
        quality_missing_fields = tuple(
            dict.fromkeys(
                field
                for item in evaluated
                if item.quality is not None
                for field in item.quality.missing_fields
            )
        )
        health = ResolvedEvidenceHealth(
            status=(
                ResolvedEvidenceStatus.POLICY_UNSATISFIED
                if policy_unsatisfied
                else ResolvedEvidenceStatus.MISSING
            ),
            selection_reason=(
                f"{parsed_policy.value.upper()}_NO_ELIGIBLE_CANDIDATE"
            ),
            missing_fields=quality_missing_fields,
            facts_usable=False,
            research_usable=False,
            limitations=tuple(
                dict.fromkeys(
                    (
                        "No candidate satisfied the requested data policy.",
                        *quality_limitations,
                    )
                )
            ),
        )
        return None, health, summaries

    selected = selected_item.candidate.observation
    lineage = selected.lineage
    lower_priority_present = any(
        item.candidate.provider_priority < selected_item.candidate.provider_priority
        for item in evaluated
    )
    state = getattr(selected, "state", ObservationState.AVAILABLE)
    selected_quality = selected_item.quality
    if selected_item.freshness is EvidenceFreshness.STALE:
        status = ResolvedEvidenceStatus.STALE
    elif state is ObservationState.PARTIAL:
        status = ResolvedEvidenceStatus.PARTIAL
    elif lower_priority_present:
        status = ResolvedEvidenceStatus.FALLBACK
    else:
        status = ResolvedEvidenceStatus.SELECTED
    health = ResolvedEvidenceHealth(
        status=status,
        selected_provider=lineage.provider,
        selected_source=lineage.source,
        selected_session=selected_item.candidate.session,
        selected_event_at=_observation_time(selected),
        fallback_used=lower_priority_present,
        selection_reason=(
            f"{parsed_policy.value.upper()}_{status.value.upper()}"
        ),
        missing_fields=(
            selected_quality.missing_fields if selected_quality is not None else ()
        ),
        facts_usable=(
            selected_quality.facts_usable if selected_quality is not None else True
        ),
        research_usable=(
            status
            in {
                ResolvedEvidenceStatus.SELECTED,
                ResolvedEvidenceStatus.FALLBACK,
            }
            and (
                selected_quality.research_usable
                if selected_quality is not None
                else True
            )
        ),
        limitations=tuple(
            dict.fromkeys(
                (
                    *(
                        (
                            "Selected evidence is stale and must not be presented as current.",
                        )
                        if status is ResolvedEvidenceStatus.STALE
                        else ()
                    ),
                    *(
                        ("Selected evidence is partial.",)
                        if status is ResolvedEvidenceStatus.PARTIAL
                        else ()
                    ),
                    *(
                        selected_quality.limitations
                        if selected_quality is not None
                        else ()
                    ),
                )
            )
        ),
    )
    return selected, health, summaries


def resolve_quote(
    candidates: Sequence[ResolutionCandidate[QuoteObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2 | None = None,
) -> ResolvedQuote:
    selected, health, summaries = _resolve(
        candidates,
        policy=policy,
        now=now,
        max_age=max_age,
        requirement=requirement,
    )
    return ResolvedQuote(quote=selected, health=health, candidates=summaries)


def resolve_depth(
    candidates: Sequence[ResolutionCandidate[DepthObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2 | None = None,
) -> ResolvedDepth:
    selected, health, summaries = _resolve(
        candidates,
        policy=policy,
        now=now,
        max_age=max_age,
        requirement=requirement,
    )
    return ResolvedDepth(depth=selected, health=health, candidates=summaries)


def resolve_auction(
    candidates: Sequence[ResolutionCandidate[AuctionObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2 | None = None,
) -> ResolvedAuction:
    selected, health, summaries = _resolve(
        candidates,
        policy=policy,
        now=now,
        max_age=max_age,
        requirement=requirement,
    )
    return ResolvedAuction(auction=selected, health=health, candidates=summaries)


def resolve_market_breadth(
    candidates: Sequence[ResolutionCandidate[MarketBreadthObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2 | None = None,
) -> ResolvedMarketBreadth:
    selected, health, summaries = _resolve(
        candidates,
        policy=policy,
        now=now,
        max_age=max_age,
        official_first=True,
        requirement=requirement,
    )
    return ResolvedMarketBreadth(
        breadth=selected,
        health=health,
        candidates=summaries,
    )


def resolve_market_index(
    candidates: Sequence[ResolutionCandidate[MarketIndexObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2 | None = None,
    official_first: bool = True,
) -> ResolvedMarketIndex:
    selected, health, summaries = _resolve(
        candidates,
        policy=policy,
        now=now,
        max_age=max_age,
        official_first=official_first,
        requirement=requirement,
    )
    return ResolvedMarketIndex(
        market_index=selected,
        health=health,
        candidates=summaries,
    )


def resolve_trading_status(
    candidates: Sequence[ResolutionCandidate[TradingStatusObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2 | None = None,
) -> ResolvedTradingStatus:
    parsed_policy = parse_realtime_policy(policy, allow_internal=True)
    selected, health, summaries = _resolve(
        candidates,
        policy=parsed_policy,
        now=now,
        max_age=max_age,
        official_first=True,
        requirement=requirement,
    )
    if selected is not None:
        evaluated = [
            _evaluate(
                candidate,
                policy=parsed_policy,
                now=now,
                max_age=max_age,
                requirement=requirement,
            )
            for candidate in candidates
        ]
        conflicting = [
            item
            for item in evaluated
            if item.eligible
            and item.candidate.observation is not selected
            and item.candidate.observation.status is not selected.status
        ]
        if conflicting:
            if selected.official:
                health = health.model_copy(
                    update={
                        "selection_reason": (
                            f"{parsed_policy.value.upper()}_OFFICIAL_CONFLICT"
                        ),
                        "limitations": (
                            *health.limitations,
                            "Current official trading status conflicts with another eligible candidate.",
                        ),
                    }
                )
            else:
                health = health.model_copy(
                    update={
                        "status": ResolvedEvidenceStatus.PARTIAL,
                        "selection_reason": (
                            f"{parsed_policy.value.upper()}_PARTIAL_CONFLICT"
                        ),
                        "facts_usable": True,
                        "research_usable": False,
                        "limitations": (
                            "Current non-official trading status conflicts with other evidence; do not present it as authoritative.",
                        ),
                    }
                )
    return ResolvedTradingStatus(
        trading_status=selected,
        health=health,
        candidates=summaries,
    )


def _bar_material_signature(bar: BarObservation) -> tuple[object, ...]:
    volume = (
        (bar.volume.value, bar.volume.unit.value)
        if bar.volume is not None
        else None
    )
    return (
        bar.open_price,
        bar.high_price,
        bar.low_price,
        bar.close_price,
        volume,
        bar.volume_status,
        bar.turnover_value,
        bar.turnover_currency,
        bar.trade_count,
        bar.price_change,
        bar.price_basis,
        bar.finalization,
    )


def _bar_candidate_rank(candidate: BarSeriesCandidate) -> tuple[int, str, str]:
    lineage = candidate.bars[0].lineage
    return candidate.provider_priority, lineage.provider, lineage.source


def _bar_candidate_summaries(
    candidates: Sequence[BarSeriesCandidate],
    *,
    policy: RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2,
) -> tuple[CandidateSummary, ...]:
    summaries: list[CandidateSummary] = []
    for candidate in candidates[:MAX_CANDIDATE_SUMMARIES]:
        latest = candidate.bars[-1]
        quality = evaluate_candidate_quality(
            latest,
            requirement=requirement,
            freshness=candidate.freshness,
            now=now,
        )
        evaluated = _evaluate(
            ResolutionCandidate(
                observation=latest,
                freshness=candidate.freshness,
                provider_priority=candidate.provider_priority,
                session=candidate.session,
                quality=quality,
            ),
            policy=policy,
            now=now,
            max_age=max_age,
        )
        eligible = evaluated.eligible
        reason_code = evaluated.reason_code
        if policy is RealtimePolicy.COMPLETED_SESSION and latest.finalization not in {
            BarFinalization.FINAL,
            BarFinalization.CORRECTED,
        }:
            eligible = False
            reason_code = "BAR_NOT_FINALIZED"
        summaries.append(
            CandidateSummary(
                provider=latest.lineage.provider,
                source=latest.lineage.source,
                freshness=evaluated.freshness,
                authority=latest.lineage.authority,
                session=candidate.session,
                event_at=_observation_time(latest),
                eligible=eligible,
                reason_code=reason_code,
            )
        )
    return tuple(summaries)


def _resolve_composed_bar_series(
    candidates: Sequence[BarSeriesCandidate],
    *,
    policy: RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2,
) -> ResolvedBarSeries:
    if policy is not RealtimePolicy.COMPLETED_SESSION:
        raise MarketDataContractError(
            "timestamp bar-series composition requires completed_session policy"
        )
    if not isinstance(requirement.target, InstrumentTarget) or not isinstance(
        requirement.request, BarCapabilityRequest
    ):
        raise MarketDataContractError(
            "timestamp bar-series composition requires an instrument bar request"
        )

    summaries = _bar_candidate_summaries(
        candidates,
        policy=policy,
        now=now,
        max_age=max_age,
        requirement=requirement,
    )
    eligible_by_bucket: dict[
        tuple[object, str, datetime, datetime],
        list[tuple[tuple[int, str, str], BarSeriesCandidate, BarObservation]],
    ] = {}
    rejected_quality: list[QualityEvaluation] = []
    for candidate in candidates:
        if candidate.session not in {MarketSession.POST_CLOSE, MarketSession.CLOSED}:
            continue
        rank = _bar_candidate_rank(candidate)
        for bar in candidate.bars:
            if bar.instrument != requirement.target.instrument:
                raise MarketDataContractError(
                    "candidate bar instrument does not match the requested instrument"
                )
            if bar.interval != requirement.request.interval:
                raise MarketDataContractError(
                    "candidate bar interval does not match the requested interval"
                )
            if bar.finalization not in {
                BarFinalization.FINAL,
                BarFinalization.CORRECTED,
            }:
                continue
            quality = evaluate_candidate_quality(
                bar,
                requirement=requirement,
                freshness=None,
                now=now,
            )
            if not quality.eligible:
                rejected_quality.append(quality)
                continue
            key = (bar.instrument, bar.interval, bar.start_at, bar.end_at)
            eligible_by_bucket.setdefault(key, []).append((rank, candidate, bar))

    if not eligible_by_bucket:
        missing_fields = tuple(
            dict.fromkeys(
                field
                for quality in rejected_quality
                for field in quality.missing_fields
            )
        )
        limitations = tuple(
            dict.fromkeys(
                limitation
                for quality in rejected_quality
                for limitation in quality.limitations
            )
        )
        return ResolvedBarSeries(
            health=ResolvedEvidenceHealth(
                status=ResolvedEvidenceStatus.POLICY_UNSATISFIED,
                selection_reason="COMPLETED_SESSION_COMPOSITION_NO_ELIGIBLE_BAR",
                missing_fields=missing_fields,
                facts_usable=False,
                research_usable=False,
                limitations=(
                    "No bar satisfied the completed-session composition policy.",
                    *limitations,
                ),
            ),
            candidates=summaries,
            composition=BarSeriesComposition(
                applied=True,
                status=BarSeriesCompositionStatus.NO_ELIGIBLE_BARS,
                limitations=("BAR_SERIES_COMPOSITION_NO_ELIGIBLE_BAR",),
            ),
        )

    retained_keys = tuple(
        sorted(
            eligible_by_bucket,
            key=lambda key: (key[2], key[3]),
        )[-requirement.request.max_bars :]
    )
    retained_candidate_ids = {
        id(candidate)
        for key in retained_keys
        for _, candidate, _ in eligible_by_bucket[key]
    }
    primary_candidate = min(
        (
            candidate
            for candidate in candidates
            if id(candidate) in retained_candidate_ids
        ),
        key=_bar_candidate_rank,
    )
    primary_id = id(primary_candidate)

    selected_entries: list[
        tuple[tuple[int, str, str], BarSeriesCandidate, BarObservation]
    ] = []
    filled_bucket_count = 0
    conflict_bucket_count = 0
    for key in retained_keys:
        entries = sorted(eligible_by_bucket[key], key=lambda item: item[0])
        winner = entries[0]
        selected_entries.append(winner)
        if id(winner[1]) != primary_id and not any(
            id(candidate) == primary_id for _, candidate, _ in entries
        ):
            filled_bucket_count += 1
        winner_signature = _bar_material_signature(winner[2])
        if any(
            _bar_material_signature(bar) != winner_signature
            for _, _, bar in entries[1:]
        ):
            conflict_bucket_count += 1

    bars = tuple(entry[2] for entry in selected_entries)
    latest = bars[-1]
    composite_freshness = (
        EvidenceFreshness.FRESH
        if latest.end_at >= requirement.request.end_at
        else EvidenceFreshness.STALE
    )
    selected_quality = combine_quality_evaluations(
        tuple(
            evaluate_candidate_quality(
                bar,
                requirement=requirement,
                freshness=(composite_freshness if bar is latest else None),
                now=now,
            )
            for bar in bars
        )
    )
    selected_candidate_ids = tuple(
        dict.fromkeys(id(candidate) for _, candidate, _ in selected_entries)
    )
    selected_candidates = tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if id(candidate) in selected_candidate_ids
            ),
            key=_bar_candidate_rank,
        )
    )
    contributing_providers = tuple(
        dict.fromkeys(candidate.bars[0].lineage.provider for candidate in selected_candidates)
    )
    contributing_sources = tuple(
        dict.fromkeys(candidate.bars[0].lineage.source for candidate in selected_candidates)
    )
    composition_limitations: list[str] = []
    if len(selected_candidates) > 1:
        composition_limitations.append(
            "BAR_SERIES_COMPOSED_FROM_MULTIPLE_CANDIDATES"
        )
    if conflict_bucket_count:
        composition_limitations.append(
            "BAR_SERIES_SAME_TIMESTAMP_CONFLICT_RESOLVED"
        )
    if conflict_bucket_count:
        composition_status = BarSeriesCompositionStatus.COMPOSED_WITH_CONFLICTS
    elif len(selected_candidates) > 1:
        composition_status = BarSeriesCompositionStatus.COMPOSED
    else:
        composition_status = BarSeriesCompositionStatus.SINGLE_CONTRIBUTOR

    state = getattr(latest, "state", ObservationState.AVAILABLE)
    if composite_freshness is EvidenceFreshness.STALE:
        status = ResolvedEvidenceStatus.STALE
    elif state is ObservationState.PARTIAL:
        status = ResolvedEvidenceStatus.PARTIAL
    else:
        status = ResolvedEvidenceStatus.SELECTED
    unique_contributor = selected_candidates[0] if len(selected_candidates) == 1 else None
    unique_lineage = unique_contributor.bars[0].lineage if unique_contributor else None
    health_limitations = tuple(
        dict.fromkeys(
            (
                *(
                    (
                        "Resolved bar series is stale and must not be presented as current.",
                    )
                    if status is ResolvedEvidenceStatus.STALE
                    else ()
                ),
                *selected_quality.limitations,
            )
        )
    )
    return ResolvedBarSeries(
        bars=bars,
        health=ResolvedEvidenceHealth(
            status=status,
            selected_provider=(unique_lineage.provider if unique_lineage else None),
            selected_source=(unique_lineage.source if unique_lineage else None),
            selected_session=MarketSession.CLOSED,
            selected_event_at=_observation_time(latest),
            fallback_used=False,
            selection_reason=(
                "COMPLETED_SESSION_COMPOSED_WITH_CONFLICTS"
                if conflict_bucket_count
                else (
                    "COMPLETED_SESSION_COMPOSED_BY_TIMESTAMP"
                    if len(selected_candidates) > 1
                    else "COMPLETED_SESSION_SINGLE_CONTRIBUTOR"
                )
            ),
            missing_fields=selected_quality.missing_fields,
            facts_usable=selected_quality.facts_usable,
            research_usable=(
                status is ResolvedEvidenceStatus.SELECTED
                and selected_quality.research_usable
            ),
            limitations=health_limitations,
        ),
        candidates=summaries,
        composition=BarSeriesComposition(
            applied=True,
            status=composition_status,
            contributing_providers=contributing_providers,
            contributing_sources=contributing_sources,
            filled_bucket_count=filled_bucket_count,
            conflict_bucket_count=conflict_bucket_count,
            limitations=tuple(composition_limitations),
        ),
    )


def resolve_bar_series(
    candidates: Sequence[BarSeriesCandidate],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
    requirement: DataRequirementV2 | None = None,
) -> ResolvedBarSeries:
    parsed_policy = parse_realtime_policy(policy, allow_internal=True)
    if (
        requirement is not None
        and isinstance(requirement.request, BarCapabilityRequest)
        and requirement.request.series_resolution
        is BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP
    ):
        return _resolve_composed_bar_series(
            candidates,
            policy=parsed_policy,
            now=now,
            max_age=max_age,
            requirement=requirement,
        )
    projected: list[ResolutionCandidate[BarObservation]] = []
    series_by_identity: dict[int, tuple[BarObservation, ...]] = {}
    for candidate in candidates:
        latest = candidate.bars[-1]
        if parsed_policy is RealtimePolicy.COMPLETED_SESSION and any(
            bar.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED}
            for bar in candidate.bars
        ):
            continue
        quality: QualityEvaluation | None = None
        if requirement is not None:
            quality = combine_quality_evaluations(
                tuple(
                    evaluate_candidate_quality(
                        bar,
                        requirement=requirement,
                        freshness=(candidate.freshness if bar is latest else None),
                        now=now,
                    )
                    for bar in candidate.bars
                )
            )
            if (
                isinstance(requirement.request, BarCapabilityRequest)
                and requirement.request.coverage is not None
                and len(candidate.bars)
                < requirement.request.coverage.minimum_bar_count
            ):
                quality = QualityEvaluation(
                    eligible=False,
                    reason_code=QualityReasonCode.BAR_COVERAGE_INSUFFICIENT,
                    reason_codes=(QualityReasonCode.BAR_COVERAGE_INSUFFICIENT,),
                    facts_usable=True,
                    research_usable=False,
                    limitations=(
                        "Candidate bar series does not satisfy the explicit minimum history depth.",
                    ),
                )
        projected_candidate = ResolutionCandidate(
            observation=latest,
            freshness=candidate.freshness,
            provider_priority=candidate.provider_priority,
            session=candidate.session,
            quality=quality,
            limitations=candidate.limitations,
        )
        projected.append(projected_candidate)
        series_by_identity[id(latest)] = candidate.bars
    selected, health, summaries = _resolve(
        projected,
        policy=parsed_policy,
        now=now,
        max_age=max_age,
        # Each bar was already evaluated above so the series can carry one
        # combined quality result without evaluating the latest bar twice.
        requirement=None,
    )
    bars = series_by_identity.get(id(selected), ()) if selected is not None else ()
    return ResolvedBarSeries(bars=bars, health=health, candidates=summaries)


__all__ = [
    "BarSeriesCandidate",
    "MAX_CANDIDATE_SUMMARIES",
    "ResolutionCandidate",
    "resolve_auction",
    "resolve_bar_series",
    "resolve_depth",
    "resolve_market_breadth",
    "resolve_market_index",
    "resolve_quote",
    "resolve_trading_status",
]
