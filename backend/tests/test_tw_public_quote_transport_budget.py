"""Single quote transport shares MIS ownership and rejects late publication."""
from datetime import datetime
from threading import Event
from time import perf_counter
from types import SimpleNamespace

import pytest

from app.market import public_quote_acquisition as owner
from app.market.providers import twse_mis_breadth_evidence as transport
from app.market.providers.twse_mis_guard import TwseMisProviderGuard
from app.market.public_quote_platform import acquire_taiwan_public_last_trade_quote
from app.market.tw_public_quote_contract import TWSE_MIS_QUOTE_RESOURCE_ID
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import InstrumentKey, Market, MarketSession
from app.market_data.policies import RealtimePolicy
from app.db.models import TaiwanStockQuoteSnapshot, RawFetchResult
from test_tw_public_quote_platform import db, FakeResponse, _raw, _records  # noqa: F401

NOW = datetime(2026, 8, 25, 10, 0, tzinfo=TAIWAN_TZ)


def test_transport_timeout_retains_slot_and_late_response_never_writes_quote(db, monkeypatch):
    entered, release = Event(), Event()
    calls = []
    def fetch(*args, **kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(5)
        return FakeResponse(_raw(_records()['2330']))
    transport.reset_io_slots()
    monkeypatch.setattr(owner.twse_mis, 'get_stock_response', fetch)
    monkeypatch.setattr(owner, 'MIS_SINGLE_QUOTE_MAX_WAIT_SECONDS', .03)
    executor = owner.TaiwanPublicQuoteAcquisitionExecutor(clock=lambda: NOW,
        provider_guard=TwseMisProviderGuard())
    started = perf_counter()
    try:
        result = acquire_taiwan_public_last_trade_quote(db, stock_id='2330',
            policy=RealtimePolicy.REQUIRE_LIVE, requested_at=NOW, acquisition=executor)
        assert entered.is_set() and perf_counter()-started < 2
        assert result.acquisition.external_calls == 1
        assert result.resolved.quote is None
        assert db.query(TaiwanStockQuoteSnapshot).count() == 0
        assert db.query(RawFetchResult).count() == 1
        # The still-running same-venue transport owns admission even for depth.
        with pytest.raises(transport.AcquisitionInFlight):
            transport.bounded_fetch(lambda **kw: pytest.fail('duplicate IO'), .03,
                interactive=True, exchange='tse')
        release.set()
        transport._IN_FLIGHT['tse'].result(timeout=3)
        assert len(calls) == 1
        db.expire_all()
        assert db.query(TaiwanStockQuoteSnapshot).count() == 0
        assert db.query(RawFetchResult).count() == 1  # no late success publication
    finally:
        release.set()
        if 'tse' in transport._IN_FLIGHT:
            transport._IN_FLIGHT['tse'].result(timeout=3)
        transport.reset_io_slots()


def test_busy_venue_consumes_zero_calls_and_does_not_trip_provider_guard():
    def busy(*args):
        raise transport.AcquisitionInFlight('TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT')
    guard = TwseMisProviderGuard(failure_threshold=1)
    executor = owner.TaiwanPublicQuoteAcquisitionExecutor(
        fetchers={TWSE_MIS_QUOTE_RESOURCE_ID:busy}, clock=lambda: NOW, provider_guard=guard)
    route = SimpleNamespace(provider_key='twse_mis', market=Market.TW,
        capability_id='quote.snapshot', resource_id=TWSE_MIS_QUOTE_RESOURCE_ID)
    instrument = InstrumentKey(market='TW', symbol='2330', venue='TWSE', instrument_type='stock')
    for _ in range(3):
        result = executor._run_route(route, instrument=instrument, session=MarketSession.CONTINUOUS)
        assert result.external_calls == 0 and result.observation is None
        assert result.health.operational.value == 'unavailable'
        assert 'TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT' in result.limitations
        assert guard.snapshot().allowed is True
