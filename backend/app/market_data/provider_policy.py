"""Pure provider-routing policy for the dark market-data control plane.

The module is deliberately unwired. It performs no provider I/O and contains
no market-specific provider catalog. Callers inject provider descriptors and
resource-health evidence; later market-owned adapters may consume the plan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Annotated

from pydantic import Field, model_validator

from app.market_data.contracts import (
    CanonicalModel,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    Market,
    MarketSession,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.policies import (
    DataPurpose,
    DataRequirement,
    RealtimePolicy,
    allows_external_acquisition,
    allows_live_subscription,
)


SUPPORTED_CAPABILITIES_BY_MARKET = {
    Market.TW: frozenset({"quote.snapshot", "quote.order_book"}),
    Market.US: frozenset({"quote.snapshot", "intraday.bars", "daily.ohlcv"}),
}
SUPPORTED_02A_CAPABILITIES = frozenset(
    capability
    for capabilities in SUPPORTED_CAPABILITIES_BY_MARKET.values()
    for capability in capabilities
)
MAX_PROVIDER_DESCRIPTORS = 16

ProviderKey = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$"),
]
CapabilityId = Annotated[str, Field(min_length=1, max_length=128)]
ReasonCode = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"),
]


class ProviderDescriptor(CanonicalModel):
    """Injected provider capabilities; never a shared production catalog."""

    contract_version: str = "omi.market.provider_descriptor.v1"
    provider_key: ProviderKey
    market: Market
    capabilities: tuple[CapabilityId, ...] = Field(min_length=1, max_length=16)
    priority: int = Field(default=100, ge=0, le=10_000)
    supported_sessions: tuple[MarketSession, ...] = Field(default=(), max_length=8)
    supports_external_fetch: bool = False
    supports_live_subscription: bool = False
    can_produce_live: bool = False
    max_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    allow_unknown_health: bool = False
    allow_disconnected_connect: bool = False

    @model_validator(mode="after")
    def _validate_descriptor(self) -> ProviderDescriptor:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("provider capabilities must be unique")
        if len(set(self.supported_sessions)) != len(self.supported_sessions):
            raise ValueError("provider supported_sessions must be unique")
        if not (self.supports_external_fetch or self.supports_live_subscription):
            raise ValueError("provider must support fetch or subscription acquisition")
        if self.supports_live_subscription and not self.can_produce_live:
            raise ValueError("live subscriptions must be able to produce live evidence")
        return self


class AcquisitionBounds(CanonicalModel):
    contract_version: str = "omi.market.acquisition_bounds.v1"
    max_provider_attempts: int = Field(default=3, ge=1, le=8)
    overall_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    max_external_calls: int = Field(default=3, ge=0, le=20)
    max_subscriptions: int = Field(default=2, ge=0, le=8)


class ProviderRoute(CanonicalModel):
    contract_version: str = "omi.market.provider_route.v1"
    provider_key: ProviderKey
    market: Market
    capability_id: CapabilityId
    priority: int = Field(ge=0, le=10_000)
    external_fetch_allowed: bool
    subscription_allowed: bool
    route_timeout_seconds: float = Field(gt=0, le=60)
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _require_acquisition_method(self) -> ProviderRoute:
        if not (self.external_fetch_allowed or self.subscription_allowed):
            raise ValueError("provider route requires an acquisition method")
        return self


class ProviderSkip(CanonicalModel):
    contract_version: str = "omi.market.provider_skip.v1"
    provider_key: ProviderKey
    reason_code: ReasonCode


class AcquisitionPlan(CanonicalModel):
    contract_version: str = "omi.market.acquisition_plan.v1"
    requirement: DataRequirement
    routes: tuple[ProviderRoute, ...] = Field(default=(), max_length=8)
    skipped_providers: tuple[ProviderSkip, ...] = Field(default=(), max_length=16)
    bounds: AcquisitionBounds
    allow_external_acquisition: bool
    allow_live_subscription: bool
    fallback_allowed: bool
    acquisition_required: bool
    unfillable: bool
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def _validate_plan(self) -> AcquisitionPlan:
        if len(self.routes) > self.bounds.max_provider_attempts:
            raise ValueError("provider routes exceed max_provider_attempts")
        if not self.allow_external_acquisition and self.routes:
            raise ValueError("zero-I/O policy cannot contain provider routes")
        if not self.allow_live_subscription and any(
            route.subscription_allowed for route in self.routes
        ):
            raise ValueError("policy forbids live subscriptions")
        if self.unfillable and self.routes:
            raise ValueError("unfillable plan cannot contain provider routes")
        if self.acquisition_required and not self.routes and not self.unfillable:
            raise ValueError("required acquisition without routes must be unfillable")
        route_keys = [route.provider_key for route in self.routes]
        if len(route_keys) != len(set(route_keys)):
            raise ValueError("provider routes must be unique")
        return self


def _dedupe_codes(codes: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(codes))


def _health_decision(
    descriptor: ProviderDescriptor,
    requirement: DataRequirement,
    health: ProviderResourceHealth | None,
) -> tuple[str | None, tuple[str, ...]]:
    if health is None:
        if descriptor.allow_unknown_health:
            return None, ("HEALTH_UNKNOWN",)
        return "HEALTH_UNKNOWN", ()

    if (
        health.provider != descriptor.provider_key
        or health.market is not descriptor.market
        or health.capability != requirement.capability_id
    ):
        return "HEALTH_CONTRACT_MISMATCH", ()

    if health.enablement is EnablementStatus.DISABLED:
        return "PROVIDER_DISABLED", ()
    if health.entitlement is EntitlementStatus.AUTH_FAILED:
        return "AUTH_FAILED", ()
    if health.entitlement is EntitlementStatus.PLAN_RESTRICTED:
        return "PLAN_RESTRICTED", ()
    if health.operational is OperationalStatus.FAILED:
        return "OPERATIONAL_FAILED", ()
    if health.operational is OperationalStatus.RATE_LIMITED:
        return "RATE_LIMITED", ()
    if health.operational is OperationalStatus.UNAVAILABLE:
        return "UNAVAILABLE", ()
    if (
        health.connection is ConnectionStatus.DISCONNECTED
        and not descriptor.allow_disconnected_connect
    ):
        return "NOT_CONNECTED", ()

    unknown_dimension = any(
        (
            health.enablement is EnablementStatus.UNKNOWN,
            health.connection is ConnectionStatus.UNKNOWN,
            health.entitlement is EntitlementStatus.UNKNOWN,
            health.operational is OperationalStatus.UNKNOWN,
            health.freshness is EvidenceFreshness.UNKNOWN,
        )
    )
    if unknown_dimension and not descriptor.allow_unknown_health:
        return "HEALTH_UNKNOWN", ()

    limitations: list[str] = []
    if unknown_dimension:
        limitations.append("HEALTH_UNKNOWN")
    if health.connection is ConnectionStatus.DISCONNECTED:
        limitations.append("BOUNDED_CONNECT_REQUIRED")
    elif health.connection is ConnectionStatus.DEGRADED:
        limitations.append("CONNECTION_DEGRADED")
    if health.operational is OperationalStatus.DEGRADED:
        limitations.append("OPERATIONAL_DEGRADED")
    if health.freshness in {
        EvidenceFreshness.STALE,
        EvidenceFreshness.MISSING,
        EvidenceFreshness.NOT_APPLICABLE,
    }:
        limitations.append(f"PROVIDER_FRESHNESS_{health.freshness.value.upper()}")
    return None, _dedupe_codes(limitations)


def plan_acquisition(
    requirement: DataRequirement,
    descriptors: Iterable[ProviderDescriptor],
    provider_health: Mapping[str, ProviderResourceHealth] | None = None,
    *,
    max_provider_attempts: int = 3,
    overall_timeout_seconds: float = 10.0,
    max_external_calls: int = 3,
    max_subscriptions: int = 2,
    fallback_allowed: bool = True,
) -> AcquisitionPlan:
    """Build a bounded route plan without performing provider I/O."""

    bounds = AcquisitionBounds(
        max_provider_attempts=max_provider_attempts,
        overall_timeout_seconds=overall_timeout_seconds,
        max_external_calls=max_external_calls,
        max_subscriptions=max_subscriptions,
    )
    descriptor_list = tuple(descriptors)
    if len(descriptor_list) > MAX_PROVIDER_DESCRIPTORS:
        raise ValueError("provider descriptor count exceeds bounded policy input")
    descriptor_keys = [descriptor.provider_key for descriptor in descriptor_list]
    if len(descriptor_keys) != len(set(descriptor_keys)):
        raise ValueError("provider descriptors must use unique provider keys")

    health_by_provider = provider_health or {}
    external_allowed = allows_external_acquisition(requirement.realtime_policy)
    subscription_allowed = allows_live_subscription(requirement.realtime_policy)
    acquisition_required = external_allowed

    common = {
        "requirement": requirement,
        "bounds": bounds,
        "allow_external_acquisition": external_allowed,
        "allow_live_subscription": subscription_allowed,
        "fallback_allowed": fallback_allowed,
        "acquisition_required": acquisition_required,
    }

    if not acquisition_required:
        return AcquisitionPlan(
            **common,
            routes=(),
            skipped_providers=(),
            unfillable=False,
            limitations=("POLICY_NO_EXTERNAL_ACQUISITION",),
        )
    if requirement.purpose is not DataPurpose.RESEARCH:
        return AcquisitionPlan(
            **common,
            routes=(),
            skipped_providers=(),
            unfillable=True,
            limitations=("PURPOSE_NOT_SUPPORTED_02A",),
        )
    market_capabilities = SUPPORTED_CAPABILITIES_BY_MARKET.get(
        requirement.instrument.market
    )
    if market_capabilities is None:
        return AcquisitionPlan(
            **common,
            routes=(),
            skipped_providers=(),
            unfillable=True,
            limitations=("MARKET_NOT_SUPPORTED_02A",),
        )
    if requirement.capability_id not in market_capabilities:
        return AcquisitionPlan(
            **common,
            routes=(),
            skipped_providers=(),
            unfillable=True,
            limitations=("CAPABILITY_NOT_SUPPORTED_02A",),
        )

    eligible_routes: list[ProviderRoute] = []
    skipped: list[ProviderSkip] = []
    for descriptor in sorted(
        descriptor_list,
        key=lambda item: (item.priority, item.provider_key),
    ):
        if descriptor.market is not requirement.instrument.market:
            skipped.append(
                ProviderSkip(
                    provider_key=descriptor.provider_key,
                    reason_code="MARKET_NOT_SUPPORTED_BY_PROVIDER",
                )
            )
            continue
        if requirement.capability_id not in descriptor.capabilities:
            skipped.append(
                ProviderSkip(
                    provider_key=descriptor.provider_key,
                    reason_code="CAPABILITY_NOT_SUPPORTED_BY_PROVIDER",
                )
            )
            continue
        if (
            requirement.session is not MarketSession.UNKNOWN
            and descriptor.supported_sessions
            and requirement.session not in descriptor.supported_sessions
        ):
            skipped.append(
                ProviderSkip(
                    provider_key=descriptor.provider_key,
                    reason_code="SESSION_NOT_SUPPORTED_BY_PROVIDER",
                )
            )
            continue
        if (
            requirement.realtime_policy is RealtimePolicy.REQUIRE_LIVE
            and not descriptor.can_produce_live
        ):
            skipped.append(
                ProviderSkip(
                    provider_key=descriptor.provider_key,
                    reason_code="LIVE_NOT_SUPPORTED_BY_PROVIDER",
                )
            )
            continue

        skip_reason, health_limitations = _health_decision(
            descriptor,
            requirement,
            health_by_provider.get(descriptor.provider_key),
        )
        if skip_reason is not None:
            skipped.append(
                ProviderSkip(
                    provider_key=descriptor.provider_key,
                    reason_code=skip_reason,
                )
            )
            continue

        route_external_fetch = external_allowed and descriptor.supports_external_fetch
        route_subscription = subscription_allowed and descriptor.supports_live_subscription
        if not (route_external_fetch or route_subscription):
            skipped.append(
                ProviderSkip(
                    provider_key=descriptor.provider_key,
                    reason_code="ACQUISITION_METHOD_NOT_ALLOWED",
                )
            )
            continue

        eligible_routes.append(
            ProviderRoute(
                provider_key=descriptor.provider_key,
                market=descriptor.market,
                capability_id=requirement.capability_id,
                priority=descriptor.priority,
                external_fetch_allowed=route_external_fetch,
                subscription_allowed=route_subscription,
                route_timeout_seconds=min(
                    descriptor.max_timeout_seconds,
                    bounds.overall_timeout_seconds,
                ),
                limitations=health_limitations,
            )
        )

    if not fallback_allowed and len(eligible_routes) > 1:
        for route in eligible_routes[1:]:
            skipped.append(
                ProviderSkip(
                    provider_key=route.provider_key,
                    reason_code="FALLBACK_DISABLED",
                )
            )
        eligible_routes = eligible_routes[:1]

    if len(eligible_routes) > bounds.max_provider_attempts:
        for route in eligible_routes[bounds.max_provider_attempts :]:
            skipped.append(
                ProviderSkip(
                    provider_key=route.provider_key,
                    reason_code="ATTEMPT_BOUND_EXCEEDED",
                )
            )
        eligible_routes = eligible_routes[: bounds.max_provider_attempts]

    limitations: list[str] = []
    if not eligible_routes:
        limitations.append("ACQUISITION_PLAN_UNFILLABLE")
    if any(item.reason_code == "ATTEMPT_BOUND_EXCEEDED" for item in skipped):
        limitations.append("PROVIDER_ROUTES_TRUNCATED")
    if any(item.reason_code == "FALLBACK_DISABLED" for item in skipped):
        limitations.append("FALLBACK_DISABLED")

    return AcquisitionPlan(
        **common,
        routes=tuple(eligible_routes),
        skipped_providers=tuple(skipped),
        unfillable=not eligible_routes,
        limitations=_dedupe_codes(limitations),
    )


__all__ = [
    "AcquisitionBounds",
    "AcquisitionPlan",
    "ProviderDescriptor",
    "ProviderRoute",
    "ProviderSkip",
    "SUPPORTED_02A_CAPABILITIES",
    "SUPPORTED_CAPABILITIES_BY_MARKET",
    "plan_acquisition",
]
