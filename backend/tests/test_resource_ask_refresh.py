from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import json

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai.schemas import AiAskRequest
from app.db.models import Base, ResourceQuoteSnapshot, ResourceOhlcvBar
from app.resource_market import service, source_health
from app.resource_market.contract import list_resource_instruments
from app.resource_market.sources import parse_yahoo_quote_record

NOW = datetime(2026, 10, 26, 15, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def isolated_clock_and_network():
    with patch("app.resource_market.source_health._now", return_value=NOW), \
         patch("app.resource_market.sources._now", return_value=NOW), \
         patch("app.resource_market.service.utc_now", return_value=NOW), \
         patch("app.resource_market.providers.yahoo.fetch_chart_payload", side_effect=AssertionError("real provider forbidden")):
        yield


def seed(db, symbol="GC", event_time=NOW - timedelta(days=17), price=100):
    instrument = list_resource_instruments(symbol=symbol)[0]
    values = {name: getattr(instrument, name) for name in (
        "provider", "exchange", "symbol", "provider_symbol", "name", "root_folder",
        "group", "asset_class", "base_asset", "quote_asset", "instrument_type")}
    row = ResourceQuoteSnapshot(**values, contract_key=instrument.contract_type,
                                last_price=price, event_time=event_time, fetched_at=NOW,
                                source_url="https://example.invalid/fixture")
    db.add(row)
    db.commit()
    return row


def chart(symbol="GC", event_time=NOW - timedelta(minutes=20), price=200):
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": f"{symbol}=F", "regularMarketPrice": price,
                 "regularMarketTime": int(event_time.timestamp())},
        "timestamp": [int(NOW.replace(hour=4).timestamp())],
        "indicators": {"quote": [{"close": [price], "open": [price - 1],
                                  "high": [price + 1], "low": [price - 2], "volume": [123]}]}
    }]}}


def ask(db, symbol="GC", trusted=True, **overrides):
    args = dict(contract_version="omi.decision.v4", question=f"{symbol} 最新價格",
                target={"type": "resource_asset", "id": symbol}, mode="data_only",
                output="evidence_only", allow_external_fetch=True,
                realtime_policy="prefer_live", refresh_policy={"before_answer": True},
                selection={"include": ["quote.snapshot", "daily.ohlcv"]})
    args.update(overrides)
    return jsonable_encoder(ai_ask.ask(db, AiAskRequest(**args), server_policy=ai_ask.AiAskServerPolicy(
        can_external_fetch=trusted, trust_source="isolated_test")))


@pytest.mark.parametrize("symbol", ["GC", "CL", "SI", "HG", "BZ", "NG"])
def test_formal_ask_refreshes_once_and_rereads_v4(db, symbol):
    seed(db, symbol)
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval",
                      return_value=(chart(symbol), "https://example.invalid/fixture")) as fetch:
        result = ask(db, symbol)
    assert fetch.call_count == 1
    assert fetch.call_args.kwargs["range_value"] == "5d"
    assert fetch.call_args.kwargs["interval"] == "1d"
    assert fetch.call_args.kwargs["timeout_seconds"] <= 10
    assert service.list_latest_resource_quotes(db, symbols=symbol)[0].last_price == 200
    assert db.query(ResourceOhlcvBar).count() == 1
    assert result["contract_version"] == "omi.decision.v4"
    quote = result["evidence"]["data"]["quote.snapshot"]
    assert quote["last_price"] == 200
    assert quote["event_time"].startswith("2026-10-26T14:40")
    assert quote["provider"] == "yahoo_chart"
    assert quote["freshness"]["status"] == "delayed"
    assert quote["freshness"]["required_session_lag_seconds"] == 1200
    assert quote["decision_usable"] is False
    assert quote["volume_unit"] is None
    assert "watch_only" in quote["limitations"]
    assert "best_effort_delayed" in quote["limitations"]
    quality = result["evidence"]["quality"]["capabilities"]["quote.snapshot"]
    assert quality["freshness"] == "delayed"
    assert quality["facts_usable"] is True
    assert quality["decision_usable"] is False
    assert quality["units"]["missing_volume_unit"] is True
    assert "volume_unit_missing" in quality["issues"]
    assert quality["status_class"] != "blocked"
    assert result["evidence"]["realtime"]["quote.snapshot"]["state"] == "delayed"
    assert result["execution"]["tool_runs"][0]["status"] == "success"


@pytest.mark.parametrize("overrides,trusted", [
    ({"allow_external_fetch": False}, True),
    ({}, False),
    ({"realtime_policy": "cache_only"}, True),
    ({"refresh_policy": {"mode": "off", "before_answer": True}}, True),
    ({"refresh_policy": {"before_answer": False}}, True),
    ({"tool_budget": {"max_calls": 0}}, True),
    ({"tool_budget": {"max_external_fetches": 0}}, True),
    ({"tool_budget": {"max_total_seconds": 0}}, True),
    ({"tool_budget": {"max_total_seconds": -1}}, True),
    ({"selection": {"include": ["resource.metadata"]}}, True),
])
def test_policy_negatives_have_no_fetch_or_db_write(db, overrides, trusted):
    seed(db)
    writes = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)
    event.listen(db.bind, "before_cursor_execute", observe)
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval", side_effect=AssertionError("fetch forbidden")) as fetch:
        ask(db, trusted=trusted, **overrides)
    assert fetch.call_count == 0
    assert writes == []


