from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import unittest
import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.migrations import get_database_revision, get_head_revision, run_database_migrations
from app.db.models import Base, StockMaster


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


@contextmanager
def migration_test_directory():
    root = Path(__file__).resolve().parents[2] / ".tmp" / "test_database_migrations"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class DatabaseMigrationTests(unittest.TestCase):
    def test_upgrade_empty_sqlite_database_to_head(self) -> None:
        with migration_test_directory() as directory:
            database_url = sqlite_url(directory / "empty.db")

            run_database_migrations(database_url)

            engine = create_engine(database_url)
            try:
                table_names = set(inspect(engine).get_table_names())
                with engine.connect() as connection:
                    resource_instrument_count = connection.execute(
                        text("SELECT COUNT(*) FROM resource_market_instrument")
                    ).scalar_one()
                    currency_instrument_count = connection.execute(
                        text(
                            "SELECT COUNT(*) FROM resource_market_instrument "
                            "WHERE root_folder = 'currency'"
                        )
                    ).scalar_one()
            finally:
                engine.dispose()

            self.assertIn("alembic_version", table_names)
            self.assertEqual(table_names - {"alembic_version"}, set(Base.metadata.tables))
            self.assertIn("stock_master", table_names)
            self.assertIn("us_stock_master", table_names)
            self.assertIn("us_daily_price", table_names)
            self.assertIn("us_sec_company_fact", table_names)
            self.assertIn("us_company_profile", table_names)
            self.assertIn("us_corporate_action", table_names)
            self.assertIn("us_short_volume_daily", table_names)
            self.assertIn("macro_series_observation", table_names)
            self.assertIn("us_watchlist_group", table_names)
            self.assertIn("us_watchlist_item", table_names)
            self.assertIn("job_run", table_names)
            self.assertIn("broker_branch_trade_daily", table_names)
            self.assertIn("market_index_daily_stat", table_names)
            self.assertIn("market_chip_daily", table_names)
            self.assertIn("market_intraday_bar", table_names)
            self.assertIn("taiwan_stock_quote_snapshot", table_names)
            self.assertIn("chart_drawing_snapshot", table_names)
            self.assertIn("taiwan_futures_quote_snapshot", table_names)
            self.assertIn("taiwan_futures_intraday_bar", table_names)
            self.assertIn("taiwan_futures_daily_bar", table_names)
            self.assertIn("provider_event", table_names)
            self.assertIn("source_health_snapshot", table_names)
            self.assertIn("app_setting", table_names)
            self.assertIn("crypto_ticker_snapshot", table_names)
            self.assertIn("crypto_order_book_snapshot", table_names)
            self.assertIn("crypto_ohlcv_bar", table_names)
            self.assertIn("crypto_derivatives_metric", table_names)
            self.assertIn("crypto_market_cap_snapshot", table_names)
            self.assertIn("crypto_spread_snapshot", table_names)
            self.assertIn("crypto_liquidation_event", table_names)
            self.assertIn("crypto_liquidation_heatmap_cell", table_names)
            self.assertIn("crypto_cvd_history", table_names)
            self.assertIn("crypto_long_short_ratio_history", table_names)
            self.assertIn("dispatch_schedule", table_names)
            self.assertIn("resource_market_instrument", table_names)
            self.assertIn("resource_quote_snapshot", table_names)
            self.assertIn("resource_ohlcv_bar", table_names)
            self.assertIn("jp_stock_master", table_names)
            self.assertIn("jp_daily_price", table_names)
            self.assertIn("jp_company_fundamental", table_names)
            self.assertIn("jp_watchlist_group", table_names)
            self.assertIn("jp_watchlist_item", table_names)
            self.assertIn("kr_stock_master", table_names)
            self.assertIn("kr_daily_price", table_names)
            self.assertIn("kr_market_index", table_names)
            self.assertIn("kr_index_daily_price", table_names)
            self.assertIn("kr_company_fundamental", table_names)
            self.assertIn("kr_investor_trade_daily", table_names)
            self.assertIn("kr_watchlist_group", table_names)
            self.assertIn("kr_watchlist_item", table_names)
            self.assertIn("watchlist_radar_snapshot_run", table_names)
            self.assertIn("watchlist_radar_snapshot_item", table_names)
            self.assertIn("watchlist_radar_outcome", table_names)
            self.assertIn("portfolio_holding", table_names)
            jp_master_columns = {
                column["name"]
                for column in inspect(engine).get_columns("jp_stock_master")
            }
            self.assertIn("market_segment", jp_master_columns)
            self.assertIn("sector_33_name", jp_master_columns)
            self.assertIn("sector_17_name", jp_master_columns)
            self.assertIn("size_name", jp_master_columns)
            self.assertGreaterEqual(resource_instrument_count, 6)
            self.assertEqual(currency_instrument_count, 9)
            self.assertEqual(get_database_revision(database_url), get_head_revision())

    def test_upgrade_legacy_create_all_database_preserves_rows(self) -> None:
        with migration_test_directory() as directory:
            database_url = sqlite_url(directory / "legacy.db")
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


    def test_repair_partial_jp_master_table_at_0016(self) -> None:
        with migration_test_directory() as directory:
            database_url = sqlite_url(directory / "partial_jp.db")
            engine = create_engine(database_url)

            try:
                with engine.begin() as connection:
                    connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
                    connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260620_0016')"))
                    connection.execute(
                        text(
                            """
                            CREATE TABLE jp_stock_master (
                                id INTEGER NOT NULL,
                                symbol VARCHAR(32) NOT NULL,
                                local_code VARCHAR(20),
                                security_name VARCHAR(240),
                                exchange VARCHAR(80),
                                asset_type VARCHAR(40) NOT NULL,
                                listing_source VARCHAR(40) NOT NULL,
                                currency VARCHAR(10) NOT NULL,
                                exchange_timezone_name VARCHAR(80),
                                is_active BOOLEAN NOT NULL,
                                first_seen_at DATETIME NOT NULL,
                                last_seen_at DATETIME NOT NULL,
                                created_at DATETIME NOT NULL,
                                updated_at DATETIME NOT NULL,
                                PRIMARY KEY (id),
                                CONSTRAINT uq_jp_stock_master_symbol UNIQUE (symbol)
                            )
                            """
                        )
                    )

                run_database_migrations(database_url)

                jp_master_columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("jp_stock_master")
                }
            finally:
                engine.dispose()

            self.assertIn("market_segment", jp_master_columns)
            self.assertIn("sector_33_code", jp_master_columns)
            self.assertIn("sector_33_name", jp_master_columns)
            self.assertIn("sector_17_code", jp_master_columns)
            self.assertIn("sector_17_name", jp_master_columns)
            self.assertIn("size_code", jp_master_columns)
            self.assertIn("size_name", jp_master_columns)
            self.assertEqual(get_database_revision(database_url), get_head_revision())

    def test_repair_partial_jp_company_fundamental_table_at_0019(self) -> None:
        with migration_test_directory() as directory:
            database_url = sqlite_url(directory / "partial_jp_fundamental.db")
            engine = create_engine(database_url)

            try:
                with engine.begin() as connection:
                    connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
                    connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260620_0019')"))
                    connection.execute(
                        text(
                            """
                            CREATE TABLE jp_company_fundamental (
                                id INTEGER NOT NULL,
                                provider VARCHAR(40) NOT NULL,
                                symbol VARCHAR(32) NOT NULL,
                                company_name VARCHAR(240),
                                exchange VARCHAR(80),
                                sector VARCHAR(120),
                                industry VARCHAR(160),
                                currency VARCHAR(10),
                                market_cap BIGINT,
                                enterprise_value BIGINT,
                                trailing_pe FLOAT,
                                forward_pe FLOAT,
                                price_to_book FLOAT,
                                dividend_yield FLOAT,
                                beta FLOAT,
                                eps_ttm FLOAT,
                                forward_eps FLOAT,
                                revenue_ttm BIGINT,
                                gross_margin FLOAT,
                                operating_margin FLOAT,
                                profit_margin FLOAT,
                                return_on_equity FLOAT,
                                return_on_assets FLOAT,
                                revenue_growth FLOAT,
                                earnings_growth FLOAT,
                                total_cash BIGINT,
                                total_debt BIGINT,
                                debt_to_equity FLOAT,
                                current_ratio FLOAT,
                                quick_ratio FLOAT,
                                shares_outstanding BIGINT,
                                book_value FLOAT,
                                earnings_date DATE,
                                ex_dividend_date DATE,
                                source_url TEXT,
                                raw_payload_hash VARCHAR(128),
                                fetched_at DATETIME NOT NULL,
                                created_at DATETIME NOT NULL,
                                updated_at DATETIME NOT NULL,
                                PRIMARY KEY (id),
                                CONSTRAINT uq_jp_company_fundamental_provider_symbol UNIQUE (provider, symbol)
                            )
                            """
                        )
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO jp_company_fundamental (
                                id, provider, symbol, company_name, currency, market_cap,
                                fetched_at, created_at, updated_at
                            )
                            VALUES (
                                1, 'yahoo_quote_summary', '7203.T', 'Toyota Motor Corporation',
                                'JPY', 41000000000000, '2026-06-20 00:00:00',
                                '2026-06-20 00:00:00', '2026-06-20 00:00:00'
                            )
                            """
                        )
                    )

                run_database_migrations(database_url)

                jp_fundamental_columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("jp_company_fundamental")
                }
                with engine.connect() as connection:
                    row_count = connection.execute(
                        text("SELECT COUNT(*) FROM jp_company_fundamental")
                    ).scalar_one()
                    market_cap = connection.execute(
                        text("SELECT market_cap FROM jp_company_fundamental WHERE symbol = '7203.T'")
                    ).scalar_one()
            finally:
                engine.dispose()

            self.assertIn("disclosed_date", jp_fundamental_columns)
            self.assertIn("fiscal_period", jp_fundamental_columns)
            self.assertIn("net_sales", jp_fundamental_columns)
            self.assertIn("operating_profit", jp_fundamental_columns)
            self.assertIn("total_assets", jp_fundamental_columns)
            self.assertIn("operating_cash_flow", jp_fundamental_columns)
            self.assertEqual(row_count, 1)
            self.assertEqual(market_cap, 41000000000000)
            self.assertEqual(get_database_revision(database_url), get_head_revision())


if __name__ == "__main__":
    unittest.main()
