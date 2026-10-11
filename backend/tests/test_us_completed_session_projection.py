from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.ai.capability_contract import _historical_intraday_fill_state, build_manifest, build_fill_plan
from app.us_market.market_truth import read_us_market_truth_bundle
from app.us_market.service import _market_truth_compat_intraday_payload
from test_us_market_truth_snapshot import _bar, _fake_components, _install_fake_components


@pytest.mark.parametrize("evaluated_at,expected_date,expected_count", [
    (datetime(2026, 9, 13, 6, tzinfo=timezone.utc), "2026-09-11", 390),
    (datetime(2026, 9, 11, 20, tzinfo=timezone.utc), "2026-09-11", 390),
    (datetime(2026, 11, 27, 18, tzinfo=timezone.utc), "2026-11-27", 210),
])
def test_empty_completed_session_keeps_date_coverage_and_fill_action(monkeypatch, evaluated_at, expected_date, expected_count):
    _install_fake_components(monkeypatch, _fake_components(intraday_available=False))
    bundle = read_us_market_truth_bundle(
        object(), symbol="AAPL", evaluated_at=evaluated_at,
        requested_scope="regular",
    )
    payload = _market_truth_compat_intraday_payload(
        bundle=bundle, session_scope="regular", interval="1m",
    )
    assert payload["requested_trade_date"] == expected_date
    assert payload["session_coverage"]["coverage_status"] == "missing"
    assert payload["session_coverage"]["expected_point_count"] == expected_count
    assert payload["session_coverage"]["missing_slot_count"] == expected_count
    assert payload["is_live"] is False
    assert payload["decision_usable"] is False
    fill = _historical_intraday_fill_state(
        scope_type="us_stock", capability_id="intraday.bars", value=payload,
        now=evaluated_at,
    )
    assert fill is not None
    assert fill["satisfied"] is False
    if bundle.series.current_session_expected:
        # The empty completed date is allowed, but older data cannot be relabeled.
        with pytest.raises(ValueError, match="missing current-session series"):
            type(bundle.series).model_validate({
                **bundle.series.model_dump(), "trade_date": "2026-08-01",
            })
        with pytest.raises(ValueError, match="missing current-session series"):
            type(bundle.series).model_validate({
                **bundle.series.model_dump(), "regular_session_completed": False,
            })


@pytest.mark.parametrize("count,complete", [(182, False), (204, False), (390, True)])
@pytest.mark.parametrize("interval", ["1m", "5m"])
@pytest.mark.parametrize("fill_at,expired", [
    (datetime(2026, 9, 1, 1, tzinfo=timezone.utc), False),
    (datetime(2026, 10, 5, 20, tzinfo=timezone.utc), False),  # inclusive day 35
    (datetime(2026, 10, 6, 20, tzinfo=timezone.utc), True),
    (datetime(2026, 10, 11, 1, tzinfo=timezone.utc), True),
])
def test_default_completed_session_carries_canonical_coverage(monkeypatch, count, complete, interval, fill_at, expired):
    quote, intraday, daily = _fake_components()
    start = datetime(2026, 8, 31, 13, 30, tzinfo=timezone.utc)
    bars = tuple(
        _bar(observation_id=f"bar-{i}", start_at=start + timedelta(minutes=i),
             end_at=start + timedelta(minutes=i + 1), close="100")
        for i in range(count)
    )
    _install_fake_components(monkeypatch, (quote, intraday.model_copy(update={"bars": bars}), daily))
    bundle = read_us_market_truth_bundle(
        object(), symbol="AAPL", evaluated_at=datetime(2026, 9, 1, 1, tzinfo=timezone.utc),
        requested_scope="regular",
    )
    result = _market_truth_compat_intraday_payload(bundle=bundle, session_scope="regular", interval=interval)
    assert result["session_coverage"]["missing_slot_count"] == 390 - count
    assert result["session_coverage"]["coverage_status"] == ("complete" if complete else "partial")
    assert result["is_partial"] is not complete
    assert result["requested_trade_date"] == "2026-08-31"
    assert result["decision_usable"] is False
    from app.us_market.schemas import USIntradayTrendRead
    transport = USIntradayTrendRead.model_validate(result).model_dump(mode="json")
    assert transport["session_coverage"]["missing_slot_count"] == 390 - count
    assert transport["requested_trade_date"] == "2026-08-31"
    assert transport["is_partial"] is not complete
    state = _historical_intraday_fill_state(scope_type="us_stock", capability_id="intraday.bars", value=result, now=fill_at)
    assert state["satisfied"] is complete
    assert state["refresh_required"] is not complete
    assert state["refresh_possible_now"] is (not complete and not expired)
    if expired:
        assert state["reason_code"] == "US_INTRADAY_HISTORY_OUTSIDE_BOUNDED_HORIZON"
    assert state["market_data_params"]["trade_date"] == "2026-08-31"


