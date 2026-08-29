from __future__ import annotations


def test_ai_and_external_adapters_have_no_provider_dependency_debt(
    architecture_evaluation,
) -> None:
    protected_rules = {
        "ai_market_provider_dependency",
        "external_adapter_backend_dependency",
    }
    assert not [
        item
        for item in architecture_evaluation.violations
        if item.key.rule in protected_rules
    ]


def test_shared_reverse_dependencies_are_all_explicit_debt(
    architecture_evaluation,
) -> None:
    actual = {
        item.key
        for item in architecture_evaluation.violations
        if item.key.rule == "shared_market_data_reverse_dependency"
    }
    declared = {
        item.key
        for item in architecture_evaluation.debt
        if item.key.rule == "shared_market_data_reverse_dependency"
    }
    assert actual == declared
