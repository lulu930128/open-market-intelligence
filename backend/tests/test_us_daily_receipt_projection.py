"""Receipt projection must preserve eligibility without deferred SQL reads."""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session
from sqlalchemy.orm import Query

from app.db.models import Base, RawFetchResult, SourceRegistry, USDailyPrice
from app.market_data.candidate_repository import CandidateReadLimitExceeded
from app.market_data.contracts import InstrumentType
from app.us_market.daily_price_repository import USDailyBarRepository
from us_daily_receipt_fixture import NOW, seed_daily_receipts


@pytest.fixture
def engine():
    value = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(value)
    yield value
    value.dispose()


def read_without_payload(engine, query):
    statements, receipts = [], []

    def capture(conn, cursor, sql, params, context, many):
        statements.append(sql)

    def loaded(db, obj):
        if isinstance(obj, RawFetchResult):
            receipts.append(obj)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as db:
            event.listen(db, "loaded_as_persistent", loaded)
            result = USDailyBarRepository(db).load_daily_bars(query)
            for raw in receipts:
                assert set(inspect(raw).dict) - {"_sa_instance_state"} == {
                    "id", "source_id", "fetched_at", "parser_version", "content_hash",
                }
                before = len(statements)
                with pytest.raises(InvalidRequestError, match="raiseload"):
                    _ = raw.raw_text
                assert len(statements) == before
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements
    assert all(sql.lstrip().startswith("SELECT") for sql in statements)
    # A deferred receipt query would lack this JOIN and create row-count N+1.
    assert all("LEFT OUTER JOIN raw_fetch_result" in sql for sql in statements)
    assert all("raw_fetch_result.raw_text" not in sql for sql in statements)
    assert all("raw_fetch_result.error_message" not in sql for sql in statements)
    return result, len(statements)


@pytest.mark.parametrize("shared", [True, False])
@pytest.mark.parametrize("instrument_type", list((InstrumentType.STOCK, InstrumentType.ETF, InstrumentType.INDEX)))
def test_large_receipt_projection_preserves_lineage_fairness_and_instrument_semantics(engine, shared, instrument_type):
    with Session(engine) as db:
        query = seed_daily_receipts(db, shared=shared, days=8)
        instrument = query.instrument.model_copy(update={"instrument_type": instrument_type})
        query = query.model_copy(update={"instrument": instrument})
        if instrument_type is InstrumentType.INDEX:
            for row in db.scalars(select(USDailyPrice)):
                row.trade_volume, row.volume_unit, row.volume_status = None, None, "not_applicable"
            db.commit()
    result, _ = read_without_payload(engine, query)
    assert result.rows_examined == result.rows_accepted == 16
    assert result.rejections == ()
    assert {series.provider for series in result.series} == {"alpaca", "yahoo_chart"}
    for series in result.series:
        assert len(series.bars) == 8
        assert series.source == f"{series.provider}.daily.fixture"
        for bar, raw_id in zip(series.bars, series.raw_result_ids):
            assert bar.lineage.raw_receipt_id == f"raw_fetch_result:{raw_id}"
            assert bar.lineage.fetched_at == NOW - timedelta(days=1)
            assert bar.lineage.content_hash
            assert bar.lineage.raw_contract_version == "fixture.v1"
            assert bar.volume_status == ("not_applicable" if instrument_type is InstrumentType.INDEX else "observed")
            assert bar.start_at.tzinfo is not None
    with Session(engine) as db, pytest.raises(CandidateReadLimitExceeded):
        USDailyBarRepository(db).load_daily_bars(query.model_copy(update={"max_rows": 15}))


