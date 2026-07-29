from __future__ import annotations

import unittest

from sqlalchemy.orm import configure_mappers

from app.db.models import Base


CRITICAL_TABLES = {
    "stock_master",
    "market_daily_price",
    "market_index_daily_stat",
    "taiwan_market_minute_state",
    "provider_event",
    "source_health_snapshot",
    "us_daily_price",
    "jp_daily_price",
    "kr_daily_price",
    "crypto_ohlcv_bar",
    "resource_ohlcv_bar",
    "portfolio_holding",
    "taiwan_option_chain_daily",
    "taiwan_derivatives_large_trader_daily",
    "taiwan_futures_term_structure_daily",
    "taiwan_quote_contract_snapshot",
    "taiwan_index_contract_snapshot",
}


class DatabaseModelContractTests(unittest.TestCase):
    def test_single_registry_configures_all_current_mappers(self) -> None:
        configure_mappers()

        self.assertEqual(len(Base.metadata.tables), 84)
        self.assertEqual(len(list(Base.registry.mappers)), 84)
        self.assertTrue(CRITICAL_TABLES.issubset(Base.metadata.tables))

    def test_all_foreign_keys_resolve_inside_shared_metadata(self) -> None:
        foreign_keys = [
            foreign_key
            for table in Base.metadata.tables.values()
            for foreign_key in table.foreign_keys
        ]

        self.assertEqual(len(foreign_keys), 45)
        for foreign_key in foreign_keys:
            with self.subTest(foreign_key=str(foreign_key)):
                self.assertIn(foreign_key.column.table.name, Base.metadata.tables)


if __name__ == "__main__":
    unittest.main()
