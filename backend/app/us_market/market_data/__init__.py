"""US market-owned seams for the shared Market Data Foundation.

This package is intentionally production-unwired until the Shared Core G0
handoff gate passes. It exposes provider descriptors, pure canonical adapters,
provider-neutral candidate reads, and outward projections; it does not execute
fallback, provider I/O, refresh, scheduling, or final evidence selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from app.us_market.market_data.integration_manifest import (
        US_MARKET_DATA_INTEGRATION_MANIFEST,
        CanonicalAdapterRegistration,
        USMarketDataIntegrationManifest,
    )


def __getattr__(name: str) -> Any:
    """Load the manifest lazily so leaf modules can be imported independently."""

    if name not in __all__:
        raise AttributeError(name)
    from app.us_market.market_data import integration_manifest

    value = getattr(integration_manifest, name)
    globals()[name] = value
    return value

__all__ = [
    "CanonicalAdapterRegistration",
    "USMarketDataIntegrationManifest",
    "US_MARKET_DATA_INTEGRATION_MANIFEST",
]
