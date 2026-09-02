"""Massive Indices pure canonical adapter entrypoints."""

from app.us_market.providers.canonical import (
    canonical_massive_index_aggregates_payload as adapt_massive_index_aggregates_payload,
)
from app.us_market.providers.canonical import (
    canonical_massive_index_snapshot_payload as adapt_massive_index_snapshot_payload,
)

__all__ = [
    "adapt_massive_index_aggregates_payload",
    "adapt_massive_index_snapshot_payload",
]
