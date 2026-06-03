from __future__ import annotations

from datetime import date
from itertools import count
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import freshness
from app.ai.schemas import AiAskRequest
from app.db.models import (
    Base,
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    RawFetchResult,
    ShareholdingDistributionWeekly,
    SourceRegistry,
    StockMaster,
)


SOURCE_COUNTER = count()


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_stock(db: Session, stock_id: str = "2330") -> None:
    db.add(
        StockMaster(
            stock_id=stock_id,
            stock_name="TSMC",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.commit()


def add_raw_source(db: Session, category: str) -> tuple[int, int]:
    index = next(SOURCE_COUNTER)
    source = SourceRegistry(
        source_name=f"test-{category}-{index}",
        source_type="test",
        category=category,
    )
    db.add(source)
    db.flush()

    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
    )
    db.add(raw)
    db.flush()
    return source.id, raw.id


def add_daily_price(db: Session, stock_id: str, trade_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "market_daily_price")
    db.add(
        MarketDailyPrice(
            source_id=source_id,
            raw_result_id=raw_result_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            close_price=100.0,
        )
    )
    db.commit()


def add_institutional_trade(db: Session, stock_id: str, trade_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "institutional_trade")
    db.add(
        InstitutionalTradeDaily(
            source_id=source_id,
            raw_result_id=raw_result_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            total_institutional_net=1000,
        )
    )
    db.commit()


def add_margin_trade(db: Session, stock_id: str, trade_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "margin_trading")
    db.add(
        MarginTradingDaily(
            source_id=source_id,
            raw_result_id=raw_result_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            margin_today_balance=100,
        )
    )
    db.commit()


def add_broker_branch_trade(db: Session, stock_id: str, trade_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "broker_branch_trade")
    db.add(
        BrokerBranchTradeDaily(
            source_id=source_id,
            raw_result_id=raw_result_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            branch_code="0010",
            branch_name="Test Branch",
            net_lots=10,
        )
    )
    db.commit()


def add_shareholding_distribution(db: Session, stock_id: str, data_date: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "shareholding_distribution")
    db.add(
        ShareholdingDistributionWeekly(
            source_id=source_id,
            raw_result_id=raw_result_id,
            data_date=data_date,
            stock_id=stock_id,
            stock_name="TSMC",
            holding_level="1",
            holding_level_order=1,
            holder_count=100,
        )
    )
    db.commit()


def add_monthly_revenue(db: Session, stock_id: str, period: date) -> None:
    source_id, raw_result_id = add_raw_source(db, "monthly_revenue")
    db.add(
        MonthlyRevenue(
            source_id=source_id,
            raw_result_id=raw_result_id,
            period=period,
            stock_id=stock_id,
            stock_name="TSMC",
            monthly_revenue=100000,
        )
    )
    db.commit()


def add_financial_metric(db: Session, stock_id: str) -> None:
    source_id, raw_result_id = add_raw_source(db, "financial_metric_quarterly")
    db.add(
        FinancialMetricQuarterly(
            source_id=source_id,
            raw_result_id=raw_result_id,
            fiscal_year=2026,
            quarter=1,
            period="2026Q1",
            stock_id=stock_id,
            stock_name="TSMC",
            eps=1.23,
            roe=10.0,
        )
    )
    db.commit()


def add_complete_stock_evidence(
    db: Session,
    stock_id: str,
    expected_trade_date: date,
) -> None:
    add_daily_price(db, stock_id, expected_trade_date)
    add_institutional_trade(db, stock_id, expected_trade_date)
    add_margin_trade(db, stock_id, expected_trade_date)
    add_broker_branch_trade(db, stock_id, expected_trade_date)
    add_shareholding_distribution(db, stock_id, date(2026, 5, 22))
    add_monthly_revenue(db, stock_id, date(2026, 4, 1))
    add_financial_metric(db, stock_id)


class AiFreshnessGuardTests(unittest.TestCase):
    def test_stock_freshness_reports_missing_evidence_pack(self) -> None:
        db = make_session()
        try:
            add_stock(db)

            with (
                patch.object(freshness, "expected_daily_price_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_institutional_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_margin_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_broker_branch_date", return_value=date(2026, 5, 29)),
            ):
                result = freshness.check_stock_data_freshness(db=db, stock_id="2330")

            self.assertFalse(result["is_current"])
            self.assertEqual(result["stale_stock_count"], 1)
            self.assertIn("market_daily_price", result["missing"])
            self.assertIn("institutional_trade_daily", result["missing"])
            self.assertIn("margin_trading_daily", result["missing"])
            self.assertIn("broker_branch_trade_daily", result["missing"])
            self.assertIn("shareholding_distribution_weekly", result["missing"])
            self.assertIn("monthly_revenue", result["missing"])
            self.assertIn("financial_metric_quarterly", result["missing"])
            self.assertEqual(result["stale_stocks"][0]["stock_id"], "2330")
            self.assertEqual(result["datasets"][0]["key"], "stock_master")
        finally:
            db.close()

    def test_stock_freshness_accepts_complete_evidence_pack(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            add_complete_stock_evidence(db, "2330", date(2026, 5, 29))

            with (
                patch.object(freshness, "expected_daily_price_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_institutional_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_margin_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_broker_branch_date", return_value=date(2026, 5, 29)),
            ):
                result = freshness.check_stock_data_freshness(db=db, stock_id="2330")

            self.assertTrue(result["is_current"])
            self.assertEqual(result["stale_stock_count"], 0)
            self.assertFalse(result["missing"])
        finally:
            db.close()

    def test_ask_downgrades_incomplete_report_without_calling_llm(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="generate report for 2330",
                scope_type="stock",
                scope_id="2330",
                mode="report",
                allow_llm=True,
                allow_write=True,
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=True,
                trust_source="token",
            )

            with (
                patch.object(freshness, "expected_daily_price_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_institutional_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_margin_trade_date", return_value=date(2026, 5, 29)),
                patch.object(freshness, "expected_broker_branch_date", return_value=date(2026, 5, 29)),
                patch.object(ai_ask.orchestrator, "generate_stock_llm_report") as generate_report,
            ):
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            generate_report.assert_not_called()
            self.assertEqual(response["mode_requested"], "report")
            self.assertEqual(response["mode_effective"], "brief")
            self.assertFalse(response["freshness"]["is_current"])
            self.assertIn("market_daily_price", response["missing"])
            self.assertIn("monthly_revenue", response["missing"])
            self.assertTrue(
                any("Report mode skipped" in warning for warning in response["warnings"])
            )
        finally:
            db.close()

    def test_ask_allows_non_persistent_analysis_without_write(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="請分析 2330 的短評與風險",
                scope_type="stock",
                scope_id="2330",
                mode="analysis",
                allow_llm=True,
                allow_write=False,
            )
            server_policy = ai_ask.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                trust_source="token",
            )

            with patch.object(
                ai_ask.orchestrator,
                "generate_stock_llm_analysis",
                return_value={"kind": "stock_llm_analysis", "warnings": []},
            ) as generate_analysis:
                response = ai_ask.ask(db=db, payload=payload, server_policy=server_policy)

            generate_analysis.assert_called_once()
            self.assertEqual(response["mode_requested"], "analysis")
            self.assertEqual(response["mode_effective"], "analysis")
            self.assertEqual(response["action"], "omi.generate_stock_llm_analysis")
            self.assertTrue(response["policy"]["can_call_llm"])
            self.assertFalse(response["policy"]["can_write"])
            self.assertFalse(response["policy"]["can_generate_report"])
        finally:
            db.close()

    def test_ask_downgrades_analysis_without_trust(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="請分析 2330 的短評與風險",
                scope_type="stock",
                scope_id="2330",
                mode="analysis",
                allow_llm=True,
                allow_write=False,
            )

            with patch.object(ai_ask.orchestrator, "generate_stock_llm_analysis") as generate_analysis:
                response = ai_ask.ask(db=db, payload=payload)

            generate_analysis.assert_not_called()
            self.assertEqual(response["mode_requested"], "analysis")
            self.assertEqual(response["mode_effective"], "brief")
            self.assertFalse(response["policy"]["can_call_llm"])
            self.assertTrue(
                any("Analysis mode requires" in warning for warning in response["warnings"])
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
