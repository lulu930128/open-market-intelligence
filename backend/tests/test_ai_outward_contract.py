from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import agentic_execution
from app.ai import query_plan
from app.ai.market_payload_contract import slot_envelope
from app.ai.market_context import taiwan_stock
from app.ai.schemas import AiAskRequest
from app.jobs import service as job_service
from app.db.models import Base, StockMaster
from app.market.broker_branch import get_broker_branch_trade_summary


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_stock(db: Session) -> None:
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="台積電",
            market="TWSE",
            instrument_type="stock",
            is_active=True,
        )
    )
    db.commit()


def quote_context() -> dict:
    compact = {
        "kind": "tw_stock_quote_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": "compact",
        "status": "ready",
        "target": {
            "type": "tw_stock",
            "id": "2330",
            "label": "台積電",
            "market": "TWSE",
        },
        "quote": {
            "kind": "quote_snapshot",
            "price": 100.0,
            "trade_date": "2026-07-17",
            "freshness": {"status": "current", "is_stale": False},
        },
        "slots": {
            "quote": {
                "status": "ready",
                "availability": "available",
                "freshness": {"status": "current"},
            }
        },
    }
    return {
        "kind": "stock_quote_context",
        "as_of": "2026-07-17",
        "scope": {"stock_id": "2330"},
        "data": {"compact": compact},
        "missing": [],
        "warnings": [],
        "source_refs": [{"type": "table", "name": "market_daily_price"}],
        "evidence_passport": {},
    }


def broker_branch_context() -> dict:
    broker = {
        "trade_date": "2026-07-17",
        "trade_dates": [
            "2026-07-11",
            "2026-07-14",
            "2026-07-15",
            "2026-07-16",
            "2026-07-17",
        ],
        "available_days": 5,
        "requested_days": 5,
        "is_partial": False,
        "buy_top": [{"branch_code": "A001", "branch_name": "測試買方", "net_lots": 120}],
        "sell_top": [{"branch_code": "B001", "branch_name": "測試賣方", "net_lots": -80}],
    }
    compact = {
        "kind": "tw_stock_broker_branch_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": "compact",
        "status": "ready",
        "target": {
            "type": "tw_stock",
            "id": "2330",
            "label": "台積電",
            "market": "TWSE",
        },
        "chips": {"broker_branch": broker},
        "freshness_by_domain": {"broker_branch": "current"},
        "slots": {
            "broker_branch": {
                "status": "ready",
                "availability": "available",
                "freshness": {"status": "current"},
            },
            "fundamentals": {
                "status": "not_requested",
                "availability": "not_requested",
                "freshness": {"status": "not_requested"},
            },
        },
    }
    return {
        "kind": "stock_broker_branch_context",
        "as_of": "2026-07-17",
        "scope": {"stock_id": "2330"},
        "data": {"broker_branch": broker, "compact": compact},
        "missing": [],
        "warnings": [],
        "source_refs": [{"type": "table", "name": "broker_branch_trade_daily"}],
        "evidence_passport": {},
    }
