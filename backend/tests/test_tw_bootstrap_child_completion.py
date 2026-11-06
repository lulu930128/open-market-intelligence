"""Real JobService/Future dependency waiting with disposable SQLite only."""
from copy import deepcopy

import pytest
from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs import service, resumption, taiwan_bar_bootstrap as bootstrap
from test_job_cooperative_quiescence import database, make_job, snapshot, wait_idle  # noqa: F401
from r1d_test_support import isolated_job_lifecycle  # noqa: F401


def finish_child(job_id, successful=True):
    def worker(db, progress):
        if not successful:
            raise service.JobExecutionError("fixture coverage missing", result={"postcondition_met": False})
        return {"postcondition_met": True}
    service.run_tracked_job(job_id, worker)


def paused_parent(database, monkeypatch, *, dispatch=False):
    monkeypatch.setattr(bootstrap, "resolve_taiwan_tier_a_target_plan", lambda *a, **k: {"symbols": ["2330", "1101"]})
    admitted = []
    def enqueue(db, stock_id, **kwargs):
        child = service.create_job(db, job_type="fixture-child", target=stock_id)
        admitted.append(child.id)
        if dispatch:
            service.submit_job_task(finish_child, child.id)
        return child, True
    monkeypatch.setattr(bootstrap, "enqueue_intraday_materialization_demand", enqueue)
    parent = make_job(database)
    service.submit_job_task(bootstrap.run_taiwan_intraday_bar_bootstrap_job, parent, ("2330", "1101"), 2)
    wait_idle()
    return parent, admitted


def test_parent_releases_single_worker_for_children_then_completes_same_id(database, monkeypatch):
    parent, children = paused_parent(database, monkeypatch, dispatch=True)
    result = snapshot(database, parent)
    assert result["status"] == "success"
    assert result["result"]["postcondition_met"] is True
    assert result["result"]["children_completed_count"] == 2
    assert [item["job_id"] for item in result["result"]["results"]] == children
    with Session(database) as db:
        assert db.query(JobRun).count() == 3


@pytest.mark.parametrize("outcome", ["success", "error", "missing", "unknown"])
def test_wait_does_not_spin_and_terminal_outcome_wakes_original_parent(database, monkeypatch, outcome):
    parent, children = paused_parent(database, monkeypatch)
    assert snapshot(database, parent)["status"] == "paused"
    descriptor = deepcopy(service._paused_tasks[parent])
    for _ in range(3):
        service._resume_ready_tasks()
        wait_idle()
        assert service._paused_tasks[parent] == descriptor
    service.submit_job_task(finish_child, children[0])
    wait_idle()
    assert snapshot(database, parent)["status"] == "paused"
    if outcome in {"success", "error"}:
        service.submit_job_task(finish_child, children[1], outcome == "success")
    else:
        with Session(database) as db:
            child = db.get(JobRun, children[1])
            if outcome == "missing":
                db.delete(child)
            else:
                child.status = "unknown"
            db.commit()
        service._resume_ready_tasks()
    wait_idle()
    result = snapshot(database, parent)
    assert result["status"] == ("success" if outcome == "success" else "error")
    assert result["result"]["postcondition_met"] is (outcome == "success")
    assert result["result"]["admitted_count"] == 2


def test_restart_recovery_uses_frozen_children_without_replanning_or_read_side_effects(database, monkeypatch):
    parent, children = paused_parent(database, monkeypatch)
    before = snapshot(database, parent)
    service._paused_tasks.clear()  # Simulate a new ready owner, not a live mutation.
    with Session(database) as db:
        obligations = service.read_paused_job_obligations(db)
    assert not service._pending_tasks and not service._paused_tasks
    assert snapshot(database, parent) == before
    monkeypatch.setattr(bootstrap, "resolve_taiwan_tier_a_target_plan", lambda *a, **k: pytest.fail("completed admission must not replan"))
    monkeypatch.setattr(bootstrap, "taiwan_presentation_session", lambda *a, **k: pytest.fail("completed admission must retain original date"))
    monkeypatch.setattr(bootstrap, "enqueue_intraday_materialization_demand", lambda *a, **k: pytest.fail("child replay"))
    service.resume_job_obligations(obligations)
    wait_idle()
    assert snapshot(database, parent)["status"] == "paused"
    for child in children:
        service.submit_job_task(finish_child, child)
    wait_idle()
    assert snapshot(database, parent)["status"] == "success"


@pytest.mark.parametrize("mutation", ["self", "duplicate", "missing", "partial"])
def test_malformed_dependency_checkpoint_is_rejected(database, monkeypatch, mutation):
    parent, children = paused_parent(database, monkeypatch)
    descriptor = deepcopy(service._paused_tasks[parent])
    checkpoint = descriptor["checkpoint"]
    state = checkpoint["state"]
    if mutation == "partial":
        state["results"].pop()
        state["totals"]["admitted"] = checkpoint["current"] = 1
    else:
        state["results"][0]["outcome"]["job_id"] = {
            "self": parent, "duplicate": children[1], "missing": None,
        }[mutation]
    with pytest.raises(ValueError, match="JOB_RESUME_CHILD_DEPENDENCIES_INVALID"):
        resumption.validate(descriptor)


def test_completion_during_pending_read_does_not_lose_wakeup(database, monkeypatch):
    parent, children = paused_parent(database, monkeypatch)
    original = service._owner_children_ready
    first = True
    def racing(descriptor):
        nonlocal first
        ready = original(descriptor)
        if first:
            first = False
            for child in children:
                finish_child(child)
            service._resume_ready_tasks()  # The concurrent completion callback.
        return ready
    monkeypatch.setattr(service, "_owner_children_ready", racing)
    service._resume_ready_tasks()
    wait_idle()
    assert snapshot(database, parent)["status"] == "success"
