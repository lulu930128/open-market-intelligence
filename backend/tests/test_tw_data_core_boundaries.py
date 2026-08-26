from __future__ import annotations

import ast
import json
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
BACKEND_APP = REPO_ROOT / "backend" / "app"
TASK_ROOT = REPO_ROOT / "docs" / "agent-runs" / "tw-market-data-platform-convergence-20260825"
DEBT_PATH = TASK_ROOT / "artifacts" / "cp0-boundary-debt.json"


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _enclosing_function(parents: dict[ast.AST, ast.AST], node: ast.AST) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def _provider_imports(path: Path) -> set[tuple[str, str]]:
    results: set[tuple[str, str]] = set()
    for node in ast.walk(_tree(path)):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        for module in modules:
            if (
                module.startswith("app.market.providers")
                or module.startswith("app.us_market.providers")
                or module == "app.market.kgi_market_data"
            ):
                results.add((_relative(path), module))
    return results


def _transaction_calls(path: Path) -> set[tuple[str, str, str]]:
    tree = _tree(path)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    results: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"commit", "rollback"}:
            continue
        results.add(
            (
                _relative(path),
                _enclosing_function(parents, node),
                node.func.attr,
            )
        )
    return results


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_no_new_router_or_ai_provider_imports_beyond_recorded_debt() -> None:
    debt = json.loads(DEBT_PATH.read_text(encoding="utf-8"))
    allowed = {
        (item["file"], item["module"])
        for item in debt["consumer_provider_imports"]
    }
    actual: set[tuple[str, str]] = set()
    for root in (BACKEND_APP / "routers", BACKEND_APP / "ai"):
        for path in root.rglob("*.py"):
            actual.update(_provider_imports(path))

    assert actual <= allowed, f"new consumer/provider imports: {sorted(actual - allowed)}"


def test_no_new_shared_market_data_transaction_owners_beyond_recorded_debt() -> None:
    debt = json.loads(DEBT_PATH.read_text(encoding="utf-8"))
    allowed = {
        (item["file"], item["function"], item["method"])
        for item in debt["market_data_transaction_calls"]
    }
    actual: set[tuple[str, str, str]] = set()
    for path in (BACKEND_APP / "market_data").rglob("*.py"):
        actual.update(_transaction_calls(path))

    assert actual <= allowed, f"new shared transaction owners: {sorted(actual - allowed)}"


def test_candidate_repository_contract_stays_pure() -> None:
    path = BACKEND_APP / "market_data" / "candidate_repository.py"
    forbidden_prefixes = (
        "app.db",
        "app.market",
        "app.routers",
        "app.ai",
        "requests",
        "httpx",
        "sqlalchemy",
    )
    imports = _imports(path)
    forbidden = sorted(
        module
        for module in imports
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden_prefixes)
    )

    assert forbidden == []
    assert _transaction_calls(path) == set()


def test_shared_gateway_contracts_and_catalog_stay_provider_and_storage_neutral() -> None:
    forbidden_prefixes = (
        "app.db",
        "app.market",
        "app.us_market",
        "app.routers",
        "app.ai",
        "requests",
        "httpx",
        "sqlalchemy",
    )
    for name in ("integration_contracts.py", "gateway.py", "provider_catalog.py"):
        path = BACKEND_APP / "market_data" / name
        imports = _imports(path)
        forbidden = sorted(
            module
            for module in imports
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            )
        )
        assert forbidden == [], f"{name} imports forbidden owners: {forbidden}"
        assert _transaction_calls(path) == set()


def test_tw_daily_repository_has_no_provider_io_or_transaction_ownership() -> None:
    path = BACKEND_APP / "market" / "daily_price_repository.py"
    forbidden_prefixes = (
        "app.market.providers",
        "requests",
        "httpx",
        "urllib",
        "subprocess",
    )
    imports = _imports(path)
    forbidden = sorted(
        module
        for module in imports
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden_prefixes)
    )

    assert forbidden == []
    assert _transaction_calls(path) == set()


def test_official_breadth_read_path_has_no_provider_io_or_transaction_ownership() -> None:
    forbidden_prefixes = (
        "app.market.providers",
        "requests",
        "httpx",
        "urllib",
        "subprocess",
    )
    for name in (
        "official_breadth_repository.py",
        "official_breadth_platform.py",
    ):
        path = BACKEND_APP / "market" / name
        imports = _imports(path)
        forbidden = sorted(
            module
            for module in imports
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            )
        )

        assert forbidden == [], f"{name} imports provider I/O: {forbidden}"
        assert _transaction_calls(path) == set()


