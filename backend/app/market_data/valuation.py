"""Provider-neutral cached valuation price contract."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from app.market_data.contracts import CanonicalModel, Market


class ValuationPriceEvidence(CanonicalModel):
    contract_version: str = "omi.market.valuation_price.v1"
    market: Market
    symbol: str
    price: Decimal | None = None
    currency: str
    as_of: date | datetime | None = None
    provider: str | None = None
    source: str | None = None
    source_kind: str
    facts_usable: bool = False
    research_usable: bool = False
    resolved_status: str
    limitations: tuple[str, ...] = ()


class ValuationPriceReader(Protocol):
    def __call__(
        self,
        db: Any,
        *,
        market: str,
        symbol: str,
        requested_at: datetime,
    ) -> ValuationPriceEvidence: ...


__all__ = ["ValuationPriceEvidence", "ValuationPriceReader"]
