"""Shared V4 projection isolates callers without copying discarded histories."""
from copy import deepcopy
import json

import pytest

from app.ai import decision_envelope, decision_envelope_v4
from test_ai_decision_envelope import _v2_response


@pytest.mark.parametrize("market,symbol,target_type", [("TW", "2330", "tw_stock"), ("US", "AAPL", "us_stock")])
def test_legacy_result_is_optional_only_at_internal_v4_seam(market, symbol, target_type):
    source = _v2_response()
    source["target"].update(type=target_type, id=symbol, market=market)
    before = deepcopy(source)
    legacy = decision_envelope.build(source)
    projected_base = decision_envelope.build(source, include_evidence_result=False)
    assert legacy["evidence"]["result"]
    legacy["evidence"]["result"] = {}
    assert projected_base == legacy
    assert source == before


@pytest.mark.parametrize("canonical_replacement", [False, True])
def test_v4_only_copies_the_selected_source_history_and_preserves_input_isolation(canonical_replacement):
    copies = []
    class TracedHistory(dict):
        def __deepcopy__(self, memo):
            copies.append(self["identity"])
            value = TracedHistory({key:deepcopy(item, memo) for key,item in self.items()})
            memo[id(self)] = value
            return value
    source = _v2_response()
    source["output"] = "evidence_only"
    source["selection"] = {"include": ["target.identity"]}
    source["result"]["data"]["unselected_history"] = TracedHistory(identity="original", points=[{"value":n} for n in range(1800)])
    replacement = deepcopy(source["result"]) if canonical_replacement else None
    if replacement is not None:
        replacement["data"]["unselected_history"]["identity"] = "canonical"
    before = json.dumps(source, sort_keys=True)
    replacement_before = json.dumps(replacement, sort_keys=True)
    copies.clear()
    result = decision_envelope_v4.build(source, canonical_result=replacement)
    assert copies == []
    assert json.dumps(source, sort_keys=True) == before
    assert json.dumps(replacement, sort_keys=True) == replacement_before
    result["target"]["id"] = "mutated"
    result["execution"]["policy"]["injected"] = True
    assert json.dumps(source, sort_keys=True) == before
    assert json.dumps(replacement, sort_keys=True) == replacement_before


@pytest.mark.parametrize("builder", [decision_envelope.build, decision_envelope_v4.build])
def test_all_returned_mutable_branches_are_isolated_from_the_caller(builder):
    source = _v2_response()
    source["analysis"]["decision_contract"]["readiness"] = {"evidence_status": "old"}
    # Preserve aliasing in the input: readiness must not mutate another branch
    # pointing at the original analysis either.
    source["result"]["aliased_analysis"] = source["analysis"]
    before = deepcopy(source)
    response = builder(source)
    visited = set()
    def mutate(value):
        if not isinstance(value, (dict, list)) or id(value) in visited:
            return
        visited.add(id(value))
        for child in list(value.values()) if isinstance(value,dict) else list(value):
            mutate(child)
        if isinstance(value, dict):
            value["fixture_mutation"] = True
        else:
            value.append("fixture_mutation")
    mutate(response)
    assert source == before


@pytest.mark.parametrize("market,symbol,target_type", [("TW", "2330", "tw_stock"), ("US", "AAPL", "us_stock")])
@pytest.mark.parametrize("canonical_replacement", [False, True])
def test_selected_technical_projection_keeps_all_mutable_branches_private(
    market, symbol, target_type, canonical_replacement,
):
    from test_ai_technical_quality_projection import technical_payload

    source = _v2_response()
    source["target"].update(type=target_type, id=symbol, market=market)
    source["output"] = "decision_with_evidence"
    source["selection"] = {"include": ["technical.indicators"]}
    technical = technical_payload(3) if market == "TW" else {
        "schema_version": "omi.research.technical.indicators.v1", "market": "US",
        "status": "partial", "quality": {"decision_usable": False, "reason_codes": ["UNKNOWN_BASIS"]},
        "input_quality": {"input_bar_count": 260}, "current": {"close": 123},
        "warnings": ["fixture"], "corporate_action": {"coverage_status": "unknown"},
    }
    source["result"]["data"].setdefault("compact", {})["technical_indicators"] = technical
    replacement = deepcopy(source["result"]) if canonical_replacement else None
    before = deepcopy((source, replacement))
    result = decision_envelope_v4.build(source, canonical_result=replacement)
    assert (source, replacement) == before
    assert result["evidence"]["data"]["technical.indicators"]

    def mutable_ids(root):
        seen, mutable = set(), set()
        def visit(value):
            if not isinstance(value, (dict, list, tuple)) or id(value) in seen:
                return
            seen.add(id(value))
            if isinstance(value, (dict, list)):
                mutable.add(id(value))
            for child in value.values() if isinstance(value, dict) else value:
                visit(child)
        visit(root)
        return mutable

    # Detect every output alias, including branches added by quality/budget
    # reconciliation, not only the top-level indicator values.
    assert mutable_ids((source, replacement)).isdisjoint(mutable_ids(result))
