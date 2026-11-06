"""Collector final flush keeps retryable work distinct from terminal rejection."""
import asyncio
from datetime import timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, RawFetchResult, TaiwanCurrentIndexSnapshot
from app.market.providers.fugle_realtime_runtime import FugleRealtimeRuntime
from test_fugle_realtime_provider import NOW, _index_message, _persist_mis_index_seed
from test_owned_restart_preflight import restart_runtime  # noqa: F401
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401


@pytest.mark.parametrize("seed_available", [True, False])
def test_terminal_postclose_rejection_flushes_but_missing_seed_stays_pending(seed_available):
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    runtime = FugleRealtimeRuntime(api_key="fixture", active_stock=None,
                                  session_factory=lambda: Session(engine))
    received = NOW.replace(hour=14, minute=5)
    micros = int(received.astimezone(timezone.utc).timestamp() * 1_000_000)
    assert runtime.buffer.ingest(_index_message(micros=micros), received_at=received)
    try:
        with Session(engine) as db:
            if seed_available:
                _persist_mis_index_seed(db, requested_at=NOW, close=35_000,
                                        previous_close=34_900)
            before_raw_count = db.query(RawFetchResult).count()

        async def check():
            # The real flush runs the real materializer on its worker thread;
            # this isolated test never starts a websocket collector.
            runtime._materializer_task = asyncio.current_task()
            lease = runtime.restart_admission.pause()
            try:
                for _ in range(2):
                    if seed_available:
                        await runtime.flush_for_restart(lease)
                        assert runtime._restart_flushed is True
                    else:
                        with pytest.raises(RuntimeError, match="unresolved materialization"):
                            await runtime.flush_for_restart(lease)
                        assert runtime._restart_flushed is False
                assert runtime.buffer.latest("indices", "IX0001") is not None
            finally:
                runtime.resume_after_restart_refusal(lease)
                runtime._materializer_task = None

        asyncio.run(check())
        with Session(engine) as db:
            assert db.query(RawFetchResult).count() == before_raw_count
            assert db.query(TaiwanCurrentIndexSnapshot).count() == int(seed_available)
    finally:
        engine.dispose()


@pytest.mark.parametrize("failed_owner", ["fugle", "crypto"])
def test_collector_failure_logs_only_bounded_owner_and_type(
    restart_runtime, monkeypatch, caplog, failed_owner,
):
    from app.crypto_market import realtime_persistence
    from app.market.providers import fugle_realtime_runtime
    async def failed_flush(*args):
        raise RuntimeError("private-fixture-payload-must-not-be-logged")

    if failed_owner == "fugle":
        collector = FugleRealtimeRuntime(api_key="fixture", active_stock=None)
        monkeypatch.setattr(collector, "flush_for_restart", failed_flush)
        monkeypatch.setattr(fugle_realtime_runtime, "_FUGLE_RUNTIME", collector)
    else:
        monkeypatch.setattr(realtime_persistence.crypto_realtime_persistence_manager,
                            "flush_once", failed_flush)
    runtime, _, _, _ = restart_runtime
    result = asyncio.run(runtime.prepare_owned_restart(timeout_seconds=1))
    assert result == {"state": "PREFLIGHT_REARMED", "stage": "COLLECTOR_FINAL_FLUSH",
                      "terminal_drain_started": False}
    assert runtime.started and runtime.http_admission.accepting
    assert runtime._restart_guard is None and not runtime._restart_undo
    assert f"owner={failed_owner} failure_type=RuntimeError" in caplog.text
    assert "deadline_remaining_ms=" in caplog.text
    assert "private-fixture-payload" not in caplog.text
