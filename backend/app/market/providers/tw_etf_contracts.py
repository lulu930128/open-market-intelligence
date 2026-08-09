from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class TaiwanEtfPcfComponentRecord:
    source_section: str
    asset_type: str
    symbol: str
    name: str | None
    name_en: str | None
    contract_month: str | None
    quantity: Decimal | None
    weight_pct: Decimal | None
    cash_in_lieu: str | None
    minimum_creation: bool | None
    order_index: int


@dataclass(frozen=True)
class TaiwanEtfPcfRecord:
    stock_id: str
    fund_id: str | None
    fund_name: str | None
    full_name: str | None
    name_en: str | None
    reference_date: date | None
    effective_date: date
    total_net_assets: Decimal | None
    issued_units: int | None
    unit_nav: Decimal | None
    creation_unit: int | None
    estimated_creation_value: Decimal | None
    estimated_cash_component: Decimal | None
    unit_change: int | None
    actual_cash_component: Decimal | None
    redemption_method: str
    source_updated_at: datetime | None
    components: tuple[TaiwanEtfPcfComponentRecord, ...]


@dataclass(frozen=True)
class TaiwanEtfInavRecord:
    stock_id: str
    fund_short_name: str | None
    investment_area: str | None
    estimated_nav: Decimal
    nav_change: Decimal | None
    market_price: Decimal | None
    price_change: Decimal | None
    premium_discount_pct: Decimal | None
    observed_at: datetime


TaiwanEtfPcfFetcher = Callable[..., TaiwanEtfPcfRecord]
TaiwanEtfInavFetcher = Callable[[str], TaiwanEtfInavRecord]
ETF_ISSUER_RESOURCE_REQUEST_LIMIT = 6


@dataclass(frozen=True)
class TaiwanEtfPcfProviderResource:
    source_url: str
    request_count: int
    fetch: TaiwanEtfPcfFetcher
    includes_component_exposure: bool = False
    unit_nav_is_daily_nav: bool = False

    def __post_init__(self) -> None:
        if self.request_count < 1:
            raise ValueError("ETF PCF provider request_count must be positive.")

    def source_url_for(self, stock_id: str) -> str:
        return self.source_url.format(stock_id=stock_id.strip().upper())


@dataclass(frozen=True)
class TaiwanEtfInavProviderResource:
    source_url: str
    request_count: int
    fetch: TaiwanEtfInavFetcher

    def __post_init__(self) -> None:
        if self.request_count < 1:
            raise ValueError("ETF iNAV provider request_count must be positive.")

    def source_url_for(self, stock_id: str) -> str:
        return self.source_url.format(stock_id=stock_id.strip().upper())


@dataclass(frozen=True)
class TaiwanEtfInstrumentIdentity:
    stock_id: str
    market: str
    issuer_code: str | None = None
    issuer_name: str | None = None
    stock_name: str | None = None
    fund_short_name: str | None = None
    fund_name: str | None = None
    fund_name_en: str | None = None

    def name_candidates(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (
                self.issuer_name,
                self.stock_name,
                self.fund_short_name,
                self.fund_name,
                self.fund_name_en,
            )
            if value
        )


@dataclass(frozen=True)
class TaiwanEtfProviderBinding:
    provider: str
    issuer_codes: frozenset[str]
    issuer_aliases: tuple[str, ...]
    markets: frozenset[str]
    pcf: TaiwanEtfPcfProviderResource | None = None
    intraday_nav: TaiwanEtfInavProviderResource | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("ETF provider id must not be empty.")
        if not self.issuer_codes and not self.issuer_aliases:
            raise ValueError("ETF provider binding requires an issuer identity.")
        if self.pcf is None and self.intraday_nav is None:
            raise ValueError("ETF provider binding requires at least one resource.")
        resource_request_count = sum(
            resource.request_count
            for resource in (self.pcf, self.intraday_nav)
            if resource is not None
        )
        if resource_request_count > ETF_ISSUER_RESOURCE_REQUEST_LIMIT:
            raise ValueError(
                "ETF issuer resource request_count exceeds the bounded refresh budget."
            )

    def supports_market(self, market: str) -> bool:
        return market.strip().upper() in self.markets
