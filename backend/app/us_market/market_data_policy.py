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


US_PROVIDER_DESCRIPTORS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        provider_key="yahoo_chart",
        market=Market.US,
        capabilities=("quote.snapshot", "intraday.bars", "daily.ohlcv"),
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
    ProviderDescriptor(
        provider_key="alphavantage",
        market=Market.US,
        capabilities=("daily.ohlcv",),
        priority=110,
        supported_sessions=(MarketSession.CLOSED,),
        supports_external_fetch=True,
        can_produce_live=False,
        max_timeout_seconds=30,
    ),
)


def us_provider_priority(provider_key: str, capability_id: str) -> int:
    """Return the single market-owned priority for one provider capability."""

    normalized_provider = str(provider_key).strip().lower()
    for descriptor in US_PROVIDER_DESCRIPTORS:
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
                for item in US_PROVIDER_DESCRIPTORS
                if capability_id in item.capabilities
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
        US_PROVIDER_DESCRIPTORS,
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
