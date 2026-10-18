"""M0.5 offline acquisition reliability: fake time, no provider network."""
from datetime import datetime, timedelta
from threading import Event
from time import monotonic
import json
import socket

import pytest
import requests
from sqlalchemy import event

from app.db.models import RawFetchResult, SourceRegistry
from app.market.providers import twse_mis_current_breadth as provider
from app.market.providers import twse_mis_breadth_evidence as io
from app.market.tw_breadth_acquisition_contract import BreadthAcquisitionEvidence
from app.market.tw_current_market_repository import inspect_breadth_acquisition_receipt
from app.market.trading_calendar import TAIWAN_TZ
from test_tw_current_market_platform import _db
from test_tw_breadth_semantics import acquire


NOW = datetime(2026, 10, 7, 10, 15, tzinfo=TAIWAN_TZ)
CODES = [str(6000 + i) for i in range(1100)]


def message(code, **overrides):
    return dict(c=code, d="20261007", t="10:15:00", z="110", v="5", tv="1",
                y="100", o="105", h="115", l="101", pz="999", ps="9", ts="0", **overrides)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("M0.5 tests cannot access network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    provider.reset_twse_mis_current_breadth_provider()
    yield
    provider.reset_twse_mis_current_breadth_provider()


@pytest.fixture
def clock(monkeypatch):
    class Fake:
        seconds = 0.0
    fake = Fake()

    class Meta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Wall(datetime, metaclass=Meta):
        @classmethod
        def now(cls, tz=None):
            return (NOW + timedelta(seconds=fake.seconds)).astimezone(tz)

    monkeypatch.setattr(provider, "monotonic", lambda: fake.seconds)
    monkeypatch.setattr(provider, "datetime", Wall)
    return fake


def fake_fetch(clock, calls, *, scan_duration=1.744, rescue_duration=0.5):
    def fetch(codes, *, timeout_seconds, **kwargs):
        rescue = len(codes) == 32
        duration = rescue_duration if rescue else scan_duration
        calls.append((list(codes), timeout_seconds))
        if duration > timeout_seconds + 1e-8:
            clock.seconds += timeout_seconds
            raise TimeoutError("fixture request exceeded its allocated deadline")
        clock.seconds += duration
        rows = []
        for code in codes:
            row = message(code)
            if not rescue and code in CODES[:64]:
                row["z"] = "-"
            if code in CODES[-20:]:
                row.update(z="-", v="0", tv="0")
            rows.append(row)
        return rows
    return fetch


def test_11_batches_19184ms_preserves_primary_coverage_and_uses_fractional_rescue(clock, monkeypatch):
    calls = []
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fake_fetch(clock, calls))
    # Before policy: existing primary scan has its entire 20 seconds.
    baseline, failed, count = provider._fetch_messages(CODES, "TWSE", 20)
    assert len(baseline) == 1100 and failed == 0 and count == 11
    assert clock.seconds == pytest.approx(19.184)
    clock.seconds = 0
    calls.clear()
    result = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: CODES)
    assert result.payload is not None, result.error
    evidence = BreadthAcquisitionEvidence.model_validate(result.payload["acquisition_diagnostics"])
    assert len(result.payload["component_stock_rows"]) == len(baseline)
    assert evidence.requested_symbol_count == evidence.returned_row_count == evidence.eligible_stock_row_count == 1100
    assert evidence.batch_count == 12
    assert evidence.actual_trade_price_count == 1048
    assert evidence.missing_z_count == 84  # Original scan: 64 traded missing + 20 no-trade.
    assert evidence.scan_start_code == evidence.scan_next_code == CODES[0]
    assert evidence.verified_no_trade_count == 20
    assert evidence.rescue.candidate_count == 64
    assert evidence.rescue.attempted_count == evidence.rescue.succeeded_count == 32
    assert evidence.rescue.skipped_count == 32
    assert evidence.rescue.skip_reasons == {"RESCUE_SKIPPED_SYMBOL_CAP": 32}
    assert calls[-1][1] == pytest.approx(0.816)
    assert evidence.budget_elapsed_seconds == pytest.approx(19.684)
    assert evidence.scan_budget_seconds == 20
    assert evidence.total_hard_deadline_seconds is None
    assert evidence.total_ceiling_seconds == 22
    assert evidence.finalization_allowance_seconds == 2
    assert evidence.rescue_max_budget_seconds == 4
    assert not evidence.deadline_exceeded
    assert evidence.batches[0].missing_examples[0]["z"] == "-"
    assert evidence.batches[-1].actual_z == 32
    assert sum(len(batch.missing_examples) for batch in evidence.batches) <= 36
    assert "msgArray" not in evidence.model_dump_json()
    assert evidence.batches[0].receipt_at == NOW + timedelta(seconds=1.744)
    assert evidence.batches[0].event_min == NOW


