"""Market-owned capability catalog for Taiwan intraday bar providers."""

from __future__ import annotations

from dataclasses import dataclass

from app.market_data.contracts import AuthorityClass, InstrumentType, Market
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
)


TW_INTRADAY_BARS_CAPABILITY_ID = "intraday.bars"

FUGLE_INTRADAY_PROVIDER = "fugle_marketdata"
FUGLE_INTRADAY_SOURCE = "fugle_candles_stream"
FUGLE_INTRADAY_RESOURCE_ID = "tw.fugle.candles.stream"
FUGLE_INTRADAY_PARSER_VERSION = "fugle.websocket.candles.v1"

KGI_INTRADAY_PROVIDER = "kgi_superpy"
KGI_INTRADAY_SOURCE = "kgi_superpy_minute_kbars"
KGI_INTRADAY_RESOURCE_ID = "tw.kgi.minute_kbars.stream"
KGI_INTRADAY_PARSER_VERSION = "kgi.superpy.minute_kbars.v1"

NSTOCK_INTRADAY_PROVIDER = "nstock"
NSTOCK_INTRADAY_SOURCE = "nstock_minute_stock_data"
NSTOCK_INTRADAY_RESOURCE_ID = "tw.nstock.minute.bars"
NSTOCK_INTRADAY_PARSER_VERSION = "nstock.minute-stock-data.v1"

YAHOO_INTRADAY_PROVIDER = "yahoo_finance_chart"
YAHOO_INTRADAY_SOURCE = "yahoo_finance_chart"
YAHOO_INTRADAY_RESOURCE_ID = "tw.yahoo.chart.intraday"
YAHOO_INTRADAY_PARSER_VERSION = "yahoo.chart.v8.intraday.v1"


NSTOCK_INTRADAY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=NSTOCK_INTRADAY_PROVIDER,
    market=Market.TW,
    capability_id=TW_INTRADAY_BARS_CAPABILITY_ID,
    resource_id=NSTOCK_INTRADAY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    venue_scope=("TWSE", "TPEX"),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    intervals=("1m",),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=10,
    can_produce_live=True,
    can_produce_final=False,
    max_timeout_seconds=20,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=1,
    health_ttl_seconds=60,
    allow_unknown_health=True,
    limitations=("CURRENT_SESSION_ONLY", "VENDOR_BEST_EFFORT"),
)

FUGLE_INTRADAY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=FUGLE_INTRADAY_PROVIDER,
    market=Market.TW,
    capability_id=TW_INTRADAY_BARS_CAPABILITY_ID,
    resource_id=FUGLE_INTRADAY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    venue_scope=("TWSE", "TPEX"),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    intervals=("1m",),
    acquisition_modes=(AcquisitionMode.SUBSCRIPTION,),
    priority=5,
    can_produce_live=True,
    can_produce_final=False,
    max_timeout_seconds=20,
    max_external_calls_per_attempt=0,
    max_subscriptions_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=1,
    health_ttl_seconds=30,
    allow_unknown_health=True,
    allow_disconnected_connect=True,
    limitations=(
        "API_KEY_REQUIRED",
        "ACTIVE_STOCK_ONLY",
        "BASIC_PLAN_ONE_CONNECTION_FIVE_SUBSCRIPTIONS",
        "BOARD_LOTS_CONVERTED_TO_SHARES",
        "BACKGROUND_MATERIALIZATION_REQUIRED",
    ),
)

KGI_INTRADAY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=KGI_INTRADAY_PROVIDER,
    market=Market.TW,
    capability_id=TW_INTRADAY_BARS_CAPABILITY_ID,
    resource_id=KGI_INTRADAY_RESOURCE_ID,
    authority=AuthorityClass.BROKER,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    venue_scope=("TWSE", "TPEX"),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    intervals=("1m",),
    acquisition_modes=(AcquisitionMode.SUBSCRIPTION,),
    priority=8,
    can_produce_live=True,
    can_produce_final=True,
    max_timeout_seconds=5,
    max_external_calls_per_attempt=0,
    max_subscriptions_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=1,
    health_ttl_seconds=30,
    allow_unknown_health=True,
    limitations=(
        "ACTIVE_KGI_LEASE_REQUIRED",
        "MATERIALIZED_FROM_BOUNDED_STREAM_BUFFER",
        "BROKER_AUTHORITY",
    ),
)

