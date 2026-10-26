"""Offline replay of stored public receipts, not live provider acceptance."""
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from app.db.models import MarketDailyPrice, RawFetchResult, StockMaster
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue
from app.market.providers.tw_official_daily import (
    TPEX_DAILY_RESOURCE_ID, TWSE_RWD_DAILY_RESOURCE_ID,
    parse_tpex_official_daily_payload, parse_twse_rwd_official_daily_payload,
)
from test_tw_public_quote_platform import db
from test_tw_official_daily_platform import FakeResponse


def test_oct12_twse_current_tpex_stale_receipt_replays_without_inventing_daily(db, monkeypatch):
    def reject_default_fetch(*args, **kwargs):
        raise AssertionError("Replay must use only explicitly supplied fixture fetchers")
    monkeypatch.setattr("app.market.daily_ohlcv_acquisition._default_fetch", reject_default_fetch)
    fixture = json.loads((Path(__file__).parent / "fixtures/tw_market_data/g6_daily_received_excerpt.json").read_text(encoding="utf-8"))
    tpex_text = json.dumps(fixture["tpex"], ensure_ascii=False)
    twse_text = json.dumps(fixture["twse"], ensure_ascii=False)
    tpex = parse_tpex_official_daily_payload(tpex_text, target_symbols=frozenset({"3324"}))
    twse = parse_twse_rwd_official_daily_payload(twse_text, target_symbols=frozenset({"2883"}))
    assert [(r.trade_date, r.close_price) for r in tpex.records] == [(date(2026, 10, 8), Decimal("1520"))]
    assert [(r.trade_date, r.close_price) for r in twse.records] == [(date(2026, 10, 12), Decimal("38.8"))]
    db.add_all([StockMaster(stock_id=symbol, stock_name="Synthetic replay", market=venue,
        instrument_type="stock", is_active=True) for symbol, venue in [("3324", "TPEX"), ("2883", "TWSE")]])
    db.commit()
    now = datetime.fromisoformat("2026-10-12T15:40:00+08:00")
    calls = []
    def fetch(route):
        calls.append(route.resource_id)
        return FakeResponse(text=tpex_text if route.resource_id == TPEX_DAILY_RESOURCE_ID else twse_text)
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={
        TPEX_DAILY_RESOURCE_ID: fetch, TWSE_RWD_DAILY_RESOURCE_ID: fetch,
    }, clock=lambda: now)
    stale = refresh_taiwan_official_daily_venue(db, venue="TPEX", trade_date=now.date(), requested_at=now, acquisition=executor, max_external_calls=1)
    assert stale["parsed_count"] == 0
    assert stale["replaced_trade_dates"] == []
    assert db.query(MarketDailyPrice).filter(MarketDailyPrice.stock_id == "3324").count() == 0
    assert db.query(RawFetchResult).count() == 1  # Failed qualification retains receipt only.
    fresh = refresh_taiwan_official_daily_venue(db, venue="TWSE", trade_date=now.date(), requested_at=now, acquisition=executor)
    assert fresh["parsed_count"] == 1
    row = db.query(MarketDailyPrice).filter(MarketDailyPrice.stock_id == "2883").one()
    assert row.trade_date == now.date() and row.close_price == 38.8
    assert row.authority == "exchange" and row.finalization == "final" and row.release_status == "released"
    assert calls == [TPEX_DAILY_RESOURCE_ID, TWSE_RWD_DAILY_RESOURCE_ID]
