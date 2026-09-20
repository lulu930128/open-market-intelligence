from datetime import date, datetime, timezone
import json

import pytest
from sqlalchemy import event

from app.db.models import RawFetchResult, StockMaster
from app.market.daily_ohlcv_platform import qualify_taiwan_eod_universe
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market_data.eod_coverage import compute_eod_coverage
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
from test_tw_daily_candidate_repository import db, _source_and_raw, _daily_row, _query


@pytest.mark.parametrize("defect,reason", [
    ("close_only", "DAILY_REQUIRED_OHLC_MISSING"),
    ("early_receipt", "DAILY_RECEIPT_BEFORE_RELEASE"),
    ("wrong_source", "DAILY_SOURCE_NOT_QUALIFIED"),
    ("receipt_identity", "DAILY_LINEAGE_IDENTITY_MISMATCH"),
])
def test_close_present_is_insufficient_and_batch_matches_candidate_qualification(db, defect, reason):
    source, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type="twse_daily", priority=10)
    row = _daily_row(source=source, raw=raw, trade_date=date(2026, 8, 21))
    db.add(StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"))
    if defect == "close_only":
        row.open_price = None
    elif defect == "early_receipt":
        raw.fetched_at = datetime(2026, 8, 21, 7, 14, tzinfo=timezone.utc)
    elif defect == "wrong_source":
        source.source_name = "unqualified_source"
    else:
        other, other_raw = _source_and_raw(db, source_name="other", parser_type="other", priority=99)
        row.raw_result_id = other_raw.id
    db.add(row)
    db.commit()
    coverage = compute_eod_coverage(db, market="TW", expected_trade_date=row.trade_date, taiwan_daily_qualifier=qualify_taiwan_eod_universe)
    assert coverage.current_count == 0
    assert coverage.partial_symbols == {"2330"}
    assert reason in coverage.qualification_reasons["2330"]
    candidates = TaiwanOfficialDailyBarRepository(db).load_daily_bars(_query())
    assert not candidates.series


def test_provider_no_ohlc_absent_symbol_and_transport_failure_remain_separate(db):
    source, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type="twse_daily", priority=10)
    raw.raw_text = json.dumps([{"Date": "20260821", "Code": "1213", "OpeningPrice": "--", "ClosingPrice": "--", "TradeVolume": "3000"}])
    db.add_all([StockMaster(stock_id=symbol, market="TWSE", instrument_type="stock") for symbol in ("1213", "1589")])
    db.add(RawFetchResult(source_id=source.id, fetched_at=datetime(2026, 8, 24, 9, tzinfo=timezone.utc), status_code=503, error_message="provider unavailable"))
    db.commit()
    statements = []
    def observe(_conn, _cursor, sql, _params, _ctx, _many):
        statements.append(sql)
    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        coverage = compute_eod_coverage(db, market="TW", expected_trade_date=date(2026, 8, 21), taiwan_daily_qualifier=qualify_taiwan_eod_universe)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)
    assert coverage.missing_symbols == {"1213", "1589"}
    assert coverage.qualification_reasons["1213"] == ("PROVIDER_REQUIRED_OHLC_MISSING",)
    assert coverage.qualification_reasons["1589"] == ("SYMBOL_ABSENT_FROM_DATED_PROVIDER_PAYLOAD",)
    assert {row["transport_status"] for row in coverage.provider_diagnostics} == {"received", "failed"}
    assert len(statements) <= 10
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)


def test_shared_coverage_fails_closed_without_market_qualification_port(db):
    db.add(StockMaster(stock_id="2330", market="TWSE", instrument_type="stock"))
    db.commit()
    with pytest.raises(ValueError, match="canonical Daily qualification port"):
        compute_eod_coverage(db, market="TW", expected_trade_date=date(2026, 8, 21))
