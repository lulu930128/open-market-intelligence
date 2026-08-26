from __future__ import annotations

import importlib

from app.main import app
from app.market.tw_dataset_catalog import TW_DATASET_CATALOG
from app.market.tw_sidecar_classification import (
    TAIWAN_SIDECAR_CONTRACTS,
    TaiwanSidecarClassification,
)


def _callable(path: str):
    module_name, separator, attribute = path.rpartition(".")
    assert separator
    return getattr(importlib.import_module(module_name), attribute)


def test_sidecar_contracts_have_exact_unique_route_coverage() -> None:
    paths = [path for contract in TAIWAN_SIDECAR_CONTRACTS for path in contract.route_paths]
    assert len(paths) == len(set(paths))

    outward_paths = {route.path for route in app.routes}
    assert set(paths) <= outward_paths


def test_cataloged_sidecars_reference_existing_datasets_and_operations() -> None:
    catalog_ids = {dataset.dataset_id for dataset in TW_DATASET_CATALOG.all()}
    for contract in TAIWAN_SIDECAR_CONTRACTS:
        assert contract.read_external_io is False
        assert contract.read_writes_storage is False
        assert contract.health_owner
        assert contract.storage_owner
        assert contract.lineage_status
        for operation in (*contract.read_operations, *contract.refresh_operations):
            assert callable(_callable(operation)), operation

        if contract.classification is TaiwanSidecarClassification.DATASET_CATALOG:
            assert contract.dataset_ids
            assert set(contract.dataset_ids) <= catalog_ids
        else:
            assert contract.dataset_ids == ()
            assert contract.ai_decision_usable is False
            assert "NOT_SHARED_DATASET_LIFECYCLE" in contract.limitations


def test_noncanonical_sidecars_fail_closed_for_research_decisions() -> None:
    noncanonical = [
        contract
        for contract in TAIWAN_SIDECAR_CONTRACTS
        if contract.classification is TaiwanSidecarClassification.COMPATIBILITY_CACHE
    ]
    assert {contract.surface_id for contract in noncanonical} == {
        "tw.disposition",
        "tw.institutional_holding_ratio",
    }
    assert all(not contract.ai_decision_usable for contract in noncanonical)
    assert all("NO_RAW_FETCH_RESULT_LINEAGE" in contract.limitations for contract in noncanonical)
