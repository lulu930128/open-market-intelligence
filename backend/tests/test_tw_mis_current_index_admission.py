"""Offline Index admission through the same stock MIS slot and runtime owner."""
from concurrent.futures import wait as future_wait
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event
import socket

import pytest
import requests

from app import runtime_admission
from app.market.providers import twse_mis_breadth_evidence as io
from app.market.providers import twse_mis_current_index as index
from app.market.providers import twse_mis_current_breadth as breadth
from app.market.providers import twse_mis_realtime_acquisition as quote
from app.market.providers.tw_current_market import CurrentIndexAdapter
from app.market.providers.twse_mis_guard import TwseMisProviderGuard
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_INDEX_CAPABILITY_ID, TW_CURRENT_INDEX_DATASET_ID,
    TWSE_MIS_CURRENT_INDEX_DESCRIPTOR, current_source_binding,
)
from app.market.tw_current_market_platform import build_taiwan_current_requirement
from app.market_data.policies import RealtimePolicy
from app.market_data.provider_catalog import plan_data_acquisition_v2

NOW = datetime(2026, 8, 26, 10, 15, tzinfo=timezone(timedelta(hours=8)))
MESSAGE = {"d": "20260826", "t": "10:15:00", "z": "24100.5", "y": "24000",
           "o": "24020", "h": "24120", "l": "23980"}
CASES = [("TAIEX", "tse", "TWSE", "2330"), ("TPEX", "otc", "TPEX", "3406")]


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
    guard = TwseMisProviderGuard()
    monkeypatch.setattr(index, "TWSE_MIS_PROVIDER_GUARD", guard)
    monkeypatch.setattr(breadth, "TWSE_MIS_PROVIDER_GUARD", guard)
    io.reset_io_slots()
    yield owner, guard
    for thread in threads:
        if thread.ident is not None:
            thread.join(timeout=2)
            assert not thread.is_alive()
    io.reset_io_slots()


def adapter(reader=index.read_twse_mis_current_index):
    binding = current_source_binding(provider="twse_mis", source="twse_mis_index_snapshot",
                                     capability_id=TW_CURRENT_INDEX_CAPABILITY_ID)
    return CurrentIndexAdapter(binding, reader, clock=lambda: NOW)


def acquire(scope, reader=index.read_twse_mis_current_index):
    requirement = build_taiwan_current_requirement(
        dataset_id=TW_CURRENT_INDEX_DATASET_ID, capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
        scope_key=scope, requested_at=NOW, policy=RealtimePolicy.PREFER_LIVE, acquiring=True,
    )
    plan = plan_data_acquisition_v2(requirement, (TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,), ())
    return adapter(reader).acquire(requirement, plan.routes[0])


def assert_denial(result, reason):
    assert result.summary.external_calls == 0
    assert result.summary.status.value == "failed"
    assert reason in result.summary.limitations
    assert result.receipts[0].error_message == reason
    assert result.receipts[0].status_code is None
    assert result.receipts[0].raw_text is None
    assert result.provider_health[0].detail_code == reason
    assert result.observations == ()


@pytest.mark.parametrize("scope,exchange,venue,symbol", CASES)
def test_success_preserves_transport_parser_and_lineage(monkeypatch, scope, exchange, venue, symbol):
    calls = []
    def fetch(*args, **kwargs):
        calls.append((args, kwargs))
        return dict(MESSAGE)
    monkeypatch.setattr(index.twse_mis, "fetch_index_message", fetch)
    payload = index.read_twse_mis_current_index(scope, 7)
    channel = "tse_t00.tw" if scope == "TAIEX" else "otc_o00.tw"
    assert calls == [((channel,), {"target": scope, "timeout_seconds": 7, "request": index.http_get})]
    assert payload.status == "available" and payload.external_calls == 1
    actual = acquire(scope)
    baseline = acquire(scope, lambda *a: payload)
    assert actual.observations == baseline.observations
    assert actual.summary == baseline.summary
    assert actual.receipts == baseline.receipts
    assert actual.observations[0].lineage.source == "twse_mis_index_snapshot"
    assert actual.observations[0].venue == venue
    observation = actual.observations[0]
    assert observation.close_value == Decimal("24100.5")
    assert observation.price_change == Decimal("100.5")
    assert observation.lineage.event_at == NOW
    assert observation.lineage.received_at == NOW
    assert observation.state.value == "partial"
    assert observation.finalization.value == "provisional"
    assert observation.provisional is True
    assert payload.payload["points"] == [{
        "time": NOW.isoformat(), "price": 24100.5, "volume": None,
        "open": 24020.0, "high": 24120.0, "low": 23980.0,
    }]


