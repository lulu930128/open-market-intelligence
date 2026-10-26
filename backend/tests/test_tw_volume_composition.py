from copy import deepcopy

import pytest

from app.market.taiwan_market_state import compose_taiwan_market_volume_state, _volume_comparison_identity
from app.ai.market_context.taiwan_market import _volume_state_with_breadth_current_value


@pytest.fixture(autouse=True)
def no_provider_network(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("volume qualification tests must not use network IO")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


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
                  same_time_baseline_5d=dict(sample_days=5, qualified_sample_days=5, sample_status="complete", median_cumulative_trade_value=69_622_509_484,
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
                                      ("median_cumulative_trade_value", None),
                                      ("qualified_sample_days", None), ("qualified_sample_days", 4),
                                      ("qualified_sample_days", 20), ("qualified_sample_days", True)])
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


def qualified_estimate(item):
    item.update(
        source="twse_mis_live_breadth", version="omi.market.breadth.v1",
        trade_value_is_estimate=True, official_flag=False, total_count=100,
        trade_value_semantics="estimated_latest_price_x_cumulative_volume_lots",
        acquisition_diagnostics=dict(acquisition_complete=True, failed_batch_count=0,
                                     skipped_batch_count=0, received_count=100, fallback_used=False),
        coverage_reason_counts=dict(advance=40, decline=30, unchanged=20, valid_no_trade=10),
    )


@pytest.mark.parametrize("branch", ["fallback", "direct"])
@pytest.mark.parametrize("venue", ["TWSE", "TPEX"])
@pytest.mark.parametrize("defect", ["failed", "skipped", "incomplete", "missing_acquisition",
                                    "missing_coverage", "partial_price", "fallback"])
def test_partial_estimate_never_qualifies_same_time_pace(branch, venue, defect):
    volume, breadth = evidence()
    for item in breadth["markets"].values():
        qualified_estimate(item)
    item = breadth["markets"][venue]
    if defect in {"failed", "skipped"}:
        item["acquisition_diagnostics"][f"{defect}_batch_count"] = 1
    elif defect == "incomplete":
        item["acquisition_diagnostics"]["acquisition_complete"] = False
    elif defect == "fallback":
        item["acquisition_diagnostics"]["fallback_used"] = True
    elif defect == "missing_acquisition":
        item.pop("acquisition_diagnostics")
    elif defect == "missing_coverage":
        item.pop("coverage_reason_counts")
    else:
        item["coverage_reason_counts"].update(advance=1, actual_trade_unavailable=39)
    baseline = volume["same_time_baseline_5d"]
    baseline.update(comparison_identity={m: _volume_comparison_identity(i) for m, i in breadth["markets"].items()},
                    qualified_sample_days=5)
    volume["same_time_baseline_20d"] = dict(baseline, sample_days=20, qualified_sample_days=20)
    if branch == "direct":
        volume.update(current_cumulative_trade_value=41_097_867_618, trade_date="2026-09-14",
                      comparison_minute="09:06", trade_value_complete=True,
                      markets=list(breadth["markets"].values()))
    original = deepcopy((volume, breadth))
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    # This remains a usable numeric fact; market representativeness is independent.
    assert result["current_cumulative_trade_value"] == 41_097_867_618
    assert result["trade_value_complete"] is True
    for days in (5, 20):
        assert result[f"same_time_baseline_{days}d"]["decision_usable"] is False
        assert result[f"same_time_baseline_{days}d"]["pace_ratio"] is None
    assert result["trade_value_qualification"]["decision_usable"] is False
    assert result["trade_value_qualification"]["reason_codes"]
    assert result["trade_value_status"] == "best_effort"
    assert (volume, breadth) == original


def test_legacy_baseline_without_qualification_evidence_is_not_decision_usable():
    volume, breadth = evidence()
    volume["same_time_baseline_5d"].pop("qualified_sample_days")
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["same_time_baseline_5d"]["decision_usable"] is False
    assert result["same_time_baseline_5d"]["pace_ratio"] is None


