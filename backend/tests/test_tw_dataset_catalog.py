from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

from app.db.models import Base
from app.market.tw_dataset_catalog import (
    TW_DATASET_CATALOG,
    TaiwanDatasetContract,
    TaiwanDatasetConvergenceStatus,
    TaiwanDatasetFrequency,
    TaiwanDatasetLineageStatus,
    TaiwanExpectedStatePolicy,
)
from app.market.tw_intraday_capabilities import (
    TW_INTRADAY_BARS_CAPABILITY_ID,
    TW_INTRADAY_DESCRIPTORS,
)
from app.market_data.contracts import Market
from app.market_data.registry import DATASET_REGISTRY, RefreshBounds


EXPECTED_TW_DATASETS = {
    "tw.quote.snapshot",
    "tw.quote.order_book.snapshot",
    "tw.quote.auction.snapshot",
    "tw.intraday.bars",
    "tw.market_index.current",
    "tw.market_breadth.current",
    "tw.daily.ohlcv",
    "tw.technical.daily",
    "tw.daily.ohlcv.full_market",
    "tw.market_breadth.daily",
    "tw.market_index.daily",
    "tw.chips.market.daily",
    "tw.chips.institutional.daily",
    "tw.chips.margin.daily",
    "tw.chips.broker_branch.daily",
    "tw.ownership.shareholding.weekly",
    "tw.fundamentals.revenue.monthly",
    "tw.fundamentals.financials.quarterly",
    "tw.company.profile",
    "tw.events.corporate",
    "tw.etf.profile",
    "tw.etf.nav.daily",
    "tw.etf.pcf.snapshot",
    "tw.etf.inav.snapshot",
    "tw.futures.quote.snapshot",
    "tw.futures.intraday.bars",
    "tw.futures.daily.bars",
    "tw.derivatives.option_chain.daily",
    "tw.derivatives.large_trader.daily",
    "tw.derivatives.term_structure.daily",
    "tw.market.minute_state",
    "tw.stock.intraday.state",
}


def _resolve_callable(path: str):
    module_name, separator, attribute = path.rpartition(".")
    assert separator
    return getattr(importlib.import_module(module_name), attribute)


def test_catalog_covers_every_audited_taiwan_dataset_family() -> None:
    datasets = TW_DATASET_CATALOG.all()
    assert {item.dataset_id for item in datasets} == EXPECTED_TW_DATASETS
    assert {item.family for item in datasets} == {
        "chips",
        "derivatives",
        "etf",
        "events",
        "fundamentals",
        "market_state",
        "price",
        "quote",
        "technical",
    }
    assert all(item.market is Market.TW for item in datasets)
    assert all(item.payload_contract for item in datasets)
    assert all(item.postcondition for item in datasets)


def test_catalog_storage_references_exist_in_shared_metadata() -> None:
    table_names = set(Base.metadata.tables)
    for dataset in TW_DATASET_CATALOG.all():
        assert set(dataset.storage_tables) <= table_names, dataset.dataset_id


def test_advertised_read_projection_and_health_paths_are_real_callables() -> None:
    for dataset in TW_DATASET_CATALOG.all():
        if not dataset.advertised:
            continue
        assert callable(_resolve_callable(dataset.read_operation)), dataset.dataset_id
        assert callable(
            _resolve_callable(dataset.projection_operation)
        ), dataset.dataset_id
        assert callable(_resolve_callable(dataset.health_operation)), dataset.dataset_id


def test_refreshable_datasets_reference_bounded_market_owned_operations() -> None:
    used_operations: set[str] = set()
    for dataset in TW_DATASET_CATALOG.all():
        if not dataset.refreshable:
            assert dataset.refresh_operation is None
            assert dataset.refresh_bounds is None
            continue
        assert dataset.refresh_operation is not None
        operation = TW_DATASET_CATALOG.operation(dataset.refresh_operation)
        used_operations.add(operation.operation_id)
        assert operation.bounds == dataset.refresh_bounds
        assert callable(_resolve_callable(operation.callable_path))
        assert ".routers." not in operation.callable_path
        assert ".ai." not in operation.callable_path
        assert "kgi" not in operation.callable_path.casefold()
        assert operation.bounds.max_calls >= 1
        assert operation.bounds.timeout_seconds >= 1
        assert operation.bounds.max_symbols >= 1
        assert operation.bounds.max_range_days >= 1
    assert used_operations == {
        operation.operation_id for operation in TW_DATASET_CATALOG.operations()
    }


def test_lineage_gaps_are_never_advertised_as_repairable() -> None:
    gaps = [
        dataset
        for dataset in TW_DATASET_CATALOG.all()
        if dataset.lineage_status is TaiwanDatasetLineageStatus.LINEAGE_GAP
    ]
    assert gaps
    assert all(not dataset.repairable for dataset in gaps)
    assert all(not dataset.advertised for dataset in gaps)
    assert all(
        dataset.convergence_status is TaiwanDatasetConvergenceStatus.LINEAGE_GAP
        for dataset in gaps
    )