def test_official_daily_adapter_and_executor_do_not_own_storage_transactions() -> None:
    forbidden_prefixes = (
        "app.db",
        "sqlalchemy",
        "app.routers",
        "app.ai",
    )
    for relative in (
        Path("market") / "providers" / "tw_official_daily.py",
        Path("market") / "daily_ohlcv_acquisition.py",
    ):
        path = BACKEND_APP / relative
        imports = _imports(path)
        forbidden = sorted(
            module
            for module in imports
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            )
        )
        assert forbidden == [], f"{relative.as_posix()} imports storage owner: {forbidden}"
        assert _transaction_calls(path) == set()


def test_official_index_adapter_and_executor_do_not_own_storage_transactions() -> None:
    forbidden_prefixes = (
        "app.db",
        "sqlalchemy",
        "app.routers",
        "app.ai",
    )
    for relative in (
        Path("market") / "providers" / "tw_official_index.py",
        Path("market") / "official_index_acquisition.py",
    ):
        path = BACKEND_APP / relative
        imports = _imports(path)
        forbidden = sorted(
            module
            for module in imports
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            )
        )
        assert forbidden == [], f"{relative.as_posix()} imports storage owner: {forbidden}"
        assert _transaction_calls(path) == set()


def test_official_index_repository_has_no_provider_io_or_transaction_ownership() -> None:
    path = BACKEND_APP / "market" / "official_index_repository.py"
    forbidden_prefixes = (
        "app.market.providers",
        "requests",
        "httpx",
        "urllib",
        "subprocess",
    )
    imports = _imports(path)
    forbidden = sorted(
        module
        for module in imports
        if any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in forbidden_prefixes
        )
    )
    assert forbidden == []
    assert _transaction_calls(path) == set()


def test_public_quote_repository_has_no_provider_io_or_transaction_ownership() -> None:
    path = BACKEND_APP / "market" / "public_quote_repository.py"
    forbidden_prefixes = (
        "app.market.providers",
        "requests",
        "httpx",
        "urllib",
        "subprocess",
    )
    imports = _imports(path)
    forbidden = sorted(
        module
        for module in imports
        if any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in forbidden_prefixes
        )
    )
    assert forbidden == []
    assert _transaction_calls(path) == set()


def test_public_quote_adapter_and_executor_do_not_own_storage_transactions() -> None:
    forbidden_prefixes = (
        "app.db",
        "sqlalchemy",
        "app.routers",
        "app.ai",
    )
    for relative in (
        Path("market") / "providers" / "tw_public_quote.py",
        Path("market") / "public_quote_acquisition.py",
    ):
        path = BACKEND_APP / relative
        imports = _imports(path)
        forbidden = sorted(
            module
            for module in imports
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            )
        )
        assert forbidden == [], f"{relative.as_posix()} imports storage owner: {forbidden}"
        assert _transaction_calls(path) == set()


def test_public_quote_transaction_has_no_provider_io_or_resolution() -> None:
    path = BACKEND_APP / "market" / "public_quote_transaction.py"
    forbidden_prefixes = (
        "app.market.providers",
        "app.market_data.resolution",
        "requests",
        "httpx",
        "urllib",
        "subprocess",
    )
    imports = _imports(path)
    forbidden = sorted(
        module
        for module in imports
        if any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in forbidden_prefixes
        )
    )
    source = path.read_text(encoding="utf-8")

    assert forbidden == []
    assert "resolve_" not in source
    assert _transaction_calls(path) == {
        (_relative(path), "persist_quote_acquisition", "commit"),
        (_relative(path), "persist_quote_acquisition", "rollback"),
    }


def test_official_daily_transaction_has_no_provider_io_or_resolution() -> None:
    path = BACKEND_APP / "market" / "daily_price_transaction.py"
    forbidden_prefixes = (
        "app.market.providers",
        "app.market_data.resolution",
        "requests",
        "httpx",
        "urllib",
        "subprocess",
    )
    imports = _imports(path)
    forbidden = sorted(
        module
        for module in imports
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden_prefixes)
    )
    source = path.read_text(encoding="utf-8")

    assert forbidden == []
    assert "resolve_" not in source
    assert _transaction_calls(path) == {
        (_relative(path), "persist_bar_acquisition", "commit"),
        (_relative(path), "persist_bar_acquisition", "rollback"),
    }


def test_official_index_transaction_has_no_provider_io_or_resolution() -> None:
    path = BACKEND_APP / "market" / "official_index_transaction.py"
    forbidden_prefixes = (
        "app.market.providers",
        "app.market_data.resolution",
        "requests",
        "httpx",
        "urllib",
        "subprocess",
    )
    imports = _imports(path)
    forbidden = sorted(
        module
        for module in imports
        if any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in forbidden_prefixes
        )
    )
    source = path.read_text(encoding="utf-8")

    assert forbidden == []
    assert "resolve_" not in source
    assert _transaction_calls(path) == {
        (_relative(path), "persist_index_acquisition", "commit"),
        (_relative(path), "persist_index_acquisition", "rollback"),
    }


