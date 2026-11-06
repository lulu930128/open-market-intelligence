"""Deletion is an immutable visibility event, not an evidence purge."""
from datetime import timedelta
import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.research import trade_journal as journal, trade_journal_http_service as service
from app.research.trade_proposal import ProposalVersion
from test_research_trade_journal import engine, DECISION, create as create_version
from test_research_trade_journal_http import api, PREFIX, create, creation_body, revision_body, assert_read_only
from test_us_watchlist_research import qualified, nomination, NOW


@pytest.mark.parametrize("market", ["TW", "US"])
def test_delete_hides_from_list_and_live_reads_but_preserves_point_in_time_history(api, engine, market, monkeypatch):
    client, clock, statements = api
    monkeypatch.setattr("app.research.proposal_monitor.utc_now", lambda: clock["now"])
    body = creation_body()
    body.update(market=market)
    if market == "US":
        body["symbol"] = "NVDA"
        body["evidence"]["market"] = "US"
    response = client.post(PREFIX, body)
    assert response.status_code == 201
    original = response.body["proposal"]
    with Session(engine) as db:
        old_row = db.execute(select(journal.proposal_versions)).one()
    clock["now"] += timedelta(seconds=1)
    path = f"{PREFIX}/{original['creation_id']}"
    intent = {"expected_revision_id": original["revision_id"]}
    removed = client.request("DELETE", path, body=intent)
    assert removed.status_code == 200 and removed.body["status"] == "deleted"
    assert client.request("DELETE", path, body=intent).body == removed.body
    with Session(engine) as db:
        rows = db.execute(select(journal.proposal_versions).order_by(journal.proposal_versions.c.revision)).all()
        assert len(rows) == 2 and rows[0] == old_row
        marker = journal._decode(rows[1])
        assert marker.deleted_at == clock["now"]
        assert marker.evidence_hash == original["evidence_hash"]
        assert marker.effective_at == ProposalVersion.model_validate(original).effective_at
        assert marker.planned_trade_dates == ProposalVersion.model_validate(original).planned_trade_dates
        assert "deleted_at" not in json.loads(rows[0].payload_json)
    assert client.post(path + "/revisions", revision_body(original)).status_code == 410
    assert client.post(path + "/promote", {**intent, "owner_id": "fixture"}).status_code == 410
    clock["readonly"] = True
    statements.clear()
    assert client.get(PREFIX, market=market).body["items"] == []
    for suffix in ("", "/revisions", "/monitor"):
        response = client.get(path + suffix)
        assert response.status_code == 410 and response.body["detail"]["code"] == "PROPOSAL_DELETED"
    historical = client.get(path, decision_at=DECISION.isoformat())
    assert historical.body["proposal"] == original
    assert len(client.get(path + "/revisions", as_of=DECISION.isoformat()).body["revisions"]) == 1
    assert_read_only(statements)


def test_delete_filter_is_applied_after_head_selection_before_pagination(api):
    client, clock, _ = api
    proposals = [create(api) for _ in range(21)]
    clock["now"] += timedelta(seconds=1)
    removed = proposals[10]
    assert client.request("DELETE", f"{PREFIX}/{removed['creation_id']}",
        body={"expected_revision_id": removed["revision_id"]}).status_code == 200
    page = client.get(PREFIX, market="TW", limit=20).body
    assert len(page["items"]) == 20 and page["has_more"] is False
    assert removed["creation_id"] not in {row["proposal"]["creation_id"] for row in page["items"]}


@pytest.mark.parametrize("scheduled,age", [(True, 1), (False, 60 * 86400)])
def test_delete_scheduled_and_expired_proposals_does_not_rebase_calendar(api, scheduled, age):
    client, clock, _ = api
    original = create(api, effective_at=(DECISION + timedelta(days=1) if scheduled else DECISION).isoformat())
    clock["now"] += timedelta(seconds=age)
    response = client.request("DELETE", f"{PREFIX}/{original['creation_id']}",
        body={"expected_revision_id": original["revision_id"]})
    assert response.status_code == 200, response.body
    assert client.get(PREFIX).body["items"] == []
    assert client.get(f"{PREFIX}/{original['creation_id']}").status_code == 410


