"""Technical transport must not hide quality evidence behind a row limit."""
from copy import deepcopy
from datetime import date, timedelta
import json

import pytest

from app.ai import capability_contract, decision_envelope_v4
from app.market.tw_workspace_research import project_technical_input_quality


def technical_payload(count=31):
    states = [{
        "trade_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
        "state": "MISSING_EVIDENCE", "market_open": True,
        "instrument_status": "unknown", "expected_session": True,
        "price_basis": {"status": "unknown", "lineage": [{"receipt": "y" * 4000}]},
        "blockers": [f"REASON_{index}"], "limitations": ["basis unknown"],
        "lineage": [{"raw_receipt_id": "x" * 4000}],
    } for index in range(count)]
    quality = {
        "status": "partial", "decision_usable": False,
        "reason_codes": [f"REASON_{index}" for index in range(count)],
        "day_states": states,
        "day_state_blockers": [{"trade_date": row["trade_date"], "state": row["state"],
                                "reasons": row["blockers"]} for row in states],
        "canonical_limitations": [f"TW_DAILY_DAY_STATE:{row['trade_date']}:MISSING_EVIDENCE:PRICE_UNKNOWN" for row in states],
        "decision_window": {"eligible": False, "available_bars": 60},
    }
    return {
        "schema_version": "tw.technical.indicators.v4", "status": "partial",
        "stock_id": "2330", "as_of": "2026-11-05", "price_basis": "raw_unadjusted",
        "decision_usable": False, "input_quality": quality,
        "warnings": [f"warning {index}" for index in range(count)],
        "lineage": {"series_revision": "revision-A", "limitations": quality["canonical_limitations"]},
        "corporate_action": {"coverage_status": "unknown"},
        "timeframes": {name: {
            "completed": {"close": 123, "ma": {"ma20": 120}},
            "current_partial": {"close": 124, "decision_usable": False},
            "decision_usable": False, "input_quality": quality,
            "corporate_action": {"coverage_status": "unknown"},
        } for name in ("daily", "weekly", "monthly")},
    }


def project(value, *, fields=None):
    data, unavailable = capability_contract.project_selected_data(
        response={"result": {"data": {"compact": {"technical_indicators": value}}}},
        selection={"required": ["technical.indicators"],
                   "limits": {"technical.indicators": 1},
                   "fields": {"technical.indicators": fields} if fields else {}},
    )
    assert unavailable == []
    return data["technical.indicators"]


def test_row_limit_preserves_all_quality_groups_reasons_and_numerical_snapshots():
    original = technical_payload()
    before = deepcopy(original)
    result = project(original)
    quality = result["input_quality"]
    assert quality["reason_codes"] == original["input_quality"]["reason_codes"]
    assert quality["day_state_summary"]["count"] == 31
    assert len(quality["day_state_summary"]["groups"]) == 31
    assert len(quality["day_state_blocker_summary"]["groups"]) == 31
    assert quality["day_state_summary"]["date_bounds_are_continuous"] is False
    assert quality["day_state_summary"]["details_projection"] == "canonical_technical_series"
    assert quality["canonical_limitations_summary"]["grouped_count"] == 31
    assert quality["decision_usable"] is False and result["decision_usable"] is False
    assert result["warnings"] == original["warnings"]
    for name, snapshot in result["timeframes"].items():
        assert snapshot["completed"] == original["timeframes"][name]["completed"]
        assert snapshot["current_partial"] == original["timeframes"][name]["current_partial"]
        assert snapshot["input_quality"]["day_state_summary"]["count"] == 31
    assert result["lineage"]["series_revision"] == "revision-A"
    assert result["lineage"]["limitations_summary"]["grouped_count"] == 31
    assert len(json.dumps(result)) < len(json.dumps(original)) / 10
    assert original == before


def test_narrow_fields_keep_quality_axes_and_long_warning_verbatim():
    original = technical_payload(2)
    original["warnings"] = ["warning " * 1000]
    result = project(original, fields=["as_of"])
    assert result["decision_usable"] is False
    assert result["price_basis"] == "raw_unadjusted"
    assert result["warnings"] == original["warnings"]
    assert result["corporate_action"] == original["corporate_action"]
    assert "timeframes" not in result


