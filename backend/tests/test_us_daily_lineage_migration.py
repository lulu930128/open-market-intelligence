from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import uuid

from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.db.migrations import create_alembic_config


@contextmanager
def _migration_directory():
    root = Path(__file__).resolve().parents[2] / ".tmp" / "test_us_daily_lineage_migration"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_us_daily_lineage_migration_preserves_legacy_rows_and_is_reversible() -> None:
    with _migration_directory() as directory:
        database_url = f"sqlite:///{(directory / 'us-daily.db').as_posix()}"
        config = create_alembic_config(database_url)
        command.upgrade(config, "20260826_0072")
        engine = create_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO us_daily_price "
                        "(provider, symbol, trade_date, currency, open_price, high_price, "
                        "low_price, close_price, trade_volume, fetched_at, created_at, updated_at) "
                        "VALUES ('yahoo_chart', 'TSM', '2026-08-21', 'USD', 240, 245, "
                        "239, 244, 1000, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )
        finally:
            engine.dispose()

        command.upgrade(config, "head")
        engine = create_engine(database_url)
        try:
            columns = {
                item["name"] for item in inspect(engine).get_columns("us_daily_price")
            }
            assert {
                "source_id",
                "raw_result_id",
                "authority",
                "raw_contract_version",
                "event_at",
                "finalization",
                "price_basis",
                "volume_unit",
                "volume_status",
            } <= columns
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT provider, symbol, raw_result_id, finalization "
                        "FROM us_daily_price WHERE symbol='TSM'"
                    )
                ).mappings().one()
            assert row["provider"] == "yahoo_chart"
            assert row["raw_result_id"] is None
            assert row["finalization"] is None
        finally:
            engine.dispose()

        command.downgrade(config, "20260826_0072")
        engine = create_engine(database_url)
        try:
            columns = {
                item["name"] for item in inspect(engine).get_columns("us_daily_price")
            }
            assert "raw_result_id" not in columns
            with engine.connect() as connection:
                count = connection.execute(
                    text("SELECT COUNT(*) FROM us_daily_price WHERE symbol='TSM'")
                ).scalar_one()
            assert count == 1
        finally:
            engine.dispose()
