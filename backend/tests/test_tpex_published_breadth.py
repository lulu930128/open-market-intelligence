"""Offline replay of the retained TPEx 2026-10-22 public highlight response."""

import copy
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import event

from app.db.models import MarketDailyPrice, RawFetchResult, SourceRegistry, StockMaster, TaiwanPublishedBreadthSnapshot
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue
from app.market.daily_price_transaction import TaiwanOfficialDailyTransaction
from app.market.official_breadth_platform import read_taiwan_official_breadth, project_taiwan_official_breadth
from app.market.providers import tpex, twse
from app.market.providers.tw_official_daily import TPEX_DAILY_RESOURCE_ID, TPEX_HIGHLIGHT_RESOURCE_ID
from app.parsers.twse_published_breadth import parse_tpex_published_breadth, TPEX_AGGREGATE_SCOPE
from app.sources.defaults import TPEX_MARKET_HIGHLIGHT_SOURCE_NAME
from test_tw_official_daily_platform import db, FakeResponse, _fixture


DAY = date(2026, 10, 22)
NOW = datetime(2026, 10, 22, 10, 30, tzinfo=timezone.utc)
RAW = (Path(__file__).parent / "fixtures/tw_market_data/tpex_market_highlight_20261022.json").read_bytes()


def test_recorded_payload_scope_partition_and_limits():
    assert hashlib.sha256(RAW).hexdigest() == "dd227ea80648d107e6e69b03eb0cb4c5dc3b09a09d2300615a6dd621b53819c7"
    parsed = parse_tpex_published_breadth(RAW.decode("utf-8-sig"), trade_date=DAY)
    assert parsed.venue == "TPEX"
    assert parsed.limits.scope == TPEX_AGGREGATE_SCOPE
    assert (parsed.advance, parsed.decline, parsed.unchanged, parsed.no_trade) == (146, 659, 63, 26)
    assert parsed.limits.universe_count == 894
    assert (parsed.limits.up_count, parsed.limits.down_count) == (17, 11)
    assert parsed.no_comparison == 0
    # Column order is not an API contract; verified labels are.
    payload = json.loads(RAW)
    payload["tables"][0]["fields"].reverse()
    payload["tables"][0]["data"][0].reverse()
    assert parse_tpex_published_breadth(json.dumps(payload), trade_date=DAY) == parsed


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(date="20261021"),
    lambda p: p["tables"][0].update(date="115/10/21"),
    lambda p: p["tables"][0]["fields"].__setitem__(7, "其他"),
    lambda p: p["tables"][0].update(title="所有證券彙總資訊"),
    lambda p: p["tables"][0].update(notes=["所有證券含ETF"]),
    lambda p: p["tables"][0]["fields"].__setitem__(1, "上漲家數"),
    lambda p: p["tables"][0]["data"][0].__setitem__(0, "895"),
    lambda p: p["tables"][0]["data"][0].__setitem__(8, "147"),
    lambda p: p["tables"][0]["data"][0].__setitem__(12, "--"),
    lambda p: p["tables"][0]["data"].append(p["tables"][0]["data"][0]),
])
def test_unverified_date_fields_scope_or_partition_rejected(mutation):
    payload = json.loads(RAW)
    mutation(payload)
    with pytest.raises(ValueError):
        parse_tpex_published_breadth(json.dumps(payload), trade_date=DAY)


def acquire(db, *, highlight=None, clock=NOW, requested_at=NOW):
    # Synthetic dated bar input for transaction composition; only RAW is the
    # exact 10/22 public payload. We do not claim these are 10/22 stock prices.
    daily = copy.deepcopy(_fixture("tpex_mainboard_quotes_excerpt_20260825.json")["payload"])
    daily["date"] = DAY.strftime("%Y%m%d")
    daily_fetch = Mock(return_value=FakeResponse(text=json.dumps(daily)))
    highlight_fetch = Mock(return_value=highlight or FakeResponse(text=RAW.decode("utf-8"), url=tpex.MARKET_HIGHLIGHT_URL))
    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={TPEX_DAILY_RESOURCE_ID: daily_fetch, TPEX_HIGHLIGHT_RESOURCE_ID: highlight_fetch},
        clock=lambda: clock, monotonic=lambda: 10.0,
    )
    result = refresh_taiwan_official_daily_venue(db, venue="TPEX", trade_date=DAY,
        requested_at=requested_at, acquisition=executor)
    return result, daily_fetch, highlight_fetch


