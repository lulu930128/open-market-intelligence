from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, event, text, update
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, MarketDailyPrice, SourceRegistry, StockMaster, TaiwanPriceMapSnapshot, TaiwanIntradayStockState
from app.market.price_map_snapshot_repository import read_input_revisions, snapshot_storage_available
from app.market.price_map_snapshot_transaction import claim_price_map_snapshot, publish_price_map_snapshot
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.tw_price_map_screening import build_tw_price_map_screening_snapshot
from app.market.trading_calendar import TAIWAN_TZ

NOW = datetime(2026, 9, 14, 10, tzinfo=TAIWAN_TZ)
BASIS = date(2026, 9, 11)


@pytest.fixture
def sessions():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    path = Path(__file__).parents[1] / "alembic/versions/20260914_0087_tw_price_map_snapshots.py"
    spec = importlib.util.spec_from_file_location("price_map_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        Base.metadata.tables["taiwan_price_map_snapshot"].drop(conn)
        Base.metadata.tables["taiwan_technical_input_revision"].drop(conn)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()
            intraday_path = path.with_name("20261006_0091_tw_intraday_revision.py")
            intraday_spec = importlib.util.spec_from_file_location("intraday_revision_migration", intraday_path)
            intraday_migration = importlib.util.module_from_spec(intraday_spec)
            intraday_spec.loader.exec_module(intraday_migration)
            intraday_migration.upgrade()
            source_path = path.with_name("20261101_0097_tw_snapshot_source_revision.py")
            source_spec = importlib.util.spec_from_file_location("source_revision_migration", source_path)
            source_migration = importlib.util.module_from_spec(source_spec)
            source_spec.loader.exec_module(source_migration)
            source_migration.upgrade()
            semantic_path = path.with_name("20261101_0098_tw_daily_semantic_revision.py")
            semantic_spec = importlib.util.spec_from_file_location("daily_semantic_migration", semantic_path)
            semantic_migration = importlib.util.module_from_spec(semantic_spec)
            semantic_spec.loader.exec_module(semantic_migration)
            semantic_migration.upgrade()
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def seed(db, count=1):
    source = SourceRegistry(source_name="test_daily", source_type="official", category="market")
    db.add(source)
    db.flush()
    for index in range(count):
        stock_id = str(2330 + index)
        db.add(StockMaster(stock_id=stock_id, stock_name=stock_id, market="TWSE", instrument_type="stock", is_active=True))
        db.add(MarketDailyPrice(stock_id=stock_id, source_id=source.id, trade_date=BASIS, close_price=100))
    db.commit()


def payload(zones=True, stock_id="2330"):
    from app.market.stock_price_map import METHODOLOGY_VERSION, PRICE_MAP_VERSION
    return {"decision_usable": True, "basis_revision": "basis-v1", "stock_id": stock_id,
        "structure_timeframe": "daily", "version": PRICE_MAP_VERSION,
        "reference": {"trade_date": BASIS.isoformat()},
        "parameter_contract": {"parameter_revision": get_technical_analysis_parameters().revision},
        "methodology": {"version": METHODOLOGY_VERSION}, "zones": [
        {"zone_id": "zone-a", "lower_bound": 99, "upper_bound": 101, "scanner_eligible": True, "geometry_status": "ready"}
    ] if zones else []}


def publish(db, stock_id="2330", zones=True):
    params = get_technical_analysis_parameters()
    token = claim_price_map_snapshot(db, stock_id=stock_id, timeframe="daily", parameters=params,
        corporate_revision="corp", basis_date=BASIS, now=NOW - timedelta(minutes=121))
    db.commit()
    assert token
    assert publish_price_map_snapshot(db, stock_id=stock_id, timeframe="daily", token=token,
        payload=payload(zones, stock_id=stock_id), parameters=params, corporate_revision="corp", now=NOW - timedelta(minutes=120))
    db.commit()
    return token


def observation(db, stock_id="2330", age=0):
    import json
    samples = json.dumps([{"time": NOW.isoformat(), "price": 100, "price_as_of": (NOW - timedelta(seconds=age)).isoformat(),
        "received_at": NOW.isoformat(), "sample_contract_version": "tw.trade_sample.v1", "lineage_complete": True}])
    db.add(TaiwanIntradayStockState(stock_id=stock_id, provider="canonical", market="TWSE", trade_date=NOW.date(),
        event_time=NOW - timedelta(seconds=age), snapshot_as_of=NOW, price_as_of=NOW - timedelta(seconds=age),
        state_contract_version="tw.intraday_stock_state.v3", current_price=100, source="canonical_fixture",
        has_actual_trade=True, lineage_complete=True, decision_usable=True, session_phase="regular",
        price_semantics="actual_trade", quality_status="ready", samples_json=samples))
    db.commit()


def scan(db, parameters=None):
    with patch("app.market.tw_price_map_screening.read_price_map_external_revision", return_value="corp"):
        return build_tw_price_map_screening_snapshot(db, parameters=parameters, generated_at=NOW)


def test_migration_revisions_and_transaction_rollback(sessions):
    with sessions() as db:
        assert snapshot_storage_available(db)
        seed(db)
        initial = read_input_revisions(db, ["2330"])["2330"]
        db.execute(update(MarketDailyPrice).values(close_price=101))
        assert read_input_revisions(db, ["2330"])["2330"] > initial
        db.rollback()
        assert read_input_revisions(db, ["2330"])["2330"] == initial
        db.query(MarketDailyPrice).delete()
        db.commit()
        assert read_input_revisions(db, ["2330"])["2330"] > initial


def test_corrected_input_and_old_worker_cannot_publish(sessions):
    with sessions() as db:
        seed(db)
        params = get_technical_analysis_parameters()
        token = claim_price_map_snapshot(db, stock_id="2330", timeframe="daily", parameters=params, corporate_revision="corp", basis_date=BASIS, now=NOW)
        db.commit()
        db.execute(update(MarketDailyPrice).values(close_price=102))
        db.commit()
        assert not publish_price_map_snapshot(db, stock_id="2330", timeframe="daily", token=token, payload=payload(), parameters=params, corporate_revision="corp", now=NOW)
        assert db.get(TaiwanPriceMapSnapshot, ("2330", "daily")).payload_json is None
        assert not publish_price_map_snapshot(db, stock_id="2330", timeframe="daily", token="old-worker", payload=payload(), parameters=params, corporate_revision="corp", now=NOW)


def test_empty_success_is_distinct_from_missing_and_reads_are_pure(sessions):
    with sessions() as db:
        seed(db, 3)
        publish(db, "2330")
        publish(db, "2331", zones=False)
        observation(db, "2330")
        observation(db, "2331")
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.bind, "before_cursor_execute", capture)
        result = scan(db, {"limit": 1})
        event.remove(db.bind, "before_cursor_execute", capture)
        assert result["coverage"]["requested_symbols"] == 3
        assert result["coverage"]["eligible_symbols"] == 2
        assert result["coverage"]["no_match_symbols"] == 1
        assert result["coverage"]["excluded_reason_counts"] == {"SNAPSHOT_NOT_COMPUTED": 1}
        assert result["pagination"]["total"] == 1
        assert not result["coverage"]["complete"]
        assert all(not query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE")) for query in statements)


def test_stale_observation_not_promoted_by_fresh_receipt_or_limit(sessions):
    with sessions() as db:
        seed(db, 2)
        for stock in ("2330", "2331"):
            publish(db, stock)
        observation(db, "2330")
        observation(db, "2331", age=120)
        small = scan(db, {"limit": 1})
        large = scan(db, {"limit": 200})
        assert small["coverage"] == large["coverage"]
        assert small["coverage"]["eligible_symbols"] == 1
        assert "OBSERVATION_NOT_CURRENT" in small["missing"]
        db.execute(update(MarketDailyPrice).where(MarketDailyPrice.stock_id == "2330").values(close_price=103))
        db.commit()
        assert scan(db)["coverage"]["eligible_symbols"] == 0


def test_scanner_parameters_fail_closed():
    for parameters in ({"timeframe": "today"}, {"limit": True}, {"near_pct": float("nan")}, {"lane": "indicative", "relation": "support_reaction"}):
        from app.market.tw_price_map_screening import normalize_price_map_scan_parameters
        with pytest.raises(ValueError):
            normalize_price_map_scan_parameters(parameters)

def test_failed_build_resumes_and_expired_claim_cannot_overwrite(sessions):
    from app.market.price_map_snapshot_transaction import fail_price_map_snapshot
    from app.jobs.taiwan_price_map_snapshot_scheduler import produce_taiwan_price_map_snapshots
    with sessions() as db:
        seed(db, 2)
        params = get_technical_analysis_parameters()
        token = claim_price_map_snapshot(db, stock_id="2330", timeframe="daily", parameters=params, corporate_revision="corp", basis_date=BASIS, now=NOW)
        db.commit()
        assert claim_price_map_snapshot(db, stock_id="2330", timeframe="daily", parameters=params, corporate_revision="corp", basis_date=BASIS, now=NOW) is None
        replacement = claim_price_map_snapshot(db, stock_id="2330", timeframe="daily", parameters=params, corporate_revision="corp", basis_date=BASIS, now=NOW + timedelta(minutes=6))
        db.commit()
        assert replacement and replacement != token
        assert not publish_price_map_snapshot(db, stock_id="2330", timeframe="daily", token=token, payload=payload(), parameters=params, corporate_revision="corp", now=NOW)
        fail_price_map_snapshot(db, stock_id="2330", timeframe="daily", token=replacement, now=NOW, error_code="test_failure")
        db.commit()
    with patch("app.jobs.taiwan_price_map_snapshot_scheduler.read_price_map_external_revision", return_value="corp"):
        result = produce_taiwan_price_map_snapshots(session_factory=sessions, builder=lambda **kwargs: payload(stock_id=kwargs["stock_id"]),
            clock=lambda: NOW, batch_size=1, timeframes=("daily",))
    assert result["published"] == 1  # Retry delay does not starve the next instrument.
    with sessions() as db:
        assert db.get(TaiwanPriceMapSnapshot, ("2331", "daily")).status == "ready"
        assert db.get(TaiwanPriceMapSnapshot, ("2330", "daily")).status == "failed"


def test_indicative_lane_never_becomes_actual_trade(sessions):
    preopen = NOW.replace(hour=8, minute=50)
    with sessions() as db:
        seed(db)
        publish(db)
        observation(db)
        db.execute(update(TaiwanIntradayStockState).values(
            event_time=preopen, snapshot_as_of=preopen, price_as_of=preopen,
            has_actual_trade=False, decision_usable=False,
            indicative_match_available=True, indicative_match_price=100, session_phase="preopen"))
        db.commit()
        with patch("app.market.tw_price_map_screening.read_price_map_external_revision", return_value="corp"):
            indicative = build_tw_price_map_screening_snapshot(db, parameters={"lane": "indicative"}, generated_at=preopen)
            actual = build_tw_price_map_screening_snapshot(db, generated_at=preopen)
        assert indicative["coverage"]["eligible_symbols"] == 1
        assert indicative["decision_usable"] is False
        assert indicative["rows"][0]["observation"]["has_actual_trade"] is False
        assert actual["coverage"]["eligible_symbols"] == 0


def test_successful_no_match_is_valid_empty_evidence(sessions):
    from app.ai.data_quality_contract import _payload_semantic_quality, _semantic_payload_empty
    with sessions() as db:
        seed(db)
        publish(db, zones=False)
        observation(db)
        result = scan(db)
        assert result["empty_result_is_valid"] is True
        assert result["facts_usable"] is True
        assert result["rows"] == []
        assert not _semantic_payload_empty("screening.price_map", result)
        assert _payload_semantic_quality("screening.price_map", result)["status_class"] == "ready"


def test_corporate_parameter_and_identity_changes_invalidate(sessions):
    from dataclasses import replace
    params = get_technical_analysis_parameters()
    with sessions() as db:
        seed(db)
        publish(db)
        observation(db)
        with patch("app.market.tw_price_map_screening.get_technical_analysis_parameters", return_value=replace(params, rsi_period=params.rsi_period + 1)):
            assert "SNAPSHOT_REVISION_STALE" in scan(db)["missing"]
        with patch("app.market.tw_price_map_screening.read_price_map_external_revision", return_value="changed"):
            assert "SNAPSHOT_REVISION_STALE" in build_tw_price_map_screening_snapshot(db, generated_at=NOW)["missing"]
        before = read_input_revisions(db, ["2330"])
        db.execute(update(StockMaster).values(market="TPEX"))
        db.commit()
        assert read_input_revisions(db, ["2330"])["2330"] > before["2330"]


def test_reactions_require_order_gap_bound_and_confirmation_window():
    from app.market.price_map_reaction import price_map_reaction
    def evaluate(prices, seconds=None, published=None):
        stamps = seconds or list(range(0, len(prices) * 30, 30))
        samples = [{"time": (NOW + timedelta(seconds=stamp)).isoformat(), "price": price} for stamp, price in zip(stamps, prices)]
        return price_map_reaction(samples, lower=99, upper=101, published_at=published or NOW,
            now=NOW + timedelta(seconds=stamps[-1]), basis_revision="stable")
    assert evaluate([102, 100, 102, 102, 102])["event"] == "support_reaction"
    assert evaluate([98, 102, 100, 102, 102, 102])["event"] == "breakout_retest"
    assert evaluate([102, 100, 102])["event"] is None
    assert evaluate([102, 100, 102, 102, 102], [0, 30, 60, 300, 330])["status"] == "sequence_gap"
    assert evaluate([102, 100, 102, 102, 102], [0, 30, 30, 60, 90])["status"] == "sequence_gap"
    assert evaluate([102, 100, 102, 102, 102], published=NOW + timedelta(seconds=45))["event"] is None


def test_ai_market_route_quality_and_projection_keep_full_coverage(sessions):
    from app.ai import capability_contract, query_plan
    from app.ai.schemas import AiAskRequest
    from app.ai.market_context.taiwan_screening import read_tw_screening_context
    request = AiAskRequest(question="台股哪些股票接近週線支撐，掃描前5檔", contract_version="omi.decision.v4",
        target={"type": "market", "market": "TW"}, mode="data_only", output="evidence_only")
    plan = query_plan.build_query_plan(payload=request, scope_type="market", question_intent="general",
        effective_mode="data_only", target_market="TW")
    assert "screening.price_map" in plan.selected_capabilities
    assert plan.selection["parameters"]["screening.price_map"]["timeframe"] == "weekly"
    assert plan.selection["parameters"]["screening.price_map"]["limit"] == 5
    assert plan.selection["parameters"]["screening.price_map"]["zone_side"] == "downside"
    assert plan.external_refresh_allowed is False
    with sessions() as db:
        seed(db)
        publish(db)
        observation(db)
        with patch("app.market.tw_price_map_screening.read_price_map_external_revision", return_value="corp"):
            context = read_tw_screening_context(db, market_data_params={"requested_capabilities": ["screening.price_map"]}, now=lambda: NOW)
        projected, unavailable = capability_contract.project_selected_data(
            response={"result": context}, selection={"required": ["screening.price_map"], "optional": [], "fields": {}, "limits": {}})
        assert unavailable == []
        result = projected["screening.price_map"]
        assert result["coverage"]["requested_symbols"] == 1
        assert result["coverage"]["complete"] is True
        assert result["rows"][0]["basis_revision"] == "basis-v1"


def test_missing_migration_is_a_truthful_read_only_result():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        seed(db)
        result = build_tw_price_map_screening_snapshot(db, generated_at=NOW)
        assert result["missing"] == ["SNAPSHOT_MIGRATION_REQUIRED"]
        assert db.query(TaiwanPriceMapSnapshot).count() == 0
    engine.dispose()

def test_reaction_reader_rejects_polling_clock_and_deduplicates_same_trade():
    import json
    from app.market.tw_intraday_state import _price_map_trade_samples
    legacy = {"time": NOW.isoformat(), "price": 100}
    qualified = {**legacy, "sample_contract_version": "tw.trade_sample.v1",
        "price_as_of": NOW.isoformat(), "received_at": NOW.isoformat(), "lineage_complete": True}
    repeated_receipt = {**qualified, "time": (NOW + timedelta(minutes=1)).isoformat(),
        "received_at": (NOW + timedelta(minutes=1)).isoformat()}
    assert _price_map_trade_samples(json.dumps([legacy]), trade_date=NOW.date()) == []
    rows = _price_map_trade_samples(json.dumps([qualified, repeated_receipt]), trade_date=NOW.date())
    assert rows == [{"time": NOW.isoformat(), "price": 100}]
    future = {**qualified, "price_as_of": (NOW + timedelta(seconds=1)).isoformat()}
    assert _price_map_trade_samples(json.dumps([future]), trade_date=NOW.date()) == []


def test_publication_after_request_is_not_visible(sessions):
    with sessions() as db:
        seed(db)
        publish(db)
        observation(db)
        db.execute(update(TaiwanPriceMapSnapshot).values(published_at=(NOW + timedelta(minutes=1)).astimezone(timezone.utc)))
        db.commit()
        assert scan(db)["coverage"]["eligible_symbols"] == 0
        assert "SNAPSHOT_PUBLICATION_NOT_AVAILABLE" in scan(db)["missing"]

def test_basis_cache_invalidates_corrections_even_when_close_unchanged(sessions):
    from app.market.stock_price_map import _basis_cache_key
    with sessions() as db:
        seed(db)
        kwargs = {"stock_id": "2330", "next_plan": {"as_of_trade_date": BASIS, "as_of_close": 100},
                  "parameter_revision": get_technical_analysis_parameters().revision}
        first = _basis_cache_key(db, **kwargs)
        db.execute(update(MarketDailyPrice).values(trade_volume=1234))
        db.commit()
        second = _basis_cache_key(db, **kwargs)
        assert first is not None and first != second
        with patch("app.market.stock_price_map.read_price_map_external_revision", return_value="new-corporate-or-calendar"):
            assert _basis_cache_key(db, **kwargs) != second


def test_daily_pilot_resumes_and_preserves_partial_empty_and_unselected(sessions):
    from app.jobs.taiwan_price_map_snapshot_scheduler import produce_taiwan_price_map_snapshots

    with sessions() as db:
        seed(db, 5)
        db.execute(update(StockMaster).where(StockMaster.stock_id == "2331").values(market="TPEX"))
        db.commit()
    calls = []

    def build(**kwargs):
        stock_id = kwargs["stock_id"]
        calls.append((stock_id, kwargs["timeframe"]))
        result = payload(stock_id=stock_id, zones=stock_id != "2332")
        if stock_id == "2331":
            result.update(status="partial", structure_input_usable=False, decision_usable=False,
                corporate_action={"coverage_status": "partial"})
        return result

    kwargs = dict(session_factory=sessions, builder=build, clock=lambda: NOW,
        batch_size=1, timeframes=("daily",), stock_ids=("2330", "2331", "2332"))
    with patch("app.jobs.taiwan_price_map_snapshot_scheduler.read_price_map_external_revision", return_value="corp"):
        reports = [produce_taiwan_price_map_snapshots(**kwargs) for _ in range(4)]
    assert [r["attempted"] for r in reports] == [1, 1, 1, 0]
    assert [r["publication_status_counts"] for r in reports] == [{"ready": 1}, {"partial": 1}, {"empty": 1}, {}]
    assert calls == [("2330", "daily"), ("2331", "daily"), ("2332", "daily")]
    assert reports[0]["scope_semantics"] == "bounded_pilot"
    assert reports[0]["selected_stock_ids"] == ["2330", "2331", "2332"]
    with sessions() as db:
        rows = db.query(TaiwanPriceMapSnapshot).order_by(TaiwanPriceMapSnapshot.stock_id).all()
        assert [(r.stock_id, r.timeframe, r.status, r.attempts) for r in rows] == [
            ("2330", "daily", "ready", 1), ("2331", "daily", "partial", 1), ("2332", "daily", "empty", 1)]
        assert all(r.basis_date == BASIS and r.published_at and r.parameter_revision == get_technical_analysis_parameters().revision
            and r.corporate_revision == "corp" and r.input_revision > 0 for r in rows)
        observation(db, "2330")
        observation(db, "2332")
        result = scan(db, {"universe": {"stock_ids": ["2330", "2331", "2332"]}})
        assert result["coverage"] == {"requested_symbols": 3, "computed_symbols": 3,
            "current_structure_symbols": 2, "eligible_symbols": 2, "matched_symbols": 1,
            "no_match_symbols": 1, "complete": False, "excluded_reason_counts": {"SNAPSHOT_PARTIAL": 1}}
        assert result["empty_result_is_valid"] is False
        assert scan(db)["coverage"]["excluded_reason_counts"] == {"SNAPSHOT_NOT_COMPUTED": 2, "SNAPSHOT_PARTIAL": 1}


@pytest.mark.parametrize("ids", [(), [], "2330", ("",), ("2330", " "), tuple(str(n) for n in range(11))])
def test_invalid_pilot_selection_never_opens_session(ids):
    from unittest.mock import Mock
    from app.jobs.taiwan_price_map_snapshot_scheduler import produce_taiwan_price_map_snapshots
    factory = Mock(side_effect=AssertionError("Invalid pilot must not access DB"))
    with pytest.raises(ValueError):
        produce_taiwan_price_map_snapshots(session_factory=factory, stock_ids=ids, timeframes=("daily",))
    factory.assert_not_called()


def test_pilot_unavailable_members_do_not_expand_to_other_stocks(sessions):
    from app.jobs.taiwan_price_map_snapshot_scheduler import produce_taiwan_price_map_snapshots
    with sessions() as db:
        seed(db, 4)
        db.execute(update(StockMaster).where(StockMaster.stock_id == "2331").values(is_active=False))
        db.execute(update(StockMaster).where(StockMaster.stock_id == "2332").values(instrument_type="etf"))
        db.commit()
    with patch("app.jobs.taiwan_price_map_snapshot_scheduler.read_price_map_external_revision", return_value="corp"):
        result = produce_taiwan_price_map_snapshots(session_factory=sessions,
            builder=lambda **kw: payload(stock_id=kw["stock_id"]), clock=lambda: NOW,
            timeframes=("daily",), stock_ids=("2330", "2331", "2332"))
    assert result["published"] == 1
    assert result["selected_stock_ids"] == ["2330"]
    assert result["unavailable_stock_ids"] == ["2331", "2332"]


def test_scheduler_binds_daily_pilot_without_changing_disabled_default(monkeypatch):
    from unittest.mock import Mock
    from app.jobs import taiwan_price_map_snapshot_scheduler as scheduler
    mock = Mock()
    monkeypatch.setattr(scheduler.settings, "enable_taiwan_price_map_snapshot_scheduler", False)
    assert scheduler.add_taiwan_price_map_snapshot_jobs(mock) is False
    mock.add_job.assert_not_called()
    monkeypatch.setattr(scheduler.settings, "enable_taiwan_price_map_snapshot_scheduler", True)
    monkeypatch.setattr(scheduler.settings, "taiwan_price_map_snapshot_stock_ids", "2330, 6147,6770")
    monkeypatch.setattr(scheduler.settings, "taiwan_price_map_snapshot_timeframes", "daily")
    assert scheduler.add_taiwan_price_map_snapshot_jobs(mock) is True
    assert mock.add_job.call_args.kwargs["kwargs"] == {"stock_ids": ("2330", "6147", "6770"), "timeframes": ("daily",)}
    assert mock.add_job.call_args.kwargs["max_instances"] == 1
    monkeypatch.setattr(scheduler.settings, "taiwan_price_map_snapshot_stock_ids", "2330,,6770")
    mock.reset_mock()
    with pytest.raises(ValueError):
        scheduler.add_taiwan_price_map_snapshot_jobs(mock)
    mock.add_job.assert_not_called()


def test_get_and_ask_read_published_pilot_without_writes(sessions):
    from fastapi import Request
    from app.ai.schemas import AiAskV4Request
    from app.routers.ai import ask_omi
    from app.routers.market import get_taiwan_price_map_screening

    with sessions() as db:
        seed(db, 3)
        publish(db, "2330")
        publish(db, "2331", zones=False)
        observation(db, "2330")
        observation(db, "2331")
        db.execute(text("PRAGMA query_only=ON"))
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            with patch("app.market.tw_price_map_screening.read_price_map_external_revision", return_value="corp"), \
                    patch("app.market.tw_price_map_screening.datetime") as frozen, \
                    patch("app.ai.tools._now", return_value=NOW), \
                    patch("app.jobs.taiwan_historical_input_repair.admit_taiwan_historical_input_repair", side_effect=AssertionError("GET repair admission")), \
                    patch("app.jobs.tw_technical_input_readiness.execute_taiwan_historical_input_step", side_effect=AssertionError("GET provider IO")), \
                    patch("app.jobs.service.submit_job_task", side_effect=AssertionError("GET job submission")):
                frozen.now.return_value = NOW
                get_result = get_taiwan_price_map_screening(timeframe="daily", relation="near_zone",
                    zone_side="any", lane="actual", near_pct=0.5, limit=1, offset=0,
                    stock_ids=["2330", "2331", "2332"], db=db)
                response = ask_omi(Request({"type": "http", "headers": [], "client": ("offline", 1)}),
                    AiAskV4Request(question="Read cached daily Price Map pilot", mode="data_only", output="evidence_only",
                        target={"type": "market", "market": "TW"}, allow_llm=False, allow_write=False,
                        realtime_policy="cache_only",
                        refresh_policy={"mode": "off", "before_answer": False},
                        selection={"include": ["screening.price_map"], "parameters": {"screening.price_map": {
                            "timeframe": "daily", "limit": 1, "universe": {"stock_ids": ["2330", "2331", "2332"]}}}}), db=db)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        evidence = response["evidence"]["data"]["screening.price_map"]
        assert response["contract_version"] == "omi.decision.v4"
        assert evidence["coverage"] == get_result["coverage"]
        assert evidence["coverage"]["computed_symbols"] == 2
        assert evidence["coverage"]["excluded_reason_counts"] == {"SNAPSHOT_NOT_COMPUTED": 1}
        assert str(evidence["expected_basis_date"]) == get_result["expected_basis_date"].isoformat()
        assert evidence["rows"][0]["basis_revision"] == get_result["rows"][0]["basis_revision"]
        assert evidence["empty_result_is_valid"] is False
        assert all(not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "REPLACE")) for sql in statements)


