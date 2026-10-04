from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.dispatch import discord_market_report as report
from app.dispatch.market_report_presentation import build_presentation, with_price_maps


IDS = ["2327", "1459", "4154", "2409", "2324", "1727", "6902", "2330"]
PARTIAL = {"1459", "4154", "1727", "6902"}
DAY = date(2026, 10, 2)
NOW = datetime(2026, 10, 3, 9, tzinfo=ZoneInfo("Asia/Taipei"))
VALUES = {"2324": (36.20, 1274998541), "1727": (123, 4312844837), "6902": (150, 71518085)}


def test_day_state_blockers_are_presented_without_inference():
    from app.dispatch.market_report_presentation import technical_blocker_lines
    facts = {"data": {"input_quality": {"day_state_blockers": [
        {"trade_date": "2026-08-10", "state": "TRADE_ACTIVITY_WITHOUT_PRICE",
         "reasons": ["ALTERNATE_OFFICIAL_PRICE_REQUIRED"]},
        {"trade_date": "2026-08-11", "state": "VERIFIED_NO_TRADE",
         "reasons": ["PRICE_BASIS_EVENT_COVERAGE_REQUIRED"]},
    ]}}}
    lines = technical_blocker_lines(facts)
    assert lines == ["有成交但缺官方價格：2026-08-10", "已驗證零成交；價格基準事件覆蓋不足：2026-08-11"]
    assert technical_blocker_lines({}) == []
    base = build_presentation(preview(), phase="postclose", report_date=DAY)
    model = with_price_maps(base, {}, technical_reports={IDS[0]: facts})
    item = next(item for item in model.stock_analysis if item["stock_id"] == IDS[0])
    assert item["technical_facts"]["data"]["input_quality"] == facts["data"]["input_quality"]
    assert item["technical_blockers"] == lines
    from app.dispatch.market_report_text import render_model_sections
    rendered = render_model_sections(model)
    assert all(line in rendered for line in lines)
    facts["data"]["input_quality"]["day_state_blockers"].clear()
    assert item["technical_facts"]["data"]["input_quality"]["day_state_blockers"]


@pytest.mark.parametrize("mode", ["live", "replay"])
def test_evidence_time_mode_threads_bounded_owner_arguments(monkeypatch, mode):
    now = datetime(2026, 10, 2, 16, tzinfo=ZoneInfo("Asia/Taipei"))
    calls = {}
    canonical = preview()
    canonical["metadata"]["cross_market"] = {"status": "partial", "as_of": NOW.isoformat()}

    def overview(db, **kw):
        calls["overview"] = kw
        return canonical

    def daily(db, stock_id, **kw):
        calls.setdefault("daily", []).append(kw)
        return SimpleNamespace(daily=None, dataset_health=None, limitations=(),
            resolved_health=SimpleNamespace(model_dump=lambda **kw: {}))

    def chart(**kw):
        calls.setdefault("chart", []).append(kw)
        return {}

    def technical(**kw):
        calls.setdefault("technical", []).append(kw)
        return {}

    def price_map(**kw):
        calls.setdefault("price_map", []).append(kw)
        return {"status": "missing", "decision_usable": False}

    monkeypatch.setattr(report.templates, "build_market_overview_preview", overview)
    monkeypatch.setattr(report, "read_taiwan_latest_daily_evidence", daily)
    monkeypatch.setattr(report, "list_stock_ohlc_chart_data", chart)
    monkeypatch.setattr(report, "build_stock_technical_report", technical)
    monkeypatch.setattr(report, "build_tw_stock_price_map", price_map)
    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
                         execute=lambda statement: None)
    model, _, _ = report.build_readonly_presentation(
        db, phase="postclose", local_now=now, evidence_time_mode=mode)
    replay = mode == "replay"
    assert calls["overview"] == {"market": "tw", **({"trade_date": DAY} if replay else {})}
    assert len(calls["price_map"]) == len(model.stock_radar) == 8
    assert all(kw == {"to_date": DAY, "requested_at": None if replay else now}
               for kw in calls["daily"])
    for kind in ("chart", "technical"):
        assert all(kw["to_date"] == DAY for kw in calls[kind])
    for kw in calls["price_map"]:
        assert kw["now"] == now
        assert (kw["as_of_date"] == DAY) if replay else ("as_of_date" not in kw)
    assert model.evidence_axes["evidence_time_mode"] == mode
    assert model.evidence_axes["semantics"] == (
        "current_cache_bounded_report_date" if replay else "strict_availability")
    assert model.cross_market == canonical["metadata"]["cross_market"]
    assert bool(model.presentation_warnings) is replay
    if replay:
        assert "not an immutable historical snapshot" in model.presentation_warnings[0]
        assert model.presentation_warnings[0] in model.full_limitations["warnings"]


