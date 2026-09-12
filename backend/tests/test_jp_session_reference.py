"""JP reference prices cannot acquire live-trade semantics from their age."""

from datetime import datetime

import pytest

from app.jp_market.quote_projection import project_jp_intraday_reference
from app.jp_market.session_policy import jp_session_phase


def test_recent_bar_is_not_a_live_trade():
    result = project_jp_intraday_reference(
        {"points": [{"time": "2026-09-11T10:00:00+09:00", "price": 3031.0}]},
        calendar_status={
            "timezone": "Asia/Tokyo", "checked_at": "2026-09-11T10:00:10+09:00",
            "date": "2026-09-11", "phase": "regular", "is_trading_day": True,
            "previous_trading_day": "2026-09-10",
        },
    )
    assert result["price"] == 3031.0
    assert result["bar_is_current_session"] is True
    assert result["last_trade_available"] is False
    assert result["decision_usable"] is False
    assert result["quote_semantics"] == "intraday_bar_close_reference"
    for surface in (result, result["freshness"]):
        assert surface["is_live"] is False
        assert surface["is_realtime"] is False
        assert surface["is_current_session_quote"] is False
        assert surface["delivery_status"] != "live"


@pytest.mark.parametrize("price", [None, True, 0, -1, float("nan"), float("inf")])
def test_invalid_reference_does_not_become_price(price):
    assert project_jp_intraday_reference({"points": [{"price": price}]}) == {}


@pytest.mark.parametrize("timestamp,phase", [
    ("2024-11-01T15:10:00+09:00", "post_close"),
    ("2024-11-05T15:10:00+09:00", "regular"),
    ("2026-09-11T11:31:00+09:00", "lunch_break"),
    ("2026-09-11T12:30:00+09:00", "regular"),
    ("2026-09-11T15:25:00+09:00", "closing_auction"),
    ("2026-09-11T15:30:00+09:00", "closing_auction"),
    ("2026-09-11T15:31:00+09:00", "post_close"),
])
def test_effective_session_boundaries(timestamp, phase):
    assert jp_session_phase(datetime.fromisoformat(timestamp)) == phase


def test_naive_session_time_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        jp_session_phase(datetime(2026, 9, 11, 12))


@pytest.mark.parametrize("scope", ["jp_stock", "jp_index", "kr_stock", "us_stock"])
def test_explicit_capability_selection_reaches_cache_only_reader(scope):
    from app.ai.ask_execution import _external_intraday_market_data_params
    from app.ai.schemas import AiAskRequest

    params = _external_intraday_market_data_params(
        AiAskRequest(question="Read selected evidence", target={"type":scope,"id":"7203.T"},
                     realtime_policy="cache_only", mode="data_only"),
        policy={"can_external_fetch":False,"query_plan":{
            "selected_capabilities":["intraday.bars", "daily.ohlcv"],
            "selection":{"limits":{"intraday.bars":5,"daily.ohlcv":10}},
        }},
    )
    assert params["include_intraday"] is True
    assert params["external_fetch_allowed"] is False
    assert params["intraday_limit"] == 5
    assert params["bars"] == 10


def test_explicit_reader_opt_out_remains_effective():
    from app.ai.ask_execution import _external_intraday_market_data_params
    from app.ai.schemas import AiAskRequest

    params = _external_intraday_market_data_params(
        AiAskRequest(question="Read evidence", realtime_policy="cache_only",
                     market_data_params={"include_intraday":False}),
        policy={"query_plan":{"selected_capabilities":["intraday.bars"]}},
    )
    assert params["include_intraday"] is False


def test_session_phase_survives_persisted_read_projection():
    from app.jp_market.service import _project_jp_intraday_payload
    from app.jp_market.schemas import JPIntradayTrendPointRead

    data = _project_jp_intraday_payload(
        {"points":[{"time":"2026-09-11T15:30:00+09:00","price":3031.0,"session":"regular"}]},
        db=None, symbol="^N225",
    )
    point = JPIntradayTrendPointRead.model_validate(data["points"][0])
    assert point.market_session_phase == "closing_auction"
    assert point.session == "regular"
    assert point.bar_ohlc_semantics == "closing_auction_reference"
    assert point.bar_close_time == point.time
    assert point.finalized is False


def test_daily_acquisition_does_not_fetch_ten_years_for_one_extra_month():
    from types import SimpleNamespace
    from unittest.mock import patch
    from app.jp_market.daily_acquisition import JPDailyAcquisition

    with patch("app.jp_market.daily_acquisition.fetch_yahoo_chart_payload", return_value=({}, "test")) as fetch:
        JPDailyAcquisition()._fetch(
            SimpleNamespace(provider_key="yahoo_chart", timeout_seconds=10),
            SimpleNamespace(target=SimpleNamespace(instrument=SimpleNamespace(symbol="7203.T")),
                            request=SimpleNamespace(start_at=datetime(2025,6,19),end_at=datetime(2026,9,11))),
        )
    assert fetch.call_args.kwargs["range_value"] == "2y"


def test_closing_auction_gap_is_not_missing_but_regular_gap_is():
    from app.ai.data_quality_contract import _continuity_summary

    def series(times):
        return {"interval":"1m", "points":[{"time":f"2026-09-11T{stamp}+09:00","price":3031.0} for stamp in times]}

    normal = _continuity_summary(series(["15:22:00","15:23:00","15:24:00","15:30:00"]), market="JP")
    assert "missing_interval" not in normal["issues"]
    missing = _continuity_summary(series(["15:19:00","15:23:00","15:24:00","15:30:00"]), market="JP")
    assert "missing_interval" in missing["issues"]


def test_quote_quality_cannot_promote_reference_to_decision_usable():
    from app.ai.capability_contract import CAPABILITIES
    from app.ai.data_quality_contract import _quality_for_capability

    spec = CAPABILITIES["quote.snapshot"]
    assert "decision_usable" in spec.default_fields
    quality = _quality_for_capability(
        {"capability":"quote.snapshot", "domain":"quote", "slot":"quote"},
        canonical={}, projected_data={"quote.snapshot":{
            "price":3031.0,"decision_usable":False,"facts_usable":True,
            "freshness_status":"latest_completed_session", "source":"yahoo_finance_chart",
            "quote_time":"2026-09-11T15:30:00+09:00",
            "limitations":["INTRADAY_BAR_CLOSE_REFERENCE_ONLY"],
        }}, realtime_assessments={}, market="JP",
    )
    assert quality["facts_usable"] is True
    assert quality["decision_usable"] is False
