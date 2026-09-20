from copy import deepcopy

import pytest

from app.market.taiwan_market_state import compose_taiwan_market_volume_state
from app.ai.market_context.taiwan_market import _volume_state_with_breadth_current_value


def evidence():
    markets = {
        market: dict(market=market, trade_date="2026-09-14", as_of="2026-09-14T09:06:00+08:00",
                     scope="full_market", trade_value=value, trade_value_semantics="official_cumulative_trade_value",
                     trade_value_is_estimate=False, official_flag=True)
        for market, value in (("TWSE", 31_097_867_618), ("TPEX", 10_000_000_000))
    }
    scope = {market: ["full_market", "official_cumulative_trade_value", False] for market in markets}
    volume = dict(current_cumulative_trade_value=None, as_of="2026-09-14T09:06:00+08:00",
                  warnings=["TWSE and TPEX cumulative trade value are not both available at the selected minute.", "Historical lineage is limited."],
                  same_time_baseline_5d=dict(sample_days=5, sample_status="complete", median_cumulative_trade_value=69_622_509_484,
                                           comparison_minute="09:06", comparison_trade_date="2026-09-14", component_scope=scope))
    return volume, {"markets": markets}


def test_fallback_recomputes_ratio_warning_and_ai_parity_without_mutation():
    volume, breadth = evidence()
    original = deepcopy((volume, breadth))
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["current_cumulative_trade_value"] == 41_097_867_618
    assert result["same_time_baseline_5d"]["pace_ratio"] == pytest.approx(0.5902956845)
    assert result["same_time_baseline_5d"]["decision_usable"] is True
    assert result["warnings"] == ["Historical lineage is limited."]
    assert result == _volume_state_with_breadth_current_value(volume, breadth=breadth)
    assert (volume, breadth) == original


@pytest.mark.parametrize("key,value", [("as_of", "2026-09-14T09:05:00+08:00"), ("trade_date", "2026-09-11"),
                                      ("scope", "local_dataset"), ("trade_value", float("nan")),
                                      ("trade_value", float("inf")), ("trade_value", True),
                                      ("trade_value", -1), ("trade_value_is_estimate", None), ("official_flag", None)])
def test_unqualified_components_never_form_usable_current_value(key, value):
    volume, breadth = evidence()
    breadth["markets"]["TPEX"][key] = value
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["current_cumulative_trade_value"] is None
    assert result["trade_value_complete"] is False
    assert result["same_time_baseline_5d"]["pace_ratio"] is None


@pytest.mark.parametrize("key,value", [("comparison_minute", "09:05"), ("component_scope", {}),
                                      ("comparison_trade_date", "2026-09-11"),
                                      ("sample_days", 4), ("median_cumulative_trade_value", 0),
                                      ("median_cumulative_trade_value", None)])
def test_valid_current_value_does_not_invent_comparable_baseline(key, value):
    volume, breadth = evidence()
    volume["same_time_baseline_5d"][key] = value
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["current_cumulative_trade_value"] is not None
    assert result["same_time_baseline_5d"]["pace_ratio"] is None
    assert result["same_time_baseline_5d"]["decision_usable"] is False