def test_replay_preview_passes_trade_date_to_canonical_overview(monkeypatch):
    calls = []
    def overview(**kw):
        calls.append(kw)
        return {"data": {}, "warnings": [], "missing": []}
    monkeypatch.setattr(report.templates.tools, "read_market_overview", overview)
    report.templates.build_market_overview_preview(None, market="tw", trade_date=DAY)
    assert calls[0]["market_data_params"] == {
        "requested_capabilities": ["market.indices"], "trade_date": DAY.isoformat()}
    report.templates.build_market_overview_preview(None, market="tw")
    assert calls[1]["market_data_params"] == {"requested_capabilities": ["market.indices"]}


@pytest.mark.parametrize("hour,minute,phase,cap", [
    (8, 55, "preopen", date(2026, 10, 1)),
    (10, 0, "intraday", date(2026, 10, 1)),
    (16, 0, "postclose", DAY),
])
def test_replay_daily_release_cap_is_shared_by_all_daily_owners(monkeypatch, hour, minute, phase, cap):
    now = datetime(2026, 10, 2, hour, minute, tzinfo=ZoneInfo("Asia/Taipei"))
    calls = {}

    def overview(db, **kw):
        calls["preview"] = kw
        return {"metadata": {"value_leaders": [{"stock_id": "2324"}]}}

    def daily(db, stock_id, **kw):
        calls["daily"] = kw
        return SimpleNamespace(daily=None, dataset_health=None, limitations=(),
            resolved_health=SimpleNamespace(model_dump=lambda **kw: {}))

    def capture(name):
        def reader(**kw):
            calls[name] = kw
            return {}
        return reader

    monkeypatch.setattr(report.templates, "build_market_overview_preview", overview)
    monkeypatch.setattr(report, "read_taiwan_latest_daily_evidence", daily)
    monkeypatch.setattr(report, "list_stock_ohlc_chart_data", capture("chart"))
    monkeypatch.setattr(report, "build_stock_technical_report", capture("technical"))
    monkeypatch.setattr(report, "build_tw_stock_price_map", capture("price_map"))
    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
                         execute=lambda statement: None)
    model, _, _ = report.build_readonly_presentation(
        db, phase=phase, local_now=now, evidence_time_mode="replay")
    assert model.report_date == DAY.isoformat()
    assert model.evidence_axes["daily_sample_cap"] == cap.isoformat()
    assert calls["preview"]["trade_date"] == cap
    assert calls["daily"] == {"to_date": cap, "requested_at": None}
    assert calls["chart"]["to_date"] == calls["technical"]["to_date"] == cap
    assert calls["price_map"]["as_of_date"] == cap
    assert calls["price_map"]["now"] == now

    # Live keeps its original date and strict availability arguments at every phase.
    report.build_readonly_presentation(db, phase=phase, local_now=now)
    assert calls["preview"] == {"market": "tw"}
    assert calls["daily"] == {"to_date": DAY, "requested_at": now}
    assert calls["chart"]["to_date"] == calls["technical"]["to_date"] == DAY
    assert "as_of_date" not in calls["price_map"]


