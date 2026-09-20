from copy import deepcopy

import pytest

from app.ai import query_plan, decision_envelope_v4
from app.ai.schemas import AiAskRequest
from app.ai import ask as ai_ask
from app.config import settings
from test_tw_public_quote_platform import db


def plan(question, *, market=True, selection=None):
    return query_plan.build_query_plan(
        payload=AiAskRequest(question=question, selection=selection or {},
            target={"type": "market", "market": "TW"} if market else {"type": "tw_stock", "id": "6147"}),
        scope_type="market" if market else "stock", question_intent="general",
        effective_mode="data_only", target_market="TW",
    )


@pytest.mark.parametrize("question,required,excluded", [
    ("現在台股大盤、漲跌家數、量能、熱門族群", {"market.indices", "market.breadth", "market.volume_state", "market.hot_groups"}, {"screening.ranking", "market.institutional_flow"}),
    ("掃描全市場接近支撐／壓力的股票", {"screening.price_map"}, {"screening.ranking"}),
    ("不要查法人排行，保留熱門族群", {"market.hot_groups"}, {"screening.ranking", "market.institutional_flow"}),
    ("不要省略熱門族群", {"market.hot_groups"}, {"screening.ranking"}),
    ("今天漲幅前10名", {"screening.intraday"}, {"screening.ranking"}),
])
def test_market_question_matrix(question, required, excluded):
    selected = set(plan(question).selected_capabilities)
    assert required <= selected
    assert not selected & excluded
    assert selected <= required | {"target.identity", "data.freshness"}


@pytest.mark.parametrize("separator", ["？", "！", "?", "!", "\n", "\r\n", "，", "。", "；"])
def test_negation_after_sentence_boundary_preserves_positive_market_request(separator):
    result = plan(f"現在台股大盤、漲跌家數、量能、熱門族群怎麼看{separator}不要查法人排行。")
    assert set(result.selected_capabilities) == {
        "target.identity", "data.freshness", "market.indices", "market.breadth",
        "market.volume_state", "market.hot_groups",
    }
    # Exclusion also stops at the same boundary when it precedes a request.
    assert "market.hot_groups" in plan(f"不要查法人排行{separator}熱門族群").selected_capabilities


@pytest.mark.parametrize("question,market,required", [
    ("掃描全市場目前接近支撐或壓力價位帶的股票，用 Price Map 列出名單。", True, {"screening.price_map"}),
    ("現在台股大盤、漲跌家數、量能、熱門族群怎麼看？不要查法人排行。", True,
     {"market.indices", "market.breadth", "market.volume_state", "market.hot_groups"}),
    ("不要查法人排行，保留熱門族群", True, {"market.hot_groups"}),
    ("今天漲幅前10名", True, {"screening.intraday"}),
    ("2330 今天1分K＋既有技術結構，不要用昨日日K冒充", False, {"intraday.bars", "technical.structure"}),
    ("2330現在收盤試搓，和最後成交分開", False, {"quote.auction", "quote.snapshot"}),
])
@pytest.mark.parametrize("atlas_enabled", [False, True])
def test_ask_request_pipeline_routes_before_evidence_io(db, monkeypatch, question, market, required, atlas_enabled):
    # Exercise target resolution, question understanding and automatic selection
    # in the production ask entry; stop before evidence acquisition/execution.
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", atlas_enabled)
    build = query_plan.build_query_plan
    captured = []

    class Planned(Exception):
        pass

    def capture_plan(**kwargs):
        captured.append(build(**kwargs))
        raise Planned

    monkeypatch.setattr(query_plan, "build_query_plan", capture_plan)
    with pytest.raises(Planned):
        ai_ask.ask(db=db, payload=AiAskRequest(
            contract_version="omi.decision.v4",
            question=question, mode="data_only", output="evidence_only", realtime_policy="cache_only",
            target={"type": "market", "market": "TW"} if market else {"type": "tw_stock", "id": "2330"},
        ))
    result = captured[0]
    assert required <= set(result.selected_capabilities)
    assert not {"screening.ranking", "market.institutional_flow"} & set(result.selected_capabilities)
    if market:
        assert set(result.selected_capabilities) == required | {"target.identity", "data.freshness"}
    assert ("news.events" in result.optional_selected_capabilities) is atlas_enabled
    if "screening.intraday" in required:
        assert result.selection["parameters"]["screening.intraday"]["limit"] == 10


@pytest.mark.parametrize("selection", [
    {"include": ["market.indices"]},
    {"required": ["market.indices"], "optional": ["news.events"]},
])
def test_atlas_does_not_override_explicit_market_selection(monkeypatch, selection):
    from app.ai.market_context import atlas_context
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", True)
    augmented = atlas_context.selection_with_atlas_shadow(selection, scope_type="market")
    result = plan("掃描全市場接近支撐／壓力的股票", selection=augmented)
    assert set(result.selected_capabilities) == {"target.identity", "data.freshness", "market.indices"}
    assert result.capability_selection_mode == "explicit"


