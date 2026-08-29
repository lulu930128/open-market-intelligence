from __future__ import annotations

from pathlib import Path

import pytest

from conftest import REPO_ROOT


def test_new_undeclared_violation_fails(
    architecture_checker, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = architecture_checker.collect_violations
    synthetic = architecture_checker.Violation(
        architecture_checker.ViolationKey(
            "shared_market_data_reverse_dependency",
            "backend/app/market_data/contracts.py",
            "<module>:import:app.market.intentional_test",
        ),
        1,
        "intentional architecture test violation",
    )

    def with_new_violation(repo_root, rules):
        return tuple(
            sorted((*original(repo_root, rules), synthetic), key=lambda item: item.key)
        )

    monkeypatch.setattr(architecture_checker, "collect_violations", with_new_violation)
    result = architecture_checker.evaluate(REPO_ROOT)
    assert not result.passed
    assert result.undeclared == (synthetic,)


def test_removed_violation_leaves_stale_debt(
    architecture_checker, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = architecture_checker.load_debt
    synthetic = architecture_checker.DebtEntry(
        "removed-intentional-test",
        architecture_checker.ViolationKey(
            "shared_market_data_reverse_dependency",
            "backend/app/market_data/contracts.py",
            "<module>:import:app.market.removed_test",
        ),
        "intentional test",
        "architecture test",
        "remove stale debt",
    )

    def with_stale_debt(path, *, rule_ids, repo_root):
        return tuple(
            sorted(
                (*original(path, rule_ids=rule_ids, repo_root=repo_root), synthetic),
                key=lambda item: item.key,
            )
        )

    monkeypatch.setattr(architecture_checker, "load_debt", with_stale_debt)
    result = architecture_checker.evaluate(REPO_ROOT)
    assert not result.passed
    assert result.stale == (synthetic,)


def test_missing_debt_path_is_configuration_error(
    architecture_checker, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = {
        "schema_version": 1,
        "debt": [
            {
                "id": "missing-path",
                "rule": "reverse_dependency",
                "path": "backend/app/market_data/missing.py",
                "occurrence": "<module>:import:app.market",
                "reason": "test",
                "owner": "test",
                "closure_gate": "remove",
                "new_occurrences_allowed": False,
            }
        ],
    }
    monkeypatch.setattr(architecture_checker, "load_toml", lambda _path: config)
    with pytest.raises(architecture_checker.ArchitectureConfigError):
        architecture_checker.load_debt(
            Path("unused.toml"),
            rule_ids={"reverse_dependency"},
            repo_root=REPO_ROOT,
        )
