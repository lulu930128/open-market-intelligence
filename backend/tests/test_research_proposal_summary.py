"""List projection preserves journal identity and leaves frozen detail untouched."""
import json

import pytest

from test_research_trade_journal import engine
from test_research_trade_journal_http import api, creation_body, PREFIX


@pytest.mark.parametrize("market,symbol", [("TW", "2330"), ("US", "AAPL")])
def test_ai_summary_is_bounded_and_full_detail_retains_frozen_evidence(api, market, symbol):
    client, clock, statements = api
    body = creation_body(market=market, symbol=symbol, workflow_origin="AI_NOMINATION")
    body["evidence"]["market"] = market
    body["evidence"]["items"][0]["snapshot_json"] = json.dumps({"rows": ["frozen evidence"] * 5000})
    created = client.post(PREFIX + "/ai", body)
    assert created.status_code == 201, created.body
    original = created.body["proposal"]
    clock["readonly"] = True
    statements.clear()
    summary = client.get(PREFIX + "/ai", market=market, limit=1)
    assert summary.status_code == 200
    assert summary.body["projection"] == "research.proposal_list.summary.v1"
    assert summary.body["evidence_included"] is summary.body["execution_ready"] is False
    row = summary.body["items"][0]
    for field in ("creation_id", "revision_id", "revision", "market", "symbol", "evidence_hash"):
        assert row[field] == original[field]
    assert row["workflow_origin"] == "AI_NOMINATION"
    assert row["assessment_status"] is None and row["reason_codes"] == []
    assert "proposal" not in row and "snapshot_json" not in json.dumps(summary.body)
    assert len(json.dumps(summary.body)) < len(json.dumps(created.body)) / 20
    full = client.get(PREFIX + "/ai", market=market, view="full")
    detail = client.get(PREFIX + "/ai/" + row["creation_id"])
    assert full.body["items"][0]["proposal"] == detail.body["proposal"] == original
    assert client.get(PREFIX, market=market, view="summary", limit=1).body == summary.body
    assert client.get(PREFIX + "/ai", view="invalid").status_code == 422
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)


def test_summary_scope_filters_pagination_and_empty_result(api):
    client, _, _ = api
    for origin in ("USER_NOMINATION", "AI_NOMINATION", "OMI_SCREEN"):
        assert client.post(PREFIX, creation_body(workflow_origin=origin)).status_code == 201
    first = client.get(PREFIX + "/ai", limit=1).body
    second = client.get(PREFIX + "/ai", limit=1, offset=1).body
    assert first["has_more"] and not second["has_more"]
    assert first["items"][0]["creation_id"] != second["items"][0]["creation_id"]
    assert {first["items"][0]["workflow_origin"], second["items"][0]["workflow_origin"]} == {"AI_NOMINATION", "OMI_SCREEN"}
    assert client.get(PREFIX + "/ai", market="US").body["items"] == []
    assert len(client.get(PREFIX + "/ai", origin="AI_NOMINATION").body["items"]) == 1


@pytest.mark.parametrize("snapshot", [None, [], {"price_map": []},
    {"price_map": {"payload": []}, "assessment": []},
    {"assessment": {"status": [], "reason_codes": "not-a-list"}},
    {"assessment": {"reason_codes": [None, "unknown"]}},
    {"request": {"horizon_sessions": 999}},
    {"request": {"horizon_sessions": True}},
])
@pytest.mark.parametrize("market,symbol,source_ref", [
    ("TW", "2330", "research.stock_nomination.v1"),
    ("US", "AAPL", "research.us_watchlist_nomination.v1"),
])
def test_summary_tolerates_non_nomination_json_without_changing_evidence(api, snapshot, market, symbol, source_ref):
    from app.research import trade_journal
    from app.research.trade_proposal import ProposalVersion

    client, clock, _ = api
    body = creation_body(market=market, symbol=symbol, workflow_origin="AI_NOMINATION")
    body["evidence"]["market"] = market
    body["evidence"]["items"].append({**body["evidence"]["items"][0],
        "source_ref": source_ref, "snapshot_json": json.dumps(snapshot),
    })
    created = client.post(PREFIX + "/ai", body)
    assert created.status_code == 201, created.body
    original = created.body["proposal"]
    clock["readonly"] = True
    summary = client.get(PREFIX + "/ai", market=market).body["items"][0]
    assert summary["stock_name"] is summary["assessment_status"] is None
    assert summary["reason_codes"] == []
    assert summary["evidence_hash"] == original["evidence_hash"]
    assert client.get(PREFIX + "/ai/" + original["creation_id"]).body["proposal"] == original
    legacy = ProposalVersion.model_validate(original).model_copy(update={"workflow_origin": None})
    assert trade_journal.workflow_origin(legacy) is None
    assert created.body["eligibility"].get("research_eligible") is not True
