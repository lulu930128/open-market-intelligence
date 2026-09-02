from __future__ import annotations

import unittest
from unittest.mock import patch

from app.us_market import (
    catalog_store,
    errors,
    fundamentals_store,
    price_store,
    service,
    watchlist_store,
)


class USMarketServiceBoundaryTests(unittest.TestCase):
    def test_service_keeps_store_facades(self) -> None:
        self.assertIs(service.upsert_us_symbol_records, catalog_store.upsert_us_symbol_records)
        self.assertIs(service.get_us_stock, catalog_store.get_us_stock)
        self.assertIs(service.upsert_us_daily_price_records, price_store.upsert_us_daily_price_records)
        self.assertIs(service.list_us_daily_prices, price_store.list_us_daily_prices)
        self.assertIs(service.get_us_company_profile, fundamentals_store.get_us_company_profile)
        self.assertIs(service.list_us_corporate_actions, fundamentals_store.list_us_corporate_actions)
        self.assertIs(service.get_us_watchlist_group, watchlist_store.get_us_watchlist_group)
        self.assertIs(service.list_us_watchlist_symbols, watchlist_store.list_us_watchlist_symbols)

    def test_service_keeps_public_error_identities(self) -> None:
        self.assertIs(service.USStockNotFoundError, errors.USStockNotFoundError)
        self.assertIs(
            service.USMarketConfigurationError,
            errors.USMarketConfigurationError,
        )
        self.assertIs(
            service.USWatchlistDuplicateItemError,
            errors.USWatchlistDuplicateItemError,
        )

    def test_workflow_dependencies_resolve_facade_functions_at_call_time(self) -> None:
        with (
            patch.object(service, "expected_us_daily_price_date") as expected_date,
            patch.object(service, "_get_us_current_quote_overlay") as quote_overlay,
            patch.object(
                service,
                "_refresh_us_watchlist_daily_through_platform",
            ) as refresh_daily,
            patch.object(service, "refresh_us_sec_companyfacts") as refresh_sec,
        ):
            dependencies = service._us_watchlist_workflow_dependencies()

        self.assertIs(dependencies.expected_daily_price_date, expected_date)
        self.assertIs(dependencies.current_quote_overlay_loader, quote_overlay)
        self.assertIs(dependencies.refresh_daily_prices, refresh_daily)
        self.assertIs(dependencies.refresh_sec_facts, refresh_sec)


if __name__ == "__main__":
    unittest.main()
