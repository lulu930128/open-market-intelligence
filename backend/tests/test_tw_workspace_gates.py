"""G1/G3 offline transport and read-purity gates; no production app lifespan."""

import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from fastapi import FastAPI
import pytest
from sqlalchemy import text

from app.db.models import StockMaster, MarketDailyPrice, RawFetchResult, SourceRegistry
from app.db.session import get_db
from app.market.trading_calendar import TAIWAN_TZ, is_taiwan_trading_day
from app.market.tw_market_dashboard import _dashboard_intraday_chart, build_tw_stock_research, search_tw_dashboard_symbols
from app.market.tw_market_dashboard_schemas import TaiwanDashboardIntradayChartRead, TaiwanStockResearchRead
from app.market.tw_workspace_research import project_tw_workspace_research, WORKSPACE_RESEARCH_MAX_BYTES, TaiwanResearchProjectionTooLarge
from app.routers.tw_market_dashboard import router
from test_tw_workspace import db, seed  # Existing disposable SQLite + network-deny fixture.


def report(timeframe, days=3):
    state = {"contract_version": "tw.daily.day_state.v1", "state": "TRADED_WITH_PRICE",
             "market_open": True, "instrument_status": "tradable", "expected_session": True,
             "price_basis": {"status": "unknown", "coverage": "missing", "limitations": ["basis unknown"], "lineage": []},
             "blockers": [], "limitations": ["source limited"],
             "lineage": [{"source": "synthetic", "raw_receipt_id": "x" * 1800}]}
    quality = {"status": "partial", "decision_usable": False, "warnings": ["history partial"],
               "reason_codes": ["GAP"], "canonical_limitations": ["unknown calendar"],
               "day_state_blockers": [{"trade_date": str(date(2015, 1, 1) + timedelta(days=i)), "state": "MISSING_EVIDENCE", "reasons": ["OFFICIAL_DAILY_EVIDENCE_REQUIRED"]} for i in range(days)],
               "day_states": [{**state, "trade_date": str(date(2015, 1, 1) + timedelta(days=i))} for i in range(days)]}
    indicator = {"time": "2026-10-08", "close": 103.5, "rsi": {"rsi14": 45.0},
                 "macd": {"macd": 1.0, "signal": 0.5, "histogram": 0.5}, "kd": {"k9": None, "d9": 50.0},
                 "input_quality": quality, "change_pct": -1.0}
    key = {"today": "daily_background", "daily": "daily_indicator"}.get(timeframe, "indicator")
    return {"kind": "omi.tw_stock_research", "version": "omi.tw_stock_research.v1", "stock_id": "00631L",
            "timeframe": timeframe, "cache_only": True, "warnings": ["保留警告"],
            "technical": {"kind": "tw_stock_technical_report", "stock_id": "00631L", "timeframe": timeframe,
                          "phase": timeframe, "confidence": "low", "generated_at": "2026-10-09T10:00:00+08:00",
                          "title": "證據不足", "summary": "保留限制與反證", "score": None, "status": "partial",
                          "decision_usable": False, "value_label": "vs 昨收", "value": None,
                          "rows": [], "badges": [], "missing": ["GAP"], "warnings": ["保留警告"],
                          "source_refs": [{"source": "synthetic"}],
                          "data": {key: indicator, "input_quality": quality, "change_pct": 2.0,
                                   "decision_state": None, "current_state_decision_usable": False,
                                   "market_session": {"is_trading_day": False, "trade_date": "2026-10-08"},
                                   "period": {"status": "current_partial"}}}}


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