@pytest.mark.parametrize("preparation_seconds", [0, 0.25])
def test_near_deadline_rescue_timeout_never_reduces_primary_coverage(clock, monkeypatch, preparation_seconds):
    class Cache(dict):
        def setdefault(self, *args):
            clock.seconds += preparation_seconds
            return super().setdefault(*args)

    monkeypatch.setattr(provider, "_CACHE", Cache())
    calls = []
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages",
                        fake_fetch(clock, calls, rescue_duration=4))
    result = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: CODES)
    evidence = result.payload["acquisition_diagnostics"]
    assert evidence["eligible_stock_row_count"] == 1100
    assert evidence["budget_elapsed_seconds"] == pytest.approx(20)
    assert evidence["rescue"]["failed_count"] == 32
    assert evidence["batches"][-1]["timeout"]
    assert result.payload["component_stock_rows"][0]["current_price"] is None
    assert len(calls) == 12


def test_exhausted_budget_skip_is_explicit_and_partial_scan_still_can_rescue(clock, monkeypatch):
    raw = provider._build_payload("TWSE", CODES, [dict(message(code), z="-") for code in CODES], 1)
    raw.update(failed_batch_count=1, skipped_batch_count=1)
    evidence = {}
    result, calls = provider._rescue_missing_z("TWSE", CODES, [], raw, prior_states=None,
                                               remaining_seconds=0, evidence=evidence)
    assert calls == 0
    assert evidence["rescue"]["skip_reasons"] == {"RESCUE_SKIPPED_BUDGET": 1100}
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", lambda codes, **kw: [message(c) for c in codes])
    result, calls = provider._rescue_missing_z("TWSE", CODES, [], raw, prior_states=None,
                                               remaining_seconds=0.8, evidence=evidence)
    assert calls == 1 and evidence["rescue"]["succeeded_count"] == 32
    assert result["failed_batch_count"] == result["skipped_batch_count"] == 1
    assert result["status"] == "partial" and not result["decision_usable"]


@pytest.mark.parametrize("failure", ["timeout", "rate_limit"])
def test_fractional_rescue_failure_has_one_attempt_then_backoff(clock, monkeypatch, failure):
    calls = []
    def fail(codes, *, timeout_seconds, **kwargs):
        calls.append(timeout_seconds)
        assert 0 < timeout_seconds <= 0.8
        if failure == "timeout":
            clock.seconds += timeout_seconds
            raise TimeoutError("fractional rescue deadline")
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError(response=response)

    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fail)
    raw = provider._build_payload("TWSE", CODES[:100], [dict(message(c), z="-") for c in CODES[:100]], 0)
    evidence = {}
    result, count = provider._rescue_missing_z("TWSE", CODES[:100], [], raw, prior_states=None,
                                               remaining_seconds=0.8, evidence=evidence)
    assert count == len(calls) == 1
    assert clock.seconds <= 0.8
    assert result["missing_z_rescue"]["status"] == "blocked"
    assert result["missing_z_rescue"]["batch_failures"][0]["reason"] == ("timeout" if failure == "timeout" else "rate_limited")
    assert evidence["rescue"]["failed_count"] == 32
    assert evidence["rescue"]["succeeded_count"] == 0
    repeated = {}
    _, count = provider._rescue_missing_z("TWSE", CODES[:100], [], raw, prior_states=None,
                                          remaining_seconds=0.8, evidence=repeated)
    assert count == 0 and len(calls) == 1
    assert repeated["rescue"]["skip_reasons"] == {"RESCUE_SKIPPED_BACKOFF": 100}