def test_automatic_supplement_preserves_caller_exclusions(monkeypatch):
    from app.ai.market_context import atlas_context
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", True)
    selection = atlas_context.selection_with_atlas_shadow(
        {"exclude": ["market.volume_state"]}, scope_type="market",
    )
    result = plan("現在台股大盤、漲跌家數、量能、熱門族群", selection=selection)
    assert "market.volume_state" not in result.selected_capabilities
    assert "market.hot_groups" in result.selected_capabilities
    assert "news.events" in result.optional_selected_capabilities
    assert "screening.ranking" not in result.selected_capabilities


@pytest.mark.parametrize("question,required", [
    ("掃描全市場目前接近支撐或壓力價位帶的股票，用 Price Map 列出名單。", {"screening.price_map"}),
    ("現在台股大盤、漲跌家數、量能、熱門族群怎麼看？不要查法人排行。",
     {"market.indices", "market.breadth", "market.volume_state", "market.hot_groups"}),
])
def test_public_v4_answer_keeps_nlp_selection_with_optional_atlas(db, monkeypatch, question, required):
    from app.ai.market_context import atlas_context
    import requests
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", True)
    monkeypatch.setattr(atlas_context, "read_shadow_context", lambda **kwargs: {
        "status": "unavailable", "facts_usable": False, "events": [],
        "reason_code": "offline_fixture", "warnings": [],
    })
    def reject_io(*args, **kwargs):
        raise AssertionError("cache-only request must not acquire provider evidence")
    monkeypatch.setattr(requests.sessions.Session, "request", reject_io)
    response = ai_ask.ask(db=db, payload=AiAskRequest(
        contract_version="omi.decision.v4", question=question,
        target={"type": "market", "market": "TW"}, mode="data_only",
        realtime_policy="cache_only", output="evidence_only",
        tool_budget={"max_external_fetches": 0},
    ))
    assert response["contract_version"] == "omi.decision.v4"
    selected = response["execution"]["selection"]
    assert set(selected["required"]) == required | {"target.identity", "data.freshness"}
    assert "news.events" in selected["optional"]


@pytest.mark.parametrize("constraint", ["不要用昨日日K冒充", "不要把昨日日K當成今天分K", "不要用昨日日K替代今天分K"])
def test_substitution_is_not_exclusion_or_positive_evidence_request(constraint):
    result = plan(f"6147 今天1分K＋既有技術結構，{constraint}", market=False)
    assert {"intraday.bars", "technical.structure"} <= set(result.selected_capabilities)
    assert "chart" not in result.excluded_domains
    assert "intraday" not in result.excluded_domains
    assert "日k" not in query_plan._selection_question(constraint)


def test_auction_alias_and_explicit_precedence():
    assert {"quote.auction", "quote.snapshot"} <= set(plan("2330現在收盤試搓，和最後成交分開", market=False).selected_capabilities)
    assert plan("試搓掃描接近支撐股票").selection["parameters"]["screening.price_map"]["lane"] == "indicative"
    result = plan("不要大盤，熱門族群", selection={"include": ["market.indices"]})
    assert set(result.selected_capabilities) == {"target.identity", "data.freshness", "market.indices"}
    assert plan("今天漲幅前10名").selection["parameters"]["screening.intraday"]["limit"] == 10


@pytest.mark.parametrize("capability", ["screening.intraday", "market.hot_groups", "screening.price_map"])
def test_required_rows_survive_budget_or_explicit_error(capability):
    rows = [{"rank": i, "stock_id": str(i), "lineage": "evidence" * 80} for i in range(10)]
    original = {"evidence": {"data": {capability: {"rows": rows}}, "quality": {}}, "execution": {}, "target": {}, "status": {}}
    for budget in (4096, 24000):
        result = decision_envelope_v4._fit_budget(deepcopy(original), selection={"required": [capability], "max_response_bytes": budget, "requested_max_response_bytes": budget})
        if result.get("error"):
            assert result["error"]["code"] == "RESPONSE_BUDGET_TOO_SMALL"
        else:
            assert result["evidence"]["data"][capability]["rows"] == rows


def test_explicit_required_field_cannot_be_summarized_away():
    value = {"points": [{"close": 100, "volume": 10}] * 200}
    result = decision_envelope_v4._fit_budget(
        {"evidence": {"data": {"intraday.bars": value}, "quality": {}}, "execution": {}, "target": {}, "status": {}},
        selection={"required": ["intraday.bars"], "fields": {"intraday.bars": ["points"]}, "max_response_bytes": 4096, "requested_max_response_bytes": 4096},
    )
    assert result["error"]["code"] == "RESPONSE_BUDGET_TOO_SMALL"
