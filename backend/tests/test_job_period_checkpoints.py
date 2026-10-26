"""Offline original-owner/Future/persistence acceptance for period checkpoints."""
import json
from copy import deepcopy
from datetime import date
from threading import Event
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.db import models as m
from app.jobs import backfill_tasks, service, resumption
from app.jobs.cooperative import JobPaused, JobStopToken, checkpoint_after_transaction, current_job_stop
from app.market import backfill
from app.utils.backfill_checkpoint import BackfillProgress, validate_period_state
from r1d_test_support import isolated_job_lifecycle, offline_asyncio  # noqa: F401
from test_job_cooperative_quiescence import make_job, snapshot, wait_idle


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "periods.sqlite").as_posix(), poolclass=NullPool)
    tables = [m.SourceRegistry, m.FetchLog, m.RawFetchResult, m.DataQualityCheck,
              m.MarketDailyPrice, m.StockMaster, m.JobRun, m.MonthlyRevenue,
              m.FinancialMetricQuarterly, m.ShareholdingDistributionWeekly]
    m.Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    monkeypatch.setattr(service, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(service.settings, "job_worker_max_concurrency", 1)
    with Session(engine) as db:
        db.add(m.StockMaster(stock_id="2330", stock_name="fixture", market="TWSE"))
        for name, category, parser in [
            ("TWSE price", "price", "price"), ("TPEX price", "price", "price"),
            ("TWSE revenue", "monthly_revenue", "monthly_revenue"),
            ("TWSE financial", "financial_metrics", "financial_metrics"),
            ("TDCC fixture", "shareholding_distribution", "tdcc_shareholding_distribution"),
        ]:
            db.add(m.SourceRegistry(source_name=name, source_type="fixture", category=category, parser_type=parser))
        db.commit()
    monkeypatch.setattr(backfill, "expected_daily_price_date", lambda: date(2026, 4, 30))
    yield engine
    wait_idle()
    engine.dispose()


def price_provider(monkeypatch, venue, on_call):
    def fetch(url, **kwargs):
        assert kwargs["timeout"] == 30
        month = (parse_qs(urlparse(url).query)["date"][0][4:6] if venue == "twse"
                 else kwargs["data"]["date"][5:7])
        on_call(month)
        rows = [[f"115/{month}/02", "1000", "10000", "10", "11", "9", "10", "0", "1"]]
        payload = {"stat": "OK", "data": rows} if venue == "twse" else {"stat": "ok", "tables": [{"data": rows}]}
        return SimpleNamespace(text=json.dumps(payload), status_code=200,
                               headers={"content-type": "application/json"}, ok=True)
    monkeypatch.setattr(backfill, "http_get" if venue == "twse" else "http_post", fetch)


@pytest.mark.parametrize("venue", ["twse", "tpex"])
@pytest.mark.parametrize("stop_at", ["provider", "commit", "after_commit"])
def test_price_original_owner_pause_resume_without_refetch(database, monkeypatch, venue, stop_at):
    entered, release = Event(), Event()
    fetched = []
    def on_call(month):
        fetched.append(month)
        if len(fetched) == 1 and stop_at == "provider":
            entered.set()
            assert release.wait(5)
    price_provider(monkeypatch, venue, on_call)
    def before_commit(db):
        if stop_at == "commit" and any(isinstance(row, m.MarketDailyPrice) for row in db.new):
            entered.set()
            assert release.wait(5)
    original_checkpoint = backfill.BackfillProgress.advance
    def advance(state, **kwargs):
        if stop_at == "after_commit" and state.completed == 0:
            entered.set()
            assert release.wait(5)
        return original_checkpoint(state, **kwargs)
    monkeypatch.setattr(backfill.BackfillProgress, "advance", advance)
    event.listen(Session, "before_commit", before_commit)
    task = getattr(backfill_tasks, f"run_{venue}_daily_price_job")
    args = ("2330", date(2026, 1, 1), date(2026, 2, 28), 1 if venue == "twse" else 2, 0.0, False)
    job_id = make_job(database)
    service.submit_job_task(task, job_id, *args)
    try:
        assert entered.wait(5)
        lease = service.request_job_pause()
        assert not service.jobs_paused(lease)
        assert fetched == ["01"]
        with Session(database) as db:
            assert db.query(m.MarketDailyPrice).count() == (1 if stop_at == "after_commit" else 0)
    finally:
        release.set()
        wait_idle()
        event.remove(Session, "before_commit", before_commit)
    assert service.jobs_paused(lease)
    assert snapshot(database, job_id)["status"] == "paused"
    with Session(database) as db:
        obligations = service.read_paused_job_obligations(db)
        descriptor = obligations[job_id]
        assert descriptor["checkpoint"]["state"]["completed"] == 1
        assert db.query(m.MarketDailyPrice).count() == 1
    # Simulate loss of the process-local cache; only durable state is available.
    service._paused_tasks.clear()
    service.resume_jobs(lease)
    assert fetched == ["01"]
    service.resume_job_obligations(obligations)
    wait_idle()
    saved = snapshot(database, job_id)
    assert fetched == ["01", "02"]
    assert saved["status"] == "success"
    assert saved["result"]["inserted_count"] == 2
    assert len(saved["result"]["months"]) == 2


@pytest.mark.parametrize("venue", ["twse", "tpex"])
@pytest.mark.parametrize("branch", ["success", "skip", "provider_error", "commit_error"])
def test_price_each_boundary_is_transaction_free(database, monkeypatch, venue, branch):
    fetched, checkpoints = [], []
    def on_call(month):
        fetched.append(month)
        if branch == "provider_error":
            raise TimeoutError("fixture provider timeout")
    price_provider(monkeypatch, venue, on_call)
    token = JobStopToken()
    token.requested.set()
    context = current_job_stop.set(token)
    if branch == "skip":
        monkeypatch.setattr(backfill, "_existing_market_row_stats", lambda **_: (20, date(2026, 1, 30)))
        monkeypatch.setattr(backfill, "_should_skip_existing_month", lambda **_: True)
    failed = []
    def fail_commit(db):
        if branch == "commit_error" and not failed and any(isinstance(row, m.MarketDailyPrice) for row in db.new):
            failed.append(True)
            raise RuntimeError("fixture commit failure")
    event.listen(Session, "before_commit", fail_commit)
    try:
        with Session(database) as db:
            def checkpoint(value):
                assert not db.in_transaction()
                checkpoints.append(value)
                checkpoint_after_transaction(db, value)
            fn = backfill.backfill_twse_stock_day if venue == "twse" else backfill.backfill_tpex_trading_stock
            with pytest.raises(JobPaused):
                fn(db, "2330", date(2026, 1, 1), date(2026, 2, 28),
                   1 if venue == "twse" else 2, 0, branch == "skip", checkpoint=checkpoint)
        assert len(checkpoints) == 1
        assert checkpoints[0]["current"] == (0 if branch in {"provider_error", "commit_error"} else 1)
        assert len(fetched) == (0 if branch == "skip" else 1)
        with Session(database) as db:
            assert db.query(m.MarketDailyPrice).count() == (1 if branch == "success" else 0)
    finally:
        current_job_stop.reset(context)
        event.remove(Session, "before_commit", fail_commit)


@pytest.mark.parametrize("venue", ["twse", "tpex"])
def test_release_window_change_retains_paused_obligation_and_blocks(database, monkeypatch, venue):
    fetched = []
    price_provider(monkeypatch, venue, lambda month: (fetched.append(month), service.request_job_pause()))
    task = getattr(backfill_tasks, f"run_{venue}_daily_price_job")
    job_id = make_job(database)
    monkeypatch.setattr(backfill, "expected_daily_price_date", lambda: date(2026, 1, 30))
    service.submit_job_task(task, job_id, "2330", date(2026, 1, 1), date(2026, 2, 28),
                            1 if venue == "twse" else 2, 0.0, False)
    wait_idle()
    assert snapshot(database, job_id)["status"] == "paused"
    monkeypatch.setattr(backfill, "expected_daily_price_date", lambda: date(2026, 2, 27))
    service.resume_jobs(service._admission_pause)
    wait_idle()
    assert fetched == ["01"]
    assert snapshot(database, job_id)["status"] == "paused"
    assert service.observe_job_quiescence()["unresolved_enqueues"] > 0


def valid_state():
    state = BackfillProgress(owner="fixture", identity=["2330"], items=["2026-01-01", "2026-02-01"], counters=("rows",))
    state.results.append({"period": "2026-01-01"})
    state.totals["rows"] = 1
    state.advance()
    return state.state


@pytest.mark.parametrize("change", ["items", "order", "identity", "keys"])
def test_changed_period_context_rejected(change):
    state = valid_state()
    items, identity, counters = list(state["items"]), ["2330"], ("rows",)
    if change == "items": items.append("2026-03-01")
    if change == "order": items.reverse()
    if change == "identity": identity = ["6488"]
    if change == "keys": counters = ("other",)
    with pytest.raises(ValueError, match="JOB_PERIOD_CONTEXT_CHANGED"):
        BackfillProgress(owner="fixture", identity=identity, items=items, counters=counters, resume_state=state)


@pytest.mark.parametrize("change", ["completed", "results", "totals", "deltas", "result_period"])
def test_malformed_period_ledger_rejected(change):
    state = deepcopy(valid_state())
    if change == "completed": state["completed"] = 2
    if change == "results": state["results"].append({})
    if change == "totals": state["totals"]["rows"] = 9
    if change == "deltas": state["deltas"][0]["rows"] = -1
    if change == "result_period": state["results"][0]["period"] = "2026-02-01"
    with pytest.raises(ValueError, match="STATE_INVALID"):
        validate_period_state(state)


def test_new_or_external_callable_never_gets_replay_by_name(monkeypatch):
    def run_unreviewed(job_id: int): pass
    run_unreviewed.__module__ = backfill_tasks.__name__
    monkeypatch.setattr(backfill_tasks, "run_unreviewed", run_unreviewed, raising=False)
    with pytest.raises(ValueError, match="TASK_UNSUPPORTED"):
        resumption.describe(run_unreviewed, (), "default")
    for module, name in [("app.dispatch.tasks", "run_dispatch_delivery_job"),
                         ("app.jobs.taiwan_intraday_demand", "run_consumer_demand")]:
        with pytest.raises(ValueError, match="TASK_UNSUPPORTED"):
            resumption.resolve(module, name)


@pytest.mark.parametrize("index", [False, True])
@pytest.mark.parametrize("symbols", [(), ("2330",), ("2330", "6488"), (123,)])
def test_bootstrap_queued_descriptor_variadic_tuple_roundtrip(index, symbols):
    from app.jobs import taiwan_bar_bootstrap as bootstrap
    task = bootstrap.run_taiwan_index_daily_bootstrap_job if index else bootstrap.run_taiwan_intraday_bar_bootstrap_job
    args = (symbols, date(2026, 1, 1), date(2026, 2, 1), 10, 10) if index else (symbols, 10)
    descriptor = {**resumption.describe(task, args, "default"), "previous_status": "queued",
                  "previous_result": None, "checkpoint": {"safe_point": "not_started"}}
    descriptor = json.loads(json.dumps(descriptor))
    if symbols == (123,):
        with pytest.raises(ValueError, match="ARGUMENT_TYPE_INVALID"):
            resumption.validate(descriptor)
    else:
        assert resumption.validate(descriptor) == (task, args)


def history_owner(monkeypatch, kind, on_call, *, outcome="success"):
    from app.market import monthly_revenue_history_backfill as revenue
    from app.market import financial_metrics_history_backfill as financial
    from app.market import shareholding_history_backfill as shareholding
    closed = []
    session = SimpleNamespace(close=lambda: closed.append(True))
    module = {"revenue": revenue, "financial": financial, "shareholding": shareholding}[kind]
    monkeypatch.setattr(module, "new_session" if kind != "shareholding" else "_new_tdcc_session", lambda: session)
    if kind == "revenue":
        monkeypatch.setattr(module, "_target_months", lambda **_: [date(2026, 1, 1), date(2026, 2, 1)])
        def fetch(session, url):
            on_call(url)
            if outcome == "error": raise TimeoutError("fixture timeout")
            return "fixture", 200, "text/html"
        monkeypatch.setattr(module, "_fetch_month_html", fetch)
        monkeypatch.setattr(module, "_stock_row_from_html", lambda *_, **__: None if outcome == "no_data" else ["2330"])
        monkeypatch.setattr(module, "_monthly_revenue_payload", lambda **kw: {
            **{key: kw[key] for key in ("source_id", "raw_result_id", "stock_id", "period")}, "report_date": kw["period"]})
        return (backfill_tasks.run_stock_monthly_revenue_history_job,
                ("2330", date(2026, 1, 1), date(2026, 2, 1), 2, 0.0, False),
                m.MonthlyRevenue, closed)
    if kind == "financial":
        monkeypatch.setattr(module, "_target_quarters", lambda **_: [(2025, 3), (2025, 4)])
        def fetch(**kw):
            on_call(f"{kw['quarter']}/{kw['statement']}")
            if outcome == "error": raise TimeoutError("fixture timeout")
            return "fixture", 200, "text/html", "https://fixture.invalid"
        monkeypatch.setattr(module, "_fetch_statement_html", fetch)
        monkeypatch.setattr(module, "_row_map_from_html", lambda **_: None if outcome == "no_data" else {})
        monkeypatch.setattr(module, "_financial_payload", lambda **kw: {
            **{key: kw[key] for key in ("source_id", "raw_result_id", "stock_id", "fiscal_year", "quarter")},
            "period": f"{kw['fiscal_year']}Q{kw['quarter']}",
        })
        return (backfill_tasks.run_stock_financial_metrics_history_job,
                ("2330", 2025, 3, 2025, 4, 2, 0.0, False), m.FinancialMetricQuarterly, closed)
    monkeypatch.setattr(module, "_load_query_form", lambda _: (["20260102", "20260109"], {}))
    def fetch(**kw):
        on_call(kw["date_value"])
        if outcome == "error": raise TimeoutError("fixture timeout")
        return SimpleNamespace(text="fixture", status_code=200)
    monkeypatch.setattr(module, "_fetch_stock_shareholding_html", fetch)
    monkeypatch.setattr(module, "_refresh_form_base_from_html", lambda **_: None)
    monkeypatch.setattr(module, "_parse_shareholding_rows", lambda **kw: [] if outcome == "no_data" else [
        m.ShareholdingDistributionWeekly(**{key: kw[key] for key in ("source_id", "raw_result_id", "stock_id", "data_date")}, holding_level="1")])
    return (backfill_tasks.run_stock_shareholding_history_job,
            ("2330", date(2026, 1, 2), date(2026, 1, 9), 2, 0.0, False), m.ShareholdingDistributionWeekly, closed)


@pytest.mark.parametrize("kind", ["revenue", "financial", "shareholding"])
@pytest.mark.parametrize("outcome", ["success", "no_data", "error", "commit_error"])
def test_history_owners_commit_or_rollback_before_pause_and_resume(database, monkeypatch, kind, outcome):
    fetched = []
    def on_call(item):
        fetched.append(item)
        service.request_job_pause()
    task, args, model, closed = history_owner(monkeypatch, kind, on_call, outcome=outcome)
    failed = []
    def fail_commit(db):
        if outcome == "commit_error" and not failed and any(isinstance(row, model) for row in db.new):
            failed.append(True)
            raise RuntimeError("fixture commit failure")
    event.listen(Session, "before_commit", fail_commit)
    job_id = make_job(database)
    try:
        service.submit_job_task(task, job_id, *args)
        wait_idle()
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert closed
    assert snapshot(database, job_id)["status"] == "paused"
    with Session(database) as db:
        obligations = service.read_paused_job_obligations(db)
        completed = obligations[job_id]["checkpoint"]["state"]["completed"]
        assert completed == (0 if outcome in {"error", "commit_error"} else 1)
        assert db.query(model).count() == (1 if outcome == "success" else 0)
    # A new ready owner loads only the durable descriptor; no local cursor.
    after = []
    history_owner(monkeypatch, kind, after.append, outcome="no_data" if outcome == "no_data" else "success")
    service._paused_tasks.clear()
    service.resume_jobs(service._admission_pause)
    service.resume_job_obligations(obligations)
    wait_idle()
    assert snapshot(database, job_id)["status"] == "success"
    with Session(database) as db:
        assert db.query(model).count() == (0 if outcome == "no_data" else 2)
    if completed:
        assert not set(fetched).intersection(after)


@pytest.mark.parametrize("field", ["args", "owner", "job_id", "binding"])
def test_period_descriptor_rejects_changed_provenance(database, monkeypatch, field):
    price_provider(monkeypatch, "twse", lambda _: service.request_job_pause())
    job_id = make_job(database)
    service.submit_job_task(backfill_tasks.run_twse_daily_price_job, job_id,
                            "2330", date(2026, 1, 1), date(2026, 2, 28), 1, 0.0, False)
    wait_idle()
    with Session(database) as db:
        descriptor = service.read_paused_job_obligations(db)[job_id]
        if field == "args":
            args = list(resumption.decode(descriptor["args"]))
            args[0] = "6488"
            descriptor["args"] = resumption.encode(tuple(args))
        else:
            descriptor["checkpoint"][field] = job_id + 1 if field == "job_id" else "changed"
        job = service.get_job(db, job_id)
        job.result_json = json.dumps({resumption.RESUME_KEY: descriptor})
        db.commit()
        with pytest.raises((ValueError, service.JobQuiescenceUnknown)):
            service.read_paused_job_obligations(db)


def test_repaused_queued_continuation_keeps_committed_cursor(database, monkeypatch):
    price_provider(monkeypatch, "twse", lambda _: service.request_job_pause())
    task = backfill_tasks.run_twse_daily_price_job
    args = ("2330", date(2026, 1, 1), date(2026, 2, 28), 1, 0.0, False)
    job_id = make_job(database)
    service.submit_job_task(task, job_id, *args)
    wait_idle()
    with Session(database) as db:
        original = service.read_paused_job_obligations(db)[job_id]
    service._persist_job_pause(job_id, task, args, "default", {"safe_point": "not_started"})
    with Session(database) as db:
        assert service.read_paused_job_obligations(db)[job_id] == original


@pytest.mark.parametrize("venue", ["twse", "tpex"])
@pytest.mark.parametrize("inserted", [0, 1])
def test_price_parsed_is_not_inserted_and_resume_keeps_true_counts(database, monkeypatch, venue, inserted):
    fetched = []
    price_provider(monkeypatch, venue, lambda month: (fetched.append(month), service.request_job_pause()))
    parser = "parse_twse_stock_day_raw" if venue == "twse" else "_parse_tpex_trading_stock_raw"
    real_parser = getattr(backfill, parser)
    def parse(**kwargs):
        rows, skipped = real_parser(**kwargs)
        return rows * 3, skipped
    monkeypatch.setattr(backfill, parser, parse)
    real_save = backfill._save_market_rows
    # Persistence fixture models duplicate / partial-existing rows. The owner
    # reports actual inserted rows independently of parser cardinality.
    monkeypatch.setattr(backfill, "_save_market_rows", lambda db, rows: real_save(db, rows[:inserted]))
    task = getattr(backfill_tasks, f"run_{venue}_daily_price_job")
    job_id = make_job(database)
    service.submit_job_task(task, job_id, "2330", date(2026, 1, 1), date(2026, 2, 28),
                            1 if venue == "twse" else 2, 0.0, False)
    wait_idle()
    assert snapshot(database, job_id)["status"] == "paused"
    with Session(database) as db:
        state = service.read_paused_job_obligations(db)[job_id]["checkpoint"]["state"]
        assert state["totals"]["total_parsed_count"] == 3
        assert state["totals"]["total_inserted_count"] == inserted
        assert state["results"][0]["inserted_count"] == inserted
    price_provider(monkeypatch, venue, fetched.append)
    service.resume_jobs(service._admission_pause)
    wait_idle()
    saved = snapshot(database, job_id)
    assert saved["status"] == "success" and fetched == ["01", "02"]
    assert saved["result"]["parsed_count"] == 6
    assert saved["result"]["inserted_count"] == 2 * inserted


@pytest.mark.parametrize("kind", ["revenue", "financial", "shareholding"])
def test_history_existing_rows_force_refresh_keeps_true_update_counts(database, monkeypatch, kind):
    task, args, model, _ = history_owner(monkeypatch, kind, lambda _: None)
    first = make_job(database)
    service.submit_job_task(task, first, *args)
    wait_idle()
    assert snapshot(database, first)["status"] == "success"
    def stop_at_start(db):
        if any(isinstance(row, m.JobRun) and row.status == "running" for row in db.dirty):
            service.request_job_pause()
    second = make_job(database)
    event.listen(Session, "before_commit", stop_at_start)
    try:
        service.submit_job_task(task, second, *args)
        wait_idle()
    finally:
        event.remove(Session, "before_commit", stop_at_start)
    assert snapshot(database, second)["status"] == "paused"
    with Session(database) as db:
        state = service.read_paused_job_obligations(db)[second]["checkpoint"]["state"]
        assert state["totals"]["inserted_count"] == 0
        if kind != "shareholding":
            assert state["totals"]["updated_count"] == 1
        assert db.query(model).count() == 2
    service.resume_jobs(service._admission_pause)
    wait_idle()
    saved = snapshot(database, second)
    assert saved["status"] == "success" and saved["result"]["inserted_count"] == 0
    if kind != "shareholding":
        assert saved["result"]["updated_count"] == 2


@pytest.mark.parametrize("venue", ["twse", "tpex"])
def test_new_process_resumes_price_cursor_without_refetch(database, monkeypatch, venue):
    import subprocess
    import sys
    from pathlib import Path

    price_provider(monkeypatch, venue, lambda _: service.request_job_pause())
    job_id = make_job(database)
    service.submit_job_task(getattr(backfill_tasks, f"run_{venue}_daily_price_job"), job_id,
                            "2330", date(2026, 1, 1), date(2026, 2, 28),
                            1 if venue == "twse" else 2, 0.0, False)
    wait_idle()
    assert snapshot(database, job_id)["status"] == "paused"
    child = '''
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path('backend/tests').resolve()))
import g3_offline_guard
g3_offline_guard.install()
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from test_job_period_checkpoints import service, backfill, price_provider, date, wait_idle, m
engine = create_engine(sys.argv[1], poolclass=NullPool)
service.SessionLocal = lambda: Session(engine)
service.settings.job_worker_max_concurrency = 1
backfill.expected_daily_price_date = lambda: date(2026, 4, 30)
fetched = []
patch = pytest.MonkeyPatch()
price_provider(patch, sys.argv[2], fetched.append)
with Session(engine) as db:
    assert service.recover_paused_jobs(db) == 1
wait_idle()
with Session(engine) as db:
    job = db.query(m.JobRun).one()
    assert job.status == 'success', job.error_message
    assert db.query(m.MarketDailyPrice).count() == 2
    assert json.loads(job.result_json)['inserted_count'] == 2
assert fetched == ['02'], fetched
service.shutdown_job_executor(wait=True)
engine.dispose()
patch.undo()
print(json.dumps({'fetched': fetched}))
'''
    result = subprocess.run([sys.executable, "-B", "-c", child, str(database.url), venue],
                            cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip())["fetched"] == ["02"]
    assert snapshot(database, job_id)["status"] == "success"
