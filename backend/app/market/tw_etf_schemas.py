from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class TaiwanEtfProfileRead(BaseModel):
    report_date: date | None = None
    fund_short_name: str | None = None
    fund_name: str | None = None
    fund_name_en: str | None = None
    fund_type: str | None = None
    benchmark_name: str | None = None
    is_customized_index: bool | None = None
    investment_scope: str | None = None
    has_performance_benchmark: bool | None = None
    performance_benchmark_name: str | None = None
    has_foreign_components: bool | None = None
    tax_id: str | None = None
    established_date: date | None = None
    listed_date: date | None = None
    fund_manager: str | None = None
    issued_units: int | None = None
    custodian: str | None = None
    issuer_name: str | None = None
    source: str
    source_url: str | None = None
    fetched_at: datetime


class TaiwanEtfNavDailyRead(BaseModel):
    nav_date: date
    issuer_name: str | None = None
    fund_name: str | None = None
    nav: float | None = None
    previous_nav: float | None = None
    nav_change: float | None = None
    nav_change_pct: float | None = None
    close_price: float | None = None
    premium_discount_pct: float | None = None
    benchmark_name: str | None = None
    benchmark_date: date | None = None
    benchmark_close: float | None = None
    benchmark_previous_close: float | None = None
    benchmark_change: float | None = None
    benchmark_change_pct: float | None = None
    source: str
    source_url: str | None = None
    fetched_at: datetime


class TaiwanEtfPcfComponentRead(BaseModel):
    source_section: str
    asset_type: str
    symbol: str
    name: str | None = None
    name_en: str | None = None
    contract_month: str | None = None
    quantity: float | None = None
    weight_pct: float | None = None
    cash_in_lieu: str | None = None
    minimum_creation: bool | None = None
    order_index: int


class TaiwanEtfPcfRead(BaseModel):
    effective_date: date
    reference_date: date | None = None
    fund_id: str | None = None
    fund_name: str | None = None
    full_name: str | None = None
    name_en: str | None = None
    total_net_assets: float | None = None
    issued_units: int | None = None
    unit_nav: float | None = None
    creation_unit: int | None = None
    estimated_creation_value: float | None = None
    estimated_cash_component: float | None = None
    unit_change: int | None = None
    actual_cash_component: float | None = None
    redemption_method: str
    component_count: int = Field(ge=0)
    components: list[TaiwanEtfPcfComponentRead] = Field(default_factory=list)
    source_updated_at: datetime | None = None
    source: str
    source_url: str | None = None
    fetched_at: datetime


class TaiwanEtfInavRead(BaseModel):
    observed_at: datetime
    fund_short_name: str | None = None
    investment_area: str | None = None
    estimated_nav: float
    nav_change: float | None = None
    market_price: float | None = None
    price_change: float | None = None
    premium_discount_pct: float | None = None
    source: str
    source_url: str | None = None
    fetched_at: datetime


class TaiwanEtfValuationMetricRead(BaseModel):
    value: float | None = None
    as_of_date: date | None = None
    observed_at: datetime | None = None
    fetched_at: datetime | None = None
    source: str | None = None
    source_url: str | None = None
    basis: str
    status: str
    issue_codes: list[str] = Field(default_factory=list)


class TaiwanEtfValuationRead(BaseModel):
    status: str
    basis: str
    market_price: TaiwanEtfValuationMetricRead
    nav: TaiwanEtfValuationMetricRead
    premium_discount_pct: float | None = None
    premium_discount_status: str
    aligned: bool = False
    issue_codes: list[str] = Field(default_factory=list)


class TaiwanEtfStrategyRead(BaseModel):
    management_style: str
    benchmark_role: str
    benchmark_name: str | None = None


class TaiwanEtfResourceStateRead(BaseModel):
    applicable: bool | None = None
    connector_supported: bool = False
    status: str
    reason_code: str | None = None
    as_of_date: date | None = None
    observed_at: datetime | None = None
    source: str | None = None


class TaiwanEtfFreshnessRead(BaseModel):
    status: str
    timezone: str = "Asia/Taipei"
    nav_release_time: str = "21:00"
    expected_nav_date: date
    latest_nav_date: date | None = None
    nav_is_current: bool = False
    profile_report_date: date | None = None
    expected_pcf_date: date | None = None
    latest_pcf_date: date | None = None
    pcf_status: str = "not_supported"
    expected_inav_date: date | None = None
    latest_inav_at: datetime | None = None
    inav_status: str = "not_supported"
    inav_age_seconds: int | None = Field(default=None, ge=0)
    session_phase: str | None = None
    refresh_recommended: bool = True
    checked_at: datetime


class TaiwanEtfSourceRead(BaseModel):
    resource: str
    provider: str
    source_url: str
    status: str
    observed_date: date | None = None
    fetched_at: datetime | None = None


class TaiwanEtfRefreshResultRead(BaseModel):
    requested_resources: list[str] = Field(default_factory=list)
    refreshed_resources: list[str] = Field(default_factory=list)
    request_count: int = Field(default=0, ge=0, le=8)
    target_nav_date: date | None = None
    target_pcf_date: date | None = None
    inav_observed_at: datetime | None = None
    errors: dict[str, str] = Field(default_factory=dict)


class TaiwanEtfOverviewRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    market: str
    instrument_type: str = "etf"
    status: str
    capabilities: dict[str, bool]
    profile: TaiwanEtfProfileRead | None = None
    daily_nav: TaiwanEtfNavDailyRead | None = None
    pcf: TaiwanEtfPcfRead | None = None
    intraday_nav: TaiwanEtfInavRead | None = None
    valuation: TaiwanEtfValuationRead
    strategy: TaiwanEtfStrategyRead
    resource_states: dict[str, TaiwanEtfResourceStateRead]
    freshness: TaiwanEtfFreshnessRead
    sources: list[TaiwanEtfSourceRead]
    warnings: list[str] = Field(default_factory=list)
    refresh: TaiwanEtfRefreshResultRead | None = None


class TaiwanEtfRefreshRequest(BaseModel):
    refresh_profile: bool = True
    refresh_nav: bool = True
    refresh_pcf: bool = False
    refresh_inav: bool = False
    target_nav_date: date | None = None
    target_pcf_date: date | None = None