def preview():
    return {"metadata": {"value_leaders": [{"stock_id": sid} for sid in IDS],
        "market_chips": {"institutional_per_stock": {"trade_date": DAY,
            "top_net_buy": [{"stock_id": "2409", "total_institutional_net": 91289209}],
            "top_net_sell": [{"stock_id": "2324", "total_institutional_net": -23520107,
                              "foreign_investor_net": -20000000, "investment_trust_net": -3000000,
                              "dealer_net": -520107}],
            "source_out_of_universe": [{"stock_id": "0050"}, {"stock_id": "9105"}]}},
        "top_industries": [{"top_stock_id": "1727", "industry": "chemical", "average_change_pct": 3.1646979547,
            "advance_count": 38, "decline_count": 3, "sample_count": 42, "trade_value": 999}],
        "weak_industries": [{"top_stock_id": "6902", "industry": "cloud", "average_change_pct": -0.6683448231,
            "advance_count": 9, "decline_count": 20, "sample_count": 35, "trade_value": 888}]}}


def test_bounded_orchestration_enriches_all_ids_through_existing_owners(monkeypatch):
    calls = []
    canonical = preview()
    monkeypatch.setattr(report.templates, "build_market_overview_preview", lambda db, **kw: canonical)
    def chart(**kw):
        assert kw["ensure_history"] is False and kw["include_intraday"] is False
        assert kw["bars"] == 90 and kw["to_date"] == NOW.date()
        calls.append(("chart", kw["stock_id"]))
        return {"freshness_status": "current", "available_bar_count": 75, "expected_minimum_bar_count": 90,
                "volume_unit": "shares", "trade_value_unit": "TWD", "volume_semantics": "finalized_traded_shares"}
    def daily(db, stock_id, **kw):
        assert kw == {"to_date": NOW.date(), "requested_at": NOW}
        close, value = VALUES.get(stock_id, (100, 10000))
        return SimpleNamespace(daily=SimpleNamespace(trade_date=DAY, close_price=close, price_change=1, trade_value=Decimal(value),
            trade_volume=1000, provider="official", source="canonical", event_at=NOW),
            resolved_health=SimpleNamespace(model_dump=lambda **kw: {"status": "selected"}),
            dataset_health=None, limitations=("upstream limitation",))
    def technical(**kw):
        assert kw["include_intraday"] is False and kw["include_volume_pace"] is False
        calls.append(("technical", kw["stock_id"]))
        return {"status": "partial" if kw["stock_id"] in PARTIAL else "ready",
                "confidence": "medium", "title": "observations", "summary": "factual",
                "missing": ["history_window"], "data": {"daily_indicator": {"time": DAY, "change_pct": 1.25,
                "ma": {"ma5": 1, "ma20": 2, "ma60": 3}, "rsi": {"rsi14": 55}, "adx": {"adx14": 22}}}}
    def price_map(**kw):
        usable = kw["stock_id"] not in PARTIAL
        return {"status": "ready" if usable else "partial", "decision_usable": usable,
                "reference": {"price": VALUES.get(kw["stock_id"], (100, 0))[0], "trade_date": DAY,
                              "freshness_status": "current"},
                "technical": {"headline": "canonical headline"}, "missing": [] if usable else ["transition_window"],
                "nearest_downside": {"anchor_price": 30}, "nearest_upside": {"anchor_price": 40}}
    monkeypatch.setattr(report, "list_stock_ohlc_chart_data", chart)
    monkeypatch.setattr(report, "read_taiwan_latest_daily_evidence", daily)
    monkeypatch.setattr(report, "build_stock_technical_report", technical)
    monkeypatch.setattr(report, "build_tw_stock_price_map", price_map)
    statements = []
    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
                         execute=lambda statement: statements.append(str(statement)))
    model, _, elapsed = report.build_readonly_presentation(db, phase="postclose", local_now=NOW)
    assert statements == ["PRAGMA query_only=ON"] and elapsed >= 0
    assert model.stock_radar == build_presentation(canonical, phase="postclose", report_date=NOW.date()).stock_radar
    assert {item["stock_id"] for item in model.stock_analysis} == set(IDS)
    assert len(calls) == 16
    for item in model.stock_analysis:
        sid = item["stock_id"]
        assert set(item["selection"]) == {"reasons"}
        assert item["market"]["trade_date"] == "2026-10-02"
        assert item["market"]["change_pct"] == 1.25 and item["market"]["volume"] == 1000
        assert type(item["market"]["trade_value"]) is int
        assert item["market"]["authority"] is None and item["market"]["finalization"] is None
        assert item["market"]["resolved_health"] == {"status": "selected"}
        assert item["market"]["selected_provider"] == "official"
        assert item["market"]["selected_source"] == "canonical"
        assert item["market"]["event_at"] == NOW.isoformat()
        assert item["market"]["dataset_health"] is None
        assert item["market"]["limitations"] == ["upstream limitation"]
        assert item["technical_facts"]["data"]["daily_indicator"]["ma"]["ma60"] == 3
        assert item["technical_facts"]["missing"] == ["history_window"]
        assert item["technical_facts"]["status"] == ("partial" if sid in PARTIAL else "ready")
        assert item["technical_facts"]["reference"]["trade_date"] == "2026-10-02"
        assert item["technical_decision"]["usable"] is (sid not in PARTIAL)
        if sid in PARTIAL:
            assert item["technical_decision"]["missing"] == ["transition_window"]
            assert item["technical_decision"]["support"] == {}
        else:
            assert item["technical_decision"]["support"] == {"anchor_price": 30}
        if sid in VALUES:
            assert (item["market"]["close"], item["market"]["trade_value"]) == VALUES[sid]
    by_id = {item["stock_id"]: item for item in model.stock_analysis}
    assert by_id["2324"]["institutional"][0]["total_institutional_net"] == -23520107
    assert by_id["2324"]["institutional"][0]["dealer_net"] == -520107
    assert by_id["2409"]["institutional"][0]["total_institutional_net"] == 91289209
    assert by_id["1727"]["sector"][0]["average_change_pct"] == 3.1646979547
    assert by_id["6902"]["sector"][0]["sample_count"] == 35
    assert all("change_pct" not in item and "trade_value" not in item for item in model.stock_radar)


