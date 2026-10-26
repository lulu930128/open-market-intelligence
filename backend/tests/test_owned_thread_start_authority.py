"""Unknown Thread.start completion must never authorize production PREPARE."""
import asyncio
from threading import Event

import pytest

from app import runtime_admission as admission
from test_owned_restart_preflight import restart_runtime  # noqa: F401
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401


@pytest.mark.parametrize("started", [False, True])
def test_start_exception_retains_worker_until_actual_completion(monkeypatch, started):
    owner = admission.DetachedAdmission()
    monkeypatch.setattr(admission, "detached_admission", owner)
    release = Event()
    worker = admission.OwnedWorkThread(target=release.wait)
    native_start = admission.Thread.start

    def ambiguous_start(thread):
        if started:
            native_start(thread)
        raise OSError("fixture ambiguous start")

    monkeypatch.setattr(admission.Thread, "start", ambiguous_start)
    try:
        with pytest.raises(OSError, match="ambiguous start"):
            worker.start()
        assert owner.pause_if_idle() is None
        assert owner.observation() == {"retained_worker_count": 1, "admission_paused": False}
        with pytest.raises(RuntimeError, match="once"):
            worker.start()
    finally:
        release.set()
        if started:
            worker.join(2)
            assert not worker.is_alive()
    if started:
        lease = owner.pause_if_idle()
        assert lease is not None
        owner.resume(lease)


def test_finished_worker_is_not_re_reserved_or_double_released_after_start_error(monkeypatch):
    owner = admission.DetachedAdmission()
    monkeypatch.setattr(admission, "detached_admission", owner)
    native_start = admission.Thread.start

    def completed_then_error(thread):
        native_start(thread)
        thread.join(2)
        assert not thread.is_alive()
        raise OSError("fixture after actual completion")

    monkeypatch.setattr(admission.Thread, "start", completed_then_error)
    with pytest.raises(OSError, match="after actual completion"):
        admission.OwnedWorkThread(target=lambda: None).start()
    lease = owner.pause_if_idle()
    assert lease is not None
    owner.resume(lease)


def test_unknown_start_blocks_real_prepare_and_keeps_terminal_drain_unstarted(
    restart_runtime, monkeypatch,
):
    """Use real coordinator/fences and disposable SQLite, never the formal DB."""
    runtime, _, _, _ = restart_runtime
    def unknown_start(thread):
        raise OSError("fixture no completion proof")
    monkeypatch.setattr(admission.Thread, "start", unknown_start)
    with pytest.raises(OSError):
        admission.OwnedWorkThread(target=lambda: None).start()

    async def check():
        result = await runtime.prepare_owned_restart(timeout_seconds=.1)
        assert result == {"state": "PREFLIGHT_REARMED",
                          "stage": "DETACHED_WORKER_QUIESCENCE",
                          "terminal_drain_started": False}
        assert runtime.owned_restart_rearmed()
        assert runtime.http_admission.accepting
        assert runtime._restart_guard is None and runtime._stop_task is None
        assert not runtime.restart_preflight()["all_writers_drained"]
        assert runtime.restart_diagnostics()["owner_observations"]["detached_workers"] == {
            "retained_worker_count": 1, "admission_paused": False,
        }
    asyncio.run(check())
