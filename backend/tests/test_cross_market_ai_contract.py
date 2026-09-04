from __future__ import annotations

import unittest

from app.ai import (
    answer_composer,
    answer_evidence,
    capability_contract,
    data_quality_contract,
    decision_contract,
    decision_core,
    decision_envelope,
    evidence_builder,
    query_plan,
)
from app.ai.market_context import taiwan_projection, taiwan_stock
from app.ai.schemas import AiAskRequest


def _canonical_context(
    *,
    stance: str = "supportive",
    status: str = "ready",
    decision_usable: bool = True,
) -> dict[str, object]:
    return {
        "kind": "cross_market_target_context",
        "schema_version": "cross_market.context.v1",
        "status": status,
        "decision_usable": decision_usable,
        "as_of": "2026-08-08",
        "decision_at": "2026-08-09T01:00:00Z",
        "methodology_version": "cross_market.relation_context.v2",
        "relation_snapshot_version": "relation_registry:42:v1",
        "snapshot_id": "cmctx:2330:test",
        "summary": {
            "stance": stance,
            "score": 3.5 if stance == "supportive" else -3.5,
            "confidence": "high",
            "title": "ADR parity is above the Taiwan reference",
            "reason_codes": ["direct_adr_parity"],
        },
        "coverage": {
            "configured_signal_count": 1,
            "available_signal_count": 1,
            "decision_usable_signal_count": 1 if decision_usable else 0,
            "configured_weight": 1.0,
            "available_weight": 1.0,
            "decision_usable_weight": 1.0 if decision_usable else 0.0,
            "coverage_ratio": 1.0 if decision_usable else 0.0,
            "excluded_by_reason": {},
        },
        "signals": [
            {
                "signal_id": "direct:42",
                "relation_id": 42,
                "bucket": "direct_equivalent",
                "relation_type": "same_equity_dr",
                "direction": stance,
                "status": status,
                "decision_usable": decision_usable,
                "contribution": 3.5 if decision_usable else None,
                "excluded_reason": None if decision_usable else "stale",
            }
        ],
        "freshness": {"status": status},
        "missing": [] if decision_usable else ["adr_daily_price"],
        "warnings": [],
        "limitations": ["direct_equivalent_only_phase_2"],
        "source_refs": [{"type": "derived", "name": "cross-market-test"}],
    }


def _analysis_digest(cross_market: dict[str, object] | None) -> dict[str, object]:
    decision_evidence: dict[str, object] = {
        "kind": "stock_decision_evidence_v1",
        "confidence_factors": {"positive": [], "negative": [], "data_limits": []},
    }
    if cross_market is not None:
        decision_evidence["cross_market"] = cross_market
    return {
        "kind": "stock_analysis_digest",
        "selected_horizon": "swing",
        "selected_timeframe": "weekly",
        "selected_score": 2.0,
        "selected_title": "Technical structure remains constructive",
        "selected_summary": "Price remains above the medium-term support zone.",
        "selected_confidence": "high",
        "technical_levels": {},
        "decision_evidence": decision_evidence,
    }


