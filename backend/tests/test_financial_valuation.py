from __future__ import annotations

import unittest
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.financial_valuation import (
    DAILY_CLOSE_PRICE_BASIS,
    resolve_latest_completed_daily_close,
)
from app.sources.defaults import TWSE_RWD_DAILY_TRADING_SOURCE_NAME


TAIPEI = ZoneInfo("Asia/Taipei")


class FinancialValuationResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_close(
        self,
        *,
        trade_date: date,
        close_price: float,
        reliability: str = "official",
        priority: int = 10,
    ) -> None:
        stock = self.db.query(StockMaster).filter(StockMaster.stock_id == "2327").first()
        if stock is None:
            self.db.add(
                StockMaster(
                    stock_id="2327",
                    stock_name="國巨",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                )
            )
        source = (
            self.db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == TWSE_RWD_DAILY_TRADING_SOURCE_NAME)
            .first()
        )
        if source is None:
            source = SourceRegistry(
                source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
                source_type="official",
                category="daily_price",
                enabled=True,
                priority=priority,
                auth_type="none",
                reliability_level=reliability,
            )
            self.db.add(source)
        self.db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime.combine(trade_date, time(8)),
            method="GET",
            content_hash=f"raw-{trade_date}-{reliability}",
            parser_version="daily-close-test-v1",
        )
        self.db.add(raw)
        self.db.flush()
        self.db.add(
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                trade_date=trade_date,
                stock_id="2327",
                stock_name="國巨",
                open_price=close_price,
                high_price=close_price,
                low_price=close_price,
                close_price=close_price,
            )
        )
        self.db.commit()

    def test_after_release_uses_expected_official_close(self) -> None:
        self._add_close(
            trade_date=date(2026, 7, 30),
            close_price=456.5,
        )

        result = resolve_latest_completed_daily_close(
            self.db,
            stock_id="2327",
            as_of=datetime(2026, 7, 30, 16, 0, tzinfo=TAIPEI),
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.price, Decimal("456.5"))
        self.assertEqual(result.price_basis, DAILY_CLOSE_PRICE_BASIS)
        self.assertEqual(result.expected_trade_date, date(2026, 7, 30))
        self.assertEqual(result.trade_date, date(2026, 7, 30))
        self.assertEqual(
            result.price_as_of,
            datetime(2026, 7, 30, 13, 30, tzinfo=TAIPEI),
        )
        self.assertEqual(result.issue_codes, ())

    def test_before_release_does_not_look_ahead_to_today(self) -> None:
        self._add_close(
            trade_date=date(2026, 7, 29),
            close_price=450,
        )
        self._add_close(
            trade_date=date(2026, 7, 30),
            close_price=456.5,
        )

        result = resolve_latest_completed_daily_close(
            self.db,
            stock_id="2327",
            as_of=datetime(2026, 7, 30, 14, 0, tzinfo=TAIPEI),
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.expected_trade_date, date(2026, 7, 29))
        self.assertEqual(result.trade_date, date(2026, 7, 29))
        self.assertEqual(result.price, Decimal("450.0"))

    def test_missing_expected_close_is_stale_not_silent_fallback(self) -> None:
        self._add_close(
            trade_date=date(2026, 7, 29),
            close_price=450,
        )

        result = resolve_latest_completed_daily_close(
            self.db,
            stock_id="2327",
            as_of=datetime(2026, 7, 30, 16, 0, tzinfo=TAIPEI),
        )

        self.assertEqual(result.status, "stale")
        self.assertIsNone(result.price)
        self.assertEqual(result.expected_trade_date, date(2026, 7, 30))
        self.assertEqual(result.trade_date, date(2026, 7, 29))
        self.assertEqual(
            result.issue_codes,
            ("valuation_price_expected_close_stale",),
        )

    def test_untrusted_close_is_not_a_valuation_input(self) -> None:
        self._add_close(
            trade_date=date(2026, 7, 30),
            close_price=456.5,
            reliability="unknown",
        )

        result = resolve_latest_completed_daily_close(
            self.db,
            stock_id="2327",
            as_of=datetime(2026, 7, 30, 16, 0, tzinfo=TAIPEI),
        )

        self.assertEqual(result.status, "untrusted")
        self.assertIsNone(result.price)
        self.assertEqual(
            result.issue_codes,
            ("valuation_price_source_untrusted",),
        )
