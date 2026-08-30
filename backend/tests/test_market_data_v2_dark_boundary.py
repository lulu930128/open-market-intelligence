from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
BACKEND_APP = REPO_ROOT / "backend" / "app"
AGENTS_ROOT = REPO_ROOT / "agents"
NEW_MODULES = {
    "app.market_data.provider_policy",
    "app.market_data.research_lease",
    "app.market_data.control_plane",
    "app.market_data.acquisition_observability",
}
NEW_MODULE_PATHS = {
    BACKEND_APP / "market_data" / f"{module.rsplit('.', 1)[-1]}.py"
    for module in NEW_MODULES
}
FORBIDDEN_NEW_MODULE_PREFIXES = (
    "app.ai",
    "app.db",
    "app.routers",
    "app.market",
    "agents",
    "requests",
    "httpx",
    "sqlalchemy",
    "multiprocessing",
    "subprocess",
    "asyncio",
)
AUTHORIZED_INTEGRATION_IMPORTS = {
    "backend/app/us_market/market_data_policy.py": [
        "app.market_data.provider_policy"
    ],
    "backend/app/market/providers/kgi_realtime_lease.py": [
        "app.market_data.research_lease"
    ],
    "backend/app/market/providers/fugle_realtime_lease.py": [
        "app.market_data.research_lease"
    ],
    "backend/app/market/tw_realtime_lease_platform.py": [
        "app.market_data.research_lease"
    ],
}
def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Call):
            dynamic_name: str | None = None
            if isinstance(node.func, ast.Name) and node.func.id == "__import__":
                dynamic_name = "__import__"
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
            ):
                dynamic_name = "importlib.import_module"
            if dynamic_name and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    modules.add(first.value)
                else:
                    modules.add(f"DYNAMIC:{dynamic_name}")
    return modules


def _matches_module_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _production_python_files() -> list[Path]:
    files = list(BACKEND_APP.rglob("*.py")) + list(AGENTS_ROOT.rglob("*.py"))
    return sorted(path for path in files if path not in NEW_MODULE_PATHS)


def test_only_explicit_market_owned_integration_imports_dark_02a_modules() -> None:
    violations: dict[str, list[str]] = {}
    for path in _production_python_files():
        matches = sorted(
            imported
            for imported in _imports(path)
            if imported in NEW_MODULES
            or any(imported.startswith(f"{module}.") for module in NEW_MODULES)
        )
        if matches:
            violations[path.relative_to(REPO_ROOT).as_posix()] = matches
    assert violations == AUTHORIZED_INTEGRATION_IMPORTS


def test_dark_modules_only_import_provider_neutral_dependencies() -> None:
    violations: dict[str, list[str]] = {}
    for path in sorted(NEW_MODULE_PATHS):
        assert path.is_file(), f"missing planned dark module: {path}"
        matches = sorted(
            imported
            for imported in _imports(path)
            if any(
                _matches_module_prefix(imported, prefix)
                for prefix in FORBIDDEN_NEW_MODULE_PREFIXES
            )
            or imported.startswith("DYNAMIC:")
        )
        if matches:
            violations[str(path.relative_to(REPO_ROOT))] = matches
    assert violations == {}


def test_market_data_package_init_remains_unwired() -> None:
    init_path = REPO_ROOT / "backend" / "app" / "market_data" / "__init__.py"
    init_source = init_path.read_text(encoding="utf-8")
    assert all(module.rsplit(".", 1)[-1] not in init_source for module in NEW_MODULES)


def test_dark_source_has_no_provider_catalog_or_side_effect_entrypoint() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in NEW_MODULE_PATHS
    )
    forbidden_literals = (
        "kgi_superpy",
        "twse_mis",
        "requests.",
        "httpx.",
        "sqlalchemy",
        "subprocess.",
        "create_task(",
    )
    assert not any(value in combined for value in forbidden_literals)