def official_daily(db, *, basis=BASIS, receipt_at=None):
    """Qualify existing fixture rows through the real canonical official reader."""
    from app.db.models import RawFetchResult
    from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
    source = db.query(SourceRegistry).one()
    source.source_name = TWSE_DAILY_TRADING_SOURCE_NAME
    source.reliability_level = "official"
    fetched_at = receipt_at or datetime.combine(basis, datetime.min.time(), tzinfo=TAIWAN_TZ).replace(hour=16)
    raw = RawFetchResult(source_id=source.id, fetched_at=fetched_at.astimezone(timezone.utc), content_hash="daily-receipt",
        parser_version="fixture.v1", status_code=200, raw_text="[]")
    db.add(raw)
    db.flush()
    db.execute(update(MarketDailyPrice).values(raw_result_id=raw.id, trade_date=basis,
        open_price=100, high_price=110, low_price=90, close_price=100,
        official=True, release_status="official_final", finalization="final"))
    db.commit()


def test_completed_daily_weekend_positions_and_negative_quality(sessions):
    weekend = datetime(2026, 9, 13, 10, tzinfo=TAIWAN_TZ)
    with sessions() as db:
        seed(db, 4)
        official_daily(db)
        db.execute(update(MarketDailyPrice).where(MarketDailyPrice.stock_id == "2331").values(close_price=108))
        db.execute(update(MarketDailyPrice).where(MarketDailyPrice.stock_id == "2332").values(finalization="provisional"))
        db.commit()
        for symbol in ("2330", "2331", "2332"):
            publish(db, symbol)
        db.execute(update(TaiwanPriceMapSnapshot).values(published_at=weekend - timedelta(days=1)))
        db.commit()
        db.execute(text("PRAGMA query_only=ON"))
        with patch("app.market.tw_price_map_screening.read_price_map_external_revision", return_value="corp"), \
                patch("app.market.tw_price_map_screening.read_tw_price_map_observations", side_effect=AssertionError("No intraday fallback")):
            result = build_tw_price_map_screening_snapshot(db, parameters={"lane": "completed_daily"}, generated_at=weekend)
            inside = build_tw_price_map_screening_snapshot(db, parameters={"lane": "completed_daily", "relation": "within_zone"}, generated_at=weekend)
        assert result["expected_basis_date"] == BASIS
        assert result["status"] == "partial"
        assert result["coverage"]["requested_symbols"] == 4
        assert result["coverage"]["eligible_symbols"] == 2
        assert result["coverage"]["matched_symbols"] == 1
        assert result["coverage"]["no_match_symbols"] == 1
        assert result["coverage"]["excluded_reason_counts"] == {"COMPLETED_DAILY_NOT_FINALIZED": 1, "SNAPSHOT_NOT_COMPUTED": 1}
        assert inside["rows"][0]["relation"] == "within_zone"
        assert inside["rows"][0]["reaction"] is None
        obs = result["rows"][0]["observation"]
        assert obs["trade_date"] == BASIS and obs["price_semantics"] == "official_finalized_daily_close"
        assert obs["has_actual_trade"] is False and obs["lineage"]["raw_receipt_id"]
        assert obs["finalization"] == "final" and obs["authority"] == "exchange"
        assert result["intraday_research_usable"] is False and result["execution_grade_usable"] is False
        assert result["empty_result_is_valid"] is False


