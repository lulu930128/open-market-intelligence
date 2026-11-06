"""Research management scope and production Desk staging without broker IO."""
from datetime import timedelta
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy.orm import Session

from app.research.candidate_service import CandidateService
from app.research import research_order_service
from test_research_trade_journal import engine
from test_research_trade_journal_http import api, PREFIX, creation_body, revision_body
from test_conditional_candidates import migration
from test_conditional_candidates import setup, invoke


@pytest.mark.parametrize("market", ["TW", "US"])
def test_scope_move_stage_edit_and_delete_are_versioned(api, engine, monkeypatch, market):
    client, clock, _ = api
    monkeypatch.setattr(research_order_service, "utc_now", lambda: clock["now"])
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration().upgrade()
    body = creation_body(market=market, workflow_origin="OMI_SCREEN")
    if market == "US":
        body["symbol"] = "NVDA"
        body["evidence"]["market"] = "US"
    initial = client.post(PREFIX + "/ai", body)
    assert initial.status_code == 201, initial.body
    p = initial.body["proposal"]
    path = PREFIX + "/ai/" + p["creation_id"]
    clock["now"] += timedelta(seconds=1)
    blocked = client.post(path + "/stage", {"expected_revision_id": p["revision_id"], "client_intent_id": "scope-intent"})
    assert blocked.status_code == 409
    moved = client.post(path + "/move", {"expected_revision_id": p["revision_id"], "origin": "AI_NOMINATION"})
    assert moved.status_code == 200, moved.body
    assert moved.body["proposal"]["evidence_hash"] == p["evidence_hash"]
    p = moved.body["proposal"]
    staged = client.post(path + "/stage", {"expected_revision_id": p["revision_id"], "client_intent_id": "scope-intent"})
    assert staged.status_code == 201, staged.body
    row = staged.body
    assert row["manual_stage"]["submission"] is None
    assert row["raw"]["protection"]["enabled"] is True
    assert len(row["raw"]["protection"]["targets"]) == len(p["strategy"]["targets"])
    changed = client.post(path + "/stage-revision", {"expected_revision_id": p["revision_id"], "stage_id": row["id"], "expected_stage_revision": row["revision"], "raw": {**row["raw"], "quantity_shares": 2000}})
    assert changed.status_code == 200, changed.body
    assert changed.body["raw"]["quantity_shares"] == 2000
    clock["now"] += timedelta(seconds=1)
    removed = client.request("DELETE", path, body={"expected_revision_id": p["revision_id"]})
    assert removed.status_code == 200
    assert client.get(PREFIX + "/ai", market=market).body["items"] == []
    with Session(engine) as db:
        with pytest.raises(ValueError, match="PROPOSAL_DELETED"):
            CandidateService(db, clock=lambda: clock["now"])._research_order_current(row["raw"])


def test_ai_scope_excludes_user_proposals_and_reversed_thesis_gets_new_risk_baseline(api):
    client, clock, _ = api
    personal = client.post(PREFIX, creation_body(workflow_origin="USER_NOMINATION")).body["proposal"]
    assert client.get(PREFIX + "/ai/" + personal["creation_id"]).status_code == 403
    assert client.get(PREFIX + "/ai").body["items"] == []
    p = client.post(PREFIX + "/ai", creation_body()).body["proposal"]
    clock["now"] += timedelta(seconds=1)
    request = revision_body(p)
    request["strategy"].update(direction=-1, entry_price=100, stop_price=105, targets=[{"price": 90, "fraction": 1}])
    result = client.post(PREFIX + "/ai/" + p["creation_id"] + "/revisions", request)
    assert result.status_code == 200, result.body
    assert result.body["proposal"]["creation_id"] != p["creation_id"]
    assert result.body["workflow_origin"] == "AI_NOMINATION"
    assert client.get(PREFIX + "/ai/" + p["creation_id"]).status_code == 410


def test_backend_single_submit_cli_reaches_existing_native_owner(setup):
    raw = {"client_intent_id": "protected-desk", "symbol": "TEST", "action": "Buy", "condition": "CASH",
        "lot": "Odd", "quantity_shares": 10, "price": "100", "protection": {
        "stop_loss": "95", "take_profit": "120", "exit_limit_price": "95", "enabled": True,
        "targets": [{"price": "110", "limit_price": "110", "fraction": "0.5"}, {"price": "120", "limit_price": "120", "fraction": "0.5"}]}}
    row = invoke(setup, "create", raw, owner_id="MCP", manual_stage=True)
    with setup[0]() as db:
        service = setup[1](db)
        original_control = service.control
        def control(value):
            result = original_control(value)
            return {**result, "session_date_matches": True} if value["operation"] == "status" else result
        service.control = control
        sent = service.send_staged(row["id"], expected_revision=row["revision"], expected_digest=row["digest"])
    assert sent["lifecycle"] == "SUBMITTED"
    calls = setup[4]
    commands = [call["request"]["argv"][0] for call in calls if call["operation"] == "command"]
    assert commands == ["desk-submit"]
    assert len(setup[3].broker.attempts) == 1
    execution = sent["manual_stage"]["submission"]["receipt"]["execution"]
    protection = setup[2].desk_order("TW", execution["execution_id"])["protection"]
    assert protection["rules"]["enabled"] is True
    assert len(protection["rules"]["targets"]) == 2
