"""G0-G2 isolated source acceptance; no production DB, provider or runtime."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import socket
from unittest.mock import Mock

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import text, update

from app.db.models import (DataQualityCheck, MarketDailyPrice, MarketDailyPriceLineage,
    MarketDailyPriceRevision, RawFetchResult, SourceRegistry, StockMaster, TaiwanPriceMapSnapshot)
from app.jobs import taiwan_price_map_snapshot_scheduler as producer
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import TaiwanOfficialDailyPlatform
from app.market.daily_price_candidates import DailyBarCandidateQuery, TaiwanCompletedDailyCandidateReader
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.daily_price_transaction import TaiwanOfficialDailyTransaction
from app.market.price_map_snapshot_repository import read_input_revisions
from app.market.providers.tw_official_daily import TW_OFFICIAL_DAILY_DESCRIPTORS, TWSE_DAILY_RESOURCE_ID
from app.market_data.contracts import BarFinalization, InstrumentKey
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import AcquisitionSummary, RawFetchReceiptV1
from test_tw_official_daily_platform import FakeResponse, _refresh
from test_tw_price_map_screening import sessions, seed, payload, NOW, BASIS, publish

MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/20261101_0098_tw_daily_semantic_revision.py"


def migration():
    spec = importlib.util.spec_from_file_location("daily_semantic_revision", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def semantic_sessions(sessions, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(producer, "read_price_map_external_revision", lambda: "corp")
    return sessions


def acquire(db, *, at=NOW, close="100", symbol="2330", extra=""):
    body = json.dumps([dict(Date=BASIS.strftime("%Y%m%d"), Code=symbol, Name=symbol,
        OpeningPrice="100", HighestPrice="102", LowestPrice="98", ClosingPrice=close,
        TradeVolume="1000", TradeValue="100000", Transaction="20", Change="1", Note=extra)])
    executor = TaiwanOfficialDailyAcquisitionExecutor(
        fetchers={TWSE_DAILY_RESOURCE_ID: lambda route: FakeResponse(text=body)},
        clock=lambda: at, monotonic=lambda: 1.0)
    platform = TaiwanOfficialDailyPlatform(
        reader=TaiwanCompletedDailyCandidateReader(TaiwanOfficialDailyBarRepository(db)),
        transaction=TaiwanOfficialDailyTransaction(db), acquisition=executor,
        descriptors=tuple(d for d in TW_OFFICIAL_DAILY_DESCRIPTORS if d.resource_id == TWSE_DAILY_RESOURCE_ID))
    result = platform.refresh_instrument(_refresh(symbol=symbol, venue="TWSE", trade_date=BASIS)
        .model_copy(update={"requested_at": at}))
    assert result.persistence.committed
    return result.persistence


def generation(db):
    return read_input_revisions(db, ["2330"])["2330"]


def read_at(db, cutoff):
    instrument = InstrumentKey(market="TW", venue="TWSE", symbol="2330", instrument_type="stock")
    query = DailyBarCandidateQuery(instrument=instrument, start_date=BASIS, end_date=BASIS, max_rows=2)
    result = TaiwanOfficialDailyBarRepository(db, available_at=cutoff).load_daily_bars(query)
    return result.series[0].bars[0] if result.series else None


def test_repeated_eod_keeps_generation_raw_lineage_and_pit(semantic_sessions):
    with semantic_sessions() as db:
        first = acquire(db)
        before = generation(db)
        repeated = acquire(db, at=NOW + timedelta(minutes=1))
        assert generation(db) == before
        # Whole-venue response formatting/other metadata can change its hash
        # without changing this symbol's parsed canonical daily semantics.
        metadata = acquire(db, at=NOW + timedelta(minutes=2), extra="unrelated payload metadata")
        assert generation(db) == before
        assert repeated.observations_unchanged == metadata.observations_unchanged == 1
        assert db.query(RawFetchResult).count() == db.query(DataQualityCheck).count() == 3
        row = db.query(MarketDailyPrice).one()
        assert row.raw_result_id == db.query(MarketDailyPriceLineage).one().raw_result_id == metadata.raw_result_ids[0]
        assert db.query(MarketDailyPriceRevision).count() == 3
        correction = acquire(db, at=NOW + timedelta(minutes=3), close="101")
        assert generation(db) > before and correction.observations_written == 1
        for minute, receipt, close in [(0, first, 100), (1, repeated, 100), (2, metadata, 100), (3, correction, 101)]:
            bar = read_at(db, NOW + timedelta(minutes=minute, seconds=30))
            assert bar.close_price == close
            assert bar.lineage.raw_receipt_id == f"raw_fetch_result:{receipt.raw_result_ids[0]}"
        assert read_at(db, NOW - timedelta(seconds=1)) is None


@pytest.mark.parametrize("field,value", [
    ("open_price", 99), ("high_price", 103), ("low_price", 97), ("close_price", 101),
    ("trade_volume", 2000), ("trade_value", 200000), ("transaction_count", 21), ("price_change", 2),
    ("authority", "derived"), ("finalization", "corrected"), ("official", False),
    ("release_status", "pending"), ("reconciliation_status", "disputed"),
    ("venue", "TPEX"), ("canonical_market", "US"), ("instrument_type", "etf"),
    ("derivation_kind", "changed"), ("aggregation_version", "changed"),
])
def test_real_daily_semantics_invalidate_transactionally(semantic_sessions, field, value):
    with semantic_sessions() as db:
        acquire(db)
        before = generation(db)
        db.execute(update(MarketDailyPrice).values({field: value}))
        assert generation(db) > before
        db.rollback()
        assert generation(db) == before
        db.execute(update(MarketDailyPrice).values({field: value}))
        db.commit()
        assert generation(db) > before


@pytest.mark.parametrize("field,value", [("parser_version", "changed"), ("source_id", -1),
    ("status_code", 500), ("error_message", "invalid"), ("content_hash", None),
    ("fetched_at", datetime(2026, 9, 11, 6, tzinfo=timezone.utc))])
def test_changed_receipt_qualification_invalidates(semantic_sessions, field, value):
    with semantic_sessions() as db:
        acquire(db)
        row = db.query(MarketDailyPrice).one()
        old = db.get(RawFetchResult, row.raw_result_id)
        clone = RawFetchResult(**{c.name: getattr(old, c.name) for c in RawFetchResult.__table__.columns if c.name != "id"})
        setattr(clone, field, value)
        db.add(clone); db.commit()
        before = generation(db)
        row.raw_result_id = clone.id
        db.commit()
        assert generation(db) > before


def test_same_value_daily_and_lineage_updates_are_stable(semantic_sessions):
    with semantic_sessions() as db:
        acquire(db)
        before = generation(db)
        db.execute(update(MarketDailyPrice).values(close_price=MarketDailyPrice.close_price, updated_at=NOW))
        db.execute(update(MarketDailyPriceLineage).values(raw_result_id=MarketDailyPriceLineage.raw_result_id, updated_at=NOW))
        db.commit()
        assert generation(db) == before
        db.execute(update(MarketDailyPriceLineage).values(lineage_digest="actual lineage correction"))
        db.commit()
        assert generation(db) > before


def test_producer_durable_fairness_past_repeatedly_stale_prefix(semantic_sessions):
    with semantic_sessions() as db:
        seed(db, 6)
        publish(db, "2330")
        publish(db, "2331")
    calls = []
    for tick in range(4):
        with semantic_sessions() as db:
            db.execute(update(MarketDailyPrice).where(MarketDailyPrice.stock_id.in_(("2330", "2331")))
                .values(close_price=101 + tick))
            db.commit()
        report = producer.produce_taiwan_price_map_snapshots(session_factory=semantic_sessions,
            builder=lambda **kw: (calls.append(kw["stock_id"]) or payload(stock_id=kw["stock_id"])),
            clock=lambda: NOW + timedelta(minutes=tick), batch_size=2)
        assert report["attempted"] == report["published"] == 2
    assert set(calls) == {"2330", "2331", "2332", "2333", "2334", "2335"}
    # Existing claimed_at is the durable ordering hint, across fresh Sessions;
    # both stale prefix and not-computed suffix receive bounded work.
    assert calls.count("2330") >= 1 and calls.count("2331") >= 1


def test_0098_downgrade_restores_trigger_without_data_loss(semantic_sessions):
    with semantic_sessions() as db:
        db.add(StockMaster(stock_id="2330", stock_name="2330", market="TWSE", instrument_type="stock", is_active=True))
        db.commit()
        acquire(db)
        frozen = [(r.id, r.raw_result_id, r.close_price) for r in db.query(MarketDailyPriceRevision)]
        before = generation(db)
        with Operations.context(MigrationContext.configure(db.connection())):
            migration().downgrade()
        db.commit()
        db.execute(update(MarketDailyPrice).values(close_price=MarketDailyPrice.close_price))
        db.commit()
        assert generation(db) == before + 2
        db.execute(update(StockMaster).values(last_seen_at=NOW))
        db.commit()
        assert generation(db) == before + 4
        with Operations.context(MigrationContext.configure(db.connection())):
            migration().upgrade()
        db.commit()
        before = generation(db)
        db.execute(update(MarketDailyPrice).values(close_price=MarketDailyPrice.close_price))
        db.execute(update(StockMaster).values(last_seen_at=NOW + timedelta(minutes=1)))
        db.commit()
        assert generation(db) == before
        assert [(r.id, r.raw_result_id, r.close_price) for r in db.query(MarketDailyPriceRevision)] == frozen


def test_repeated_eod_during_claim_can_publish_and_only_corrected_stock_rebuilds(semantic_sessions):
    builds = []
    with semantic_sessions() as db:
        db.add_all([StockMaster(stock_id=s, stock_name=s, market="TWSE", instrument_type="stock", is_active=True)
            for s in ("2330", "2331")])
        db.commit()
        acquire(db)
        acquire(db, symbol="2331")
        original = read_input_revisions(db, ["2330", "2331"])
    def build(**kw):
        symbol = kw["stock_id"]
        builds.append(symbol)
        with semantic_sessions() as writer:
            acquire(writer, symbol=symbol, at=NOW + timedelta(seconds=10), extra="repeated EOD during build")
        return payload(stock_id=symbol)
    def run(builder=build):
        return producer.produce_taiwan_price_map_snapshots(session_factory=semantic_sessions,
            builder=builder, clock=lambda: NOW + timedelta(minutes=1))
    first = run()
    assert first["published"] == 2 and first["superseded"] == 0
    assert run()["attempted"] == 0
    with semantic_sessions() as db:
        assert read_input_revisions(db, ["2330", "2331"]) == original
        neighbor_token = db.get(TaiwanPriceMapSnapshot, ("2331", "daily")).claim_token
        acquire(db, at=NOW + timedelta(minutes=2), close="101")
    rebuilt = run(lambda **kw: (builds.append(kw["stock_id"]) or payload(stock_id=kw["stock_id"])))
    assert rebuilt["published"] == rebuilt["attempted"] == 1
    assert builds == ["2330", "2331", "2330"]
    with semantic_sessions() as db:
        assert db.get(TaiwanPriceMapSnapshot, ("2331", "daily")).claim_token == neighbor_token
        assert generation(db) > original["2330"]


@pytest.mark.parametrize("field,value", [("evidence_kind", "materialized"), ("source_interval", "5s"),
    ("materialization_version", "new"), ("component_content_hashes_json", '["changed"]'),
    ("component_raw_result_ids_json", '[123]')])
def test_real_lineage_semantics_invalidate(semantic_sessions, field, value):
    with semantic_sessions() as db:
        acquire(db)
        before = generation(db)
        db.execute(update(MarketDailyPriceLineage).values({field: value}))
        db.commit()
        assert generation(db) > before


def test_source_candidate_switch_and_raw_mutation_remain_invalidating(semantic_sessions):
    with semantic_sessions() as db:
        acquire(db)
        before = generation(db)
        # Candidate insert/delete and source semantics keep their existing guards.
        other = SourceRegistry(source_name="other official candidate", source_type="official", category="market")
        db.add(other); db.flush()
        row = MarketDailyPrice(stock_id="2330", source_id=other.id, trade_date=BASIS, close_price=100)
        db.add(row); db.commit()
        assert generation(db) > before
        before = generation(db)
        db.delete(row); db.commit()
        assert generation(db) > before
        before = generation(db)
        db.execute(update(SourceRegistry).values(priority=SourceRegistry.priority + 1)); db.commit()
        assert generation(db) > before
        before = generation(db)
        db.execute(update(RawFetchResult).values(content_hash="changed in place")); db.commit()
        assert generation(db) > before


def test_additive_alembic_schema_upgrade_and_downgrade_on_isolated_fixture(semantic_sessions):
    with semantic_sessions() as db:
        # 0096 is also real migration DDL here, not just ORM create_all shape.
        MarketDailyPriceRevision.__table__.drop(db.connection())
        path = MIGRATION_PATH.with_name("20261031_0096_taiwan_daily_revisions.py")
        spec = importlib.util.spec_from_file_location("pit_schema_migration", path)
        pit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pit)
        with Operations.context(MigrationContext.configure(db.connection())):
            pit.upgrade()
        config = Config()
        config.set_main_option("script_location", str(MIGRATION_PATH.parents[1]))
        config.attributes.update(connection=db.connection(), database_url="sqlite://")
        graph = ScriptDirectory.from_config(config)
        assert graph.get_current_head() == migration().revision
        assert graph.get_revision(migration().revision).down_revision == "20261101_0097"
        command.stamp(config, "20261101_0097")
        command.upgrade(config, "head")
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261101_0098"
        db.commit()
        acquire(db)
        before = generation(db)
        acquire(db, at=NOW + timedelta(minutes=1))
        assert generation(db) == before
        counts = (db.query(RawFetchResult).count(), db.query(MarketDailyPriceRevision).count())
        config.attributes["connection"] = db.connection()
        command.downgrade(config, "20261101_0097")
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261101_0097"
        assert (db.query(RawFetchResult).count(), db.query(MarketDailyPriceRevision).count()) == counts
        command.upgrade(config, "head")
        db.commit()
        assert generation(db) == before


def test_same_raw_content_finality_correction_retains_original_pit(semantic_sessions):
    with semantic_sessions() as db:
        first = acquire(db)
        original = read_at(db, NOW)
        raw = db.get(RawFetchResult, first.raw_result_ids[0])
        before = generation(db)
        later = NOW + timedelta(minutes=2)
        receipt = RawFetchReceiptV1(provider=original.lineage.provider, source=original.lineage.source,
            resource_id=TWSE_DAILY_RESOURCE_ID, fetched_at=later, method="GET", status_code=200,
            content_hash=raw.content_hash, raw_text=raw.raw_text, parser_version=raw.parser_version)
        result = TaiwanOfficialDailyTransaction(db).persist_bar_acquisition(
            _refresh(symbol="2330", venue="TWSE", trade_date=BASIS).model_copy(update={"requested_at": later}),
            BarAcquisitionResult(summary=AcquisitionSummary(attempted=True, status="completed"),
                observations=(original.model_copy(update={"finalization": BarFinalization.CORRECTED}),),
                receipts=(receipt,)))
        assert result.observations_written == 1 and result.observations_unchanged == 0
        assert generation(db) > before
        assert read_at(db, later).finalization == "corrected"
        assert read_at(db, NOW + timedelta(seconds=30)).finalization == "final"


@pytest.mark.parametrize("writer", ["sync", "upsert"])
def test_real_stock_master_seen_only_writers_do_not_invalidate(semantic_sessions, monkeypatch, writer):
    from app.stocks import service
    with semantic_sessions() as db:
        seed(db)
        publish(db)
        before = generation(db)
        token = db.get(TaiwanPriceMapSnapshot, ("2330", "daily")).claim_token
        for minute in (1, 2):
            seen = (NOW + timedelta(minutes=minute)).astimezone(timezone.utc)
            monkeypatch.setattr(service, "utc_now", lambda: seen)
            if writer == "sync":
                assert service.sync_stocks_from_market_daily(db)["updated_count"] == 1
            else:
                row = db.query(MarketDailyPrice).one()
                service._upsert_stock_master_from_market_daily_row(db, stock_id=row.stock_id,
                    stock_name=row.stock_name, source_id=row.source_id)
                db.commit()
            assert db.query(StockMaster).one().last_seen_at.replace(tzinfo=timezone.utc) == seen.astimezone(timezone.utc)
            assert generation(db) == before
        assert db.get(TaiwanPriceMapSnapshot, ("2330", "daily")).claim_token == token


@pytest.mark.parametrize("field,value", [("stock_id", "9999"), ("market", "TPEX"),
    ("instrument_type", "etf"), ("is_active", False), ("stock_name", "corrected name"),
    ("first_seen_at", datetime(2026, 1, 1, tzinfo=timezone.utc))])
def test_stock_identity_and_status_changes_still_invalidate(semantic_sessions, field, value):
    with semantic_sessions() as db:
        seed(db)
        before = generation(db)
        db.execute(update(StockMaster).values({field: value}))
        db.commit()
        assert generation(db) > before
        if field == "stock_id":
            assert read_input_revisions(db, ["9999"])["9999"] > 0


def test_producer_preserves_configured_timeframe_order_with_durable_progress(semantic_sessions):
    with semantic_sessions() as db:
        seed(db, 2)
    calls = []
    def build(**kw):
        calls.append((kw["stock_id"], kw["timeframe"]))
        return {**payload(stock_id=kw["stock_id"]), "structure_timeframe": kw["timeframe"]}
    for _ in range(4):
        result = producer.produce_taiwan_price_map_snapshots(session_factory=semantic_sessions,
            builder=build, clock=lambda: NOW, batch_size=1, timeframes=("weekly", "daily"))
        assert result["attempted"] == result["published"] == 1
    assert calls == [("2330", "weekly"), ("2330", "daily"), ("2331", "weekly"), ("2331", "daily")]