def test_etf_and_derivatives_lineage_debt_is_truthfully_not_advertised() -> None:
    debt_families = {
        dataset.dataset_id: dataset
        for dataset in TW_DATASET_CATALOG.all()
        if dataset.family in {"etf", "derivatives"}
    }

    assert debt_families
    assert all(not dataset.advertised for dataset in debt_families.values())
    assert all(
        dataset.lineage_status is TaiwanDatasetLineageStatus.LINEAGE_GAP
        for dataset in debt_families.values()
    )
    assert all(dataset.limitations for dataset in debt_families.values())


def test_platform_owned_datasets_have_canonical_lineage_and_repair_paths() -> None:
    platform_owned = {
        dataset.dataset_id: dataset
        for dataset in TW_DATASET_CATALOG.all()
        if dataset.convergence_status
        is TaiwanDatasetConvergenceStatus.PLATFORM_OWNED
    }
    assert set(platform_owned) == {
        "tw.quote.snapshot",
        "tw.quote.order_book.snapshot",
        "tw.quote.auction.snapshot",
        "tw.intraday.bars",
        "tw.market_index.current",
        "tw.market_breadth.current",
        "tw.daily.ohlcv",
        "tw.daily.ohlcv.full_market",
        "tw.market_breadth.daily",
        "tw.market_index.daily",
        "tw.technical.daily",
    }
    for dataset in platform_owned.values():
        assert dataset.required_lineage_fields
        assert dataset.lineage_status in {
            TaiwanDatasetLineageStatus.CANONICAL_RAW_RECEIPT,
            TaiwanDatasetLineageStatus.DERIVED_COMPONENT_LINEAGE,
        }
    assert platform_owned["tw.quote.snapshot"].repairable is False
    assert platform_owned["tw.technical.daily"].refreshable is False
    assert platform_owned["tw.technical.daily"].repairable is False
    assert all(
        dataset.repairable
        for dataset_id, dataset in platform_owned.items()
        if dataset_id
        not in {
            "tw.quote.snapshot",
            "tw.quote.order_book.snapshot",
            "tw.quote.auction.snapshot",
            "tw.market_index.current",
            "tw.market_breadth.current",
            "tw.technical.daily",
        }
    )


def test_existing_shared_tw_registry_entries_do_not_drift_from_market_catalog() -> None:
    shared_tw = {
        spec.dataset_id: spec
        for spec in DATASET_REGISTRY.all()
        if spec.market is Market.TW
    }
    assert set(shared_tw) == {
        "tw.quote.snapshot",
        "tw.quote.order_book.snapshot",
        "tw.quote.auction.snapshot",
        "tw.intraday.bars",
        "tw.market_index.current",
        "tw.market_breadth.current",
        "tw.daily.ohlcv",
        "tw.daily.ohlcv.full_market",
        "tw.market_breadth.daily",
        "tw.market_index.daily",
        "tw.technical.daily",
    }
    for dataset_id, shared in shared_tw.items():
        market_owned = TW_DATASET_CATALOG.get(dataset_id)
        assert shared.capability_ids == market_owned.capability_ids
        assert shared.refreshable == market_owned.refreshable
        assert shared.repairable == market_owned.repairable
        assert shared.refresh_operation == market_owned.refresh_operation
        assert shared.refresh_bounds == market_owned.refresh_bounds


def test_tw_intraday_capability_id_is_canonical_across_contract_owners() -> None:
    shared = DATASET_REGISTRY.get("tw.intraday.bars")
    market_owned = TW_DATASET_CATALOG.get("tw.intraday.bars")

    assert TW_INTRADAY_BARS_CAPABILITY_ID == "intraday.bars"
    assert shared.capability_ids == (TW_INTRADAY_BARS_CAPABILITY_ID,)
    assert market_owned.capability_ids == (TW_INTRADAY_BARS_CAPABILITY_ID,)
    assert {
        descriptor.capability_id for descriptor in TW_INTRADAY_DESCRIPTORS
    } == {TW_INTRADAY_BARS_CAPABILITY_ID}


def test_current_breadth_scope_does_not_claim_official_full_market() -> None:
    breadth = TW_DATASET_CATALOG.get("tw.market_breadth.current")

    assert (
        breadth.scope_kind
        == "TWSE_or_TPEX_full_market_registered_stock_universe"
    )


def test_contract_rejects_lineage_gap_repairability() -> None:
    with pytest.raises(ValidationError, match="lineage-gap dataset"):
        TaiwanDatasetContract(
            dataset_id="tw.invalid",
            family="invalid",
            payload_contract="invalid.v1",
            scope_kind="stock",
            capability_ids=("invalid",),
            storage_tables=("market_intraday_bar",),
            read_operation="app.market.intraday.get_market_intraday_history",
            projection_operation="app.routers.market.get_stock_intraday_history",
            health_operation="app.market.tw_dataset_health.read_taiwan_dataset_health",
            frequency=TaiwanDatasetFrequency.INTRADAY,
            expected_state_policy=TaiwanExpectedStatePolicy.CURRENT_SESSION,
            eligibility_policy="listed",
            refreshable=True,
            repairable=True,
            refresh_operation="tw.invalid",
            refresh_bounds=RefreshBounds(
                max_calls=1,
                timeout_seconds=10,
                max_symbols=1,
                max_range_days=1,
            ),
            postcondition="invalid",
            lineage_status=TaiwanDatasetLineageStatus.LINEAGE_GAP,
            convergence_status=TaiwanDatasetConvergenceStatus.LINEAGE_GAP,
        )
