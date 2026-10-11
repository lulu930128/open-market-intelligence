from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[3]


def test_intraday_discovery_guard_rules_are_active(architecture_checker, architecture_evaluation):
    assert architecture_evaluation.passed
    rules = architecture_checker.load_rules(ROOT / "architecture/constraints.toml")
    assert {"tw_intraday_radar_read_boundary", "tw_intraday_radar_read_transaction",
            "tw_intraday_candidate_engine_pure"} <= {rule["id"] for rule in rules}


def test_screening_and_discovery_share_lightweight_reader_without_tier_a_or_bars():
    for filename in ("tw_intraday_state.py", "tw_intraday_discovery.py"):
        source = (ROOT / "backend/app/market" / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "read_taiwan_intraday_stock_states" for node in ast.walk(tree))
    source = (ROOT / "backend/app/market/tw_intraday_discovery.py").read_text(encoding="utf-8")
    assert "MarketIntradayBar" not in source
    assert "resolve_taiwan_intraday_target_universe" not in source
    assert "list_taiwan_stock_universe" in source


def test_receipt_evidence_is_internal_and_outward_contract_only_references_it(architecture_checker, architecture_evaluation):
    assert architecture_evaluation.passed
    rules = architecture_checker.load_rules(ROOT / "architecture/constraints.toml")
    rule = next(rule for rule in rules if rule["id"] == "tw_breadth_receipt_evidence_internal")
    assert rule["kind"] == "python_forbidden_import"
    assert "backend/app/market_data" in rule["roots"]
    assert "app.market.tw_breadth_acquisition_contract" in rule["forbidden_prefixes"]
    from app.market_data.contracts import BreadthAcquisitionDiagnostics
    fields = BreadthAcquisitionDiagnostics.model_fields
    assert {"receipt_evidence_id", "receipt_evidence_version", "missing_z_rescue"} <= fields.keys()
    assert "batches" not in fields and "missing_examples" not in fields
