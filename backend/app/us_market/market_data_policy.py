"""Market-owned provider descriptors for bounded US acquisition planning.

This module declares provider capabilities only. It performs no provider I/O,
health probing, fallback, persistence, or final evidence selection.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.market_data.contracts import Market, MarketSession, ProviderResourceHealth
from app.market_data.policies import DataRequirement
from app.market_data.provider_policy import (
    AcquisitionPlan,
    ProviderDescriptor,
    plan_acquisition,
)
from app.market_data.provider_catalog import AcquisitionMode
from app.us_market.market_data.descriptors import (
    US_DAILY_CANDIDATE_DESCRIPTORS,
    US_DAILY_PROVIDER_DESCRIPTORS,
)


US_PROVIDER_DESCRIPTORS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        provider_key="yahoo_chart",
        market=Market.US,
        capabilities=("quote.snapshot", "intraday.bars"),
        priority=100,
        supported_sessions=(
            MarketSession.PRE_OPEN,
            MarketSession.CONTINUOUS,
            MarketSession.CLOSING_AUCTION,
            MarketSession.POST_CLOSE,
            MarketSession.CLOSED,
        ),
        supports_external_fetch=True,
        can_produce_live=False,
        max_timeout_seconds=25,
    ),
)


def _provider_descriptors(
    capability_id: str,
    *,
    include_daily_candidates: bool = True,
) -> tuple[ProviderDescriptor, ...]:
    """Project the canonical V2 Daily catalog into the legacy policy shape.

    Quote/intraday callers still use the legacy policy contract. Daily priority
    and eligibility are owned only by ``US_DAILY_PROVIDER_DESCRIPTORS``.
    """

    if capability_id != "daily.ohlcv":
        return tuple(
            item for item in US_PROVIDER_DESCRIPTORS
            if capability_id in item.capabilities
        )
    daily_descriptors = (
        US_DAILY_CANDIDATE_DESCRIPTORS
        if include_daily_candidates
        else US_DAILY_PROVIDER_DESCRIPTORS
    )
    return tuple(
        ProviderDescriptor(
            provider_key=item.provider_key,
            market=item.market,
            capabilities=(item.capability_id,),
            priority=item.priority,
            supported_sessions=item.supported_sessions,
            supports_external_fetch=AcquisitionMode.FETCH in item.acquisition_modes,
            can_produce_live=item.can_produce_live,
            max_timeout_seconds=item.max_timeout_seconds,
        )
        for item in daily_descriptors
    )


def us_provider_priority(provider_key: str, capability_id: str) -> int:
    """Return the single market-owned priority for one provider capability."""

    normalized_provider = str(provider_key).strip().lower()
    for descriptor in _provider_descriptors(capability_id):
        if (
            descriptor.provider_key == normalized_provider
            and capability_id in descriptor.capabilities
        ):
            return descriptor.priority
    return 10_000


def us_provider_order(capability_id: str) -> tuple[str, ...]:
    return tuple(
        descriptor.provider_key
        for descriptor in sorted(
            (
                item
                for item in _provider_descriptors(capability_id)
            ),
            key=lambda item: (item.priority, item.provider_key),
        )
    )


def build_us_acquisition_plan(
    requirement: DataRequirement,
    provider_health: Mapping[str, ProviderResourceHealth] | None = None,
    *,
    max_provider_attempts: int = 2,
    overall_timeout_seconds: float = 30,
    max_external_calls: int = 2,
    fallback_allowed: bool = True,
) -> AcquisitionPlan:
    """Return a pure, bounded plan for one US requirement."""

    if requirement.instrument.market is not Market.US:
        raise ValueError("US acquisition planning requires a US instrument")
    return plan_acquisition(
        requirement,
        _provider_descriptors(
            requirement.capability_id,
            include_daily_candidates=False,
        ),
        provider_health,
        max_provider_attempts=max_provider_attempts,
        overall_timeout_seconds=overall_timeout_seconds,
        max_external_calls=max_external_calls,
        max_subscriptions=0,
        fallback_allowed=fallback_allowed,
    )


__all__ = [
    "US_PROVIDER_DESCRIPTORS",
    "build_us_acquisition_plan",
    "us_provider_order",
    "us_provider_priority",
]
