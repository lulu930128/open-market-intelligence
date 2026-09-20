from dataclasses import fields
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.ai.capability_contract import project_selected_data
from app.ai.query_plan import build_query_plan
from app.ai.schemas import AiAskRequest
from app.ai.market_context.taiwan_stock import TaiwanStockDependencies, read_stock_technical_context


@pytest.mark.parametrize("extra", [[], ["technical.relative_strength"]])
def test_query_plan_records_map_dependencies_without_dropping_mixed_selection(extra):
    payload = AiAskRequest(
        question="Read cached Price Map", mode="data_only", output="evidence_only",
        selection={"required": ["technical.price_map", *extra]},
    )
    plan = build_query_plan(payload=payload, scope_type="stock", question_intent="general", effective_mode="data_only", target_market="TW")
    if extra:
        assert "build_tw_stock_technical_evidence" in plan.required_readers
    else:
        assert plan.required_readers == ("get_stock", "build_tw_stock_price_map")
    assert plan.external_refresh_allowed is False


@pytest.mark.parametrize("timeframe,status,usable", [
    ("weekly", "ready", True), ("monthly", "partial", False),
])
def test_map_only_selection_calls_canonical_map_without_unrequested_readers(timeframe, status, usable):
    unused = Mock(side_effect=AssertionError("Unrequested reader executed"))
    stock = SimpleNamespace(stock_id="2330", stock_name="台積電", market="TWSE")
    price_map = {
        "version": "tw.stock.price_map.v4", "stock_id": "2330", "status": status,
        "requested_timeframe": timeframe, "structure_timeframe": timeframe,
        "decision_usable": usable, "reference": {"trade_date": "2026-09-14", "freshness_status": "current"},
        "corporate_action": {"coverage_status": "complete"}, "zones": [],
        "missing": [] if usable else ["completed_period_input_not_usable"],
        "warnings": ["history warning"], "source_refs": [{"type": "derived", "name": "app.market.stock_price_map"}],
    }
    reader = Mock(return_value=price_map)
    deps = TaiwanStockDependencies(**{
        **{field.name: unused for field in fields(TaiwanStockDependencies)},
        "stock_service": SimpleNamespace(get_stock=Mock(return_value=stock)),
        "build_tw_stock_price_map": reader,
        "now": lambda: datetime(2026, 9, 14, 10, tzinfo=timezone.utc),
    })
    context = read_stock_technical_context(None, "2330", dependencies=deps, market_data_params={
        "requested_capabilities": ["target.identity", "technical.price_map", "data.freshness"],
        "capability_parameters": {"technical.price_map": {"timeframe": timeframe}},
    })
    assert reader.call_count == 1
    assert reader.call_args.kwargs["timeframe"] == timeframe
    unused.assert_not_called()
    assert context["missing"] == price_map["missing"]
    assert context["warnings"] == price_map["warnings"]
    assert context["data"]["compact"]["freshness_by_capability"]["technical.price_map"]["decision_usable"] is usable
    projected, unavailable = project_selected_data(response={"result": context}, selection={
        "required": ["technical.price_map"], "optional": [], "fields": {}, "limits": {},
    })
    assert not unavailable
    assert projected["technical.price_map"]["requested_timeframe"] == timeframe
    reader.side_effect = RuntimeError("map calculation failed")
    failed = read_stock_technical_context(None, "2330", dependencies=deps, market_data_params={
        "requested_capabilities": ["technical.price_map"],
    })
    assert failed["missing"] == ["technical.price_map"]
    assert failed["data"]["price_map"] is None
    assert "map calculation failed" in failed["warnings"][0]
