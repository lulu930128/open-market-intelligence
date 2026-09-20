from datetime import datetime, timedelta, timezone

import pytest

from app.ai.capability_contract import _historical_intraday_fill_state
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
def test_default_completed_session_carries_canonical_coverage(monkeypatch, count, complete, interval):
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
    state = _historical_intraday_fill_state(scope_type="us_stock", capability_id="intraday.bars", value=result)
    assert state["satisfied"] is complete
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
