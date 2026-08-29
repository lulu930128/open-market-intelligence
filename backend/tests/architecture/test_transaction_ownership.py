from __future__ import annotations


def test_routers_do_not_own_transactions(architecture_evaluation) -> None:
    assert not [
        item
        for item in architecture_evaluation.violations
        if item.key.rule == "router_transaction"
    ]


def test_shared_transaction_debt_is_exact(architecture_evaluation) -> None:
    actual = {
        item.key
        for item in architecture_evaluation.violations
        if item.key.rule == "shared_market_data_transaction"
    }
    declared = {
        item.key
        for item in architecture_evaluation.debt
        if item.key.rule == "shared_market_data_transaction"
    }
    assert actual == declared