class QueryPlanContractTests(unittest.TestCase):
    def test_empty_broker_branch_summary_explains_window_and_date_semantics(
        self,
    ) -> None:
        db = make_session()
        try:
            summary = get_broker_branch_trade_summary(
                db,
                stock_id="2330",
                days=5,
            )
        finally:
            db.close()

        self.assertEqual(
            summary["aggregation_window"]["mode"],
            "multi_session_net",
        )
        self.assertEqual(
            summary["aggregation_window"]["requested_trading_days"],
            5,
        )
        self.assertEqual(
            summary["date_semantics"]["trade_date"],
            "market_observation_date",
        )
        self.assertIn(
            "not_market_freshness",
            summary["date_semantics"]["created_at"],
        )

    def test_timeout_refresh_job_is_reused_before_second_provider_call(self) -> None:
        db = make_session()
        try:
            calls: list[int] = []

            def fake_deadline(**kwargs):
                job_id = kwargs["tracking_job_id"]
                calls.append(job_id)
                return (
                    {
                        "__background_job": {
                            "job_id": job_id,
                            "status": "running",
                            "deduplicated": False,
                            "poll_url": f"/api/jobs/{job_id}",
                        }
                    },
                    "timeout",
                    "deadline",
                )

            plan = {
                "tool_plan": [
                    {
                        "tool": "us.refresh_daily_price",
                        "args": {
                            "symbol": "NVDA",
                            "provider": "yahoo",
                            "outputsize": "compact",
                            "requested_capabilities": ["us_daily_price"],
                        },
                        "reason": "test timeout dedupe",
                    }
                ]
            }
            budget = {
                "max_calls": 1,
                "max_external_fetches": 1,
                "max_total_seconds": 10,
            }
            with patch.object(
                agentic_execution,
                "_execute_tool_with_deadline",
                side_effect=fake_deadline,
            ) as execute:
                first_runs, _ = agentic_execution.execute_tool_plan(
                    db=db,
                    plan=plan,
                    budget=budget,
                    can_external_fetch=True,
                )
                second_runs, _ = agentic_execution.execute_tool_plan(
                    db=db,
                    plan=plan,
                    budget=budget,
                    can_external_fetch=True,
                )

            self.assertEqual(execute.call_count, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(first_runs[0]["status"], "timeout")
            self.assertEqual(second_runs[0]["status"], "background_running")
            self.assertTrue(second_runs[0]["job"]["deduplicated"])
            self.assertEqual(
                first_runs[0]["job"]["job_id"],
                second_runs[0]["job"]["job_id"],
            )
            active = job_service.list_jobs(
                db,
                status="running",
                job_type=agentic_execution.BACKGROUND_TOOL_JOB_TYPE,
            )
            self.assertEqual(len(active), 1)
        finally:
            db.close()

    def test_tool_run_separates_transport_success_from_operation_failure(
        self,
    ) -> None:
        db = make_session()
        try:
            with patch.object(
                agentic_execution,
                "_execute_tool_with_deadline",
                return_value=(
                    {
                        "status": "error",
                        "provider": "tdcc",
                        "stock_id": "8299",
                        "refresh_outcome": "failed",
                        "error_message": "TDCC request timed out",
                        "failed_steps": [
                            {
                                "dataset": "shareholding_distribution",
                                "provider": "tdcc",
                                "target": "8299",
                                "status": "error",
                                "error_message": "TDCC request timed out",
                            }
                        ],
                    },
                    "success",
                    None,
                ),
            ):
                runs, _ = agentic_execution.execute_tool_plan(
                    db=db,
                    plan={
                        "tool_plan": [
                            {
                                "tool": "us.read_sec_fundamentals",
                                "args": {"symbol": "8299"},
                                "reason": "status contract regression",
                            }
                        ]
                    },
                    budget={
                        "max_calls": 1,
                        "max_external_fetches": 0,
                        "max_total_seconds": 10,
                    },
                    can_external_fetch=False,
                )

            run = runs[0]
            self.assertEqual(run["status"], "success")
            self.assertEqual(run["transport_status"], "success")
            self.assertEqual(run["operation_status"], "failed")
            self.assertEqual(run["evidence_status"], "unavailable")
            self.assertEqual(run["result_status"], "error")
            self.assertEqual(run["error"], "TDCC request timed out")
            self.assertEqual(
                run["result_summary"]["failed_steps"][0]["provider"],
                "tdcc",
            )
        finally:
            db.close()

    def test_job_public_status_uses_final_business_state(self) -> None:
        db = make_session()
        try:
            job = job_service.create_job(
                db,
                job_type=agentic_execution.BACKGROUND_TOOL_JOB_TYPE,
                target="2330",
                request={"profile": "full"},
            )
            job_service.start_job(db, job.id)
            completed = job_service.complete_job(
                db,
                job.id,
                result={"status": "partial", "warning_count": 1},
            )

            serialized = job_service.serialize_job(completed)

            self.assertEqual(serialized["status"], "success")
            self.assertEqual(serialized["public_status"], "partial")
        finally:
            db.close()

    def test_background_job_inner_error_finishes_as_failed(self) -> None:
        db = make_session()
        try:
            job = job_service.create_job(
                db,
                job_type=agentic_execution.BACKGROUND_TOOL_JOB_TYPE,
                target="8299",
                request={"profile": "shareholding"},
            )
            job_service.start_job(db, job.id)

            agentic_execution._finish_background_job_in_session(
                db,
                job.id,
                tool_name="tw.refresh_shareholding",
                status="success",
                value={
                    "status": "error",
                    "provider": "tdcc",
                    "error_message": "TDCC request timed out",
                },
            )

            serialized = job_service.serialize_job(
                job_service.get_job(db, job.id)
            )
            self.assertEqual(serialized["status"], "error")
            self.assertEqual(serialized["public_status"], "failed")
            self.assertEqual(
                serialized["result"]["error"],
                "TDCC request timed out",
            )
        finally:
            db.close()

    def test_slot_contract_distinguishes_available_but_stale_from_ready(self) -> None:
        slot = slot_envelope(
            status="ready",
            capability="tw_fundamentals",
            availability="available",
            freshness_status="stale",
        )

        self.assertEqual(slot["availability"], "available")
        self.assertEqual(slot["freshness"]["status"], "stale")
        self.assertEqual(slot["usability"], "limited")

    def test_background_refresh_dedupe_key_covers_capability_dimensions(self) -> None:
        base = agentic_execution._background_job_request(
            "tw.refresh_stock_evidence",
            {
                "stock_id": "2330",
                "profile": "full",
                "providers": ["twse", "tpex"],
                "from_date": "2026-07-01",
                "to_date": "2026-07-19",
                "include_today": True,
            },
        )
        compact = agentic_execution._background_job_request(
            "tw.refresh_stock_evidence",
            {
                "stock_id": "2330",
                "profile": "compact",
                "providers": ["twse", "tpex"],
                "from_date": "2026-07-01",
                "to_date": "2026-07-19",
                "include_today": True,
            },
        )

        self.assertEqual(base["normalized_target"], "2330")
        self.assertEqual(base["refresh_profile"], "full")
        self.assertEqual(base["provider_set"], ["tpex", "twse"])
        self.assertEqual(base["date_range"]["from"], "2026-07-01")
        self.assertTrue(base["include_today"])
        self.assertEqual(
            base["requested_capabilities"],
            ["tw.refresh_stock_evidence"],
        )
        self.assertNotEqual(base, compact)

    def test_explicit_market_target_preserves_market_identity(self) -> None:
        payload = AiAskRequest(
            question="台股大盤最新狀態",
            target={"type": "market", "market": "TW"},
            mode="data_only",
        )

        resolution = ai_ask._resolve_scope(db=None, payload=payload)

        self.assertEqual(resolution.selected_scope_type, "market")
        self.assertEqual(resolution.selected_market, "TW")
        self.assertEqual(ai_ask._resolution_target(resolution)["market"], "TW")

    def test_auto_market_breadth_returns_brief_human_answer(self) -> None:
        payload = AiAskRequest(
            question="今天漲跌家數與跌停家數如何？",
            target={"type": "market", "market": "TW"},
            mode="auto",
        )
        breadth = {
            "label": "上市全市場廣度",
            "status": "ready",
            "decision_usable": True,
            "advance_count": 88,
            "decline_count": 971,
            "unchanged_count": 12,
            "limit_up_count": 4,
            "limit_down_count": 84,
        }
        result = {
            "kind": "market_brief",
            "as_of": "2026-07-17",
            "summary": {
                "kind": "market_brief_summary",
                "as_of": "2026-07-17",
                "human_answer": {"lines": ["市場廣度"]},
                "breadth": breadth,
            },
            "data": {
                "compact": {
                    "kind": "tw_market_compact_evidence",
                    "status": "ready",
                    "target": {
                        "type": "market",
                        "id": "TW",
                        "label": "台股市場",
                        "market": "TW",
                    },
                    "breadth": breadth,
                    "slots": {
                        "market_breadth": {
                            "status": "ready",
                            "availability": "available",
                            "freshness": {"status": "current"},
                            "usability": "usable",
                        }
                    },
                }
            },
            "missing": [],
            "warnings": [],
            "source_refs": [{"type": "table", "name": "market_index_daily"}],
        }
        with (
            patch.object(ai_ask, "_check_freshness", return_value={"is_current": True}),
            patch.object(
                ai_ask,
                "_build_brief",
                return_value=("omi.generate_market_brief", result),
            ),
        ):
            response = ai_ask.ask(db=None, payload=payload)  # type: ignore[arg-type]

        self.assertEqual(response["mode"]["effective"], "brief")
        self.assertTrue(response["analysis_ready"])
        self.assertEqual(
            response["analysis"]["human_answer"]["style"],
            "market_breadth_summary",
        )
        self.assertIn("明顯偏弱", response["analysis"]["human_answer"]["headline"])

    def test_quote_plan_excludes_analysis_readers_and_external_refresh(self) -> None:
        payload = AiAskRequest(
            question="2330 最新收盤價",
            target={"type": "tw_stock", "id": "2330"},
            mode="brief",
            payload_level="summary",
            diagnostics_level="debug",
        )

        plan = query_plan.build_query_plan(
            payload=payload,
            scope_type="stock",
            question_intent="quote",
            effective_mode="brief",
        )

        self.assertEqual(plan.response_mode, "brief")
        self.assertEqual(plan.payload_level, "summary")
        self.assertEqual(plan.diagnostics_level, "debug")
        self.assertFalse(plan.external_refresh_allowed)
        self.assertIn("quote_snapshot", plan.required_capabilities)
        self.assertIn("technical_decision_evidence", plan.excluded_capabilities)
        self.assertIn("get_broker_branch_trade_summary", plan.excluded_readers)

    def test_quote_reader_calls_only_identity_daily_price_and_calendar(self) -> None:
        stock = SimpleNamespace(stock_id="2330", stock_name="台積電", market="TWSE")
        daily = SimpleNamespace(
            trade_date=date(2026, 7, 17),
            close_price=100.0,
            open_price=99.0,
            high_price=101.0,
            low_price=98.0,
            price_change=1.0,
            trade_volume=10_000,
        )
        stock_service = SimpleNamespace(
            get_stock=Mock(return_value=stock),
            StockNotFoundError=RuntimeError,
        )
        market_service = SimpleNamespace(
            get_latest_stock_daily_price=Mock(return_value=daily),
        )
        excluded = {
            name: Mock(side_effect=AssertionError(f"excluded reader called: {name}"))
            for name in query_plan.QUOTE_ONLY_EXCLUDED_READERS
        }
        dependencies = taiwan_stock.TaiwanStockDependencies(
            market_service=market_service,
            stock_service=stock_service,
            build_stock_technical_report=excluded["build_stock_technical_report"],
            build_taiwan_calendar_status=Mock(
                return_value={
                    "phase": "market_closed",
                    "release_windows": {
                        "market_daily_price": {"expected_trade_date": "2026-07-17"}
                    },
                }
            ),
            build_taiwan_source_health=Mock(),
            build_us_overnight_impact_report=excluded["build_us_overnight_impact_report"],
            get_broker_branch_trade_summary=excluded["get_broker_branch_trade_summary"],
            read_taiwan_bars=excluded["read_taiwan_bars"],
            read_taiwan_quote_evidence=excluded["read_taiwan_quote_evidence"],
            acquire_taiwan_quote_evidence=excluded["read_taiwan_quote_evidence"],
            read_taiwan_latest_daily_evidence=market_service.get_latest_stock_daily_price,
            now=Mock(return_value="2026-07-19T00:00:00Z"),
        )

        with patch.object(
            taiwan_stock.taiwan_events,
            "build_tw_stock_event_context",
            return_value={
                "data": {},
                "missing": [],
                "warnings": [],
                "source_refs": [
                    {"type": "resolved_market_data", "name": "tw.events"}
                ],
            },
        ):
            result = taiwan_stock.read_stock_quote_context(
                db=SimpleNamespace(),
                stock_id="2330",
                market_data_params={"payload_level": "compact"},
                dependencies=dependencies,
            )

        self.assertEqual(result["kind"], "stock_quote_context")
        self.assertEqual(result["data"]["compact"]["status"], "ready")
        self.assertEqual(
            result["data"]["compact"]["slots"]["technical"]["status"],
            "not_requested",
        )
        self.assertIn(
            {"type": "resolved_market_data", "name": "tw.events"},
            result["source_refs"],
        )
        stock_service.get_stock.assert_called_once()
        market_service.get_latest_stock_daily_price.assert_called_once()
        for reader in excluded.values():
            reader.assert_not_called()

    def test_released_official_daily_does_not_treat_previous_session_as_current(self) -> None:
        missing: list[str] = []
        warnings: list[str] = []
        state = taiwan_stock._apply_taiwan_official_daily_release_truth(
            latest_daily=SimpleNamespace(trade_date=date(2026, 8, 28)),
            calendar_status={
                "release_windows": {
                    "market_daily_price": {
                        "status": "released",
                        "is_released": True,
                        "expected_trade_date": "2026-08-31",
                    }
                }
            },
            missing=missing,
            warnings=warnings,
        )

        self.assertEqual(state["status"], "released_but_unavailable")
        self.assertTrue(state["unavailable_after_release"])
        self.assertEqual(missing, ["market_daily_price"])
        self.assertTrue(
            any(
                warning.startswith("TW_OFFICIAL_DAILY_RELEASED_BUT_UNAVAILABLE")
                for warning in warnings
            )
        )

    def test_current_session_reference_uses_latest_completed_close(self) -> None:
        quote = {
            "source": "market_daily_price",
            "provider": "local_daily_close",
            "trade_date": "2026-08-28",
            "previous_close": 2410.0,
        }

        resolved = taiwan_stock._apply_taiwan_current_price_contract(
            quote=quote,
            intraday_bars={},
            latest_daily=SimpleNamespace(
                trade_date=date(2026, 8, 28),
                close_price=2420.0,
            ),
            calendar_status={
                "date": "2026-08-31",
                "previous_trading_day": "2026-08-31",
                "is_trading_day": True,
                "phase": "post_close",
            },
            checked_at=datetime(2026, 8, 31, 15, 20, tzinfo=timezone(timedelta(hours=8))),
        )

        self.assertEqual(resolved["source_kind"], "previous_close_reference")
        self.assertEqual(resolved["reference_price"], 2420.0)

    def test_broker_branch_reader_does_not_load_fundamental_or_technical_domains(self) -> None:
        stock = SimpleNamespace(stock_id="2330", stock_name="台積電", market="TWSE")
        stock_service = SimpleNamespace(
            get_stock=Mock(return_value=stock),
            StockNotFoundError=RuntimeError,
        )
        branch_summary = broker_branch_context()["data"]["broker_branch"]
        excluded = {
            name: Mock(side_effect=AssertionError(f"excluded reader called: {name}"))
            for name in query_plan.BROKER_BRANCH_EXCLUDED_READERS
        }
        dependencies = taiwan_stock.TaiwanStockDependencies(
            market_service=SimpleNamespace(**excluded),
            stock_service=stock_service,
            build_stock_technical_report=excluded["build_stock_technical_report"],
            build_taiwan_calendar_status=Mock(
                return_value={
                    "phase": "market_closed",
                    "release_windows": {
                        "broker_branch_trade_daily": {
                            "expected_trade_date": "2026-07-17"
                        }
                    },
                }
            ),
            build_taiwan_source_health=Mock(),
            build_us_overnight_impact_report=excluded["build_us_overnight_impact_report"],
            get_broker_branch_trade_summary=Mock(return_value=branch_summary),
            read_taiwan_bars=excluded["read_taiwan_bars"],
            read_taiwan_quote_evidence=excluded["read_taiwan_quote_evidence"],
            acquire_taiwan_quote_evidence=excluded["read_taiwan_quote_evidence"],
            read_taiwan_latest_daily_evidence=Mock(
                side_effect=AssertionError(
                    "excluded reader called: read_taiwan_latest_daily_evidence"
                )
            ),
            now=Mock(return_value="2026-07-19T00:00:00Z"),
        )

        result = taiwan_stock.read_stock_broker_branch_context(
            db=SimpleNamespace(),
            stock_id="2330",
            branch_days=5,
            market_data_params={"payload_level": "summary"},
            dependencies=dependencies,
        )

        self.assertEqual(result["kind"], "stock_broker_branch_context")
        self.assertEqual(result["data"]["compact"]["status"], "ready")
        self.assertEqual(
            result["data"]["compact"]["slots"]["fundamentals"]["status"],
            "not_requested",
        )
        self.assertNotIn("monthly_revenue", result["missing"])
        dependencies.get_broker_branch_trade_summary.assert_called_once()
        for reader in excluded.values():
            reader.assert_not_called()

    def test_quote_ask_is_data_only_and_keeps_readiness_layers_separate(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="2330 最新收盤價",
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
                payload_level="compact",
                diagnostics_level="debug",
                allow_external_fetch=True,
            )
            freshness_result = {
                "scope_profile": "quote_only",
                "is_current": True,
                "refresh_recommended": True,
                "missing": [],
                "warnings": [],
            }
            with (
                patch.object(
                    ai_ask.freshness,
                    "check_stock_daily_price_freshness",
                    return_value=freshness_result,
                ),
                patch.object(
                    ai_ask.tools,
                    "read_stock_quote_context",
                    return_value=quote_context(),
                ) as quote_reader,
                patch.object(
                    ai_ask.tools,
                    "read_stock_context",
                    side_effect=AssertionError("full stock reader must not run"),
                ),
                patch.object(ai_ask.agentic_tools, "run_tw_stock_tool_session") as refresh,
            ):
                response = ai_ask.ask(db=db, payload=payload)

            quote_reader.assert_called_once()
            refresh.assert_not_called()
            self.assertTrue(response["ok"])
            self.assertEqual(response["action"], "omi.read_stock_quote")
            self.assertEqual(response["mode"]["effective"], "data_only")
            self.assertEqual(response["mode"]["response"], "data_only")
            self.assertTrue(response["facts_ready"])
            self.assertTrue(response["answer_ready"])
            self.assertFalse(response["analysis_ready"])
            self.assertFalse(response["decision_ready"])
            self.assertNotIn("human_answer", response["analysis"])
            self.assertNotIn("decision_contract", response["analysis"])
            self.assertEqual(response["reasoning_steps"], [])
            self.assertFalse(response["query_plan"]["external_refresh_allowed"])
            self.assertEqual(response["diagnostics"]["level"], "debug")
        finally:
            db.close()

    def test_quote_brief_uses_same_scoped_reader_and_returns_quote_answer(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="2330 最新收盤價",
                target={"type": "tw_stock", "id": "2330"},
                mode="brief",
                payload_level="summary",
                diagnostics_level="basic",
                allow_external_fetch=True,
            )
            freshness_result = {
                "scope_profile": "quote_only",
                "is_current": True,
                "refresh_recommended": True,
                "refresh_endpoint": None,
                "missing": [],
                "warnings": [],
            }
            with (
                patch.object(
                    ai_ask.freshness,
                    "check_stock_daily_price_freshness",
                    return_value=freshness_result,
                ),
                patch.object(
                    ai_ask.tools,
                    "read_stock_quote_context",
                    return_value=quote_context(),
                ) as quote_reader,
                patch.object(
                    ai_ask.tools,
                    "read_stock_context",
                    side_effect=AssertionError("full stock reader must not run"),
                ),
                patch.object(ai_ask.agentic_tools, "run_tw_stock_tool_session") as refresh,
            ):
                response = ai_ask.ask(db=db, payload=payload)

            quote_reader.assert_called_once()
            refresh.assert_not_called()
            self.assertTrue(response["ok"])
            self.assertEqual(response["mode"]["effective"], "brief")
            self.assertEqual(response["mode"]["response"], "brief")
            self.assertTrue(response["facts_ready"])
            self.assertTrue(response["analysis_ready"])
            self.assertTrue(response["answer_ready"])
            self.assertFalse(response["decision_ready"])
            human_answer = response["analysis"]["human_answer"]
            self.assertEqual(human_answer["style"], "quote_summary")
            self.assertEqual(human_answer["action_plan"], [])
            self.assertIn("100 元", human_answer["text"])
            self.assertIn("2026-07-17", human_answer["text"])
            self.assertFalse(
                any(action.get("type") == "refresh_data" for action in response["next_actions"])
            )
        finally:
            db.close()

    def test_broker_branch_answer_trust_ignores_monthly_revenue_domain(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question="2330 近五天分點主要買賣方",
                target={"type": "tw_stock", "id": "2330"},
                mode="brief",
                branch_days=5,
                diagnostics_level="debug",
            )
            freshness_result = {
                "scope_profile": "broker_branch_only",
                "is_current": True,
                "refresh_recommended": False,
                "missing": [],
                "warnings": [],
            }
            with (
                patch.object(
                    ai_ask.freshness,
                    "check_stock_broker_branch_freshness",
                    return_value=freshness_result,
                ),
                patch.object(
                    ai_ask.tools,
                    "read_stock_broker_branch_context",
                    return_value=broker_branch_context(),
                ) as branch_reader,
                patch.object(
                    ai_ask.tools,
                    "read_stock_context",
                    side_effect=AssertionError("full stock reader must not run"),
                ),
            ):
                response = ai_ask.ask(db=db, payload=payload)

            branch_reader.assert_called_once()
            self.assertTrue(response["ok"])
            self.assertEqual(response["action"], "omi.read_stock_broker_branch")
            self.assertEqual(response["analysis"]["human_answer"]["style"], "broker_branch_summary")
            self.assertNotIn("monthly_revenue", response["missing"])
            self.assertNotIn("monthly_revenue", response["evidence_passport"]["missing"])
            self.assertIn(
                "broker_branch_trade_daily",
                response["evidence_passport"]["required_capabilities"],
            )
            self.assertFalse(response["query_plan"]["external_refresh_allowed"])
        finally:
            db.close()

    def test_multi_intent_broker_request_uses_standard_reader(self) -> None:
        db = make_session()
        try:
            add_stock(db)
            payload = AiAskRequest(
                question=(
                    "2330 latest price, daily chart, technical, institutional, "
                    "margin, and broker branch"
                ),
                contract_version="omi.decision.v4",
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
                output="evidence_only",
            )
            context = {
                "kind": "stock_context",
                "as_of": "2026-07-24",
                "scope": {"stock_id": "2330"},
                "data": {
                    "chart": {
                        "latest_data_date": "2026-07-24",
                        "points": [
                            {
                                "bar_time": "2026-07-24",
                                "close_price": 100.0,
                            }
                        ],
                    },
                    "compact": {
                        "kind": "stock_compact_evidence",
                        "status": "ready",
                        "quote": {
                            "price": 100.0,
                            "trade_date": "2026-07-24",
                        },
                        "technical": {"analysis": {"selected_score": 1}},
                        "chips": {
                            "institutional": {"trade_date": "2026-07-24"},
                            "margin": {"trade_date": "2026-07-24"},
                            "broker_branch": {"trade_date": "2026-07-24"},
                        },
                        "freshness_by_domain": {
                            "quote": "current",
                            "chart": "current",
                            "technical": "current",
                            "chips": "current",
                            "broker_branch": "current",
                        },
                    },
                },
                "missing": [],
                "warnings": [],
                "source_refs": [],
            }
            with (
                patch.object(
                    ai_ask,
                    "_check_freshness",
                    return_value={
                        "is_current": True,
                        "missing": [],
                        "warnings": [],
                    },
                ),
                patch.object(
                    ai_ask.tools,
                    "read_stock_context",
                    return_value=context,
                ) as full_reader,
                patch.object(
                    ai_ask.tools,
                    "read_stock_broker_branch_context",
                    side_effect=AssertionError(
                        "broker-only reader must not run for multi-intent request"
                    ),
                ),
            ):
                response = ai_ask.ask(db=db, payload=payload)

            full_reader.assert_called_once()
            self.assertEqual(response["action"], "omi.read_stock_context")
            self.assertEqual(
                response["execution"]["query_plan"]["reader_profile"],
                "standard",
            )
            selected = set(
                response["execution"]["selection"]["required"]
            )
            self.assertTrue(
                {
                    "quote.snapshot",
                    "daily.ohlcv",
                    "technical.structure",
                    "chips.institutional",
                    "chips.margin",
                    "broker_branch.summary",
                }
                <= selected
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
