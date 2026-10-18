"""G8-1 offline timing receipts; deterministic clocks and caller/worker barriers."""
from copy import deepcopy
from threading import Event, get_ident

import pytest
import requests
from pydantic import ValidationError

from app.observability import provider_http
from app.market.providers import twse_mis_breadth_evidence as io
from app.market.tw_breadth_acquisition_contract import AcquisitionBatchEvidence, BreadthAcquisitionEvidence
from test_tw_breadth_acquisition_evidence import CODES, clock, offline, message, provider


def batch_receipts(diagnostics):
    return [AcquisitionBatchEvidence.model_validate(batch).model_dump()
            for batch in diagnostics["batches"]]


@pytest.mark.parametrize("market", ["TWSE", "TPEX"])
@pytest.mark.parametrize("phase", ["scan", "rescue"])
def test_start_budget_precedes_admission_and_wait_excludes_classification(clock, monkeypatch, market, phase):
    before_request = provider.TWSE_MIS_PROVIDER_GUARD.before_request
    classify = provider._classify_message
    calls = []

    def admission():
        clock.seconds += 0.5
        return before_request()

    def fetch(codes, **kwargs):
        calls.append((codes, kwargs["exchange"], kwargs["timeout_seconds"]))
        clock.seconds += 0.25
        kwargs["phase_timing"].update(transport_seconds=0.2, decode_seconds=0.05)
        return [message(codes[0])]

    def classification(*args, **kwargs):
        clock.seconds += 0.75
        return classify(*args, **kwargs)

    monkeypatch.setattr(provider.TWSE_MIS_PROVIDER_GUARD, "before_request", admission)
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fetch)
    monkeypatch.setattr(provider, "_classify_message", classification)
    diagnostics = {}
    rows, failed, count = provider._fetch_messages(["2330"], market, 20, phase=phase, diagnostics=diagnostics)
    batch = batch_receipts(diagnostics)[0]
    assert (len(rows), failed, count) == (1, 0, 1)
    assert calls == [(["2330"], "otc" if market == "TPEX" else "tse", 19.5)]
    assert batch["remaining_budget_at_start_seconds"] == 20
    assert batch["caller_wait_seconds"] == 0.25
    assert batch["classification_seconds"] == 0.75
    assert batch["duration_ms"] == 1500


@pytest.mark.parametrize("deadline", [0, -1])
def test_expired_initial_budget_clamps_all_skipped_batches(clock, monkeypatch, deadline):
    def forbidden(*args, **kwargs):
        pytest.fail("expired scan cannot start IO")

    monkeypatch.setattr(provider, "bounded_fetch", forbidden)
    diagnostics = {}
    assert provider._fetch_messages(CODES[:200], "TWSE", 20, deadline=deadline,
                                    diagnostics=diagnostics) == ([], 0, 0)
    assert diagnostics["skipped_batch_count"] == 2
    for batch in batch_receipts(diagnostics):
        assert batch["remaining_budget_at_start_seconds"] == 0
        assert batch["caller_wait_seconds"] is None
        assert not batch["attempted"] and batch["error"] == "budget_exhausted"


@pytest.mark.parametrize("exception,stage", [(requests.ConnectTimeout, "connect"), (requests.ReadTimeout, "read")])
def test_wrapped_provider_timeout_wait_excludes_exception_handling(clock, monkeypatch, exception, stage):
    normalize = provider.provider_http_failure
    calls = []

    def transport(*args, **kwargs):
        calls.append(kwargs["timeout"])
        clock.seconds += 0.25
        raise exception("synthetic only")

    def handling(exc):
        clock.seconds += 0.5
        return normalize(exc)

    monkeypatch.setattr(provider.twse_mis, "monotonic", lambda: clock.seconds)
    monkeypatch.setattr(provider_http.http_client, "request", transport)
    monkeypatch.setattr(provider, "provider_http_failure", handling)
    diagnostics = {}
    assert provider._fetch_messages(["2330"], "TWSE", 20, diagnostics=diagnostics) == ([], 1, 1)
    batch = batch_receipts(diagnostics)[0]
    assert calls == [20]
    assert batch["remaining_budget_at_start_seconds"] == 20
    assert batch["caller_wait_seconds"] == batch["transport_seconds"] == 0.25
    assert batch["timeout_origin"] == "provider" and batch["timeout_stage"] == stage
    assert batch["duration_ms"] == 750


