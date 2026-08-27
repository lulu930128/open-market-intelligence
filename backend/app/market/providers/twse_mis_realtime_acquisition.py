"""Pure TWSE MIS full-snapshot adapter for quote, depth, and auction ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from app.market.providers import twse_mis
from app.market.providers.tw_public_quote import (
    TWSE_MIS_QUOTE_PARSER_VERSION,
    endpoint_for_instrument,
    exchange_code_for_venue,
    parse_twse_mis_quote_payload,
)
from app.market.providers.twse_mis_canonical import (
    MIS_PROVIDER,
    MIS_SOURCE,
    canonical_snapshot_from_twse_mis,
)
from app.market.tw_realtime_capabilities import (
    MIS_AUCTION_RESOURCE_ID,
    MIS_ORDER_BOOK_RESOURCE_ID,
)
from app.market.tw_public_quote_contract import TWSE_MIS_QUOTE_RESOURCE_ID
from app.market_data.contracts import (
    CanonicalMarketSnapshot,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    MarketSession,
    OperationalStatus,
    ProviderResourceHealth,
)
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
from app.market_data.provider_catalog import DataAcquisitionPlanV2


@dataclass(frozen=True, slots=True)
class TwseMisProviderSnapshot:
    raw_text: str | None
    status: str
    url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    error: str | None = None


TwseMisSnapshotReader = Callable[[str, str | None, int], TwseMisProviderSnapshot]
Clock = Callable[[], datetime]


def _default_reader(
    symbol: str,
    venue: str | None,
    timeout_seconds: int,
) -> TwseMisProviderSnapshot:
    response = twse_mis.get_stock_response(
        [symbol],
        exchange=exchange_code_for_venue(venue),
        timeout_seconds=timeout_seconds,
    )
    return TwseMisProviderSnapshot(
        raw_text=str(response.text or ""),
        status="available" if 200 <= int(response.status_code) < 300 else "failed",
        url=str(response.url or ""),
        status_code=int(response.status_code),
        content_type=str(response.headers.get("content-type") or "") or None,
        error=(
            None
            if 200 <= int(response.status_code) < 300
            else f"HTTP {int(response.status_code)}"
        ),
    )


@dataclass(frozen=True, slots=True)
class _AcquiredSnapshot:
    snapshot: CanonicalMarketSnapshot | None
    summary: AcquisitionSummary
    receipts: tuple[RawFetchReceiptV1, ...]
    provider_health: tuple[ProviderResourceHealth, ...]


class TwseMisRealtimeAcquisitionAdapter:
    """Fetch once per symbol and expose capability-specific canonical results."""

    def __init__(
        self,
        reader: TwseMisSnapshotReader = _default_reader,
        *,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._clock = clock
        self._cache: dict[str, tuple[TwseMisProviderSnapshot, datetime]] = {}

    def _health(
        self,
        requirement: DataRequirementV2,
        *,
        checked_at: datetime,
        healthy: bool,
        detail_code: str,
    ) -> ProviderResourceHealth:
        return ProviderResourceHealth(
            provider=MIS_PROVIDER,
            market=requirement.target.instrument.market,
            capability=requirement.request.capability_id,
            enablement=EnablementStatus.ENABLED,
            connection=(
                ConnectionStatus.CONNECTED
                if healthy
                else ConnectionStatus.DISCONNECTED
            ),
            entitlement=EntitlementStatus.ENTITLED,
            operational=(
                OperationalStatus.HEALTHY
                if healthy
                else OperationalStatus.FAILED
            ),
            freshness=(
                EvidenceFreshness.FRESH
                if healthy
                and requirement.session
                in {MarketSession.CLOSE_RESOLUTION, MarketSession.POST_CLOSE}
                else EvidenceFreshness.LIVE
                if healthy
                else EvidenceFreshness.MISSING
            ),
            checked_at=checked_at,
            detail_code=detail_code,
        )

    def _acquire(
        self,
        requirement: DataRequirementV2,
        plan: DataAcquisitionPlanV2,
        *,
        resource_id: str,
    ) -> _AcquiredSnapshot:
        if plan.requirement != requirement:
            raise ValueError("MIS acquisition plan does not match requirement")
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("MIS realtime acquisition requires instrument target")
        routes = tuple(
            route
            for route in plan.routes
            if route.provider_key == MIS_PROVIDER and route.resource_id == resource_id
        )
        if not routes:
            return _AcquiredSnapshot(
                snapshot=None,
                summary=AcquisitionSummary(
                    attempted=False,
                    status=AcquisitionStatus.NOT_ATTEMPTED,
                    limitations=(f"MIS_ROUTE_NOT_PLANNED:{resource_id}",),
                ),
                receipts=(),
                provider_health=(),
            )
        if len(routes) != 1:
            raise ValueError("MIS acquisition plan contains duplicate resource route")
        route = routes[0]
        instrument = requirement.target.instrument
        cached = self._cache.get(instrument.symbol)
        external_calls = 0
        if cached is None:
            sampled_at = self._clock()
            if sampled_at.tzinfo is None or sampled_at.utcoffset() is None:
                raise ValueError("MIS acquisition clock must return timezone-aware time")
            try:
                provider_snapshot = self._reader(
                    instrument.symbol,
                    instrument.venue,
                    route.timeout_seconds,
                )
            except Exception as exc:
                provider_snapshot = TwseMisProviderSnapshot(
                    raw_text=None,
                    status="failed",
                    url=endpoint_for_instrument(instrument),
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                )
            self._cache[instrument.symbol] = (provider_snapshot, sampled_at)
            external_calls = 1
        else:
            provider_snapshot, sampled_at = cached

        raw_text = provider_snapshot.raw_text or ""
        content_hash = sha256(raw_text.encode("utf-8")).hexdigest()
        receipt = RawFetchReceiptV1(
            provider=MIS_PROVIDER,
            source=MIS_SOURCE,
            resource_id=resource_id,
            fetched_at=sampled_at,
            method="GET",
            url=provider_snapshot.url or endpoint_for_instrument(instrument),
            status_code=provider_snapshot.status_code,
            content_type=provider_snapshot.content_type,
            content_hash=content_hash,
            raw_text=provider_snapshot.raw_text,
            parser_version=TWSE_MIS_QUOTE_PARSER_VERSION,
            error_message=provider_snapshot.error,
        )
        attempt = AcquisitionResourceAttempt(
            provider=MIS_PROVIDER,
            resource_id=resource_id,
        )
        if provider_snapshot.status != "available" or not provider_snapshot.raw_text:
            health = self._health(
                requirement,
                checked_at=sampled_at,
                healthy=False,
                detail_code="PROVIDER_REQUEST_FAILED",
            )
            return _AcquiredSnapshot(
                snapshot=None,
                summary=AcquisitionSummary(
                    attempted=True,
                    status=AcquisitionStatus.FAILED,
                    providers_attempted=(MIS_PROVIDER,),
                    resource_attempts=(attempt,),
                    external_calls=external_calls,
                    limitations=("PROVIDER_REQUEST_FAILED",),
                ),
                receipts=(receipt,),
                provider_health=(health,),
            )
        try:
            message = parse_twse_mis_quote_payload(
                provider_snapshot.raw_text,
                target_symbol=instrument.symbol,
            )
            snapshot = canonical_snapshot_from_twse_mis(
                instrument=instrument,
                message=message,
                session=requirement.session,
                fetched_at=sampled_at,
                expected_trade_date=None,
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
                                "source": MIS_SOURCE,
                                "raw_contract_version": TWSE_MIS_QUOTE_PARSER_VERSION,
                                "received_at": sampled_at,
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
                    "trading_status": with_receipt_lineage(
                        snapshot.trading_status
                    ),
                }
            )
        except Exception as exc:
            failed_receipt = receipt.model_copy(
                update={"error_message": f"{type(exc).__name__}: {exc}"[:1000]}
            )
            health = self._health(
                requirement,
                checked_at=sampled_at,
                healthy=False,
                detail_code="PAYLOAD_PARSE_FAILED",
            )
            return _AcquiredSnapshot(
                snapshot=None,
                summary=AcquisitionSummary(
                    attempted=True,
                    status=AcquisitionStatus.FAILED,
                    providers_attempted=(MIS_PROVIDER,),
                    resource_attempts=(attempt,),
                    external_calls=external_calls,
                    limitations=("PAYLOAD_PARSE_FAILED",),
                ),
                receipts=(failed_receipt,),
                provider_health=(health,),
            )
        health = self._health(
            requirement,
            checked_at=sampled_at,
            healthy=True,
            detail_code="CANONICAL_SNAPSHOT_AVAILABLE",
        )
        return _AcquiredSnapshot(
            snapshot=snapshot,
            summary=AcquisitionSummary(
                attempted=True,
                status=AcquisitionStatus.COMPLETED,
                providers_attempted=(MIS_PROVIDER,),
                resource_attempts=(attempt,),
                external_calls=external_calls,
            ),
            receipts=(receipt,),
            provider_health=(health,),
        )

    def acquire_quote_observations(self, requirement, plan) -> QuoteAcquisitionResult:
        acquired = self._acquire(
            requirement,
            plan,
            resource_id=TWSE_MIS_QUOTE_RESOURCE_ID,
        )
        observation = acquired.snapshot.quote if acquired.snapshot is not None else None
        return QuoteAcquisitionResult(
            summary=acquired.summary,
            observations=(observation,) if observation is not None else (),
            receipts=acquired.receipts,
            provider_health=acquired.provider_health,
        )

    def acquire_depth_observations(self, requirement, plan) -> DepthAcquisitionResult:
        acquired = self._acquire(
            requirement,
            plan,
            resource_id=MIS_ORDER_BOOK_RESOURCE_ID,
        )
        observation = acquired.snapshot.depth if acquired.snapshot is not None else None
        return DepthAcquisitionResult(
            summary=acquired.summary,
            observations=(observation,) if observation is not None else (),
            receipts=acquired.receipts,
            provider_health=acquired.provider_health,
        )

    def acquire_auction_observations(self, requirement, plan) -> AuctionAcquisitionResult:
        acquired = self._acquire(
            requirement,
            plan,
            resource_id=MIS_AUCTION_RESOURCE_ID,
        )
        observation = acquired.snapshot.auction if acquired.snapshot is not None else None
        summary = acquired.summary
        if acquired.snapshot is not None and observation is None:
            summary = summary.model_copy(
                update={
                    "status": AcquisitionStatus.PARTIAL,
                    "limitations": ("MIS_AUCTION_OBSERVATION_UNAVAILABLE",),
                }
            )
        return AuctionAcquisitionResult(
            summary=summary,
            observations=(observation,) if observation is not None else (),
            receipts=acquired.receipts,
            provider_health=acquired.provider_health,
        )


__all__ = [
    "TwseMisProviderSnapshot",
    "TwseMisRealtimeAcquisitionAdapter",
    "TwseMisSnapshotReader",
]
