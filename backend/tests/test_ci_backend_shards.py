"""The CI scheduler must never drop, duplicate, or split a test module."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    "ci_backend_shards", Path(__file__).resolve().parents[2] / "scripts/ci-backend-shards.py"
)
sharding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sharding)


def test_partition_is_complete_disjoint_and_deterministic():
    nodes = [f"backend/tests/test_{module}.py::test_value[{value}]"
             for module in range(13) for value in range(module + 1)]
    shards = sharding.partition(nodes, 8)
    modules = [module for shard in shards for module in shard]
    assert len(modules) == len(set(modules)) == 13
    assert set(modules) == {node.split("::", 1)[0] for node in nodes}
    assert shards == sharding.partition(list(reversed(nodes)), 8)
    assert sum(sum(node.split("::", 1)[0] in shard for node in nodes) for shard in shards) == len(nodes)


def test_observed_slow_files_are_spread_across_workers():
    slow = list(sharding.SLOW_FILE_SECONDS)
    nodes = [f"{module}::test_one" for module in slow]
    nodes += [f"backend/tests/test_fast_{i}.py::test_one" for i in range(40)]
    shards = sharding.partition(nodes, 8)
    assert len({index for index, shard in enumerate(shards) if set(shard) & set(slow)}) == len(slow)


@pytest.mark.parametrize("nodes,count", [([], 2), (["a.py::test_x"] * 2, 2), (["a.py::test_x"], 0)])
def test_invalid_inventory_fails_closed(nodes, count):
    with pytest.raises(ValueError):
        sharding.partition(nodes, count)


def test_execution_collection_must_match_planned_nodeids():
    guard = sharding.CollectionReceipt(expected=["a.py::test_x", "a.py::test_y"])
    guard.pytest_collection_finish(SimpleNamespace(items=[
        SimpleNamespace(nodeid="a.py::test_y"), SimpleNamespace(nodeid="a.py::test_x")]))
    with pytest.raises(pytest.UsageError, match="differs"):
        guard.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid="a.py::test_x")]))
