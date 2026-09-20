from copy import deepcopy

import pytest

from app.ai import capability_contract, data_quality_contract, decision_envelope_v4


def completed_daily_evidence():
    quality = {
        "quote.snapshot": {"temporal": {"latest_date": "2026-09-16"}, "decision_usable": True},
        "technical.structure": {"temporal": {"latest_date": "2026-09-15"}, "decision_usable": True, "issues": []},
    }
    data = {
        "quote.snapshot": {"price": 204, "session_date_relation": {
            "expected": True, "status": "aligned",
            "relation": "expected_current_session_vs_completed_daily",
            "quote_date": "2026-09-16", "current_session_date": "2026-09-16",
            "completed_daily_date": "2026-09-15", "previous_trading_day": "2026-09-15",
        }},
        "technical.structure": {
            "market": "TW", "symbol": "6147", "timeframe": "daily",
            "as_of": "2026-09-15", "latest_price": 196, "decision_snapshot": "completed",
            "price_basis": "raw_unadjusted", "lineage": {
                "dataset_id": "tw.daily.ohlcv", "series_revision": "fixture-revision",
                "latest_component": {"event_at": "2026-09-15T13:30:00+08:00"},
            },
        },
    }
    return quality, data


def fuse(quality, data):
    return data_quality_contract._fusion_issues(
        quality, projected_data=data, target={"id": "6147", "type": "tw_stock", "market": "TW"},
    )


def test_completed_daily_structure_is_legal_without_selecting_daily_ohlcv():
    quality, data = completed_daily_evidence()
    assert fuse(quality, data) == []
    assert quality["technical.structure"]["decision_usable"] is True


@pytest.mark.parametrize("field,value", [
    ("symbol", "2330"), ("market", "US"), ("timeframe", "1m"),
    ("decision_snapshot", "current_partial"), ("price_basis", "split_adjusted"),
    ("lineage", {}),
])
def test_cross_date_exception_rejects_mismatched_basis(field, value):
    quality, data = completed_daily_evidence()
    data["technical.structure"][field] = value
    assert fuse(quality, data)[0]["code"] == "price_basis_date_mismatch"
    assert quality["technical.structure"]["decision_usable"] is False


@pytest.mark.parametrize("technical_date", ["2026-09-14", "2026-09-17"])
def test_old_or_future_structure_is_blocked_even_with_equal_price(technical_date):
    quality, data = completed_daily_evidence()
    quality["technical.structure"]["temporal"]["latest_date"] = technical_date
    data["technical.structure"]["latest_price"] = data["quote.snapshot"]["price"]
    assert fuse(quality, data)[0]["code"] == "price_basis_date_mismatch"


def test_relation_does_not_upgrade_stale_or_unusable_structure():
    quality, data = completed_daily_evidence()
    quality["technical.structure"].update(decision_usable=False, issues=["stale"])
    original = deepcopy(quality)
    assert fuse(quality, data) == []
    assert quality == original


def test_adjusted_quote_or_missing_relation_remains_blocked():
    for change in ({"price_basis": "adjusted"}, {"session_date_relation": {}}, {"stock_id": "2330"}):
        quality, data = completed_daily_evidence()
        data["quote.snapshot"].update(change)
        assert fuse(quality, data)[0]["code"] == "price_basis_date_mismatch"


def test_public_projection_keeps_basis_and_validates_relation_without_daily_selection():
    _, data = completed_daily_evidence()
    quote = data["quote.snapshot"]
    quote.update(trade_date="2026-09-16", quote_time="2026-09-16T10:30:00+08:00", currency="TWD", price_unit="TWD", source="fixture")
    selection = capability_contract.normalize_selection(
        selection={"required": ["quote.snapshot", "technical.structure"]},
        output="decision_with_evidence", realtime_policy="cache_only", payload_level="standard",
        scope_type="stock", target_market="TW", question_intent="trend_view",
    )
    response = {
        "kind": "ai_ask", "ok": True, "request_status": "completed",
        "target": {"type": "tw_stock", "id": "6147", "market": "TW"},
        "mode": {"response": "analysis", "payload_level": "standard"},
        "analysis": {"question_intent": "trend_view"},
        "result": {"data": {"compact": {"quote": quote, "technical": data["technical.structure"]}}},
        "query_plan": {"target_type": "stock", "selection": selection},
    }
    result = decision_envelope_v4.build(response)
    technical = result["evidence"]["data"]["technical.structure"]
    assert technical["price_basis"] == "raw_unadjusted"
    assert technical["lineage"]["series_revision"] == "fixture-revision"
    assert "daily.ohlcv" not in result["evidence"]["data"]
    assert not any(issue["code"] == "price_basis_date_mismatch" for issue in result["evidence"]["quality"]["fusion"]["issues"])

    response["result"]["data"]["compact"]["technical"]["symbol"] = "2330"
    mismatch = decision_envelope_v4.build(response)
    assert any(issue["code"] == "price_basis_date_mismatch" for issue in mismatch["evidence"]["quality"]["fusion"]["issues"])
