from datetime import date
from dataclasses import replace
from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.models import USShortVolumeDaily
from app.us_market.errors import USMarketDataFetchError
from app.us_market.fundamentals_store import upsert_us_short_volume_records, list_us_short_volumes
from app.us_market.schemas import USShortVolumeDailyRead
from app.us_market.sources import parse_finra_short_volume

HEADER = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
ROW = "20261104|AAPL|17472974.646448|171462|33182522.951729|B,Q,N\n"


def test_fractional_rows_and_share_classes_are_not_discarded_or_merged():
    records = parse_finra_short_volume(HEADER + ROW +
        "20261104|BF/A|1.000001|0|2|Q\n20261104|BF/B|3|0|4.123456|Q\n3\n",
        trade_date=date(2026, 11, 4))
    assert [row.symbol for row in records] == ["AAPL", "BF.A", "BF.B"]
    assert records[0].short_volume == Decimal("17472974.646448")
    assert records[0].total_volume == Decimal("33182522.951729")
    assert records[0].short_ratio == pytest.approx(0.5265716133720796)


def test_cqs_preferred_symbol_preserves_case_and_never_collides_with_common_stock():
    # Exact distinct rows observed in FINRA CNMSshvol20261105.txt.
    records = parse_finra_short_volume(HEADER +
        "20261105|TpC|85620.500000|352|158288.856100|B,Q,N\n"
        "20261105|TPC|250133.096802|60|489864.247579|B,Q,N\n2\n",
        trade_date=date(2026, 11, 5))
    by_symbol = {record.symbol: record for record in records}
    assert set(by_symbol) == {"TpC", "TPC"}
    assert by_symbol["TpC"].source_symbol == "TpC"
    assert by_symbol["TPC"].short_volume == Decimal("250133.096802")
    engine = create_engine("sqlite:///:memory:")
    USShortVolumeDaily.__table__.create(engine)
    try:
        with Session(engine) as db:
            upsert_us_short_volume_records(db, records)
            for requested, expected in (("TpC", "TpC"), ("TPC", "TPC"), ("tpc", "TPC")):
                rows = list_us_short_volumes(db, symbol=requested)
                assert len(rows) == 1 and rows[0].symbol == expected
                assert rows[0].short_volume == by_symbol[expected].short_volume
            upsert_us_short_volume_records(db, [replace(by_symbol["TPC"], provider="other")])
            assert [row.symbol for row in list_us_short_volumes(db, symbol="TpC")] == ["TpC"]
            assert list_us_short_volumes(db, symbol="TpC", provider="other") == []
    finally:
        engine.dispose()


def test_case_reconciliation_requires_same_payload_and_preserves_real_uppercase_identity():
    records = parse_finra_short_volume(HEADER +
        "20261104|TpA|11|0|20|Q\n20261104|TpC|30|0|40|Q\n"
        "20261104|TPC|50|0|60|Q\n20261104|ABCpA|70|0|80|Q\n4\n",
        trade_date=date(2026, 11, 4))
    by_symbol = {record.symbol: record for record in records}
    engine = create_engine("sqlite:///:memory:")
    USShortVolumeDaily.__table__.create(engine)
    try:
        with Session(engine) as db:
            upsert_us_short_volume_records(db, [
                replace(by_symbol["TpA"], symbol="TPA"),
                replace(by_symbol["TpC"], symbol="TPC"),
                replace(by_symbol["ABCpA"], symbol="ABCPA", raw_payload_hash="different-file"),
            ])
            result = upsert_us_short_volume_records(db, records, reconcile_legacy_symbols=True)
            assert result["reconciled_symbol_count"] == 1
            assert not list_us_short_volumes(db, symbol="TPA")
            assert list_us_short_volumes(db, symbol="TPC")[0].short_volume == Decimal(50)
            assert list_us_short_volumes(db, symbol="TpC")[0].short_volume == Decimal(30)
            assert list_us_short_volumes(db, symbol="ABCPA")[0].raw_payload_hash == "different-file"
    finally:
        engine.dispose()


def test_exact_duplicate_remains_an_error_instead_of_adding_or_dropping_volume():
    with pytest.raises(USMarketDataFetchError, match="duplicate symbol/date/market"):
        parse_finra_short_volume(HEADER + ROW + ROW + "2\n", trade_date=date(2026, 11, 4))


@pytest.mark.parametrize("payload", [
    "not a file", HEADER, HEADER + ROW + "2\n",
    HEADER + ROW + ROW,
    HEADER + ROW.replace("17472974.646448", "NaN"),
    HEADER + ROW.replace("17472974.646448", "-1"),
    HEADER + ROW.replace("17472974.646448", "0.1234567"),
    HEADER + ROW.replace("17472974.646448", "9007199254740991.000001"),
    HEADER + ROW.replace("17472974.646448", "1000000000000000000"),
    HEADER + ROW.replace("33182522.951729", "1"),
    HEADER + ROW.replace("20261104", "20261103"),
    HEADER + ROW + "20261104|BF||0||B,Q,N\n",
])
def test_malformed_file_fails_before_any_persistence(payload):
    with pytest.raises(USMarketDataFetchError):
        parse_finra_short_volume(payload, trade_date=date(2026, 11, 4))


