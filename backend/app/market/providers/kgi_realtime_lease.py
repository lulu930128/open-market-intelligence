"""KGI implementation port for the shared persistent viewer-lease owner."""

from __future__ import annotations

from app.market.providers.kgi_canonical import KGI_PROVIDER
from app.market.providers.kgi_superpy import (
    acquire_kgi_superpy_quote_lease,
    get_kgi_superpy_quote_lease_summary,
    get_kgi_superpy_quote_runtime_status,
    get_kgi_superpy_quote_snapshot,
    get_kgi_superpy_market_stream_snapshot,
    heartbeat_kgi_superpy_quote_lease,
    release_kgi_superpy_quote_lease,
)
from app.market.providers.kgi_realtime_acquisition import (
    KgiRealtimeAcquisitionAdapter,
    KgiRealtimeProviderSnapshot,
)
from app.market_data.contracts import (
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    OperationalStatus,
    ProviderResourceHealth,
)
from app.market_data.integration_contracts import DataRequirementV2, InstrumentTarget
from app.market_data.provider_catalog import ProviderResourceRouteV2
from app.market_data.research_lease import (
    ViewerLeaseOwnerKind,
    ViewerLeasePortSummary,
    ViewerLeaseState,
)


class KgiRealtimeQuoteLeasePort:
    @property
    def provider_key(self) -> str:
        return KGI_PROVIDER

    def health(self, requirement: DataRequirementV2) -> ProviderResourceHealth:
        status = get_kgi_superpy_quote_runtime_status()
        enabled = bool(status.get("enabled"))
        configured = bool(status.get("configured"))
        running = bool(status.get("process_running"))
        return ProviderResourceHealth(
            provider=KGI_PROVIDER,
            market=requirement.target.instrument.market,
            capability=requirement.request.capability_id,
            enablement=(
                EnablementStatus.ENABLED if enabled else EnablementStatus.DISABLED
            ),
            connection=(
                ConnectionStatus.CONNECTED
                if running
                else ConnectionStatus.DISCONNECTED
                if enabled
                else ConnectionStatus.NOT_APPLICABLE
            ),
            entitlement=(
                EntitlementStatus.UNKNOWN
            ),
            operational=(
                OperationalStatus.HEALTHY
                if configured
                else OperationalStatus.UNAVAILABLE
            ),
            freshness=(
                EvidenceFreshness.LIVE if running else EvidenceFreshness.MISSING
            ),
            checked_at=requirement.requested_at,
            detail_code=str(status.get("status") or "UNKNOWN").upper(),
        )

    def acquire(
        self,
        requirement: DataRequirementV2,
        route: ProviderResourceRouteV2,
        *,
        owner_kind: ViewerLeaseOwnerKind,
    ) -> ViewerLeaseState:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("KGI viewer lease requires instrument target")
        if route.provider_key != self.provider_key or not route.subscription_allowed:
            raise ValueError("KGI viewer lease received an invalid shared route")
        return ViewerLeaseState.model_validate(
            acquire_kgi_superpy_quote_lease(
                requirement.target.instrument.symbol,
                owner_kind=owner_kind,
            )
        )

    def heartbeat(self, lease_id: str) -> ViewerLeaseState | None:
        state = heartbeat_kgi_superpy_quote_lease(lease_id)
        return ViewerLeaseState.model_validate(state) if state is not None else None

    def release(self, lease_id: str) -> ViewerLeaseState | None:
        state = release_kgi_superpy_quote_lease(lease_id)
        return ViewerLeaseState.model_validate(state) if state is not None else None

    def summary(self) -> ViewerLeasePortSummary:
        return ViewerLeasePortSummary.model_validate(
            get_kgi_superpy_quote_lease_summary()
        )

    def acquisition_adapter(self, *, clock) -> KgiRealtimeAcquisitionAdapter:
        def read_snapshot(symbol: str) -> KgiRealtimeProviderSnapshot:
            snapshot = get_kgi_superpy_quote_snapshot(symbol)
            return KgiRealtimeProviderSnapshot(
                quote=snapshot.quote,
                status=snapshot.status,
                error=snapshot.error,
            )

        return KgiRealtimeAcquisitionAdapter(read_snapshot, clock=clock)

    def market_stream_snapshot(
        self,
        stock_id: str,
        *,
        recent_trade_limit: int = 40,
        auction_limit: int = 40,
        kbar_limit: int = 60,
        diagnostic_limit: int = 0,
    ) -> dict:
        return get_kgi_superpy_market_stream_snapshot(
            stock_id,
            recent_trade_limit=recent_trade_limit,
            auction_limit=auction_limit,
            kbar_limit=kbar_limit,
            diagnostic_limit=diagnostic_limit,
        )


__all__ = ["KgiRealtimeQuoteLeasePort"]
