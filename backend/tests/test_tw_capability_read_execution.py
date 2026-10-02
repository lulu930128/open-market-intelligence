from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ai import ask_execution, capability_contract, query_plan
from app.ai.capability_resolution_registry import CapabilityReadNode, compile_tw_stock_read_plan
from app.ai.market_context import taiwan_stock
from app.ai.read_execution import ReadExecution
from app.ai.schemas import AiAskRequest
from app.db.models import StockMaster


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'read.db'}")
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def dependencies():
    now = datetime(2026, 9, 29, 8, tzinfo=timezone.utc)
    stock = SimpleNamespace(stock_id="2328", stock_name="Test", market="TWSE", instrument_type="stock")
    market = Mock()
    market.get_latest_stock_institutional_trade.return_value = SimpleNamespace(trade_date=date(2026, 9, 28), foreign_investor_net=100)
    market.get_latest_stock_margin_trade.return_value = SimpleNamespace(trade_date=date(2026, 9, 28), margin_today_balance=20)
    market.list_stock_monthly_revenue_history.return_value = [SimpleNamespace(period="202608", monthly_revenue=123)]
    market.list_stock_financial_metric_history.return_value = []
    market.list_stock_ohlc_chart_data.return_value = {
        "points": [{"time": "2026-09-28", "close": 12}], "timeframe": "daily",
        "latest_data_date": "2026-09-28", "freshness_status": "current", "requested_bars": 260,
    }
    health = Mock(side_effect=lambda **kw: {"entries": [{"resource": kw["dataset"], "status": "current", "ok": True,
        "latest_data_date": "2026-09-28", "expected_data_date": "2026-09-28", "release_status": "released"}]})
    return taiwan_stock.TaiwanStockDependencies(
        market_service=market, stock_service=SimpleNamespace(get_stock=Mock(return_value=stock)),
        build_stock_technical_report=Mock(return_value={}),
        build_taiwan_calendar_status=Mock(return_value={"date": "2026-09-29", "phase": "closed"}),
        build_taiwan_source_health=health, build_us_overnight_impact_report=Mock(return_value={}),
        get_broker_branch_trade_summary=Mock(return_value={}), read_taiwan_bars=Mock(),
        read_taiwan_quote_evidence=Mock(return_value={}), acquire_taiwan_quote_evidence=Mock(side_effect=AssertionError("acquisition")),
        read_taiwan_latest_daily_evidence=Mock(return_value=None),
        read_taiwan_company_profile=Mock(), get_taiwan_stock_event_history=Mock(return_value={}),
        build_tw_stock_technical_evidence=Mock(return_value={}), now=lambda: now,
    )


def read(db, dependencies, capabilities, **params):
    return taiwan_stock.read_stock_context(db, "2328", dependencies=dependencies, market_data_params={
        "requested_capabilities": ["target.identity", *capabilities, "data.freshness"],
        "realtime_policy": "cache_only", "external_fetch_allowed": False, **params,
    })


def nodes(result):
    return [item["node"] for item in result["read_execution"]["nodes"]]


@pytest.mark.parametrize("capabilities,expected", [
    (["chips.institutional", "chips.margin"], {"identity", "institutional", "margin", "selected_freshness"}),
    (["fundamentals.revenue"], {"identity", "revenue", "selected_freshness"}),
    (["daily.ohlcv"], {"identity", "daily", "selected_freshness"}),
])
def test_narrow_scope_does_not_execute_supplemental_readers(db, dependencies, capabilities, expected):
    result = read(db, dependencies, capabilities)
    assert set(nodes(result)) == expected
    assert all(item["status"] == "completed" for item in result["read_execution"]["nodes"])
    dependencies.build_stock_technical_report.assert_not_called()
    dependencies.build_tw_stock_technical_evidence.assert_not_called()
    dependencies.get_broker_branch_trade_summary.assert_not_called()
    dependencies.build_us_overnight_impact_report.assert_not_called()
    dependencies.read_taiwan_quote_evidence.assert_not_called()
    dependencies.read_taiwan_company_profile.assert_not_called()
    dependencies.acquire_taiwan_quote_evidence.assert_not_called()
    dependencies.market_service.list_latest_stock_shareholding_distribution.assert_not_called()
    assert all(call.kwargs.get("dataset") for call in dependencies.build_taiwan_source_health.call_args_list)
    assert "score_model" not in result["data"]["analysis"]


