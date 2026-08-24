from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
BACKEND_APP = REPO_ROOT / "backend" / "app"
AGENTS_ROOT = REPO_ROOT / "agents"
TASK_ROOT = REPO_ROOT / "docs" / "agent-runs" / "market-data-integration-v2-20260821"
BASELINE_PATH = TASK_ROOT / "artifacts" / "02a-source-baseline.json"

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
    "threading",
    "multiprocessing",
    "subprocess",
    "asyncio",
)
AUTHORIZED_INTEGRATION_IMPORTS = {
    "backend/app/us_market/market_data_policy.py": [
        "app.market_data.provider_policy"
    ],
}
AUTHORIZED_PROTECTED_DRIFT = {
    "agents/omi_mcp_server/public_contract_snapshot.json",
    "backend/app/ai/market_context/taiwan_stock.py",
}


def _sha256(path: Path) -> str:
    canonical_source = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(canonical_source).hexdigest()


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


def test_baseline_artifact_is_parseable_and_truthful_about_dark_start() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["result"] == "passed"
    assert baseline["foundation_reference"]["expected_target_count"] == 30
    assert baseline["foundation_reference"]["current_mismatch_count"] == 0
    assert baseline["foundation_reference"]["closure_eligible"] is False
    assert baseline["planned_modules_existed_before_02a"] is False
    assert baseline["production_import_matches_before_02a"] == []
    assert baseline["safety"] == {
        "production_wiring": False,
        "real_provider_calls": 0,
        "research_leases_created": 0,
        "db_writes": 0,
        "runtime_mutations": 0,
        "commit_or_push": False,
    }


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


def test_market_data_package_init_remains_unwired_and_hash_stable() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    protected = {
        item["path"]: item["sha256"] for item in baseline["protected_files"]
    }
    init_path = REPO_ROOT / "backend" / "app" / "market_data" / "__init__.py"
    init_source = init_path.read_text(encoding="utf-8")
    assert _sha256(init_path) == protected["backend/app/market_data/__init__.py"]
    assert all(module.rsplit(".", 1)[-1] not in init_source for module in NEW_MODULES)


def test_protected_consumer_drift_is_explicitly_bounded() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    mismatches = []
    for item in baseline["protected_files"]:
        path = REPO_ROOT / item["path"]
        actual = _sha256(path)
        if actual != item["sha256"]:
            mismatches.append(
                {
                    "path": item["path"],
                    "expected": item["sha256"],
                    "actual": actual,
                }
            )
    assert {item["path"] for item in mismatches} <= AUTHORIZED_PROTECTED_DRIFT


def test_foundation_reference_matches_current_validated_checkpoint() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    checkpoint_path = REPO_ROOT / baseline["foundation_reference"]["artifact"]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    extension_path = (
        REPO_ROOT
        / "docs"
        / "agent-runs"
        / "tw-realtime-market-state-remediation-20260824"
        / "artifacts"
        / "acceptance-extension-checkpoint.json"
    )
    extension = json.loads(extension_path.read_text(encoding="utf-8"))
    assert checkpoint["validation"]["result"] == "passed"
    assert extension["validation"]["result"] == "passed"
    assert checkpoint["coverage"]["target_count"] == 30
    assert len(checkpoint["files"]) == 30
    extension_files = {item["path"]: item for item in extension["files"]}
    mismatches = []
    for item in checkpoint["files"]:
        item = extension_files.get(item["path"], item)
        path = REPO_ROOT / item["path"]
        actual = _sha256(path) if path.is_file() else None
        if actual != item["sha256"]:
            mismatches.append(
                {
                    "path": item["path"],
                    "expected": item["sha256"],
                    "actual": actual,
                }
            )
    for item in extension_files.values():
        if any(base_item["path"] == item["path"] for base_item in checkpoint["files"]):
            continue
        path = REPO_ROOT / item["path"]
        actual = _sha256(path) if path.is_file() else None
        if actual != item["sha256"]:
            mismatches.append(
                {
                    "path": item["path"],
                    "expected": item["sha256"],
                    "actual": actual,
                }
            )
    assert mismatches == []


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
