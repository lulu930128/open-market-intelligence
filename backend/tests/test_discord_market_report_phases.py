"""Fixed trading-session fixtures; never a Sunday/live acceptance substitute."""
from copy import deepcopy
from datetime import date, datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from app.dispatch import discord_market_report as report
from app.dispatch.market_report_discord import render_compact_content
from app.dispatch.market_report_text import render_presentation


DAY = date(2026, 10, 22)
PREVIOUS = date(2026, 10, 21)
TZ = ZoneInfo("Asia/Taipei")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError("phase fixtures must never connect to a provider or Discord")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def envelope(phase):
    clock = {"preopen": "08:54", "intraday": "09:59", "postclose": "13:33"}[phase]
    stamp = f"{DAY}T{clock}:00+08:00"
    lane = "indicative" if phase == "preopen" else "actual"
    semantics = "indicative_match" if lane == "indicative" else "actual_trade_only"
    row = {"stock_id": "2330", "stock_name": "fixture", "trade_date": DAY.isoformat(),
           "event_time": stamp, "lane": lane, "current_price": 123, "change_pct": 2,
           "price_semantics": semantics, "facts_usable_for_ranking": True,
           "decision_usable": False, "lineage": {"source": "canonical_state", "raw_result_ids": ["fixture:1"]}}
    ranking = {"lane": lane, "status": "partial", "facts_usable_for_ranking": True,
               "observed_trade_date": DAY.isoformat(), "event_time": stamp,
               "coverage": {"coverage_ratio": .5}, "rows": [row], "decision_usable": False}
    groups = {**ranking, "as_of": stamp, "price_semantics": semantics,
              "groups": [{"group_name": "半導體", "mean_return_pct": 1.5}]}
    auction = {"as_of": f"{DAY}T08:54:00+08:00", "status": "provisional",
               "price_semantics": "auction_indicative", "source": "canonical_auction_breadth",
               "is_provisional": True, "decision_usable": False,
               "advance_count": 20, "decline_count": 10, "unchanged_count": 5,
               "coverage_count": 35, "universe_count": 100}
    indices = [{"index_id": identity, "value": 25000, "change_pct": 1, "as_of": stamp,
                "trade_date": DAY.isoformat(), "event_time": stamp,
                "authority": "provider" if phase == "intraday" and identity == "TAIEX" else "official_exchange",
                "freshness": {"status": "current"}, "decision_usable": True,
                "current_for_requested_session": True,
                "source": "fugle_indices_stream" if phase == "intraday" and identity == "TAIEX" else "twse_mis_index_snapshot",
                "quote_semantics": "official_close" if phase == "postclose" else "current_session_last_trade",
                "finalization": "final" if phase == "postclose" else "intraday",
                "official_close_confirmed": phase == "postclose", "official_source": phase == "postclose",
                "provisional": phase != "postclose",
                "official_close": {"value": 24000, "trade_date": PREVIOUS.isoformat(),
                                   "as_of": f"{PREVIOUS}T13:30:00+08:00", "source": "official_daily"}}
               for identity in ("TAIEX", "TPEX")]
    breadth = {"trade_date": DAY.isoformat(), "as_of": stamp, "session_semantics": "current_session",
               "price_semantics": "current_last_trade_vs_reference", "status": "partial", "source": "twse_mis_live_breadth",
               "advance_count": 800, "decline_count": 200, "coverage_count": 1000,
               "universe_count": 2000, "auction_breadth": auction}
    return {"as_of": stamp, "warnings": ["owner coverage partial"], "missing": ["owner gap"],
            "data": {"latest_trade_date": str(DAY if phase == "postclose" else PREVIOUS),
                     "market": {"indices": {"items": indices}}, "breadth": breadth,
                     "breadth_by_market": {venue: {**breadth,
                         "finalization": "session_final" if phase == "postclose" else "provisional",
                         "session_semantics": "latest_completed_session" if phase == "postclose" else "current_session",
                         "close_reconciliation": {"status": "partial"},
                         "is_provisional": phase != "postclose"} for venue in ("TWSE", "TPEX")},
                     "volume_state": {"status": "partial", "trade_date": str(DAY), "as_of": stamp,
                                      "current_cumulative_trade_value": 123456, "source": "canonical_volume",
                                      "trade_value_authority_status": "estimated", "trade_value_coverage_status": "partial"},
                     "screening": {"intraday": ranking, "hot_groups": groups},
                     "index_intraday": {"expected_trade_date": str(DAY), "status": "partial", "indices": []},
                     "value_leaders": [{"stock_id": "9999", "change_pct": 99}],
                     "top_industries": [{"industry": "yesterday_only", "average_change_pct": 99}],
                     "cross_market": {"markets": {"us": {"status": "current", "assets": [
                         {"id": "SPX", "status": "current", "change_pct": 1,
                          "as_of": f"{PREVIOUS}T16:00:00-04:00", "source": "overnight_cache"}]}}}}}


