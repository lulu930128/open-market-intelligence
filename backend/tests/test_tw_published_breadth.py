from datetime import date, datetime, timezone
import copy
import json

import pytest
from sqlalchemy import event

from app.db.models import MarketDailyPrice, RawFetchResult, StockMaster, TaiwanPublishedBreadthSnapshot
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue
from app.market.official_breadth_platform import read_taiwan_official_breadth, project_taiwan_official_breadth
from app.parsers.twse_published_breadth import parse_twse_published_breadth
from app.market.providers.tw_official_daily import TWSE_RWD_DAILY_RESOURCE_ID
from test_tw_official_daily_platform import db, FakeResponse, _fixture

DAY = date(2026, 8, 27)
NOW = datetime(2026, 8, 27, 10, 30, tzinfo=timezone.utc)


def payload():
    raw = copy.deepcopy(_fixture("twse_mi_index_allbut0999_excerpt_20260827.json")["payload"])
    raw["tables"] = [t for t in raw["tables"] if t.get("title") != "漲跌證券數合計"]
    raw["tables"].append({"title": "漲跌證券數合計", "fields": ["類型", "整體市場", "股票"],
        "data": [["上漲(漲停)", "999(99)", "20(3)"], ["下跌(跌停)", "999(99)", "8(1)"],
                 ["持平", "999", "2"], ["未成交", "999", "3"], ["無比價", "999", "1"]]})
    return raw


def test_strict_stock_column_partition_and_missing_evidence():
    source = payload()
    result = parse_twse_published_breadth(json.dumps(source), trade_date=DAY)
    assert result.limits.universe_count == 34
    assert result.limits.up_count == 3
    assert result.limits.down_count == 1
    assert result.no_comparison == 1
    mutations = [
        lambda p: p.pop("date"),
        lambda p: p.update(date="20260826"),
        lambda p: p["tables"][-1]["fields"].__setitem__(2, "其他"),
        lambda p: p["tables"][-1]["data"].pop(),
        lambda p: p["tables"][-1]["data"].append(p["tables"][-1]["data"][0]),
        lambda p: p["tables"][-1]["data"][0].__setitem__(2, "20"),
        lambda p: p["tables"][-1]["data"][0].__setitem__(2, "20(21)"),
    ]
    for mutate in mutations:
        broken = copy.deepcopy(source)
        mutate(broken)
        with pytest.raises(ValueError):
            parse_twse_published_breadth(json.dumps(broken), trade_date=DAY)


def acquire(db, raw):
    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={TWSE_RWD_DAILY_RESOURCE_ID: lambda _: FakeResponse(text=json.dumps(raw))},
        clock=lambda: NOW, monotonic=lambda: 10.0,
    )
    return refresh_taiwan_official_daily_venue(db, venue="TWSE", trade_date=DAY,
        requested_at=NOW, acquisition=executor)


def test_acquisition_persistence_cache_read_and_temporal_gates(db):
    db.add(StockMaster(stock_id="3711", stock_name="test", market="TWSE", instrument_type="stock", is_active=True))
    db.commit()
    acquire(db, payload())
    stored = db.query(TaiwanPublishedBreadthSnapshot).one()
    assert stored.error_code is None
    assert stored.raw_result_id == db.query(RawFetchResult).one().id
    statements = []
    def capture(_c, _cursor, statement, *_): statements.append(statement.lower())
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        result = read_taiwan_official_breadth(db, venue="TWSE", trade_date=DAY, requested_at=NOW)
        outward = project_taiwan_official_breadth(result)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert outward["limit_up_count"] == 3
    assert outward["limit_down_count"] == 1
    assert outward["scope"] == "twse_published_stock_aggregate"
    assert outward["total_count"] == 34
    assert outward["published_limits"]["basis"] == "exchange_published_aggregate"
    assert result.resolved.breadth.limits is None
    assert all("raw_text" not in statement for statement in statements)
    assert not any(statement.lstrip().startswith(("insert", "update", "delete")) for statement in statements)
    before = read_taiwan_official_breadth(db, venue="TWSE", trade_date=DAY,
        requested_at=datetime(2026, 8, 27, 7, 0, tzinfo=timezone.utc))
    assert before.resolved.breadth is None
    raw = db.query(RawFetchResult).one()
    raw.fetched_at = datetime(2026, 8, 27, 7, 0)
    db.commit()
    assert read_taiwan_official_breadth(db, venue="TWSE", trade_date=DAY, requested_at=NOW).resolved.breadth is None


def test_bad_aggregate_does_not_fabricate_totals_or_discard_daily_bar(db):
    db.add(StockMaster(stock_id="3711", stock_name="test", market="TWSE", instrument_type="stock", is_active=True))
    db.commit()
    raw = payload()
    raw["tables"][-1]["data"].pop()
    acquire(db, raw)
    assert db.query(TaiwanPublishedBreadthSnapshot).one().error_code == "OFFICIAL_AGGREGATE_RECEIPT_REJECTED"
    result = read_taiwan_official_breadth(db, venue="TWSE", trade_date=DAY, requested_at=NOW)
    assert result.resolved.breadth is not None
    assert result.resolved.breadth.published_limits is None
    assert "OFFICIAL_AGGREGATE_RECEIPT_REJECTED" in result.limitations


def test_published_companion_rolls_back_with_daily_transaction(db, monkeypatch):
    from app.market.daily_price_transaction import TaiwanOfficialDailyTransaction

    db.add(StockMaster(stock_id="3711", stock_name="test", market="TWSE", instrument_type="stock", is_active=True))
    db.commit()
    def fail(*args, **kwargs):
        raise RuntimeError("transaction failure")
    monkeypatch.setattr(TaiwanOfficialDailyTransaction, "_quality_check", fail)
    with pytest.raises(RuntimeError, match="transaction failure"):
        acquire(db, payload())
    assert db.query(TaiwanPublishedBreadthSnapshot).count() == 0
    assert db.query(RawFetchResult).count() == 0
    assert db.query(MarketDailyPrice).count() == 0
