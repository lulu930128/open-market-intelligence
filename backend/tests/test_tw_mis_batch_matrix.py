"""Synthetic cost models test safety, not production latency or tuning gains."""
from copy import deepcopy
from threading import Event

import pytest

from test_tw_breadth_acquisition_evidence import CODES, clock, offline, message, provider, io


@pytest.mark.parametrize("batch_size", [20, 40, 60, 100])
@pytest.mark.parametrize("model", ["per_call", "per_symbol", "slow_prefix"])
def test_scan_matrix_bounds_quota_and_rotates_to_unvisited_tail(clock, monkeypatch, batch_size, model):
    monkeypatch.setattr(provider, "_BATCH_SIZE", batch_size)
    codes = CODES[:600]
    seen, calls = set(), []
    def fetch(batch, *, timeout_seconds, **kwargs):
        assert 0 < timeout_seconds <= provider._BATCH_MAX_WAIT_SECONDS
        assert len(batch) <= batch_size
        calls.append(list(batch))
        cost = 1.0 if model == "per_call" else len(batch) * .025
        if model == "slow_prefix" and codes[0] in batch:
            cost = 8.0
        clock.seconds += min(cost, timeout_seconds)
        if cost > timeout_seconds:
            raise TimeoutError("synthetic bounded transport timeout")
        seen.update(batch)
        return [message(code) for code in batch]
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fetch)
    cursor = codes[0]
    for _ in range(4):
        start = clock.seconds
        offset = codes.index(cursor)
        rotated = codes[offset:] + codes[:offset]
        diagnostics = {}
        before = len(calls)
        rows, failed, attempts = provider._fetch_messages(rotated, "TWSE", 20, diagnostics=diagnostics)
        assert clock.seconds - start <= 20 + 1e-8
        assert attempts == len(calls) - before == diagnostics["attempted_batch_count"]
        flattened = [code for batch in calls[before:] for code in batch]
        assert len(flattened) == len(set(flattened))
        assert len(rows) <= len(flattened)
        assert failed == diagnostics["failed_batch_count"]
        cursor = diagnostics["scan_next_code"]
    expected = set(codes[batch_size:] if model == "slow_prefix" else codes)
    assert expected <= seen  # A slow prefix cannot starve the tail.


@pytest.mark.parametrize("batch_size", [20, 40, 60, 100])
def test_caller_timeout_keeps_venue_slot_and_does_not_publish_late_result(clock, monkeypatch, batch_size):
    monkeypatch.setattr(provider, "_BATCH_SIZE", batch_size)
    monkeypatch.setattr(io, "monotonic", lambda: clock.seconds)
    entered, release = Event(), Event()
    calls = []
    def fetch(batch, **kwargs):
        calls.append((list(batch), kwargs["exchange"]))
        if kwargs["exchange"] == "tse":
            entered.set()
            assert release.wait(5)
        return [message(code) for code in batch]
    original_wait = io.wait
    def expire(futures, timeout):
        assert entered.wait(2)
        clock.seconds += timeout
        return set(), set(futures)
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fetch)
    monkeypatch.setattr(io, "wait", expire)
    diagnostics, blocked = {}, {}
    try:
        assert provider._fetch_messages(CODES[:batch_size * 3], "TWSE", 20, diagnostics=diagnostics) == ([], 1, 1)
        assert diagnostics["scan_next_code"] == CODES[batch_size]
        assert clock.seconds == provider._BATCH_MAX_WAIT_SECONDS
        assert provider._fetch_messages(CODES[batch_size:batch_size * 3], "TWSE", 20, diagnostics=blocked) == ([], 0, 0)
        assert blocked["scan_next_code"] == CODES[batch_size]
        assert all(not batch["attempted"] for batch in blocked["batches"])
        monkeypatch.setattr(io, "wait", original_wait)
        assert len(io.bounded_fetch(fetch, 1, ["6488"], exchange="otc")) == 1
        published = deepcopy(diagnostics)
        guard = provider.TWSE_MIS_PROVIDER_GUARD.snapshot()
    finally:
        release.set()
        io._IN_FLIGHT["tse"].result(timeout=2)
    assert len(calls) == 2
    assert diagnostics == published
    assert provider.TWSE_MIS_PROVIDER_GUARD.snapshot() == guard
    assert not provider._CACHE and not provider._STOCK_ROWS