def test_receipt_persistence_inspect_and_outward_reference_are_read_only(clock, monkeypatch):
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fake_fetch(clock, []))
    produced = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: CODES)
    db, engine = _db()
    try:
        result = acquire(db, produced.payload, NOW + timedelta(seconds=20))
        raw = db.query(RawFetchResult).order_by(RawFetchResult.id.desc()).first()
        assert raw is not None
        stored = json.loads(raw.raw_text)["acquisition_diagnostics"]
        assert stored["acquisition_id"] == produced.payload["acquisition_diagnostics"]["acquisition_id"]
        outward = result.resolved.breadth.acquisition_diagnostics.model_dump()
        assert outward["receipt_evidence_id"] == stored["acquisition_id"]
        assert "batches" not in outward
        # Pending invalid WIP must not autoflush from inspection.
        db.add(SourceRegistry(source_name="pending-evidence-inspect"))
        statements = []
        event.listen(engine, "before_cursor_execute", lambda c, cur, stmt, *args: statements.append(stmt))
        inspected = inspect_breadth_acquisition_receipt(db, raw_result_id=raw.id)
        assert inspected["raw_result_id"] == raw.id
        assert inspected["content_hash"] == raw.content_hash
        assert inspected["raw_receipt_id"] == f"raw_fetch_result:{raw.id}"
        assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        assert inspect_breadth_acquisition_receipt(db, raw_result_id=999999) is None
    finally:
        db.close()
        engine.dispose()


def test_socket_timeout_is_not_wall_bound_and_slots_are_bounded_isolated_resettable():
    entered, release, completed = Event(), Event(), Event()

    def stuck(*args, **kwargs):
        # Deterministic model of a request still reading despite socket timeout.
        entered.set()
        release.wait(2)
        completed.set()
        return ["late"]

    start = monotonic()
    try:
        with pytest.raises(TimeoutError, match="ACQUISITION_DEADLINE"):
            io.bounded_fetch(stuck, 0.02, exchange="tse", timeout_seconds=0.02)
        assert entered.is_set() and not completed.is_set()
        assert monotonic() - start < 0.5
        slot = io._IN_FLIGHT["tse"]
        for _ in range(5):
            with pytest.raises(io.AcquisitionInFlight):
                io.bounded_fetch(stuck, 0.02, exchange="tse")
        assert io._IN_FLIGHT["tse"] is slot
        with pytest.raises(io.AcquisitionInFlight, match="RESET_REQUIRES_IDLE"):
            io.reset_io_slots()
        assert io.bounded_fetch(lambda **kw: ["otc"], 0.1, exchange="otc") == ["otc"]
        assert len(io._IN_FLIGHT) == 2
    finally:
        release.set()
        assert completed.wait(1)
        io._IN_FLIGHT["tse"].result(timeout=1)
    assert io.bounded_fetch(lambda **kw: ["recovered"], 0.1, exchange="tse") == ["recovered"]
    io.reset_io_slots()
    assert not io._IN_FLIGHT


def test_late_transport_cannot_modify_cache_guard_or_publish_rows(monkeypatch):
    release, completed = Event(), Event()

    def delayed(*args, **kwargs):
        release.wait(2)
        completed.set()
        return [message("6442")]

    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", delayed)
    try:
        evidence = {}
        rows, failed, calls = provider._fetch_messages(["6442"], "TWSE", 0.02, diagnostics=evidence)
        assert rows == [] and failed == calls == 1
        guard = provider.TWSE_MIS_PROVIDER_GUARD.snapshot()
        more = {}
        assert provider._fetch_messages(["6442"], "TWSE", 1, diagnostics=more) == ([], 0, 0)
        assert more["batches"][0]["error"] == "transport_in_flight"
        assert not more["batches"][0]["attempted"]
    finally:
        release.set()
        assert completed.wait(1)
        io._IN_FLIGHT["tse"].result(timeout=1)
    assert not provider._CACHE and not provider._STOCK_ROWS
    assert provider.TWSE_MIS_PROVIDER_GUARD.snapshot() == guard
    assert evidence["batches"][0]["returned"] == 0


