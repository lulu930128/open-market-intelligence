"""Offline R4-C capability isolation; no provider or production database access."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import socket

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster
from app.market import tw_realtime_lease_platform as platform
from app.market.providers.kgi_realtime_acquisition import (
    KgiRealtimeAcquisitionAdapter, KgiRealtimeProviderSnapshot,
)
from app.market.public_quote_platform import read_taiwan_public_last_trade_quote
from app.market_data.research_lease import ViewerLeaseState
from app.market.public_quote_transaction import TaiwanPublicQuoteTransaction
from app.market.realtime_snapshot_transaction import TaiwanDepthTransaction, TaiwanAuctionTransaction
from app.market.intraday_transaction import TaiwanIntradayBarTransaction
from app.market_data.policies import RealtimePolicy
from app.market_data.contracts import MarketSession
from app.market.tw_realtime_capabilities import KGI_AUCTION_DESCRIPTOR

NOW = datetime(2026, 10, 21, 13, 24, 17, tzinfo=timezone(timedelta(hours=8)))
SYNC_MIS = platform._sync_mis_depth_snapshot
ACQUIRE_DEPTH = platform.acquire_taiwan_depth
ACQUIRE_AUCTION = platform.acquire_taiwan_auction
SYNC_BARS = platform._sync_kgi_minute_bars


@pytest.fixture
def context(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(StockMaster(stock_id="2330", stock_name="fixture", market="TWSE", instrument_type="stock"))
        db.commit()
        raw = dict(symbol="2330", datetime="20261021132417", received_at=NOW.isoformat(),
                   simtrade=0, close=2405, volume=2, total_volume=100,
                   bid_prices=[], bid_volumes=[], ask_prices=[], ask_volumes=[])
        monkeypatch.setattr(platform._KGI_REALTIME_PORT, "acquisition_adapter",
                            lambda *, clock: KgiRealtimeAcquisitionAdapter(
                                lambda _: KgiRealtimeProviderSnapshot(quote=raw, status="live"), clock=clock))
        monkeypatch.setattr(platform._KGI_REALTIME_PORT, "quote_snapshot",
                            lambda _: KgiRealtimeProviderSnapshot(quote=raw, status="live"))
        monkeypatch.setattr(platform, "_sync_kgi_minute_bars", lambda *a, **k: None)
        monkeypatch.setattr(platform, "acquire_taiwan_depth", lambda *a, **k: None)
        monkeypatch.setattr(platform, "_has_research_usable_depth", lambda result: result is not None)
        monkeypatch.setattr(platform, "_sync_mis_depth_snapshot", lambda *a, **k: None)
        state = ViewerLeaseState(lease_id="fixture-lease", stock_id="2330", provider="kgi_superpy",
                                 owner_kind="acceptance_probe", status="live", message="fixture",
                                 fallback_source="resolved_fallback")
        yield db, raw, state
    engine.dispose()


def test_absent_actual_is_not_live(context):
    db, raw, state = context
    raw["volume"] = 0
    result = platform._sync_if_live(db, state, requested_at=NOW)
    assert result.status == "degraded"
    assert "QUOTE_UNQUALIFIED" in result.error
    quote = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
    assert not quote.resolved.health.research_usable


@pytest.mark.parametrize("step", ["quote", "kbar", "depth", "auction"])
@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_step_faults_preserve_committed_quote_and_identify_step(context, monkeypatch, step, error_type):
    db, raw, state = context
    calls = []
    def fail(*a, **k):
        raise error_type("fixture private text must not escape")
    def auction(*a, **k):
        calls.append("auction")
        if step == "auction":
            return fail()
        return SimpleNamespace(acquisition=SimpleNamespace(attempted=False))
    monkeypatch.setattr(platform, "acquire_taiwan_auction", auction)
    target = {"quote": "acquire_taiwan_public_last_trade_quote", "kbar": "_sync_kgi_minute_bars",
              "depth": "_sync_mis_depth_snapshot"}.get(step)
    if target:
        monkeypatch.setattr(platform, target, fail)
    result = platform._sync_if_live(db, state, requested_at=NOW)
    assert result.status == "degraded"
    assert f"{step.upper()}:{error_type.__name__}" in result.error
    assert "private" not in result.error
    if step != "quote":
        quote = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
        assert quote.resolved.quote.last_trade_price == 2405
        assert quote.resolved.quote.lineage.provider == "kgi_superpy"
        assert quote.resolved.quote.lineage.event_at == NOW
        assert quote.resolved.health.research_usable
        assert calls == ["auction"]
        assert "QUOTE_QUALIFIED" in result.message


@pytest.mark.parametrize("age,qualified", [(15, True), (16, False)])
def test_original_event_time_gate(context, age, qualified):
    db, raw, state = context
    raw["datetime"] = (NOW - timedelta(seconds=age)).strftime("%Y%m%d%H%M%S")
    result = platform._sync_if_live(db, state, requested_at=NOW)
    assert (result.status == "live") is qualified
    quote = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
    assert quote.resolved.health.research_usable is qualified


def test_real_failed_mis_fallback_keeps_quote_and_runs_auction(context, monkeypatch):
    db, raw, state = context
    monkeypatch.setattr(platform, "_sync_mis_depth_snapshot", SYNC_MIS)
    monkeypatch.setattr(platform, "refresh_taiwan_realtime_snapshot",
                        lambda *a, **k: SimpleNamespace(depth=None))
    result = platform._sync_if_live(db, state, requested_at=NOW)
    assert result.status == "degraded"
    assert "DEPTH:RuntimeError:MIS_DEPTH_FALLBACK_UNAVAILABLE" in result.error
    assert "QUOTE_QUALIFIED" in result.message
    quote = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
    assert quote.resolved.quote.last_trade_price == 2405
    assert quote.resolved.health.research_usable


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_quote_persistence_failure_is_fail_closed(context, monkeypatch, error_type):
    db, raw, state = context
    def fail(*a, **k):
        raise error_type("private fixture persistence error")
    monkeypatch.setattr(TaiwanPublicQuoteTransaction, "persist_quote_acquisition", fail)
    result = platform._sync_if_live(db, state, requested_at=NOW)
    assert result.status == "degraded"
    assert "QUOTE:" in result.error
    assert error_type.__name__ in result.error
    assert "private" not in result.error
    assert "QUOTE_UNQUALIFIED" in result.message
    assert read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW).resolved.quote is None


@pytest.mark.parametrize("valid", [True, False])
def test_closing_auction_never_promoted_to_actual(context, valid, monkeypatch):
    db, raw, state = context
    now = NOW.replace(minute=28)
    raw.update(datetime="20261021132817", received_at=now.isoformat(),
               simtrade=1, close=2405 if valid else None)
    original = platform.acquire_taiwan_auction
    captured = []
    def acquire(*a, **k):
        result = original(*a, **k)
        captured.append(result)
        return result
    monkeypatch.setattr(platform, "acquire_taiwan_auction", acquire)
    result = platform._sync_if_live(db, state, requested_at=now)
    assert result.status == "degraded"
    assert "QUOTE_UNQUALIFIED" in result.error
    assert ("AUCTION_UNQUALIFIED" not in result.error) is valid, captured[0].resolved.health.model_dump()
    assert not read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=now).resolved.health.research_usable


def test_non_live_underlying_does_not_sync(context, monkeypatch):
    db, raw, state = context
    def forbidden(*a, **k):
        raise AssertionError("must not sync")
    monkeypatch.setattr(platform, "_sync_canonical_snapshot", forbidden)
    subscribing = state.model_copy(update={"status": "subscribing"})
    assert platform._sync_if_live(db, subscribing, requested_at=NOW) == subscribing


def test_fresh_cache_does_not_hide_absent_current_snapshot(context, monkeypatch):
    db, raw, state = context
    assert platform._sync_if_live(db, state, requested_at=NOW).status == "live"
    monkeypatch.setattr(platform._KGI_REALTIME_PORT, "quote_snapshot",
                        lambda _: KgiRealtimeProviderSnapshot(quote=None, status="live"))
    result = platform._sync_if_live(db, state, requested_at=NOW + timedelta(seconds=1))
    assert result.status == "degraded"
    assert "QUOTE_UNQUALIFIED" in result.error
    quote = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
    assert quote.resolved.quote.last_trade_price == 2405
    assert quote.resolved.quote.lineage.event_at == NOW


@pytest.mark.parametrize("step", ["kbar", "depth", "auction"])
def test_transaction_owner_rolls_back_db_failure_preserving_quote(context, monkeypatch, step):
    db, raw, state = context
    owners = {"kbar": TaiwanIntradayBarTransaction, "depth": TaiwanDepthTransaction,
              "auction": TaiwanAuctionTransaction}
    failures = []
    def fail_upsert(self, *a, **k):
        failures.append(step)
        self._db.add(StockMaster(stock_id="2330", stock_name="duplicate", market="TWSE"))
        self._db.flush()  # Real SQLite IntegrityError leaves Session inactive until owner rollback.
    monkeypatch.setattr(owners[step], "_upsert", fail_upsert)
    if step == "kbar":
        monkeypatch.setattr(platform, "_sync_kgi_minute_bars", SYNC_BARS)
        monkeypatch.setattr(platform, "_KGI_LAST_MATERIALIZED_FINAL_BAR", {})
        monkeypatch.setattr(platform._KGI_REALTIME_PORT, "market_stream_snapshot", lambda *a, **k: {
            "stock_id": "2330", "minute_kbars": [dict(event_id="fixture-bar",
                event_time="2026-10-21T13:23:00+08:00", received_at=NOW.isoformat(),
                open=2400, high=2405, low=2395, close=2405, volume_lots=2)]})
    elif step == "depth":
        raw.update(bid_prices=[2400], bid_volumes=[2], ask_prices=[2405], ask_volumes=[3])
        monkeypatch.setattr(platform, "acquire_taiwan_depth", ACQUIRE_DEPTH)
    else:
        def auction(db, **kwargs):
            trial = dict(raw, datetime="20261021132817", simtrade=1)
            now = NOW.replace(minute=28)
            trial["received_at"] = now.isoformat()
            adapter = KgiRealtimeAcquisitionAdapter(
                lambda _: KgiRealtimeProviderSnapshot(quote=trial, status="live"), clock=lambda: now)
            return ACQUIRE_AUCTION(db, stock_id="2330", policy=RealtimePolicy.REQUIRE_LIVE,
                requested_at=now, session=MarketSession.CLOSING_AUCTION,
                descriptors=(KGI_AUCTION_DESCRIPTOR,), acquisition=adapter)
        monkeypatch.setattr(platform, "acquire_taiwan_auction", auction)
    result = platform._sync_if_live(db, state, requested_at=NOW)
    assert failures == [step]
    assert db.is_active
    assert "SESSION_INACTIVE" not in (result.error or "")
    if step != "auction":
        assert "DB_SYNC_FAILED_STOPPED" in result.error
    quote = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
    assert quote.resolved.quote.last_trade_price == 2405
    assert quote.resolved.quote.lineage.event_at == NOW
    assert quote.resolved.health.research_usable


def test_inactive_session_stops_without_lease_owned_rollback(context, monkeypatch):
    db, raw, state = context
    calls = []
    def dirty_failure(*a, **k):
        db.add(StockMaster(stock_id="2330", stock_name="duplicate", market="TWSE"))
        db.flush()
    monkeypatch.setattr(platform, "_sync_kgi_minute_bars", dirty_failure)
    monkeypatch.setattr(platform, "acquire_taiwan_depth", lambda *a, **k: calls.append("depth"))
    result = platform._sync_if_live(db, state, requested_at=NOW)
    assert "SESSION_INACTIVE" in result.error
    assert not db.is_active
    assert calls == []
    db.rollback()  # Test owns cleanup; production lease owner did not assume rollback authority.
    quote = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=NOW)
    assert quote.resolved.quote.last_trade_price == 2405
