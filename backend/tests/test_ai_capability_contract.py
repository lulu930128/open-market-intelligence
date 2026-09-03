from __future__ import annotations

import unittest
from unittest.mock import ANY, Mock, patch

from app.ai import (
    agentic_execution,
    agentic_planning,
    capability_contract,
    contract_manifest,
    data_quality_contract,
    decision_core,
    public_contract,
    query_plan,
)
from app.ai.market_context import taiwan_stock
from app.ai.schemas import AiAskRequest


class AiCapabilityContractTests(unittest.TestCase):
    def _quality_item(
        self,
        *,
        capability: str,
        payload: dict,
        returned_count: int = 1,
        requested_limit: int | None = None,
        canonical_available_count: int | None = None,
        truncated: bool = False,
        canonical_coverage_status: str | None = None,
        market: str = "US",
    ) -> dict:
        manifest_item = {
            "capability": capability,
            "domain": "technical" if capability == "technical.structure" else "price",
            "slot": capability.replace(".", "_"),
            "required": True,
            "status": "available",
            "returned_count": returned_count,
            "truncated": truncated,
        }
        if canonical_available_count is not None:
            manifest_item["canonical_available_count"] = canonical_available_count
        if canonical_coverage_status is not None:
            manifest_item["coverage_status"] = canonical_coverage_status
        if requested_limit is not None:
            manifest_item["requested_limit"] = requested_limit
            manifest_item["effective_limit"] = requested_limit
        quality = data_quality_contract.build_quality_contract(
            canonical={
                "ok": True,
                "request_status": "completed",
                "target": {
                    "type": "tw_stock" if market == "TW" else "us_stock",
                    "market": market,
                },
                "status": {"readiness": {"decision_required": True}},
                "evidence": {},
            },
            selection={"output": "decision_with_evidence"},
            manifest={"capabilities": [manifest_item]},
            projected_data={capability: payload},
            realtime_assessments={},
            scope_type="stock",
        )
        return quality["capabilities"][capability]

    def test_truncated_projection_does_not_demote_canonical_intraday_coverage(
        self,
    ) -> None:
        base_payload = {
            "status": "current",
            "freshness": {"status": "current"},
            "coverage_status": "complete",
            "trade_date": "2026-09-03",
            "point_count": 456,
            "volume_unit": "shares",
            "provider": "yahoo_chart",
            "source": "yahoo.chart.1m",
            "points": [
                {
                    "time": f"2026-09-03T14:{minute:02d}:00+00:00",
                    "price": 410.0 + minute,
                    "volume": 1000,
                }
                for minute in range(5)
            ],
            "quality": {
                "status": "current",
                "facts_usable": True,
                "decision_usable": True,
            },
        }

        full = self._quality_item(
            capability="intraday.bars",
            payload={
                **base_payload,
                "points": [
                    {
                        "time": f"2026-09-03T14:{minute:02d}:00+00:00",
                        "price": 410.0 + minute,
                        "volume": 1000,
                    }
                    for minute in range(20)
                ],
            },
            returned_count=20,
            requested_limit=20,
            canonical_available_count=456,
            canonical_coverage_status="complete",
        )
        truncated = self._quality_item(
            capability="intraday.bars",
            payload=base_payload,
            returned_count=5,
            requested_limit=20,
            canonical_available_count=456,
            truncated=True,
            canonical_coverage_status="complete",
        )

        self.assertEqual(full["canonical_dataset_coverage"], "complete")
        self.assertEqual(truncated["canonical_dataset_coverage"], "complete")
        self.assertEqual(full["consumer_projection_coverage"], "truncated")
        self.assertEqual(truncated["consumer_projection_coverage"], "truncated")
        self.assertEqual(full["freshness_status"], truncated["freshness_status"])
        self.assertEqual(full["decision_usable"], truncated["decision_usable"])
        self.assertNotIn("insufficient_history", truncated["issues"])

    def test_true_stale_intraday_is_not_upgraded_by_projection_coverage(self) -> None:
        item = self._quality_item(
            capability="intraday.bars",
            payload={
                "status": "stale",
                "freshness": {"status": "stale"},
                "coverage_status": "complete",
                "trade_date": "2026-09-02",
                "point_count": 456,
                "volume_unit": "shares",
                "provider": "yahoo_chart",
                "source": "yahoo.chart.1m",
                "points": [
                    {
                        "time": "2026-09-02T19:59:00+00:00",
                        "price": 121.0,
                        "volume": 1000,
                    }
                ],
                "quality": {
                    "status": "stale",
                    "facts_usable": True,
                    "decision_usable": False,
                },
            },
            returned_count=1,
            requested_limit=5,
            canonical_available_count=456,
            truncated=True,
            canonical_coverage_status="complete",
        )

        self.assertEqual(item["freshness_status"], "stale")
        self.assertEqual(item["canonical_dataset_coverage"], "complete")
        self.assertEqual(item["consumer_projection_coverage"], "truncated")
        self.assertFalse(item["decision_usable"])

    def test_current_session_intraday_blocks_cross_date_series(self) -> None:
        item = self._quality_item(
            capability="intraday.bars",
            market="TW",
            payload={
                "status": "current",
                "session_scope": "current_session",
                "expected_trade_date": "2026-09-03",
                "interval": "1m",
                "point_count": 4,
                "volume_unit": "shares",
                "provider": "fugle_marketdata",
                "source": "fugle.intraday.1m",
                "indices": [
                    {
                        "index_id": "TAIEX",
                        "points": [
                            {"time": "2026-09-03T09:00:00+08:00", "price": 102},
                            {"time": "2026-09-03T09:01:00+08:00", "price": 103},
                        ],
                    },
                    {
                        "index_id": "TPEX",
                        "points": [
                            {"time": "2026-09-02T13:30:00+08:00", "price": 100},
                            {"time": "2026-09-03T09:01:00+08:00", "price": 101},
                        ],
                    },
                ],
                "quality": {
                    "status": "current",
                    "facts_usable": True,
                    "decision_usable": True,
                },
            },
        )

        self.assertEqual(item["coverage_status"], "partial")
        self.assertEqual(item["current_session_identity"]["status"], "mismatch")
        self.assertEqual(
            item["current_session_identity"]["unexpected_trade_dates"],
            ["2026-09-02"],
        )
        self.assertIn(
            "CURRENT_SESSION_SERIES_DATE_MISMATCH",
            item["reason_codes"],
        )
        self.assertFalse(item["decision_usable"])
        self.assertFalse(item["intraday_research_usable"])

    def test_historical_intraday_allows_expected_cross_session_boundary(self) -> None:
        item = self._quality_item(
            capability="intraday.bars",
            market="TW",
            payload={
                "status": "current",
                "session_scope": "history",
                "interval": "1m",
                "point_count": 4,
                "volume_unit": "shares",
                "provider": "fugle_marketdata",
                "source": "fugle.intraday.1m",
                "points": [
                    {"time": "2026-09-02T13:29:00+08:00", "price": 100},
                    {"time": "2026-09-02T13:30:00+08:00", "price": 101},
                    {"time": "2026-09-03T09:00:00+08:00", "price": 102},
                    {"time": "2026-09-03T09:01:00+08:00", "price": 103},
                ],
                "quality": {
                    "status": "current",
                    "facts_usable": True,
                    "decision_usable": True,
                },
            },
        )

        self.assertEqual(
            item["current_session_identity"]["status"],
            "not_applicable",
        )
        self.assertNotIn(
            "CURRENT_SESSION_SERIES_DATE_MISMATCH",
            item["reason_codes"],
        )

    def test_current_session_identity_uses_pre_compaction_observed_dates(self) -> None:
        item = self._quality_item(
            capability="intraday.bars",
            market="TW",
            payload={
                "status": "current",
                "session_scope": "current_session",
                "expected_trade_date": "2026-09-03",
                "observed_trade_dates": ["2026-09-02", "2026-09-03"],
                "interval": "1m",
                "point_count": 2,
                "volume_unit": "shares",
                "provider": "fugle_marketdata",
                "source": "fugle.intraday.1m",
                "points": [
                    {"time": "2026-09-03T09:01:00+08:00", "price": 103},
                ],
                "quality": {
                    "status": "current",
                    "facts_usable": True,
                    "decision_usable": True,
                },
            },
            returned_count=1,
        )

        self.assertEqual(item["current_session_identity"]["status"], "mismatch")
        self.assertEqual(
            item["current_session_identity"]["unexpected_trade_dates"],
            ["2026-09-02"],
        )
        self.assertFalse(item["decision_usable"])

    def test_payload_semantic_missing_caps_generic_quality(self) -> None:
        item = self._quality_item(
            capability="technical.structure",
            payload={
                "status": "missing",
                "quality": {
                    "status": "missing",
                    "facts_usable": False,
                    "decision_usable": False,
                    "reason_codes": ["DAILY_OHLCV_MISSING"],
                },
                "limitations": ["CANONICAL_DAILY_OHLCV_UNAVAILABLE"],
            },
        )

        self.assertEqual(item["status"], "missing")
        self.assertEqual(item["status_class"], "blocked")
        self.assertEqual(item["availability_status"], "missing")
        self.assertEqual(item["usability_status"], "unusable")
        self.assertFalse(item["facts_usable"])
        self.assertFalse(item["decision_usable"])
        self.assertIn("DAILY_OHLCV_MISSING", item["reason_codes"])

    def test_cache_only_does_not_clear_daily_refresh_recommendation(self) -> None:
        item = self._quality_item(
            capability="daily.ohlcv",
            returned_count=0,
            requested_limit=20,
            payload={
                "status": "missing",
                "point_count": 0,
                "freshness": {
                    "status": "missing",
                    "refresh_recommended": True,
                    "refresh_allowed": False,
                    "refresh_requested": False,
                },
                "quality": {
                    "facts_usable": False,
                    "decision_usable": False,
                },
            },
        )

        self.assertEqual(item["freshness_status"], "missing")
        self.assertTrue(item["refresh_recommended"])
        self.assertFalse(item["refresh_allowed"])
        self.assertFalse(item["refresh_requested"])
        self.assertFalse(item["facts_usable"])
        self.assertFalse(item["decision_usable"])

    def test_stale_daily_can_keep_facts_but_not_decision_usability(self) -> None:
        item = self._quality_item(
            capability="daily.ohlcv",
            returned_count=2,
            requested_limit=2,
            payload={
                "status": "stale",
                "points": [
                    {"time": "2026-08-27", "close": 100},
                    {"time": "2026-08-28", "close": 101},
                ],
                "volume_unit": "shares",
                "quality": {
                    "status": "stale",
                    "facts_usable": True,
                    "decision_usable": False,
                },
            },
        )

        self.assertEqual(item["status"], "stale")
        self.assertEqual(item["status_class"], "limited")
        self.assertTrue(item["facts_usable"])
        self.assertFalse(item["decision_usable"])
        self.assertEqual(item["usability_status"], "limited")
        self.assertTrue(item["refresh_recommended"])

    def test_stale_daily_uses_typed_top_level_canonical_quality(self) -> None:
        item = self._quality_item(
            capability="daily.ohlcv",
            returned_count=2,
            requested_limit=2,
            payload={
                "status": "stale",
                "freshness_status": "stale",
                "expected_trade_date": "2026-08-28",
                "latest_trade_date": "2026-08-27",
                "points": [
                    {"time": "2026-08-26", "close": 100},
                    {"time": "2026-08-27", "close": 101},
                ],
                "volume_unit": "shares",
                "facts_usable": True,
                "decision_usable": False,
                "refresh_recommended": True,
                "selected_provider": "yahoo_chart",
                "selected_source": "yahoo.chart.1d",
            },
        )

        self.assertEqual(item["status"], "stale")
        self.assertEqual(item["status_class"], "limited")
        self.assertEqual(item["availability_status"], "available")
        self.assertEqual(item["freshness_status"], "stale")
        self.assertTrue(item["facts_usable"])
        self.assertFalse(item["decision_usable"])
        self.assertEqual(item["usability_status"], "limited")
        self.assertTrue(item["refresh_recommended"])
        self.assertEqual(item["selected_provider"], "yahoo_chart")
        self.assertEqual(item["selected_source"], "yahoo.chart.1d")

    def test_current_daily_still_requires_structural_quality_for_decision(self) -> None:
        item = self._quality_item(
            capability="daily.ohlcv",
            returned_count=2,
            requested_limit=2,
            payload={
                "status": "current",
                "points": [
                    {"time": "2026-08-27", "close": 100},
                    {"time": "2026-08-28", "close": 101},
                ],
                "volume_unit": "shares",
                "quality": {
                    "status": "current",
                    "facts_usable": True,
                    "decision_usable": True,
                },
            },
        )

        self.assertEqual(item["status"], "current")
        self.assertEqual(item["status_class"], "ready")
        self.assertTrue(item["facts_usable"])
        self.assertTrue(item["decision_usable"])
        self.assertFalse(item["refresh_recommended"])

    def test_session_close_unavailable_payload_fails_closed_across_status_axes(
        self,
    ) -> None:
        quality = data_quality_contract.build_quality_contract(
            canonical={
                "ok": True,
                "request_status": "completed",
                "target": {"type": "tw_stock", "market": "TW"},
                "status": {"readiness": {"decision_required": False}},
                "evidence": {},
            },
            selection={"output": "evidence_only"},
            manifest={
                "capabilities": [
                    {
                        "capability": "quote.session_close",
                        "domain": "quote",
                        "slot": "quote_session_close",
                        "required": True,
                        "status": "unavailable",
                        "returned_count": 1,
                    }
                ]
            },
            projected_data={
                "quote.session_close": {
                    "status": "unavailable",
                    "available": False,
                    "price": None,
                    "finalization": "unavailable",
                    "freshness": {
                        "status": "unavailable",
                        "is_current": False,
                    },
                    "facts_usable": False,
                    "research_usable": False,
                    "decision_usable": False,
                }
            },
            realtime_assessments={},
            scope_type="stock",
        )

        item = quality["capabilities"]["quote.session_close"]
        self.assertEqual(item["availability_status"], "unavailable")
        self.assertEqual(item["coverage_status"], "missing")
        self.assertEqual(item["release_status"], "not_released")
        self.assertEqual(item["usability_status"], "unusable")
        self.assertFalse(item["facts_usable"])
        self.assertFalse(item["decision_usable"])

    def test_tw_etf_fundamentals_gate_runs_before_readers(self) -> None:
        market_service = Mock()

        result = taiwan_stock._read_stock_fundamental_inputs(
            db=object(),
            stock_id="0050",
            revenue_months=12,
            financial_quarters=8,
            applicable=False,
            market_service=market_service,
        )

        self.assertEqual(
            result,
            {
                "latest_revenue": None,
                "latest_financial": None,
                "revenue_history": [],
                "financial_history": [],
            },
        )
        market_service.get_latest_stock_monthly_revenue.assert_not_called()
        market_service.get_latest_stock_financial_metric.assert_not_called()
        market_service.list_stock_monthly_revenue_history.assert_not_called()
        market_service.list_stock_financial_metric_history.assert_not_called()

    def test_stock_cross_market_capabilities_share_canonical_lineage(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "cross_market.overnight",
                    "cross_market.relations",
                    "cross_market.parity",
                ]
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            target_market="TW",
            question_intent="cross_market",
        )
        context = {
            "schema_version": "cross_market.context.v1",
            "status": "ready",
            "decision_usable": True,
            "as_of": "2026-08-08",
            "decision_at": "2026-08-09T01:00:00Z",
            "methodology_version": "cross_market.direct_parity.v1",
            "relation_snapshot_version": "relation_registry:42:v1",
            "snapshot_id": "cmctx:2330:test",
            "summary": {
                "stance": "supportive",
                "score": 3.5,
                "confidence": "high",
                "title": "ADR parity supportive",
                "reason_codes": ["direct_adr_parity"],
            },
            "signals": [
                {
                    "relation_id": 42,
                    "bucket": "direct_equivalent",
                    "status": "ready",
                    "decision_usable": True,
                }
            ],
            "coverage": {"coverage_ratio": 1.0},
            "warnings": [],
            "limitations": ["direct_equivalent_only_phase_2"],
        }
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
            "as_of": "2026-08-08",
            "stance": "risk_on",
            "context_status": "ready",
            "decision_usable": True,
            "summary": "ADR parity supportive",
            "signals": context["signals"],
            "coverage": context["coverage"],
            "methodology_version": context["methodology_version"],
            "relation_snapshot_version": context["relation_snapshot_version"],
            "snapshot_id": context["snapshot_id"],
            "limitations": context["limitations"],
            "source": "app.market.cross_market.context",
            "freshness": {"status": "current"},
            "warnings": [],
            "cross_market_context": context,
            "adr_parity": parity,
        }
        response = {
            "target": {"type": "tw_stock", "id": "2330", "market": "TW"},
            "freshness": {"status": "current", "is_current": True},
            "result": {"data": {"compact": {"cross_market": overnight}}},
        }

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        self.assertEqual(unavailable, [])
        self.assertEqual(
            projected["cross_market.overnight"]["snapshot_id"],
            "cmctx:2330:test",
        )
        self.assertEqual(
            projected["cross_market.relations"]["relation_snapshot_version"],
            "relation_registry:42:v1",
        )
        self.assertEqual(
            projected["cross_market.parity"]["mapping_resolution"]["relation_id"],
            42,
        )

    def test_market_sample_ranking_projects_sample_scope_and_units(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["market.sample_ranking"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="market",
            target_market="TW",
            question_intent="market_overview",
        )
        response = {
            "target": {"type": "market", "id": "TW", "market": "TW"},
            "result": {
                "data": {
                    "compact": {
                        "sample_ranking": {
                            "kind": "tw_market_sample_ranking",
                            "status": "partial",
                            "scope": "omi_local_daily_sample",
                            "scope_label": "OMI 台股本機日線樣本",
                            "is_full_market": False,
                            "coverage_status": "sample_only",
                            "as_of": "2026-07-31",
                            "latest_trade_date": "2026-07-31",
                            "source": "market_daily_price",
                            "currency": "TWD",
                            "price_unit": "TWD_per_share",
                            "volume_unit": "shares",
                            "trade_value_unit": "TWD",
                            "unit_semantics": {
                                "close_price": "TWD_per_share",
                                "trade_volume": "shares",
                                "trade_value": "TWD",
                            },
                            "sample_coverage": {
                                "status": "partial",
                                "sample_count": 84,
                                "universe_count": 1_973,
                            },
                            "value_leaders": [
                                {
                                    "stock_id": "2330",
                                    "close_price": 1_160.0,
                                    "trade_volume": 25_000_000,
                                    "trade_value": 29_000_000_000,
                                }
                            ],
                            "warnings": ["bounded local sample"],
                        }
                    }
                }
            },
        }

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        sample = projected["market.sample_ranking"]
        self.assertNotIn("market.sample_ranking", unavailable)
        self.assertEqual(sample["scope"], "omi_local_daily_sample")
        self.assertFalse(sample["is_full_market"])
        self.assertEqual(sample["coverage_status"], "sample_only")
        self.assertEqual(sample["volume_unit"], "shares")
        self.assertEqual(sample["trade_value_unit"], "TWD")
        self.assertFalse(
            data_quality_contract._unit_summary(sample)[
                "missing_volume_unit"
            ]
        )

    def test_registry_v2_manifest_is_metadata_complete_and_digest_stable(self) -> None:
        manifest = contract_manifest.public_contract_manifest()

        self.assertEqual(
            manifest["capability_registry_version"],
            "omi.capability.registry.v3",
        )
        self.assertEqual(
            manifest["selection_version"],
            "omi.capability.selection.v2",
        )
        self.assertEqual(
            manifest["targets"],
            public_contract.target_catalog(),
        )
        self.assertEqual(
            manifest["capabilities"],
            capability_contract.capability_catalog(),
        )
        self.assertEqual(
            manifest["capability_schema_versions"]["quote.snapshot"],
            "tw.quote.snapshot.v2",
        )
        self.assertEqual(
            manifest["digest"],
            contract_manifest.public_contract_manifest()["digest"],
        )
        self.assertEqual(len(manifest["digest"]), 64)
        self.assertTrue(
            all(
                {
                    "title",
                    "description",
                    "markets",
                    "parameter_schema",
                    "frequency",
                    "unit_semantics",
                    "event_time_basis",
                    "deprecated",
                    "replacement_capabilities",
                    "side_effect_policy",
                    "schema_version",
                }
                <= set(item)
                for item in manifest["capabilities"]
            )
        )

    def test_market_applicability_rejects_taiwan_capability_for_us_market(
        self,
    ) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["market.volume_state"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="market",
            target_market="US",
            question_intent="market_overview",
        )

        self.assertNotIn("market.volume_state", selection["required"])
        self.assertEqual(
            selection["unmet_required_capabilities"][0]["reason_code"],
            "unsupported_market",
        )
        self.assertEqual(
            selection["unmet_required_capabilities"][0]["supported_markets"],
            ["TW"],
        )

    def test_selection_parameters_require_registered_capability_schema(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "does not accept parameters",
        ):
            capability_contract.normalize_selection(
                selection={
                    "include": ["quote.snapshot"],
                    "parameters": {"quote.snapshot": {"unexpected": True}},
                },
                output="evidence_only",
                realtime_policy="cache_only",
                payload_level="compact",
                scope_type="stock",
                target_market="TW",
                question_intent="quote",
            )

    def test_tw_generic_quote_defaults_do_not_require_session_close(self) -> None:
        selection = capability_contract.normalize_selection(
            selection=None,
            output="decision_with_evidence",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            target_market="TW",
            question_intent="quote",
        )

        self.assertIn("quote.snapshot", selection["required"])
        self.assertNotIn("quote.session_close", selection["required"])

    def test_tw_explicit_close_question_requires_session_close(self) -> None:
        plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question="2330 今天收盤價是多少？",
                target={"type": "tw_stock", "id": "2330"},
            ),
            scope_type="stock",
            target_market="TW",
            question_intent="quote",
            effective_mode="brief",
        )

        self.assertIn("quote.session_close", plan.selection["required"])

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

    def test_quote_capabilities_publish_opening_handoff_fields(self) -> None:
        snapshot = capability_contract.CAPABILITIES["quote.snapshot"]
        auction = capability_contract.CAPABILITIES["quote.auction"]

        for field in (
            "presentation_trade_date",
            "presentation_session_state",
            "presentation_session_transition_at",
            "market_calendar_phase",
            "instrument_phase",
            "observation_reason_code",
            "observation_semantics",
            "actual_trade_occurred",
            "actual_trade_price_cached",
            "actual_trade_price_source",
            "actual_trade_price_as_of",
        ):
            self.assertIn(field, snapshot.fields)
            self.assertIn(field, snapshot.default_fields)

        for field in (
            "market_calendar_phase",
            "instrument_phase",
            "observation_reason_code",
        ):
            self.assertIn(field, auction.fields)
            self.assertIn(field, auction.default_fields)

    def test_volume_contract_fields_survive_capability_projection(self) -> None:
        intraday = capability_contract.CAPABILITIES["intraday.bars"]
        daily = capability_contract.CAPABILITIES["daily.ohlcv"]
        session_close = capability_contract.CAPABILITIES["quote.session_close"]

        for field in (
            "base_volume_unit",
            "quote_volume_unit",
            "volume_contracts",
            "volume_event_time",
            "volume_semantics",
            "volume_status",
            "bar_volume_sum_shares",
            "bar_volume_sum_lots",
            "bar_volume_trade_date",
            "bar_volume_latest_time",
            "bar_volume_scope",
            "closing_match_volume_shares",
            "closing_match_volume_lots",
            "closing_match_volume_source",
            "closing_match_volume_source_field",
            "closing_match_volume_event_time",
            "session_cumulative_volume_shares",
            "session_cumulative_volume_lots",
            "session_cumulative_volume_trade_date",
            "session_cumulative_volume_source",
            "session_cumulative_volume_source_field",
            "session_cumulative_volume_event_time",
            "session_cumulative_volume_status",
            "cumulative_volume_source",
            "cumulative_volume_status",
            "unallocated_volume_shares",
            "unallocated_volume_lots",
            "volume_reconciliation",
            "currency",
            "price_unit",
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
        for field in (
            "closing_match_volume_shares",
            "closing_match_volume_lots",
            "session_cumulative_volume_shares",
            "session_cumulative_volume_lots",
            "session_cumulative_volume_trade_date",
            "session_cumulative_volume_event_time",
            "volume_available",
            "volume_status",
            "volume_provider",
            "volume_source",
            "volume_event_time",
            "volume_scope",
            "volume_decision_usable",
        ):
            self.assertIn(field, session_close.fields)
            self.assertIn(field, session_close.default_fields)

    def test_order_book_contract_exposes_non_tradable_closing_snapshot_axes(self) -> None:
        order_book = capability_contract.CAPABILITIES["quote.order_book"]

        for field in (
            "live_available",
            "snapshot_available",
            "snapshot_status",
            "snapshot_semantics",
            "snapshot_trade_date",
            "snapshot_session",
            "snapshot_decision_usable",
        ):
            self.assertIn(field, order_book.fields)
            self.assertIn(field, order_book.default_fields)

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

    def test_intraday_series_promotes_canonical_unit_metadata(self) -> None:
        canonical = capability_contract._canonical_intraday_value(
            {
                "series": {
                    "1m": {
                        "interval": "1m",
                        "volume_unit": "shares",
                        "canonical_volume_unit": "shares",
                        "provider_volume_unit": "lots",
                        "volume_conversion": {
                            "from": "lots",
                            "to": "shares",
                            "multiplier": 1000,
                        },
                        "trade_value_unit": "TWD",
                        "bar_volume_sum_shares": 3_012_567,
                        "bar_volume_sum_lots": 3_012.567,
                        "bar_volume_trade_date": "2026-08-06",
                        "session_cumulative_volume_shares": 3_091_000,
                        "session_cumulative_volume_lots": 3_091,
                        "session_cumulative_volume_source": "twse_mis",
                        "session_cumulative_volume_status": "time_skew",
                        "cumulative_volume_shares": 3_091_000,
                        "cumulative_volume_source": "twse_mis",
                        "cumulative_volume_status": "time_skew",
                        "unallocated_volume_shares": 78_433,
                        "volume_reconciliation": {
                            "status": "time_skew",
                            "difference_shares": 78_433,
                        },
                        "points": [
                            {
                                "time": "2026-07-29T13:30:00+08:00",
                                "volume": 7_206_000,
                                "volume_shares": 7_206_000,
                                "volume_lots": 7_206.0,
                            }
                        ],
                    }
                }
            }
        )

        self.assertEqual(canonical["volume_unit"], "shares")
        self.assertEqual(canonical["canonical_volume_unit"], "shares")
        self.assertEqual(canonical["provider_volume_unit"], "lots")
        self.assertEqual(canonical["volume_conversion"]["multiplier"], 1000)
        self.assertEqual(canonical["trade_value_unit"], "TWD")
        self.assertEqual(canonical["bar_volume_sum_shares"], 3_012_567)
        self.assertEqual(canonical["session_cumulative_volume_shares"], 3_091_000)
        self.assertEqual(canonical["cumulative_volume_source"], "twse_mis")
        self.assertEqual(canonical["unallocated_volume_shares"], 78_433)
        self.assertEqual(canonical["volume_reconciliation"]["status"], "time_skew")

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

    def test_selection_traces_default_and_explicit_response_budgets(self) -> None:
        default_selection = capability_contract.normalize_selection(
            selection={"include": ["market.indices"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="market",
            target_market="TW",
            question_intent="market_overview",
        )

        self.assertIsNone(
            default_selection["requested_max_response_bytes"]
        )
        self.assertEqual(
            default_selection["default_max_response_bytes"],
            32_768,
        )
        self.assertEqual(
            default_selection["effective_max_response_bytes"],
            32_768,
        )
        self.assertEqual(
            default_selection["max_response_ceiling_bytes"],
            65_536,
        )
        self.assertEqual(
            default_selection["response_budget_source"],
            "payload_default_adaptive",
        )

        explicit_selection = capability_contract.normalize_selection(
            selection={
                "include": ["market.indices"],
                "max_response_bytes": 20_000,
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="market",
            target_market="TW",
            question_intent="market_overview",
        )

        self.assertEqual(
            explicit_selection["requested_max_response_bytes"],
            20_000,
        )
        self.assertEqual(
            explicit_selection["effective_max_response_bytes"],
            20_000,
        )
        self.assertEqual(
            explicit_selection["max_response_ceiling_bytes"],
            20_000,
        )
        self.assertEqual(
            explicit_selection["response_budget_source"],
            "caller_explicit",
        )

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

    def test_tw_screening_question_infers_typed_ranking_selection(self) -> None:
        payload = AiAskRequest(
            question="台股近五日外資買超排行前十名",
            contract_version="omi.decision.v4",
            target={"type": "market", "market": "TW"},
            mode="data_only",
            output="evidence_only",
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="market",
            question_intent="general",
            effective_mode="data_only",
            target_market="TW",
        )

        self.assertEqual(plan.capability_selection_mode, "inferred")
        self.assertEqual(
            set(plan.selected_capabilities),
            {
                "target.identity",
                "screening.ranking",
                "screening.coverage",
                "data.freshness",
            },
        )
        self.assertEqual(
            plan.selection["parameters"]["screening.ranking"],
            {
                "metric": "foreign_investor_net_shares",
                "window": 5,
                "sort_order": "desc",
                "limit": 10,
                "offset": 0,
            },
        )
        self.assertIn("screening", plan.requested_domains)
        self.assertNotIn("chips", plan.requested_domains)
        self.assertNotIn("sample_ranking", plan.requested_domains)
        self.assertEqual(plan.selection["unsupported_capabilities"], [])
        self.assertFalse(plan.external_refresh_allowed)

    def test_tw_screening_question_infers_metric_and_sort_direction(self) -> None:
        cases = (
            (
                "台股投信賣超排行前20名",
                "investment_trust_net_shares",
                "asc",
                20,
            ),
            (
                "台股近十日融資餘額減少排行前五名",
                "margin_balance_change_pct",
                "asc",
                5,
            ),
        )

        for question, metric, sort_order, limit in cases:
            with self.subTest(question=question):
                plan = query_plan.build_query_plan(
                    payload=AiAskRequest(
                        question=question,
                        contract_version="omi.decision.v4",
                        target={"type": "market", "market": "TW"},
                        mode="data_only",
                        output="evidence_only",
                    ),
                    scope_type="market",
                    question_intent="general",
                    effective_mode="data_only",
                    target_market="TW",
                )

                parameters = plan.selection["parameters"][
                    "screening.ranking"
                ]
                self.assertEqual(parameters["metric"], metric)
                self.assertEqual(parameters["sort_order"], sort_order)
                self.assertEqual(parameters["limit"], limit)

    def test_explicit_selection_overrides_tw_screening_question_inference(
        self,
    ) -> None:
        plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question="台股近五日外資買超排行前十名",
                contract_version="omi.decision.v4",
                target={"type": "market", "market": "TW"},
                mode="data_only",
                output="evidence_only",
                selection={"include": ["market.breadth"]},
            ),
            scope_type="market",
            question_intent="general",
            effective_mode="data_only",
            target_market="TW",
        )

        self.assertEqual(plan.capability_selection_mode, "explicit")
        self.assertIn("market.breadth", plan.selected_capabilities)
        self.assertNotIn("screening.ranking", plan.selected_capabilities)

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
            selection={"include": ["ownership.distribution"]},
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
                    "ownership.distribution": {
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
            {"tw.refresh_shareholding": ("intraday.bars",)},
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
        self.assertEqual(deferred["operation"], "tw.refresh_shareholding")
        self.assertEqual(deferred["produced_capabilities"], ["intraday.bars"])

    def test_non_ready_market_capabilities_receive_explicit_fill_resolution(
        self,
    ) -> None:
        selection = {
            "version": "omi.capability.selection.v2",
            "required": [
                "market.sectors",
                "market.sample_ranking",
                "market.hot_groups",
                "market.volume_state",
                "intraday.bars",
            ],
            "optional": [],
        }
        manifest = {
            "capabilities": [
                {
                    "capability": "market.sectors",
                    "status": "partial",
                    "status_class": "limited",
                    "payload_included": True,
                    "refresh_recommended": False,
                    "refresh_strategy": "derived",
                    "quality_issues": [],
                },
                {
                    "capability": "market.sample_ranking",
                    "status": "missing",
                    "status_class": "blocked",
                    "payload_included": False,
                    "refresh_recommended": False,
                    "refresh_strategy": "derived",
                    "quality_issues": ["volume_unit_missing"],
                },
                {
                    "capability": "market.hot_groups",
                    "status": "partial",
                    "status_class": "limited",
                    "payload_included": True,
                    "refresh_recommended": False,
                    "refresh_strategy": "scheduler_owned",
                    "quality_issues": [],
                },
                {
                    "capability": "market.volume_state",
                    "status": "partial",
                    "status_class": "limited",
                    "payload_included": True,
                    "refresh_recommended": False,
                    "refresh_strategy": "derived",
                    "quality_issues": [],
                },
                {
                    "capability": "intraday.bars",
                    "status": "stale",
                    "status_class": "blocked",
                    "payload_included": True,
                    "refresh_recommended": False,
                    "refresh_strategy": "reader_fetch",
                    "quality_issues": ["live_requirement_not_satisfied"],
                },
            ]
        }
        canonical = {
            "ok": True,
            "request_status": "completed",
            "target": {"type": "market", "id": "TW", "market": "TW"},
        }

        plan = capability_contract.build_fill_plan(
            canonical=canonical,
            selection=selection,
            manifest=manifest,
            scope_type="market",
        )

        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["summary"]["deferred_count"], 3)
        self.assertEqual(plan["summary"]["unfillable_count"], 1)
        self.assertEqual(plan["summary"]["already_attempted_count"], 1)
        reasons = {
            item["capability"]: item["reason"]
            for item in plan["resolutions"]
        }
        self.assertEqual(
            reasons["market.sectors"],
            "derived_rebuild_completed_with_quality_limits",
        )
        self.assertEqual(
            reasons["market.sample_ranking"],
            "contract_schema_fix_required",
        )
        self.assertEqual(
            reasons["market.hot_groups"],
            "scheduler_owned_current",
        )
        self.assertEqual(
            reasons["market.volume_state"],
            "history_accumulation_required",
        )
        self.assertEqual(
            reasons["intraday.bars"],
            "reader_fetch_on_primary_request",
        )

    def test_fill_plan_does_not_repeat_already_attempted_primary_reader(
        self,
    ) -> None:
        selection = {
            "version": "omi.capability.selection.v2",
            "required": ["intraday.bars"],
            "optional": [],
        }
        manifest = {
            "capabilities": [
                {
                    "capability": "intraday.bars",
                    "status": "missing",
                    "status_class": "blocked",
                    "payload_included": False,
                    "refresh_recommended": True,
                    "refresh_strategy": "reader_fetch",
                    "quality_issues": [],
                }
            ]
        }
        canonical = {
            "ok": True,
            "request_status": "completed",
            "target": {"type": "market", "id": "TW", "market": "TW"},
        }

        plan = capability_contract.build_fill_plan(
            canonical=canonical,
            selection=selection,
            manifest=manifest,
            scope_type="market",
            tool_runs=[
                {
                    "tool": "tw.read_market_overview",
                    "status": "error",
                    "operation_status": "failed",
                    "arguments": {
                        "requested_capabilities": [
                            "intraday.bars"
                        ]
                    },
                }
            ],
        )

        self.assertEqual(plan["actions"], [])
        attempted = plan["already_attempted_actions"][0]
        self.assertEqual(
            attempted["reason"],
            "already_attempted_primary_reader",
        )

    def test_reconciliation_exposes_primary_reader_and_final_quality(self) -> None:
        selection = {
            "version": "omi.capability.selection.v2",
            "required": ["intraday.bars"],
            "optional": [],
        }
        manifest = {
            "capabilities": [
                {
                    "capability": "intraday.bars",
                    "status": "stale",
                    "status_class": "blocked",
                    "payload_included": True,
                    "refresh_recommended": False,
                    "refresh_strategy": "reader_fetch",
                    "quality_issues": ["live_requirement_not_satisfied"],
                }
            ]
        }
        canonical = {
            "ok": True,
            "request_status": "completed",
            "target": {"type": "market", "id": "TW", "market": "TW"},
        }
        plan = capability_contract.build_fill_plan(
            canonical=canonical,
            selection=selection,
            manifest=manifest,
            scope_type="market",
        )

        reconciliation = capability_contract.build_refresh_reconciliation(
            selection=selection,
            manifest=manifest,
            fill_plan=plan,
            tool_runs=[],
            scope_type="market",
        )
        outcome = reconciliation["capabilities"]["intraday.bars"]
        self.assertTrue(outcome["primary_reader_attempted"])
        self.assertFalse(outcome["tool_run_attempted"])
        self.assertFalse(outcome["provider_fetch_attempted"])
        self.assertFalse(outcome["cache_hit"])
        self.assertEqual(
            outcome["not_attempted_reason"],
            "primary_reader_completed_without_tracked_provider_fetch",
        )
        self.assertTrue(reconciliation["primary_reader_attempted"])
        self.assertFalse(reconciliation["provider_fetch_attempted"])
        self.assertEqual(
            reconciliation["not_attempted_reason"],
            "primary_reader_completed_without_tracked_provider_fetch",
        )
        self.assertTrue(outcome["final_payload_present"])
        self.assertEqual(
            outcome["final_quality_issue"],
            ["live_requirement_not_satisfied"],
        )
        self.assertEqual(outcome["resolution_type"], "already_attempted")
        self.assertEqual(
            outcome["unresolved_reason"],
            "reader_fetch_on_primary_request",
        )

    def test_reconciliation_distinguishes_requested_refresh_from_policy_denial(self) -> None:
        selection = {
            "version": "omi.capability.selection.v2",
            "required": ["daily.ohlcv"],
            "optional": [],
            "realtime_policy": "prefer_live",
        }
        manifest = {
            "capabilities": [
                {
                    "capability": "daily.ohlcv",
                    "status": "missing",
                    "status_class": "blocked",
                    "payload_included": False,
                    "quality_issues": [],
                }
            ]
        }
        fill_plan = {
            "actions": [],
            "deferred_actions": [],
            "unfillable_actions": [],
            "already_attempted_actions": [],
        }

        reconciliation = capability_contract.build_refresh_reconciliation(
            selection=selection,
            manifest=manifest,
            fill_plan=fill_plan,
            tool_runs=[],
            scope_type="stock",
            request_policy={
                "allow_external_fetch": True,
                "can_external_fetch": False,
            },
        )

        self.assertTrue(reconciliation["refresh_requested"])
        self.assertFalse(reconciliation["refresh_allowed"])
        self.assertFalse(reconciliation["provider_fetch_attempted"])
        self.assertEqual(
            reconciliation["not_attempted_reason"],
            "refresh_policy_denied",
        )

    def test_tw_quote_and_intraday_use_reader_fetch_not_fill_operations(
        self,
    ) -> None:
        for capability_id in (
            "quote.snapshot",
            "quote.order_book",
            "quote.auction",
            "quote.official_close",
            "intraday.bars",
        ):
            spec = capability_contract.CAPABILITIES[capability_id]
            self.assertEqual(
                spec.refresh_strategy_for_scope("stock"),
                "reader_fetch",
            )
            self.assertIsNone(spec.fill_operation_for_scope("stock"))

        self.assertNotIn(
            "tw.refresh_quote",
            capability_contract.EXECUTABLE_FILL_OPERATIONS,
        )
        self.assertNotIn(
            "tw.refresh_intraday",
            capability_contract.EXECUTABLE_FILL_OPERATIONS,
        )
        self.assertLessEqual(
            capability_contract.EXECUTABLE_FILL_OPERATIONS,
            set(agentic_execution.ALLOWED_TOOLS),
        )

    def test_reconciliation_uses_operation_failure_not_transport_success(
        self,
    ) -> None:
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
            "target": {"type": "tw_stock", "id": "8299", "market": "TW"},
            "evidence": {
                "freshness_by_capability": {
                    "ownership.distribution": {
                        "status": "empty",
                        "refresh_recommended": True,
                    }
                },
                "slots": {},
            },
        }
        manifest = capability_contract.build_manifest(
            canonical=canonical,
            selection=selection,
            projected_data={
                "target.identity": canonical["target"],
                "data.freshness": {"status": "missing"},
            },
        )
        fill_plan = capability_contract.build_fill_plan(
            canonical=canonical,
            selection=selection,
            manifest=manifest,
            scope_type="stock",
        )
        reconciliation = capability_contract.build_refresh_reconciliation(
            selection=selection,
            manifest=manifest,
            fill_plan=fill_plan,
            tool_runs=[
                {
                    "tool": "tw.refresh_shareholding",
                    "status": "success",
                    "transport_status": "success",
                    "operation_status": "failed",
                    "evidence_status": "unavailable",
                    "result_status": "error",
                    "arguments": {
                        "stock_id": "8299",
                        "requested_capabilities": [
                            "ownership.distribution"
                        ],
                    },
                    "result_summary": {
                        "status": "error",
                        "refresh_outcome": "failed",
                        "error_message": "TDCC timed out",
                    },
                }
            ],
            scope_type="stock",
        )

        attempt = reconciliation["attempts"][0]
        outcome = reconciliation["capabilities"]["ownership.distribution"]
        self.assertEqual(attempt["transport_status"], "success")
        self.assertEqual(attempt["operation_status"], "failed")
        self.assertFalse(outcome["tool_succeeded"])
        self.assertEqual(outcome["reconciliation"], "attempt_failed_or_blocked")
        self.assertIsNotNone(outcome["remaining_fill_action"])
        self.assertEqual(
            outcome["remaining_fill_action_detail"]["operation"],
            "tw.refresh_shareholding",
        )

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

    def test_daily_points_selection_adds_semantic_companion_fields(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["daily.ohlcv"],
                "fields": {
                    "daily.ohlcv": ["points", "volume_unit"],
                },
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            question_intent="general",
        )

        self.assertEqual(
            selection["fields"]["daily.ohlcv"],
            [
                "points",
                "volume_unit",
                "trade_value_unit",
                "currency",
            ],
        )
        self.assertEqual(
            capability_contract.normalize_selection(
                selection={"include": ["daily.ohlcv"]},
                output="evidence_only",
                realtime_policy="cache_only",
                payload_level="compact",
                scope_type="stock",
                question_intent="general",
            )["fields"],
            {},
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
                    "target_market": "TW",
                    "supported_scopes": [
                        "market",
                        "tw_index",
                        "tw_futures",
                        "us_stock",
                        "jp_index",
                        "kr_index",
                        "crypto_market",
                    ],
                    "supported_markets": ["TW"],
                    "message": (
                        "market.breadth is not supported for target "
                        "scope=stock, market=TW."
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
        self.assertIn("read_taiwan_quote_evidence", plan.required_readers)
        self.assertIn("read_taiwan_bars", plan.required_readers)

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
        self.assertEqual(len(source_health["problems_preview"]), 2)
        self.assertTrue(
            all(
                entry["status"] in {"stale", "empty"}
                for entry in source_health["problems_preview"]
            )
        )
        self.assertTrue(source_health["truncated"])
        self.assertTrue(source_health["is_partial"])

    def test_source_health_summary_projection_keeps_problem_preview(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["diagnostics.source_health"],
                "fields": {"diagnostics.source_health": ["summary"]},
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="summary",
            scope_type="source_health",
            question_intent="general",
        )
        response = {
            "target": {"type": "source_health"},
            "result": {
                "data": {
                    "summary": {"entry_count": 2, "problem_count": 1},
                    "entries": [
                        {"resource": "quote", "status": "current"},
                        {"resource": "daily", "status": "stale"},
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
        self.assertEqual(source_health["summary"]["problem_count"], 1)
        self.assertEqual(source_health["summary"]["returned_problem_count"], 0)
        self.assertEqual(
            source_health["problems_preview"],
            [{"resource": "daily", "status": "stale"}],
        )

    def test_bounded_projection_preserves_nested_health_slot_evidence(self) -> None:
        payload = {
            "health_dimensions": {
                "scheduler_contract": {
                    "slot_coverage": {
                        "2026-08-28": {
                            "missing_symbol_slots": {
                                "3711": ["08:30", "08:35"]
                            }
                        }
                    }
                }
            }
        }

        projected = capability_contract._bounded_value(payload, limit=20)

        self.assertEqual(
            projected["health_dimensions"]["scheduler_contract"]
            ["slot_coverage"]["2026-08-28"]["missing_symbol_slots"]["3711"],
            ["08:30", "08:35"],
        )

    def test_projection_uses_real_compact_taiwan_field_names(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": [
                    "quote.snapshot",
                    "chips.institutional",
                    "fundamentals.revenue",
                    "fundamentals.financials",
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
                    "fundamentals.financials": [
                        "financial_contract",
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
                            "financial_contract": {
                                "contract_version": "omi.financial.v1",
                                "normalized": {"status": "ready"},
                                "derived": {
                                    "ttm_eps_status": "ready",
                                    "ttm_eps": "12.72",
                                },
                                "valuation": {"status": "unavailable"},
                                "quality": {
                                    "semantic_validity": "valid",
                                    "decision_usable": True,
                                    "issues": [],
                                },
                            },
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
        self.assertEqual(
            projected["fundamentals.financials"]["financial_contract"][
                "contract_version"
            ],
            "omi.financial.v1",
        )
        self.assertEqual(
            projected["fundamentals.financials"]["financial_contract"][
                "derived"
            ]["ttm_eps"],
            "12.72",
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
        self.assertEqual(
            selection["required"],
            [
                "target.identity",
                "data.freshness",
                "diagnostics.source_health",
            ],
        )
        self.assertEqual(
            selection["deprecated_aliases"],
            [
                {
                    "alias": "source.health",
                    "canonical_capability": "diagnostics.source_health",
                    "status": "deprecated_alias",
                }
            ],
        )
        self.assertEqual(projected["data.freshness"]["status"], "missing")
        self.assertEqual(
            projected["data.freshness"]["as_of"],
            "2026-07-27T13:30:00+08:00",
        )
        self.assertEqual(
            projected["diagnostics.source_health"]["status"],
            "partial",
        )
        self.assertEqual(
            projected["diagnostics.source_health"]["summary"]["stale_count"],
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

    def test_us_capability_plan_keeps_quote_and_intraday_fill_owners_separate(self) -> None:
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
        self.assertEqual(len(plan["tool_plan"]), 2)
        self.assertEqual(
            [step["tool"] for step in plan["tool_plan"]],
            ["us.refresh_quote", "us.refresh_intraday_bars"],
        )
        self.assertEqual(
            [step["args"]["requested_capabilities"] for step in plan["tool_plan"]],
            [["quote.snapshot"], ["intraday.bars"]],
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

    def test_tw_explicit_daily_selection_uses_bounded_daily_reader(self) -> None:
        plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question="只讀 3711 最近 20 根正式日 K",
                target={"type": "tw_stock", "id": "3711"},
                mode="data_only",
                selection={
                    "include": [
                        "target.identity",
                        "daily.ohlcv",
                        "data.freshness",
                    ],
                    "limits": {"daily.ohlcv": 20},
                },
            ),
            scope_type="stock",
            target_market="TW",
            question_intent="general",
            effective_mode="data_only",
        )

        self.assertEqual(plan.reader_profile, "daily_only")
        self.assertEqual(
            plan.required_readers,
            ("get_stock", "list_stock_ohlc_chart_data"),
        )
        self.assertFalse(plan.external_refresh_allowed)
        self.assertIn("read_fundamentals", plan.excluded_readers)
        self.assertIn("read_taiwan_source_health", plan.excluded_readers)
        self.assertEqual(plan.selection["limits"]["daily.ohlcv"], 20)

    def test_tw_explicit_technical_selection_uses_only_technical_dependencies(
        self,
    ) -> None:
        plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question="只讀 3711 最近 60 根日 K 與技術結構",
                target={"type": "tw_stock", "id": "3711"},
                mode="data_only",
                output="evidence_only",
                selection={
                    "include": [
                        "target.identity",
                        "daily.ohlcv",
                        "technical.structure",
                        "technical.indicators",
                        "data.freshness",
                    ],
                    "limits": {"daily.ohlcv": 60},
                },
            ),
            scope_type="stock",
            target_market="TW",
            question_intent="trend_view",
            effective_mode="data_only",
        )

        self.assertEqual(plan.reader_profile, "technical_only")
        self.assertEqual(
            plan.required_readers,
            (
                "get_stock",
                "list_stock_ohlc_chart_data",
                "build_stock_technical_report",
                "build_tw_stock_technical_evidence",
            ),
        )
        self.assertIn("read_fundamentals", plan.excluded_readers)
        self.assertIn("read_cross_market_context", plan.excluded_readers)
        self.assertIn("get_broker_branch_trade_summary", plan.excluded_readers)
        self.assertFalse(plan.external_refresh_allowed)

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

    def test_us_fundamental_tool_returns_versioned_contract_and_legacy_summary(self) -> None:
        contract = {
            "contract_version": "omi.financial.v1",
            "quality": {"decision_usable": True},
        }
        summary = {"symbol": "AAPL", "metric_count": 7}
        with (
            patch.object(
                agentic_execution.us_market_service,
                "get_us_sec_financial_contract",
                return_value=contract,
            ) as read_contract,
            patch.object(
                agentic_execution.us_market_service,
                "get_us_sec_fundamental_summary",
                return_value=summary,
            ) as read_summary,
        ):
            result = agentic_execution._execute_tool(
                db=object(),
                tool_name="us.read_sec_fundamentals",
                args={"symbol": "AAPL"},
            )

        self.assertEqual(result["financial_contract"]["contract_version"], "omi.financial.v1")
        self.assertEqual(result["sec_fundamentals"]["metric_count"], 7)
        read_contract.assert_called_once_with(db=ANY, symbol="AAPL", periods=8)
        read_summary.assert_called_once_with(db=ANY, symbol="AAPL")

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

    def test_explicit_selection_locks_required_capabilities_and_traces_origins(
        self,
    ) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["market.indices"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="market",
            target_market="TW",
            question_intent="market_overview",
            requested_capabilities=(
                "market.sectors",
                "chips.institutional",
            ),
        )

        self.assertEqual(
            selection["required"],
            ["target.identity", "market.indices", "data.freshness"],
        )
        self.assertEqual(selection["optional"], [])
        self.assertEqual(
            selection["inference_policy"],
            "explicit_selection_locked",
        )
        self.assertEqual(
            selection["capability_origins"]["market.indices"],
            {
                "origin": "explicit_required",
                "requested_as": "required",
            },
        )
        self.assertEqual(selection["unmet_required_capabilities"], [])
        self.assertEqual(selection["unsupported_capabilities"], [])

    def test_explicit_selection_survives_nlp_negation_of_same_domain(self) -> None:
        payload = AiAskRequest(
            question="請提供台積電最近交易日盤中資料，但不要把週六描述成盤中。",
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
            selection={"include": ["intraday.bars"]},
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="quote",
            effective_mode="data_only",
            target_market="TW",
        )

        self.assertIn("intraday.bars", plan.selection["required"])
        self.assertNotIn("intraday.bars", plan.selection["excluded"])
        self.assertEqual(
            plan.selection["inference_policy"],
            "explicit_selection_locked",
        )

    def test_explicit_intraday_selection_uses_focused_reader_for_general_intent(
        self,
    ) -> None:
        payload = AiAskRequest(
            question="讀取這檔股票指定的盤中證據。",
            contract_version="omi.decision.v4",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
            selection={"include": ["intraday.bars"]},
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="general",
            effective_mode="data_only",
            target_market="TW",
        )

        self.assertEqual(plan.reader_profile, "quote_only")
        self.assertIn("read_taiwan_bars", plan.required_readers)
        self.assertIn("build_stock_technical_report", plan.excluded_readers)
        self.assertIn("get_broker_branch_trade_summary", plan.excluded_readers)

    def test_natural_regulation_question_uses_event_only_capabilities(self) -> None:
        question = "2330 是否為處置股？請說明撮合間隔與交易限制。"
        intent = decision_core.infer_question_intent(question)
        plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question=question,
                contract_version="omi.decision.v4",
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
                output="evidence_only",
            ),
            scope_type="stock",
            question_intent=intent,
            effective_mode="data_only",
            target_market="TW",
        )

        self.assertEqual(intent, "regulation")
        self.assertEqual(plan.reader_profile, "event_only")
        self.assertEqual(
            set(plan.selected_capabilities),
            {
                "target.identity",
                "regulation.disposition",
                "regulation.trading_restrictions",
                "data.freshness",
            },
        )

    def test_natural_official_close_question_uses_quote_only_path(self) -> None:
        question = "2330 最近交易日的正式收盤價是多少？"
        intent = decision_core.infer_question_intent(question)
        plan = query_plan.build_query_plan(
            payload=AiAskRequest(
                question=question,
                contract_version="omi.decision.v4",
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
                output="evidence_only",
            ),
            scope_type="stock",
            question_intent=intent,
            effective_mode="data_only",
            target_market="TW",
        )

        self.assertEqual(intent, "quote")
        self.assertEqual(plan.reader_profile, "quote_only")
        self.assertIn("quote.official_close", plan.selected_capabilities)
        self.assertNotIn("daily.ohlcv", plan.selected_capabilities)
        self.assertNotIn("technical.structure", plan.selected_capabilities)

    def test_watchlist_radar_v2_engine_and_readiness_are_public(self) -> None:
        selection = capability_contract.normalize_selection(
            selection={"include": ["watchlist.radar"]},
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="watchlist",
            target_market="TW",
            question_intent="general",
        )
        response = {
            "target": {"type": "tw_watchlist", "id": 1, "market": "TW"},
            "result": {
                "freshness": {
                    "status": "latest_completed_session",
                    "is_current": True,
                },
                "data": {
                    "compact": {
                        "radar": {
                            "mode": "action",
                            "radar_count": 1,
                            "cache_status": "computed",
                            "radar_engine": {
                                "active_version": "radar_v2.0-active",
                                "mode": "active",
                                "technical_direction_owner": "backend",
                            },
                            "radar_v2_summary": {
                                "evaluated_count": 1,
                                "universe_evaluated_count": 20,
                                "universe_scope": "complete_calculation_universe",
                                "readiness": {
                                    "operational_status": "active",
                                    "validation_status": "unverified",
                                    "limitations": [
                                        {
                                            "code": "walk_forward_incremental_value_not_verified"
                                        }
                                    ],
                                },
                            },
                            "results": [
                                {
                                    "stock_id": "2330",
                                    "radar_v2": {
                                        "rule_version": "radar_v2.0-active"
                                    },
                                }
                            ],
                        }
                    }
                }
            },
        }

        projected, unavailable = capability_contract.project_selected_data(
            response=response,
            selection=selection,
        )

        self.assertEqual(unavailable, [])
        radar = projected["watchlist.radar"]
        self.assertEqual(
            radar["radar_engine"]["active_version"],
            "radar_v2.0-active",
        )
        self.assertEqual(
            radar["radar_v2_summary"]["readiness"]["operational_status"],
            "active",
        )
        self.assertEqual(
            radar["radar_v2_summary"]["universe_evaluated_count"],
            20,
        )

    def test_manifest_distinguishes_requested_and_effective_limits(
        self,
    ) -> None:
        selection = capability_contract.normalize_selection(
            selection={
                "include": ["daily.ohlcv"],
                "limits": {"daily.ohlcv": 700},
            },
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            scope_type="stock",
            target_market="TW",
            question_intent="general",
        )
        projected = {
            "daily.ohlcv": {
                "points": [{"close": index} for index in range(500)],
                "returned_point_count": 500,
                "truncated": True,
            }
        }
        manifest = capability_contract.build_manifest(
            canonical={
                "ok": True,
                "request_status": "completed",
                "target": {
                    "type": "tw_stock",
                    "id": "2330",
                    "market": "TW",
                },
                "evidence": {},
            },
            selection=selection,
            projected_data=projected,
        )
        daily = next(
            item
            for item in manifest["capabilities"]
            if item["capability"] == "daily.ohlcv"
        )

        self.assertEqual(daily["default_limit"], 30)
        self.assertEqual(daily["maximum_limit"], 500)
        self.assertEqual(daily["requested_limit"], 700)
        self.assertEqual(daily["effective_limit"], 500)
        self.assertEqual(daily["returned_count"], 500)
        self.assertTrue(daily["truncated"])


if __name__ == "__main__":
    unittest.main()
