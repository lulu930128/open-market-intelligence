"""Keep rotating bounded scan admission when an early batch fails."""
import pytest

from test_tw_breadth_acquisition_evidence import clock, offline, message, CODES, provider


@pytest.mark.parametrize("market", ["TWSE", "TPEX"])
def test_early_failed_prefix_cannot_starve_unattempted_tail(clock, monkeypatch, market):
    codes = CODES[:600]
    starts = []

    def fetch(batch, *, timeout_seconds, **kwargs):
        starts.append(batch[0])
        if batch[0] == codes[0]:
            clock.seconds += 0.1
            raise ValueError("synthetic malformed prefix")
        clock.seconds += min(1.5, timeout_seconds)
        if timeout_seconds < 1.5:
            raise TimeoutError("synthetic scan deadline")
        return [message(code) for code in batch]

    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fetch)
    observed = set()
    round_starts = []
    for _ in range(4):
        began = clock.seconds
        result = provider.read_twse_mis_current_breadth(market, 4, universe_reader=lambda _: codes)
        receipt = result.payload["acquisition_diagnostics"]
        round_starts.append(receipt["scan_start_code"])
        assert clock.seconds - began <= 4
        assert receipt["universe_count"] == 600
        assert result.payload["message_count"] < 600
        assert result.status == "partial"
        rows = provider.get_cached_current_breadth_stock_rows(market)
        assert result.payload["not_received_count"] == 600 - len(rows)
        observed.update(row["code"] for row in rows)
        provider._CACHE[market]["expires_at"] = 0
    assert codes[500] in observed
    assert len(set(round_starts)) > 1
    assert not (set(codes[:100]) & observed)
