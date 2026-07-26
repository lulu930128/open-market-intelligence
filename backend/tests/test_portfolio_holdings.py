from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, JPStockMaster, KRStockMaster, StockMaster, USStockMaster
from app.portfolio import service
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


if __name__ == "__main__":
    unittest.main()
