from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from datetime import datetime, timezone

from app.ai import (
    agentic_planning,
    agentic_policy,
    ask_stages,
    capability_contract,
    capability_resolution_registry,
    decision_envelope_v4,
    pipeline_progress,
    tool_catalog,
)
from app.ai.market_context import capability_context
from app.ai.schemas import AiAskV4Request
from app.ai.schemas import AiAskRequest


class CapabilityResolutionRegistryTest(unittest.TestCase):
    def test_registry_covers_every_applicable_scope_once(self) -> None:
        expected: set[tuple[str, str]] = set()
        for spec in capability_contract.CAPABILITY_SPECS:
            scopes = (
                capability_resolution_registry.PUBLIC_SCOPE_TYPES
                if "*" in spec.scopes
                else spec.scopes
            )
            expected.update((scope, spec.capability_id) for scope in scopes)

        registry = capability_contract.CAPABILITY_RESOLUTION_REGISTRY
        self.assertEqual(set(registry), expected)
        self.assertEqual(len(registry), len(expected))
        self.assertEqual(len(capability_contract.CAPABILITY_SPECS), 68)

    def test_registry_entries_use_supported_statuses_and_modes(self) -> None:
        for entry in capability_contract.CAPABILITY_RESOLUTION_REGISTRY.values():
            self.assertIn(
                entry.implementation_status,
                capability_resolution_registry.IMPLEMENTATION_STATUSES,
            )
            self.assertIn(
                entry.resolution_mode,
                capability_resolution_registry.RESOLUTION_MODES,
            )
            self.assertGreater(dict(entry.bounds)["default_item_limit"], 0)
            if entry.operation is None:
                self.assertFalse(entry.backgroundable)
            else:
                self.assertIn(entry.capability_id, entry.produces)
                self.assertTrue(entry.backgroundable)

    def test_operation_allowlist_has_one_canonical_or_internal_owner(self) -> None:
        canonical_operations = {
            entry.operation
            for entry in capability_contract.CAPABILITY_RESOLUTION_REGISTRY.values()
            if entry.operation is not None
        }
        internal_operations = set(
            capability_resolution_registry.INTERNAL_ONLY_OPERATIONS
        )

        self.assertEqual(
            set(agentic_policy.ALLOWED_TOOLS),
            canonical_operations | internal_operations,
        )
        self.assertTrue(
            capability_contract.EXECUTABLE_FILL_OPERATIONS
            <= canonical_operations
        )
        self.assertEqual(
            canonical_operations
            - capability_contract.EXECUTABLE_FILL_OPERATIONS,
            {
                "cross_market.refresh_context",
                "tw.refresh_watchlist_evidence",
                "us.refresh_company_profile",
                "us.refresh_corporate_actions",
            },
        )

    def test_scope_specific_resolution_does_not_overstate_refreshability(
        self,
    ) -> None:
        resolution = capability_contract.capability_resolution_for

        self.assertEqual(
            resolution(
                scope_type="stock",
                capability_id="quote.snapshot",
            ).resolution_mode,
            "reader_fetch",
        )
        self.assertEqual(
            resolution(
                scope_type="us_stock",
                capability_id="quote.snapshot",
            ).operation,
            "us.refresh_quote",
        )
        self.assertEqual(
            resolution(
                scope_type="tw_futures",
                capability_id="quote.snapshot",
            ).resolution_mode,
            "cache_only",
        )
        self.assertEqual(
            resolution(
                scope_type="crypto_asset",
                capability_id="crypto.order_book",
            ).operation,
            "crypto.refresh_order_book",
        )
        self.assertEqual(
            resolution(
                scope_type="crypto_market",
                capability_id="crypto.order_book",
            ).resolution_mode,
            "cache_only",
        )

    def test_existing_composite_operations_have_canonical_scoped_owners(
        self,
    ) -> None:
        for capability_id in (
            "cross_market.overnight",
            "cross_market.relations",
            "cross_market.parity",
        ):
            entry = capability_contract.capability_resolution_for(
                scope_type="stock",
                capability_id=capability_id,
            )
            self.assertEqual(entry.resolution_mode, "composite_fill")
            self.assertEqual(entry.operation, "cross_market.refresh_context")
            self.assertEqual(
                entry.produces,
                capability_resolution_registry.COMPOSITE_OPERATION_PRODUCES[
                    "cross_market.refresh_context"
                ],
            )
            self.assertEqual(
                entry.side_effect_policy,
                "bounded_cache_write",
            )

        self.assertEqual(
            capability_contract.capability_resolution_for(
                scope_type="watchlist",
                capability_id="watchlist.ranking",
            ).operation,
            "tw.refresh_watchlist_evidence",
        )
        self.assertEqual(
            capability_contract.capability_resolution_for(
                scope_type="us_stock",
                capability_id="company.profile",
            ).operation,
            "us.refresh_company_profile",
        )
        self.assertEqual(
            capability_contract.capability_resolution_for(
                scope_type="us_stock",
                capability_id="corporate.actions",
            ).operation,
            "us.refresh_corporate_actions",
        )

    def test_private_key_required_scheduler_and_derived_modes_are_explicit(
        self,
    ) -> None:
        resolution = capability_contract.capability_resolution_for

        portfolio = resolution(
            scope_type="portfolio",
            capability_id="portfolio.holdings",
        )
        self.assertEqual(portfolio.implementation_status, "connected_private")
        self.assertEqual(portfolio.resolution_mode, "private")
        self.assertEqual(portfolio.trust_requirement, "server_trusted")

        macro = resolution(
            scope_type="us_macro",
            capability_id="macro.observations",
        )
        self.assertEqual(
            macro.implementation_status,
            "connected_key_required_for_refresh",
        )
        self.assertEqual(macro.resolution_mode, "key_required")
        self.assertIsNotNone(macro.blocking_reason)
        self.assertIsNotNone(macro.next_fill)

        scheduler = resolution(
            scope_type="market",
            capability_id="screening.intraday",
        )
        self.assertEqual(scheduler.resolution_mode, "scheduler_cache")
        self.assertEqual(
            scheduler.freshness_owner,
            "scheduler_and_cache",
        )

        derived = resolution(
            scope_type="stock",
            capability_id="technical.structure",
        )
        self.assertEqual(derived.resolution_mode, "derived")
        self.assertEqual(
            derived.depends_on,
            ("quote.snapshot", "daily.ohlcv", "intraday.bars"),
        )

    def test_deprecated_capabilities_have_replacements(self) -> None:
        deprecated = [
            entry
            for entry in capability_contract.CAPABILITY_RESOLUTION_REGISTRY.values()
            if entry.deprecated
        ]
        self.assertTrue(deprecated)
        for entry in deprecated:
            self.assertEqual(entry.implementation_status, "deprecated")
            self.assertEqual(entry.resolution_mode, "deprecated")
            self.assertTrue(entry.replacement_capabilities)

    def test_resolution_catalog_is_bounded_and_json_serializable(self) -> None:
        rows = capability_contract.capability_resolution_catalog(
            scope_type="stock",
            capability_id="quote.snapshot",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["scope_type"], "stock")
        self.assertEqual(rows[0]["capability_id"], "quote.snapshot")
        self.assertEqual(rows[0]["bounds"]["default_item_limit"], 5)
        json.dumps(rows, sort_keys=True)

    def test_capability_status_keeps_provider_and_full_registry_views_separate(
        self,
    ) -> None:
        result = capability_context.read_capability_status(
            now=datetime.now(timezone.utc)
        )

        self.assertEqual(result["summary"]["provider_contract_count"], 15)
        self.assertEqual(result["summary"]["registry_capability_count"], 68)
        self.assertEqual(result["summary"]["registry_resolution_count"], 218)
        self.assertEqual(len(result["data"]["provider_contracts"]), 15)
        self.assertEqual(len(result["data"]["capability_registry"]), 68)
        self.assertEqual(len(result["data"]["resolutions"]), 218)
        blocked_providers = {
            item["id"]: item
            for item in result["data"]["provider_contracts"]
            if item["status"] == "provider_not_connected"
        }
        self.assertEqual(
            set(blocked_providers),
            {
                "news_events",
                "us_options_flow_earnings",
                "jp_tdnet_disclosures",
                "kr_opendart_disclosures",
                "hk_market",
            },
        )
        for item in blocked_providers.values():
            self.assertTrue(item["blocking_reason"])
            self.assertTrue(item["next_fill"])

        scoped = capability_context.read_capability_status(
            market_data_params={"scope_type": "us_stock"},
            now=datetime.now(timezone.utc),
        )
        self.assertTrue(scoped["data"]["resolutions"])
        self.assertTrue(
            all(
                item["scope_type"] == "us_stock"
                for item in scoped["data"]["resolutions"]
            )
        )

    def test_continuation_runtime_and_public_schema_share_eight_action_limit(
        self,
    ) -> None:
        request_schema = AiAskV4Request.model_json_schema()
        continuation = request_schema["properties"]["continuation"]
        self.assertEqual(
            continuation["properties"]["selected_action_ids"]["maxItems"],
            8,
        )
        ask_tool = next(
            tool
            for tool in tool_catalog.list_ai_tools()["tools"]
            if tool["name"] == "omi.ask"
        )
        tool_continuation = ask_tool["input_schema"]["properties"][
            "continuation"
        ]
        self.assertEqual(
            tool_continuation["properties"]["selected_action_ids"][
                "maxItems"
            ],
            8,
        )

    def test_manifest_projects_scope_specific_resolution_metadata(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["company.profile"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="us_stock",
            question_intent="general",
        )
        target = {"type": "us_stock", "id": "AAPL", "market": "US"}
        manifest = capability_contract.build_manifest(
            canonical={
                "ok": True,
                "request_status": "completed",
                "target": target,
                "evidence": {
                    "freshness": {"status": "missing"},
                    "freshness_by_capability": {
                        "company.profile": {
                            "status": "missing",
                            "refresh_recommended": True,
                        }
                    },
                    "slots": {},
                },
            },
            selection=selection,
            projected_data={
                "target.identity": target,
                "data.freshness": {"status": "missing"},
            },
        )
        profile = next(
            item
            for item in manifest["capabilities"]
            if item["capability"] == "company.profile"
        )

        self.assertEqual(profile["implementation_status"], "connected")
        self.assertEqual(profile["resolution_mode"], "composite_fill")
        self.assertEqual(profile["fill_operation"], "us.refresh_company_profile")

    def test_fill_plan_exposes_composite_operations_and_signed_continuation(
        self,
    ) -> None:
        cases = (
            (
                "stock",
                "cross_market.relations",
                "cross_market.refresh_context",
                {"type": "tw_stock", "id": "2330", "market": "TW"},
            ),
            (
                "watchlist",
                "watchlist.ranking",
                "tw.refresh_watchlist_evidence",
                {"type": "watchlist", "id": "1", "market": "TW"},
            ),
            (
                "us_stock",
                "company.profile",
                "us.refresh_company_profile",
                {"type": "us_stock", "id": "AAPL", "market": "US"},
            ),
            (
                "us_stock",
                "corporate.actions",
                "us.refresh_corporate_actions",
                {"type": "us_stock", "id": "AAPL", "market": "US"},
            ),
        )
        for scope_type, capability_id, operation, target in cases:
            with self.subTest(scope_type=scope_type, capability=capability_id):
                selection = {
                    "version": "omi.capability.selection.v2",
                    "required": [capability_id],
                    "optional": [],
                }
                plan = capability_contract.build_fill_plan(
                    canonical={
                        "ok": True,
                        "request_status": "completed",
                        "target": target,
                    },
                    selection=selection,
                    manifest={
                        "capabilities": [
                            {
                                "capability": capability_id,
                                "status": "missing",
                                "status_class": "blocked",
                                "payload_included": False,
                                "refresh_recommended": True,
                                "quality_issues": [],
                            }
                        ]
                    },
                    scope_type=scope_type,
                )

                self.assertEqual(plan["action_count"], 1)
                self.assertEqual(plan["actions"][0]["operation"], operation)
                self.assertTrue(plan["actions"][0]["executable"])
                self.assertTrue(plan["partition"]["complete"])
                self.assertEqual(
                    plan["partition"]["selected_capabilities"],
                    [capability_id],
                )
                continuation = plan["actions"][0]["invoke"]["arguments"][
                    "continuation"
                ]
                self.assertEqual(
                    capability_contract.selected_fill_capabilities(
                        continuation=continuation,
                        selection=selection,
                        target=target,
                        scope_type=scope_type,
                    ),
                    (capability_id,),
                )

    def test_fill_partition_is_complete_and_pairwise_disjoint(self) -> None:
        selected = [
            "target.identity",
            "daily.ohlcv",
            "company.profile",
            "data.freshness",
        ]
        target = {"type": "us_stock", "id": "AAPL", "market": "US"}
        plan = capability_contract.build_fill_plan(
            canonical={
                "ok": True,
                "request_status": "completed",
                "target": target,
            },
            selection={
                "version": "omi.capability.selection.v2",
                "required": selected,
                "optional": [],
            },
            manifest={
                "capabilities": [
                    {
                        "capability": "target.identity",
                        "status": "ready",
                        "status_class": "ready",
                        "payload_included": True,
                    },
                    {
                        "capability": "daily.ohlcv",
                        "status": "current",
                        "status_class": "ready",
                        "payload_included": True,
                    },
                    {
                        "capability": "company.profile",
                        "status": "missing",
                        "status_class": "blocked",
                        "payload_included": False,
                        "refresh_recommended": True,
                    },
                    {
                        "capability": "data.freshness",
                        "status": "partial",
                        "status_class": "limited",
                        "payload_included": True,
                    },
                ]
            },
            scope_type="us_stock",
        )

        partition = plan["partition"]
        memberships: dict[str, list[str]] = {}
        for group_name in capability_contract.FILL_PARTITION_GROUPS:
            for capability_id in partition[group_name]:
                memberships.setdefault(capability_id, []).append(group_name)
        self.assertEqual(set(memberships), set(selected))
        self.assertTrue(all(len(groups) == 1 for groups in memberships.values()))
        self.assertEqual(memberships["daily.ohlcv"], ["already_satisfied"])
        self.assertEqual(memberships["company.profile"], ["actions"])
        self.assertEqual(memberships["target.identity"], ["not_applicable"])
        self.assertEqual(memberships["data.freshness"], ["not_applicable"])

    def test_every_registry_entry_has_exactly_one_fill_partition_resolution(
        self,
    ) -> None:
        for (scope_type, capability_id), resolution in (
            capability_contract.CAPABILITY_RESOLUTION_REGISTRY.items()
        ):
            with self.subTest(scope_type=scope_type, capability=capability_id):
                target = {
                    "type": scope_type,
                    "id": "TEST",
                    "market": "TW" if scope_type != "us_stock" else "US",
                }
                plan = capability_contract.build_fill_plan(
                    canonical={
                        "ok": True,
                        "request_status": "completed",
                        "target": target,
                    },
                    selection={
                        "version": "omi.capability.selection.v2",
                        "required": [capability_id],
                        "optional": [],
                    },
                    manifest={
                        "capabilities": [
                            {
                                "capability": capability_id,
                                "status": "missing",
                                "status_class": "blocked",
                                "payload_included": False,
                                "refresh_recommended": True,
                                "resolution_mode": resolution.resolution_mode,
                            }
                        ]
                    },
                    scope_type=scope_type,
                )
                memberships = [
                    group_name
                    for group_name in capability_contract.FILL_PARTITION_GROUPS
                    if capability_id in plan["partition"][group_name]
                ]
                self.assertEqual(len(memberships), 1)
                self.assertTrue(plan["partition"]["complete"])
                if resolution.operation is not None:
                    self.assertEqual(memberships, ["actions"])
                    self.assertEqual(
                        plan["actions"][0]["operation"],
                        resolution.operation,
                    )
                else:
                    self.assertNotEqual(memberships, ["actions"])

    def test_background_refresh_is_partitioned_as_job_not_duplicate_action(
        self,
    ) -> None:
        plan = capability_contract.build_fill_plan(
            canonical={
                "ok": True,
                "request_status": "completed",
                "target": {"type": "us_stock", "id": "AAPL", "market": "US"},
            },
            selection={
                "version": "omi.capability.selection.v2",
                "required": ["daily.ohlcv"],
                "optional": [],
            },
            manifest={
                "capabilities": [
                    {
                        "capability": "daily.ohlcv",
                        "status": "missing",
                        "status_class": "blocked",
                        "payload_included": False,
                        "refresh_recommended": True,
                    }
                ]
            },
            scope_type="us_stock",
            tool_runs=[
                {
                    "tool": "us.refresh_daily_price",
                    "status": "timeout",
                    "operation_status": "pending",
                    "evidence_status": "pending",
                    "arguments": {"requested_capabilities": ["daily.ohlcv"]},
                    "job": {
                        "job_id": 73,
                        "status": "running",
                        "deduplicated": False,
                        "poll_url": "/api/jobs/73",
                        "status_url": "/api/ai/refresh-status/73",
                    },
                }
            ],
        )

        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["partition"]["jobs"], ["daily.ohlcv"])
        self.assertEqual(plan["summary"]["job_count"], 1)
        self.assertEqual(plan["summary"]["unresolved_count"], 1)
        job = plan["jobs"][0]
        self.assertEqual(job["job_id"], 73)
        self.assertEqual(job["status_url"], "/api/ai/refresh-status/73")
        self.assertNotIn("poll_url", job)
        self.assertEqual(plan["resolutions"], [job])

        continuation = {"fill_plan": plan}
        decision_envelope_v4._compact_continuation(continuation)
        compact_plan = continuation["fill_plan"]
        self.assertEqual(compact_plan["jobs"][0]["job_id"], 73)
        self.assertEqual(
            compact_plan["jobs"][0]["status_url"],
            "/api/ai/refresh-status/73",
        )
        self.assertEqual(compact_plan["partition"]["jobs"], ["daily.ohlcv"])

    def test_selected_continuation_forces_only_registered_composite_tools(
        self,
    ) -> None:
        budget = {
            "max_calls": 3,
            "max_external_fetches": 3,
            "max_total_seconds": 25,
        }
        us_plan, _ = agentic_planning.plan_us_stock_tools(
            question="fill selected capabilities",
            symbol="AAPL",
            target={"type": "us_stock", "id": "AAPL"},
            gaps={"missing": []},
            budget=budget,
            can_call_llm=False,
            requested_capabilities=("company.profile", "corporate.actions"),
            force_selected_capabilities=True,
        )
        self.assertEqual(
            [step["tool"] for step in us_plan["tool_plan"]],
            ["us.refresh_company_profile", "us.refresh_corporate_actions"],
        )

        tw_plan, _ = agentic_planning.plan_tw_stock_tools(
            question="fill selected capability",
            stock_id="2330",
            target={"type": "tw_stock", "id": "2330"},
            gaps={"missing": []},
            overnight_gaps=None,
            budget=budget,
            can_call_llm=False,
            requested_capabilities=("cross_market.relations",),
            force_selected_capabilities=True,
        )
        self.assertEqual(
            [step["tool"] for step in tw_plan["tool_plan"]],
            ["cross_market.refresh_context"],
        )
        self.assertEqual(
            tw_plan["tool_plan"][0]["args"]["requested_capabilities"],
            ["cross_market.relations"],
        )

        watchlist_plan, _ = agentic_planning.plan_tw_watchlist_tools(
            group_id=1,
            gaps={"missing": [], "refresh_recommended": False},
            budget=budget,
            include_children=True,
            enabled_only=True,
            requested_capabilities=("watchlist.radar",),
            force_selected_capabilities=True,
        )
        self.assertEqual(
            [step["tool"] for step in watchlist_plan["tool_plan"]],
            ["tw.refresh_watchlist_evidence"],
        )
        self.assertEqual(
            watchlist_plan["tool_plan"][0]["args"][
                "requested_capabilities"
            ],
            ["watchlist.radar"],
        )

    def test_tool_stage_routes_signed_watchlist_continuation_when_fresh(
        self,
    ) -> None:
        target = {"type": "watchlist", "id": "1"}
        selection = capability_contract.normalize_selection(
            selection={"include": ["watchlist.radar"]},
            output="evidence_only",
            realtime_policy="prefer_live",
            payload_level="compact",
            scope_type="watchlist",
            question_intent="general",
        )
        action_id = capability_contract.fill_action_id(
            capability_id="watchlist.radar",
            target=target,
            selection_version=selection["version"],
        )
        captured: dict = {}

        def run_watchlist(**kwargs):
            captured.update(kwargs)
            return {
                "tool_plan": {"provider": "capability_registry"},
                "tool_runs": [],
                "warnings": [],
                "freshness": {
                    "is_current": True,
                    "refresh_recommended": False,
                },
            }

        ask_stages.execute_tool_stages(
            scope_type="watchlist",
            payload=AiAskRequest(
                question="fill selected watchlist capability",
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
            ),
            resolution=SimpleNamespace(selected_scope_id="1"),
            policy={"can_external_fetch": True},
            query_plan={
                "realtime_policy": "prefer_live",
                "external_refresh_allowed": True,
                "selected_capabilities": ["watchlist.radar"],
                "selection": selection,
            },
            freshness_result={
                "is_current": True,
                "refresh_recommended": False,
            },
            progress=pipeline_progress.OmiPipelineProgress(
                lambda event: None
            ),
            progress_callback=None,
            resolution_target=lambda resolution: target,
            require_scope_id=lambda request, scope_type: request.target["id"],
            require_group_id=lambda request: 1,
            refresh_before_answer_enabled=lambda request: True,
            run_us_stock_tool_session=lambda **kwargs: {},
            run_tw_stock_tool_session=lambda **kwargs: {},
            run_tw_watchlist_tool_session=run_watchlist,
        )

        self.assertEqual(
            captured["requested_capabilities"],
            ("watchlist.radar",),
        )
        self.assertTrue(captured["force_selected_capabilities"])


if __name__ == "__main__":
    unittest.main()