@pytest.mark.parametrize("bad_day", ["current", "history", "legacy_history"])
def test_persisted_estimate_qualification_survives_read_and_composition(bad_day):
    import json
    from datetime import date
    from app.db.models import TaiwanMarketMinuteState
    from app.market.taiwan_market_state import persist_taiwan_market_minute_state, read_taiwan_market_volume_state
    from test_taiwan_market_state import make_session, market_summary_payload

    db = make_session()
    try:
        for day in (7, 8, 9, 10, 11, 14):
            payload = market_summary_payload(date(2026, 9, day), hour=9, minute=6,
                                            twse_trade_value=1000, tpex_trade_value=200)
            for item in payload["indices"]:
                qualified_estimate(item["breadth"])
                if day == (14 if bad_day == "current" else 11) and item["market"] == "TWSE":
                    item["breadth"]["acquisition_diagnostics"]["acquisition_complete"] = False
            persist_taiwan_market_minute_state(db, payload=payload)
        if bad_day == "legacy_history":
            row = db.query(TaiwanMarketMinuteState).filter_by(trade_date=date(2026, 9, 11), market="TWSE").one()
            sources = json.loads(row.component_sources_json)
            for component in sources:
                component.pop("trade_value_evidence", None)
            row.component_sources_json = json.dumps(sources)
            db.commit()
        state = read_taiwan_market_volume_state(db)
        assert state["current_cumulative_trade_value"] == 1200
        assert state["trade_value_complete"] is True
        assert state["same_time_baseline_5d"]["decision_usable"] is False
        assert state["same_time_baseline_5d"]["pace_ratio"] is None
        assert compose_taiwan_market_volume_state(state, breadth=None)["same_time_baseline_5d"]["decision_usable"] is False
        if bad_day != "current":
            assert state["same_time_baseline_5d"]["sample_days"] == 4
            assert state["baseline_diagnostics"]["unqualified_trade_value"] == 1
    finally:
        db.close()
        db.bind.dispose()


@pytest.mark.parametrize("estimated", [True, False])
def test_qualified_persisted_5d_20d_preserves_authority_and_typed_roundtrip(estimated):
    from datetime import date, timedelta
    from app.market.schemas import TaiwanMarketVolumeStateRead
    from app.market.trading_calendar import is_taiwan_trading_day
    from app.market.taiwan_market_state import persist_taiwan_market_minute_state, read_taiwan_market_volume_state
    from test_taiwan_market_state import make_session, market_summary_payload
    db = make_session()
    try:
        current_day = date(2026, 10, 22)
        days = [current_day - timedelta(days=n) for n in range(40)
                if is_taiwan_trading_day(current_day - timedelta(days=n))][:21]
        for day in reversed(days):
            payload = market_summary_payload(day, hour=11, minute=19,
                                            twse_trade_value=1000, tpex_trade_value=200)
            if estimated:
                for item in payload["indices"]:
                    qualified_estimate(item["breadth"])
            persist_taiwan_market_minute_state(db, payload=payload)
        result = read_taiwan_market_volume_state(db)
        typed = TaiwanMarketVolumeStateRead.model_validate(result).model_dump(mode="json")
        recomposed = compose_taiwan_market_volume_state(typed, breadth=None)
        for state in (result, typed, recomposed):
            assert state["trade_value_qualification"]["decision_usable"] is True
            for count in (5, 20):
                baseline = state[f"same_time_baseline_{count}d"]
                assert baseline["pace_ratio"] == 1
                assert baseline["decision_usable"] is True
                assert baseline["qualified_sample_days"] == count
            assert state["estimated_cumulative_trade_value"] == (1200 if estimated else None)
            assert state["official_cumulative_trade_value"] == (None if estimated else 1200)
            assert state["trade_date"] == "2026-10-22"
        assert not db.dirty and not db.new
    finally:
        db.close()
        db.bind.dispose()


@pytest.mark.parametrize("field,value", [("received_count", 99), ("failed_batch_count", None),
                                        ("skipped_batch_count", False), ("acquisition_complete", "true")])
def test_malformed_acquisition_cannot_become_complete(field, value):
    volume, breadth = evidence()
    for item in breadth["markets"].values():
        qualified_estimate(item)
    breadth["markets"]["TWSE"]["acquisition_diagnostics"][field] = value
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["trade_value_qualification"]["decision_usable"] is False


