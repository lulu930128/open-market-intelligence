"""Natural public asks must resolve scope before selecting the canonical owner."""
from copy import deepcopy

import pytest

from app.ai import ask as ai_ask, query_plan, scope_resolution
from app.ai.schemas import AiAskRequest
from app.config import settings
from app.db.models import WatchlistGroup
from test_tw_intraday_convergence import NOW, db, persist_stock


NATURAL_QUESTION = "現在台股強弱族群怎麼看？哪些族群盤中最強、哪些較弱？請只用正式成交資料。"


def request(question, **kwargs):
    return AiAskRequest(
        contract_version="omi.decision.v4", question=question,
        mode="brief", output="decision_with_evidence",
        realtime_policy="cache_only", allow_llm=False,
        allow_external_fetch=False, **kwargs,
    )


def capture_public_plan(db, monkeypatch, payload):
    original = query_plan.build_query_plan
    captured = {}

    class Planned(Exception):
        pass

    def capture(**kwargs):
        captured.update(kwargs)
        captured["plan"] = original(**kwargs)
        raise Planned

    monkeypatch.setattr(query_plan, "build_query_plan", capture)
    with pytest.raises(Planned):
        ai_ask.ask(db=db, payload=payload)
    return captured


@pytest.mark.parametrize("question", [
    NATURAL_QUESTION, "台股熱門族群", "強勢族群有哪些", "族群排行",
    "哪些族群盤中最強", "哪些族群最強", "今天哪些題材最強",
    "hot sectors", "sector strength", "sector strength in Taiwan market",
    "台股半導體族群盤中表現如何", "market group performance",
])
@pytest.mark.parametrize("atlas_enabled", [False, True])
def test_natural_auto_scope_selects_hot_groups(db, monkeypatch, question, atlas_enabled):
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", atlas_enabled)
    payload = request(question)
    before = deepcopy(payload.model_dump())
    result = capture_public_plan(db, monkeypatch, payload)
    assert result["scope_type"] == "market"
    assert result["payload"].target["type"] == "market"
    assert result["payload"].target["market"] == "TW"
    assert "market.hot_groups" in result["plan"].selected_capabilities
    assert not any(cap.startswith("watchlist.") for cap in result["plan"].selected_capabilities)
    assert payload.model_dump() == before


@pytest.mark.parametrize("question,target,expected_id", [
    ("自選群組 #3 熱門族群", None, "3"),
    ("watchlist 3 hot sectors", None, "3"),
    ("group #3 sector strength", None, "3"),
    ("核心持股", None, "3"),
    ("核心持股 台股強弱族群", None, "3"),
    ("強勢族群有哪些", {"type": "tw_watchlist", "id": "3"}, "3"),
    ("台股熱門族群", {"type": "tw_watchlist", "label": "核心持股"}, "3"),
])
def test_explicit_watchlist_and_persisted_names_win(db, monkeypatch, question, target, expected_id):
    db.add(WatchlistGroup(id=3, group_name="核心持股", is_active=True))
    db.commit()
    payload = request(question, **({"target": target} if target else {}))
    result = capture_public_plan(db, monkeypatch, payload)
    assert result["scope_type"] == "watchlist"
    assert result["payload"].target["type"] == "tw_watchlist"
    assert result["payload"].target["id"] == expected_id
    assert "watchlist.ranking" in result["plan"].selected_capabilities
    assert "market.hot_groups" not in result["plan"].selected_capabilities


@pytest.mark.parametrize("question,target", [
    ("我的自選", None), ("我的自選群組", None),
    ("我的自選熱門族群", None), ("my group sector strength", None),
    ("這個 group 怎麼看", None),
    ("台股熱門族群", {"type": "tw_watchlist"}),
])
def test_unresolved_watchlist_or_ambiguous_group_still_clarifies(db, question, target):
    result = ai_ask.ask(db=db, payload=request(question, **({"target": target} if target else {})))
    assert result["target"]["type"] == "tw_watchlist"
    assert result["request_status"] == "clarification_required"
    assert "market.hot_groups" not in result["evidence"]["data"]


def test_persisted_market_phrase_name_wins_unless_market_target_is_explicit(db):
    db.add(WatchlistGroup(id=3, group_name="熱門族群", is_active=True))
    db.commit()
    natural = scope_resolution._resolve_scope(db, request("台股熱門族群"))
    assert (natural.selected_scope_type, natural.selected_scope_id) == ("watchlist", "3")
    explicit = scope_resolution._resolve_scope(db, request("台股熱門族群", target={"type": "market", "market": "TW"}))
    assert explicit.selected_scope_type == "market"


@pytest.mark.parametrize("group_name,expected_scope", [
    ("核心持股", "market"), ("半導體", "watchlist"), ("半導體族群", "watchlist"),
])
def test_semiconductor_phrase_respects_actual_persisted_name(db, monkeypatch, group_name, expected_scope):
    db.add(WatchlistGroup(id=3, group_name=group_name, is_active=True))
    db.commit()
    result = capture_public_plan(db, monkeypatch, request("台股半導體族群盤中表現如何"))
    assert result["scope_type"] == expected_scope
    assert ("market.hot_groups" in result["plan"].selected_capabilities) is (expected_scope == "market")
    if expected_scope == "watchlist":
        assert result["payload"].target["id"] == "3"


def test_natural_and_explicit_public_asks_share_persisted_hot_group_projection(db, monkeypatch):
    from app.ai import tools as ai_tools

    persist_stock(db, "2330", 601)
    persist_stock(db, "2454", 120)
    persist_stock(db, "3711", 30)
    monkeypatch.setattr(ai_tools, "_now", lambda: NOW)
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", False)
    natural = ai_ask.ask(db=db, payload=request(NATURAL_QUESTION))
    explicit = ai_ask.ask(db=db, payload=request(
        NATURAL_QUESTION, target={"type": "market", "market": "TW"},
        selection={"required": ["market.hot_groups"]},
    ))
    for response in (natural, explicit):
        assert response["target"]["type"] == "market"
        assert response["request_status"] != "clarification_required"
        assert response["execution"]["tool_runs"] == []
    natural_groups = natural["evidence"]["data"]["market.hot_groups"]
    explicit_groups = explicit["evidence"]["data"]["market.hot_groups"]
    assert natural_groups == explicit_groups
    assert natural_groups["lane"] == "actual"
    assert natural_groups["facts_usable_for_ranking"] is True
    assert natural_groups["decision_usable"] is False
    assert natural_groups["execution_grade_usable"] is False
    assert natural_groups["groups"]
    assert natural_groups["coverage"]["ranking_eligible_count"] == 3
    group = natural_groups["groups"][0]
    assert group["group_id"]
    assert group["group_name"] == "半導體業"
    assert group["lineage"]["raw_result_ids"]
