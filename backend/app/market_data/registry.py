"""Pure Dataset Registry v1 for canonical market-data lifecycle truth."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import Field, model_validator

from app.market_data.contracts import (
    CanonicalModel,
    DatasetHealth,
    DatasetHealthStatus,
    Market,
)


class DatasetFrequency(str, Enum):
    EVENT = "event"
    INTRADAY = "intraday"
    DAILY = "daily"


class ExpectedStatePolicy(str, Enum):
    CURRENT_SESSION = "current_session"
    LATEST_COMPLETED_SESSION = "latest_completed_session"
    REQUESTED_OR_LATEST_COMPLETED = "requested_or_latest_completed"


class EligibilityPolicy(str, Enum):
    MARKET_TRADING_DAY = "market_trading_day"
    LISTED_INSTRUMENT_AND_TRADING_DAY = "listed_instrument_and_trading_day"
    LISTED_INSTRUMENT_MARKET_DAY_AND_INSTRUMENT_ELIGIBLE = (
        "listed_instrument_market_day_and_instrument_eligible"
    )
    LISTED_INSTRUMENT = "listed_instrument"


class RefreshBounds(CanonicalModel):
    max_calls: int = Field(ge=1, le=500)
    timeout_seconds: int = Field(ge=1, le=120)
    max_symbols: int = Field(ge=1, le=500)
    max_range_days: int = Field(ge=1, le=3650)


class DatasetSpec(CanonicalModel):
    registry_version: str = "omi.market.dataset_registry.v1"
    dataset_id: str = Field(min_length=1, max_length=128)
    schema_version: str = Field(min_length=1, max_length=64)
    market: Market
    scope_kind: str = Field(min_length=1, max_length=64)
    owner: str = Field(min_length=1, max_length=128)
    read_operation: str = Field(min_length=1, max_length=192)
    projection_id: str = Field(min_length=1, max_length=128)
    capability_ids: tuple[str, ...]
    frequency: DatasetFrequency
    expected_state_policy: ExpectedStatePolicy
    eligibility_policy: EligibilityPolicy
    storage_reference: str | None = Field(default=None, max_length=192)
    refreshable: bool = False
    refresh_operation: str | None = Field(default=None, max_length=128)
    refresh_bounds: RefreshBounds | None = None
    postcondition: str = Field(min_length=1, max_length=256)
    repairable: bool = False

    @model_validator(mode="after")
    def _validate_lifecycle_contract(self) -> DatasetSpec:
        if not self.capability_ids:
            raise ValueError("dataset requires at least one capability mapping")
        if self.refreshable:
            if not self.refresh_operation:
                raise ValueError("refreshable dataset requires refresh_operation")
            if self.refresh_bounds is None:
                raise ValueError("refreshable dataset requires refresh_bounds")
        elif self.refresh_operation is not None or self.refresh_bounds is not None:
            raise ValueError("non-refreshable dataset cannot advertise refresh metadata")
        if self.repairable and not self.refreshable:
            raise ValueError("repairable dataset must be refreshable")
        return self


class DatasetRegistry:
    def __init__(self, specs: tuple[DatasetSpec, ...]) -> None:
        by_id = {spec.dataset_id: spec for spec in specs}
        if len(by_id) != len(specs):
            raise ValueError("dataset IDs must be unique")
        self._specs = specs
        self._by_id = by_id

    def get(self, dataset_id: str) -> DatasetSpec:
        try:
            return self._by_id[dataset_id]
        except KeyError as exc:
            raise KeyError(f"Unknown market dataset: {dataset_id}") from exc

    def all(self) -> tuple[DatasetSpec, ...]:
        return self._specs


INTERNAL_DATASET_REFRESH_OPERATIONS = frozenset(
    {
        "tw.reconcile_full_market_eod",
        "tw.refresh_official_market_index",
        "tw.acquire_public_last_trade_quote",
        "tw.refresh_realtime_snapshot",
        "tw.refresh_intraday_bars",
        "tw.refresh_current_index",
        "tw.refresh_current_breadth",
        "us.reconcile_full_market_eod",
    }
)


def evaluate_dataset_health(
    spec: DatasetSpec,
    *,
    expected_date: date | None,
    latest_date: date | None,
    checked_at: datetime,
    eligible: bool | None,
    partial: bool = False,
    stale: bool = False,
    provider_available: bool = True,
) -> DatasetHealth:
    """Evaluate health from caller-supplied calendar/storage facts without I/O."""

    if eligible is False:
        status = DatasetHealthStatus.NOT_APPLICABLE
        detail_code = "DATASET_NOT_ELIGIBLE"
    elif eligible is None:
        status = DatasetHealthStatus.UNKNOWN
        detail_code = "ELIGIBILITY_UNKNOWN"
    elif not provider_available:
        status = DatasetHealthStatus.UNAVAILABLE
        detail_code = "PROVIDER_UNAVAILABLE"
    elif latest_date is None:
        status = DatasetHealthStatus.MISSING
        detail_code = "LATEST_DATE_MISSING"
    elif partial:
        status = DatasetHealthStatus.PARTIAL
        detail_code = "DATASET_PARTIAL"
    elif stale:
        status = DatasetHealthStatus.STALE
        detail_code = "DATASET_STALE"
    elif expected_date is None:
        status = DatasetHealthStatus.UNKNOWN
        detail_code = "EXPECTED_DATE_UNKNOWN"
    elif latest_date < expected_date:
        status = DatasetHealthStatus.STALE
        detail_code = "LATEST_DATE_BEHIND_EXPECTED"
    else:
        status = DatasetHealthStatus.HEALTHY
        detail_code = "DATASET_CURRENT"
    return DatasetHealth(
        dataset_id=spec.dataset_id,
        market=spec.market,
        status=status,
        expected_date=expected_date,
        latest_date=latest_date,
        checked_at=checked_at,
        refreshable=spec.refreshable,
        refresh_operation=spec.refresh_operation,
        detail_code=detail_code,
    )


DATASET_REGISTRY = DatasetRegistry(
    (
        DatasetSpec(
            dataset_id="tw.quote.snapshot",
            schema_version="omi.market.quote.v1",
            market=Market.TW,
            scope_kind="stock",
            owner="app.market.public_quote_platform",
            read_operation="read_taiwan_public_last_trade_quote",
            projection_id="quote.snapshot.stock.TW",
            capability_ids=("quote.snapshot", "quote.last_trade"),
            frequency=DatasetFrequency.EVENT,
            expected_state_policy=ExpectedStatePolicy.CURRENT_SESSION,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT_AND_TRADING_DAY,
            storage_reference="taiwan_stock_quote_snapshot",
            refreshable=True,
            refresh_operation="tw.acquire_public_last_trade_quote",
            refresh_bounds=RefreshBounds(
                max_calls=1,
                timeout_seconds=10,
                max_symbols=1,
                max_range_days=1,
            ),
            postcondition="Return a quote snapshot or a truthful unavailable/partial state.",
        ),
        DatasetSpec(
            dataset_id="tw.quote.order_book.snapshot",
            schema_version="omi.market.depth.v1",
            market=Market.TW,
            scope_kind="stock",
            owner="app.market.taiwan_realtime_platform",
            read_operation="read_taiwan_depth",
            projection_id="quote.order_book.stock.TW",
            capability_ids=("quote.order_book",),
            frequency=DatasetFrequency.EVENT,
            expected_state_policy=ExpectedStatePolicy.CURRENT_SESSION,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT_AND_TRADING_DAY,
            storage_reference="source_registry+raw_fetch_result+taiwan_stock_depth_snapshot+taiwan_stock_depth_level",
            refreshable=True,
            refresh_operation="tw.refresh_realtime_snapshot",
            refresh_bounds=RefreshBounds(
                max_calls=3,
                timeout_seconds=40,
                max_symbols=1,
                max_range_days=1,
            ),
            postcondition="Persist a canonical bounded order book and raw receipt, reread, and return resolved depth or truthful missing, stale, partial, or policy-unsatisfied evidence.",
        ),
        DatasetSpec(
            dataset_id="tw.quote.auction.snapshot",
            schema_version="omi.market.auction.v1",
            market=Market.TW,
            scope_kind="stock",
            owner="app.market.taiwan_realtime_platform",
            read_operation="read_taiwan_auction",
            projection_id="quote.auction.stock.TW",
            capability_ids=("quote.auction",),
            frequency=DatasetFrequency.EVENT,
            expected_state_policy=ExpectedStatePolicy.CURRENT_SESSION,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT_AND_TRADING_DAY,
            storage_reference="source_registry+raw_fetch_result+taiwan_stock_auction_snapshot",
            refreshable=True,
            refresh_operation="tw.refresh_realtime_snapshot",
            refresh_bounds=RefreshBounds(
                max_calls=3,
                timeout_seconds=40,
                max_symbols=1,
                max_range_days=1,
            ),
            postcondition="During a supported auction session, persist indicative evidence and its raw receipt, reread, and never project it as an actual trade.",
        ),
        DatasetSpec(
            dataset_id="tw.intraday.bars",
            schema_version="omi.market.bar.v1",
            market=Market.TW,
            scope_kind="stock",
            owner="app.market.tw_intraday_platform",
            read_operation="read_taiwan_intraday_bars",
            projection_id="intraday.bars.stock.TW",
            capability_ids=("intraday.bars",),
            frequency=DatasetFrequency.INTRADAY,
            expected_state_policy=ExpectedStatePolicy.CURRENT_SESSION,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT_AND_TRADING_DAY,
            storage_reference="source_registry+raw_fetch_result+market_intraday_bar+market_intraday_bar_lineage",
            refreshable=True,
            refresh_operation="tw.refresh_intraday_bars",
            refresh_bounds=RefreshBounds(
                max_calls=2,
                timeout_seconds=40,
                max_symbols=1,
                max_range_days=93,
            ),
            postcondition="Persist canonical bar receipts, reread, and return bounded resolved bars or a truthful unavailable/partial state.",
            repairable=True,
        ),
        DatasetSpec(
            dataset_id="tw.daily.ohlcv",
            schema_version="omi.market.bar.v1",
            market=Market.TW,
            scope_kind="stock",
            owner="app.market.daily_ohlcv_platform",
            read_operation="MarketDataGateway.resolve_bars",
            projection_id="daily.ohlcv.stock.TW",
            capability_ids=("daily.ohlcv", "technical.structure"),
            frequency=DatasetFrequency.DAILY,
            expected_state_policy=ExpectedStatePolicy.REQUESTED_OR_LATEST_COMPLETED,
            eligibility_policy=(
                EligibilityPolicy.LISTED_INSTRUMENT_MARKET_DAY_AND_INSTRUMENT_ELIGIBLE
            ),
            storage_reference="source_registry+raw_fetch_result+market_daily_price",
            refreshable=True,
            refresh_operation="tw.refresh_daily_price",
            refresh_bounds=RefreshBounds(
                max_calls=1,
                timeout_seconds=30,
                max_symbols=1,
                max_range_days=3650,
            ),
            postcondition="Official raw receipt and canonical row commit, repository reread, and latest selected trade date reaches the bounded expected date.",
            repairable=True,
        ),
        DatasetSpec(
            dataset_id="tw.market_index.current",
            schema_version="omi.market.index_observation.v1",
            market=Market.TW,
            scope_kind="market_index",
            owner="app.market.tw_current_market_platform",
            read_operation="read_taiwan_current_index",
            projection_id="market.index.snapshot.index.TW",
            capability_ids=("market.index.snapshot",),
            frequency=DatasetFrequency.EVENT,
            expected_state_policy=ExpectedStatePolicy.CURRENT_SESSION,
            eligibility_policy=EligibilityPolicy.MARKET_TRADING_DAY,
            storage_reference="source_registry+raw_fetch_result+taiwan_current_index_snapshot",
            refreshable=True,
            refresh_operation="tw.refresh_current_index",
            refresh_bounds=RefreshBounds(
                max_calls=2,
                timeout_seconds=40,
                max_symbols=1,
                max_range_days=1,
            ),
            postcondition="Persist and reread a canonical provisional current index snapshot without replacing completed official evidence.",
            repairable=False,
        ),
        DatasetSpec(
            dataset_id="tw.market_breadth.current",
            schema_version="omi.market.breadth.v1",
            market=Market.TW,
            scope_kind="market",
            owner="app.market.tw_current_market_platform",
            read_operation="read_taiwan_current_breadth",
            projection_id="market.breadth.current.market.TW",
            capability_ids=("market.breadth.current",),
            frequency=DatasetFrequency.EVENT,
            expected_state_policy=ExpectedStatePolicy.CURRENT_SESSION,
            eligibility_policy=EligibilityPolicy.MARKET_TRADING_DAY,
            storage_reference="source_registry+raw_fetch_result+taiwan_current_breadth_snapshot",
            refreshable=True,
            refresh_operation="tw.refresh_current_breadth",
            refresh_bounds=RefreshBounds(
                max_calls=1,
                timeout_seconds=40,
                max_symbols=1,
                max_range_days=1,
            ),
            postcondition="Persist and reread canonical current breadth with unknown and missing partitions preserved.",
            repairable=False,
        ),
        DatasetSpec(
            dataset_id="tw.technical.daily",
            schema_version="tw.technical.indicator_series.v3",
            market=Market.TW,
            scope_kind="stock",
            owner="app.market.technical_indicator_gateway",
            read_operation="calculate_active_daily_indicators",
            projection_id="technical.indicators.daily.TW",
            capability_ids=("technical.indicators", "technical.structure"),
            frequency=DatasetFrequency.DAILY,
            expected_state_policy=ExpectedStatePolicy.REQUESTED_OR_LATEST_COMPLETED,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT,
            storage_reference="source_registry+raw_fetch_result+market_daily_price",
            postcondition="Versioned backend series derives from resolved persisted daily OHLCV with algorithm, price basis, and parameter contract.",
        ),
        DatasetSpec(
            dataset_id="us.intraday.bars",
            schema_version="omi.market.bar.v1",
            market=Market.US,
            scope_kind="us_stock",
            owner="app.us_market.service",
            read_operation="get_us_stock_intraday_trend",
            projection_id="intraday.bars.us_stock.US",
            capability_ids=("quote.snapshot", "intraday.bars"),
            frequency=DatasetFrequency.INTRADAY,
            expected_state_policy=ExpectedStatePolicy.CURRENT_SESSION,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT_AND_TRADING_DAY,
            storage_reference="request_scoped_provider_result",
            refreshable=True,
            refresh_operation="us.read_intraday_trend",
            refresh_bounds=RefreshBounds(
                max_calls=1,
                timeout_seconds=25,
                max_symbols=1,
                max_range_days=5,
            ),
            postcondition="Return bounded current-session bars or a truthful provider limitation.",
        ),
        DatasetSpec(
            dataset_id="us.daily.ohlcv",
            schema_version="omi.market.bar.v1",
            market=Market.US,
            scope_kind="us_stock",
            owner="app.us_market.service",
            read_operation="get_us_daily_prices",
            projection_id="daily.ohlcv.us_stock.US",
            capability_ids=("daily.ohlcv",),
            frequency=DatasetFrequency.DAILY,
            expected_state_policy=ExpectedStatePolicy.REQUESTED_OR_LATEST_COMPLETED,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT,
            storage_reference="us_daily_price",
            refreshable=True,
            refresh_operation="us.refresh_daily_price",
            refresh_bounds=RefreshBounds(
                max_calls=1,
                timeout_seconds=30,
                max_symbols=1,
                max_range_days=3650,
            ),
            postcondition="Latest stored trade date reaches the bounded requested/expected date.",
            repairable=True,
        ),
        DatasetSpec(
            dataset_id="tw.daily.ohlcv.full_market",
            schema_version="omi.market.eod_coverage.v1",
            market=Market.TW,
            scope_kind="full_market_stock_universe",
            owner="app.market_data.eod_coverage",
            read_operation="cached_eod_coverage_projection",
            projection_id="daily.ohlcv.full_market.TW",
            capability_ids=("daily.ohlcv",),
            frequency=DatasetFrequency.DAILY,
            expected_state_policy=ExpectedStatePolicy.LATEST_COMPLETED_SESSION,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT,
            storage_reference="market_dataset_coverage_checkpoint+market_daily_price",
            refreshable=True,
            refresh_operation="tw.reconcile_full_market_eod",
            refresh_bounds=RefreshBounds(
                max_calls=2,
                timeout_seconds=120,
                max_symbols=2,
                max_range_days=1,
            ),
            postcondition="All active TWSE/TPEx ordinary stocks are classified current, partial, stale, or missing for the expected completed session.",
            repairable=True,
        ),
        DatasetSpec(
            dataset_id="us.daily.ohlcv.full_market",
            schema_version="omi.market.eod_coverage.v1",
            market=Market.US,
            scope_kind="full_market_stock_universe",
            owner="app.market_data.eod_coverage",
            read_operation="cached_eod_coverage_projection",
            projection_id="daily.ohlcv.full_market.US",
            capability_ids=("daily.ohlcv",),
            frequency=DatasetFrequency.DAILY,
            expected_state_policy=ExpectedStatePolicy.LATEST_COMPLETED_SESSION,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT,
            storage_reference="market_dataset_coverage_checkpoint+us_daily_price",
            refreshable=True,
            refresh_operation="us.reconcile_full_market_eod",
            refresh_bounds=RefreshBounds(
                max_calls=250,
                timeout_seconds=120,
                max_symbols=250,
                max_range_days=5,
            ),
            postcondition="The official active US stock universe has a durable bounded progress checkpoint for the expected completed session.",
            repairable=True,
        ),
        DatasetSpec(
            dataset_id="tw.market_index.daily",
            schema_version="omi.market.index_observation.v1",
            market=Market.TW,
            scope_kind="official_market_index",
            owner="app.market.official_index_platform",
            read_operation="MarketDataGateway.resolve_market_index",
            projection_id="market.index.daily.TW",
            capability_ids=("market.index.daily",),
            frequency=DatasetFrequency.DAILY,
            expected_state_policy=ExpectedStatePolicy.LATEST_COMPLETED_SESSION,
            eligibility_policy=EligibilityPolicy.MARKET_TRADING_DAY,
            storage_reference=(
                "source_registry+raw_fetch_result+market_index_daily_stat"
            ),
            refreshable=True,
            refresh_operation="tw.refresh_official_market_index",
            refresh_bounds=RefreshBounds(
                max_calls=1,
                timeout_seconds=30,
                max_symbols=1,
                max_range_days=1,
            ),
            postcondition=(
                "The requested official TAIEX/TPEX completed-session row rereads "
                "with raw receipt lineage and selected resolved evidence."
            ),
            repairable=True,
        ),
        DatasetSpec(
            dataset_id="tw.market_breadth.daily",
            schema_version="omi.market.breadth.v1",
            market=Market.TW,
            scope_kind="venue_active_ordinary_stock_universe",
            owner="app.market.official_breadth_platform",
            read_operation="MarketDataGateway.resolve_market_breadth",
            projection_id="market.breadth.venue.TW",
            capability_ids=("market.breadth",),
            frequency=DatasetFrequency.DAILY,
            expected_state_policy=ExpectedStatePolicy.LATEST_COMPLETED_SESSION,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT,
            storage_reference=(
                "stock_master+source_registry+raw_fetch_result+market_daily_price"
            ),
            refreshable=True,
            refresh_operation="tw.reconcile_full_market_eod",
            refresh_bounds=RefreshBounds(
                max_calls=2,
                timeout_seconds=120,
                max_symbols=2,
                max_range_days=1,
            ),
            postcondition=(
                "Each TWSE/TPEX active ordinary-stock member is classified as "
                "advance, decline, unchanged, unknown, or missing from one "
                "coherent official raw receipt."
            ),
            repairable=True,
        ),
    )
)


__all__ = [
    "DATASET_REGISTRY",
    "DatasetFrequency",
    "DatasetRegistry",
    "DatasetSpec",
    "EligibilityPolicy",
    "ExpectedStatePolicy",
    "INTERNAL_DATASET_REFRESH_OPERATIONS",
    "RefreshBounds",
    "evaluate_dataset_health",
]