@pytest.fixture
def seeded(db):
    db.add(StockMaster(stock_id="6488", stock_name="test", market="TPEX", instrument_type="stock", is_active=True))
    db.commit()
    return db


def test_eod_producer_receipt_transaction_gateway_projection(seeded, monkeypatch):
    commits = []
    event.listen(seeded, "after_commit", lambda _: commits.append(True))
    result, daily_fetch, highlight_fetch = acquire(seeded)
    assert daily_fetch.call_count == highlight_fetch.call_count == 1
    assert len(commits) == 1
    assert [a["resource_id"] for a in result["resource_attempts"]] == [TPEX_DAILY_RESOURCE_ID, TPEX_HIGHLIGHT_RESOURCE_ID]
    snapshot = seeded.query(TaiwanPublishedBreadthSnapshot).one()
    receipt = seeded.get(RawFetchResult, snapshot.raw_result_id)
    assert snapshot.venue == "TPEX" and snapshot.trade_date == DAY and snapshot.error_code is None
    assert receipt.raw_text.encode("utf-8") == RAW
    assert receipt.content_hash == hashlib.sha256(RAW).hexdigest()
    assert seeded.get(SourceRegistry, receipt.source_id).source_name == TPEX_MARKET_HIGHLIGHT_SOURCE_NAME
    assert seeded.query(MarketDailyPrice).one().raw_result_id != receipt.id
    assert result["raw_result_id"] == seeded.query(MarketDailyPrice).one().raw_result_id
    assert seeded.query(RawFetchResult).count() == 2
    deny_io = Mock(side_effect=AssertionError("read cannot fetch"))
    monkeypatch.setattr(tpex, "get_response", deny_io)
    monkeypatch.setattr(tpex, "fetch_market_highlight_payload", deny_io)
    monkeypatch.setattr(twse, "get_response", deny_io)
    pending = StockMaster(stock_id="9999", stock_name="pending", market="TPEX", instrument_type="stock")
    seeded.add(pending)
    statements = []
    event.listen(seeded.get_bind(), "before_cursor_execute", lambda _c, _cu, sql, *_: statements.append(sql.lower()))
    resolved = read_taiwan_official_breadth(seeded, venue="TPEX", trade_date=DAY, requested_at=NOW)
    outward = project_taiwan_official_breadth(resolved)
    assert resolved.resolved.breadth.lineage.raw_receipt_id == f"raw_fetch_result:{receipt.id}"
    assert outward["scope"] == TPEX_AGGREGATE_SCOPE
    assert outward["market_session"] == "closed" and outward["official"]
    assert outward["unchanged_count"] == 63 and outward["unknown_count"] == 26
    assert outward["classification_reason_counts"]["unknown"] == 26
    assert outward["valid_no_trade_count"] == 0  # cannot split the mixed category
    assert "PUBLISHED_NO_TRADE_INCLUDES_SUSPENDED" in outward["limitations"]
    assert outward["limit_up_count"] == 17 and outward["limit_down_count"] == 11
    assert not outward["decision_usable"]
    assert pending in seeded.new
    assert not any(s.lstrip().startswith(("insert", "update", "delete")) for s in statements)
    assert not any("raw_text" in s for s in statements)
    deny_io.assert_not_called()


def test_all_daily_and_published_rows_rollback_together(seeded, monkeypatch):
    original = TaiwanOfficialDailyTransaction._quality_check

    def fail(self, **kwargs):
        if kwargs["receipt"].source == TPEX_MARKET_HIGHLIGHT_SOURCE_NAME:
            self._db.flush()
            assert self._db.query(TaiwanPublishedBreadthSnapshot).count() == 1
            raise RuntimeError("rollback test")
        return original(self, **kwargs)
    monkeypatch.setattr(TaiwanOfficialDailyTransaction, "_quality_check", fail)
    with pytest.raises(RuntimeError, match="rollback test"):
        acquire(seeded)
    assert seeded.query(TaiwanPublishedBreadthSnapshot).count() == 0
    assert seeded.query(MarketDailyPrice).count() == 0
    assert seeded.query(RawFetchResult).count() == 0


