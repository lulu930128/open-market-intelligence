from __future__ import annotations

from app.ai.capability_projection_registry import (
    validate_capability_projection_registry,
)
from app.market_data.registry import DATASET_REGISTRY


def test_advertised_capability_projection_registry_is_valid() -> None:
    assert validate_capability_projection_registry() == ()


def test_dataset_registry_keys_match_contract_ids() -> None:
    contracts = DATASET_REGISTRY.all()
    assert contracts
    assert len({contract.dataset_id for contract in contracts}) == len(contracts)
    assert all(DATASET_REGISTRY.get(contract.dataset_id) is contract for contract in contracts)