@pytest.mark.parametrize("market", ["TWSE", "TPEX"])
def test_truncated_scan_rotates_across_refreshes_without_merging_old_rows(clock, monkeypatch, market):
    codes = CODES[:600]
    starts = []
    def slow(batch, *, timeout_seconds, **kwargs):
        starts.append(batch[0])
        duration = 1.5
        clock.seconds += min(duration, timeout_seconds)
        if duration > timeout_seconds:
            raise TimeoutError("fixture vendor latency")
        return [message(code) for code in batch]
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", slow)
    observed = set()
    for expected_start, next_start in ((codes[0], codes[200]), (codes[200], codes[400]), (codes[400], codes[0])):
        began = clock.seconds
        result = provider.read_twse_mis_current_breadth(market, 4, universe_reader=lambda _: codes)
        assert clock.seconds - began <= 4
        assert result.external_calls == 3
        assert result.status == "partial"
        diag = result.payload["acquisition_diagnostics"]
        assert diag["scan_start_code"] == expected_start
        assert diag["scan_next_code"] == next_start
        assert diag["requested_symbol_count"] == 300
        assert result.payload["message_count"] == 200
        assert result.payload["not_received_count"] == 400
        assert result.payload["skipped_batch_count"] == 3
        current = {row["code"] for row in provider.get_cached_current_breadth_stock_rows(market)}
        assert len(current) == 200 and not (current & observed)
        observed |= current
        # A cache hit performs no IO and does not advance scan scheduling.
        cached = provider.read_twse_mis_current_breadth(market, 4, universe_reader=lambda _: codes)
        assert cached.external_calls == 0
        provider._CACHE[market]["expires_at"] = 0
    assert observed == set(codes)
    assert starts == [codes[0], codes[100], codes[200], codes[200], codes[300], codes[400], codes[400], codes[500], codes[0]]


@pytest.mark.parametrize("market", ["TWSE", "TPEX"])
@pytest.mark.parametrize("digest_seconds,exceeded", [(0.1, False), (1.0, False), (3.0, True)])
def test_timely_batch_survives_digest_tail_and_never_starts_io_after_scan_budget(
    clock, monkeypatch, market, digest_seconds, exceeded,
):
    calls = []
    def fetch(codes, **kwargs):
        calls.append(clock.seconds)
        clock.seconds += 19.8
        return [message(code) for code in codes]
    digest = provider.original_message_evidence
    def slow_digest(*args):
        clock.seconds += digest_seconds
        return digest(*args)
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fetch)
    monkeypatch.setattr(provider, "original_message_evidence", slow_digest)
    # Fast finalization still leaves a fractional allocation; the next IO fails
    # honestly rather than completing another 19.8 seconds outside its budget.
    def bounded(fetcher, seconds, *args, **kwargs):
        if seconds < 19.8:
            calls.append(clock.seconds)
            clock.seconds += seconds
            raise TimeoutError("fixture bounded IO")
        return fetcher(*args, **kwargs)
    monkeypatch.setattr(provider, "bounded_fetch", bounded)
    outcome = provider.read_twse_mis_current_breadth(market, 20, universe_reader=lambda _: CODES)
    receipt = BreadthAcquisitionEvidence.model_validate(outcome.payload["acquisition_diagnostics"])
    assert receipt.eligible_stock_row_count == 100
    assert outcome.payload["message_count"] == 100 and outcome.payload["not_received_count"] == 1000
    assert outcome.status == "partial" and not outcome.payload["decision_usable"]
    assert all(start < 20 for start in calls)
    assert receipt.batches[0].fetch_completed_in_budget
    assert receipt.batches[0].fetch_decode_seconds == pytest.approx(19.8)
    assert receipt.batches[0].digest_seconds == pytest.approx(digest_seconds)
    assert receipt.batches[0].error is None
    assert receipt.total_elapsed_seconds == pytest.approx(max(20, 19.8 + digest_seconds))
    assert receipt.deadline_exceeded is exceeded
    assert receipt.total_hard_deadline_seconds is None
    assert receipt.timing_policy == "bounded_io_cooperative_finalization"
    assert receipt.phase_seconds["scan"] == pytest.approx(receipt.total_elapsed_seconds)
    assert set(receipt.phase_seconds) == {"preparation", "scan", "payload_build", "rescue", "receipt_finalization"}
    assert receipt.scan_next_code == CODES[100]
    if exceeded:
        assert outcome.detail_code == "TWSE_MIS_FINALIZATION_CEILING_EXCEEDED"


