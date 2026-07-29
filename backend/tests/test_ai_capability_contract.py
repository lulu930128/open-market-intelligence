from __future__ import annotations

import unittest
from unittest.mock import ANY, patch

from app.ai import agentic_execution, agentic_planning, capability_contract, query_plan
from app.ai.schemas import AiAskRequest


class AiCapabilityContractTests(unittest.TestCase):
    def test_quote_capability_projects_session_close_identity_fields(self) -> None:
        spec = capability_contract.CAPABILITIES["quote.snapshot"]

        for field in (
            "is_historical",
            "requested_trade_date",
            "regular_session_close",
            "regular_session_close_time",
            "regular_session_close_trade_date",
            "timezone",
        ):
            self.assertIn(field, spec.fields)
            self.assertIn(field, spec.default_fields)

    def test_volume_contract_fields_survive_capability_projection(self) -> None:
        intraday = capability_contract.CAPABILITIES["intraday.bars"]
        daily = capability_contract.CAPABILITIES["daily.ohlcv"]

        for field in (
            "base_volume_unit",
            "quote_volume_unit",
            "volume_contracts",
            "volume_event_time",
            "volume_semantics",
            "volume_status",
            "market_events",
            "sort_order",
        ):
            self.assertIn(field, intraday.fields)
            self.assertIn(field, intraday.default_fields)
        for field in (
            "base_volume_unit",
            "quote_volume_unit",
            "volume_semantics",
            "volume_status",
        ):
            self.assertIn(field, daily.fields)
            self.assertIn(field, daily.default_fields)

    def test_tw_futures_intraday_projection_prefers_contract_volume_chart(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["intraday.bars"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="full",
            scope_type="tw_futures",
            question_intent="quote",
        )
        response = {
            "target": {"type": "tw_futures", "id": "TXF", "market": "TW"},
            "result": {
                "data": {
                    "compact": {
                        "intraday_chart": {
                            "timeframe": "today",
                            "interval": "1m",
                            "point_count": 1,
                            "returned_point_count": 1,
                            "volume_unit": "contracts",
                            "volume_contracts": 82,
                            "volume_event_time": "2026-07-28T21:23:00+08:00",
                            "volume_semantics": "interval_contracts",
                            "volume_status": "available",
                            "session": "after_hours",
                            "sessions": ["after_hours"],
                            "source": "TAIFEX MIS 1-minute chart",
                            "provider": "taifex_mis",
                            "points": [
                                {
                                    "time": "2026-07-28T21:23:00+08:00",
                                    "close": 41_671,
                                    "volume_contracts": 82,
                                    "volume_unit": "contracts",
                                    "volume_semantics": "interval_contracts",
                                    "volume_status": "available",
                                    "session": "after_hours",
                                }
                            ],
                        }
                    },
                    "intraday_bars": [
                        {
                            "bar_time": "2026-07-28T21:23:00+08:00",
                            "close_price": 41_671,
                            "total_volume": 82,
                        }
                    ],
                }
            },
        }

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        intraday = projected["intraday.bars"]
        self.assertNotIn("intraday.bars", unavailable)
        self.assertEqual(intraday["volume_unit"], "contracts")
        self.assertEqual(intraday["volume_semantics"], "interval_contracts")
        self.assertEqual(intraday["volume_status"], "available")
        self.assertEqual(
            intraday["volume_event_time"],
            "2026-07-28T21:23:00+08:00",
        )
        self.assertEqual(intraday["session"], "after_hours")
        self.assertEqual(intraday["source"], "TAIFEX MIS 1-minute chart")
        self.assertEqual(intraday["provider"], "taifex_mis")
        self.assertEqual(intraday["points"][0]["volume_contracts"], 82)

    def test_selection_keeps_mandatory_truth_and_bounded_fields(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["quote.snapshot", "intraday.bars"],
                "fields": {
                    "quote.snapshot": [
                        "price",
                        "quote_time",
                        "quote_semantics",
                    ]
                },
                "limits": {"intraday.points": 3},
                "max_response_bytes": 20_000,
            },
            output="evidence_only",
            realtime_policy="require_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )

        self.assertEqual(selection["required"][0], "target.identity")
        self.assertIn("data.freshness", selection["required"])
        self.assertEqual(selection["limits"]["intraday.points"], 3)
        self.assertEqual(selection["max_response_bytes"], 20_000)
        self.assertEqual(selection["realtime_policy"], "require_live")

    def test_natural_language_chip_capabilities_do_not_select_siblings(self) -> None:
        payload = AiAskRequest(
            question=(
                "2330 台積電只查法人買賣超與融資融券，"
                "不要股權分散，也不要基本面。"
            ),
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="general",
            effective_mode="data_only",
        )

        self.assertEqual(
            set(plan.selected_capabilities),
            {
                "target.identity",
                "chips.institutional",
                "chips.margin",
                "data.freshness",
            },
        )
        self.assertEqual(plan.capability_selection_mode, "restrictive")
        self.assertIn("ownership.distribution", plan.selection["excluded"])
        self.assertNotIn("fundamentals.revenue", plan.selected_capabilities)
        self.assertNotIn("fundamentals.financials", plan.selected_capabilities)

    def test_natural_language_only_institutional_does_not_expand_chips_domain(
        self,
    ) -> None:
        payload = AiAskRequest(
            question="2330 只查法人。",
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="general",
            effective_mode="data_only",
        )

        self.assertEqual(
            set(plan.selected_capabilities),
            {
                "target.identity",
                "chips.institutional",
                "data.freshness",
            },
        )
        self.assertEqual(plan.capability_selection_mode, "restrictive")

    def test_natural_language_institutional_hint_without_restrictive_term_is_additive(
        self,
    ) -> None:
        payload = AiAskRequest(
            question="2330 法人買賣超分析。",
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="general",
            effective_mode="data_only",
        )

        self.assertEqual(plan.capability_selection_mode, "additive")
        self.assertIn("quote.snapshot", plan.selected_capabilities)
        self.assertIn("daily.ohlcv", plan.selected_capabilities)
        self.assertIn("technical.structure", plan.selected_capabilities)
        self.assertIn("chips.institutional", plan.selected_capabilities)

    def test_natural_language_chip_negation_is_capability_scoped(self) -> None:
        payload = AiAskRequest(
            question="2330 不要法人，只要融資。",
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="general",
            effective_mode="data_only",
        )

        self.assertIn("chips.margin", plan.selected_capabilities)
        self.assertNotIn("chips.institutional", plan.selected_capabilities)
        self.assertNotIn("ownership.distribution", plan.selected_capabilities)
        self.assertEqual(plan.capability_selection_mode, "restrictive")

    def test_structured_selection_remains_authoritative_over_question_hints(self) -> None:
        payload = AiAskRequest(
            question="查 2330 法人、融資券與股權分級。",
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
            selection={"include": ["chips.margin"]},
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="general",
            effective_mode="data_only",
        )

        self.assertIn("chips.margin", plan.selected_capabilities)
        self.assertNotIn("chips.institutional", plan.selected_capabilities)
        self.assertNotIn("ownership.distribution", plan.selected_capabilities)
        self.assertEqual(plan.capability_selection_mode, "explicit")

    def test_capability_freshness_plans_only_the_stale_chip_dataset(self) -> None:
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
        canonical = {
            "ok": True,
            "request_status": "completed",
            "target": {"type": "tw_stock", "id": "2330", "market": "TW"},
            "evidence": {
                "freshness": {"status": "current"},
                "freshness_by_domain": {"chips": {"status": "stale"}},
                "freshness_by_capability": {
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
                },
                "slots": {},
            },
        }
        projected = {
            "target.identity": canonical["target"],
            "chips.institutional": {
                "trade_date": "2026-07-24",
                "foreign_investor_net": 100,
            },
            "chips.margin": {
                "trade_date": "2026-07-24",
                "margin_today_balance": 200,
            },
            "ownership.distribution": {
                "trade_date": "2026-07-17",
                "distribution": [{"holding_level": "1", "holder_count": 10}],
            },
            "data.freshness": {"status": "current"},
        }

        manifest = capability_contract.build_manifest(
            canonical=canonical,
            selection=selection,
            projected_data=projected,
        )
        fill_plan = capability_contract.build_fill_plan(
            canonical=canonical,
            selection=selection,
            manifest=manifest,
            scope_type="stock",
        )

        statuses = {
            item["capability"]: item["status"]
            for item in manifest["capabilities"]
        }
        self.assertEqual(statuses["chips.institutional"], "current")
        self.assertEqual(statuses["chips.margin"], "current")
        self.assertEqual(statuses["ownership.distribution"], "stale")
        self.assertEqual(
            [action["capability"] for action in fill_plan["actions"]],
            ["ownership.distribution"],
        )
        self.assertEqual(
            fill_plan["actions"][0]["produced_capabilities"],
            ["ownership.distribution"],
        )

    def test_fill_plan_defers_operation_that_cannot_produce_capability(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["quote.snapshot"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )
        canonical = {
            "ok": True,
            "request_status": "completed",
            "target": {"type": "tw_stock", "id": "2330", "market": "TW"},
            "evidence": {
                "freshness": {"status": "missing"},
                "freshness_by_capability": {
                    "quote.snapshot": {
                        "status": "empty",
                        "refresh_recommended": True,
                    }
                },
                "slots": {},
            },
        }
        projected = {
            "target.identity": canonical["target"],
            "data.freshness": {"status": "missing"},
        }
        manifest = capability_contract.build_manifest(
            canonical=canonical,
            selection=selection,
            projected_data=projected,
        )

        with patch.dict(
            capability_contract.FILL_OPERATION_PRODUCED_CAPABILITIES,
            {"tw.refresh_quote": ("intraday.bars",)},
        ):
            fill_plan = capability_contract.build_fill_plan(
                canonical=canonical,
                selection=selection,
                manifest=manifest,
                scope_type="stock",
            )

        self.assertEqual(fill_plan["actions"], [])
        deferred = fill_plan["deferred_actions"][0]
        self.assertEqual(
            deferred["reason"],
            "operation_does_not_produce_capability",
        )
        self.assertEqual(deferred["operation"], "tw.refresh_quote")
        self.assertEqual(deferred["produced_capabilities"], ["intraday.bars"])

    def test_fill_plan_defers_stale_capability_during_refresh_cooldown(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["ownership.distribution"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        canonical = {
            "ok": True,
            "request_status": "completed",
            "target": {"type": "tw_stock", "id": "2330", "market": "TW"},
            "evidence": {
                "freshness": {"status": "current"},
                "freshness_by_capability": {
                    "ownership.distribution": {
                        "status": "stale",
                        "refresh_recommended": False,
                        "next_eligible_refresh_at": "2026-07-25T06:00:00+00:00",
                    }
                },
                "slots": {},
            },
        }
        projected = {
            "target.identity": canonical["target"],
            "data.freshness": {"status": "current"},
        }

        manifest = capability_contract.build_manifest(
            canonical=canonical,
            selection=selection,
            projected_data=projected,
        )
        fill_plan = capability_contract.build_fill_plan(
            canonical=canonical,
            selection=selection,
            manifest=manifest,
            scope_type="stock",
        )

        self.assertEqual(fill_plan["actions"], [])
        self.assertEqual(fill_plan["action_count"], 0)
        deferred = next(
            item
            for item in fill_plan["deferred_actions"]
            if item["capability"] == "ownership.distribution"
        )
        self.assertEqual(deferred["reason"], "refresh_cooldown")
        self.assertEqual(
            deferred["next_eligible_refresh_at"],
            "2026-07-25T06:00:00+00:00",
        )

    def test_fill_plan_refreshes_missing_capability_during_release_window(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["ownership.distribution"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        canonical = {
            "ok": True,
            "request_status": "completed",
            "target": {"type": "tw_stock", "id": "2330", "market": "TW"},
            "evidence": {
                "freshness": {"status": "missing"},
                "freshness_by_capability": {
                    "ownership.distribution": {
                        "status": "empty",
                        "release_status": "pending",
                        "refresh_recommended": True,
                    }
                },
                "slots": {},
            },
        }
        projected = {
            "target.identity": canonical["target"],
            "data.freshness": {"status": "missing"},
        }

        manifest = capability_contract.build_manifest(
            canonical=canonical,
            selection=selection,
            projected_data=projected,
        )
        fill_plan = capability_contract.build_fill_plan(
            canonical=canonical,
            selection=selection,
            manifest=manifest,
            scope_type="stock",
        )

        self.assertEqual(fill_plan["action_count"], 1)
        self.assertEqual(
            [action["capability"] for action in fill_plan["actions"]],
            ["ownership.distribution"],
        )
        self.assertEqual(fill_plan["deferred_actions"], [])

    def test_market_breadth_projects_count_fields_and_market_intraday_pack(self) -> None:
        response = {
            "target": {"type": "market", "id": "TW", "market": "TW"},
            "result": {
                "data": {
                    "compact": {
                        "breadth": {
                            "trade_date": "2026-07-24",
                            "status": "ready",
                            "advance_count": 700,
                            "decline_count": 500,
                            "unchanged_count": 20,
                            "total_count": 1220,
                            "scope": "full_market",
                            "direct_market_breadth": True,
                            "proxy_used": False,
                            "included_markets": ["TWSE", "TPEX"],
                        },
                        "index_intraday": {
                            "enabled": True,
                            "bar_limit": 2,
                            "index_ids": ["TAIEX", "TPEX"],
                            "indices": [
                                {
                                    "index_id": "TAIEX",
                                    "intraday_bars": {
                                        "series": {
                                            "1m": {
                                                "interval": "1m",
                                                "points": [
                                                    {
                                                        "bar_time": "2026-07-24T13:29:00+08:00",
                                                        "close_price": 23500,
                                                    },
                                                    {
                                                        "bar_time": "2026-07-24T13:30:00+08:00",
                                                        "close_price": 23510,
                                                    },
                                                ],
                                            }
                                        }
                                    },
                                }
                            ],
                        },
                    }
                }
            },
        }
        selection = capability_contract.normalize_selection(
            selection={"include": ["market.breadth", "intraday.bars"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="market",
            question_intent="market_breadth",
        )

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        self.assertEqual(projected["market.breadth"]["advance_count"], 700)
        self.assertEqual(
            projected["market.breadth"]["included_markets"],
            ["TWSE", "TPEX"],
        )
        self.assertTrue(
            projected["market.breadth"]["direct_market_breadth"]
        )
        self.assertFalse(projected["market.breadth"]["proxy_used"])
        self.assertEqual(
            projected["intraday.bars"]["index_ids"],
            ["TAIEX", "TPEX"],
        )
        self.assertNotIn("market.breadth", unavailable)
        self.assertNotIn("intraday.bars", unavailable)

    def test_defaults_preserve_existing_non_stock_context_surfaces(self) -> None:
        expected_by_scope = {
            "market": {
                "market.sample_ranking",
                "market.cross_market",
                "market.chips",
            },
            "tw_futures": {
                "derivatives.positioning",
                "derivatives.structure",
            },
            "watchlist": {
                "watchlist.ranking",
                "watchlist.radar",
                "watchlist.coverage",
            },
            "portfolio": {
                "portfolio.summary",
                "portfolio.holdings",
                "portfolio.valuation",
            },
            "us_macro": {
                "macro.series",
                "macro.observations",
            },
            "resource_asset": {
                "resource.metadata",
                "quote.snapshot",
                "daily.ohlcv",
            },
            "us_stock": {
                "company.profile",
                "corporate.actions",
                "market.short_volume",
            },
        }

        for scope_type, expected in expected_by_scope.items():
            with self.subTest(scope_type=scope_type):
                selection = capability_contract.normalize_selection(
                    selection={},
                    output="evidence_only",
                    realtime_policy="cache_only",
                    payload_level="compact",
                    scope_type=scope_type,
                    question_intent="general",
                )
                self.assertTrue(expected <= set(selection["required"]))

    def test_target_specific_capabilities_project_bounded_existing_context(self) -> None:
        response = {
            "target": {"type": "portfolio", "id": "active"},
            "result": {
                "data": {
                    "summary": {
                        "holding_count": 2,
                        "priced_holding_count": 1,
                        "missing_price_count": 1,
                        "stale_price_count": 0,
                        "market_counts": {"tw": 2},
                        "currencies": ["TWD"],
                    },
                    "holdings": [
                        {
                            "market": "tw",
                            "symbol": "2330",
                            "quantity": 1000,
                            "currency": "TWD",
                            "latest_price": 1000,
                            "market_value": 1_000_000,
                        },
                        {
                            "market": "tw",
                            "symbol": "2317",
                            "quantity": 2000,
                            "currency": "TWD",
                            "latest_price": None,
                            "market_value": None,
                        },
                    ],
                    "valuation": {
                        "cost_by_currency": {"TWD": 800_000},
                        "market_value_by_currency": {"TWD": 1_000_000},
                        "unrealized_pnl_by_currency": {"TWD": 200_000},
                        "cross_currency_total": None,
                    },
                    "compact": {},
                }
            },
        }
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "portfolio.summary",
                    "portfolio.holdings",
                    "portfolio.valuation",
                ],
                "limits": {"portfolio.holdings": 1},
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="portfolio",
            question_intent="general",
        )

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        self.assertEqual(projected["portfolio.summary"]["holding_count"], 2)
        self.assertEqual(len(projected["portfolio.holdings"]), 1)
        self.assertEqual(
            projected["portfolio.holdings"][0]["symbol"],
            "2317",
        )
        self.assertEqual(
            projected["portfolio.valuation"]["market_value_by_currency"],
            {"TWD": 1_000_000},
        )
        self.assertNotIn("portfolio.holdings", unavailable)

    def test_selection_rejects_unknown_capability_and_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown capability"):
            capability_contract.normalize_selection(
                selection={"include": ["tw.everything"]},
                output=None,
                realtime_policy=None,
                payload_level="compact",
                scope_type="stock",
                question_intent="general",
            )

        with self.assertRaisesRegex(ValueError, "Unsupported field"):
            capability_contract.normalize_selection(
                selection={
                    "include": ["quote.snapshot"],
                    "fields": {"quote.snapshot": ["raw_provider_payload"]},
                },
                output=None,
                realtime_policy=None,
                payload_level="compact",
                scope_type="stock",
                question_intent="quote",
            )

    def test_selection_reports_known_capability_unsupported_for_scope(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["market.breadth"],
                "fields": {"market.breadth": ["advance_count"]},
                "limits": {"market.breadth": 10},
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="market_breadth",
        )

        self.assertNotIn("market.breadth", selection["required"])
        self.assertIn("target.identity", selection["required"])
        self.assertIn("data.freshness", selection["required"])
        self.assertNotIn("market.breadth", selection["fields"])
        self.assertNotIn("market.breadth", selection["limits"])
        self.assertEqual(
            selection["unsupported_capabilities"],
            [
                {
                    "capability": "market.breadth",
                    "status": "unsupported",
                    "reason_code": "unsupported_target_scope",
                    "requested_as": "required",
                    "request_source": "explicit_selection",
                    "target_scope": "stock",
                    "supported_scopes": [
                        "market",
                        "tw_index",
                        "tw_futures",
                        "us_stock",
                        "jp_index",
                        "kr_index",
                        "crypto_market",
                    ],
                    "message": (
                        "market.breadth is not supported for target scope stock."
                    ),
                }
            ],
        )
        self.assertEqual(
            selection["unmet_required_capabilities"],
            selection["unsupported_capabilities"],
        )

    def test_optional_unsupported_capability_is_not_unmet_required(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={"optional": ["market.breadth"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="quote",
        )

        self.assertEqual(
            selection["unsupported_capabilities"][0]["requested_as"],
            "optional",
        )
        self.assertEqual(selection["unmet_required_capabilities"], [])

    def test_query_plan_maps_v4_selection_to_existing_reader_domains(self) -> None:
        payload = AiAskRequest(
            question="只要 2330 最新價與三筆盤中資料",
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
            selection={
                "include": ["quote.snapshot", "intraday.bars"],
                "limits": {"intraday.points": 3},
            },
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="quote",
            effective_mode="data_only",
        )

        self.assertIn("quote", plan.requested_domains)
        self.assertIn("intraday", plan.requested_domains)
        self.assertIn("quote.snapshot", plan.selected_capabilities)
        self.assertIn("intraday.bars", plan.selected_capabilities)
        self.assertIn("get_taiwan_stock_quote_depth", plan.required_readers)
        self.assertIn("get_market_intraday_history", plan.required_readers)

    def test_multi_intent_broker_question_uses_standard_stock_planner(self) -> None:
        payload = AiAskRequest(
            question=(
                "2330 latest price, daily chart, technical, institutional, "
                "margin, and broker branch"
            ),
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
            intents=["broker_branch", "quote", "trend_view"],
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="broker_branch",
            effective_mode="data_only",
        )

        self.assertEqual(plan.required_readers, ())
        self.assertEqual(plan.excluded_readers, ())
        self.assertIn("quote.snapshot", plan.selected_capabilities)
        self.assertIn("daily.ohlcv", plan.selected_capabilities)
        self.assertIn("technical.structure", plan.selected_capabilities)
        self.assertIn("chips.institutional", plan.selected_capabilities)
        self.assertIn("chips.margin", plan.selected_capabilities)
        self.assertIn("broker_branch.summary", plan.selected_capabilities)
        self.assertTrue(
            {"quote", "chart", "technical", "chips", "broker_branch"}
            <= set(plan.requested_domains)
        )

    def test_pure_broker_question_keeps_bounded_fast_path(self) -> None:
        payload = AiAskRequest(
            question="2330 broker branch",
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
            intents=["broker_branch"],
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="broker_branch",
            effective_mode="data_only",
        )

        self.assertEqual(
            plan.required_readers,
            ("get_stock", "get_broker_branch_trade_summary"),
        )
        self.assertIn(
            "get_latest_stock_monthly_revenue",
            plan.excluded_readers,
        )
        self.assertFalse(plan.external_refresh_allowed)

    def test_explicit_intents_add_capabilities_without_keyword_hints(self) -> None:
        payload = AiAskRequest(
            question="2330",
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
            intents=["broker_branch", "quote", "trend_view"],
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="broker_branch",
            effective_mode="data_only",
        )

        self.assertIn("quote.snapshot", plan.selected_capabilities)
        self.assertIn("daily.ohlcv", plan.selected_capabilities)
        self.assertIn("technical.structure", plan.selected_capabilities)
        self.assertIn("broker_branch.summary", plan.selected_capabilities)
        self.assertEqual(plan.required_readers, ())

    def test_market_volume_question_selects_bounded_volume_capability(self) -> None:
        payload = AiAskRequest(
            question="只要今天台股成交值與量能速度，不要排行。",
            contract_version="omi.decision.v4",
            target={"type": "market", "market": "TW"},
            mode="data_only",
            output="evidence_only",
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="market",
            question_intent="market_breadth",
            effective_mode="data_only",
        )

        self.assertIn("volume", plan.requested_domains)
        self.assertIn("market.volume_state", plan.selected_capabilities)
        self.assertIn("market.breadth", plan.selected_capabilities)

    def test_tw_futures_night_volume_selects_contract_quote_and_intraday(self) -> None:
        payload = AiAskRequest(
            question="TXF 夜盤目前成交量",
            contract_version="omi.decision.v4",
            target={"type": "tw_futures", "id": "TXF", "market": "TW"},
            mode="data_only",
            output="evidence_only",
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="tw_futures",
            question_intent="general",
            effective_mode="data_only",
        )

        self.assertIn("volume", plan.requested_domains)
        self.assertIn("intraday", plan.requested_domains)
        self.assertIn("quote.snapshot", plan.selected_capabilities)
        self.assertIn("intraday.bars", plan.selected_capabilities)
        self.assertNotIn("market.volume_state", plan.selected_capabilities)
        self.assertEqual(plan.selection["unsupported_capabilities"], [])

    def test_requested_domain_augments_instead_of_replacing_default_capabilities(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={},
            output=None,
            realtime_policy=None,
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
            requested_domains=("intraday",),
        )

        self.assertIn("daily.ohlcv", selection["required"])
        self.assertIn("technical.structure", selection["required"])
        self.assertIn("intraday.bars", selection["required"])

    def test_diagnostic_selection_ignores_market_domains_and_forces_evidence_only(self) -> None:
        cases = (
            (
                "capability_status",
                "diagnostics.capabilities",
                ("chips", "technical"),
            ),
            (
                "data_freshness",
                "diagnostics.data_freshness",
                ("chips", "quote"),
            ),
            (
                "source_health",
                "diagnostics.source_health",
                ("fundamentals", "intraday"),
            ),
        )
        for scope_type, expected_capability, requested_domains in cases:
            with self.subTest(scope_type=scope_type):
                selection = capability_contract.normalize_selection(
                    selection={},
                    output="decision_with_evidence",
                    realtime_policy="prefer_live",
                    payload_level="compact",
                    scope_type=scope_type,
                    question_intent="general",
                    requested_domains=requested_domains,
                )

                self.assertEqual(selection["output"], "evidence_only")
                self.assertEqual(
                    selection["required"],
                    ["target.identity", expected_capability],
                )
                self.assertNotIn("data.freshness", selection["required"])
                self.assertFalse(
                    {
                        "chips.institutional",
                        "chips.margin",
                        "quote.snapshot",
                        "technical.structure",
                    }
                    & set(selection["required"])
                )

    def test_source_health_projection_reports_bounded_entry_counts(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["diagnostics.source_health"],
                "limits": {"diagnostics.source_health": 2},
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="source_health",
            question_intent="general",
        )
        response = {
            "target": {"type": "source_health"},
            "result": {
                "data": {
                    "filters": {"market": None, "limit": 200},
                    "summary": {"entry_count": 3, "problem_count": 2},
                    "entries": [
                        {
                            "market": "tw",
                            "provider": "provider-a",
                            "resource": "quote",
                            "status": "current",
                            "checked_at": "2026-07-24T10:00:00+08:00",
                        },
                        {
                            "market": "tw",
                            "provider": "provider-b",
                            "resource": "daily",
                            "status": "stale",
                            "checked_at": "2026-07-24T10:01:00+08:00",
                        },
                        {
                            "market": "us",
                            "provider": "provider-c",
                            "resource": "intraday",
                            "status": "empty",
                            "checked_at": "2026-07-24T10:02:00+08:00",
                        },
                    ],
                }
            },
        }

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        source_health = projected["diagnostics.source_health"]
        self.assertNotIn("diagnostics.source_health", unavailable)
        self.assertEqual(source_health["summary"]["entry_count"], 3)
        self.assertEqual(source_health["summary"]["returned_entry_count"], 2)
        self.assertEqual(source_health["summary"]["problem_count"], 2)
        self.assertEqual(
            source_health["summary"]["returned_problem_count"],
            2,
        )
        self.assertEqual(source_health["returned_count"], 2)
        self.assertEqual(len(source_health["entries"]), 2)
        self.assertTrue(source_health["truncated"])
        self.assertTrue(source_health["is_partial"])

    def test_projection_uses_real_compact_taiwan_field_names(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "quote.snapshot",
                    "chips.institutional",
                    "fundamentals.revenue",
                ],
                "fields": {
                    "quote.snapshot": ["latest_price", "quote_time"],
                    "chips.institutional": [
                        "trade_date",
                        "foreign_investor_net",
                    ],
                    "fundamentals.revenue": [
                        "latest_revenue",
                        "revenue_history",
                    ],
                },
                "limits": {"fundamentals.revenue": 1},
            },
            output="evidence_only",
            realtime_policy=None,
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        response = {
            "target": {"type": "tw_stock", "id": "2330"},
            "freshness": {"status": "current"},
            "result": {
                "data": {
                    "compact": {
                        "quote": {
                            "latest_price": 1_100,
                            "quote_time": "2026-07-24T09:01:00+08:00",
                            "raw": "omit",
                        },
                        "chips": {
                            "institutional": {
                                "trade_date": "2026-07-23",
                                "foreign_investor_net": 123,
                                "dealer_net": 999,
                            }
                        },
                        "fundamentals": {
                            "latest_revenue": {
                                "period": "2026-06-01",
                                "monthly_revenue": 100,
                            },
                            "revenue_history": [
                                {"period": "2026-05-01", "monthly_revenue": 90},
                                {"period": "2026-06-01", "monthly_revenue": 100},
                            ],
                        },
                    }
                }
            },
        }

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        self.assertEqual(unavailable, [])
        self.assertEqual(
            projected["quote.snapshot"],
            {
                "latest_price": 1_100,
                "quote_time": "2026-07-24T09:01:00+08:00",
            },
        )
        self.assertEqual(
            projected["chips.institutional"],
            {"trade_date": "2026-07-23", "foreign_investor_net": 123},
        )
        self.assertEqual(
            projected["fundamentals.revenue"]["revenue_history"],
            [{"period": "2026-06-01", "monthly_revenue": 100}],
        )

    def test_capability_catalog_is_consumer_neutral(self) -> None:
        catalog = capability_contract.capability_catalog(scope_type="stock")
        ids = {item["capability_id"] for item in catalog}

        self.assertIn("quote.snapshot", ids)
        self.assertIn("fundamentals.revenue", ids)
        self.assertFalse(
            any(
                token in item["capability_id"]
                for item in catalog
                for token in ("kuro", "voice", "desktop_pet")
            )
        )

    def test_crypto_order_book_projection_uses_bounded_provider_fields(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["crypto.order_book"],
                "limits": {"crypto.order_book": 1},
            },
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="crypto_asset",
            question_intent="quote",
        )
        response = {
            "target": {"type": "crypto_asset", "id": "BTC", "market": "CRYPTO"},
            "freshness": {"status": "current"},
            "result": {
                "data": {
                    "compact": {
                        "order_book": [
                            {
                                "provider": "okx",
                                "symbol": "BTC-USDT",
                                "best_bid_price": 99.0,
                                "best_ask_price": 100.0,
                            },
                            {
                                "provider": "binance",
                                "symbol": "BTC-USDT",
                                "best_bid_price": 100.0,
                                "best_ask_price": 101.0,
                                "event_time": "2026-07-24T01:00:00+00:00",
                                "fetched_at": "2026-07-24T01:00:01+00:00",
                            },
                        ]
                    }
                }
            },
        }

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        self.assertNotIn("crypto.order_book", unavailable)
        self.assertEqual(
            projected["crypto.order_book"],
            [
                {
                    "provider": "binance",
                    "symbol": "BTC-USDT",
                    "best_bid_price": 100.0,
                    "best_ask_price": 101.0,
                    "event_time": "2026-07-24T01:00:00+00:00",
                    "fetched_at": "2026-07-24T01:00:01+00:00",
                }
            ],
        )

    def test_market_freshness_and_source_health_project_from_result_payload(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "target.identity",
                    "data.freshness",
                    "source.health",
                ]
            },
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="market",
            question_intent="overview",
        )
        response = {
            "target": {"type": "market", "id": "TW", "market": "TW"},
            "result": {
                "as_of": "2026-07-27T13:30:00+08:00",
                "freshness": {
                    "is_current": False,
                    "missing": ["market_breadth.tpex"],
                    "warnings": ["TPEX breadth is partial."],
                },
                "data": {
                    "compact": {
                        "source_health": {
                            "status": "partial",
                            "as_of": "2026-07-27T05:30:00+00:00",
                            "summary": {
                                "entry_count": 4,
                                "ok_count": 3,
                                "stale_count": 1,
                            },
                            "warnings": [],
                        }
                    }
                },
            },
        }

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        self.assertEqual(unavailable, [])
        self.assertEqual(projected["data.freshness"]["status"], "missing")
        self.assertEqual(
            projected["data.freshness"]["as_of"],
            "2026-07-27T13:30:00+08:00",
        )
        self.assertEqual(projected["source.health"]["status"], "partial")
        self.assertEqual(
            projected["source.health"]["summary"]["stale_count"],
            1,
        )

    def test_tw_capability_plan_refreshes_only_selected_missing_dataset(self) -> None:
        plan, warnings = agentic_planning.plan_tw_stock_tools(
            question="補齊營收",
            stock_id="2330",
            target={"type": "tw_stock", "id": "2330"},
            gaps={
                "missing": [
                    "market_daily_price",
                    "monthly_revenue",
                    "financial_metric_quarterly",
                ],
                "refresh_recommended": True,
            },
            budget={
                "max_calls": 3,
                "max_external_fetches": 3,
                "max_total_seconds": 25,
            },
            can_call_llm=False,
            requested_capabilities=("fundamentals.revenue",),
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            [step["tool"] for step in plan["tool_plan"]],
            ["tw.refresh_revenue"],
        )
        self.assertEqual(
            plan["tool_plan"][0]["args"]["requested_capabilities"],
            ["fundamentals.revenue"],
        )

    def test_us_capability_plan_refreshes_only_selected_missing_dataset(self) -> None:
        plan, warnings = agentic_planning.plan_us_stock_tools(
            question="NVDA fundamentals",
            symbol="NVDA",
            target={"type": "us_stock", "id": "NVDA"},
            gaps={
                "missing": [
                    "us_daily_price",
                    "us_intraday_trend",
                    "us_sec_company_fact",
                ]
            },
            budget={
                "max_calls": 3,
                "max_external_fetches": 3,
                "max_total_seconds": 25,
            },
            can_call_llm=False,
            requested_capabilities=("fundamentals.financials",),
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            [step["tool"] for step in plan["tool_plan"]],
            ["us.refresh_sec_facts"],
        )
        self.assertEqual(
            plan["tool_plan"][0]["args"]["requested_capabilities"],
            ["fundamentals.financials"],
        )

    def test_us_capability_plan_merges_capabilities_for_shared_tool(self) -> None:
        plan, warnings = agentic_planning.plan_us_stock_tools(
            question="AAPL quote and intraday",
            symbol="AAPL",
            target={"type": "us_stock", "id": "AAPL"},
            gaps={"missing": ["us_intraday_trend"]},
            budget={
                "max_calls": 3,
                "max_external_fetches": 3,
                "max_total_seconds": 25,
            },
            can_call_llm=False,
            requested_capabilities=("quote.snapshot", "intraday.bars"),
        )

        self.assertEqual(warnings, [])
        self.assertEqual(len(plan["tool_plan"]), 1)
        self.assertEqual(
            plan["tool_plan"][0]["tool"],
            "us.read_intraday_trend",
        )
        self.assertEqual(
            plan["tool_plan"][0]["args"]["requested_capabilities"],
            ["quote.snapshot", "intraday.bars"],
        )

    def test_legacy_intraday_limit_maps_to_canonical_selection_limit(
        self,
    ) -> None:
        plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question="AAPL intraday",
                target={"type": "us_stock", "id": "AAPL"},
                selection={"include": ["intraday.bars"]},
                market_data_params={"intraday_limit": 30},
            ),
            scope_type="us_stock",
            question_intent="quote",
            effective_mode="brief",
        )

        self.assertEqual(plan.selection["limits"]["intraday.bars"], 30)

    def test_explicit_intraday_selection_limit_overrides_legacy_alias(
        self,
    ) -> None:
        plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question="AAPL intraday",
                target={"type": "us_stock", "id": "AAPL"},
                selection={
                    "include": ["intraday.bars"],
                    "limits": {"intraday.bars": 12},
                },
                market_data_params={"intraday_limit": 30},
            ),
            scope_type="us_stock",
            question_intent="quote",
            effective_mode="brief",
        )

        self.assertEqual(plan.selection["limits"]["intraday.bars"], 12)

    def test_crypto_capability_plan_is_target_provider_and_interval_bounded(self) -> None:
        plan, warnings = agentic_planning.plan_crypto_asset_tools(
            asset="BTC",
            target={"type": "crypto_asset", "id": "BTC"},
            requested_capabilities=("quote.snapshot", "daily.ohlcv"),
            selection={
                "limits": {
                    "quote.snapshot": 1,
                    "daily.ohlcv": 12,
                }
            },
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            [step["tool"] for step in plan["tool_plan"]],
            ["crypto.refresh_ticker", "crypto.refresh_ohlcv"],
        )
        for step in plan["tool_plan"]:
            self.assertEqual(step["args"]["provider"], "binance")
            self.assertEqual(step["args"]["symbol"], "BTC-USDT")
        self.assertEqual(plan["tool_plan"][1]["args"]["interval"], "1d")
        self.assertEqual(plan["tool_plan"][1]["args"]["limit"], 12)

    def test_crypto_tool_executes_one_provider_and_one_symbol(self) -> None:
        with patch.object(
            agentic_execution.crypto_market_service,
            "refresh_crypto_tickers",
            return_value={"status": "success", "refreshed_count": 1},
        ) as refresh:
            result = agentic_execution._execute_tool(
                db=object(),
                tool_name="crypto.refresh_ticker",
                args={"provider": "binance", "symbol": "BTC-USDT"},
            )

        self.assertEqual(result["refreshed_count"], 1)
        refresh.assert_called_once_with(
            db=ANY,
            providers=["binance"],
            symbols=["BTC-USDT"],
        )

    def test_continuation_revalidates_action_against_target_and_selection(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["fundamentals.revenue"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )
        target = {"type": "tw_stock", "id": "2330", "market": "TW"}
        action_id = capability_contract.fill_action_id(
            capability_id="fundamentals.revenue",
            target=target,
            selection_version=selection["version"],
        )
        plan_id = capability_contract.fill_plan_id(
            target=target,
            action_ids=[action_id],
        )

        selected = capability_contract.selected_fill_capabilities(
            continuation={
                "plan_id": plan_id,
                "plan_action_ids": [action_id],
                "selected_action_ids": [action_id],
            },
            selection=selection,
            target=target,
            scope_type="stock",
        )

        self.assertEqual(selected, ("fundamentals.revenue",))
        forged_action_id = "fill_forged"
        with self.assertRaisesRegex(ValueError, "unknown or non-executable"):
            capability_contract.selected_fill_capabilities(
                continuation={
                    "plan_id": capability_contract.fill_plan_id(
                        target=target,
                        action_ids=[forged_action_id],
                    ),
                    "plan_action_ids": [forged_action_id],
                    "selected_action_ids": [forged_action_id],
                },
                selection=selection,
                target=target,
                scope_type="stock",
            )


if __name__ == "__main__":
    unittest.main()
