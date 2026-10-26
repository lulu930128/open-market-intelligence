"""Offline shared-slot, deadline and runtime-owner regressions; no network."""
from concurrent.futures import wait as future_wait
from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace
import socket

import pytest

from app import runtime_admission
from app.market.providers import twse_mis_breadth_evidence as io
from app.market.providers import twse_mis_realtime_acquisition as single
from app.market.providers.tw_public_quote import TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR as DESCRIPTOR
from app.market.providers.twse_mis_guard import TwseMisProviderGuard
from app.market_data.contracts import MarketSession
from app.market_data.provider_catalog import plan_data_acquisition_v2
from test_tw_realtime_capabilities import _requirement
from test_twse_mis_realtime_acquisition import _payload

NOW = datetime(2026, 8, 26, 2, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("network forbidden"))
    owner = runtime_admission.DetachedAdmission()
    monkeypatch.setattr(runtime_admission, "detached_admission", owner)
    threads = []
    class TrackedThread(runtime_admission.OwnedWorkThread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            threads.append(self)
    monkeypatch.setattr(io, "Thread", TrackedThread)
    io.reset_io_slots()
    yield owner
    for thread in threads:
        if thread.ident is not None:
            thread.join(timeout=2)
            assert not thread.is_alive()
    io.reset_io_slots()


def acquire(adapter):
    requirement = _requirement(DESCRIPTOR, session=MarketSession.CONTINUOUS)
    requirement = requirement.model_copy(update={
        "bounds": requirement.bounds.model_copy(update={
            "max_external_calls": 1, "max_subscriptions": 0, "timeout_seconds": 8,
        }),
    })
    plan = plan_data_acquisition_v2(requirement, (DESCRIPTOR,), ())
    assert len(plan.routes) == 1
    return adapter.acquire_quote_observations(requirement, plan)


def response(code=200):
    return SimpleNamespace(status_code=code, text=_payload(), headers={},
                           url="https://mis.twse.com.tw/stock/api/getStockInfo.jsp")


@pytest.mark.parametrize("budget,expected", [(20, 8), (8, 8), (3, 3)])
def test_default_reader_caps_deadline_and_fetches_exactly_one_symbol(monkeypatch, budget, expected):
    calls = []
    def fetch(codes, **kwargs):
        calls.append((codes, kwargs))
        return response()
    monkeypatch.setattr(single.twse_mis, "get_stock_response", fetch)
    result = single._default_reader("2330", "TWSE", budget)
    assert result.status_code == 200
    assert calls == [(["2330"], {"exchange": "tse", "timeout_seconds": expected})]
    adapter = single.TwseMisRealtimeAcquisitionAdapter(clock=lambda: NOW)
    assert adapter._provider_guard is single.TWSE_MIS_PROVIDER_GUARD


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf"), -float("inf")])
def test_invalid_wait_never_starts_transport(seconds):
    with pytest.raises(io.AcquisitionDeadlineExceeded):
        io.bounded_fetch(lambda **kw: pytest.fail("IO forbidden"), seconds, exchange="tse")
    assert io._IN_FLIGHT == {}


def test_breadth_slot_blocks_single_without_consuming_recovery_probe(monkeypatch):
    entered, release = Event(), Event()
    def busy(**kwargs):
        entered.set()
        assert release.wait(2)
    def expired(fs, **kwargs):
        assert entered.wait(1)
        return set(), set(fs)
    monkeypatch.setattr(io, "wait", expired)
    try:
        with pytest.raises(io.AcquisitionDeadlineExceeded):
            io.bounded_fetch(busy, 8, exchange="tse")
        seconds = [0.0]
        guard = TwseMisProviderGuard(rate_limit_cooldown_seconds=1, monotonic=lambda: seconds[0])
        guard.record_http_failure(guard.before_request().attempt, 429)
        seconds[0] = 2
        monkeypatch.setattr(single.twse_mis, "get_stock_response", lambda *a, **k: pytest.fail("busy IO"))
        result = acquire(single.TwseMisRealtimeAcquisitionAdapter(clock=lambda: NOW, provider_guard=guard))
        assert result.summary.external_calls == 0
        assert result.observations == ()
        assert result.provider_health[0].detail_code == "TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT"
        # Recovery remains available, not falsely healthy and not left busy.
        retry = guard.before_request()
        assert retry.allowed and retry.probe
        guard.cancel_attempt(retry.attempt)
    finally:
        release.set()


def test_late_single_retains_slot_and_runtime_owner_without_publishing(monkeypatch, offline):
    entered, release = Event(), Event()
    def fetch(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return response()
    def expired(fs, **kwargs):
        assert entered.wait(1)
        return set(), set(fs)
    monkeypatch.setattr(single.twse_mis, "get_stock_response", fetch)
    monkeypatch.setattr(io, "wait", expired)
    guard = TwseMisProviderGuard(failure_threshold=1)
    adapter = single.TwseMisRealtimeAcquisitionAdapter(clock=lambda: NOW, provider_guard=guard)
    try:
        result = acquire(adapter)
        assert result.summary.external_calls == 1
        assert not result.observations
        before = guard.snapshot()
        assert not before.allowed
        assert offline.pause_if_idle() is None
        with pytest.raises(io.AcquisitionInFlight):
            io.bounded_fetch(lambda **kw: pytest.fail("overlap"), 8, exchange="tse")
        monkeypatch.setattr(io, "wait", future_wait)
        # A distinct venue has its own bounded slot.
        assert io.bounded_fetch(lambda **kw: "otc", 1, exchange="otc") == "otc"
    finally:
        release.set()
        io._IN_FLIGHT["tse"].result(timeout=2)
    assert adapter._cache["2330"][0].raw_text is None
    assert guard.snapshot().generation == before.generation
    assert not guard.snapshot().allowed


def test_runtime_pause_blocks_io_without_poisoning_slot_or_guard(monkeypatch, offline):
    lease = offline.pause_if_idle()
    assert lease is not None
    guard = TwseMisProviderGuard(failure_threshold=1)
    monkeypatch.setattr(single.twse_mis, "get_stock_response", lambda *a, **kw: pytest.fail("paused IO"))
    try:
        result = acquire(single.TwseMisRealtimeAcquisitionAdapter(clock=lambda: NOW, provider_guard=guard))
        assert result.summary.external_calls == 0
        assert result.provider_health[0].detail_code == "TWSE_MIS_RUNTIME_ADMISSION_PAUSED"
        assert guard.snapshot().allowed
        assert io._IN_FLIGHT == {}
    finally:
        offline.resume(lease)
    monkeypatch.setattr(single.twse_mis, "get_stock_response", lambda *a, **kw: response())
    assert single._default_reader("2330", "TWSE", 8).status == "available"


def test_unknown_thread_start_retains_slot_until_actual_completion(monkeypatch):
    targets = []
    calls = []
    class RefusedThread:
        def __init__(self, **kwargs):
            targets.append(kwargs["target"])
        def start(self):
            raise OSError("fixture start failure")
    monkeypatch.setattr(io, "Thread", RefusedThread)
    try:
        with pytest.raises(OSError):
            io.bounded_fetch(lambda **kw: calls.append("completed"), 1, exchange="tse")
        assert not calls
        with pytest.raises(io.AcquisitionInFlight):
            io.bounded_fetch(lambda **kw: pytest.fail("unknown delivery retry"), 1, exchange="tse")
        with pytest.raises(io.AcquisitionInFlight):
            io.reset_io_slots()
    finally:
        # Simulate completion of the original retained worker, not a new fetch.
        targets[0]()
    assert calls == ["completed"]
    assert io._IN_FLIGHT["tse"].done()


def test_429_on_single_blocks_next_request_across_adapters(monkeypatch):
    calls = []
    monkeypatch.setattr(single.twse_mis, "get_stock_response",
                        lambda *a, **kw: calls.append(a) or response(429))
    guard = TwseMisProviderGuard()
    first = acquire(single.TwseMisRealtimeAcquisitionAdapter(clock=lambda: NOW, provider_guard=guard))
    second = acquire(single.TwseMisRealtimeAcquisitionAdapter(clock=lambda: NOW, provider_guard=guard))
    assert first.summary.external_calls == 1
    assert second.summary.external_calls == 0
    assert second.provider_health[0].detail_code in second.summary.limitations
    assert "TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT" not in first.summary.limitations
    assert len(calls) == 1 and not guard.snapshot().allowed


@pytest.mark.parametrize("reason", [
    "TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT",
    "TWSE_MIS_RUNTIME_ADMISSION_PAUSED",
])
def test_formal_quote_route_preserves_zero_io_denial_in_summary(monkeypatch, reason):
    from app.db.models import RawFetchResult, TaiwanStockQuoteSnapshot
    from app.market.public_quote_platform import acquire_taiwan_public_last_trade_quote
    from app.market_data.policies import RealtimePolicy
    from test_twse_mis_realtime_acquisition import _db

    def denied(*args):
        raise io.AcquisitionInFlight(reason)

    guard = TwseMisProviderGuard()
    adapter = single.TwseMisRealtimeAcquisitionAdapter(
        reader=denied, clock=lambda: NOW, provider_guard=guard,
    )
    db, engine = _db()
    try:
        result = acquire_taiwan_public_last_trade_quote(
            db, stock_id="2330", policy=RealtimePolicy.PREFER_LIVE,
            requested_at=NOW, acquisition=adapter,
        )
        assert result.acquisition.external_calls == 0
        assert result.acquisition.status.value == "failed"
        assert "PROVIDER_REQUEST_FAILED" in result.acquisition.limitations
        assert reason in result.acquisition.limitations
        assert "ROUTE_REQUIREMENT_UNSATISFIED:twse_mis:twse_mis.stock_info" in result.acquisition.limitations
        raw = db.query(RawFetchResult).one()
        assert raw.error_message == reason
        assert raw.status_code is None and raw.raw_text is None
        assert db.query(TaiwanStockQuoteSnapshot).count() == 0
        assert guard.snapshot().allowed
    finally:
        db.close()
        engine.dispose()


def test_active_in_budget_breadth_slot_also_blocks_single(monkeypatch, offline):
    entered, release = Event(), Event()
    guard = TwseMisProviderGuard()

    def busy(**kwargs):
        entered.set()
        assert release.wait(2)
        return "completed"

    def observe_during_wait(fs, **kwargs):
        assert entered.wait(1)
        result = acquire(single.TwseMisRealtimeAcquisitionAdapter(
            clock=lambda: NOW, provider_guard=guard,
        ))
        assert result.summary.external_calls == 0
        assert "TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT" in result.summary.limitations
        assert offline.pause_if_idle() is None
        assert guard.snapshot().allowed
        release.set()
        return future_wait(fs, **kwargs)

    monkeypatch.setattr(single.twse_mis, "get_stock_response", lambda *a, **kw: pytest.fail("overlap"))
    monkeypatch.setattr(io, "wait", observe_during_wait)
    try:
        assert io.bounded_fetch(busy, 1, exchange="tse") == "completed"
    finally:
        release.set()
