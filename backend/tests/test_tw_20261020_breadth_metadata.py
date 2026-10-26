"""Deterministic regression for the 2026-10-20 main/auction lineage mixup."""
from copy import deepcopy

import pytest

from app.ai.data_quality_contract import build_quality_contract


def quality(payload):
    return build_quality_contract(
        canonical={"target": {"market": "TW"}, "evidence": {}},
        selection={"output": "evidence_only"},
        manifest={"capabilities": [{"capability": "market.breadth",
            "required": True, "status": "partial", "returned_count": 1}]},
        projected_data={"market.breadth": payload}, realtime_assessments={},
        scope_type="market",
    )["capabilities"]["market.breadth"]


@pytest.mark.parametrize("auction_first", [True, False])
def test_main_breadth_metadata_never_selects_supplemental_auction(auction_first):
    historical = {"source": "canonical_auction_breadth", "provider": "auction_provider",
        "event_at": "2026-10-20T08:58:59+08:00",
        "fetched_at": "2026-10-20T08:59:31+08:00", "fallback_used": True}
    auction = {"auction_breadth": historical, "latest_completed_auctions": [historical]}
    main = {"status": "partial", "market_session": "continuous",
        "decision_usable": False, "as_of": "2026-10-20T09:12:00+08:00",
        "markets": {"TWSE": {**auction, "lineage": {
            "provider": "twse_mis", "source": "twse_mis_live_breadth",
            "event_at": "2026-10-20T09:12:00+08:00",
            "fetched_at": "2026-10-20T09:12:38+08:00"}}},
        "source": "app.market.indices.summary", "fallback_used": False}
    payload = {**auction, **main} if auction_first else {**main, **auction}
    before = deepcopy(payload)
    result = quality(payload)
    assert result["selected_source"] == "app.market.indices.summary"
    assert result["selected_provider"] == "twse_mis"
    assert result["event_time"] == "2026-10-20T09:12:00+08:00"
    assert result["fetched_at"] == "2026-10-20T09:12:38+08:00"
    assert result["fallback_used"] is False
    assert result["decision_usable"] is False
    assert payload == before  # History is still available in its own lane.


def test_missing_main_metadata_does_not_borrow_auction_history():
    result = quality({"status": "partial", "market_session": "continuous",
        "auction_breadth": {"source": "canonical_auction_breadth"},
        "markets": {"TWSE": {"latest_completed_auctions": [{
            "provider": "twse_mis", "event_at": "2026-10-20T08:58:59+08:00"}]}}})
    assert result["selected_source"] is None
    assert result["selected_provider"] is None
    assert result["event_time"] is None


def test_primary_auction_observation_retains_its_own_metadata():
    result = quality({"status": "partial", "market_session": "opening_auction",
        "source": "canonical_auction_breadth", "provider": "twse_mis",
        "event_at": "2026-10-20T08:58:59+08:00", "decision_usable": False})
    assert result["selected_source"] == "canonical_auction_breadth"
    assert result["event_time"] == "2026-10-20T08:58:59+08:00"
    assert result["decision_usable"] is False
