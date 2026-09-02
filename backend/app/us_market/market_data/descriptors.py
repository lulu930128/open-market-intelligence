"""Market-owned US V2 provider capability descriptors for Shared Core injection."""

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


YAHOO_DAILY_RESOURCE_ID = "yahoo_chart.daily"
YAHOO_QUOTE_RESOURCE_ID = "yahoo_chart.quote"
YAHOO_INTRADAY_RESOURCE_ID = "yahoo_chart.intraday"
ALPACA_SIP_DAILY_RESOURCE_ID = "alpaca.sip.historical.daily"
ALPHAVANTAGE_DAILY_RESOURCE_ID = "alphavantage.daily"
TWELVE_QUOTE_RESOURCE_ID = "twelve_data.quote"
TWELVE_INTRADAY_RESOURCE_ID = "twelve_data.intraday"
MASSIVE_INDEX_QUOTE_RESOURCE_ID = "massive.indices.snapshot"
MASSIVE_INDEX_INTRADAY_RESOURCE_ID = "massive.indices.aggregates.1m"
MASSIVE_INDEX_DAILY_RESOURCE_ID = "massive.indices.aggregates.1d"

MASSIVE_INDEX_QUOTE_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="massive",
    market=Market.US,
    capability_id="quote.snapshot",
    resource_id=MASSIVE_INDEX_QUOTE_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.INDEX,),
    supported_sessions=(
        MarketSession.PRE_OPEN,
        MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION,
        MarketSession.POST_CLOSE,
        MarketSession.CLOSED,
    ),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=90,
    can_produce_live=True,
    max_timeout_seconds=15,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=1,
    allow_unknown_health=True,
    limitations=(
        "API_KEY_REQUIRED",
        "MASSIVE_INDICES_ONLY",
        "PROVIDER_TIMEFRAME_MUST_BE_VERIFIED",
    ),
)

MASSIVE_INDEX_INTRADAY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="massive",
    market=Market.US,
    capability_id="intraday.bars",
    resource_id=MASSIVE_INDEX_INTRADAY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.INDEX,),
    intervals=("1m",),
    supported_sessions=(
        MarketSession.PRE_OPEN,
        MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION,
        MarketSession.POST_CLOSE,
        MarketSession.CLOSED,
    ),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=90,
    can_produce_live=True,
    max_timeout_seconds=15,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=5,
    allow_unknown_health=True,
    limitations=(
        "API_KEY_REQUIRED",
        "MASSIVE_INDICES_ONLY",
        "MASSIVE_INDEX_VOLUME_NOT_APPLICABLE",
    ),
)

MASSIVE_INDEX_DAILY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="massive",
    market=Market.US,
    capability_id="daily.ohlcv",
    resource_id=MASSIVE_INDEX_DAILY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.INDEX,),
    intervals=("1d",),
    supported_sessions=(MarketSession.CLOSED,),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=90,
    can_produce_final=True,
    max_timeout_seconds=15,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=3650,
    allow_unknown_health=True,
    limitations=(
        "API_KEY_REQUIRED",
        "MASSIVE_INDICES_ONLY",
        "MASSIVE_INDEX_HISTORY_START_2023_02_14",
        "MASSIVE_INDEX_VOLUME_NOT_APPLICABLE",
    ),
)

YAHOO_QUOTE_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="yahoo_chart",
    market=Market.US,
    capability_id="quote.snapshot",
    resource_id=YAHOO_QUOTE_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF, InstrumentType.INDEX),
    supported_sessions=(
        MarketSession.PRE_OPEN,
        MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION,
        MarketSession.POST_CLOSE,
        MarketSession.CLOSED,
    ),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=100,
    can_produce_live=False,
    max_timeout_seconds=25,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=5,
    allow_unknown_health=True,
    limitations=("DELAYED_VENDOR_EVIDENCE",),
)

YAHOO_INTRADAY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="yahoo_chart",
    market=Market.US,
    capability_id="intraday.bars",
    resource_id=YAHOO_INTRADAY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF, InstrumentType.INDEX),
    intervals=("1m",),
    supported_sessions=(
        MarketSession.PRE_OPEN,
        MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION,
        MarketSession.POST_CLOSE,
        MarketSession.CLOSED,
    ),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=100,
    can_produce_live=False,
    max_timeout_seconds=25,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=5,
    allow_unknown_health=True,
    limitations=("DELAYED_VENDOR_EVIDENCE",),
)

YAHOO_DAILY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="yahoo_chart",
    market=Market.US,
    capability_id="daily.ohlcv",
    resource_id=YAHOO_DAILY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF, InstrumentType.INDEX),
    intervals=("1d",),
    supported_sessions=(MarketSession.CLOSED,),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=100,
    can_produce_final=True,
    max_timeout_seconds=25,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=3650,
    allow_unknown_health=True,
    limitations=("DELAYED_VENDOR_EVIDENCE",),
)

