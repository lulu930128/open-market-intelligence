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
from app.market.indicator_service import calculate_indicator_points_from_ohlc_points
from app.market.schemas import TechnicalReportRead
from app.market.technical_report import TAIPEI_TZ, _fmt_price, build_stock_technical_report


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

    def test_daily_report_can_overlay_current_price_without_relabeling_daily_indicators(self) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 23, 10, 0, tzinfo=TAIPEI_TZ),
            ),
            patch(
                "app.market.technical_report.get_intraday_trend",
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
            "below_all",
        )
        self.assertTrue(any(row["key"] == "price_position" for row in report["rows"]))
        self.assertTrue(any(badge["label"] == "失守 MA60" for badge in report["badges"]))
        self.assertTrue(report["data"]["price_context"]["range_signals"])
        self.assertTrue(
            any(badge["label"] == "盤中價 × 已收盤指標" for badge in report["badges"])
        )
        self.assertEqual(
            report["evidence_passport"]["as_of"],
            "2026-03-23T10:00:00+08:00",
        )

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
                "app.market.technical_report.get_intraday_trend"
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
        self.assertEqual(
            report["data"]["price_context"]["technical_price_basis"],
            "official_completed_daily_close",
        )
        self.assertEqual(report["data"]["price_context"]["price_time"], "2026-03-20")
        self.assertFalse(
            any(
                badge["label"] == "盤中價 × 已收盤指標"
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
            patch("app.ai.tools.get_taiwan_stock_quote_depth") as quote_depth,
            patch("app.ai.tools.get_market_intraday_history") as intraday_history,
        ):
            context = ai_tools.read_stock_context(
                db=self.db,
                stock_id="2330",
                analysis_horizon="swing",
                include_intraday=False,
            )

        quote_depth.assert_not_called()
        intraday_history.assert_not_called()

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

        def history_result(*, db, stock_id, interval, range_value, refresh):
            return {
                "stock_id": stock_id,
                "symbol": "2330.TW",
                "interval": interval,
                "range": range_value,
                "provider": "test_provider",
                "source": f"test_{interval}",
                "from_time": datetime(2026, 3, 21, 9, 0),
                "to_time": quote_time,
                "point_count": 2,
                "cached_count": 0,
                "refreshed_count": 2,
                "points": [
                    {
                        "time": datetime(2026, 3, 21, 9, 0),
                        "open": 180.0,
                        "high": 181.0,
                        "low": 179.5,
                        "close": 180.5,
                        "volume": 1000,
                    },
                    {
                        "time": quote_time,
                        "open": 180.5,
                        "high": 182.0,
                        "low": 180.0,
                        "close": 181.5,
                        "volume": 1500,
                    },
                ],
            }

        with (
            patch(
                "app.market.technical_report.get_intraday_trend",
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
                "app.ai.tools.get_taiwan_stock_quote_depth",
                return_value={
                    "provider": "test_provider",
                    "source": "twse_mis_quote_depth",
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
                    "depth_available": True,
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
            patch("app.ai.tools.get_market_intraday_history", side_effect=history_result) as intraday_history,
        ):
            context = ai_tools.read_stock_context(
                db=self.db,
                stock_id="2330",
                analysis_horizon="intraday",
                include_intraday=True,
            )

        quote_depth.assert_called_once()
        self.assertEqual(intraday_history.call_count, 2)

        compact = context["data"]["compact"]
        self.assertEqual(compact["quote"]["source"], "twse_mis_quote_depth")
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
        self.assertEqual(set(compact["intraday_bars"]["series"].keys()), {"1m", "5m"})
        self.assertEqual(compact["intraday_bars"]["series"]["1m"]["returned_point_count"], 2)
        self.assertEqual(compact["intraday_bars"]["series"]["5m"]["latest"]["close"], 181.5)
        self.assertEqual(compact["freshness_by_domain"]["quote"]["status"], "live")
        self.assertEqual(compact["slots"]["quote"]["status"], "ready")
        self.assertEqual(compact["slots"]["intraday"]["status"], "ready")
        self.assertEqual(compact["slots"]["intraday"]["payload_level"], "compact")
        self.assertTrue(
            any(ref["name"] == "market_intraday_bar" for ref in compact["source_refs"])
        )

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

        def chart_result(*, index_id, timeframe, bars, db):
            return {
                "index_id": index_id,
                "timeframe": timeframe,
                "from_date": daily_points[0]["time"],
                "to_date": daily_points[-1]["time"],
                "point_count": len(daily_points),
                "points": daily_points,
            }

        with (
            patch("app.ai.tools.get_market_index_ohlc_chart_data", side_effect=chart_result),
            patch(
                "app.ai.tools.get_market_index_intraday",
                return_value={
                    "stock_id": "TAIEX",
                    "symbol": "^TWII",
                    "source": "twse_index_5s",
                    "previous_close": 18090.0,
                    "point_count": len(intraday_points),
                    "points": intraday_points,
                },
            ),
            patch(
                "app.ai.tools.get_market_index_summary",
                return_value={
                    "indices": [
                        {
                            "index_id": "TAIEX",
                            "label": "加權指數",
                            "market": "TWSE",
                            "source": "test",
                            "time": date(2026, 3, 20),
                            "close": 18111.0,
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
        self.assertEqual(compact["daily_chart"]["timeframe"], "daily")
        self.assertTrue(compact["daily_chart"]["points"])
        self.assertEqual(compact["intraday_bars"]["bar_limit"], 1)
        series = compact["intraday_bars"]["series"]["1m"]
        self.assertEqual(series["point_count"], 12)
        self.assertEqual(series["returned_point_count"], 1)
        self.assertEqual(len(series["points"]), 1)
        self.assertEqual(series["latest"]["price"], 18111.0)
        self.assertEqual(compact["slots"]["intraday"]["status"], "ready")
        self.assertEqual(compact["slots"]["intraday"]["payload_level"], "summary")
        self.assertEqual(compact["slots"]["chips_flows"]["status"], "missing")
        self.assertEqual(len(context["data"]["intraday"]["points"]), 12)

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
        self.assertEqual(report["score"], 0)
        TechnicalReportRead.model_validate(report)
        self.assertEqual(report["value_label"], "vs 昨收")
        self.assertGreater(report["value"], 0)
        self.assertTrue(any(row["key"] == "daily_background" for row in report["rows"]))

    def test_today_report_stale_intraday_preserves_response_score_contract(self) -> None:
        with (
            patch(
                "app.market.technical_report._now",
                return_value=datetime(2026, 3, 24, 8, 30, tzinfo=TAIPEI_TZ),
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
                "app.market.technical_report.get_intraday_trend",
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


if __name__ == "__main__":
    unittest.main()
