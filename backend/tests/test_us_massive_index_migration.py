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
    root = Path(__file__).resolve().parents[2] / ".tmp" / "test_us_massive_index_migration"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_massive_index_lineage_migration_is_additive_and_reversible() -> None:
    with _migration_directory() as directory:
        database_url = f"sqlite:///{(directory / 'massive-index.db').as_posix()}"
        config = create_alembic_config(database_url)
        command.upgrade(config, "20260901_0076")
        command.upgrade(config, "head")

        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            intraday_columns = {
                item["name"]
                for item in inspector.get_columns("market_intraday_bar")
            }
            lineage_columns = {
                item["name"]
                for item in inspector.get_columns("market_intraday_bar_lineage")
            }
            quote_columns = {
                item["name"]
                for item in inspector.get_columns("us_quote_snapshot")
            }
            assert "volume_status" in intraday_columns
            assert "provider_timeframe" in lineage_columns
            assert "provider_timeframe" in quote_columns
        finally:
            engine.dispose()

        command.downgrade(config, "20260901_0076")
        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            assert "volume_status" not in {
                item["name"]
                for item in inspector.get_columns("market_intraday_bar")
            }
            assert "provider_timeframe" not in {
                item["name"]
                for item in inspector.get_columns("market_intraday_bar_lineage")
            }
            assert "provider_timeframe" not in {
                item["name"]
                for item in inspector.get_columns("us_quote_snapshot")
            }
        finally:
            engine.dispose()
