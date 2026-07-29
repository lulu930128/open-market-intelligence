from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.ai import capability_contract, decision_envelope, scope_resolution
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

    def test_v4_projects_only_selected_capabilities_and_omits_legacy_result(self) -> None:
        response = _v2_response()
        response["result"]["data"]["compact"]["quote"] = {
            "price": 1000,
            "change_pct": 1.5,
            "quote_time": "2026-07-23T13:30:00+08:00",
            "provider": "test",
            "unused_large_field": ["x" * 1000 for _ in range(50)],
        }
        response["result"]["data"]["large_unselected_payload"] = [
            {"value": "x" * 1000} for _ in range(100)
        ]
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["quote.snapshot"],
                "fields": {
                    "quote.snapshot": [
                        "price",
                        "quote_time",
                        "provider",
                    ]
                },
                "max_response_bytes": 16_384,
            },
            output="decision_with_evidence",
            realtime_policy="prefer_live",
            payload_level="summary",
            scope_type="stock",
            question_intent="entry_decision",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        self.assertEqual(canonical["contract_version"], "omi.decision.v4")
        self.assertEqual(
            canonical["compatibility"],
            {
                "public_contract": "omi.decision.v4",
                "legacy_contracts_accepted": False,
            },
        )
        self.assertNotIn("result", canonical["evidence"])
        self.assertEqual(
            canonical["evidence"]["data"]["quote.snapshot"],
            {
                "price": 1000,
                "quote_time": "2026-07-23T13:30:00+08:00",
                "provider": "test",
            },
        )
        self.assertNotIn(
            "large_unselected_payload",
            json.dumps(canonical, ensure_ascii=False),
        )
        self.assertEqual(
            canonical["evidence"]["manifest"]["version"],
            "omi.data.manifest.v1",
        )
        self.assertLessEqual(
            len(
                json.dumps(
                    canonical,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            selection["max_response_bytes"],
        )

    def test_v4_keeps_quality_summary_under_minimum_response_budget(self) -> None:
        response = _v2_response()
        compact = response["result"]["data"]["compact"]
        compact["quote"] = {
            "price": 1000,
            "quote_time": "2026-07-24T13:30:00+08:00",
            "provider": "test",
            "unused_large_field": ["x" * 1000 for _ in range(100)],
        }
        response["execution"] = {
            "tool_runs": [
                {
                    "tool": f"tool-{index}",
                    "provider": "provider",
                    "status": "completed",
                    "detail": "x" * 1000,
                }
                for index in range(40)
            ]
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["quote.snapshot"],
                "max_response_bytes": 4_096,
            },
            output="decision_with_evidence",
            realtime_policy="prefer_live",
            payload_level="summary",
            scope_type="stock",
            question_intent="entry_decision",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        payload_bytes = len(
            json.dumps(
                canonical,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        self.assertLessEqual(payload_bytes, 4_096)
        self.assertEqual(
            canonical["evidence"]["quality"]["version"],
            "omi.data.quality.v1",
        )
        self.assertIn(
            "quote.snapshot",
            canonical["evidence"]["quality"]["capabilities"],
        )
        self.assertTrue(canonical["projection"]["budget_met"])
        self.assertTrue(canonical["projection"]["truncated"])
        self.assertTrue(
            canonical["projection"]["trimmed_fields"]
            or canonical["projection"]["trimmed_lists"]
            or canonical["projection"]["omitted_capabilities"]
        )
        if not canonical["projection"]["omitted_capabilities"]:
            self.assertNotIn(
                "projection.omitted_capabilities",
                " ".join(canonical["limitations"]["warnings"]),
            )

    def test_v4_hard_caps_rich_multi_capability_minimum_budget_envelope(
        self,
    ) -> None:
        response = _v2_response()
        compact = response["result"]["data"]["compact"]
        compact["quote"] = {
            "price": 1000,
            "quote_time": "2026-07-24T13:30:00+08:00",
            "provider": "test",
        }
        compact["chart"] = {
            "latest_data_date": "2026-07-24",
            "points": [
                {
                    "date": f"2026-07-{day:02d}",
                    "close": 900 + day,
                    "volume": 10_000 + day,
                }
                for day in range(1, 25)
            ],
            "volume_unit": "shares",
        }
        compact["technical"] = {
            "latest_price": 1000,
            "trend": "bullish",
            "moving_averages": {"ma5": 990, "ma20": 960},
        }
        compact["institutional"] = {
            "latest_data_date": "2026-07-24",
            "foreign_net": 100,
        }
        compact["margin"] = {
            "latest_data_date": "2026-07-24",
            "margin_balance": 1000,
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "quote.snapshot",
                    "daily.ohlcv",
                    "technical.structure",
                    "chips.institutional",
                    "chips.margin",
                    "ownership.distribution",
                ],
                "max_response_bytes": 4_096,
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )
        payload_bytes = len(
            json.dumps(
                canonical,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )

        self.assertLessEqual(payload_bytes, 4_096)
        self.assertTrue(canonical["projection"]["budget_met"])
        self.assertEqual(
            canonical["projection"]["actual_response_bytes"],
            payload_bytes,
        )
        self.assertTrue(canonical["projection"]["truncated"])
        self.assertTrue(canonical["projection"]["trimmed_fields"])
        self.assertEqual(canonical["contract_version"], "omi.decision.v4")
        self.assertEqual(canonical["evidence"]["data"], {})
        self.assertEqual(
            canonical["evidence"]["quality"]["version"],
            "omi.data.quality.v1",
        )

    def test_v4_semantic_empty_ownership_payload_is_not_usable(self) -> None:
        response = _v2_response()
        response["result"]["data"]["compact"]["chips"] = {
            "shareholding": [{}, {}],
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["ownership.distribution"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )
        quality = canonical["evidence"]["quality"]["capabilities"][
            "ownership.distribution"
        ]

        self.assertFalse(quality["facts_usable"])
        self.assertFalse(quality["decision_usable"])
        self.assertEqual(quality["completeness"], "empty")
        self.assertNotEqual(quality["status_class"], "ready")
        self.assertIn("semantic_payload_empty", quality["issues"])

    def test_v4_stale_intraday_bars_remain_fact_usable(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "intraday": "stale",
                "technical": "latest_completed_session",
            }
        )
        response["target"] = {
            "type": "us_stock",
            "id": "AAPL",
            "market": "US",
        }
        response["result"]["data"]["compact"]["intraday_bars"] = {
            "interval": "1m",
            "point_count": 2,
            "returned_point_count": 2,
            "points": [
                {
                    "bar_time": "2020-07-24T10:31:00-04:00",
                    "close_price": 180.0,
                    "volume": 100,
                },
                {
                    "bar_time": "2020-07-24T10:32:00-04:00",
                    "close_price": 180.5,
                    "volume": 120,
                },
            ],
            "event_time": "2020-07-24T10:32:00-04:00",
            "provider": "yahoo_chart",
            "source": "us_intraday_trend",
            "volume_unit": "shares",
            "continuity": "continuous",
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["intraday.bars"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="us_stock",
            question_intent="quote",
        )
        response["query_plan"] = {
            "target_type": "us_stock",
            "selection": selection,
        }

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )
        quality = canonical["evidence"]["quality"]["capabilities"][
            "intraday.bars"
        ]

        self.assertEqual(quality["freshness"], "stale")
        self.assertTrue(quality["facts_usable"])
        self.assertFalse(quality["decision_usable"])
        self.assertEqual(quality["completeness"], "complete")

    def test_v4_stale_quote_remains_fact_usable_but_not_decision_usable(
        self,
    ) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "stale",
                "technical": "latest_completed_session",
            }
        )
        response["result"]["data"]["compact"]["quote"] = {
            "price": 1000,
            "trade_date": "2026-07-22",
            "quote_time": "2026-07-22T13:30:00+08:00",
            "provider": "local_daily_close",
            "source": "market_daily_price",
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["quote.snapshot"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )
        quality = canonical["evidence"]["quality"]["capabilities"][
            "quote.snapshot"
        ]

        self.assertEqual(quality["status"], "stale")
        self.assertTrue(quality["facts_usable"])
        self.assertFalse(quality["decision_usable"])
        self.assertTrue(canonical["status"]["readiness"]["response_ready"])
        self.assertFalse(canonical["status"]["readiness"]["decision_ready"])
        self.assertTrue(
            any(
                warning.startswith(
                    "capability:quote.snapshot:stale_observed_at="
                )
                for warning in canonical["limitations"]["warnings"]
            )
        )

    def test_v4_stale_quote_requires_complete_provenance(self) -> None:
        quote = {
            "price": 1000,
            "trade_date": "2026-07-22",
            "quote_time": "2026-07-22T13:30:00+08:00",
            "provider": "local_daily_close",
            "source": "market_daily_price",
        }

        for missing_field in ("quote_time", "provider", "source"):
            with self.subTest(missing_field=missing_field):
                response = _v2_response(
                    freshness_by_domain={
                        "quote": "stale",
                        "technical": "latest_completed_session",
                    }
                )
                response["result"]["data"]["compact"]["quote"] = {
                    key: value
                    for key, value in quote.items()
                    if key != missing_field
                }
                selection = capability_contract.normalize_selection(
                    selection={"include": ["quote.snapshot"]},
                    output="evidence_only",
                    realtime_policy="cache_only",
                    payload_level="compact",
                    scope_type="stock",
                    question_intent="quote",
                )
                response["query_plan"]["selection"] = selection
                response["query_plan"]["target_type"] = "stock"

                canonical = decision_envelope.for_requested_contract(
                    response,
                    requested_contract_version="omi.decision.v4",
                )
                quality = canonical["evidence"]["quality"]["capabilities"][
                    "quote.snapshot"
                ]

                self.assertFalse(quality["facts_usable"])
                self.assertFalse(quality["decision_usable"])

    def test_v4_moves_unselected_context_gaps_out_of_selected_limitations(
        self,
    ) -> None:
        response = _v2_response()
        response["missing"] = [
            "monthly_revenue",
            "us_overnight_tw_impact",
        ]
        response["warnings"] = [
            "monthly_revenue is stale",
            "NVDA overnight context is stale",
        ]
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "quote.snapshot",
                    "technical.structure",
                ],
            },
            output="decision_with_evidence",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="trend_view",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )
        limitations = canonical["limitations"]

        self.assertNotIn("monthly_revenue", limitations["missing"])
        self.assertNotIn("us_overnight_tw_impact", limitations["missing"])
        self.assertNotIn(
            "monthly_revenue is stale",
            limitations["warnings"],
        )
        self.assertIn(
            "monthly_revenue",
            limitations["supplemental_context_gaps"]["missing"],
        )
        self.assertIn(
            "us_overnight_tw_impact",
            limitations["supplemental_context_gaps"]["missing"],
        )
        self.assertEqual(
            canonical["evidence"]["passport"]["trust_scope"],
            "selected_capabilities",
        )

    def test_v4_selected_freshness_ignores_unselected_stock_datasets(
        self,
    ) -> None:
        response = _v2_response(
            freshness_by_domain={
                "chips": "stale",
                "technical": "latest_completed_session",
            }
        )
        compact = response["result"]["data"]["compact"]
        compact["freshness_by_capability"] = {
            "chips.institutional": {
                "status": "current",
                "dataset": "institutional_trade_daily",
                "is_current": True,
                "latest": "2026-07-24",
                "refresh_recommended": False,
            },
            "chips.margin": {
                "status": "current",
                "dataset": "margin_trading_daily",
                "is_current": True,
                "latest": "2026-07-24",
                "refresh_recommended": False,
            },
            "ownership.distribution": {
                "status": "stale",
                "dataset": "shareholding_distribution_weekly",
                "is_current": False,
                "latest": "2026-07-17",
                "refresh_recommended": True,
            },
            "fundamentals.revenue": {
                "status": "missing",
                "dataset": "monthly_revenue",
                "is_current": False,
                "latest": None,
                "refresh_recommended": True,
            },
        }
        compact["chips"] = {
            "institutional": {
                "trade_date": "2026-07-24",
                "foreign_investor_net": -9_636_606,
                "total_institutional_net": -8_781_367,
                "source": "institutional_trade_daily",
            },
            "margin": {
                "trade_date": "2026-07-24",
                "margin_today_balance": 31_915,
                "short_today_balance": 67,
                "source": "margin_trading_daily",
            },
        }
        response["freshness"] = {
            "status": "partial",
            "is_current": False,
            "datasets": [
                {
                    "key": "institutional_trade_daily",
                    "latest": "2026-07-24",
                    "is_current": True,
                },
                {
                    "key": "margin_trading_daily",
                    "latest": "2026-07-24",
                    "is_current": True,
                },
                {
                    "key": "shareholding_distribution_weekly",
                    "latest": "2026-07-17",
                    "is_current": False,
                },
                {
                    "key": "monthly_revenue",
                    "latest": None,
                    "is_current": False,
                },
            ],
            "missing": [
                "shareholding_distribution_weekly",
                "monthly_revenue",
            ],
            "warnings": [
                "shareholding_distribution_weekly is stale",
                "monthly_revenue is missing",
            ],
        }
        response["missing"] = [
            "shareholding_distribution_weekly",
            "monthly_revenue",
        ]
        response["warnings"] = [
            "shareholding_distribution_weekly is stale",
            "monthly_revenue is missing",
        ]
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "chips.institutional",
                    "chips.margin",
                ],
                "exclude": [
                    "ownership.distribution",
                    "fundamentals.revenue",
                    "fundamentals.financials",
                ],
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )
        selected_freshness = canonical["evidence"]["data"]["data.freshness"]

        self.assertEqual(selected_freshness["scope"], "selected_capabilities")
        self.assertEqual(selected_freshness["status"], "current")
        self.assertTrue(selected_freshness["is_current"])
        self.assertEqual(
            [item["key"] for item in selected_freshness["datasets"]],
            [
                "institutional_trade_daily",
                "margin_trading_daily",
            ],
        )
        self.assertEqual(selected_freshness["missing"], [])
        self.assertEqual(selected_freshness["warnings"], [])
        self.assertEqual(canonical["evidence"]["quality"]["status"], "ready")
        self.assertEqual(canonical["evidence"]["quality"]["trust_level"], "high")
        self.assertEqual(canonical["limitations"]["missing"], [])
        self.assertEqual(
            canonical["continuation"]["fill_plan"]["action_count"],
            0,
        )
        supplemental = canonical["limitations"]["supplemental_context_gaps"]
        self.assertFalse(supplemental["affects_selected_quality"])
        self.assertIn(
            "shareholding_distribution_weekly",
            supplemental["missing"],
        )
        self.assertIn("monthly_revenue", supplemental["missing"])

    def test_v4_unselected_intraday_gap_is_supplemental_only(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "intraday": "missing",
                "technical": "partial",
                "chips": "current",
            }
        )
        compact = response["result"]["data"]["compact"]
        compact["freshness_by_capability"] = {
            "technical.structure": {
                "status": "current",
                "dataset": "market_daily_price",
                "is_current": True,
                "latest": "2026-07-24",
                "refresh_recommended": False,
            },
            "ownership.distribution": {
                "status": "current",
                "dataset": "shareholding_distribution_weekly",
                "is_current": True,
                "latest": "2026-07-18",
                "refresh_recommended": False,
            },
        }
        compact["technical"] = {
            "trade_date": "2026-07-24",
            "latest_price": 2350,
            "levels": {"latest_price": 2350},
            "source": "market_daily_price",
        }
        compact["chips"] = {
            "shareholding": {
                "trade_date": "2026-07-18",
                "distribution": [
                    {
                        "holding_level": "1",
                        "holder_count": 1_000,
                        "share_count": 10_000,
                        "share_ratio": 1.5,
                    }
                ],
                "source": "shareholding_distribution_weekly",
            }
        }
        response["freshness"] = {
            "status": "partial",
            "is_current": False,
            "datasets": [
                {
                    "key": "market_daily_price",
                    "latest": "2026-07-24",
                    "is_current": True,
                },
                {
                    "key": "shareholding_distribution_weekly",
                    "latest": "2026-07-18",
                    "is_current": True,
                },
                {
                    "key": "intraday_bars",
                    "latest": None,
                    "is_current": False,
                },
            ],
            "missing": ["intraday_bars"],
            "warnings": [
                "Provider refresh reported refreshed_count=54 but returned no intraday points."
            ],
        }
        response["missing"] = ["intraday_bars"]
        response["warnings"] = [
            "Provider refresh reported refreshed_count=54 but returned no intraday points."
        ]
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "technical.structure",
                    "ownership.distribution",
                ],
                "exclude": ["intraday.bars"],
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        self.assertEqual(canonical["evidence"]["quality"]["status"], "ready")
        self.assertEqual(canonical["limitations"]["missing"], [])
        self.assertEqual(canonical["limitations"]["warnings"], [])
        supplemental = canonical["limitations"]["supplemental_context_gaps"]
        self.assertIn("intraday_bars", supplemental["missing"])
        self.assertIn(
            "Provider refresh reported refreshed_count=54 but returned no intraday points.",
            supplemental["warnings"],
        )
        self.assertEqual(
            canonical["continuation"]["fill_plan"]["action_count"],
            0,
        )

    def test_v4_reports_known_scope_incompatibility_without_rejecting(self) -> None:
        response = _v2_response()
        response["result"]["data"]["compact"]["freshness_by_capability"] = {}
        selection = capability_contract.normalize_selection(
            selection={"include": ["market.breadth"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="market_breadth",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        self.assertTrue(canonical["ok"])
        self.assertEqual(canonical["request_status"], "completed")
        unsupported = canonical["limitations"]["unsupported_capabilities"]
        self.assertEqual(len(unsupported), 1)
        self.assertEqual(unsupported[0]["capability"], "market.breadth")
        self.assertEqual(
            unsupported[0]["reason_code"],
            "unsupported_target_scope",
        )
        self.assertEqual(
            canonical["evidence"]["manifest"]["unsupported_capabilities"],
            unsupported,
        )
        self.assertEqual(
            canonical["evidence"]["manifest"]["unsupported_count"],
            1,
        )
        self.assertEqual(
            canonical["evidence"]["manifest"]["unmet_required_count"],
            1,
        )
        self.assertEqual(
            canonical["evidence"]["quality"]["status"],
            "blocked",
        )
        self.assertFalse(
            canonical["status"]["readiness"]["analysis_ready"],
        )
        self.assertNotEqual(
            canonical["status"]["readiness"]["evidence_status"],
            "ready",
        )
        self.assertIn(
            "capability:market.breadth",
            canonical["limitations"]["missing"],
        )
        self.assertEqual(
            canonical["limitations"]["unmet_required_capabilities"],
            unsupported,
        )

    def test_v4_synthesizes_tw_index_freshness_from_domain_contract(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": {
                    "status": "latest_completed_session",
                    "latest": "2026-07-27T13:30:00+08:00",
                    "is_current": True,
                }
            },
        )
        response.pop("freshness", None)
        response["target"] = {
            "type": "tw_index",
            "id": "TAIEX",
            "market": "TW",
            "label": "加權指數",
        }
        response["resolution"]["target"] = dict(response["target"])
        response["result"]["data"]["compact"]["quote"] = {
            "index_id": "TAIEX",
            "latest_price": 43634.19,
            "quote_time": "2026-07-27T13:30:00+08:00",
            "source": "twse_index_5s",
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["quote.snapshot"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="tw_index",
            question_intent="quote",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "tw_index"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        freshness = canonical["evidence"]["data"]["data.freshness"]
        self.assertEqual(freshness["status"], "current")
        self.assertEqual(freshness["scope"], "selected_capabilities")
        self.assertEqual(freshness["selected_capabilities"], ["quote.snapshot"])
        self.assertIn("quote.snapshot", freshness["dependency_datasets"])
        self.assertNotIn(
            "capability:data.freshness",
            canonical["limitations"]["missing"],
        )

    def test_v4_preserves_realtime_metadata_and_quality_across_payload_levels(
        self,
    ) -> None:
        for payload_level in ("compact", "standard", "full"):
            with self.subTest(payload_level=payload_level):
                response = _v2_response(
                    freshness_by_domain={
                        "quote": "current",
                        "intraday": "current",
                    },
                )
                response["mode"]["payload_level"] = payload_level
                response["query_plan"]["payload_level"] = payload_level
                compact = response["result"]["data"]["compact"]
                compact["quote"] = {
                    "latest_price": 43_634.19,
                    "quote_time": "2026-07-27T13:34:00+08:00",
                    "source": "twse_index_5s_snapshot",
                    "volume": None,
                    "volume_unit": None,
                    "canonical_volume_unit": None,
                    "volume_status": "not_provided",
                    "trade_value": None,
                    "trade_value_unit": "TWD",
                    "trade_value_status": "not_provided",
                    "trade_value_source": None,
                    "official_close_status": "confirmed",
                    "official_close_price": 43_634.19,
                    "official_close_raw": 43_634.19,
                    "official_close_display": "43,634.19",
                    "official_close_precision": 2,
                    "selected_candidate": "official_close",
                    "selection_reason": "confirmed_official_close",
                    "bid_levels": [
                        {
                            "level": level,
                            "price": 43_634.0 - level,
                            "volume_lots": 100 + level,
                            "order_count": None,
                            "order_count_status": "not_provided",
                        }
                        for level in range(1, 6)
                    ],
                    "ask_levels": [
                        {
                            "level": level,
                            "price": 43_634.0 + level,
                            "volume_lots": 90 + level,
                            "order_count": None,
                            "order_count_status": "not_provided",
                        }
                        for level in range(1, 6)
                    ],
                    "bid_depth": [
                        {
                            "level": level,
                            "price": 43_634.0 - level,
                            "volume_lots": 100 + level,
                            "order_count": None,
                            "order_count_status": "not_provided",
                        }
                        for level in range(1, 6)
                    ],
                    "ask_depth": [
                        {
                            "level": level,
                            "price": 43_634.0 + level,
                            "volume_lots": 90 + level,
                            "order_count": None,
                            "order_count_status": "not_provided",
                        }
                        for level in range(1, 6)
                    ],
                    "top5_bid_volume_lots": 1_230,
                    "top5_ask_volume_lots": 1_100,
                    "top5_imbalance": 130,
                    "depth_order_count_status": "not_provided",
                    "indicative_unmatched_buy_volume_lots": None,
                    "indicative_unmatched_sell_volume_lots": None,
                    "indicative_unmatched_status": "not_provided",
                }
                compact["intraday_bars"] = {
                    "interval": "5m",
                    "requested_interval": "5m",
                    "source_interval": "1m",
                    "effective_interval": "5m",
                    "interval_status": "ready",
                    "aggregation_method": "local_ohlcv_1m_to_5m",
                    "source_point_count": 5,
                    "aggregated_point_count": 1,
                    "point_count": 1,
                    "returned_point_count": 1,
                    "volume_unit": "provider_units",
                    "volume_status": "provider_specific",
                    "points": [
                        {
                            "bar_time": "2026-07-27T09:00:00+08:00",
                            "bar_close_time": "2026-07-27T09:05:00+08:00",
                            "open": 43_100.0,
                            "high": 43_200.0,
                            "low": 43_050.0,
                            "close": 43_180.0,
                            "volume": 100,
                            "is_partial": False,
                            "finalized": True,
                        }
                    ],
                    "cache_status": "persisted_hit",
                    "cache_hit": True,
                    "cache_trade_date": "2026-07-27",
                    "cache_latest_time": "2026-07-27T09:04:00+08:00",
                    "fallback_used": False,
                    "source": "market_intraday_bar_cache",
                }
                selection = capability_contract.normalize_selection(
                    selection={
                        "required": [
                            "quote.snapshot",
                            "intraday.bars",
                        ],
                    },
                    output="evidence_only",
                    realtime_policy="cache_only",
                    payload_level=payload_level,
                    scope_type="tw_index",
                    question_intent="quote",
                )
                response["query_plan"]["selection"] = selection
                response["query_plan"]["target_type"] = "tw_index"

                canonical = decision_envelope.for_requested_contract(
                    response,
                    requested_contract_version="omi.decision.v4",
                )

                quote = canonical["evidence"]["data"]["quote.snapshot"]
                intraday = canonical["evidence"]["data"]["intraday.bars"]
                quality = canonical["evidence"]["quality"]["capabilities"]
                self.assertEqual(quote["volume_status"], "not_provided")
                self.assertEqual(
                    quote["depth_order_count_status"],
                    "not_provided",
                )
                self.assertIsNone(
                    quote["indicative_unmatched_buy_volume_lots"],
                )
                self.assertEqual(
                    quote["indicative_unmatched_status"],
                    "not_provided",
                )
                self.assertEqual(
                    quote["selected_candidate"],
                    "official_close",
                )
                self.assertEqual(len(quote["bid_levels"]), 5)
                self.assertEqual(len(quote["ask_levels"]), 5)
                self.assertIsNone(
                    quote["bid_levels"][0]["order_count"],
                )
                self.assertEqual(
                    intraday["aggregation_method"],
                    "local_ohlcv_1m_to_5m",
                )
                self.assertEqual(
                    intraday["cache_status"],
                    "persisted_hit",
                )
                self.assertTrue(
                    quality["quote.snapshot"]["payload_included"],
                )
                self.assertTrue(
                    quality["intraday.bars"]["payload_included"],
                )
                self.assertNotIn(
                    "volume_unit_missing",
                    quality["intraday.bars"]["issues"],
                )
                self.assertNotIn(
                    "missing_interval",
                    quality["intraday.bars"]["issues"],
                )

    def test_v4_synthesizes_freshness_for_intraday_and_market_breadth(
        self,
    ) -> None:
        cases = (
            {
                "scope_type": "tw_index",
                "target": {
                    "type": "tw_index",
                    "id": "TAIEX",
                    "market": "TW",
                },
                "capability": "intraday.bars",
                "domain": "intraday",
                "compact_key": "intraday_bars",
                "value": {
                    "interval": "1m",
                    "source_interval": "1m",
                    "effective_interval": "1m",
                    "point_count": 1,
                    "volume_unit": "provider_units",
                    "points": [
                        {
                            "time": "2026-07-27T13:30:00+08:00",
                            "price": 43_634.19,
                            "volume": 100,
                        }
                    ],
                    "source": "twse_index_5s_snapshot",
                },
            },
            {
                "scope_type": "market",
                "target": {
                    "type": "market",
                    "id": "TW",
                    "market": "TW",
                },
                "capability": "market.breadth",
                "domain": "breadth",
                "compact_key": "breadth",
                "value": {
                    "trade_date": "2026-07-27",
                    "status": "partial",
                    "advance_count": 900,
                    "decline_count": 800,
                    "unchanged_count": 100,
                    "universe_count": 2_000,
                    "classified_count": 1_800,
                    "unknown_count": 200,
                    "coverage_ratio": 0.9,
                    "is_full_market": False,
                    "source": "official_segment_breadth_partial",
                },
            },
        )
        for case in cases:
            with self.subTest(capability=case["capability"]):
                response = _v2_response(
                    freshness_by_domain={
                        case["domain"]: "latest_completed_session",
                    },
                )
                response.pop("freshness", None)
                response["target"] = case["target"]
                response["resolution"]["target"] = dict(case["target"])
                response["result"]["data"]["compact"][
                    case["compact_key"]
                ] = case["value"]
                selection = capability_contract.normalize_selection(
                    selection={
                        "required": [
                            case["capability"],
                            "data.freshness",
                        ],
                    },
                    output="evidence_only",
                    realtime_policy="cache_only",
                    payload_level="compact",
                    scope_type=case["scope_type"],
                    question_intent="data_freshness",
                )
                response["query_plan"]["selection"] = selection
                response["query_plan"]["target_type"] = case["scope_type"]

                canonical = decision_envelope.for_requested_contract(
                    response,
                    requested_contract_version="omi.decision.v4",
                )

                freshness = canonical["evidence"]["data"][
                    "data.freshness"
                ]
                freshness_quality = canonical["evidence"]["quality"][
                    "capabilities"
                ]["data.freshness"]
                self.assertIn("status", freshness)
                self.assertIn("datasets", freshness)
                self.assertIn("missing", freshness)
                self.assertIn("warnings", freshness)
                self.assertNotIn(
                    "semantic_payload_empty",
                    freshness_quality["issues"],
                )

    def test_v4_includes_freshness_and_source_health_payload_when_selected(
        self,
    ) -> None:
        response = _v2_response(
            freshness_by_domain={"source_health": "current"},
        )
        response["freshness"] = {
            "status": "current",
            "as_of": "2026-07-27T18:00:00+08:00",
            "is_current": True,
            "datasets": ["source_health_snapshot"],
            "missing": [],
            "warnings": [],
        }
        response["result"]["data"]["compact"]["source_health"] = {
            "status": "current",
            "as_of": "2026-07-27T18:00:00+08:00",
            "summary": {
                "healthy_count": 3,
                "problem_count": 0,
            },
            "warnings": [],
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["data.freshness", "source.health"],
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="market",
            question_intent="data_freshness",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "market"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        self.assertEqual(
            canonical["evidence"]["data"]["data.freshness"]["status"],
            "current",
        )
        self.assertEqual(
            canonical["evidence"]["data"]["source.health"]["summary"],
            {
                "healthy_count": 3,
                "problem_count": 0,
            },
        )
        manifest = {
            item["capability"]: item
            for item in canonical["evidence"]["manifest"]["capabilities"]
        }
        self.assertTrue(manifest["data.freshness"]["payload_included"])
        self.assertTrue(manifest["source.health"]["payload_included"])

    def test_v4_compacts_metadata_before_omitting_required_evidence(self) -> None:
        response = _v2_response()
        response["result"]["data"]["compact"]["quote"] = {
            "price": 1000,
            "quote_time": "2026-07-24T13:30:00+08:00",
            "provider": "test",
        }
        response["execution"] = {
            "tool_runs": [
                {
                    "tool": f"tool-{index}",
                    "provider": "provider",
                    "status": "completed",
                    "detail": "x" * 2_000,
                }
                for index in range(40)
            ]
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["quote.snapshot"],
                "fields": {
                    "quote.snapshot": [
                        "price",
                        "quote_time",
                        "provider",
                    ]
                },
                "max_response_bytes": 32_768,
            },
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        self.assertEqual(
            canonical["evidence"]["data"]["quote.snapshot"],
            {
                "price": 1000,
                "quote_time": "2026-07-24T13:30:00+08:00",
                "provider": "test",
            },
        )
        self.assertNotIn(
            "quote.snapshot",
            canonical["projection"]["omitted_capabilities"],
        )
        self.assertTrue(canonical["projection"]["budget_met"])

    def test_v4_brief_budget_keeps_selected_evidence_summaries(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "final_snapshot",
                "chart": "current",
                "technical": "current",
                "chips": "current",
                "broker_branch": "current",
            }
        )
        compact = response["result"]["data"]["compact"]
        compact["quote"] = {
            "price": 2350,
            "change": -55,
            "change_pct": -2.2869,
            "trade_date": "2026-07-24",
            "quote_time": "2026-07-24T13:30:00+08:00",
            "status": "final_snapshot",
            "provider": "local_daily_close",
            "volume_unit": "lots",
            "freshness": {"status": "final_snapshot"},
        }
        compact["chart"] = {
            "latest_data_date": "2026-07-24",
            "point_count": 120,
            "points": [
                {
                    "date": f"2026-03-{(index % 28) + 1:02d}",
                    "open_price": 2200 + index,
                    "high_price": 2210 + index,
                    "low_price": 2190 + index,
                    "close_price": 2205 + index,
                    "volume": 100_000 + index,
                }
                for index in range(120)
            ],
            "volume_unit": "shares",
            "source": "market_daily_price",
        }
        compact["technical"] = {
            "analysis": {
                "selected_summary": "日線偏弱，等待量價重新轉強。",
                "selected_score": 38,
            },
            "levels": {
                "latest_price": 2350,
                "entry": {
                    "breakout_confirm_above": {"price": 2505},
                },
                "risk": {
                    "technical_invalidation": {"price": 2290},
                },
            },
            "reports": {
                f"report-{index}": {"detail": "x" * 1_000}
                for index in range(20)
            },
        }
        compact["chips"] = {
            "institutional": {
                "trade_date": "2026-07-24",
                "foreign_investor_net": -12_500,
                "total_institutional_net": -10_300,
            },
            "margin": {
                "trade_date": "2026-07-24",
                "margin_today_balance": 21_000,
                "short_today_balance": 1_300,
            },
            "broker_branch": {
                "trade_date": "2026-07-24",
                "available_days": 5,
                "requested_days": 5,
                "buy_top": [
                    {
                        "branch_name": f"買方分點-{index}",
                        "net_lots": 100 - index,
                        "detail": "x" * 1_000,
                    }
                    for index in range(15)
                ],
                "sell_top": [
                    {
                        "branch_name": f"賣方分點-{index}",
                        "net_lots": -100 + index,
                        "detail": "x" * 1_000,
                    }
                    for index in range(15)
                ],
            },
            "shareholding": {
                "trade_date": "2026-07-17",
                "distribution": [
                    {
                        "holding_level": str(index),
                        "holder_count": 1_000 + index,
                        "share_count": 10_000 + index,
                        "share_ratio": 1.5,
                    }
                    for index in range(10)
                ],
                "source": "shareholding_distribution_weekly",
            },
        }
        response["tool_runs"] = [
            {
                "tool": f"tool-{index}",
                "provider": "provider",
                "status": "success",
                "result": {"raw": "x" * 5_000},
            }
            for index in range(20)
        ]
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "quote.snapshot",
                    "daily.ohlcv",
                    "technical.structure",
                    "chips.institutional",
                    "chips.margin",
                    "ownership.distribution",
                    "broker_branch.summary",
                ],
                "max_response_bytes": 32_768,
            },
            output="decision_with_evidence",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="broker_branch",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )
        data = canonical["evidence"]["data"]
        core_capabilities = {
            "target.identity",
            "quote.snapshot",
            "daily.ohlcv",
            "technical.structure",
            "chips.institutional",
            "chips.margin",
            "broker_branch.summary",
            "data.freshness",
        }

        self.assertTrue(core_capabilities <= set(data))
        self.assertEqual(data["quote.snapshot"]["price"], 2350)
        self.assertEqual(
            data["technical.structure"]["projection_level"],
            "summary",
        )
        self.assertEqual(
            len(data["broker_branch.summary"]["buy_top"]),
            3,
        )
        self.assertEqual(
            data["daily.ohlcv"]["point_count"],
            120,
        )
        self.assertIn("latest_point", data["daily.ohlcv"])
        self.assertTrue(canonical["projection"]["budget_met"])
        self.assertTrue(canonical["projection"]["truncated"])
        self.assertFalse(
            core_capabilities
            & set(canonical["projection"]["omitted_capabilities"])
        )

    def test_v4_data_only_budget_keeps_required_evidence_summaries(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "latest_completed_session",
                "chart": "current",
                "technical": "current",
                "chips": "current",
            }
        )
        response["mode"] = {
            "requested": "data_only",
            "effective": "data_only",
            "response": "data_only",
            "payload_level": "compact",
        }
        response["report_level"] = "standard"
        compact = response["result"]["data"]["compact"]
        compact["quote"] = {
            "price": 2350,
            "change_pct": -2.2869,
            "trade_date": "2026-07-24",
            "quote_time": "2026-07-24T13:30:00+08:00",
            "status": "latest_completed_session",
            "provider": "local_daily_close",
            "volume_unit": "lots",
        }
        compact["chart"] = {
            "latest_data_date": "2026-07-24",
            "point_count": 120,
            "points": [
                {
                    "date": f"2026-03-{(index % 28) + 1:02d}",
                    "open_price": 2200 + index,
                    "high_price": 2210 + index,
                    "low_price": 2190 + index,
                    "close_price": 2205 + index,
                    "volume": 100_000 + index,
                }
                for index in range(120)
            ],
            "volume_unit": "shares",
            "source": "market_daily_price",
        }
        compact["technical"] = {
            "analysis": {
                "selected_summary": "Downtrend with a bounded rebound setup.",
                "selected_score": 38,
            },
            "levels": {
                "latest_price": 2350,
                "entry": {"breakout_confirm_above": {"price": 2505}},
                "risk": {"technical_invalidation": {"price": 2290}},
            },
            "reports": {
                f"report-{index}": {"detail": "x" * 2_000}
                for index in range(20)
            },
        }
        compact["chips"] = {
            "institutional": {
                "trade_date": "2026-07-24",
                "foreign_investor_net": -9_636_606,
                "total_institutional_net": -8_781_367,
            },
            "margin": {
                "trade_date": "2026-07-24",
                "margin_today_balance": 31_915,
                "short_today_balance": 67,
            },
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "quote.snapshot",
                    "daily.ohlcv",
                    "technical.structure",
                    "chips.institutional",
                    "chips.margin",
                ],
                "limits": {"daily.ohlcv": 120},
                "max_response_bytes": 32_768,
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )
        required_capabilities = set(selection["required"])
        data = canonical["evidence"]["data"]

        self.assertTrue(required_capabilities <= set(data))
        self.assertEqual(
            data["technical.structure"]["projection_level"],
            "summary",
        )
        self.assertEqual(data["daily.ohlcv"]["points_included"], 0)
        self.assertLessEqual(
            canonical["projection"]["actual_response_bytes"],
            32_768,
        )
        self.assertTrue(canonical["projection"]["budget_met"])
        self.assertFalse(
            required_capabilities
            & set(canonical["projection"]["omitted_capabilities"])
        )

    def test_v4_realtime_state_does_not_depend_on_selected_output_fields(self) -> None:
        response = _v2_response()
        response["result"]["data"]["compact"]["quote"] = {
            "status": "delayed_daily_close",
            "latest_price": 2350,
            "trade_date": "2026-07-24",
            "provider": "local_daily_close",
            "market_status": "closed",
            "session_phase": "post_close_snapshot",
            "is_realtime": False,
            "freshness": {
                "status": "daily_close",
                "is_stale": False,
            },
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["quote.snapshot"],
                "fields": {
                    "quote.snapshot": [
                        "latest_price",
                        "trade_date",
                    ]
                },
                "max_response_bytes": 32_768,
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        self.assertEqual(
            canonical["evidence"]["data"]["quote.snapshot"],
            {
                "latest_price": 2350,
                "trade_date": "2026-07-24",
            },
        )
        self.assertEqual(
            canonical["evidence"]["realtime"]["quote.snapshot"]["state"],
            "latest_completed_session",
        )
        self.assertTrue(
            canonical["evidence"]["realtime"]["quote.snapshot"][
                "decision_usable"
            ]
        )

    def test_v4_stale_capability_returns_granular_fill_action(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "stale",
                "technical": "latest_completed_session",
            }
        )
        response["result"]["data"]["compact"]["quote"] = {
            "price": 1000,
            "quote_time": "2026-07-22T13:30:00+08:00",
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["quote.snapshot"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        actions = canonical["continuation"]["fill_plan"]["actions"]
        quote_action = next(
            item for item in actions if item["capability"] == "quote.snapshot"
        )
        self.assertEqual(quote_action["operation"], "tw.refresh_quote")
        self.assertEqual(quote_action["estimated_calls"], 1)
        self.assertTrue(quote_action["executable"])
        self.assertEqual(quote_action["invoke"]["tool"], "omi.ask")
        self.assertTrue(quote_action["invoke"]["arguments"]["question"])
        self.assertEqual(
            quote_action["invoke"]["arguments"]["continuation"][
                "selected_action_ids"
            ],
            [quote_action["action_id"]],
        )
        self.assertIn(
            quote_action["action_id"],
            quote_action["invoke"]["arguments"]["continuation"][
                "plan_action_ids"
            ],
        )
        self.assertFalse(canonical["answer"])
        self.assertFalse(canonical["decision"])

    def test_v4_chip_quality_and_fill_plan_use_capability_freshness(
        self,
    ) -> None:
        response = _v2_response(
            freshness_by_domain={
                "chips": "stale",
                "technical": "latest_completed_session",
            }
        )
        compact = response["result"]["data"]["compact"]
        compact["freshness_by_capability"] = {
            "chips.institutional": {
                "status": "current",
                "refresh_recommended": False,
            },
            "chips.margin": {
                "status": "current",
                "refresh_recommended": False,
            },
            "ownership.distribution": {
                "status": "stale",
                "refresh_recommended": True,
            },
        }
        compact["chips"] = {
            "institutional": {
                "trade_date": "2026-07-24",
                "foreign_investor_net": 100,
                "source": "institutional_trade_daily",
            },
            "margin": {
                "trade_date": "2026-07-24",
                "margin_today_balance": 200,
                "source": "margin_trading_daily",
            },
            "shareholding": {
                "trade_date": "2026-07-17",
                "distribution": [
                    {"holding_level": "1", "holder_count": 10}
                ],
                "source": "shareholding_distribution_weekly",
            },
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "chips.institutional",
                    "chips.margin",
                    "ownership.distribution",
                ]
            },
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )
        quality = canonical["evidence"]["quality"]["capabilities"]

        self.assertEqual(
            quality["chips.institutional"]["status_authority"],
            "freshness_by_capability",
        )
        self.assertEqual(
            quality["chips.institutional"]["status_class"],
            "ready",
        )
        self.assertEqual(quality["chips.margin"]["status_class"], "ready")
        self.assertEqual(
            quality["ownership.distribution"]["status_class"],
            "blocked",
        )
        self.assertEqual(
            [
                action["capability"]
                for action in canonical["continuation"]["fill_plan"]["actions"]
            ],
            ["ownership.distribution"],
        )

    def test_v4_quality_contract_reconciles_stale_domain_slot_and_readiness(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "stale",
                "technical": "latest_completed_session",
            },
            trust_level="medium",
        )
        response["result"]["data"]["compact"]["quote"] = {
            "price": 1000,
            "quote_time": "2026-07-22T13:30:00+08:00",
            "provider": "test",
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["quote.snapshot"]},
            output="decision_with_evidence",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="entry_decision",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        quality = canonical["evidence"]["quality"]
        quote_quality = quality["capabilities"]["quote.snapshot"]
        self.assertEqual(quality["version"], "omi.data.quality.v1")
        self.assertEqual(quote_quality["status"], "stale")
        self.assertEqual(quote_quality["status_class"], "blocked")
        self.assertFalse(quote_quality["decision_usable"])
        quote_manifest = next(
            item
            for item in canonical["evidence"]["manifest"]["capabilities"]
            if item["capability"] == "quote.snapshot"
        )
        self.assertEqual(quote_manifest["status"], "stale")
        self.assertEqual(quote_manifest["status_class"], "blocked")
        self.assertEqual(
            canonical["evidence"]["slots"]["quote"]["status"],
            "blocked",
        )
        self.assertFalse(
            canonical["status"]["readiness"]["decision_ready"]
        )
        self.assertTrue(
            canonical["status"]["readiness"]["response_ready"]
        )
        self.assertTrue(
            canonical["status"]["readiness"]["decision_blocked"]
        )
        self.assertEqual(
            canonical["status"]["readiness"]["answer_kind"],
            "decision",
        )
        self.assertEqual(canonical["decision"]["action_plan"], [])
        self.assertEqual(canonical["decision"]["price_levels"], {})
        self.assertEqual(
            canonical["answer"]["stance"],
            "insufficient_data",
        )

    def test_v4_realtime_ready_quote_overrides_legacy_blocked_slot(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "stale",
                "technical": "latest_completed_session",
            }
        )
        response["result"]["data"]["compact"]["slots"]["quote"] = {
            "status": "blocked",
            "freshness": {"status": "stale"},
        }
        response["result"]["data"]["slots"]["quote"] = {
            "status": "blocked",
            "freshness": {"status": "stale"},
        }
        response["result"]["data"]["compact"]["quote"] = {
            "price": 2350,
            "change": -55,
            "change_pct": -2.2869,
            "total_volume_lots": 21505,
            "volume_unit": "lots",
            "trade_date": "2026-07-24",
            "quote_time": "2026-07-24T13:30:00+08:00",
            "status": "final_snapshot",
            "market_status": "latest_session_close",
            "session_phase": "post_close_snapshot",
            "is_realtime": False,
            "freshness": {
                "status": "final_snapshot",
                "is_stale": False,
            },
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["quote.snapshot"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        with patch(
            "app.ai.realtime_contract._calendar_completed_session",
            return_value=True,
        ):
            canonical = decision_envelope.for_requested_contract(
                response,
                requested_contract_version="omi.decision.v4",
            )

        quote_quality = canonical["evidence"]["quality"]["capabilities"][
            "quote.snapshot"
        ]
        self.assertEqual(quote_quality["status_authority"], "realtime")
        self.assertEqual(quote_quality["status_class"], "ready")
        self.assertTrue(quote_quality["facts_usable"])
        self.assertTrue(quote_quality["decision_usable"])
        self.assertNotIn("status_sources_disagree", quote_quality["issues"])
        self.assertTrue(
            any(
                item["code"] == "status_sources_disagree"
                and item["resolved_by"] == "realtime"
                and item["visibility"] == "debug"
                and item["affects_facts"] is False
                and item["affects_decision"] is False
                for item in quote_quality["contradictions"]
            )
        )
        self.assertNotIn(
            "status_sources_disagree",
            canonical["evidence"]["passport"]["reasons"],
        )
        self.assertNotIn("volume_unit_missing", quote_quality["issues"])
        self.assertNotIn(
            "capability:quote.snapshot",
            canonical["limitations"]["missing"],
        )
        self.assertEqual(
            canonical["evidence"]["passport"]["domains"]["quote"][
                "status_class"
            ],
            "ready",
        )
        self.assertFalse(
            any(
                "status_sources_disagree" in warning
                for warning in canonical["limitations"]["warnings"]
            )
        )

    def test_v4_keeps_upstream_trust_but_exposes_selected_capability_trust(
        self,
    ) -> None:
        response = _v2_response(trust_level="high")
        response["evidence_passport"]["summary"] = "資料可信度高"
        selection = capability_contract.normalize_selection(
            selection={"include": ["quote.snapshot"]},
            output="decision_with_evidence",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="entry_decision",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        passport = canonical["evidence"]["passport"]
        selected_trust = canonical["evidence"]["quality"]["trust_level"]
        self.assertEqual(passport["trust_level"], selected_trust)
        self.assertEqual(
            passport["source_trust"]["trust_level"],
            selected_trust,
        )
        self.assertEqual(passport["trust_scope"], "selected_capabilities")
        self.assertEqual(
            passport["source_trust"]["trust_scope"],
            "selected_capabilities",
        )
        self.assertEqual(
            passport["upstream_source_trust"]["trust_level"],
            "high",
        )
        self.assertEqual(
            passport["upstream_source_trust"]["trust_score"],
            91,
        )
        self.assertEqual(
            passport["upstream_source_trust"]["summary"],
            "資料可信度高",
        )
        self.assertEqual(
            passport["decision_readiness"]["trust_level"],
            selected_trust,
        )
        self.assertEqual(
            canonical["evidence"]["quality"]["trust_scope"],
            "decision_readiness",
        )

    def test_v4_quality_contract_detects_intraday_interval_mismatch(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "current",
                "intraday": "current",
                "technical": "latest_completed_session",
            }
        )
        response["result"]["data"]["compact"]["intraday_bars"] = {
            "interval": "1m",
            "point_count": 3,
            "returned_point_count": 3,
            "points": [
                {
                    "bar_time": "2026-07-24T09:00:00+08:00",
                    "close_price": 1000,
                },
                {
                    "bar_time": "2026-07-24T09:00:05+08:00",
                    "close_price": 1001,
                },
                {
                    "bar_time": "2026-07-24T09:00:10+08:00",
                    "close_price": 1002,
                },
            ],
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["intraday.bars"]},
            output="decision_with_evidence",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="entry_decision",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        intraday_quality = canonical["evidence"]["quality"]["capabilities"][
            "intraday.bars"
        ]
        self.assertEqual(
            intraday_quality["continuity"]["status"],
            "partial",
        )
        self.assertIn(
            "interval_mismatch",
            intraday_quality["continuity"]["issues"],
        )
        self.assertFalse(intraday_quality["decision_usable"])
        self.assertFalse(
            canonical["status"]["readiness"]["decision_ready"]
        )

    def test_v4_quality_contract_blocks_cross_date_quote_daily_and_technical_fusion(
        self,
    ) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "current",
                "chart": "current",
                "technical": "current",
            }
        )
        compact = response["result"]["data"]["compact"]
        compact["quote"] = {
            "price": 2350,
            "trade_date": "2026-07-24",
            "quote_time": "2026-07-24T13:30:00+08:00",
            "currency": "TWD",
            "price_unit": "TWD_per_share",
        }
        compact["chart"] = {
            "latest_data_date": "2026-07-23",
            "points": [
                {
                    "bar_time": "2026-07-23T13:30:00+08:00",
                    "close_price": 2405,
                }
            ],
            "currency": "TWD",
            "price_unit": "TWD_per_share",
        }
        compact["technical"] = {
            "trade_date": "2026-07-23",
            "latest_price": 2405,
            "levels": {"support": 2380},
            "currency": "TWD",
            "price_unit": "TWD_per_share",
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "quote.snapshot",
                    "daily.ohlcv",
                    "technical.structure",
                ]
            },
            output="decision_with_evidence",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="entry_decision",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        quality = canonical["evidence"]["quality"]
        issue_codes = {
            item["code"] for item in quality["fusion"]["issues"]
        }
        self.assertIn("price_basis_date_mismatch", issue_codes)
        self.assertIn("quote_daily_date_mismatch", issue_codes)
        self.assertFalse(
            quality["capabilities"]["technical.structure"]["decision_usable"]
        )
        self.assertFalse(
            quality["capabilities"]["daily.ohlcv"]["decision_usable"]
        )
        self.assertFalse(canonical["status"]["readiness"]["decision_ready"])
        self.assertEqual(canonical["decision"]["price_levels"], {})

    def test_v4_quality_contract_requires_volume_units_for_decision_use(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "current",
                "technical": "latest_completed_session",
            }
        )
        response["result"]["data"]["compact"]["quote"] = {
            "price": 2350,
            "trade_date": "2026-07-24",
            "volume": 1000,
            "currency": "TWD",
            "price_unit": "TWD_per_share",
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["quote.snapshot"]},
            output="decision_with_evidence",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="entry_decision",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        quote_quality = canonical["evidence"]["quality"]["capabilities"][
            "quote.snapshot"
        ]
        self.assertTrue(quote_quality["units"]["missing_volume_unit"])
        self.assertEqual(
            quote_quality["units"]["missing_unit_fields"],
            ["volume"],
        )
        self.assertIn("volume_unit_missing", quote_quality["issues"])
        self.assertFalse(quote_quality["decision_usable"])
        self.assertFalse(canonical["status"]["readiness"]["decision_ready"])

    def test_market_target_resolves_to_market_specific_context(self) -> None:
        for market in ("US", "JP", "KR", "TW"):
            with self.subTest(market=market):
                resolution = scope_resolution._resolve_scope(
                    None,
                    AiAskRequest(
                        question="目前市場怎麼看？",
                        target={"type": "market", "market": market},
                    ),
                )
                self.assertEqual(resolution.selected_scope_type, "market")
                self.assertEqual(resolution.selected_scope_id, market)
                self.assertEqual(resolution.selected_market, market)

        id_only_resolution = scope_resolution._resolve_scope(
            db=None,
            payload=AiAskRequest(
                question="US market context",
                target={"type": "market", "id": "US"},
            ),
        )
        self.assertEqual(id_only_resolution.selected_scope_type, "market")
        self.assertEqual(id_only_resolution.selected_scope_id, "US")
        self.assertEqual(id_only_resolution.selected_market, "US")

    def test_v4_require_live_blocks_completed_session_fallback(self) -> None:
        response = _v2_response(
            freshness_by_domain={
                "quote": "latest_completed_session",
                "technical": "latest_completed_session",
            }
        )
        response["result"]["data"]["compact"]["quote"] = {
            "price": 2350,
            "last_price": 2350,
            "price_available": True,
            "fallback_used": True,
            "fallback_type": "latest_completed_session_close",
            "trade_date": "2026-07-24",
            "quote_time": "2026-07-24T13:30:00+08:00",
            "provider": "local_daily_cache",
            "source": "daily_price",
            "status": "final_snapshot",
            "market_status": "latest_session_close",
            "session_phase": "post_close_snapshot",
            "is_realtime": False,
            "freshness": {
                "status": "latest_completed_session",
                "is_stale": False,
            },
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["quote.snapshot"]},
            output="evidence_only",
            realtime_policy="require_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )
        response["query_plan"]["selection"] = selection
        response["query_plan"]["target_type"] = "stock"

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        realtime = canonical["evidence"]["realtime"]["quote.snapshot"]
        quote_quality = canonical["evidence"]["quality"]["capabilities"][
            "quote.snapshot"
        ]
        self.assertFalse(realtime["policy_satisfied"])
        self.assertFalse(realtime["decision_usable"])
        self.assertEqual(realtime["status_class"], "blocked")
        self.assertFalse(quote_quality["decision_usable"])
        self.assertFalse(canonical["status"]["readiness"]["decision_ready"])
        self.assertIn(
            "live_requirement_not_satisfied",
            canonical["limitations"]["missing"],
        )

    def test_provider_failures_separate_request_background_and_history(
        self,
    ) -> None:
        response = _v2_response()
        response["target"] = {
            "type": "jp_index",
            "id": "^N225",
            "market": "JP",
            "label": "Nikkei 225",
        }
        response["resolution"]["target"] = dict(response["target"])
        response["result"]["data"]["source_health"] = {
            "kind": "jp_source_health",
            "expected_daily_price_date": "2026-07-23",
            "entries": [
                {
                    "resource": "daily_price",
                    "provider": "yahoo_chart",
                    "target": "^N225",
                    "status": "stale",
                    "latest_data_date": "2026-07-21",
                    "expected_data_date": "2026-07-23",
                    "freshness_lag_days": 2,
                    "reason": "behind expected session",
                    "latest_event": {
                        "provider": "yahoo_chart",
                        "resource": "daily_price",
                        "target": "^N225",
                        "status": "failed",
                        "event_time": "2026-07-23T00:00:00+00:00",
                    },
                },
                {
                    "resource": "company_fundamental",
                    "provider": "opendart",
                    "target": "005930",
                    "status": "stale",
                    "latest_data_date": "2025-12-31",
                    "expected_data_date": "2026-03-31",
                    "reason": "unrelated KR fundamental cache is stale",
                },
            ],
        }
        response["tool_runs"] = [
            {
                "tool": "jp.refresh_daily_price",
                "status": "skipped",
                "error": "External fetch budget reached.",
            }
        ]

        canonical = decision_envelope.build(response)
        failures = canonical["limitations"]["provider_failures"]
        background = canonical["limitations"]["background_source_health"]
        historical = canonical["limitations"]["historical_provider_events"]
        selected = canonical["limitations"]["selected_source_health"]
        supplemental = canonical["limitations"]["supplemental_source_health"]

        self.assertTrue(
            any(
                item.get("tool") == "jp.refresh_daily_price"
                and item.get("status") == "skipped"
                for item in failures
            )
        )
        self.assertTrue(
            any(
                item.get("provider") == "yahoo_chart"
                and item.get("status") == "stale"
                for item in background
            )
        )
        self.assertEqual(
            selected[0]["source_health_relevance"],
            "selected",
        )
        self.assertFalse(
            any(item.get("provider") == "opendart" for item in background)
        )
        self.assertEqual(
            supplemental[0]["source_health_relevance"],
            "supplemental",
        )
        self.assertEqual(supplemental[0]["provider"], "opendart")
        self.assertFalse(
            any(item.get("provider") == "yahoo_chart" for item in failures)
        )
        self.assertTrue(
            any(
                item.get("resource") == "daily_price"
                and item.get("status") == "failed"
                for item in historical
            )
        )
        self.assertEqual(
            canonical["limitations"]["current_request_failures"],
            failures,
        )

    def test_focused_quote_treats_same_target_unselected_resource_as_supplemental(
        self,
    ) -> None:
        response = _v2_response(
            freshness_by_domain={"quote": "current"},
        )
        response["query_plan"]["selected_capabilities"] = [
            "quote.snapshot",
            "data.freshness",
        ]
        response["query_plan"]["requested_domains"] = ["quote", "freshness"]
        response["result"]["data"]["source_health"] = {
            "kind": "taiwan_source_health",
            "expected_daily_price_date": "2026-07-27",
            "entries": [
                {
                    "resource": "taiwan_stock_quote_snapshot",
                    "provider": "twse_mis",
                    "target": "2330",
                    "market": "TW",
                    "status": "stale",
                    "reason": "quote snapshot is stale",
                },
                {
                    "resource": "financial_metric_quarterly",
                    "provider": "twse_openapi",
                    "target": "2330",
                    "market": "TW",
                    "status": "stale",
                    "reason": "unselected fundamental resource is stale",
                },
                {
                    "resource": "taiwan_stock_quote_snapshot",
                    "provider": "twse_mis",
                    "target": "2317",
                    "market": "TW",
                    "status": "stale",
                    "reason": "different target in the same market",
                },
            ],
        }

        canonical = decision_envelope.build(response)

        background = canonical["limitations"]["background_source_health"]
        supplemental = canonical["limitations"]["supplemental_source_health"]
        self.assertTrue(
            any(
                item.get("resource") == "taiwan_stock_quote_snapshot"
                for item in background
            )
        )
        self.assertFalse(
            any(
                item.get("resource") == "financial_metric_quarterly"
                for item in background
            )
        )
        self.assertTrue(
            any(
                item.get("resource") == "financial_metric_quarterly"
                and item.get("source_health_relevance") == "supplemental"
                for item in supplemental
            )
        )
        self.assertTrue(
            any(
                item.get("target") == "2317"
                and item.get("source_health_relevance") == "supplemental"
                for item in supplemental
            )
        )

    def test_successful_current_refresh_does_not_retain_old_event_as_failure(
        self,
    ) -> None:
        response = _v2_response()
        response["result"]["data"]["source_health"] = {
            "kind": "taiwan_source_health",
            "expected_daily_price_date": "2026-07-27",
            "entries": [
                {
                    "resource": "taiwan_stock_quote_snapshot",
                    "provider": "twse_mis",
                    "target": "2330",
                    "status": "stale",
                    "reason": "historical snapshot is stale",
                    "latest_event": {
                        "provider": "twse_mis",
                        "resource": "taiwan_stock_quote_snapshot",
                        "target": "2330",
                        "status": "failed",
                        "event_time": "2026-07-24T05:24:00+00:00",
                    },
                }
            ],
        }
        response["tool_runs"] = [
            {
                "tool": "tw.refresh_quote",
                "provider": "twse_mis",
                "status": "completed",
                "message": "Current-session quote refreshed.",
            }
        ]

        canonical = decision_envelope.build(response)

        self.assertEqual(canonical["limitations"]["provider_failures"], [])
        self.assertEqual(
            canonical["limitations"]["current_request_failures"],
            [],
        )
        self.assertEqual(
            canonical["limitations"]["background_source_health"][0][
                "resource"
            ],
            "taiwan_stock_quote_snapshot",
        )
        self.assertEqual(
            canonical["limitations"]["historical_provider_events"][0][
                "event_time"
            ],
            "2026-07-24T05:24:00+00:00",
        )

    def test_v4_projects_intraday_from_canonical_result_before_mode_projection(
        self,
    ) -> None:
        response = _v2_response(freshness_by_domain={"intraday": "current"})
        response["target"] = {
            "type": "us_stock",
            "id": "AAPL",
            "market": "US",
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["intraday.bars"],
                "limits": {"intraday.points": 2},
            },
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="standard",
            scope_type="us_stock",
            question_intent="quote",
        )
        response["query_plan"] = {
            "target_type": "us_stock",
            "payload_level": "standard",
            "selection": selection,
        }
        response["tool_runs"] = [
            {
                "tool": "us.read_intraday_trend",
                "status": "success",
                "arguments": {
                    "symbol": "AAPL",
                    "requested_capabilities": ["intraday.bars"],
                },
                "external_fetch": True,
                "writes_cache": False,
                "result_summary": {
                    "point_count": 3,
                    "returned_point_count": 3,
                },
                "duration_ms": 25,
            }
        ]
        response["result"] = {
            "kind": "us_stock_context",
            "data": {
                "compact": {
                    "intraday_bars": {
                        "enabled": True,
                        "payload_level": "standard",
                        "bar_limit": 2,
                    }
                }
            },
        }
        canonical_result = {
            "kind": "us_stock_context",
            "data": {
                "compact": {
                    "intraday_bars": {
                        "enabled": True,
                        "payload_level": "standard",
                        "bar_limit": 2,
                        "series": {
                            "1m": {
                                "interval": "1m",
                                "source": "yahoo_finance_chart",
                                "provider": "yahoo_chart",
                                "volume_unit": "shares",
                                "volume_semantics": "interval_shares",
                                "point_count": 3,
                                "returned_point_count": 3,
                                "points": [
                                    {
                                        "time": "2026-07-24T09:30:00-04:00",
                                        "price": 210.0,
                                    },
                                    {
                                        "time": "2026-07-24T09:31:00-04:00",
                                        "price": 210.5,
                                    },
                                    {
                                        "time": "2026-07-24T09:32:00-04:00",
                                        "price": 211.0,
                                    },
                                ],
                            }
                        },
                    },
                    "freshness_by_domain": {"intraday": "current"},
                    "slots": {"intraday": {"status": "ready"}},
                }
            },
        }

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
            canonical_result=canonical_result,
        )

        intraday = canonical["evidence"]["data"]["intraday.bars"]
        self.assertEqual(intraday["interval"], "1m")
        self.assertEqual(intraday["source"], "yahoo_finance_chart")
        self.assertEqual(
            [point["price"] for point in intraday["points"]],
            [210.5, 211.0],
        )
        self.assertEqual(intraday["returned_point_count"], 2)
        self.assertTrue(intraday["truncated"])
        self.assertEqual(intraday["latest_point"]["price"], 211.0)
        self.assertEqual(
            intraday["event_time"],
            "2026-07-24T09:32:00-04:00",
        )
        self.assertEqual(intraday["volume_unit"], "shares")
        reconciliation = canonical["execution"]["refresh_reconciliation"]
        intraday_outcome = reconciliation["capabilities"]["intraday.bars"]
        self.assertTrue(intraday_outcome["tool_succeeded"])
        self.assertTrue(intraday_outcome["payload_included"])
        self.assertEqual(
            intraday_outcome["reconciliation"],
            (
                "satisfied"
                if intraday_outcome["usable_evidence_available"]
                else "evidence_available_with_quality_limits"
            ),
        )
        self.assertIsNone(intraday_outcome["remaining_fill_action"])
        self.assertNotIn(
            "intraday.bars",
            {
                action["capability"]
                for action in canonical["continuation"]["fill_plan"]["actions"]
            },
        )

    def test_v4_keeps_fill_action_when_tool_succeeds_without_projected_payload(
        self,
    ) -> None:
        response = _v2_response(freshness_by_domain={"intraday": "current"})
        response["target"] = {
            "type": "us_stock",
            "id": "AAPL",
            "market": "US",
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["intraday.bars"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="standard",
            scope_type="us_stock",
            question_intent="quote",
        )
        response["query_plan"] = {
            "target_type": "us_stock",
            "payload_level": "standard",
            "selection": selection,
        }
        response["tool_runs"] = [
            {
                "tool": "us.read_intraday_trend",
                "status": "success",
                "arguments": {
                    "symbol": "AAPL",
                    "requested_capabilities": ["intraday.bars"],
                },
                "external_fetch": True,
                "writes_cache": False,
                "result_summary": {"status": "success"},
                "duration_ms": 25,
            }
        ]
        response["result"] = {
            "kind": "us_stock_context",
            "data": {
                "compact": {
                    "freshness_by_domain": {"intraday": "current"},
                    "slots": {"intraday": {"status": "ready"}},
                }
            },
        }

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
        )

        actions = canonical["continuation"]["fill_plan"]["actions"]
        intraday_action = next(
            action
            for action in actions
            if action["capability"] == "intraday.bars"
        )
        self.assertEqual(intraday_action["reason"], "payload_not_included")
        intraday_outcome = canonical["execution"]["refresh_reconciliation"][
            "capabilities"
        ]["intraday.bars"]
        self.assertTrue(intraday_outcome["tool_succeeded"])
        self.assertFalse(intraday_outcome["usable_evidence_available"])
        self.assertEqual(
            intraday_outcome["reconciliation"],
            "successful_without_usable_evidence",
        )
        self.assertEqual(
            intraday_outcome["remaining_fill_action"],
            intraday_action["action_id"],
        )

    def test_v4_projects_daily_ohlcv_from_canonical_result_before_mode_projection(
        self,
    ) -> None:
        response = _v2_response(freshness_by_domain={"chart": "current"})
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["daily.ohlcv"],
                "limits": {"daily.points": 2},
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        response["query_plan"] = {
            "target_type": "stock",
            "payload_level": "compact",
            "selection": selection,
        }
        response["result"] = {
            "kind": "stock_context",
            "data": {"compact": {"freshness_by_domain": {"chart": "current"}}},
        }
        canonical_result = {
            "kind": "stock_context",
            "data": {
                "chart": {
                    "latest_data_date": "2026-07-24",
                    "point_count": 3,
                    "points": [
                        {"bar_time": "2026-07-22", "close_price": 2300},
                        {"bar_time": "2026-07-23", "close_price": 2320},
                        {"bar_time": "2026-07-24", "close_price": 2350},
                    ],
                    "currency": "TWD",
                    "price_unit": "TWD_per_share",
                    "volume_unit": "shares",
                    "source": "market_daily_price",
                },
                "compact": {
                    "freshness_by_domain": {"chart": "current"},
                    "slots": {"daily_chart": {"status": "ready"}},
                },
            },
        }

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
            canonical_result=canonical_result,
        )

        daily = canonical["evidence"]["data"]["daily.ohlcv"]
        self.assertEqual(daily["latest_data_date"], "2026-07-24")
        self.assertEqual(
            [point["close_price"] for point in daily["points"]],
            [2320, 2350],
        )
        self.assertEqual(daily["returned_point_count"], 2)
        self.assertTrue(daily["truncated"])
        self.assertEqual(daily["volume_unit"], "shares")

    def test_v4_projects_source_health_entries_from_canonical_result(
        self,
    ) -> None:
        response = _v2_response(freshness_by_domain={"source_health": "partial"})
        response["target"] = {
            "type": "source_health",
            "market": "TW",
        }
        selection = capability_contract.normalize_selection(
            selection={},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="source_health",
            question_intent="general",
        )
        response["query_plan"] = {
            "target_type": "source_health",
            "payload_level": "compact",
            "selection": selection,
        }
        response["result"] = {
            "kind": "unified_source_health_context",
            "data": {
                "compact": {
                    "resources": {"entry_count": 1, "problem_count": 1},
                    "freshness_by_domain": {"source_health": "partial"},
                }
            },
        }
        canonical_result = {
            "kind": "unified_source_health_context",
            "data": {
                "filters": {"market": "TW", "limit": 50},
                "summary": {"entry_count": 1, "problem_count": 1},
                "entries": [
                    {
                        "market": "TW",
                        "resource": "market_daily_price",
                        "status": "stale",
                    }
                ],
                "compact": {
                    "resources": {"entry_count": 1, "problem_count": 1},
                    "freshness_by_domain": {"source_health": "partial"},
                    "slots": {"data_quality": {"status": "partial"}},
                },
            },
        }

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
            canonical_result=canonical_result,
        )

        source_health = canonical["evidence"]["data"]["diagnostics.source_health"]
        self.assertEqual(source_health["summary"]["problem_count"], 1)
        self.assertEqual(
            source_health["entries"][0]["resource"],
            "market_daily_price",
        )

    def test_v4_source_health_budget_keeps_summary_and_problem_sample(
        self,
    ) -> None:
        response = _v2_response(freshness_by_domain={"source_health": "partial"})
        response["target"] = {
            "type": "source_health",
            "market": "all",
        }
        selection = capability_contract.normalize_selection(
            selection={
                "limits": {"diagnostics.source_health": 200},
                "max_response_bytes": 131_072,
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="standard",
            scope_type="source_health",
            question_intent="general",
        )
        response["query_plan"] = {
            "target_type": "source_health",
            "payload_level": "standard",
            "selection": selection,
        }
        entries = [
            {
                "market": "tw" if index % 2 == 0 else "us",
                "resource": f"resource-{index}",
                "target": "all",
                "provider": "provider",
                "status": "stale" if index < 65 else "current",
                "reason": "x" * 2_000,
                "checked_at": "2026-07-22T16:28:44+08:00",
            }
            for index in range(200)
        ]
        canonical_result = {
            "kind": "unified_source_health_context",
            "data": {
                "filters": {"market": None, "limit": 200},
                "summary": {
                    "entry_count": 200,
                    "total_entry_count": 200,
                    "returned_entry_count": 200,
                    "problem_count": 65,
                    "total_problem_count": 65,
                    "returned_problem_count": 65,
                },
                "entries": entries,
                "freshness": {
                    "status": "expired",
                    "checked_at": "2026-07-22T16:28:44+08:00",
                    "is_current": False,
                },
            },
        }

        canonical = decision_envelope.for_requested_contract(
            response,
            requested_contract_version="omi.decision.v4",
            canonical_result=canonical_result,
        )
        source_health = canonical["evidence"]["data"][
            "diagnostics.source_health"
        ]

        self.assertEqual(source_health["summary"]["total_entry_count"], 200)
        self.assertEqual(source_health["summary"]["total_problem_count"], 65)
        self.assertLessEqual(len(source_health["entries"]), 20)
        self.assertEqual(
            sum(source_health["summary"]["returned_status_counts"].values()),
            len(source_health["entries"]),
        )
        self.assertEqual(
            sum(source_health["summary"]["returned_market_counts"].values()),
            len(source_health["entries"]),
        )
        self.assertEqual(
            source_health["summary"]["returned_problem_count"],
            len(source_health["entries"]),
        )
        self.assertTrue(
            all(
                entry["status"] != "current"
                for entry in source_health["entries"]
            )
        )
        self.assertTrue(source_health["truncated"])
        self.assertNotIn(
            "diagnostics.source_health",
            canonical["projection"]["omitted_capabilities"],
        )
        self.assertTrue(canonical["projection"]["budget_met"])


if __name__ == "__main__":
    unittest.main()
