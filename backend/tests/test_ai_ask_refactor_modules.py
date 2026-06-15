from __future__ import annotations

import unittest

from types import SimpleNamespace

from app.ai import ask as ai_ask
from app.ai import ask_finalizer
from app.ai import ask_policy, ask_response_support, scope_resolution
from app.ai.schemas import AiAskRequest


class AiAskRefactorModuleTests(unittest.TestCase):
    def test_scope_resolution_resolves_explicit_futures_target(self) -> None:
        payload = AiAskRequest(
            question="台指期現在怎麼看？",
            target={"type": "tw_futures", "id": "txf"},
        )

        resolution = scope_resolution._resolve_scope(db=None, payload=payload)

        self.assertEqual(resolution.selected_scope_type, "tw_futures")
        self.assertEqual(resolution.selected_scope_id, "TXF")
        self.assertEqual(
            scope_resolution._resolution_target(resolution),
            {"type": "tw_futures", "id": "TXF", "label": None, "market": "TW"},
        )

    def test_policy_validation_and_trust_gating(self) -> None:
        payload = AiAskRequest(
            question="2330 目前可以買嗎？",
            target={"type": "tw_stock", "id": "2330"},
            allow_llm=True,
            allow_write=True,
            allow_external_fetch=True,
        )

        ask_policy._validate_request(payload)
        policy = ask_policy._policy(
            payload,
            ask_policy.AiAskServerPolicy(
                can_call_llm=True,
                can_write=False,
                can_external_fetch=True,
                trust_source="server",
            ),
        )

        self.assertTrue(policy["can_call_llm"])
        self.assertFalse(policy["can_write"])
        self.assertFalse(policy["can_generate_report"])
        self.assertTrue(policy["can_external_fetch"])

        with self.assertRaisesRegex(ValueError, "target.type"):
            ask_policy._validate_request(
                AiAskRequest(question="test", target={"type": "unsupported"})
            )

    def test_clarification_response_contract_uses_evidence_passport(self) -> None:
        payload = AiAskRequest(question="這檔現在怎麼看？")
        resolution = scope_resolution._clarify_scope(
            "stock",
            payload.question,
            "Question looks like a stock request but no target was resolved.",
        )

        response = ask_response_support._clarification_response(
            payload=payload,
            resolution=resolution,
            requested_mode="brief",
            policy={"can_generate_report": False},
        )

        self.assertEqual(response["contract_version"], "omi.ai.ask.v2")
        self.assertEqual(response["action"], "omi.ask.clarify")
        self.assertTrue(response["clarification"]["required"])
        self.assertEqual(response["next_actions"][0]["type"], "ask_clarification")
        self.assertIn("target_scope", response["evidence_passport"]["missing"])

    def test_ask_keeps_compatibility_aliases(self) -> None:
        self.assertIs(ai_ask._resolve_scope, scope_resolution._resolve_scope)
        self.assertIs(ai_ask._validate_request, ask_policy._validate_request)
        self.assertIs(ai_ask._report_level, ask_response_support._report_level)

    def test_finalizer_builds_response_and_progress_contract(self) -> None:
        events: list[dict[str, object]] = []
        progress = SimpleNamespace(
            evidence_passport=lambda passport: events.append(
                {"stage": "evidence_passport", "trust_level": passport.get("trust_level")}
            ),
            answer_ready=lambda **kwargs: events.append({"stage": "answer_ready", **kwargs}),
        )
        payload = AiAskRequest(
            question="2330 現在可以買嗎？",
            target={"type": "tw_stock", "id": "2330"},
        )
        resolution = scope_resolution.ScopeResolution(
            selected_scope_type="stock",
            selected_scope_id="2330",
            display_name="台積電",
            confidence="high",
            source="test",
        )
        assembled = SimpleNamespace(
            analysis_digest={"selected_score": 3, "source": "test"},
            result_source_refs=[{"type": "table", "name": "market_daily_price"}],
            combined_missing=[],
            combined_warnings=[],
            answer_ready=True,
            clarification={"required": False},
            next_actions=[],
            response_analysis={"human_answer": {"text": "結論：觀察。"}},
            reasoning_steps=[{"stage": "decision_synthesis", "message": "已組合回答。"}],
        )

        response = ask_finalizer.finalize_ask_response(
            payload=payload,
            resolution=resolution,
            requested_mode="auto",
            effective_mode="brief",
            action="omi.generate_stock_brief",
            result={"kind": "stock_context", "as_of": "2026-06-12"},
            response_target={"type": "tw_stock", "id": "2330", "label": "台積電"},
            assembled=assembled,
            policy={"can_call_llm": False},
            tool_plan={},
            tool_runs=[],
            freshness_result={"is_current": True, "missing": [], "warnings": []},
            progress=progress,
        )

        self.assertEqual(response["contract_version"], "omi.ai.ask.v2")
        self.assertTrue(response["answer_ready"])
        self.assertEqual(response["report_level"], "brief")
        self.assertEqual(response["target"]["id"], "2330")
        self.assertIn("evidence_passport", response)
        self.assertEqual(events[0]["stage"], "evidence_passport")
        self.assertEqual(events[1]["stage"], "answer_ready")


if __name__ == "__main__":
    unittest.main()
