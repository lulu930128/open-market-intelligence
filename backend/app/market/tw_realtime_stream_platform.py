"""Cache-only Taiwan realtime stream compatibility projection."""

from __future__ import annotations

from typing import Protocol

from app.market.providers.kgi_canonical import KGI_PROVIDER
from app.market.providers.kgi_realtime_lease import KgiRealtimeQuoteLeasePort
from app.market.tw_realtime_capabilities import KGI_QUOTE_SNAPSHOT_DESCRIPTOR
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2


class TaiwanRealtimeStreamPort(Protocol):
    @property
    def provider_key(self) -> str: ...

    def market_stream_snapshot(
        self,
        stock_id: str,
        *,
        recent_trade_limit: int,
        auction_limit: int,
        kbar_limit: int,
        diagnostic_limit: int,
    ) -> dict: ...


_KGI_STREAM_PORT = KgiRealtimeQuoteLeasePort()
_STREAM_DESCRIPTORS = (KGI_QUOTE_SNAPSHOT_DESCRIPTOR,)
_STREAM_PORTS: dict[str, TaiwanRealtimeStreamPort] = {
    KGI_PROVIDER: _KGI_STREAM_PORT,
}

_PRESENTATION_TELEMETRY_CONTRACT = {
    "projection_scope": "presentation_only",
    "canonical_truth": False,
    "decision_usable": False,
    "research_usable": False,
    "provider_specific": True,
}


def read_taiwan_realtime_market_stream(
    stock_id: str,
    *,
    recent_trade_limit: int = 40,
    auction_limit: int = 40,
    kbar_limit: int = 60,
    diagnostic_limit: int = 0,
    descriptors: tuple[ProviderCapabilityDescriptorV2, ...] = _STREAM_DESCRIPTORS,
    ports: dict[str, TaiwanRealtimeStreamPort] = _STREAM_PORTS,
) -> dict:
    normalized = str(stock_id or "").strip().upper()
    if not normalized:
        raise ValueError("stock_id is required")
    candidates = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.provider_key in ports
        and descriptor.capability_id == KGI_QUOTE_SNAPSHOT_DESCRIPTOR.capability_id
        and descriptor.can_produce_live
    )
    if not candidates:
        raise ValueError("Taiwan realtime stream projection has no registered port")
    descriptor = min(
        candidates,
        key=lambda item: (item.priority, item.provider_key, item.resource_id),
    )
    payload = ports[descriptor.provider_key].market_stream_snapshot(
        normalized,
        recent_trade_limit=recent_trade_limit,
        auction_limit=auction_limit,
        kbar_limit=kbar_limit,
        diagnostic_limit=diagnostic_limit,
    )
    if not isinstance(payload, dict):
        raise ValueError("Taiwan realtime stream port returned a non-object payload")
    return {
        **payload,
        **_PRESENTATION_TELEMETRY_CONTRACT,
    }


__all__ = ["TaiwanRealtimeStreamPort", "read_taiwan_realtime_market_stream"]
