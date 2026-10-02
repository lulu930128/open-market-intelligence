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


@pytest.mark.parametrize("symbol,word", [("2330", "試搓"), ("2344", "試搓"), ("2330", "試撮"), ("2330", "indicative auction")])
@pytest.mark.parametrize("mixed,explicit", [(False, False), (False, True), (True, False)])
def test_selected_auction_reaches_production_acquisition(db, monkeypatch, symbol, word, mixed, explicit):
    from app.ai import tools as ai_tools
    from app.db.models import StockMaster

    if symbol == "2344":
        db.add(StockMaster(stock_id=symbol, stock_name="華邦電", market="TWSE", instrument_type="stock"))
        db.commit()
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", False)

    class Acquired(BaseException):
        pass

    def acquire(**kwargs):
        assert kwargs["stock_id"] == symbol
        assert "quote.auction" in kwargs["requested_capabilities"]
        raise Acquired

    monkeypatch.setattr(ai_tools, "acquire_taiwan_quote_evidence_projection", acquire)
    with pytest.raises(Acquired):
        ai_ask.ask(db=db, server_policy=ai_ask.AiAskServerPolicy(can_external_fetch=True), payload=AiAskRequest(
            contract_version="omi.decision.v4",
            question=f"{symbol} 現在{word}多少？相對昨收漲跌多少？這是不是正式成交？" + ("＋順便看技術面" if mixed else ""),
            target={"type": "tw_stock", "id": symbol},
            selection={"required": ["quote.auction"]} if explicit else {},
            mode="data_only", output="evidence_only", realtime_policy="prefer_live", allow_external_fetch=True,
        ))


def test_natural_mixed_quote_preserves_technical_evidence():
    result = plan("2330 試搓狀況＋順便看技術面", market=False)
    assert result.reader_profile == "standard"
    assert {"quote.auction", "technical.structure", "daily.ohlcv"} <= set(result.selected_capabilities)


def test_natural_quote_is_bounded_without_explicit_selection():
    result = plan("台積電 2330 現在試搓多少？相對昨收漲跌多少？這是不是正式成交？", market=False)
    assert result.reader_profile == "quote_only"
    assert set(result.selected_capabilities) == {"target.identity", "data.freshness", "quote.auction"}


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


@pytest.mark.parametrize("phrase", ["強弱族群", "族群強弱", "熱門族群", "強勢族群"])
def test_intraday_market_group_aliases_use_existing_selection_merge(phrase):
    selected = set(plan(f"現在台股盤中走勢如何？請說明大盤、漲跌家數、量能、{phrase}與資料限制。").selected_capabilities)
    assert selected == {"target.identity", "data.freshness", "market.indices", "market.breadth", "market.volume_state", "market.hot_groups"}


@pytest.mark.parametrize("question,metric,order,limit", [
    ("現在盤中漲幅前10名是誰？請只用目前盤中實際成交資料。", "change_pct", "desc", 10),
    ("現在盤中跌幅前十名", "change_pct", "asc", 10),
    ("盤中前十名上漲股票", "change_pct", "desc", 10),
    ("目前下跌最多的前10檔", "change_pct", "asc", 10),
    ("台股盤中成交值前十名", "estimated_trade_value", "desc", 10),
    ("前五名盤中成交金額", "estimated_trade_value", "desc", 5),
    ("盤中成交量前二十名", "cumulative_volume_lots", "desc", 20),
    ("intraday top losers", "change_pct", "asc", 20),
])
def test_intraday_top_n_word_order_and_chinese_numbers(question, metric, order, limit):
    result = plan(question)
    assert "screening.intraday" in result.selected_capabilities
    assert "screening.ranking" not in result.selected_capabilities
    assert result.selection["parameters"]["screening.intraday"] == {
        "metric": metric, "sort_order": order, "limit": limit, "offset": 0,
    }


@pytest.mark.parametrize("question", [
    "不要查盤中跌幅前十名，只看大盤", "昨天收盤漲幅前十名", "近日線漲幅前十名",
    "過去五天漲幅前十名", "盤中上漲下跌家數", "盤前成交量如何", "不要看族群強弱，只看大盤",
])
def test_non_ranking_and_negated_questions_do_not_infer_intraday_rankings(question):
    selected = set(plan(question).selected_capabilities)
    assert "screening.intraday" not in selected
    assert "market.hot_groups" not in selected


def test_explicit_daily_selection_keeps_precedence_over_intraday_words():
    result = plan("盤中漲幅前十名", selection={"include": ["screening.ranking"]})
    assert "screening.intraday" not in result.selected_capabilities


