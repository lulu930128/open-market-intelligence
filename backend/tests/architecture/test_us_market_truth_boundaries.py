from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _source(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_us_market_truth_composer_is_read_only_and_provider_neutral() -> None:
    source = _source("backend/app/us_market/market_truth.py")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert not any(name.startswith("app.us_market.providers") for name in imported)
    assert not any(name.startswith("app.jobs") for name in imported)
    assert "SessionLocal" not in source
    assert "datetime.now" not in source
    assert calls.isdisjoint(
        {
            "commit",
            "rollback",
            "refresh",
            "enqueue",
            "ensure_history_coverage",
        }
    )


def test_us_session_policy_is_market_owned_and_does_not_claim_authority() -> None:
    source = _source("backend/app/us_market/session_policy.py")

    assert "app.us_market.providers" not in source
    assert "does not prove an exchange auction" in source


def test_legacy_us_intraday_no_longer_maps_close_boundary_to_regular() -> None:
    source = _source("backend/app/us_market/service.py")

    assert 'in {"continuous", "closing_auction"}' not in source
    assert "and bar.end_at.astimezone(US_MARKET_TIMEZONE) == session_close_at" in source


def test_market_truth_contracts_remain_typed_only() -> None:
    source = _source("backend/app/us_market/market_truth_contracts.py")

    for forbidden in (
        "sqlalchemy",
        "app.db",
        "app.us_market.providers",
        "requests",
        "httpx",
    ):
        assert forbidden not in source


def test_truth_shadow_is_diagnostic_only_and_not_wired_to_consumers() -> None:
    shadow = _source("backend/app/us_market/market_truth_shadow.py")
    router = _source("backend/app/routers/us_market.py")

    for forbidden in (
        "app.routers",
        "app.ai",
        "app.mcp",
        "app.us_market.providers",
        "sqlalchemy",
    ):
        assert forbidden not in shadow
    assert "market_truth_shadow" not in router
    assert "DIAGNOSTIC_ONLY_NO_CONSUMER_CUTOVER" in shadow
