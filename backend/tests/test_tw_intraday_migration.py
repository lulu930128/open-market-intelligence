from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import uuid

from alembic import command
from sqlalchemy import create_engine, inspect

from app.db.migrations import create_alembic_config


@contextmanager
def _migration_directory():
    root = Path(__file__).resolve().parents[2] / ".tmp" / "test_tw_intraday_migration"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_intraday_lineage_migration_is_additive_and_scoped_on_downgrade() -> None:
    with _migration_directory() as directory:
        database_url = f"sqlite:///{(directory / 'intraday.db').as_posix()}"
        config = create_alembic_config(database_url)
        command.upgrade(config, "head")

        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            assert "market_intraday_bar" in tables
            assert "market_intraday_bar_lineage" in tables
            columns = {
                item["name"]
                for item in inspector.get_columns("market_intraday_bar_lineage")
            }
            assert {
                "bar_id",
                "source_id",
                "raw_result_id",
                "provider",
                "source",
                "raw_contract_version",
                "source_interval",
                "calculation_version",
                "component_raw_result_ids_json",
            } <= columns
            assert "payload_json" not in columns
            indexes = {
                item["name"]
                for item in inspector.get_indexes("market_intraday_bar")
            }
            assert "ix_market_intraday_bar_stock_market_interval_time" in indexes
        finally:
            engine.dispose()

        command.downgrade(config, "20260826_0072")
        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            indexes = {
                item["name"]
                for item in inspector.get_indexes("market_intraday_bar")
            }
            assert "ix_market_intraday_bar_stock_market_interval_time" not in indexes
            assert "market_intraday_bar_lineage" in inspector.get_table_names()
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        command.downgrade(config, "20260826_0069")
        engine = create_engine(database_url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert "market_intraday_bar" in tables
            assert "market_intraday_bar_lineage" not in tables
        finally:
            engine.dispose()

        command.upgrade(config, "head")
