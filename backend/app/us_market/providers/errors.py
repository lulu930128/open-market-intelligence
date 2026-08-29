"""Typed, secret-safe failures raised by US provider adapters."""

from __future__ import annotations

from app.us_market.errors import USMarketDataFetchError


class USProviderDataError(USMarketDataFetchError):
    def __init__(
        self,
        *,
        provider: str,
        code: str,
        category: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.category = category


__all__ = ["USProviderDataError"]
