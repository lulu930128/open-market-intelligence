from __future__ import annotations

from datetime import date, datetime, timedelta
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import reports as ai_reports
from app.ai import tools as ai_tools
from app.db.models import (
    Base,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.technical_report import TAIPEI_TZ, build_stock_technical_report


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_raw_source(db: Session, category: str) -> tuple[int, int]:
    source = SourceRegistry(
        source_name=f"test-{category}",
        source_type="test",
        category=category,
    )
    db.add(source)
    db.flush()

    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
        url=f"https://example.test/{category}",
        status_code=200,
        content_hash=f"{category}-hash",
        raw_text="{}",
    )
    db.add(raw)
    db.flush()
    return source.id, raw.id


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


def add_daily_history(db: Session, stock_id: str = "2330", count: int = 80) -> None:
    source_id, raw_result_id = add_raw_source(db, "market_daily_price")
    start = date(2026, 1, 1)

    for index in range(count):
        close = 100.0 + index
        db.add(
            MarketDailyPrice(
                source_id=source_id,
                raw_result_id=raw_result_id,
                trade_date=start + timedelta(days=index),
                stock_id=stock_id,
                stock_name="TSMC",
                trade_volume=1_000_000 + index * 1000,
                open_price=close - 1,
                high_price=close + 2,
                low_price=close - 2,
                close_price=close,
                price_change=1.0,
            )
        )

    db.commit()


def add_chip_rows(db: Session, stock_id: str = "2330") -> None:
    institutional_source_id, institutional_raw_id = add_raw_source(db, "institutional_trade")
    margin_source_id, margin_raw_id = add_raw_source(db, "margin_trading")
    trade_date = date(2026, 3, 21)

    db.add(
        InstitutionalTradeDaily(
            source_id=institutional_source_id,
            raw_result_id=institutional_raw_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            total_institutional_net=2_000_000,
        )
    )
    db.add(
        MarginTradingDaily(
            source_id=margin_source_id,
            raw_result_id=margin_raw_id,
            trade_date=trade_date,
            stock_id=stock_id,
            stock_name="TSMC",
            margin_previous_balance=100_000,
            margin_today_balance=98_000,
        )
    )
    db.commit()


class TechnicalReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        add_stock(self.db)
        add_daily_history(self.db)
        add_chip_rows(self.db)

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def test_daily_report_returns_prompt_ready_rows(self) -> None:
        report = build_stock_technical_report(
            db=self.db,
            stock_id="2330",
            timeframe="daily",
            include_intraday=False,
        )

        self.assertEqual(report["kind"], "tw_stock_technical_report")
        self.assertEqual(report["timeframe"], "daily")
        self.assertEqual(report["phase"], "daily")
        self.assertEqual(report["value_label"], "vs MA20")
        self.assertTrue(report["rows"])
        self.assertIn("daily_indicator", report["data"])
        self.assertEqual(report["evidence_passport"]["target_kind"], "tw_stock_technical_report")
        self.assertIn(report["evidence_passport"]["trust_level"], {"high", "medium", "low"})
        self.assertTrue(
            any(
                source["name"] == "market_daily_price"
                for source in report["evidence_passport"]["source_breakdown"]
            )
        )

    def test_weekly_and_monthly_reports_return_scored_rows(self) -> None:
        weekly = build_stock_technical_report(
            db=self.db,
            stock_id="2330",
            timeframe="weekly",
            include_intraday=False,
        )
        monthly = build_stock_technical_report(
            db=self.db,
            stock_id="2330",
            timeframe="monthly",
            include_intraday=False,
        )

        self.assertEqual(weekly["timeframe"], "weekly")
        self.assertEqual(monthly["timeframe"], "monthly")
        self.assertIsInstance(weekly["score"], int)
        self.assertIsInstance(monthly["score"], int)
        self.assertTrue(weekly["rows"])
        self.assertTrue(monthly["rows"])

    def test_stock_context_auto_horizon_defaults_to_swing_score(self) -> None:
        context = ai_tools.read_stock_context(
            db=self.db,
            stock_id="2330",
            analysis_horizon="auto",
            include_intraday=False,
        )

        analysis = context["data"]["analysis"]
        self.assertEqual(analysis["selected_horizon"], "swing")
        self.assertEqual(analysis["selected_timeframe"], "weekly")
        self.assertIn("daily", context["data"]["technical_reports"])
        self.assertIn("weekly", context["data"]["technical_reports"])
        self.assertIn("monthly", context["data"]["technical_reports"])

    def test_stock_context_exposes_technical_price_levels(self) -> None:
        context = ai_tools.read_stock_context(
            db=self.db,
            stock_id="2330",
            analysis_horizon="swing",
            include_intraday=False,
        )

        levels = context["data"]["technical_levels"]
        self.assertEqual(levels["kind"], "technical_price_levels")
        self.assertEqual(levels["basis_timeframe"], "daily")
        self.assertIsNotNone(levels["latest_price"])
        self.assertIn("preferred_zone", levels["entry"])
        self.assertIsNotNone(levels["entry"]["preferred_zone"]["low"])
        self.assertIsNotNone(levels["entry"]["preferred_zone"]["high"])
        self.assertIn("do_not_chase_above", levels["entry"])
        self.assertIn("short_stop", levels["risk"])
        self.assertIn("technical_invalidation", levels["risk"])

    def test_stock_context_exposes_refined_score_model(self) -> None:
        context = ai_tools.read_stock_context(
            db=self.db,
            stock_id="2330",
            analysis_horizon="swing",
            include_intraday=False,
        )

        score_model = context["data"]["analysis"]["score_model"]
        self.assertEqual(score_model["version"], "technical_factor_weight_v1")
        self.assertEqual(score_model["score_range"], "-7..+7")
        self.assertIn("swing", score_model["horizon_factor_scores"])
        daily_factors = score_model["timeframe_factor_scores"]["daily"]
        self.assertTrue(
            {"trend", "momentum", "volume", "volatility", "chips"}.issubset(daily_factors)
        )
        self.assertIn("base_selected_score", score_model)

    def test_stock_brief_summary_exposes_selected_analysis_score(self) -> None:
        brief = ai_reports.build_stock_brief(
            db=self.db,
            stock_id="2330",
            analysis_horizon="swing",
        )

        analysis = brief["summary"]["analysis"]
        self.assertEqual(analysis["selected_horizon"], "swing")
        self.assertEqual(analysis["horizon_label"], "中短線")
        self.assertIn("中短線評分", analysis["display"])

    def test_today_report_marks_non_trading_day_without_intraday_fetch(self) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 6, 14, 10, 0, tzinfo=TAIPEI_TZ),
            ),
            patch("app.market.technical_report.get_intraday_trend") as intraday,
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        intraday.assert_not_called()
        self.assertEqual(report["phase"], "market_closed")
        self.assertEqual(report["confidence"], "medium")
        self.assertEqual(report["title"], "台股休市")
        self.assertIn("台股休市", report["summary"])
        self.assertIn("下一交易日", report["data"]["market_session"]["summary"])
        self.assertFalse(report["data"]["market_session"]["is_trading_day"])
        self.assertEqual(report["data"]["intraday"]["point_count"], 0)
        self.assertTrue(any(row["key"] == "market_session" for row in report["rows"]))
        self.assertNotIn("intraday_trend.points", report["missing"])

    def test_today_report_waits_when_intraday_has_no_points(self) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 10, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report.get_intraday_trend",
                return_value={
                    "stock_id": "2330",
                    "symbol": "2330",
                    "source": "test_intraday",
                    "previous_close": 180.0,
                    "point_count": 0,
                    "points": [],
                },
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        self.assertEqual(report["phase"], "waiting_intraday")
        self.assertEqual(report["confidence"], "low")
        self.assertIn("intraday_trend.points", report["missing"])
        self.assertIn(report["evidence_passport"]["trust_level"], {"low", "blocked"})
        self.assertIn("intraday_trend.points", report["evidence_passport"]["missing"])

    def test_today_report_uses_opening_phase_for_sparse_intraday_points(self) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 10, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report.get_intraday_trend",
                return_value={
                    "stock_id": "2330",
                    "symbol": "2330",
                    "source": "test_intraday",
                    "previous_close": 180.0,
                    "point_count": 1,
                    "points": [
                        {
                            "time": "2026-03-23T09:01:00+08:00",
                            "price": 183.0,
                            "volume": 3000,
                            "open": 182.0,
                            "high": 183.0,
                            "low": 182.0,
                        }
                    ],
                },
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        self.assertEqual(report["phase"], "opening")
        self.assertEqual(report["confidence"], "low")
        self.assertEqual(report["value_label"], "vs 昨收")
        self.assertGreater(report["value"], 0)
        self.assertTrue(any(row["key"] == "daily_background" for row in report["rows"]))


if __name__ == "__main__":
    unittest.main()
