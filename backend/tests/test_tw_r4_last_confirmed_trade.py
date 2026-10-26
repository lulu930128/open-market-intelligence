"""R4 offline canonical/AI regressions; all persistence is in-memory SQLite."""
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import socket

import pytest

from app.ai.market_context.taiwan_projection import _compact_quote_snapshot
from app.market.providers.fugle_realtime import FugleRealtimeBuffer, fugle_quote_acquisition
from app.market.providers.tw_public_quote import TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR
from app.market.providers.twse_mis_breadth_evidence import AcquisitionInFlight
from app.market.providers.twse_mis_guard import TwseMisProviderGuard
from app.market.providers.twse_mis_realtime_acquisition import TwseMisRealtimeAcquisitionAdapter
from app.market.public_quote_platform import (
    TaiwanPublicQuoteCandidateReader,
    acquire_taiwan_public_last_trade_quote,
    build_taiwan_public_quote_requirement,
    project_taiwan_public_last_trade_quote,
    read_taiwan_public_last_trade_quote,
)
from app.market.public_quote_repository import TaiwanPublicQuoteRepository
from app.market.public_quote_transaction import TaiwanPublicQuoteTransaction
from app.market.quote_depth import read_taiwan_quote_evidence_projection
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import AuthorityClass, ObservationState, TradeObservationState
from app.market_data.gateway import MarketDataGateway
from app.market_data.policies import RealtimePolicy
from app.market_data.provider_catalog import plan_data_acquisition_v2
from test_fugle_realtime_provider import _aggregate_message, _instrument
from test_tw_public_quote_platform import db, _executor, _raw_with_message_updates, _records  # noqa: F401


START = datetime(2026, 8, 25, 10, tzinfo=TAIWAN_TZ)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("R4 fixtures must not connect to a network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _requirement(now):
    return build_taiwan_public_quote_requirement(
        instrument=_instrument(), policy=RealtimePolicy.PREFER_LIVE, requested_at=now,
    )


def _persist_mis(db, now, *, price="2400", volume="10"):
    raw = _raw_with_message_updates(
        _records()["2330"], d=now.strftime("%Y%m%d"), t=now.strftime("%H:%M:%S"),
        tlong=str(int(now.timestamp() * 1000)), ts="0", z=price,
        tv="1" if price != "-" else "0", v=volume, y="2390", pz="2500",
        a="2501_", b="2499_",
    )
    requirement = _requirement(now)
    plan = plan_data_acquisition_v2(requirement, (TWSE_MIS_PUBLIC_QUOTE_DESCRIPTOR,))
    acquisition = _executor(raw, now).acquire_quote_observations(requirement, plan)
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(requirement, acquisition)


def _fugle(now, *, trade_time, trial=False):
    message = _aggregate_message()
    message["data"].update(date=now.date().isoformat(), isTrial=trial,
        lastPrice=1235, lastUpdated=int(now.timestamp() * 1_000_000))
    message["data"]["lastTrade"] = {"price": 1210, "size": 2, "serial": 123}
    if trade_time is not None:
        message["data"]["lastTrade"]["time"] = trade_time
    message["data"]["lastTrial"] = {"price": 1235, "size": 9,
        "time": int(now.timestamp() * 1_000_000), "serial": 124}
    message["data"]["total"] = {"tradeVolume": 10, "time": int(now.timestamp() * 1_000_000)}
    return message


@pytest.mark.parametrize("trial", [False, True])
@pytest.mark.parametrize("trade_time", [None, "invalid", 0, True])
@pytest.mark.parametrize("fallback", ["lastTrial", "total", "lastUpdated"])
def test_fugle_price_without_valid_trade_time_cannot_borrow_snapshot_time(trial, trade_time, fallback):
    buffer = FugleRealtimeBuffer()
    message = _fugle(START, trade_time=trade_time, trial=trial)
    if fallback != "lastTrial":
        del message["data"]["lastTrial"]
    if fallback == "lastUpdated":
        del message["data"]["total"]["time"]
    assert buffer.ingest(message, received_at=START)
    record = buffer.latest("aggregates", "2330")
    acquisition = fugle_quote_acquisition(record, _requirement(START))
    quote = acquisition.observations[0]
    assert quote.last_trade_price is None
    assert quote.last_trade_quantity is None
    assert quote.trade_state is not TradeObservationState.TRADE_OBSERVED
    assert acquisition.receipts[0].raw_text == record.raw_text
    assert acquisition.receipts[0].content_hash == hashlib.sha256(record.raw_text.encode()).hexdigest()
    assert '"price":1210' in record.raw_text


@pytest.mark.parametrize("trial", [False, True])
def test_fugle_late_receipt_preserves_actual_microsecond_event_and_quantity(db, trial):
    event = START.replace(microsecond=123456)
    now = START + timedelta(minutes=3)
    buffer = FugleRealtimeBuffer()
    assert buffer.ingest(_fugle(now, trade_time=int(event.timestamp() * 1_000_000), trial=trial), received_at=now)
    record = buffer.latest("aggregates", "2330")
    acquisition = fugle_quote_acquisition(record, _requirement(now))
    quote = acquisition.observations[0]
    assert quote.lineage.event_at == event
    assert quote.lineage.received_at == now
    assert quote.last_trade_price == Decimal("1210")
    assert quote.last_trade_quantity.value == Decimal("2000")
    assert quote.cumulative_quantity.value == Decimal("10000")
    assert quote.state is (ObservationState.INDICATIVE if trial else ObservationState.AVAILABLE)
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(_requirement(now), acquisition)
    result = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=now)
    assert result.resolved.health.facts_usable
    assert not result.resolved.health.research_usable
    assert result.resolved.quote.lineage.event_at == event


