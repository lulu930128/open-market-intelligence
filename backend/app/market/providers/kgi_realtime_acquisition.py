"""Pure KGI realtime acquisition adapter for Shared MarketDataGateway ports.

This module performs no database work and owns no lease lifecycle. It reads one
already-bounded provider snapshot through an injected port, converts it into
canonical observations, and returns a raw receipt for an external transaction
owner to persist atomically.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any

from app.market.providers.kgi_canonical import (
    KGI_PROVIDER,
    KGI_RAW_CONTRACT_VERSION,
    KGI_SOURCE,
    canonical_snapshot_from_kgi,
)
from app.market.tw_realtime_capabilities import (
    KGI_AUCTION_RESOURCE_ID,
    KGI_ORDER_BOOK_RESOURCE_ID,
    KGI_QUOTE_RESOURCE_ID,
)
from app.market_data.contracts import CanonicalMarketSnapshot
from app.market_data.gateway import (
    AuctionAcquisitionResult,
    DepthAcquisitionResult,
    QuoteAcquisitionResult,
)
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    DataRequirementV2,
    InstrumentTarget,
    RawFetchReceiptV1,
    SnapshotCapabilityRequest,
)
from app.market_data.provider_catalog import (
    DataAcquisitionPlanV2,
    ProviderResourceRouteV2,
)


@dataclass(frozen=True, slots=True)
class KgiRealtimeProviderSnapshot:
    quote: dict[str, Any] | None
    status: str
    error: str | None = None


KgiRealtimeSnapshotReader = Callable[[str], KgiRealtimeProviderSnapshot]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class _CanonicalAcquisition:
    snapshot: CanonicalMarketSnapshot | None
    summary: AcquisitionSummary
    receipts: tuple[RawFetchReceiptV1, ...]


class KgiRealtimeAcquisitionAdapter:
    """Implement quote/depth/auction acquisition without persistence or leases."""

    def __init__(
        self,
        snapshot_reader: KgiRealtimeSnapshotReader,
        *,
        clock: Clock,
    ) -> None:
        self._snapshot_reader = snapshot_reader
        self._clock = clock

    @staticmethod
    def _planned_route(
        plan: DataAcquisitionPlanV2,
        *,
        resource_id: str,
    ) -> ProviderResourceRouteV2 | None:
        routes = tuple(
            route
            for route in plan.routes
            if route.provider_key == KGI_PROVIDER
            and route.resource_id == resource_id
        )
        if len(routes) > 1:
            raise ValueError("KGI acquisition plan contains duplicate resource routes")
        return routes[0] if routes else None

    @staticmethod
    def _not_planned(resource_id: str) -> _CanonicalAcquisition:
        return _CanonicalAcquisition(
            snapshot=None,
            summary=AcquisitionSummary(
                attempted=False,
                status=AcquisitionStatus.NOT_ATTEMPTED,
                limitations=(f"KGI_ROUTE_NOT_PLANNED:{resource_id}",),
            ),
            receipts=(),
        )

    def _acquire(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
        *,
        resource_id: str,
    ) -> _CanonicalAcquisition:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("KGI realtime acquisition requires an instrument target")
        route = self._planned_route(plan, resource_id=resource_id)
        if route is None:
            return self._not_planned(resource_id)

        provider_snapshot = self._snapshot_reader(
            requirement.target.instrument.symbol
        )
        attempt = AcquisitionResourceAttempt(
            provider=KGI_PROVIDER,
            resource_id=resource_id,
        )
        normalized_status = str(provider_snapshot.status or "").strip().lower()
        if normalized_status != "live" or provider_snapshot.quote is None:
            status_code = normalized_status.upper() or "UNKNOWN"
            return _CanonicalAcquisition(
                snapshot=None,
                summary=AcquisitionSummary(
                    attempted=True,
                    status=AcquisitionStatus.UNAVAILABLE,
                    providers_attempted=(KGI_PROVIDER,),
                    resource_attempts=(attempt,),
                    limitations=(f"KGI_PROVIDER_{status_code}",),
                ),
                receipts=(),
            )

        sampled_at = self._clock()
        if sampled_at.tzinfo is None or sampled_at.utcoffset() is None:
            raise ValueError("KGI acquisition clock must return timezone-aware time")
        quote = dict(provider_snapshot.quote)
        raw_text = json.dumps(
            quote,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        content_hash = sha256(raw_text.encode("utf-8")).hexdigest()
        snapshot = canonical_snapshot_from_kgi(
            instrument=requirement.target.instrument,
            quote=quote,
            session=requirement.session,
            received_at=sampled_at,
            auction_type=(
                requirement.request.auction_type
                if isinstance(requirement.request, SnapshotCapabilityRequest)
                else None
            ),
        )

        def with_receipt_lineage(observation: Any) -> Any:
            if observation is None:
                return None
            return observation.model_copy(
                update={
                    "lineage": observation.lineage.model_copy(
                        update={
                            "fetched_at": sampled_at,
                            "content_hash": content_hash,
                        }
                    )
                }
            )

        snapshot = snapshot.model_copy(
            update={
                "quote": with_receipt_lineage(snapshot.quote),
                "depth": with_receipt_lineage(snapshot.depth),
                "auction": with_receipt_lineage(snapshot.auction),
                "trading_status": with_receipt_lineage(snapshot.trading_status),
            }
        )
        receipt = RawFetchReceiptV1(
            provider=KGI_PROVIDER,
            source=KGI_SOURCE,
            resource_id=resource_id,
            fetched_at=sampled_at,
            method="STREAM",
            content_type="application/json",
            content_hash=content_hash,
            raw_text=raw_text,
            parser_version=KGI_RAW_CONTRACT_VERSION,
            error_message=provider_snapshot.error,
        )
        return _CanonicalAcquisition(
            snapshot=snapshot,
            summary=AcquisitionSummary(
                attempted=True,
                status=AcquisitionStatus.COMPLETED,
                providers_attempted=(KGI_PROVIDER,),
                resource_attempts=(attempt,),
            ),
            receipts=(receipt,),
        )

    def acquire_quote_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> QuoteAcquisitionResult:
        acquired = self._acquire(
            requirement,
            plan,
            resource_id=KGI_QUOTE_RESOURCE_ID,
        )
        observation = acquired.snapshot.quote if acquired.snapshot is not None else None
        return QuoteAcquisitionResult(
            summary=acquired.summary,
            observations=(observation,) if observation is not None else (),
            receipts=acquired.receipts,
        )

    def acquire_depth_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> DepthAcquisitionResult:
        acquired = self._acquire(
            requirement,
            plan,
            resource_id=KGI_ORDER_BOOK_RESOURCE_ID,
        )
        observation = acquired.snapshot.depth if acquired.snapshot is not None else None
        return DepthAcquisitionResult(
            summary=acquired.summary,
            observations=(observation,) if observation is not None else (),
            receipts=acquired.receipts,
        )

    def acquire_auction_observations(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
    ) -> AuctionAcquisitionResult:
        acquired = self._acquire(
            requirement,
            plan,
            resource_id=KGI_AUCTION_RESOURCE_ID,
        )
        observation = (
            acquired.snapshot.auction if acquired.snapshot is not None else None
        )
        summary = acquired.summary
        if acquired.snapshot is not None and observation is None:
            summary = summary.model_copy(
                update={
                    "status": AcquisitionStatus.PARTIAL,
                    "limitations": ("KGI_AUCTION_OBSERVATION_UNAVAILABLE",),
                }
            )
        return AuctionAcquisitionResult(
            summary=summary,
            observations=(observation,) if observation is not None else (),
            receipts=acquired.receipts,
        )


__all__ = [
    "KgiRealtimeAcquisitionAdapter",
    "KgiRealtimeProviderSnapshot",
    "KgiRealtimeSnapshotReader",
]
