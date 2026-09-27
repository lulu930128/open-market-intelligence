from copy import deepcopy

import pytest

from app.market.taiwan_market_state import compose_taiwan_market_volume_state, _volume_comparison_identity
from app.ai.market_context.taiwan_market import _volume_state_with_breadth_current_value


def evidence():
    markets = {
        market: dict(market=market, trade_date="2026-09-14", as_of="2026-09-14T09:06:00+08:00",
                     scope="full_market", trade_value=value, trade_value_semantics="official_cumulative_trade_value",
                     trade_value_is_estimate=False, official_flag=True,
                     lineage=dict(provider="twse_mis", source="fixture", raw_receipt_id=f"raw_fetch_result:{market}",
                                  content_hash="a" * 64, event_at="2026-09-14T09:06:00+08:00"))
        for market, value in (("TWSE", 31_097_867_618), ("TPEX", 10_000_000_000))
    }
    scope = {market: ["full_market", "official_cumulative_trade_value", False] for market in markets}
    volume = dict(current_cumulative_trade_value=None, as_of="2026-09-14T09:06:00+08:00",
                  warnings=["TWSE and TPEX cumulative trade value are not both available at the selected minute.", "Historical lineage is limited."],
                  same_time_baseline_5d=dict(sample_days=5, sample_status="complete", median_cumulative_trade_value=69_622_509_484,
                                           comparison_minute="09:06", comparison_trade_date="2026-09-14", component_scope=scope,
                                           comparison_identity={market: _volume_comparison_identity(item) for market, item in markets.items()}))
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
                                      ("trade_value", -1), ("trade_value_is_estimate", None),
                                      ("trade_value_is_estimate", 0), ("trade_value_is_estimate", "false"),
                                      ("trade_value_is_estimate", True), ("official_flag", None),
                                      ("trade_value_semantics", "different_semantics"),
                                      ("lineage", {}), ("lineage", None)])
def test_unqualified_components_never_form_usable_current_value(key, value):
    volume, breadth = evidence()
    breadth["markets"]["TPEX"][key] = value
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["current_cumulative_trade_value"] is None
    assert result["trade_value_complete"] is False
    assert result["same_time_baseline_5d"]["pace_ratio"] is None


@pytest.mark.parametrize("key,value", [("comparison_minute", "09:05"), ("comparison_identity", {}),
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


def test_postclose_typed_estimated_1330_components_keep_baseline_warming():
    from datetime import date
    from app.market.taiwan_market_state import persist_taiwan_market_minute_state, read_taiwan_market_volume_state
    from test_taiwan_market_state import make_session, market_summary_payload
    from app.market.schemas import MarketBreadthRead, TaiwanMarketVolumeStateRead
    volume, breadth = evidence()
    values = {"TWSE": 926_014_494_083, "TPEX": 252_844_999_459}
    event = "2026-09-22T13:30:00+08:00"
    for market, item in breadth["markets"].items():
        item.update(trade_date="2026-09-22", as_of=event, trade_value=values[market],
            trade_value_is_estimate=True, official_flag=False,
            trade_value_semantics="estimated_latest_price_x_cumulative_volume_lots")
        item["lineage"]["event_at"] = event
    db = make_session()
    try:
        payload = market_summary_payload(date(2026, 9, 22), hour=13, minute=30,
            twse_trade_value=values["TWSE"], tpex_trade_value=values["TPEX"])
        for item in payload["indices"]:
            item["breadth"].update(breadth["markets"][item["market"]])
        persist_taiwan_market_minute_state(db, payload=payload)
        db.commit()
        persisted = read_taiwan_market_volume_state(db)
        assert all(item["trade_value_is_estimate"] is True for item in persisted["markets"])
        assert persisted["current_cumulative_trade_value"] == 1_178_859_493_542
        serialized = TaiwanMarketVolumeStateRead.model_validate(persisted).model_dump(mode="json")
        assert serialized["current_cumulative_trade_value"] == 1_178_859_493_542
        assert serialized["estimated_cumulative_trade_value"] == 1_178_859_493_542
        assert serialized["official_cumulative_trade_value"] is None
        assert serialized["trade_value_complete"] is True
        assert serialized["baseline_readiness_status"] == "warming_up"
        for item in payload["indices"]:
            projected = MarketBreadthRead.model_validate(item["breadth"]).model_dump(mode="json")
            assert projected["trade_value_is_estimate"] is True
            assert projected["official_flag"] is False
            assert projected["lineage"]["event_at"] == event
        # Exercise the independent current breadth selection with no usable minute value.
        persisted["current_cumulative_trade_value"] = None
        result = compose_taiwan_market_volume_state(persisted, breadth=breadth)
        assert result["current_cumulative_trade_value"] == 1_178_859_493_542
        assert result["estimated_cumulative_trade_value"] == 1_178_859_493_542
        assert result["official_cumulative_trade_value"] is None
        assert result["trade_value_authority_status"] == "estimated"
        assert result["trade_value_coverage_status"] == "complete"
        assert result["baseline_readiness_status"] == "warming_up"
        assert result["status"] == "partial"
        assert result["same_time_baseline_5d"]["pace_ratio"] is None
        assert result == _volume_state_with_breadth_current_value(persisted, breadth=breadth)
    finally:
        db.close()
        db.bind.dispose()


def test_receipt_event_mismatch_cannot_be_hidden_by_selected_1330_bucket():
    volume, breadth = evidence()
    breadth["markets"]["TPEX"]["lineage"]["event_at"] = "2026-09-14T09:08:30+08:00"
    assert compose_taiwan_market_volume_state(volume, breadth=breadth)["current_cumulative_trade_value"] is None
