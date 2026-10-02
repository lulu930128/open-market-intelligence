from datetime import datetime, timedelta, timezone
from unittest.mock import patch, Mock

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db.models import Base, MarketRefreshPriority, StockMaster, USStockMaster
from app.config import settings
from app.jobs.market_refresh_priority import active_market_refresh_priorities, request_market_refresh_priority
from app.market_data.eod_coverage import reconcile_eod_coverage
from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE
from test_eod_coverage import EXPECTED, _us_daily_row


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    engine.dispose()


@pytest.mark.parametrize("market,venue,symbol", [("US", "NASDAQ", "AMD"), ("TW", "TWSE", "2330")])
@pytest.mark.parametrize("remaining_seconds", [60, -60], ids=["active", "expired"])
def test_priority_renewal_preserves_identity_and_cleans_only_expired_rows(
    db, monkeypatch, market, venue, symbol, remaining_seconds,
):
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(settings, "market_refresh_priority_ttl_seconds", 300)
    instrument = (USStockMaster(symbol=symbol, exchange=venue, is_active=True) if market == "US"
                  else StockMaster(stock_id=symbol, market=venue, is_active=True))
    target = MarketRefreshPriority(
        market=market, venue=venue, symbol=symbol,
        requested_at=now - timedelta(minutes=5), expires_at=now + timedelta(seconds=remaining_seconds),
    )
    others = [MarketRefreshPriority(
        market="US", venue="NYSE", symbol=name,
        requested_at=now - timedelta(minutes=5), expires_at=now + timedelta(seconds=seconds),
    ) for name, seconds in (("EXPIRED", -1), ("ACTIVE", 120), ("BOUNDARY", 0))]
    db.add_all([instrument, target, *others])
    db.commit()
    target_id = target.id
    statements = []

    def record_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.upper())

    event.listen(db.get_bind(), "before_cursor_execute", record_sql)
    try:
        result = request_market_refresh_priority(db, market=market, symbol=symbol, now=now)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record_sql)

    assert result == {"status": "prioritized", "market": market, "venue": venue,
                      "symbol": symbol, "expires_at": (now + timedelta(seconds=300)).isoformat()}
    writes = [sql for sql in statements if sql.startswith(("UPDATE MARKET_REFRESH_PRIORITY", "DELETE FROM MARKET_REFRESH_PRIORITY"))]
    assert len(writes) == 2
    assert writes[0].startswith("UPDATE MARKET_REFRESH_PRIORITY")
    assert writes[1].startswith("DELETE FROM MARKET_REFRESH_PRIORITY")
    # Verify committed values in a fresh identity map, not the renewed ORM object.
    with Session(db.get_bind(), autoflush=False) as reader:
        rows = reader.execute(select(MarketRefreshPriority)).scalars().all()
        assert len(rows) == 3
        assert {row.symbol for row in rows} == {symbol, "ACTIVE", "BOUNDARY"}
        renewed = next(row for row in rows if row.symbol == symbol)
        assert (renewed.id, renewed.market, renewed.venue) == (target_id, market, venue)
        assert renewed.requested_at.replace(tzinfo=timezone.utc) == now
        assert renewed.expires_at.replace(tzinfo=timezone.utc) == now + timedelta(seconds=300)
        active = next(row for row in rows if row.symbol == "ACTIVE")
        assert active.requested_at.replace(tzinfo=timezone.utc) == now - timedelta(minutes=5)
        assert active.expires_at.replace(tzinfo=timezone.utc) == now + timedelta(seconds=120)


def test_priority_insert_race_recovers_savepoint_and_preserves_caller_work(db, monkeypatch):
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    db.add(USStockMaster(symbol="AMD", exchange="NASDAQ", is_active=True))
    winner = MarketRefreshPriority(
        market="US", venue="NASDAQ", symbol="AMD",
        requested_at=now - timedelta(hours=1), expires_at=now - timedelta(seconds=1),
    )
    db.add(winner)
    db.commit()
    winner_id = winner.id
    db.add(USStockMaster(symbol="CALLER", exchange="NYSE", is_active=True))
    # Keep caller work in the outer transaction, persisted but not committed.
    db.flush()
    execute = db.execute
    missed = False

    def miss_first_priority_select(statement, *args, **kwargs):
        nonlocal missed
        if not missed and getattr(statement, "is_select", False) and "market_refresh_priority" in str(statement):
            missed = True
            # Deterministic stale SELECT; the insert still hits the real unique
            # constraint and must roll back only its nested transaction.
            return execute(statement.where(False), *args, **kwargs)
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", miss_first_priority_select)
    with patch.object(db, "begin_nested", wraps=db.begin_nested) as nested:
        result = request_market_refresh_priority(db, market="US", symbol="AMD", now=now)
    assert missed
    nested.assert_called_once()
    assert result["status"] == "prioritized"
    with Session(db.get_bind(), autoflush=False) as reader:
        renewed = reader.execute(select(MarketRefreshPriority)).scalar_one()
        assert renewed.id == winner_id
        assert renewed.requested_at.replace(tzinfo=timezone.utc) == now
        assert renewed.expires_at.replace(tzinfo=timezone.utc).isoformat() == result["expires_at"]
        assert reader.execute(select(USStockMaster).where(USStockMaster.symbol == "CALLER")).scalar_one()


