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