@pytest.mark.parametrize("timeframe", ["today", "daily", "weekly", "monthly"])
@pytest.mark.parametrize("days", [3, 3000])
def test_projection_size_semantic_parity_and_mcp_envelope(timeframe, days):
    full = report(timeframe, days)
    before = deepcopy(full)
    start = perf_counter()
    full_wire = encode(TaiwanStockResearchRead.model_validate(full).model_dump(mode="json"))
    full_ms = (perf_counter() - start) * 1000
    start = perf_counter()
    concise = project_tw_workspace_research(full)
    wire = encode(concise)
    concise_ms = (perf_counter() - start) * 1000
    assert full == before
    assert len(wire) <= WORKSPACE_RESEARCH_MAX_BYTES
    for key in ("title", "summary", "score", "phase", "confidence", "status", "decision_usable", "rows", "missing", "warnings", "source_refs"):
        assert concise["technical"][key] == full["technical"][key]
    summary = concise["technical_summary"]
    original = full["technical"]["data"][summary["basis"]]
    for key in ("time", "close", "rsi", "macd", "kd"):
        assert summary[key] == original[key]
    quality = concise["technical"]["data"]["input_quality"]
    assert quality["day_state_summary"]["count"] == days
    assert quality["day_state_blocker_summary"]["count"] == days
    assert quality["day_state_blocker_summary"]["groups"][0]["semantics"]["reasons"] == ["OFFICIAL_DAILY_EVIDENCE_REQUIRED"]
    assert quality["day_state_summary"]["groups"][0]["semantics"]["price_basis"]["limitations"] == ["basis unknown"]
    assert quality["decision_usable"] is False
    assert summary["change_pct"] == -1.0
    assert concise["technical"]["data"]["change_pct"] == 2.0
    assert concise["technical"]["data"]["market_session"] == full["technical"]["data"]["market_session"]
    # MCP wire-shape serialization only: no adapter invocation or host claim.
    mcp = {"content": [{"type": "text", "text": wire.decode()}], "structuredContent": concise, "isError": False}
    mcp_wire = encode(mcp)
    assert json.loads(mcp_wire)["structuredContent"] == concise
    assert len(mcp_wire) < 3 * WORKSPACE_RESEARCH_MAX_BYTES
    if days == 3000:
        assert len(wire) < len(full_wire) / 100
    print(json.dumps({"timeframe": timeframe, "days": days, "full_bytes": len(full_wire), "workspace_bytes": len(wire),
                      "mcp_envelope_bytes": len(mcp_wire), "full_encode_ms": round(full_ms, 3), "project_encode_ms": round(concise_ms, 3)}))


async def request(app, query):
    path, _, query_string = query.partition("?")
    messages = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
               "path": path, "raw_path": path.encode(), "query_string": query_string.encode(), "headers": [],
               "server": ("fixture", 80), "client": ("fixture", 123), "root_path": ""}, receive, send)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, body


@pytest.mark.parametrize("timeframe", ["today", "daily", "weekly", "monthly"])
def test_http_full_default_workspace_and_budget(db, timeframe):
    symbol = seed(db, 1)[0]
    db.execute(text("PRAGMA query_only=ON"))
    db.add(StockMaster(stock_id="pending", market="TWSE", instrument_type="stock"))
    app = FastAPI()
    app.include_router(router, prefix="/tw")
    app.dependency_overrides[get_db] = lambda: db
    full = report(timeframe, 3000)
    full["technical"]["stock_id"] = symbol
    path = f"/tw/stocks/{symbol}/research?timeframe={timeframe}"
    with patch("app.market.tw_market_dashboard.build_stock_technical_report", return_value=full["technical"]):
        samples = {}
        for projection in ("full", "workspace"):
            start = perf_counter()
            status, body = asyncio.run(request(app, path + f"&projection={projection}"))
            samples[projection] = {"bytes": len(body), "elapsed_ms": round((perf_counter()-start)*1000, 3)}
            assert status == 200
            assert json.loads(body)["technical"]["decision_usable"] is False
            if projection == "full":
                assert len(json.loads(body)["technical"]["data"]["input_quality"]["day_states"]) == 3000
                assert asyncio.run(request(app, path))[1] == body
            else:
                assert len(body) <= WORKSPACE_RESEARCH_MAX_BYTES
        assert asyncio.run(request(app, path + "&projection=invalid"))[0] == 422
        full["technical"]["warnings"] = ["警" * WORKSPACE_RESEARCH_MAX_BYTES]
        status, body = asyncio.run(request(app, path + "&projection=workspace"))
        assert status == 413
        assert json.loads(body)["detail"]["code"] == "TW_WORKSPACE_RESEARCH_BUDGET_EXCEEDED"
    assert db.new
    print(json.dumps({"http_fixture": timeframe, **samples}))


