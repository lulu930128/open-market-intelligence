"""Market-owned Taiwan realtime provider capability descriptors.

The shared market-data core consumes these descriptors without importing or
special-casing KGI SuperPy or TWSE MIS. Provider adapters remain responsible for
I/O and canonical conversion only.
"""

from dataclasses import dataclass

from app.market.providers.kgi_canonical import (
    KGI_PROVIDER,
    KGI_RAW_CONTRACT_VERSION,
    KGI_SOURCE,
)
from app.market.providers.tw_public_quote import (
    TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,
    TWSE_MIS_QUOTE_PARSER_VERSION,
)
from app.market.providers.twse_mis_canonical import MIS_PROVIDER, MIS_SOURCE
from app.market.tw_public_quote_contract import (
    TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
)
from app.market_data.contracts import (
    AuthorityClass,
    InstrumentType,
    Market,
    MarketSession,
)
from app.market_data.provider_catalog import (
    AcquisitionMode,
    DescriptorTargetKind,
    ProviderCapabilityDescriptorV2,
)


TW_QUOTE_SNAPSHOT_CAPABILITY_ID = TW_PUBLIC_LAST_TRADE_CAPABILITY_ID
TW_ORDER_BOOK_CAPABILITY_ID = "quote.order_book"
TW_AUCTION_CAPABILITY_ID = "quote.auction"
TW_ORDER_BOOK_DATASET_ID = "tw.quote.order_book.snapshot"
TW_AUCTION_DATASET_ID = "tw.quote.auction.snapshot"

KGI_QUOTE_RESOURCE_ID = "kgi_superpy.quote.snapshot"
KGI_ORDER_BOOK_RESOURCE_ID = "kgi_superpy.quote.order_book"
KGI_AUCTION_RESOURCE_ID = "kgi_superpy.auction"
MIS_ORDER_BOOK_RESOURCE_ID = "twse_mis.order_book"
MIS_AUCTION_RESOURCE_ID = "twse_mis.auction"
FUGLE_QUOTE_RESOURCE_ID = "tw.fugle.aggregates.stream"
FUGLE_PROVIDER = "fugle_marketdata"
FUGLE_QUOTE_SOURCE = "fugle_aggregates_stream"
FUGLE_QUOTE_PARSER_VERSION = "fugle.websocket.aggregates.v1"

_TW_INSTRUMENT_TYPES = (InstrumentType.STOCK, InstrumentType.ETF)
_TW_VENUES = ("TWSE", "TPEX")
_ACTIVE_QUOTE_SESSIONS = (
    MarketSession.PRE_OPEN,
    MarketSession.OPENING_AUCTION,
    MarketSession.CONTINUOUS,
    MarketSession.CLOSING_AUCTION,
)
_AUCTION_SESSIONS = (
    MarketSession.OPENING_AUCTION,
    MarketSession.CONTINUOUS,
    MarketSession.CLOSING_AUCTION,
)


def _kgi_descriptor(
    *,
    capability_id: str,
    resource_id: str,
    sessions: tuple[MarketSession, ...],
    limitations: tuple[str, ...],
) -> ProviderCapabilityDescriptorV2:
    return ProviderCapabilityDescriptorV2(
        provider_key=KGI_PROVIDER,
        market=Market.TW,
        capability_id=capability_id,
        resource_id=resource_id,
        authority=AuthorityClass.BROKER,
        target_kinds=(DescriptorTargetKind.INSTRUMENT,),
        venue_scope=_TW_VENUES,
        instrument_types=_TW_INSTRUMENT_TYPES,
        supported_sessions=sessions,
        acquisition_modes=(AcquisitionMode.SUBSCRIPTION,),
        priority=5,
        can_produce_live=True,
        can_produce_final=False,
        max_timeout_seconds=45,
        max_external_calls_per_attempt=0,
        max_subscriptions_per_attempt=1,
        max_symbols_per_call=1,
        max_range_days=1,
        health_ttl_seconds=30,
        allow_unknown_health=True,
        allow_disconnected_connect=True,
        limitations=limitations,
    )


def _mis_descriptor(
    *,
    capability_id: str,
    resource_id: str,
    sessions: tuple[MarketSession, ...],
    limitations: tuple[str, ...],
) -> ProviderCapabilityDescriptorV2:
    return ProviderCapabilityDescriptorV2(
        provider_key=MIS_PROVIDER,
        market=Market.TW,
        capability_id=capability_id,
        resource_id=resource_id,
        authority=AuthorityClass.EXCHANGE,
        target_kinds=(DescriptorTargetKind.INSTRUMENT,),
        venue_scope=_TW_VENUES,
        instrument_types=_TW_INSTRUMENT_TYPES,
        supported_sessions=sessions,
        acquisition_modes=(AcquisitionMode.FETCH,),
        priority=20,
        can_produce_live=True,
        can_produce_final=False,
        max_timeout_seconds=10,
        max_external_calls_per_attempt=1,
        max_subscriptions_per_attempt=0,
        max_symbols_per_call=1,
        max_range_days=1,
        health_ttl_seconds=30,
        allow_unknown_health=True,
        limitations=limitations,
    )


