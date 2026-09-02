from __future__ import annotations

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP = REPO_ROOT / "backend" / "app"


def _router_operations(module_path: Path) -> dict[str, tuple[str, str]]:
    tree = ast.parse(module_path.read_text(encoding="utf-8-sig"))
    operations: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            target = decorator.func
            if not (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "router"
                and target.attr in {"get", "post", "put", "patch", "delete"}
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                continue
            operations[node.name] = (target.attr, decorator.args[0].value)
    return operations


def _function_parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {
        argument.arg
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
    }


def _parameter_default(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter_name: str,
) -> ast.AST | None:
    positional = [*node.args.posonlyargs, *node.args.args]
    positional_defaults = [
        None for _ in range(len(positional) - len(node.args.defaults))
    ] + list(node.args.defaults)
    for argument, default in zip(positional, positional_defaults):
        if argument.arg == parameter_name:
            return default
    for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        if argument.arg == parameter_name:
            return default
    return None


def _is_provider_control_default(default: ast.AST | None) -> bool:
    if not isinstance(default, ast.Call) or _qualified_name(default.func) not in {
        "Query",
        "Path",
    }:
        return False
    rendered = ast.unparse(default)
    return "yahoo_chart" in rendered or "alphavantage" in rendered


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _qualified_name(node.value)
        return f"{owner}.{node.attr}" if owner else node.attr
    return ""


class _ProviderCallVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.function_stack: list[str] = []
        self.calls: set[tuple[str, str, str]] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        callee = _qualified_name(node.func)
        is_us_market_call = any(
            token in callee
            for token in (
                "us_market_service",
                "refresh_us_daily_prices",
                "list_us_ohlc_chart_data",
                "repair_us_ohlc_history",
            )
        )
        if is_us_market_call and any(keyword.arg == "provider" for keyword in node.keywords):
            owner = self.function_stack[0] if self.function_stack else "<module>"
            self.calls.add((self.relative_path, owner, callee))
        self.generic_visit(node)


def test_us_product_routes_cannot_expand_provider_selection_surface() -> None:
    router_path = BACKEND_APP / "routers" / "us_market.py"
    tree = ast.parse(router_path.read_text(encoding="utf-8-sig"))
    operations = _router_operations(router_path)
    provider_routes: set[tuple[str, str]] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if "provider" not in _function_parameter_names(node):
            continue
        operation = operations.get(node.name)
        if operation is not None and (
            "{provider}" in operation[1]
            or _is_provider_control_default(_parameter_default(node, "provider"))
        ):
            provider_routes.add(operation)

    # Product refresh accepts a deprecated provider argument but ignores it;
    # provider-specific repair remains diagnostics-only.
    assert provider_routes == {
        ("post", "/daily/{symbol}/refresh"),
        ("post", "/diagnostics/providers/{provider}/ohlc/{symbol}/repair"),
    }


def test_frontend_us_market_requests_do_not_choose_a_provider() -> None:
    violations: list[str] = []
    provider_argument = re.compile(
        r"\bprovider\s*:\s*['\"](?:auto|alpaca|alphavantage|massive|twelve_data|yahoo_chart)['\"]"
    )
    for path in (REPO_ROOT / "frontend" / "src").rglob("*.ts*"):
        content = path.read_text(encoding="utf-8-sig")
        offsets = [match.start() for match in re.finditer(r"/api/", content)]
        for index, offset in enumerate(offsets):
            endpoint_end = offsets[index + 1] if index + 1 < len(offsets) else len(content)
            request = content[offset:endpoint_end]
            if request.startswith("/api/us-market") and provider_argument.search(request):
                violations.append(str(path.relative_to(REPO_ROOT)))
    assert violations == []


def test_us_provider_selected_calls_are_frozen_to_named_legacy_debt() -> None:
    roots = (
        BACKEND_APP / "jobs",
        BACKEND_APP / "market_data",
        BACKEND_APP / "ai",
    )
    calls: set[tuple[str, str, str]] = set()
    for root in roots:
        for path in root.rglob("*.py"):
            relative_path = path.relative_to(BACKEND_APP).as_posix()
            visitor = _ProviderCallVisitor(relative_path)
            visitor.visit(ast.parse(path.read_text(encoding="utf-8-sig")))
            calls.update(visitor.calls)

    assert calls == set()


def test_us_ohlc_repair_job_uses_canonical_platform_not_legacy_service() -> None:
    job_path = BACKEND_APP / "jobs" / "backfill_tasks.py"
    source = job_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    repair = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_run_canonical_us_ohlc_repair"
    )
    calls = {
        _qualified_name(node.func)
        for node in ast.walk(repair)
        if isinstance(node, ast.Call)
    }
    assert "USDailyOhlcvPlatform" in calls
    assert "us_market_service.repair_us_ohlc_history" not in calls
    assert "us_market_service.refresh_us_daily_prices" not in calls


def test_shared_market_data_reverse_dependency_is_frozen_to_eod_legacy_debt() -> None:
    violations: list[str] = []
    for path in (BACKEND_APP / "market_data").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.us_market.service":
                violations.append(path.relative_to(BACKEND_APP).as_posix())
            elif isinstance(node, ast.Import):
                if any(alias.name == "app.us_market.service" for alias in node.names):
                    violations.append(path.relative_to(BACKEND_APP).as_posix())
    assert sorted(set(violations)) == []


def test_us_production_consumers_do_not_import_raw_daily_storage() -> None:
    protected_roots = (
        BACKEND_APP / "ai",
        BACKEND_APP / "market",
        BACKEND_APP / "watchlists",
    )
    violations: list[str] = []
    for root in protected_roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.module != "app.db.models":
                    continue
                if any(alias.name == "USDailyPrice" for alias in node.names):
                    violations.append(path.relative_to(BACKEND_APP).as_posix())
    assert violations == []


def test_cross_provider_fallback_is_frozen_to_one_named_legacy_service_function() -> None:
    service_path = BACKEND_APP / "us_market" / "service.py"
    tree = ast.parse(service_path.read_text(encoding="utf-8-sig"))
    fallback_owners: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        called = {
            _qualified_name(call.func)
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        }
        if {
            "refresh_us_daily_prices_from_yahoo_chart",
            "refresh_us_daily_prices_from_alphavantage",
        }.issubset(called):
            fallback_owners.add(node.name)

    assert fallback_owners == {"refresh_us_daily_prices"}
