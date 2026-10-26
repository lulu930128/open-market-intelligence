"""Offline G2 answer regression: selected evidence and acquisition are separate axes."""

from copy import deepcopy
from datetime import datetime

import pytest

from app.ai import answer_composer, capability_contract, decision_envelope_v4, realtime_contract


EVENT = "2026-10-19T08:46:00+08:00"


def auction_observation(*, price=123, status="current"):
    return {
        "kind": "quote_auction", "status": status, "available": True,
        "session_phase": "preopen_auction", "market_session_status": "preopen_auction",
        "applicability_status": "applicable", "availability_status": "available",
        "indicative_match_available": price is not None, "indicative_match_price": price,
        "indicative_match_volume_lots": 42 if price is not None else None,
        "auction_time": EVENT, "provider_event_time": EVENT,
        "provider": "twse_mis", "source": "twse_mis",
        "freshness": {"status": status, "is_current": status == "current"},
    }


def receipt(status):
    return {
        "requested": True, "attempted": status != "unverified", "status": status,
        "providers_attempted": ["twse_mis"] if status != "unverified" else [],
        "resource_attempts": [], "limitations": ["fixture_diagnostic"],
        "persistence": {"status": "completed", "opaque_receipt": "keep-me"},
    }


def response(auction=None, *, acquisition=None, requested=False, allowed=False,
             output="decision_with_evidence", mode="data_only", realtime_policy="cache_only"):
    selection = capability_contract.normalize_selection(
        selection={"required": ["quote.auction"], "optional": ["quote.snapshot", "quote.order_book"]},
        output=output, realtime_policy=realtime_policy, payload_level="standard",
        scope_type="stock", target_market="TW", question_intent="quote",
    )
    components = {"trade": None}
    if auction is not None:
        components["auction"] = auction
    return {
        "kind": "ai_ask", "contract_version": "omi.ai.ask.v2", "ok": True,
        "request_status": "completed", "question": "2221 盤前試撮多少？",
        "target": {"type": "tw_stock", "id": "2221", "market": "TW"},
        "mode": {"requested": mode, "effective": mode, "response": "analysis", "payload_level": "standard"},
        "analysis": {"question_intent": "quote", "human_answer": {}},
        "result": {"kind": "stock_brief", "data": {
            "compact": {"quote": {
                "status": "partial", "price": None, "trade": None,
                "session_phase": "preopen_auction", "price_decision_usable": False,
                "execution_usable": False, "components": components,
            }},
            "provider_contract": {"provider_attempts_by_capability": {
                "quote.auction": acquisition,
                # A different capability's failure must not contaminate auction.
                "quote.snapshot": receipt("partial"),
            } if acquisition else {}},
        }},
        "policy": {"allow_llm": False, "allow_external_fetch": requested,
                   "can_external_fetch": allowed, "response_preferences": {"locale": "zh-TW"}},
        "query_plan": {"selection": selection, "target_type": "stock"},
        "missing": [], "warnings": [], "source_refs": [], "tool_runs": [],
    }


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    annotate = realtime_contract.annotate_selected_data
    monkeypatch.setattr(realtime_contract, "annotate_selected_data", lambda *args, **kwargs: annotate(
        *args, **kwargs, now=datetime.fromisoformat("2026-10-19T08:46:05+08:00"),
    ))


@pytest.mark.parametrize("mode", ["data_only", "brief"])
@pytest.mark.parametrize("case,expected", [
    ("not_requested", "本次未要求更新，未查詢來源"),
    ("denied", "政策不允許執行"),
    ("not_executed", "本次未執行來源查詢"),
    ("failed", "取得失敗（failed）"),
    ("partial", "取得結果不完整（partial）"),
    ("unverified", "缺少取得回執"),
    ("no_match", "未提供符合條件的試搓撮合價"),
])
def test_missing_quote_explains_acquisition_without_inventing_provider_failure(mode, case, expected):
    acquisition = receipt("completed" if case == "no_match" else case) if case in {
        "failed", "partial", "unverified", "no_match",
    } else None
    source = response(
        auction_observation(price=None) if case == "no_match" else None,
        acquisition=acquisition, requested=case != "not_requested", allowed=case not in {"not_requested", "denied"},
        realtime_policy="cache_only" if case == "not_requested" else "prefer_live", mode=mode,
    )
    original = deepcopy(source)
    result = decision_envelope_v4.build(source)
    text = result["answer"]["text"]
    assert expected in text
    assert "並非正式成交" in text
    assert "不可用於交易決策或執行" in text
    if case != "failed":
        assert "取得失敗" not in text
    if case == "not_requested":
        assert "快取沒有符合條件的目前試搓觀測" in text
        assert "不能據此判定來源沒有資料" in text
    if case in {"failed", "partial", "no_match"}:
        assert "twse_mis" in text
    if case == "unverified":
        assert "本次未查詢來源" not in text
    assert result["status"]["readiness"]["decision_ready"] is False
    assert source == original
    if acquisition:
        assert result["execution"]["refresh_reconciliation"]["capabilities"]["quote.auction"]["primary_reader_acquisition"] == acquisition


