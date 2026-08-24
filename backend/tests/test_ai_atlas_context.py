from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import capability_contract, capability_resolution_registry, query_plan
from app.ai.market_context import atlas_context, capability_context
from app.ai.schemas import AiAskRequest
from app.config import settings
from app.db.models import Base, StockMaster


NOW = datetime(2026, 8, 23, 4, 0, tzinfo=timezone.utc)


class _Response:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


class AtlasContextTests(unittest.TestCase):
    def _settings(self, **updates: object) -> ExitStack:
        stack = ExitStack()
        for name, value in updates.items():
            stack.enter_context(patch.object(settings, name, value))
        return stack

    def test_auto_selection_is_optional_and_respects_explicit_callers(self) -> None:
        with self._settings(omi_atlas_shadow_enabled=True):
            planned = atlas_context.selection_with_atlas_shadow(
                {},
                scope_type="stock",
            )
            self.assertTrue(planned["auto_planning"])
            self.assertEqual(planned["optional"], ["news.events"])

            explicit = {"required": ["quote.snapshot"]}
            self.assertEqual(
                atlas_context.selection_with_atlas_shadow(
                    explicit,
                    scope_type="stock",
                ),
                explicit,
            )
            excluded = {"exclude": ["news.events"]}
            self.assertEqual(
                atlas_context.selection_with_atlas_shadow(
                    excluded,
                    scope_type="stock",
                ),
                excluded,
            )
            unsupported = atlas_context.selection_with_atlas_shadow(
                {},
                scope_type="crypto_asset",
            )
            self.assertEqual(unsupported, {})

    def test_query_plan_keeps_atlas_supplemental(self) -> None:
        with self._settings(omi_atlas_shadow_enabled=True):
            payload = AiAskRequest(
                contract_version="omi.decision.v4",
                question="2330 現在有哪些需要注意的情報？",
                target={"type": "stock", "id": "2330", "market": "TW"},
                output="evidence_only",
            )
            payload = payload.model_copy(
                update={
                    "selection": atlas_context.selection_with_atlas_shadow(
                        payload.selection,
                        scope_type="stock",
                    )
                }
            )
            plan = query_plan.build_query_plan(
                payload=payload,
                scope_type="stock",
                target_market="TW",
                question_intent="analysis",
                effective_mode="data_only",
            )

        self.assertIn("news.events", plan.optional_selected_capabilities)
        self.assertNotIn("news.events", plan.selected_capabilities)

    def test_successful_read_is_bounded_and_drops_document_body(self) -> None:
        payload = {
            "contract_version": "1.1",
            "profile": "evidence_pack_v1",
            "generated_at": "2026-08-23T03:59:00Z",
            "data": {
                "event_count": 2,
                "events": [
                    {
                        "id": "evt-1",
                        "title": "TSMC event",
                        "summary": "bounded summary",
                        "event_type": "company_update",
                        "primary_domain": "technology",
                        "confidence": 0.9,
                        "evidence_count": 3,
                        "independent_source_count": 2,
                        "has_primary_source": True,
                        "evidence": [
                            {
                                "id": f"doc-{index}",
                                "source_name": "Official source",
                                "canonical_url": (
                                    "javascript:alert(1)"
                                    if index == 1
                                    else f"https://example.test/{index}"
                                ),
                                "title": f"Document {index}",
                                "summary": "document summary",
                                "body_excerpt": "must not cross the OMI boundary",
                            }
                            for index in range(3)
                        ],
                    },
                    {"id": "evt-2", "title": "second event"},
                ],
            },
            "freshness": {"status": "current", "oldest_observed_at": "2026-08-23T03:00:00Z"},
            "coverage": {"domain": "technology", "source_count": 4},
            "warnings": ["provider coverage is bounded"],
        }
        get = Mock(return_value=_Response(payload))
        with self._settings(
            omi_atlas_shadow_enabled=True,
            omi_atlas_api_base_url="http://127.0.0.1:8790",
            omi_atlas_max_events=1,
            omi_atlas_max_evidence_per_event=2,
            omi_atlas_lookback_hours=168,
            omi_atlas_timeout_seconds=1.5,
        ), patch.object(atlas_context.http_client, "get", get):
            result = atlas_context.read_shadow_context(
                target={"type": "stock", "id": "2330", "label": "TSMC"},
                now=NOW,
            )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["contract_version"], "1.1")
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(len(result["events"][0]["evidence"]), 2)
        self.assertNotIn("body_excerpt", result["events"][0]["evidence"][0])
        self.assertNotIn("canonical_url", result["events"][0]["evidence"][1])
        self.assertTrue(result["facts_usable"])
        self.assertFalse(result["decision_usable"])
        self.assertEqual(result["absence_interpretation"], "unknown_not_observed")
        self.assertEqual(result["freshness"]["status"], "current")
        self.assertEqual(get.call_args.args[0], "http://127.0.0.1:8790/api/v1/brief")
        self.assertEqual(get.call_args.kwargs["params"]["profile"], "evidence_pack_v1")
        self.assertEqual(get.call_args.kwargs["params"]["q"], "TSMC")

    def test_empty_result_is_ready_but_not_negative_evidence(self) -> None:
        payload = {
            "contract_version": "1.1",
            "profile": "evidence_pack_v1",
            "generated_at": "2026-08-23T03:59:00Z",
            "data": {"event_count": 0, "events": []},
            "freshness": {"status": "current"},
            "coverage": {"source_count": 4},
            "warnings": [],
        }
        with self._settings(omi_atlas_shadow_enabled=True), patch.object(
            atlas_context.http_client,
            "get",
            return_value=_Response(payload),
        ):
            result = atlas_context.read_shadow_context(
                target={"type": "market", "market": "TW"},
                now=NOW,
            )

        self.assertEqual(result["status"], "ready_empty")
        self.assertFalse(result["facts_usable"])
        self.assertFalse(result["decision_usable"])
        self.assertTrue(result["missing"])
        self.assertEqual(result["absence_interpretation"], "unknown_not_observed")

    def test_timeout_and_contract_mismatch_fail_closed(self) -> None:
        with self._settings(omi_atlas_shadow_enabled=True), patch.object(
            atlas_context.http_client,
            "get",
            side_effect=requests.Timeout(),
        ):
            timeout = atlas_context.read_shadow_context(
                target={"type": "stock", "id": "2330"},
                now=NOW,
            )
        self.assertEqual(timeout["status"], "unavailable")
        self.assertEqual(timeout["reason_code"], "atlas_timeout")

        mismatch_payload = {
            "contract_version": "2.0",
            "profile": "evidence_pack_v1",
            "data": {"events": []},
        }
        with self._settings(omi_atlas_shadow_enabled=True), patch.object(
            atlas_context.http_client,
            "get",
            return_value=_Response(mismatch_payload),
        ):
            mismatch = atlas_context.read_shadow_context(
                target={"type": "stock", "id": "2330"},
                now=NOW,
            )
        self.assertEqual(mismatch["status"], "incompatible")
        self.assertEqual(
            mismatch["reason_code"],
            "atlas_contract_version_mismatch",
        )

    def test_non_loopback_base_url_is_rejected_without_http(self) -> None:
        get = Mock()
        with self._settings(
            omi_atlas_shadow_enabled=True,
            omi_atlas_api_base_url="https://atlas.example.com",
        ), patch.object(atlas_context.http_client, "get", get):
            result = atlas_context.read_shadow_context(
                target={"type": "stock", "id": "2330"},
                now=NOW,
            )

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason_code"], "atlas_base_url_not_loopback")
        get.assert_not_called()

    def test_disabled_shadow_does_not_issue_http(self) -> None:
        get = Mock()
        with self._settings(omi_atlas_shadow_enabled=False), patch.object(
            atlas_context.http_client,
            "get",
            get,
        ):
            result = atlas_context.read_shadow_context(
                target={"type": "stock", "id": "2330"},
                now=NOW,
            )

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["reason_code"], "atlas_shadow_disabled")
        get.assert_not_called()

    def test_attach_and_projection_do_not_change_core_quality(self) -> None:
        result = {
            "missing": ["core_missing"],
            "warnings": ["core_warning"],
            "data": {"compact": {"slots": {}}},
        }
        context = atlas_context._base_payload(
            status="unavailable",
            target={"type": "stock", "id": "2330"},
            query="2330",
            generated_at=NOW,
        )
        context.update(
            {
                "reason_code": "atlas_connection_unavailable",
                "missing": ["Atlas supplemental context is unavailable."],
            }
        )
        atlas_context.attach_to_result(result, context)

        self.assertEqual(result["missing"], ["core_missing"])
        self.assertEqual(result["warnings"], ["core_warning"])
        self.assertEqual(
            result["data"]["compact"]["slots"]["news_events"]["status"],
            "unavailable",
        )
        projected, unavailable = capability_contract.project_selected_data(
            response={"result": result},
            selection={
                "required": [],
                "optional": ["news.events"],
                "fields": {},
                "limits": {},
            },
        )
        self.assertEqual(unavailable, [])
        self.assertFalse(projected["news.events"]["decision_usable"])
        self.assertEqual(projected["news.events"]["status"], "unavailable")

    def test_registry_and_provider_status_expose_shadow_boundary(self) -> None:
        entry = capability_contract.capability_resolution_for(
            scope_type="stock",
            capability_id="news.events",
        )
        self.assertEqual(entry.resolution_mode, "cache_only")
        self.assertEqual(entry.provider_contract_ids, ("news_events",))
        self.assertEqual(entry.side_effect_policy, "read_only_local_service")
        self.assertEqual(
            capability_resolution_registry.PROVIDER_CONTRACTS_BY_SCOPE_CAPABILITY[
                ("market", "news.events")
            ],
            ("news_events",),
        )

        with self._settings(omi_atlas_shadow_enabled=True):
            status = capability_context.read_capability_status(
                capability_id="news_events",
                now=NOW,
            )
        row = status["data"]["provider_contracts"][0]
        self.assertEqual(row["status"], "connected_shadow_readonly")
        self.assertEqual(row["provider"], "Open Intel Atlas")
        self.assertNotIn("blocking_reason", row)

    def test_omi_ask_projects_atlas_through_public_v4_contract(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        db = Session(engine)
        db.add(StockMaster(stock_id="2330", stock_name="TSMC", is_active=True))
        db.commit()
        context = atlas_context._base_payload(
            status="available",
            target={"type": "stock", "id": "2330", "label": "TSMC"},
            query="TSMC",
            generated_at=NOW,
        )
        context.update(
            {
                "event_count": 1,
                "returned_count": 1,
                "facts_usable": True,
                "events": [
                    {
                        "id": "evt-1",
                        "title": "TSMC event",
                        "evidence": [
                            {
                                "id": "doc-1",
                                "canonical_url": "https://example.test/doc-1",
                            }
                        ],
                    }
                ],
            }
        )
        try:
            with self._settings(omi_atlas_shadow_enabled=True), patch.object(
                atlas_context,
                "read_shadow_context",
                return_value=context,
            ) as read:
                response = ai_ask.ask(
                    db=db,
                    payload=AiAskRequest(
                        contract_version="omi.decision.v4",
                        question="2330 現在有哪些需要注意的情報？",
                        target={"type": "tw_stock", "id": "2330", "market": "TW"},
                        mode="data_only",
                        output="evidence_only",
                        selection={
                            "required": ["target.identity"],
                            "optional": ["news.events"],
                            "max_response_bytes": 65536,
                        },
                    ),
                    server_policy=ai_ask.AiAskServerPolicy(),
                )
        finally:
            db.close()
            engine.dispose()

        self.assertEqual(response["contract_version"], "omi.decision.v4")
        self.assertIn(
            "news.events",
            response["execution"]["selection"]["optional"],
        )
        self.assertIn("news.events", response["evidence"]["data"], response)
        self.assertEqual(
            response["evidence"]["data"]["news.events"]["status"],
            "available",
        )
        self.assertFalse(
            response["evidence"]["data"]["news.events"]["decision_usable"]
        )
        read.assert_called_once()


if __name__ == "__main__":
    unittest.main()
