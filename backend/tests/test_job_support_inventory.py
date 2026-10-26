"""Coverage follows executable submissions; no fixed task count or copied inventory."""
import ast
import importlib.util
from pathlib import Path

from app.jobs import resumption


ROOT = Path(__file__).resolve().parents[2]


def test_every_reachable_submission_has_explicit_replay_policy():
    spec = importlib.util.spec_from_file_location("job_inventory", ROOT / "scripts/job-support-inventory.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.inventory(ROOT)
    reachable = {tuple(row["task"].rsplit(".", 1)) for row in result["tasks"]}
    assert reachable == resumption.QUEUED_TASKS | resumption.ORIGINAL_STATE_MACHINE_TASKS
    # Source-audited forwarding sinks, not extra workers. A new dynamic sink
    # requires a caller trace; it cannot silently disappear from the inventory.
    assert {(row["module"], row["expression"]) for row in result["unresolved_forwarding"]} == {
        ("app.routers.jobs", "task"), ("app.routers.market", "task"),
        ("app.routers.market_family_helpers", "task"),
    }
    assert all(row["submissions"] and row["owner_evidence"] for row in result["tasks"])


def test_running_period_allowlist_matches_wired_entrypoints():
    path = ROOT / "backend/app/jobs/backfill_tasks.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wired = {}
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        for call in ast.walk(function):
            if isinstance(call, ast.Call) and ast.unparse(call.func) == "period_checkpoint_arguments":
                wired[("app.jobs.backfill_tasks", function.name)] = ast.literal_eval(call.args[1])
    assert wired == resumption.PERIOD_TASK_OWNERS
    assert not (resumption.QUEUED_TASKS & resumption.ORIGINAL_STATE_MACHINE_TASKS)


def test_shared_period_ledger_has_no_domain_or_io_dependency():
    tree = ast.parse((ROOT / "backend/app/utils/backfill_checkpoint.py").read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module)
    assert imports <= {"copy", "typing"}


def test_bounded_owner_policy_matches_injected_entrypoints():
    wired = {}
    for module in {identity[0] for identity in resumption.OWNER_TASKS}:
        tree = ast.parse((ROOT / "backend" / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8"))
        for function in tree.body:
            if isinstance(function, ast.FunctionDef):
                for call in ast.walk(function):
                    if isinstance(call, ast.Call) and ast.unparse(call.func) == "owner_continuation_arguments":
                        wired[(module, function.name)] = ast.literal_eval(call.args[1])
    assert wired == resumption.OWNER_TASKS
    assert resumption.ORIGINAL_HANDOFF_TASKS <= resumption.ORIGINAL_STATE_MACHINE_TASKS
    assert not (resumption.ORIGINAL_HANDOFF_TASKS & resumption.QUEUED_TASKS)