def test_ai_taiwan_quote_context_depends_on_data_core_projection() -> None:
    tools_path = BACKEND_APP / "ai" / "tools.py"
    context_path = BACKEND_APP / "ai" / "market_context" / "taiwan_stock.py"
    tools_source = tools_path.read_text(encoding="utf-8")
    context_source = context_path.read_text(encoding="utf-8")

    assert "app.market.public_quote_platform" in tools_source
    assert "app.market.quote_depth" not in tools_source
    assert "read_taiwan_public_quote" in context_source
    assert "get_taiwan_stock_quote_depth" not in context_source
    assert 'canonical_requested_provider = "auto"' in context_source
    assert '"provider_control_status": (' in context_source
    assert 'quote_depth.get("provider_attempts")' in context_source


def test_ai_intraday_compatibility_reader_cannot_trigger_provider_refresh() -> None:
    context_path = BACKEND_APP / "ai" / "market_context" / "taiwan_stock.py"
    tree = _tree(context_path)
    compact_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_compact_intraday_bars"
    )
    compact_source = ast.get_source_segment(
        context_path.read_text(encoding="utf-8"),
        compact_function,
    )

    assert compact_source is not None
    assert "refresh_allowed = False" in compact_source
    assert "refresh=False" in compact_source
    assert "realtime_policy" not in compact_source


def test_migrated_quote_cannot_fall_back_to_legacy_mis_bar_masquerading() -> None:
    path = BACKEND_APP / "market" / "intraday.py"
    source = path.read_text(encoding="utf-8")

    for forbidden in (
        "TWSE_MIS_STOCK_INFO_URL",
        "_fetch_mis_message",
        "_fetch_mis_snapshot",
        "_apply_mis_volume_adjustment",
        "resolve_twse_mis_actual_trade",
        "twse_mis_snapshot_z",
    ):
        assert forbidden not in source
    assert "read_taiwan_public_last_trade_quote" in source


def test_taiwan_ohlc_get_cannot_start_legacy_history_backfill() -> None:
    path = BACKEND_APP / "market" / "service.py"
    source = path.read_text(encoding="utf-8")

    assert "app.market.backfill" not in source
    assert "_ensure_stock_history" not in source
    assert "backfill_twse_stock_day" not in source
    assert "backfill_tpex_trading_stock" not in source
    assert "Deprecated ensure_history was ignored" in source


def test_taiwan_indicator_api_uses_versioned_backend_gateway() -> None:
    router_path = BACKEND_APP / "routers" / "indicators.py"
    router_source = router_path.read_text(encoding="utf-8")

    assert "app.market.technical_indicator_gateway" in router_source
    assert "calculate_active_daily_indicators" in router_source
    assert "app.market.indicator_service" not in router_source
    assert 'router.get("/contract/active")' in router_source


def test_taiwan_frontend_indicator_projection_honors_backend_authority_metadata() -> None:
    frontend = REPO_ROOT / "frontend" / "src" / "components"
    authority_path = frontend / "stock-k-line" / "indicatorAuthority.ts"
    consumers = (
        frontend / "stock-k-line" / "indicatorProjection.ts",
        frontend / "chart" / "lightweight-chart" / "indicatorSeriesProjection.ts",
        frontend / "LightweightKLineChart.tsx",
    )
    authority_source = authority_path.read_text(encoding="utf-8")

    assert 'calculation_role === "backend_authoritative"' in authority_source
    assert 'startsWith("tw.technical.indicators.")' in authority_source
    assert "parameter_contract" in authority_source
    for path in consumers:
        source = path.read_text(encoding="utf-8")
        assert "indicatorAuthority" in source, _relative(path)
        assert "backendIndicatorParametersMatch" in source, _relative(path)


def test_taiwan_technical_truth_reads_resolved_daily_platform() -> None:
    paths = (
        BACKEND_APP / "market" / "technical_indicator_gateway.py",
        BACKEND_APP / "market" / "technical_evidence.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "read_taiwan_official_daily" in source, _relative(path)
        assert "db.query(MarketDailyPrice)" not in source, _relative(path)


def test_index_summary_attaches_completed_data_core_projection() -> None:
    indices_path = BACKEND_APP / "market" / "indices.py"
    projection_path = BACKEND_APP / "market" / "tw_dashboard_data_core.py"
    indices_source = indices_path.read_text(encoding="utf-8")
    projection_source = projection_path.read_text(encoding="utf-8")

    assert "_attach_completed_data_core_evidence" in indices_source
    assert "attach_taiwan_dashboard_data_core" in indices_source
    assert "read_taiwan_official_index" in projection_source
    assert "read_taiwan_official_breadth" in projection_source
    assert "provider_fetch" not in projection_source
    assert "refresh_" not in projection_source
    assert "legacy_compatibility" not in projection_source
    assert 'else "data_core_missing"' in projection_source
