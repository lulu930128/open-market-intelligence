"""Receipt coverage, actual-trade cache invariants and bounded refresh rescue."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.market.providers import twse_mis_current_breadth as provider
from app.market.providers.tw_current_market import CurrentBreadthAdapter, CurrentMarketProviderPayload
from app.market.tw_current_market_acquisition import TaiwanCurrentBreadthAcquisitionExecutor
from app.market.tw_current_market_capabilities import TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR, TW_CURRENT_BREADTH_CAPABILITY_ID
from app.market.tw_current_market_platform import refresh_taiwan_current_breadth, read_taiwan_current_breadth, project_taiwan_current_breadth
from app.market.public_quote_repository import read_current_stock_price_states
from app.market_data.contracts import BreadthRescueDiagnostics
from test_tw_current_market_platform import _db, _binding
from test_tw_breadth_convergence import NOW, message


def acquire(db, payload, now=NOW):
    adapter = CurrentBreadthAdapter(
        _binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
        lambda *_: CurrentMarketProviderPayload(payload=payload, status="available", url="https://example.test", external_calls=0),
        clock=lambda: now,
    )
    return refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=now,
        descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,),
        acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)))


@pytest.mark.parametrize("current_volume,cached_volume,reason", [
    ("6", 5, "SESSION_CACHE_VOLUME_INCREASED"),
    ("4", 5, "SESSION_CACHE_VOLUME_DECREASED"),
    ("5", None, "SESSION_CACHE_VOLUME_UNVERIFIED"),
    ("-", 5, "SESSION_CACHE_VOLUME_UNVERIFIED"),
])
def test_cache_rejects_unconfirmed_or_changed_volume(current_volume, cached_volume, reason):
    prior = dict(trade_date=NOW.date(), price=110, price_as_of=NOW,
                 has_actual_trade=True, cumulative_volume_lots=cached_volume)
    payload = provider._build_payload("TWSE", ["2330"],
        [message(t="10:16:00", z="-", v=current_volume)], 0, prior_states={"2330": prior})
    row = payload["component_stock_rows"][0]
    assert row["current_price"] is None
    assert row["price_as_of"] is None
    assert row["cache_rejection_reason"] == reason
    assert payload["classified_count"] == 0
    assert "2330" not in payload["price_states"]
    if current_volume != "-":
        assert payload["coverage_reason_counts"]["actual_trade_unavailable"] == 1


def test_valid_no_trade_preserves_partition_without_acquisition_or_integrity_failure():
    db, engine = _db()
    try:
        raw = provider._build_payload("TWSE", ["2330", "2454"],
            [message(), message("2454", z="-", v="0", tv="0")], 0)
        result = acquire(db, raw)
        assert result.resolved.breadth is not None, result.model_dump()
        assert result.resolved.breadth.state.value == "available"
        projected = project_taiwan_current_breadth(result)
        assert projected["unknown_count"] == projected["valid_no_trade_count"] == 1
        assert projected["unchanged_count"] == 0
        assert projected["observation_received_freshness"] == "current"
        assert projected["observation_coverage_ratio"] == 1
        assert projected["directional_coverage_ratio"] == 0.5
        assert projected["directional_coverage_status"] == "partial"
        assert projected["trade_state_resolution_status"] == "complete"
        assert projected["directional_unavailable_count"] == 0
        assert projected["decision_usable"] is True, projected["resolved_health"]
        assert sum(projected["coverage_reason_counts"].values()) == projected["partition_total"] == 2
        from app.market.schemas import MarketBreadthRead
        outward = MarketBreadthRead.model_validate(projected).model_dump(mode="json")
        for key in ("observation_received_freshness", "last_trade_recency", "valid_no_trade_count",
                    "observation_coverage_count", "directional_coverage_count", "directional_coverage_status",
                    "trade_state_resolution_status", "acquisition_diagnostics"):
            assert outward[key] == projected[key]
        assert "RECEIVED_UNCLASSIFIED" not in projected["limitations"]
        with patch.object(provider, "_fetch_messages", side_effect=AssertionError("read-side fetch")), \
             patch.object(provider, "_rescue_missing_z", side_effect=AssertionError("read-side rescue")):
            reread = project_taiwan_current_breadth(read_taiwan_current_breadth(db, venue="TWSE", requested_at=NOW))
        assert reread["observation_received_freshness"] == "current"
        assert reread["valid_no_trade_count"] == 1
    finally:
        db.close()
        engine.dispose()


def test_all_no_trade_is_current_with_no_trade_recency_not_applicable():
    db, engine = _db()
    try:
        raw = provider._build_payload("TWSE", ["2330"], [message(z="-", v="0", tv="0")], 0)
        projected = project_taiwan_current_breadth(acquire(db, raw))
        assert projected["status"] == "available"
        assert projected["last_trade_recency"] == "not_applicable"
        assert projected["observation_received_freshness"] == "current"
        assert projected["directional_coverage_ratio"] == 0
        assert projected["valid_no_trade_count"] == 1
        assert projected["trade_value"] is None  # No fabricated zero/price.
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("kind", ["missing", "missing_z", "missing_reference", "batch_failure"])
def test_real_gaps_still_degrade_quality_without_fabricating_staleness(kind):
    db, engine = _db()
    try:
        rows = [message()]
        if kind != "missing":
            rows.append(message("2454", **({"z": "-"} if kind == "missing_z" else {"y": "-"} if kind == "missing_reference" else {})))
        raw = provider._build_payload("TWSE", ["2330", "2454"], rows, int(kind == "batch_failure"))
        projected = project_taiwan_current_breadth(acquire(db, raw))
        assert projected["status"] == "partial"
        assert projected["decision_usable"] is False
        assert projected["observation_received_freshness"] == "current"
        assert projected["partition_total"] == 2
        if kind == "missing":
            assert projected["observation_coverage_status"] == "partial"
        else:
            assert projected["observation_coverage_ratio"] == 1
    finally:
        db.close()
        engine.dispose()


def test_confirmed_volume_persists_and_invalidated_price_does_not_resurrect():
    db, engine = _db()
    try:
        acquire(db, provider._build_payload("TWSE", ["2330", "2454"], [message(), message("2454")], 0))
        states = read_current_stock_price_states(db, venue="TWSE", requested_at=NOW)
        original = states["2330"]
        assert original["cumulative_volume_lots"] == 5
        later = NOW + timedelta(minutes=1)
        raw = provider._build_payload("TWSE", ["2330", "2454"],
            [message(z="-", t="10:16:00"), message("2454", t="10:16:00")], 0, prior_states=states)
        acquire(db, raw, later)
        retained = read_current_stock_price_states(db, venue="TWSE", requested_at=later)["2330"]
        assert retained == original
        raw = provider._build_payload("TWSE", ["2330", "2454"],
            [message(z="-", v="6", t="10:17:00"), message("2454", t="10:17:00")], 0, prior_states={"2330": retained})
        acquire(db, raw, later + timedelta(minutes=1))
        assert "2330" not in read_current_stock_price_states(db, venue="TWSE", requested_at=later + timedelta(minutes=1))
    finally:
        db.close()
        engine.dispose()


def test_receipt_after_rescue_io_is_visible_to_refresh_canonical_reread():
    db, engine = _db()
    try:
        received = NOW + timedelta(seconds=3)
        raw = provider._build_payload("TWSE", ["2330"], [message(t="10:15:02")], 0)
        ticks = iter((NOW, received))
        adapter = CurrentBreadthAdapter(
            _binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
            lambda *_: CurrentMarketProviderPayload(payload=raw, status="available", url="https://example.test", external_calls=1),
            clock=lambda: next(ticks),
        )
        result = refresh_taiwan_current_breadth(db, venue="TWSE", requested_at=NOW,
            descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,),
            acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)))
        assert result.resolved.breadth is not None, result.model_dump()
        assert result.resolved.breadth.lineage.received_at == received
        assert result.resolved.breadth.lineage.event_at == NOW + timedelta(seconds=2)
        assert result.resolved.breadth.price_states["2330"].price_as_of == NOW + timedelta(seconds=2)
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def rescue_scope():
    provider.reset_twse_mis_current_breadth_provider()
    codes = [str(6000 + i) for i in range(250)]
    # Mock the clock, not session semantics or actual-trade validation.
    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Clock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    with patch.object(provider, "datetime", Clock):
        yield codes
    provider.reset_twse_mis_current_breadth_provider()


def test_rescue_success_is_bounded_persistable_and_rotates_after_backoff(rescue_scope):
    calls = []
    def fetch(codes, **kwargs):
        calls.append((list(codes), kwargs["timeout_seconds"]))
        return [message(code, z="101" if len(codes) == 32 else "-") for code in codes]
    with patch.object(provider.twse_mis, "fetch_stock_messages", side_effect=fetch):
        first = provider.read_twse_mis_current_breadth("TPEX", 20, universe_reader=lambda _: rescue_scope)
        assert [len(codes) for codes, _ in calls] == [100, 100, 50, 32]
        assert calls[-1][1] <= 4
        assert first.external_calls == 4
        diag = BreadthRescueDiagnostics.model_validate(first.payload["missing_z_rescue"])
        assert diag.status == "complete"
        assert diag.resolved_count == diag.selected_count == 32
        assert first.payload["coverage_reason_counts"]["actual_trade_unavailable"] == 218
        assert first.payload["price_states"]["6000"]["cumulative_volume_lots"] == 5
        db, engine = _db()
        try:
            projected = project_taiwan_current_breadth(acquire(db, first.payload))
            assert projected["acquisition_diagnostics"]["missing_z_rescue"]["resolved_count"] == 32
            assert projected["status"] == "partial"
        finally:
            db.close()
            engine.dispose()
        provider._CACHE["TPEX"]["expires_at"] = 0
        second = provider.read_twse_mis_current_breadth("TPEX", 20, universe_reader=lambda _: rescue_scope)
        assert second.payload["missing_z_rescue"]["status"] == "backoff"
        assert len(calls) == 7  # Full acquisition only; no repeated rescue.
        provider._CACHE["TPEX"].update(expires_at=0, rescue_next_at=0)
        provider.read_twse_mis_current_breadth("TPEX", 20, universe_reader=lambda _: rescue_scope)
        assert calls[-1][0] == rescue_scope[32:64]


@pytest.mark.parametrize("rescue_values", [
    {"z": "-", "o": "101", "h": "101", "l": "101"},
    {"z": "101", "d": "20260825"},
    {"z": "101", "ts": "1"},
    {"z": "101", "t": "10:14:00"},
    {"z": "101", "v": "4"},
])
def test_rescue_unresolved_never_infers_price_or_accepts_wrong_date(rescue_scope, rescue_values):
    def fetch(codes, **_):
        return [message(code, **(rescue_values if len(codes) == 32 else {"z": "-"})) for code in codes]
    with patch.object(provider.twse_mis, "fetch_stock_messages", side_effect=fetch):
        result = provider.read_twse_mis_current_breadth("TPEX", 20, universe_reader=lambda _: rescue_scope)
    diag = result.payload["missing_z_rescue"]
    assert diag["status"] == "partial"
    assert diag["resolved_count"] == 0
    assert diag["unresolved_count"] == 32
    assert result.payload["classified_count"] == 0
    assert result.payload["price_states"] == {}


def test_rescue_guard_rate_limit_and_timeout_do_not_start_retry_storm(rescue_scope):
    import requests
    def fetch(codes, **_):
        if len(codes) == 32:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "120"
            raise requests.HTTPError(response=response)
        return [message(code, z="-") for code in codes]
    with patch.object(provider.twse_mis, "fetch_stock_messages", side_effect=fetch) as fetcher:
        result = provider.read_twse_mis_current_breadth("TPEX", 20, universe_reader=lambda _: rescue_scope)
        assert fetcher.call_count == 4
        diag = result.payload["missing_z_rescue"]
        assert diag["status"] == "blocked"
        assert diag["backoff_seconds"] == 300
        assert diag["attempted_batch_count"] == diag["failed_batch_count"] == 1
        assert diag["batch_failures"][0]["reason"] == "rate_limited"
        assert result.operational_status.value == "rate_limited"
        assert provider.TWSE_MIS_PROVIDER_GUARD.snapshot().allowed is False
        provider._CACHE["TPEX"]["expires_at"] = 0
        provider.read_twse_mis_current_breadth("TPEX", 20, universe_reader=lambda _: rescue_scope)
        assert fetcher.call_count == 4
    provider.reset_twse_mis_current_breadth_provider()
    raw = provider._build_payload("TPEX", rescue_scope, [message(code, z="-") for code in rescue_scope], 0)
    with patch.object(provider, "_fetch_messages", side_effect=AssertionError("exhausted budget")):
        payload, calls = provider._rescue_missing_z("TPEX", rescue_scope, [], raw, prior_states=None, remaining_seconds=0.8)
    assert calls == 0
    assert payload["missing_z_rescue"]["status"] == "skipped"


def test_rescue_excludes_valid_no_trade_and_valid_session_cache(rescue_scope):
    actual = provider._build_payload("TPEX", rescue_scope[:1], [message(rescue_scope[0])], 0)
    prior = actual["price_states"]
    messages = [message(code, z="-", v="5" if code in prior else "0", tv="0") for code in rescue_scope]
    raw = provider._build_payload("TPEX", rescue_scope, messages, 0, prior_states=prior)
    with patch.object(provider, "_fetch_messages", side_effect=AssertionError("no candidates")):
        payload, calls = provider._rescue_missing_z("TPEX", rescue_scope, messages, raw, prior_states=prior, remaining_seconds=4)
    assert calls == 0
    assert payload["missing_z_rescue"]["candidate_count"] == 0
