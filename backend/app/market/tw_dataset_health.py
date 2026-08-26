"""Cache-only storage and lineage evidence for Taiwan dataset contracts.

This module deliberately does not infer dataset freshness. Release calendars,
instrument eligibility, and current-session semantics remain owned by each
dataset's market service. The common projection answers the narrower questions
that can be evaluated uniformly and without provider I/O: does compatible
storage exist, is there an observed row, and can that row satisfy the catalog's
lineage claim?
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.orm import Session

from app.market.tw_dataset_catalog import (
    TW_DATASET_CATALOG,
    TaiwanDatasetCatalog,
    TaiwanDatasetContract,
    TaiwanDatasetLineageStatus,
)
from app.market_data.contracts import CanonicalModel, DatasetHealth


class TaiwanDatasetStorageStatus(str, Enum):
    OBSERVED = "observed"
    MISSING = "missing"
    LINEAGE_INCOMPLETE = "lineage_incomplete"
    LINEAGE_LIMITED = "lineage_limited"
    SCHEMA_UNAVAILABLE = "schema_unavailable"


@dataclass(frozen=True, slots=True)
class TaiwanDatasetStorageProbe:
    table_name: str
    observed_field: str
    scope_field: str | None = None
    fixed_filters: tuple[tuple[str, object], ...] = ()


class TaiwanDatasetStorageEvidence(CanonicalModel):
    contract_version: str = "omi.market.tw_dataset_storage_evidence.v1"
    dataset_id: str
    checked_at: datetime
    status: TaiwanDatasetStorageStatus
    storage_table: str
    scope_value: str | None = None
    has_observation: bool
    latest_observed_value: str | None = None
    lineage_status: TaiwanDatasetLineageStatus
    lineage_observed: bool | None = None
    freshness_status: str = "not_evaluated"
    detail_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class TaiwanDatasetPlatformProjection(CanonicalModel):
    contract_version: str = "omi.market.tw_dataset_platform_projection.v1"
    contract_scope: Literal["storage_lineage_only"] = "storage_lineage_only"
    dataset: TaiwanDatasetContract
    storage_evidence: TaiwanDatasetStorageEvidence
    lifecycle_health: DatasetHealth | None = None
    limitations: tuple[str, ...] = ("FRESHNESS_REQUIRES_DATASET_POLICY",)


def _probe(
    table: str,
    observed: str,
    scope: str | None = None,
    *fixed_filters: tuple[str, object],
) -> TaiwanDatasetStorageProbe:
    return TaiwanDatasetStorageProbe(
        table_name=table,
        observed_field=observed,
        scope_field=scope,
        fixed_filters=tuple(fixed_filters),
    )


TW_DATASET_STORAGE_PROBES: dict[str, TaiwanDatasetStorageProbe] = {
    "tw.quote.snapshot": _probe("taiwan_stock_quote_snapshot", "fetched_at", "stock_id"),
    "tw.quote.order_book.snapshot": _probe(
        "taiwan_stock_depth_snapshot", "event_at", "stock_id"
    ),
    "tw.quote.auction.snapshot": _probe(
        "taiwan_stock_auction_snapshot", "event_at", "stock_id"
    ),
    "tw.intraday.bars": _probe("market_intraday_bar", "bar_time", "stock_id"),
    "tw.market_index.current": _probe(
        "taiwan_current_index_snapshot", "event_at", "index_id"
    ),
    "tw.market_breadth.current": _probe(
        "taiwan_current_breadth_snapshot", "event_at", "venue"
    ),
    "tw.daily.ohlcv": _probe("market_daily_price", "trade_date", "stock_id"),
    "tw.technical.daily": _probe("market_daily_price", "trade_date", "stock_id"),
    "tw.daily.ohlcv.full_market": _probe(
        "market_dataset_coverage_checkpoint",
        "checked_at",
        None,
        ("dataset_id", "tw.daily.ohlcv"),
        ("market", "TW"),
    ),
    "tw.market_breadth.daily": _probe("market_daily_price", "trade_date"),
    "tw.market_index.daily": _probe("market_index_daily_stat", "trade_date", "index_id"),
    "tw.chips.market.daily": _probe("market_chip_daily", "trade_date", "index_id"),
    "tw.chips.institutional.daily": _probe(
        "institutional_trade_daily", "trade_date", "stock_id"
    ),
    "tw.chips.margin.daily": _probe("margin_trading_daily", "trade_date", "stock_id"),
    "tw.chips.broker_branch.daily": _probe(
        "broker_branch_trade_daily", "trade_date", "stock_id"
    ),
    "tw.ownership.shareholding.weekly": _probe(
        "shareholding_distribution_weekly", "data_date", "stock_id"
    ),
    "tw.fundamentals.revenue.monthly": _probe("monthly_revenue", "period", "stock_id"),
    "tw.fundamentals.financials.quarterly": _probe(
        "financial_metric_quarterly", "period", "stock_id"
    ),
    "tw.company.profile": _probe("stock_profile", "report_date", "stock_id"),
    "tw.events.corporate": _probe(
        "provider_event",
        "observed_at",
        "target",
        ("market", "tw"),
        ("event_type", "corporate_event_refresh"),
    ),
    "tw.etf.profile": _probe("taiwan_etf_profile", "report_date", "stock_id"),
    "tw.etf.nav.daily": _probe("taiwan_etf_nav_daily", "nav_date", "stock_id"),
    "tw.etf.pcf.snapshot": _probe(
        "taiwan_etf_pcf_snapshot", "effective_date", "stock_id"
    ),
    "tw.etf.inav.snapshot": _probe(
        "taiwan_etf_inav_snapshot", "observed_at", "stock_id"
    ),
    "tw.futures.quote.snapshot": _probe(
        "taiwan_futures_quote_snapshot", "fetched_at", "symbol"
    ),
    "tw.futures.intraday.bars": _probe(
        "taiwan_futures_intraday_bar", "bar_time", "symbol"
    ),
    "tw.futures.daily.bars": _probe(
        "taiwan_futures_daily_bar", "trade_date", "symbol"
    ),
    "tw.derivatives.option_chain.daily": _probe(
        "taiwan_option_chain_daily", "trade_date", "product_code"
    ),
    "tw.derivatives.large_trader.daily": _probe(
        "taiwan_derivatives_large_trader_daily", "trade_date", "contract_code"
    ),
    "tw.derivatives.term_structure.daily": _probe(
        "taiwan_futures_term_structure_daily", "trade_date", "symbol"
    ),
    "tw.market.minute_state": _probe(
        "taiwan_market_minute_state", "minute_at", "index_id"
    ),
    "tw.stock.intraday.state": _probe(
        "taiwan_intraday_stock_state", "event_time", "stock_id"
    ),
}


def _serialized_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _lineage_result(
    contract: TaiwanDatasetContract,
    row: Any,
    column_names: set[str],
) -> tuple[TaiwanDatasetStorageStatus, bool | None, tuple[str, ...]]:
    if contract.lineage_status is TaiwanDatasetLineageStatus.LINEAGE_GAP:
        return (
            TaiwanDatasetStorageStatus.LINEAGE_INCOMPLETE,
            False,
            ("CATALOG_DECLARED_LINEAGE_GAP",),
        )
    if contract.lineage_status is TaiwanDatasetLineageStatus.SOURCE_ONLY:
        return (
            TaiwanDatasetStorageStatus.LINEAGE_LIMITED,
            False,
            ("SOURCE_ONLY_WITHOUT_RAW_RECEIPT",),
        )
    if contract.lineage_status is TaiwanDatasetLineageStatus.DERIVED_COMPONENT_LINEAGE:
        return (
            TaiwanDatasetStorageStatus.OBSERVED,
            None,
            ("DERIVED_COMPONENT_LINEAGE_REQUIRES_DATASET_PROJECTION",),
        )
    if {"source_id", "raw_result_id"}.issubset(column_names):
        if row.source_id is not None and row.raw_result_id is not None:
            return TaiwanDatasetStorageStatus.OBSERVED, True, ()
        return (
            TaiwanDatasetStorageStatus.LINEAGE_INCOMPLETE,
            False,
            ("LATEST_ROW_MISSING_SOURCE_OR_RAW_RECEIPT",),
        )
    return (
        TaiwanDatasetStorageStatus.LINEAGE_INCOMPLETE,
        False,
        ("PRIMARY_STORAGE_HAS_NO_SOURCE_RAW_COLUMNS",),
    )


def read_taiwan_dataset_storage_evidence(
    db: Session,
    dataset_id: str,
    *,
    scope_value: str | None = None,
    catalog: TaiwanDatasetCatalog = TW_DATASET_CATALOG,
    checked_at: datetime | None = None,
) -> TaiwanDatasetStorageEvidence:
    """Read one bounded latest-row probe without provider calls or mutation."""

    contract = catalog.get(dataset_id)
    probe = TW_DATASET_STORAGE_PROBES[dataset_id]
    resolved_checked_at = checked_at or datetime.now(timezone.utc)
    bind = db.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(probe.table_name):
        return TaiwanDatasetStorageEvidence(
            dataset_id=dataset_id,
            checked_at=resolved_checked_at,
            status=TaiwanDatasetStorageStatus.SCHEMA_UNAVAILABLE,
            storage_table=probe.table_name,
            scope_value=scope_value,
            has_observation=False,
            lineage_status=contract.lineage_status,
            detail_codes=("STORAGE_TABLE_UNAVAILABLE",),
            limitations=("FRESHNESS_REQUIRES_DATASET_POLICY",),
        )

    table = Table(probe.table_name, MetaData(), autoload_with=bind)
    column_names = set(table.c.keys())
    required_probe_columns = {probe.observed_field}
    required_probe_columns.update(name for name, _ in probe.fixed_filters)
    if scope_value is not None and probe.scope_field is not None:
        required_probe_columns.add(probe.scope_field)
    missing_columns = sorted(required_probe_columns - column_names)
    if missing_columns:
        return TaiwanDatasetStorageEvidence(
            dataset_id=dataset_id,
            checked_at=resolved_checked_at,
            status=TaiwanDatasetStorageStatus.SCHEMA_UNAVAILABLE,
            storage_table=probe.table_name,
            scope_value=scope_value,
            has_observation=False,
            lineage_status=contract.lineage_status,
            detail_codes=("STORAGE_PROBE_COLUMNS_UNAVAILABLE", *missing_columns),
            limitations=("FRESHNESS_REQUIRES_DATASET_POLICY",),
        )

    selected_columns = [table.c[probe.observed_field]]
    if "source_id" in column_names:
        selected_columns.append(table.c.source_id)
    if "raw_result_id" in column_names:
        selected_columns.append(table.c.raw_result_id)
    statement = select(*selected_columns)
    for field, value in probe.fixed_filters:
        statement = statement.where(table.c[field] == value)
    detail_codes: list[str] = []
    if scope_value is not None:
        if probe.scope_field is None:
            detail_codes.append("SCOPE_FILTER_NOT_SUPPORTED")
        else:
            statement = statement.where(table.c[probe.scope_field] == scope_value)
    statement = statement.order_by(
        table.c[probe.observed_field].desc(),
        table.c.id.desc(),
    ).limit(1)
    row = db.execute(statement).first()
    if row is None:
        return TaiwanDatasetStorageEvidence(
            dataset_id=dataset_id,
            checked_at=resolved_checked_at,
            status=TaiwanDatasetStorageStatus.MISSING,
            storage_table=probe.table_name,
            scope_value=scope_value,
            has_observation=False,
            lineage_status=contract.lineage_status,
            detail_codes=tuple((*detail_codes, "NO_PERSISTED_OBSERVATION")),
            limitations=("FRESHNESS_REQUIRES_DATASET_POLICY",),
        )

    status, lineage_observed, lineage_codes = _lineage_result(
        contract,
        row,
        column_names,
    )
    return TaiwanDatasetStorageEvidence(
        dataset_id=dataset_id,
        checked_at=resolved_checked_at,
        status=status,
        storage_table=probe.table_name,
        scope_value=scope_value,
        has_observation=True,
        latest_observed_value=_serialized_value(row[0]),
        lineage_status=contract.lineage_status,
        lineage_observed=lineage_observed,
        detail_codes=tuple((*detail_codes, *lineage_codes)),
        limitations=("FRESHNESS_REQUIRES_DATASET_POLICY",),
    )


def read_taiwan_dataset_platform_projection(
    db: Session,
    dataset_id: str,
    *,
    scope_value: str | None = None,
    catalog: TaiwanDatasetCatalog = TW_DATASET_CATALOG,
    checked_at: datetime | None = None,
) -> TaiwanDatasetPlatformProjection:
    """Return catalog plus storage/lineage evidence, never freshness policy."""

    return TaiwanDatasetPlatformProjection(
        dataset=catalog.get(dataset_id),
        storage_evidence=read_taiwan_dataset_storage_evidence(
            db,
            dataset_id,
            scope_value=scope_value,
            catalog=catalog,
            checked_at=checked_at,
        ),
    )


def read_taiwan_dataset_health(
    db: Session,
    dataset_id: str,
    *,
    scope_value: str | None = None,
    catalog: TaiwanDatasetCatalog = TW_DATASET_CATALOG,
    checked_at: datetime | None = None,
) -> TaiwanDatasetPlatformProjection:
    """Compatibility alias for the explicitly named platform projection."""

    return read_taiwan_dataset_platform_projection(
        db,
        dataset_id,
        scope_value=scope_value,
        catalog=catalog,
        checked_at=checked_at,
    )


__all__ = [
    "TW_DATASET_STORAGE_PROBES",
    "TaiwanDatasetPlatformProjection",
    "TaiwanDatasetStorageEvidence",
    "TaiwanDatasetStorageProbe",
    "TaiwanDatasetStorageStatus",
    "read_taiwan_dataset_health",
    "read_taiwan_dataset_platform_projection",
    "read_taiwan_dataset_storage_evidence",
]