@pytest.mark.parametrize("volume,qualified", [("10", True), ("11", False), ("9", False)])
@pytest.mark.parametrize("preloaded", [False, True])
def test_missing_z_keeps_fact_but_volume_increase_invalidates_current(db, volume, qualified, preloaded):
    _persist_mis(db, START)
    now = START + timedelta(seconds=5)
    _persist_mis(db, now, price="-", volume=volume)
    repository = TaiwanPublicQuoteRepository(db)
    if preloaded:
        repository.preload_quote_candidates((_instrument(),), requested_at=now)
    requirement = build_taiwan_public_quote_requirement(
        instrument=_instrument(), policy=RealtimePolicy.CACHE_ONLY, requested_at=now,
    )
    result = MarketDataGateway().resolve_quote(requirement, reader=TaiwanPublicQuoteCandidateReader(repository))
    quote = result.resolved.quote
    assert quote.last_trade_price == Decimal("2400")
    assert quote.lineage.event_at == START
    assert quote.latest_observation_lineage.event_at == now
    assert quote.latest_observation_lineage.received_at == now
    assert result.resolved.health.facts_usable
    assert result.resolved.health.research_usable is qualified
    projection = project_taiwan_public_last_trade_quote(result)
    assert projection["last_trade_time"] == START
    assert projection["last_trade_is_current_session"]
    assert projection["resolved_health"]["research_usable"] is qualified
    depth = read_taiwan_quote_evidence_projection(db=db, stock_id="2330", requested_at=now)
    compact = _compact_quote_snapshot(latest_daily=None, quote_depth=depth, quote_error=None,
        session_phase="regular", current_session_date=START.date().isoformat(), is_trading_day=True)
    assert compact["last_trade_price"] == 2400
    assert compact["price_decision_usable"] is qualified


def test_cache_stale_ai_quote_retains_fact_and_distinct_latest_observation(db):
    _persist_mis(db, START)
    now = START + timedelta(minutes=3)
    _persist_mis(db, now, price="-", volume="10")
    depth = read_taiwan_quote_evidence_projection(db=db, stock_id="2330", requested_at=now)
    compact = _compact_quote_snapshot(latest_daily=None, quote_depth=depth, quote_error=None,
        session_phase="regular", current_session_date=START.date().isoformat(), is_trading_day=True)
    assert compact["last_trade_price"] == 2400
    assert datetime.fromisoformat(compact["last_trade_time"]) == START
    assert compact["price_decision_usable"] is False
    evidence = depth["data_core_components"]["quote.snapshot"]
    assert evidence["resolved_health"]["facts_usable"] is True
    assert evidence["resolved_health"]["research_usable"] is False
    assert datetime.fromisoformat(evidence["latest_observation_lineage"]["event_at"]) == now


def test_new_day_missing_trade_never_uses_previous_close_or_yesterday(db):
    _persist_mis(db, START)
    now = START + timedelta(days=1)
    _persist_mis(db, now, price="-", volume="0")
    result = read_taiwan_public_last_trade_quote(db, stock_id="2330", requested_at=now)
    assert result.resolved.quote is None
    assert not result.resolved.health.research_usable


def test_fugle_trade_date_cannot_relabel_yesterday_as_today(db):
    message = _fugle(START, trade_time=int((START - timedelta(days=1)).timestamp() * 1_000_000))
    buffer = FugleRealtimeBuffer()
    assert buffer.ingest(message, received_at=START)
    acquisition = fugle_quote_acquisition(buffer.latest("aggregates", "2330"), _requirement(START))
    assert acquisition.observations[0].last_trade_price is None


def test_fugle_new_snapshot_cannot_regress_last_trade_event():
    buffer = FugleRealtimeBuffer()
    assert buffer.ingest(_fugle(START, trade_time=int(START.timestamp() * 1_000_000)), received_at=START)
    later = START + timedelta(seconds=2)
    older = START - timedelta(seconds=2)
    assert not buffer.ingest(_fugle(later, trade_time=int(older.timestamp() * 1_000_000)), received_at=later)
    assert buffer.latest("aggregates", "2330").event_at == START


