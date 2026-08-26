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
from app.market_data.policies import RealtimePolicy, parse_realtime_policy


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

    def __post_init__(self) -> None:
        if self.provider_priority < 0:
            raise ValueError("provider_priority must be non-negative")


@dataclass(frozen=True, slots=True)
class BarSeriesCandidate:
    bars: tuple[BarObservation, ...]
    freshness: EvidenceFreshness
    provider_priority: int = 100
    session: MarketSession = MarketSession.UNKNOWN

    def __post_init__(self) -> None:
        if not self.bars:
            raise ValueError("bar series candidates require at least one bar")
        if self.provider_priority < 0:
            raise ValueError("provider_priority must be non-negative")
        instrument = self.bars[0].instrument
        interval = self.bars[0].interval
        if any(bar.instrument != instrument for bar in self.bars):
            raise ValueError("candidate bars must share one instrument key")
        if any(bar.interval != interval for bar in self.bars):
            raise ValueError("candidate bars must share one interval")
        if any(
            current.start_at >= following.start_at
            for current, following in zip(self.bars, self.bars[1:])
        ):
            raise ValueError("candidate bars must be strictly ordered")


@dataclass(frozen=True, slots=True)
class _EvaluatedCandidate(Generic[ObservationT]):
    candidate: ResolutionCandidate[ObservationT]
    freshness: EvidenceFreshness
    eligible: bool
    reason_code: str


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
) -> _EvaluatedCandidate[ObservationT]:
    observation = candidate.observation
    observed_at = _observation_time(observation)
    freshness, temporal_rejection = _effective_freshness(
        candidate.freshness,
        observed_at=observed_at,
        now=now,
        max_age=max_age,
        completed_session=policy is RealtimePolicy.COMPLETED_SESSION,
    )
    if temporal_rejection:
        return _EvaluatedCandidate(candidate, freshness, False, temporal_rejection)
    state = getattr(observation, "state", ObservationState.AVAILABLE)
    if state is ObservationState.MISSING:
        return _EvaluatedCandidate(candidate, freshness, False, "OBSERVATION_MISSING")
    if policy is RealtimePolicy.CACHE_ONLY:
        is_cache = (
            observation.lineage.cache_hit
            or observation.lineage.authority is AuthorityClass.CACHE
        )
        if not is_cache:
            return _EvaluatedCandidate(candidate, freshness, False, "NOT_CACHE_EVIDENCE")
    elif policy is RealtimePolicy.REQUIRE_LIVE:
        if freshness is not EvidenceFreshness.LIVE:
            return _EvaluatedCandidate(candidate, freshness, False, "LIVE_REQUIRED")
    elif policy is RealtimePolicy.COMPLETED_SESSION:
        if candidate.session not in {MarketSession.POST_CLOSE, MarketSession.CLOSED}:
            return _EvaluatedCandidate(
                candidate, freshness, False, "SESSION_NOT_COMPLETED"
            )
    if freshness in {
        EvidenceFreshness.MISSING,
        EvidenceFreshness.NOT_APPLICABLE,
        EvidenceFreshness.UNKNOWN,
    }:
        return _EvaluatedCandidate(candidate, freshness, False, "FRESHNESS_UNUSABLE")
    return _EvaluatedCandidate(candidate, freshness, True, "ELIGIBLE")


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
        _evaluate(candidate, policy=parsed_policy, now=now, max_age=max_age)
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
        health = ResolvedEvidenceHealth(
            status=(
                ResolvedEvidenceStatus.POLICY_UNSATISFIED
                if policy_unsatisfied
                else ResolvedEvidenceStatus.MISSING
            ),
            selection_reason=(
                f"{parsed_policy.value.upper()}_NO_ELIGIBLE_CANDIDATE"
            ),
            facts_usable=False,
            research_usable=False,
            limitations=("No candidate satisfied the requested data policy.",),
        )
        return None, health, summaries

    selected = selected_item.candidate.observation
    lineage = selected.lineage
    lower_priority_present = any(
        item.candidate.provider_priority < selected_item.candidate.provider_priority
        for item in evaluated
    )
    state = getattr(selected, "state", ObservationState.AVAILABLE)
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
        facts_usable=True,
        research_usable=status in {
            ResolvedEvidenceStatus.SELECTED,
            ResolvedEvidenceStatus.FALLBACK,
        },
        limitations=(
            ("Selected evidence is stale and must not be presented as current.",)
            if status is ResolvedEvidenceStatus.STALE
            else ("Selected evidence is partial.",)
            if status is ResolvedEvidenceStatus.PARTIAL
            else ()
        ),
    )
    return selected, health, summaries


def resolve_quote(
    candidates: Sequence[ResolutionCandidate[QuoteObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
) -> ResolvedQuote:
    selected, health, summaries = _resolve(
        candidates, policy=policy, now=now, max_age=max_age
    )
    return ResolvedQuote(quote=selected, health=health, candidates=summaries)


def resolve_depth(
    candidates: Sequence[ResolutionCandidate[DepthObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
) -> ResolvedDepth:
    selected, health, summaries = _resolve(
        candidates, policy=policy, now=now, max_age=max_age
    )
    return ResolvedDepth(depth=selected, health=health, candidates=summaries)


def resolve_auction(
    candidates: Sequence[ResolutionCandidate[AuctionObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
) -> ResolvedAuction:
    selected, health, summaries = _resolve(
        candidates, policy=policy, now=now, max_age=max_age
    )
    return ResolvedAuction(auction=selected, health=health, candidates=summaries)


def resolve_market_breadth(
    candidates: Sequence[ResolutionCandidate[MarketBreadthObservation]],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
) -> ResolvedMarketBreadth:
    selected, health, summaries = _resolve(
        candidates,
        policy=policy,
        now=now,
        max_age=max_age,
        official_first=True,
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
) -> ResolvedMarketIndex:
    selected, health, summaries = _resolve(
        candidates,
        policy=policy,
        now=now,
        max_age=max_age,
        official_first=True,
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
) -> ResolvedTradingStatus:
    parsed_policy = parse_realtime_policy(policy, allow_internal=True)
    selected, health, summaries = _resolve(
        candidates,
        policy=parsed_policy,
        now=now,
        max_age=max_age,
        official_first=True,
    )
    if selected is not None:
        evaluated = [
            _evaluate(
                candidate,
                policy=parsed_policy,
                now=now,
                max_age=max_age,
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


def resolve_bar_series(
    candidates: Sequence[BarSeriesCandidate],
    *,
    policy: str | RealtimePolicy,
    now: datetime,
    max_age: timedelta,
) -> ResolvedBarSeries:
    parsed_policy = parse_realtime_policy(policy, allow_internal=True)
    projected: list[ResolutionCandidate[BarObservation]] = []
    series_by_identity: dict[int, tuple[BarObservation, ...]] = {}
    for candidate in candidates:
        latest = candidate.bars[-1]
        if parsed_policy is RealtimePolicy.COMPLETED_SESSION and any(
            bar.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED}
            for bar in candidate.bars
        ):
            continue
        projected_candidate = ResolutionCandidate(
            observation=latest,
            freshness=candidate.freshness,
            provider_priority=candidate.provider_priority,
            session=candidate.session,
        )
        projected.append(projected_candidate)
        series_by_identity[id(latest)] = candidate.bars
    selected, health, summaries = _resolve(
        projected,
        policy=parsed_policy,
        now=now,
        max_age=max_age,
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