def test_priority_persists_deduplicates_expires_and_rejects_unknown(db):
    db.add_all([StockMaster(stock_id="2330", market="TWSE", is_active=True),
                USStockMaster(symbol="TSM", exchange="NYSE", is_active=True)])
    db.commit()
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    for _ in range(2):
        assert request_market_refresh_priority(db, market="US", symbol="tsm", now=now)["venue"] == "NYSE"
    assert len(db.execute(select(MarketRefreshPriority)).scalars().all()) == 1
    assert active_market_refresh_priorities(db, market="US", now=now) == ("TSM",)
    assert active_market_refresh_priorities(db, market="TW", now=now) == ()
    assert active_market_refresh_priorities(db, market="US", now=now + timedelta(hours=3)) == ()
    assert request_market_refresh_priority(db, market="TW", symbol="UNKNOWN", now=now)["status"] == "not_registered"


def test_priority_can_arrive_between_symbols_and_preserves_background_dispatch(db):
    symbols = tuple("ABCDEFG")
    db.add_all([USStockMaster(symbol=s, exchange="NYSE", asset_type="stock", is_active=True) for s in symbols])
    db.commit()
    calls = []
    def refresh(db, *, symbol, **kwargs):
        calls.append(symbol)
        db.add(_us_daily_row(db, symbol=symbol, trade_date=EXPECTED, close_price=20))
        db.commit()
    def priorities():
        return ("G", "F", "E", "D") if calls else ()
    with patch.object(US_FULL_MARKET_EOD_LIFECYCLE, "refresh_symbol", side_effect=refresh):
        result = reconcile_eod_coverage(
            db, market="US", expected_trade_date=EXPECTED, max_symbols=5,
            max_runtime_seconds=30, sleep_seconds=0, us_port=US_FULL_MARKET_EOD_LIFECYCLE,
            priority_symbols=priorities,
        )
    assert calls == ["A", "G", "F", "E", "B"]
    assert result["continuation_required"] is True
    assert result["postcondition_met"] is False


def test_cache_only_tool_policy_does_not_register_priority():
    from app.ai import agentic_execution as execution
    with patch.object(execution.settings, "enable_market_refresh_priority", True), patch.object(
        execution, "request_market_refresh_priority"
    ) as request:
        runs, _ = execution.execute_tool_plan(
            db=Mock(), plan={"tool_plan": [{"tool": "us.refresh_daily_price", "args": {"symbol": "TSM"}}]},
            budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 10},
            can_external_fetch=False,
        )
    request.assert_not_called()
    assert runs[0]["status"] == "blocked"


def test_authorized_tool_prioritizes_before_reusing_existing_refresh(db):
    from app.ai import agentic_execution as execution
    from app.db.models import JobRun
    db.add(USStockMaster(symbol="TSM", exchange="NYSE", is_active=True))
    db.commit()
    with patch.object(execution.settings, "enable_market_refresh_priority", True), patch.object(
        execution.job_service, "find_active_job", return_value=JobRun(id=5, status="running", job_type="ai.tool_refresh")
    ), patch.object(execution, "_execute_tool_with_deadline") as acquire:
        runs, _ = execution.execute_tool_plan(
            db=db, plan={"tool_plan": [{"tool": "us.refresh_daily_price", "args": {"symbol": "TSM"}}]},
            budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 10},
            can_external_fetch=True,
        )
    acquire.assert_not_called()
    assert runs[0]["repair_priority"]["status"] == "prioritized"
    assert runs[0]["job"]["job_id"] == 5
    assert active_market_refresh_priorities(db, market="US") == ("TSM",)
    from app.ai.decision_envelope_v4 import _compact_execution
    projected = {"tool_runs": runs}
    _compact_execution(projected)
    assert projected["tool_runs"][0]["repair_priority"]["status"] == "prioritized"
    assert projected["tool_runs"][0]["job"]["job_id"] == 5


def test_priority_migration_roundtrip_preserves_other_tables(monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    path = Path(__file__).parents[1] / "alembic/versions/20260912_0084_market_refresh_priority.py"
    spec = importlib.util.spec_from_file_location("priority_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE unrelated (value INTEGER)"))
        connection.execute(text("INSERT INTO unrelated VALUES (7)"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        connection.execute(text("INSERT INTO market_refresh_priority (market, venue, symbol, requested_at, expires_at) VALUES ('US', 'NYSE', 'TSM', '2026-09-12 01:00:00', '2026-09-12 02:00:00')"))
        module.upgrade()
        assert connection.execute(text("SELECT symbol FROM market_refresh_priority")).scalar_one() == "TSM"
        assert "market_refresh_priority" in inspect(connection).get_table_names()
        columns = {column["name"] for column in inspect(connection).get_columns("market_refresh_priority")}
        assert columns == set(MarketRefreshPriority.__table__.columns.keys())
        module.downgrade()
        assert "market_refresh_priority" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT value FROM unrelated")).scalar_one() == 7
    engine.dispose()