@pytest.mark.parametrize("symbol,price", [("2221", 123), ("3055", 127)])
@pytest.mark.parametrize("mode", ["data_only", "brief"])
def test_completed_indicative_survives_partial_actual_trade(symbol, price, mode):
    source = response(auction_observation(price=price), acquisition=receipt("completed"), requested=True,
                      allowed=True, realtime_policy="prefer_live", mode=mode)
    source["target"]["id"] = symbol
    result = decision_envelope_v4.build(source)
    text = result["answer"]["text"]
    assert f"{price} 元" in text and symbol in text
    assert EVENT in text and "twse_mis" in text and "取得程序完成" in text
    assert "取得失敗" not in text and "已過期" not in text
    assert "並非正式成交" in text
    assert result["request_status"] == "completed"
    data = result["evidence"]["data"]["quote.snapshot"]
    assert data.get("trade") is None and data.get("price") is None
    assert data["price_decision_usable"] is False
    assert source["result"]["data"]["compact"]["quote"]["execution_usable"] is False
    quality = result["evidence"]["quality"]["capabilities"]["quote.auction"]
    assert quality["execution_grade_usable"] is False
    realtime = result["evidence"]["realtime"]["quote.snapshot"]
    assert realtime["price_decision_usable"] is False
    assert realtime["execution_grade_usable"] is False


def test_stale_indicative_keeps_event_time_but_is_never_current():
    result = decision_envelope_v4.build(response(auction_observation(status="stale")))
    text = result["answer"]["text"]
    assert "已過期試搓觀測" in text and "不代表目前試搓" in text
    assert EVENT in text and "123 元" in text and "twse_mis" in text
    assert "未查詢來源" in text
    assert not result["status"]["readiness"]["decision_ready"]


def test_missing_price_is_not_zero_or_derived_from_book():
    auction = auction_observation(price=None)
    auction.update(best_bid={"price": 100}, best_ask={"price": 101})
    source = response(auction, acquisition=receipt("completed"), requested=True, allowed=True, realtime_policy="prefer_live")
    source["target"]["id"] = "6151"
    result = decision_envelope_v4.build(source)
    assert "無資料" in result["answer"]["headline"]
    assert "有委託簿也不代表有試搓撮合" in result["answer"]["text"]
    assert "100 元" not in result["answer"]["text"] and "101 元" not in result["answer"]["text"]
    assert result["evidence"]["data"]["quote.auction"]["indicative_match_price"] is None


def test_evidence_only_preserves_same_quality_and_receipts_without_answer():
    source = response(auction_observation(), acquisition=receipt("completed"), requested=True,
                      allowed=True, realtime_policy="require_live")
    factual = decision_envelope_v4.build(source)
    source["query_plan"]["selection"]["output"] = "evidence_only"
    evidence = decision_envelope_v4.build(source)
    assert evidence["answer"] == {}
    assert evidence["evidence"]["data"] == factual["evidence"]["data"]
    assert evidence["evidence"]["quality"]["capabilities"] == factual["evidence"]["quality"]["capabilities"]
    assert evidence["evidence"]["realtime"] == factual["evidence"]["realtime"]
    assert evidence["execution"]["refresh_reconciliation"] == factual["execution"]["refresh_reconciliation"]
    assert evidence["execution"]["selection"]["realtime_policy"] == "require_live"
    assert evidence["execution"]["policy"]["allow_llm"] is False


def test_pure_answer_uses_typed_quality_and_does_not_mutate_evidence():
    auction = auction_observation()
    original = deepcopy(auction)
    answer = answer_composer.build_quote_consumer_answer(
        target={"id": "2221", "market": "TW"}, analysis_digest={"compact_evidence": {"auction": auction}},
        auction_quality={"freshness_status": "stale"},
        auction_reconciliation={"not_attempted_reason": "refresh_not_requested"},
        missing=[], warnings=[], summary_limit=3, response_preferences=None,
    )
    assert "已過期" in answer["headline"] and EVENT in answer["text"]
    assert auction == original


