"""Executable KR provider capability policy, never imported by Shared Core."""

from app.market_data.contracts import AuthorityClass, InstrumentType, Market, MarketSession
from app.market_data.provider_catalog import (
    AcquisitionMode, DescriptorTargetKind, ProviderCapabilityDescriptorV2,
)


KR_DAILY_PARSER_VERSION = "kr.canonical.daily.v1"

KR_DAILY_DESCRIPTORS = tuple(
    ProviderCapabilityDescriptorV2(
        provider_key=provider, market=Market.KR, capability_id="daily.ohlcv",
        resource_id=f"{provider}.kr.daily", authority=authority,
        target_kinds=(DescriptorTargetKind.INSTRUMENT,), venue_scope=("KRX",),
        instrument_types=(InstrumentType.STOCK, InstrumentType.ETF), intervals=("1d",),
        supported_sessions=(MarketSession.CLOSED,), acquisition_modes=(AcquisitionMode.FETCH,),
        priority=priority, can_produce_live=False, can_produce_final=True,
        max_timeout_seconds=15, max_external_calls_per_attempt=1,
        max_range_days=3650, allow_unknown_health=True,
        limitations=("KR_REGULAR_SESSION_ONLY", "KR_PROVIDER_VENUE_COVERAGE_UNVERIFIED"),
    )
    for provider, authority, priority in (
        ("krx_data", AuthorityClass.EXCHANGE, 10),
        ("yahoo_chart", AuthorityClass.VENDOR, 20),
    )
)

KR_DAILY_DESCRIPTOR_BY_PROVIDER = {item.provider_key: item for item in KR_DAILY_DESCRIPTORS}
