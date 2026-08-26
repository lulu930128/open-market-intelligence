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
    root = Path(__file__).resolve().parents[2] / ".tmp" / "test_tw_realtime_migration"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_depth_auction_migration_is_additive_typed_and_scoped_on_downgrade() -> None:
    with _migration_directory() as directory:
        database_url = _sqlite_url(directory / "realtime.db")
        config = create_alembic_config(database_url)
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            assert {
                "taiwan_stock_depth_snapshot",
                "taiwan_stock_depth_level",
                "taiwan_stock_auction_snapshot",
            } <= tables
            assert "taiwan_stock_quote_snapshot" in tables

            depth_columns = {
                column["name"]
                for column in inspector.get_columns("taiwan_stock_depth_level")
            }
            assert {
                "side",
                "level",
                "price",
                "quantity_value",
                "quantity_unit",
                "price_state",
            } <= depth_columns
            assert "payload_json" not in depth_columns
            auction_columns = {
                column["name"]
                for column in inspector.get_columns("taiwan_stock_auction_snapshot")
            }
            assert {
                "auction_type",
                "indicative_price",
                "provisional",
                "source_id",
                "raw_result_id",
            } <= auction_columns
            assert "raw_payload_json" not in auction_columns
        finally:
            engine.dispose()

        command.downgrade(config, "20260825_0068")
        engine = create_engine(database_url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert "taiwan_stock_depth_snapshot" not in tables
            assert "taiwan_stock_depth_level" not in tables
            assert "taiwan_stock_auction_snapshot" not in tables
            assert "taiwan_stock_quote_snapshot" in tables
        finally:
            engine.dispose()

        command.upgrade(config, "head")
