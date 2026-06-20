from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.ai import ask_stages, llm, pipeline_progress
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


if __name__ == "__main__":
    unittest.main()