@pytest.mark.parametrize("bad", ["old_date", "missing_field", "http_failure"])
def test_bad_companion_preserves_daily_bars_and_degrades_published_read(seeded, bad):
    payload = json.loads(RAW)
    if bad == "old_date":
        payload["date"] = "20261021"
    if bad == "missing_field":
        payload["tables"][0]["fields"][12] = "其他"
    response = FakeResponse(text=json.dumps(payload), status_code=503 if bad == "http_failure" else 200)
    result, _, fetch = acquire(seeded, highlight=response)
    assert fetch.call_count == 1
    assert seeded.query(MarketDailyPrice).count() == 1
    assert seeded.query(TaiwanPublishedBreadthSnapshot).count() == 0
    assert result["limitations"]
    resolved = read_taiwan_official_breadth(seeded, venue="TPEX", trade_date=DAY,
        requested_at=NOW, allow_universe_fallback=False)
    assert resolved.resolved.breadth is None
    assert not resolved.resolved.health.research_usable


def test_executor_denies_pre_release_companion_without_io(seeded):
    before = datetime(2026, 10, 22, 5, 0, tzinfo=timezone.utc)
    result, _, fetch = acquire(seeded, clock=before)
    fetch.assert_not_called()
    assert "OFFICIAL_AGGREGATE_NOT_RELEASED" in result["limitations"]
    assert seeded.query(TaiwanPublishedBreadthSnapshot).count() == 0


def test_transaction_independently_rejects_pre_release_receipt(seeded, monkeypatch):
    original = TaiwanOfficialDailyTransaction._raw_receipt

    def pre_release(self, source, receipt):
        raw = original(self, source, receipt)
        if receipt.source == TPEX_MARKET_HIGHLIGHT_SOURCE_NAME:
            raw.fetched_at = datetime(2026, 10, 22, 5, 0, tzinfo=timezone.utc)
        return raw

    monkeypatch.setattr(TaiwanOfficialDailyTransaction, "_raw_receipt", pre_release)
    result, _, _ = acquire(seeded)
    assert "OFFICIAL_AGGREGATE_RECEIPT_REJECTED" in result["limitations"]
    snapshot = seeded.query(TaiwanPublishedBreadthSnapshot).one()
    assert snapshot.payload_json is None
    assert snapshot.error_code == "OFFICIAL_AGGREGATE_RECEIPT_REJECTED"
    assert read_taiwan_official_breadth(seeded, venue="TPEX", trade_date=DAY,
        requested_at=NOW, allow_universe_fallback=False).resolved.breadth is None


def test_published_receipt_does_not_require_price_rows(seeded):
    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={
            TPEX_DAILY_RESOURCE_ID: lambda _: FakeResponse(text="unavailable", status_code=503),
            TPEX_HIGHLIGHT_RESOURCE_ID: lambda _: FakeResponse(text=RAW.decode("utf-8")),
        },
        clock=lambda: NOW, monotonic=lambda: 10.0,
    )
    result = refresh_taiwan_official_daily_venue(seeded, venue="TPEX", trade_date=DAY,
        requested_at=NOW, acquisition=executor)
    assert result["parse_status"] == "error"  # the daily-price postcondition still failed
    assert seeded.query(MarketDailyPrice).count() == 0
    assert seeded.query(TaiwanPublishedBreadthSnapshot).one().error_code is None
    resolved = read_taiwan_official_breadth(seeded, venue="TPEX", trade_date=DAY,
        requested_at=NOW, allow_universe_fallback=False)
    assert resolved.resolved.breadth.universe_count == 894
    assert resolved.resolved.breadth.scope == TPEX_AGGREGATE_SCOPE


def test_published_reader_release_venue_and_date_gates(seeded):
    acquire(seeded)
    assert read_taiwan_official_breadth(seeded, venue="TWSE", trade_date=DAY,
        requested_at=NOW, allow_universe_fallback=False).resolved.breadth is None
    assert read_taiwan_official_breadth(seeded, venue="TPEX", trade_date=date(2026, 10, 21),
        requested_at=NOW, allow_universe_fallback=False).resolved.breadth is None
    snapshot = seeded.query(TaiwanPublishedBreadthSnapshot).one()
    raw = seeded.get(RawFetchResult, snapshot.raw_result_id)
    raw.fetched_at = datetime(2026, 10, 22, 5, 0)
    seeded.commit()
    for at in (datetime(2026, 10, 22, 5, 29, tzinfo=timezone.utc), NOW):
        assert read_taiwan_official_breadth(seeded, venue="TPEX", trade_date=DAY,
            requested_at=at, allow_universe_fallback=False).resolved.breadth is None


