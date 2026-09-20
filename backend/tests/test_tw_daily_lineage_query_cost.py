"""Canonical validation must not lazy-load receipts or their raw payloads."""
from datetime import date

from sqlalchemy import event

from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
from test_tw_daily_candidate_repository import db, _source_and_raw, _daily_row, _query


def test_candidate_lineage_is_loaded_in_one_bounded_query(db):
    source, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME, parser_type="twse_daily", priority=10)
    db.add(_daily_row(source=source, raw=raw, trade_date=date(2026, 8, 21)))
    db.commit()
    db.expunge_all()
    statements = []
    def observe(_conn, _cursor, sql, _params, _ctx, _many):
        statements.append(sql)
    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        repository = TaiwanOfficialDailyBarRepository(db)
        result = repository.load_daily_bars(_query())
        assert result.series
        assert len(statements) == 1
        db.expunge_all()
        statements.clear()
        assert repository.latest_candidate_start_date(
            instrument=_query().instrument, end_date=date(2026, 8, 21), max_rows=80,
        ) == date(2026, 8, 21)
        assert len(statements) == 1
        assert "raw_text" not in statements[0]
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)
