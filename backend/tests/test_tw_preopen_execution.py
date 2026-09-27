from datetime import datetime, timedelta
import json

import pytest
from sqlalchemy import event, text

from app.ai import ask, tools, capability_contract, query_plan
from app.ai.schemas import AiAskRequest
from app.ai import decision_envelope_v4
from app.config import settings
from app.db.models import StockMaster, TaiwanIntradayStockState
from app.market import quote_depth
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_intraday_state import (
    build_tw_intraday_screening_snapshot, build_tw_intraday_group_snapshots,
    persist_taiwan_intraday_stock_states,
)
from test_tw_public_quote_platform import db
from test_twse_mis_realtime_acquisition import _adapter, _payload
import test_tw_intraday_market_capabilities as state_fixtures
from test_tw_session_answers import market_response


NOW = datetime(2026, 8, 26, 8, 45, tzinfo=TAIWAN_TZ)


@pytest.mark.parametrize("symbol", ["2330", "2344"])
@pytest.mark.parametrize("kind", ["natural", "explicit", "mixed", "cache_only"])
@pytest.mark.parametrize("shadow", [False, True])
@pytest.mark.parametrize("mode", ["auto", "data_only"])
def test_public_ask_reads_real_canonical_auction(db, monkeypatch, symbol, kind, shadow, mode):
    import requests
    network_calls = []
    def reject_network(*args, **kwargs):
        network_calls.append(args)
        raise AssertionError("offline production-path test must not use network")
    monkeypatch.setattr(requests.sessions.Session, "request", reject_network)
    if symbol == "2344":
        db.add(StockMaster(stock_id=symbol, stock_name="華邦電", market="TWSE", instrument_type="stock"))
        db.commit()
    if kind == "mixed":
        from test_technical_report import add_daily_history
        add_daily_history(db, stock_id=symbol)
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", shadow)
    from app.ai.market_context import atlas_context
    monkeypatch.setattr(atlas_context, "read_shadow_context", lambda **kwargs: {"status": "unavailable"})
    monkeypatch.setattr(tools, "_now", lambda: NOW)
    raw = json.loads(_payload(trial=True))
    raw["msgArray"][0]["c"] = symbol
    raw["msgArray"][0]["ch"] = f"tse_{symbol}.tw"
    calls = []
    acquire_bundle = quote_depth.acquire_taiwan_quote_evidence_bundle
    read_projection = quote_depth.read_taiwan_quote_evidence_projection
    requested = []

    def acquire(**kwargs):
        requested.append(kwargs["requested_capabilities"])
        bundle = acquire_bundle(kwargs["db"], stock_id=kwargs["stock_id"], requested_at=NOW,
                                requested_capabilities=kwargs["requested_capabilities"],
                                acquisition=_adapter(json.dumps(raw), NOW, calls))
        return quote_depth.project_taiwan_quote_evidence_bundle(db=db, stock_id=symbol, bundle=bundle)

    monkeypatch.setattr(tools, "acquire_taiwan_quote_evidence_projection", acquire)
    monkeypatch.setattr(tools, "read_taiwan_quote_evidence_projection", lambda **kw: read_projection(**kw, requested_at=NOW))
    statements = []
    if kind == "cache_only":
        acquire(db=db, stock_id=symbol, requested_capabilities=("quote.auction",))
        calls.clear()
        requested.clear()
        db.execute(text("PRAGMA query_only=ON"))
        event.listen(db.bind, "before_cursor_execute", lambda conn, cursor, statement, params, context, many: statements.append(statement))
    response = ask.ask(db=db, server_policy=ask.AiAskServerPolicy(can_external_fetch=True), payload=AiAskRequest(
        contract_version="omi.decision.v4", question=f"{symbol} 今天早上試搓多少？相對昨收漲跌多少？這是不是正式成交？" + ("順便看技術面" if kind == "mixed" else ""),
        target={"type": "tw_stock", "id": symbol} if kind == "explicit" else {}, mode=mode, output="decision_with_evidence",
        realtime_policy="cache_only" if kind == "cache_only" else "prefer_live", allow_external_fetch=True,
        selection={"required": ["quote.auction"]} if kind == "explicit" else {},
    ))
    auction = response["evidence"]["data"]["quote.auction"]
    assert response["execution"]["query_plan"]["reader_profile"] == ("standard" if kind == "mixed" else "quote_only")
    assert auction["indicative_match_price"] == 1178
    assert auction["provider"] == "twse_mis"
    assert auction["change_reference"]["auction_change"] == 8
    assert auction["change_reference"]["auction_change_pct"] == pytest.approx(8 / 1170 * 100)
    assert network_calls == []
    assert "試搓" in response["answer"]["text"] or "試撮" in response["answer"]["text"]
    if kind == "cache_only":
        assert calls == requested == []
        assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for s in statements)
    else:
        assert len(calls) == 1
        assert "quote.auction" in requested[0]
    if kind == "mixed":
        assert "technical.structure" in response["execution"]["selection"]["required"]
        technical = response["evidence"]["data"]["technical.structure"]
        assert technical["latest_price"] == 179.0
        assert response["evidence"]["data"]["daily.ohlcv"]


