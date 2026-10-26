"""Offline replay of timeout/cursor and positive-volume missing-z shapes."""
import pytest

from app.market.providers.twse_mis_breadth_evidence import AcquisitionDeadlineExceeded
from test_tw_breadth_acquisition_evidence import clock, offline, message, provider


def test_seventh_batch_deadline_preserves_quota_and_next_round_cursor(clock, monkeypatch):
    codes = [str(1000 + i) for i in range(1080)]
    calls = []

    def fetch(function, remaining, batch, **kwargs):
        calls.append(list(batch))
        if len(calls) == 7:
            clock.seconds += remaining
            raise AcquisitionDeadlineExceeded("TWSE_MIS_ACQUISITION_DEADLINE")
        clock.seconds += 3
        return [message(code) for code in batch]

    monkeypatch.setattr(provider, "bounded_fetch", fetch)
    evidence = {}
    rows, failed, attempts = provider._fetch_messages(codes, "TWSE", 20, diagnostics=evidence)
    assert (len(rows), failed, attempts) == (600, 1, 7)
    assert evidence["skipped_batch_count"] == 4
    assert len(calls) == 7 and clock.seconds == 20
    assert evidence["scan_next_code"] == codes[600]
    assert evidence["batches"][6]["timeout_origin"] == "acquisition_deadline"
    assert evidence["batches"][6]["timeout_stage"] is None
    assert all(not batch["attempted"] for batch in evidence["batches"][7:])
    calls.clear()
    monkeypatch.setattr(provider, "bounded_fetch", lambda function, remaining, batch, **kw:
                        calls.append(list(batch)) or [message(code) for code in batch])
    rotated = codes[600:] + codes[:600]
    rows, failed, attempts = provider._fetch_messages(rotated, "TWSE", 20)
    assert (len(rows), failed, attempts) == (1080, 0, 11)
    assert calls[0][0] == codes[600]


@pytest.mark.parametrize("volume", [1, 45, 3756])
def test_received_positive_volume_without_z_does_not_become_directional(volume):
    raw = message("3406")
    raw.update(z="-", v=str(volume), tv="-", ts="0", pz="1110")
    row = provider._classify_message(raw, "TWSE")
    assert row["current_price"] is None
    assert row["direction"] is None
    assert row["has_actual_trade"] is False


@pytest.mark.parametrize("timeout_batch", [10, 11])
def test_early_live_tail_deadline_keeps_one_round_and_original_budget(clock, monkeypatch, timeout_batch):
    codes = [str(1000 + i) for i in range(1080)]
    calls = []

    def fetch(function, remaining, batch, **kwargs):
        calls.append(tuple(batch))
        assert kwargs["timeout_seconds"] <= remaining
        if len(calls) == timeout_batch:
            clock.seconds += remaining
            raise AcquisitionDeadlineExceeded("TWSE_MIS_ACQUISITION_DEADLINE")
        clock.seconds += 1.5
        return [message(code) for code in batch]

    monkeypatch.setattr(provider, "bounded_fetch", fetch)
    evidence = {}
    rows, failed, attempts = provider._fetch_messages(codes, "TWSE", 20, diagnostics=evidence)
    assert clock.seconds == pytest.approx(20)
    assert (len(rows), failed, attempts) == ((timeout_batch - 1) * 100, 1, timeout_batch)
    assert evidence["skipped_batch_count"] == 11 - timeout_batch
    assert evidence["scan_next_code"] == codes[(timeout_batch - 1) * 100]
    assert evidence["batches"][timeout_batch - 1]["timeout_origin"] == "acquisition_deadline"
    for batch in evidence["batches"][timeout_batch:]:
        assert batch["error"] == "budget_exhausted"
        assert not batch["attempted"] and batch["caller_wait_seconds"] is None
    assert len({code for call in calls for code in call}) == sum(map(len, calls))