@pytest.mark.parametrize("relation", ["touching", "support_reaction", "resistance_reaction", "breakout_retest", "breakdown_retest"])
def test_completed_daily_cannot_claim_intraday_reaction(relation):
    from app.market.tw_price_map_screening import normalize_price_map_scan_parameters
    with pytest.raises(ValueError, match="closing price position"):
        normalize_price_map_scan_parameters({"lane": "completed_daily", "relation": relation})


def test_completed_daily_holiday_and_http_ask_parity_are_read_only(sessions, monkeypatch):
    from fastapi import Request
    from app.ai.schemas import AiAskV4Request, AiAskRequest
    from app.ai.query_plan import build_query_plan
    from app.routers.ai import ask_omi
    from app.routers.market import get_taiwan_price_map_screening
    from app.market.trading_calendar import latest_completed_taiwan_session_date
    holiday = datetime(2026, 9, 28, 16, tzinfo=TAIWAN_TZ)
    basis = date(2026, 9, 24)  # 25 中秋、週末、28 教師節都不產生日線。
    assert latest_completed_taiwan_session_date(holiday) == basis
    with sessions() as db:
        seed(db)
        official_daily(db, basis=basis)
        import sys
        monkeypatch.setattr(sys.modules[__name__], "BASIS", basis)
        monkeypatch.setattr(sys.modules[__name__], "NOW", holiday)
        publish(db)
        db.execute(update(TaiwanPriceMapSnapshot).values(published_at=holiday - timedelta(days=3)))
        db.commit()
        db.execute(text("PRAGMA query_only=ON"))
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            with patch("app.market.tw_price_map_screening.read_price_map_external_revision", return_value="corp"), \
                    patch("app.market.tw_price_map_screening.datetime") as frozen, patch("app.ai.tools._now", return_value=holiday):
                frozen.now.return_value = holiday
                http = get_taiwan_price_map_screening(timeframe="daily", relation="within_zone", zone_side="any",
                    lane="completed_daily", near_pct=0.5, limit=1, offset=0, stock_ids=["2330"], db=db)
                response = ask_omi(Request({"type": "http", "headers": [], "client": ("offline", 1)}),
                    AiAskV4Request(question="盤後掃描收盤位於支撐價位帶的股票", mode="data_only", output="evidence_only",
                        target={"type": "market", "market": "TW"}, allow_llm=False, allow_write=False,
                        realtime_policy="cache_only", refresh_policy={"mode": "off", "before_answer": False},
                        selection={"include": ["screening.price_map"], "parameters": {"screening.price_map": {
                            "lane": "completed_daily", "relation": "within_zone", "universe": {"stock_ids": ["2330"]}}}}), db=db)
                server_path = Path(__file__).parents[2] / "agents/omi_mcp_server/server.py"
                spec = importlib.util.spec_from_file_location("price_map_mcp_parity", server_path)
                server = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(server)
                schema = server._load_public_contract_snapshot()["ask_input_schema"]
                scanner_schema = schema["properties"]["selection"]["properties"]["parameters"]["properties"]["screening.price_map"]
                assert "completed_daily" in scanner_schema["properties"]["lane"]["enum"]
                def post(path, payload):
                    assert path == "/api/ai/ask" and payload["allow_write"] is False and payload["allow_external_fetch"] is False
                    return ask_omi(Request({"type": "http", "headers": [], "client": ("offline", 1)}),
                        AiAskV4Request.model_validate(payload), db=db)
                with patch.object(server, "_api_post", side_effect=post):
                    mcp = server._call_tool("omi.ask", {"question": "盤後掃描哪些股票接近支撐", "mode": "data_only",
                        "output": "evidence_only", "target": {"type": "market", "market": "TW"},
                        "realtime_policy": "cache_only", "allow_external_fetch": False,
                        "refresh_policy": {"mode": "off", "before_answer": False},
                        "selection": {"include": ["screening.price_map"], "parameters": {"screening.price_map": {
                            "lane": "completed_daily", "relation": "within_zone", "universe": {"stock_ids": ["2330"]}}}}})
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        evidence = response["evidence"]["data"]["screening.price_map"]
        assert http["coverage"]["complete"] is True and evidence["coverage"] == http["coverage"]
        assert http["expected_basis_date"] == basis and str(evidence["expected_basis_date"]) == basis.isoformat()
        assert evidence["rows"][0]["current_price"] == http["rows"][0]["current_price"] == 100
        assert evidence["rows"][0]["relation"] == "within_zone"
        assert evidence["rows"][0]["observation"]["lineage"]["raw_receipt_id"] == http["rows"][0]["observation"]["lineage"]["raw_receipt_id"]
        assert evidence["warnings"] == http["warnings"]
        assert mcp["evidence"]["data"]["screening.price_map"] == evidence
        assert all(not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "REPLACE")) for sql in statements)
    plan = build_query_plan(payload=AiAskRequest(question="盤後掃描哪些股票接近支撐", target={"type": "market", "market": "TW"}),
        scope_type="market", question_intent="general", effective_mode="data_only", target_market="TW")
    assert plan.selection["parameters"]["screening.price_map"]["lane"] == "completed_daily"


