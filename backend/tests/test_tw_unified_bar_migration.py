from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid

from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.db.migrations import create_alembic_config


@contextmanager
def _migration_directory():
    root = Path(__file__).resolve().parents[2] / ".tmp" / "test_tw_unified_bar_migration"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_unified_bar_identity_migration_preserves_legacy_market_semantics() -> None:
    with _migration_directory() as directory:
        database_url = f"sqlite:///{(directory / 'unified-bar.db').as_posix()}"
        config = create_alembic_config(database_url)
        command.upgrade(config, "20260901_0075")

        engine = create_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO market_intraday_bar "
                        "(provider, stock_id, market, symbol, interval, bar_time, "
                        "open_price, high_price, low_price, close_price, trade_volume, "
                        "trade_value, source, source_url, created_at, updated_at) "
                        "VALUES (:provider, :stock_id, :market, :symbol, :interval, "
                        ":bar_time, 100, 101, 99, 100.5, 10, 1005, :source, NULL, "
                        ":created_at, :updated_at)"
                    ),
                    {
                        "provider": "legacy-provider",
                        "stock_id": "2330",
                        "market": "TWSE",
                        "symbol": "2330",
                        "interval": "5m",
                        "bar_time": datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc),
                        "source": "legacy-source",
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    },
                )
        finally:
            engine.dispose()

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            intraday_columns = {
                item["name"] for item in inspector.get_columns("market_intraday_bar")
            }
            daily_columns = {
                item["name"] for item in inspector.get_columns("market_daily_price")
            }
            assert {"source_id", "canonical_market", "venue", "instrument_type"} <= intraday_columns
            assert {
                "canonical_market",
                "venue",
                "instrument_type",
                "authority",
                "finalization",
                "official",
                "release_status",
                "reconciliation_status",
                "derivation_kind",
                "aggregation_version",
            } <= daily_columns
            assert {
                "market_daily_price_lineage",
                "market_daily_price_reconciliation",
            } <= set(inspector.get_table_names())

            daily_raw = next(
                item
                for item in inspector.get_columns("market_daily_price")
                if item["name"] == "raw_result_id"
            )
            intraday_raw = next(
                item
                for item in inspector.get_columns("market_intraday_bar_lineage")
                if item["name"] == "raw_result_id"
            )
            assert daily_raw["nullable"] is True
            assert intraday_raw["nullable"] is True

            with engine.connect() as connection:
                legacy = connection.execute(
                    text(
                        "SELECT market, canonical_market, venue, instrument_type "
                        "FROM market_intraday_bar WHERE provider='legacy-provider'"
                    )
                ).mappings().one()
            assert legacy == {
                "market": "TWSE",
                "canonical_market": None,
                "venue": None,
                "instrument_type": None,
            }
        finally:
            engine.dispose()

        command.downgrade(config, "20260901_0075")
        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            assert "market_daily_price_lineage" not in inspector.get_table_names()
            assert "market_daily_price_reconciliation" not in inspector.get_table_names()
            intraday_columns = {
                item["name"] for item in inspector.get_columns("market_intraday_bar")
            }
            assert "canonical_market" not in intraday_columns
            with engine.connect() as connection:
                assert connection.execute(
                    text(
                        "SELECT market FROM market_intraday_bar "
                        "WHERE provider='legacy-provider'"
                    )
                ).scalar_one() == "TWSE"
        finally:
            engine.dispose()

        command.upgrade(config, "head")
