from __future__ import annotations

import unittest

from app.ai import decision_envelope, scope_resolution
from app.ai.schemas import AiAskRequest


def _v2_response(
    *,
    freshness_by_domain: dict[str, str] | None = None,
    trust_level: str = "high",
    ok: bool = True,
) -> dict:
    freshness_by_domain = freshness_by_domain or {
        "quote": "daily_close",
        "technical": "latest_completed_session",
    }
    query_plan = {
        "requested_domains": ["quote", "technical"],
        "required_domains": ["quote", "technical"],
        "payload_level": "compact",
    }
    passport = {
        "kind": "evidence_passport",
        "trust_level": trust_level,
        "trust_score": 91,
        **decision_envelope.build_domain_passport(
            compact={"freshness_by_domain": freshness_by_domain},
            query_plan=query_plan,
        ),
    }
    return {
        "kind": "ai_ask",
        "contract_version": "omi.ai.ask.v2",
        "ok": ok,
        "request_status": "completed",
        "question": "台積電可以怎麼規劃進場？",
        "target": {
            "type": "tw_stock",
            "id": "2330",
            "market": "TW",
            "label": "台積電",
        },
        "mode": {
            "requested": "brief",
            "effective": "brief",
            "response": "analysis",
            "payload_level": "compact",
        },
        "action": "omi.generate_stock_brief",
        "caller_profile": "frontend_readonly",
        "strategy_profile": "technical_swing",
        "resolution": {
            "target": {
                "type": "tw_stock",
                "id": "2330",
                "market": "TW",
                "exchange": "TWSE",
            }
        },
        "facts_ready": True,
        "analysis_ready": True,
        "answer_ready": True,
        "decision_ready": True,
        "blocked_sections": [],
        "available_sections": ["evidence", "human_answer", "decision_contract"],
        "analysis": {
            "question_intent": "entry_decision",
            "human_answer": {
                "kind": "consumer_market_answer",
                "headline": "等待回測確認，不追價",
                "text": "現階段先等價格回測支撐區並確認量價。",
                "summary": ["趨勢仍偏多", "短線不宜追價"],
                "stance_label": "條件式偏多",
                "confidence_label": "中",
                "source": "deterministic",
            },
            "decision_contract": {
                "intent": "entry_decision",
                "answer_source": "deterministic",
                "sections": {
                    "action_plan": [{"label": "等待", "text": "回測支撐再評估"}],
                    "scenarios": [{"label": "偏多", "text": "守住支撐且量能回升"}],
                    "counter_evidence": ["跌破技術失效位"],
                    "risks": ["資料僅到最近收盤"],
                    "data_limits": [],
                },
                "readiness": {"decision_ready": True},
            },
            "technical_levels": {
                "latest_price": 1000,
                "entry": {"preferred_zone": [970, 990]},
                "risk": {"technical_invalidation": 950},
            },
        },
        "result": {
            "kind": "stock_brief",
            "data": {
                "compact": {
                    "payload_level": "compact",
                    "freshness_by_domain": freshness_by_domain,
                    "slots": {
                        "quote": {"status": "ready"},
                        "technical": {"status": "ready"},
                        "data_quality": {"status": "ready"},
                    },
                },
                "slots": {
                    "quote": {"status": "ready"},
                    "technical": {"status": "ready"},
                    "data_quality": {"status": "ready"},
                },
            },
        },
        "freshness": {"status": "current"},
        "missing": [],
        "warnings": [],
        "source_refs": [{"type": "table", "name": "market_daily_price"}],
        "evidence_passport": passport,
        "policy": {"allow_llm": False},
        "query_plan": query_plan,
        "tool_plan": {"max_calls": 4},
        "tool_runs": [],
        "reasoning_steps": [{"stage": "decision", "message": "已完成決策結構"}],
        "diagnostics": {},
        "report_level": "brief",
        "next_context": {"last_target": {"type": "tw_stock", "id": "2330"}},
        "clarification": {},
        "next_actions": [],
        "error": {},
    }