def test_full_market_batches_skip_valid_headers_and_continue_after_integrity_failure(sessions):
    from app.jobs import taiwan_price_map_snapshot_scheduler as producer
    from sqlalchemy.exc import IntegrityError
    with sessions() as db:
        seed(db, 27)
    calls = []
    def build(**kw):
        symbol = kw["stock_id"]
        calls.append(symbol)
        if symbol == "2330" and calls.count(symbol) == 1:
            raise IntegrityError("fixture build", {}, Exception("fixture"))
        return payload(stock_id=symbol)
    with patch.object(producer, "read_price_map_external_revision", return_value="corp"), \
            patch.object(producer, "claim_price_map_snapshot", wraps=claim_price_map_snapshot) as claim:
        reports = [producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build,
            clock=lambda: NOW, batch_size=12, timeframes=("daily",)) for _ in range(4)]
        assert [r["attempted"] for r in reports] == [12, 12, 3, 0]
        assert claim.call_count == 27  # Finished prefix never opens one claim transaction per symbol again.
        assert reports[0]["failed"] == 1 and reports[0]["published"] == 11
        assert reports[-1]["coverage_before"] == {"requested_items": 27, "status_counts": {"failed": 1, "ready": 26}}
        assert reports[-1]["skipped_reason_counts"] == {"current_published": 26, "retry_not_due": 1}
        retry = producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build,
            clock=lambda: NOW + timedelta(seconds=61), batch_size=12, timeframes=("daily",))
    assert retry["attempted"] == retry["published"] == 1
    assert all(r["scope_semantics"] == "bounded_batch_not_full_market" for r in reports)
    with sessions() as db:
        rows = db.query(TaiwanPriceMapSnapshot).all()
        assert len(rows) == 27 and all(r.status == "ready" for r in rows)
        assert db.get(TaiwanPriceMapSnapshot, ("2330", "daily")).attempts == 2