@pytest.mark.parametrize("daily_seconds,expected_calls,remaining", [(22, 1, 8), (29.5, 0, None), (30, 0, None), (40, 0, None)])
def test_daily_and_companion_share_soft_deadline(seeded, monkeypatch, daily_seconds, expected_calls, remaining):
    monkeypatch.setattr("app.market.daily_ohlcv_platform.monotonic", lambda: 0.0)
    tick = [0.0]
    daily_payload = copy.deepcopy(_fixture("tpex_mainboard_quotes_excerpt_20260825.json")["payload"])
    daily_payload["date"] = DAY.strftime("%Y%m%d")
    def daily(route):
        assert route.timeout_seconds == 30
        tick[0] += daily_seconds
        return FakeResponse(text=json.dumps(daily_payload))
    highlight = Mock(return_value=FakeResponse(text=RAW.decode("utf-8")))
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={
        TPEX_DAILY_RESOURCE_ID: daily, TPEX_HIGHLIGHT_RESOURCE_ID: highlight},
        clock=lambda: NOW, monotonic=lambda: tick[0])
    result = refresh_taiwan_official_daily_venue(seeded, venue="TPEX", trade_date=DAY,
        requested_at=NOW, acquisition=executor)
    assert result["parse_status"] == "success"
    assert seeded.query(MarketDailyPrice).count() == 1
    assert highlight.call_count == expected_calls
    if remaining is not None:
        assert highlight.call_args.args[0].timeout_seconds == remaining
    else:
        assert "ACQUISITION_DEADLINE_EXHAUSTED" in result["limitations"]


@pytest.mark.parametrize("whitespace", [" ", "\t", "\r\n", "\u3000", "\u00a0"])
def test_scope_allows_only_equivalent_whitespace(whitespace):
    raw = json.loads(RAW)
    for key in ["title", "notes"]:
        if key == "title":
            raw["tables"][0][key] = whitespace.join(raw["tables"][0][key])
        else:
            raw["tables"][0][key] = [whitespace.join(raw["tables"][0][key][0])]
    assert parse_tpex_published_breadth(json.dumps(raw), trade_date=DAY) == parse_tpex_published_breadth(RAW.decode(), trade_date=DAY)
    raw["tables"][0]["notes"][0] += "ETF"
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        parse_tpex_published_breadth(json.dumps(raw), trade_date=DAY)


def test_twse_published_only_uses_original_transaction_without_bar_rewrite(db):
    from app.market.providers.tw_official_daily import TWSE_RWD_DAILY_RESOURCE_ID, TWSE_DAILY_RESOURCE_ID
    from test_tw_published_breadth import payload, DAY as day, NOW as now, acquire as twse_acquire
    db.add(StockMaster(stock_id="3711", market="TWSE", instrument_type="stock", is_active=True))
    db.commit()
    twse_acquire(db, payload())
    daily_receipt = db.query(MarketDailyPrice).one().raw_result_id
    db.query(TaiwanPublishedBreadthSnapshot).delete(); db.commit()
    fetch = Mock(return_value=FakeResponse(text=json.dumps(payload())))
    denied = Mock(side_effect=AssertionError("no daily fallback"))
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={TWSE_RWD_DAILY_RESOURCE_ID: fetch,
        TWSE_DAILY_RESOURCE_ID: denied}, clock=lambda: now, monotonic=lambda: 0.0)
    result = refresh_taiwan_official_daily_venue(db, venue="TWSE", trade_date=day,
        requested_at=now, acquisition=executor, refresh_daily=False)
    assert result["external_call_count"] == 1 and result["parsed_count"] == 0
    assert db.query(MarketDailyPrice).one().raw_result_id == daily_receipt
    assert read_taiwan_official_breadth(db, venue="TWSE", trade_date=day,
        requested_at=now, allow_universe_fallback=False).resolved.breadth.published_limits is not None
    denied.assert_not_called()