ALPHAVANTAGE_DAILY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="alphavantage",
    market=Market.US,
    capability_id="daily.ohlcv",
    resource_id=ALPHAVANTAGE_DAILY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    intervals=("1d",),
    supported_sessions=(MarketSession.CLOSED,),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=120,
    can_produce_final=True,
    max_timeout_seconds=30,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=3650,
    allow_unknown_health=True,
    limitations=("API_KEY_REQUIRED", "INDEX_SUPPORT_NOT_DECLARED"),
)

ALPACA_SIP_DAILY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="alpaca",
    market=Market.US,
    capability_id="daily.ohlcv",
    resource_id=ALPACA_SIP_DAILY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    intervals=("1d",),
    supported_sessions=(MarketSession.CLOSED,),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=110,
    can_produce_final=True,
    max_timeout_seconds=25,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=3650,
    allow_unknown_health=True,
    limitations=("DELAYED_SIP_EVIDENCE", "FIFTEEN_MINUTE_SIP_RESTRICTION"),
)

TWELVE_QUOTE_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="twelve_data",
    market=Market.US,
    capability_id="quote.snapshot",
    resource_id=TWELVE_QUOTE_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    supported_sessions=(
        MarketSession.PRE_OPEN,
        MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION,
        MarketSession.POST_CLOSE,
        MarketSession.CLOSED,
    ),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=110,
    can_produce_live=True,
    max_timeout_seconds=15,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=1,
    allow_unknown_health=True,
    limitations=("PARTIAL_US_MARKET_VOLUME", "PERSONAL_INTERNAL_USE_ONLY"),
)

TWELVE_INTRADAY_DESCRIPTOR = ProviderCapabilityDescriptorV2(
    provider_key="twelve_data",
    market=Market.US,
    capability_id="intraday.bars",
    resource_id=TWELVE_INTRADAY_RESOURCE_ID,
    authority=AuthorityClass.VENDOR,
    target_kinds=(DescriptorTargetKind.INSTRUMENT,),
    instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
    intervals=("1m", "5m", "15m", "30m", "45m", "1h"),
    supported_sessions=(
        MarketSession.PRE_OPEN,
        MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION,
        MarketSession.POST_CLOSE,
        MarketSession.CLOSED,
    ),
    acquisition_modes=(AcquisitionMode.FETCH,),
    priority=110,
    can_produce_live=True,
    max_timeout_seconds=15,
    max_external_calls_per_attempt=1,
    max_symbols_per_call=1,
    max_range_days=30,
    allow_unknown_health=True,
    limitations=("PARTIAL_US_MARKET_VOLUME", "PERSONAL_INTERNAL_USE_ONLY"),
)

US_DAILY_PROVIDER_DESCRIPTORS = (
    YAHOO_DAILY_DESCRIPTOR,
    ALPACA_SIP_DAILY_DESCRIPTOR,
)

# Compatibility export for the completed Alpaca rollout. Production planning
# and the historical name now intentionally reference the same executable
# inventory; Alpha Vantage Daily is not part of either tuple.
US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS = (
    YAHOO_DAILY_DESCRIPTOR,
    ALPACA_SIP_DAILY_DESCRIPTOR,
)

US_DAILY_CANDIDATE_DESCRIPTORS = (
    YAHOO_DAILY_DESCRIPTOR,
    ALPACA_SIP_DAILY_DESCRIPTOR,
)

# Registered descriptors include source-ready canary integrations. They are
# intentionally separate from the active production inventory above: a
# provider must pass its account-level coverage and entitlement gate before it
# can participate in normal resolution.
US_DAILY_REGISTERED_DESCRIPTORS = (
    MASSIVE_INDEX_DAILY_DESCRIPTOR,
    *US_DAILY_CANDIDATE_DESCRIPTORS,
)


def us_daily_history_descriptors(
    descriptors: tuple[ProviderCapabilityDescriptorV2, ...] = US_DAILY_PROVIDER_DESCRIPTORS,
) -> tuple[ProviderCapabilityDescriptorV2, ...]:
    """Return an operation-scoped history plan view of the active inventory.

    The executable provider inventory remains ``descriptors``. Only explicit
    history coverage work prefers Alpaca before Yahoo; normal Daily refresh
    keeps the descriptor-declared Yahoo-first priority.
    """

    preference = {"alpaca": 0, "yahoo_chart": 1, "massive": 2}
    ordered = sorted(
        descriptors,
        key=lambda item: (
            preference.get(item.provider_key, len(preference)),
            item.priority,
            item.provider_key,
            item.resource_id,
        ),
    )
    return tuple(
        descriptor.model_copy(update={"priority": 100 + index * 10})
        for index, descriptor in enumerate(ordered)
    )