@pytest.mark.parametrize("timeframe", ["today", "daily", "weekly", "monthly"])
def test_real_report_empty_history_remains_truthful(db, timeframe):
    symbol = seed(db, 1)[0]
    db.execute(text("PRAGMA query_only=ON"))
    result = build_tw_stock_research(db, stock_id=symbol, timeframe=timeframe, projection="workspace")
    assert result["technical"]["stock_id"] == symbol
    assert len(encode(result)) <= WORKSPACE_RESEARCH_MAX_BYTES


@pytest.mark.parametrize("timeframe", ["today", "daily", "weekly", "monthly"])
def test_populated_canonical_report_projection(db, timeframe):
    symbol = seed(db, 1)[0]
    source = db.query(SourceRegistry).filter(SourceRegistry.parser_type == "twse_daily_trading").one()
    db.query(RawFetchResult).filter(RawFetchResult.source_id == source.id).update({"status_code": 200})
    day = date(2025, 1, 1)
    while day <= date(2026, 10, 8):
        if is_taiwan_trading_day(day) and day not in {date(2026, 8, 24), date(2026, 8, 25)}:
            raw = RawFetchResult(source_id=source.id, status_code=200, fetched_at=datetime.combine(day, datetime.min.time(), TAIWAN_TZ) + timedelta(hours=18),
                                 content_hash=str(day), parser_version="twse.stock_day_all.v1", raw_text="[]")
            db.add(raw)
            db.flush()
            close = 100 + day.day / 10
            db.add(MarketDailyPrice(source_id=source.id, raw_result_id=raw.id, stock_id=symbol, trade_date=day,
                                   open_price=close, high_price=close+1, low_price=close-1, close_price=close,
                                   price_change=0.1, trade_volume=10000))
        day += timedelta(days=1)
    db.commit()
    db.execute(text("PRAGMA query_only=ON"))
    start = perf_counter()
    full = build_tw_stock_research(db, stock_id=symbol, timeframe=timeframe)
    compute_ms = (perf_counter()-start)*1000
    start = perf_counter()
    full_wire = encode(TaiwanStockResearchRead.model_validate(full).model_dump(mode="json"))
    full_encode_ms = (perf_counter()-start)*1000
    start = perf_counter()
    concise = project_tw_workspace_research(full)
    concise_wire = encode(concise)
    projection_ms = (perf_counter()-start)*1000
    summary = concise["technical_summary"]
    original = full["technical"]["data"].get(summary["basis"], {})
    assert original.get("close") is not None, str(full["technical"])[:2500]
    for key in ("time", "close", "rsi", "macd", "kd", "change_pct"):
        assert json.loads(encode(summary[key])) == json.loads(encode(original.get(key)))
    for key in ("warnings", "missing", "title", "summary", "score", "confidence", "phase", "rows", "source_refs"):
        assert json.loads(encode(concise["technical"][key])) == json.loads(encode(full["technical"][key]))
    assert len(concise_wire) <= WORKSPACE_RESEARCH_MAX_BYTES
    print(json.dumps({"populated_fixture": timeframe, "compute_ms": round(compute_ms, 3), "full_bytes": len(full_wire),
                      "workspace_bytes": len(concise_wire), "full_encode_ms": round(full_encode_ms, 3), "projection_encode_ms": round(projection_ms, 3)}))


def test_search_etf_eligibility_and_no_autoflush(db):
    for symbol, market, kind, active in [("00631L", "TWSE", "ETF", True), ("2330", "TWSE", "stock", True),
                                        ("00632", "TPEX", "etf", True), ("00633", "TWSE", "warrant", True),
                                        ("00634", "US", "stock", True), ("00635", "TWSE", "etf", False)]:
        db.add(StockMaster(stock_id=symbol, stock_name=symbol, market=market, instrument_type=kind, is_active=active))
    db.commit()
    db.execute(text("PRAGMA query_only=ON"))
    db.add(StockMaster(stock_id="unflushed", market="TWSE", instrument_type="stock"))
    assert search_tw_dashboard_symbols(db, keyword="00631L")["count"] == 1
    assert {row["stock_id"] for row in search_tw_dashboard_symbols(db, keyword="006")["items"]} == {"00631L", "00632"}
    assert search_tw_dashboard_symbols(db, keyword="%_")["count"] == 0
    assert db.new