def test_valid_published_is_not_refetched_for_partial_daily(seeded, monkeypatch):
    acquire(seeded)
    seeded.query(MarketDailyPrice).delete(); seeded.commit()
    published_receipt = seeded.query(TaiwanPublishedBreadthSnapshot).one().raw_result_id
    daily_payload = copy.deepcopy(_fixture("tpex_mainboard_quotes_excerpt_20260825.json")["payload"])
    daily_payload["date"] = DAY.strftime("%Y%m%d")
    highlight = Mock(side_effect=AssertionError("published is already qualified"))
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={
        TPEX_DAILY_RESOURCE_ID: lambda _: FakeResponse(text=json.dumps(daily_payload)),
        TPEX_HIGHLIGHT_RESOURCE_ID: highlight}, clock=lambda: NOW, monotonic=lambda: 0.0)
    from app.market.daily_ohlcv_platform import qualify_taiwan_eod_universe
    from app.market_data.eod_coverage import reconcile_eod_coverage
    def refresh(**kwargs):
        return refresh_taiwan_official_daily_venue(**kwargs, requested_at=NOW, acquisition=executor)
    monkeypatch.setattr("app.market_data.eod_coverage.utc_now", lambda: NOW)
    monkeypatch.setattr("app.market_data.eod_coverage.taiwan_bulk_eod_refresh_window", lambda **_: (True, None, "test"))
    result = reconcile_eod_coverage(seeded, market="TW", expected_trade_date=DAY,
        taiwan_daily_qualifier=qualify_taiwan_eod_universe, taiwan_venue_refresher=refresh)
    assert result["postcondition_met"] and result["external_call_budget_used"] == 1
    assert seeded.query(TaiwanPublishedBreadthSnapshot).one().raw_result_id == published_receipt
    highlight.assert_not_called()


@pytest.mark.parametrize("planning_seconds,expected_timeout", [(8, 22), (30, None)])
def test_platform_planning_consumes_same_acquisition_budget(seeded, monkeypatch, planning_seconds, expected_timeout):
    from app.market import daily_ohlcv_platform as platform
    tick = [0.0]
    original = platform.plan_refresh_acquisition_v1
    def plan(*args):
        tick[0] = planning_seconds
        return original(*args)
    monkeypatch.setattr(platform, "monotonic", lambda: tick[0])
    monkeypatch.setattr(platform, "plan_refresh_acquisition_v1", plan)
    fetch = Mock(return_value=FakeResponse(text=RAW.decode()))
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={TPEX_HIGHLIGHT_RESOURCE_ID: fetch},
        clock=lambda: NOW, monotonic=lambda: tick[0])
    result = platform.refresh_taiwan_official_daily_venue(seeded, venue="TPEX", trade_date=DAY,
        requested_at=NOW, acquisition=executor, refresh_daily=False)
    if expected_timeout is None:
        fetch.assert_not_called()
        assert result["external_call_count"] == 0
        assert "ACQUISITION_DEADLINE_EXHAUSTED" in result["limitations"]
    else:
        assert fetch.call_args.args[0].timeout_seconds == expected_timeout


def test_default_transport_disables_redirects_and_forwards_remaining_timeout(seeded, monkeypatch):
    import requests
    from app import http_client
    from app.market import daily_ohlcv_platform as platform
    tick = [0.0]
    daily = copy.deepcopy(_fixture("tpex_mainboard_quotes_excerpt_20260825.json")["payload"])
    daily["date"] = DAY.strftime("%Y%m%d")
    calls = []
    def transport(method, url, **kwargs):
        calls.append((url, kwargs))
        assert kwargs["allow_redirects"] is False
        if url == tpex.DAILY_QUOTES_URL:
            assert kwargs["timeout"] == 30
            tick[0] += 22
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps(daily).encode()
            response.url = url
            return response
        assert url == tpex.MARKET_HIGHLIGHT_URL
        assert kwargs["timeout"] == 8
        raise requests.Timeout("bounded fake transport timeout")
    monkeypatch.setattr(platform, "monotonic", lambda: 0.0)
    monkeypatch.setattr(http_client, "request", transport)
    executor = TaiwanOfficialDailyAcquisitionExecutor(clock=lambda: NOW, monotonic=lambda: tick[0])
    result = platform.refresh_taiwan_official_daily_venue(seeded, venue="TPEX", trade_date=DAY,
        requested_at=NOW, acquisition=executor)
    assert len(calls) == result["external_call_count"] == 2
    assert result["parse_status"] == "success"
    assert seeded.query(MarketDailyPrice).one().raw_result_id == result["raw_result_id"]
    assert "PROVIDER_REQUEST_FAILED" in result["limitations"]
