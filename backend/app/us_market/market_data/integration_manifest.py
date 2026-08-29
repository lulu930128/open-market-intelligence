"""Declarative US Shared Core production binding and adoption gates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.market_data.contracts import Market
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2
from app.us_market.market_data.adapters import (
    adapt_alpaca_stock_bars_payload,
    adapt_yahoo_chart_payload,
)
from app.us_market.daily_price_candidates import (
    build_us_completed_daily_candidate_reader,
)
from app.us_market.market_data.descriptors import US_DAILY_CANDIDATE_DESCRIPTORS
from app.us_market.market_data.projection import (
    project_resolved_us_bars,
    project_resolved_us_daily_bars,
    project_resolved_us_quote,
)


@dataclass(frozen=True, slots=True)
class CanonicalAdapterRegistration:
    provider_key: str
    capability_ids: tuple[str, ...]
    adapter: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class USMarketDataIntegrationManifest:
    market: Market
    provider_descriptors: tuple[ProviderCapabilityDescriptorV2, ...]
    canonical_adapters: tuple[CanonicalAdapterRegistration, ...]
    candidate_reader: Callable[..., Any]
    resolved_projectors: tuple[Callable[..., dict[str, Any]], ...]
    production_binding_available: bool
    shared_core_contract_version: str | None
    handoff_gate: str
    limitations: tuple[str, ...]


US_MARKET_DATA_INTEGRATION_MANIFEST = USMarketDataIntegrationManifest(
    market=Market.US,
    provider_descriptors=US_DAILY_CANDIDATE_DESCRIPTORS,
    canonical_adapters=(
        CanonicalAdapterRegistration(
            provider_key="yahoo_chart",
            capability_ids=("quote.snapshot", "intraday.bars", "daily.ohlcv"),
            adapter=adapt_yahoo_chart_payload,
        ),
        CanonicalAdapterRegistration(
            provider_key="alpaca",
            capability_ids=("daily.ohlcv",),
            adapter=adapt_alpaca_stock_bars_payload,
        ),
    ),
    candidate_reader=build_us_completed_daily_candidate_reader,
    resolved_projectors=(
        project_resolved_us_quote,
        project_resolved_us_bars,
        project_resolved_us_daily_bars,
    ),
    production_binding_available=True,
    shared_core_contract_version="omi.market.data_requirement.v2",
    handoff_gate="US_DAILY_BACKEND_V1_SOURCE_ACCEPTED",
    limitations=(
        "ALPACA_DAILY_SUPPORTS_STOCK_AND_ETF_ONLY",
        "US_INDEX_DAILY_FALLBACK_REMAINS_YAHOO_ONLY",
        "TWELVE_DATA_QUOTE_INTRADAY_SOURCE_READY_NOT_DAILY_PRODUCTION",
    ),
)


__all__ = [
    "CanonicalAdapterRegistration",
    "USMarketDataIntegrationManifest",
    "US_MARKET_DATA_INTEGRATION_MANIFEST",
]