def test_quality_groups_keep_distinct_reasons_and_noncontiguous_counts():
    full = report("monthly", 3)
    quality = full["technical"]["data"]["input_quality"]
    quality["day_state_blockers"][1]["reasons"] = ["PRICE_BASIS_CHANGED"]
    quality["day_states"][1]["limitations"] = ["different limit"]
    result = project_tw_workspace_research(full)["technical"]["data"]["input_quality"]
    blockers = result["day_state_blocker_summary"]["groups"]
    assert [item["count"] for item in blockers] == [2, 1]
    assert blockers[0]["first_trade_date"] == "2015-01-01" and blockers[0]["last_trade_date"] == "2015-01-03"
    assert blockers[1]["semantics"]["reasons"] == ["PRICE_BASIS_CHANGED"]
    assert len(result["day_state_summary"]["groups"]) == 2


@pytest.mark.parametrize("timeframe", ["today", "daily", "weekly", "monthly"])
def test_dated_canonical_limitations_are_bounded_without_losing_reasons(timeframe):
    full = report(timeframe, 1700)
    quality = full["technical"]["data"]["input_quality"]
    tokens = [f"TW_DAILY_DAY_STATE:{state['trade_date']}:MISSING_EVIDENCE:OFFICIAL_DAILY_EVIDENCE_REQUIRED"
              for state in quality["day_states"]]
    quality["canonical_limitations"] += tokens
    quality["decision_window"] = {"continuous": False, "eligible": False, "missing_trading_day_count": None}
    quality["history_coverage"] = {"status": "partial", "reason_codes": ["HISTORY_GAP"]}
    full["technical"]["evidence_passport"] = {"source_refs": [{"source": "synthetic"}], "warnings": ["partial"], "as_of": None}
    full["limitations"] = ["original envelope limitation"]
    before = deepcopy(full)
    projected = project_tw_workspace_research(full)
    assert full == before
    assert len(encode(projected)) < 96 * 1024
    assert projected["limitations"][0] == "original envelope limitation"
    assert projected["technical"]["evidence_passport"] == full["technical"]["evidence_passport"]
    for key, value in full["technical"]["data"].items():
        if key == "input_quality":
            continue
        if isinstance(value, dict) and "input_quality" in value:
            assert {k: v for k, v in projected["technical"]["data"][key].items() if k != "input_quality"} == {k: v for k, v in value.items() if k != "input_quality"}
        else:
            assert projected["technical"]["data"][key] == value
    compact = projected["technical"]["data"]["input_quality"]
    summary = compact["canonical_limitations_summary"]
    assert compact["canonical_limitations"] == ["unknown calendar"]
    assert summary["total_count"] == 1701 and summary["grouped_count"] == 1700 and summary["retained_count"] == 1
    assert summary["groups"] == [{"state": "MISSING_EVIDENCE", "reason": "OFFICIAL_DAILY_EVIDENCE_REQUIRED",
                                  "count": 1700, "first_trade_date": "2015-01-01", "last_trade_date": quality["day_states"][-1]["trade_date"]}]
    assert summary["date_bounds_are_continuous"] is False
    assert summary["details_projection"] == "full" and summary["details_field"] == "canonical_limitations"
    for key in quality.keys() - {"canonical_limitations", "day_states", "day_state_blockers"}:
        assert compact[key] == quality[key]
    assert compact == projected["technical"]["data"][projected["technical_summary"]["basis"]]["input_quality"]