KGI_QUOTE_SNAPSHOT_DESCRIPTOR = _kgi_descriptor(
    capability_id=TW_QUOTE_SNAPSHOT_CAPABILITY_ID,
    resource_id=KGI_QUOTE_RESOURCE_ID,
    sessions=_ACTIVE_QUOTE_SESSIONS,
    limitations=(
        "ENTITLEMENT_REQUIRED",
        "ACTIVE_LEASE_REQUIRED",
        "ROUND_LOT_ONLY",
    ),
)
FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key=FUGLE_PROVIDER,
    market=Market.TW,
    capability_id=TW_QUOTE_SNAPSHOT_CAPABILITY_ID,
    resource_id=FUGLE_QUOTE_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    venue_scope=("TWSE",),
    instrument_types=_TW_INSTRUMENT_TYPES,
    supported_sessions=_ACTIVE_QUOTE_SESSIONS,
    acquisition_modes=(AcquisitionMode.SUBSCRIPTION,),
    priority=10,
    can_produce_live=True,
    can_produce_final=False,
    max_timeout_seconds=30,
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
        "ROUND_LOT_ONLY",
        "BACKGROUND_MATERIALIZATION_REQUIRED",
    ),
)
KGI_ORDER_BOOK_DESCRIPTOR = _kgi_descriptor(
    capability_id=TW_ORDER_BOOK_CAPABILITY_ID,
    resource_id=KGI_ORDER_BOOK_RESOURCE_ID,
    sessions=_ACTIVE_QUOTE_SESSIONS,
    limitations=(
        "ENTITLEMENT_REQUIRED",
        "ACTIVE_LEASE_REQUIRED",
        "LEVEL_5_MAXIMUM",
        "ROUND_LOT_ONLY",
    ),
)
KGI_AUCTION_DESCRIPTOR = _kgi_descriptor(
    capability_id=TW_AUCTION_CAPABILITY_ID,
    resource_id=KGI_AUCTION_RESOURCE_ID,
    sessions=_AUCTION_SESSIONS,
    limitations=(
        "ENTITLEMENT_REQUIRED",
        "ACTIVE_LEASE_REQUIRED",
        "INDICATIVE_NOT_ACTUAL_TRADE",
    ),
)
MIS_ORDER_BOOK_DESCRIPTOR = _mis_descriptor(
    capability_id=TW_ORDER_BOOK_CAPABILITY_ID,
    resource_id=MIS_ORDER_BOOK_RESOURCE_ID,
    sessions=_ACTIVE_QUOTE_SESSIONS,
    limitations=(
        "PUBLIC_BEST_EFFORT_NO_SLA",
        "LEVEL_5_MAXIMUM",
        "SINGLE_SYMBOL_ONLY",
    ),
)
MIS_AUCTION_DESCRIPTOR = _mis_descriptor(
    capability_id=TW_AUCTION_CAPABILITY_ID,
    resource_id=MIS_AUCTION_RESOURCE_ID,
    sessions=_AUCTION_SESSIONS,
    limitations=(
        "PUBLIC_BEST_EFFORT_NO_SLA",
        "INDICATIVE_NOT_ACTUAL_TRADE",
        "SINGLE_SYMBOL_ONLY",
    ),
)

TW_REALTIME_PROVIDER_DESCRIPTORS = (
    KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
    KGI_ORDER_BOOK_DESCRIPTOR,
    KGI_AUCTION_DESCRIPTOR,
    FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR,
    TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,
    MIS_ORDER_BOOK_DESCRIPTOR,
    MIS_AUCTION_DESCRIPTOR,
)


@dataclass(frozen=True, slots=True)
class TaiwanRealtimeSourceBinding:
    descriptor: ProviderCapabilityDescriptorV2
    source: str
    parser_version: str
    source_type: str
    auth_type: str
    reliability_level: str


