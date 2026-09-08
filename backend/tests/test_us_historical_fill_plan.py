from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.ai import capability_contract as contract
from app.ai import data_quality_contract

NOW = datetime(2026, 9, 7, 13, tzinfo=timezone.utc)


def build_case(complete=False, day="2026-09-04"):
    payload = {"requested_trade_date": day, "session_scope": "regular", "interval": "1m",
               "point_count": 390 if complete else 333, "is_partial": not complete,
               "session_coverage": {"coverage_status": "complete" if complete else "partial",
                                    "missing_slot_count": 0 if complete else 57}}
    canonical = {"ok": True, "request_status": "completed",
                 "target": {"type": "us_stock", "id": "TSM", "market": "US"},
                 "evidence": {}, "execution": {}}
    selection = {"version": "test", "required": ["intraday.bars"], "optional": []}
    with patch.object(contract, "datetime") as clock:
        clock.now.return_value = NOW
        manifest = contract.build_manifest(
            canonical=canonical, selection=selection, projected_data={"intraday.bars": payload},
            realtime_assessments={"intraday.bars": {"state": "latest_completed_session", "status_class": "ready",
                "decision_usable": False, "refresh_recommended": False, "refresh_possible_now": False}},
        )
    plan = contract.build_fill_plan(canonical=canonical, selection=selection, manifest=manifest, scope_type="us_stock")
    return canonical, selection, manifest, plan


def test_final_quality_projection_cannot_erase_historical_fill_requirement():
    canonical, selection, manifest, _ = build_case()
    payload = {"requested_trade_date": "2026-09-04", "point_count": 333, "is_partial": True,
               "session_coverage": {"coverage_status": "partial"},
               "points": [{"time": "2026-09-04T19:02:00Z", "price": 428.84}]}
    realtime = {"intraday.bars": {"state": "latest_completed_session", "status_class": "ready",
                "facts_usable": True, "decision_usable": False, "refresh_recommended": False, "refresh_possible_now": False}}
    canonical["evidence"]["manifest"] = manifest
    quality = data_quality_contract.build_quality_contract(canonical=canonical, selection=selection,
        manifest=manifest, projected_data={"intraday.bars": payload}, realtime_assessments=realtime, scope_type="us_stock")
    final = data_quality_contract.apply_quality_contract(canonical, quality=quality)
    item = final["evidence"]["manifest"]["capabilities"][0]
    assert item["refresh_recommended"] is True
    assert item["refresh_possible_now"] is True
    assert item["decision_usable"] is False
    plan = contract.build_fill_plan(canonical=final, selection=selection,
        manifest=final["evidence"]["manifest"], scope_type="us_stock")
    assert plan["action_count"] == 1


@pytest.mark.parametrize("complete", [False, True])
def test_completed_session_fill_and_reconciliation_share_satisfaction(complete):
    canonical, selection, manifest, plan = build_case(complete)
    item = manifest["capabilities"][0]
    assert item["fill_state"]["satisfied"] is complete
    assert item["refresh_recommended"] is not complete
    assert item["refresh_requires_market_open"] is False
    assert ("intraday.bars" in plan["partition"]["already_satisfied"]) is complete
    assert plan["action_count"] == (0 if complete else 1)
    result = contract.build_refresh_reconciliation(
            selection=selection, manifest=manifest, fill_plan=plan, tool_runs=[], scope_type="us_stock",
    )
    assert (result["capabilities"]["intraday.bars"]["resolution_type"] == "satisfied") is complete


def test_continuation_preserves_and_binds_historical_window():
    canonical, selection, manifest, plan = build_case()
    action = plan["actions"][0]
    args = action["invoke"]["arguments"]
    assert args["market_data_params"] == {"trade_date": "2026-09-04", "session_scope": "regular", "interval": "1m"}
    assert action["reason"] == "historical_intraday_coverage_partial"
    assert contract.selected_fill_capabilities(
        continuation=args["continuation"], selection=selection, target=canonical["target"],
        scope_type="us_stock", market_data_params=args["market_data_params"],
    ) == ("intraday.bars",)
    wrong = deepcopy(args["market_data_params"])
    wrong["trade_date"] = "2026-09-03"
    with pytest.raises(ValueError):
        contract.selected_fill_capabilities(continuation=args["continuation"], selection=selection,
            target=canonical["target"], scope_type="us_stock", market_data_params=wrong)


@pytest.mark.parametrize("day", ["2026-09-07", "2026-09-08", "2026-01-02"])
def test_ineligible_historical_window_is_explicitly_unfillable(day):
    _, _, _, plan = build_case(day=day)
    assert plan["action_count"] == 0
    assert plan["unfillable_actions"][0]["reason"].startswith("US_INTRADAY_")


def test_complete_supplemental_and_current_closed_keep_existing_satisfaction():
    assert contract._fill_payload_is_satisfied({"status_class": "ready", "payload_included": True, "decision_usable": False})
    assert contract._historical_intraday_fill_state(scope_type="us_stock", capability_id="intraday.bars", value={"is_partial": True}) is None


def test_non_us_continuation_keeps_existing_action_identity():
    target = {"type": "stock", "id": "2330", "market": "TW"}
    selection = {"version": "test", "required": ["intraday.bars"]}
    action_id = contract.fill_action_id(capability_id="intraday.bars", target=target, selection_version="test")
    continuation = {"plan_id": contract.fill_plan_id(target=target, action_ids=[action_id]),
                    "plan_action_ids": [action_id], "selected_action_ids": [action_id]}
    # Exercise identity compatibility independently of other markets' inventory.
    resolution = contract.capability_resolution_for(scope_type="us_stock", capability_id="intraday.bars")
    with patch.object(contract, "capability_resolution_for", return_value=resolution):
        assert contract.selected_fill_capabilities(continuation=continuation, selection=selection,
            target=target, scope_type="stock", market_data_params={"trade_date": "2026-09-04"}) == ("intraday.bars",)