def test_producer_next_session_correction_and_external_version_republish(sessions):
    from dataclasses import replace
    from app.jobs import taiwan_price_map_snapshot_scheduler as producer
    from app.market.trading_calendar import latest_completed_taiwan_session_date
    now = datetime(2026, 9, 11, 16, tzinfo=TAIWAN_TZ)
    corporate = "corp"
    parameters = get_technical_analysis_parameters()
    with sessions() as db:
        seed(db)
        official_daily(db)
    def build(**kw):
        value = payload(stock_id=kw["stock_id"])
        value["parameter_contract"]["parameter_revision"] = kw["parameters"].revision
        value["reference"]["trade_date"] = latest_completed_taiwan_session_date(kw["now"]).isoformat()
        return value
    def run():
        return producer.produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build,
            clock=lambda: now, stock_ids=("2330",), timeframes=("daily",))
    with patch.object(producer, "read_price_map_external_revision", side_effect=lambda: corporate), \
            patch.object(producer, "get_technical_analysis_parameters", side_effect=lambda: parameters):
        assert run()["published"] == 1
        now += timedelta(days=2)
        assert run()["attempted"] == 0  # Sunday remains Friday's completed session.
        now += timedelta(days=1)
        with sessions() as db:
            official_daily(db, basis=now.date(), receipt_at=now)
        assert run()["coverage_before"]["status_counts"] == {"stale": 1}
        with sessions() as db:
            row = db.get(TaiwanPriceMapSnapshot, ("2330", "daily"))
            assert row.basis_date == date(2026, 9, 14)
            previous = row.input_revision
            db.execute(update(MarketDailyPrice).values(close_price=101))
            db.commit()
        assert run()["published"] == 1
        corporate = "calendar-or-corporate-corrected"
        assert run()["published"] == 1
        parameters = replace(parameters, rsi_period=parameters.rsi_period + 1)
        assert run()["published"] == 1
        with sessions() as db:
            db.execute(update(TaiwanPriceMapSnapshot).values(methodology_version="outdated-methodology"))
            db.commit()
        assert run()["published"] == 1
        assert run()["attempted"] == 0
    with sessions() as db:
        row = db.get(TaiwanPriceMapSnapshot, ("2330", "daily"))
        assert row.input_revision > previous and row.corporate_revision == corporate
        assert row.parameter_revision == parameters.revision
        with patch("app.market.tw_price_map_screening.read_price_map_external_revision", return_value=corporate), \
                patch("app.market.tw_price_map_screening.get_technical_analysis_parameters", return_value=parameters):
            result = build_tw_price_map_screening_snapshot(db, parameters={"lane": "completed_daily"}, generated_at=now)
        assert result["expected_basis_date"] == now.date()
        assert result["rows"][0]["basis_date"] == now.date() and result["rows"][0]["current_price"] == 101


