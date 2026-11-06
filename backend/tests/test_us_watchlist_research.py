"""US research acceptance on isolated SQLite and synthetic qualified evidence.

Qualified fixtures are not live corporate-action coverage acceptance.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import math
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs import us_watchlist_research as scans
from app.research import trade_journal as journal, trade_journal_http_service as http
from app.research.market_policy import frozen_sessions, session_close
from app.research.stock_nomination import StockNomination, create_nominations
from app.research.trade_proposal import EvidenceItem, PaperBar, PaperCosts, ProposalEvidence, canonical_json
from app.us_market import watchlist_research as us
from app.us_market.research_math import evaluate_us_strategy
from app.market_data.contracts import Market, InstrumentKey, InstrumentType, BarFinalization
from test_research_trade_journal import engine, evidence, strategy, costs, create, DECISION
from test_research_trade_journal_http import api, PREFIX, creation_body

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
DAY = date(2026, 11, 4)


def qualified_evidence():
    days = []
    day = DAY
    while len(days) < 260:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    bars = []
    for index, day in enumerate(reversed(days)):
        close = 100 + (10 + index / 60) * math.sin(index * math.pi / 10)
        stamp = session_close("US", day) + timedelta(hours=5)
        bars.append(PaperBar(market="US", symbol="NVDA", trade_date=day, open_price=close - 0.3,
            high_price=close + 2, low_price=close - 2, close_price=close, source_ref="fixture:canonical",
            data_revision=f"r-{index}", source_available_at=stamp, received_at=stamp,
            price_basis="raw", corporate_action="clear").model_dump(mode="json"))
    # Close between established support and resistance, with two confirmed targets per side.
    bars[-1].update(open_price=100, close_price=100, high_price=102, low_price=98)
    return {"reason_codes": [], "bars": bars, "identity": {"market": "US", "symbol": "NVDA", "venue": "NASDAQ"},
            "research": {"technical_indicators": {"quality": {"decision_usable": True}},
                         "corporate_action_coverage": {"status": "complete"}}}


@pytest.fixture
def qualified(monkeypatch):
    item = qualified_evidence()
    monkeypatch.setattr(us, "utc_now", lambda: NOW)
    monkeypatch.setattr(http, "utc_now", lambda: NOW)
    monkeypatch.setattr(us, "list_us_watchlist_symbols", lambda *a, **k: ["NVDA"])
    monkeypatch.setattr(us, "read_evidence", lambda *a, **k: item)
    return item


def nomination(**changes):
    return StockNomination(**{"market": "US", "stock_ids": ("NVDA",), "as_of_trade_date": DAY,
        "requested_at": NOW, "nomination_origin": "OMI_SCREEN", **changes})


def test_us_both_directions_persist_deduplicate_and_do_not_promote(engine, qualified):
    from app.research.trade_journal_http_schemas import ProposalPromote
    with Session(engine) as db:
        first = create_nominations(db, nomination(), automatic=True)
        second = create_nominations(db, nomination(), automatic=True)
        assert len(first["scenarios"]) == 2
        assert all(row["proposal"] is not None for row in first["scenarios"])
        assert all(row["deduplicated"] for row in second["scenarios"])
        for row in first["scenarios"]:
            read = row["proposal"]
            proposal = read["proposal"]
            assert proposal["market"] == "US" and read["currency"] == "USD"
            assert proposal["strategy"]["shares"] == 1
            assert read["promotion_supported"] is False
            assert read["setup_evaluation"]["net_stop_loss"] is None
            assert "market" in proposal["evidence"]
            result = http.promote(db, proposal["creation_id"], ProposalPromote(
                expected_revision_id=proposal["revision_id"], owner_id="fixture"))
            assert result["reason_codes"] == ["US_RESEARCH_PROMOTION_UNSUPPORTED"]
        assert len(db.execute(select(journal.proposal_versions)).all()) == 2


def test_non_watchlist_and_unknown_coverage_never_save(engine, qualified, monkeypatch):
    qualified["reason_codes"] = ["CORPORATE_ACTION_INTERVAL_PROOF_MISSING"]
    with Session(engine) as db:
        blocked = create_nominations(db, nomination(stock_ids=("NVDA", "AAPL")))
        assert len(blocked["scenarios"]) == 4
        assert all(row["proposal"] is None for row in blocked["scenarios"])
        assert blocked["scenarios"][-1]["reason_codes"] == ["US_ENABLED_WATCHLIST_MEMBERSHIP_REQUIRED"]
        assert db.execute(select(journal.proposal_versions)).all() == []


def test_no_setup_is_distinct_from_missing_data(engine, qualified):
    for bar in qualified["bars"]:
        bar.update(open_price=100, close_price=100, high_price=101, low_price=99)
    with Session(engine) as db:
        rows = create_nominations(db, nomination())["scenarios"]
        assert {row["status"] for row in rows} == {"NO_SETUP"}
        assert all(row["proposal"] is None for row in rows)


def test_filters_apply_before_pagination_and_legacy_tw_hash_survives(engine):
    with Session(engine) as db, db.begin():
        tw = create(db)
        for _ in range(22):
            create(db)
        ev = evidence()
        item = EvidenceItem(source_ref=us.SOURCE, source_available_at=ev.items[0].source_available_at,
            received_at=ev.items[0].received_at, data_revision="us-fixture",
            snapshot_json=canonical_json({"request": {"nomination_origin": "OMI_SCREEN"}}))
        saved = journal.create_proposal(db, market="US", symbol="NVDA",
            evidence=ProposalEvidence(market="US", as_of_trade_date=ev.as_of_trade_date, cutoff=ev.cutoff,
                                      price_basis="raw", items=(item,)),
            strategy=strategy(direction=-1, stop_price=105, targets=({"price": 90, "fraction": 1},),
                              qualification_refs=(us.SOURCE,)), costs=costs(), effective_at=DECISION,
            now=DECISION, change_reason="fixture")
    with Session(engine) as db:
        result = journal.list_proposal_heads(db, as_of=NOW, limit=1, offset=0,
                                             market="US", origin="OMI_SCREEN", direction="short")
        assert [row.creation_id for row in result] == [saved.creation_id]
        assert journal.list_proposal_heads(db, as_of=NOW, limit=20, offset=0, market="US", direction="long") == ()
        raw = db.execute(select(journal.proposal_versions).where(journal.proposal_versions.c.revision_id == tw.revision_id)).one()
        assert "market" not in json.loads(raw.payload_json)["evidence"]
        assert journal._decode(raw) == tw


def test_us_calendar_dst_and_outcome_market_boundary(engine):
    assert session_close("US", date(2026, 10, 30)).astimezone(timezone.utc).hour == 20
    assert session_close("US", date(2026, 11, 6)).astimezone(timezone.utc).hour == 21
    anchor = datetime(2026, 11, 5, 23, tzinfo=timezone.utc)
    us_dates, _ = frozen_sessions("US", anchor, 15)
    tw_dates, _ = frozen_sessions("TW", anchor, 15)
    assert us_dates[0] == date(2026, 11, 6) and tw_dates[0] != us_dates[0]
    from app.research.paper_outcome import calculate_paper_outcomes
    with Session(engine) as db, db.begin():
        version = create(db)
    day = version.planned_trade_dates[0]
    bar = PaperBar(market="US", symbol=version.symbol, trade_date=day, open_price=100, high_price=101,
                  low_price=99, close_price=100, source_ref="fixture", data_revision="v1", price_basis="raw",
                  source_available_at=session_close("US", day), received_at=session_close("US", day))
    with pytest.raises(ValueError, match="market does not match"):
        calculate_paper_outcomes(version=version, decision_at=DECISION, outcome_as_of=NOW, bars=(bar,))


def test_us_dollar_math_allows_high_price_shorts_and_keeps_borrow_unknown():
    s = strategy(direction=-1, entry_price=250.1234, stop_price=255.12,
                 targets=({"price": 240.12, "fraction": 1},), shares=3)
    unknown = evaluate_us_strategy(s, PaperCosts(version="unknown"), 10)
    assert Decimal(unknown["gross_risk"]) == Decimal("14.9898")
    assert "short_borrow_per_share_session" in unknown["missing_costs"]
    assert unknown["target_scenarios"][0]["net_rr"] is None
    known = evaluate_us_strategy(s, costs(commission_rate=0, minimum_commission=0,
        sell_tax_rate=0, short_borrow_per_share_session=0.1), 10)
    assert Decimal(known["stop_scenario"]["costs"]["total"]) == 3


def test_us_revision_retains_market_evidence_and_original_risk(engine, qualified, monkeypatch):
    from app.research.trade_journal_http_schemas import ProposalRevise
    from app.research.trade_proposal import ProposalVersion
    with Session(engine) as db:
        saved = create_nominations(db, nomination())["scenarios"][1]["proposal"]["proposal"]
        version = ProposalVersion.model_validate(saved)
        later = NOW + timedelta(hours=1)
        monkeypatch.setattr(http, "utc_now", lambda: later)
        revised = http.revise(db, version.creation_id, ProposalRevise(expected_revision_id=version.revision_id,
            strategy=version.strategy.model_copy(update={"shares": 2}), costs=version.costs, change_reason="Size update"))
        assert revised.proposal.market == "US" and revised.currency == "USD"
        assert revised.proposal.evidence_hash == version.evidence_hash
        assert revised.proposal.initial_risk_amount == version.initial_risk_amount
        assert revised.proposal.planned_trade_dates == frozen_sessions("US", later, 15)[0]


def test_scheduler_continues_only_pending_receipts_and_never_replays_errors(engine, monkeypatch):
    monkeypatch.setattr("app.db.session.SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(scans, "utc_now", lambda: datetime(2026, 11, 4, 22, tzinfo=timezone.utc))
    monkeypatch.setattr(scans.settings, "enable_us_watchlist_research_scheduler", True)
    calls = []
    monkeypatch.setattr(scans, "enqueue_scan", lambda db, request: calls.append(request))
    latest = {"id": 8, "status": "success", "request": {"basis_trade_date": DAY.isoformat()}, "result": {"next_cursor": 1}}
    monkeypatch.setattr(scans, "read_latest", lambda db: {"job": latest})
    scans.run_scheduled_scan()
    assert calls[-1].resume_job_id == 8
    latest["status"] = "error"
    scans.run_scheduled_scan()
    assert len(calls) == 1
    latest.update(status="success", result={"next_cursor": None})
    scans.run_scheduled_scan()
    assert len(calls) == 1
    latest["request"]["basis_trade_date"] = "2026-11-03"
    scans.run_scheduled_scan()
    assert len(calls) == 2 and calls[-1].resume_job_id is None


def test_scan_empty_and_frozen_membership_bounded_resume(engine, qualified, monkeypatch):
    payload = {"symbols": [], "cursor": 0, "basis_trade_date": DAY.isoformat(),
               "requested_at": NOW.isoformat(), "membership_hash": "empty"}
    with Session(engine) as db:
        empty = scans.scan_slice(db, payload, lambda **k: None)
        assert empty["processed_symbols"] == 0 and empty["scenarios"] == []
        assert empty["next_cursor"] is None and empty["provider_calls"] == 0
        monkeypatch.setattr(scans, "MAX_SYMBOLS_PER_SLICE", 1)
        payload.update(symbols=["NVDA", "REMOVED"], membership_hash="frozen")
        first = scans.scan_slice(db, payload, lambda **k: None)
        assert first["next_cursor"] == 1 and first["created"] == 2
        last = scans.scan_slice(db, {**payload, "cursor": 1}, lambda **k: None)
        assert last["processed_symbols"] == 2 and last["next_cursor"] is None
        assert last["data_blocked"] == 2  # Removal does not broaden the frozen scope.


def test_monitor_is_close_only_readonly_and_observation_id_stable(engine, qualified, monkeypatch):
    with Session(engine) as db:
        saved = create_nominations(db, nomination())["scenarios"][0]["proposal"]["proposal"]
        from app.research.trade_proposal import ProposalVersion
        version = ProposalVersion.model_validate(saved).model_copy(update={"calendar_verified": True})
        db.execute(text("PRAGMA query_only=ON"))
        monkeypatch.setattr("app.us_market.trading_calendar.expected_us_daily_price_date",
                            lambda **k: version.planned_trade_dates[0])
        qualified["bars"][-1].update(close_price=version.strategy.entry_price,
                                     trade_date=version.planned_trade_dates[0].isoformat())
        at = NOW + timedelta(days=4)
        first = us.read_monitor(db, version, at)
        second = us.read_monitor(db, version, at + timedelta(minutes=1))
        assert first["status"] == "REVIEWABLE"
        assert first["confirmation_basis"] == "us_completed_daily_close"
        assert first["observation_id"] == second["observation_id"]
        qualified["reason_codes"] = ["STALE"]
        assert us.read_monitor(db, version, at)["status"] == "DATA_UNKNOWN"


def test_http_us_filter_currency_and_no_invalid_market(api):
    client, clock, _ = api
    ev = evidence().model_dump(mode="json")
    ev["market"] = "US"
    response = client.post(PREFIX, creation_body(market="US", symbol="NVDA", evidence=ev))
    assert response.status_code == 201, response.body
    assert response.body["currency"] == "USD" and not response.body["promotion_supported"]
    clock["readonly"] = True
    assert len(client.get(PREFIX, market="US").body["items"]) == 1
    assert client.get(PREFIX, market="TW").body["items"] == []
    assert client.get(PREFIX, market="INVALID").status_code == 422


def test_canonical_receipts_and_corporate_unknown_fail_closed(monkeypatch):
    fixtures = qualified_evidence()
    instrument = InstrumentKey(market=Market.US, symbol="NVDA", instrument_type=InstrumentType.STOCK, venue="NASDAQ")
    canonical = []
    for row in fixtures["bars"]:
        day = date.fromisoformat(row["trade_date"])
        receipt = datetime.fromisoformat(row["received_at"])
        canonical.append(SimpleNamespace(instrument=instrument, interval="1d", price_basis="raw",
            finalization=BarFinalization.FINAL, end_at=session_close("US", day),
            open_price=row["open_price"], high_price=row["high_price"], low_price=row["low_price"], close_price=row["close_price"],
            lineage=SimpleNamespace(received_at=receipt, fetched_at=receipt, content_hash=row["data_revision"],
                raw_receipt_id=None, event_at=session_close("US", day), provider="fixture", source="canonical")))
    projection = {"technical_indicators": {"quality": {"decision_usable": True, "reason_codes": []}},
        "corporate_action_coverage": {"status": "complete"}, "daily_ohlcv": {"bars": fixtures["bars"]}}
    monkeypatch.setattr(us, "build_us_market_research", lambda *a, **k: projection)
    platform = SimpleNamespace(identity=SimpleNamespace(instrument=instrument), result=SimpleNamespace(resolved=SimpleNamespace(bars=canonical)))
    monkeypatch.setattr(us, "USDailyOhlcvPlatform", lambda db: SimpleNamespace(read=lambda **k: platform))
    ready = us.read_evidence(None, "NVDA", DAY, NOW)
    assert ready["reason_codes"] == []
    projection["corporate_action_coverage"] = {"status": "unknown", "reason_codes": ["CORPORATE_ACTION_INTERVAL_PROOF_MISSING"]}
    assert "CORPORATE_ACTION_INTERVAL_PROOF_MISSING" in us.read_evidence(None, "NVDA", DAY, NOW)["reason_codes"]
    canonical[-1].lineage.received_at = NOW + timedelta(seconds=1)
    assert "US_DAILY_IDENTITY_FINALIZATION_OR_RECEIPT_INVALID" in us.read_evidence(None, "NVDA", DAY, NOW)["reason_codes"]


def test_scan_enqueue_and_resume_are_commands_status_get_is_readonly(engine, monkeypatch):
    JobRun.__table__.create(engine)
    monkeypatch.setattr(scans, "utc_now", lambda: NOW)
    monkeypatch.setattr(scans, "list_us_watchlist_symbols", lambda *a, **k: ["NVDA", "AAPL"])
    submitted = []
    monkeypatch.setattr(scans.jobs, "submit_job_task", lambda *a: submitted.append(a))
    with Session(engine) as db:
        queued = scans.enqueue_scan(db, scans.ScanRequest())
        again = scans.enqueue_scan(db, scans.ScanRequest())
        assert queued["id"] == again["id"] and len(submitted) == 1
        job = db.get(JobRun, queued["id"])
        job.status = "success"
        job.result_json = json.dumps({"next_cursor": 1})
        db.commit()
        next_job = scans.enqueue_scan(db, scans.ScanRequest(resume_job_id=job.id))
        assert next_job["request"]["symbols"] == ["NVDA", "AAPL"] and next_job["request"]["cursor"] == 1
        db.rollback()
        db.execute(text("PRAGMA query_only=ON"))
        assert scans.read_latest(db)["job"]["id"] == next_job["id"]
        assert len(submitted) == 2