TW_REALTIME_SOURCE_BINDINGS = (
    TaiwanRealtimeSourceBinding(
        descriptor=FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR,
        source=FUGLE_QUOTE_SOURCE,
        parser_version=FUGLE_QUOTE_PARSER_VERSION,
        source_type="stream",
        auth_type="api_key",
        reliability_level="vendor",
    ),
    TaiwanRealtimeSourceBinding(
        descriptor=KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
        source=KGI_SOURCE,
        parser_version=KGI_RAW_CONTRACT_VERSION,
        source_type="stream",
        auth_type="broker_credentials",
        reliability_level="broker",
    ),
    TaiwanRealtimeSourceBinding(
        descriptor=KGI_ORDER_BOOK_DESCRIPTOR,
        source=KGI_SOURCE,
        parser_version=KGI_RAW_CONTRACT_VERSION,
        source_type="stream",
        auth_type="broker_credentials",
        reliability_level="broker",
    ),
    TaiwanRealtimeSourceBinding(
        descriptor=KGI_AUCTION_DESCRIPTOR,
        source=KGI_SOURCE,
        parser_version=KGI_RAW_CONTRACT_VERSION,
        source_type="stream",
        auth_type="broker_credentials",
        reliability_level="broker",
    ),
    TaiwanRealtimeSourceBinding(
        descriptor=TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,
        source=MIS_SOURCE,
        parser_version=TWSE_MIS_QUOTE_PARSER_VERSION,
        source_type="api",
        auth_type="none",
        reliability_level="official",
    ),
    TaiwanRealtimeSourceBinding(
        descriptor=MIS_ORDER_BOOK_DESCRIPTOR,
        source=MIS_SOURCE,
        parser_version=TWSE_MIS_QUOTE_PARSER_VERSION,
        source_type="api",
        auth_type="none",
        reliability_level="official",
    ),
    TaiwanRealtimeSourceBinding(
        descriptor=MIS_AUCTION_DESCRIPTOR,
        source=MIS_SOURCE,
        parser_version=TWSE_MIS_QUOTE_PARSER_VERSION,
        source_type="api",
        auth_type="none",
        reliability_level="official",
    ),
)


def realtime_source_binding(
    *,
    provider: str,
    source: str,
    resource_id: str,
) -> TaiwanRealtimeSourceBinding | None:
    matches = tuple(
        binding
        for binding in TW_REALTIME_SOURCE_BINDINGS
        if binding.descriptor.provider_key == provider
        and binding.source == source
        and binding.descriptor.resource_id == resource_id
    )
    if len(matches) > 1:
        raise ValueError("duplicate Taiwan realtime source binding")
    return matches[0] if matches else None


def quote_source_binding(
    *,
    provider: str,
    source: str,
) -> TaiwanRealtimeSourceBinding | None:
    matches = tuple(
        binding
        for binding in TW_REALTIME_SOURCE_BINDINGS
        if binding.descriptor.capability_id == TW_QUOTE_SNAPSHOT_CAPABILITY_ID
        and binding.descriptor.provider_key == provider
        and binding.source == source
    )
    if len(matches) > 1:
        raise ValueError("duplicate Taiwan quote source binding")
    return matches[0] if matches else None


def capability_source_binding(
    *,
    capability_id: str,
    provider: str,
    source: str,
) -> TaiwanRealtimeSourceBinding | None:
    matches = tuple(
        binding
        for binding in TW_REALTIME_SOURCE_BINDINGS
        if binding.descriptor.capability_id == capability_id
        and binding.descriptor.provider_key == provider
        and binding.source == source
    )
    if len(matches) > 1:
        raise ValueError("duplicate Taiwan capability source binding")
    return matches[0] if matches else None


__all__ = [
    "FUGLE_PROVIDER",
    "FUGLE_QUOTE_PARSER_VERSION",
    "FUGLE_QUOTE_RESOURCE_ID",
    "FUGLE_QUOTE_SOURCE",
    "FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR",
    "KGI_AUCTION_DESCRIPTOR",
    "KGI_AUCTION_RESOURCE_ID",
    "KGI_ORDER_BOOK_DESCRIPTOR",
    "KGI_ORDER_BOOK_RESOURCE_ID",
    "KGI_QUOTE_RESOURCE_ID",
    "KGI_QUOTE_SNAPSHOT_DESCRIPTOR",
    "MIS_AUCTION_DESCRIPTOR",
    "MIS_AUCTION_RESOURCE_ID",
    "MIS_ORDER_BOOK_DESCRIPTOR",
    "MIS_ORDER_BOOK_RESOURCE_ID",
    "TW_AUCTION_CAPABILITY_ID",
    "TW_AUCTION_DATASET_ID",
    "TW_ORDER_BOOK_CAPABILITY_ID",
    "TW_ORDER_BOOK_DATASET_ID",
    "TW_QUOTE_SNAPSHOT_CAPABILITY_ID",
    "TW_REALTIME_PROVIDER_DESCRIPTORS",
    "TW_REALTIME_SOURCE_BINDINGS",
    "TaiwanRealtimeSourceBinding",
    "quote_source_binding",
    "capability_source_binding",
    "realtime_source_binding",
]