@pytest.mark.parametrize("with_payload", [False, True])
def test_optional_auto_planned_auction_does_not_replace_regular_quote_answer(with_payload):
    source = response(auction_observation(price=None) if with_payload else None)
    source["question"] = "2221 最新報價與技術結構"
    source["query_plan"]["selection"].update(
        required=["quote.snapshot"], optional=["quote.auction"], auto_planned=True,
    )
    source["result"]["data"]["compact"]["quote"].update(
        price=125, session_phase="regular_live", status="current",
    )
    source["analysis"]["human_answer"] = {
        "headline": "2221 最近價格為 125 元", "text": "2221 最近價格為 125 元",
        "summary": ["正常盤報價"], "style": "quote_summary",
    }
    result = decision_envelope_v4.build(source)
    assert result["answer"]["style"] == "quote_summary"
    assert "125 元" in result["answer"]["text"]
    assert "quote.auction" in result["execution"]["selection"]["optional"]


@pytest.mark.parametrize("auction", [None, {"indicative_match_available": True, "indicative_match_price": None}])
def test_completed_receipt_without_explicit_no_match_evidence_stays_unknown(auction):
    result = decision_envelope_v4.build(response(
        auction, acquisition=receipt("completed"), requested=True, allowed=True, realtime_policy="prefer_live",
    ))
    assert "試搓撮合價未確認" in result["answer"]["text"]
    assert "未提供符合條件" not in result["answer"]["text"]


@pytest.mark.parametrize("status", ["failed", "unavailable"])
def test_no_attempted_fetch_does_not_turn_receipt_status_into_provider_failure(status):
    acquisition = {"requested": True, "attempted": False, "status": status}
    result = decision_envelope_v4.build(response(
        acquisition=acquisition, requested=True, allowed=False, realtime_policy="prefer_live",
    ))
    assert "政策不允許執行" in result["answer"]["text"]
    assert "取得失敗" not in result["answer"]["text"]
    assert "來源無法使用" not in result["answer"]["text"]


@pytest.mark.parametrize("refresh", [False, True])
def test_public_ask_with_real_canonical_reader_and_offline_acquisition(monkeypatch, refresh):
    from app.ai import ask, tools
    from app.ai.schemas import AiAskRequest
    from app.config import settings
    from app.market import quote_depth
    from test_twse_mis_realtime_acquisition import _adapter, _db, _payload

    db, engine = _db()
    now = datetime.fromisoformat("2026-08-26T08:45:00+08:00")
    calls = []
    acquired = {}

    def acquire(**kwargs):
        assert refresh, "cache-only must not dispatch acquisition"
        bundle = quote_depth.acquire_taiwan_quote_evidence_bundle(
            db, stock_id="2330", requested_at=now,
            requested_capabilities=kwargs["requested_capabilities"],
            acquisition=_adapter(_payload(trial=True), now, calls),
        )
        projected = quote_depth.project_taiwan_quote_evidence_bundle(db=db, stock_id="2330", bundle=bundle)
        acquired.update(projected)
        return projected

    read = quote_depth.read_taiwan_quote_evidence_projection
    monkeypatch.setattr(tools, "acquire_taiwan_quote_evidence_projection", acquire)
    monkeypatch.setattr(tools, "read_taiwan_quote_evidence_projection", lambda **kw: read(**kw, requested_at=now))
    monkeypatch.setattr(tools, "_now", lambda: now)
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", False)
    try:
        if not refresh:
            db.connection().exec_driver_sql("PRAGMA query_only=ON")
        result = ask.ask(db=db, server_policy=ask.AiAskServerPolicy(can_external_fetch=True), payload=AiAskRequest(
            question="2330 盤前試撮多少？", target={"type": "tw_stock", "id": "2330"},
            mode="data_only", output="decision_with_evidence", contract_version="omi.decision.v4",
            selection={"required": ["quote.auction", "quote.snapshot"]}, allow_llm=False,
            allow_external_fetch=refresh, realtime_policy="prefer_live" if refresh else "cache_only",
            refresh_policy={"before_answer": True},
        ))
        text = result["answer"]["text"]
        outcome = result["execution"]["refresh_reconciliation"]["capabilities"]["quote.auction"]
        assert outcome["provider_fetch_attempted"] is refresh
        if refresh:
            assert len(calls) == 1
            assert "1,178 元" in text and "取得程序完成" in text and "並非正式成交" in text
            assert "2026-08-26T08:45:00+08:00" in text and "twse_mis" in text
            assert acquired["actual_trade_occurred"] is False
            assert acquired["last_trade_available"] is False
            assert outcome["primary_reader_acquisition"] == acquired["provider_attempts_by_capability"]["quote.auction"]
        else:
            assert calls == []
            assert "未要求更新，未查詢來源" in text and "快取沒有符合條件" in text
            assert "取得失敗" not in text
    finally:
        db.close()
        engine.dispose()