def test_wide_request_aggregates_once_and_deduplicates_dependencies(db, dependencies):
    selected = ["daily.ohlcv", "technical.indicators", "technical.swings", "chips.institutional", "chips.margin",
                "fundamentals.revenue", "fundamentals.financials"]
    with patch.object(taiwan_stock, "build_database_financial_contract", return_value={"status": "missing"}):
        result = read(db, dependencies, selected)
    actual = nodes(result)
    assert len(actual) == len(set(actual))
    assert set(actual) == set(compile_tw_stock_read_plan(selected))
    dependencies.stock_service.get_stock.assert_called_once()
    dependencies.market_service.list_stock_ohlc_chart_data.assert_called_once()
    dependencies.build_tw_stock_technical_evidence.assert_called_once()
    dependencies.market_service.list_stock_monthly_revenue_history.assert_called_once()
    dependencies.market_service.list_stock_financial_metric_history.assert_called_once()
    dependencies.get_broker_branch_trade_summary.assert_not_called()
    dependencies.build_us_overnight_impact_report.assert_not_called()
    compact = result["data"]["compact"]
    assert compact["chips"]["institutional"]["foreign_investor_net"] == 100
    assert compact["chips"]["margin"]["margin_today_balance"] == 20
    assert compact["fundamentals"]["latest_revenue"]["monthly_revenue"] == 123


@pytest.mark.parametrize("failure", [TimeoutError("bounded"), ValueError("invalid row")])
def test_capability_failure_preserves_other_evidence(db, dependencies, failure):
    dependencies.market_service.get_latest_stock_margin_trade.side_effect = failure
    result = read(db, dependencies, ["chips.institutional", "chips.margin"])
    assert result["data"]["compact"]["chips"]["institutional"]["foreign_investor_net"] == 100
    assert result["freshness"]["status"] == "partial"
    assert result["data"]["compact"]["freshness_by_capability"]["chips.margin"]["status"] == "missing"
    assert result["data"]["compact"]["freshness_by_capability"]["chips.institutional"]["status"] == "current"
    assert "read_node.margin" in result["missing"]


def test_sql_deadline_is_enforced_and_next_node_has_clean_read_session(db):
    execution = ReadExecution(db, (CapabilityReadNode("slow", timeout_seconds=0.02), CapabilityReadNode("fast")))
    assert execution.run("slow", lambda session: session.execute(text(
        "WITH RECURSIVE x(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM x WHERE n<100000000) SELECT sum(n) FROM x"
    )).scalar()) is None
    assert execution.run("fast", lambda session: session.execute(text("SELECT 42")).scalar()) == 42
    assert execution.runs[0]["status"] == "timeout"
    assert execution.runs[0]["duration_ms"] < 2000
    assert execution.runs[1]["status"] == "completed"
    assert db.execute(text("PRAGMA query_only")).scalar() == 0


def test_read_session_forbids_writes_and_dedupes_success(db):
    execution = ReadExecution(db, (CapabilityReadNode("write"), CapabilityReadNode("read")))
    execution.run("write", lambda session: session.execute(text("CREATE TABLE forbidden (n INTEGER)")))
    assert execution.runs[0]["status"] == "error"
    call = Mock(return_value={"ok": True})
    assert execution.run("read", call) == execution.run("read", call)
    call.assert_called_once()
    assert db.execute(text("SELECT name FROM sqlite_master WHERE name='forbidden'")).first() is None


@pytest.mark.parametrize("mode", ["data_only", "brief", "full"])
@pytest.mark.parametrize("level", ["compact", "standard", "full"])
def test_modes_and_projection_share_one_graph_and_dispatch(db, mode, level):
    payload = AiAskRequest(question="2328", target={"type": "tw_stock", "id": "2328"}, mode=mode,
        payload_level=level, selection={"include": ["chips.institutional", "fundamentals.revenue"]},
        realtime_policy="cache_only", allow_llm=False, allow_external_fetch=False, allow_write=False)
    plan = query_plan.build_query_plan(payload=payload, scope_type="stock", question_intent="general", effective_mode=mode)
    assert plan.reader_profile == "capability_graph"
    assert set(plan.required_readers) == {"identity", "institutional", "revenue", "selected_freshness"}
    policy = {"query_plan": plan.as_dict(), "can_external_fetch": False}
    dispatch = {"data_only": ask_execution._read_data_only, "brief": ask_execution._build_brief, "full": ask_execution._generate_report}[mode]
    with patch.object(ask_execution.tools, "read_stock_context", return_value={}) as reader, \
            patch.object(ask_execution.orchestrator, "generate_stock_llm_report", return_value={}) as report:
        dispatch(db, payload, "stock", policy=policy)
    if mode == "full":
        assert report.call_args.kwargs["read_context"] == {}
    reader.assert_called_once()
    assert reader.call_args.kwargs["market_data_params"]["external_fetch_allowed"] is False