def select(monkeypatch, phase, payload=None):
    hour, minute = {"preopen": (8, 55), "intraday": (10, 0), "postclose": (16, 0)}[phase]
    now = datetime.combine(DAY, datetime.min.time(), TZ).replace(hour=hour, minute=minute)
    reader = Mock(return_value=payload or envelope(phase))
    monkeypatch.setattr(report.templates.tools, "read_market_overview", reader)
    db = Mock()
    result = report.build_report_selection(db, phase=phase, local_now=now)
    db.commit.assert_not_called()
    db.flush.assert_not_called()
    return result, reader


@pytest.mark.parametrize("identity", ["TAIEX", "TPEX"])
@pytest.mark.parametrize("override", [
    {}, {"freshness": {"status": "delayed"}},
    {"quote_semantics": "intraday_last_trade"},
    {"quote_semantics": "closing_auction_last_trade"},
    {"quote_semantics": "official_close"},
    {"freshness": {"status": "stale"}}, {"freshness": {}},
    {"authority": "derived_proxy", "decision_usable": False},
    {"authority": "unverified", "decision_usable": False},
    {"authority": "unknown", "decision_usable": False},
    {"authority": None, "decision_usable": False},
    {"decision_usable": False}, {"decision_usable": None}, {"decision_usable": "true"},
    {"current_for_requested_session": False}, {"finalization": "final"},
    {"trade_date": str(PREVIOUS)}, {"trade_date": None},
    {"event_time": None}, {"event_time": str(DAY)},
    {"event_time": f"{DAY}T09:59:00"},
    {"event_time": f"{DAY}T10:01:00+08:00"},
    {"event_time": f"{PREVIOUS}T09:59:00+08:00"},
])
def test_intraday_formal_index_contract(monkeypatch, identity, override):
    payload = envelope("intraday")
    row = next(row for row in payload["data"]["market"]["indices"]["items"] if row["index_id"] == identity)
    row.update(override)
    model = select(monkeypatch, "intraday", payload)[0].model
    accepted = not override or override == {"freshness": {"status": "delayed"}}
    assert (identity in [item["index_id"] for item in model.indices["items"]]) is accepted
    assert len(model.indices["items"]) == (2 if accepted else 1)


def test_intraday_missing_resolver_qualification_stays_pending(monkeypatch):
    payload = envelope("intraday")
    for row in payload["data"]["market"]["indices"]["items"]:
        row.pop("decision_usable")
    model = select(monkeypatch, "intraday", payload)[0].model
    assert model.indices["items"] == []


def test_intraday_preserves_formal_sources_and_uses_event_not_receipt_clock(monkeypatch):
    payload = envelope("intraday")
    rows = payload["data"]["market"]["indices"]["items"]
    for row in rows:
        row["as_of"] = f"{DAY}T10:01:00+08:00"
        row["event_time"] = f"{DAY}T10:00:00+08:00"
    model = select(monkeypatch, "intraday", payload)[0].model
    assert [(row["index_id"], row["authority"], row["source"]) for row in model.indices["items"]] == [
        ("TAIEX", "provider", "fugle_indices_stream"),
        ("TPEX", "official_exchange", "twse_mis_index_snapshot"),
    ]
    assert all(model.phase_selection["sections"][f"index.{identity}"]["status"] == "selected"
               for identity in ("TAIEX", "TPEX"))