@pytest.mark.parametrize("value", [None, Decimal("0"), Decimal("9007199254740993.00"),
                                  Decimal("1.5"), Decimal("NaN"), Decimal("Infinity")])
def test_daily_trade_value_preserves_exact_integer_or_rejects_invalid(monkeypatch, value):
    monkeypatch.setattr(report, "list_stock_ohlc_chart_data", lambda **kw: {})
    monkeypatch.setattr(report, "build_stock_technical_report", lambda **kw: {})
    monkeypatch.setattr(report, "read_taiwan_latest_daily_evidence", lambda *args, **kw: SimpleNamespace(
        daily=SimpleNamespace(trade_date=DAY, close_price=Decimal("36.2"), price_change=None,
            trade_value=value, trade_volume=None, provider="official", source="canonical", event_at=NOW),
        resolved_health=SimpleNamespace(model_dump=lambda **kw: {"status": "selected"}),
        dataset_health=None, limitations=()))
    if value is not None and (not value.is_finite() or value != value.to_integral_value()):
        with pytest.raises(ValueError, match="integral TWD"):
            report.read_stock_analysis_facts(None, stock_id="2324", local_now=NOW)
    else:
        market, _ = report.read_stock_analysis_facts(None, stock_id="2324", local_now=NOW)
        if value is None:
            assert market["trade_value"] is None
        else:
            assert type(market["trade_value"]) is int
            assert Decimal(market["trade_value"]) == value


def test_enrichment_detaches_inputs_and_bitcoin_field_availability():
    base = build_presentation({"metadata": {"value_leaders": [{"stock_id": "2324", "change_pct": 999}],
        "cross_market": {"markets": {"crypto": {"assets": [
            {"id": "BTC", "status": "current", "price": 100, "change_pct": None}]}}}}},
        phase="postclose", report_date=DAY)
    facts = {"2324": {"close": 36.2, "trade_value": 1274998541}}
    original = deepcopy(facts)
    model = with_price_maps(base, {}, market_facts=facts)
    facts["2324"]["close"] = 999
    assert model.stock_analysis[0]["market"] == original["2324"]
    assert model.stock_analysis[0]["change_pct"] is None
    btc = model.cross_market_strip["promoted"][0]
    assert btc["price"] == 100 and btc["availability"] == {"price": "available", "change_pct": "missing"}
