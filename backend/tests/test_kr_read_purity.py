"""Read/command boundary regressions without provider IO or production storage."""

from contextlib import ExitStack
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.kr_market import service
from app.kr_market.source_health import build_kr_source_health
from app.routers import kr_market as routes


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    service._KR_STOCK_INTRADAY_CACHE.clear()
    service._KR_INDEX_INTRADAY_CACHE.clear()
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.mark.parametrize("reader,kwargs", [
    (service.get_kr_stock_intraday_trend, {"symbol": "005930"}),
    (service.get_kr_index_intraday_trend, {"index_id": "KOSPI"}),
    (service.list_kr_ohlc_chart_data, {"symbol": "005930"}),
    (service.list_kr_index_ohlc_chart_data, {"index_id": "KOSPI"}),
    (build_kr_source_health, {"symbol": "005930"}),
    (service.get_kr_index_summary, {}),
])
def test_cold_read_never_acquires_or_writes(db, reader, kwargs):
    with ExitStack() as stack:
        for method in ("commit", "flush", "add", "add_all", "delete"):
            stack.enter_context(patch.object(db, method, side_effect=AssertionError(f"read called {method}")))
        spies = [stack.enter_context(patch.object(service, name, side_effect=AssertionError("read acquired provider")))
                 for name in ("fetch_yahoo_chart_payload", "fetch_naver_index_intraday_page_payload",
                              "fetch_naver_index_realtime_payload", "fetch_krx_daily_price_payload",
                              "fetch_naver_index_chart_payload")]
        result = reader(db, **kwargs)
        assert isinstance(result, dict)
        for spy in spies:
            spy.assert_not_called()


@pytest.mark.parametrize("endpoint,kwargs", [
    (routes.get_kr_stock_intraday_chart, {"symbol": "005930", "refresh": True}),
    (routes.get_kr_index_intraday_chart, {"index_id": "KOSPI", "refresh": True}),
    (routes.get_kr_index_intraday_chart, {"index_id": "KOSPI", "reload_all": True}),
    (routes.get_kr_ohlc_chart_data, {"symbol": "005930", "ensure_history": True}),
    (routes.get_kr_index_ohlc_chart, {"index_id": "KOSPI", "ensure_history": True}),
])
def test_deprecated_get_flags_are_rejected_before_dispatch(db, endpoint, kwargs):
    with patch.object(db, "commit", side_effect=AssertionError("GET wrote")):
        with pytest.raises(HTTPException) as error:
            endpoint(db=db, **kwargs)
    assert error.value.status_code == 400
    assert "cache-only" in error.value.detail


def test_read_cannot_enable_external_fetch_or_reload(db):
    for reader, kwargs in (
        (service.get_kr_stock_intraday_trend, {"symbol": "005930", "external_fetch_allowed": True}),
        (service.get_kr_index_intraday_trend, {"index_id": "KOSPI", "reload_all": True}),
        (service.list_kr_ohlc_chart_data, {"symbol": "005930", "ensure_history": True}),
    ):
        with pytest.raises(ValueError, match="cache-only"):
            reader(db, **kwargs)


def test_source_health_exposes_rollout_separately_and_resolves_kosdaq_master(db, monkeypatch):
    from app.config import settings
    from app.db.models import KRStockMaster
    db.add(KRStockMaster(symbol="123456.KQ", local_code="123456", market_segment="KOSDAQ", asset_type="stock"))
    db.commit()
    monkeypatch.setattr(settings, "kr_canonical_daily_enabled", False)
    with patch.object(db, "commit", side_effect=AssertionError("health read wrote")):
        health = build_kr_source_health(db, symbol="123456")
    assert health["filters"]["symbol"] == "123456.KQ"
    daily = health["resolved_datasets"]["kr.daily.ohlcv"]
    assert daily["active_reader"] == "legacy_daily_compatibility"
    assert daily["rollout_status"] == "disabled"
    assert daily["freshness_status"] == "missing"
    assert not daily["decision_usable"]
    assert "KR_CANONICAL_DAILY_ROLLOUT_DISABLED" in daily["limitations"]
    from app.ai import ask as ai_ask
    from app.ai.schemas import AiAskRequest
    with patch.object(db, "commit", side_effect=AssertionError("outward health wrote")):
        response = ai_ask.ask(db=db, payload=AiAskRequest(contract_version="omi.decision.v4",
            question="Read saved source health", target={"type": "source_health", "id": "kr", "market": "KR"},
            mode="data_only", realtime_policy="cache_only",
            market_data_params={"market": "kr", "target": "123456"},
            selection={"required": ["diagnostics.source_health"]},
            refresh_policy={"mode": "off", "before_answer": False}),
            server_policy=ai_ask.AiAskServerPolicy())
    assert "evidence" in response, response
    outward = response["evidence"]["data"]["diagnostics.source_health"]["resolved_datasets"]["kr.daily.ohlcv"]
    assert outward["rollout_status"] == "disabled"
    assert not outward["decision_usable"]
    assert response["execution"]["refresh_reconciliation"]["provider_fetch_attempted"] is False


@pytest.mark.parametrize("kind,args", [("stock", {"symbol": "005930"}), ("index", {"index_id": "KOSPI"})])
def test_ai_read_and_explicit_refresh_have_distinct_dispatch_and_budget(db, kind, args):
    from app.ai.agentic_execution import _execute_tool
    from app.ai.agentic_policy import ALLOWED_TOOLS
    from app.ai.capability_contract import EXECUTABLE_FILL_OPERATIONS, FILL_OPERATION_PRODUCED_CAPABILITIES
    read_name = f"kr.read_{kind}_intraday_trend"
    command_name = f"kr.refresh_{kind}_intraday_trend"
    assert not ALLOWED_TOOLS[read_name].external_fetch
    assert ALLOWED_TOOLS[command_name].external_fetch
    assert read_name not in EXECUTABLE_FILL_OPERATIONS
    assert FILL_OPERATION_PRODUCED_CAPABILITIES[command_name] == ("intraday.bars",)
    with patch.object(service, f"get_kr_{kind}_intraday_trend", return_value={}) as reader:
        with patch.object(service, f"refresh_kr_{kind}_intraday_trend", return_value={}) as command:
            _execute_tool(db, read_name, args)
            reader.assert_called_once()
            assert reader.call_args.kwargs["external_fetch_allowed"] is False
            command.assert_not_called()
            _execute_tool(db, command_name, args)
            command.assert_called_once()
            if kind == "index":
                assert command.call_args.kwargs["max_pages"] == 1


def test_bar_reference_cannot_be_promoted_to_live_trade_or_decision():
    from datetime import datetime, timezone
    from app.market.calendar_status import build_kr_calendar_status
    from app.kr_market.intraday_reference import build_intraday_price_reference
    calendar = build_kr_calendar_status(now=datetime(2026, 9, 11, 1, 1, tzinfo=timezone.utc))
    summary = {"source": "yahoo_finance_chart", "points": [{"time": "2026-09-11T10:00:00+09:00", "price": 100}]}
    reference = build_intraday_price_reference(summary, calendar_status=calendar)
    assert reference["price"] == 100
    assert reference["facts_usable"]
    assert reference["quote_semantics"] == "intraday_bar_close_reference"
    assert not reference["is_live"] and not reference["last_trade_available"]
    assert not reference["decision_usable"] and not reference["usable_for_intraday"]
    assert reference["freshness"]["status"] != "live"
    for malformed in (float("nan"), float("inf"), -1, 0, True, "100"):
        summary["points"][0]["price"] = malformed
        assert build_intraday_price_reference(summary, calendar_status=calendar) == {}
