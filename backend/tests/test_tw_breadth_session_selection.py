"""Offline receipt replay: breadth selection, without adopting a live runtime."""

from datetime import date, datetime, timedelta, timezone
import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import event

from app.db.models import RawFetchResult, SourceRegistry, TaiwanPublishedBreadthSnapshot
from app.market.indices import get_market_index_summary
from app.market.official_breadth_platform import read_taiwan_official_breadth
from app.market.taiwan_rules import expected_daily_price_date, taiwan_daily_price_release_at
from app.market.tw_current_market_platform import read_taiwan_breadth_lanes
from app.market.tw_market_dashboard import _build_resolved_indices, build_tw_market_dashboard
from app.market.tw_market_dashboard_schemas import TaiwanDashboardBreadthRead, TaiwanMarketDashboardRead
from app.market.schemas import MarketIndexSummaryRead
from app.parsers.twse_published_breadth import PublishedStockBreadth, TWSE_AGGREGATE_SCOPE, TPEX_AGGREGATE_SCOPE
from app.sources.defaults import TWSE_RWD_DAILY_TRADING_SOURCE_NAME, TPEX_MARKET_HIGHLIGHT_SOURCE_NAME
from test_tw_official_breadth_platform import db


TZ = timezone(timedelta(hours=8))
DAY = date(2026, 11, 3)
# Replayed counts supplied in the work item, not an assertion of current live DB.
CASES = {
    "TWSE": (58, 1000, 22, 8, 1088, TWSE_AGGREGATE_SCOPE, TWSE_RWD_DAILY_TRADING_SOURCE_NAME),
    "TPEX": (59, 782, 32, 24, 897, TPEX_AGGREGATE_SCOPE, TPEX_MARKET_HIGHLIGHT_SOURCE_NAME),
}


def at(hour, minute=0, second=0, *, day=3):
    return datetime(2026, 11, day, hour, minute, second, tzinfo=TZ)


def persist(db, venue, *, trade_date=DAY, fetched_at=None):
    up, down, flat, unknown, total, scope, source_name = CASES[venue]
    source = db.query(SourceRegistry).filter_by(source_name=source_name).first()
    if source is None:
        source = SourceRegistry(source_name=source_name, source_type="api", category="market", reliability_level="official")
        db.add(source)
        db.flush()
    parsed = PublishedStockBreadth(
        venue=venue, trade_date=trade_date, advance=up, decline=down, unchanged=flat,
        no_trade=0 if venue == "TWSE" else unknown,
        no_comparison=unknown if venue == "TWSE" else 0,
        limits=dict(scope=scope, universe_count=total, up_count=1, down_count=2),
    )
    raw = RawFetchResult(source_id=source.id, fetched_at=(fetched_at or at(14)).astimezone(timezone.utc).replace(tzinfo=None),
                         status_code=200, content_hash="a" * 64)
    db.add(raw)
    db.flush()
    stored = TaiwanPublishedBreadthSnapshot(venue=venue, trade_date=trade_date, raw_result_id=raw.id,
                                           payload_json=parsed.model_dump_json())
    db.add(stored)
    db.commit()
    return raw, stored, source


def persist_mis(db, venue):
    from app.market.providers.tw_current_market import CurrentBreadthAdapter
    from app.market.tw_current_market_acquisition import TaiwanCurrentBreadthAcquisitionExecutor
    from app.market.tw_current_market_capabilities import TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR, TW_CURRENT_BREADTH_CAPABILITY_ID
    from app.market.tw_current_market_platform import refresh_taiwan_current_breadth
    from test_tw_current_market_platform import _binding, _payload_reader

    received, total = (100, 1080) if venue == "TWSE" else (852, 887)
    # Synthetic directions; only coverage counts replay the reported MIS state.
    payload = dict(snapshot_as_of=at(13, 29).isoformat(), trade_date=DAY.isoformat(),
                   scope="full_market_registered_stock_universe", universe_source=f"stock_master.active.{venue}.ordinary_stock",
                   universe_count=total, advance_count=received, decline_count=0, unchanged_count=0,
                   received_unclassified_count=0, not_received_count=total - received)
    adapter = CurrentBreadthAdapter(_binding("twse_mis", "twse_mis_live_breadth", TW_CURRENT_BREADTH_CAPABILITY_ID),
                                   _payload_reader(payload, [], "mis"), clock=lambda: at(13, 29))
    refresh_taiwan_current_breadth(db, venue=venue, requested_at=at(13, 29),
        descriptors=(TWSE_MIS_CURRENT_BREADTH_DESCRIPTOR,), acquisition=TaiwanCurrentBreadthAcquisitionExecutor((adapter,)))


