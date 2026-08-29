from __future__ import annotations


def test_frontend_provider_selection_is_frozen_to_exact_debt(
    architecture_evaluation,
) -> None:
    actual = {
        item.key
        for item in architecture_evaluation.violations
        if item.key.rule == "frontend_provider_selection"
    }
    declared = {
        item.key
        for item in architecture_evaluation.debt
        if item.key.rule == "frontend_provider_selection"
    }
    assert actual == declared


def test_external_adapter_boundary_has_no_debt(architecture_evaluation) -> None:
    assert not [
        item
        for item in architecture_evaluation.violations
        if item.key.rule == "external_adapter_backend_dependency"
    ]
