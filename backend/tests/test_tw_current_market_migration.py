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
    root = Path(__file__).resolve().parents[2] / ".tmp" / "test_tw_current_market_migration"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_current_market_migration_is_additive_and_scoped_on_downgrade() -> None:
    with _migration_directory() as directory:
        database_url = f"sqlite:///{(directory / 'current-market.db').as_posix()}"
        config = create_alembic_config(database_url)
        command.upgrade(config, "head")

        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            assert "taiwan_current_index_snapshot" in tables
            assert "taiwan_current_breadth_snapshot" in tables

            index_columns = {
                item["name"]
                for item in inspector.get_columns("taiwan_current_index_snapshot")
            }
            assert {
                "source_id",
                "raw_result_id",
                "provider",
                "source",
                "raw_contract_version",
                "event_at",
                "received_at",
                "fetched_at",
                "index_id",
                "session",
                "finalization",
                "provisional",
            } <= index_columns
            assert "payload_json" not in index_columns

            breadth_columns = {
                item["name"]
                for item in inspector.get_columns("taiwan_current_breadth_snapshot")
            }
            assert {
                "source_id",
                "raw_result_id",
                "provider",
                "source",
                "raw_contract_version",
                "event_at",
                "received_at",
                "fetched_at",
                "venue",
                "universe_count",
                "received_unclassified_count",
                "not_received_count",
                "decision_usable",
            } <= breadth_columns
            assert "payload_json" not in breadth_columns
        finally:
            engine.dispose()

        command.downgrade(config, "20260826_0070")
        engine = create_engine(database_url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert "taiwan_current_index_snapshot" not in tables
            assert "taiwan_current_breadth_snapshot" not in tables
            assert "market_intraday_bar_lineage" in tables
        finally:
            engine.dispose()

        command.upgrade(config, "head")
