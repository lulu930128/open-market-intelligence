"""Real Alembic adoption and original Yahoo maintenance owner lifecycle."""

from datetime import timedelta
import json
import shutil

from alembic import command
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from app.db.migrations import create_alembic_config
from app.db.models import (
    MarketIntradayBar, MarketIntradayBarLineage, RawFetchResult, SourceRegistry,
    TaiwanTechnicalInputRevision, USIntradayObservationState,
)
from app.db.session import SessionLocal
from app.us_market.intraday_maintenance import (
    repair_us_yahoo_intraday_minute_integrity, rollback_us_yahoo_intraday_minute_repair,
)
from test_us_intraday_receipt_ordering import START, _batch, _persist, _state
from test_us_intraday_observation_state import _many_batch, _watermarks


TABLE = "us_intraday_observation_state"
TRIGGER = "tr_us_intraday_observation_state_bar_delete"


def _legacy_0098_fixture(path):
    config = create_alembic_config(f"sqlite:///{path}")
    command.upgrade(config, "20261030_0095")
    # Isolate the preexisting 0001/current-metadata -> 0096 duplicate-table
    # defect. This removes an EMPTY fixture table only, never runtime data.
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    with engine.begin() as c:
        assert c.exec_driver_sql("SELECT count(*) FROM market_daily_price_revision").scalar() == 0
        c.exec_driver_sql("DROP TABLE market_daily_price_revision")
    engine.dispose()
    command.upgrade(config, "20261101_0098")
    return config


@pytest.fixture(scope="module")
def migrated_template(tmp_path_factory):
    path = tmp_path_factory.mktemp("observation-schema") / "head.db"
    config = _legacy_0098_fixture(path)
    assert ScriptDirectory.from_config(config).get_heads() == ["20261104_0099"]
    command.upgrade(config, "head")  # Sidecar already exists from metadata.
    return path


@pytest.fixture
def migrated_engine(migrated_template, tmp_path):
    path = tmp_path / "lifecycle.db"
    shutil.copyfile(migrated_template, path)
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool, connect_args={"timeout": 30})
    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA busy_timeout=30000")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar() == "wal"
    yield engine
    engine.dispose()


def _assert_schema(engine):
    columns = inspect(engine).get_columns(TABLE)
    assert [c["name"] for c in columns] == ["bar_id", "observed_fetched_at", "observed_content_hash"]
    assert columns[2]["type"].length == 128
    assert [fk["referred_table"] for fk in inspect(engine).get_foreign_keys(TABLE)] == ["market_intraday_bar"]
    with engine.connect() as c:
        assert c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "20261104_0099"
        assert c.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:n"), {"n": TRIGGER}).scalar()


@pytest.mark.xfail(strict=True, raises=OperationalError,
                   reason="Inherited 0001/current metadata -> 0096 duplicate daily revision table; before 0099")
def test_empty_alembic_chain_to_head(tmp_path):
    try:
        command.upgrade(create_alembic_config(f"sqlite:///{tmp_path / 'empty.db'}"), "head")
    except OperationalError as exc:
        assert str(exc.orig) == "table market_daily_price_revision already exists"
        raise


def test_0099_handles_metadata_bootstrap(migrated_engine):
    _assert_schema(migrated_engine)


def test_0098_upgrade_preserves_legacy_rows_without_inventing_observations(tmp_path):
    path = tmp_path / "legacy.db"
    config = _legacy_0098_fixture(path)
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    # 0001 imports today's metadata. Remove only the new empty table in this
    # isolated fixture to reconstruct actual pre-0099 schema, not production.
    USIntradayObservationState.__table__.drop(engine)
    with SessionLocal(bind=engine) as db:
        row = MarketIntradayBar(provider="massive", stock_id="^GSPC", market="SP_INDEX",
            symbol="^GSPC", interval="1m", bar_time=START, close_price=100, source="legacy")
        db.add(row)
        db.commit()
        row_id = row.id
    command.upgrade(config, "head")
    _assert_schema(engine)
    with SessionLocal(bind=engine) as db:
        assert db.get(MarketIntradayBar, row_id).close_price == 100
        assert db.query(USIntradayObservationState).count() == 0
    engine.dispose()