def test_incident_1119_value_is_retained_without_promoting_011_pace():
    volume, breadth = evidence()
    for market, item in breadth["markets"].items():
        qualified_estimate(item)
        total, received, directional = (1080, 497, 76) if market == "TWSE" else (887, 297, 75)
        item.update(total_count=total, trade_value=10_000_000_000 if market == "TWSE" else 3_956_232_687)
        item["acquisition_diagnostics"].update(acquisition_complete=False, failed_batch_count=1,
                                             skipped_batch_count=5, received_count=received)
        item["coverage_reason_counts"] = dict(advance=directional, decline=0, unchanged=0,
            valid_no_trade=0, actual_trade_unavailable=received-directional, provider_missing=total-received)
    volume["same_time_baseline_5d"].update(median_cumulative_trade_value=134_323_923_524,
        comparison_identity={m: _volume_comparison_identity(i) for m, i in breadth["markets"].items()})
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["current_cumulative_trade_value"] == 13_956_232_687
    assert result["trade_value_complete"] is True
    assert result["trade_value_qualification"]["status"] == "best_effort"
    assert result["same_time_baseline_5d"]["pace_ratio"] is None


def test_qualified_fallback_preserves_event_received_date_and_source_lineage():
    volume, breadth = evidence()
    for item in breadth["markets"].values():
        qualified_estimate(item)
        item["lineage"]["received_at"] = "2026-09-14T09:07:02+08:00"
        item["observation_received_at"] = "2026-09-14T09:07:02+08:00"
    volume["same_time_baseline_5d"]["comparison_identity"] = {
        market: _volume_comparison_identity(item) for market, item in breadth["markets"].items()
    }
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["same_time_baseline_5d"]["decision_usable"] is True
    assert result["trade_value_authority_status"] == "estimated"
    assert result["official_cumulative_trade_value"] is None
    for item in result["markets"]:
        original = breadth["markets"][item["market"]]
        assert item["trade_date"] == original["trade_date"]
        assert item["as_of"] == original["as_of"]
        assert item["lineage"] == original["lineage"]
        assert item["observation_received_at"] == original["observation_received_at"]
        assert item["trade_value_qualification"]["price_coverage_ratio"] == 1


@pytest.mark.parametrize("partition", [None, {}, {"advance": 100},
    dict(advance=100, decline=0, unchanged=0, valid_no_trade=False),
    dict(advance=101, decline=0, unchanged=0, valid_no_trade=0),
    dict(advance=99, decline=0, unchanged=0, valid_no_trade=0),
    dict(advance=100, decline=0, unchanged=0, valid_no_trade=-1)])
def test_missing_or_malformed_price_partition_stays_best_effort(partition):
    volume, breadth = evidence()
    for item in breadth["markets"].values():
        qualified_estimate(item)
    breadth["markets"]["TWSE"]["coverage_reason_counts"] = partition
    result = compose_taiwan_market_volume_state(volume, breadth=breadth)
    assert result["current_cumulative_trade_value"] == 41_097_867_618
    assert result["trade_value_qualification"]["decision_usable"] is False


def test_official_index_value_owner_retains_existing_authority_alias():
    from datetime import date
    from app.market.schemas import TaiwanMarketVolumeStateRead
    from app.market.taiwan_market_state import persist_taiwan_market_minute_state, read_taiwan_market_volume_state
    from test_taiwan_market_state import make_session, market_summary_payload
    db = make_session()
    try:
        for day in (7, 8, 9, 10, 11, 14):
            payload = market_summary_payload(date(2026, 9, day), hour=9, minute=6,
                                            twse_trade_value=1000, tpex_trade_value=200)
            for item in payload["indices"]:
                item["breadth"]["trade_value"] = None
                item["official"] = True  # Existing index-summary authority contract.
            persist_taiwan_market_minute_state(db, payload=payload)
        result = read_taiwan_market_volume_state(db)
        assert result["same_time_baseline_5d"]["pace_ratio"] == 1
        typed = TaiwanMarketVolumeStateRead.model_validate(result).model_dump(mode="json")
        assert typed["trade_value_qualification"]["decision_usable"] is True
        assert typed["official_cumulative_trade_value"] == 1200
    finally:
        db.close()
        db.bind.dispose()