@pytest.mark.parametrize("mutation,reason", [
    ("hash", "US_DAILY_CONTENT_HASH_MISMATCH"),
    ("parser", "US_DAILY_PARSER_CONTRACT_MISMATCH"),
    ("source", "US_DAILY_SOURCE_RECEIPT_MISMATCH"),
    ("legacy", "US_DAILY_LEGACY_COMPAT_LINEAGE_REJECTED"),
    ("incomplete", "US_DAILY_LINEAGE_INCOMPLETE"),
    ("missing_raw", "US_DAILY_LINEAGE_INCOMPLETE"),
    ("missing_source", "US_DAILY_LINEAGE_INCOMPLETE"),
])
def test_projected_receipts_keep_canonical_rejection_reasons(engine, mutation, reason):
    with Session(engine) as db:
        query = seed_daily_receipts(db, days=2)
        raw = db.scalars(select(RawFetchResult).order_by(RawFetchResult.id)).first()
        source = db.get(SourceRegistry, raw.source_id)
        rows = list(db.scalars(select(USDailyPrice).where(USDailyPrice.raw_result_id == raw.id)))
        if mutation == "hash":
            raw.content_hash = "bad-hash"
        elif mutation == "parser":
            raw.parser_version = "fixture.v2"
        elif mutation == "source":
            raw.source_id += 1000
        elif mutation == "legacy":
            source.source_type = "compatibility_adapter"
        elif mutation == "incomplete":
            for row in rows:
                row.close_price = None
        elif mutation == "missing_raw":
            for row in rows:
                row.raw_result_id = None
            # Without a cutoff, the outer join exposes missing lineage for
            # rejection. With a cutoff SQL already excludes missing receipts.
            query = query.model_copy(update={"available_at": None})
        elif mutation == "missing_source":
            for row in rows:
                row.source_id = None
        db.commit()
    result, _ = read_without_payload(engine, query)
    assert result.rows_examined == 4
    assert result.rows_accepted == 2
    assert [r.reason_code for r in result.rejections] == [reason, reason]


def test_receipt_cutoff_parser_suffix_and_read_count_do_not_scale_with_days(engine):
    with Session(engine) as db:
        query = seed_daily_receipts(db, days=180, shared=True)
        for row in db.scalars(select(USDailyPrice)):
            row.raw_contract_version = "fixture.v1+canonical.v2"
        db.commit()
    result, count = read_without_payload(engine, query)
    assert result.rows_accepted == 360
    empty, empty_count = read_without_payload(engine, query.model_copy(update={"available_at": NOW - timedelta(days=2)}))
    assert empty.rows_examined == 0
    # Provider lanes and bounded overflow probes, independent of the 360 rows.
    assert count <= empty_count * 2


@pytest.mark.parametrize("consumer", ["repository", "daily", "truth", "bundle", "chart", "research"])
def test_full_receipt_and_metadata_only_have_identical_consumer_payloads(engine, monkeypatch, consumer):
    from fastapi.encoders import jsonable_encoder
    from app.us_market import market_truth
    from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
    from app.us_market.daily_ohlcv_chart import read_us_daily_ohlcv_chart
    from app.us_market.research_service import build_us_market_research

    class FullReceiptQuery(Query):
        """Test-only control: reproduce the pre-G3 Daily entity selection."""

        def options(self, *options):
            if [column["entity"] for column in self.column_descriptions] == [
                USDailyPrice, RawFetchResult, SourceRegistry,
            ]:
                return self
            return super().options(*options)

    with Session(engine) as db:
        query = seed_daily_receipts(db, days=180)
    # Only this per-evaluation UUID is intentionally nondeterministic. No market
    # field, lineage, revision, coverage, timestamp or limitation is normalized.
    monkeypatch.setattr(market_truth, "uuid4", lambda: "00000000-0000-0000-0000-000000000003")
    readers = {
        "repository": lambda db: USDailyBarRepository(db).load_daily_bars(query),
        "daily": lambda db: USDailyOhlcvPlatform(db).read(symbol="AAPL", bars=180, now=NOW).projection,
        "truth": lambda db: market_truth.read_us_market_truth_snapshot(db, symbol="AAPL", evaluated_at=NOW),
        "bundle": lambda db: market_truth.read_us_market_truth_bundle(db, symbol="AAPL", evaluated_at=NOW, include_session_summary=True),
        "chart": lambda db: read_us_daily_ohlcv_chart(db, symbol="AAPL", bars=180, now=NOW, include_intraday_overlay=True),
        "research": lambda db: build_us_market_research(db, symbol="AAPL", bars=260, now=NOW),
    }
    with Session(engine, query_cls=FullReceiptQuery) as db:
        before = jsonable_encoder(readers[consumer](db))
    with Session(engine) as db:
        after = jsonable_encoder(readers[consumer](db))
    assert after == before