@pytest.mark.parametrize("selection_key", ["include", "required"])
@pytest.mark.parametrize("capability,parameters", [
    ("screening.intraday", {"metric": "change_pct", "sort_order": "desc", "limit": 10, "offset": 0}),
    ("market.hot_groups", {"limit": 7}),
])
def test_explicit_intraday_controls_preserve_parameters_and_caller_input(selection_key, capability, parameters):
    # Deliberately disagree with the prose: explicit controls own the selection.
    selection = {selection_key: [capability], "parameters": {capability: parameters}}
    original = deepcopy(selection)
    result = plan("盤中跌幅前二十名，也看強弱族群", selection=selection)
    assert set(result.selected_capabilities) == {"target.identity", "data.freshness", capability}
    assert result.selection["parameters"][capability] == parameters
    assert result.capability_selection_mode == "explicit"
    assert selection == original


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
    ("現在盤中漲幅前10名是誰？請只用目前盤中實際成交資料。", True, {"screening.intraday"}),
    ("台股盤中成交值前十名", True, {"screening.intraday"}),
    ("現在台股盤中走勢如何？請說明大盤、漲跌家數、量能、強弱族群與資料限制。", True,
     {"market.indices", "market.breadth", "market.volume_state", "market.hot_groups"}),
    ("2330 今天1分K＋既有技術結構，不要用昨日日K冒充", False, {"intraday.bars", "technical.structure"}),
    ("2330現在收盤試搓，和最後成交分開", False, {"quote.auction", "quote.snapshot"}),
    ("台積電 2330 現在試搓多少？相對昨收漲跌多少？這是不是正式成交？", False, {"quote.auction"}),
    ("2344 現在試搓多少？相對昨收漲跌多少？這是不是正式成交？", False, {"quote.auction"}),
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
    pure_quote = not market and required <= {"quote.auction", "quote.snapshot"}
    if pure_quote:
        assert result.reader_profile == "capability_graph"
        assert "quote" in result.required_readers
        assert "technical_reports" not in result.required_readers
        assert "news.events" not in result.optional_selected_capabilities
    else:
        assert ("news.events" in result.optional_selected_capabilities) is atlas_enabled
    if "screening.intraday" in required:
        assert result.selection["parameters"]["screening.intraday"] == {
            "metric": "estimated_trade_value" if "成交值" in question else "change_pct",
            "sort_order": "desc", "limit": 10, "offset": 0,
        }


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
    ("現在台股盤中走勢如何？請說明大盤、漲跌家數、量能、強弱族群與資料限制。",
     {"market.indices", "market.breadth", "market.volume_state", "market.hot_groups"}),
    ("現在盤中漲幅前10名是誰？請只用目前盤中實際成交資料。", {"screening.intraday"}),
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


@pytest.mark.parametrize("symbol,name", [("2330", "台積電"), ("2344", "華邦電")])
@pytest.mark.parametrize("atlas_enabled", [False, True])
def test_original_preopen_question_resolves_target_and_public_manifest_without_selection(db, monkeypatch, symbol, name, atlas_enabled):
    from app.ai.market_context import atlas_context
    from app.db.models import StockMaster
    import requests

    if symbol == "2344":
        db.add(StockMaster(stock_id=symbol, stock_name=name, market="TWSE", instrument_type="stock"))
        db.commit()
    monkeypatch.setattr(settings, "omi_atlas_shadow_enabled", atlas_enabled)
    monkeypatch.setattr(atlas_context, "read_shadow_context", lambda **kwargs: {
        "status": "unavailable", "facts_usable": False, "events": [],
        "reason_code": "offline_fixture", "warnings": [],
    })
    def reject_io(*args, **kwargs):
        raise AssertionError("source regression must not acquire provider evidence")
    monkeypatch.setattr(requests.sessions.Session, "request", reject_io)
    response = ai_ask.ask(db=db, payload=AiAskRequest(
        contract_version="omi.decision.v4",
        question=f"{name} {symbol} 現在試搓多少？相對昨收漲跌多少？這是不是正式成交？",
        mode="data_only", output="evidence_only", realtime_policy="cache_only",
        tool_budget={"max_external_fetches": 0},
    ))
    assert response["contract_version"] == "omi.decision.v4"
    assert response["target"]["id"] == symbol
    assert "quote.auction" in response["execution"]["selection"]["required"]
    assert "quote.auction" in str(response["evidence"]["manifest"])


def test_auction_alias_and_explicit_precedence():
    assert {"quote.auction", "quote.snapshot"} <= set(plan("2330現在收盤試搓，和最後成交分開", market=False).selected_capabilities)
    assert plan("試搓掃描接近支撐股票").selection["parameters"]["screening.price_map"]["lane"] == "indicative"
    result = plan("不要大盤，熱門族群", selection={"include": ["market.indices"]})
    assert set(result.selected_capabilities) == {"target.identity", "data.freshness", "market.indices"}
    assert plan("今天漲幅前10名").selection["parameters"]["screening.intraday"]["limit"] == 10


@pytest.mark.parametrize("question,expected", [
    ("現在台股試搓狀況如何？不要把試搓當正式成交。", True),
    ("台股盤前 indicative breadth", True),
    ("不要查試搓，只看正式成交漲跌家數", False),
    ("不要把試搓當正式成交", False),
    ("台股正式市場漲跌家數", False),
])
def test_auction_presentation_intent_shares_positive_planning_terms(question, expected):
    assert query_plan.has_auction_intent(question, market="TW") is expected


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