@pytest.mark.parametrize("venue", CASES)
@pytest.mark.parametrize("hour,minute,second,selected_lane,target_day", [
    (7, 59, 59, "official_daily", 2),
    (8, 0, 0, "official_daily", 2),
    (8, 30, 0, "official_daily", 2),
    (8, 59, 59, "official_daily", 2),
    (9, 0, 0, "current_registered", None),
    (12, 0, 0, "current_registered", None),
    (13, 25, 0, "current_registered", None),
    (13, 29, 59, "current_registered", None),
    (13, 30, 0, "official_daily", 3),
    (13, 31, 0, "official_daily", 3),
    (15, 15, 0, "official_daily", 3),
])
def test_selection_boundaries_without_receipt(db, venue, hour, minute, second, selected_lane, target_day):
    lanes = read_taiwan_breadth_lanes(db, venue=venue, requested_at=at(hour, minute, second))
    assert lanes["selected_lane"] == selected_lane
    assert lanes["status"] == ("pending" if target_day else "not_applicable")
    if target_day:
        assert lanes["trade_date"] == DAY.replace(day=target_day)


@pytest.mark.parametrize("venue", CASES)
def test_qualified_early_aggregate_is_independent_of_daily_ohlcv(db, venue):
    raw, _, _ = persist(db, venue, fetched_at=at(13, 31))
    result = read_taiwan_official_breadth(db, venue=venue, requested_at=at(13, 32), allow_universe_fallback=False)
    assert result.resolved.breadth.lineage.raw_receipt_id == f"raw_fetch_result:{raw.id}"
    assert result.resolved.breadth.lineage.received_at is None
    assert result.resolved.breadth.lineage.fetched_at == at(13, 31)
    lanes = read_taiwan_breadth_lanes(db, venue=venue, requested_at=at(13, 32))
    assert lanes["status"] == "selected"
    assert lanes["official_daily"]["official"] is True
    assert lanes["official_daily"]["finalization"] == "official_final"
    assert lanes["official_daily"]["decision_usable"] is False
    assert expected_daily_price_date(now=at(14, 30)) == date(2026, 11, 2)
    assert taiwan_daily_price_release_at(DAY) == at(15, 15)
    # Preopen keeps yesterday until the first regular-session requirement.
    persist(db, venue, trade_date=date(2026, 11, 2), fetched_at=at(16, day=2))
    assert read_taiwan_breadth_lanes(db, venue=venue, requested_at=at(8, 59))["trade_date"] == date(2026, 11, 2)
    next_day = read_taiwan_breadth_lanes(db, venue=venue, requested_at=at(8, 45, day=4))
    assert next_day["status"] == "selected"
    assert next_day["official_daily"]["trade_date"] == DAY
    assert read_taiwan_breadth_lanes(db, venue=venue, requested_at=at(13, 30))["status"] == "pending"


@pytest.mark.parametrize("venue", CASES)
@pytest.mark.parametrize("fault", ["preclose", "future", "source", "authority", "http", "error", "payload", "date", "venue", "scope", "partition", "zero"])
def test_invalid_receipt_never_replaces_mis_or_becomes_official(db, venue, fault):
    raw, stored, source = persist(db, venue)
    if fault == "preclose": raw.fetched_at = at(13, 29).astimezone(timezone.utc).replace(tzinfo=None)
    elif fault == "future": raw.fetched_at = at(19).astimezone(timezone.utc).replace(tzinfo=None)
    elif fault == "source": source.source_name = "untrusted_source"
    elif fault == "authority": source.reliability_level = "unknown"
    elif fault == "http": raw.status_code = 503
    elif fault == "error": stored.error_code = "OFFICIAL_AGGREGATE_RECEIPT_REJECTED"
    elif fault == "payload": stored.payload_json = "{"
    else:
        payload = json.loads(stored.payload_json)
        if fault == "date": payload["trade_date"] = "2026-11-02"
        elif fault == "venue": payload["venue"] = "TPEX" if venue == "TWSE" else "TWSE"
        elif fault == "scope": payload["limits"]["scope"] = "active_ordinary_stock_universe"
        elif fault == "partition": payload["unchanged"] += 1
        elif fault == "zero":
            for key in ("advance", "decline", "unchanged", "no_trade", "no_comparison"): payload[key] = 0
            payload["limits"].update(universe_count=0, up_count=0, down_count=0)
        stored.payload_json = json.dumps(payload)
    db.commit()
    lanes = read_taiwan_breadth_lanes(db, venue=venue, requested_at=at(18))
    assert lanes["status"] == "pending"
    assert lanes["selected_lane"] == "official_daily"
    assert lanes["official_daily"]["decision_usable"] is False


