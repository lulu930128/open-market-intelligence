from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.migrations import get_database_revision, get_head_revision, run_database_migrations
from app.db.models import Base, StockMaster


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


class DatabaseMigrationTests(unittest.TestCase):
    def test_upgrade_empty_sqlite_database_to_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = sqlite_url(Path(directory) / "empty.db")

            run_database_migrations(database_url)

            engine = create_engine(database_url)
            try:
                table_names = set(inspect(engine).get_table_names())
            finally:
                engine.dispose()

            self.assertIn("alembic_version", table_names)
            self.assertIn("stock_master", table_names)
            self.assertIn("job_run", table_names)
            self.assertIn("broker_branch_trade_daily", table_names)
            self.assertEqual(get_database_revision(database_url), get_head_revision())

    def test_upgrade_legacy_create_all_database_preserves_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = sqlite_url(Path(directory) / "legacy.db")
            engine = create_engine(database_url)

            try:
                Base.metadata.create_all(bind=engine)
                with Session(engine) as db:
                    db.add(
                        StockMaster(
                            stock_id="2330",
                            stock_name="台積電",
                            market="TWSE",
                            instrument_type="stock",
                        )
                    )
                    db.commit()

                run_database_migrations(database_url)

                with engine.connect() as connection:
                    stock_name = connection.execute(
                        text("SELECT stock_name FROM stock_master WHERE stock_id = :stock_id"),
                        {"stock_id": "2330"},
                    ).scalar_one()
            finally:
                engine.dispose()

            self.assertEqual(stock_name, "台積電")
            self.assertEqual(get_database_revision(database_url), get_head_revision())


if __name__ == "__main__":
    unittest.main()