@pytest.mark.parametrize("phase", ["preopen", "intraday", "postclose"])
def test_fixed_times_use_distinct_reader_contracts_and_surfaces(monkeypatch, phase):
    original = envelope(phase)
    before = deepcopy(original)
    selection, reader = select(monkeypatch, phase, original)
    args = reader.call_args.kwargs
    assert args["include_intraday"] is (phase == "intraday")
    assert args["market_data_params"]["trade_date"] == str(DAY if phase == "postclose" else PREVIOUS)
    params = args["market_data_params"]["capability_parameters"]
    if phase != "postclose":
        assert params["screening.intraday"]["lane"] == ("indicative" if phase == "preopen" else "actual")
    else:
        assert "screening.intraday" not in args["market_data_params"]["requested_capabilities"]
    model = selection.model
    compact, audit = render_compact_content(model), render_presentation(model)
    assert "owner coverage partial" in audit and "owner gap" in audit
    assert original == before
    assert len(compact.encode("utf-16-le")) // 2 <= 1900
    if phase == "preopen":
        assert model.indices["items"][0]["value"] == 24000
        assert model.breadth["advance_count"] == 20 and model.breadth["decision_usable"] is False
        assert model.value_leaders[0]["stock_id"] == "9999"
        assert "provisional" in compact and "非正式成交" in compact and "SPX" in compact
    elif phase == "intraday":
        assert model.indices["items"][0]["value"] == 25000
        assert model.breadth["advance_count"] == 800
        assert model.volume["current_cumulative_trade_value"] == 123456
        assert model.index_intraday["status"] == "partial"
        assert model.stock_radar == [] and model.value_leaders == [] and model.strong_sectors == []
        assert "2330" in compact and "半導體" in compact and "9999" not in compact
    else:
        assert model.indices["items"][0]["official_close_confirmed"] is True
        assert model.value_leaders[0]["stock_id"] == "9999" and model.strong_sectors
        assert model.phase_selection["sections"]["daily_rankings"]["status"] == "daily_sample"
        assert model.breadth["advance_count"] == 800
        assert all("official" not in row for row in model.breadth_by_market.values())
        assert "session_final" in audit and "reconciliation=partial" in audit
        assert "盤前預期回顧 unavailable" in compact and "官方發布狀態個別確認" in compact


@pytest.mark.parametrize("phase", ["intraday", "postclose"])
def test_previous_day_or_later_same_day_never_fills_current_slots(monkeypatch, phase):
    for stamp in (f"{PREVIOUS}T13:30:00+08:00", f"{DAY}T23:00:00+08:00"):
        payload = envelope(phase)
        payload["data"]["latest_trade_date"] = PREVIOUS.isoformat()
        for block in [*payload["data"]["market"]["indices"]["items"], payload["data"]["breadth"],
                      payload["data"]["volume_state"], *payload["data"]["breadth_by_market"].values()]:
            block.update(trade_date=stamp[:10], as_of=stamp, event_time=stamp)
        for block in payload["data"]["screening"].values():
            block.update(observed_trade_date=stamp[:10], as_of=stamp, event_time=stamp)
        model = select(monkeypatch, phase, payload)[0].model
        assert not model.indices["items"] and model.breadth["status"] == "pending"
        assert model.volume["status"] == "pending"
        assert model.phase_selection["candidates"]["rows"] == []
        assert "9999" not in render_compact_content(model)


def test_missing_auction_and_wrong_lane_are_unavailable_without_daily_substitution(monkeypatch):
    payload = envelope("preopen")
    payload["data"]["breadth"]["auction_breadth"]["status"] = "stale"
    payload["data"]["screening"]["intraday"]["lane"] = "actual"
    model = select(monkeypatch, "preopen", payload)[0].model
    assert model.breadth["status"] == "unavailable" and "advance_count" not in model.breadth
    assert model.phase_selection["candidates"]["rows"] == []


@pytest.mark.parametrize("field,value", [("official_close_confirmed", False), ("finalization", "provisional"),
                                        ("official_source", False), ("provisional", True)])
def test_postclose_does_not_promote_session_close_or_estimates(monkeypatch, field, value):
    payload = envelope("postclose")
    payload["data"]["market"]["indices"]["items"][0][field] = value
    model = select(monkeypatch, "postclose", payload)[0].model
    assert [row["index_id"] for row in model.indices["items"]] == ["TPEX"]
    assert model.phase_selection["sections"]["index.TAIEX"]["status"] == "pending"


def test_intraday_never_reads_daily_stock_facts_or_price_maps(monkeypatch):
    selection, _ = select(monkeypatch, "intraday")
    daily, price_map = Mock(side_effect=AssertionError("daily is not current")), Mock(side_effect=AssertionError("map is historical"))
    monkeypatch.setattr(report, "read_stock_analysis_facts", daily)
    monkeypatch.setattr(report, "build_tw_stock_price_map", price_map)
    db = Mock()
    db.get_bind.return_value.dialect.name = "sqlite"
    report.build_readonly_presentation(db, phase="intraday", local_now=selection.local_now, selection=selection)
    daily.assert_not_called()
    price_map.assert_not_called()
    assert str(db.execute.call_args.args[0]) == "PRAGMA query_only=ON"


def test_rich_phase_chart_and_audit_are_detached_and_do_not_send(monkeypatch):
    selection, _ = select(monkeypatch, "preopen")
    sender = Mock(side_effect=AssertionError("no Discord delivery"))
    monkeypatch.setattr(report, "send_discord_rich_report", sender)
    monkeypatch.setattr(report, "render_market_dashboard_chart", lambda model: b"fixture-png")
    monkeypatch.setattr(report, "render_stock_analysis_chart", Mock(side_effect=AssertionError("legacy chart")))
    monkeypatch.setattr(report, "render_technology_pulse_chart", Mock(side_effect=AssertionError("legacy chart")))
    rich = report.build_rich_report(selection.model, mode="audit")
    assert [item.filename for item in rich.attachments] == ["market_dashboard.png", "full_report.txt", "evidence.json"]
    assert b'"phase_selection"' in rich.attachments[-1].data
    assert "試撮" in rich.embeds[0]["description"]
    sender.assert_not_called()