def test_caller_deadline_and_inflight_skip_cannot_publish_late_worker_timing(clock, monkeypatch):
    entered, release = Event(), Event()
    caller = get_ident()
    calls = []

    def stuck(*args, **kwargs):
        calls.append(get_ident())
        entered.set()
        assert release.wait(5)
        kwargs["phase_timing"].update(transport_seconds=99, decode_seconds=2)
        return [message("2330")]

    def exhausted_wait(futures, timeout):
        assert get_ident() == caller
        assert entered.wait(2)
        clock.seconds += 20
        return set(), set(futures)

    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", stuck)
    monkeypatch.setattr(io, "wait", exhausted_wait)
    diagnostics, blocked = {}, {}
    try:
        assert provider._fetch_messages(CODES[:200], "TWSE", 20, diagnostics=diagnostics) == ([], 1, 1)
        first, skipped = batch_receipts(diagnostics)
        assert first["remaining_budget_at_start_seconds"] == first["caller_wait_seconds"] == 20
        assert first["timeout_origin"] == "acquisition_deadline"
        assert first["timeout_stage"] is first["transport_seconds"] is first["decode_seconds"] is None
        assert skipped["remaining_budget_at_start_seconds"] == 0
        assert skipped["caller_wait_seconds"] is None
        assert diagnostics["scan_next_code"] == CODES[100]
        assert provider._fetch_messages(["2330"], "TWSE", 20, diagnostics=blocked) == ([], 0, 0)
        inflight = batch_receipts(blocked)[0]
        assert inflight["error"] == "transport_in_flight" and not inflight["attempted"]
        assert inflight["remaining_budget_at_start_seconds"] == 20
        assert inflight["caller_wait_seconds"] is None
        published = deepcopy(diagnostics)
        guard = provider.TWSE_MIS_PROVIDER_GUARD.snapshot()
    finally:
        release.set()
        io._IN_FLIGHT["tse"].result(timeout=2)
    assert len(calls) == 1 and calls[0] != caller
    assert diagnostics == published
    assert provider.TWSE_MIS_PROVIDER_GUARD.snapshot() == guard
    assert not provider._CACHE and not provider._STOCK_ROWS


def test_429_then_guard_open_keep_budget_but_no_wait_for_skipped_slots(clock, monkeypatch):
    calls = []

    def limited(*args, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        clock.seconds += 0.25
        response = requests.Response()
        response.status_code = 429
        response.headers["Retry-After"] = "60"
        raise requests.HTTPError(response=response)

    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", limited)
    diagnostics, blocked = {}, {}
    assert provider._fetch_messages(CODES[:300], "TWSE", 20, diagnostics=diagnostics) == ([], 1, 1)
    first, *skipped = batch_receipts(diagnostics)
    assert first["remaining_budget_at_start_seconds"] == 20
    assert first["caller_wait_seconds"] == 0.25 and first["error"] == "rate_limited"
    assert diagnostics["skipped_batch_count"] == 2
    assert diagnostics["scan_next_code"] == CODES[100]
    assert provider._fetch_messages(["2330"], "TWSE", 20, diagnostics=blocked) == ([], 0, 0)
    for batch in skipped + batch_receipts(blocked):
        assert batch["caller_wait_seconds"] is None
        assert not batch["attempted"] and batch["error"] == "guard_open"
    assert [batch["remaining_budget_at_start_seconds"] for batch in skipped] == [19.75, 19.75]
    assert batch_receipts(blocked)[0]["remaining_budget_at_start_seconds"] == 20
    assert calls == [20]


def test_new_receipt_and_old_missing_keys_roundtrip_same_version(clock, monkeypatch):
    calls = []

    def fetch(codes, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        clock.seconds += 1
        return [message(code) for code in codes]

    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fetch)
    result = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: CODES[:500])
    raw = result.payload["acquisition_diagnostics"]
    receipt = BreadthAcquisitionEvidence.model_validate(raw)
    assert receipt.version == "tw.mis.breadth.acquisition.v1"
    assert calls == [20, 19, 18, 17, 16]
    assert [batch.remaining_budget_at_start_seconds for batch in receipt.batches] == calls
    assert [batch.caller_wait_seconds for batch in receipt.batches] == [1] * 5
    assert receipt.scan_budget_seconds == 20 and receipt.finalization_allowance_seconds == 2
    assert receipt.total_ceiling_seconds == 22
    old = deepcopy(raw)
    for batch in old["batches"]:
        del batch["remaining_budget_at_start_seconds"]
        del batch["caller_wait_seconds"]
    decoded = BreadthAcquisitionEvidence.model_validate(old)
    assert decoded.version == receipt.version
    for batch in decoded.batches:
        assert batch.remaining_budget_at_start_seconds is batch.caller_wait_seconds is None
    for field in ("remaining_budget_at_start_seconds", "caller_wait_seconds"):
        with pytest.raises(ValidationError):
            AcquisitionBatchEvidence.model_validate({**raw["batches"][0], field: -0.1})