@pytest.mark.parametrize("event_time,now,status", [
    (NOW - timedelta(hours=2), NOW, "delayed"),
    (NOW - timedelta(hours=2, seconds=1), NOW, "stale"),
    (None, NOW, "missing"),
    (NOW + timedelta(minutes=6), NOW, "stale"),
    (datetime(2026, 10, 23, 20, 55, tzinfo=timezone.utc), datetime(2026, 10, 25, 12, tzinfo=timezone.utc), "latest_completed_session"),
    (datetime(2026, 10, 22, 20, 55, tzinfo=timezone.utc), datetime(2026, 10, 25, 12, tzinfo=timezone.utc), "stale"),
    (datetime(2026, 10, 26, 20, 55, tzinfo=timezone.utc), datetime(2026, 10, 26, 21, 30, tzinfo=timezone.utc), "latest_completed_session"),
    (datetime(2026, 11, 6, 21, 55, tzinfo=timezone.utc), datetime(2026, 11, 8, 12, tzinfo=timezone.utc), "latest_completed_session"),
])
def test_event_time_session_semantics(event_time, now, status):
    result = source_health.commodity_freshness(exchange="COMEX", event_time=event_time, now=now)
    assert result["status"] == status
    assert "commodity_holiday_and_halt_calendar_unverified" in result["limitations"]


def test_fresh_price_only_does_not_refresh_missing_daily(db):
    seed(db, event_time=NOW - timedelta(minutes=20))
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval") as fetch:
        result = ask(db, selection={"include": ["quote.snapshot"]})
    fetch.assert_not_called()
    assert result["evidence"]["data"]["quote.snapshot"]["last_price"] == 100
    quality = result["evidence"]["quality"]
    assert quality["facts_ready"] is True
    assert quality["status"] != "blocked"
    assert quality["capabilities"]["quote.snapshot"]["facts_usable"] is True


def test_provider_failure_keeps_snapshot_and_v4_failure(db):
    seed(db)
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval", side_effect=TimeoutError("fixture timeout")) as fetch:
        result = ask(db)
    assert fetch.call_count == 1
    assert result["evidence"]["data"]["quote.snapshot"]["last_price"] == 100
    assert result["evidence"]["data"]["quote.snapshot"]["freshness"]["status"] == "stale"
    assert "fixture timeout" in json.dumps(result)
    assert result["evidence"]["data"]["quote.snapshot"]["event_time"] == "2026-10-09T15:00:00+00:00"
    assert result["evidence"]["quality"]["capabilities"]["quote.snapshot"]["facts_usable"] is True
    assert result["evidence"]["realtime"]["quote.snapshot"]["state"] == "stale"


def test_successful_transport_with_old_event_remains_stale(db):
    seed(db)
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval", return_value=(
        chart(event_time=NOW - timedelta(hours=3)), "https://example.invalid/fixture")):
        result = ask(db)
    assert result["evidence"]["data"]["quote.snapshot"]["freshness"]["status"] == "stale"


@pytest.mark.parametrize("symbol", ["UNKNOWN", "", "NO-SUCH-FX"])
def test_owner_rejects_unknown_resource(db, symbol):
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval") as fetch:
        receipt = service.refresh_resource_for_answer(db, symbol=symbol, allow_external_fetch=True,
            realtime_policy="prefer_live", before_answer=True,
            budget={"max_calls": 1, "max_external_fetches": 1, "max_total_seconds": 5},
            requested_capabilities=("quote.snapshot",))
    assert receipt["status"] == "skipped"
    fetch.assert_not_called()


def test_unsubscribed_does_not_fetch_or_commit(db):
    seed(db)
    with patch.object(service, "market_data_subscription_skip_reason", return_value="subscription disabled"), \
         patch.object(service, "fetch_yahoo_chart_payload_for_interval") as fetch, \
         patch.object(db, "commit") as commit:
        ask(db)
    fetch.assert_not_called()
    commit.assert_not_called()


def test_parser_does_not_pair_metadata_price_with_bar_time():
    payload = chart()
    del payload["chart"]["result"][0]["meta"]["regularMarketTime"]
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [180]
    record = parse_yahoo_quote_record(payload, instrument=list_resource_instruments(symbol="GC")[0], source_url="fixture")
    assert record.last_price == 180
    assert record.event_time == NOW.replace(hour=4)


@pytest.mark.parametrize("price,event_time", [(None, NOW), (float("nan"), NOW),
    (200, NOW - timedelta(days=20)), (200, NOW + timedelta(minutes=10))])
