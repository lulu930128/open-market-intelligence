"""Executable Japanese daily provider policy. No IO or database ownership."""

from app.market_data.contracts import AuthorityClass, InstrumentType, Market, MarketSession
from app.market_data.provider_catalog import (
    AcquisitionMode, DescriptorTargetKind, ProviderCapabilityDescriptorV2,
)


JP_DAILY_DESCRIPTORS = (
    ProviderCapabilityDescriptorV2(
        provider_key="jquants", market=Market.JP, capability_id="daily.ohlcv",
        resource_id="jquants.jp.daily", authority=AuthorityClass.EXCHANGE,
        target_kinds=(DescriptorTargetKind.INSTRUMENT,), venue_scope=("XJPX",),
        instrument_types=(InstrumentType.STOCK, InstrumentType.ETF), intervals=("1d",),
        supported_sessions=(MarketSession.CLOSED,), acquisition_modes=(AcquisitionMode.FETCH,),
        priority=10, can_produce_live=False, can_produce_final=True,
        max_external_calls_per_attempt=1, max_range_days=3650, allow_unknown_health=True,
        limitations=("ENTITLEMENT_REQUIRED", "COMPLETED_SESSION_ONLY"),
    ),
    ProviderCapabilityDescriptorV2(
        provider_key="yahoo_chart", market=Market.JP, capability_id="daily.ohlcv",
        resource_id="yahoo.jp.daily", authority=AuthorityClass.VENDOR,
        target_kinds=(DescriptorTargetKind.INSTRUMENT,), venue_scope=("XJPX",),
        instrument_types=(InstrumentType.STOCK, InstrumentType.ETF, InstrumentType.INDEX),
        intervals=("1d",), supported_sessions=(MarketSession.CLOSED,),
        acquisition_modes=(AcquisitionMode.FETCH,), priority=100,
        can_produce_live=False, can_produce_final=True, max_range_days=3650, allow_unknown_health=True,
        limitations=("VENDOR_COMPLETED_DAILY",),
    ),
)


def daily_descriptor(provider: str) -> ProviderCapabilityDescriptorV2:
    for descriptor in JP_DAILY_DESCRIPTORS:
        if descriptor.provider_key == provider:
            return descriptor
    raise ValueError(f"Unregistered JP daily provider: {provider}")
