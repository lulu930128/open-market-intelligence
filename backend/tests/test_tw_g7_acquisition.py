"""Offline G7: preserve timeout identity, evidence and bounded provider ownership."""
from threading import Event

import pytest
import requests

from app.observability import provider_http
from app.market.providers import twse_mis_breadth_evidence as io
from app.market.tw_breadth_acquisition_contract import AcquisitionBatchEvidence
from test_tw_breadth_acquisition_evidence import clock, offline, message, provider


@pytest.mark.parametrize("market", ["TWSE", "TPEX"])
@pytest.mark.parametrize("exception,stage", [(requests.ConnectTimeout, "connect"), (requests.ReadTimeout, "read")])
def test_wrapped_provider_timeout_remains_timeout_with_completed_transport_timing(clock, monkeypatch, market, exception, stage):
    calls = []
    monkeypatch.setattr(provider.twse_mis, "monotonic", lambda: clock.seconds)

    def transport(*args, **kwargs):
        calls.append(kwargs["timeout"])
        clock.seconds += 0.25
        raise exception("synthetic only")

    monkeypatch.setattr(provider_http.http_client, "request", transport)
    diagnostics = {}
    assert provider._fetch_messages(["2330"], market, 20, diagnostics=diagnostics) == ([], 1, 1)
    assert calls == [20]
    batch = AcquisitionBatchEvidence.model_validate(diagnostics["batches"][0]).model_dump()
    assert batch["error"] == "timeout"  # Before G7: transport_error
    assert batch["timeout"] is True
    assert batch["timeout_origin"] == "provider"
    assert batch["timeout_stage"] == stage
    assert batch["transport_seconds"] == pytest.approx(0.25)
    assert batch["decode_seconds"] is None
    assert batch["returned"] == batch["actual_z"] == 0
    assert diagnostics["batch_failures"][0]["http_status"] is None
    # Existing guard policy: one failure stays allowed; three open cooldown.
    assert provider.TWSE_MIS_PROVIDER_GUARD.snapshot().allowed
    for _ in range(2):
        provider._fetch_messages(["2330"], market, 20)
    assert not provider.TWSE_MIS_PROVIDER_GUARD.snapshot().allowed
    assert provider._fetch_messages(["2330"], market, 20) == ([], 0, 0)
    assert len(calls) == 3


def test_worker_timeout_is_not_rewritten_as_caller_deadline():
    original = TimeoutError("worker socket failure")

    def fail(**kwargs):
        raise original

    with pytest.raises(TimeoutError) as caught:
        io.bounded_fetch(fail, 1, exchange="tse")
    assert caught.value is original


def test_deadline_receipt_does_not_claim_socket_timeout_or_admit_late_result(monkeypatch):
    release = Event()

    def stuck(*args, **kwargs):
        assert release.wait(2)
        kwargs["phase_timing"]["transport_seconds"] = 1.0
        return [message("2330")]

    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", stuck)
    diagnostics = {}
    try:
        assert provider._fetch_messages(["2330"], "TWSE", 0.02, diagnostics=diagnostics) == ([], 1, 1)
        batch = AcquisitionBatchEvidence.model_validate(diagnostics["batches"][0]).model_dump()
        assert batch["timeout_origin"] == "acquisition_deadline"
        assert batch["timeout_stage"] is None and batch["transport_seconds"] is None
        assert provider._fetch_messages(["2330"], "TWSE", 1) == ([], 0, 0)
        guard = provider.TWSE_MIS_PROVIDER_GUARD.snapshot()
    finally:
        release.set()
        io._IN_FLIGHT["tse"].result(timeout=1)
    assert diagnostics["batches"][0].get("transport_seconds") is None
    assert diagnostics["batches"][0]["returned"] == 0
    assert provider.TWSE_MIS_PROVIDER_GUARD.snapshot() == guard
    assert not provider._CACHE and not provider._STOCK_ROWS


@pytest.mark.parametrize("z,ts", [("-", "0"), ("NaN", "0"), ("110", "1")])
def test_missing_invalid_or_trial_z_never_promotes_alternatives(z, ts):
    row = message("2330")
    row.update(z=z, ts=ts, pz="999", a="112_", b="108_", trade={"z": "111"})
    classified = provider._classify_message(row, "TWSE")
    assert classified["current_price"] is None
    assert classified["direction"] is None
    assert not classified["has_actual_trade"]
