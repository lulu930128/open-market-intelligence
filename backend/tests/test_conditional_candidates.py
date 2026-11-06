"""G0-G4 isolated Research/Native integration; never uses the real control client."""
from dataclasses import replace
from datetime import timedelta
import importlib.util
from pathlib import Path
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.research import candidate_store as store
from app.research.conditional_candidate import CandidateSpec, Evidence, Group, Truth, evaluate, metrics, validate_raw
from app.research.candidate_evidence import MarketEvidence, order_qualification
from app.research.candidate_service import CandidateService
from app.research.candidate_control import ControlUnavailable
from execution_runtime.application import ExecutionApplication
from execution_runtime.headless import dispatch
from execution_runtime.runtime import ExecutionRuntime
from execution_runtime.strategy import SourceSnapshot
from execution_runtime.tests.fake_sdk import ACCOUNT, DAY, NOW, FakeSession


def raw(**changes):
    return {"symbol": "2330", "direction": "long", "action": "Buy", "condition": "CASH",
        "lot": "Odd", "quantity": 1, "valid_from_date": DAY, "valid_until_date": "2026-11-02",
        "hold_overnight": True, "conditions": {"kind": "AND", "clauses": [
            {"kind": "compare", "metric": {"kind": "price", "field": "last_trade", "timeframe": "snapshot"}, "operator": "<", "value": "2180"},
            {"kind": "compare", "metric": {"kind": "rsi", "field": "value", "timeframe": "1d", "parameters": [14]}, "operator": "<=", "value": "1"},
            {"kind": "compare", "metric": {"kind": "macd", "field": "histogram", "timeframe": "1d", "parameters": [12, 26, 9]}, "operator": ">=", "value": "9999"}]}, **changes}