def test_read_ownership_never_derives_acquisition_from_fill_operations():
    assert capability_contract.CAPABILITY_RESOLUTION_REGISTRY[("stock", "chips.margin")].operation == "tw.refresh_margin"
    assert set(compile_tw_stock_read_plan(["chips.margin"])) == {"identity", "margin", "selected_freshness"}
    assert "source_health" not in compile_tw_stock_read_plan(["data.freshness"])


def test_registry_order_is_topological_and_executed_once(db, dependencies):
    from app.ai.capability_resolution_registry import TW_STOCK_READ_NODES

    for node_id in TW_STOCK_READ_NODES:
        for dependency in TW_STOCK_READ_NODES[node_id].depends_on:
            assert list(TW_STOCK_READ_NODES).index(dependency) < list(TW_STOCK_READ_NODES).index(node_id)
    result = read(db, dependencies, ["technical.structure", "chips.institutional"])
    assert nodes(result) == result["read_execution"]["planned_nodes"]
    assert "quote" not in nodes(result)
    assert "intraday" not in nodes(result)


def test_canonical_bar_reads_share_only_identical_request_inputs(db):
    from app.market.tw_bar_service import TaiwanBarService, taiwan_bar_read_scope

    result = Mock()
    result.model_copy.return_value = result
    with patch.object(TaiwanBarService, "_read_daily_bars", return_value=result) as reader:
        with taiwan_bar_read_scope():
            with Session(db.get_bind()) as other:
                TaiwanBarService(db).read_bars(instrument_id="2328", interval="1d", limit=260, include_partial=False)
                TaiwanBarService(other).read_bars(instrument_id="2328", interval="1d", limit=260, include_partial=False)
                assert reader.call_count == 1
                TaiwanBarService(db).read_bars(instrument_id="2328", interval="1d", limit=260, include_partial=True)
                assert reader.call_count == 2
                TaiwanBarService(db).read_bars(instrument_id="2328", interval="1d", limit=120, include_partial=False)
                assert reader.call_count == 3
        TaiwanBarService(db).read_bars(instrument_id="2328", interval="1d", limit=260, include_partial=False)
        assert reader.call_count == 4


@pytest.mark.parametrize("mode", ["data_only", "brief", "full"])
def test_public_v4_preserves_partial_evidence_in_one_read_graph(db, dependencies, mode):
    from app.ai import ask as ask_module

    StockMaster.__table__.create(db.get_bind())
    db.add(StockMaster(stock_id="2328", stock_name="Test", market="TWSE", instrument_type="stock"))
    db.commit()
    dependencies.market_service.get_latest_stock_margin_trade.side_effect = TimeoutError("bounded")
    payload = AiAskRequest(contract_version="omi.decision.v4", question="2328 selected evidence",
        target={"type": "tw_stock", "id": "2328", "market": "TW"}, mode=mode,
        output="evidence_only", selection={"include": ["chips.institutional", "chips.margin"], "max_response_bytes": 100000},
        diagnostics_level="debug", realtime_policy="cache_only", allow_llm=False, allow_external_fetch=False, allow_write=False)
    with patch.object(ask_module.tools, "read_stock_context", side_effect=lambda **kwargs: read(
        db, dependencies, ["chips.institutional", "chips.margin"],
    )) as reader, patch.object(ask_module.agentic_tools, "run_tw_stock_tool_session", side_effect=AssertionError("no acquisition")), \
            patch.object(ask_module.portfolio_service, "get_position_context_for_scope", return_value=None):
        response = ask_module.ask(db, payload)
    reader.assert_called_once()
    assert response["contract_version"] == "omi.decision.v4"
    assert response["ok"] is True
    assert response["evidence"]["data"]["chips.institutional"]["foreign_investor_net"] == 100
    # A missing required capability keeps the existing blocked quality gate;
    # fail-soft preserves the independent usable facts without upgrading it.
    assert response["evidence"]["quality"]["status"] == "blocked"
    assert response["evidence"]["quality"]["capabilities"]["chips.institutional"]["facts_usable"] is True
    assert response["evidence"]["quality"]["capabilities"]["chips.margin"]["facts_usable"] is False
    assert response["execution"]["tool_runs"] == []
    assert any(row["status"] == "timeout" for row in response["execution"]["query_plan"]["read_execution"]["nodes"])