def test_state_only_does_not_touch_generation_or_canonical(migrated_engine):
    _persist(migrated_engine, _batch(1, "100"))
    before = _state(migrated_engine)
    def generation():
        with SessionLocal(bind=migrated_engine) as db:
            return db.get(TaiwanTechnicalInputRevision, "^GSPC").intraday_generation
    original_generation = generation()
    _persist(migrated_engine, _batch(3, "100"))
    assert _state(migrated_engine) == before and generation() == original_generation
    assert _watermarks(migrated_engine)[0][1] == _batch(3, "100")[1].receipts[0].fetched_at.replace(tzinfo=None)


def test_fk_off_bulk_delete_cleanup_rollback_and_id_reuse(migrated_engine):
    _persist(migrated_engine, _many_batch(1, 2))
    before = _watermarks(migrated_engine)
    bar_id = before[0][0]
    with SessionLocal(bind=migrated_engine) as db:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 0
        db.query(MarketIntradayBar).filter_by(id=bar_id).delete(synchronize_session=False)
        assert [s.bar_id for s in db.query(USIntradayObservationState)] == [before[1][0]]
        db.rollback()
    assert _watermarks(migrated_engine) == before
    with SessionLocal(bind=migrated_engine) as db:
        db.query(MarketIntradayBar).filter_by(id=bar_id).delete(synchronize_session=False)
        db.commit()
        db.add(MarketIntradayBar(id=bar_id, provider="other", stock_id="OTHER", market="NASDAQ",
            symbol="OTHER", interval="1m", bar_time=START, close_price=5, source="fixture"))
        db.commit()
        assert db.get(USIntradayObservationState, bar_id) is None
        assert db.query(USIntradayObservationState).one().bar_id == before[1][0]


def _seed_yahoo(engine, *, canonical=True, states=True):
    with SessionLocal(bind=engine) as db:
        source = SourceRegistry(source_name="yahoo.chart.1m", source_type="api", category="market_data")
        db.add(source)
        db.flush()
        ids = []
        for second in ([0, 20] if canonical else [20, 40]):
            bar = MarketIntradayBar(provider="yahoo_chart", stock_id="AAPL", market="NASDAQ",
                symbol="AAPL", interval="1m", bar_time=START + timedelta(seconds=second),
                open_price=100, high_price=101, low_price=99, close_price=100, trade_volume=10,
                volume_status="observed", source="yahoo.chart.1m")
            raw = RawFetchResult(source_id=source.id, method="GET", content_hash=f"hash-{second}",
                parser_version="yahoo.chart.v8", fetched_at=START + timedelta(minutes=2))
            db.add_all([bar, raw])
            db.flush()
            db.add(MarketIntradayBarLineage(bar_id=bar.id, source_id=source.id, raw_result_id=raw.id,
                provider="yahoo_chart", source="yahoo.chart.1m", authority="vendor",
                raw_contract_version="yahoo.chart.v8", event_at=bar.bar_time,
                fetched_at=raw.fetched_at, received_at=raw.fetched_at, finalization="final", source_interval="1m"))
            if states:
                db.add(USIntradayObservationState(bar_id=bar.id,
                    observed_fetched_at=START + timedelta(minutes=3), observed_content_hash=f"new-hash-{second}"))
            ids.append(bar.id)
        db.commit()
        return ids


def test_yahoo_unchanged_survivor_apply_and_rollback_restore_exact_states(migrated_engine, tmp_path):
    survivor, deleted = _seed_yahoo(migrated_engine)
    before = _watermarks(migrated_engine)
    path = tmp_path / "repair.json"
    with SessionLocal(bind=migrated_engine) as db:
        result = repair_us_yahoo_intraday_minute_integrity(db, apply=True, audit_manifest_path=path)
        assert result["bar_rows_deleted"] == 1 and result["conflict_group_count"] == 0
    assert _watermarks(migrated_engine) == [before[0]]
    manifest = json.loads(path.read_text())
    assert manifest["groups"][0]["deleted"][0]["observation_state"]["bar_id"] == deleted
    with SessionLocal(bind=migrated_engine) as db:
        result = rollback_us_yahoo_intraday_minute_repair(db, apply=True, audit_manifest_path=path)
        assert result["status"] == "completed"
        assert {b.id for b in db.query(MarketIntradayBar)} == {survivor, deleted}
        assert db.query(MarketIntradayBarLineage).count() == 2
    assert _watermarks(migrated_engine) == before


