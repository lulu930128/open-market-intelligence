from __future__ import annotations

import ast
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai import capability_contract
from app.ai.capability_projection_registry import (
    CAPABILITY_PROJECTION_SPECS,
    validate_capability_projection_registry,
)
from app.market_data.contracts import DatasetHealthStatus
from app.market_data.registry import (
    DATASET_REGISTRY,
    DatasetFrequency,
    DatasetSpec,
    EligibilityPolicy,
    ExpectedStatePolicy,
    INTERNAL_DATASET_REFRESH_OPERATIONS,
    evaluate_dataset_health,
)


NOW = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)


def test_registry_contains_per_symbol_and_full_market_eod_datasets() -> None:
    specs = DATASET_REGISTRY.all()
    assert {spec.dataset_id for spec in specs} == {
        "tw.quote.snapshot",
        "tw.quote.order_book.snapshot",
        "tw.quote.auction.snapshot",
        "tw.intraday.bars",
        "tw.market_index.current",
        "tw.market_breadth.current",
        "tw.daily.ohlcv",
        "tw.technical.daily",
        "us.intraday.bars",
        "us.daily.ohlcv",
        "tw.daily.ohlcv.full_market",
        "tw.market_breadth.daily",
        "tw.market_index.daily",
        "us.daily.ohlcv.full_market",
        "us.daily.ohlcv.priority_research",
    }
    for spec in specs:
        assert spec.owner
        assert spec.read_operation
        assert spec.projection_id
        assert spec.postcondition
        assert spec.expected_state_policy
        assert spec.eligibility_policy


def test_refreshable_datasets_have_executable_operation_bounds_and_postcondition() -> None:
    executable = (
        capability_contract.canonical_executable_fill_operations()
        | INTERNAL_DATASET_REFRESH_OPERATIONS
    )
    for spec in DATASET_REGISTRY.all():
        if not spec.refreshable:
            continue
        assert spec.refresh_operation in executable
        assert spec.refresh_bounds is not None
        assert spec.refresh_bounds.max_calls >= 1
        assert spec.refresh_bounds.timeout_seconds >= 1
        assert spec.postcondition
        for operation in spec.additional_refresh_operations:
            assert operation.operation in executable
            assert operation.bounds.max_calls >= 1
            assert operation.bounds.timeout_seconds >= 1
            assert operation.postcondition


def test_public_quote_dataset_declares_bounded_shared_platform_contract() -> None:
    spec = DATASET_REGISTRY.get("tw.quote.snapshot")
    assert spec.owner == "app.market.public_quote_platform"
    assert spec.read_operation == "read_taiwan_public_last_trade_quote"
    assert spec.capability_ids == (
        "quote.snapshot",
        "quote.last_trade",
        "quote.session_close",
    )
    assert spec.refreshable is True
    assert spec.refresh_operation == "tw.acquire_public_last_trade_quote"
    assert spec.refresh_bounds is not None
    assert spec.refresh_bounds.max_calls == 1
    assert spec.refresh_bounds.timeout_seconds == 10
    assert spec.refresh_bounds.max_symbols == 1
    assert spec.refresh_bounds.max_range_days == 1


def test_priority_us_ohlc_advertises_only_its_executable_shared_platform_repair() -> None:
    spec = DATASET_REGISTRY.get("us.daily.ohlcv.priority_research")
    assert spec.refreshable is True
    assert spec.repairable is True
    assert spec.refresh_operation == "us.reconcile_priority_daily_ohlcv"
    assert spec.refresh_bounds is not None
    assert spec.refresh_bounds.max_symbols == 20


def test_non_refreshable_dataset_cannot_advertise_operation_or_repairability() -> None:
    with pytest.raises(ValidationError, match="cannot advertise refresh metadata"):
        DatasetSpec(
            dataset_id="tw.invalid",
            schema_version="v1",
            market="TW",
            scope_kind="stock",
            owner="owner",
            read_operation="read",
            projection_id="projection",
            capability_ids=("quote.snapshot",),
            frequency=DatasetFrequency.EVENT,
            expected_state_policy=ExpectedStatePolicy.CURRENT_SESSION,
            eligibility_policy=EligibilityPolicy.LISTED_INSTRUMENT,
            refreshable=False,
            refresh_operation="tw.fake",
            postcondition="Truthful status is returned.",
        )


