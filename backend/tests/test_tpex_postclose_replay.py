"""11/04 official receipt replay through real acquisition/transaction/read owners."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.db.models import Base, MarketDailyPrice, MarketIndexDailyStat, RawFetchResult, SourceRegistry, StockMaster
from app.db.session import SessionLocal
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue, qualify_taiwan_eod_universe
from app.market.official_index_acquisition import TaiwanOfficialIndexAcquisitionExecutor
from app.market.official_index_platform import refresh_taiwan_official_index, read_taiwan_official_index
from app.market.official_index_repository import TaiwanOfficialIndexRepository
from app.market.tw_daily_reconciliation import TaiwanDailyReconciliationTransaction
from app.market_data import eod_coverage
from test_tw_official_daily_platform import FakeResponse


DAY = date(2026, 11, 4)
NOW = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)
FIXTURE = json.loads((Path(__file__).parent / 'fixtures/tw_market_data/tpex_postclose_excerpt_20261104.json').read_text(encoding='utf-8'))
DATED = 'tpex_dated_daily_quotes'
HIGHLIGHT = 'tpex_after_trading_highlight'
PRIMARY = 'tpex_mainboard_quotes'
CLOSE = 'tpex_mainboard_daily_close_quotes'


@pytest.fixture
def db(monkeypatch):
    # Bind the actual production sessionmaker to isolated storage; no real I/O.
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    def forbidden(*args, **kwargs):
        pytest.fail('unexpected external provider call')
    monkeypatch.setattr('app.market.providers.tpex.get_response', forbidden)
    monkeypatch.setattr('app.market.providers.twse.get_response', forbidden)
    with SessionLocal(bind=engine) as session:
        assert session.autoflush is False
        yield session
    engine.dispose()


def executor(calls, clock=lambda: NOW):
    payloads = {PRIMARY: 'primary', CLOSE: 'close', DATED: 'dated', HIGHLIGHT: 'highlight',
                'MI_INDEX_ALLBUT0999': 'twse', 'STOCK_DAY_ALL': 'primary'}
    def fetch(route):
        calls.append(route.resource_id)
        return FakeResponse(text=json.dumps(FIXTURE[payloads[route.resource_id]], ensure_ascii=False))
    return TaiwanOfficialDailyAcquisitionExecutor(fetchers={key: fetch for key in payloads}, clock=clock)


def seed(db):
    db.add_all([StockMaster(stock_id=s, market=v, instrument_type='stock', is_active=True)
                for s, v in [('2330', 'TWSE'), ('3105', 'TPEX'), ('6182', 'TPEX'), ('6488', 'TPEX')]])
    db.commit()


def test_received_old_date_is_not_transport_failure(db):
    seed(db)
    result = refresh_taiwan_official_daily_venue(db, venue='TPEX', trade_date=DAY, requested_at=NOW,
        acquisition=executor([]), refresh_published=False, max_external_calls=1)
    assert result['fetch_status'] == 'success'
    assert result['parse_status'] == 'error' and result['parsed_count'] == 0
    assert 'EXPECTED_TRADE_DATE_NOT_OBSERVED' in result['limitations']
    assert db.query(RawFetchResult).one().status_code == 200
    assert db.query(MarketDailyPrice).count() == 0


def test_natural_bounded_opportunities_reach_dated_resource_and_preserve_twse(db, monkeypatch):
    seed(db)
    calls, clock = [], [NOW]
    acquisition = executor(calls, lambda: clock[0])
    monkeypatch.setattr(eod_coverage, 'utc_now', lambda: clock[0])
    def run():
        return eod_coverage.reconcile_eod_coverage(db, market='TW', expected_trade_date=DAY,
            max_symbols=2, taiwan_daily_qualifier=qualify_taiwan_eod_universe, error_backoff_seconds=60,
            taiwan_venue_refresher=lambda **kw: refresh_taiwan_official_daily_venue(
                **kw, requested_at=clock[0], acquisition=acquisition))
    first = run()
    assert first['current_count'] == 1 and first['external_call_budget_used'] == 2
    status = first['checkpoint']['detail']['repair']['provider_results'][-1]
    assert status['dataset_status'] == 'stale_payload'
    original = db.query(MarketDailyPrice).filter_by(stock_id='2330').one().raw_result_id
    assert run()['attempted_count'] == 0  # Existing backoff; no new scheduler.
    results = [first]
    for _ in range(3):
        clock[0] += timedelta(seconds=61)
        db.expire_all()
        results.append(run())
    assert DATED in calls
    assert all(x.get('external_call_budget_used', 0) <= 2 for x in results)
    assert results[-1]['current_count'] == 4
    assert calls.count('MI_INDEX_ALLBUT0999') == 1
    assert db.query(MarketDailyPrice).filter_by(stock_id='2330').one().raw_result_id == original
    for symbol, close in [('3105', 501), ('6182', 82.8), ('6488', 619)]:
        row = db.query(MarketDailyPrice).filter_by(stock_id=symbol).one()
        raw = db.get(RawFetchResult, row.raw_result_id)
        source = db.get(SourceRegistry, row.source_id)
        assert row.trade_date == DAY and row.close_price == close
        assert raw.source_id == source.id and raw.parser_version == 'tpex_dated_daily_quotes.v1'
        assert source.source_name == 'TPEx Dated Daily Quotes'
    coverage = eod_coverage.compute_eod_coverage(db, market='TW', expected_trade_date=DAY,
        taiwan_daily_qualifier=qualify_taiwan_eod_universe)
    assert coverage.current_symbols == {'2330','3105','6182','6488'}


def index_executor(calls, *, primary=None, highlight=None):
    def fetch(route):
        calls.append(route.resource_id)
        payload = (FIXTURE['index'] if primary is None else primary) if route.resource_id == 'tpex_daily_trading_index' else (FIXTURE['highlight'] if highlight is None else highlight)
        return FakeResponse(text=json.dumps(payload, ensure_ascii=False))
    return TaiwanOfficialIndexAcquisitionExecutor(fetchers={'tpex_daily_trading_index': fetch, HIGHLIGHT: fetch}, clock=lambda: NOW)


def test_official_highlight_close_has_real_stat_raw_join_and_reconciliation(db):
    calls = []
    result = refresh_taiwan_official_index(db, index_id='TPEX', trade_date=DAY, requested_at=NOW,
        acquisition=index_executor(calls))
    # Close is usable for reconciliation, but complete index totals remain missing.
    assert not result.postcondition_satisfied
    assert any(r.reason_code == 'QUALITY_PARTIAL_NOT_ALLOWED' for r in result.result.resolved.candidates)
    assert calls == ['tpex_daily_trading_index', HIGHLIGHT]
    row, source, raw = db.query(MarketIndexDailyStat, SourceRegistry, RawFetchResult).join(
        SourceRegistry, SourceRegistry.id == MarketIndexDailyStat.source_id).join(
        RawFetchResult, RawFetchResult.id == MarketIndexDailyStat.raw_result_id).one()
    assert row.trade_date == DAY and row.close_value == 343.5 and row.price_change == -2.02
    assert row.trade_volume is row.trade_value is row.transaction_count is None
    assert source.source_name == 'TPEx After Trading Market Highlight' and raw.source_id == source.id
    assert raw.parser_version == 'tpex.highlight_index_close.v1'
    assert json.loads(raw.raw_text) == FIXTURE['highlight']
    read = read_taiwan_official_index(db, index_id='TPEX', trade_date=DAY, requested_at=NOW)
    assert read.resolved.market_index is None  # Existing complete-index read contract stays strict.
    stored = TaiwanOfficialIndexRepository(db).load_market_index(index_id='TPEX', trade_date=DAY)
    assert stored.observation.close_value == Decimal('343.5')
    assert stored.observation.state.value == 'partial'
    assert 'INDEX_MARKET_TOTALS_PARTIAL' in read.limitations
    assert len(calls) == 2  # Read has no acquisition side effect.
    from test_tw_unified_daily_bars import _tpex_components
    from app.market.tw_bar_materializer import materialize_tpex_completed_daily_candidate
    from app.market.tw_bar_materialization_transaction import TaiwanBarMaterializationTransaction
    components, formal_close, raw_ids, hashes = _tpex_components(db, trade_date=DAY)
    # Synthetic component history exercises the actual derived transaction; only
    # the official highlight receipt above is claimed as real 11/04 evidence.
    formal_close = formal_close.model_copy(update={key: Decimal('343.5')
        for key in ('open_price', 'high_price', 'low_price', 'close_price')})
    candidate = materialize_tpex_completed_daily_candidate(components, formal_close_component=formal_close,
        component_raw_result_ids=raw_ids, component_content_hashes=hashes, coverage_complete=True, as_of=NOW)
    TaiwanBarMaterializationTransaction(db).persist_materialized_daily_bar(candidate)
    candidate = db.query(MarketDailyPrice).filter_by(stock_id='TPEX').one()
    before = (candidate.open_price, candidate.high_price, candidate.low_price, candidate.close_price)
    reconciled = TaiwanDailyReconciliationTransaction(db).reconcile_tpex_daily_stat(trade_date=DAY)
    assert reconciled.status.value == 'matched'
    assert (candidate.open_price, candidate.high_price, candidate.low_price, candidate.close_price) == before
    # A receipt from the breadth parser cannot masquerade as qualified index data.
    raw.parser_version = 'tpex_published_breadth.v1'
    db.commit()
    with pytest.raises(ValueError, match='EVIDENCE_INVALID'):
        TaiwanDailyReconciliationTransaction(db).reconcile_tpex_daily_stat(trade_date=DAY)


def test_dated_resource_is_planned_with_exact_date_and_existing_http_owner(db, monkeypatch):
    from app.market.providers import tpex
    requests = []
    def get(url, **kwargs):
        requests.append((url, kwargs))
        return FakeResponse(text=json.dumps(FIXTURE['dated']), url=url)
    monkeypatch.setattr(tpex, 'get_response', get)
    seed(db)
    result = refresh_taiwan_official_daily_venue(db, venue='TPEX', trade_date=DAY, requested_at=NOW,
        refresh_published=False, max_external_calls=1,
        acquisition=TaiwanOfficialDailyAcquisitionExecutor(clock=lambda: NOW),
        route_state={'version':1, 'venue':'TPEX', 'trade_date':DAY.isoformat(), 'attempted_resources':[PRIMARY, CLOSE]})
    assert requests[0][0] == 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes'
    assert requests[0][1]['params'] == {'date':'2026/11/04','response':'json'}
    assert requests[0][1]['allow_redirects'] is False
    assert result['external_call_count'] == 1 and result['parsed_count'] == 3


def complete_primary():
    # Controlled same-day complete record; not a claim about real 11/04 totals.
    record = dict(FIXTURE['index'][-1])
    record.update(Date='1151104', TPExIndex='343.5', Change='-2.02')
    return [record]


def test_current_complete_primary_stops_fallback_and_later_partial_cannot_replace_it(db):
    calls = []
    first = refresh_taiwan_official_index(db, index_id='TPEX', trade_date=DAY, requested_at=NOW,
        acquisition=index_executor(calls, primary=complete_primary()))
    assert first.postcondition_satisfied and calls == ['tpex_daily_trading_index']
    row = db.query(MarketIndexDailyStat).one()
    original = (row.source_id, row.raw_result_id, row.close_value, row.price_change,
                row.trade_volume, row.trade_value, row.transaction_count, row.updated_at)
    raw_count = db.query(RawFetchResult).count()
    for close in ['343.5', '344.5']:
        payload = json.loads(json.dumps(FIXTURE['highlight']))
        payload['tables'][0]['data'][0][5] = close
        second = refresh_taiwan_official_index(db, index_id='TPEX', trade_date=DAY, requested_at=NOW,
            acquisition=index_executor(calls, highlight=payload))
        assert second.postcondition_satisfied  # Previously qualified complete row remains.
        assert second.persistence.observations_written == 0
        assert second.persistence.observations_unchanged == 1
        assert 'INDEX_PARTIAL_RECEIPT_NOT_REPLACING_COMPLETE' in second.limitations
        db.refresh(row)
        assert original == (row.source_id, row.raw_result_id, row.close_value, row.price_change,
                            row.trade_volume, row.trade_value, row.transaction_count, row.updated_at)
    assert db.query(RawFetchResult).count() == raw_count + 4  # Both stale and unused partial receipts retained.
    assert calls == ['tpex_daily_trading_index'] + ['tpex_daily_trading_index', HIGHLIGHT] * 2


@pytest.mark.parametrize('fault', ['date', 'table_date', 'fields', 'ohlc', 'status'])
def test_dated_payload_qualification_does_not_fabricate_current_bars(db, fault):
    seed(db)
    payload = json.loads(json.dumps(FIXTURE['dated']))
    if fault == 'date':
        payload['date'] = '20261103'
        payload['tables'][0]['date'] = '115/11/03'
    elif fault == 'table_date':
        payload['tables'][0]['date'] = '115/11/03'
    elif fault == 'fields':
        payload['tables'][0]['fields'][8] = '成交張數'
    elif fault == 'ohlc':
        for row in payload['tables'][0]['data']:
            row[4] = '--'
    else:
        payload['stat'] = 'not published'
    acquisition = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={DATED: lambda _: FakeResponse(text=json.dumps(payload))}, clock=lambda: NOW)
    result = refresh_taiwan_official_daily_venue(db, venue='TPEX', trade_date=DAY, requested_at=NOW,
        acquisition=acquisition, refresh_published=False, max_external_calls=1,
        route_state={'version':1, 'venue':'TPEX', 'trade_date':DAY.isoformat(), 'attempted_resources':[PRIMARY,CLOSE]})
    assert result['external_call_count'] == 1 and result['fetch_status'] == 'success'
    assert result['parse_status'] == 'error' and result['parsed_count'] == 0
    assert db.query(MarketDailyPrice).count() == 0 and db.query(RawFetchResult).count() == 1


@pytest.mark.parametrize('fault', ['date', 'table_date', 'close', 'status'])
def test_invalid_highlight_cannot_publish_stat(db, fault):
    payload = json.loads(json.dumps(FIXTURE['highlight']))
    if fault == 'date':
        payload['date'] = '20261103'
        payload['tables'][0]['date'] = '115/11/03'
    elif fault == 'table_date':
        payload['tables'][0]['date'] = '115/11/03'
    elif fault == 'close':
        payload['tables'][0]['data'][0][5] = '--'
    else:
        payload['stat'] = 'not published'
    calls = []
    result = refresh_taiwan_official_index(db, index_id='TPEX', trade_date=DAY, requested_at=NOW,
        acquisition=index_executor(calls, highlight=payload))
    assert len(calls) == 2 and not result.postcondition_satisfied
    assert db.query(MarketIndexDailyStat).count() == 0 and db.query(RawFetchResult).count() == 2


@pytest.mark.parametrize('shape', ['string', 'short', 'long'])
def test_malformed_highlight_row_retains_receipt_without_stat(db, shape):
    payload = json.loads(json.dumps(FIXTURE['highlight']))
    row = payload['tables'][0]['data'][0]
    payload['tables'][0]['data'] = [
        '0000031000000' if shape == 'string' else row[:-1] if shape == 'short' else row + ['extra']
    ]
    calls = []
    result = refresh_taiwan_official_index(db, index_id='TPEX', trade_date=DAY, requested_at=NOW,
        acquisition=index_executor(calls, highlight=payload))
    assert calls == ['tpex_daily_trading_index', HIGHLIGHT]
    assert not result.postcondition_satisfied
    assert db.query(MarketIndexDailyStat).count() == 0
    assert result.persistence.committed and result.persistence.receipts_written == 2
    assert result.persistence.observations_written == 0
    raw = db.query(RawFetchResult).filter_by(parser_version='tpex.highlight_index_close.v1').one()
    assert raw.status_code == 200 and json.loads(raw.raw_text) == payload
    assert raw.error_message == 'TPEx highlight index row shape mismatch'
    assert 'PAYLOAD_PARSE_FAILED' in result.limitations


def test_index_fallback_obeys_shared_deadline_and_exact_http_params(db, monkeypatch):
    from app.market.providers import tpex
    requests = []
    def fetch(url, **kwargs):
        requests.append((url, kwargs))
        payload = FIXTURE['index'] if 'openapi' in url else FIXTURE['highlight']
        return FakeResponse(text=json.dumps(payload), url=url)
    monkeypatch.setattr(tpex, 'get_response', fetch)
    ticks = iter([0, 0, 30, 30])
    timed = refresh_taiwan_official_index(db, index_id='TPEX', trade_date=DAY, requested_at=NOW,
        acquisition=TaiwanOfficialIndexAcquisitionExecutor(clock=lambda: NOW, monotonic=lambda: next(ticks)))
    assert timed.acquisition.external_calls == 1 and 'TIME_BUDGET_EXHAUSTED' in timed.limitations
    assert db.query(MarketIndexDailyStat).count() == 0
    refresh_taiwan_official_index(db, index_id='TPEX', trade_date=DAY, requested_at=NOW,
        acquisition=TaiwanOfficialIndexAcquisitionExecutor(clock=lambda: NOW))
    assert requests[-1][0] == tpex.MARKET_HIGHLIGHT_URL
    assert requests[-1][1]['params'] == {'date':'2026/11/04', 'response':'json'}
    assert requests[-1][1]['allow_redirects'] is False


def test_real_scheduler_upgrades_partial_then_skips_complete_index(db, monkeypatch):
    from app.jobs import scheduler
    phase, calls = [0], []
    def fetch(route):
        calls.append(route.resource_id)
        if route.resource_id == 'twse_fmtqik':
            # Synthetic already-current peer; the production TPEx receipts stay exact.
            payload = [{'Date':'1151104', 'TAIEX':'30000', 'Change':'1',
                        'TradeVolume':'1000', 'TradeValue':'2000', 'Transaction':'3'}]
        elif route.resource_id == 'tpex_daily_trading_index':
            payload = FIXTURE['index'] if phase[0] == 0 else complete_primary()
        else:
            payload = FIXTURE['highlight']
        return FakeResponse(text=json.dumps(payload))
    acquisition = TaiwanOfficialIndexAcquisitionExecutor(fetchers={resource:fetch for resource in
        ('twse_fmtqik', 'tpex_daily_trading_index', HIGHLIGHT)}, clock=lambda: NOW + timedelta(minutes=5*phase[0]))
    # Only inject external I/O. Real scheduler, read, planner, transaction and resolver execute.
    monkeypatch.setattr(scheduler, 'refresh_taiwan_official_index', lambda *args, **kwargs:
        refresh_taiwan_official_index(*args, **kwargs, acquisition=acquisition))
    first = scheduler._reconcile_taiwan_official_index_rows(db, requested_at=NOW)
    assert first[-1]['status'] == 'postcondition_unsatisfied'
    assert calls == ['twse_fmtqik', 'tpex_daily_trading_index', HIGHLIGHT]
    partial = read_taiwan_official_index(db, index_id='TPEX', trade_date=DAY, requested_at=NOW)
    assert partial.resolved.market_index is None and not partial.resolved.health.facts_usable
    row = db.query(MarketIndexDailyStat).filter_by(index_id='TPEX').one()
    old_raw = row.raw_result_id
    assert row.transaction_count is None
    phase[0] = 1
    second = scheduler._reconcile_taiwan_official_index_rows(db, requested_at=NOW + timedelta(minutes=5))
    assert [item['status'] for item in second] == ['already_current', 'refreshed']
    assert calls == ['twse_fmtqik', 'tpex_daily_trading_index', HIGHLIGHT, 'tpex_daily_trading_index']
    db.refresh(row)
    assert row.raw_result_id != old_raw and row.transaction_count is not None
    assert db.get(RawFetchResult, row.raw_result_id).parser_version == 'tpex.daily_trading_index.v1'
    third = scheduler._reconcile_taiwan_official_index_rows(db, requested_at=NOW + timedelta(minutes=10))
    assert [item['status'] for item in third] == ['already_current', 'already_current']
    assert len(calls) == 4
