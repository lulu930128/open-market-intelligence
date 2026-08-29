"""Typed errors owned by the Shared Market Data Foundation."""

from __future__ import annotations


class MarketDataContractError(ValueError):
    """Internal canonical/resolution invariant violation.

    This remains a ``ValueError`` subclass for compatibility with existing
    pure-contract callers, but transport layers must classify it as an
    internal service failure rather than a client parameter error.
    """

    code = "MARKET_DATA_CONTRACT_VIOLATION"


__all__ = ["MarketDataContractError"]