class AiDecisionEnvelopeTests(unittest.TestCase):
    def test_v3_builds_one_canonical_decision_envelope(self) -> None:
        response = decision_envelope.build(_v2_response())

        self.assertEqual(response["kind"], "omi_decision")
        self.assertEqual(response["contract_version"], "omi.decision.v3")
        self.assertTrue(response["status"]["readiness"]["decision_ready"])
        self.assertEqual(response["answer"]["headline"], "等待回測確認，不追價")
        self.assertEqual(response["decision"]["intent"], "entry_decision")
        self.assertEqual(response["decision"]["price_levels"]["latest_price"], 1000)
        self.assertEqual(response["target"]["exchange"], "TWSE")
        self.assertEqual(response["evidence"]["slots"]["quote"]["status"], "ready")
        self.assertEqual(
            response["evidence"]["slots"]["quote"]["freshness"]["status"],
            "daily_close",
        )
        self.assertEqual(response["execution"]["strategy_profile"], "technical_swing")
        self.assertEqual(
            response["continuation"]["next_context"]["last_target"]["id"],
            "2330",
        )
        self.assertEqual(
            response["compatibility"]["source_contract_version"],
            "omi.ai.ask.v2",
        )
        self.assertNotIn("analysis", response)
        self.assertNotIn("result", response)

    def test_stale_required_domain_blocks_decision_and_marks_slots(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "stale",
                "technical": "latest_completed_session",
            },
            trust_level="medium",
        )
        response["warnings"] = ["報價資料已過期"]

        canonical = decision_envelope.build(response)

        readiness = canonical["status"]["readiness"]
        self.assertFalse(readiness["decision_ready"])
        self.assertIn("decision", readiness["blocked_sections"])
        self.assertEqual(readiness["evidence_status"], "partial")
        self.assertEqual(canonical["evidence"]["slots"]["quote"]["status"], "blocked")
        self.assertEqual(
            canonical["evidence"]["slots"]["quote"]["usability"],
            "unusable",
        )
        self.assertEqual(
            canonical["evidence"]["slots"]["data_quality"]["status"],
            "partial",
        )
        self.assertEqual(canonical["limitations"]["warnings"], ["報價資料已過期"])

    def test_business_error_keeps_canonical_shape(self) -> None:
        response = _v2_response(ok=False)
        response.update(
            {
                "request_status": "failed",
                "facts_ready": False,
                "analysis_ready": False,
                "answer_ready": False,
                "decision_ready": False,
                "error": {
                    "code": "TARGET_NOT_FOUND",
                    "message": "找不到指定標的",
                    "retryable": False,
                },
            }
        )

        canonical = decision_envelope.build(response)

        self.assertFalse(canonical["ok"])
        self.assertEqual(canonical["request_status"], "failed")
        self.assertEqual(canonical["answer"]["headline"], "等待回測確認，不追價")
        self.assertEqual(canonical["error"]["code"], "TARGET_NOT_FOUND")
        self.assertFalse(canonical["status"]["readiness"]["decision_ready"])

    def test_v2_remains_available_only_when_requested(self) -> None:
        response = _v2_response()

        legacy = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.ai.ask.v2",
        )
        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v3",
        )

        self.assertEqual(legacy["contract_version"], "omi.ai.ask.v2")
        self.assertEqual(canonical["contract_version"], "omi.decision.v3")

    def test_market_target_resolves_to_market_specific_context(self) -> None:
        cases = (
            ("US", "us_stock", "^GSPC"),
            ("JP", "jp_index", "^N225"),
            ("KR", "kr_index", "KOSPI"),
            ("TW", "market", None),
        )
        for market, expected_type, expected_id in cases:
            with self.subTest(market=market):
                resolution = scope_resolution._resolve_scope(
                    None,
                    AiAskRequest(
                        question="目前市場怎麼看？",
                        target={"type": "market", "market": market},
                    ),
                )
                self.assertEqual(resolution.selected_scope_type, expected_type)
                self.assertEqual(resolution.selected_scope_id, expected_id)
                self.assertEqual(resolution.selected_market, market)


if __name__ == "__main__":
    unittest.main()
