from __future__ import annotations

import unittest

from app.ai import (
    capability_contract,
    capability_resolution_registry,
    decision_envelope_v4,
    query_plan,
)
from app.ai.schemas import AiAskRequest


TECHNICAL_CAPABILITIES = (
    "technical.indicators",
    "technical.swings",
    "technical.fibonacci",
    "technical.divergence",
    "technical.breakout",
    "technical.volume_profile",
    "technical.anchored_vwap",
    "technical.relative_strength",
)


class TechnicalCapabilityContractTests(unittest.TestCase):
    def test_new_capabilities_are_taiwan_stock_read_only_derived_contracts(self) -> None:
        for capability_id in TECHNICAL_CAPABILITIES:
            with self.subTest(capability_id=capability_id):
                spec = capability_contract.CAPABILITIES[capability_id]
                self.assertEqual(spec.domain, "technical")
                self.assertEqual(spec.slot, "technical")
                self.assertEqual(spec.scopes, ("stock",))
                self.assertEqual(spec.markets, ("TW",))
                self.assertEqual(spec.side_effect_policy, "read_only")
                self.assertIn(
                    capability_id,
                    capability_resolution_registry.DERIVED_DEPENDENCIES,
                )

    def test_projection_uses_canonical_compact_paths_without_status_in_payload(self) -> None:
        response = {
            "result": {
                "data": {
                    "compact": {
                        "technical_indicators": {
                            "schema_version": "tw.technical.indicators.v3",
                            "status": "partial",
                            "price_basis": "raw_unadjusted",
                            "methods": {"rsi": {"method": "wilder_smoothed_gain_loss"}},
                            "timeframes": {"daily": {"decision_snapshot": "completed"}},
                            "warnings": ["corporate action coverage partial"],
                            "source_refs": [{"type": "table", "name": "market_daily_price"}],
                        },
                        "technical_advanced": {
                            "breakout": {
                                "algorithm_version": "tw.technical.advanced.v2",
                                "status": "ready",
                                "state": "rejected_attempt",
                                "level": 505.0,
                                "close": 482.5,
                                "price_basis": "raw_unadjusted",
                                "decision_usable": True,
                            }
                        },
                    }
                }
            }
        }
        selection = {
            "required": ["technical.indicators", "technical.breakout"],
            "optional": [],
            "fields": {},
            "limits": {},
        }

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        self.assertEqual(unavailable, [])
        self.assertEqual(
            projected["technical.indicators"]["schema_version"],
            "tw.technical.indicators.v3",
        )
        self.assertEqual(
            projected["technical.indicators"]["timeframes"]["daily"]["decision_snapshot"],
            "completed",
        )
        self.assertEqual(
            projected["technical.breakout"]["state"],
            "rejected_attempt",
        )
        self.assertEqual(projected["technical.breakout"]["close"], 482.5)

    def test_advanced_capabilities_do_not_expand_default_technical_domain(self) -> None:
        self.assertEqual(
            capability_contract.DOMAIN_CAPABILITIES["technical"],
            ("technical.structure",),
        )

    def test_natural_language_routes_to_specific_technical_capability(self) -> None:
        cases = (
            ("2408 RSI 是多少？", "technical.indicators"),
            ("2408 KDJ 現在是多少？", "technical.indicators"),
            ("2408 Fibonacci 位階", "technical.fibonacci"),
            ("2408 是否突破？", "technical.breakout"),
            ("2408 有沒有背離？", "technical.divergence"),
            ("2408 的 POC 成本區", "technical.volume_profile"),
            ("2408 anchored VWAP", "technical.anchored_vwap"),
            ("2408 相對大盤強弱", "technical.relative_strength"),
        )
        for question, expected in cases:
            with self.subTest(question=question):
                payload = AiAskRequest(
                    question=question,
                    contract_version="omi.decision.v4",
                    target={"type": "tw_stock", "id": "2408"},
                    mode="data_only",
                    output="evidence_only",
                )
                plan = query_plan.build_query_plan(
                    payload=payload,
                    scope_type="stock",
                    question_intent="general",
                    effective_mode="data_only",
                    target_market="TW",
                )

                self.assertIn(expected, plan.selected_capabilities)
                self.assertEqual(plan.capability_selection_mode, "additive")

    def test_response_budget_summaries_keep_decision_fields_and_bound_large_rows(self) -> None:
        indicator = decision_envelope_v4._brief_capability_summary(
            "technical.indicators",
            {
                "schema_version": "tw.technical.indicators.v3",
                "status": "partial",
                "as_of": "2026-08-12",
                "price_basis": "raw_unadjusted",
                "methods": {"rsi": {"method": "wilder_smoothed_gain_loss"}},
                "timeframes": {
                    "daily": {
                        "decision_snapshot": "completed",
                        "completed": {
                            "close": 482.5,
                            "rsi": {"rsi14": 53.25},
                            "raw_internal_debug": "x" * 10_000,
                        },
                    }
                },
            },
        )
        volume_profile = decision_envelope_v4._brief_capability_summary(
            "technical.volume_profile",
            {
                "status": "partial",
                "poc": 480.5,
                "val": 455.0,
                "vah": 505.0,
                "bins": [{"index": index, "volume": index * 1000} for index in range(24)],
                "high_volume_nodes": [
                    {"index": index, "mid": 480.0 + index, "volume": 10_000 - index}
                    for index in range(8)
                ],
            },
        )

        self.assertEqual(indicator["projection_level"], "summary")
        self.assertEqual(
            indicator["timeframes"]["daily"]["completed"]["close"],
            482.5,
        )
        self.assertNotIn(
            "raw_internal_debug",
            indicator["timeframes"]["daily"]["completed"],
        )
        self.assertEqual(volume_profile["projection_level"], "summary")
        self.assertEqual(volume_profile["bins_included"], 0)
        self.assertEqual(len(volume_profile["high_volume_nodes"]), 3)


if __name__ == "__main__":
    unittest.main()
