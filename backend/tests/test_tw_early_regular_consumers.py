"""Persisted recorded early bars through real HTTP routes and MCP forwarding."""
from datetime import datetime, timedelta, timezone
import importlib.util
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.market.trading_calendar import TAIWAN_TZ
from app.routers import ai, market, tw_market_bars, tw_market_dashboard
from test_tw_early_regular_daily import DAY, EARLY, FINAL, seed, acquire, payload


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return EARLY.astimezone(tz) if tz else EARLY.replace(tzinfo=None)


class OfflineClient:
    """Use the repo's native ASGI test pattern without installing HTTP clients."""
    def __init__(self, app):
        self.app = app

    def request(self, method, path, *, params=None, body=None):
        messages = []
        async def run():
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode() if body is not None else b"", "more_body": False}
            async def send(message):
                messages.append(message)
            await self.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                "query_string": urlencode(params or {}, doseq=True).encode(),
                "headers": [(b"content-type", b"application/json")], "client": ("offline", 1),
                "server": ("offline", 80)}, receive, send)
        asyncio.run(run())
        raw = b"".join(m.get("body", b"") for m in messages[1:]).decode()
        return SimpleNamespace(status_code=messages[0]["status"], text=raw, json=lambda: json.loads(raw))

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, json):
        return self.request("POST", path, body=json)


@pytest.fixture
def consumer(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db)
        # Synthetic prior-day storage state only, not a historical source claim.
        # The current early payload/receipt remains the recorded 11/03 excerpt.
        prior = payload()
        prior["date"] = (DAY - timedelta(days=1)).strftime("%Y%m%d")
        acquire(db, now=FINAL - timedelta(days=1), body=prior, trade_date=DAY - timedelta(days=1))
        acquire(db)
        app = FastAPI()
        app.include_router(market.router, prefix="/api/market")
        app.include_router(tw_market_bars.router, prefix="/api/market")
        app.include_router(tw_market_dashboard.router, prefix="/api/market/tw-dashboard")
        app.include_router(ai.router, prefix="/api/ai")
        app.dependency_overrides[get_db] = lambda: db
        monkeypatch.setattr("app.market.daily_ohlcv_platform.datetime", FrozenDatetime)
        monkeypatch.setattr("app.market.tw_bar_service.datetime", FrozenDatetime)
        monkeypatch.setattr("app.market.tw_market_dashboard.datetime", FrozenDatetime)
        monkeypatch.setattr("app.market.trading_calendar.taiwan_now", lambda now=None: (now or EARLY).astimezone(TAIWAN_TZ))
        monkeypatch.setattr("app.ai.tools._now", lambda: EARLY)
        def forbidden(*args, **kwargs): raise AssertionError("Consumer attempted public HTTP acquisition")
        monkeypatch.setattr("requests.sessions.Session.request", forbidden)
        db.execute(text("PRAGMA query_only=ON"))
        statements = []
        def capture(_conn, _cursor, sql, *_args): statements.append(sql.lstrip().upper())
        event.listen(engine, "before_cursor_execute", capture)
        yield OfflineClient(app), db, statements
        event.remove(engine, "before_cursor_execute", capture)
    engine.dispose()


def mcp_server():
    path = Path(__file__).parents[2] / "agents/omi_mcp_server/server.py"
    spec = importlib.util.spec_from_file_location("early_daily_mcp", path)
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    return server


