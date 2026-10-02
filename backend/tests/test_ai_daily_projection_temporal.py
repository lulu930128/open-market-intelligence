"""History depth must not change the identity of a projected latest Daily bar."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.ai import capability_contract
from app.ai.decision_envelope_v4 import _brief_capability_summary
from app.ai.projection_temporal import series_point_sort_key, series_point_time


def bars(count=2):
    latest = datetime(2026, 10, 1, 20, tzinfo=timezone.utc)
    return [
        {
            "start_at": (latest - timedelta(days=count - i - 1, hours=6, minutes=30)).isoformat(),
            "end_at": (latest - timedelta(days=count - i - 1)).isoformat(),
            "event_at": (latest - timedelta(days=count - i - 1)).isoformat(),
            "close_price": str(614.73 + i),
        }
        for i in range(count)
    ]


def test_us_daily_two_bars_summary_selects_latest():
    rows = bars()
    summary = _brief_capability_summary("daily.ohlcv", {
        "bars": rows, "selected_event_at": rows[-1]["event_at"],
        "latest_trade_date": "2026-10-01",
    })
    assert summary["latest_point"]["close_price"] == "615.73"
    assert summary["latest_point"]["end_at"] == rows[1]["end_at"]
    assert summary["latest_point"]["event_at"] == rows[1]["event_at"]
    assert summary["event_time"] == rows[1]["end_at"]


@pytest.mark.parametrize("limit", [1, 8, 30, 120, 260])
@pytest.mark.parametrize("order", ["asc", "desc", "interleaved"])
def test_daily_latest_identity_is_independent_of_history_depth(limit, order):
    rows = bars(260)
    latest = rows[-1]
    if order == "desc":
        rows = rows[::-1]
    elif order == "interleaved":
        rows = rows[::2] + rows[1::2]
    response = {"target": {"type": "us_stock", "id": "AMD"}, "result": {"data": {
        "resolved_market_data": {"daily_ohlcv": {
            "bars": rows, "point_count": 260, "selected_event_at": latest["event_at"],
            "latest_trade_date": "2026-10-01", "facts_usable": True,
        }},
    }}}
    original = deepcopy(response)
    selection = capability_contract.normalize_selection(
        selection={"include": ["daily.ohlcv"], "limits": {"daily.ohlcv": limit}},
        output="evidence_only", realtime_policy="cache_only", payload_level="compact",
        scope_type="us_stock", question_intent="general",
    )
    projected, unavailable = capability_contract.project_selected_data(response=response, selection=selection)
    assert "daily.ohlcv" not in unavailable
    value = projected["daily.ohlcv"]
    summary = _brief_capability_summary("daily.ohlcv", value)
    assert summary["latest_point"] == latest
    assert summary["event_time"] == latest["end_at"]
    assert value["returned_point_count"] == limit
    assert value["truncated"] is (limit < 260)
    assert response == original


@pytest.mark.parametrize("field", ["end_at", "event_at", "start_at"])
def test_canonical_timestamp_fields_order_and_project(field):
    rows = [{field: "2026-09-30T20:00:00Z", "close_price": "1"},
            {field: "2026-10-01T16:00:00-04:00", "close_price": "2"}]
    summary = _brief_capability_summary("daily.ohlcv", {"bars": rows})
    assert summary["latest_point"]["close_price"] == "2"
    assert summary["event_time"] == rows[1][field]


def test_tied_latest_timestamps_match_stable_tail_truncation():
    latest = bars()[-1]
    revised = {**latest, "close_price": "616.00"}
    for rows in ([latest, revised], [revised]):
        summary = _brief_capability_summary("daily.ohlcv", {"bars": rows})
        assert summary["latest_point"] == revised


def test_shared_precedence_skips_malformed_fields_and_normalizes_timezones():
    point = {"end_at": "invalid", "event_at": "2026-10-01T16:00:00-04:00", "bar_time": "2026-09-01"}
    assert series_point_time(point) == point["event_at"]
    assert series_point_sort_key(point) == series_point_sort_key({"end_at": "2026-10-01T20:00:00Z"})
    assert series_point_time({**point, "end_at": "2026-10-02"}) == "2026-10-02"
    assert series_point_sort_key({"date": "2026-10-01"}).tzinfo is timezone.utc
    assert series_point_time({"end_at": None, "event_at": "invalid"}) is None


@pytest.mark.parametrize("metadata", [
    {"selected_event_at": "2026-10-02T20:00:00Z"},
    {"latest_trade_date": "2026-10-02"},
    {"latest_data_date": "2026-10-02"},
])
def test_daily_summary_fails_closed_on_conflicting_temporal_metadata(metadata):
    value = {"bars": [{**bars()[-1], "trade_date": "2026-10-01"}],
             "facts_usable": True, "research_usable": True, "decision_usable": True,
             "limitations": ["existing_limit"], **metadata}
    original = deepcopy(value)
    summary = _brief_capability_summary("daily.ohlcv", value)
    assert summary["latest_point"] == {}
    assert summary["event_time"] is None
    assert summary["status"] == "blocked"
    assert summary["reason_code"] == "DAILY_LATEST_POINT_TEMPORAL_MISMATCH"
    assert summary["facts_usable"] is summary["research_usable"] is summary["decision_usable"] is False
    assert summary["limitations"] == ["existing_limit", "DAILY_LATEST_POINT_TEMPORAL_MISMATCH"]
    assert value == original


def test_selected_lineage_event_is_not_assumed_to_equal_bar_end():
    point = {**bars()[-1], "event_at": "2026-10-01T19:59:59Z"}
    summary = _brief_capability_summary("daily.ohlcv", {
        "bars": [point], "selected_event_at": "2026-10-01T15:59:59-04:00",
    })
    assert summary["latest_point"] == point
    assert "reason_code" not in summary


def test_empty_daily_summary_does_not_invent_temporal_identity():
    summary = _brief_capability_summary("daily.ohlcv", {"bars": []})
    assert summary["latest_point"] == {}
    assert summary["event_time"] is None