def test_stale_delete_invalid_input_and_missing_identity_are_predictable(api, engine):
    client, clock, _ = api
    original = create(api)
    path = f"{PREFIX}/{original['creation_id']}"
    clock["now"] += timedelta(seconds=1)
    revised = client.post(path + "/revisions", revision_body(original))
    assert revised.status_code == 201
    assert client.request("DELETE", path, body={"expected_revision_id": original["revision_id"]}).status_code == 409
    assert client.request("DELETE", path, body={}).status_code == 422
    assert client.request("DELETE", PREFIX + "/missing", body={"expected_revision_id": "missing"}).status_code == 404
    with Session(engine) as db:
        assert len(journal.list_versions(db, creation_id=original["creation_id"], as_of=clock["now"])) == 2
    assert len(client.get(PREFIX).body["items"]) == 1


def test_delete_rollback_and_database_conflict_preserve_evidence(engine):
    with Session(engine) as db, db.begin():
        original = create_version(db)
    now = DECISION + timedelta(days=40)
    with Session(engine) as db:
        with pytest.raises(RuntimeError, match="fixture rollback"):
            with db.begin():
                journal.delete_proposal(db, creation_id=original.creation_id,
                    expected_revision_id=original.revision_id, now=now)
                raise RuntimeError("fixture rollback")
        with db.begin():
            assert journal.proposal_at(db, creation_id=original.creation_id, decision_at=now) == original
            marker = journal.delete_proposal(db, creation_id=original.creation_id,
                expected_revision_id=original.revision_id, now=now)
        with pytest.raises(IntegrityError, match="immutable"):
            with db.begin():
                # A competing append cannot supersede the same immutable head.
                journal._insert(db, marker.model_copy(update={"revision_id": "competing-revision"}))
        with db.begin(), pytest.raises(journal.ProposalDeletedError):
            journal.revise_proposal(db, creation_id=original.creation_id,
                expected_revision_id=marker.revision_id, strategy=original.strategy, costs=original.costs,
                effective_at=now + timedelta(seconds=1), now=now, change_reason="Must not resurrect")


def test_us_automatic_scan_never_recreates_deleted_candidate(engine, qualified):
    from app.research.stock_nomination import create_nominations
    with Session(engine) as db:
        first = create_nominations(db, nomination(), automatic=True)
        proposal = first["scenarios"][0]["proposal"]["proposal"]
        service.delete(db, proposal["creation_id"], service.ProposalDelete(expected_revision_id=proposal["revision_id"]))
        again = create_nominations(db, nomination(), automatic=True)
        assert again["scenarios"][0]["status"] == "DELETED"
        assert again["scenarios"][0]["proposal"] is None
        assert again["scenarios"][1]["deduplicated"] is True
        assert len(journal.list_proposal_heads(db, as_of=NOW, limit=20, offset=0, market="US")) == 1


def test_tw_automatic_scan_never_recreates_deleted_candidate(engine, monkeypatch):
    from app.research import stock_nomination as nominations
    from app.market.tw_trade_eligibility import EligibilityEvidence
    from test_tw_swing_screening import _evidence, CUTOFF, REQUESTED_AT
    now = REQUESTED_AT + timedelta(hours=1)
    monkeypatch.setattr(nominations, "utc_now", lambda: now)
    monkeypatch.setattr(service, "utc_now", lambda: now)
    item = _evidence("2330")
    zones = item.price_map.payload["zones"]
    extra = [{**zones[0], "zone_id": "support2", "lower_bound": 97, "upper_bound": 98},
             {**zones[1], "zone_id": "resistance2", "lower_bound": 102, "upper_bound": 103}]
    item = item.model_copy(update={"price_map": item.price_map.model_copy(update={
        "payload": {**item.price_map.payload, "zones": [*zones, *extra]}})})
    monkeypatch.setattr(nominations, "read_tw_swing_evidence", lambda *a, **kw: (item,))
    monkeypatch.setattr(nominations, "read_tw_trade_eligibility_evidence",
        lambda request, db: EligibilityEvidence(stock_id=request.stock_id, market=request.market))
    request = nominations.StockNomination(stock_ids=("2330",), direction="long", as_of_trade_date=CUTOFF,
        requested_at=REQUESTED_AT, nomination_origin="OMI_SCREEN")
    with Session(engine) as db:
        first = nominations.create_nominations(db, request, automatic=True)
        saved = first["scenarios"][0]["proposal"]["proposal"]
        service.delete(db, saved["creation_id"], service.ProposalDelete(expected_revision_id=saved["revision_id"]))
        again = nominations.create_nominations(db, request, automatic=True)
        assert again["scenarios"][0]["status"] == "DELETED" and again["scenarios"][0]["proposal"] is None
        assert journal.list_proposal_heads(db, as_of=now, limit=20, offset=0) == ()