def test_postclose_old_daily_sample_stays_pending_but_indices_remain(monkeypatch):
    payload = envelope("postclose")
    payload["data"]["latest_trade_date"] = str(PREVIOUS)
    model = select(monkeypatch, "postclose", payload)[0].model
    assert len(model.indices["items"]) == 2
    assert not model.stock_radar and not model.value_leaders and not model.strong_sectors
    assert model.phase_selection["sections"]["daily_rankings"]["status"] == "pending"


@pytest.mark.parametrize("phase, expected", [("preopen", "unavailable"), ("postclose", "pending")])
@pytest.mark.parametrize("contradictory_rankings", [False, True])
def test_empty_daily_sample_never_qualifies_by_date_alone(monkeypatch, phase, expected, contradictory_rankings):
    payload = envelope(phase)
    payload["data"]["sample_coverage"] = {"status": "empty", "sample_count": 0,
                                            "universe_count": 1973}
    if not contradictory_rankings:
        payload["data"]["value_leaders"] = []
        payload["data"]["top_industries"] = []
    model = select(monkeypatch, phase, payload)[0].model
    assert model.phase_selection["sections"]["daily_rankings"]["status"] == expected
    assert model.stock_radar == [] and model.value_leaders == [] and model.strong_sectors == []


def test_candidate_identity_cannot_hide_previous_day_event(monkeypatch):
    payload = envelope("intraday")
    payload["data"]["screening"]["intraday"]["rows"][0]["event_time"] = f"{PREVIOUS}T13:30:00+08:00"
    model = select(monkeypatch, "intraday", payload)[0].model
    assert model.phase_selection["candidates"]["rows"] == []
    assert model.phase_selection["sections"]["candidates"]["status"] == "pending"


def test_overnight_future_cache_is_not_a_preopen_reference(monkeypatch):
    payload = envelope("preopen")
    payload["data"]["cross_market"]["markets"]["us"]["assets"][0]["as_of"] = f"{DAY}T16:00:00-04:00"
    model = select(monkeypatch, "preopen", payload)[0].model
    assert "SPX" not in render_compact_content(model)
    assert "隔夜美股基準 unavailable" in render_compact_content(model)


@pytest.mark.parametrize("phase", ["preopen", "intraday", "postclose"])
def test_real_reader_routing_is_cache_only_on_empty_fixture_database(monkeypatch, phase):
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.orm import Session
    from app.ai.market_context import taiwan_market
    from app.db.models import Base
    tools = report.templates.tools
    hour = {"preopen": 8, "intraday": 10, "postclose": 16}[phase]
    now = datetime(2026, 10, 22, hour, 55 if phase == "preopen" else 0, tzinfo=TZ)
    monkeypatch.setattr(tools, "_now", lambda: now)
    monkeypatch.setattr(tools.tw_cross_market, "read_tw_cross_market_context", Mock(return_value={"status": "missing"}))
    monkeypatch.setattr(tools.tw_market_chips, "read_tw_market_chips_context", Mock(return_value={"status": "missing"}))
    monkeypatch.setattr(tools, "read_taiwan_market_volume_state", Mock(return_value={"status": "missing"}))
    monkeypatch.setattr(taiwan_market, "_market_indices_capability", Mock(return_value={"items": [], "status": "missing"}))
    monkeypatch.setattr(taiwan_market, "_market_breadth_from_index_summary", Mock(return_value={}))
    pack = Mock(return_value={})
    monkeypatch.setattr(taiwan_market, "_market_index_intraday_pack", pack)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    writes = []
    def check_statement(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() not in {"SELECT", "PRAGMA", "WITH"}:
            writes.append(statement.split()[0])
    event.listen(engine, "before_cursor_execute", check_statement)
    try:
        with Session(engine) as db:
            db.execute(text("PRAGMA query_only=ON"))
            selection = report.build_report_selection(db, phase=phase, local_now=now)
            assert not db.new and not db.dirty and not db.deleted
            assert selection.model.phase_selection["sections"]["daily_rankings"]["status"] in {"pending", "unavailable"}
            assert not selection.model.stock_radar
        assert writes == []
        assert pack.call_args.kwargs["include_intraday"] is (phase == "intraday")
    finally:
        engine.dispose()