US_SOURCE_READY_PROVIDER_DESCRIPTORS = (
    MASSIVE_INDEX_QUOTE_DESCRIPTOR,
    MASSIVE_INDEX_INTRADAY_DESCRIPTOR,
    MASSIVE_INDEX_DAILY_DESCRIPTOR,
    TWELVE_QUOTE_DESCRIPTOR,
    TWELVE_INTRADAY_DESCRIPTOR,
)

US_QUOTE_PROVIDER_DESCRIPTORS = (
    YAHOO_QUOTE_DESCRIPTOR,
    TWELVE_QUOTE_DESCRIPTOR,
)

US_INTRADAY_PROVIDER_DESCRIPTORS = (
    YAHOO_INTRADAY_DESCRIPTOR,
    TWELVE_INTRADAY_DESCRIPTOR,
)

US_QUOTE_REGISTERED_DESCRIPTORS = (
    MASSIVE_INDEX_QUOTE_DESCRIPTOR,
    *US_QUOTE_PROVIDER_DESCRIPTORS,
)

US_INTRADAY_REGISTERED_DESCRIPTORS = (
    MASSIVE_INDEX_INTRADAY_DESCRIPTOR,
    *US_INTRADAY_PROVIDER_DESCRIPTORS,
)


def us_quote_descriptor_for_resource(resource_id: str) -> ProviderCapabilityDescriptorV2:
    for descriptor in US_QUOTE_REGISTERED_DESCRIPTORS:
        if descriptor.resource_id == resource_id:
            return descriptor
    raise ValueError(f"unregistered US quote resource: {resource_id}")


def us_intraday_descriptor_for_resource(resource_id: str) -> ProviderCapabilityDescriptorV2:
    for descriptor in US_INTRADAY_REGISTERED_DESCRIPTORS:
        if descriptor.resource_id == resource_id:
            return descriptor
    raise ValueError(f"unregistered US intraday resource: {resource_id}")


def us_daily_descriptor_for_resource(
    resource_id: str,
) -> ProviderCapabilityDescriptorV2:
    for descriptor in US_DAILY_REGISTERED_DESCRIPTORS:
        if descriptor.resource_id == resource_id:
            return descriptor
    raise ValueError(f"unregistered US daily resource: {resource_id}")


def us_provider_auth_type(provider_key: str) -> str:
    normalized = str(provider_key).strip().lower()
    if normalized == "yahoo_chart":
        return "none"
    if normalized in {"alpaca", "alphavantage", "massive", "twelve_data"}:
        return "api_key"
    raise ValueError(f"unregistered US provider auth metadata: {provider_key}")

__all__ = [
    "ALPHAVANTAGE_DAILY_DESCRIPTOR",
    "ALPHAVANTAGE_DAILY_RESOURCE_ID",
    "ALPACA_SIP_DAILY_DESCRIPTOR",
    "ALPACA_SIP_DAILY_RESOURCE_ID",
    "MASSIVE_INDEX_DAILY_DESCRIPTOR",
    "MASSIVE_INDEX_DAILY_RESOURCE_ID",
    "MASSIVE_INDEX_INTRADAY_DESCRIPTOR",
    "MASSIVE_INDEX_INTRADAY_RESOURCE_ID",
    "MASSIVE_INDEX_QUOTE_DESCRIPTOR",
    "MASSIVE_INDEX_QUOTE_RESOURCE_ID",
    "TWELVE_INTRADAY_DESCRIPTOR",
    "TWELVE_INTRADAY_RESOURCE_ID",
    "TWELVE_QUOTE_DESCRIPTOR",
    "TWELVE_QUOTE_RESOURCE_ID",
    "US_INTRADAY_PROVIDER_DESCRIPTORS",
    "US_INTRADAY_REGISTERED_DESCRIPTORS",
    "US_QUOTE_PROVIDER_DESCRIPTORS",
    "US_QUOTE_REGISTERED_DESCRIPTORS",
    "US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS",
    "US_DAILY_CANDIDATE_DESCRIPTORS",
    "US_DAILY_PROVIDER_DESCRIPTORS",
    "US_DAILY_REGISTERED_DESCRIPTORS",
    "US_SOURCE_READY_PROVIDER_DESCRIPTORS",
    "YAHOO_DAILY_DESCRIPTOR",
    "YAHOO_DAILY_RESOURCE_ID",
    "YAHOO_INTRADAY_DESCRIPTOR",
    "YAHOO_INTRADAY_RESOURCE_ID",
    "YAHOO_QUOTE_DESCRIPTOR",
    "YAHOO_QUOTE_RESOURCE_ID",
    "us_daily_descriptor_for_resource",
    "us_daily_history_descriptors",
    "us_intraday_descriptor_for_resource",
    "us_provider_auth_type",
    "us_quote_descriptor_for_resource",
]