def test_receipt_finalization_itself_is_measured(clock, monkeypatch):
    original_dump = BreadthAcquisitionEvidence.model_dump
    def slow_dump(self, *args, **kwargs):
        clock.seconds += 3
        return original_dump(self, *args, **kwargs)
    monkeypatch.setattr(BreadthAcquisitionEvidence, "model_dump", slow_dump)
    receipt = provider._finish_acquisition({}, market="TWSE", codes=[], payload=None,
        started=0, started_wall=NOW, timeout_seconds=20, acquisition_id="synthetic")
    assert receipt["total_elapsed_seconds"] == 3
    assert receipt["phase_seconds"]["receipt_finalization"] == 3
    assert receipt["finished_at"] == (NOW + timedelta(seconds=3)).isoformat()


def test_transport_and_json_decode_clocks_are_separate(clock, monkeypatch):
    monkeypatch.setattr(provider.twse_mis, "monotonic", lambda: clock.seconds)
    def request(*args, **kwargs):
        clock.seconds += 1
        return object()
    def decode(_response):
        clock.seconds += 2
        return {"rtcode": "0000", "msgArray": [message("6000")]}
    monkeypatch.setattr(provider.twse_mis, "json_from_response", decode)
    timing = {}
    rows = provider.twse_mis.fetch_stock_messages(["6000"], request=request, phase_timing=timing)
    assert len(rows) == 1 and timing == {"transport_seconds": 1, "decode_seconds": 2}


def test_decode_exception_is_not_a_transport_success(clock, monkeypatch):
    def malformed(*args, **kwargs):
        clock.seconds += 0.2
        raise ValueError("invalid JSON fixture")
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", malformed)
    diag = {}
    rows, failed, calls = provider._fetch_messages(CODES[:100], "TWSE", 20, diagnostics=diag)
    assert rows == [] and failed == calls == 1
    assert diag["batches"][0]["error"] == "parse_error"
    assert diag["batches"][0]["fetch_decode_seconds"] == pytest.approx(0.2)


@pytest.mark.parametrize("market", ["TWSE", "TPEX"])
def test_all_batches_succeed_but_payload_finalization_overrun_is_partial(clock, monkeypatch, market):
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", lambda codes, **_: [message(c) for c in codes])
    build = provider._build_payload
    def slow_build(*args, **kwargs):
        value = build(*args, **kwargs)
        clock.seconds += 23
        return value
    monkeypatch.setattr(provider, "_build_payload", slow_build)
    result = provider.read_twse_mis_current_breadth(market, 20, universe_reader=lambda _: CODES)
    receipt = result.payload["acquisition_diagnostics"]
    assert result.status == result.payload["status"] == "partial"
    assert result.operational_status.value == "degraded"
    assert result.external_calls == 11 and result.payload["failed_batch_count"] == 0
    assert result.payload["message_count"] == 1100
    assert receipt["eligible_stock_row_count"] == receipt["universe_count"] == 1100
    assert not result.payload["decision_usable"] and receipt["deadline_exceeded"]
    assert receipt["total_elapsed_seconds"] == 23 and receipt["phase_seconds"]["payload_build"] == 23
    assert market not in provider._LAST_GOOD
