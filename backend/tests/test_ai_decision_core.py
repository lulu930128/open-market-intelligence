from __future__ import annotations

import unittest
from unittest.mock import patch

from app.ai import ask as ai_ask
from app.ai import decision_core
from app.ai.schemas import AiAskRequest


class AiDecisionCoreTests(unittest.TestCase):
    def test_regulation_question_is_not_generic_analysis(self) -> None:
        question = "2330 是否為處置股？撮合間隔與交易限制是什麼？"

        self.assertEqual(
            decision_core.infer_question_intent(question),
            "regulation",
        )
        self.assertIn(
            "regulation",
            decision_core.infer_question_intents(question),
        )

    def test_dated_close_question_is_quote_intent(self) -> None:
        for question in (
            "AAPL 2026-07-20 收盤價",
            "查 AAPL 20 號的收盤價",
            "AAPL closing price on 2026-07-20",
        ):
            with self.subTest(question=question):
                self.assertEqual(
                    decision_core.infer_question_intent(question),
                    "quote",
                )

    def test_infer_question_intents_preserves_independent_multi_intents(
        self,
    ) -> None:
        intents = decision_core.infer_question_intents(
            "2330 latest price, trend, broker branch, and freshness"
        )

        self.assertEqual(intents[0], "broker_branch")
        self.assertIn("quote", intents)
        self.assertIn("trend_view", intents)
        self.assertIn("data_freshness", intents)

    def test_market_breadth_intent_precedes_generic_market_analysis(self) -> None:
        self.assertEqual(
            decision_core.infer_question_intent("今天漲跌家數與跌停家數如何？"),
            "market_breadth",
        )

    def test_entry_question_understanding_handles_pullback_wording(self) -> None:
        understanding = decision_core.understand_question(
            question="以現在來說，2327 國巨適合買入嗎？如果要等回檔，價格大概看哪裡？",
            requested_horizon="auto",
            strategy_profile="short_term_momentum",
        )

        self.assertEqual(understanding.intent, "entry_decision")
        self.assertEqual(understanding.intent_confidence, "high")
        self.assertEqual(understanding.analysis_horizon, "swing")
        self.assertIn("買入", understanding.matched_hints)

    def test_position_risk_understanding_extracts_entry_price(self) -> None:
        context = decision_core.infer_position_context(
            "我買在2390，如果跌下去我該加碼還是認賠？停損要守哪？"
        )

        self.assertTrue(context.has_position_context)
        self.assertEqual(context.entry_price, 2390)
        self.assertEqual(context.decision_topic, "stop_loss")
        self.assertEqual(
            decision_core.infer_question_intent(
                "我買在2390，如果跌下去我該加碼還是認賠？停損要守哪？"
            ),
            "position_risk_decision",
        )

    def test_position_context_with_cost_price_routes_to_position_decision(self) -> None:
        understanding = decision_core.understand_question(
            question="我今天這檔買在444，你怎麼看",
            requested_horizon="auto",
            strategy_profile="technical_swing",
        )

        self.assertEqual(understanding.intent, "position_risk_decision")
        self.assertTrue(understanding.position_context.has_position_context)
        self.assertEqual(understanding.position_context.entry_price, 444)
        self.assertEqual(understanding.position_context.decision_topic, "position")

    def test_intraday_risk_question_sets_intraday_horizon(self) -> None:
        understanding = decision_core.understand_question(
            question="今天盤中 2330 追高風險怎麼看？跌到多少要先防守？",
            requested_horizon="auto",
            strategy_profile="short_term_momentum",
        )

        self.assertEqual(understanding.intent, "risk_check")
        self.assertEqual(understanding.analysis_horizon, "intraday")
        self.assertEqual(understanding.analysis_horizon_source, "question_intraday_hint")

    def test_analysis_with_freshness_keeps_analysis_as_primary_intent(self) -> None:
        understanding = decision_core.understand_question(
            question="分析台積電 2330，並告訴我各項資料日期與缺資料狀態。",
            requested_horizon="auto",
            strategy_profile="technical_swing",
        )

        self.assertEqual(understanding.intent, "general")
        self.assertEqual(understanding.intents, ("general", "data_freshness"))
        self.assertEqual(
            understanding.as_policy_payload()["intents"],
            ["general", "data_freshness"],
        )

    def test_pure_freshness_question_remains_freshness_primary(self) -> None:
        understanding = decision_core.understand_question(
            question="台積電 2330 的資料新鮮度",
        )

        self.assertEqual(understanding.intent, "data_freshness")
        self.assertEqual(understanding.intents, ("data_freshness",))

    def test_taiwan_futures_night_session_question_sets_intraday_horizon(self) -> None:
        horizon, source = decision_core.infer_analysis_horizon(
            question="TXF 夜盤大跌，所以外資現在一定又加空了嗎？",
            requested_horizon="auto",
            strategy_profile="technical_swing",
        )

        self.assertEqual((horizon, source), ("intraday", "question_intraday_hint"))

    def test_swing_and_long_horizon_are_inferred_from_question(self) -> None:
        swing_horizon, swing_source = decision_core.infer_analysis_horizon(
            question="TSLA 這幾週走勢怎麼看？",
            requested_horizon="auto",
            strategy_profile="short_term_momentum",
        )
        long_horizon, long_source = decision_core.infer_analysis_horizon(
            question="這檔長線投資可以嗎，基本面和營收如何？",
            requested_horizon="auto",
            strategy_profile="short_term_momentum",
        )

        self.assertEqual((swing_horizon, swing_source), ("swing", "question_swing_hint"))
        self.assertEqual((long_horizon, long_source), ("long", "question_long_hint"))

    def test_structured_swing_prompt_prefers_trend_view_over_generic_risk_wording(self) -> None:
        question = (
            "用中線波段角度分析目前標的。請使用日K/週K、均線、動能、量能、籌碼、營收與相對市場資料；"
            "先給結論，再列出趨勢、支撐壓力、觀察條件與主要風險。"
        )

        understanding = decision_core.understand_question(
            question=question,
            requested_horizon="swing",
            strategy_profile="technical_swing",
        )

        self.assertEqual(understanding.intent, "trend_view")
        self.assertEqual(understanding.analysis_horizon, "swing")
        self.assertIn("波段", understanding.matched_hints)
        self.assertIn("趨勢", understanding.matched_hints)

    def test_ui_swing_intent_guides_analysis_prompt_without_explicit_trend_keywords(self) -> None:
        understanding = decision_core.understand_question(
            question="請用這個角度分析目前標的，先給結論，再列觀察條件與主要風險。",
            requested_horizon="auto",
            strategy_profile="technical_swing",
            conversation_context={"ui_context": {"ask_intent": "swing"}},
        )

        self.assertEqual(understanding.intent, "trend_view")
        self.assertEqual(understanding.analysis_horizon, "swing")

    def test_common_chinese_question_phrasings_are_classified(self) -> None:
        cases = [
            ("這裡可以進一點嗎？", "entry_decision", "entry", "swing"),
            ("拉回到哪裡可以接？", "entry_decision", "entry", "swing"),
            ("這裡追會不會太晚？", "entry_decision", "entry", "swing"),
            ("前高附近還能追嗎？", "entry_decision", "entry", "swing"),
            ("回測 MA20 可不可以買？", "entry_decision", "entry", "swing"),
            ("現在是不是買點？", "entry_decision", "entry", "swing"),
            ("想分批買，價位怎麼抓？", "entry_decision", "entry", "swing"),
            ("這檔值得買嗎？", "entry_decision", "entry", "swing"),
            ("要不要進場？", "entry_decision", "entry", "swing"),
            ("可以低接嗎？", "entry_decision", "entry", "swing"),
            ("如果跌到支撐要加碼嗎？", "entry_decision", "entry", "swing"),
            ("突破前高後可以買進嗎？", "entry_decision", "entry", "swing"),
            ("以現在來說適合買入嗎？", "entry_decision", "entry", "swing"),
            ("今天盤中可以追嗎？", "entry_decision", "entry", "intraday"),
            ("我買在2390，要停損嗎？", "position_risk_decision", "stop_loss", "swing"),
            ("成本2390，跌破哪裡該砍？", "position_risk_decision", "stop_loss", "swing"),
            ("手上有台積電還能抱嗎？", "position_risk_decision", "hold", "swing"),
            ("續抱還是先減碼？", "position_risk_decision", "exit", "swing"),
            ("已經賺一段了要停利嗎？", "position_risk_decision", "take_profit", "swing"),
            ("我套牢了要認賠嗎？", "position_risk_decision", "exit", "swing"),
            ("跌破哪條線會轉弱？", "risk_check", "risk", "swing"),
            ("最大風險在哪？", "risk_check", "risk", "swing"),
            ("這裡會不會太危險？", "risk_check", "risk", "swing"),
            ("這支是不是轉弱了？", "risk_check", "risk", "swing"),
            ("還強嗎？", "trend_view", "none", "swing"),
            ("短線走勢怎麼看？", "trend_view", "none", "short"),
            ("這幾週波段怎麼看？", "trend_view", "none", "swing"),
            ("明天開盤要注意什麼？", "general", "none", "intraday"),
            ("月K跟基本面適合投資嗎？", "general", "none", "long"),
            ("這檔是否該出場？", "position_risk_decision", "exit", "swing"),
        ]

        for question, expected_intent, expected_topic, expected_horizon in cases:
            with self.subTest(question=question):
                understanding = decision_core.understand_question(
                    question=question,
                    requested_horizon="auto",
                    strategy_profile="short_term_momentum",
                )

                self.assertEqual(understanding.intent, expected_intent)
                self.assertEqual(understanding.position_context.decision_topic, expected_topic)
                self.assertEqual(understanding.analysis_horizon, expected_horizon)

    def test_ask_wrappers_delegate_to_decision_core(self) -> None:
        payload = AiAskRequest(
            question="現在盤中可以追嗎？",
            target={"type": "tw_stock", "id": "2330"},
            allow_external_fetch=True,
            analysis_horizon="auto",
        )

        self.assertEqual(ai_ask._infer_question_intent(payload.question), "entry_decision")
        self.assertEqual(ai_ask._infer_analysis_horizon(payload), "intraday")
        self.assertTrue(ai_ask._include_tw_intraday(payload))

    def test_explicit_intraday_capability_enables_tw_reader_for_neutral_question(
        self,
    ) -> None:
        payload = AiAskRequest(
            question="TAIEX status",
            contract_version="omi.decision.v4",
            target={"type": "tw_index", "id": "TAIEX"},
            mode="data_only",
            output="evidence_only",
            realtime_policy="prefer_live",
            allow_external_fetch=True,
            selection={"include": ["intraday.bars"]},
        )

        self.assertTrue(
            ai_ask._include_tw_intraday(
                payload,
                policy={
                    "can_external_fetch": True,
                    "query_plan": {
                        "selected_capabilities": [
                            "target.identity",
                            "intraday.bars",
                        ]
                    },
                },
            )
        )

    def test_cache_only_intraday_capability_reads_persisted_tw_bars(self) -> None:
        payload = AiAskRequest(
            question="TAIEX status",
            contract_version="omi.decision.v4",
            target={"type": "tw_index", "id": "TAIEX"},
            mode="data_only",
            output="evidence_only",
            realtime_policy="cache_only",
            selection={"include": ["intraday.bars"]},
        )

        self.assertTrue(
            ai_ask._include_tw_intraday(
                payload,
                policy={
                    "can_external_fetch": False,
                    "query_plan": {
                        "selected_capabilities": ["intraday.bars"],
                    },
                },
            )
        )

    def test_ask_response_exposes_question_understanding(self) -> None:
        payload = AiAskRequest(
            question="以現在來說，2327 國巨適合買入嗎？如果要等回檔，價格大概看哪裡？",
            target={"type": "tw_stock", "id": "2327"},
            mode="brief",
            allow_external_fetch=False,
        )
        fake_result = {
            "kind": "ai_data_envelope",
            "data": {
                "analysis": {
                    "selected_horizon": "swing",
                    "selected_score": 2,
                    "selected_title": "回檔觀察",
                    "selected_summary": "偏多但不追高。",
                    "selected_confidence": "medium",
                    "scores": {"swing": 2},
                },
                "technical_levels": {},
                "decision_evidence": {},
            },
            "missing": [],
            "warnings": [],
            "source_refs": [],
        }

        with (
            patch.object(
                ai_ask,
                "_resolve_scope",
                return_value=ai_ask.ScopeResolution(
                    selected_scope_type="stock",
                    selected_scope_id="2327",
                    display_name="2327 國巨",
                    confidence="high",
                    source="test",
                ),
            ),
            patch.object(ai_ask, "_check_freshness", return_value={"is_current": True}),
            patch.object(ai_ask, "_build_brief", return_value=("omi.generate_stock_brief", fake_result)),
        ):
            progress_events = []
            response = ai_ask.ask(
                db=None,  # type: ignore[arg-type]
                payload=payload,
                progress_callback=progress_events.append,
            )

        understanding = response["analysis"]["question_understanding"]
        self.assertEqual(understanding["intent"], "entry_decision")
        self.assertEqual(understanding["analysis_horizon"], "swing")
        self.assertEqual(understanding["analysis_horizon_source"], "default")
        self.assertIn("買入", understanding["matched_hints"])
        self.assertEqual(response["analysis"]["question_intent"], "entry_decision")
        progress_stages = [event["stage"] for event in progress_events]
        self.assertIn("question_understanding", progress_stages)
        self.assertIn("evidence_read", progress_stages)
        self.assertIn("evidence_passport", progress_stages)
        self.assertEqual(progress_stages[-1], "answer_ready")

    def test_auto_mode_routes_decision_questions_to_analysis_when_llm_is_allowed(self) -> None:
        payload = AiAskRequest(
            question="2330 現在可以買入嗎？",
            target={"type": "tw_stock", "id": "2330"},
            mode="auto",
            allow_llm=True,
        )
        policy = ai_ask._policy(
            payload,
            ai_ask.AiAskServerPolicy(can_call_llm=True, trust_source="local_allowlist"),
        )
        policy["question_intent"] = "entry_decision"

        self.assertEqual(ai_ask._infer_mode(payload, "stock", policy), "analysis")

    def test_auto_analysis_falls_back_to_brief_when_llm_fails(self) -> None:
        payload = AiAskRequest(
            question="2330 現在可以買入嗎？",
            target={"type": "tw_stock", "id": "2330"},
            mode="auto",
            allow_llm=True,
            allow_external_fetch=False,
        )
        fake_result = {
            "kind": "ai_data_envelope",
            "data": {
                "analysis": {
                    "selected_horizon": "swing",
                    "selected_score": 1,
                    "selected_title": "觀察",
                    "selected_summary": "先等確認。",
                    "selected_confidence": "medium",
                },
                "technical_levels": {},
                "decision_evidence": {},
            },
            "missing": [],
            "warnings": [],
            "source_refs": [],
        }

        with (
            patch.object(
                ai_ask,
                "_resolve_scope",
                return_value=ai_ask.ScopeResolution(
                    selected_scope_type="stock",
                    selected_scope_id="2330",
                    display_name="2330 台積電",
                    confidence="high",
                    source="test",
                ),
            ),
            patch.object(ai_ask, "_check_freshness", return_value={"is_current": True}),
            patch.object(
                ai_ask,
                "_generate_analysis",
                side_effect=ai_ask.llm.OpenAIConfigurationError("missing key"),
            ),
            patch.object(ai_ask, "_build_brief", return_value=("omi.generate_stock_brief", fake_result)),
        ):
            response = ai_ask.ask(
                db=None,  # type: ignore[arg-type]
                payload=payload,
                server_policy=ai_ask.AiAskServerPolicy(
                    can_call_llm=True,
                    trust_source="local_allowlist",
                ),
            )

        self.assertEqual(response["mode"]["requested"], "analysis")
        self.assertEqual(response["mode"]["effective"], "brief")
        self.assertEqual(response["mode"]["response"], "brief")
        self.assertIn("Auto analysis skipped", response["warnings"][0])
        self.assertEqual(response["action"], "omi.generate_stock_brief")


if __name__ == "__main__":
    unittest.main()