@pytest.mark.parametrize("available", [False, True])
def test_actual_summary_and_dashboard_paths_preserve_scopes_and_pending(db, available, tmp_path):
    for venue in CASES:
        persist_mis(db, venue)
    if available:
        for venue, receipt_at in [("TWSE", at(15, 20, 20)), ("TPEX", at(17, 3, 53))]:
            persist(db, venue, fetched_at=receipt_at)
    statements = []
    def capture(_conn, _cursor, statement, *_): statements.append(statement.lower())
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with patch("requests.sessions.Session.request", side_effect=AssertionError("external IO")):
            summary = get_market_index_summary(db, requested_at=at(18), allow_universe_fallback=False)
            _, resolved, _ = _build_resolved_indices(db, requested_at=at(18), allow_universe_fallback=False)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert not any(s.lstrip().startswith(("insert", "update", "delete")) for s in statements)
    serialized = MarketIndexSummaryRead.model_validate(summary).model_dump(mode="json")
    (tmp_path / ("official-summary.json" if available else "pending-summary.json")).write_text(
        json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in summary["indices"]:
        venue = item["market"]
        lanes = item["breadth_lanes"]
        assert lanes["selected_lane"] == "official_daily"
        assert "current_registered" in lanes
        mis_count, mis_total = (100, 1080) if venue == "TWSE" else (852, 887)
        assert lanes["current_registered"]["received_count"] == mis_count
        assert lanes["current_registered"]["total_count"] == mis_total
        assert lanes["current_registered"]["received_coverage_ratio"] == mis_count / mis_total
        main = TaiwanDashboardBreadthRead.model_validate(resolved[venue])
        if available:
            up, down, flat, unknown, total, scope, _ = CASES[venue]
            assert (main.advance, main.decline, main.unchanged, main.unknown, main.universe) == (up, down, flat, unknown, total)
            assert (item["breadth"]["advance_count"], item["breadth"]["total_count"]) == (up, total)
            assert main.official is True and main.provisional is False
            assert main.finalization == "official_final"
            assert main.scope == scope
            assert main.decision_usable is False
            assert main.status == "partial"
            http_breadth = next(i["breadth"] for i in serialized["indices"] if i["market"] == venue)
            assert http_breadth["official"] is True
            assert http_breadth["finalization"] == "official_final"
            assert http_breadth["total_count"] == total
            assert main.observation_coverage_ratio == 1
            assert main.coverage_ratio == (up + down + flat) / total
        else:
            assert item["breadth"] is None
            assert item["breadth_status"]["status"] == "pending"
            assert main.status == "pending" and main.universe is None
            assert main.unknown is None and main.advance is None
            with pytest.raises(ValidationError):
                TaiwanDashboardBreadthRead.model_validate({**resolved[venue], "advance": 0})


@pytest.mark.parametrize("venue", CASES)
def test_official_http_api_reads_qualified_published_receipt(db, venue):
    from app.routers import market
    persist(db, venue)
    app = FastAPI()
    app.include_router(market.router, prefix="/api/market")
    app.dependency_overrides[market.get_db] = lambda: db
    result = read_taiwan_official_breadth(db, venue=venue, requested_at=at(18))
    messages = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "GET", "scheme": "http", "path": "/api/market/breadth/official",
             "query_string": f"venue={venue}".encode(), "headers": [],
             "server": ("offline.test", 80), "client": ("127.0.0.1", 1), "root_path": ""}
    with patch.object(market, "read_taiwan_official_breadth", return_value=result):
        # No server/process/lifespan startup, only the actual route and model.
        asyncio.run(app(scope, receive, send))
    assert next(m for m in messages if m["type"] == "http.response.start")["status"] == 200
    data = json.loads(b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body"))["resolved"]["breadth"]
    assert data["universe_count"] == CASES[venue][4]
    assert data["official"] is True and data["provisional"] is False


@pytest.mark.parametrize("now,expected_status,expected_day", [
    (at(13, 29), "partial", 3),
    (at(13, 30), "pending", 3),
    (at(13, 32), "partial", 3),
    (at(8, 45, day=4), "partial", 3),
])
def test_dashboard_now_reaches_breadth_selection_without_wall_clock(db, now, expected_status, expected_day):
    for venue in CASES:
        persist_mis(db, venue)
        persist(db, venue, fetched_at=at(13, 31))
    with patch("app.market.tw_market_dashboard._build_resolved_indices", wraps=_build_resolved_indices) as read:
        payload = TaiwanMarketDashboardRead.model_validate(build_tw_market_dashboard(db, now=now))
    read.assert_called_once_with(db, requested_at=now)
    for venue, main in payload.resolved_breadth.items():
        assert main.status == expected_status
        assert main.trade_date == DAY.replace(day=expected_day)
        assert main.official is (now >= at(13, 31))
        if now >= at(13, 31):
            assert main.universe == CASES[venue][4]
            assert main.observation_received_at is None
            assert main.finalization == "official_final"
        elif expected_status == "pending":
            assert main.advance is None
        else:
            assert main.universe == (1080 if venue == "TWSE" else 887)
            assert main.provisional is True
    assert set(payload.resolved_breadth) == set(CASES)