@pytest.mark.parametrize("failure", ["timeout", "guard", "slot"])
def test_failed_acquisition_keeps_known_fact_without_cross_provider_fetch(db, failure):
    _persist_mis(db, START)
    now = START + timedelta(minutes=1)
    calls = []
    guard = TwseMisProviderGuard()
    if failure == "guard":
        guard.record_http_failure(guard.before_request().attempt, 429)

    def reader(*args):
        calls.append(args)
        if failure == "slot":
            raise AcquisitionInFlight("TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT")
        raise TimeoutError("fixture transport timeout")

    result = acquire_taiwan_public_last_trade_quote(
        db, stock_id="2330", policy=RealtimePolicy.PREFER_LIVE, requested_at=now,
        acquisition=TwseMisRealtimeAcquisitionAdapter(reader, clock=lambda: now, provider_guard=guard),
    )
    assert result.resolved.quote.last_trade_price == Decimal("2400")
    assert result.resolved.quote.lineage.event_at == START
    assert result.resolved.health.facts_usable
    assert not result.resolved.health.research_usable
    assert result.acquisition.status.value == "failed"
    assert result.acquisition.providers_attempted == ("twse_mis",)
    assert result.acquisition.external_calls == (1 if failure == "timeout" else 0)
    assert len(calls) == (0 if failure == "guard" else 1)
    projection = project_taiwan_public_last_trade_quote(result)
    assert projection["acquisition_status"] == "failed"
    assert projection["last_trade_price"] == 2400
    assert projection["freshness"]["is_stale"]


@pytest.mark.parametrize("trial", [False, True])
def test_fugle_missing_last_trade_never_promotes_trial_lastprice_or_previous_close(trial):
    message = _fugle(START, trade_time=None, trial=trial)
    del message["data"]["lastTrade"]
    buffer = FugleRealtimeBuffer()
    assert buffer.ingest(message, received_at=START)
    quote = fugle_quote_acquisition(buffer.latest("aggregates", "2330"), _requirement(START)).observations[0]
    assert quote.last_trade_price is None
    assert quote.last_trade_quantity is None
    assert quote.cumulative_quantity.value == 10000
    assert quote.trade_state is not TradeObservationState.TRADE_OBSERVED


@pytest.mark.parametrize("gate", ["future", "authority"])
def test_fugle_existing_shared_future_and_authority_gates_remain_closed(db, gate):
    event = START + timedelta(minutes=6) if gate == "future" else START
    buffer = FugleRealtimeBuffer()
    assert buffer.ingest(_fugle(START, trade_time=int(event.timestamp() * 1_000_000)), received_at=START)
    requirement = _requirement(START)
    acquisition = fugle_quote_acquisition(buffer.latest("aggregates", "2330"), requirement)
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(requirement, acquisition)
    if gate == "authority":
        requirement = requirement.model_copy(update={"quality": requirement.quality.model_copy(
            update={"minimum_authority": AuthorityClass.EXCHANGE})})
    result = MarketDataGateway().resolve_quote(requirement,
        reader=TaiwanPublicQuoteCandidateReader(TaiwanPublicQuoteRepository(db)))
    assert result.resolved.quote is None
    assert not result.resolved.health.research_usable
    if gate == "authority":
        assert any(c.reason_code == "QUALITY_AUTHORITY_BELOW_MINIMUM" for c in result.resolved.candidates)


@pytest.mark.parametrize("trial", [False, True])
@pytest.mark.parametrize("preloaded", [False, True])
def test_fugle_invalid_trade_does_not_replace_persisted_actual_or_claim_mis_lineage(db, trial, preloaded):
    buffer = FugleRealtimeBuffer()
    assert buffer.ingest(_fugle(START, trade_time=int(START.timestamp() * 1_000_000)), received_at=START)
    first = fugle_quote_acquisition(buffer.latest("aggregates", "2330"), _requirement(START))
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(_requirement(START), first)
    now = START + timedelta(seconds=5)
    assert buffer.ingest(_fugle(now, trade_time=None, trial=trial), received_at=now)
    second = fugle_quote_acquisition(buffer.latest("aggregates", "2330"), _requirement(now))
    TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(_requirement(now), second)
    repository = TaiwanPublicQuoteRepository(db)
    if preloaded:
        repository.preload_quote_candidates((_instrument(),), requested_at=now)
    result = MarketDataGateway().resolve_quote(_requirement(now),
        reader=TaiwanPublicQuoteCandidateReader(repository))
    assert result.resolved.quote is not None
    assert result.resolved.quote.last_trade_price == Decimal("1210")
    assert result.resolved.quote.lineage.event_at == START
    assert result.resolved.quote.lineage.provider == "fugle_marketdata"
    assert result.resolved.quote.lineage.source == "fugle_aggregates_stream"
    assert not result.acquisition.attempted
    assert result.acquisition.external_calls == 0
    if trial:
        assert result.resolved.quote.state is ObservationState.INDICATIVE
        assert not result.resolved.health.research_usable
