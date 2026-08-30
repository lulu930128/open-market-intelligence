from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.research.technical import (
    TW_DAILY_PROFILE,
    US_DAILY_PROFILE,
    US_INDEX_DAILY_PROFILE,
    build_technical_indicators,
    build_technical_structure,
)


def _bars(count: int, *, first_close: float = 100.0) -> list[dict]:
    start = date(2025, 1, 1)
    return [
        {
            "time": (start + timedelta(days=index)).isoformat(),
            "open": first_close + index - 0.5,
            "high": first_close + index + 1,
            "low": first_close + index - 1,
            "close": first_close + index,
            "volume": 1_000 + index * 10,
        }
        for index in range(count)
    ]


def test_market_profiles_are_versioned_and_market_specific() -> None:
    assert US_DAILY_PROFILE.profile_version == "us.equity.daily.v1"
    assert US_DAILY_PROFILE.market == "US"
    assert 200 in US_DAILY_PROFILE.moving_average_periods
    assert US_DAILY_PROFILE.calendar_id == "us.exchange_calendar.v1"
    assert US_DAILY_PROFILE.timezone == "America/New_York"
    assert US_DAILY_PROFILE.benchmark_symbol is None
    assert US_DAILY_PROFILE.benchmark_status == "not_configured"
    assert US_INDEX_DAILY_PROFILE.profile_version == "us.index.daily.v1"
    assert US_INDEX_DAILY_PROFILE.volume_unit is None
    assert US_INDEX_DAILY_PROFILE.corporate_action_policy == "not_applicable"
    assert TW_DAILY_PROFILE.market == "TW"
    assert TW_DAILY_PROFILE.decision_minimum_bars == 60


def test_shared_engine_returns_stable_us_indicator_methods() -> None:
    result = build_technical_indicators(
        market="US",
        symbol="AAPL",
        bars=_bars(220),
        profile=US_DAILY_PROFILE,
        freshness_status="current",
        resolved_facts_usable=True,
        corporate_action_coverage="complete",
        lineage={"selected_provider": "fixture"},
    )

    assert result["schema_version"] == "omi.research.technical.indicators.v1"
    assert result["algorithm_version"] == "omi.research.technical.shared.v1"
    assert result["status"] == "available"
    assert result["quality"]["decision_usable"] is True
    assert result["current"]["moving_averages"]["ma20"] == pytest.approx(309.5)
    assert result["current"]["moving_averages"]["ma200"] == pytest.approx(219.5)
    assert result["current"]["rsi"]["rsi14"] == pytest.approx(100.0)
    assert result["current"]["atr"]["atr14"] == pytest.approx(2.0)
    assert result["warmup"]["ma200"]["ready"] is True
    assert result["period_completeness"] == {
        "latest_period": "completed",
        "provisional_included": False,
    }


def test_unknown_corporate_action_coverage_blocks_decision_not_facts() -> None:
    result = build_technical_indicators(
        market="US",
        symbol="AAPL",
        bars=_bars(220),
        profile=US_DAILY_PROFILE,
        freshness_status="fresh",
        resolved_facts_usable=True,
        corporate_action_coverage="unknown",
    )

    assert result["status"] == "partial"
    assert result["quality"]["facts_usable"] is True
    assert result["quality"]["decision_usable"] is False
    assert "CORPORATE_ACTION_COVERAGE_INCOMPLETE" in result["quality"]["reason_codes"]


def test_index_not_applicable_volume_and_corporate_actions_do_not_block_decision() -> None:
    bars = [{**bar, "volume": None} for bar in _bars(220)]
    indicators = build_technical_indicators(
        market="US",
        symbol="^GSPC",
        bars=bars,
        profile=US_INDEX_DAILY_PROFILE,
        freshness_status="current",
        resolved_facts_usable=True,
        corporate_action_coverage="not_applicable",
    )
    structure = build_technical_structure(
        indicators=indicators,
        bars=bars,
        profile=US_INDEX_DAILY_PROFILE,
    )

    assert indicators["status"] == "available"
    assert indicators["quality"]["decision_usable"] is True
    assert indicators["current"]["volume"] is None
    assert indicators["current"]["volume_vs_ma20_pct"] is None
    assert "CORPORATE_ACTION_COVERAGE_INCOMPLETE" not in indicators["quality"][
        "reason_codes"
    ]
    assert "BREAKOUT_WITHOUT_VOLUME_CONFIRMATION" not in structure[
        "counter_evidence"
    ]


def test_structure_uses_shared_indicators_and_preserves_quality() -> None:
    bars = _bars(220)
    indicators = build_technical_indicators(
        market="US",
        symbol="AAPL",
        bars=bars,
        profile=US_DAILY_PROFILE,
        freshness_status="current",
        resolved_facts_usable=True,
        corporate_action_coverage="unknown",
    )
    structure = build_technical_structure(
        indicators=indicators,
        bars=bars,
        profile=US_DAILY_PROFILE,
    )

    assert structure["schema_version"] == "omi.research.technical.structure.v1"
    assert structure["trend_state"] == "bullish_stack"
    assert structure["quality"]["decision_usable"] is False
    assert structure["metrics"]["price_vs_ma20_pct"] is not None
    assert structure["current_state"]["trend"] == "bullish_stack"
    assert structure["current_state"]["volume_state"] == "above_average"
    assert "RSI_OVERHEATED" in structure["counter_evidence"]
    assert "CORPORATE_ACTION_COVERAGE_INCOMPLETE" in structure["limitations"]
    assert structure["invalidation"]["bullish_below"] is not None


def test_malformed_bars_are_skipped_without_converting_unknown_to_zero() -> None:
    result = build_technical_indicators(
        market="US",
        symbol="BAD",
        bars=[
            {"time": "2026-08-20", "open": 1, "high": 2, "low": 0.5, "close": None},
            {"time": "2026-08-21", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": None},
        ],
        profile=US_DAILY_PROFILE,
        freshness_status="current",
        resolved_facts_usable=True,
    )

    assert result["bar_count"] == 1
    assert result["current"]["volume"] is None
    assert result["current"]["volume_vs_ma20_pct"] is None
    assert result["input_quality"]["skipped_or_duplicate_count"] == 1


def test_duplicate_and_out_of_order_dates_are_normalized_deterministically() -> None:
    bars = list(reversed(_bars(40)))
    duplicate = dict(bars[-1])
    duplicate["close"] = duplicate["close"] + 2
    duplicate["high"] = duplicate["high"] + 2
    bars.append(duplicate)

    result = build_technical_indicators(
        market="US",
        symbol="AAPL",
        bars=bars,
        profile=US_DAILY_PROFILE,
        freshness_status="current",
        resolved_facts_usable=True,
    )

    assert result["bar_count"] == 40
    assert result["input_quality"]["input_bar_count"] == 41
    assert result["input_quality"]["skipped_or_duplicate_count"] == 1
    assert result["as_of"] == "2025-02-09"