class CrossMarketAiContractTests(unittest.TestCase):
    def test_question_intent_and_default_selection_are_cross_market_focused(self) -> None:
        intent = decision_core.infer_question_intent(
            "2330 的 ADR 與美股隔夜影響如何？"
        )
        self.assertEqual(intent, "cross_market")

        selection = capability_contract.normalize_selection(
            selection=None,
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            target_market="TW",
            question_intent=intent,
        )

        self.assertEqual(
            selection["required"],
            [
                "target.identity",
                "cross_market.overnight",
                "cross_market.relations",
                "cross_market.parity",
                "data.freshness",
            ],
        )

        for stock_id, question in (
            ("2330", "2330 的 ADR 與美股隔夜影響如何？"),
            ("2408", "2408 的 MU 與美股隔夜影響如何？"),
        ):
            with self.subTest(stock_id=stock_id):
                plan = query_plan.build_query_plan(
                    payload=AiAskRequest(
                        question=question,
                        target={"type": "stock", "id": stock_id, "market": "TW"},
                        output="evidence_only",
                        realtime_policy="cache_only",
                    ),
                    scope_type="stock",
                    question_intent=decision_core.infer_question_intent(question),
                    effective_mode="data_only",
                    target_market="TW",
                )
                self.assertEqual(plan.reader_profile, "standard")
                self.assertEqual(plan.requested_domains, ("cross_market",))
                self.assertEqual(
                    plan.selection["required"],
                    [
                        "target.identity",
                        "cross_market.overnight",
                        "cross_market.relations",
                        "cross_market.parity",
                        "data.freshness",
                    ],
                )
                self.assertNotIn("market.cross_market", plan.selected_capabilities)
                self.assertEqual(plan.selection["unsupported_capabilities"], [])
                self.assertEqual(plan.selection["unmet_required_capabilities"], [])

    def test_cross_market_domain_is_scoped_before_capability_diagnostics(self) -> None:
        stock_selection = capability_contract.normalize_selection(
            selection={},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            target_market="TW",
            question_intent="general",
            requested_domains=("cross_market",),
        )

        self.assertTrue(
            {
                "cross_market.overnight",
                "cross_market.relations",
                "cross_market.parity",
            }
            <= set(stock_selection["required"])
        )
        self.assertNotIn("market.cross_market", stock_selection["required"])
        self.assertEqual(stock_selection["unsupported_capabilities"], [])
        self.assertEqual(stock_selection["unmet_required_capabilities"], [])

        market_selection = capability_contract.normalize_selection(
            selection={},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="market",
            target_market="TW",
            question_intent="general",
            requested_domains=("cross_market",),
        )

        self.assertIn("market.cross_market", market_selection["required"])
        self.assertNotIn("cross_market.overnight", market_selection["required"])
        self.assertNotIn("cross_market.relations", market_selection["required"])
        self.assertNotIn("cross_market.parity", market_selection["required"])
        self.assertEqual(market_selection["unsupported_capabilities"], [])

    def test_explicit_market_cross_market_request_for_stock_remains_unsupported(
        self,
    ) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["market.cross_market"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            target_market="TW",
            question_intent="cross_market",
        )

        self.assertNotIn("market.cross_market", selection["required"])
        self.assertEqual(
            selection["unsupported_capabilities"],
            [
                {
                    "capability": "market.cross_market",
                    "status": "unsupported",
                    "reason_code": "unsupported_target_scope",
                    "requested_as": "required",
                    "request_source": "explicit_selection",
                    "target_scope": "stock",
                    "target_market": "TW",
                    "supported_scopes": ["market"],
                    "supported_markets": [],
                    "message": (
                        "market.cross_market is not supported for target "
                        "scope=stock, market=TW."
                    ),
                }
            ],
        )
        self.assertEqual(
            selection["unmet_required_capabilities"],
            selection["unsupported_capabilities"],
        )

    def test_decision_projection_is_context_only_with_stable_lineage(self) -> None:
        projected = evidence_builder.cross_market_decision_evidence(
            {"cross_market_context": _canonical_context()}
        )

        self.assertEqual(projected["role"], "confirmation_or_counter_evidence")
        self.assertEqual(projected["ranking_effect"], "none")
        self.assertEqual(projected["technical_score_effect"], "none")
        self.assertEqual(projected["snapshot_id"], "cmctx:2330:test")
        self.assertEqual(
            projected["relation_snapshot_version"],
            "relation_registry:42:v1",
        )
        self.assertEqual(projected["signals"][0]["relation_id"], 42)

    def test_taiwan_stock_decision_evidence_receives_overnight_context(self) -> None:
        evidence = taiwan_stock._stock_decision_evidence(
            latest_daily=None,
            chart={"points": []},
            latest_revenue=None,
            latest_financial=None,
            technical_reports={},
            overnight_impact={"cross_market_context": _canonical_context()},
            missing=[],
            source_refs=[],
        )

        self.assertEqual(
            evidence["cross_market"]["snapshot_id"],
            "cmctx:2330:test",
        )

    def test_cross_market_answer_is_structured_and_never_emits_trade_action(self) -> None:
        projected = evidence_builder.cross_market_decision_evidence(
            {"cross_market_context": _canonical_context()}
        )
        answer = answer_composer.build_consumer_human_answer(
            question_intent="cross_market",
            target={"type": "tw_stock", "id": "2330", "label": "TSMC"},
            analysis_digest=_analysis_digest(projected),
            missing=[],
            warnings=[],
            selected_capabilities=[
                "cross_market.overnight",
                "cross_market.relations",
                "cross_market.parity",
            ],
            requested_domains=["cross_market"],
            response_preferences={"locale": "en-US"},
        )

        self.assertEqual(answer["style"], "cross_market_context_summary")
        self.assertEqual(answer["stance"], "supportive")
        self.assertEqual(answer["ranking_effect"], "none")
        self.assertEqual(answer["technical_score_effect"], "none")
        self.assertEqual(answer["action_plan"], [])
        self.assertEqual(answer["cross_market_context"]["snapshot_id"], "cmctx:2330:test")
        self.assertIn("technical ranking is unchanged", answer["headline"])

    def test_context_can_augment_but_not_flip_technical_answer(self) -> None:
        projected = evidence_builder.cross_market_decision_evidence(
            {"cross_market_context": _canonical_context(stance="adverse")}
        )
        baseline = answer_composer.build_consumer_human_answer(
            question_intent="trend_view",
            target={"type": "tw_stock", "id": "2330", "label": "TSMC"},
            analysis_digest=_analysis_digest(None),
            missing=[],
            warnings=[],
            response_preferences={"locale": "en-US"},
        )
        contextual = answer_composer.build_consumer_human_answer(
            question_intent="trend_view",
            target={"type": "tw_stock", "id": "2330", "label": "TSMC"},
            analysis_digest=_analysis_digest(projected),
            missing=[],
            warnings=[],
            response_preferences={"locale": "en-US"},
        )

        self.assertEqual(contextual["headline"], baseline["headline"])
        self.assertEqual(contextual["stance"], baseline["stance"])
        self.assertEqual(contextual["action_plan"], baseline["action_plan"])
        self.assertEqual(contextual["ranking_effect"], "none")
        self.assertTrue(
            any("Cross-market counter-evidence" in item for item in contextual["risks"])
        )

    def test_outward_decision_contract_exposes_bounded_cross_market_context(self) -> None:
        projected = evidence_builder.cross_market_decision_evidence(
            {"cross_market_context": _canonical_context()}
        )
        human_answer = answer_composer.build_consumer_human_answer(
            question_intent="cross_market",
            target={"type": "tw_stock", "id": "2330", "label": "TSMC"},
            analysis_digest=_analysis_digest(projected),
            missing=[],
            warnings=[],
            response_preferences={"locale": "en-US"},
        )

        outward = decision_contract.build_decision_contract(
            question_intent="cross_market",
            target={"type": "tw_stock", "id": "2330", "label": "TSMC"},
            human_answer=human_answer,
            freshness_result={"status": "current", "is_current": True},
            missing=[],
            warnings=[],
            answer_ready=True,
        )

        context = outward["context"]["cross_market"]
        self.assertTrue(outward["readiness"]["has_context"])
        self.assertEqual(context["snapshot_id"], "cmctx:2330:test")
        self.assertEqual(context["ranking_effect"], "none")
        self.assertEqual(context["technical_score_effect"], "none")
        self.assertNotIn("signals", context)

    def test_v4_envelope_keeps_bounded_decision_context_and_full_capability_data(
        self,
    ) -> None:
        canonical_context = _canonical_context()
        projected = evidence_builder.cross_market_decision_evidence(
            {"cross_market_context": canonical_context}
        )
        human_answer = answer_composer.build_consumer_human_answer(
            question_intent="cross_market",
            target={"type": "tw_stock", "id": "2330", "label": "TSMC"},
            analysis_digest=_analysis_digest(projected),
            missing=[],
            warnings=[],
            response_preferences={"locale": "en-US"},
        )
        outward_contract = decision_contract.build_decision_contract(
            question_intent="cross_market",
            target={"type": "tw_stock", "id": "2330", "label": "TSMC"},
            human_answer=human_answer,
            freshness_result={"status": "current", "is_current": True},
            missing=[],
            warnings=[],
            answer_ready=True,
        )
        parity = {
            "kind": "adr_parity",
            "status": "ready",
            "is_current": True,
            "stock_id": "2330",
            "mapping": {"adr_symbol": "TSM", "local_shares_per_adr": 5},
            "mapping_resolution": {"relation_id": 42, "relation_version": 1},
            "adr_trade_date": "2026-08-08",
            "implied_gap_pct": 3.5,
            "missing": [],
            "warnings": [],
        }
        overnight = {
            "kind": "us_overnight_tw_impact",
            "stock_id": "2330",
            "as_of": "2026-08-08",
            "stance": "risk_on",
            "context_status": "ready",
            "decision_usable": True,
            "summary": "ADR parity supportive",
            "signals": canonical_context["signals"],
            "coverage": canonical_context["coverage"],
            "methodology_version": canonical_context["methodology_version"],
            "relation_snapshot_version": canonical_context[
                "relation_snapshot_version"
            ],
            "snapshot_id": canonical_context["snapshot_id"],
            "limitations": canonical_context["limitations"],
            "source": "app.market.cross_market.context",
            "freshness": {"status": "current"},
            "warnings": [],
            "cross_market_context": canonical_context,
            "adr_parity": parity,
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "cross_market.overnight",
                    "cross_market.relations",
                    "cross_market.parity",
                ]
            },
            output="decision_with_evidence",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            target_market="TW",
            question_intent="cross_market",
        )
        response = {
            "kind": "ai_ask",
            "contract_version": "omi.ai.ask.v2",
            "ok": True,
            "request_status": "completed",
            "question": "How do TSM ADR and the US overnight session affect 2330?",
            "target": {
                "type": "tw_stock",
                "id": "2330",
                "market": "TW",
                "label": "TSMC",
            },
            "mode": {
                "requested": "brief",
                "effective": "brief",
                "response": "analysis",
                "payload_level": "compact",
            },
            "action": "omi.ask",
            "caller_profile": "kuro",
            "facts_ready": True,
            "analysis_ready": True,
            "answer_ready": True,
            "decision_ready": False,
            "blocked_sections": [],
            "available_sections": [
                "evidence",
                "human_answer",
                "decision_contract",
            ],
            "analysis": {
                "question_intent": "cross_market",
                "human_answer": human_answer,
                "decision_contract": outward_contract,
            },
            "result": {"data": {"compact": {"cross_market": overnight}}},
            "freshness": {"status": "current", "is_current": True},
            "missing": [],
            "warnings": [],
            "source_refs": [{"type": "derived", "name": "cross-market-test"}],
            "evidence_passport": {"kind": "evidence_passport"},
            "policy": {"allow_llm": False},
            "query_plan": {
                "target_type": "stock",
                "requested_domains": ["cross_market"],
                "required_domains": ["cross_market"],
                "payload_level": "compact",
                "selection": selection,
            },
            "tool_plan": {"max_calls": 0},
            "tool_runs": [],
            "reasoning_steps": [],
            "diagnostics": {},
            "next_context": {},
            "clarification": {},
            "next_actions": [],
            "error": {},
        }

        envelope = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        self.assertEqual(envelope["contract_version"], "omi.decision.v4")
        decision_context = envelope["decision"]["context"]["cross_market"]
        self.assertEqual(decision_context["snapshot_id"], "cmctx:2330:test")
        self.assertEqual(decision_context["ranking_effect"], "none")
        self.assertNotIn("signals", decision_context)
        evidence_context = envelope["evidence"]["data"][
            "cross_market.relations"
        ]
        self.assertEqual(evidence_context["snapshot_id"], "cmctx:2330:test")
        self.assertEqual(evidence_context["signals"][0]["relation_id"], 42)

    def test_unusable_context_is_a_visible_data_limit(self) -> None:
        projected = evidence_builder.cross_market_decision_evidence(
            {
                "cross_market_context": _canonical_context(
                    status="stale",
                    decision_usable=False,
                )
            }
        )
        lines = answer_evidence.decision_evidence_data_lines(
            {"cross_market": projected},
            response_preferences={"locale": "en-US"},
        )

        self.assertTrue(any("not decision-usable" in line for line in lines))

    def test_overnight_readiness_follows_canonical_context_status(self) -> None:
        context = _canonical_context(status="stale", decision_usable=False)
        context["warnings"] = ["fx_cache_stale"]
        context["limitations"] = ["latest_cache_projection"]
        overnight = {
            "kind": "us_overnight_tw_impact",
            "as_of": "2026-08-08",
            "context_status": "stale",
            "decision_usable": False,
            "coverage": context["coverage"],
            "freshness": {"status": "current", "is_current": True},
            "missing": [],
            "warnings": [],
            "cross_market_context": context,
        }

        freshness_by_capability = (
            taiwan_projection._build_freshness_by_capability(
                quote={},
                intraday_bars={},
                source_health=None,
                overnight_impact=overnight,
                missing=[],
            )
        )
        overnight_freshness = freshness_by_capability[
            "cross_market.overnight"
        ]

        self.assertEqual(overnight_freshness["status"], "stale")
        self.assertFalse(overnight_freshness["is_current"])
        self.assertFalse(overnight_freshness["decision_usable"])
        self.assertIn("fx_cache_stale", overnight_freshness["warnings"])

        quality = data_quality_contract._quality_for_capability(
            {
                "capability": "cross_market.overnight",
                "domain": "cross_market",
                "slot": "cross_market",
                "required": True,
                "status": "available",
            },
            canonical={
                "target": {"type": "tw_stock", "market": "TW"},
                "evidence": {
                    "freshness_by_capability": freshness_by_capability,
                    "freshness_by_domain": {"cross_market": "current"},
                    "slots": {},
                },
            },
            projected_data={"cross_market.overnight": overnight},
            realtime_assessments={},
            market="TW",
        )

        self.assertEqual(quality["freshness_status"], "stale")
        self.assertEqual(quality["usability_status"], "limited")
        self.assertTrue(quality["facts_usable"])
        self.assertFalse(quality["decision_usable"])


if __name__ == "__main__":
    unittest.main()
