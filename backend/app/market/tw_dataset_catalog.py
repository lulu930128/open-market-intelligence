"""Market-owned lifecycle catalog for Taiwan production dataset families.

The catalog is declarative. It names current readers and bounded mutation
operations without importing them, so provider and storage implementations do
not leak into the shared market-data core.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from app.market_data.contracts import CanonicalModel, Market
from app.market_data.registry import RefreshBounds


class TaiwanDatasetFrequency(str, Enum):
    EVENT = "event"
    INTRADAY = "intraday"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    IRREGULAR = "irregular"


class TaiwanExpectedStatePolicy(str, Enum):
    CURRENT_SESSION = "current_session"
    LATEST_COMPLETED_SESSION = "latest_completed_session"
    REQUESTED_OR_LATEST_COMPLETED = "requested_or_latest_completed"
    LATEST_PUBLISHED_PERIOD = "latest_published_period"
    ON_DEMAND_SNAPSHOT = "on_demand_snapshot"


class TaiwanDatasetLineageStatus(str, Enum):
    CANONICAL_RAW_RECEIPT = "canonical_raw_receipt"
    DERIVED_COMPONENT_LINEAGE = "derived_component_lineage"
    SOURCE_RAW_COMPATIBILITY = "source_raw_compatibility"
    SOURCE_ONLY = "source_only"
    LINEAGE_GAP = "lineage_gap"


class TaiwanDatasetConvergenceStatus(str, Enum):
    PLATFORM_OWNED = "platform_owned"
    COMPATIBILITY = "compatibility"
    COMPATIBILITY_DERIVED = "compatibility_derived"
    LINEAGE_GAP = "lineage_gap"


class TaiwanDatasetOperationSpec(CanonicalModel):
    contract_version: str = "omi.market.tw_dataset_operation.v1"
    operation_id: str = Field(min_length=1, max_length=128)
    callable_path: str = Field(min_length=3, max_length=256)
    external_io: bool
    writes_storage: bool
    bounds: RefreshBounds
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_callable_path(self) -> TaiwanDatasetOperationSpec:
        module, separator, function = self.callable_path.rpartition(".")
        if not separator or not module.startswith("app.") or not function:
            raise ValueError("operation callable_path must be an app module function")
        if ".routers." in module or ".ai." in module:
            raise ValueError("dataset operations cannot be owned by routers or AI")
        return self


class TaiwanDatasetContract(CanonicalModel):
    contract_version: str = "omi.market.tw_dataset_contract.v1"
    dataset_id: str = Field(min_length=1, max_length=128)
    family: str = Field(min_length=1, max_length=64)
    payload_contract: str = Field(min_length=1, max_length=128)
    market: Market = Market.TW
    scope_kind: str = Field(min_length=1, max_length=96)
    capability_ids: tuple[str, ...]
    storage_tables: tuple[str, ...]
    read_operation: str = Field(min_length=3, max_length=256)
    projection_operation: str = Field(min_length=3, max_length=256)
    health_operation: str = Field(min_length=3, max_length=256)
    frequency: TaiwanDatasetFrequency
    expected_state_policy: TaiwanExpectedStatePolicy
    eligibility_policy: str = Field(min_length=1, max_length=128)
    advertised: bool = True
    refreshable: bool = False
    repairable: bool = False
    refresh_operation: str | None = Field(default=None, max_length=128)
    refresh_bounds: RefreshBounds | None = None
    postcondition: str = Field(min_length=1, max_length=512)
    lineage_status: TaiwanDatasetLineageStatus
    required_lineage_fields: tuple[str, ...] = ()
    convergence_status: TaiwanDatasetConvergenceStatus
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> TaiwanDatasetContract:
        if not self.capability_ids:
            raise ValueError("Taiwan dataset requires capability mappings")
        if not self.storage_tables:
            raise ValueError("Taiwan dataset requires durable storage tables")
        if self.refreshable:
            if self.refresh_operation is None or self.refresh_bounds is None:
                raise ValueError("refreshable dataset requires operation and bounds")
        elif self.refresh_operation is not None or self.refresh_bounds is not None:
            raise ValueError("non-refreshable dataset cannot advertise refresh metadata")
        if self.repairable and not self.refreshable:
            raise ValueError("repairable dataset must be refreshable")
        if (
            self.lineage_status is TaiwanDatasetLineageStatus.LINEAGE_GAP
            and self.repairable
        ):
            raise ValueError("lineage-gap dataset cannot advertise repairability")
        if (
            self.convergence_status is TaiwanDatasetConvergenceStatus.PLATFORM_OWNED
            and self.lineage_status
            not in {
                TaiwanDatasetLineageStatus.CANONICAL_RAW_RECEIPT,
                TaiwanDatasetLineageStatus.DERIVED_COMPONENT_LINEAGE,
            }
        ):
            raise ValueError("platform-owned dataset requires canonical lineage")
        return self


class TaiwanDatasetCatalog:
    def __init__(
        self,
        *,
        datasets: tuple[TaiwanDatasetContract, ...],
        operations: tuple[TaiwanDatasetOperationSpec, ...],
    ) -> None:
        self._datasets = datasets
        self._operations = operations
        self._by_dataset = {item.dataset_id: item for item in datasets}
        self._by_operation = {item.operation_id: item for item in operations}
        if len(self._by_dataset) != len(datasets):
            raise ValueError("Taiwan dataset IDs must be unique")
        if len(self._by_operation) != len(operations):
            raise ValueError("Taiwan dataset operation IDs must be unique")
        for dataset in datasets:
            if not dataset.refreshable:
                continue
            operation = self._by_operation.get(str(dataset.refresh_operation))
            if operation is None:
                raise ValueError(
                    f"dataset '{dataset.dataset_id}' references unknown operation"
                )
            if dataset.refresh_bounds != operation.bounds:
                raise ValueError(
                    f"dataset '{dataset.dataset_id}' bounds drift from operation"
                )

    def get(self, dataset_id: str) -> TaiwanDatasetContract:
        try:
            return self._by_dataset[dataset_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Taiwan dataset: {dataset_id}") from exc

    def operation(self, operation_id: str) -> TaiwanDatasetOperationSpec:
        try:
            return self._by_operation[operation_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Taiwan dataset operation: {operation_id}") from exc

    def all(self) -> tuple[TaiwanDatasetContract, ...]:
        return self._datasets

    def operations(self) -> tuple[TaiwanDatasetOperationSpec, ...]:
        return self._operations


def _bounds(
    calls: int,
    timeout: int,
    symbols: int,
    days: int,
) -> RefreshBounds:
    return RefreshBounds(
        max_calls=calls,
        timeout_seconds=timeout,
        max_symbols=symbols,
        max_range_days=days,
    )


TW_DATASET_OPERATIONS = (
    TaiwanDatasetOperationSpec(
        operation_id="tw.acquire_public_last_trade_quote",
        callable_path="app.market.public_quote_platform.acquire_taiwan_public_last_trade_quote",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(1, 10, 1, 1),
        limitations=("PUBLIC_BEST_EFFORT_NO_SLA", "ACTIVE_SESSION_ONLY"),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_realtime_snapshot",
        callable_path="app.market.taiwan_realtime_platform.refresh_taiwan_realtime_snapshot",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(3, 40, 1, 1),
        limitations=(
            "ACTIVE_SESSION_ONLY",
            "AUCTION_EVIDENCE_ONLY_DURING_SUPPORTED_AUCTION_SESSION",
            "INDICATIVE_NOT_ACTUAL_TRADE",
        ),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_intraday_bars",
        callable_path="app.market.tw_intraday_platform.refresh_taiwan_intraday_bars",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(2, 40, 1, 93),
        limitations=(
            "VENDOR_BEST_EFFORT_NO_SLA",
            "ACTIVE_SESSION_DATA_NOT_REPAIRABLE_AFTER_PROVIDER_RETENTION",
        ),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_current_index",
        callable_path="app.market.tw_current_market_operations.refresh_taiwan_current_index_operation",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(2, 40, 1, 1),
        limitations=("CURRENT_SESSION_ONLY", "PROVISIONAL_EVIDENCE"),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_current_breadth",
        callable_path="app.market.tw_current_market_operations.refresh_taiwan_current_breadth_operation",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(1, 40, 1, 1),
        limitations=("CURRENT_SESSION_ONLY", "COVERAGE_MAY_BE_PARTIAL"),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_daily_price",
        callable_path="app.market.daily_ohlcv_platform.refresh_taiwan_official_daily",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(1, 30, 1, 3650),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.reconcile_full_market_eod",
        callable_path="app.market_data.eod_coverage.reconcile_eod_coverage",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(2, 120, 2, 1),
        limitations=("VENUE_BOUNDED_BULK_REFRESH",),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_official_market_index",
        callable_path="app.market.official_index_platform.refresh_taiwan_official_index",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(1, 30, 1, 1),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_market_chip_daily",
        callable_path="app.market.market_chips.refresh_market_chip_daily",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(20, 120, 2, 1),
        limitations=("LEGACY_TRANSACTION_OWNER", "RAW_RECEIPT_LINEAGE_GAP"),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_institutional",
        callable_path="app.market.daily_metrics_backfill.ensure_stock_daily_metrics",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(3, 120, 1, 31),
        limitations=("LEGACY_MULTI_CATEGORY_ENTRYPOINT",),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_margin",
        callable_path="app.market.daily_metrics_backfill.ensure_stock_daily_metrics",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(3, 120, 1, 31),
        limitations=("LEGACY_MULTI_CATEGORY_ENTRYPOINT",),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_broker_branch",
        callable_path="app.market.broker_branch.ensure_broker_branch_daily",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(1, 120, 1, 1),
        limitations=("TOP15_CENSORED_COVERAGE",),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_shareholding",
        callable_path="app.market.shareholding_history_backfill.ensure_stock_shareholding_history",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(12, 120, 1, 370),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_revenue",
        callable_path="app.market.monthly_revenue_history_backfill.ensure_stock_monthly_revenue_history",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(24, 120, 1, 730),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_financials",
        callable_path="app.market.financial_metrics_history_backfill.ensure_stock_financial_metrics_history",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(16, 120, 1, 1460),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_company_profile",
        callable_path="app.market.taiwan_fundamental_snapshot_refresh.refresh_taiwan_fundamental_snapshot",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(3, 120, 1, 1),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_corporate_events",
        callable_path="app.market.tw_corporate_events.refresh_taiwan_corporate_events",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(12, 120, 3, 93),
        limitations=("FILE_CACHE_RAW_RECEIPT_GAP",),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_etf",
        callable_path="app.market.tw_etf.refresh_taiwan_etf",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(4, 120, 1, 2),
        limitations=("TWSE_ETF_V1", "MULTI_RESOURCE_LEGACY_TRANSACTION"),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_derivatives",
        callable_path="app.market.tw_derivatives.refresh_taiwan_derivatives",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(5, 120, 5, 1),
        limitations=("TAIFEX_POST_CLOSE", "RAW_RECEIPT_LINEAGE_GAP"),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_futures_quote",
        callable_path="app.market.tw_futures.refresh_taiwan_futures_quotes",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(3, 30, 3, 1),
        limitations=("KGI_PROVIDER_DEFERRED",),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_futures_intraday",
        callable_path="app.market.tw_futures.refresh_taiwan_futures_intraday_bars",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(1, 30, 1, 1),
    ),
    TaiwanDatasetOperationSpec(
        operation_id="tw.refresh_futures_daily",
        callable_path="app.market.tw_futures.refresh_taiwan_futures_daily_bars",
        external_io=True,
        writes_storage=True,
        bounds=_bounds(1, 120, 1, 1000),
    ),
)


def _dataset(
    *,
    dataset_id: str,
    family: str,
    payload: str,
    scope: str,
    capabilities: tuple[str, ...],
    tables: tuple[str, ...],
    read: str,
    projection: str,
    health: str = "app.market.tw_dataset_health.read_taiwan_dataset_platform_projection",
    frequency: TaiwanDatasetFrequency,
    expected: TaiwanExpectedStatePolicy,
    eligibility: str,
    postcondition: str,
    lineage: TaiwanDatasetLineageStatus,
    convergence: TaiwanDatasetConvergenceStatus,
    lineage_fields: tuple[str, ...] = (),
    refresh_operation: str | None = None,
    refresh_bounds: RefreshBounds | None = None,
    repairable: bool = False,
    limitations: tuple[str, ...] = (),
) -> TaiwanDatasetContract:
    return TaiwanDatasetContract(
        dataset_id=dataset_id,
        family=family,
        payload_contract=payload,
        scope_kind=scope,
        capability_ids=capabilities,
        storage_tables=tables,
        read_operation=read,
        projection_operation=projection,
        health_operation=health,
        frequency=frequency,
        expected_state_policy=expected,
        eligibility_policy=eligibility,
        refreshable=refresh_operation is not None,
        repairable=repairable,
        refresh_operation=refresh_operation,
        refresh_bounds=refresh_bounds,
        postcondition=postcondition,
        lineage_status=lineage,
        required_lineage_fields=lineage_fields,
        convergence_status=convergence,
        limitations=limitations,
    )


_CANONICAL_LINEAGE = (
    "source_id",
    "raw_result_id",
    "event_or_trade_date",
    "fetched_at",
    "content_hash",
)


TW_DATASET_CONTRACTS = (
    _dataset(
        dataset_id="tw.quote.snapshot",
        family="quote",
        payload="omi.market.quote.v1",
        scope="listed_stock_or_etf",
        capabilities=(
            "quote.snapshot",
            "quote.last_trade",
            "quote.session_close",
        ),
        tables=("source_registry", "raw_fetch_result", "taiwan_stock_quote_snapshot"),
        read="app.market.public_quote_platform.read_taiwan_public_last_trade_quote",
        projection="app.routers.tw_public_quotes.get_public_last_trade_quote",
        frequency=TaiwanDatasetFrequency.EVENT,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="listed_instrument_and_trading_day",
        refresh_operation="tw.acquire_public_last_trade_quote",
        refresh_bounds=_bounds(1, 10, 1, 1),
        repairable=False,
        postcondition="Repository reread selects an actual last trade or returns truthful missing, stale, partial, or policy_unsatisfied evidence.",
        lineage=TaiwanDatasetLineageStatus.CANONICAL_RAW_RECEIPT,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
        limitations=("PUBLIC_BEST_EFFORT_NO_SLA",),
    ),
    _dataset(
        dataset_id="tw.quote.order_book.snapshot",
        family="quote",
        payload="omi.market.depth.v1",
        scope="listed_stock_or_etf",
        capabilities=("quote.order_book",),
        tables=(
            "source_registry",
            "raw_fetch_result",
            "taiwan_stock_depth_snapshot",
            "taiwan_stock_depth_level",
        ),
        read="app.market.taiwan_realtime_platform.read_taiwan_depth",
        projection="app.market.quote_depth.get_taiwan_stock_quote_depth",
        frequency=TaiwanDatasetFrequency.EVENT,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="listed_instrument_current_session",
        refresh_operation="tw.refresh_realtime_snapshot",
        refresh_bounds=_bounds(3, 40, 1, 1),
        repairable=False,
        postcondition="Repository reread resolves a bounded canonical order book with provider, source, event time, raw receipt, quality, and truthful limitations.",
        lineage=TaiwanDatasetLineageStatus.CANONICAL_RAW_RECEIPT,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
        limitations=("ACTIVE_SESSION_ONLY", "LEVEL_5_MAXIMUM"),
    ),
    _dataset(
        dataset_id="tw.quote.auction.snapshot",
        family="quote",
        payload="omi.market.auction.v1",
        scope="listed_stock_or_etf",
        capabilities=("quote.auction",),
        tables=(
            "source_registry",
            "raw_fetch_result",
            "taiwan_stock_auction_snapshot",
        ),
        read="app.market.taiwan_realtime_platform.read_taiwan_auction",
        projection="app.market.quote_depth.get_taiwan_stock_quote_depth",
        frequency=TaiwanDatasetFrequency.EVENT,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="listed_instrument_supported_auction_session",
        refresh_operation="tw.refresh_realtime_snapshot",
        refresh_bounds=_bounds(3, 40, 1, 1),
        repairable=False,
        postcondition="Supported-session indicative auction evidence persists with raw lineage, rereads through quality and Resolver, and never becomes an actual trade.",
        lineage=TaiwanDatasetLineageStatus.CANONICAL_RAW_RECEIPT,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
        limitations=(
            "SUPPORTED_AUCTION_SESSION_ONLY",
            "INDICATIVE_NOT_ACTUAL_TRADE",
        ),
    ),
    _dataset(
        dataset_id="tw.intraday.bars",
        family="price",
        payload="omi.market.bar.v1",
        scope="listed_stock",
        capabilities=("intraday.bars",),
        tables=(
            "source_registry",
            "raw_fetch_result",
            "market_intraday_bar",
            "market_intraday_bar_lineage",
        ),
        read="app.market.tw_intraday_platform.read_taiwan_intraday_bars",
        projection="app.routers.market.get_stock_intraday_history",
        frequency=TaiwanDatasetFrequency.INTRADAY,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="listed_instrument_and_trading_day",
        refresh_operation="tw.refresh_intraday_bars",
        refresh_bounds=_bounds(2, 40, 1, 93),
        repairable=True,
        postcondition="Provider observations and raw receipts commit atomically, then repository reread resolves bounded bars without presenting a quote snapshot as a bar.",
        lineage=TaiwanDatasetLineageStatus.DERIVED_COMPONENT_LINEAGE,
        lineage_fields=(
            *_CANONICAL_LINEAGE,
            "source_interval",
            "calculation_version",
            "component_raw_result_ids",
        ),
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
        limitations=(
            "VENDOR_BEST_EFFORT_NO_SLA",
            "DERIVED_INTERVALS_REQUIRE_COMPONENT_LINEAGE_PROJECTION",
        ),
    ),
    _dataset(
        dataset_id="tw.daily.ohlcv",
        family="price",
        payload="omi.market.bar.v1",
        scope="listed_stock_or_etf",
        capabilities=("daily.ohlcv", "technical.structure"),
        tables=("source_registry", "raw_fetch_result", "market_daily_price"),
        read="app.market.service.list_stock_ohlc_chart_data",
        projection="app.market.service.list_stock_ohlc_chart_data",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.REQUESTED_OR_LATEST_COMPLETED,
        eligibility="listed_instrument_market_day_and_instrument_eligible",
        refresh_operation="tw.refresh_daily_price",
        refresh_bounds=_bounds(1, 30, 1, 3650),
        repairable=True,
        postcondition="Official receipt and canonical row commit, reread, and resolve through the shared Gateway.",
        lineage=TaiwanDatasetLineageStatus.CANONICAL_RAW_RECEIPT,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
    ),
    _dataset(
        dataset_id="tw.market_index.current",
        family="market_state",
        payload="omi.market.index_observation.v1",
        scope="TAIEX_or_TPEX",
        capabilities=("market.index.snapshot",),
        tables=(
            "source_registry",
            "raw_fetch_result",
            "taiwan_current_index_snapshot",
        ),
        read="app.market.tw_current_market_platform.read_taiwan_current_index",
        projection="app.market.tw_current_market_platform.project_taiwan_current_index",
        frequency=TaiwanDatasetFrequency.EVENT,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="current_taiwan_session_and_supported_index",
        refresh_operation="tw.refresh_current_index",
        refresh_bounds=_bounds(2, 40, 1, 1),
        repairable=False,
        postcondition="Current index raw receipt and canonical snapshot commit, reread, quality evaluate, and resolve without changing completed official evidence.",
        lineage=TaiwanDatasetLineageStatus.CANONICAL_RAW_RECEIPT,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
        limitations=("CURRENT_SESSION_PROVISIONAL", "HISTORICAL_GAPS_NOT_REPAIRABLE"),
    ),
    _dataset(
        dataset_id="tw.market_breadth.current",
        family="market_state",
        payload="omi.market.breadth.v1",
        scope="TWSE_or_TPEX_full_market_registered_stock_universe",
        capabilities=("market.breadth.current",),
        tables=(
            "source_registry",
            "raw_fetch_result",
            "taiwan_current_breadth_snapshot",
        ),
        read="app.market.tw_current_market_platform.read_taiwan_current_breadth",
        projection="app.market.tw_current_market_platform.project_taiwan_current_breadth",
        frequency=TaiwanDatasetFrequency.EVENT,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="current_taiwan_session_and_supported_venue",
        refresh_operation="tw.refresh_current_breadth",
        refresh_bounds=_bounds(1, 40, 1, 1),
        repairable=False,
        postcondition="Current breadth preserves classified, received-unclassified, and not-received partitions through canonical reread and resolution.",
        lineage=TaiwanDatasetLineageStatus.CANONICAL_RAW_RECEIPT,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
        limitations=("CURRENT_SESSION_PROVISIONAL", "COVERAGE_MAY_BE_PARTIAL"),
    ),
    _dataset(
        dataset_id="tw.technical.daily",
        family="technical",
        payload="tw.technical.indicator_series.v3",
        scope="listed_stock_or_etf",
        capabilities=("technical.indicators", "technical.structure"),
        tables=("source_registry", "raw_fetch_result", "market_daily_price"),
        read="app.market.technical_indicator_gateway.calculate_active_daily_indicators",
        projection="app.routers.indicators.get_stock_daily_indicators",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.REQUESTED_OR_LATEST_COMPLETED,
        eligibility="listed_instrument_with_resolved_daily_ohlcv",
        postcondition="Versioned backend series derives only from persisted resolved daily OHLCV and exposes algorithm, price basis, and parameter contract.",
        lineage=TaiwanDatasetLineageStatus.DERIVED_COMPONENT_LINEAGE,
        lineage_fields=(
            "daily_ohlcv_source_id",
            "daily_ohlcv_raw_result_id",
            "algorithm_version",
            "price_basis",
            "parameter_contract",
        ),
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
        limitations=("DERIVED_FROM_TW_DAILY_OHLCV",),
    ),
    _dataset(
        dataset_id="tw.daily.ohlcv.full_market",
        family="price",
        payload="omi.market.eod_coverage.v1",
        scope="full_market_stock_universe",
        capabilities=("daily.ohlcv",),
        tables=("market_dataset_coverage_checkpoint", "market_daily_price"),
        read="app.market_data.eod_coverage.cached_eod_coverage_projection",
        projection="app.routers.market_data.get_eod_coverage",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="active_registered_universe",
        refresh_operation="tw.reconcile_full_market_eod",
        refresh_bounds=_bounds(2, 120, 2, 1),
        repairable=True,
        postcondition="Current, partial, stale, and missing partitions equal the active universe after persisted reread.",
        lineage=TaiwanDatasetLineageStatus.DERIVED_COMPONENT_LINEAGE,
        lineage_fields=("expected_trade_date", "latest_trade_date", "partition_counts"),
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
    ),
    _dataset(
        dataset_id="tw.market_breadth.daily",
        family="market_state",
        payload="omi.market.breadth.v1",
        scope="venue_active_ordinary_stock_universe",
        capabilities=("market.breadth",),
        tables=("stock_master", "source_registry", "raw_fetch_result", "market_daily_price"),
        read="app.market.official_breadth_platform.read_taiwan_official_breadth",
        projection="app.routers.market.get_taiwan_official_market_breadth",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="active_registered_ordinary_stock_universe",
        refresh_operation="tw.reconcile_full_market_eod",
        refresh_bounds=_bounds(2, 120, 2, 1),
        repairable=True,
        postcondition="One coherent official venue/date receipt partitions every active member into advance, decline, unchanged, unknown, or missing.",
        lineage=TaiwanDatasetLineageStatus.DERIVED_COMPONENT_LINEAGE,
        lineage_fields=("source_id", "raw_result_id", "trade_date", "universe_count"),
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
    ),
    _dataset(
        dataset_id="tw.market_index.daily",
        family="market_state",
        payload="omi.market.index_observation.v1",
        scope="official_market_index",
        capabilities=("market.index.daily",),
        tables=("source_registry", "raw_fetch_result", "market_index_daily_stat"),
        read="app.market.official_index_platform.read_taiwan_official_index",
        projection="app.routers.tw_market_indices.get_official_index_daily",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="market_trading_day",
        refresh_operation="tw.refresh_official_market_index",
        refresh_bounds=_bounds(1, 30, 1, 1),
        repairable=True,
        postcondition="Official index row rereads with raw receipt lineage and shared Resolver selection.",
        lineage=TaiwanDatasetLineageStatus.CANONICAL_RAW_RECEIPT,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.PLATFORM_OWNED,
    ),
    _dataset(
        dataset_id="tw.chips.market.daily",
        family="chips",
        payload="tw.market_chip.daily.v1",
        scope="market_index",
        capabilities=("derivatives.positioning",),
        tables=("market_chip_daily",),
        read="app.market.market_chips.get_latest_market_chip_daily",
        projection="app.market.market_chips.market_chip_daily_to_dict",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="supported_market_index_and_release_window",
        refresh_operation="tw.refresh_market_chip_daily",
        refresh_bounds=_bounds(20, 120, 2, 1),
        postcondition="Persist and reread every released component with explicit missing fields and source detail.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("SOURCE_DETAILS_WITHOUT_RAW_RECEIPT_FK",),
    ),
    _dataset(
        dataset_id="tw.chips.institutional.daily",
        family="chips",
        payload="tw.chips.institutional.v1",
        scope="listed_stock",
        capabilities=("chips.institutional",),
        tables=("source_registry", "raw_fetch_result", "institutional_trade_daily"),
        read="app.market.service.get_latest_stock_institutional_trade",
        projection="app.ai.market_context.taiwan_stock.read_stock_context",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="listed_instrument_market_day_and_release_window",
        refresh_operation="tw.refresh_institutional",
        refresh_bounds=_bounds(3, 120, 1, 31),
        repairable=True,
        postcondition="Expected-date institutional row rereads with source/raw lineage and no silent category omission.",
        lineage=TaiwanDatasetLineageStatus.SOURCE_RAW_COMPATIBILITY,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.COMPATIBILITY,
    ),
    _dataset(
        dataset_id="tw.chips.margin.daily",
        family="chips",
        payload="tw.chips.margin.v1",
        scope="listed_stock",
        capabilities=("chips.margin",),
        tables=("source_registry", "raw_fetch_result", "margin_trading_daily"),
        read="app.market.service.get_latest_stock_margin_trade",
        projection="app.ai.market_context.taiwan_stock.read_stock_context",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="listed_instrument_market_day_and_release_window",
        refresh_operation="tw.refresh_margin",
        refresh_bounds=_bounds(3, 120, 1, 31),
        repairable=True,
        postcondition="Expected-date margin row rereads with source/raw lineage and unknown values preserved.",
        lineage=TaiwanDatasetLineageStatus.SOURCE_RAW_COMPATIBILITY,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.COMPATIBILITY,
    ),
    _dataset(
        dataset_id="tw.chips.broker_branch.daily",
        family="chips",
        payload="tw.broker_branch.summary.v1",
        scope="listed_stock",
        capabilities=("broker_branch.summary",),
        tables=("source_registry", "raw_fetch_result", "broker_branch_trade_daily", "broker_branch_snapshot_quality", "broker_branch_behavior_feature_snapshot"),
        read="app.market.broker_branch.get_broker_branch_trade_summary",
        projection="app.ai.market_context.taiwan_stock.read_stock_broker_branch_context",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="listed_instrument_market_day_and_provider_coverage",
        refresh_operation="tw.refresh_broker_branch",
        refresh_bounds=_bounds(1, 120, 1, 1),
        repairable=True,
        postcondition="Trade and quality rows reread for the expected date with Top15 censored absence semantics intact.",
        lineage=TaiwanDatasetLineageStatus.SOURCE_RAW_COMPATIBILITY,
        lineage_fields=("source_id", "raw_result_id", "expected_trade_date", "absence_semantics", "coverage_status"),
        convergence=TaiwanDatasetConvergenceStatus.COMPATIBILITY,
        limitations=("TOP15_CENSORED_COVERAGE",),
    ),
    _dataset(
        dataset_id="tw.ownership.shareholding.weekly",
        family="chips",
        payload="tw.ownership.distribution.v1",
        scope="listed_stock",
        capabilities=("ownership.distribution",),
        tables=("source_registry", "raw_fetch_result", "shareholding_distribution_weekly"),
        read="app.market.service.list_latest_stock_shareholding_distribution",
        projection="app.ai.market_context.taiwan_stock.read_stock_context",
        frequency=TaiwanDatasetFrequency.WEEKLY,
        expected=TaiwanExpectedStatePolicy.LATEST_PUBLISHED_PERIOD,
        eligibility="listed_instrument_and_tdcc_publication",
        refresh_operation="tw.refresh_shareholding",
        refresh_bounds=_bounds(12, 120, 1, 370),
        repairable=True,
        postcondition="Latest published distribution rereads with source/raw lineage; unpublished is not zero.",
        lineage=TaiwanDatasetLineageStatus.SOURCE_RAW_COMPATIBILITY,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.COMPATIBILITY,
    ),
    _dataset(
        dataset_id="tw.fundamentals.revenue.monthly",
        family="fundamentals",
        payload="tw.fundamentals.revenue.v1",
        scope="listed_stock",
        capabilities=("fundamentals.revenue",),
        tables=("source_registry", "raw_fetch_result", "monthly_revenue"),
        read="app.market.service.get_latest_stock_monthly_revenue",
        projection="app.ai.market_context.taiwan_stock.read_stock_context",
        frequency=TaiwanDatasetFrequency.MONTHLY,
        expected=TaiwanExpectedStatePolicy.LATEST_PUBLISHED_PERIOD,
        eligibility="listed_company_and_mops_publication",
        refresh_operation="tw.refresh_revenue",
        refresh_bounds=_bounds(24, 120, 1, 730),
        repairable=True,
        postcondition="Latest published monthly period rereads with source/raw/report-date lineage.",
        lineage=TaiwanDatasetLineageStatus.SOURCE_RAW_COMPATIBILITY,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.COMPATIBILITY,
    ),
    _dataset(
        dataset_id="tw.fundamentals.financials.quarterly",
        family="fundamentals",
        payload="tw.fundamentals.financials.v1",
        scope="listed_stock",
        capabilities=("fundamentals.financials",),
        tables=("source_registry", "raw_fetch_result", "financial_metric_quarterly", "tw_financial_filing", "tw_financial_statement_fact", "tw_financial_corporate_action", "tw_financial_normalized_fact", "tw_financial_basis_assessment"),
        read="app.market.service.get_latest_stock_financial_metric",
        projection="app.ai.market_context.taiwan_stock.read_stock_context",
        frequency=TaiwanDatasetFrequency.QUARTERLY,
        expected=TaiwanExpectedStatePolicy.LATEST_PUBLISHED_PERIOD,
        eligibility="listed_company_and_filing_publication",
        refresh_operation="tw.refresh_financials",
        refresh_bounds=_bounds(16, 120, 1, 1460),
        repairable=True,
        postcondition="Latest reportable filing/quarter rereads with known-at, source/raw, basis, and normalization limits.",
        lineage=TaiwanDatasetLineageStatus.SOURCE_RAW_COMPATIBILITY,
        lineage_fields=("source_id", "raw_result_id", "report_or_period_end", "known_at_or_filed_at"),
        convergence=TaiwanDatasetConvergenceStatus.COMPATIBILITY,
    ),
    _dataset(
        dataset_id="tw.company.profile",
        family="fundamentals",
        payload="tw.company.profile.v1",
        scope="listed_stock_or_etf",
        capabilities=("company.profile",),
        tables=("source_registry", "raw_fetch_result", "stock_profile"),
        read="app.market.tw_company_profile.read_taiwan_company_profile",
        projection="app.market.tw_company_profile.project_taiwan_company_profile",
        frequency=TaiwanDatasetFrequency.IRREGULAR,
        expected=TaiwanExpectedStatePolicy.LATEST_PUBLISHED_PERIOD,
        eligibility="listed_instrument",
        refresh_operation="tw.refresh_company_profile",
        refresh_bounds=_bounds(3, 120, 1, 1),
        repairable=True,
        postcondition="Latest profile row rereads with source/raw/report-date lineage.",
        lineage=TaiwanDatasetLineageStatus.SOURCE_RAW_COMPATIBILITY,
        lineage_fields=_CANONICAL_LINEAGE,
        convergence=TaiwanDatasetConvergenceStatus.COMPATIBILITY,
        limitations=("COMPATIBILITY_REFRESH_TRANSACTION_OWNER",),
    ),
    _dataset(
        dataset_id="tw.events.corporate",
        family="events",
        payload="tw.events.corporate.v1",
        scope="market_and_listed_stock",
        capabilities=("events.upcoming", "events.calendar", "events.history"),
        tables=("provider_event",),
        read="app.market.tw_corporate_events.list_taiwan_corporate_events",
        projection="app.market.tw_corporate_events.get_taiwan_stock_event_summary",
        frequency=TaiwanDatasetFrequency.EVENT,
        expected=TaiwanExpectedStatePolicy.LATEST_PUBLISHED_PERIOD,
        eligibility="provider_publication_and_lookahead_window",
        refresh_operation="tw.refresh_corporate_events",
        refresh_bounds=_bounds(12, 120, 3, 93),
        postcondition="Current cache and history expose provider, event date, fetched state, errors, and missing providers without destructive replacement.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("FILE_CACHE_WITHOUT_SHARED_RAW_RECEIPT",),
    ),
    _dataset(
        dataset_id="tw.etf.profile",
        family="etf",
        payload="tw.etf.profile.v1",
        scope="twse_etf",
        capabilities=("etf.profile",),
        tables=("taiwan_etf_profile",),
        read="app.market.tw_etf.get_taiwan_etf_overview",
        projection="app.routers.tw_market_etfs.get_taiwan_etf_overview_api",
        frequency=TaiwanDatasetFrequency.IRREGULAR,
        expected=TaiwanExpectedStatePolicy.LATEST_PUBLISHED_PERIOD,
        eligibility="registered_twse_etf",
        refresh_operation="tw.refresh_etf",
        refresh_bounds=_bounds(4, 120, 1, 2),
        postcondition="Profile resource rereads for the target ETF with truthful provider/resource errors.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("SOURCE_URL_WITHOUT_RAW_RECEIPT_FK",),
    ),
    _dataset(
        dataset_id="tw.etf.nav.daily",
        family="etf",
        payload="tw.etf.nav.v1",
        scope="twse_etf",
        capabilities=("etf.nav",),
        tables=("taiwan_etf_nav_daily",),
        read="app.market.tw_etf.get_taiwan_etf_overview",
        projection="app.routers.tw_market_etfs.get_taiwan_etf_overview_api",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="registered_twse_etf_and_nav_release",
        refresh_operation="tw.refresh_etf",
        refresh_bounds=_bounds(4, 120, 1, 2),
        postcondition="Expected NAV date rereads with source and premium/discount inputs or truthful missing fields.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("SOURCE_URL_WITHOUT_RAW_RECEIPT_FK",),
    ),
    _dataset(
        dataset_id="tw.etf.pcf.snapshot",
        family="etf",
        payload="tw.etf.pcf.v1",
        scope="issuer_supported_etf",
        capabilities=("etf.pcf",),
        tables=("taiwan_etf_pcf_snapshot", "taiwan_etf_pcf_component"),
        read="app.market.tw_etf.get_taiwan_etf_overview",
        projection="app.routers.tw_market_etfs.get_taiwan_etf_overview_api",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_PUBLISHED_PERIOD,
        eligibility="issuer_registry_support_and_pcf_publication",
        refresh_operation="tw.refresh_etf",
        refresh_bounds=_bounds(4, 120, 1, 2),
        postcondition="Header and all components reread atomically for one issuer contract and effective date.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("ISSUER_SPECIFIC_CONTRACT", "SOURCE_URL_WITHOUT_RAW_RECEIPT_FK"),
    ),
    _dataset(
        dataset_id="tw.etf.inav.snapshot",
        family="etf",
        payload="tw.etf.inav.v1",
        scope="issuer_supported_etf",
        capabilities=("etf.inav",),
        tables=("taiwan_etf_inav_snapshot",),
        read="app.market.tw_etf.get_taiwan_etf_overview",
        projection="app.routers.tw_market_etfs.get_taiwan_etf_overview_api",
        frequency=TaiwanDatasetFrequency.INTRADAY,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="issuer_registry_support_and_active_session",
        refresh_operation="tw.refresh_etf",
        refresh_bounds=_bounds(4, 120, 1, 2),
        postcondition="Latest issuer iNAV snapshot rereads with observed/fetched time and truthful unavailable status.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("ISSUER_SPECIFIC_CONTRACT", "SOURCE_URL_WITHOUT_RAW_RECEIPT_FK"),
    ),
    _dataset(
        dataset_id="tw.futures.quote.snapshot",
        family="derivatives",
        payload="tw.futures.quote.v1",
        scope="supported_futures_contract",
        capabilities=("quote.snapshot", "derivatives.positioning"),
        tables=("taiwan_futures_quote_snapshot",),
        read="app.market.tw_futures.get_latest_taiwan_futures_quotes",
        projection="app.routers.tw_market_futures.get_latest_taiwan_futures_quotes_api",
        frequency=TaiwanDatasetFrequency.EVENT,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="supported_contract_and_session",
        refresh_operation="tw.refresh_futures_quote",
        refresh_bounds=_bounds(3, 30, 3, 1),
        postcondition="Requested contract/session quote rereads with provider event time or truthful unavailable state.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("RAW_JSON_WITHOUT_RAW_RECEIPT_FK", "KGI_PROVIDER_DEFERRED"),
    ),
    _dataset(
        dataset_id="tw.futures.intraday.bars",
        family="derivatives",
        payload="tw.futures.bar.v1",
        scope="supported_futures_contract",
        capabilities=("intraday.bars", "derivatives.structure"),
        tables=("taiwan_futures_intraday_bar",),
        read="app.market.tw_futures.list_taiwan_futures_intraday_bars",
        projection="app.routers.tw_market_futures.list_taiwan_futures_intraday_bars_api",
        frequency=TaiwanDatasetFrequency.INTRADAY,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="supported_contract_and_session",
        refresh_operation="tw.refresh_futures_intraday",
        refresh_bounds=_bounds(1, 30, 1, 1),
        postcondition="Requested interval rereads without synthesizing missing bars from quote snapshots.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("RAW_RECEIPT_AND_FINALIZATION_GAP",),
    ),
    _dataset(
        dataset_id="tw.futures.daily.bars",
        family="derivatives",
        payload="tw.futures.bar.v1",
        scope="supported_futures_contract",
        capabilities=("daily.ohlcv", "derivatives.structure"),
        tables=("taiwan_futures_daily_bar",),
        read="app.market.tw_futures.list_taiwan_futures_daily_bars",
        projection="app.routers.tw_market_futures.list_taiwan_futures_daily_bars_api",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="supported_contract_and_taifex_release",
        refresh_operation="tw.refresh_futures_daily",
        refresh_bounds=_bounds(1, 120, 1, 1000),
        postcondition="Requested contract/date range rereads with official settlement and volume semantics.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("RAW_JSON_WITHOUT_RAW_RECEIPT_FK",),
    ),
    _dataset(
        dataset_id="tw.derivatives.option_chain.daily",
        family="derivatives",
        payload="tw.derivatives.option_chain.v1",
        scope="txo_option_chain",
        capabilities=("derivatives.structure",),
        tables=("taiwan_option_chain_daily",),
        read="app.market.tw_derivatives.list_taiwan_option_chain",
        projection="app.routers.tw_market_futures.list_taiwan_option_chain_api",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="taifex_post_close_release",
        refresh_operation="tw.refresh_derivatives",
        refresh_bounds=_bounds(5, 120, 5, 1),
        postcondition="Expected-date chain rereads with calculation status, missing Greeks, and source limits.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("MULTI_RESOURCE_RAW_RECEIPT_GAP",),
    ),
    _dataset(
        dataset_id="tw.derivatives.large_trader.daily",
        family="derivatives",
        payload="tw.derivatives.large_trader.v1",
        scope="taifex_top5_top10",
        capabilities=("derivatives.positioning",),
        tables=("taiwan_derivatives_large_trader_daily",),
        read="app.market.tw_derivatives.list_taiwan_large_traders",
        projection="app.routers.tw_market_futures.list_taiwan_large_traders_api",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="taifex_post_close_release",
        refresh_operation="tw.refresh_derivatives",
        refresh_bounds=_bounds(5, 120, 5, 1),
        postcondition="Expected-date Top5/10 rows reread without treating censored absence as zero or total-market inventory.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("TOP5_TOP10_CENSORED", "RAW_RECEIPT_LINEAGE_GAP"),
    ),
    _dataset(
        dataset_id="tw.derivatives.term_structure.daily",
        family="derivatives",
        payload="tw.derivatives.term_structure.v1",
        scope="tx_futures_curve",
        capabilities=("derivatives.structure",),
        tables=("taiwan_futures_term_structure_daily", "market_index_daily_stat"),
        read="app.market.tw_derivatives.list_taiwan_term_structure",
        projection="app.routers.tw_market_futures.list_taiwan_term_structure_api",
        frequency=TaiwanDatasetFrequency.DAILY,
        expected=TaiwanExpectedStatePolicy.LATEST_COMPLETED_SESSION,
        eligibility="taifex_post_close_and_spot_close_available",
        refresh_operation="tw.refresh_derivatives",
        refresh_bounds=_bounds(5, 120, 5, 1),
        postcondition="Curve rereads with futures and spot component dates, calculation status, and explicit missing basis.",
        lineage=TaiwanDatasetLineageStatus.LINEAGE_GAP,
        convergence=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        limitations=("DERIVED_COMPONENT_RAW_LINEAGE_GAP",),
    ),
    _dataset(
        dataset_id="tw.market.minute_state",
        family="market_state",
        payload="tw.market.minute_state.v1",
        scope="market_index_minute",
        capabilities=("market.intraday_state",),
        tables=("taiwan_market_minute_state",),
        read="app.market.indices.get_market_index_intraday",
        projection="app.market.tw_market_dashboard.build_tw_market_dashboard",
        frequency=TaiwanDatasetFrequency.INTRADAY,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="active_market_session",
        postcondition="Derived minute state identifies component freshness, quality, and provisional status without hidden provider acquisition.",
        lineage=TaiwanDatasetLineageStatus.DERIVED_COMPONENT_LINEAGE,
        lineage_fields=(
            "component_raw_result_ids_json",
            "component_sources_json",
            "component_event_times_json",
            "component_time_skew_seconds",
            "calculation_version",
            "lineage_complete",
        ),
        convergence=TaiwanDatasetConvergenceStatus.COMPATIBILITY_DERIVED,
        limitations=("LEGACY_ROWS_WITHOUT_COMPONENT_LINEAGE_ARE_NOT_DECISION_READY",),
    ),
    _dataset(
        dataset_id="tw.stock.intraday.state",
        family="market_state",
        payload="tw.stock.intraday.state.v1",
        scope="bounded_stock_universe",
        capabilities=("quote.snapshot", "market.intraday_state"),
        tables=("taiwan_intraday_stock_state",),
        read="app.market.providers.twse_mis_current_breadth.get_cached_current_breadth_stock_rows",
        projection="app.market.tw_market_dashboard.build_tw_market_dashboard",
        frequency=TaiwanDatasetFrequency.INTRADAY,
        expected=TaiwanExpectedStatePolicy.CURRENT_SESSION,
        eligibility="bounded_universe_and_active_session",
        postcondition="Derived stock state preserves quote-vs-indicative semantics and reports component freshness/quality.",
        lineage=TaiwanDatasetLineageStatus.DERIVED_COMPONENT_LINEAGE,
        lineage_fields=(
            "component_raw_result_ids_json",
            "component_sources_json",
            "component_event_times_json",
            "component_time_skew_seconds",
            "calculation_version",
            "lineage_complete",
        ),
        convergence=TaiwanDatasetConvergenceStatus.COMPATIBILITY_DERIVED,
        limitations=("LEGACY_ROWS_WITHOUT_COMPONENT_LINEAGE_ARE_NOT_DECISION_READY",),
    ),
)


TW_DATASET_CATALOG = TaiwanDatasetCatalog(
    datasets=TW_DATASET_CONTRACTS,
    operations=TW_DATASET_OPERATIONS,
)


__all__ = [
    "TW_DATASET_CATALOG",
    "TW_DATASET_CONTRACTS",
    "TW_DATASET_OPERATIONS",
    "TaiwanDatasetCatalog",
    "TaiwanDatasetContract",
    "TaiwanDatasetConvergenceStatus",
    "TaiwanDatasetFrequency",
    "TaiwanDatasetLineageStatus",
    "TaiwanDatasetOperationSpec",
    "TaiwanExpectedStatePolicy",
]
