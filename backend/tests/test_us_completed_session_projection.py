from datetime import datetime, timedelta, timezone

import pytest

from app.ai.capability_contract import _historical_intraday_fill_state
from app.us_market.market_truth import read_us_market_truth_bundle
from app.us_market.service import _market_truth_compat_intraday_payload
from test_us_market_truth_snapshot import _bar, _fake_components, _install_fake_components


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