def auction_states(db, now=NOW):
    rows = []
    for i, price in enumerate((109, 102, 98)):
        symbol = str(9001 + i)
        db.add(StockMaster(stock_id=symbol, stock_name=symbol, market="TWSE", instrument_type="stock", industry="半導體業", is_active=True))
        row = state_fixtures.TaiwanIntradayMarketCapabilityTests._stock_state_row(symbol, "TWSE", price, 100, now)
        row.update(current_price=None, has_actual_trade=False, price_as_of=None,
                   indicative_match_available=True, indicative_match_price=price, market_session="preopen")
        rows.append(row)
    db.commit()
    persist_taiwan_intraday_stock_states(db, rows=rows, now=now)
    return [r["code"] for r in rows]


def test_indicative_ranking_and_groups_share_pure_read_lane(db):
    ids = auction_states(db)
    before = [(s.id, s.current_price, s.has_actual_trade) for s in db.query(TaiwanIntradayStockState).all()]
    db.execute(text("PRAGMA query_only=ON"))
    result = build_tw_intraday_screening_snapshot(db, generated_at=NOW,
                parameters={"lane": "indicative", "universe": {"stock_ids": ids}, "limit": 2})
    assert [r["stock_id"] for r in result["rows"]] == ids[:2]
    assert [r["value"] for r in result["rows"]] == pytest.approx([9, 2])
    assert result["lane"] == "indicative" and result["provisional"]
    assert result["facts_usable_for_ranking"] and not result["decision_usable"]
    for row in result["rows"]:
        assert row["price_semantics"] == "indicative_match" and not row["has_actual_trade"]
        assert row["lineage"]["raw_result_ids"]
        assert not row["decision_usable"] and not row["execution_grade_usable"]
        for metric in ("estimated_trade_value", "cumulative_volume_lots", "five_minute_return", "fifteen_minute_return"):
            assert row[metric] is None
    groups = build_tw_intraday_group_snapshots(db, generated_at=NOW)["hot_groups"]
    group = next(g for g in groups["groups"] if g["classified_count"] == 3)
    assert group["mean_return_pct"] == pytest.approx(3)
    assert group["facts_usable_for_ranking"] and group["provisional"]
    assert not group["decision_usable"] and not groups["decision_usable"]
    assert group["estimated_trade_value"] is None and group["median_five_minute_return"] is None
    assert group["lineage"]["raw_result_ids"]
    from app.market.tw_market_dashboard import _project_hot_groups_for_dashboard
    from app.market.tw_market_dashboard_schemas import TaiwanDashboardGroupRead
    projected = _project_hot_groups_for_dashboard(groups, session_phase="preopen")
    assert projected
    for item in projected:
        outward = TaiwanDashboardGroupRead.model_validate(item).model_dump()
        assert outward["lane"] == "indicative" and outward["provisional"]
        assert outward["price_semantics"] == "indicative_match"
        assert outward["observation_freshness"] == "current"
        assert outward["lineage"]["raw_result_ids"]
        assert not outward["decision_usable"] and not outward["execution_grade_usable"]
    assert [(s.id, s.current_price, s.has_actual_trade) for s in db.query(TaiwanIntradayStockState).all()] == before
    assert not db.dirty


@pytest.mark.parametrize("failure", ["stale", "prior_date", "future", "missing_reference", "missing_lineage"])
def test_indicative_invalid_observations_cannot_rank(db, failure):
    ids = auction_states(db)
    for state in db.query(TaiwanIntradayStockState).all():
        if failure == "stale":
            state.event_time = NOW - timedelta(minutes=5)
        elif failure == "prior_date":
            state.trade_date = NOW.date() - timedelta(days=1)
        elif failure == "future":
            state.event_time = NOW + timedelta(seconds=1)
        elif failure == "missing_reference":
            state.previous_close = None
        else:
            state.lineage_complete = False
    db.commit()
    ranking = build_tw_intraday_screening_snapshot(db, generated_at=NOW, parameters={"lane": "indicative"})
    groups = build_tw_intraday_group_snapshots(db, generated_at=NOW)["hot_groups"]
    assert not ranking["rows"] and not ranking["facts_usable_for_ranking"]
    assert not groups["facts_usable_for_ranking"]