@pytest.mark.parametrize("scope,exchange,venue,symbol", CASES)
def test_active_stock_slot_blocks_index_without_consuming_probe(monkeypatch, offline, scope, exchange, venue, symbol):
    owner, _ = offline
    seconds = [0.0]
    guard = TwseMisProviderGuard(rate_limit_cooldown_seconds=1, monotonic=lambda: seconds[0])
    guard.record_http_failure(guard.before_request().attempt, 429)
    seconds[0] = 2
    monkeypatch.setattr(index, "TWSE_MIS_PROVIDER_GUARD", guard)
    entered, release = Event(), Event()
    def stock(*a, **kw):
        entered.set()
        assert release.wait(2)
        return []
    def waiting(fs, **kw):
        assert entered.wait(1)
        before = guard.snapshot()
        assert_denial(acquire(scope), "TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT")
        assert guard.snapshot() == before
        probe = guard.before_request()
        assert probe.allowed and probe.probe
        guard.cancel_attempt(probe.attempt)
        assert owner.pause_if_idle() is None
        release.set()
        return future_wait(fs, **kw)
    monkeypatch.setattr(index.twse_mis, "fetch_index_message", lambda *a, **k: pytest.fail("overlap"))
    monkeypatch.setattr(io, "wait", waiting)
    try:
        assert io.bounded_fetch(stock, 2, exchange=exchange) == []
    finally:
        release.set()


@pytest.mark.parametrize("scope,exchange,venue,symbol", CASES)
def test_late_index_blocks_breadth_quote_and_index_but_not_other_venue(monkeypatch, offline, scope, exchange, venue, symbol):
    owner, guard = offline
    entered, release = Event(), Event()
    def fetch(*a, **kw):
        entered.set()
        assert release.wait(2)
        return dict(MESSAGE)
    def expired(fs, **kw):
        assert entered.wait(1)
        return set(), set(fs)
    monkeypatch.setattr(index.twse_mis, "fetch_index_message", fetch)
    monkeypatch.setattr(io, "wait", expired)
    try:
        result = acquire(scope)
        assert result.summary.external_calls == 1
        assert "TWSE_MIS_ACQUISITIONDEADLINEEXCEEDED" in result.summary.limitations
        before = guard.snapshot()
        assert owner.pause_if_idle() is None
        assert_denial(acquire(scope), "TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT")
        with pytest.raises(io.AcquisitionInFlight):
            quote._default_reader(symbol, venue, 2)
        diagnostics = {}
        assert breadth._fetch_messages([symbol], venue, 2, diagnostics=diagnostics) == ([], 0, 0)
        assert diagnostics["attempted_batch_count"] == 0
        assert guard.snapshot() == before
        monkeypatch.setattr(io, "wait", future_wait)
        monkeypatch.setattr(index.twse_mis, "fetch_index_message", lambda *a, **kw: dict(MESSAGE))
        other = "TPEX" if scope == "TAIEX" else "TAIEX"
        assert acquire(other).observations
        before_completion = guard.snapshot()
    finally:
        release.set()
        io._IN_FLIGHT[exchange].result(timeout=2)
    assert guard.snapshot() == before_completion  # late result cannot heal/publish
    assert result.observations == ()


@pytest.mark.parametrize("scope,exchange,venue,symbol", CASES)
def test_runtime_pause_is_zero_io_and_resumes(monkeypatch, offline, scope, exchange, venue, symbol):
    owner, guard = offline
    lease = owner.pause_if_idle()
    assert lease is not None
    monkeypatch.setattr(index.twse_mis, "fetch_index_message", lambda *a, **k: pytest.fail("paused IO"))
    before = guard.snapshot()
    try:
        assert_denial(acquire(scope), "TWSE_MIS_RUNTIME_ADMISSION_PAUSED")
        assert guard.snapshot() == before
        assert io._IN_FLIGHT == {}
    finally:
        owner.resume(lease)
    monkeypatch.setattr(index.twse_mis, "fetch_index_message", lambda *a, **k: dict(MESSAGE))
    assert acquire(scope).observations


