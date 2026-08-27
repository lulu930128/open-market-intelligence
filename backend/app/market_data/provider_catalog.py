"""Pure capability-resource catalog and bounded acquisition planning.

Market owners inject descriptors and provider health. This module deliberately
contains no production provider names, URLs, credentials, imports, or I/O.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.market_data.contracts import (
    AuthorityClass,
    CanonicalModel,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentType,
    Market,
    MarketSession,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    DatasetTarget,
    InstrumentTarget,
    RefreshRequirementV1,
)
from app.market_data.policies import RealtimePolicy, allows_external_acquisition


ProviderKey = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$"),
]
ResourceId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
]
ReasonCode = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"),
]


class AcquisitionMode(str, Enum):
    FETCH = "fetch"
    SUBSCRIPTION = "subscription"


class DescriptorTargetKind(str, Enum):
    INSTRUMENT = "instrument"
    DATASET = "dataset"


class ProviderCapabilityDescriptorV2(CanonicalModel):
    """One provider resource serving one capability under explicit bounds."""

    contract_version: str = "omi.market.provider_capability_descriptor.v2"
    provider_key: ProviderKey
    market: Market
    capability_id: str = Field(min_length=1, max_length=128)
    resource_id: ResourceId
    authority: AuthorityClass
    target_kinds: tuple[DescriptorTargetKind, ...] = Field(min_length=1, max_length=2)
    dataset_ids: tuple[str, ...] = Field(default=(), max_length=16)
    dataset_scope_keys: tuple[str, ...] = Field(default=(), max_length=32)
    venue_scope: tuple[str, ...] = Field(default=(), max_length=16)
    instrument_types: tuple[InstrumentType, ...] = Field(default=(), max_length=16)
    intervals: tuple[str, ...] = Field(default=(), max_length=16)
    supported_sessions: tuple[MarketSession, ...] = Field(default=(), max_length=8)
    acquisition_modes: tuple[AcquisitionMode, ...] = Field(min_length=1, max_length=2)
    priority: int = Field(default=100, ge=0, le=10_000)
    can_produce_live: bool = False
    can_produce_final: bool = False
    max_timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_external_calls_per_attempt: int = Field(default=1, ge=0, le=20)
    max_subscriptions_per_attempt: int = Field(default=0, ge=0, le=8)
    max_symbols_per_call: int = Field(default=1, ge=1, le=5_000)
    max_range_days: int = Field(default=1, ge=1, le=3650)
    health_ttl_seconds: int = Field(default=300, ge=1, le=86_400)
    allow_unknown_health: bool = False
    allow_disconnected_connect: bool = False
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=16)

    @field_validator("venue_scope", mode="before")
    @classmethod
    def _normalize_venues(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(item.strip().upper() if isinstance(item, str) else item for item in value)
        return value

    @model_validator(mode="after")
    def _validate_descriptor(self) -> ProviderCapabilityDescriptorV2:
        unique_groups = (
            (self.target_kinds, "target_kinds"),
            (self.dataset_ids, "dataset_ids"),
            (self.dataset_scope_keys, "dataset_scope_keys"),
            (self.venue_scope, "venue_scope"),
            (self.instrument_types, "instrument_types"),
            (self.intervals, "intervals"),
            (self.supported_sessions, "supported_sessions"),
            (self.acquisition_modes, "acquisition_modes"),
            (self.limitations, "limitations"),
        )
        for values, label in unique_groups:
            if len(values) != len(set(values)):
                raise ValueError(f"descriptor {label} must be unique")
        if DescriptorTargetKind.DATASET in self.target_kinds and not self.dataset_ids:
            raise ValueError("dataset resources require dataset_ids")
        if self.dataset_ids and DescriptorTargetKind.DATASET not in self.target_kinds:
            raise ValueError("dataset_ids require the dataset target kind")
        if self.dataset_scope_keys and DescriptorTargetKind.DATASET not in self.target_kinds:
            raise ValueError("dataset_scope_keys require the dataset target kind")
        if AcquisitionMode.FETCH in self.acquisition_modes:
            if self.max_external_calls_per_attempt < 1:
                raise ValueError("fetch resources require an external-call bound")
        elif self.max_external_calls_per_attempt != 0:
            raise ValueError("non-fetch resources cannot advertise external calls")
        if AcquisitionMode.SUBSCRIPTION in self.acquisition_modes:
            if not self.can_produce_live:
                raise ValueError("subscription resources must produce live evidence")
            if self.max_subscriptions_per_attempt < 1:
                raise ValueError("subscription resources require a subscription bound")
        elif self.max_subscriptions_per_attempt != 0:
            raise ValueError("non-subscription resources cannot advertise subscriptions")
        return self


class ProviderResourceRouteV2(CanonicalModel):
    contract_version: str = "omi.market.provider_resource_route.v2"
    provider_key: ProviderKey
    market: Market
    capability_id: str = Field(min_length=1, max_length=128)
    resource_id: ResourceId
    authority: AuthorityClass
    priority: int = Field(ge=0, le=10_000)
    fetch_allowed: bool
    subscription_allowed: bool
    timeout_seconds: int = Field(ge=1, le=120)
    max_external_calls: int = Field(ge=0, le=20)
    max_subscriptions: int = Field(ge=0, le=8)
    max_symbols: int = Field(ge=1, le=5_000)
    max_range_days: int = Field(ge=1, le=3650)
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def _validate_route(self) -> ProviderResourceRouteV2:
        if not (self.fetch_allowed or self.subscription_allowed):
            raise ValueError("resource route requires an allowed acquisition mode")
        if self.fetch_allowed != (self.max_external_calls > 0):
            raise ValueError("fetch route and external-call bound must agree")
        if self.subscription_allowed != (self.max_subscriptions > 0):
            raise ValueError("subscription route and subscription bound must agree")
        return self


class ProviderResourceSkipV2(CanonicalModel):
    contract_version: str = "omi.market.provider_resource_skip.v2"
    provider_key: ProviderKey
    resource_id: ResourceId
    reason_code: ReasonCode


class DataAcquisitionPlanV2(CanonicalModel):
    contract_version: str = "omi.market.data_acquisition_plan.v2"
    requirement: DataRequirementV2
    routes: tuple[ProviderResourceRouteV2, ...] = Field(default=(), max_length=8)
    skipped_resources: tuple[ProviderResourceSkipV2, ...] = Field(default=(), max_length=32)
    acquisition_required: bool
    unfillable: bool
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def _validate_plan(self) -> DataAcquisitionPlanV2:
        if len(self.routes) > self.requirement.bounds.max_provider_attempts:
            raise ValueError("routes exceed requirement provider-attempt bound")
        if sum(route.max_external_calls for route in self.routes) > self.requirement.bounds.max_external_calls:
            raise ValueError("routes exceed requirement external-call bound")
        if sum(route.max_subscriptions for route in self.routes) > self.requirement.bounds.max_subscriptions:
            raise ValueError("routes exceed requirement subscription bound")
        if not self.acquisition_required and self.routes:
            raise ValueError("non-acquiring plan cannot contain routes")
        if self.unfillable and self.routes:
            raise ValueError("unfillable plan cannot contain routes")
        if self.acquisition_required and not self.routes and not self.unfillable:
            raise ValueError("required acquisition without routes must be unfillable")
        _require_unique_routes(self.routes)
        return self


class RefreshAcquisitionPlanV1(CanonicalModel):
    contract_version: str = "omi.market.refresh_acquisition_plan.v1"
    requirement: RefreshRequirementV1
    routes: tuple[ProviderResourceRouteV2, ...] = Field(default=(), max_length=8)
    skipped_resources: tuple[ProviderResourceSkipV2, ...] = Field(default=(), max_length=32)
    unfillable: bool
    limitations: tuple[ReasonCode, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def _validate_plan(self) -> RefreshAcquisitionPlanV1:
        if len(self.routes) > self.requirement.max_provider_attempts:
            raise ValueError("routes exceed refresh provider-attempt bound")
        if sum(route.max_external_calls for route in self.routes) > self.requirement.max_external_calls:
            raise ValueError("routes exceed refresh external-call bound")
        if any(route.subscription_allowed for route in self.routes):
            raise ValueError("refresh plan cannot contain subscriptions")
        if self.unfillable and self.routes:
            raise ValueError("unfillable refresh plan cannot contain routes")
        if not self.routes and not self.unfillable:
            raise ValueError("empty refresh plan must be unfillable")
        _require_unique_routes(self.routes)
        return self


def _require_unique_routes(routes: tuple[ProviderResourceRouteV2, ...]) -> None:
    keys = [(route.provider_key, route.resource_id) for route in routes]
    if len(keys) != len(set(keys)):
        raise ValueError("provider resource routes must be unique")


def _unique_codes(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _target_facts(
    requirement: DataRequirementV2 | RefreshRequirementV1,
) -> tuple[Market, DescriptorTargetKind, str | None, InstrumentType | None]:
    target = requirement.target
    if isinstance(target, InstrumentTarget):
        return (
            target.instrument.market,
            DescriptorTargetKind.INSTRUMENT,
            target.instrument.venue,
            target.instrument.instrument_type,
        )
    assert isinstance(target, DatasetTarget)
    return target.market, DescriptorTargetKind.DATASET, None, None


def _health_index(
    records: Iterable[ProviderResourceHealth],
) -> dict[tuple[str, Market, str], ProviderResourceHealth]:
    indexed: dict[tuple[str, Market, str], ProviderResourceHealth] = {}
    for record in records:
        key = (record.provider, record.market, record.capability)
        if key in indexed:
            raise ValueError("provider health records must be unique by provider/market/capability")
        indexed[key] = record
    return indexed


def _health_decision(
    descriptor: ProviderCapabilityDescriptorV2,
    health: ProviderResourceHealth | None,
    *,
    requested_at: datetime,
) -> tuple[str | None, tuple[str, ...]]:
    if health is None:
        return (
            (None, ("HEALTH_UNKNOWN",))
            if descriptor.allow_unknown_health
            else ("HEALTH_UNKNOWN", ())
        )
    age_seconds = (requested_at - health.checked_at).total_seconds()
    if age_seconds < 0 or age_seconds > descriptor.health_ttl_seconds:
        return (
            (None, ("HEALTH_STALE",))
            if descriptor.allow_unknown_health
            else ("HEALTH_STALE", ())
        )
    terminal = (
        (health.enablement is EnablementStatus.DISABLED, "PROVIDER_DISABLED"),
        (health.entitlement is EntitlementStatus.AUTH_FAILED, "AUTH_FAILED"),
        (health.entitlement is EntitlementStatus.PLAN_RESTRICTED, "PLAN_RESTRICTED"),
        (health.operational is OperationalStatus.FAILED, "OPERATIONAL_FAILED"),
        (health.operational is OperationalStatus.RATE_LIMITED, "RATE_LIMITED"),
        (health.operational is OperationalStatus.UNAVAILABLE, "UNAVAILABLE"),
    )
    for matched, reason in terminal:
        if matched:
            return reason, ()
    unknown = any(
        (
            health.enablement is EnablementStatus.UNKNOWN,
            health.connection is ConnectionStatus.UNKNOWN,
            health.entitlement is EntitlementStatus.UNKNOWN,
            health.operational is OperationalStatus.UNKNOWN,
            health.freshness is EvidenceFreshness.UNKNOWN,
        )
    )
    if unknown and not descriptor.allow_unknown_health:
        return "HEALTH_UNKNOWN", ()
    if (
        health.connection is ConnectionStatus.DISCONNECTED
        and not descriptor.allow_disconnected_connect
    ):
        return "NOT_CONNECTED", ()
    limitations: list[str] = []
    if unknown:
        limitations.append("HEALTH_UNKNOWN")
    if health.connection is ConnectionStatus.DISCONNECTED:
        limitations.append("BOUNDED_CONNECT_REQUIRED")
    elif health.connection is ConnectionStatus.DEGRADED:
        limitations.append("CONNECTION_DEGRADED")
    if health.operational is OperationalStatus.DEGRADED:
        limitations.append("OPERATIONAL_DEGRADED")
    return None, tuple(limitations)


def _descriptor_skip_reason(
    descriptor: ProviderCapabilityDescriptorV2,
    requirement: DataRequirementV2 | RefreshRequirementV1,
    *,
    capability_id: str | None,
) -> str | None:
    market, target_kind, venue, instrument_type = _target_facts(requirement)
    if descriptor.market is not market:
        return "MARKET_NOT_SUPPORTED_BY_RESOURCE"
    if capability_id is not None and descriptor.capability_id != capability_id:
        return "CAPABILITY_NOT_SUPPORTED_BY_RESOURCE"
    if target_kind not in descriptor.target_kinds:
        return "TARGET_KIND_NOT_SUPPORTED_BY_RESOURCE"
    if isinstance(requirement, RefreshRequirementV1):
        if requirement.dataset_id not in descriptor.dataset_ids:
            return "DATASET_NOT_SUPPORTED_BY_RESOURCE"
        if (
            isinstance(requirement.target, DatasetTarget)
            and descriptor.dataset_scope_keys
            and requirement.target.scope_key not in descriptor.dataset_scope_keys
        ):
            return "DATASET_SCOPE_NOT_SUPPORTED_BY_RESOURCE"
        if AcquisitionMode.FETCH not in descriptor.acquisition_modes:
            return "REFRESH_FETCH_NOT_SUPPORTED"
    if venue and descriptor.venue_scope and venue not in descriptor.venue_scope:
        return "VENUE_NOT_SUPPORTED_BY_RESOURCE"
    if (
        instrument_type is not None
        and descriptor.instrument_types
        and instrument_type not in descriptor.instrument_types
    ):
        return "INSTRUMENT_TYPE_NOT_SUPPORTED_BY_RESOURCE"
    if isinstance(requirement, DataRequirementV2):
        if (
            requirement.session is not MarketSession.UNKNOWN
            and descriptor.supported_sessions
            and requirement.session not in descriptor.supported_sessions
        ):
            return "SESSION_NOT_SUPPORTED_BY_RESOURCE"
        if isinstance(requirement.request, BarCapabilityRequest):
            if descriptor.intervals and requirement.request.interval not in descriptor.intervals:
                return "INTERVAL_NOT_SUPPORTED_BY_RESOURCE"
        if (
            requirement.realtime_policy is RealtimePolicy.REQUIRE_LIVE
            and not descriptor.can_produce_live
        ):
            return "LIVE_NOT_SUPPORTED_BY_RESOURCE"
    return None


def _route(
    descriptor: ProviderCapabilityDescriptorV2,
    *,
    fetch_allowed: bool,
    subscription_allowed: bool,
    timeout_seconds: int,
    max_external_calls: int,
    max_subscriptions: int,
    max_symbols: int,
    max_range_days: int,
    limitations: tuple[str, ...],
) -> ProviderResourceRouteV2:
    return ProviderResourceRouteV2(
        provider_key=descriptor.provider_key,
        market=descriptor.market,
        capability_id=descriptor.capability_id,
        resource_id=descriptor.resource_id,
        authority=descriptor.authority,
        priority=descriptor.priority,
        fetch_allowed=fetch_allowed,
        subscription_allowed=subscription_allowed,
        timeout_seconds=min(descriptor.max_timeout_seconds, timeout_seconds),
        max_external_calls=max_external_calls,
        max_subscriptions=max_subscriptions,
        max_symbols=min(descriptor.max_symbols_per_call, max_symbols),
        max_range_days=min(descriptor.max_range_days, max_range_days),
        limitations=_unique_codes((*descriptor.limitations, *limitations)),
    )


def plan_data_acquisition_v2(
    requirement: DataRequirementV2,
    descriptors: Iterable[ProviderCapabilityDescriptorV2],
    provider_health: Iterable[ProviderResourceHealth] = (),
) -> DataAcquisitionPlanV2:
    """Build a deterministic provider-resource plan without performing I/O."""

    if not allows_external_acquisition(requirement.realtime_policy):
        return DataAcquisitionPlanV2(
            requirement=requirement,
            acquisition_required=False,
            unfillable=False,
            limitations=("POLICY_NO_EXTERNAL_ACQUISITION",),
        )
    if (
        requirement.bounds.max_provider_attempts == 0
        or (
            requirement.bounds.max_external_calls == 0
            and requirement.bounds.max_subscriptions == 0
        )
    ):
        return DataAcquisitionPlanV2(
            requirement=requirement,
            acquisition_required=True,
            unfillable=True,
            limitations=("ACQUISITION_BUDGET_ZERO",),
        )

    descriptor_list = tuple(descriptors)
    if len(descriptor_list) > 32:
        raise ValueError("provider descriptor input exceeds bounded catalog size")
    descriptor_keys = [(item.provider_key, item.resource_id) for item in descriptor_list]
    if len(descriptor_keys) != len(set(descriptor_keys)):
        raise ValueError("provider descriptors must be unique by provider/resource")
    health = _health_index(provider_health)
    routes: list[ProviderResourceRouteV2] = []
    skipped: list[ProviderResourceSkipV2] = []
    used_calls = 0
    used_subscriptions = 0

    for descriptor in sorted(
        descriptor_list,
        key=lambda item: (item.priority, item.provider_key, item.resource_id),
    ):
        reason = _descriptor_skip_reason(
            descriptor,
            requirement,
            capability_id=requirement.request.capability_id,
        )
        if reason is None:
            reason, health_limitations = _health_decision(
                descriptor,
                health.get((descriptor.provider_key, descriptor.market, descriptor.capability_id)),
                requested_at=requirement.requested_at,
            )
        else:
            health_limitations = ()
        if reason is not None:
            skipped.append(
                ProviderResourceSkipV2(
                    provider_key=descriptor.provider_key,
                    resource_id=descriptor.resource_id,
                    reason_code=reason,
                )
            )
            continue
        if len(routes) >= requirement.bounds.max_provider_attempts:
            reason = "ATTEMPT_BOUND_EXCEEDED"
        else:
            fetch = AcquisitionMode.FETCH in descriptor.acquisition_modes
            subscribe = (
                AcquisitionMode.SUBSCRIPTION in descriptor.acquisition_modes
                and requirement.bounds.max_subscriptions > used_subscriptions
            )
            remaining_calls = requirement.bounds.max_external_calls - used_calls
            remaining_subscriptions = requirement.bounds.max_subscriptions - used_subscriptions
            route_calls = min(descriptor.max_external_calls_per_attempt, remaining_calls) if fetch else 0
            route_subscriptions = (
                min(descriptor.max_subscriptions_per_attempt, remaining_subscriptions)
                if subscribe
                else 0
            )
            if fetch and route_calls == 0 and route_subscriptions == 0:
                reason = "EXTERNAL_CALL_BOUND_EXCEEDED"
            elif not fetch and route_subscriptions == 0:
                reason = "ACQUISITION_MODE_NOT_ALLOWED"
            else:
                routes.append(
                    _route(
                        descriptor,
                        fetch_allowed=route_calls > 0,
                        subscription_allowed=route_subscriptions > 0,
                        timeout_seconds=requirement.bounds.timeout_seconds,
                        max_external_calls=route_calls,
                        max_subscriptions=route_subscriptions,
                        max_symbols=1,
                        max_range_days=3650,
                        limitations=health_limitations,
                    )
                )
                used_calls += route_calls
                used_subscriptions += route_subscriptions
                continue
        skipped.append(
            ProviderResourceSkipV2(
                provider_key=descriptor.provider_key,
                resource_id=descriptor.resource_id,
                reason_code=reason,
            )
        )

    limitations: list[str] = []
    if not routes:
        limitations.append("ACQUISITION_PLAN_UNFILLABLE")
    if any(item.reason_code == "ATTEMPT_BOUND_EXCEEDED" for item in skipped):
        limitations.append("RESOURCE_ROUTES_TRUNCATED")
    return DataAcquisitionPlanV2(
        requirement=requirement,
        routes=tuple(routes),
        skipped_resources=tuple(skipped),
        acquisition_required=True,
        unfillable=not routes,
        limitations=tuple(limitations),
    )


def plan_refresh_acquisition_v1(
    requirement: RefreshRequirementV1,
    descriptors: Iterable[ProviderCapabilityDescriptorV2],
    provider_health: Iterable[ProviderResourceHealth] = (),
) -> RefreshAcquisitionPlanV1:
    """Build a bounded fetch-only repair plan from injected dataset resources."""

    descriptor_list = tuple(descriptors)
    if len(descriptor_list) > 32:
        raise ValueError("provider descriptor input exceeds bounded catalog size")
    descriptor_keys = [(item.provider_key, item.resource_id) for item in descriptor_list]
    if len(descriptor_keys) != len(set(descriptor_keys)):
        raise ValueError("provider descriptors must be unique by provider/resource")
    health = _health_index(provider_health)
    routes: list[ProviderResourceRouteV2] = []
    skipped: list[ProviderResourceSkipV2] = []
    used_calls = 0

    for descriptor in sorted(
        descriptor_list,
        key=lambda item: (item.priority, item.provider_key, item.resource_id),
    ):
        reason = _descriptor_skip_reason(descriptor, requirement, capability_id=None)
        if reason is None:
            reason, health_limitations = _health_decision(
                descriptor,
                health.get((descriptor.provider_key, descriptor.market, descriptor.capability_id)),
                requested_at=requirement.requested_at,
            )
        else:
            health_limitations = ()
        if reason is not None:
            skipped.append(
                ProviderResourceSkipV2(
                    provider_key=descriptor.provider_key,
                    resource_id=descriptor.resource_id,
                    reason_code=reason,
                )
            )
            continue
        if len(routes) >= requirement.max_provider_attempts:
            reason = "ATTEMPT_BOUND_EXCEEDED"
        else:
            remaining_calls = requirement.max_external_calls - used_calls
            route_calls = min(descriptor.max_external_calls_per_attempt, remaining_calls)
            if route_calls == 0:
                reason = "EXTERNAL_CALL_BOUND_EXCEEDED"
            else:
                routes.append(
                    _route(
                        descriptor,
                        fetch_allowed=True,
                        subscription_allowed=False,
                        timeout_seconds=requirement.timeout_seconds,
                        max_external_calls=route_calls,
                        max_subscriptions=0,
                        max_symbols=requirement.max_symbols,
                        max_range_days=requirement.max_range_days,
                        limitations=health_limitations,
                    )
                )
                used_calls += route_calls
                continue
        skipped.append(
            ProviderResourceSkipV2(
                provider_key=descriptor.provider_key,
                resource_id=descriptor.resource_id,
                reason_code=reason,
            )
        )

    limitations = () if routes else ("REFRESH_PLAN_UNFILLABLE",)
    return RefreshAcquisitionPlanV1(
        requirement=requirement,
        routes=tuple(routes),
        skipped_resources=tuple(skipped),
        unfillable=not routes,
        limitations=limitations,
    )


__all__ = [
    "AcquisitionMode",
    "DataAcquisitionPlanV2",
    "DescriptorTargetKind",
    "ProviderCapabilityDescriptorV2",
    "ProviderResourceRouteV2",
    "ProviderResourceSkipV2",
    "RefreshAcquisitionPlanV1",
    "plan_data_acquisition_v2",
    "plan_refresh_acquisition_v1",
]
