"""Declarative US Shared Core production binding and adoption gates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.market_data.contracts import Market
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2
from app.us_market.market_data.adapters import (
    adapt_alpaca_stock_bars_payload,
    adapt_twelve_data_intraday_payload,
    adapt_twelve_data_quote_payload,
    adapt_yahoo_chart_payload,
)
from app.us_market.market_data.descriptors import (
    US_DAILY_CANDIDATE_DESCRIPTORS,
    US_INTRADAY_PROVIDER_DESCRIPTORS,
    US_QUOTE_PROVIDER_DESCRIPTORS,
)
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
class CapabilityIntegrationBinding:
    capability_id: str
    dataset_id: str
    reader_owner: str
    transaction_owner: str
    refresh_operation: str


@dataclass(frozen=True, slots=True)
class USMarketDataIntegrationManifest:
    market: Market
    provider_descriptors: tuple[ProviderCapabilityDescriptorV2, ...]
    canonical_adapters: tuple[CanonicalAdapterRegistration, ...]
    capability_bindings: tuple[CapabilityIntegrationBinding, ...]
    resolved_projectors: tuple[Callable[..., dict[str, Any]], ...]
    production_binding_available: bool
    shared_core_contract_version: str | None
    handoff_gate: str
    limitations: tuple[str, ...]


US_MARKET_DATA_INTEGRATION_MANIFEST = USMarketDataIntegrationManifest(
    market=Market.US,
    provider_descriptors=tuple(
        {
            descriptor.resource_id: descriptor
            for descriptor in (
                *US_DAILY_CANDIDATE_DESCRIPTORS,
                *US_QUOTE_PROVIDER_DESCRIPTORS,
                *US_INTRADAY_PROVIDER_DESCRIPTORS,
            )
        }.values()
    ),
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
        CanonicalAdapterRegistration(
            provider_key="twelve_data",
            capability_ids=("quote.snapshot",),
            adapter=adapt_twelve_data_quote_payload,
        ),
        CanonicalAdapterRegistration(
            provider_key="twelve_data",
            capability_ids=("intraday.bars",),
            adapter=adapt_twelve_data_intraday_payload,
        ),
    ),
    resolved_projectors=(
        project_resolved_us_quote,
        project_resolved_us_bars,
        project_resolved_us_daily_bars,
    ),
    production_binding_available=True,
    shared_core_contract_version="omi.market.data_requirement.v2",
    handoff_gate="US_MARKET_CORE_SOURCE_CHECKPOINT_READY",
    limitations=(
        "ALPACA_DAILY_SUPPORTS_STOCK_AND_ETF_ONLY",
        "US_INDEX_DAILY_FALLBACK_REMAINS_YAHOO_ONLY",
        "US_INTRADAY_MATERIALIZER_FEATURE_OFF_BOUNDED_CANARY_ONLY",
        "US_MATERIALIZER_KEYED_CONCURRENCY_RUNTIME_ACCEPTANCE_PENDING",
        "RUNTIME_ADOPTION_AND_LIVE_PROVIDER_ACCEPTANCE_REMAIN_SEPARATE",
    ),
    capability_bindings=(
        CapabilityIntegrationBinding(
            capability_id="daily.ohlcv",
            dataset_id="us.daily.ohlcv",
            reader_owner="app.us_market.daily_price_candidates.USCompletedDailyCandidateReader",
            transaction_owner="app.us_market.daily_price_transaction.USDailyPriceTransaction",
            refresh_operation="us.refresh_daily_ohlcv",
        ),
        CapabilityIntegrationBinding(
            capability_id="quote.snapshot",
            dataset_id="us.quote.snapshot",
            reader_owner="app.us_market.intraday_repository.USQuoteRepository",
            transaction_owner="app.us_market.intraday_transaction.USQuoteTransaction",
            refresh_operation="us.refresh_quote",
        ),
        CapabilityIntegrationBinding(
            capability_id="intraday.bars",
            dataset_id="us.intraday.bars",
            reader_owner="app.us_market.intraday_repository.USIntradayBarRepository",
            transaction_owner="app.us_market.intraday_transaction.USIntradayBarTransaction",
            refresh_operation="us.refresh_intraday_bars",
        ),
    ),
)


__all__ = [
    "CanonicalAdapterRegistration",
    "CapabilityIntegrationBinding",
    "USMarketDataIntegrationManifest",
    "US_MARKET_DATA_INTEGRATION_MANIFEST",
]
