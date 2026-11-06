"""Prevent the research feature from growing a second data/execution owner."""
import ast
from conftest import REPO_ROOT


def test_us_watchlist_research_rejects_provider_and_candidate_imports(architecture_checker, monkeypatch):
    rule = next(rule for rule in architecture_checker.load_rules(REPO_ROOT / "architecture/constraints.toml")
                if rule["id"] == "us_watchlist_research_uses_canonical_read_owners")
    source = REPO_ROOT / "backend/app/us_market/watchlist_research.py"
    tree = ast.parse("from app.us_market.providers import yahoo\nfrom app.research.candidate_service import CandidateService\n")
    collector = architecture_checker.PythonFactCollector()
    collector.visit(tree)
    monkeypatch.setattr(architecture_checker, "iter_rule_files", lambda *a: (source,))
    monkeypatch.setattr(architecture_checker, "parse_python", lambda *a: (tree, collector))
    violations = architecture_checker.check_forbidden_imports(REPO_ROOT, rule)
    assert len(violations) == 2


def test_us_watchlist_research_rejects_refresh_calls(architecture_checker, monkeypatch):
    rule = next(rule for rule in architecture_checker.load_rules(REPO_ROOT / "architecture/constraints.toml")
                if rule["id"] == "us_watchlist_research_no_acquisition")
    source = REPO_ROOT / "backend/app/us_market/watchlist_research.py"
    tree = ast.parse("def read():\n    return platform.refresh(symbol='NVDA')\n")
    collector = architecture_checker.PythonFactCollector()
    collector.visit(tree)
    monkeypatch.setattr(architecture_checker, "iter_rule_files", lambda *a: (source,))
    monkeypatch.setattr(architecture_checker, "parse_python", lambda *a: (tree, collector))
    assert architecture_checker.check_forbidden_calls(REPO_ROOT, rule)