def evidence(spec, *, prices=("2175", "0.5", "10000"), now=NOW, price="100", day=DAY):
    values = {}
    for metric, value in zip(metrics(spec.conditions), prices):
        if value is None:
            continue
        values[metric.key] = Evidence(value=value, source="isolated-fixture", source_at=now-timedelta(seconds=1),
            received_at=now, available_at=now, valid_until=now+timedelta(seconds=30), revision="fixture-v1",
            quality="usable", completed=metric.kind != "price", timeframe=metric.timeframe,
            parameters=metric.parameters, algorithm_version="fixture-v1" if metric.kind != "price" else None)
    return MarketEvidence(values, price, {"basis": "support", "source": "isolated-fixture"}, day,
                          "80", "2300", {"source": "isolated-fixture"})


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261030_0095_conditional_candidates.py"
    spec = importlib.util.spec_from_file_location("candidate_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def setup(tmp_path, request):
    engine = create_engine("sqlite:///" + (tmp_path / "research.sqlite").as_posix())
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration().upgrade()
    factory = sessionmaker(engine)
    sdk = FakeSession()
    runtime = ExecutionRuntime(tmp_path / "execution.sqlite", account_id=ACCOUNT, trade_date=DAY,
        session_factory=sdk.binding, clock=lambda: NOW,
        strategy_effects=request.node.name == "test_authorized_entry_fill_automatic_limit_exit_no_second_consent")
    runtime.start()
    app = ExecutionApplication(runtime)
    calls = []
    active = {"online": True, "market": None}
    def control(value):
        # A second writer must be admitted during every external IPC call.
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA busy_timeout=50")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        calls.append(value)
        if not active["online"]:
            raise ControlUnavailable("OFFLINE_FIXTURE")
        if value["operation"] == "status":
            return {"broker_session": "CONNECTED", "trade_date": DAY, "strategy_effects": False}
        try:
            return dispatch(app, value["request"], selected_account=ACCOUNT)
        except ValueError as exc:
            raise ControlUnavailable(str(exc)) from exc
    def service(db):
        return CandidateService(db, control=control, clock=lambda: NOW,
            evidence=lambda db, spec, now: active["market"] or evidence(spec, now=now))
    yield factory, service, runtime, sdk, calls, active
    runtime.close()
    engine.dispose()


def invoke(setup, method, *args, **kwargs):
    factory, service, *_ = setup
    with factory() as db:
        return getattr(service(db), method)(*args, **kwargs)


def make_pending(setup, data=None):
    candidate = invoke(setup, "create", data or raw(), owner_id="fixture-owner")
    matched = invoke(setup, "observe", candidate["id"])
    return candidate, matched["pending"]


def no_effects(setup):
    runtime, sdk = setup[2:4]
    assert sdk.broker.attempts == sdk.broker.cancels == []
    with runtime._journal.connection(readonly=True) as con:
        for table in ("intents", "orders", "fills"):
            assert con.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM journal WHERE kind='SUBMIT_CLAIMED'").fetchone()[0] == 0
    assert runtime.verify()


def test_research_revision_promote_existing_candidate_owner(setup, monkeypatch):
    import json
    from fastapi import FastAPI
    from app.db.session import get_db
    from app.research import trade_journal as journal, trade_journal_http_service as service
    from app.research.trade_proposal import EvidenceItem, PaperTarget, content_hash
    from app.routers.research_trade_journal import router
    from test_research_trade_journal import costs, evidence as journal_evidence, migration as journal_migration, strategy
    from test_research_trade_journal_http import OfflineClient, PREFIX

    factory, candidate_owner, *unused = setup
    with factory.kw["bind"].begin() as connection, Operations.context(MigrationContext.configure(connection)):
        journal_migration().upgrade()  # Both real 0094/0095 migrations, isolated DB only.
    monkeypatch.setattr(service, "utc_now", lambda: NOW)
    writes = []
    def owner(db):
        instance = candidate_owner(db)
        original = instance.create
        def create(*args, **kwargs):
            value = original(*args, **kwargs)
            writes.append(value)
            return value
        instance.create = create
        instance.evidence = lambda *args: pytest.fail("Promotion must not read market/provider evidence")
        return instance
    monkeypatch.setattr(service, "CandidateService", owner)
    app = FastAPI()
    app.include_router(router, prefix=PREFIX)
    def fixture_db():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = fixture_db
    client = OfflineClient(app)
    base = journal_evidence()
    snapshot = {"request": {"nomination_origin": "OMI_SCREEN", "horizon_sessions": 10},
        "eligibility": {"request": {"stock_id": "2330", "market": "TWSE", "direction": "long",
            "as_of_trade_date": str(base.as_of_trade_date), "requested_at": base.cutoff.isoformat(),
            "entry_trade_date": DAY, "horizon_sessions": 10, "quantity": 1000, "candidate_research_eligible": True},
            "evidence": {"stock_id": "2330", "market": "TWSE"}}}
    evidence = base.model_copy(update={"items": (*base.items, EvidenceItem(
        source_ref="research.stock_nomination.v1", source_available_at=base.items[0].source_available_at,
        received_at=base.items[0].received_at, data_revision=content_hash(snapshot), snapshot_json=json.dumps(snapshot)))})
    with factory() as db, db.begin():
        proposal = journal.create_proposal(db, symbol="2330", evidence=evidence, costs=costs(),
            strategy=strategy(entry_rule="at_or_below", targets=(PaperTarget(price=110, fraction=.5),
                                                                 PaperTarget(price=115, fraction=.5))),
            now=NOW-timedelta(minutes=2), effective_at=NOW-timedelta(minutes=2), change_reason="fixture research nomination")
    url = f"{PREFIX}/{proposal.creation_id}/promote"
    body = {"expected_revision_id": proposal.revision_id, "owner_id": "fixture-user"}
    response = client.post(url, body)
    assert response.status_code == 200 and response.body["status"] == "PROMOTED"
    candidate = response.body["candidate"]
    assert candidate["created"] and candidate["revision"] == 1 and not response.body["execution_ready"]
    spec = candidate["raw"]
    assert (spec["space_id"], spec["source"], spec["conditions"]["operator"]) == ("AGENT_SPACE", "AGENT_PROPOSAL", "<=")
    assert spec["valid_from_date"] == str(proposal.planned_trade_dates[0])
    assert spec["valid_until_date"] == str(proposal.planned_trade_dates[9])
    link = spec["reference_notes"]["research_proposal"]
    assert link["origin"] == "OMI_SCREEN" and link["revision_id"] == proposal.revision_id
    assert link["proposal_digest"] == content_hash(proposal.model_dump(mode="json"))
    assert link["proposal"] == proposal.model_dump(mode="json")  # Includes TP2, evidence timestamps, cutoff and hashes.
    assert spec["take_profit"] == 110 and link["take_profit_mapping"] == "TP1_FULL_QUANTITY_ONLY"
    assert "TP2_PROVENANCE_ONLY_NOT_ENABLED" in response.body["warnings"]
    with pytest.raises(ValueError, match="RESEARCH_PROVENANCE_IMMUTABLE"):
        invoke(setup, "change", candidate["id"], expected_revision=1, operation="revise", raw={**spec, "reference_notes": {}})
    changed = invoke(setup, "change", candidate["id"], expected_revision=1, operation="revise", raw={**spec, "quantity": 2000})
    repeated = client.post(url, body).body["candidate"]
    assert not repeated["created"] and repeated["id"] == candidate["id"] and repeated["revision"] == 2
    assert repeated["digest"] == changed["digest"] and repeated["raw"]["quantity"] == 2000
    with factory() as db, db.begin():
        revised = journal.revise_proposal(db, creation_id=proposal.creation_id, expected_revision_id=proposal.revision_id,
            strategy=strategy(entry_rule="at_or_above"), costs=costs(),
            now=NOW-timedelta(minutes=1), effective_at=NOW-timedelta(minutes=1), change_reason="fixture explicit trigger revision")
    assert client.post(url, body).status_code == 409
    body["expected_revision_id"] = revised.revision_id
    above = client.post(url, body).body["candidate"]
    assert above["id"] != candidate["id"] and above["revision"] == 1
    assert above["raw"]["conditions"]["operator"] == ">="
    with factory() as db, db.begin():
        confirmed = journal.revise_proposal(db, creation_id=proposal.creation_id, expected_revision_id=revised.revision_id,
            strategy=revised.strategy.model_copy(update={"mode": "confirmed"}), costs=costs(),
            now=NOW, effective_at=NOW, change_reason="fixture unmappable confirmation")
    blocked = client.post(url, {**body, "expected_revision_id": confirmed.revision_id}).body
    assert blocked["status"] == "DATA_BLOCKED" and blocked["candidate"] is None
    assert "COMPLETED_DAILY_CONFIRMATION_NOT_REPRESENTABLE" in blocked["reason_codes"]
    assert len(writes) == 3  # Original owner invoked; repeat returns existing head without a new append.
    with factory() as db:
        adopted_before = store.latest(db, store.candidates)
    deleted = client.request("DELETE", f"{PREFIX}/{proposal.creation_id}",
        body={"expected_revision_id": confirmed.revision_id})
    assert deleted.status_code == 200
    assert client.post(url, {**body, "expected_revision_id": confirmed.revision_id}).status_code == 410
    with factory() as db:
        marker = journal.list_versions(db, creation_id=proposal.creation_id, as_of=NOW)[-1]
    with factory() as db, pytest.raises(ValueError, match="STALE_RESEARCH_REVISION"):
        candidate_owner(db).create(spec, owner_id="fixture-user", research_revision=marker)
    with factory() as db:
        assert store.latest(db, store.candidates) == adopted_before
        assert len(store.history(db, store.candidates, candidate["id"])) == 2
        assert len(store.latest(db, store.candidates)) == 2
        assert store.latest(db, store.pending) == []
    assert setup[4] == []  # No control / prepare / approve / Native call.
    no_effects(setup)


@pytest.mark.parametrize("price,rsi,macd,expected", [
    ("2175", "0.5", "10000", "TRUE"), ("2180", "0.5", "10000", "FALSE"),
    ("2175", "1", "9999", "TRUE"), ("2175", "1.01", "10000", "FALSE"),
    ("2175", "0.5", "9998.99", "FALSE"), ("2175", None, "10000", "UNKNOWN"),
    ("2180", None, "10000", "FALSE")])
def test_b_truth_matrix(price, rsi, macd, expected):
    spec = CandidateSpec.model_validate(raw())
    assert evaluate(spec.conditions, evidence(spec, prices=(price, rsi, macd)).values, NOW).value == expected


@pytest.mark.parametrize("op,value,expected", [("<", "2180", "FALSE"), ("<=", "2180", "TRUE"),
    (">", "2180", "FALSE"), (">=", "2180", "TRUE"), ("==", "2180", "TRUE")])
def test_comparators_and_or_unknown(op, value, expected):
    spec = CandidateSpec.model_validate(raw())
    clause = spec.conditions.clauses[0].model_copy(update={"operator": op})
    values = evidence(spec, prices=(value, None, None)).values
    assert evaluate(clause, values, NOW).value == expected
    group = Group(kind="OR", clauses=(clause, spec.conditions.clauses[1]))
    assert evaluate(group, values, NOW).value == ("TRUE" if expected == "TRUE" else "UNKNOWN")


@pytest.mark.parametrize("change", [{"quality": "stale"}, {"completed": False}, {"parameters": (9,)},
                                    {"available_at": NOW + timedelta(seconds=1)}])
def test_unqualified_daily_unknown(change):
    spec = CandidateSpec.model_validate(raw())
    values = evidence(spec).values
    key = metrics(spec.conditions)[1].key
    values[key] = values[key].model_copy(update=change)
    assert evaluate(spec.conditions, values, NOW) == Truth.UNKNOWN


def test_invalid_a_raw_history_crud_without_executor(setup):
    setup[5]["online"] = False
    data = raw(symbol="3481", direction="short", action="Sell", condition="SHORT_SELLING", lot="Common",
               quantity=1000, reference_entry="50.6", stop_loss="50", take_profit="55",
               valid_from_date=None, valid_until_date=None)
    candidate = invoke(setup, "create", data, owner_id="fixture-owner")
    assert candidate["raw"] == data
    assert {"INCOMPLETE_DATE", "INVALID_LEVEL_DIRECTION"} <= set(candidate["validation_reasons"])
    assert invoke(setup, "observe", candidate["id"])["reason"] == "CANDIDATE_NOT_ACTIVE"
    for revision, operation in enumerate(("pause", "resume", "revise", "cancel"), 1):
        candidate = invoke(setup, "change", candidate["id"], expected_revision=revision,
                           operation=operation, **({"raw": data} if operation == "revise" else {}))
    assert invoke(setup, "get", candidate["id"])["lifecycle"] == "CANCELLED"
    assert len(invoke(setup, "history", candidate["id"])) == 5
    assert setup[4] == []
    no_effects(setup)


def test_dates_and_append_only_migration(setup):
    candidate = invoke(setup, "create", raw(valid_from_date="20261029"), owner_id="fixture-owner")
    assert any("valid_from_date" in e for e in candidate["validation_reasons"])
    engine = setup[0].kw["bind"]
    for sql in ("DELETE FROM research_candidate_revision", "UPDATE research_candidate_revision SET revision=8",
                "INSERT OR REPLACE INTO research_candidate_revision SELECT * FROM research_candidate_revision"):
        with pytest.raises(Exception, match="immutable"):
            with engine.begin() as con:
                con.execute(text(sql))
    with pytest.raises(RuntimeError, match="retention"):
        with engine.begin() as con, Operations.context(MigrationContext.configure(con)):
            migration().downgrade()
    no_effects(setup)


def test_match_restart_duplicate_ticks_and_overnight(setup):
    candidate, pending = make_pending(setup)
    for _ in range(4):
        assert invoke(setup, "observe", candidate["id"])["pending"] == pending
    assert len(invoke(setup, "pending", candidate["id"])) == 1
    with setup[0]() as db:
        assert len(store.history(db, store.pending, pending["id"])) == 1
        db.rollback()
        service = setup[1](db)
        service.clock = lambda: NOW + timedelta(days=1)
        following = service.observe(candidate["id"])["pending"]
        assert following["trade_date"] != pending["trade_date"]
        assert following["id"] != pending["id"]
    no_effects(setup)


def test_offline_pending_prepare_revision_reject_reopen(setup):
    setup[5]["online"] = False
    candidate, pending = make_pending(setup)
    offline = invoke(setup, "prepare", pending["id"])
    assert offline["executor_status"] == "OFFLINE_OR_UNKNOWN"
    setup[5]["online"] = True
    prepared = invoke(setup, "prepare", pending["id"])
    assert prepared["state"] == "NATIVE_PREVIEW"
    assert not any(c.get("request", {}).get("argv", [None])[0] == "confirm" for c in setup[4])
    app = ExecutionApplication(setup[2])
    link = prepared["native"]
    with pytest.raises(ValueError, match="CANDIDATE_SELECTION_REQUIRED"):
        app.confirm(link["review_id"], expected_revision=1, expected_digest=link["digest"])
    revised = invoke(setup, "revise_pending", pending["id"], expected_revision=prepared["revision"], price="105", quantity=2)
    assert app.status(link["review_id"])["state"] == "REJECTED"
    with pytest.raises(ValueError, match="STALE_PENDING_SELECTION"):
        invoke(setup, "approve", pending["id"], expected_revision=prepared["revision"], expected_digest=prepared["digest"])
    next_preview = invoke(setup, "prepare", revised["id"])
    assert next_preview["native"]["digest"] != link["digest"]
    cancelled = invoke(setup, "cancel_pending", pending["id"], expected_revision=next_preview["revision"])
    assert cancelled["state"] == "CANCELLED"
    assert app.status(next_preview["native"]["review_id"])["state"] == "REJECTED"
    no_effects(setup)


def test_ipc_failure_retains_invalidation_and_never_blocks_db(setup):
    candidate, pending = make_pending(setup)
    prepared = invoke(setup, "prepare", pending["id"])
    setup[5]["online"] = False
    changed = invoke(setup, "change", candidate["id"], expected_revision=1, operation="cancel")
    assert changed["state"] == "CANCELLED"
    records = invoke(setup, "pending", candidate["id"])
    assert records[0]["native_invalidation"] == "PENDING_EXECUTOR"
    setup[5]["online"] = True
    invoke(setup, "drain_invalidations", candidate["id"])
    assert ExecutionApplication(setup[2]).status(prepared["native"]["review_id"])["state"] == "REJECTED"
    no_effects(setup)


def test_qualification_preopen_odd_tick_limits_and_unknown_borrow():
    spec = CandidateSpec.model_validate(raw(lot="Common", quantity=1000))
    preopen = NOW.replace(hour=0, minute=45)
    market = evidence(spec, now=preopen)
    common = order_qualification(spec, "100", market, preopen)
    assert common["send_ready"] and common["order_accepting"] and not common["matching_window"]
    odd = order_qualification(spec.model_copy(update={"lot": "Odd", "quantity": 1}), "100", market, preopen)
    assert not odd["send_ready"] and not odd["order_accepting"]
    assert "OUTSIDE_DAILY_PRICE_LIMITS" in order_qualification(spec, "3000", market, NOW)["reasons"]
    assert "INVALID_PRICE_TICK" in order_qualification(spec, "100.1", market, NOW)["reasons"]
    assert "DAILY_PRICE_LIMITS_UNKNOWN" in order_qualification(spec, "100", replace(market, trade_date="2026-10-28"), NOW)["reasons"]
    short = spec.model_copy(update={"direction": "short", "condition": "SHORT_SELLING", "action": "Sell"})
    assert "BORROW_UNKNOWN" in order_qualification(short, "100", market, NOW)["reasons"]


def test_monitor_offline_restart_no_repeat_pending(setup):
    from app.jobs.candidate_monitor import run_cycle
    setup[5]["online"] = False
    candidate = invoke(setup, "create", raw(), owner_id="fixture-owner")
    for _ in range(3):
        result = run_cycle(setup[0], setup[1])
        assert result["state"] == "RUNNING" and result["errors"] == 0
    assert len(invoke(setup, "pending", candidate["id"])) == 1
    no_effects(setup)


def test_authorized_entry_fill_automatic_limit_exit_no_second_consent(setup):
    # Separate effects fixture, never production: one Entry and one authorized Exit.
    runtime, sdk = setup[2:4]
    candidate, pending = make_pending(setup, raw(reference_entry="100", stop_loss="95", take_profit="110", exit_limit_price="94"))
    preview = invoke(setup, "prepare", pending["id"])
    selected = invoke(setup, "approve", pending["id"], expected_revision=preview["revision"], expected_digest=preview["digest"])
    assert selected["state"] == "SELECTED"
    assert len(sdk.broker.attempts) == 1
    receipt = selected["execution_receipt"]
    sid = receipt["draft"]["command"]["strategy_id"]
    app = ExecutionApplication(runtime)
    strategy = app.strategy_status(sid)
    entry_id = strategy["entry_execution_id"]
    sdk.event(sdk.broker.fill(strategy["entry"]["broker_order_id"], 1, "fixture-entry-fill", price="100"))
    app.observe_strategy_price(sid, SourceSnapshot("fixture-stop", NOW.isoformat(), {"isolated": True}),
        request_id="fixture-stop", expected_revision=1, symbol="2330", price="95")
    assert runtime._strategy_idle.wait(10)
    assert runtime.strategy_error is None
    assert len(sdk.broker.attempts) == 2
    assert sdk.broker.attempts[-1]["action"] == "Sell" and sdk.broker.attempts[-1]["price"] == 94
    assert sdk.broker.attempts[-1]["time_in_force"] == "ROD"
    final = app.strategy_status(sid)
    assert final["entry_execution_id"] == entry_id and final["exits"][0]["quantity"] == 1
    assert final["effective_position"] == 1  # Exit sent is NOT a fill.
    assert sum(c.get("request", {}).get("argv", [None])[0] == "confirm" for c in setup[4]) == 1
    assert runtime.verify()


def test_prepare_reply_racing_candidate_revision_rejects_orphan(setup):
    candidate, pending = make_pending(setup)
    factory, builder = setup[:2]
    with factory() as db:
        service = builder(db)
        original = service.control
        def racing_control(value):
            response = original(value)
            if value.get("request", {}).get("argv", [None])[0] == "candidate-prepare":
                invoke(setup, "change", candidate["id"], expected_revision=1, operation="pause")
            return response
        service.control = racing_control
        result = service.prepare(pending["id"])
    assert result["state"] == "STALE"
    reviews = ExecutionApplication(setup[2]).list()
    assert len(reviews) == 1 and reviews[0]["state"] == "REJECTED"
    no_effects(setup)


@pytest.mark.parametrize("operation", ["revise", "pause", "cancel"])
def test_evaluation_outside_writer_and_rechecks_candidate_head(setup, operation):
    candidate = invoke(setup, "create", raw(), owner_id="fixture-owner")
    with setup[0]() as db:
        service = setup[1](db)
        def concurrent_evidence(reader, spec, now):
            assert not db.in_transaction()
            invoke(setup, "change", candidate["id"], expected_revision=1, operation=operation,
                   **({"raw": raw(quantity=2)} if operation == "revise" else {}))
            return evidence(spec, now=now)
        service.evidence = concurrent_evidence
        result = service.observe(candidate["id"])
    assert result["reason"] == "CANDIDATE_CHANGED_DURING_EVALUATION"
    assert invoke(setup, "pending", candidate["id"]) == []
    no_effects(setup)


def test_lost_confirm_response_is_never_replayed(setup):
    candidate, pending = make_pending(setup)
    preview = invoke(setup, "prepare", pending["id"])
    setup[5]["online"] = False
    result = invoke(setup, "approve", pending["id"], expected_revision=preview["revision"], expected_digest=preview["digest"])
    assert result["state"] == "SELECTION_UNKNOWN"
    setup[5]["online"] = True
    assert invoke(setup, "observe", candidate["id"])["reason"] == "ENTRY_ALREADY_SELECTED"
    with pytest.raises(ValueError):
        invoke(setup, "approve", pending["id"], expected_revision=result["revision"], expected_digest=result["digest"])
    no_effects(setup)


def test_canonical_limits_mapping_with_receipt_and_missing_bounds():
    from app.market.providers.tw_public_quote import quote_observation_from_twse_mis
    from app.market_data.contracts import InstrumentKey, InstrumentType, Market, MarketSession
    instrument = InstrumentKey(market=Market.TW, symbol="2330", venue="TWSE", instrument_type=InstrumentType.STOCK)
    message = dict(c="2330", d="20261029", t="10:00:00", z="100", tv="1", v="1", ts="0", u="110", w="90")
    def convert(data):
        return quote_observation_from_twse_mis(instrument=instrument, message=data,
            session=MarketSession.CONTINUOUS, received_at=NOW, fetched_at=NOW, content_hash="fixture-hash")
    quote = convert(message)
    assert str(quote.price_limits.upper) == "110" and str(quote.price_limits.lower) == "90"
    assert quote.price_limits.trade_date.isoformat() == DAY
    assert quote.price_limits.lineage.received_at == NOW
    assert quote.price_limits.lineage.content_hash == "fixture-hash"
    assert convert({**message, "u": "-"}).price_limits is None
    assert convert({**message, "w": "120"}).price_limits is None


def test_reader_uses_canonical_technical_parameters_and_real_typed_bars():
    from types import SimpleNamespace as NS
    from test_tw_technical_service import _series
    from app.market.technical_parameters import get_technical_analysis_parameters
    from app.research.candidate_evidence import read_market_evidence
    series = _series()
    day = series.bars[-1].start_at.date()
    now = series.bars[-1].end_at + timedelta(hours=10)
    empty = NS(resolved=NS(quote=None, depth=None, auction=None))
    bundle = NS(quote=empty, depth=empty, auction=empty)
    parameters = get_technical_analysis_parameters(persisted_settings={})
    with patch('app.market.taiwan_quote_evidence.read_taiwan_quote_evidence_bundle', return_value=bundle), \
         patch('app.market.tw_bar_service.TaiwanBarService.read_bars', return_value=series) as read, \
         patch('app.market.technical_parameters.get_technical_analysis_parameters', return_value=parameters), \
         patch('app.market.taiwan_rules.expected_daily_price_date', return_value=day):
        spec = CandidateSpec.model_validate(raw())
        value = read_market_evidence(None, spec, now)
    assert read.call_args.kwargs['include_partial'] is False
    assert read.call_args.kwargs['interval'] == '1d'
    rsi, macd = [value.values[m.key] for m in metrics(spec.conditions)[1:]]
    assert rsi.parameters == (14,) and macd.parameters == (12, 26, 9)
    assert rsi.completed and rsi.algorithm_version and rsi.received_at == series.bars[-1].lineage.received_at
    assert value.proposed_limit is not None and value.price_evidence['basis'] == 'support'


def test_missing_price_remains_pending_then_technical_level_arrives(setup):
    spec = CandidateSpec.model_validate(raw())
    setup[5]['market'] = evidence(spec, price=None)
    candidate, pending = make_pending(setup)
    assert 'WAITING_PRICE' in pending['qualification']['reasons']
    assert invoke(setup, 'prepare', pending['id'])['native'] is None
    setup[5]['market'] = evidence(spec, price='100')
    observed = invoke(setup, 'observe', candidate['id'])
    assert observed['pending']['price'] == '100' and not observed['created']
    assert invoke(setup, 'prepare', pending['id'])['state'] == 'NATIVE_PREVIEW'
    no_effects(setup)


def test_far_price_candidate_persists_without_native_preview(setup):
    spec = CandidateSpec.model_validate(raw())
    setup[5]['market'] = evidence(spec, price='3000')
    candidate, pending = make_pending(setup)
    assert candidate['lifecycle'] == 'ACTIVE'
    assert pending['price'] == '3000' and 'OUTSIDE_DAILY_PRICE_LIMITS' in pending['qualification']['reasons']
    assert invoke(setup, 'prepare', pending['id'])['native'] is None
    assert not setup[4]
    no_effects(setup)


def test_native_candidate_binding_survives_reopen_without_send(setup):
    _, pending = make_pending(setup)
    preview = invoke(setup, 'prepare', pending['id'])
    runtime = setup[2]
    previous = ExecutionApplication(runtime).status(preview['native']['review_id'])
    runtime.close()
    runtime.start()
    assert ExecutionApplication(runtime).status(preview['native']['review_id']) == previous
    with pytest.raises(ValueError, match='CANDIDATE_SELECTION_REQUIRED'):
        ExecutionApplication(runtime).confirm(preview['native']['review_id'], expected_revision=1,
                                              expected_digest=preview['native']['digest'])
    no_effects(setup)


def test_http_crud_and_reads_never_prepare_or_confirm(setup):
    from fastapi import FastAPI
    from test_research_trade_journal_http import OfflineClient
    from app.routers import conditional_candidates as api
    app = FastAPI()
    app.include_router(api.router, prefix='/candidates')
    def session():
        with setup[0]() as db:
            yield db
    app.dependency_overrides[api.get_db] = session
    client = OfflineClient(app)
    with patch.object(api, 'CandidateService', setup[1]):
        response = client.post('/candidates', {'raw': raw(), 'owner_id': 'fixture-owner'})
        assert response.status_code == 201
        candidate = response.body
        for path in ('/candidates', '/candidates/' + candidate['id'], '/candidates/' + candidate['id'] + '/pending'):
            assert client.get(path).status_code == 200
        assert client.post('/candidates/' + candidate['id'] + '/pause', {'expected_revision': 1}).status_code == 200
        stale = client.post('/candidates/' + candidate['id'] + '/cancel', {'expected_revision': 1})
        assert stale.status_code == 409 and stale.body['detail']['code'] == 'STALE_CANDIDATE_REVISION'
        assert client.post('/candidates/' + candidate['id'] + '/cancel', {'expected_revision': 2}).status_code == 200
    assert not setup[4]
    no_effects(setup)


@pytest.fixture
def special_candidate_setup(setup, monkeypatch, record_property):
    """2026-10-30 research-only cases; fail on any executor or effect call."""
    from unittest.mock import Mock

    now = NOW.replace(day=30)
    active = setup[5]
    blocked = Mock(side_effect=AssertionError("SPECIAL_CANDIDATE_NO_EXECUTOR_CALLS"))
    for owner, name in ((CandidateService, "approve"), (ExecutionApplication, "confirm"),
                        (ExecutionRuntime, "submit"), (ExecutionRuntime, "cancel"),
                        (setup[3], "create_order"), (setup[3], "cancel_order"),
                        (setup[3].broker, "fill")):
        monkeypatch.setattr(owner, name, blocked)

    def service(db):
        return CandidateService(db, control=blocked, clock=lambda: now,
            evidence=lambda db, spec, clock: active["market"] or evidence(
                spec, now=clock, day="2026-10-30", price="2160"))

    isolated = (setup[0], service, *setup[2:])
    yield isolated
    blocked.assert_not_called()
    assert setup[4] == []
    assert ExecutionApplication(setup[2]).list() == []
    no_effects(setup)
    record_property("no_effects", {"control_calls": 0, "native_reviews": 0,
        "approve_confirm_submit_cancel_order_calls": 0, "intents": 0, "orders": 0,
        "fills": 0, "submit_claims": 0, "sdk_attempts": 0, "sdk_cancels": 0,
        "fake_fill_calls": 0, "evidence_source": "isolated-fixture"})


@pytest.mark.parametrize("prices,daily_change,expected", [
    (("2175", "1", "9999"), None, "TRUE"),
    (("2180", "1", "9999"), None, "FALSE"),
    (("2175", "1.01", "9999"), None, "FALSE"),
    (("2175", "1", "9998.99"), None, "FALSE"),
    (("2180", None, "9999"), None, "FALSE"),
    (("2175", None, "9999"), None, "UNKNOWN"),
    (("2175", "1", None), None, "UNKNOWN"),
    (("2175", "1", "9999"), {"completed": False}, "UNKNOWN"),
    (("2175", "1", "9999"), {"quality": "stale"}, "UNKNOWN"),
])
def test_special_2330_service_truth(special_candidate_setup, prices, daily_change, expected, record_property):
    setup = special_candidate_setup
    data = raw(space_id="AGENT_SPACE", source="AGENT_PROPOSAL", valid_from_date="2026-10-30")
    spec = CandidateSpec.model_validate(data)
    market = evidence(spec, prices=prices, now=NOW.replace(day=30), day="2026-10-30", price="2160")
    if daily_change:
        key = metrics(spec.conditions)[1].key
        market.values[key] = market.values[key].model_copy(update=daily_change)
    setup[5]["market"] = market
    candidate = invoke(setup, "create", data, owner_id="fixture-owner")
    assert candidate["validation_reasons"] == []
    assert candidate["spec"]["space_id"] == "AGENT_SPACE"
    assert candidate["spec"]["source"] == "AGENT_PROPOSAL"
    assert (candidate["spec"]["lot"], candidate["spec"]["quantity"]) == ("Odd", 1)
    assert candidate["raw"]["conditions"] == data["conditions"]
    result = invoke(setup, "observe", candidate["id"])
    assert result["truth"] == expected
    pending = invoke(setup, "pending", candidate["id"])
    if expected == "TRUE":
        assert len(pending) == 1 and result["created"] is True
        assert pending[0]["state"] == "PENDING_APPROVAL" and pending[0]["native"] is None
        assert pending[0]["price"] == "2160"  # Fixture support, not the fixed 2180 trigger.
        assert invoke(setup, "observe", candidate["id"])["created"] is False
    else:
        assert pending == [] and result["reason"] == "NO_MATCH"
    record_property("case_result", {"symbol": "2330", "prices_rsi_macd": prices,
        "daily_change": daily_change, "truth": result["truth"], "pending_count": len(pending)})


def test_special_2330_candidate_and_pending_crud(special_candidate_setup, record_property):
    setup = special_candidate_setup
    data = raw(space_id="AGENT_SPACE", source="AGENT_PROPOSAL", valid_from_date="2026-10-30")
    candidate, pending = make_pending(setup, data)
    edited = invoke(setup, "revise_pending", pending["id"], expected_revision=1, price="2155", quantity=1)
    assert edited["price"] == "2155" and edited["quantity"] == 1
    assert edited["revision"] > pending["revision"] and edited["digest"] != pending["digest"]
    assert edited["native"] is None
    cancelled = invoke(setup, "cancel_pending", pending["id"], expected_revision=edited["revision"])
    assert cancelled["state"] == "CANCELLED"
    assert invoke(setup, "observe", candidate["id"])["created"] is False
    changed_raw = {**data, "reference_notes": {"isolated_revision": 2}}
    candidate = invoke(setup, "change", candidate["id"], expected_revision=1, operation="revise", raw=changed_raw)
    next_pending = invoke(setup, "observe", candidate["id"])["pending"]
    assert next_pending["id"] != pending["id"] and next_pending["candidate_revision"] == 2
    candidate = invoke(setup, "change", candidate["id"], expected_revision=2, operation="pause")
    assert candidate["lifecycle"] == "PAUSED"
    assert invoke(setup, "observe", candidate["id"]) == {"truth": "UNKNOWN", "reason": "CANDIDATE_NOT_ACTIVE"}
    candidate = invoke(setup, "change", candidate["id"], expected_revision=3, operation="resume")
    assert candidate["lifecycle"] == "ACTIVE"
    resumed = invoke(setup, "observe", candidate["id"])["pending"]
    assert resumed["id"] != next_pending["id"] and resumed["candidate_revision"] == 4
    invoke(setup, "change", candidate["id"], expected_revision=4, operation="cancel")
    # Each invoke opens a fresh SQLAlchemy Session: re-read persisted revisions, no hard delete.
    assert invoke(setup, "get", candidate["id"])["lifecycle"] == "CANCELLED"
    assert invoke(setup, "list")[0]["id"] == candidate["id"]
    history = invoke(setup, "history", candidate["id"])
    assert [r["event"] for r in history] == ["CREATED", "REVISE", "PAUSE", "RESUME", "CANCEL"]
    assert history[0]["raw"] == data and history[1]["raw"] == changed_raw
    assert all(r["raw"]["conditions"] == data["conditions"] for r in history)
    pending_states = {r["id"]: r["state"] for r in invoke(setup, "pending", candidate["id"])}
    assert pending_states == {pending["id"]: "CANCELLED", next_pending["id"]: "STALE", resumed["id"]: "CANCELLED"}
    with setup[0]() as db:
        assert len(store.history(db, store.pending, pending["id"])) == 4
    record_property("case_result", {"symbol": "2330", "candidate_revisions": 5,
        "pending_identities": 3, "first_pending_revisions": 4, "lifecycle": "CANCELLED",
        "trigger_price_unchanged": "2180", "hard_delete": False})


@pytest.mark.parametrize("exit_limit,limits_known,expected_reasons", [
    ("55", True, ["BORROW_UNKNOWN", "SHORT_COVER_UNVERIFIED"]),
    (None, True, ["BORROW_UNKNOWN", "SHORT_COVER_UNVERIFIED", "EXIT_LIMIT_REQUIRED"]),
    ("55", False, ["DAILY_PRICE_LIMITS_UNKNOWN", "BORROW_UNKNOWN", "SHORT_COVER_UNVERIFIED"]),
])
def test_special_3481_short_semantics_and_blocked_prepare(special_candidate_setup, exit_limit,
                                                        limits_known, expected_reasons, record_property):
    setup = special_candidate_setup
    # Explicit hypothetical bounds only; no assertion about the real 3481 trading range.
    lower_limit, upper_limit = "40", "50.6"
    invalid = raw(symbol="3481", space_id="AGENT_SPACE", source="AGENT_PROPOSAL",
        direction="short", action="Sell", condition="SHORT_SELLING", lot="Common", quantity=1000,
        reference_entry="50.6", stop_loss="50", take_profit="55", exit_limit_price=exit_limit,
        price_basis="explicit", proposed_limit=upper_limit, valid_from_date="2026-10-30",
        conditions={"kind": "compare", "metric": {"kind": "price", "field": "last_trade", "timeframe": "snapshot"},
                    "operator": ">=", "value": upper_limit},
        reference_notes={"bounds": "hypothetical isolated fixture, not verified market data"})
    candidate = invoke(setup, "create", invalid, owner_id="fixture-owner")
    original = candidate
    assert candidate["raw"] == invalid and candidate["lifecycle"] == "DRAFT"
    assert candidate["validation_reasons"] == ["INVALID_LEVEL_DIRECTION"]
    assert invoke(setup, "observe", candidate["id"]) == {"truth": "UNKNOWN", "reason": "CANDIDATE_NOT_ACTIVE"}
    assert invoke(setup, "pending", candidate["id"]) == []

    # A separate, explicit test revision supplies a valid short ordering; never mutate the raw original.
    valid = {**invalid, "stop_loss": "55", "take_profit": "45"}
    candidate = invoke(setup, "change", candidate["id"], expected_revision=1, operation="revise", raw=valid)
    assert candidate["validation_reasons"] == [] and candidate["lifecycle"] == "ACTIVE"
    spec = CandidateSpec.model_validate(valid)
    assert spec.take_profit < spec.proposed_limit < spec.stop_loss
    market = replace(evidence(spec, prices=(upper_limit,), now=NOW.replace(day=30),
                              day="2026-10-30", price=upper_limit),
        price_evidence={"basis": "explicit", "source": "isolated-fixture"},
        lower_limit=lower_limit if limits_known else None, upper_limit=upper_limit if limits_known else None,
        limits_source={"source": "hypothetical-isolated-bounds"} if limits_known else {})
    setup[5]["market"] = market
    observed = invoke(setup, "observe", candidate["id"])
    pending = observed["pending"]
    assert observed["truth"] == "TRUE" and observed["created"] is True
    assert pending["price"] == upper_limit and pending["quantity"] == 1000
    qualified = pending["qualification"]
    assert qualified["reasons"] == expected_reasons
    assert qualified["borrow_status"] == "UNKNOWN" and qualified["fill_status"] == "NOT_SUBMITTED"
    assert qualified["send_ready"] is False
    prepared = invoke(setup, "prepare", pending["id"])
    assert prepared["state"] == "PENDING_APPROVAL" and prepared["native"] is None
    assert prepared["qualification"]["reasons"] == expected_reasons
    assert prepared["revision"] == pending["revision"]  # No remote preparation or claim.
    edited = invoke(setup, "revise_pending", pending["id"], expected_revision=1, price=upper_limit, quantity=1000)
    assert invoke(setup, "prepare", edited["id"])["qualification"]["reasons"] == expected_reasons
    invoke(setup, "cancel_pending", pending["id"], expected_revision=edited["revision"])
    invoke(setup, "change", candidate["id"], expected_revision=2, operation="pause")
    invoke(setup, "change", candidate["id"], expected_revision=3, operation="resume")
    resumed = invoke(setup, "observe", candidate["id"])["pending"]
    assert resumed["id"] != pending["id"] and resumed["native"] is None
    invoke(setup, "change", candidate["id"], expected_revision=4, operation="cancel")
    history = invoke(setup, "history", candidate["id"])
    assert len(history) == 5 and history[0]["raw"] == invalid and history[0]["digest"] == original["digest"]
    assert history[1]["raw"] == valid
    assert invoke(setup, "get", candidate["id"])["lifecycle"] == "CANCELLED"
    assert invoke(setup, "list")[0]["id"] == candidate["id"]
    assert all(p["state"] == "CANCELLED" for p in invoke(setup, "pending", candidate["id"]))
    record_property("case_result", {"symbol": "3481", "hypothetical_limits": [lower_limit, upper_limit],
        "limits_known": limits_known, "raw_invalid_code": "INVALID_LEVEL_DIRECTION",
        "valid_short_levels": {"take_profit": "45", "entry": upper_limit, "stop_loss": "55"},
        "prepare_reasons": expected_reasons, "native_preview": False,
        "candidate_revisions": 5, "lifecycle": "CANCELLED", "hard_delete": False})
