"""Strict provider-neutral contracts for market observations and health state.

This module is deliberately pure: it owns no provider I/O, persistence, market
service, AI, or presentation behavior. Market-specific adapters normalize raw
payloads into these models before resolution or downstream consumption.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Market(str, Enum):
    TW = "TW"
    US = "US"
    JP = "JP"
    KR = "KR"
    HK = "HK"
    CRYPTO = "CRYPTO"
    RESOURCE = "RESOURCE"


class InstrumentType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    INDEX = "index"
    FUTURE = "future"
    OPTION = "option"
    CRYPTO_ASSET = "crypto_asset"
    RESOURCE_ASSET = "resource_asset"


class MarketSession(str, Enum):
    PRE_OPEN = "pre_open"
    OPENING_AUCTION = "opening_auction"
    CONTINUOUS = "continuous"
    CLOSING_AUCTION = "closing_auction"
    CLOSE_RESOLUTION = "close_resolution"
    POST_CLOSE = "post_close"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class InstrumentTradability(str, Enum):
    TRADABLE = "tradable"
    HALTED = "halted"
    SUSPENDED = "suspended"
    DELISTED = "delisted"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class ObservationState(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    MISSING = "missing"
    INDICATIVE = "indicative"
    STALE = "stale"


class TradeObservationState(str, Enum):
    UNKNOWN = "unknown"
    AWAITING_FIRST_TRADE = "awaiting_first_trade"
    INDICATIVE_OBSERVED = "indicative_observed"
    TRADE_OBSERVED = "trade_observed"
    NOT_APPLICABLE = "not_applicable"


class RegulatoryFlag(str, Enum):
    ATTENTION = "attention"
    DISPOSITION = "disposition"
    ABNORMAL = "abnormal"
    RESTRICTED = "restricted"


class BarFinalization(str, Enum):
    PROVISIONAL = "provisional"
    FINAL = "final"
    CORRECTED = "corrected"
    UNKNOWN = "unknown"


class DepthCapability(str, Enum):
    NONE = "none"
    LEVEL_1 = "level_1"
    LEVEL_5 = "level_5"
    FULL = "full"


class DepthPriceState(str, Enum):
    PRICED = "priced"
    LIMIT_PRICE = "limit_price"
    NON_PRICE = "non_price"
    UNKNOWN = "unknown"


class QuantityUnit(str, Enum):
    SHARE = "share"
    BOARD_LOT = "board_lot"
    CONTRACT = "contract"
    COIN = "coin"
    UNIT = "unit"


class PriceUnit(str, Enum):
    CURRENCY = "currency"
    INDEX_POINT = "index_point"


class AuthorityClass(str, Enum):
    EXCHANGE = "exchange"
    BROKER = "broker"
    VENDOR = "vendor"
    DERIVED = "derived"
    CACHE = "cache"


class AuctionType(str, Enum):
    OPENING = "opening"
    CLOSING = "closing"
    INTRADAY = "intraday"
    UNKNOWN = "unknown"


class EnablementStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class EntitlementStatus(str, Enum):
    ENTITLED = "entitled"
    PLAN_RESTRICTED = "plan_restricted"
    AUTH_FAILED = "auth_failed"
    UNKNOWN = "unknown"


class OperationalStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class EvidenceFreshness(str, Enum):
    LIVE = "live"
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class DatasetHealthStatus(str, Enum):
    HEALTHY = "healthy"
    STALE = "stale"
    PARTIAL = "partial"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ResolvedEvidenceStatus(str, Enum):
    SELECTED = "selected"
    FALLBACK = "fallback"
    PARTIAL = "partial"
    STALE = "stale"
    MISSING = "missing"
    POLICY_UNSATISFIED = "policy_unsatisfied"


class CanonicalModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class InstrumentKey(CanonicalModel):
    market: Market
    symbol: str = Field(min_length=1, max_length=64)
    instrument_type: InstrumentType
    venue: str | None = Field(default=None, max_length=32)

    @field_validator("symbol", "venue", mode="before")
    @classmethod
    def _normalize_identifier(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _require_venue_for_listed_instruments(self) -> InstrumentKey:
        listed_types = {
            InstrumentType.STOCK,
            InstrumentType.ETF,
            InstrumentType.INDEX,
            InstrumentType.FUTURE,
            InstrumentType.OPTION,
        }
        if self.instrument_type in listed_types and not self.venue:
            raise ValueError("venue is required for listed instruments")
        return self


class SourceLineage(CanonicalModel):
    provider: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    authority: AuthorityClass
    raw_contract_version: str | None = Field(default=None, max_length=64)
    event_at: datetime | None = None
    received_at: datetime | None = None
    fetched_at: datetime | None = None
    cache_hit: bool = False
    observation_id: str | None = Field(default=None, max_length=128)
    raw_receipt_id: str | None = Field(default=None, max_length=128)
    content_hash: str | None = Field(default=None, max_length=128)

    @field_validator("event_at", "received_at", "fetched_at")
    @classmethod
    def _require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("lineage timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _require_one_timestamp(self) -> SourceLineage:
        if not any((self.event_at, self.received_at, self.fetched_at)):
            raise ValueError("lineage requires event_at, received_at, or fetched_at")
        return self


class Quantity(CanonicalModel):
    value: Decimal = Field(ge=0)
    unit: QuantityUnit
    original_value: Decimal | None = Field(default=None, ge=0)
    original_unit: QuantityUnit | None = None
    scale: Decimal = Field(default=Decimal("1"), gt=0)

    @model_validator(mode="after")
    def _validate_original_quantity(self) -> Quantity:
        if (self.original_value is None) != (self.original_unit is None):
            raise ValueError("original_value and original_unit must be provided together")
        return self


class DepthLevel(CanonicalModel):
    level: int = Field(ge=1, le=20)
    price: Decimal | None = Field(default=None, gt=0)
    quantity: Quantity | None = None
    price_state: DepthPriceState = DepthPriceState.PRICED

    @model_validator(mode="after")
    def _validate_price_state(self) -> DepthLevel:
        if self.price_state in {DepthPriceState.PRICED, DepthPriceState.LIMIT_PRICE}:
            if self.price is None:
                raise ValueError("priced depth levels require price")
        elif self.price is not None:
            raise ValueError("non-price depth levels cannot carry a numeric price")
        return self


def _validate_positive_prices(values: dict[str, Decimal | None]) -> None:
    for field_name, value in values.items():
        if value is not None and value <= 0:
            raise ValueError(f"{field_name} must be positive when present")


class QuoteObservation(CanonicalModel):
    contract_version: str = "omi.market.quote.v1"
    instrument: InstrumentKey
    lineage: SourceLineage
    trade_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    state: ObservationState = ObservationState.AVAILABLE
    trade_state: TradeObservationState = TradeObservationState.UNKNOWN
    last_trade_price: Decimal | None = None
    last_trade_quantity: Quantity | None = None
    cumulative_quantity: Quantity | None = None
    open_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    previous_close: Decimal | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate_quote_prices(self) -> QuoteObservation:
        _validate_positive_prices(
            {
                "last_trade_price": self.last_trade_price,
                "open_price": self.open_price,
                "high_price": self.high_price,
                "low_price": self.low_price,
                "previous_close": self.previous_close,
            }
        )
        if self.high_price is not None and self.low_price is not None:
            if self.high_price < self.low_price:
                raise ValueError("high_price cannot be below low_price")
        return self


class DepthObservation(CanonicalModel):
    contract_version: str = "omi.market.depth.v1"
    instrument: InstrumentKey
    lineage: SourceLineage
    capability: DepthCapability
    bids: tuple[DepthLevel, ...] = ()
    asks: tuple[DepthLevel, ...] = ()
    state: ObservationState = ObservationState.AVAILABLE

    @model_validator(mode="after")
    def _validate_depth_capability(self) -> DepthObservation:
        maximum = {
            DepthCapability.NONE: 0,
            DepthCapability.LEVEL_1: 1,
            DepthCapability.LEVEL_5: 5,
            DepthCapability.FULL: 20,
        }[self.capability]
        for side_name, levels in (("bids", self.bids), ("asks", self.asks)):
            if len(levels) > maximum:
                raise ValueError(f"{side_name} exceed declared depth capability")
            ranks = [level.level for level in levels]
            if ranks != sorted(ranks) or len(ranks) != len(set(ranks)):
                raise ValueError(f"{side_name} levels must be unique and ordered")
            if ranks and ranks[-1] > maximum:
                raise ValueError(f"{side_name} level exceeds declared depth capability")
        return self


class AuctionObservation(CanonicalModel):
    contract_version: str = "omi.market.auction.v1"
    instrument: InstrumentKey
    lineage: SourceLineage
    auction_type: AuctionType
    state: ObservationState = ObservationState.INDICATIVE
    indicative_price: Decimal | None = None
    indicative_quantity: Quantity | None = None
    best_bid: DepthLevel | None = None
    best_ask: DepthLevel | None = None
    provisional: bool = True

    @model_validator(mode="after")
    def _validate_auction(self) -> AuctionObservation:
        _validate_positive_prices({"indicative_price": self.indicative_price})
        if not self.provisional:
            raise ValueError("auction observations are provisional evidence")
        return self


class BarObservation(CanonicalModel):
    contract_version: str = "omi.market.bar.v1"
    instrument: InstrumentKey
    lineage: SourceLineage
    interval: str = Field(min_length=1, max_length=16)
    start_at: datetime
    end_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Quantity | None = None
    volume_status: Literal["observed", "missing", "not_applicable"] | None = None
    price_basis: Literal["raw", "adjusted", "provider_default"] | None = None
    instrument_name: str | None = Field(default=None, max_length=120)
    turnover_value: Decimal | None = Field(default=None, ge=0)
    turnover_currency: str | None = Field(default=None, min_length=3, max_length=3)
    trade_count: int | None = Field(default=None, ge=0)
    price_change: Decimal | None = None
    finalization: BarFinalization

    @field_validator("start_at", "end_at")
    @classmethod
    def _require_aware_bar_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("bar timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_bar(self) -> BarObservation:
        if self.start_at >= self.end_at:
            raise ValueError("bar start_at must be before end_at")
        _validate_positive_prices(
            {
                "open_price": self.open_price,
                "high_price": self.high_price,
                "low_price": self.low_price,
                "close_price": self.close_price,
            }
        )
        if self.high_price < max(self.open_price, self.low_price, self.close_price):
            raise ValueError("bar high_price is inconsistent")
        if self.low_price > min(self.open_price, self.high_price, self.close_price):
            raise ValueError("bar low_price is inconsistent")
        if (self.turnover_value is None) != (self.turnover_currency is None):
            raise ValueError(
                "turnover_value and turnover_currency must be provided together"
            )
        if self.volume_status == "observed" and self.volume is None:
            raise ValueError("observed volume_status requires volume")
        if self.volume_status in {"missing", "not_applicable"} and self.volume is not None:
            raise ValueError(f"{self.volume_status} volume_status requires volume=None")
        return self


class MarketBreadthObservation(CanonicalModel):
    contract_version: str = "omi.market.breadth.v1"
    market: Market
    venue: str = Field(min_length=1, max_length=32)
    lineage: SourceLineage
    session: MarketSession
    trade_date: date
    scope: str = Field(min_length=1, max_length=64)
    universe_source: str = Field(min_length=1, max_length=192)
    universe_count: int = Field(ge=0)
    advance_count: int = Field(ge=0)
    decline_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    trade_value: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    state: ObservationState = ObservationState.AVAILABLE
    price_semantics: str = Field(min_length=1, max_length=64)
    official: bool = False
    provisional: bool = False

    @property
    def classified_count(self) -> int:
        return self.advance_count + self.decline_count + self.unchanged_count

    @model_validator(mode="after")
    def _validate_partition(self) -> MarketBreadthObservation:
        partition = self.classified_count + self.unknown_count + self.missing_count
        if partition != self.universe_count:
            raise ValueError(
                "breadth classified/unknown/missing counts must equal universe_count"
            )
        incomplete = (
            self.unknown_count > 0
            or self.missing_count > 0
            or self.trade_value is None
        )
        if incomplete and self.state is ObservationState.AVAILABLE:
            raise ValueError("incomplete breadth must be partial or stale")
        if not incomplete and self.state is ObservationState.PARTIAL:
            raise ValueError("complete breadth cannot be partial")
        if (self.trade_value is None) != (self.currency is None):
            raise ValueError("breadth trade_value and currency must be paired")
        if self.session in {MarketSession.POST_CLOSE, MarketSession.CLOSED}:
            if self.provisional:
                raise ValueError("completed-session breadth cannot be provisional")
        return self


class MarketIndexObservation(CanonicalModel):
    contract_version: str = "omi.market.index_observation.v1"
    market: Market
    index_id: str = Field(min_length=1, max_length=32)
    venue: str = Field(min_length=1, max_length=32)
    lineage: SourceLineage
    session: MarketSession
    trade_date: date
    close_value: Decimal = Field(gt=0)
    price_change: Decimal
    trade_volume: Quantity | None = None
    trade_value: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    transaction_count: int | None = Field(default=None, ge=0)
    state: ObservationState = ObservationState.AVAILABLE
    value_semantics: str = Field(min_length=1, max_length=64)
    finalization: BarFinalization
    official: bool = False
    provisional: bool = False

    @model_validator(mode="after")
    def _validate_market_index(self) -> MarketIndexObservation:
        incomplete = any(
            value is None
            for value in (
                self.trade_volume,
                self.trade_value,
                self.transaction_count,
            )
        )
        if incomplete and self.state is ObservationState.AVAILABLE:
            raise ValueError(
                "incomplete market index observation must be partial or stale"
            )
        if not incomplete and self.state is ObservationState.PARTIAL:
            raise ValueError("complete market index observation cannot be partial")
        if (self.trade_value is None) != (self.currency is None):
            raise ValueError("market index trade_value and currency must be paired")
        if self.session in {MarketSession.POST_CLOSE, MarketSession.CLOSED}:
            if self.provisional:
                raise ValueError("completed-session market index cannot be provisional")
            if self.finalization is BarFinalization.PROVISIONAL:
                raise ValueError("completed-session market index must be final")
        return self


class MarketSessionContext(CanonicalModel):
    market: Market
    session: MarketSession
    observed_at: datetime
    trade_date: date | None = None

    @field_validator("observed_at")
    @classmethod
    def _require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value


class TradingStatusObservation(CanonicalModel):
    contract_version: str = "omi.market.trading_status.v1"
    instrument: InstrumentKey
    lineage: SourceLineage
    status: InstrumentTradability
    regulatory_flags: frozenset[RegulatoryFlag] = frozenset()
    reason: str | None = Field(default=None, max_length=256)
    effective_at: datetime | None = None
    official: bool = False

    @field_validator("effective_at")
    @classmethod
    def _require_aware_effective_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("effective_at must be timezone-aware")
        return value


class ProviderResourceHealth(CanonicalModel):
    contract_version: str = "omi.market.provider_resource_health.v1"
    provider: str = Field(min_length=1, max_length=64)
    market: Market
    capability: str = Field(min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, min_length=1, max_length=128)
    enablement: EnablementStatus
    connection: ConnectionStatus
    entitlement: EntitlementStatus
    operational: OperationalStatus
    freshness: EvidenceFreshness
    checked_at: datetime
    detail_code: str | None = Field(default=None, max_length=64)
    retry_after_seconds: int | None = Field(default=None, ge=0)
    cooldown_until: datetime | None = None

    @field_validator("checked_at")
    @classmethod
    def _require_aware_checked_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return value

    @field_validator("cooldown_until")
    @classmethod
    def _require_aware_cooldown_until(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("cooldown_until must be timezone-aware")
        return value


class DatasetHealth(CanonicalModel):
    contract_version: str = "omi.market.dataset_health.v1"
    dataset_id: str = Field(min_length=1, max_length=128)
    market: Market
    status: DatasetHealthStatus
    expected_date: date | None = None
    latest_date: date | None = None
    checked_at: datetime
    refreshable: bool
    refresh_operation: str | None = Field(default=None, max_length=128)
    detail_code: str | None = Field(default=None, max_length=64)

    @field_validator("checked_at")
    @classmethod
    def _require_aware_dataset_checked_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_refresh_contract(self) -> DatasetHealth:
        if self.refreshable and not self.refresh_operation:
            raise ValueError("refreshable datasets require refresh_operation")
        if not self.refreshable and self.refresh_operation:
            raise ValueError("non-refreshable datasets cannot advertise refresh_operation")
        return self


class ResolvedEvidenceHealth(CanonicalModel):
    contract_version: str = "omi.market.resolved_evidence_health.v1"
    status: ResolvedEvidenceStatus
    selected_provider: str | None = Field(default=None, max_length=64)
    selected_source: str | None = Field(default=None, max_length=128)
    selected_session: MarketSession | None = None
    selected_event_at: datetime | None = None
    fallback_used: bool = False
    selection_reason: str = Field(min_length=1, max_length=256)
    missing_fields: tuple[str, ...] = ()
    facts_usable: bool = False
    research_usable: bool = False
    limitations: tuple[str, ...] = ()

    @field_validator("selected_event_at")
    @classmethod
    def _require_aware_selected_event_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("selected_event_at must be timezone-aware")
        return value


class CandidateSummary(CanonicalModel):
    provider: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    freshness: EvidenceFreshness
    authority: AuthorityClass
    session: MarketSession = MarketSession.UNKNOWN
    event_at: datetime | None = None
    eligible: bool
    reason_code: str = Field(min_length=1, max_length=64)

    @field_validator("event_at")
    @classmethod
    def _require_aware_candidate_event_at(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("event_at must be timezone-aware")
        return value


class BarSeriesCompositionStatus(str, Enum):
    NOT_APPLIED = "not_applied"
    NO_ELIGIBLE_BARS = "no_eligible_bars"
    SINGLE_CONTRIBUTOR = "single_contributor"
    COMPOSED = "composed"
    COMPOSED_WITH_CONFLICTS = "composed_with_conflicts"


class BarSeriesComposition(CanonicalModel):
    """How a resolved bar series was assembled from eligible candidates.

    This is deliberately separate from the market temporal reconciliation
    axis, which compares two already-identified evidence objects.
    """

    contract_version: str = "omi.market.bar_series_composition.v1"
    applied: bool = False
    status: BarSeriesCompositionStatus = BarSeriesCompositionStatus.NOT_APPLIED
    contributing_providers: tuple[str, ...] = Field(default=(), max_length=8)
    contributing_sources: tuple[str, ...] = Field(default=(), max_length=8)
    filled_bucket_count: int = Field(default=0, ge=0, le=5000)
    conflict_bucket_count: int = Field(default=0, ge=0, le=5000)
    limitations: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def _validate_composition(self) -> BarSeriesComposition:
        if len(set(self.contributing_providers)) != len(self.contributing_providers):
            raise ValueError("contributing_providers must be unique")
        if len(set(self.contributing_sources)) != len(self.contributing_sources):
            raise ValueError("contributing_sources must be unique")
        if not self.applied:
            if self.status is not BarSeriesCompositionStatus.NOT_APPLIED:
                raise ValueError("non-applied composition must use status=not_applied")
            if any(
                (
                    self.contributing_providers,
                    self.contributing_sources,
                    self.filled_bucket_count,
                    self.conflict_bucket_count,
                    self.limitations,
                )
            ):
                raise ValueError("non-applied composition cannot report composition work")
        elif self.status is BarSeriesCompositionStatus.NOT_APPLIED:
            raise ValueError("applied composition requires an applied status")
        if (
            self.status is BarSeriesCompositionStatus.NO_ELIGIBLE_BARS
            and any(
                (
                    self.contributing_providers,
                    self.contributing_sources,
                    self.filled_bucket_count,
                    self.conflict_bucket_count,
                )
            )
        ):
            raise ValueError("no-eligible-bars composition cannot report contributors")
        if (
            self.status is BarSeriesCompositionStatus.COMPOSED_WITH_CONFLICTS
            and self.conflict_bucket_count == 0
        ):
            raise ValueError("conflict composition status requires a conflict bucket")
        if (
            self.conflict_bucket_count > 0
            and self.status is not BarSeriesCompositionStatus.COMPOSED_WITH_CONFLICTS
        ):
            raise ValueError("conflict buckets require composed_with_conflicts status")
        return self


class ResolvedQuote(CanonicalModel):
    contract_version: str = "omi.market.resolved_quote.v1"
    quote: QuoteObservation | None = None
    health: ResolvedEvidenceHealth
    candidates: tuple[CandidateSummary, ...] = ()


class ResolvedDepth(CanonicalModel):
    contract_version: str = "omi.market.resolved_depth.v1"
    depth: DepthObservation | None = None
    health: ResolvedEvidenceHealth
    candidates: tuple[CandidateSummary, ...] = ()


class ResolvedAuction(CanonicalModel):
    contract_version: str = "omi.market.resolved_auction.v1"
    auction: AuctionObservation | None = None
    health: ResolvedEvidenceHealth
    candidates: tuple[CandidateSummary, ...] = ()


class ResolvedBarSeries(CanonicalModel):
    contract_version: str = "omi.market.resolved_bar_series.v1"
    bars: tuple[BarObservation, ...] = ()
    health: ResolvedEvidenceHealth
    candidates: tuple[CandidateSummary, ...] = ()
    composition: BarSeriesComposition = BarSeriesComposition()

    @model_validator(mode="after")
    def _validate_bar_series_identity(self) -> ResolvedBarSeries:
        if self.bars:
            instrument = self.bars[0].instrument
            interval = self.bars[0].interval
            if any(bar.instrument != instrument for bar in self.bars):
                raise ValueError("resolved bars must share one instrument key")
            if any(bar.interval != interval for bar in self.bars):
                raise ValueError("resolved bars must share one interval")
            if any(
                current.start_at >= following.start_at
                for current, following in zip(self.bars, self.bars[1:])
            ):
                raise ValueError("resolved bars must be strictly ordered")
        return self


class ResolvedMarketBreadth(CanonicalModel):
    contract_version: str = "omi.market.resolved_breadth.v1"
    breadth: MarketBreadthObservation | None = None
    health: ResolvedEvidenceHealth
    candidates: tuple[CandidateSummary, ...] = ()


class ResolvedMarketIndex(CanonicalModel):
    contract_version: str = "omi.market.resolved_index.v1"
    market_index: MarketIndexObservation | None = None
    health: ResolvedEvidenceHealth
    candidates: tuple[CandidateSummary, ...] = ()


class ResolvedTradingStatus(CanonicalModel):
    contract_version: str = "omi.market.resolved_trading_status.v1"
    trading_status: TradingStatusObservation | None = None
    health: ResolvedEvidenceHealth
    candidates: tuple[CandidateSummary, ...] = ()


class CanonicalMarketSnapshot(CanonicalModel):
    contract_version: str = "omi.market.snapshot.v1"
    instrument: InstrumentKey
    session: MarketSessionContext | None = None
    quote: QuoteObservation | None = None
    depth: DepthObservation | None = None
    auction: AuctionObservation | None = None
    trading_status: TradingStatusObservation | None = None

    @model_validator(mode="after")
    def _require_observation(self) -> CanonicalMarketSnapshot:
        observations = (self.quote, self.depth, self.auction, self.trading_status)
        if not any(observations):
            raise ValueError("snapshot requires at least one observation")
        for observation in observations:
            if observation is not None and observation.instrument != self.instrument:
                raise ValueError("snapshot observations must share the same instrument key")
        if self.session is not None and self.session.market != self.instrument.market:
            raise ValueError("snapshot session market must match instrument market")
        return self
