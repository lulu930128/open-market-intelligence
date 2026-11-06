"""PIT read indexes preserve observations and cover bounded stock/date reads."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.db.models import MarketDailyPrice, MarketDailyPriceRevision


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261106_0101_tw_daily_read_indexes.py"
    spec = importlib.util.spec_from_file_location("daily_read_indexes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_replay_downgrade_preserve_rows_and_enable_bounded_query():
    engine = create_engine("sqlite:///:memory:")
    for model in (MarketDailyPrice, MarketDailyPriceRevision):
        model.__table__.create(engine)
    module = migration()
    with engine.begin() as connection:
        for table, name in module.INDEXES:
            connection.exec_driver_sql(f"DROP INDEX {name}")
            connection.exec_driver_sql(f"INSERT INTO {table} (id,source_id,raw_result_id,stock_id,trade_date,close_price,created_at,updated_at) VALUES (1,1,1,'2330','2026-11-05',2240,'2026-11-05','2026-11-05'),(2,1,2,'2317','2026-11-05',219,'2026-11-05','2026-11-05')")
        before = {table: connection.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").fetchall()
                  for table, _ in module.INDEXES}
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            module.upgrade()  # Fresh metadata and already-applied indexes are valid.
            for table, name in module.INDEXES:
                plan = connection.exec_driver_sql(f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE stock_id='2330' AND trade_date>='2026-11-01' AND trade_date<='2026-11-05'").fetchall()
                assert any(name in row[-1] and "stock_id=? AND trade_date>? AND trade_date<?" in row[-1] for row in plan)
                assert connection.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").fetchall() == before[table]
            module.downgrade()
        for table, name in module.INDEXES:
            assert name not in {item["name"] for item in inspect(connection).get_indexes(table)}
            assert connection.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").fetchall() == before[table]
    engine.dispose()


def test_mismatched_existing_index_fails_closed():
    engine = create_engine("sqlite:///:memory:")
    MarketDailyPrice.__table__.create(engine)
    module = migration()
    with engine.begin() as connection:
        table, name = module.INDEXES[0]
        connection.exec_driver_sql(f"DROP INDEX {name}")
        connection.exec_driver_sql(f"CREATE INDEX {name} ON {table} (trade_date)")
        with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="Unexpected existing index"):
            module.upgrade()
    engine.dispose()
