from __future__ import annotations

from conftest import REPO_ROOT


def test_current_architecture_matches_exact_declared_debt(architecture_evaluation) -> None:
    assert architecture_evaluation.passed
    assert {item.key for item in architecture_evaluation.violations} == {
        item.key for item in architecture_evaluation.debt
    }


def test_required_dependency_rules_exist(architecture_checker) -> None:
    rules = architecture_checker.load_rules(
        REPO_ROOT / "architecture" / "constraints.toml"
    )
    rule_ids = {rule["id"] for rule in rules}
    assert {
        "shared_market_data_reverse_dependency",
        "shared_market_data_database_dependency",
        "shared_market_data_integration_dependency",
        "ai_market_provider_dependency",
        "external_adapter_backend_dependency",
        "tw_consumer_canonical_storage_access",
        "tw_radar_canonical_intraday_access",
    } <= rule_ids


def test_forbidden_import_names_tracks_only_selected_models(
    architecture_checker, monkeypatch
) -> None:
    import ast

    source = REPO_ROOT / "backend" / "tests" / "architecture" / "conftest.py"
    tree = ast.parse(
        "from app.db.models import MarketDailyPrice, StockMaster\n"
    )
    monkeypatch.setattr(
        architecture_checker,
        "iter_rule_files",
        lambda _root, _rule: (source,),
    )
    monkeypatch.setattr(
        architecture_checker,
        "parse_python",
        lambda _path: (tree, architecture_checker.PythonFactCollector()),
    )
    violations = architecture_checker.check_forbidden_import_names(
        REPO_ROOT,
        {
            "id": "test_storage_boundary",
            "roots": ["consumer.py"],
            "extensions": [".py"],
            "modules": ["app.db.models"],
            "forbidden_names": ["MarketDailyPrice"],
        },
    )
    assert len(violations) == 1
    assert violations[0].key.occurrence == (
        "<module>:import-name:app.db.models:MarketDailyPrice"
    )
