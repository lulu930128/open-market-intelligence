from __future__ import annotations

from app.research.technical.aggregation import (
    aggregate_intraday_payload,
    aggregate_intraday_points,
)


def test_regular_bars_anchor_at_0930_and_aggregate_ohlcv() -> None:
    points = [
        {
            "time": "2026-03-09T09:30:00-04:00",
            "session": "regular",
            "price": 100.0,
            "open": 99.5,
            "high": 100.2,
            "low": 99.4,
            "volume": 10,
        },
        {
            "time": "2026-03-09T09:34:00-04:00",
            "session": "regular",
            "price": 101.0,
            "open": 100.0,
            "high": 101.2,
            "low": 99.9,
            "volume": 20,
        },
        {
            "time": "2026-03-09T09:35:00-04:00",
            "session": "regular",
            "price": 102.0,
            "volume": 30,
        },
    ]

    result = aggregate_intraday_points(points, interval="5m", session_scope="regular")

    assert len(result) == 2
    assert result[0] == {
        "time": "2026-03-09T09:30:00-04:00",
        "session": "regular",
        "price": 101.0,
        "open": 99.5,
        "high": 101.2,
        "low": 99.4,
        "volume": 30,
        "volume_status": "available",
    }
    assert result[1]["time"] == "2026-03-09T09:35:00-04:00"


def test_all_scope_never_mixes_premarket_and_regular_four_hour_bars() -> None:
    points = [
        {"time": "2026-11-02T09:29:00-05:00", "session": "pre_market", "price": 90, "volume": 5},
        {"time": "2026-11-02T09:30:00-05:00", "session": "regular", "price": 100, "volume": 10},
        {"time": "2026-11-02T13:31:00-05:00", "session": "regular", "price": 105, "volume": 20},
        {"time": "2026-11-02T16:00:00-05:00", "session": "after_hours", "price": 103, "volume": 7},
    ]

    result = aggregate_intraday_points(points, interval="4h", session_scope="all")

    assert [item["session"] for item in result] == [
        "pre_market",
        "regular",
        "regular",
        "after_hours",
    ]
    assert result[1]["time"] == "2026-11-02T09:30:00-05:00"
    assert result[2]["time"] == "2026-11-02T13:30:00-05:00"


def test_payload_discloses_source_and_effective_interval() -> None:
    payload = {
        "points": [
            {"time": "2026-03-09T09:30:00-04:00", "session": "regular", "price": 100},
            {"time": "2026-03-09T09:31:00-04:00", "session": "regular", "price": 101},
        ],
        "point_count": 2,
    }

    result = aggregate_intraday_payload(payload, interval="5m", session_scope="regular")

    assert result["source_interval"] == "1m"
    assert result["effective_interval"] == "5m"
    assert result["source_point_count"] == 2
    assert result["sampling_mode"] == "server_aggregated"
    assert result["aggregation_method"] == "session_anchored_ohlcv.v1"
    assert result["bar_finalization_status"] == "completed"
    assert result["partial_bar_count"] == 0
    assert result["points"][0]["finalized"] is True
    assert result["point_count"] == 1


def test_live_window_marks_only_latest_bucket_partial() -> None:
    payload = {
        "points": [
            {"time": "2026-03-09T09:30:00-04:00", "session": "regular", "price": 100},
            {"time": "2026-03-09T09:35:00-04:00", "session": "regular", "price": 101},
        ],
        "source_status": {"is_live_window": True},
    }

    result = aggregate_intraday_payload(payload, interval="5m", session_scope="regular")

    assert result["points"][0]["finalized"] is True
    assert result["points"][0]["is_partial"] is False
    assert result["points"][1]["finalized"] is False
    assert result["points"][1]["is_partial"] is True
    assert result["bar_finalization_status"] == "contains_current_partial"
    assert result["partial_bar_count"] == 1


def test_missing_minutes_and_early_close_do_not_fabricate_bars() -> None:
    points = [
        {"time": "2026-11-27T12:55:00-05:00", "session": "regular", "price": 100},
        {"time": "2026-11-27T12:59:00-05:00", "session": "regular", "price": 101},
    ]

    result = aggregate_intraday_points(points, interval="5m", session_scope="regular")

    assert len(result) == 1
    assert result[0]["time"] == "2026-11-27T12:55:00-05:00"
    assert result[0]["price"] == 101


def test_missing_volume_never_becomes_a_partial_sum() -> None:
    points = [
        {
            "time": "2026-08-21T16:01:00-04:00",
            "session": "after_hours",
            "price": 100,
            "volume": None,
            "volume_status": "provider_unavailable",
        },
        {
            "time": "2026-08-21T16:02:00-04:00",
            "session": "after_hours",
            "price": 101,
            "volume": 25,
        },
    ]

    result = aggregate_intraday_points(points, interval="5m", session_scope="extended")

    assert result[0]["volume"] is None
    assert result[0]["volume_status"] == "partial"


def test_early_close_after_hours_buckets_anchor_at_1300() -> None:
    points = [
        {
            "time": "2026-11-27T13:02:00-05:00",
            "session": "after_hours",
            "price": 100,
            "volume": None,
        },
        {
            "time": "2026-11-27T13:06:00-05:00",
            "session": "after_hours",
            "price": 101,
            "volume": None,
        },
    ]

    result = aggregate_intraday_points(points, interval="5m", session_scope="extended")

    assert [point["time"] for point in result] == [
        "2026-11-27T13:00:00-05:00",
        "2026-11-27T13:05:00-05:00",
    ]