def test_health_evaluation_separates_not_applicable_unavailable_missing_and_stale() -> None:
    spec = DATASET_REGISTRY.get("tw.daily.ohlcv")
    assert (
        spec.eligibility_policy
        is EligibilityPolicy.LISTED_INSTRUMENT_MARKET_DAY_AND_INSTRUMENT_ELIGIBLE
    )
    expected = date(2026, 8, 19)
    cases = (
        ({"eligible": False, "latest_date": None}, DatasetHealthStatus.NOT_APPLICABLE),
        ({"eligible": None, "latest_date": None}, DatasetHealthStatus.UNKNOWN),
        (
            {"eligible": True, "latest_date": None, "provider_available": False},
            DatasetHealthStatus.UNAVAILABLE,
        ),
        ({"eligible": True, "latest_date": None}, DatasetHealthStatus.MISSING),
        (
            {"eligible": True, "latest_date": date(2026, 8, 18)},
            DatasetHealthStatus.STALE,
        ),
        (
            {
                "eligible": True,
                "latest_date": expected,
                "stale": True,
            },
            DatasetHealthStatus.STALE,
        ),
        (
            {"eligible": True, "latest_date": expected},
            DatasetHealthStatus.HEALTHY,
        ),
    )
    for kwargs, expected_status in cases:
        health = evaluate_dataset_health(
            spec,
            expected_date=expected,
            checked_at=NOW,
            **kwargs,
        )
        assert health.status is expected_status


def test_advertised_foundation_scopes_have_real_projectors_and_fixture_payloads() -> None:
    assert validate_capability_projection_registry() == ()
    advertised = {spec.key for spec in CAPABILITY_PROJECTION_SPECS if spec.advertised}
    assert advertised == {
        ("quote.snapshot", "stock", "TW"),
        ("quote.session_close", "stock", "TW"),
        ("quote.snapshot", "us_stock", "US"),
        ("intraday.bars", "stock", "TW"),
        ("intraday.bars", "us_stock", "US"),
        ("daily.ohlcv", "stock", "TW"),
        ("daily.ohlcv", "us_stock", "US"),
        ("technical.indicators", "stock", "TW"),
        ("technical.structure", "stock", "TW"),
        ("technical.indicators", "us_stock", "US"),
        ("technical.structure", "us_stock", "US"),
    }
    for spec in CAPABILITY_PROJECTION_SPECS:
        projected = spec.projector(spec.fixture_context)
        if spec.advertised:
            assert spec.projector_name == "capability_contract.paths"
            assert projected not in (None, {}, [])
        else:
            assert projected["status"] == "unavailable"

    tw_structure = next(
        spec
        for spec in CAPABILITY_PROJECTION_SPECS
        if spec.key == ("technical.structure", "stock", "TW")
    )
    assert "technical_advanced" not in tw_structure.fixture_context["data"]


def test_us_general_defaults_and_explicit_capabilities_are_truthful() -> None:
    spec = capability_contract.CAPABILITIES["technical.structure"]
    assert "us_stock" in spec.scopes
    assert spec.markets == ("TW", "US")
    defaults = capability_contract._default_capabilities("us_stock", "general")
    assert "technical.indicators" in defaults
    assert "technical.structure" in defaults
    assert "ownership.insider_transactions" not in defaults
    assert all(
        capability_contract._compatible(
            capability_contract.CAPABILITIES[capability_id],
            "us_stock",
            "US",
        )
        for capability_id in defaults
    )
    insider = capability_contract.CAPABILITIES["ownership.insider_transactions"]
    assert insider.markets == ("US",)
    assert capability_contract._compatible(insider, "us_stock", "US") is True
    selection = capability_contract.normalize_selection(
        selection={"include": ["technical.structure"]},
        output="evidence_only",
        realtime_policy="cache_only",
        payload_level="compact",
        scope_type="us_stock",
        target_market="US",
        question_intent="general",
    )
    assert "technical.structure" in selection["required"]
    assert selection["unmet_required_capabilities"] == []
    insider_selection = capability_contract.normalize_selection(
        selection={"include": ["ownership.insider_transactions"]},
        output="evidence_only",
        realtime_policy="cache_only",
        payload_level="compact",
        scope_type="us_stock",
        target_market="US",
        question_intent="general",
    )
    assert insider_selection["required"] == [
        "target.identity",
        "ownership.insider_transactions",
        "data.freshness",
    ]
    assert insider_selection["unmet_required_capabilities"] == []


def test_dataset_registry_has_no_ai_scheduler_provider_or_database_imports() -> None:
    module_path = Path(__file__).parents[1] / "app" / "market_data" / "registry.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    forbidden = ("app.ai", "app.jobs", "app.market.providers", "app.db", "sqlalchemy")
    assert not any(module.startswith(forbidden) for module in imported_modules)
