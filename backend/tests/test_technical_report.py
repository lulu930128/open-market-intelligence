from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
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
from app.market.indicator_service import calculate_indicator_points_from_ohlc_points
from app.market.signal_service import calculate_latest_stock_signals
from app.market.schemas import TechnicalReportRead
from app.market.technical_evidence import build_tw_stock_technical_evidence
from app.market.technical_indicator_gateway import calculate_active_daily_indicators
from app.market.technical_report import (
    TAIPEI_TZ,
    _canonical_intraday_payload,
    _fmt_price,
    _today_market_session,
    build_stock_technical_report,
)
from app.market.tw_bar_contracts import TaiwanBarSessionScope
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_raw_source(db: Session, category: str) -> tuple[int, int]:
    source_name = (
        TWSE_DAILY_TRADING_SOURCE_NAME
        if category == "market_daily_price"
        else f"test-{category}"
    )
    source = SourceRegistry(
        source_name=source_name,
        source_type=("official" if category == "market_daily_price" else "test"),
        category=category,
        reliability_level=(
            "official" if category == "market_daily_price" else "unknown"
        ),
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
    def test_post_close_session_separates_previous_from_latest_completed_day(
        self,
    ) -> None:
        with patch(
            "app.market.technical_report._now",
            return_value=datetime(2026, 9, 4, 22, 0, tzinfo=TAIPEI_TZ),
        ):
            session = _today_market_session()

        self.assertEqual(session["previous_trading_day"], "2026-09-03")
        self.assertEqual(
            session["latest_completed_trade_date"],
            "2026-09-04",
        )

    def test_canonical_intraday_payload_is_scoped_to_current_session(self) -> None:
        bar = SimpleNamespace(
            start_at=datetime(2026, 9, 4, 9, 0, tzinfo=TAIPEI_TZ),
            open_price=100,
            high_price=101,
            low_price=99,
            close_price=100,
            volume=SimpleNamespace(value=1000),
            finalization=SimpleNamespace(value="final"),
            lineage=SimpleNamespace(source="test_current_session"),
        )
        series = SimpleNamespace(
            bars=[bar],
            current_session_coverage=SimpleNamespace(
                status=SimpleNamespace(value="partial_prefix"),
                model_dump=lambda **_kwargs: {
                    "status": "partial_prefix",
                    "observed_bucket_count": 1,
                    "missing_bucket_count": 1,
                },
            ),
            history=SimpleNamespace(
                requested_coverage_satisfied=True,
                history_status=SimpleNamespace(value="ready"),
            ),
            identity=SimpleNamespace(
                series_fingerprint="fingerprint",
                series_revision="revision",
            ),
        )

        with patch(
            "app.market.technical_report.TaiwanBarService"
        ) as service_class:
            service_class.return_value.read_scoped_bars.return_value = series

            payload = _canonical_intraday_payload(object(), "2330")

        service_class.return_value.read_scoped_bars.assert_called_once_with(
            instrument_id="2330",
            interval="1m",
            limit=500,
            include_partial=True,
            session_scope=TaiwanBarSessionScope.CURRENT_SESSION,
        )
        service_class.return_value.read_bars.assert_not_called()
        self.assertEqual(payload["point_count"], 1)
        self.assertEqual(payload["points"][0]["time"].date(), date(2026, 9, 4))
        self.assertEqual(payload["series_coverage"]["status"], "partial_prefix")
        self.assertTrue(payload["series_coverage"]["opening_covered"])
        self.assertFalse(payload["series_coverage"]["current_window_complete"])
        self.assertFalse(
            payload["series_coverage"]["current_cumulative_volume_complete"]
        )

    def test_price_display_does_not_strip_integer_trailing_zeroes(self) -> None:
        self.assertEqual(_fmt_price(2350), "2,350")
        self.assertEqual(_fmt_price(2350.0), "2,350")
        self.assertEqual(_fmt_price(235.5), "235.5")

    def setUp(self) -> None:
        self.db = make_session()
        add_stock(self.db)
        add_daily_history(self.db)
        add_chip_rows(self.db)

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def assertSlotEnvelope(
        self,
        slot: dict,
        *,
        payload_ref: str | None = None,
        payload_level: str | None = None,
    ) -> None:
        self.assertIsInstance(slot.get("status"), str)
        self.assertIsInstance(slot.get("capability"), str)
        self.assertIsInstance(slot.get("priority"), str)
        if payload_ref is not None:
            self.assertEqual(slot.get("payload_ref"), payload_ref)
        if payload_level is not None:
            self.assertEqual(slot.get("payload_level"), payload_level)

    def test_indicator_points_include_scanning_indicators(self) -> None:
        start = date(2026, 1, 1)
        points = [
            {
                "time": start + timedelta(days=index),
                "open": 100.0 + index,
                "high": 102.0 + index,
                "low": 98.0 + index,
                "close": 100.0 + index,
                "volume": 1_000_000 + index * 1000,
                "price_change": 1.0 if index else None,
            }
            for index in range(30)
        ]

        indicators = calculate_indicator_points_from_ohlc_points(points)
        latest = indicators[-1]

        self.assertIn("bollinger", latest)
        self.assertIn("kd", latest)
        self.assertIn("support_resistance", latest)
        self.assertIsNotNone(latest["bollinger"]["upper20"])
        self.assertIsNotNone(latest["kd"]["k9"])
        self.assertEqual(latest["support_resistance"]["support20"], 107.0)
        self.assertEqual(latest["support_resistance"]["resistance20"], 130.0)

    def test_api_ai_and_frontend_series_share_resolved_backend_indicator_truth(self) -> None:
        vendor_source_id, vendor_raw_id = add_raw_source(self.db, "vendor_duplicate")
        self.db.add(
            MarketDailyPrice(
                source_id=vendor_source_id,
                raw_result_id=vendor_raw_id,
                trade_date=date(2026, 3, 21),
                stock_id="2330",
                stock_name="TSMC vendor duplicate",
                trade_volume=9_999_999,
                open_price=9_998.0,
                high_price=10_001.0,
                low_price=9_997.0,
                close_price=10_000.0,
                price_change=9_821.0,
            )
        )
        self.db.commit()

        api_series = calculate_active_daily_indicators(
            db=self.db,
            stock_id="2330",
            limit=250,
        )
        evidence = build_tw_stock_technical_evidence(
            db=self.db,
            stock_id="2330",
            corporate_event_history={
                "cache_status": "current",
                "coverage_start": "2020-01-01",
                "coverage_end": "2026-12-31",
                "results": [],
            },
        )
        api_latest = api_series[-1]
        ai_latest = evidence["indicators"]["timeframes"]["daily"]["completed"]

        self.assertEqual(api_latest["close"], 179.0)
        self.assertEqual(api_latest["algorithm_version"], "tw.technical.indicators.v4")
        self.assertEqual(api_latest["calculation_role"], "backend_authoritative")
        self.assertEqual(api_latest["rsi"], ai_latest["rsi"])
        self.assertEqual(api_latest["macd"], ai_latest["macd"])
        self.assertEqual(api_latest["kd"], ai_latest["kd"])
        self.assertEqual(
            evidence["indicators"]["lineage"]["resolved_health"]["selected_provider"],
            "twse_openapi",
        )
        self.assertNotEqual(api_latest["close"], 10_000.0)

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
        self.assertEqual(
            report["data"]["current_state"]["version"],
            "tw_technical_current_state_v1",
        )
        self.assertEqual(report["evidence_passport"]["target_kind"], "tw_stock_technical_report")
        self.assertIn(report["evidence_passport"]["trust_level"], {"high", "medium", "low"})
        self.assertTrue(
            any(
                source["name"] == "market_daily_price"
                for source in report["evidence_passport"]["source_breakdown"]
            )
        )

    def test_report_and_signal_share_canonical_indicator_truth(self) -> None:
        report = build_stock_technical_report(
            db=self.db,
            stock_id="2330",
            timeframe="daily",
            include_intraday=False,
        )
        signal = calculate_latest_stock_signals(
            db=self.db,
            stock_id="2330",
            limit=100,
        )
        report_indicator = report["data"]["daily_indicator"]
        signal_indicator = signal["indicator_snapshot"]

        self.assertEqual(report["algorithm_version"], "tw.technical.indicators.v4")
        self.assertEqual(signal["indicator_engine"], report["indicator_engine"])
        self.assertEqual(report_indicator["rsi"], signal_indicator["rsi"])
        self.assertEqual(report_indicator["macd"], signal_indicator["macd"])
        self.assertEqual(report_indicator["kd"], signal_indicator["kd"])
        self.assertIn("j9", report_indicator["kd"])

    def test_indicator_engine_has_no_runtime_legacy_fallback(self) -> None:
        report = build_stock_technical_report(
            db=self.db,
            stock_id="2330",
            timeframe="daily",
            include_intraday=False,
        )

        self.assertEqual(report["indicator_engine"]["active_engine"], "canonical")
        self.assertFalse(report["indicator_engine"]["legacy_fallback_allowed"])
        self.assertEqual(
            report["algorithm_version"],
            "tw.technical.indicators.v4",
        )

    def test_daily_report_separates_finalized_decision_from_provisional_current_state(self) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 10, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "source": "test_intraday",
                    "previous_close": 179.0,
                    "points": [
                        {
                            "time": "2026-03-23T10:00:00+08:00",
                            "price": 130.0,
                            "volume": 5000,
                        }
                    ],
                },
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="daily",
                include_intraday=True,
            )

        price_context = report["data"]["price_context"]
        self.assertEqual(report["phase"], "daily_intraday")
        self.assertEqual(report["confidence"], "medium")
        self.assertEqual(price_context["price"], 130.0)
        self.assertTrue(price_context["is_provisional"])
        self.assertEqual(
            price_context["technical_price_basis"],
            "intraday_series_latest_price",
        )
        self.assertFalse(price_context["bid_ask_price_used"])
        self.assertEqual(price_context["daily_indicator_time"], "2026-03-21")
        self.assertEqual(
            price_context["moving_average_structure"]["price_state"],
            "above_all",
        )
        price_row = next(
            row for row in report["rows"] if row["key"] == "price_position"
        )
        self.assertIn("179", price_row["description"])
        self.assertNotIn("130", price_row["description"])
        self.assertTrue(any(badge["label"] == "站上 MA60" for badge in report["badges"]))
        self.assertTrue(report["data"]["price_context"]["range_signals"])
        self.assertTrue(
            any(badge["label"] == "今日暫估指標另列" for badge in report["badges"])
        )
        self.assertEqual(
            report["evidence_passport"]["as_of"],
            "2026-03-23T10:00:00+08:00",
        )
        self.assertEqual(report["data"]["decision_snapshot"], "completed")
        self.assertEqual(report["data"]["decision_state"]["position"]["price"], 179.0)
        self.assertEqual(report["data"]["current_state"]["position"]["price"], 179.0)
        self.assertEqual(report["data"]["decision_state_time"], "2026-03-21")
        self.assertEqual(report["data"]["current_state_time"], "2026-03-21")
        self.assertTrue(report["data"]["current_state_decision_usable"])
        self.assertIsNone(report["data"]["current_partial_indicator"])
        self.assertIsNone(report["data"]["current_observation"])
        self.assertEqual(report["data"]["daily_indicator"]["time"], date(2026, 3, 21))

    def test_post_close_report_does_not_inject_session_close_into_bar_truth(self) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 8, 27, 14, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "source": "persisted_intraday",
                    "previous_close": 592.0,
                    "points": [
                        {
                            "time": "2026-08-27T11:49:55+08:00",
                            "price": 601.0,
                            "volume": 8_000_000,
                        }
                    ],
                },
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="daily",
                include_intraday=True,
            )

        self.assertEqual(report["data"]["price_context"]["price"], 601.0)
        self.assertEqual(
            report["data"]["price_context"]["technical_price_basis"],
            "intraday_series_latest_price",
        )
        self.assertIsNone(report["data"]["current_partial_indicator"])
        self.assertEqual(report["data"]["current_state"]["position"]["price"], 179.0)
        self.assertEqual(report["data"]["decision_state"]["position"]["price"], 179.0)
        self.assertIsNone(report["data"]["current_observation"])

    def test_post_close_official_daily_owns_headline_when_already_published(self) -> None:
        lineage = (
            self.db.query(MarketDailyPrice)
            .filter(MarketDailyPrice.stock_id == "2330")
            .order_by(MarketDailyPrice.trade_date.desc())
            .first()
        )
        self.assertIsNotNone(lineage)
        self.db.add_all(
            [
                MarketDailyPrice(
                    source_id=lineage.source_id,
                    raw_result_id=lineage.raw_result_id,
                    trade_date=date(2026, 8, 26),
                    stock_id="2330",
                    stock_name="TSMC",
                    trade_volume=10_500_000,
                    open_price=590.0,
                    high_price=595.0,
                    low_price=588.0,
                    close_price=592.0,
                    price_change=2.0,
                ),
                MarketDailyPrice(
                source_id=lineage.source_id,
                raw_result_id=lineage.raw_result_id,
                trade_date=date(2026, 8, 27),
                stock_id="2330",
                stock_name="TSMC",
                trade_volume=11_106_000,
                open_price=608.0,
                high_price=608.0,
                low_price=593.0,
                close_price=605.0,
                price_change=13.0,
                ),
            ]
        )
        self.db.commit()

        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 8, 27, 14, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "source": "persisted_intraday",
                    "previous_close": 592.0,
                    "points": [
                        {
                            "time": "2026-08-27T11:49:55+08:00",
                            "price": 601.0,
                            "volume": 8_000_000,
                        }
                    ],
                },
            ),
            patch(
                "app.market.technical_report._current_partial_daily_indicator",
                return_value=None,
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        self.assertEqual(report["phase"], "post_close")
        self.assertEqual(report["title"], "正式日線已發布")
        self.assertEqual(report["rows"][0]["key"], "official_close_price")
        self.assertEqual(report["rows"][0]["label"], "正式收盤")
        self.assertEqual(report["rows"][0]["value"], 605.0)
        self.assertEqual(
            report["data"]["intraday"]["price_semantics"],
            "official_daily_close",
        )
        self.assertEqual(report["data"]["intraday"]["previous_close"], 592.0)

    def test_trailing_intraday_window_does_not_invent_open_range_or_volume_pace(self) -> None:
        points = [
            {
                "time": f"2026-03-23T11:{25 + index:02d}:00+08:00",
                "price": 180.0 + index,
                "open": 180.0 + index,
                "high": 181.0 + index,
                "low": 179.0 + index,
                "volume": 1_000,
            }
            for index in range(9)
        ]
        points.append(
            {
                "time": "2026-03-23T13:24:00+08:00",
                "price": 190.0,
                "open": 189.0,
                "high": 191.0,
                "low": 188.0,
                "volume": 1_000,
            }
        )
        coverage = {
            "status": "trailing_window",
            "opening_covered": False,
            "continuous_session_covered": False,
            "session_volume_complete": False,
            "gap_count": 255,
        }
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 13, 24, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "source": "nstock_minute_stock_data",
                    "previous_close": 179.0,
                    "points": points,
                    "series_coverage": coverage,
                },
            ),
            patch(
                "app.market.technical_report._current_partial_daily_indicator",
                side_effect=AssertionError(
                    "partial coverage must not build provisional OHLCV indicators"
                ),
            ),
            patch(
                "app.market.technical_report.build_tw_stock_volume_pace",
                side_effect=AssertionError(
                    "partial coverage must not compute cumulative volume pace"
                ),
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        intraday = report["data"]["intraday"]
        self.assertEqual(report["phase"], "intraday")
        self.assertEqual(report["title"], "盤中資料涵蓋不完整")
        self.assertEqual(report["score"], 0)
        self.assertFalse(intraday["score_eligible"])
        self.assertIsNone(intraday["stats"]["open"])
        self.assertIsNone(intraday["stats"]["high"])
        self.assertIsNone(intraday["stats"]["low"])
        self.assertIsNone(intraday["stats"]["volume"])
        self.assertIsNone(intraday["opening_gap_pct"])
        self.assertIsNone(intraday["price_vs_open_pct"])
        self.assertEqual(intraday["volume_pace"]["status"], "partial")

    def test_daily_report_uses_finalized_daily_state_after_close(self) -> None:
        self.db.query(MarketDailyPrice).filter(
            MarketDailyPrice.trade_date > date(2026, 3, 20)
        ).delete(synchronize_session=False)
        self.db.commit()

        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 20, 19, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload"
            ) as intraday,
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="daily",
                include_intraday=True,
            )

        intraday.assert_not_called()
        self.assertEqual(report["phase"], "daily")
        self.assertEqual(report["confidence"], "high")
        self.assertFalse(report["data"]["price_context"]["is_provisional"])
        self.assertTrue(report["data"]["current_state_decision_usable"])
        self.assertIsNone(report["data"]["current_observation"])
        self.assertEqual(
            report["data"]["price_context"]["technical_price_basis"],
            "official_completed_daily_close",
        )
        self.assertEqual(report["data"]["price_context"]["price_time"], "2026-03-20")
        self.assertFalse(
            any(
                badge["label"] == "今日暫估指標另列"
                for badge in report["badges"]
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

    def test_historical_cutoff_applies_to_all_technical_evidence(self) -> None:
        cutoff = date(2026, 2, 20)
        with patch(
            "app.ai.tools.get_taiwan_stock_event_history",
            return_value={
                "cache_status": "current",
                "coverage_start": "2020-01-01",
                "coverage_end": "2026-12-31",
                "results": [],
            },
        ):
            context = ai_tools.read_stock_technical_context(
                db=self.db,
                stock_id="2330",
                bars=40,
                analysis_horizon="swing",
                market_data_params={"trade_date": cutoff.isoformat()},
            )

        reports = context["data"]["technical_reports"]
        self.assertNotIn("today", reports)
        self.assertLessEqual(reports["daily"]["data"]["daily_indicator"]["time"], cutoff)
        self.assertLessEqual(reports["weekly"]["data"]["indicator"]["time"], cutoff)
        self.assertLessEqual(reports["monthly"]["data"]["indicator"]["time"], cutoff)
        evidence = context["data"]["technical_evidence"]
        completed = evidence["indicators"]["timeframes"]["daily"]["completed"]
        self.assertLessEqual(completed["time"], cutoff)
        self.assertIsNone(
            evidence["indicators"]["timeframes"]["daily"]["current_partial"]
        )
        relative_strength = evidence["relative_strength"]
        self.assertLessEqual(
            date.fromisoformat(relative_strength["stock_latest_date"]),
            cutoff,
        )
        benchmark_latest = relative_strength.get("benchmark_latest_date")
        if benchmark_latest is not None:
            self.assertLessEqual(date.fromisoformat(benchmark_latest), cutoff)
        self.assertEqual(
            evidence["indicators"]["corporate_action"]["relevant_analysis_end"],
            cutoff.isoformat(),
        )

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
        self.assertIn("short_term_stop", levels["risk"])
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

    def test_stock_context_exposes_compact_evidence_without_intraday_fetch(self) -> None:
        with (
            patch("app.ai.tools.read_taiwan_quote_evidence_projection") as quote_depth,
            patch("app.ai.tools._read_taiwan_bars") as bar_reader,
        ):
            context = ai_tools.read_stock_context(
                db=self.db,
                stock_id="2330",
                analysis_horizon="swing",
                include_intraday=False,
            )

        quote_depth.assert_not_called()
        bar_reader.assert_not_called()

        compact = context["data"]["compact"]
        self.assertEqual(compact["kind"], "stock_compact_evidence")
        self.assertEqual(compact["version"], "stock_compact_evidence.v1")
        self.assertEqual(compact["target"]["id"], "2330")
        self.assertEqual(compact["quote"]["source"], "market_daily_price")
        self.assertEqual(compact["quote"]["status"], "delayed_daily_close")
        self.assertEqual(compact["quote"]["latest_price"], compact["quote"]["price"])
        self.assertFalse(compact["quote"]["is_realtime"])
        self.assertIsNone(compact["quote"]["latency_ms"])
        self.assertIn("session_phase", compact["quote"])
        self.assertFalse(compact["intraday_bars"]["enabled"])
        self.assertIn("technical", compact)
        self.assertIn("chips", compact)
        self.assertEqual(compact["chips"]["institutional"]["quantity_unit"], "shares")
        self.assertEqual(compact["chips"]["margin"]["quantity_unit"], "lots")
        self.assertEqual(compact["chips"]["margin"]["raw_unit"], "lots")
        self.assertEqual(compact["chips"]["margin"]["normalized_unit"], "shares")
        self.assertEqual(
            compact["chips"]["margin"]["normalized_quantities"][
                "margin_today_balance"
            ],
            98_000_000,
        )
        self.assertEqual(compact["chips"]["margin"]["lot_size"], 1000)
        self.assertIn("fundamentals", compact)
        self.assertEqual(compact["events"], {})
        self.assertEqual(compact["regulation"], {})
        self.assertIn("quote", compact["freshness_by_domain"])
        self.assertIn("technical", compact["freshness_by_domain"])
        self.assertIn("chips", compact["freshness_by_domain"])
        self.assertIn("fundamentals", compact["freshness_by_domain"])
        self.assertEqual(compact["payload_level"], "compact")
        self.assertEqual(compact["slots"]["quote"]["payload_ref"], "quote")
        self.assertEqual(compact["slots"]["intraday"]["status"], "not_requested")
        self.assertEqual(compact["slots"]["intraday"]["payload_ref"], "intraday_bars")
        self.assertIn(compact["slots"]["cross_market"]["status"], {"ready", "partial", "missing"})
        self.assertEqual(compact["slots"]["cross_market"]["payload_ref"], "cross_market")

    def test_stock_context_compact_slots_follow_consumer_contract(self) -> None:
        context = ai_tools.read_stock_context(
            db=self.db,
            stock_id="2330",
            analysis_horizon="swing",
            include_intraday=False,
        )

        compact = context["data"]["compact"]
        slots = compact["slots"]
        expected_slots = {
            "identity",
            "quote",
            "intraday",
            "daily_chart",
            "technical",
            "chips_flows",
            "fundamentals",
            "cross_market",
            "news_events",
            "data_quality",
        }
        self.assertTrue(expected_slots.issubset(slots))

        for slot_key in expected_slots:
            self.assertSlotEnvelope(slots[slot_key])

        payload_ref_by_slot = {
            "identity": "target",
            "quote": "quote",
            "intraday": "intraday_bars",
            "daily_chart": "full.data.chart",
            "technical": "technical",
            "chips_flows": "chips",
            "fundamentals": "fundamentals",
            "cross_market": "cross_market",
            "data_quality": "data_quality",
        }
        for slot_key, payload_ref in payload_ref_by_slot.items():
            self.assertSlotEnvelope(slots[slot_key], payload_ref=payload_ref)

        payload_level_slots = expected_slots - {"identity"}
        for slot_key in payload_level_slots:
            self.assertSlotEnvelope(slots[slot_key], payload_level="compact")

    def test_payload_presence_helper_does_not_treat_false_as_data(self) -> None:
        self.assertFalse(ai_tools._has_payload_value({"available": False, "rows": []}))
        self.assertFalse(ai_tools._has_payload_value({"note": "   ", "rows": []}))
        self.assertTrue(ai_tools._has_payload_value({"price": 0}))

    def test_stock_context_compact_intraday_includes_quote_and_bars(self) -> None:
        quote_time = datetime(2026, 3, 21, 10, 5)

        def bar_series_result(*, db, instrument_id, interval, **kwargs):
            start = datetime(2026, 3, 21, 9, 0)
            bars = (
                SimpleNamespace(
                    start_at=start,
                    end_at=start + timedelta(minutes=1),
                    open_price=180.0,
                    high_price=181.0,
                    low_price=179.5,
                    close_price=180.5,
                    volume=SimpleNamespace(
                        value=1000,
                        unit=SimpleNamespace(value="shares"),
                    ),
                    turnover_value=None,
                    trade_count=None,
                    finalization=SimpleNamespace(value="final"),
                    lineage=SimpleNamespace(
                        provider="test_provider",
                        source=f"test_{interval}",
                    ),
                    volume_status="available",
                ),
                SimpleNamespace(
                    start_at=quote_time,
                    end_at=quote_time + timedelta(minutes=1),
                    open_price=180.5,
                    high_price=182.0,
                    low_price=180.0,
                    close_price=181.5,
                    volume=SimpleNamespace(
                        value=1500,
                        unit=SimpleNamespace(value="shares"),
                    ),
                    turnover_value=None,
                    trade_count=None,
                    finalization=SimpleNamespace(value="final"),
                    lineage=SimpleNamespace(
                        provider="test_provider",
                        source=f"test_{interval}",
                    ),
                    volume_status="available",
                ),
            )
            return SimpleNamespace(
                instrument=SimpleNamespace(
                    symbol=instrument_id,
                    model_dump=lambda **_kwargs: {
                        "market": "TW",
                        "symbol": instrument_id,
                        "instrument_type": "stock",
                        "venue": "TWSE",
                    },
                ),
                requested_interval=interval,
                base_interval="1m",
                bars=bars,
                bar_states=tuple(
                    SimpleNamespace(
                        start_at=bar.start_at,
                        source_interval="1m",
                        technical_eligible=True,
                    )
                    for bar in bars
                ),
                history=SimpleNamespace(
                    available_from=start,
                    available_to=quote_time,
                    requested_coverage_satisfied=True,
                    history_status=SimpleNamespace(value="ready"),
                    model_dump=lambda **_kwargs: {"history_status": "ready"},
                ),
                identity=SimpleNamespace(
                    series_fingerprint="a" * 64,
                    lineage_digest="b" * 64,
                    state_digest="c" * 64,
                    series_revision="d" * 64,
                ),
                session_resolution=(
                    SimpleNamespace(trade_date=date(2026, 3, 21)),
                ),
                current_session_coverage=SimpleNamespace(
                    trade_date=date(2026, 3, 21),
                    snapshot_phase=SimpleNamespace(value="ready"),
                    status=SimpleNamespace(value="complete_session"),
                ),
                warnings=(),
                limitations=(),
            )

        with (
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "source": "test_intraday",
                    "point_count": 2,
                    "previous_close": 179.0,
                    "points": [
                        {"time": "09:00", "close": 180.5, "volume": 1000},
                        {"time": "10:05", "close": 181.5, "volume": 1500},
                    ],
                },
            ),
            patch(
                "app.ai.tools.read_taiwan_quote_evidence_projection",
                return_value={
                    "provider": "test_provider",
                    "source": "twse_mis_public_quote",
                    "session_phase": "regular",
                    "phase_label": "regular",
                    "trade_date": date(2026, 3, 21),
                    "quote_time": quote_time,
                    "fetched_at": quote_time,
                    "last_price": 181.5,
                    "previous_close": 179.0,
                    "open_price": 180.0,
                    "high_price": 182.0,
                    "low_price": 179.5,
                    "change": 2.5,
                    "change_pct": 1.4,
                    "total_volume_lots": 2500,
                    "best_bid_price": 181.0,
                    "best_bid_size_lots": 20,
                    "best_ask_price": 181.5,
                    "best_ask_size_lots": 15,
                    "spread": 0.5,
                    "spread_pct": 0.28,
                    "depth_available": False,
                    "depth_status": "unavailable",
                    "provider_attempts": [
                        {
                            "provider": "test_provider",
                            "resource_id": "twse_mis_public_quote",
                        }
                    ],
                    "resolved_health": {
                        "fallback_used": False,
                        "selection_reason": "selected_ranked_candidate",
                    },
                    "freshness": {
                        "status": "live",
                        "is_live": True,
                        "is_stale": False,
                        "age_seconds": 5,
                        "expected_trade_date": date(2026, 3, 21),
                        "message": "ok",
                    },
                },
            ) as quote_depth,
            patch("app.ai.tools._read_taiwan_bars", side_effect=bar_series_result) as bar_reader,
        ):
            context = ai_tools.read_stock_context(
                db=self.db,
                stock_id="2330",
                analysis_horizon="intraday",
                include_intraday=True,
            )

        quote_depth.assert_called_once()
        bar_reader.assert_called_once()

        compact = context["data"]["compact"]
        self.assertEqual(compact["quote"]["source"], "twse_mis_public_quote")
        self.assertEqual(compact["quote"]["latest_price"], 181.5)
        self.assertEqual(compact["quote"]["price"], 181.5)
        self.assertEqual(compact["quote"]["last_price"], 181.5)
        self.assertTrue(compact["quote"]["is_realtime"])
        self.assertEqual(compact["quote"]["event_age_seconds"], 5)
        self.assertIsNone(compact["quote"]["latency_ms"])
        self.assertEqual(
            compact["quote"]["latency_ms_semantics"],
            "deprecated_network_latency_ms",
        )
        self.assertEqual(compact["quote"]["session_phase"], "regular")
        self.assertTrue(compact["intraday_bars"]["enabled"])
        self.assertEqual(set(compact["intraday_bars"]["series"].keys()), {"1m"})
        self.assertEqual(compact["intraday_bars"]["series"]["1m"]["returned_point_count"], 2)
        self.assertEqual(compact["intraday_bars"]["series"]["1m"]["latest"]["close"], 181.5)
        self.assertEqual(compact["intraday_bars"]["session_scope"], "current_session")
        self.assertEqual(
            compact["intraday_bars"]["series"]["1m"]["expected_trade_date"],
            "2026-03-21",
        )
        self.assertEqual(
            compact["freshness_by_capability"]["intraday.bars"]["status"],
            "current",
        )
        self.assertEqual(compact["freshness_by_domain"]["quote"]["status"], "live")
        self.assertEqual(compact["slots"]["quote"]["status"], "ready")
        self.assertEqual(compact["slots"]["intraday"]["status"], "ready")
        self.assertEqual(compact["slots"]["intraday"]["payload_level"], "compact")
        self.assertTrue(
            any(ref["name"] == "market_intraday_bar" for ref in compact["source_refs"])
        )
        self.assertNotIn("refresh", bar_reader.call_args.kwargs)
        self.assertEqual(
            bar_reader.call_args.kwargs["session_scope"],
            "current_session",
        )
        requested_at = bar_reader.call_args.kwargs["requested_at"]
        self.assertIsInstance(requested_at, datetime)
        self.assertIsNotNone(requested_at.tzinfo)

    def test_tw_index_context_compact_intraday_respects_payload_level(self) -> None:
        daily_points = [
            {
                "time": date(2026, 3, 1) + timedelta(days=index),
                "open": 18000.0 + index,
                "high": 18050.0 + index,
                "low": 17950.0 + index,
                "close": 18020.0 + index,
                "volume": 1_000_000 + index,
            }
            for index in range(30)
        ]
        intraday_points = [
            {
                "time": datetime(2026, 3, 20, 9, 0, tzinfo=TAIPEI_TZ)
                + timedelta(minutes=index),
                "price": 18100.0 + index,
                "open": 18100.0 + index,
                "high": 18110.0 + index,
                "low": 18090.0 + index,
                "volume": None,
            }
            for index in range(12)
        ]

        def chart_bundle(*, instrument_id, interval, **kwargs):
            source_points = intraday_points if interval == "1m" else daily_points
            bars = []
            states = []
            for point in source_points:
                raw_time = point["time"]
                start_at = (
                    raw_time
                    if isinstance(raw_time, datetime)
                    else datetime.combine(raw_time, datetime.min.time(), TAIPEI_TZ)
                )
                end_at = start_at + (
                    timedelta(minutes=1) if interval == "1m" else timedelta(days=1)
                )
                bars.append(
                    SimpleNamespace(
                        start_at=start_at,
                        end_at=end_at,
                        open_price=point["open"],
                        high_price=point["high"],
                        low_price=point["low"],
                        close_price=point.get("close", point.get("price")),
                        volume=None,
                        turnover_value=None,
                        trade_count=None,
                        finalization=SimpleNamespace(value="final"),
                        lineage=SimpleNamespace(
                            provider="test_provider",
                            source="tw_bar_service",
                        ),
                        volume_status="not_applicable",
                    )
                )
                states.append(
                    SimpleNamespace(
                        start_at=start_at,
                        source_interval="1m" if interval == "1m" else "1d",
                        technical_eligible=True,
                    )
                )
            revision = (interval.replace("m", "1") + "e" * 64)[:64]
            bar_series = SimpleNamespace(
                instrument=SimpleNamespace(
                    symbol=instrument_id,
                    model_dump=lambda **_kwargs: {
                        "market": "TW",
                        "symbol": instrument_id,
                        "instrument_type": "index",
                        "venue": "TWSE",
                    },
                ),
                requested_interval=interval,
                base_interval="1m" if interval == "1m" else "1d",
                bars=tuple(bars),
                bar_states=tuple(states),
                history=SimpleNamespace(
                    available_from=bars[0].start_at,
                    available_to=bars[-1].start_at,
                    requested_coverage_satisfied=True,
                    history_status=SimpleNamespace(value="ready"),
                    model_dump=lambda **_kwargs: {"history_status": "ready"},
                ),
                identity=SimpleNamespace(
                    series_fingerprint="a" * 64,
                    lineage_digest="b" * 64,
                    state_digest="c" * 64,
                    series_revision=revision,
                ),
                session_resolution=(
                    SimpleNamespace(trade_date=date(2026, 3, 20)),
                ),
                warnings=(),
                limitations=(),
            )
            technical_points = tuple(
                {
                    "time": bar.start_at,
                    "close": float(bar.close_price),
                }
                for bar in bars
            )
            technical = SimpleNamespace(
                points=technical_points,
                algorithm_version="tw.technical.indicators.v4",
                parameter_contract={"schema_version": "tw.technical.parameters.v1"},
                status=SimpleNamespace(value="available"),
                warnings=(),
                model_dump=lambda **_kwargs: {
                    "points": list(technical_points),
                    "algorithm_version": "tw.technical.indicators.v4",
                    "bar_series_revision": revision,
                },
            )
            return SimpleNamespace(
                bars=bar_series,
                technical=technical,
                series_revision=revision,
            )

        with (
            patch("app.ai.tools._read_taiwan_chart", side_effect=chart_bundle),
            patch(
                "app.ai.tools._read_taiwan_index_intraday_bars",
                side_effect=lambda *, index_id, **_kwargs: chart_bundle(
                    instrument_id=index_id,
                    interval="1m",
                ).bars,
            ),
            patch(
                "app.ai.tools._calculate_taiwan_technical",
                side_effect=lambda bars: chart_bundle(
                    instrument_id=bars.instrument.symbol,
                    interval="1m",
                ).technical,
            ),
            patch(
                "app.ai.tools.get_market_index_summary",
                return_value={
                    "indices": [
                        {
                            "index_id": "TAIEX",
                            "label": "加權指數",
                            "market": "TWSE",
                            "source": "fugle_indices_stream",
                            "provider": "fugle_marketdata",
                            "time": date(2026, 3, 20),
                            "as_of": "2026-03-20T13:20:00+08:00",
                            "close": 18111.0,
                            "previous_close": 18090.0,
                            "change": 21.0,
                            "change_pct": 21.0 / 18090.0 * 100,
                            "current_data_core": {
                                "index": {
                                    "status": "selected",
                                    "index_id": "TAIEX",
                                    "provider": "fugle_marketdata",
                                    "source": "fugle_indices_stream",
                                    "close": 18111.0,
                                    "change": 21.0,
                                    "previous_close": 18090.0,
                                    "as_of": "2026-03-20T13:20:00+08:00",
                                    "trade_date": "2026-03-20",
                                    "session": "continuous",
                                    "provisional": True,
                                    "official": False,
                                    "decision_usable": True,
                                    "resolved_health": {
                                        "status": "selected",
                                        "research_usable": True,
                                        "selection_reason": "canonical_current_index",
                                    },
                                }
                            },
                        }
                    ]
                },
            ),
            patch(
                "app.ai.tools._now",
                return_value=datetime(2026, 3, 20, 13, 20, tzinfo=TAIPEI_TZ),
            ),
            patch("app.ai.tools.get_latest_market_chip_daily", return_value=None),
            patch(
                "app.ai.tools.get_market_index_contributions",
                return_value={"positive": [], "negative": [], "source": "test"},
            ),
        ):
            context = ai_tools.read_tw_index_context(
                db=self.db,
                index_id="TAIEX",
                include_intraday=True,
                analysis_horizon="intraday",
                market_data_params={"payload_level": "summary"},
            )

        compact = context["data"]["compact"]
        self.assertEqual(compact["kind"], "tw_index_compact_evidence")
        self.assertEqual(compact["payload_level"], "summary")
        self.assertEqual(compact["target"]["type"], "tw_index")
        self.assertEqual(compact["quote"]["price"], 18111.0)
        self.assertEqual(compact["daily_chart"]["requested_interval"], "1d")
        self.assertTrue(compact["daily_chart"]["points"])
        self.assertEqual(compact["intraday_bars"]["bar_limit"], 1)
        series = compact["intraday_bars"]["series"]["1m"]
        self.assertEqual(series["point_count"], 12)
        self.assertEqual(series["returned_point_count"], 1)
        self.assertEqual(len(series["points"]), 1)
        self.assertEqual(series["latest"]["price"], 18111.0)
        self.assertEqual(series["session_scope"], "current_session")
        self.assertEqual(series["expected_trade_date"], "2026-03-20")
        self.assertEqual(series["observed_trade_dates"], ["2026-03-20"])
        self.assertEqual(compact["slots"]["intraday"]["status"], "ready")
        self.assertEqual(compact["slots"]["intraday"]["payload_level"], "summary")
        self.assertEqual(compact["slots"]["chips_flows"]["status"], "missing")
        self.assertEqual(len(context["data"]["intraday"]["points"]), 12)
        source_refs = context["source_refs"]
        self.assertIn(
            {"type": "resolved_market_data", "name": "tw.market_index.daily"},
            source_refs,
        )
        self.assertIn(
            {"type": "resolved_market_data", "name": "tw.market_index.current"},
            source_refs,
        )
        self.assertIn(
            {"type": "external_or_cache", "name": "market_index_intraday"},
            source_refs,
        )
        self.assertNotIn(
            {"type": "external_or_cache", "name": "yahoo_finance_chart"},
            source_refs,
        )

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
            patch("app.market.technical_report._canonical_intraday_payload") as intraday,
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
                "app.market.technical_report._canonical_intraday_payload",
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
                "app.market.technical_report._canonical_intraday_payload",
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
        self.assertEqual(report["score"], 0)
        TechnicalReportRead.model_validate(report)
        self.assertEqual(report["value_label"], "vs 昨收")
        self.assertGreater(report["value"], 0)
        self.assertTrue(any(row["key"] == "daily_background" for row in report["rows"]))

    def test_today_report_accepts_datetime_intraday_point_time(self) -> None:
        point_time = datetime(2026, 3, 23, 9, 1, tzinfo=TAIPEI_TZ)
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 10, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "stock_id": "2330",
                    "symbol": "2330",
                    "source": "test_intraday",
                    "previous_close": 180.0,
                    "point_count": 1,
                    "points": [
                        {
                            "time": point_time,
                            "price": 183.0,
                            "volume": 3_000,
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
        self.assertEqual(report["data"]["intraday"]["latest_point"]["time"], point_time)
        TechnicalReportRead.model_validate(report)

    def test_today_report_stale_intraday_preserves_response_score_contract(self) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 24, 8, 30, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "stock_id": "2330",
                    "symbol": "2330",
                    "source": "test_intraday",
                    "previous_close": 180.0,
                    "point_count": 1,
                    "points": [
                        {
                            "time": "2026-03-23T13:30:00+08:00",
                            "price": 183.0,
                            "volume": 3_000,
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

        self.assertEqual(report["phase"], "stale_intraday")
        self.assertEqual(report["score"], 0)
        self.assertFalse(report["data"]["intraday"]["score_eligible"])
        TechnicalReportRead.model_validate(report)

    def test_today_report_uses_finalized_backend_daily_projection_after_close(
        self,
    ) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 14, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "source": "test_intraday",
                    "previous_close": 180.0,
                    "points": [
                        {
                            "time": "2026-03-23T11:49:00+08:00",
                            "price": 183.0,
                            "volume": 10_000,
                        }
                    ],
                },
            ),
            patch(
                "app.market.technical_report._current_partial_daily_indicator",
                return_value={
                    "close": 185.0,
                    "open": 181.0,
                    "high": 186.0,
                    "low": 180.0,
                    "volume": 20_000,
                    "event_time": "2026-03-23T13:30:00+08:00",
                    "source": "taiwan_bar_service",
                    "session_close_finalization": "final",
                },
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        self.assertEqual(report["phase"], "post_close")
        self.assertEqual(report["score"], 0)
        price_row = report["rows"][0]
        self.assertEqual(price_row["key"], "session_close_price")
        self.assertEqual(price_row["label"], "收盤成交")
        self.assertEqual(price_row["value"], 185.0)
        self.assertNotIn("即時價格", str(report))
        self.assertEqual(
            report["data"]["intraday"]["price_semantics"],
            "session_close",
        )

    def test_today_report_does_not_call_last_trade_live_after_close(self) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 14, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "source": "test_intraday",
                    "previous_close": 180.0,
                    "points": [
                        {
                            "time": "2026-03-23T11:49:00+08:00",
                            "price": 183.0,
                            "volume": 10_000,
                        }
                    ],
                },
            ),
            patch(
                "app.market.technical_report._current_partial_daily_indicator",
                return_value=None,
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        self.assertEqual(report["phase"], "post_close_pending_close")
        self.assertEqual(report["score"], 0)
        self.assertEqual(report["rows"][0]["label"], "最後盤中成交")
        self.assertNotIn("即時價格", str(report))
        self.assertEqual(
            report["data"]["intraday"]["price_semantics"],
            "last_intraday_trade_pending_session_close",
        )

    def test_today_report_does_not_synthesize_bar_from_session_close_when_intraday_empty(
        self,
    ) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 14, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "source": "test_intraday",
                    "previous_close": 180.0,
                    "points": [],
                },
            ),
            patch(
                "app.market.technical_report._current_partial_daily_indicator",
                return_value=None,
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        self.assertEqual(report["phase"], "post_close_pending_close")
        self.assertEqual(report["rows"][0]["label"], "資料狀態")
        self.assertIsNone(report["value"])
        self.assertIn("intraday_trend.points", report["missing"])

    def test_today_report_uses_same_time_volume_pace_instead_of_daily_average(self) -> None:
        points = [
            {
                "time": f"2026-03-23T10:{minute:02d}:00+08:00",
                "price": 181.0 + minute / 100,
                "volume": 1_000,
                "open": 181.0,
                "high": 182.0,
                "low": 180.0,
            }
            for minute in range(6)
        ]
        volume_pace = {
            "kind": "tw_stock_same_time_volume_pace",
            "stock_id": "2330",
            "status": "ready",
            "as_of": "2026-03-23T10:05:00+08:00",
            "trade_date": "2026-03-23",
            "comparison_minute": "10:05",
            "calculation_basis": "same-time test baseline",
            "current_cumulative_volume": 6_000,
            "same_time_baseline_5d": {
                "sample_days": 5,
                "pace_ratio": 1.5,
            },
            "same_time_baseline_20d": {
                "sample_days": 20,
                "pace_ratio": 1.2,
            },
            "warnings": [],
        }

        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 10, 5, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "stock_id": "2330",
                    "symbol": "2330",
                    "source": "test_intraday",
                    "previous_close": 180.0,
                    "point_count": len(points),
                    "points": points,
                },
            ),
            patch(
                "app.market.technical_report.build_tw_stock_volume_pace",
                return_value=volume_pace,
            ),
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
            )

        row = next(item for item in report["rows"] if item["key"] == "volume_pace")
        self.assertEqual(row["display_value"], "1.50×")
        self.assertIn("同時段量比 5日 1.50× / 20日 1.20×", row["description"])
        self.assertNotIn("20日均量占比", row["description"])
        self.assertEqual(report["data"]["intraday"]["volume_pace"]["status"], "ready")

    def test_today_core_report_does_not_read_volume_pace_when_omitted(self) -> None:
        points = [
            {
                "time": "2026-03-23T10:05:00+08:00",
                "price": 181.0,
                "volume": 1_000,
                "open": 181.0,
                "high": 182.0,
                "low": 180.0,
            }
        ]

        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 10, 5, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report._canonical_intraday_payload",
                return_value={
                    "stock_id": "2330",
                    "symbol": "2330",
                    "source": "test_intraday",
                    "previous_close": 180.0,
                    "point_count": len(points),
                    "points": points,
                },
            ),
            patch(
                "app.market.technical_report.build_tw_stock_volume_pace"
            ) as volume_pace_reader,
        ):
            report = build_stock_technical_report(
                db=self.db,
                stock_id="2330",
                timeframe="today",
                include_intraday=True,
                include_volume_pace=False,
            )

        volume_pace_reader.assert_not_called()
        self.assertFalse(
            any(item["key"] == "volume_pace" for item in report["rows"])
        )
        self.assertEqual(
            report["data"]["intraday"]["volume_pace"]["status"],
            "not_requested",
        )
        self.assertFalse(report["data"]["intraday"]["volume_pace_requested"])
        self.assertNotIn("intraday_volume.same_time_baseline_5d", report["missing"])


if __name__ == "__main__":
    unittest.main()
