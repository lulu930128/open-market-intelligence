from __future__ import annotations

import unittest

from app.ai import answer_composer
from app.ai import ask as ai_ask


def _technical_levels() -> dict[str, object]:
    return {
        "kind": "technical_price_levels",
        "latest_price": 930,
        "entry": {
            "preferred_zone": {"low": 803, "high": 834},
            "do_not_chase_above": {"price": 871},
            "breakout_confirm_above": {"price": 950},
        },
        "risk": {
            "short_stop": {"price": 771},
            "technical_invalidation": {"price": 716},
        },
    }


class AiAnswerComposerTests(unittest.TestCase):
    def test_entry_answer_uses_price_levels_and_data_limits(self) -> None:
        answer = answer_composer.build_question_aware_consumer_answer(
            question_intent="entry_decision",
            target={"label": "2327 國巨"},
            analysis_digest={
                "selected_score": 3,
                "selected_confidence": "high",
                "display": "中短線偏多",
                "technical_levels": _technical_levels(),
                "decision_evidence": {
                    "market_session": {
                        "is_trading_day": False,
                        "date": "2026-06-14",
                        "latest_daily_date": "2026-06-12",
                        "next_trading_day": "2026-06-15",
                        "summary": "2026-06-14 非台股交易日，使用 2026-06-12 日線。",
                    },
                    "data_quality": {
                        "price": {"source": "market_daily_price.close_price", "as_of": "2026-06-12"}
                    },
                },
            },
            missing=[],
            warnings=[],
        )

        self.assertEqual(answer["source"], "question_intent")
        self.assertIn("不建議追價", answer["headline"])
        self.assertIn("追價上限 871", answer["summary"][0])
        self.assertIn("2026-06-14 非台股交易日", answer["data_limits"][0])
        self.assertIn("價格來源 market_daily_price.close_price", answer["data_limits"][1])
        self.assertEqual(
            [item["label"] for item in answer["scenarios"]],
            ["回測支撐", "突破延伸", "失效防守"],
        )
        self.assertIn("803-834", answer["scenarios"][0]["text"])
        self.assertIn("950", answer["scenarios"][1]["text"])
        self.assertIn("716", answer["counter_evidence"][0])
        self.assertIn("情境：", answer["text"])
        self.assertIn("反證：", answer["text"])
        self.assertIn("結論：", answer["text"])

    def test_llm_answer_filters_soft_missing_data_when_backend_has_no_gap(self) -> None:
        answer = answer_composer.build_llm_consumer_answer(
            report={
                "headline": "偏多但等確認",
                "stance": "bullish",
                "confidence": "high",
                "key_observations": ["站上 MA20", "缺少盤中成交快照"],
                "interpretation": ["回檔守住前低再評估"],
                "next_checks": ["等量能確認"],
                "risks": ["跌破 MA20 轉弱"],
                "missing_data": ["缺少 intraday_trend"],
            },
            target={"label": "2330 台積電"},
            analysis_digest={"display": "中短線偏多"},
            missing=[],
            warnings=[],
        )

        self.assertEqual(answer["source"], "llm_report")
        self.assertEqual(answer["data_limits"], [])
        self.assertNotIn("缺少盤中成交快照", answer["summary"])
        self.assertNotIn("缺少 intraday_trend", answer["detail"])
        self.assertIn("站上 MA20", answer["summary"])

    def test_source_health_data_limits_are_user_readable(self) -> None:
        limits = answer_composer.source_health_data_limits(
            {
                "entries": [
                    {
                        "resource": "market_daily_price",
                        "label": "Daily price",
                        "status": "stale",
                        "required": True,
                        "latest_data_date": "2026-06-12",
                        "expected_data_date": "2026-06-15",
                    },
                    {
                        "resource": "monthly_revenue",
                        "label": "Monthly revenue",
                        "status": "not_applicable",
                        "required": False,
                    },
                    {
                        "resource": "broker_branch_trade_daily",
                        "label": "Broker branch trade",
                        "status": "empty",
                        "required": True,
                    },
                ]
            }
        )

        self.assertEqual(
            limits,
            [
                "日收盤資料落後：最新 2026-06-12，預期 2026-06-15。",
                "券商分點目前沒有本地資料。",
            ],
        )

    def test_consumer_answer_includes_source_health_data_limits(self) -> None:
        answer = answer_composer.build_consumer_human_answer(
            question_intent="trend_view",
            target={"label": "2330 台積電"},
            analysis_digest={
                "display": "中短線評分 +2｜偏多",
                "selected_score": 2,
                "selected_confidence": "medium",
                "source_health": {
                    "entries": [
                        {
                            "resource": "institutional_trade_daily",
                            "label": "Institutional trade",
                            "status": "stale",
                            "required": True,
                            "latest_data_date": "2026-06-12",
                            "expected_data_date": "2026-06-15",
                        }
                    ]
                },
            },
            missing=[],
            warnings=[],
        )

        self.assertIn("法人買賣超資料落後", answer["data_limits"][0])
        self.assertIn("資料限制", answer["text"])

    def test_consumer_answer_caps_high_confidence_when_source_health_has_gaps(self) -> None:
        answer = answer_composer.build_consumer_human_answer(
            question_intent="trend_view",
            target={"label": "6449 鈺邦"},
            analysis_digest={
                "display": "中短線評分 +3｜偏多",
                "selected_score": 3,
                "selected_confidence": "high",
                "source_health": {
                    "entries": [
                        {
                            "resource": "institutional_trade_daily",
                            "label": "Institutional trade",
                            "status": "stale",
                            "required": True,
                            "latest_data_date": "2026-06-12",
                            "expected_data_date": "2026-06-16",
                        }
                    ]
                },
            },
            missing=[],
            warnings=[],
        )

        self.assertEqual(answer["confidence"], "medium")
        self.assertEqual(answer["confidence_label"], "中")
        self.assertIn("資料可信度限制", "\n".join(answer["data_limits"]))
        self.assertIn("信心：中", answer["text"])

    def test_trend_view_prefers_structured_price_levels_over_llm_wording(self) -> None:
        answer = answer_composer.build_consumer_human_answer(
            question_intent="trend_view",
            target={"label": "2303 聯電"},
            analysis_digest={
                "display": "中線結構偏多，但短線偏熱。",
                "selected_score": 3,
                "selected_confidence": "high",
                "technical_levels": {
                    "kind": "technical_price_levels",
                    "latest_price": 141.0,
                    "entry": {
                        "preferred_zone": {"low": 129.0, "high": 134.0},
                        "breakout_confirm_above": {"price": 156.0},
                        "do_not_chase_above": {"price": 143.0},
                    },
                    "risk": {
                        "short_stop": {"price": 124.0},
                        "technical_invalidation": {"price": 130.0},
                    },
                },
            },
            missing=[],
            warnings=[],
            llm_report={
                "headline": "2303 聯電：波段偏多但短線偏熱，141 元靠近追價上限",
                "interpretation": ["請觀察是否站穩 141 附近。"],
            },
        )

        self.assertEqual(answer["source"], "question_intent")
        self.assertEqual(answer["intent"], "trend_view")
        self.assertIn("129-134", answer["headline"])
        self.assertIn("129-134", answer["text"])
        self.assertIn("143", answer["text"])
        self.assertIn("156", answer["text"])
        self.assertIn("130", answer["text"])
        self.assertIn("回測支撐", [item["label"] for item in answer["scenarios"]])
        self.assertTrue(
            any("突破 156" in item["text"] for item in answer["scenarios"])
        )
        self.assertTrue(any("130" in item for item in answer["counter_evidence"]))
        self.assertNotIn("站穩 141", answer["text"])

    def test_position_decision_answer_keeps_decision_contract(self) -> None:
        answer = answer_composer.build_position_decision_consumer_answer(
            position_decision={
                "headline": "2330 低於成本但尚未觸發 -5% 停損",
                "stance": "bullish",
                "confidence": "high",
                "summary": ["成本 2,390 / 最新 2,310，浮動約 -3.35%。"],
                "action_plan": [{"label": "技術停損", "text": "觀察 MA20 2,280。"}],
                "risks": ["缺少部位大小。"],
                "data_limits": ["缺少部位大小。"],
                "entry_price": 2390,
                "latest_price": 2310,
                "levels": {"ma20": 2280},
                "direct_answer": "先看 MA20 是否失守。",
            },
            missing=[],
            warnings=[],
        )

        self.assertEqual(answer["source"], "position_decision")
        self.assertEqual(answer["intent"], "position_risk_decision")
        self.assertIn("position_decision", answer)
        self.assertEqual(
            [item["label"] for item in answer["scenarios"]],
            ["成本附近", "技術防守", "續抱條件"],
        )
        self.assertIn("MA20 2,280", answer["counter_evidence"][0])
        self.assertIn("方向：偏多", answer["text"])

    def test_watchlist_answer_uses_radar_section_only_when_available(self) -> None:
        with_radar = answer_composer.build_watchlist_consumer_answer(
            human_answer={
                "sections": [
                    {"label": "結論", "text": "科技股偏多。"},
                    {"label": "雷達", "text": "2 檔命中；優先看 2330 台積電。"},
                    {"label": "追蹤", "text": "2330 台積電"},
                    {"label": "等回測", "text": "2303 聯電"},
                    {"label": "保守", "text": "2454 聯發科"},
                ],
                "text": "結論：科技股偏多。",
            },
            overview={"stance": "偏多", "confidence": "high"},
            missing=[],
            warnings=[],
        )

        self.assertEqual(with_radar["summary"][0], "2 檔命中；優先看 2330 台積電。")
        self.assertEqual(with_radar["action_plan"][0]["label"], "雷達")
        self.assertIn("雷達：2 檔命中", with_radar["text"])

        without_radar = answer_composer.build_watchlist_consumer_answer(
            human_answer={
                "sections": [
                    {"label": "結論", "text": "科技股偏多。"},
                    {"label": "追蹤", "text": "2330 台積電"},
                    {"label": "等回測", "text": "2303 聯電"},
                    {"label": "保守", "text": "2454 聯發科"},
                ],
                "text": "結論：科技股偏多。",
            },
            overview={"stance": "偏多", "confidence": "high"},
            missing=[],
            warnings=[],
        )

        self.assertEqual(
            [item["label"] for item in without_radar["action_plan"]],
            ["優先看", "等回測", "保守"],
        )

    def test_watchlist_radar_answer_is_question_aware(self) -> None:
        digest = {
            "kind": "watchlist_sector_digest",
            "group_name": "科技股",
            "stance": "結構偏多",
            "confidence": "high",
            "display": "科技股 結構偏多；上漲 2、下跌 1。",
            "human_answer": {
                "text": "結論：科技股 結構偏多。\n雷達：2 檔命中。",
            },
            "radar": {
                "mode": "action",
                "matched_count": 2,
                "radar_count": 2,
                "is_current": True,
                "buckets": [
                    {"key": "breakout", "label": "突破動能", "count": 1},
                    {"key": "risk", "label": "風險優先", "count": 1},
                ],
            },
            "radar_rows": [
                {
                    "stock_id": "2330",
                    "label": "2330 台積電",
                    "bucket": "breakout",
                    "bucket_label": "突破動能",
                    "urgency": "high",
                    "action_label": "追蹤突破延續",
                    "change_pct_text": "+1.50%",
                    "primary_signal_label": "突破 20 日高",
                },
                {
                    "stock_id": "2454",
                    "label": "2454 聯發科",
                    "bucket": "risk",
                    "bucket_label": "風險優先",
                    "urgency": "medium",
                    "action_label": "優先檢查風控",
                    "change_pct_text": "-2.93%",
                    "primary_signal_label": "動能轉弱",
                },
            ],
        }

        risk_answer = answer_composer.build_consumer_human_answer(
            question_intent="risk_check",
            target={"type": "tw_watchlist", "label": "科技股"},
            analysis_digest=digest,
            missing=[],
            warnings=[],
        )

        self.assertEqual(risk_answer["source"], "watchlist_radar")
        self.assertEqual(risk_answer["style"], "watchlist_radar_summary")
        self.assertIn("風險", risk_answer["headline"])
        self.assertEqual(risk_answer["radar_rows"][0]["stock_id"], "2454")
        self.assertIn("2454 聯發科", risk_answer["summary"][1])
        self.assertNotIn("目前標的", risk_answer["text"])

        risk_answer_with_llm = answer_composer.build_consumer_human_answer(
            question_intent="risk_check",
            target={"type": "tw_watchlist", "label": "科技股"},
            analysis_digest=digest,
            missing=[],
            warnings=[],
            llm_report={"headline": "LLM 報告"},
        )
        self.assertEqual(risk_answer_with_llm["source"], "watchlist_radar")

        entry_answer = answer_composer.build_consumer_human_answer(
            question_intent="entry_decision",
            target={"type": "tw_watchlist", "label": "科技股"},
            analysis_digest=digest,
            missing=[],
            warnings=[],
        )

        self.assertEqual(entry_answer["source"], "watchlist_radar")
        self.assertIn("不建議整包追價", entry_answer["headline"])
        self.assertEqual(entry_answer["radar_rows"][0]["stock_id"], "2330")
        self.assertIn("雷達 2 檔命中", entry_answer["text"])

    def test_watchlist_radar_intent_understands_split_large_move_buckets(self) -> None:
        digest = {
            "radar_rows": [
                {
                    "stock_id": "3008",
                    "label": "3008 大立光",
                    "bucket": "surge_up",
                    "bucket_label": "急漲追價",
                    "urgency": "high",
                },
                {
                    "stock_id": "3661",
                    "label": "3661 世芯-KY",
                    "bucket": "selloff_risk",
                    "bucket_label": "急跌風控",
                    "urgency": "high",
                },
                {
                    "stock_id": "2454",
                    "label": "2454 聯發科",
                    "bucket": "trend_reclaim",
                    "bucket_label": "轉強站回",
                    "urgency": "medium",
                },
            ],
        }

        risk_rows = answer_composer.watchlist_radar_rows_for_intent(
            digest,
            question_intent="risk_check",
        )
        entry_rows = answer_composer.watchlist_radar_rows_for_intent(
            digest,
            question_intent="entry_decision",
        )

        self.assertEqual([row["stock_id"] for row in risk_rows], ["3661", "3008"])
        self.assertEqual([row["stock_id"] for row in entry_rows], ["3008", "2454"])

    def test_ask_wrappers_delegate_to_answer_composer(self) -> None:
        answer = {
            "headline": "測試",
            "stance_label": "偏多",
            "confidence_label": "高",
            "summary": ["第一點"],
            "action_plan": [{"label": "現在", "text": "觀察"}],
        }

        self.assertEqual(
            ai_ask._consumer_text(answer),
            answer_composer.consumer_text(answer),
        )
        self.assertEqual(
            ai_ask._generic_data_limits(missing=["x"], warnings=[]),
            answer_composer.generic_data_limits(missing=["x"], warnings=[]),
        )


if __name__ == "__main__":
    unittest.main()