def test_us_quality_is_preserved_without_taiwan_day_state_projection():
    value = {"schema_version": "omi.research.technical.indicators.v1", "market": "US",
             "quality": {"decision_usable": False, "reason_codes": [str(i) for i in range(31)]},
             "input_quality": {"input_bar_count": 260}, "current": {"close": 123}}
    result = project(value)
    assert result["quality"] == value["quality"]
    assert result["current"] == value["current"]
    assert "quality_projection" not in result


@pytest.mark.parametrize("bad_states", [None, "unknown", [None], [{"state": "unknown"}]])
def test_malformed_day_states_are_preserved_without_fabricating_empty_coverage(bad_states):
    value = {"decision_usable": False, "day_states": bad_states}
    assert project_technical_input_quality(value) == value


def test_budget_summary_keeps_each_timeframe_quality_and_corporate_restriction():
    result = project(technical_payload(2))
    summary = decision_envelope_v4._brief_capability_summary("technical.indicators", result)
    assert summary["decision_usable"] is False
    assert summary["quality_projection"] == result["quality_projection"]
    for name, snapshot in summary["timeframes"].items():
        assert snapshot["decision_usable"] is False
        assert snapshot["input_quality"] == result["timeframes"][name]["input_quality"]
        assert snapshot["corporate_action"] == result["timeframes"][name]["corporate_action"]


def test_distinct_lineage_limitation_groups_do_not_share_temporary_object_identity():
    value = technical_payload(2)
    for name in ("daily", "weekly", "monthly"):
        value["timeframes"][name]["lineage"] = {
            "limitations": [f"TW_DAILY_DAY_STATE:2026-11-05:MISSING_EVIDENCE:{name}"]}
    result = project(value)
    for name, snapshot in result["timeframes"].items():
        assert snapshot["lineage"]["limitations_summary"]["groups"][0]["reason"] == name


@pytest.mark.parametrize("budget", [4096, 1048576])
def test_public_v4_preserves_quality_or_explicitly_rejects_insufficient_budget(budget):
    from app.ai import decision_envelope
    from test_ai_decision_envelope import _v2_response

    response = _v2_response()
    response["query_plan"] = {"target_type": "stock", "payload_level": "full",
        "selection": capability_contract.normalize_selection(
            selection={"include": ["technical.indicators"], "max_response_bytes": budget},
            output="evidence_only", realtime_policy="cache_only", payload_level="full",
            scope_type="stock", target_market="TW", question_intent="general",
        )}
    response["result"]["data"]["compact"]["technical_indicators"] = technical_payload()
    canonical = decision_envelope.for_requested_contract(response, requested_contract_version="omi.decision.v4")
    if budget == 4096:
        assert canonical["ok"] is False
        assert canonical["projection"]["required_payload_preserved"] is False
        assert canonical["request_status"] == "rejected"
    else:
        value = canonical["evidence"]["data"]["technical.indicators"]
        assert canonical["projection"]["required_payload_preserved"] is True
        assert value["input_quality"]["day_state_summary"]["count"] == 31
        assert len(value["input_quality"]["reason_codes"]) == 31
        assert value["decision_usable"] is False
        assert canonical["status"]["readiness"]["decision_ready"] is False


@pytest.mark.parametrize("status,expected", [("stale", "partial"), ("missing", "missing")])
def test_selected_stale_observation_is_not_reclassified_as_missing(status, expected):
    canonical = {"evidence": {}}
    projected = {"quote.snapshot": {"status": status,
                                    "selected_event_at": "2026-11-05T19:25:11Z"}}
    decision_envelope_v4._project_selected_freshness(
        canonical, selection={"required": ["quote.snapshot", "data.freshness"]},
        projected_data=projected,
    )
    summary = projected["data.freshness"]
    assert summary["status"] == expected
    assert summary["is_current"] is False
    if status == "stale":
        assert summary["missing"] == []
        assert summary["as_of"] == "2026-11-05T19:25:11Z"
