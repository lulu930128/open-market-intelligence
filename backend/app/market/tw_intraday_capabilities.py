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
