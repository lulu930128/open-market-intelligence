"""Deterministic file shards with fresh pytest processes and exact collection receipts."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
# Conservative seconds from CI run 40290503629. These are scheduling hints,
# never a test allowlist; discovery below owns the complete test inventory.
SLOW_FILE_SECONDS = {
    "backend/tests/test_job_cooperative_quiescence.py": 540,
    "backend/tests/test_job_dedupe.py": 480,
    "backend/tests/test_job_owner_ledgers.py": 540,
}


def partition(nodeids: list[str], count: int) -> list[list[str]]:
    if count < 1 or not nodeids or len(nodeids) != len(set(nodeids)):
        raise ValueError("Expected a nonempty, unique collection and positive shard count")
    modules = Counter(node.split("::", 1)[0] for node in nodeids)
    costs = {path: max(total, SLOW_FILE_SECONDS.get(path, 0))
             for path, total in modules.items()}
    shards: list[list[str]] = [[] for _ in range(count)]
    loads = [0] * count
    for path in sorted(modules, key=lambda name: (-costs[name], name)):
        index = min(range(count), key=lambda i: (loads[i], i))
        shards[index].append(path)
        loads[index] += costs[path]
    assigned = [path for shard in shards for path in shard]
    if Counter(assigned) != Counter({path: 1 for path in modules}):
        raise ValueError("Shard coverage is not an exact partition")
    return [sorted(shard) for shard in shards]


class CollectionReceipt:
    def __init__(self, output: Path | None = None, expected: list[str] | None = None):
        self.output, self.expected = output, expected

    def pytest_collection_finish(self, session):
        import pytest

        nodes = [item.nodeid.replace("\\", "/") for item in session.items]
        if self.expected is not None and Counter(nodes) != Counter(self.expected):
            raise pytest.UsageError("Module collection differs from the complete shard manifest")
        if self.output is not None:
            self.output.write_text(json.dumps(nodes, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int)
    parser.add_argument("--shards", type=int, default=8)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "ci-results")
    parser.add_argument("--collect", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--module", help=argparse.SUPPRESS)
    parser.add_argument("--expected", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    # Match `python -m pytest` import semantics, including backend.tests helpers.
    sys.path.insert(0, str(ROOT))
    if args.collect:
        import pytest

        return int(pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", "backend/tests"],
                              plugins=[CollectionReceipt(output=args.collect)]))
    if args.module:
        import pytest

        expected = json.loads(args.expected.read_text(encoding="utf-8"))
        return int(pytest.main(["-q", "-ra", "-p", "no:cacheprovider", "--durations=5",
                               "-o", "faulthandler_timeout=120", args.module],
                              plugins=[CollectionReceipt(expected=expected)]))
    if args.shards < 1 or (not args.plan_only and
                          (args.shard is None or not 0 <= args.shard < args.shards)):
        parser.error("--shard must be in [0, --shards)")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    collection = output / "collection.json"
    with (output / "collection.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([sys.executable, __file__, "--collect", str(collection)],
                                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print("\n".join((output / "collection.log").read_text(encoding="utf-8").splitlines()[-60:]))
        return result.returncode
    nodes = json.loads(collection.read_text(encoding="utf-8"))
    shards = partition(nodes, args.shards)
    manifest = {
        "total_tests": len(nodes), "total_modules": sum(map(len, shards)),
        "collection_sha256": hashlib.sha256("\n".join(sorted(nodes)).encode()).hexdigest(),
        "shards": [{"index": i, "modules": paths,
                    "test_count": sum(node.split("::", 1)[0] in paths for node in nodes)}
                   for i, paths in enumerate(shards)],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Exact partition: {len(nodes)} tests / {manifest['total_modules']} modules / {args.shards} shards", flush=True)
    print(f"Collection SHA256: {manifest['collection_sha256']}", flush=True)
    for shard in manifest["shards"]:
        print(f"Shard {shard['index']}: {shard['test_count']} tests, {len(shard['modules'])} modules", flush=True)
    if args.plan_only:
        return 0
    receipts = []
    for index, module in enumerate(shards[args.shard]):
        expected = [node for node in nodes if node.split("::", 1)[0] == module]
        expected_path = output / f"module-{index:03d}.json"
        expected_path.write_text(json.dumps(expected) + "\n", encoding="utf-8")
        print(f"\n=== {module} ({len(expected)} tests; fresh process) ===", flush=True)
        log_path = output / f"module-{index:03d}.log"
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run([sys.executable, __file__, "--module", module,
                                     "--expected", str(expected_path)],
                                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        print(log_path.read_text(encoding="utf-8"), flush=True)
        receipts.append({"module": module, "tests": len(expected), "exit_code": result.returncode})
        (output / "results.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8")
        # Keep executing this shard after assertion failures, so CI reports all
        # modules. Collection/usage errors also remain failing receipts.
    return int(any(receipt["exit_code"] != 0 for receipt in receipts))


if __name__ == "__main__":
    raise SystemExit(main())