def test_http_daily_today_and_raw_mcp_bars_preserve_research_scope(consumer):
    client, db, statements = consumer
    strict = client.get("/api/market/ohlc/2330", params={"bars": 1, "include_intraday": False})
    assert strict.status_code == 200 and strict.json()["latest_data_date"] == (DAY - timedelta(days=1)).isoformat()
    assert strict.json()["points"][-1]["release_status"] == "released"
    early = client.get("/api/market/ohlc/2330", params={"bars": 1, "allow_early_regular": True})
    assert early.status_code == 200, early.text
    chart = early.json()
    assert chart["latest_data_date"] == DAY.isoformat()
    assert chart["release_status"] == "regular_research" and not chart["official_final"]
    assert chart["latest_finalized_data_date"] == (DAY - timedelta(days=1)).isoformat() and not chart["decision_usable"]
    assert chart["points"][0]["trading_scope"] == "regular_session"
    assert chart["points"][0]["raw_receipt_id"]
    for timeframe in ("daily", "today"):
        r = client.get("/api/market/tw-dashboard/stocks/2330/chart", params={"timeframe": timeframe, "bars": 20})
        assert r.status_code == 200, r.text
        assert r.json()["chart"]["latest_data_date"] == DAY.isoformat()
        assert r.json()["chart"]["points"][-1]["release_status"] == "regular_research"
        if timeframe == "today":
            assert not r.json()["intraday_chart"]["points"]  # no 1m bars manufactured from daily
    old_date = DAY - timedelta(days=1)
    with patch("app.market.tw_market_dashboard.get_market_intraday_history", return_value={
        "points": [{"time": f"{old_date}T13:30:00+08:00", "open": 2330, "high": 2330, "low": 2330, "close": 2330, "volume": 1000}]}):
        old = client.get("/api/market/tw-dashboard/stocks/2330/chart", params={"timeframe": "today", "bars": 20})
    assert old.status_code == 200, old.text
    assert old.json()["intraday_chart"]["trade_date"] == old_date.isoformat()
    assert old.json()["intraday_chart"]["session_relation"] == "previous_session"
    assert old.json()["chart"]["latest_data_date"] == DAY.isoformat()
    server = mcp_server()
    def get(path, params):
        r = client.get(path, params={k: v for k, v in params.items() if v is not None})
        assert r.status_code == 200, r.text
        return r.json()
    with patch.object(server, "_api_get", side_effect=get):
        bars = server._call_tool("omi.read_taiwan_bars", {"instrument_id": "2330", "interval": "1d",
            "from": "2026-11-03T00:00:00+08:00", "to": "2026-11-03T14:35:00+08:00", "include_partial": True})
        strict_bars = server._call_tool("omi.read_taiwan_bars", {"instrument_id": "2330", "interval": "1d",
            "from": "2026-11-03T00:00:00+08:00", "to": "2026-11-03T14:35:00+08:00", "include_partial": False})
    assert len(bars["bars"]) == 1 and not strict_bars["bars"]
    assert bars["bar_states"][0]["release_status"] == "pending_release"
    assert bars["bar_states"][0]["technical_eligible"] is False
    assert "OFFICIAL_FINAL_PENDING" in bars["bars"][0]["limitations"]
    assert statements and not any(sql.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "REPLACE")) for sql in statements)


def test_http_and_mcp_daily_capability_read_same_early_bar_cache_only(consumer):
    client, db, statements = consumer
    request = {"question": "讀取 2330 今日一般交易日 K 供研究", "mode": "data_only", "output": "evidence_only",
        "target": {"type": "tw_stock", "id": "2330", "market": "TW"}, "allow_llm": False,
        "allow_write": False, "allow_external_fetch": False, "realtime_policy": "cache_only",
        "refresh_policy": {"mode": "off", "before_answer": False},
        "selection": {"include": ["daily.ohlcv"], "limits": {"daily.ohlcv": 2}}}
    r = client.post("/api/ai/ask", json=request)
    assert r.status_code == 200, r.text
    evidence = r.json()["evidence"]["data"]["daily.ohlcv"]
    assert evidence["latest_data_date"] == DAY.isoformat(), evidence
    assert evidence["release_status"] == "regular_research" and not evidence["official_final"]
    point = (evidence.get("points") or [evidence.get("latest_point", {})])[-1]
    assert point.get("trading_scope") == "regular_session", evidence
    assert point["raw_receipt_id"] and evidence["decision_usable"] is False
    server = mcp_server()
    def post(path, payload):
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        return response.json()
    with patch.object(server, "_api_post", side_effect=post):
        mcp = server._call_tool("omi.ask", request)
    assert mcp["evidence"]["data"]["daily.ohlcv"] == evidence
    assert statements and not any(sql.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "REPLACE")) for sql in statements)


