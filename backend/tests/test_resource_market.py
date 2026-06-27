from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, ResourceOhlcvBar, ResourceQuoteSnapshot, utc_now
from app.resource_market.contract import list_resource_instruments, resource_provider_contract
from app.resource_market.service import list_latest_resource_quotes, list_resource_ohlcv_bars


class ResourceMarketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_resource_contract_is_watch_only_with_default_commodities(self) -> None:
        contract = resource_provider_contract()
        symbols = {instrument["symbol"] for instrument in contract["instruments"]}

        self.assertFalse(contract["execution_enabled"])
        self.assertFalse(contract["ai_execution_enabled"])
        self.assertEqual(contract["trade_candidate_symbols"], [])
        self.assertIn("crypto", {folder["key"] for folder in contract["root_folders"]})
        self.assertIn("commodity", {folder["key"] for folder in contract["root_folders"]})
        self.assertTrue({"GC", "SI", "HG", "CL"}.issubset(symbols))
        self.assertTrue(all(not row["tradable"] for row in contract["instruments"]))
        self.assertTrue(all(row["quote_asset"] == "USDT" for row in contract["instruments"]))

    def test_resource_instrument_filters_normalize_symbols(self) -> None:
        matches = list_resource_instruments(group="metals", symbol="hg")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].display_name, "銅")
        self.assertEqual(matches[0].symbol, "HG")

    def test_resource_quote_and_ohlcv_read_queries_are_cache_only(self) -> None:
        fetched_at = utc_now()
        self.db.add(
            ResourceQuoteSnapshot(
                provider="provider_pending",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC",
                name="Gold Futures",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USDT",
                instrument_type="futures",
                contract_key="front_month",
                last_price=2400.0,
                fetched_at=fetched_at,
            )
        )
        self.db.add(
            ResourceOhlcvBar(
                provider="provider_pending",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC",
                name="Gold Futures",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USDT",
                instrument_type="futures",
                contract_key="front_month",
                interval="1d",
                bar_time=fetched_at,
                close_price=2400.0,
                fetched_at=fetched_at,
            )
        )
        self.db.commit()

        quotes = list_latest_resource_quotes(self.db, symbols="gc", group="metals")
        bars = list_resource_ohlcv_bars(self.db, symbols="GC", interval="1d")

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].last_price, 2400.0)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close_price, 2400.0)


if __name__ == "__main__":
    unittest.main()