@pytest.mark.parametrize("states", [False, True])
def test_yahoo_semantic_rekey_with_state_conflicts_legacy_remains_supported(migrated_engine, tmp_path, states):
    _seed_yahoo(migrated_engine, canonical=False, states=states)
    before = _watermarks(migrated_engine)
    with SessionLocal(bind=migrated_engine) as db:
        result = repair_us_yahoo_intraday_minute_integrity(db, apply=True, audit_manifest_path=tmp_path / "repair.json")
        if states:
            assert result["status"] == "partial" and result["conflict_group_count"] == 1
            assert result["conflicts"][0]["reason"] == "OBSERVATION_STATE_REKEY_REQUIRES_REVALIDATION"
            assert result["writes_performed"] == 0 and db.query(MarketIntradayBar).count() == 2
            assert result["next_after_group_id"] is not None
        else:
            assert result["status"] == "complete" and db.query(MarketIntradayBar).count() == 1
    assert _watermarks(migrated_engine) == before


@pytest.mark.parametrize("conflict", ["newer_state", "old_manifest", "reused_id"])
def test_yahoo_rollback_cannot_overwrite_later_evidence(migrated_engine, tmp_path, conflict):
    survivor, deleted = _seed_yahoo(migrated_engine, states=conflict != "old_manifest")
    path = tmp_path / "repair.json"
    with SessionLocal(bind=migrated_engine) as db:
        repair_us_yahoo_intraday_minute_integrity(db, apply=True, audit_manifest_path=path)
        if conflict == "reused_id":
            db.add(MarketIntradayBar(id=deleted, provider="other", stock_id="OTHER", market="NASDAQ",
                symbol="OTHER", interval="1m", bar_time=START, close_price=5, source="fixture"))
        else:
            state = db.get(USIntradayObservationState, survivor)
            if state is None:
                state = USIntradayObservationState(bar_id=survivor)
                db.add(state)
            state.observed_fetched_at = START + timedelta(minutes=5)
            state.observed_content_hash = "later-observation"
        db.commit()
    if conflict == "old_manifest":
        manifest = json.loads(path.read_text())
        for group in manifest["groups"]:
            for item in [group["survivor_before"], *group["deleted"]]:
                item.pop("observation_state")
        path.write_text(json.dumps(manifest))
    before = _watermarks(migrated_engine)
    with SessionLocal(bind=migrated_engine) as db:
        result = rollback_us_yahoo_intraday_minute_repair(db, apply=True, audit_manifest_path=path)
        assert result["status"] == "blocked" and result["writes_performed"] == 0
        assert ("DELETED_ROW_ID_REUSED" if conflict == "reused_id" else "OBSERVATION_STATE_CHANGED") in {
            c["reason"] for c in result["conflicts"]}
    assert _watermarks(migrated_engine) == before


def test_yahoo_failure_after_delete_rolls_back_trigger_cleanup(migrated_engine, tmp_path, monkeypatch):
    _seed_yahoo(migrated_engine)
    before = _watermarks(migrated_engine)
    with SessionLocal(bind=migrated_engine) as db:
        flush = db.flush
        def fail_after_delete(*args, **kwargs):
            deleted = bool(db.deleted)
            flush(*args, **kwargs)
            if deleted:
                assert db.query(USIntradayObservationState).count() == 1
                raise RuntimeError("after delete and trigger")
        monkeypatch.setattr(db, "flush", fail_after_delete)
        with pytest.raises(RuntimeError, match="after delete and trigger"):
            repair_us_yahoo_intraday_minute_integrity(db, apply=True, audit_manifest_path=tmp_path / "repair.json")
    assert _watermarks(migrated_engine) == before
