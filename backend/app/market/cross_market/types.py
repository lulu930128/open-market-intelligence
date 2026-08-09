from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


CANONICAL_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9._-]{2,16}:[A-Z0-9.^_-]{1,40}$")


class CrossMarketBucket(str, Enum):
    DIRECT_EQUIVALENT = "direct_equivalent"
    INDUSTRY_PEER = "industry_peer"
    THEME_SUPPLY_CHAIN = "theme_supply_chain"
    MACRO_MARKET = "macro_market"


class CrossMarketRelationType(str, Enum):
    SAME_EQUITY_DR = "same_equity_dr"
    SECONDARY_LISTING = "secondary_listing"
    INDUSTRY_PEER = "industry_peer"
    SECTOR_PROXY = "sector_proxy"
    SUPPLY_CHAIN_SUPPLIER = "supply_chain_supplier"
    SUPPLY_CHAIN_CUSTOMER = "supply_chain_customer"
    CUSTOMER_DEMAND_PROXY = "customer_demand_proxy"
    END_MARKET_PROXY = "end_market_proxy"
    THEME_PROXY = "theme_proxy"
    MACRO_PROXY = "macro_proxy"


class CrossMarketReviewStatus(str, Enum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class CrossMarketEvidenceGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


RELATION_BUCKET_BY_TYPE = {
    CrossMarketRelationType.SAME_EQUITY_DR.value: CrossMarketBucket.DIRECT_EQUIVALENT.value,
    CrossMarketRelationType.SECONDARY_LISTING.value: CrossMarketBucket.DIRECT_EQUIVALENT.value,
    CrossMarketRelationType.INDUSTRY_PEER.value: CrossMarketBucket.INDUSTRY_PEER.value,
    CrossMarketRelationType.SECTOR_PROXY.value: CrossMarketBucket.INDUSTRY_PEER.value,
    CrossMarketRelationType.SUPPLY_CHAIN_SUPPLIER.value: CrossMarketBucket.THEME_SUPPLY_CHAIN.value,
    CrossMarketRelationType.SUPPLY_CHAIN_CUSTOMER.value: CrossMarketBucket.THEME_SUPPLY_CHAIN.value,
    CrossMarketRelationType.CUSTOMER_DEMAND_PROXY.value: CrossMarketBucket.THEME_SUPPLY_CHAIN.value,
    CrossMarketRelationType.END_MARKET_PROXY.value: CrossMarketBucket.THEME_SUPPLY_CHAIN.value,
    CrossMarketRelationType.THEME_PROXY.value: CrossMarketBucket.THEME_SUPPLY_CHAIN.value,
    CrossMarketRelationType.MACRO_PROXY.value: CrossMarketBucket.MACRO_MARKET.value,
}

DIRECT_RELATION_TYPES = frozenset(
    {
        CrossMarketRelationType.SAME_EQUITY_DR.value,
        CrossMarketRelationType.SECONDARY_LISTING.value,
    }
)

PRODUCTION_EVIDENCE_GRADES = frozenset(
    {
        CrossMarketEvidenceGrade.A.value,
        CrossMarketEvidenceGrade.B.value,
        CrossMarketEvidenceGrade.C.value,
    }
)


def normalize_market(value: str) -> str:
    market = str(value or "").strip().upper()
    if not market or not re.fullmatch(r"[A-Z0-9._-]{2,16}", market):
        raise ValueError("market must be a 2-16 character canonical market code")
    return market


def normalize_instrument_type(value: str) -> str:
    instrument_type = str(value or "").strip().lower()
    if not instrument_type or not re.fullmatch(r"[a-z0-9._-]{2,32}", instrument_type):
        raise ValueError("instrument_type must be a canonical 2-32 character value")
    return instrument_type


def normalize_canonical_symbol(*, market: str, symbol: str) -> str:
    normalized_market = normalize_market(market)
    raw_symbol = str(symbol or "").strip().upper()
    if ":" in raw_symbol:
        canonical_symbol = raw_symbol
    else:
        canonical_symbol = f"{normalized_market}:{raw_symbol}"
    if not CANONICAL_SYMBOL_PATTERN.fullmatch(canonical_symbol):
        raise ValueError("canonical_symbol must use MARKET:SYMBOL format")
    prefix, _separator, _local_symbol = canonical_symbol.partition(":")
    if prefix != normalized_market:
        raise ValueError("canonical_symbol market prefix does not match market")
    return canonical_symbol


@dataclass(frozen=True)
class InstrumentRef:
    market: str
    instrument_type: str
    canonical_symbol: str
    provider_symbol: str | None = None
    exchange: str | None = None
    currency: str | None = None

    @classmethod
    def create(
        cls,
        *,
        market: str,
        instrument_type: str,
        symbol: str,
        provider_symbol: str | None = None,
        exchange: str | None = None,
        currency: str | None = None,
    ) -> "InstrumentRef":
        normalized_market = normalize_market(market)
        return cls(
            market=normalized_market,
            instrument_type=normalize_instrument_type(instrument_type),
            canonical_symbol=normalize_canonical_symbol(
                market=normalized_market,
                symbol=symbol,
            ),
            provider_symbol=(
                str(provider_symbol).strip() or None
                if provider_symbol is not None
                else None
            ),
            exchange=str(exchange).strip().upper() or None if exchange else None,
            currency=str(currency).strip().upper() or None if currency else None,
        )


def taiwan_stock_ref(stock_id: str) -> InstrumentRef:
    normalized = str(stock_id or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,20}", normalized):
        raise ValueError("stock_id must be a 2-20 character Taiwan instrument id")
    return InstrumentRef.create(
        market="TW",
        instrument_type="stock",
        symbol=normalized,
        provider_symbol=normalized,
        currency="TWD",
    )
