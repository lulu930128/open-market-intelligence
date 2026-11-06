"""TAIEX monthly fallback through the real acquisition/transaction/reread owner."""
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine
from app.db.models import Base, MarketIndexDailyStat, RawFetchResult, SourceRegistry
from app.db.session import SessionLocal
from app.market.official_index_acquisition import TaiwanOfficialIndexAcquisitionExecutor
from app.market.official_index_platform import refresh_taiwan_official_index, read_taiwan_official_index
from app.market.providers import twse
from app.market.providers.tw_official_index import TWSE_INDEX_RESOURCE_ID
from test_tw_official_index_platform import FakeResponse

DAY = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)
RWD = "twse_rwd_fmtqik"
FIELDS = ["日期", "成交股數", "成交金額", "成交筆數", "發行量加權股價指數", "漲跌點數"]


def monthly():
    return {"stat": "OK", "date": "20261101", "fields": FIELDS,
            "data": [["115/11/04", "1,000", "2,000", "100", "42,000", "-20"],
                     ["115/11/05", "1,100", "2,100", "110", "41,574.72", "-1,374.19"]]}


def primary(current=False):
    return [{"Date": "1151105" if current else "1151104", "TradeVolume": "1000", "TradeValue": "2000",
             "Transaction": "100", "TAIEX": "42000", "Change": "-20"}]


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'index.db'}")
    Base.metadata.create_all(engine)
    with SessionLocal(bind=engine) as db:
        assert not db.autoflush
        yield db
    engine.dispose()


def run(db, *, body=None, current=False, deadline=False):
    calls, elapsed = [], [0]
    body = monthly() if body is None else body
    def fetch(route):
        calls.append(route.resource_id)
        if deadline:
            elapsed[0] += 31
        value = primary(current) if route.resource_id == TWSE_INDEX_RESOURCE_ID else body
        url = twse.MARKET_DAILY_URL if route.resource_id == TWSE_INDEX_RESOURCE_ID else twse.MARKET_DAILY_HISTORY_URL + "?date=20261101&response=json"
        return FakeResponse(text=json.dumps(value, ensure_ascii=False), url=url)
    acquisition = TaiwanOfficialIndexAcquisitionExecutor(fetchers={TWSE_INDEX_RESOURCE_ID: fetch, RWD: fetch},
        clock=lambda: NOW, monotonic=lambda: elapsed[0])
    return refresh_taiwan_official_index(db, index_id="TAIEX", trade_date=DAY,
        requested_at=NOW, acquisition=acquisition), calls


def test_stale_primary_rwd_exact_day_upgrades_legacy_row_with_real_lineage(db):
    legacy = MarketIndexDailyStat(index_id="TAIEX", market="TWSE", trade_date=DAY,
        close_value=123, price_change=-1, source="twse_rwd_fmtqik")
    db.add(legacy); db.commit(); row_id = legacy.id
    result, calls = run(db)
    assert result.postcondition_satisfied and calls == [TWSE_INDEX_RESOURCE_ID, RWD]
    assert result.acquisition.external_calls == 2 and result.persistence.committed
    db.expire_all(); row = db.query(MarketIndexDailyStat).one()
    assert row.id == row_id and row.trade_date == DAY and row.close_value == 41574.72
    raw = db.get(RawFetchResult, row.raw_result_id); source = db.get(SourceRegistry, row.source_id)
    assert raw.source_id == source.id and source.source_name == "TWSE Official Market Index Daily"
    assert raw.parser_version == "twse.rwd_fmtqik.v1" and raw.url.endswith("date=20261101&response=json")
    assert raw.content_hash == sha256(raw.raw_text.encode()).hexdigest()
    assert db.query(RawFetchResult).count() == 2
    read = read_taiwan_official_index(db, index_id="TAIEX", trade_date=DAY, requested_at=NOW)
    assert read.resolved.market_index.lineage.provider == "twse_rwd"
    assert read.resolved.market_index.lineage.content_hash == raw.content_hash
    assert read.resolved.health.facts_usable and read.resolved.health.research_usable