def test_indicative_does_not_fill_trade_metrics_or_regular_lane(db):
    auction_states(db)
    for metric in ("estimated_trade_value", "five_minute_return", "cumulative_volume_lots"):
        result = build_tw_intraday_screening_snapshot(db, generated_at=NOW, parameters={"lane": "indicative", "metric": metric})
        assert result["status"] == "unavailable" and not result["rows"]
    actual = build_tw_intraday_screening_snapshot(db, generated_at=NOW.replace(hour=9, minute=1))
    assert actual["lane"] == "actual" and actual["rows"] == []
    assert build_tw_intraday_group_snapshots(db, generated_at=NOW.replace(hour=9, minute=1))["hot_groups"]["lane"] == "actual"


@pytest.mark.parametrize("question,capability", [
    ("今天台股盤前有哪些明顯強勢的股票？試搓漲幅比較大的有哪些？", "screening.intraday"),
    ("現在台股記憶體族群試搓狀況如何？哪些股票偏強、哪些偏弱？", "market.hot_groups"),
    ("現在台股試搓有沒有接近漲停或跌停的股票？", "screening.intraday"),
])
def test_natural_auction_ranking_uses_typed_lane(question, capability):
    plan = query_plan.build_query_plan(payload=AiAskRequest(question=question), scope_type="market", target_market="TW", question_intent="general", effective_mode="data_only")
    assert capability in plan.selected_capabilities
    assert plan.selection["parameters"][capability]["lane"] == "indicative"


@pytest.mark.parametrize("companion", [True, False])
def test_generic_preopen_breadth_separates_formal_trade_and_auction(companion):
    breadth = {"status": "pending", "market_session": "preopen", "advance_count": 0, "decline_count": 0, "unchanged_count": 0}
    if companion:
        breadth["auction_breadth"] = {"status": "provisional", "advance_count": 431, "decline_count": 109, "unchanged_count": 156,
                                    "coverage_count": 696, "universe_count": 1080, "as_of": "2026-09-22T08:40:00+08:00"}
    result = decision_envelope_v4.build(market_response(["market.breadth"], {"breadth": breadth}))
    answer = result["answer"]["text"]
    assert "正式成交尚未開始" in answer
    assert "0 / 0 / 0" not in answer
    assert ("431 / 109 / 156" in answer) is companion


def test_public_market_ask_projects_indicative_without_provider_io(db, monkeypatch):
    import requests
    auction_states(db)
    monkeypatch.setattr(tools, "_now", lambda: NOW)
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", False)
    def reject(*args, **kwargs):
        raise AssertionError("cache-only must not acquire")
    monkeypatch.setattr(requests.sessions.Session, "request", reject)
    monkeypatch.setattr(tools, "acquire_taiwan_quote_evidence_projection", reject)
    db.execute(text("PRAGMA query_only=ON"))
    result = ask.ask(db=db, payload=AiAskRequest(
        contract_version="omi.decision.v4", question="今天台股盤前有哪些明顯強勢的股票或族群？試搓漲幅比較大的有哪些？",
        target={"type": "market", "market": "TW"}, mode="data_only", output="decision_with_evidence", realtime_policy="cache_only",
    ))
    for capability in ("screening.intraday", "market.hot_groups"):
        data = result["evidence"]["data"][capability]
        assert data["lane"] == "indicative" and data["provisional"]
        assert data["facts_usable_for_ranking"]
        assert not data["decision_usable"] and not data["execution_grade_usable"]
    assert "試搓暫定觀測" in result["answer"]["text"]
    assert not result["status"]["readiness"]["decision_ready"]


def test_unrelated_technical_request_does_not_acquire_quote(db, monkeypatch):
    called = []
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", False)
    monkeypatch.setattr(tools, "acquire_taiwan_quote_evidence_projection", lambda **kw: called.append(kw))
    ask.ask(db=db, server_policy=ask.AiAskServerPolicy(can_external_fetch=True), payload=AiAskRequest(
        contract_version="omi.decision.v4", question="2330 日線技術結構", target={"type": "tw_stock", "id": "2330"},
        mode="data_only", realtime_policy="prefer_live", allow_external_fetch=True,
    ))
    assert called == []


def test_acquired_auction_reference_includes_same_request_late_receipt(db):
    calls = []
    received = NOW + timedelta(seconds=2)
    bundle = quote_depth.acquire_taiwan_quote_evidence_bundle(
        db, stock_id="2330", requested_at=NOW, requested_capabilities=("quote.auction",),
        acquisition=_adapter(_payload(trial=True), received, calls),
    )
    projected = quote_depth.project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
    assert len(calls) == 1
    assert projected["change_reference"]["auction_change"] == 8
    assert bundle.quote.resolved.quote.lineage.event_at == NOW
    assert bundle.quote.resolved.quote.lineage.received_at == received
    assert bundle.auction.resolved.auction.lineage.event_at == NOW
