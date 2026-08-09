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
    "tw_financial_filing",
    "tw_financial_parse_run",
    "tw_financial_parse_run_review",
    "tw_financial_statement_fact",
    "tw_financial_corporate_action",
    "tw_financial_normalized_fact",
    "tw_financial_basis_assessment",
    "us_corporate_event",
    "radar_rule_config",
    "radar_feature_snapshot",
    "radar_rule_evaluation",
    "radar_signal_event",
    "radar_universe_observation",
    "radar_evaluation_event_link",
    "radar_watchlist_projection",
    "radar_outcome_path",
    "radar_outcome_event_link",
    "radar_backtest_run",
    "cross_market_relation",
    "cross_market_relation_evidence",
    "cross_market_signal_snapshot",
}


class DatabaseModelContractTests(unittest.TestCase):
    def test_single_registry_configures_all_current_mappers(self) -> None:
        configure_mappers()

        self.assertEqual(len(Base.metadata.tables), 107)
        self.assertEqual(len(list(Base.registry.mappers)), 107)
        self.assertTrue(CRITICAL_TABLES.issubset(Base.metadata.tables))

    def test_all_foreign_keys_resolve_inside_shared_metadata(self) -> None:
        foreign_keys = [
            foreign_key
            for table in Base.metadata.tables.values()
            for foreign_key in table.foreign_keys
        ]

        self.assertEqual(len(foreign_keys), 75)
        for foreign_key in foreign_keys:
            with self.subTest(foreign_key=str(foreign_key)):
                self.assertIn(foreign_key.column.table.name, Base.metadata.tables)


if __name__ == "__main__":
    unittest.main()
