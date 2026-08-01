from __future__ import annotations

import unittest
from unittest.mock import patch

from app.ai import answer_composer, decision_core, technical_analysis, us_decision_adapter
from app.ai.market_context.taiwan_projection import _compact_intraday_history
from app.db.models import StockMaster
from app.market.financial_metrics_history_backfill import _financial_payload


class AiP2SemanticTests(unittest.TestCase):
    def test_intraday_request_falls_back_to_daily_without_intraday_score(self) -> None:
        summary = technical_analysis._technical_analysis_summary(
            technical_reports={
                "today": {
                    "timeframe": "today",
                    "phase": "market_closed",
                    "score": None,
                    "title": "台股休市",
                    "confidence": "medium",
                    "data": {"intraday": {"point_count": 0}},
                },
                "daily": {
                    "timeframe": "daily",
                    "phase": "daily",
                    "score": 3,
                    "title": "短線偏多",
                    "summary": "日線證據可用。",
                    "confidence": "medium",
                    "rows": [],
                },
            },
            requested_horizon="intraday",
        )

        self.assertEqual(summary["selected_horizon"], "short")
        self.assertEqual(summary["effective_horizon"], "short")
        self.assertEqual(summary["selected_timeframe"], "daily")
        self.assertIsNone(summary["intraday_score"])
        self.assertEqual(summary["horizon_fallback_reason"], "intraday_evidence_unavailable")
        self.assertEqual(summary["fallback_reason"], "intraday_evidence_unavailable")
        self.assertIn("今日：盤中證據不足", summary["selected_title"])
        self.assertIn("歷史結構：短線偏多", summary["selected_title"])
        self.assertEqual(summary["today_state"]["status"], "unavailable")
        self.assertEqual(summary["historical_structure"]["title"], "短線偏多")
        self.assertIn("僅能引用歷史結構", summary["composite_state"])

    def test_intraday_summary_separates_today_from_historical_structure(self) -> None:
        summary = technical_analysis._technical_analysis_summary(
            technical_reports={
                "today": {
                    "timeframe": "today",
                    "phase": "intraday",
                    "score": 4,
                    "title": "盤中偏多",
                    "summary": "今日量價轉強。",
                    "confidence": "medium",
                    "rows": [],
                    "data": {
                        "intraday": {
                            "point_count": 12,
                            "score_eligible": True,
                            "is_current_session": True,
                            "latest_point": {
                                "time": "2026-07-31T10:15:00+08:00",
                                "price": 110,
                            },
                        }
                    },
                },
                "daily": {
                    "timeframe": "daily",
                    "phase": "daily",
                    "score": -3,
                    "title": "波段偏空",
                    "summary": "日線仍在空頭結構。",
                    "confidence": "high",
                    "rows": [],
                },
            },
            requested_horizon="intraday",
        )

        self.assertEqual(summary["effective_horizon"], "intraday")
        self.assertIsNone(summary["fallback_reason"])
        self.assertEqual(summary["today_state"]["title"], "盤中偏多")
        self.assertEqual(summary["historical_structure"]["title"], "波段偏空")
        self.assertEqual(
            summary["selected_title"],
            "今日：盤中偏多｜歷史結構：波段偏空",
        )
        self.assertIn("歷史結構為波段偏空", summary["composite_state"])

    def test_provider_refresh_without_points_is_explicit_empty(self) -> None:
        compact = _compact_intraday_history(
            {
                "provider": "example",
                "point_count": 0,
                "refreshed_count": 3,
                "points": [],
            }
        )

        self.assertEqual(compact["status"], "empty")
        self.assertEqual(compact["returned_point_count"], 0)
        self.assertTrue(any("returned no intraday points" in item for item in compact["warnings"]))

    def test_broker_branch_wording_is_not_entry_intent(self) -> None:
        self.assertEqual(
            decision_core.infer_question_intent("2380 近五天分點主要買賣方"),
            "broker_branch",
        )

    def test_broker_branch_answer_has_no_trading_instruction(self) -> None:
        answer = answer_composer.build_consumer_human_answer(
            question_intent="broker_branch",
            target={"id": "2380", "label": "2380 虹光"},
            analysis_digest={
                "compact_evidence": {
                    "chips": {
                        "broker_branch": {
                            "trade_date": "2026-07-17",
                            "requested_days": 5,
                            "available_days": 5,
                            "buy_top": [{"branch_name": "甲分點", "net_lots": 120}],
                            "sell_top": [{"branch_name": "乙分點", "net_lots": -80}],
                        }
                    }
                }
            },
            missing=[],
            warnings=[],
        )

        self.assertEqual(answer["style"], "broker_branch_summary")
        self.assertEqual(answer["action_plan"], [])
        self.assertIn("甲分點", answer["text"])
        self.assertNotIn("先不要買", answer["text"])

    def test_compact_context_action_text_does_not_repeat_label(self) -> None:
        answer = answer_composer.build_compact_context_consumer_answer(
            target={},
            analysis_digest={
                "slot_status_counts": {"ready": 1},
                "ready_slots": ["daily_price"],
                "problem_slots": [],
            },
            missing=[],
            warnings=[],
        )

        self.assertEqual(answer["headline"], "市場 資料狀態")
        self.assertNotIn("可用：可用：", answer["text"])

    def test_negative_us_score_is_bearish_not_neutral(self) -> None:
        component = {"key": "price_trend", "score": -5, "weight": 1.0, "included": True, "summary": "down"}
        zero = {"key": "other", "score": 0, "weight": 0.0, "included": True, "summary": "ok"}
        with (
            patch.object(us_decision_adapter, "_price_trend_component", return_value=component),
            patch.object(us_decision_adapter, "_volume_component", return_value=zero),
            patch.object(us_decision_adapter, "_fundamentals_component", return_value=zero),
            patch.object(us_decision_adapter, "_short_volume_component", return_value=zero),
            patch.object(us_decision_adapter, "_source_health_component", return_value=zero),
        ):
            decision = us_decision_adapter.build_us_stock_decision_adapter(
                {"data": {"daily_prices": [{"close_price": 100}]}, "missing": [], "warnings": []},
                "swing",
            )

        self.assertEqual(decision["selected_score"], -5)
        self.assertEqual(decision["stance"], "bearish")
        self.assertEqual(decision["selected_title"], "美股偏弱")

    def test_history_backfill_does_not_invent_release_date_from_fetch_time(self) -> None:
        payload = _financial_payload(
            source_id=1,
            raw_result_id=2,
            fiscal_year=2026,
            quarter=1,
            stock_id="2330",
            stock=StockMaster(stock_id="2330", stock_name="台積電"),
            market="TWSE",
            income={"公司名稱": "台積電", "營業收入": "100"},
            balance={},
        )

        self.assertIsNone(payload["report_date"])
        self.assertIsNone(payload["released_at"])
        self.assertIsNone(payload["filed_at"])
        self.assertEqual(payload["period"], "2026Q1")


if __name__ == "__main__":
    unittest.main()
