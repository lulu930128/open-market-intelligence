"""Production EOD dict continuation and canonical ETF daily replay; fixture IO only."""
from datetime import date, datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine, event

from app.db.models import Base, MarketDailyPrice, MarketDatasetCoverageCheckpoint, StockMaster
from app.db.session import SessionLocal
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import (
    qualify_taiwan_eod_universe, read_taiwan_official_daily, refresh_taiwan_official_daily_venue,
    refresh_taiwan_official_daily,
)
from app.market.tw_universe import list_taiwan_stock_universe
from app.market_data import eod_coverage as owner
from test_tw_official_daily_platform import FakeResponse

DAY = date(2026, 11, 4)
NOW = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'etf.db'}")
    Base.metadata.create_all(engine)
    with SessionLocal(bind=engine) as session:
        assert session.autoflush is False
        yield session
    engine.dispose()


def payload(resource, symbols, day=DAY, *, missing_close=False):
    """Synthetic official schemas, not a claim about real ETF prices or dates."""
    if resource == "MI_INDEX_ALLBUT0999":
        fields = ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差"]
        rows = [[s, s, "1000", "10", "100000", "100", "102", "99", "--" if missing_close else "101", "+", "1"] for s in symbols]
        return {"stat": "OK", "date": day.strftime("%Y%m%d"), "tables": [{"fields": fields, "data": rows,
            "notes": ["本統計資訊僅含一般交易，不含零股、盤後定價、鉅額、拍賣、標購。"],
            "title": "每日收盤行情(全部(不含權證、牛熊證))"}]}
    if resource == "tpex_dated_daily_quotes":
        fields = ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額(元)", "成交筆數"]
        return {"stat": "ok", "date": day.strftime("%Y%m%d"), "tables": [{"date": day.strftime("%Y%m%d"), "fields": fields,
            "data": [[s, s, "--" if missing_close else "101", "1", "100", "102", "99", "100", "1000", "100000", "10"] for s in symbols]}]}
    return [{"Date": day.strftime("%Y%m%d"), "Code": s, "Name": s, "OpeningPrice": "100", "HighestPrice": "102",
             "LowestPrice": "99", "ClosingPrice": "--" if missing_close else "101", "TradeVolume": "1000", "TradeValue": "100000", "Transaction": "10",
             "SecuritiesCompanyCode": s, "CompanyName": s, "Open": "100", "High": "102", "Low": "99", "Close": "--" if missing_close else "101",
             "TradingShares": "1000", "TransactionAmount": "100000", "TransactionNumber": "10"} for s in symbols]


def executor(symbols, calls, *, now=NOW, day=DAY, missing_close=False):
    def fetch(route):
        calls.append(route.resource_id)
        return FakeResponse(text=json.dumps(payload(route.resource_id, symbols, day, missing_close=missing_close), ensure_ascii=False))
    return TaiwanOfficialDailyAcquisitionExecutor(fetchers={r: fetch for r in (
        "MI_INDEX_ALLBUT0999", "STOCK_DAY_ALL", "tpex_mainboard_quotes", "tpex_dated_daily_quotes", "tpex_mainboard_daily_close_quotes")}, clock=lambda: now)


def qualifier(db, *, trade_date, include_published=False):
    # Published breadth is a separate postcondition, fixture-qualified here;
    # all stock/ETF qualification below is the actual canonical repository.
    result = qualify_taiwan_eod_universe(db, trade_date=trade_date)
    result["published_breadth"] = {"TWSE": True, "TPEX": True}
    return result


@pytest.mark.parametrize("venue,symbol,attempted", [
    ("TWSE", "0050", []), ("TWSE", "0050", ["MI_INDEX_ALLBUT0999"]),
    ("TPEX", "006201", []), ("TPEX", "006201", ["tpex_mainboard_quotes"]),
    ("TPEx", "006201", []),
])
def test_production_dict_route_collects_non_watchlist_etf(db, venue, symbol, attempted):
    db.add_all([StockMaster(stock_id=symbol, market=venue, instrument_type="etf"),
                StockMaster(stock_id="009999", market=venue, instrument_type="etf", is_active=False)])
    db.commit()
    state = {"version": 1, "venue": venue, "trade_date": DAY.isoformat(), "attempted_resources": attempted} if attempted else {}
    calls = []
    result = refresh_taiwan_official_daily_venue(db, venue=venue, trade_date=DAY, requested_at=NOW,
        route_state=state, refresh_published=False, acquisition=executor([symbol], calls))
    assert result["inserted_count"] == 1
    read = read_taiwan_official_daily(db, stock_id=symbol, from_date=DAY, to_date=DAY, requested_at=NOW)
    bar = read.resolved.bars[0]
    assert (bar.instrument.symbol, bar.instrument.venue, bar.instrument.instrument_type.value) == (symbol, venue.upper(), "etf")
    assert bar.finalization.value == "final" and bar.end_at.date() == DAY
    assert bar.lineage.raw_receipt_id == f"raw_fetch_result:{result['raw_result_id']}"
    assert db.query(MarketDailyPrice).count() == 1 and list_taiwan_stock_universe(db) == []
    assert owner.compute_eod_coverage(db, market="TW", expected_trade_date=DAY, taiwan_daily_qualifier=qualifier).etf_coverage.current_symbols == {symbol}