def test_invalid_or_regressing_response_preserves_prior_snapshot(db, price, event_time):
    seed(db)
    payload = chart(event_time=event_time, price=200)
    payload["chart"]["result"][0]["meta"]["regularMarketPrice"] = price
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [price]
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval", return_value=(payload, "fixture")):
        result = ask(db)
    assert result["evidence"]["data"]["quote.snapshot"]["last_price"] == 100
    assert result["execution"]["tool_runs"][0]["status"] == "error"


def test_zero_price_is_preserved_as_observation(db):
    seed(db)
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval", return_value=(chart(price=0), "fixture")):
        result = ask(db)
    assert result["evidence"]["data"]["quote.snapshot"]["last_price"] == 0


def test_daily_only_request_repairs_missing_daily_once(db):
    seed(db, event_time=NOW - timedelta(minutes=20))
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval", return_value=(chart(), "fixture")) as fetch:
        ask(db, selection={"include": ["daily.ohlcv"]})
    assert fetch.call_count == 1
    assert db.query(ResourceOhlcvBar).count() == 1


def test_disabled_daily_does_not_block_price_or_write_daily(db):
    seed(db)
    with patch.object(service, "market_data_subscription_skip_reason", side_effect=lambda db, key, resource:
                      "disabled" if resource == "ohlcv" else None), \
         patch.object(service, "fetch_yahoo_chart_payload_for_interval", return_value=(chart(), "fixture")):
        result = ask(db)
    assert result["evidence"]["data"]["quote.snapshot"]["last_price"] == 200
    assert db.query(ResourceOhlcvBar).count() == 0


def test_weekend_completed_session_stays_read_only_in_v4(db):
    seed(db, event_time=datetime(2026, 10, 23, 20, 55, tzinfo=timezone.utc))
    with patch("app.resource_market.source_health._now", return_value=datetime(2026, 10, 25, 12, tzinfo=timezone.utc)), \
         patch.object(service, "fetch_yahoo_chart_payload_for_interval") as fetch:
        result = ask(db, selection={"include": ["quote.snapshot"]})
    fetch.assert_not_called()
    assert result["evidence"]["realtime"]["quote.snapshot"]["state"] == "latest_completed_session"


def test_registered_fx_reaches_shared_refresh_owner(db):
    with patch.object(service, 'market_data_subscription_skip_reason', return_value=None), \
         patch('app.resource_market.source_health.build_resource_source_health', return_value={
             'entries':[{'resource':'quote','ok':False},{'resource':'ohlcv','ok':False}]}), \
         patch.object(service, 'refresh_resource_quotes', return_value={'status':'success','refreshed_count':1}) as refresh:
        receipt=service.refresh_resource_for_answer(db,symbol='USD-TWD',allow_external_fetch=True,
            realtime_policy='prefer_live',before_answer=True,
            budget={'max_calls':1,'max_external_fetches':1,'max_total_seconds':5},
            requested_capabilities=('quote.snapshot','daily.ohlcv'))
    assert receipt['external_fetches']==1
    refresh.assert_called_once()
    assert refresh.call_args.kwargs['symbols']=='USD-TWD'
    assert refresh.call_args.kwargs['include_daily'] is True


def test_missing_price_never_counts_as_fresh(db):
    seed(db, event_time=NOW, price=None)
    health = source_health.build_resource_source_health(db, symbols="GC", intervals="1d", include_events=False)
    assert health["entries"][0]["ok"] is False
    assert "source_price_missing" in health["entries"][0]["freshness"]["reason_codes"]


def test_concurrent_newer_snapshot_is_not_overwritten(db):
    row = seed(db)
    def fetch(**kwargs):
        row.event_time = NOW - timedelta(minutes=5)
        row.last_price = 300
        db.commit()
        return chart(), "fixture"
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval", side_effect=fetch):
        result = ask(db)
    assert result["evidence"]["data"]["quote.snapshot"]["last_price"] == 300
    assert "resource_quote_event_time_regressed" in json.dumps(result)


def test_empty_daily_response_reports_limitation_but_keeps_price_facts(db):
    seed(db)
    payload = chart()
    payload["chart"]["result"][0]["timestamp"] = []
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval", return_value=(payload, "fixture")):
        result = ask(db)
    assert result["evidence"]["data"]["quote.snapshot"]["last_price"] == 200
    assert result["evidence"]["quality"]["capabilities"]["quote.snapshot"]["facts_usable"] is True
    assert "requested daily bars missing" in json.dumps(result)
    assert db.query(ResourceOhlcvBar).count() == 0


def test_formal_unknown_target_never_fetches_or_writes(db):
    with patch.object(service, "fetch_yahoo_chart_payload_for_interval") as fetch, \
         patch.object(db, "commit") as commit:
        ask(db, symbol="UNKNOWN")
    fetch.assert_not_called()
    commit.assert_not_called()