@pytest.mark.parametrize("interval", ["1m", "5m"])
def test_unknown_finalization_does_not_become_complete(monkeypatch, interval):
    from app.market_data.contracts import BarFinalization
    quote, intraday, daily = _fake_components()
    start = datetime(2026, 8, 31, 13, 30, tzinfo=timezone.utc)
    bars = tuple(
        _bar(observation_id=f"bar-{i}", start_at=start + timedelta(minutes=i),
             end_at=start + timedelta(minutes=i + 1), close="100").model_copy(
                 update={"finalization": BarFinalization.UNKNOWN})
        for i in range(390)
    )
    _install_fake_components(monkeypatch, (quote, intraday.model_copy(update={"bars": bars}), daily))
    bundle = read_us_market_truth_bundle(
        object(), symbol="AAPL", evaluated_at=datetime(2026, 9, 1, 1, tzinfo=timezone.utc),
        requested_scope="regular",
    )
    result = _market_truth_compat_intraday_payload(bundle=bundle, session_scope="regular", interval=interval)
    assert result["is_partial"] is True
    assert result["session_coverage"]["unfinalized_count"] == 390
    assert all(not p["finalized"] for p in result["points"])
    for now in (datetime(2026, 9, 1, 1, tzinfo=timezone.utc), datetime(2026, 10, 11, tzinfo=timezone.utc)):
        state = _historical_intraday_fill_state(scope_type="us_stock", capability_id="intraday.bars", value=result, now=now)
        assert state["satisfied"] is False
        assert state["refresh_required"] is True
        assert state["refresh_possible_now"] is (now.month == 9)


@pytest.fixture(params=["1m", "5m"])
def complete_payload(monkeypatch, request):
    quote, intraday, daily = _fake_components(quote_available=False, intraday_limitations=(
        "PARTIAL_US_MARKET_VOLUME", "PERSONAL_INTERNAL_USE_ONLY",
    ))
    start = datetime(2026, 8, 31, 13, 30, tzinfo=timezone.utc)
    bars = tuple(_bar(observation_id=f"bar-{i}", start_at=start + timedelta(minutes=i),
                      end_at=start + timedelta(minutes=i + 1), close="100") for i in range(390))
    _install_fake_components(monkeypatch, (quote, intraday.model_copy(update={"bars": bars}), daily))
    bundle = read_us_market_truth_bundle(object(), symbol="AAPL",
        evaluated_at=datetime(2026, 9, 1, 1, tzinfo=timezone.utc), requested_scope="regular")
    return _market_truth_compat_intraday_payload(bundle=bundle, session_scope="regular", interval=request.param)


@pytest.mark.parametrize("day,scope,reason", [
    ("2026-10-12", "regular", "US_INTRADAY_SESSION_NOT_COMPLETED"),
    ("2026-10-11", "regular", "US_INTRADAY_NO_TRADING_SESSION"),
    ("2026-09-07", "regular", "US_INTRADAY_NO_TRADING_SESSION"),
    ("invalid", "regular", "US_INTRADAY_INVALID_REQUEST"),
    ("2026-08-31", "invalid", "US_INTRADAY_INVALID_REQUEST"),
    (123, "regular", "US_INTRADAY_INVALID_REQUEST"),
])
def test_complete_label_cannot_override_invalid_session(complete_payload, day, scope, reason):
    payload = complete_payload
    payload.update(requested_trade_date=day, session_scope=scope)
    payload["session_coverage"].update(trade_date=day, requested_scope=scope)
    state = _historical_intraday_fill_state(scope_type="us_stock", capability_id="intraday.bars",
        value=payload, now=datetime(2026, 10, 11, 12, tzinfo=timezone.utc))
    assert state["satisfied"] is False
    assert state["refresh_required"] is True
    assert state["refresh_possible_now"] is False
    assert state["reason_code"] == reason