def test_stock_complete_etf_missing_drives_existing_job_and_preserves_stock(db, monkeypatch):
    db.add(StockMaster(stock_id="2330", market="TWSE", instrument_type="stock")); db.commit()
    refresh_taiwan_official_daily_venue(db, venue="TWSE", trade_date=DAY, requested_at=NOW,
        route_state={}, refresh_published=False, acquisition=executor(["2330"], []))
    stock = db.query(MarketDailyPrice).one()
    before = (stock.id, stock.raw_result_id, stock.updated_at)
    monkeypatch.setattr(owner, "utc_now", lambda: NOW)
    old = owner.reconcile_eod_coverage(db, market="TW", expected_trade_date=DAY, taiwan_daily_qualifier=qualifier)
    assert old["postcondition_met"] and old["attempted_count"] == 0
    checkpoint = db.get(MarketDatasetCoverageCheckpoint, old["checkpoint"]["id"])
    detail = json.loads(checkpoint.detail_json)
    detail["venue_route_states"] = {"TWSE": {"version": 1, "venue": "TWSE", "trade_date": DAY.isoformat(),
        "attempted_resources": ["MI_INDEX_ALLBUT0999"]}}
    checkpoint.detail_json = json.dumps(detail); db.commit()
    db.add(StockMaster(stock_id="0050", market="TWSE", instrument_type="etf")); db.commit()
    coverage = owner.compute_eod_coverage(db, market="TW", expected_trade_date=DAY, taiwan_daily_qualifier=qualifier, include_published=True)
    assert coverage.current_count == coverage.universe_count == 1
    assert not coverage.postcondition_met
    pending = owner.persist_eod_coverage(db, coverage)
    assert pending.repair_status != "complete" and "venue_route_states" not in json.loads(pending.detail_json)
    assert owner.should_enqueue_eod_reconcile(db, market="TW", expected_trade_date=DAY, now=NOW, taiwan_daily_qualifier=qualifier)
    calls = []
    states = []
    def refresh(db, **kwargs):
        states.append(kwargs["route_state"])
        return refresh_taiwan_official_daily_venue(db, **kwargs, requested_at=NOW, acquisition=executor(["2330", "0050"], calls))
    result = owner.reconcile_eod_coverage(db, market="TW", expected_trade_date=DAY, taiwan_daily_qualifier=qualifier,
        taiwan_venue_refresher=refresh, max_runtime_seconds=30)
    assert states == [{}] and result["postcondition_met"] and result["current_count"] == result["universe_count"] == 1
    etf = result["checkpoint"]["detail"]["etf_coverage"]
    assert etf["universe_count"] == etf["current_count"] == 1 and etf["postcondition_met"]
    db.expire_all(); stock = db.get(MarketDailyPrice, before[0])
    assert (stock.id, stock.raw_result_id, stock.updated_at) == before
    assert [s.stock_id for s in list_taiwan_stock_universe(db)] == ["2330"]
    assert not owner.should_enqueue_eod_reconcile(db, market="TW", expected_trade_date=DAY, now=NOW, taiwan_daily_qualifier=qualifier)