@pytest.mark.parametrize("scope,exchange,venue,symbol", CASES)
def test_429_guard_and_recovery(monkeypatch, scope, exchange, venue, symbol):
    seconds = [0.0]
    guard = TwseMisProviderGuard(monotonic=lambda: seconds[0])
    monkeypatch.setattr(index, "TWSE_MIS_PROVIDER_GUARD", guard)
    calls = []
    def limited(*a, **k):
        calls.append(a)
        response = requests.Response()
        response.status_code = 429
        response.headers["Retry-After"] = "3"
        raise requests.HTTPError("fixture 429", response=response)
    monkeypatch.setattr(index.twse_mis, "fetch_index_message", limited)
    first, second = acquire(scope), acquire(scope)
    assert first.summary.external_calls == 1 and second.summary.external_calls == 0
    assert first.receipts[0].status_code == second.receipts[0].status_code == 429
    assert "fixture 429" in first.receipts[0].error_message
    assert first.provider_health[0].detail_code in first.summary.limitations
    assert second.provider_health[0].detail_code in second.summary.limitations
    assert len(calls) == 1 and not guard.snapshot().allowed
    seconds[0] = 1000
    monkeypatch.setattr(index.twse_mis, "fetch_index_message", lambda *a, **kw: dict(MESSAGE))
    assert acquire(scope).observations
    assert guard.snapshot().allowed


@pytest.mark.parametrize("scope,exchange,venue,symbol", CASES)
def test_provider_timeout_is_not_slot_denial(monkeypatch, scope, exchange, venue, symbol):
    def timeout(*a, **kw):
        raise requests.Timeout("fixture socket timeout")
    monkeypatch.setattr(index.twse_mis, "fetch_index_message", timeout)
    result = acquire(scope)
    assert result.summary.external_calls == 1
    assert "TWSE_MIS_TIMEOUT" in result.summary.limitations
    assert result.receipts[0].error_message == "Timeout: fixture socket timeout"
    assert io._IN_FLIGHT[exchange].done()


@pytest.mark.parametrize("scope,exchange,venue,symbol", CASES)
def test_unknown_native_start_retains_owned_reservation_and_slot(monkeypatch, offline, scope, exchange, venue, symbol):
    owner, _ = offline
    workers = []
    def unknown_start(worker):
        workers.append(worker)
        raise OSError("fixture unknown native dispatch")
    monkeypatch.setattr(runtime_admission.Thread, "start", unknown_start)
    calls = []
    monkeypatch.setattr(index.twse_mis, "fetch_index_message", lambda *a, **k: calls.append(a) or dict(MESSAGE))
    try:
        first = acquire(scope)
        assert first.summary.external_calls == 1  # conservative unknown-IO reservation
        assert "TWSE_MIS_OSERROR" in first.summary.limitations
        assert owner.pause_if_idle() is None
        assert_denial(acquire(scope), "TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT")
        assert not calls and len(workers) == 1
        with pytest.raises(io.AcquisitionInFlight):
            io.reset_io_slots()
    finally:
        workers[0].run()  # simulate original worker completion, never retry
    assert len(calls) == 1
    lease = owner.pause_if_idle()
    assert lease is not None
    owner.resume(lease)


@pytest.mark.parametrize("scope,exchange,venue,symbol", CASES)
def test_formal_index_route_persists_admission_reason(monkeypatch, offline, scope, exchange, venue, symbol):
    from app.db.models import RawFetchResult, TaiwanCurrentIndexSnapshot
    from app.market.tw_current_market_acquisition import TaiwanCurrentIndexAcquisitionExecutor
    from app.market.tw_current_market_platform import refresh_taiwan_current_index
    from test_tw_current_market_platform import _db

    owner, _ = offline
    lease = owner.pause_if_idle()
    db, engine = _db()  # isolated in-memory SQLite only
    try:
        result = refresh_taiwan_current_index(
            db, index_id=scope, requested_at=NOW,
            descriptors=(TWSE_MIS_CURRENT_INDEX_DESCRIPTOR,),
            acquisition=TaiwanCurrentIndexAcquisitionExecutor((adapter(),)),
        )
        assert result.acquisition.external_calls == 0
        assert "TWSE_MIS_RUNTIME_ADMISSION_PAUSED" in result.acquisition.limitations
        raw = db.query(RawFetchResult).one()
        assert raw.error_message == "TWSE_MIS_RUNTIME_ADMISSION_PAUSED"
        assert raw.status_code is None and raw.raw_text is None
        assert db.query(TaiwanCurrentIndexSnapshot).count() == 0
    finally:
        db.close()
        engine.dispose()
        owner.resume(lease)
