"""Exact unreleased Daily requests never expose previous-session bar payloads."""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.ai import agentic_tools
from app.ai.market_context.us_context import USContextDependencies, read_us_stock_context
from app.us_market import daily_ohlcv_chart, service
from app.us_market.daily_ohlcv_acquisition import USDailyOhlcvAcquisitionExecutor
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from test_us_technical_explicit_fill import db, forbid, seed


NOW = datetime(2026, 9, 30, 8, tzinfo=ZoneInfo("America/New_York"))


@pytest.mark.parametrize("requested,reason", [
    (date(2026, 9, 30), "US_DAILY_REQUESTED_SESSION_NOT_RELEASED"),
    (date(2026, 10, 1), "US_DAILY_REQUESTED_SESSION_NOT_RELEASED"),
    (date(2026, 9, 26), "US_DAILY_REQUESTED_DATE_NOT_TRADING_SESSION"),
])
def test_exact_ineligible_read_rejects_before_resolving_stale_cache(db, requested, reason):
    seed(db, symbol="AAPL", count=260)
    db.execute(text("PRAGMA query_only=ON"))
    platform = USDailyOhlcvPlatform(db)
    latest = platform.read(symbol="AAPL", now=NOW)
    assert latest.projection["latest_trade_date"] == "2026-09-29"
    assert latest.projection["bars"]
    with patch.object(platform, "_run", side_effect=AssertionError("ineligible resolution")):
        with pytest.raises(ValueError, match=reason):
            platform.read(symbol="AAPL", now=NOW, to_date=requested)
    historical = platform.read(symbol="AAPL", now=NOW, to_date=date(2026, 9, 28))
    assert historical.projection["latest_trade_date"] == "2026-09-28"
    assert historical.projection["expected_trade_date"] == "2026-09-28"
    assert historical.projection["bars"]


@pytest.mark.parametrize("include_intraday,require_close", [(False, False), (True, True)])
def test_exact_unreleased_context_has_no_previous_daily_evidence(db, monkeypatch, include_intraday, require_close):
    seed(db, symbol="AAPL", count=260)
    db.execute(text("PRAGMA query_only=ON"))
    monkeypatch.setattr(daily_ohlcv_chart, "datetime", type("Clock", (datetime,), {
        "now": classmethod(lambda cls, tz=None: NOW),
    }))
    monkeypatch.setattr(service, "build_us_source_health", lambda **kwargs: {"entries": []})
    monkeypatch.setattr(service, "get_us_quote_snapshot", forbid)
    monkeypatch.setattr(service, "get_us_intraday_trend", lambda **kwargs: {"points": []})
    monkeypatch.setattr(USDailyOhlcvAcquisitionExecutor, "acquire_bar_observations", forbid)
    daily_reads = []
    original_read = USDailyOhlcvPlatform.read

    def observe_read(platform, **kwargs):
        daily_reads.append((kwargs.get("to_date"), kwargs.get("now")))
        return original_read(platform, **kwargs)

    monkeypatch.setattr(USDailyOhlcvPlatform, "read", observe_read)
    caps = ["daily.ohlcv", "technical.structure"] + (["intraday.bars"] if include_intraday else [])
    context = read_us_stock_context(
        db, symbol="AAPL",
        dependencies=USContextDependencies(us_market_service=service, latest_profile=forbid,
            scan_us_stock_gaps=agentic_tools.scan_us_stock_gaps, now=lambda: NOW),
        market_data_params={"trade_date": "2026-09-30", "session_scope": "extended",
            "require_daily_close": require_close, "include_intraday": include_intraday,
            "requested_capabilities": caps},
    )
    daily = context["data"]["resolved_market_data"]["daily_ohlcv"]
    # Both the direct Daily read and the compatibility chart hit the real guard.
    assert daily_reads == [(date(2026, 9, 30), NOW)] * 2
    assert "US_DAILY_REQUESTED_SESSION_NOT_RELEASED" in daily["limitations"]
    assert not daily.get("bars")
    assert not daily.get("points")
    assert not daily.get("facts_usable")
    assert not context["data"]["daily_prices"]
    assert not context["data"]["chart"]
    assert context["summary"]["latest_close"] is None
    assert context["data"]["compact"]["quote"].get("price") is None
    technical = context["data"]["resolved_research"]["technical_structure"]
    assert technical["status"] == "missing"
    assert "US_DAILY_REQUESTED_SESSION_NOT_RELEASED" in technical["quality"]["reason_codes"]