def test_current_openapi_still_costs_one_call_and_keeps_identity(db):
    result, calls = run(db, current=True)
    assert result.postcondition_satisfied and calls == [TWSE_INDEX_RESOURCE_ID]
    assert result.result.resolved.market_index.lineage.provider == "twse_openapi"


@pytest.mark.parametrize("kind", ["non_ok", "row_string", "misaligned", "header", "close", "change", "negative", "no_exact_day"])
def test_invalid_or_missing_rwd_target_keeps_receipts_without_stat(db, kind):
    body = deepcopy(monthly())
    if kind == "non_ok": body["stat"] = "查無資料"
    elif kind == "row_string": body["data"] = ["0000031000000"]
    elif kind == "misaligned": body["data"][1].pop()
    elif kind == "header": body["fields"] = list(reversed(FIELDS))
    elif kind == "close": body["data"][1][4] = "--"
    elif kind == "change": body["data"][1][5] = "--"
    elif kind == "negative": body["data"][1][1] = "-1"
    else:
        body["date"] = "20261105"  # Header cannot manufacture exact row evidence.
        body["data"] = body["data"][:1]
    result, calls = run(db, body=body)
    assert calls == [TWSE_INDEX_RESOURCE_ID, RWD] and not result.postcondition_satisfied
    assert result.persistence.committed and db.query(RawFetchResult).count() == 2
    assert db.query(MarketIndexDailyStat).count() == 0
    assert not result.result.resolved.health.facts_usable


def test_shared_deadline_does_not_start_fallback(db):
    result, calls = run(db, deadline=True)
    assert calls == [TWSE_INDEX_RESOURCE_ID] and not result.postcondition_satisfied
    assert "TIME_BUDGET_EXHAUSTED" in result.acquisition.limitations
    assert db.query(RawFetchResult).count() == 1 and db.query(MarketIndexDailyStat).count() == 0


def test_default_rwd_fetch_uses_target_month_and_actual_receipt_url(db, monkeypatch):
    from app.market.official_index_contract import TWSE_RWD_INDEX_PARSER_VERSION
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        if url == twse.MARKET_DAILY_URL:
            return FakeResponse(text=json.dumps(primary()), url=url)
        assert url == twse.MARKET_DAILY_HISTORY_URL
        assert kwargs["params"] == {"date": "20261101", "response": "json"}
        assert 0 < kwargs["timeout_seconds"] <= 30
        return FakeResponse(text=json.dumps(monthly()), url=url + "?date=20261101&response=json")
    monkeypatch.setattr(twse, "get_response", fetch)
    executor = TaiwanOfficialIndexAcquisitionExecutor(clock=lambda: NOW)
    result = refresh_taiwan_official_index(db, index_id="TAIEX", trade_date=DAY, requested_at=NOW, acquisition=executor)
    assert result.postcondition_satisfied and len(calls) == 2
    raw = db.query(RawFetchResult).filter_by(parser_version=TWSE_RWD_INDEX_PARSER_VERSION).one()
    assert raw.url == calls[-1][0] + "?date=20261101&response=json"


@pytest.mark.parametrize("dataset_id,operation,calls,seconds,symbols", [
    ("tw.market_index.daily", "tw.refresh_official_market_index", 2, 30, 1),
    ("tw.daily.ohlcv.full_market", "tw.reconcile_full_market_eod", 6, 120, 6),
    ("tw.market_breadth.daily", "tw.reconcile_full_market_eod", 6, 120, 6),
])
def test_catalog_registry_and_operation_bounds_agree(dataset_id, operation, calls, seconds, symbols):
    from app.market.tw_dataset_catalog import TW_DATASET_CATALOG
    from app.market_data.registry import DATASET_REGISTRY, RefreshBounds
    expected = RefreshBounds(max_calls=calls, timeout_seconds=seconds, max_symbols=symbols, max_range_days=1)
    assert DATASET_REGISTRY.get(dataset_id).refresh_bounds == expected
    assert TW_DATASET_CATALOG.get(dataset_id).refresh_bounds == expected
    assert TW_DATASET_CATALOG.operation(operation).bounds == expected