def test_missing_etf_retries_pending_resource_in_fresh_session(db, monkeypatch):
    db.add(StockMaster(stock_id="6182", market="TPEX", instrument_type="stock")); db.commit()
    refresh_taiwan_official_daily_venue(db, venue="TPEX", trade_date=DAY, requested_at=NOW,
        route_state={}, refresh_published=False, acquisition=executor(["6182"], []))
    db.add(StockMaster(stock_id="006201", market="TPEX", instrument_type="etf")); db.commit()
    at = NOW
    monkeypatch.setattr(owner, "utc_now", lambda: at)
    calls = []
    def run(session, missing):
        def refresh(db, **kwargs):
            return refresh_taiwan_official_daily_venue(db, **kwargs, requested_at=at,
                acquisition=executor(["6182", "006201"], calls, now=at, missing_close=missing))
        return owner.reconcile_eod_coverage(session, market="TW", expected_trade_date=DAY,
            max_symbols=2, error_backoff_seconds=60, taiwan_daily_qualifier=qualifier, taiwan_venue_refresher=refresh)
    first = run(db, True)
    assert not first["postcondition_met"] and first["current_count"] == first["universe_count"] == 1
    assert first["etf_coverage"]["missing_count"] == 1 and first["etf_coverage"]["postcondition_met"] is False
    assert len(calls) == 2
    pending_resources = first["checkpoint"]["detail"]["venue_route_states"]["TPEX"]["pending_resources"]
    previous_calls = set(calls)
    with SessionLocal(bind=db.get_bind()) as fresh:
        assert not owner.should_enqueue_eod_reconcile(fresh, market="TW", expected_trade_date=DAY,
            now=NOW + timedelta(seconds=59), taiwan_daily_qualifier=qualifier)
        at = NOW + timedelta(seconds=60)
        assert owner.should_enqueue_eod_reconcile(fresh, market="TW", expected_trade_date=DAY, now=at, taiwan_daily_qualifier=qualifier)
        second = run(fresh, False)
        assert second["postcondition_met"] and second["etf_coverage"]["current_count"] == 1
        assert calls[-1] in pending_resources and calls[-1] not in previous_calls and len(calls) == 3
        assert first["checkpoint"]["id"] == second["checkpoint"]["id"]
        assert read_taiwan_official_daily(fresh, stock_id="006201", from_date=DAY, to_date=DAY, requested_at=at).resolved.bars


def test_alias_single_refresh_batch_and_cache_only_reread(db):
    db.add(StockMaster(stock_id="0050", market="TWSE", instrument_type="exchange_traded_fund")); db.commit()
    result = refresh_taiwan_official_daily(db, stock_id="0050", trade_date=DAY,
        requested_at=NOW, acquisition=executor(["0050"], []))
    assert result.persistence.committed
    assert db.query(MarketDailyPrice).one().instrument_type == "etf"
    statements = []
    def record(_c, _cu, statement, *_args): statements.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        read = read_taiwan_official_daily(db, stock_id="0050", from_date=DAY, to_date=DAY, requested_at=NOW)
        scope = owner.compute_eod_coverage(db, market="TW", expected_trade_date=DAY, taiwan_daily_qualifier=qualifier)
        assert read.requirement.target.instrument.instrument_type.value == read.resolved.bars[0].instrument.instrument_type.value == "etf"
        assert scope.etf_coverage.current_symbols == {"0050"} and scope.universe_count == 0
        assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    owner.persist_eod_coverage(db, scope)
    assert not owner.should_enqueue_eod_reconcile(db, market="TW", expected_trade_date=DAY, now=NOW, taiwan_daily_qualifier=qualifier)


def test_expected_date_and_etf_early_to_final_remain_distinct(db):
    day = date(2026, 11, 5)
    assert owner.expected_eod_trade_date("TW", now=datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)) == DAY
    early = datetime(2026, 11, 5, 6, 35, tzinfo=timezone.utc)
    assert owner.expected_eod_trade_date("TW", now=early) == DAY
    final = datetime(2026, 11, 5, 7, 20, tzinfo=timezone.utc)
    assert owner.expected_eod_trade_date("TW", now=final) == day
    db.add(StockMaster(stock_id="0050", market="TWSE", instrument_type="etf")); db.commit()
    result = refresh_taiwan_official_daily_venue(db, venue="TWSE", trade_date=day, requested_at=early,
        route_state={}, refresh_published=False, acquisition=executor(["0050"], [], now=early, day=day))
    assert result["research_ready_count"] == 1 and result["release_status"] == "regular_research"
    research = read_taiwan_official_daily(db, stock_id="0050", from_date=day, to_date=day, requested_at=early, allow_early_regular=True)
    assert research.resolved.bars and "OFFICIAL_FINAL_PENDING" in research.resolved.bars[0].limitations
    assert not read_taiwan_official_daily(db, stock_id="0050", from_date=day, to_date=day, requested_at=final).resolved.bars
    assert not owner.compute_eod_coverage(db, market="TW", expected_trade_date=day, taiwan_daily_qualifier=qualifier).postcondition_met
    refresh_taiwan_official_daily_venue(db, venue="TWSE", trade_date=day, requested_at=final,
        route_state=result["route_continuation"], refresh_published=False, acquisition=executor(["0050"], [], now=final, day=day))
    completed = read_taiwan_official_daily(db, stock_id="0050", from_date=day, to_date=day, requested_at=final)
    assert completed.resolved.bars[0].finalization.value == "final"
    assert "OFFICIAL_FINAL_PENDING" not in completed.resolved.bars[0].limitations
