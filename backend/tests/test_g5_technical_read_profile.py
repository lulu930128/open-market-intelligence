"""Bounded G5 read-cost contracts; injected time is not a live latency claim."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.ai import ask as ask_module, read_execution
from app.ai.market_context import taiwan_stock
from app.ai.schemas import AiAskRequest
from app.db.models import StockMaster
from app.market import technical_evidence
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.tw_technical_service import TaiwanTechnicalService
from test_tw_capability_read_execution import db, dependencies  # noqa: F401
from test_tw_technical_service import _series


SELECTIONS = [
    ["technical.indicators"],
    ["technical.structure"],
    ["technical.indicators", "technical.structure"],
]


@pytest.mark.parametrize("selected", SELECTIONS)
@pytest.mark.parametrize("minimal_fields", [False, True])
@pytest.mark.parametrize("node_seconds", [0.25, 16.0])
def test_selected_technical_node_runs_once_and_keeps_deadline(
    db, dependencies, selected, minimal_fields, node_seconds,
):
    """Single/combined fields use one owner call; CPU overrun stays missing."""
    StockMaster.__table__.create(db.get_bind())
    db.add(StockMaster(stock_id="2330", stock_name="Fixture", market="TWSE", instrument_type="stock"))
    db.commit()
    dependencies.stock_service.get_stock.return_value = SimpleNamespace(
        stock_id="2330", stock_name="Fixture", market="TWSE", instrument_type="stock",
    )
    series = _series(count=80)
    bars = Mock(return_value=series)
    clock = [0.0]
    captured = []
    calculate = TaiwanTechnicalService.calculate
    calculations = []

    def counted_calculate(self, *args, **kwargs):
        calculations.append(args[0].requested_interval)
        return calculate(self, *args, **kwargs)

    def owner(**kwargs):
        result = technical_evidence.build_tw_stock_technical_evidence(**kwargs)
        clock[0] += node_seconds
        return result

    dependencies.build_tw_stock_technical_evidence.side_effect = owner

    def reader(**kwargs):
        result = taiwan_stock.read_stock_context(
            db, "2330", dependencies=dependencies,
            market_data_params=kwargs["market_data_params"],
        )
        captured.append(result)
        return result

    selection = {"include": selected}
    if minimal_fields:
        selection["fields"] = {
            key: ["status", "as_of", "warnings" if key.endswith("indicators") else "limitations"]
            for key in selected
        }
    request = AiAskRequest(
        contract_version="omi.decision.v4", question="2330 技術證據",
        target={"type": "tw_stock", "id": "2330"}, selection=selection,
        output="evidence_only", payload_level="summary", realtime_policy="cache_only",
        refresh_policy={"mode": "off", "before_answer": False},
        tool_budget={"max_external_fetches": 0, "total_seconds": 28},
        allow_external_fetch=False, allow_write=False, allow_llm=False,
    )
    with (
        patch.object(read_execution, "monotonic", side_effect=lambda: clock[0]),
        patch.object(ask_module.tools, "read_stock_context", side_effect=reader),
        patch.object(ask_module.agentic_tools, "run_tw_stock_tool_session", side_effect=AssertionError("no acquisition")),
        patch.object(technical_evidence, "TaiwanBarService", return_value=SimpleNamespace(read_bars=bars)),
        patch.object(technical_evidence, "get_technical_analysis_parameters", return_value=get_technical_analysis_parameters(persisted_settings={})),
        patch.object(technical_evidence, "_benchmark_points", return_value=[]),
        patch.object(technical_evidence, "build_tw_sector_benchmark", return_value={"status": "not_available", "points": []}),
        patch.object(TaiwanTechnicalService, "calculate", counted_calculate),
    ):
        response = ask_module.ask(db, request)

    dependencies.build_tw_stock_technical_evidence.assert_called_once()
    dependencies.get_taiwan_stock_event_history.assert_called_once()
    dependencies.market_service.list_stock_ohlc_chart_data.assert_called_once()
    dependencies.acquire_taiwan_quote_evidence.assert_not_called()
    # Daily, weekly, monthly and optional current observation are built once
    # by the existing evidence owner, regardless of capability/field count.
    assert bars.call_count == 4
    assert len(calculations) == 3
    assert dependencies.build_stock_technical_report.call_count == (3 if "technical.structure" in selected else 0)
    assert len(captured) == 1
    runs = captured[0]["read_execution"]["nodes"]
    evidence_runs = [run for run in runs if run["node"] == "technical_evidence"]
    assert len(evidence_runs) == 1
    run = evidence_runs[0]
    assert run["timeout_seconds"] == 15.0
    assert run["duration_ms"] == node_seconds * 1000
    assert run["status"] == ("timeout" if node_seconds > 15 else "completed")
    if node_seconds > 15:
        assert captured[0]["data"]["technical_evidence"] == {}
        assert "read_node.technical_evidence" in captured[0]["missing"]
    else:
        indicators = captured[0]["data"]["technical_evidence"]["indicators"]
        assert indicators["status"] == "partial"  # Corporate history is unqualified.
        assert indicators["decision_usable"] is False
        assert indicators["warnings"]
        if minimal_fields and "technical.indicators" in selected:
            projected = response["evidence"]["data"]["technical.indicators"]
            assert set(projected) <= {"status", "as_of", "warnings"}
            assert projected["status"] == "partial"


@pytest.mark.parametrize("empty", [False, True])
def test_daily_qualification_is_not_replaced_by_complete_intraday(empty):
    series = _series(technical_eligible=False, count=80)
    if empty:
        series = series.model_copy(update={"bars": (), "bar_states": ()})
    with (
        patch.object(technical_evidence, "TaiwanBarService", return_value=SimpleNamespace(read_bars=Mock(return_value=series))),
        patch.object(technical_evidence, "get_technical_analysis_parameters", return_value=get_technical_analysis_parameters(persisted_settings={})),
    ):
        result = technical_evidence.build_tw_stock_technical_evidence(
            db=object(), stock_id="2330", requested_capabilities={"technical.indicators"},
            corporate_event_history={}, intraday_points=[{"close": 100, "volume": 1000}] * 240,
        )
    if empty:
        assert result["status"] == "missing"
        assert result["missing"] == ["tw.daily.ohlcv"]
        assert "indicators" not in result
    else:
        indicators = result["indicators"]
        assert indicators["status"] == "partial"
        assert indicators["decision_usable"] is False
        assert indicators["input_quality"]["reason_codes"]
        assert indicators["timeframes"]["daily"]["current_partial"] is None
