from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, JPStockMaster, KRStockMaster, PortfolioHolding, StockMaster, USStockMaster
from app.portfolio import kgi_sync, service
from app.portfolio.schemas import PortfolioHoldingCreate


class PortfolioHoldingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.db.add_all(
            [
                StockMaster(stock_id="2330", stock_name="TSMC", market="TWSE", instrument_type="stock"),
                USStockMaster(symbol="AAPL", security_name="Apple Inc."),
                USStockMaster(symbol="MSFT", security_name=None),
                JPStockMaster(symbol="7203.T", security_name="Toyota Motor"),
                KRStockMaster(symbol="005930.KS", security_name="Samsung Electronics"),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_create_list_and_position_context(self) -> None:
        holding = service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="tw",
                symbol="2330",
                quantity=2000,
                cost_amount=100000,
            ),
        )

        self.assertEqual(holding["market"], "tw")
        self.assertEqual(holding["symbol"], "2330")
        self.assertEqual(holding["currency"], "TWD")
        self.assertEqual(holding["average_cost"], 50)
        self.assertEqual(holding["position_context"]["entry_price"], 50)

        holdings = service.list_holdings(self.db, market="tw")
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["position_context"]["source"], "portfolio_holding")

        context = service.get_position_context_for_scope(
            self.db,
            scope_type="stock",
            scope_id="2330",
        )
        self.assertEqual(context["entry_price"], 50)
        self.assertEqual(context["currency"], "TWD")

    def test_position_context_without_db_session_is_empty(self) -> None:
        context = service.get_position_context_for_scope(
            None,
            scope_type="stock",
            scope_id="2330",
        )

        self.assertEqual(context, {})

    def test_normalizes_cross_market_symbols(self) -> None:
        jp_holding = service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="jp",
                symbol="7203",
                quantity=10,
                cost_amount=30000,
            ),
        )
        kr_holding = service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="kr",
                symbol="5930",
                quantity=5,
                cost_amount=350000,
            ),
        )
        us_holding = service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="us",
                symbol="nasdaq:aapl",
                quantity=3,
                cost_amount=600,
            ),
        )

        self.assertEqual(jp_holding["symbol"], "7203.T")
        self.assertEqual(jp_holding["currency"], "JPY")
        self.assertEqual(kr_holding["symbol"], "005930.KS")
        self.assertEqual(kr_holding["currency"], "KRW")
        self.assertEqual(us_holding["symbol"], "AAPL")
        self.assertEqual(us_holding["currency"], "USD")

    def test_duplicate_holding_is_rejected(self) -> None:
        payload = PortfolioHoldingCreate(
            market="us",
            symbol="AAPL",
            quantity=1,
            cost_amount=100,
        )
        service.create_holding(self.db, payload)

        with self.assertRaises(service.PortfolioDuplicateHoldingError):
            service.create_holding(self.db, payload)

    def test_missing_symbol_is_rejected(self) -> None:
        with self.assertRaises(service.PortfolioSymbolNotFoundError):
            service.create_holding(
                self.db,
                PortfolioHoldingCreate(
                    market="us",
                    symbol="NVDA",
                    quantity=1,
                    cost_amount=100,
                ),
            )

    def test_symbol_with_missing_display_name_is_allowed(self) -> None:
        holding = service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="us",
                symbol="MSFT",
                quantity=1,
                cost_amount=100,
            ),
        )

        self.assertEqual(holding["symbol"], "MSFT")
        self.assertIsNone(holding["symbol_name"])

    def test_kgi_sync_replaces_only_selected_market_and_preserves_user_metadata(self) -> None:
        tw = service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="tw",
                symbol="2330",
                quantity=1,
                cost_amount=10,
                note="核心部位",
                tags="long-term",
            ),
        )
        us = service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="us",
                symbol="AAPL",
                quantity=2,
                cost_amount=200,
            ),
        )
        self.db.add(
            PortfolioHolding(
                market="tw",
                symbol="2317",
                symbol_name="Hon Hai",
                quantity=1,
                cost_amount=100,
                currency="TWD",
                source="manual",
            )
        )
        self.db.commit()

        result = kgi_sync.sync_kgi_holdings(
            self.db,
            market="tw",
            fetcher=lambda _market: {
                "market": "tw",
                "source": "kgi_superpy",
                "status": "available",
                "holding_count": 1,
                "records": [
                    {
                        "symbol": "2330",
                        "symbol_name": "台積電",
                        "quantity": 2000,
                        "cost_amount": 1_200_000,
                        "currency": "TWD",
                    }
                ],
                "warnings": [],
                "observed_at": "2026-08-19T02:00:00Z",
            },
        )

        holdings = service.list_holdings(self.db, market="tw")
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["id"], tw["id"])
        self.assertEqual(holdings[0]["quantity"], 2000)
        self.assertEqual(holdings[0]["note"], "核心部位")
        self.assertEqual(holdings[0]["tags"], "long-term")
        self.assertEqual(holdings[0]["source"], "kgi_superpy")
        self.assertEqual(service.list_holdings(self.db, market="us")[0]["id"], us["id"])

    def test_kgi_us_sync_keeps_missing_cost_truthful_and_maps_exchange_suffix(self) -> None:
        result = kgi_sync.sync_kgi_holdings(
            self.db,
            market="us",
            fetcher=lambda _market: {
                "market": "us",
                "source": "kgi_superpy",
                "status": "available",
                "holding_count": 1,
                "records": [
                    {
                        "symbol": "AAPL.O",
                        "symbol_name": "Apple Inc.",
                        "quantity": 3,
                        "cost_amount": None,
                        "currency": "USD",
                    }
                ],
                "warnings": ["missing_cost_basis:1"],
                "observed_at": "2026-08-19T02:00:00+00:00",
            },
        )

        holding = service.list_holdings(self.db, market="us")[0]
        self.assertEqual(result["missing_cost_basis_count"], 1)
        self.assertEqual(holding["symbol"], "AAPL")
        self.assertIsNone(holding["cost_amount"])
        self.assertIsNone(holding["average_cost"])
        self.assertFalse(holding["position_context"]["has_position_context"])

    def test_kgi_failure_does_not_clear_existing_holdings(self) -> None:
        original = service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="tw",
                symbol="2330",
                quantity=10,
                cost_amount=1000,
            ),
        )

        with self.assertRaises(kgi_sync.KgiPortfolioUnavailableError):
            kgi_sync.sync_kgi_holdings(
                self.db,
                market="tw",
                fetcher=lambda _market: {
                    "market": "tw",
                    "status": "failed",
                    "error": "provider unavailable",
                },
            )

        remaining = service.list_holdings(self.db, market="tw")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], original["id"])
        self.assertEqual(remaining[0]["quantity"], 10)

    def test_malformed_kgi_payload_does_not_clear_existing_holdings(self) -> None:
        service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="tw",
                symbol="2330",
                quantity=10,
                cost_amount=1000,
            ),
        )

        with self.assertRaises(kgi_sync.KgiPortfolioPayloadError):
            kgi_sync.sync_kgi_holdings(
                self.db,
                market="tw",
                fetcher=lambda _market: {
                    "market": "tw",
                    "source": "kgi_superpy",
                    "status": "available",
                    "holding_count": 1,
                    "records": [{"symbol": "2330", "quantity": "bad"}],
                    "warnings": [],
                    "observed_at": "2026-08-19T02:00:00Z",
                },
            )

        self.assertEqual(len(service.list_holdings(self.db, market="tw")), 1)

    def test_successful_empty_kgi_result_clears_only_selected_market(self) -> None:
        service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="tw",
                symbol="2330",
                quantity=10,
                cost_amount=1000,
            ),
        )
        service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="us",
                symbol="AAPL",
                quantity=2,
                cost_amount=200,
            ),
        )

        result = kgi_sync.sync_kgi_holdings(
            self.db,
            market="tw",
            fetcher=lambda _market: {
                "market": "tw",
                "source": "kgi_superpy",
                "status": "empty",
                "holding_count": 0,
                "records": [],
                "warnings": [],
                "observed_at": "2026-08-19T02:00:00Z",
            },
        )

        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(service.list_holdings(self.db, market="tw"), [])
        self.assertEqual(len(service.list_holdings(self.db, market="us")), 1)

    def test_database_commit_failure_rolls_back_replacement(self) -> None:
        original = service.create_holding(
            self.db,
            PortfolioHoldingCreate(
                market="tw",
                symbol="2330",
                quantity=10,
                cost_amount=1000,
            ),
        )
        records = [
            {
                "symbol": "2330",
                "symbol_name": "台積電",
                "quantity": 99,
                "cost_amount": 9900,
                "currency": "TWD",
            }
        ]

        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                kgi_sync.replace_kgi_holdings(
                    self.db,
                    market="tw",
                    records=records,
                    source_updated_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
                    warnings=[],
                )

        remaining = service.list_holdings(self.db, market="tw")
        self.assertEqual(remaining[0]["id"], original["id"])
        self.assertEqual(remaining[0]["quantity"], 10)


if __name__ == "__main__":
    unittest.main()