def test_source_health_updates_do_not_invalidate_geometry_but_source_semantics_do(sessions):
    path = Path(__file__).parents[1] / "alembic/versions/20261101_0097_tw_snapshot_source_revision.py"
    spec = importlib.util.spec_from_file_location("source_revision_regression", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sessions() as db:
        seed(db)
        with Operations.context(MigrationContext.configure(db.connection())):
            migration.downgrade()
        db.commit()
        initial = read_input_revisions(db, ["2330"])["2330"]
        db.execute(update(SourceRegistry).values(last_success_at=NOW))
        db.commit()
        assert read_input_revisions(db, ["2330"])["2330"] == initial + 2  # Reproduce 0087 OLD/NEW churn.
        with Operations.context(MigrationContext.configure(db.connection())):
            migration.upgrade()
        db.commit()
        publish(db)
        stable = read_input_revisions(db, ["2330"])["2330"]
        db.execute(update(SourceRegistry).values(last_success_at=NOW + timedelta(minutes=1), last_error_message="health only"))
        db.commit()
        assert read_input_revisions(db, ["2330"])["2330"] == stable
        db.execute(update(SourceRegistry).values(priority=SourceRegistry.priority))
        db.commit()
        assert read_input_revisions(db, ["2330"])["2330"] == stable
        db.execute(update(SourceRegistry).values(priority=SourceRegistry.priority + 1))
        db.commit()
        assert read_input_revisions(db, ["2330"])["2330"] > stable
        stable = read_input_revisions(db, ["2330"])["2330"]
        db.execute(update(SourceRegistry).values(reliability_level="official"))
        db.commit()
        assert read_input_revisions(db, ["2330"])["2330"] > stable
        assert "SNAPSHOT_REVISION_STALE" in scan(db)["missing"]
