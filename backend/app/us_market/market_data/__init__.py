"""US market-owned seams for the shared Market Data Foundation.

This package is intentionally production-unwired until the Shared Core G0
handoff gate passes. It exposes provider descriptors, pure canonical adapters,
provider-neutral candidate reads, and outward projections; it does not execute
fallback, provider I/O, refresh, scheduling, or final evidence selection.
"""

from app.us_market.market_data.integration_manifest import (
    US_MARKET_DATA_INTEGRATION_MANIFEST,
    CanonicalAdapterRegistration,
    USMarketDataIntegrationManifest,
)

__all__ = [
    "CanonicalAdapterRegistration",
    "USMarketDataIntegrationManifest",
    "US_MARKET_DATA_INTEGRATION_MANIFEST",
]
