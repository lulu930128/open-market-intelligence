from __future__ import annotations

import unittest

from app.ai import answer_composer, answer_data_limits, reports
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
    def test_broker_primary_intent_uses_multi_domain_answer_profile(self) -> None:
        answer = answer_composer.build_consumer_human_answer(
            question_intent="broker_branch",
            target={
                "type": "tw_stock",
                "id": "2330",
                "market": "TW",
                "label": "台積電",
            },
            analysis_digest={
                "kind": "stock_analysis_digest",
                "selected_summary": "日線偏弱，等待量價重新轉強。",
                "selected_confidence": "medium",
                "compact_evidence": {
                    "quote": {
                        "price": 2350,
                        "quote_time": "2026-07-24T13:30:00+08:00",
                        "is_realtime": False,
                    },
                    "technical": {
                        "analysis": {
                            "selected_summary": "日線偏弱，等待量價重新轉強。",
                        },
                        "levels": {
                            "entry": {
                                "breakout_confirm_above": {"price": 2505},
                            },
                            "risk": {
                                "technical_invalidation": {"price": 2290},
                            },
                        },
                    },
                    "chips": {
                        "institutional": {
                            "trade_date": "2026-07-24",
                            "foreign_investor_net": -12500,
                            "total_institutional_net": -10300,
                        },
                        "margin": {
                            "trade_date": "2026-07-24",
                            "margin_today_balance": 21000,
                            "short_today_balance": 1300,
                        },
                        "broker_branch": {
                            "trade_date": "2026-07-24",
                            "available_days": 5,
                            "requested_days": 5,
                            "buy_top": [
                                {"branch_name": "分點甲", "net_lots": 120},
                            ],
                            "sell_top": [
                                {"branch_name": "分點乙", "net_lots": -80},
                            ],
                        },
                    },
                },
            },
            missing=[
                "shareholding_distribution_weekly",
                "monthly_revenue",
                "us_overnight_tw_impact",
            ],
            warnings=[
                "shareholding_distribution_weekly is stale",
                "monthly_revenue is stale",
                "US overnight context is stale",
            ],
            selected_capabilities=[
                "target.identity",
                "quote.snapshot",
                "daily.ohlcv",
                "technical.structure",
                "chips.institutional",
                "chips.margin",
                "broker_branch.summary",
                "data.freshness",
            ],
            requested_domains=[
                "quote",
                "chart",
                "technical",
                "chips",
                "broker_branch",
                "freshness",
            ],
        )

        self.assertEqual(answer["style"], "multi_domain_stock_summary")
        self.assertIn("2,350", answer["text"])
        self.assertIn("日線偏弱", answer["text"])
        self.assertIn("外資", answer["text"])
        self.assertIn("融資", answer["text"])
        self.assertIn("分點甲", answer["text"])
        self.assertIn("2,290", answer["text"])
        rendered_limits = "\n".join(answer["data_limits"])
        self.assertIn("shareholding_distribution_weekly", rendered_limits)
        self.assertNotIn("monthly_revenue", rendered_limits)
        self.assertNotIn("overnight", rendered_limits.casefold())

    def test_us_price_keeps_raw_number_and_adds_rounded_display_text(self) -> None:
        summary = reports._compact_us_stock_summary(
            {
                "summary": {},
                "data": {
                    "daily_prices": [
                        {
                            "trade_date": "2026-07-17",
                            "close_price": 202.80999755859375,
                        },
                        {
                            "trade_date": "2026-07-16",
                            "close_price": 200.0,
                        },
                    ]
                },
                "missing": [],
            }
        )

        self.assertEqual(summary["latest"]["close"], 202.80999755859375)
        self.assertEqual(summary["latest"]["close_display"], "202.81")
        self.assertIn("Latest US close 202.81", summary["highlights"][0])
        self.assertNotIn("202.80999755859375", summary["highlights"][0])

    def test_market_breadth_answer_calls_clear_weakness_from_decliners(self) -> None:
        answer = answer_composer.build_consumer_human_answer(
            question_intent="market_breadth",
            target={"type": "market", "market": "TW", "label": "台股"},
            analysis_digest={
                "kind": "market_brief_digest",
                "breadth": {
                    "label": "上市全市場廣度",
                    "advance_count": 88,
                    "decline_count": 971,
                    "unchanged_count": 12,
                    "limit_up_count": 4,
                    "limit_down_count": 84,
                },
            },
            missing=[],
            warnings=[],
            summary_limit=4,
            response_preferences=None,
        )

        self.assertEqual(answer["style"], "market_breadth_summary")
        self.assertEqual(answer["stance"], "bearish")
        self.assertIn("明顯偏弱", answer["headline"])
        self.assertIn("上漲 88、下跌 971", answer["text"])
        self.assertIn("跌停 84", answer["text"])
        self.assertEqual(answer["action_plan"], [])

    def test_market_breadth_answer_localizes_missing_counts_without_python_none(self) -> None:
        answer = answer_composer.build_consumer_human_answer(
            question_intent="market_breadth",
            target={"type": "market", "market": "TW", "label": "台股"},
            analysis_digest={
                "kind": "market_brief_digest",
                "breadth": {
                    "advance_count": None,
                    "decline_count": None,
                    "unchanged_count": None,
                    "limit_up_count": None,
                    "limit_down_count": None,
                },
            },
            missing=[],
            warnings=[],
        )

        self.assertIn("上漲 無資料、下跌 無資料、持平 無資料", answer["text"])
        self.assertNotIn("None", answer["text"])
        self.assertNotIn("漲停", answer["text"])

    def test_compact_context_answer_does_not_leak_english_next_fill_into_zh_tw(self) -> None:
        answer = answer_composer.build_compact_context_consumer_answer(
            target={"type": "market", "market": "TW", "label": "台股"},
            analysis_digest={
                "slot_status_counts": {"missing": 1},
                "problem_slots": [
                    {
                        "key": "derivatives",
                        "status": "missing",
                        "next_fill": (
                            "Keep derivatives as auxiliary risk context unless "
                            "the target market has a native derivatives workflow."
                        ),
                    }
                ],
            },
            missing=[],
            warnings=[],
            response_preferences={"effective_locale": "zh-TW"},
        )

        next_action = answer["action_plan"][-1]["text"]
        self.assertIn("refresh/provider", next_action)
        self.assertNotIn("Keep derivatives", next_action)

    def test_fallback_provider_stale_is_diagnostics_only(self) -> None:
        source_health = {
            "entries": [
                {
                    "resource": "daily_price",
                    "provider": "yahoo",
                    "provider_role": "selected",
                    "status": "current",
                    "required": True,
                },
                {
                    "resource": "daily_price",
                    "provider": "alphavantage",
                    "provider_role": "fallback",
                    "status": "stale",
                    "latest_data_date": "2026-06-18",
                    "expected_data_date": "2026-07-17",
                    "required": True,
                },
            ]
        }
        warning = (
            "US fallback provider stale: daily_price via alphavantage - "
            "latest 2026-06-18"
        )

        limits = answer_data_limits.source_health_data_limits(source_health)
        cap, reasons = answer_data_limits.confidence_cap_from_evidence(
            analysis_digest={"source_health": source_health},
            missing=[],
            warnings=[warning],
        )

        self.assertEqual(limits, [])
        self.assertIsNone(cap)
        self.assertEqual(reasons, [])
        self.assertFalse(answer_data_limits.warning_is_data_limit(warning))

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

    def test_generic_data_limits_translate_dataset_keys(self) -> None:
        limits = answer_composer.generic_data_limits(
            missing=[
                "institutional_trade_daily",
                "margin_trading_daily",
                "broker_branch_trade_daily",
                "us_overnight_tw_impact",
            ],
            warnings=[
                "Local OMI data is incomplete for 1 stock(s); affected datasets: institutional_trade_daily, margin_trading_daily, broker_branch_trade_daily. Refresh OMI before relying on AI conclusions.",
            ],
        )

        self.assertEqual(
            limits[0],
            "資料缺口或落後：法人買賣超、融資融券、券商分點、美股隔夜影響；結論需保留彈性。",
        )
        self.assertEqual(
            limits[1],
            "本地 OMI 資料尚未完整更新：法人買賣超、融資融券、券商分點；刷新後再依賴結論。",
        )

    def test_source_health_limits_are_prioritized_over_generic_missing(self) -> None:
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
                            "latest_data_date": "2026-06-26",
                            "expected_data_date": "2026-06-30",
                        }
                    ]
                },
            },
            missing=["institutional_trade_daily"],
            warnings=[],
        )

        self.assertIn("法人買賣超資料落後", answer["data_limits"][0])
        self.assertIn("資料缺口或落後：法人買賣超", answer["data_limits"][1])

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

    def test_multi_domain_answer_falls_back_to_aggressive_pullback_zone(self) -> None:
        answer = answer_composer.build_multi_domain_stock_consumer_answer(
            target={
                "type": "tw_stock",
                "id": "2330",
                "market": "TW",
                "label": "台積電",
            },
            analysis_digest={
                "selected_summary": "短線等待回測確認。",
                "compact_evidence": {
                    "quote": {
                        "price": 1000,
                        "trade_date": "2026-07-24",
                    },
                    "technical": {
                        "analysis": {"selected_summary": "短線等待回測確認。"},
                        "levels": {
                            "entry": {
                                "aggressive_zone": {
                                    "low": 970,
                                    "high": 985,
                                }
                            }
                        },
                    },
                },
            },
            missing=[],
            warnings=[],
            summary_limit=4,
            response_preferences=None,
        )

        self.assertIn("回測區 970–985", answer["text"])
        self.assertNotIn("回測區 缺資料", answer["text"])

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

    def test_consumer_text_uses_english_response_preferences(self) -> None:
        answer = {
            "headline": "Watch the breakout first",
            "stance_label": "Bullish",
            "confidence_label": "High",
            "summary": ["Price is above MA20"],
            "action_plan": [{"label": "Now", "text": "Wait for volume confirmation."}],
            "data_limits": ["There is 1 missing data item."],
        }

        text = answer_composer.consumer_text(
            answer,
            response_preferences={"effective_locale": "en-US"},
        )

        self.assertIn("Conclusion: Watch the breakout first", text)
        self.assertIn("Direction: Bullish / Confidence: High", text)
        self.assertIn("Key points:", text)
        self.assertIn("What to do:", text)
        self.assertIn("Data limits:", text)
        self.assertNotIn("結論：", text)

    def test_question_aware_answer_uses_english_response_preferences(self) -> None:
        answer = answer_composer.build_question_aware_consumer_answer(
            question_intent="entry_decision",
            target={"label": "2327 Yageo"},
            analysis_digest={
                "selected_score": 4,
                "selected_confidence": "high",
                "display": "Swing structure is bullish",
                "scores": {"swing": 4, "short": 2},
            },
            missing=[],
            warnings=[],
            response_preferences={"effective_locale": "en-US"},
        )

        self.assertEqual(answer["stance_label"], "Bullish")
        self.assertEqual(answer["confidence_label"], "High")
        self.assertIn("bullish watchlist", answer["headline"])
        self.assertEqual(
            [item["label"] for item in answer["action_plan"]],
            ["Now", "Entry condition", "Risk control"],
        )
        self.assertIn("Score: Swing +4, Short term +2", answer["summary"])
        self.assertIn("Conclusion:", answer["text"])
        self.assertIn("Direction: Bullish", answer["text"])
        self.assertNotIn("怎麼做：", answer["text"])

    def test_question_aware_answer_uses_japanese_response_preferences(self) -> None:
        answer = answer_composer.build_question_aware_consumer_answer(
            question_intent="entry_decision",
            target={"label": "2327 Yageo"},
            analysis_digest={
                "selected_score": 4,
                "selected_confidence": "high",
                "display": "Swing structure is bullish",
                "scores": {"swing": 4, "short": 2},
            },
            missing=[],
            warnings=[],
            response_preferences={"effective_locale": "ja-JP"},
        )

        self.assertEqual(answer["stance_label"], "強気寄り")
        self.assertEqual(answer["confidence_label"], "高")
        self.assertIn("強気候補", answer["headline"])
        self.assertEqual(
            [item["label"] for item in answer["action_plan"]],
            ["今", "エントリー条件", "リスク管理"],
        )
        self.assertIn("スコア：スイング +4、短期 +2", answer["summary"])
        self.assertIn("結論：", answer["text"])
        self.assertIn("方向：強気寄り", answer["text"])
        self.assertIn("対応：", answer["text"])
        self.assertNotIn("What to do:", answer["text"])

    def test_decision_evidence_uses_english_response_preferences(self) -> None:
        preferences = {"effective_locale": "en-US"}
        evidence = {
            "market_session": {
                "is_trading_day": False,
                "date": "2026-06-14",
                "latest_daily_date": "2026-06-12",
                "next_trading_day": "2026-06-15",
                "summary": "2026-06-14 台股休市，最新日線截至 2026-06-12。",
            },
            "data_quality": {
                "price": {"source": "market_daily_price.close_price", "as_of": "2026-06-12"},
                "volume": {"source": "market_daily_price.trade_volume", "display_value": "393.6 張"},
            },
            "recent_volatility": {
                "label": "high",
                "lookback_days": 5,
                "max_abs_change_pct": 6.8,
                "range_pct": 13.2,
                "large_move_days": 2,
            },
            "indicator_quality": {
                "macd": {"is_consistent": False},
            },
            "fundamentals": {
                "monthly_revenue": {
                    "period": "2026-05",
                    "year_over_year_pct": 12.5,
                    "month_over_month_pct": 3.2,
                }
            },
            "confidence_factors": {
                "data_limits": ["institutional_trade_daily 尚缺或不完整。"],
            },
        }

        summary = answer_composer.decision_evidence_summary_lines(
            evidence,
            response_preferences=preferences,
        )
        risks = answer_composer.decision_evidence_risk_lines(
            evidence,
            response_preferences=preferences,
        )
        data_limits = answer_composer.decision_evidence_data_lines(
            evidence,
            response_preferences=preferences,
        )

        self.assertIn("2026-06-14 is not a Taiwan trading day", summary[0])
        self.assertIn("Recent 5 days show high volatility", summary[1])
        self.assertIn("reduce size before chasing", risks[0])
        self.assertIn("MACD histogram does not match", risks[1])
        self.assertIn("Price source market_daily_price.close_price, as of 2026-06-12.", data_limits)
        self.assertIn("Volume source market_daily_price.trade_volume, displayed as about 393.6 張.", data_limits)
        data_gap_lines = answer_composer.decision_evidence_data_lines(
            {"confidence_factors": {"data_limits": ["institutional_trade_daily 尚缺或不完整。"]}},
            response_preferences=preferences,
        )
        self.assertIn("institutional trade is missing or incomplete.", data_gap_lines)

    def test_watchlist_radar_answer_uses_english_response_preferences(self) -> None:
        digest = {
            "kind": "watchlist_sector_digest",
            "group_name": "Tech watchlist",
            "stance": "結構偏多",
            "confidence": "high",
            "display": "Tech watchlist has 2 radar hits.",
            "radar": {
                "mode": "action",
                "matched_count": 2,
                "radar_count": 2,
                "is_current": False,
                "buckets": [
                    {"key": "breakout", "label": "突破動能", "count": 1},
                    {"key": "risk", "label": "風險優先", "count": 1},
                ],
            },
            "radar_rows": [
                {
                    "stock_id": "2330",
                    "label": "2330 TSMC",
                    "bucket": "breakout",
                    "bucket_label": "突破動能",
                    "urgency": "high",
                    "action_label": "追蹤突破延續",
                    "change_pct_text": "+1.50%",
                    "primary_signal_key": "donchian_breakout",
                    "primary_signal_label": "突破 20 日高",
                },
                {
                    "stock_id": "2454",
                    "label": "2454 MediaTek",
                    "bucket": "risk",
                    "bucket_label": "風險優先",
                    "urgency": "medium",
                    "action_label": "優先檢查風控",
                    "change_pct_text": "-2.93%",
                    "primary_signal_key": "macd_negative",
                    "primary_signal_label": "動能轉弱",
                },
            ],
        }

        answer = answer_composer.build_consumer_human_answer(
            question_intent="entry_decision",
            target={"type": "tw_watchlist", "label": "Tech watchlist"},
            analysis_digest=digest,
            missing=[],
            warnings=[],
            response_preferences={"effective_locale": "en-US"},
        )

        self.assertEqual(answer["source"], "watchlist_radar")
        self.assertEqual(answer["stance_label"], "Structurally bullish")
        self.assertIn("do not chase the whole basket", answer["headline"])
        self.assertIn("Radar matched 2 names: Breakout 1, Risk 1.", answer["summary"][0])
        self.assertIn("Candidate list: 2330 TSMC", answer["summary"][1])
        self.assertIn("20-day high breakout", answer["summary"][1])
        self.assertEqual(
            [item["label"] for item in answer["action_plan"]],
            ["Watch first", "Confirm", "Exclude"],
        )
        self.assertIn("Radar includes stale daily data", answer["data_limits"][0])
        self.assertIn("What to do:", answer["text"])
        self.assertNotIn("雷達", answer["text"])

    def test_watchlist_radar_answer_uses_japanese_response_preferences(self) -> None:
        digest = {
            "kind": "watchlist_sector_digest",
            "group_name": "Tech watchlist",
            "stance": "結構偏多",
            "confidence": "high",
            "display": "Tech watchlist has 2 radar hits.",
            "radar": {
                "mode": "action",
                "matched_count": 2,
                "radar_count": 2,
                "is_current": False,
                "buckets": [
                    {"key": "breakout", "label": "突破動能", "count": 1},
                    {"key": "risk", "label": "風險優先", "count": 1},
                ],
            },
            "radar_rows": [
                {
                    "stock_id": "2330",
                    "label": "2330 TSMC",
                    "bucket": "breakout",
                    "bucket_label": "突破動能",
                    "urgency": "high",
                    "action_label": "追蹤突破延續",
                    "change_pct_text": "+1.50%",
                    "primary_signal_key": "donchian_breakout",
                    "primary_signal_label": "突破 20 日高",
                },
                {
                    "stock_id": "2454",
                    "label": "2454 MediaTek",
                    "bucket": "risk",
                    "bucket_label": "風險優先",
                    "urgency": "medium",
                    "action_label": "優先檢查風控",
                    "change_pct_text": "-2.93%",
                    "primary_signal_key": "macd_negative",
                    "primary_signal_label": "動能轉弱",
                },
            ],
        }

        answer = answer_composer.build_consumer_human_answer(
            question_intent="entry_decision",
            target={"type": "tw_watchlist", "label": "Tech watchlist"},
            analysis_digest=digest,
            missing=[],
            warnings=[],
            response_preferences={"effective_locale": "ja-JP"},
        )

        self.assertEqual(answer["source"], "watchlist_radar")
        self.assertEqual(answer["stance_label"], "構造は強気寄り")
        self.assertIn("追いかけ買いしない", answer["headline"])
        self.assertIn("レーダーで 2 銘柄が一致：ブレイク 1、リスク 1。", answer["summary"][0])
        self.assertIn("候補リスト：2330 TSMC", answer["summary"][1])
        self.assertIn("20日高値ブレイク", answer["summary"][1])
        self.assertEqual(
            [item["label"] for item in answer["action_plan"]],
            ["先に確認", "確認", "除外"],
        )
        self.assertIn("レーダーには遅延した日足データ", answer["data_limits"][0])
        self.assertIn("対応：", answer["text"])
        self.assertNotIn("What to do:", answer["text"])

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