@pytest.mark.parametrize("damage", [
    "missing_slot_count", "gap_count", "duplicate_count", "non_monotonic_count", "off_grid_count",
    "unfinalized_count", "unknown_finalization", "wrong_date", "wrong_scope", "missing_coverage",
    "missing", "partial", "unusable", "provisional",
])
@pytest.mark.parametrize("expired", [False, True])
def test_complete_label_requires_canonical_validity(complete_payload, damage, expired):
    payload = complete_payload
    coverage = payload["session_coverage"]
    if damage.endswith("_count"):
        coverage[damage] = 1
    elif damage == "unknown_finalization":
        coverage["unfinalized_count"] = None
    elif damage == "wrong_date":
        coverage["trade_date"] = "2026-08-28"
    elif damage == "wrong_scope":
        coverage["requested_scope"] = "all"
    elif damage == "missing_coverage":
        payload["session_coverage"] = None
    elif damage in {"missing", "partial"}:
        coverage["coverage_status"] = damage
    elif damage == "unusable":
        payload["bar_source_status"]["has_usable_data"] = False
    else:
        payload["is_partial"] = True
    state = _historical_intraday_fill_state(scope_type="us_stock", capability_id="intraday.bars",
        value=payload, now=datetime(2026, 10, 11, tzinfo=timezone.utc) if expired else datetime(2026, 9, 1, 1, tzinfo=timezone.utc))
    assert state["satisfied"] is False
    assert state["refresh_required"] is True
    assert state["refresh_possible_now"] is not expired


@pytest.mark.parametrize("expired", [False, True])
def test_manifest_fill_plan_keeps_quote_quality_and_projection_independent(complete_payload, expired):
    payload = complete_payload
    # A bounded outward sample retains the canonical coverage/finalization proof.
    payload["points"] = payload["points"][:1]
    payload.update(returned_count=1, truncated=True)
    before = deepcopy(payload)
    canonical = {"ok": True, "request_status": "completed",
        "target": {"type": "us_stock", "id": "AAPL", "market": "US"}, "evidence": {}, "execution": {}}
    selection = {"version": "test", "required": ["quote.snapshot", "intraday.bars"], "optional": []}
    manifest = build_manifest(canonical=canonical, selection=selection,
        projected_data={"intraday.bars": payload},
        now=datetime(2026, 10, 11, tzinfo=timezone.utc) if expired else datetime(2026, 9, 1, 1, tzinfo=timezone.utc))
    items = {item["capability"]: item for item in manifest["capabilities"]}
    assert items["intraday.bars"]["fill_state"]["satisfied"] is True
    assert items["intraday.bars"]["refresh_possible_now"] is False
    assert items["intraday.bars"]["historical_fill_required"] is False
    assert items["quote.snapshot"]["payload_included"] is False
    plan = build_fill_plan(canonical=canonical, selection=selection, manifest=manifest, scope_type="us_stock")
    assert "intraday.bars" in plan["partition"]["already_satisfied"]
    assert "quote.snapshot" not in plan["partition"]["already_satisfied"]
    assert payload == before
    assert payload["decision_usable"] is False
    assert "PARTIAL_US_MARKET_VOLUME" in payload["warnings"]
    assert "PERSONAL_INTERNAL_USE_ONLY" in payload["warnings"]


@pytest.mark.parametrize("scope", ["regular", "extended", "all"])
@pytest.mark.parametrize("interval", ["1m", "5m"])
@pytest.mark.parametrize("expired", [False, True])
def test_early_close_regular_coverage_is_not_extended_coverage(monkeypatch, scope, interval, expired):
    quote, intraday, daily = _fake_components()
    start = datetime(2026, 11, 27, 14, 30, tzinfo=timezone.utc)
    bars = tuple(_bar(observation_id=f"early-{i}", start_at=start + timedelta(minutes=i),
                      end_at=start + timedelta(minutes=i + 1), close="100") for i in range(210))
    _install_fake_components(monkeypatch, (quote, intraday.model_copy(update={"bars": bars}), daily))
    evaluated = datetime(2026, 11, 28, 1, tzinfo=timezone.utc)
    bundle = read_us_market_truth_bundle(object(), symbol="AAPL", evaluated_at=evaluated, requested_scope=scope)
    payload = _market_truth_compat_intraday_payload(bundle=bundle, session_scope=scope, interval=interval)
    coverage = payload["session_coverage"]
    assert coverage["expected_point_count"] == 210
    assert coverage["missing_slot_count"] == 0
    assert coverage["unfinalized_count"] == 0
    if scope != "regular":
        assert coverage["regular_coverage_status"] == "complete"
        assert coverage["coverage_status"] in {"partial", "missing"}
        assert payload["is_partial"] is True
    state = _historical_intraday_fill_state(scope_type="us_stock", capability_id="intraday.bars",
        value=payload, now=datetime(2027, 1, 4, tzinfo=timezone.utc) if expired else evaluated)
    assert state["satisfied"] is (scope == "regular")
    assert state["refresh_required"] is (scope != "regular")
    assert state["refresh_possible_now"] is False
    if expired:
        assert state["reason_code"] == "US_INTRADAY_HISTORY_OUTSIDE_BOUNDED_HORIZON"
