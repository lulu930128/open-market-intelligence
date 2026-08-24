"""Acquisition and resolution policy vocabulary for canonical market data."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Protocol

from pydantic import Field, field_validator

from app.market_data.contracts import (
    CanonicalMarketSnapshot,
    CanonicalModel,
    InstrumentKey,
    InstrumentTradability,
    MarketSession,
    ProviderResourceHealth,
)


class RealtimePolicy(str, Enum):
    CACHE_ONLY = "cache_only"
    PREFER_LIVE = "prefer_live"
    REQUIRE_LIVE = "require_live"
    COMPLETED_SESSION = "completed_session"


class DataPurpose(str, Enum):
    VIEWER = "viewer"
    RESEARCH = "research"
    BACKGROUND_COLLECTOR = "background_collector"
    REPAIR = "repair"


class DataRequirement(CanonicalModel):
    contract_version: str = "omi.market.data_requirement.v1"
    instrument: InstrumentKey
    capability_id: str = Field(min_length=1, max_length=128)
    realtime_policy: RealtimePolicy
    purpose: DataPurpose
    session: MarketSession
    instrument_tradability: InstrumentTradability = InstrumentTradability.UNKNOWN
    requested_at: datetime
    max_age_seconds: int = Field(ge=1, le=86400)
    max_candidates: int = Field(default=8, ge=1, le=8)

    @field_validator("requested_at")
    @classmethod
    def _require_aware_requested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        return value


class AcquisitionResult(CanonicalModel):
    contract_version: str = "omi.market.acquisition_result.v1"
    snapshots: tuple[CanonicalMarketSnapshot, ...] = ()
    provider_health: tuple[ProviderResourceHealth, ...] = ()
    external_calls: int = Field(default=0, ge=0, le=20)
    subscriptions_created: int = Field(default=0, ge=0, le=8)
    limitations: tuple[str, ...] = ()


class MarketDataAcquisitionPort(Protocol):
    """Port implemented by market owners; Foundation provides no live implementation."""

    def acquire(self, requirement: DataRequirement) -> AcquisitionResult: ...


PUBLIC_REALTIME_POLICIES = frozenset(
    {
        RealtimePolicy.CACHE_ONLY.value,
        RealtimePolicy.PREFER_LIVE.value,
        RealtimePolicy.REQUIRE_LIVE.value,
    }
)
INTERNAL_REALTIME_POLICIES = frozenset(item.value for item in RealtimePolicy)


def parse_realtime_policy(
    value: str | RealtimePolicy,
    *,
    allow_internal: bool = False,
) -> RealtimePolicy:
    if isinstance(value, RealtimePolicy):
        parsed = value
    else:
        try:
            parsed = RealtimePolicy(str(value or "").strip().lower())
        except ValueError as exc:
            allowed = (
                INTERNAL_REALTIME_POLICIES if allow_internal else PUBLIC_REALTIME_POLICIES
            )
            raise ValueError(
                "Unsupported realtime policy. Expected one of: "
                + ", ".join(sorted(allowed))
            ) from exc
    if parsed is RealtimePolicy.COMPLETED_SESSION and not allow_internal:
        raise ValueError("completed_session is an internal canonical policy")
    return parsed


def allows_external_acquisition(policy: str | RealtimePolicy) -> bool:
    parsed = parse_realtime_policy(policy, allow_internal=True)
    return parsed in {RealtimePolicy.PREFER_LIVE, RealtimePolicy.REQUIRE_LIVE}


def allows_live_subscription(policy: str | RealtimePolicy) -> bool:
    parsed = parse_realtime_policy(policy, allow_internal=True)
    return parsed in {RealtimePolicy.PREFER_LIVE, RealtimePolicy.REQUIRE_LIVE}


def requirement_allows_external_acquisition(requirement: DataRequirement) -> bool:
    return allows_external_acquisition(requirement.realtime_policy)


__all__ = [
    "INTERNAL_REALTIME_POLICIES",
    "PUBLIC_REALTIME_POLICIES",
    "RealtimePolicy",
    "AcquisitionResult",
    "DataPurpose",
    "DataRequirement",
    "MarketDataAcquisitionPort",
    "allows_external_acquisition",
    "allows_live_subscription",
    "parse_realtime_policy",
    "requirement_allows_external_acquisition",
]
