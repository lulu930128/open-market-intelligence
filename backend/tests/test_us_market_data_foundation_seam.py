from __future__ import annotations

import ast
from pathlib import Path

from app.market_data.contracts import Market
from app.us_market.market_data import US_MARKET_DATA_INTEGRATION_MANIFEST
from app.us_market.market_data.descriptors import (
    US_DAILY_CANDIDATE_DESCRIPTORS,
    US_DAILY_PROVIDER_DESCRIPTORS,
)
from app.us_market.market_data.adapters import (
    adapt_alpaca_stock_bars_payload,
    adapt_alphavantage_daily_payload,
    adapt_yahoo_chart_payload,
)
from app.us_market.providers.canonical import (
    canonical_alpaca_stock_bars_payload,
    canonical_alphavantage_daily_payload,
    canonical_yahoo_chart_payload,
)


def test_legacy_candidate_store_is_removed_after_canonical_repository_cutover() -> None:
    backend = Path(__file__).parents[1]
    removed = backend / "app" / "us_market" / "market_data" / "candidate_store.py"
    assert not removed.exists()
    imports: list[str] = []
    for module_path in (backend / "app").rglob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
    assert "app.us_market.market_data.candidate_store" not in imports


def test_integration_manifest_exposes_capability_keyed_us_production_bindings() -> None:
    manifest = US_MARKET_DATA_INTEGRATION_MANIFEST

    assert manifest.market is Market.US
    assert {
        (item.provider_key, item.capability_id)
        for item in manifest.provider_descriptors
    } == {
        ("yahoo_chart", "daily.ohlcv"),
        ("alpaca", "daily.ohlcv"),
        ("yahoo_chart", "quote.snapshot"),
        ("twelve_data", "quote.snapshot"),
        ("yahoo_chart", "intraday.bars"),
        ("twelve_data", "intraday.bars"),
    }
    assert [item.provider_key for item in manifest.canonical_adapters] == [
        "yahoo_chart",
        "alpaca",
        "twelve_data",
        "twelve_data",
    ]
    assert manifest.production_binding_available is True
    assert manifest.shared_core_contract_version == "omi.market.data_requirement.v2"
    assert manifest.handoff_gate == "US_MARKET_CORE_SOURCE_CHECKPOINT_READY"
    assert not hasattr(manifest, "candidate_reader")
    assert "US_INTRADAY_MATERIALIZER_FEATURE_OFF_BOUNDED_CANARY_ONLY" in manifest.limitations
    assert (
        "US_MATERIALIZER_KEYED_CONCURRENCY_RUNTIME_ACCEPTANCE_PENDING"
        in manifest.limitations
    )
    assert {
        (item.capability_id, item.dataset_id, item.refresh_operation)
        for item in manifest.capability_bindings
    } == {
        ("daily.ohlcv", "us.daily.ohlcv", "us.refresh_daily_ohlcv"),
        ("quote.snapshot", "us.quote.snapshot", "us.refresh_quote"),
        ("intraday.bars", "us.intraday.bars", "us.refresh_intraday_bars"),
    }
    assert "ALPACA_DAILY_SUPPORTS_STOCK_AND_ETF_ONLY" in manifest.limitations
    assert "US_INDEX_DAILY_FALLBACK_REMAINS_YAHOO_ONLY" in manifest.limitations
    assert "alphavantage" not in {
        item.provider_key for item in manifest.provider_descriptors
    }
    assert "alphavantage" not in {
        item.provider_key for item in manifest.canonical_adapters
    }
    assert not hasattr(manifest, "resolver")
    assert not hasattr(manifest, "fallback_executor")


def test_alphavantage_daily_cannot_reenter_production_inventory() -> None:
    assert [item.provider_key for item in US_DAILY_PROVIDER_DESCRIPTORS] == [
        "yahoo_chart",
        "alpaca",
    ]
    assert [item.provider_key for item in US_DAILY_CANDIDATE_DESCRIPTORS] == [
        "yahoo_chart",
        "alpaca",
    ]
    assert "alphavantage" not in {
        item.provider_key
        for item in US_MARKET_DATA_INTEGRATION_MANIFEST.provider_descriptors
    }


def test_new_adapter_entrypoints_are_the_existing_pure_canonical_converters() -> None:
    assert adapt_yahoo_chart_payload is canonical_yahoo_chart_payload
    assert (
        adapt_alphavantage_daily_payload
        is canonical_alphavantage_daily_payload
    )
    assert adapt_alpaca_stock_bars_payload is canonical_alpaca_stock_bars_payload


def test_new_us_market_data_package_has_no_runtime_or_consumer_dependency() -> None:
    package = (
        Path(__file__).parents[1]
        / "app"
        / "us_market"
        / "market_data"
    )
    forbidden_prefixes = (
        "app.ai",
        "app.jobs",
        "app.routers",
        "app.us_market.service",
    )
    violations: list[str] = []
    for module_path in package.rglob("*.py"):
        if module_path.name == "legacy_compat.py":
            continue
        tree = ast.parse(module_path.read_text(encoding="utf-8-sig"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        if any(
            imported.startswith(forbidden_prefixes)
            for imported in imports
        ):
            violations.append(module_path.relative_to(package).as_posix())
    assert violations == []


def test_new_canonical_adapters_import_no_io_or_persistence_layer() -> None:
    adapters = (
        Path(__file__).parents[1]
        / "app"
        / "us_market"
        / "market_data"
        / "adapters"
    )
    forbidden_prefixes = (
        "app.db",
        "app.us_market.service",
        "app.us_market.sources",
        "httpx",
        "requests",
        "sqlalchemy",
    )
    imports: list[str] = []
    for module_path in adapters.rglob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
    assert not any(imported.startswith(forbidden_prefixes) for imported in imports)


def test_alpaca_and_twelve_provider_modules_own_no_database_or_transaction() -> None:
    providers = Path(__file__).parents[1] / "app" / "us_market" / "providers"
    module_paths = (
        providers / "alpaca.py",
        providers / "twelve_data.py",
        providers / "errors.py",
    )
    forbidden_prefixes = ("app.db", "sqlalchemy")
    forbidden_calls = {"commit", "rollback", "flush"}
    violations = []
    for module_path in module_paths:
        tree = ast.parse(module_path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    alias.name.startswith(forbidden_prefixes)
                    for alias in node.names
                ):
                    violations.append(module_path.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(forbidden_prefixes):
                    violations.append(module_path.name)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden_calls
            ):
                violations.append(module_path.name)
    assert violations == []


def test_twelve_descriptors_are_source_ready_and_capability_advertised() -> None:
    from app.us_market.market_data.descriptors import (
        US_SOURCE_READY_PROVIDER_DESCRIPTORS,
    )

    assert [
        (item.provider_key, item.capability_id, item.resource_id)
        for item in US_SOURCE_READY_PROVIDER_DESCRIPTORS
    ] == [
        ("twelve_data", "quote.snapshot", "twelve_data.quote"),
        ("twelve_data", "intraday.bars", "twelve_data.intraday"),
    ]
    assert {
        item.capability_id
        for item in US_MARKET_DATA_INTEGRATION_MANIFEST.provider_descriptors
        if item.provider_key == "twelve_data"
    } == {"quote.snapshot", "intraday.bars"}
