"""SEC persistence keeps ordered upsert semantics with bounded key lookups."""
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import USSecCompanyFact
from app.us_market.fundamentals_store import upsert_us_sec_fact_records
from app.us_market.sources import USSecFactRecord


@pytest.fixture(params=[True, False], ids=["autoflush", "production_no_autoflush"])
def db(request):
    engine = create_engine("sqlite:///:memory:")
    USSecCompanyFact.__table__.create(engine)
    with Session(engine, autoflush=request.param) as session:
        yield session
    engine.dispose()


def fact(key, **changes):
    record = USSecFactRecord(
        fact_key=str(key), cik="0000000001", symbol="TEST", entity_name="Fixture",
        taxonomy="us-gaap", tag="Assets", label="Assets", description=None,
        unit="USD", fiscal_year=2026, fiscal_period="Q3", form="10-Q",
        filed_date=date(2026, 11, 1), period_start_date=None,
        period_end_date=date(2026, 9, 30), accession_number="fixture-accession",
        frame=None, value_numeric=100, value_text="100", source_url="https://example.test/facts",
    )
    return replace(record, **changes)


def test_large_mixed_upsert_has_bounded_selects_and_preserves_duplicate_counts(db):
    upsert_us_sec_fact_records(db, [fact("existing")])
    statements = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, len(parameters)))

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        records = [fact(i) for i in range(1001)] + [
            fact("existing", symbol=None, entity_name=None, value_numeric=200),
            fact(0, value_numeric=300, value_text="300"),
        ]
        assert upsert_us_sec_fact_records(db, records) == {
            "inserted_count": 1001, "updated_count": 2,
        }
        assert len(statements) == 3
        assert [count for _, count in statements] == [500, 500, 2]
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert db.query(USSecCompanyFact).count() == 1002
    assert db.query(USSecCompanyFact).filter_by(fact_key="0").one().value_numeric == 300
    existing = db.query(USSecCompanyFact).filter_by(fact_key="existing").one()
    assert (existing.symbol, existing.entity_name, existing.value_numeric) == ("TEST", "Fixture", 200)


def test_updates_preserve_fact_identity_and_clear_nullable_values(db):
    upsert_us_sec_fact_records(db, [fact("same")])
    upsert_us_sec_fact_records(db, [fact("same", taxonomy="changed", unit="shares",
        label=None, description=None, value_numeric=None, value_text="unknown", source_url=None)])
    row = db.query(USSecCompanyFact).one()
    assert (row.taxonomy, row.unit, row.tag) == ("us-gaap", "USD", "Assets")
    assert (row.label, row.value_numeric, row.value_text, row.source_url) == (None, None, "unknown", None)


def test_failed_commit_rolls_back_updates_and_inserts_and_session_recovers(db, monkeypatch):
    upsert_us_sec_fact_records(db, [fact("existing")])
    original_commit = db.commit

    def fail_after_flush():
        db.flush()
        raise RuntimeError("fixture commit failure")

    monkeypatch.setattr(db, "commit", fail_after_flush)
    records = [fact("existing", value_numeric=200), fact("new")]
    with pytest.raises(RuntimeError, match="fixture commit failure"):
        upsert_us_sec_fact_records(db, records)
    row = db.query(USSecCompanyFact).one()
    assert row.fact_key == "existing" and row.value_numeric == 100
    monkeypatch.setattr(db, "commit", original_commit)
    assert upsert_us_sec_fact_records(db, records) == {"inserted_count": 1, "updated_count": 1}


def test_preexisting_pending_fact_is_flushed_before_batch_lookup(db):
    db.add(USSecCompanyFact(**vars(fact("pending"))))
    assert upsert_us_sec_fact_records(db, [fact("pending", value_numeric=200)]) == {
        "inserted_count": 0, "updated_count": 1,
    }
    assert db.query(USSecCompanyFact).one().value_numeric == 200


def test_empty_upsert_preserves_zero_receipt(db):
    assert upsert_us_sec_fact_records(db, []) == {"inserted_count": 0, "updated_count": 0}
