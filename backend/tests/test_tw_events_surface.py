from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.ai import ask_execution, capability_contract, query_plan
from app.ai.market_context import taiwan_events, taiwan_stock
from app.ai.schemas import AiAskRequest


NOW = datetime(2026, 7, 29, 2, 0, tzinfo=timezone.utc)


class TaiwanEventSurfaceTests(unittest.TestCase):
    def test_current_empty_upcoming_result_is_ready_not_missing(self) -> None:
        summary = Mock(
            return_value={
                "stock_id": "2330",
                "checked_at": NOW,
                "cache_status": "current",
                "cache_fetched_at": NOW,
                "warning": None,
                "result_count": 0,
                "results": [],
            }
        )

        context = taiwan_events.build_tw_stock_event_context(
            stock_id="2330",
            market="TWSE",
            market_data_params={
                "requested_capabilities": ["events.upcoming"],
                "capability_parameters": {
                    "events.upcoming": {"days": 14, "limit": 7}
                },
            },
            now=NOW,
            get_event_summary=summary,
            get_event_history=Mock(),
            get_disposition_status=Mock(),
        )

        payload = context["data"]["events.upcoming"]
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["events"], [])
        self.assertTrue(payload["empty_result_is_valid"])
        self.assertEqual(context["missing"], [])
        self.assertTrue(
            context["freshness_by_capability"]["events.upcoming"]["is_current"]
        )
        summary.assert_called_once_with(
            "2330",
            market="TWSE",
            reminder_days=14,
            max_results=7,
            now=NOW,
        )

    def test_event_only_stock_reader_does_not_load_market_analysis_domains(
        self,
    ) -> None:
        stock = SimpleNamespace(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
        )
        summary = Mock(
            return_value={
                "stock_id": "2330",
                "checked_at": NOW,
                "cache_status": "current",
                "cache_fetched_at": NOW,
                "warning": None,
                "result_count": 0,
                "results": [],
            }
        )
        excluded = Mock(
            side_effect=AssertionError(
                "event-only reader loaded an analysis dependency"
            )
        )
        dependencies = taiwan_stock.TaiwanStockDependencies(
            market_service=SimpleNamespace(),
            stock_service=SimpleNamespace(
                get_stock=Mock(return_value=stock),
                StockNotFoundError=RuntimeError,
            ),
            build_stock_technical_report=excluded,
            build_taiwan_calendar_status=excluded,
            build_taiwan_source_health=excluded,
            build_us_overnight_impact_report=excluded,
            get_broker_branch_trade_summary=excluded,
            get_market_intraday_history=excluded,
            get_taiwan_stock_quote_depth=excluded,
            get_taiwan_disposition_status=Mock(),
            get_taiwan_stock_event_summary=summary,
            get_taiwan_stock_event_history=Mock(),
            now=Mock(return_value=NOW),
        )

        result = taiwan_stock.read_stock_event_context(
            db=SimpleNamespace(),
            stock_id="2330",
            market_data_params={
                "payload_level": "compact",
                "requested_capabilities": ["events.upcoming"],
            },
            dependencies=dependencies,
        )

        self.assertEqual(result["kind"], "stock_event_context")
        self.assertEqual(
            result["data"]["compact"]["events"]["upcoming"]["status"],
            "ready",
        )
        self.assertEqual(
            result["data"]["compact"]["slots"]["events_upcoming"][
                "usability"
            ],
            "usable",
        )
        summary.assert_called_once()
        excluded.assert_not_called()

    def test_explicit_event_selection_uses_event_only_query_plan(self) -> None:
        payload = AiAskRequest(
            question="2330 未來 30 天事件",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            output="evidence_only",
            selection={
                "include": ["events.upcoming"],
                "parameters": {
                    "events.upcoming": {"days": 30, "limit": 10}
                },
            },
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            target_market="TW",
            question_intent="general",
            effective_mode="data_only",
        )

        self.assertEqual(plan.reader_profile, "event_only")
        self.assertFalse(plan.external_refresh_allowed)
        self.assertIn(
            "get_taiwan_stock_event_summary",
            plan.required_readers,
        )
        self.assertNotIn(
            "get_taiwan_stock_event_history",
            plan.required_readers,
        )
        self.assertNotIn(
            "get_taiwan_disposition_status",
            plan.required_readers,
        )
        self.assertIn(
            "list_stock_ohlc_chart_data",
            plan.excluded_readers,
        )

    def test_event_only_execution_dispatches_to_bounded_reader(self) -> None:
        payload = AiAskRequest(
            question="2330 未來事件",
            target={"type": "tw_stock", "id": "2330"},
            mode="data_only",
            market_data_params={
                "reader_profile": "event_only",
                "requested_capabilities": ["events.upcoming"],
            },
        )
        expected = {
            "kind": "stock_event_context",
            "freshness": {
                "scope_profile": "event_only",
                "status": "current",
                "is_current": True,
            },
        }

        with patch.object(
            ask_execution.tools,
            "read_stock_event_context",
            return_value=expected,
        ) as reader:
            action, result = ask_execution._read_data_only(
                db=SimpleNamespace(),
                payload=payload,
                scope_type="stock",
                question_intent="general",
            )
            freshness = ask_execution._check_freshness(
                db=SimpleNamespace(),
                payload=payload,
                scope_type="stock",
                question_intent="general",
            )

        self.assertEqual(action, "omi.read_stock_events")
        self.assertIs(result, expected)
        self.assertEqual(freshness["scope_profile"], "event_only")
        self.assertEqual(reader.call_count, 2)

    def test_missing_disposition_cache_does_not_claim_unrestricted_trading(
        self,
    ) -> None:
        context = taiwan_events.build_tw_stock_event_context(
            stock_id="2330",
            market="TWSE",
            market_data_params={
                "requested_capabilities": [
                    "regulation.disposition",
                    "regulation.trading_restrictions",
                ]
            },
            now=NOW,
            get_event_summary=Mock(),
            get_event_history=Mock(),
            get_disposition_status=Mock(
                return_value={
                    "stock_id": "2330",
                    "checked_at": NOW,
                    "cache_status": "missing",
                    "cache_fetched_at": None,
                    "status": "none",
                    "is_disposition": False,
                    "is_active": False,
                    "warning": "尚無處置證券 cache。",
                }
            ),
        )

        restrictions = context["data"]["regulation.trading_restrictions"]
        self.assertEqual(restrictions["status"], "missing")
        self.assertEqual(restrictions["trading_mode"], "unknown")
        self.assertEqual(restrictions["analysis_basis"], "unknown")
        self.assertIsNone(restrictions["requires_full_precollection"])
        self.assertIn("taiwan_disposition_cache", restrictions["missing"])

    def test_active_disposition_exposes_effective_matching_restrictions(
        self,
    ) -> None:
        context = taiwan_events.build_tw_stock_event_context(
            stock_id="2330",
            market="TWSE",
            market_data_params={
                "requested_capabilities": [
                    "regulation.trading_restrictions"
                ]
            },
            now=NOW,
            get_event_summary=Mock(),
            get_event_history=Mock(),
            get_disposition_status=Mock(
                return_value={
                    "stock_id": "2330",
                    "checked_at": NOW,
                    "cache_status": "current",
                    "cache_fetched_at": NOW,
                    "status": "active",
                    "is_disposition": True,
                    "is_active": True,
                    "start_date": date(2026, 7, 28),
                    "end_date": date(2026, 8, 10),
                    "matching_interval_minutes": 20,
                    "requires_full_precollection": True,
                    "margin_trading_suspended": True,
                    "provider": "twse_openapi",
                    "source_name": "TWSE 處置證券",
                    "warning": None,
                }
            ),
        )

        restrictions = context["data"]["regulation.trading_restrictions"]
        self.assertEqual(
            restrictions["trading_mode"],
            "disposition_batch_auction",
        )
        self.assertEqual(restrictions["analysis_basis"], "effective_matches")
        self.assertEqual(restrictions["matching_interval_minutes"], 20)
        self.assertTrue(restrictions["requires_full_precollection"])
        self.assertTrue(restrictions["margin_trading_suspended"])
        self.assertEqual(restrictions["effective_start_date"], "2026-07-28")

    def test_capability_projection_reads_stock_event_compact_paths(self) -> None:
        value = {
            "kind": "tw_stock_event_upcoming",
            "status": "ready",
            "stock_id": "2330",
            "as_of": NOW.isoformat(),
            "days": 30,
            "result_count": 1,
            "events": [{"event_id": "event-1", "start_date": "2026-08-01"}],
            "source": "taiwan_corporate_event_cache",
            "cache_policy": "cache_only",
            "cache_status": "current",
            "empty_result_is_valid": False,
            "missing": [],
            "warnings": [],
        }
        projected, unavailable = capability_contract.project_selected_data(
            response={
                "result": {
                    "data": {
                        "compact": {
                            "events": {
                                "upcoming": value,
                            }
                        }
                    }
                }
            },
            selection={
                "required": ["events.upcoming"],
                "optional": [],
                "fields": {},
                "limits": {},
            },
        )

        self.assertEqual(unavailable, [])
        self.assertEqual(
            projected["events.upcoming"]["events"][0]["event_id"],
            "event-1",
        )

    def test_event_parameters_and_market_applicability_are_validated(self) -> None:
        selection = capability_contract.normalize_selection(
            scope_type="stock",
            target_market="TW",
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            question_intent="events",
            selection={
                "required": ["events.upcoming"],
                "parameters": {
                    "events.upcoming": {"days": 60, "limit": 25}
                },
            },
        )
        self.assertEqual(
            selection["parameters"]["events.upcoming"]["days"],
            60,
        )

        with self.assertRaisesRegex(ValueError, "at most 365"):
            capability_contract.normalize_selection(
                scope_type="stock",
                target_market="TW",
                output="evidence_only",
                realtime_policy="cache_only",
                payload_level="compact",
                question_intent="events",
                selection={
                    "required": ["events.upcoming"],
                    "parameters": {
                        "events.upcoming": {"days": 366}
                    },
                },
            )

        unsupported = capability_contract.normalize_selection(
            scope_type="stock",
            target_market="US",
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            question_intent="events",
            selection={"required": ["events.upcoming"]},
        )
        self.assertEqual(
            unsupported["unmet_required_capabilities"][0]["reason_code"],
            "unsupported_market",
        )

        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            capability_contract.normalize_selection(
                scope_type="market",
                target_market="TW",
                output="evidence_only",
                realtime_policy="cache_only",
                payload_level="compact",
                question_intent="events",
                selection={
                    "required": ["events.calendar"],
                    "parameters": {
                        "events.calendar": {"date_from": "2026/07/29"}
                    },
                },
            )

        market_events = capability_contract.normalize_selection(
            scope_type="market",
            target_market="TW",
            output="evidence_only",
            realtime_policy="cache_only",
            payload_level="compact",
            question_intent="events",
            requested_domains=("events",),
            selection=None,
        )
        self.assertIn("events.calendar", market_events["required"])
        self.assertNotIn("events.upcoming", market_events["required"])


if __name__ == "__main__":
    unittest.main()