def test_fractional_database_and_http_roundtrip_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    USShortVolumeDaily.__table__.create(engine)
    try:
        with Session(engine) as db:
            records = parse_finra_short_volume(HEADER + ROW)
            assert upsert_us_short_volume_records(db, records)["inserted_count"] == 1
            assert upsert_us_short_volume_records(db, records)["updated_count"] == 1
            rows = list_us_short_volumes(db, symbol="AAPL")
            assert len(rows) == 1
            assert rows[0].short_volume == records[0].short_volume
            assert rows[0].total_volume == records[0].total_volume
            public = USShortVolumeDailyRead.model_validate(rows[0]).model_dump(mode="json")
            assert public["short_volume"] == 17472974.646448
            assert public["total_volume"] == 33182522.951729
            classes = parse_finra_short_volume(HEADER +
                "20261104|BF/A|1.000001|0|2|Q\n20261104|BF/B|3|0|4.123456|Q\n")
            upsert_us_short_volume_records(db, classes)
            assert list_us_short_volumes(db, symbol="BF") == []
            for symbol in ("BF/B", "BF.B", "BF-B"):
                assert [row.symbol for row in list_us_short_volumes(db, symbol=symbol)] == ["BF.B"]
    finally:
        engine.dispose()


def test_migration_preserves_rows_indexes_and_refuses_lossy_downgrade():
    path = Path(__file__).parents[1] / "alembic/versions/20261106_0100_finra_fractional_volume.py"
    spec = importlib.util.spec_from_file_location("finra_fractional_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE us_short_volume_daily "
            "(id INTEGER PRIMARY KEY, symbol TEXT UNIQUE, short_volume BIGINT, "
            "short_exempt_volume BIGINT, total_volume BIGINT)"))
        connection.execute(text("CREATE INDEX ix_finra_symbol ON us_short_volume_daily(symbol)"))
        connection.execute(text("INSERT INTO us_short_volume_daily VALUES (7, 'OLD', 250, 0, 1000)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()  # Current-metadata baseline is safe.
            assert connection.execute(text("SELECT * FROM us_short_volume_daily")).one() == (7, "OLD", 250, 0, 1000)
            assert "ix_finra_symbol" in {item["name"] for item in inspect(connection).get_indexes("us_short_volume_daily")}
            connection.execute(text("UPDATE us_short_volume_daily SET short_volume=1.123456 WHERE id=7"))
            with pytest.raises(RuntimeError, match="fractional evidence"):
                migration.downgrade()
            assert connection.execute(text("SELECT short_volume FROM us_short_volume_daily")).scalar_one() == 1.123456
            connection.execute(text("UPDATE us_short_volume_daily SET short_volume=250 WHERE id=7"))
            migration.downgrade()
            assert connection.execute(text("SELECT short_volume FROM us_short_volume_daily")).scalar_one() == 250
    engine.dispose()


@pytest.mark.parametrize("reconcile", [False, True])
def test_symbol_reconciliation_is_opt_in_and_exact_payload_scoped(reconcile):
    engine = create_engine("sqlite:///:memory:")
    USShortVolumeDaily.__table__.create(engine)
    records = parse_finra_short_volume(HEADER +
        "20261104|ABC/W|1|0|2|Q\n20261104|KEEP/W|1|0|2|Q\n"
        "20261104|KEEP|4|0|8|Q\n20261104|HASH/W|1|0|2|Q\n4\n",
        trade_date=date(2026, 11, 4))
    by_symbol = {record.symbol: record for record in records}
    legacy = [replace(by_symbol["ABC.W"], symbol="ABC"),
              replace(by_symbol["KEEP.W"], symbol="KEEP"),
              replace(by_symbol["HASH.W"], symbol="HASH", raw_payload_hash="different"),
              replace(by_symbol["ABC.W"], symbol="ABC", trade_date=date(2026, 11, 3)),
              replace(by_symbol["ABC.W"], symbol="ABC", provider="another_provider")]
    try:
        with Session(engine) as db:
            upsert_us_short_volume_records(db, legacy)
            result = upsert_us_short_volume_records(db, records, reconcile_legacy_symbols=reconcile)
            assert result["reconciled_symbol_count"] == int(reconcile)
            assert db.query(USShortVolumeDaily).filter_by(symbol="ABC").count() == (2 if reconcile else 3)
            assert db.query(USShortVolumeDaily).filter_by(symbol="HASH").one().raw_payload_hash == "different"
            assert db.query(USShortVolumeDaily).filter_by(symbol="KEEP").one().short_volume == 4
            assert upsert_us_short_volume_records(db, records, reconcile_legacy_symbols=reconcile)["reconciled_symbol_count"] == 0
    finally:
        engine.dispose()


def test_symbol_reconciliation_rolls_back_retirement_and_inserts_on_failure(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    USShortVolumeDaily.__table__.create(engine)
    records = parse_finra_short_volume(HEADER + "20261104|ABC/W|1|0|2|Q\n1\n",
                                       trade_date=date(2026, 11, 4))
    try:
        with Session(engine) as db:
            upsert_us_short_volume_records(db, [replace(records[0], symbol="ABC")])
            def fail_commit():
                db.flush()
                raise RuntimeError("simulated commit failure")
            monkeypatch.setattr(db, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="simulated commit failure"):
                upsert_us_short_volume_records(db, records, reconcile_legacy_symbols=True)
            assert [(row.symbol, row.short_volume) for row in db.query(USShortVolumeDaily)] == [("ABC", Decimal("1"))]
    finally:
        engine.dispose()