def test_limitation_grouping_retains_unknown_malformed_and_noncontiguous_semantics():
    from app.market.tw_workspace_research import _compact_quality
    retained = ["future restriction", "TW_DAILY_DAY_STATE:2026-02-30:UNKNOWN:RISK",
                "TW_DAILY_DAY_STATE:20260101:UNKNOWN:RISK", "OTHER:2026-01-01:UNKNOWN:RISK",
                "TW_DAILY_DAY_STATE:2026-01-01::RISK", "TW_DAILY_DAY_STATE:2026-01-01:UNKNOWN:", None]
    quality = {"decision_usable": None, "canonical_limitations": retained + [
        "TW_DAILY_DAY_STATE:2026-01-03:UNKNOWN:RISK:with_suffix",
        "TW_DAILY_DAY_STATE:2026-01-01:UNKNOWN:RISK:with_suffix",
        "TW_DAILY_DAY_STATE:2026-01-01:UNKNOWN:RISK:with_suffix",
        "TW_DAILY_DAY_STATE:2026-01-02:CONFLICTED_EVIDENCE:RISK:with_suffix",
        "TW_DAILY_DAY_STATE:2026-01-02:UNKNOWN:DIFFERENT_RISK",
    ], "future_axis": {"state": None, "limitations": ["keep"]}}
    before = deepcopy(quality)
    compact = _compact_quality(quality)  # Also works if the producer omits day_states.
    assert quality == before
    assert compact["canonical_limitations"] == retained
    assert compact["decision_usable"] is None and compact["future_axis"] == quality["future_axis"]
    summary = compact["canonical_limitations_summary"]
    assert summary["grouped_count"] == 5 and summary["retained_count"] == len(retained)
    assert summary["groups"][0] == {"state": "UNKNOWN", "reason": "RISK:with_suffix", "count": 3,
                                     "first_trade_date": "2026-01-01", "last_trade_date": "2026-01-03"}
    assert len(summary["groups"]) == 3
    assert _compact_quality({"canonical_limitations": retained}) == {"canonical_limitations": retained}


def test_distinct_limitation_reasons_still_fail_closed_over_budget():
    full = report("monthly", 1)
    quality = full["technical"]["data"]["input_quality"]
    quality["canonical_limitations"] = [f"TW_DAILY_DAY_STATE:2026-01-01:UNKNOWN:DISTINCT_{i}" for i in range(1500)]
    before = deepcopy(full)
    with pytest.raises(TaiwanResearchProjectionTooLarge):
        project_tw_workspace_research(full)
    assert full == before


def test_chart_projects_resolver_coverage_before_display_slice(db):
    at = datetime(2026, 10, 8, 9, 2, tzinfo=TAIWAN_TZ)
    points = [{"time": at + timedelta(minutes=i), "close": 100} for i in range(263)]
    coverage = {"contract_version": "tw.bar.current_session_coverage.v2", "trade_date": "2026-10-08",
                "status": "trailing_window", "session_completed": True, "expected_bucket_count": 265,
                "observed_bucket_count": 263, "missing_bucket_count": 2, "snapshot_reason_codes": ["MISSING_OPENING"],
                "current_cumulative_volume_complete": False}
    history = {"points": points, "series_coverage": coverage, "cache_trade_date": "2026-10-08",
               "cache_latest_time": points[-1]["time"], "limitations": ["opening unknown"], "resolved_health": {"status": "partial"}}
    with patch("app.market.tw_market_dashboard.get_market_intraday_history", return_value=history) as read:
        chart, _ = _dashboard_intraday_chart(db, stock_id="00631L", bars=20)
    assert chart["series_coverage"] is coverage
    model = TaiwanDashboardIntradayChartRead.model_validate(chart)
    assert model.series_coverage.session_completed is True
    assert model.series_coverage.current_cumulative_volume_complete is False
    assert model.series_coverage.snapshot_reason_codes == ["MISSING_OPENING"]
    assert model.point_count == 20 and model.points[-1].time.hour == 13 and model.points[-1].time.minute == 24
    assert model.coverage_scope == "resolver_series_before_display_slice"
    assert model.cache_latest_time.date() == date(2026, 10, 8)
    assert model.limitations == ["opening unknown"]
    read.assert_called_once_with(db=db, stock_id="00631L", interval="1m", range_value="5d", refresh=False)


def test_generated_contract_exposes_workspace_input_and_schema():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("tw_gates_generator", root / "scripts/generate-tw-dashboard-mcp-contract-snapshot.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generated = generator._load_snapshot()
    research = next(t for t in generated["workspace_tools"] if t["name"] == "omi.read_tw_stock_research")
    assert research["inputSchema"]["properties"]["projection"]["default"] == "full"
    assert "anyOf" in research["outputSchema"]
    definitions = research["outputSchema"]["$defs"]
    assert definitions["TaiwanWorkspaceResearchRead"]["properties"]["version"]["const"] == "omi.tw_stock_research.workspace.v1"
    assert definitions["TaiwanStockResearchRead"]["properties"]["version"]["const"] == "omi.tw_stock_research.v1"
    assert {"time", "close", "rsi", "macd", "kd", "change_pct"} <= definitions["WorkspaceIndicatorSummary"]["properties"].keys()
