from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.ai import ask_stages, capability_contract, llm, pipeline_progress
from app.ai.schemas import AiAskRequest


class AiAskStagesTests(unittest.TestCase):
    def test_normalize_payload_for_resolution_updates_auto_target(self) -> None:
        payload = AiAskRequest(question="2330 怎麼看")
        resolution = SimpleNamespace(selected_scope_id="2330")

        normalized = ask_stages.normalize_payload_for_resolution(
            payload=payload,
            resolution=resolution,
            request_target_id=lambda request: None,
            request_target_type=lambda request: "auto",
            resolution_target=lambda value: {"type": "tw_stock", "id": value.selected_scope_id},
        )

        self.assertEqual(normalized.target, {"type": "tw_stock", "id": "2330"})

    def test_build_question_stage_populates_policy_and_progress(self) -> None:
        events = []
        progress = pipeline_progress.OmiPipelineProgress(events.append)
        payload = AiAskRequest(
            question="2330 現在可以買入嗎？",
            target={"type": "tw_stock", "id": "2330"},
            mode="auto",
        )

        stage = ask_stages.build_question_stage(
            payload=payload,
            scope_type="stock",
            server_policy=object(),
            progress=progress,
            build_policy=lambda request, server_policy: {"can_generate_analysis": True},
            infer_mode=lambda request, scope_type, policy: "analysis",
            normalize_analysis_horizon=lambda value: value,
        )

        self.assertEqual(stage.question_intent, "entry_decision")
        self.assertEqual(stage.requested_mode, "analysis")
        self.assertTrue(stage.auto_mode_requested)
        self.assertEqual(stage.policy["question_intent"], "entry_decision")
        self.assertIn("question_understanding", stage.policy)
        self.assertEqual(events[0]["stage"], "question_understanding")

    def test_build_question_stage_owns_intraday_inference_without_refresh_escalation(
        self,
    ) -> None:
        progress = pipeline_progress.OmiPipelineProgress(lambda event: None)
        question = "TSM intraday live quote"
        payload = AiAskRequest(
            question=question,
            target={"type": "us_stock", "id": "TSM"},
            analysis_horizon="auto",
            allow_external_fetch=False,
        )

        stage = ask_stages.build_question_stage(
            payload=payload,
            scope_type="us_stock",
            server_policy=object(),
            progress=progress,
            build_policy=lambda request, server_policy: {
                "allow_external_fetch": request.allow_external_fetch
            },
            infer_mode=lambda request, scope_type, policy: "data_only",
            normalize_analysis_horizon=lambda value: value,
        )

        self.assertEqual(stage.payload.question, question)
        self.assertEqual(stage.requested_horizon, "auto")
        self.assertEqual(stage.effective_horizon, "intraday")
        self.assertEqual(stage.payload.analysis_horizon, "intraday")
        self.assertEqual(
            stage.policy["analysis_horizon"],
            {
                "requested": "auto",
                "effective": "intraday",
                "defaulted": True,
            },
        )
        self.assertFalse(stage.payload.allow_external_fetch)
        self.assertFalse(stage.policy["allow_external_fetch"])

    def test_build_question_stage_attaches_response_preferences(self) -> None:
        progress = pipeline_progress.OmiPipelineProgress(lambda event: None)
        payload = AiAskRequest(
            question="2330 怎麼看？",
            target={"type": "tw_stock", "id": "2330"},
            conversation_context={
                "ui_context": {
                    "settings": {
                        "response_locale": "en-US",
                        "response_language": "English",
                        "theme": "dark",
                        "technical_analysis_parameters": "server_persisted",
                    }
                }
            },
        )

        stage = ask_stages.build_question_stage(
            payload=payload,
            scope_type="stock",
            server_policy=object(),
            progress=progress,
            build_policy=lambda request, server_policy: {},
            infer_mode=lambda request, scope_type, policy: "brief",
            normalize_analysis_horizon=lambda value: value,
        )

        preferences = stage.policy["response_preferences"]
        self.assertEqual(preferences["requested_locale"], "en-US")
        self.assertEqual(preferences["effective_locale"], "en-US")
        self.assertEqual(preferences["language"], "English")
        self.assertEqual(preferences["theme"], "dark")
        self.assertIn("English", preferences["language_instruction"])

    def test_build_question_stage_honors_explicit_no_advice_request(self) -> None:
        progress = pipeline_progress.OmiPipelineProgress(lambda event: None)
        payload = AiAskRequest(
            question="只回資料狀態，不要投資建議",
            target={"type": "tw_stock", "id": "2330"},
        )

        stage = ask_stages.build_question_stage(
            payload=payload,
            scope_type="stock",
            server_policy=object(),
            progress=progress,
            build_policy=lambda request, server_policy: {
                "can_generate_analysis": True
            },
            infer_mode=lambda request, scope_type, policy: (
                "data_only"
                if request.output == "evidence_only"
                else "analysis"
            ),
            normalize_analysis_horizon=lambda value: value,
        )

        self.assertEqual(stage.payload.output, "evidence_only")
        self.assertEqual(stage.requested_mode, "data_only")

    def test_build_question_stage_promotes_saved_position_context(self) -> None:
        progress = pipeline_progress.OmiPipelineProgress(lambda event: None)
        payload = AiAskRequest(
            question="AAPL risk?",
            target={"type": "us_stock", "id": "AAPL"},
            position_context={
                "source": "portfolio_holding",
                "holding_id": 7,
                "entry_price": 150,
                "quantity": 10,
                "cost_amount": 1500,
                "currency": "USD",
            },
        )

        stage = ask_stages.build_question_stage(
            payload=payload,
            scope_type="us_stock",
            server_policy=object(),
            progress=progress,
            build_policy=lambda request, server_policy: {},
            infer_mode=lambda request, scope_type, policy: "brief",
            normalize_analysis_horizon=lambda value: value,
        )

        self.assertEqual(stage.question_intent, "position_risk_decision")
        self.assertTrue(stage.position_context["has_position_context"])
        self.assertEqual(stage.position_context["entry_price"], 150)
        self.assertEqual(stage.policy["position_context"]["source"], "portfolio_holding")
        self.assertEqual(
            stage.policy["question_understanding"]["intent"],
            "position_risk_decision",
        )

    def test_execute_tool_stages_runs_tw_stock_refresh_and_preserves_warnings(self) -> None:
        events = []
        progress = pipeline_progress.OmiPipelineProgress(events.append)
        payload = AiAskRequest(
            question="2330 今天最新怎麼看",
            target={"type": "tw_stock", "id": "2330"},
            allow_external_fetch=True,
        )
        freshness_result = {"is_current": False, "refresh_recommended": True}

        state = ask_stages.execute_tool_stages(
            scope_type="stock",
            payload=payload,
            resolution=SimpleNamespace(selected_scope_id="2330"),
            policy={"can_external_fetch": True},
            freshness_result=freshness_result,
            progress=progress,
            progress_callback=None,
            resolution_target=lambda resolution: {"type": "tw_stock", "id": resolution.selected_scope_id},
            require_scope_id=lambda request, scope_type: request.target["id"],
            require_group_id=lambda request: 1,
            refresh_before_answer_enabled=lambda request: True,
            run_us_stock_tool_session=lambda **kwargs: {},
            run_tw_stock_tool_session=lambda **kwargs: {
                "tool_plan": {"provider": "fallback"},
                "tool_runs": [{"tool": "tw.refresh_stock_evidence", "status": "success"}],
                "warnings": ["refreshed with fallback"],
                "freshness": {"is_current": True, "refresh_recommended": False},
            },
            run_tw_watchlist_tool_session=lambda **kwargs: {},
        )

        self.assertEqual(state.tool_plan["provider"], "fallback")
        self.assertEqual(state.tool_runs[0]["tool"], "tw.refresh_stock_evidence")
        self.assertEqual(state.warnings, ["refreshed with fallback"])
        self.assertTrue(state.freshness_result["is_current"])
        self.assertIn("tool_execution", [event["stage"] for event in events])

    def test_execute_tool_stages_runs_tw_selected_continuation_when_fresh(
        self,
    ) -> None:
        progress = pipeline_progress.OmiPipelineProgress(lambda event: None)
        target = {"type": "tw_stock", "id": "8299"}
        selection = capability_contract.normalize_selection(
            selection={"include": ["ownership.distribution"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        action_id = capability_contract.fill_action_id(
            capability_id="ownership.distribution",
            target=target,
            selection_version=selection["version"],
        )
        payload = AiAskRequest(
            question="補抓選取的股權分散能力",
            target=target,
            allow_external_fetch=True,
            contract_version="omi.decision.v4",
            continuation={
                "plan_id": capability_contract.fill_plan_id(
                    target=target,
                    action_ids=[action_id],
                ),
                "plan_action_ids": [action_id],
                "selected_action_ids": [action_id],
            },
        )
        captured: dict = {}

        def run_tw(**kwargs):
            captured.update(kwargs)
            return {
                "tool_plan": {"provider": "deterministic"},
                "tool_runs": [],
                "warnings": [],
                "freshness": {
                    "is_current": True,
                    "refresh_recommended": False,
                },
            }

        state = ask_stages.execute_tool_stages(
            scope_type="stock",
            payload=payload,
            resolution=SimpleNamespace(selected_scope_id="8299"),
            policy={"can_external_fetch": True},
            query_plan={
                "realtime_policy": "prefer_live",
                "external_refresh_allowed": True,
                "selected_capabilities": ["ownership.distribution"],
                "selection": selection,
            },
            freshness_result={
                "is_current": True,
                "refresh_recommended": False,
            },
            progress=progress,
            progress_callback=None,
            resolution_target=lambda resolution: {
                "type": "tw_stock",
                "id": resolution.selected_scope_id,
            },
            require_scope_id=lambda request, scope_type: request.target["id"],
            require_group_id=lambda request: 1,
            refresh_before_answer_enabled=lambda request: True,
            run_us_stock_tool_session=lambda **kwargs: {},
            run_tw_stock_tool_session=run_tw,
            run_tw_watchlist_tool_session=lambda **kwargs: {},
        )

        self.assertEqual(captured["stock_id"], "8299")
        self.assertEqual(
            captured["requested_capabilities"],
            ("ownership.distribution",),
        )
        self.assertEqual(state.tool_plan["provider"], "deterministic")

    def test_execute_tool_stages_runs_bounded_jp_stale_refresh(self) -> None:
        progress = pipeline_progress.OmiPipelineProgress(lambda event: None)
        payload = AiAskRequest(
            question="日經資料更新後再回答",
            target={"type": "jp_index", "id": "^N225"},
            allow_external_fetch=True,
            contract_version="omi.decision.v4",
        )
        captured: dict = {}

        def run_regional(**kwargs):
            captured.update(kwargs)
            return {
                "tool_plan": {
                    "provider": "deterministic",
                    "tool_plan": [
                        {
                            "tool": "jp.refresh_daily_price",
                            "args": {"symbol": "^N225"},
                        }
                    ],
                },
                "tool_runs": [
                    {"tool": "jp.refresh_daily_price", "status": "success"}
                ],
                "warnings": [],
                "freshness": {
                    "is_current": True,
                    "refresh_recommended": False,
                },
            }

        state = ask_stages.execute_tool_stages(
            scope_type="jp_index",
            payload=payload,
            resolution=SimpleNamespace(selected_scope_id="^N225"),
            policy={"can_external_fetch": True},
            query_plan={
                "realtime_policy": "prefer_live",
                "external_refresh_allowed": True,
                "selected_capabilities": ["daily.ohlcv"],
            },
            freshness_result={
                "is_current": False,
                "refresh_recommended": True,
            },
            progress=progress,
            progress_callback=None,
            resolution_target=lambda resolution: {
                "type": "jp_index",
                "id": resolution.selected_scope_id,
            },
            require_scope_id=lambda request, scope_type: request.target["id"],
            require_group_id=lambda request: 1,
            refresh_before_answer_enabled=lambda request: True,
            run_us_stock_tool_session=lambda **kwargs: {},
            run_tw_stock_tool_session=lambda **kwargs: {},
            run_tw_watchlist_tool_session=lambda **kwargs: {},
            run_regional_market_tool_session=run_regional,
        )

        self.assertEqual(captured["market"], "JP")
        self.assertTrue(captured["is_index"])
        self.assertEqual(captured["target_id"], "^N225")
        self.assertEqual(
            state.tool_runs[0]["tool"],
            "jp.refresh_daily_price",
        )
        self.assertTrue(state.freshness_result["is_current"])

    def test_execute_mode_stage_falls_back_to_brief_when_auto_analysis_llm_fails(self) -> None:
        events = []
        progress = pipeline_progress.OmiPipelineProgress(events.append)
        payload = AiAskRequest(
            question="2330 現在可以買入嗎？",
            target={"type": "tw_stock", "id": "2330"},
            mode="auto",
        )
        warnings: list[str] = []

        def fail_analysis(*args, **kwargs):
            raise llm.OpenAIConfigurationError("missing key")

        result = ask_stages.execute_mode_stage(
            db=None,
            payload=payload,
            scope_type="stock",
            effective_mode="analysis",
            auto_mode_requested=True,
            tool_runs=[],
            warnings=warnings,
            progress=progress,
            read_data_only=lambda *args, **kwargs: ("read", {}),
            build_brief=lambda *args, **kwargs: ("brief", {"kind": "ai_data_envelope"}),
            generate_analysis=fail_analysis,
            generate_report=lambda *args, **kwargs: ("report", {}),
        )

        self.assertEqual(result.effective_mode, "brief")
        self.assertEqual(result.action, "brief")
        self.assertIn("Auto analysis skipped", result.warnings[0])
        self.assertIn(
            "evidence_read:llm_fallback_to_brief",
            [event["dedupe_key"] for event in events],
        )

    def test_assemble_response_analysis_combines_answer_context(self) -> None:
        events = []
        captured_human_answer_kwargs = {}
        progress = pipeline_progress.OmiPipelineProgress(events.append)
        question_understanding = SimpleNamespace(
            as_policy_payload=lambda: {"intent": "entry_decision"}
        )

        assembled = ask_stages.assemble_response_analysis(
            result={"warnings": ["result warning"], "missing": ["daily_price"], "source_refs": [{"name": "market_daily_price"}]},
            freshness_result={"warnings": ["freshness warning"], "missing": ["margin_trade"]},
            warnings=["base warning"],
            resolution=SimpleNamespace(),
            effective_mode="brief",
            policy={"response_preferences": {"effective_locale": "en-US", "language": "English"}},
            requested_mode="brief",
            question_understanding=question_understanding,
            question_intent="entry_decision",
            position_context={},
            scope_type="stock",
            response_target={"type": "tw_stock", "id": "2330"},
            progress=progress,
            extract_list=lambda source, key: source.get(key, []),
            extract_analysis_digest=lambda result, policy: {"kind": "stock_analysis_digest"},
            clarification_dict=lambda resolution: {},
            build_next_actions=lambda **kwargs: [],
            build_position_decision=lambda **kwargs: {},
            try_attach_position_decision_llm=lambda **kwargs: {},
            build_consumer_human_answer=lambda **kwargs: (
                captured_human_answer_kwargs.update(kwargs) or {"text": "結論：觀察。"}
            ),
            build_reasoning_steps=lambda **kwargs: [
                {"stage": "decision_synthesis", "message": "已組合回答。"}
            ],
            payload=AiAskRequest(question="2330 可以買嗎"),
        )

        self.assertEqual(
            assembled.combined_missing,
            ["daily_price", "margin_trade"],
        )
        self.assertEqual(
            assembled.combined_warnings,
            ["base warning", "freshness warning", "result warning"],
        )
        self.assertEqual(assembled.response_analysis["human_answer"]["text"], "結論：觀察。")
        self.assertEqual(assembled.response_analysis["response_preferences"]["effective_locale"], "en-US")
        self.assertEqual(
            captured_human_answer_kwargs["response_preferences"]["effective_locale"],
            "en-US",
        )
        self.assertEqual(assembled.reasoning_steps[0]["stage"], "decision_synthesis")
        self.assertIn("decision_synthesis", [event["stage"] for event in events])

    def test_assemble_response_analysis_builds_position_decision_for_us_stock(self) -> None:
        progress = pipeline_progress.OmiPipelineProgress(lambda event: None)
        question_understanding = SimpleNamespace(
            as_policy_payload=lambda: {"intent": "position_risk_decision"}
        )

        assembled = ask_stages.assemble_response_analysis(
            result={},
            freshness_result={},
            warnings=[],
            resolution=SimpleNamespace(),
            effective_mode="brief",
            policy={},
            requested_mode="brief",
            question_understanding=question_understanding,
            question_intent="position_risk_decision",
            position_context={"has_position_context": True, "entry_price": 150},
            scope_type="us_stock",
            response_target={"type": "us_stock", "id": "AAPL"},
            progress=progress,
            extract_list=lambda source, key: source.get(key, []),
            extract_analysis_digest=lambda result, policy: {"kind": "stock_analysis_digest"},
            clarification_dict=lambda resolution: {},
            build_next_actions=lambda **kwargs: [],
            build_position_decision=lambda **kwargs: {"summary": ["position decision"]},
            try_attach_position_decision_llm=lambda **kwargs: kwargs["position_decision"],
            build_consumer_human_answer=lambda **kwargs: {},
            build_reasoning_steps=lambda **kwargs: [],
            payload=AiAskRequest(question="AAPL risk?"),
        )

        self.assertEqual(assembled.position_decision["summary"], ["position decision"])
        self.assertEqual(
            assembled.response_analysis["question_understanding"]["position_context"]["entry_price"],
            150,
        )

    def test_assemble_response_analysis_projects_decision_contract(self) -> None:
        progress = pipeline_progress.OmiPipelineProgress(lambda event: None)
        question_understanding = SimpleNamespace(
            as_policy_payload=lambda: {"intent": "entry_decision"}
        )

        def build_human_answer(**kwargs):
            return {
                "source": "question_intent",
                "style": "question_aware_summary",
                "headline": "Use a pullback plan",
                "text": "Conclusion: use a pullback plan.",
                "summary": ["Latest price is above the preferred zone."],
                "action_plan": [{"label": "Entry", "text": "Wait for pullback confirmation."}],
                "scenarios": [{"label": "Pullback", "text": "Preferred zone holds."}],
                "counter_evidence": ["Breaks the invalidation line."],
                "risks": ["Do not chase an extended move."],
                "data_limits": ["Daily price is stale."],
            }

        assembled = ask_stages.assemble_response_analysis(
            result={
                "warnings": ["result warning"],
                "missing": ["daily_price"],
                "source_refs": [{"name": "market_daily_price"}],
            },
            freshness_result={
                "is_current": False,
                "refresh_recommended": True,
                "warnings": ["freshness warning"],
                "missing": ["margin_trade"],
            },
            warnings=["base warning"],
            resolution=SimpleNamespace(),
            effective_mode="brief",
            policy={},
            requested_mode="brief",
            question_understanding=question_understanding,
            question_intent="entry_decision",
            position_context={},
            scope_type="stock",
            response_target={"type": "tw_stock", "id": "2330", "label": "2330 TSMC"},
            progress=progress,
            extract_list=lambda source, key: source.get(key, []),
            extract_analysis_digest=lambda result, policy: {"kind": "stock_analysis_digest"},
            clarification_dict=lambda resolution: {},
            build_next_actions=lambda **kwargs: [],
            build_position_decision=lambda **kwargs: {},
            try_attach_position_decision_llm=lambda **kwargs: {},
            build_consumer_human_answer=build_human_answer,
            build_reasoning_steps=lambda **kwargs: [],
            payload=AiAskRequest(question="Should I buy 2330 on a pullback?"),
        )

        decision_contract = assembled.response_analysis["decision_contract"]
        self.assertEqual(decision_contract["kind"], "omi_ai_decision_contract")
        self.assertEqual(decision_contract["version"], "decision_contract.v1")
        self.assertEqual(decision_contract["intent"], "entry_decision")
        self.assertEqual(decision_contract["answer_source"], "question_intent")
        self.assertEqual(decision_contract["answer_style"], "question_aware_summary")
        self.assertEqual(decision_contract["target"]["id"], "2330")
        self.assertEqual(decision_contract["headline"], "Use a pullback plan")
        self.assertEqual(decision_contract["text"], "Conclusion: use a pullback plan.")
        self.assertEqual(
            decision_contract["sections"]["action_plan"],
            [{"label": "Entry", "text": "Wait for pullback confirmation."}],
        )
        self.assertEqual(
            decision_contract["sections"]["scenarios"],
            [{"label": "Pullback", "text": "Preferred zone holds."}],
        )
        self.assertEqual(
            decision_contract["sections"]["counter_evidence"],
            ["Breaks the invalidation line."],
        )
        self.assertEqual(decision_contract["missing"], ["daily_price", "margin_trade"])
        self.assertEqual(
            decision_contract["warnings"],
            ["base warning", "freshness warning", "result warning"],
        )
        self.assertEqual(
            decision_contract["readiness"],
            {
                "answer_ready": True,
                "decision_ready": True,
                "has_text": True,
                "has_action_plan": True,
                "has_scenarios": True,
                "has_counter_evidence": True,
                "has_risks": True,
                "has_data_limits": True,
                "has_missing": True,
                "has_warnings": True,
            },
        )
        self.assertFalse(decision_contract["freshness"]["is_current"])
        self.assertTrue(decision_contract["freshness"]["refresh_recommended"])


if __name__ == "__main__":
    unittest.main()