def test_completed_daily_full_scan_uses_early_and_preserves_history_gate(sessions, monkeypatch):
    # Real snapshot migration/transaction fixture; daily evidence is the recorded
    # early receipt. Geometry is an isolated test fixture, not a live MA60 claim.
    import test_tw_price_map_screening as existing
    from fastapi import Request
    from fastapi.encoders import jsonable_encoder
    from app.ai.schemas import AiAskV4Request
    from app.market.tw_price_map_screening import build_tw_price_map_screening_snapshot
    with sessions() as db:
        seed(db)
        acquire(db)
        monkeypatch.setattr(existing, "BASIS", DAY)
        monkeypatch.setattr(existing, "NOW", EARLY + timedelta(minutes=119))
        original_payload = existing.payload
        def geometry(*args, **kwargs):
            result = original_payload(*args, **kwargs)
            result["zones"][0].update(lower_bound=2290, upper_bound=2300)
            return result
        monkeypatch.setattr(existing, "payload", geometry)
        existing.publish(db)
        db.execute(text("PRAGMA query_only=ON"))
        with patch("app.market.tw_price_map_screening.read_price_map_external_revision", return_value="corp"), \
                patch("app.market.tw_price_map_screening.datetime", FrozenDatetime), patch("app.ai.tools._now", return_value=EARLY):
            result = build_tw_price_map_screening_snapshot(db, parameters={"lane": "completed_daily"}, generated_at=EARLY)
            http = market.get_taiwan_price_map_screening(timeframe="daily", relation="within_zone", zone_side="any",
                lane="completed_daily", near_pct=0.5, limit=20, offset=0, stock_ids=None, db=db)
            request = {"question": "盤後一般交易收盤價落在價位帶的研究候選", "mode": "data_only", "output": "evidence_only",
                "target": {"type": "market", "market": "TW"}, "allow_llm": False, "allow_write": False,
                "allow_external_fetch": False, "realtime_policy": "cache_only", "refresh_policy": {"mode": "off", "before_answer": False},
                "selection": {"include": ["screening.price_map"], "parameters": {"screening.price_map": {"lane": "completed_daily", "relation": "within_zone"}}}}
            def post(path, payload):
                assert path == "/api/ai/ask"
                return jsonable_encoder(ai.ask_omi(Request({"type": "http", "headers": [], "client": ("offline", 1)}), AiAskV4Request.model_validate(payload), db=db))
            server = mcp_server()
            with patch.object(server, "_api_post", side_effect=post):
                mcp = server._call_tool("omi.ask", request)
        assert result["coverage"]["eligible_symbols"] == 1 and not result["coverage"]["complete"]
        assert result["release_status"] == "regular_research" and not result["decision_usable"]
        # A prepared historical structure can inspect the actual early price;
        # the other stocks remain explicitly excluded when their structure is missing.
        assert result["coverage"]["matched_symbols"] == 1 and result["rows"][0]["current_price"] == 2295
        assert result["coverage"]["excluded_reason_counts"] == {"SNAPSHOT_NOT_COMPUTED": 3}
        assert http["rows"][0]["observation"]["release_status"] == "regular_research"
        assert http["rows"][0]["observation"]["trade_date"] == DAY
        assert jsonable_encoder(http)["rows"][0]["observation"]["trade_date"] == DAY.isoformat()
        evidence = mcp["evidence"]["data"]["screening.price_map"]
        assert evidence["rows"][0]["observation"]["trade_date"] == DAY.isoformat()
        assert evidence["rows"][0]["observation"]["price_semantics"] == "official_regular_session_research_close"
        assert evidence["rows"][0]["decision_usable"] is False and not evidence["decision_usable"]


from test_tw_price_map_screening import sessions  # noqa: E402,F401