def test_advanced_indicator_selection_does_not_derive_other_capabilities():
    from app.market import tw_technical_service as technical
    from app.market.technical_parameters import get_technical_analysis_parameters

    with patch.object(technical, "build_swing_evidence", side_effect=AssertionError("unselected swings")), \
            patch.object(technical, "build_relative_strength", side_effect=AssertionError("unselected benchmark")), \
            patch.object(technical, "build_breakout_evidence", side_effect=AssertionError("unselected breakout")):
        result = technical.TaiwanTechnicalService().calculate_advanced(
            points=[], canonical_points=[], benchmark_points=[], parameters=get_technical_analysis_parameters(),
            requested_capabilities={"technical.indicators", "daily.ohlcv"},
        )
    assert result["swings"] == {}
    assert result["relative_strength"] == {}


@pytest.mark.parametrize("overrides,trusted", [
    ({"realtime_policy": "cache_only"}, True),
    ({"allow_external_fetch": False}, True),
    ({}, False),
    ({"tool_budget": {"max_calls": 0}}, True),
    ({"tool_budget": {"max_external_fetches": 0}}, True),
    ({"refresh_policy": {"mode": "off"}}, True),
    ({"refresh_policy": {"before_answer": False}}, True),
    ({"selection": {"required": ["daily.ohlcv"]}}, True),
])
def test_graph_quote_acquisition_respects_request_authority_and_budget(db, overrides, trusted):
    from app.ai import ask as ask_module

    StockMaster.__table__.create(db.get_bind())
    db.add(StockMaster(stock_id="2328", stock_name="Test", market="TWSE", instrument_type="stock"))
    db.commit()
    args = {
        "contract_version": "omi.decision.v4", "question": "2328 selected evidence",
        "target": {"type": "tw_stock", "id": "2328", "market": "TW"},
        "mode": "data_only", "output": "evidence_only",
        "selection": {"required": ["quote.auction"]},
        "allow_external_fetch": True, "realtime_policy": "prefer_live", **overrides,
    }

    class ReadStarted(BaseException):
        pass

    with patch.object(ask_module.tools, "acquire_taiwan_quote_evidence_projection") as acquire, \
            patch.object(ask_module.portfolio_service, "get_position_context_for_scope", return_value=None), \
            patch.object(ask_module, "_read_data_only", side_effect=ReadStarted):
        with pytest.raises(ReadStarted):
            ask_module.ask(db, AiAskRequest(**args), server_policy=ask_module.AiAskServerPolicy(
                can_external_fetch=trusted,
            ))
    acquire.assert_not_called()


@pytest.mark.parametrize("failure", [None, TimeoutError("bounded")])
def test_graph_quote_attempt_consumes_command_budget_before_other_fills(db, failure):
    from app.ai import ask as ask_module

    StockMaster.__table__.create(db.get_bind())
    db.add(StockMaster(stock_id="2328", stock_name="Test", market="TWSE", instrument_type="stock"))
    db.commit()
    payload = AiAskRequest(
        contract_version="omi.decision.v4", question="2328 auction",
        target={"type": "tw_stock", "id": "2328", "market": "TW"},
        mode="data_only", output="evidence_only", allow_external_fetch=True,
        selection={"required": ["quote.auction"]}, realtime_policy="prefer_live",
        tool_budget={"max_calls": 1, "max_external_fetches": 1},
    )
    before = payload.model_dump()

    class ToolStageReached(BaseException):
        pass

    with patch.object(ask_module.portfolio_service, "get_position_context_for_scope", return_value=None), \
            patch.object(ask_module.tools, "acquire_taiwan_quote_evidence_projection", side_effect=failure) as acquire, \
            patch.object(ask_module, "_read_data_only", return_value=("omi.read_stock_context", {"freshness": {"is_current": True}})) as reader, \
            patch.object(ask_module.ask_stages, "execute_tool_stages", side_effect=ToolStageReached) as stage:
        with pytest.raises(ToolStageReached):
            ask_module.ask(db, payload, server_policy=ask_module.AiAskServerPolicy(can_external_fetch=True))
    acquire.assert_called_once()
    reader.assert_called_once()
    assert stage.call_args.kwargs["payload"].tool_budget["max_calls"] == 0
    assert stage.call_args.kwargs["payload"].tool_budget["max_external_fetches"] == 0
    assert payload.model_dump() == before