YAHOO_INTRADAY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=YAHOO_INTRADAY_PROVIDER,
    market=Market.TW,
    capability_id=TW_INTRADAY_BARS_CAPABILITY_ID,
    resource_id=YAHOO_INTRADAY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    venue_scope=("TWSE", "TPEX"),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    intervals=("1m", "5m", "15m", "30m", "1h", "4h"),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=20,
    can_produce_live=False,
    can_produce_final=False,
    max_timeout_seconds=20,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=93,
    health_ttl_seconds=300,
    allow_unknown_health=True,
    limitations=("VENDOR_DELAY_POSSIBLE", "PROVIDER_DEFAULT_ADJUSTMENT"),
)

TW_INTRADAY_DESCRIPTORS = (
    FUGLE_INTRADAY_DESCRIPTOR,
    KGI_INTRADAY_DESCRIPTOR,
    NSTOCK_INTRADAY_DESCRIPTOR,
    YAHOO_INTRADAY_DESCRIPTOR,
)


@dataclass(frozen=True, slots=True)
class TaiwanIntradaySourceBinding:
    descriptor: ProviderCapabilityDescriptorV2
    source: str
    parser_version: str
    source_type: str = "api"
    auth_type: str = "none"
    reliability_level: str = "vendor"


_BINDINGS = (
    TaiwanIntradaySourceBinding(
        descriptor=FUGLE_INTRADAY_DESCRIPTOR,
        source=FUGLE_INTRADAY_SOURCE,
        parser_version=FUGLE_INTRADAY_PARSER_VERSION,
        source_type="stream",
        auth_type="api_key",
        reliability_level="vendor",
    ),
    TaiwanIntradaySourceBinding(
        descriptor=KGI_INTRADAY_DESCRIPTOR,
        source=KGI_INTRADAY_SOURCE,
        parser_version=KGI_INTRADAY_PARSER_VERSION,
        source_type="stream",
        auth_type="broker_credentials",
        reliability_level="broker",
    ),
    TaiwanIntradaySourceBinding(
        descriptor=NSTOCK_INTRADAY_DESCRIPTOR,
        source=NSTOCK_INTRADAY_SOURCE,
        parser_version=NSTOCK_INTRADAY_PARSER_VERSION,
    ),
    TaiwanIntradaySourceBinding(
        descriptor=YAHOO_INTRADAY_DESCRIPTOR,
        source=YAHOO_INTRADAY_SOURCE,
        parser_version=YAHOO_INTRADAY_PARSER_VERSION,
    ),
)


def intraday_source_binding(
    *,
    provider: str,
    source: str,
    resource_id: str | None = None,
) -> TaiwanIntradaySourceBinding | None:
    for binding in _BINDINGS:
        if (
            binding.descriptor.provider_key == provider
            and binding.source == source
            and (
                resource_id is None
                or binding.descriptor.resource_id == resource_id
            )
        ):
            return binding
    return None


__all__ = [
    "FUGLE_INTRADAY_DESCRIPTOR",
    "FUGLE_INTRADAY_PARSER_VERSION",
    "FUGLE_INTRADAY_PROVIDER",
    "FUGLE_INTRADAY_RESOURCE_ID",
    "FUGLE_INTRADAY_SOURCE",
    "KGI_INTRADAY_DESCRIPTOR",
    "KGI_INTRADAY_PARSER_VERSION",
    "KGI_INTRADAY_PROVIDER",
    "KGI_INTRADAY_RESOURCE_ID",
    "KGI_INTRADAY_SOURCE",
    "NSTOCK_INTRADAY_DESCRIPTOR",
    "NSTOCK_INTRADAY_PARSER_VERSION",
    "NSTOCK_INTRADAY_PROVIDER",
    "NSTOCK_INTRADAY_RESOURCE_ID",
    "NSTOCK_INTRADAY_SOURCE",
    "TW_INTRADAY_BARS_CAPABILITY_ID",
    "TW_INTRADAY_DESCRIPTORS",
    "TaiwanIntradaySourceBinding",
    "YAHOO_INTRADAY_DESCRIPTOR",
    "YAHOO_INTRADAY_PARSER_VERSION",
    "YAHOO_INTRADAY_PROVIDER",
    "YAHOO_INTRADAY_RESOURCE_ID",
    "YAHOO_INTRADAY_SOURCE",
    "intraday_source_binding",
]
