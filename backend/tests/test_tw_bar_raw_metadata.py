"""Production Session isolation; metadata SQL shape and semantic gates are separate."""
from dataclasses import replace
from datetime import datetime, timedelta
import json

import pytest
from sqlalchemy import event

from app.db.models import MarketIntradayBar, MarketIntradayBarLineage, RawFetchResult, SourceRegistry
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_materialization_transaction import TaiwanBarMaterializationTransaction
from app.market.tw_bar_materializer import materialize_index_minute_candidates
from test_tw_index_bar_materialization import _db, _event, TRADE_DATE


def _candidate(db):
    _event(db, provider="fugle_marketdata", source_name="fugle_indices_stream",
        event_at=datetime(2026, 9, 1, 9, 0, 20, tzinfo=TAIWAN_TZ), close=45000)
    db.commit()
    return materialize_index_minute_candidates(db, index_id="TAIEX", trade_date=TRADE_DATE,
        as_of=datetime(2026, 9, 1, 9, 2, tzinfo=TAIWAN_TZ)).candidates[0]


@pytest.mark.parametrize("component_count", [1, 401])
def test_raw_metadata_projection_and_chunk_queries_not_per_candidate(component_count):
    db, engine = _db()
    statements = []
    try:
        assert db.autoflush is False
        candidate = _candidate(db)
        rows = [RawFetchResult(source_id=candidate.source_id, parser_version="fugle.websocket.indices.v1",
            content_hash=f"component-{i}", raw_text="large fixture payload " * 1000)
            for i in range(component_count - 1)]
        db.add_all(rows)
        db.flush()
        candidate = replace(candidate,
            component_raw_result_ids=(*candidate.component_raw_result_ids, *(row.id for row in rows)),
            component_content_hashes=(*candidate.component_content_hashes, *(row.content_hash for row in rows)))
        db.commit()
        candidates = tuple(replace(candidate, observation=candidate.observation.model_copy(update={
            "start_at": candidate.observation.start_at + timedelta(minutes=i),
            "end_at": candidate.observation.end_at + timedelta(minutes=i)})) for i in range(12))

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append((statement, len(parameters)))

        event.listen(engine, "before_cursor_execute", capture)
        result = TaiwanBarMaterializationTransaction(db).persist_materialized_bars(candidates)
        event.remove(engine, "before_cursor_execute", capture)
        raw_reads = [(sql, count) for sql, count in statements if sql.lstrip().upper().startswith("SELECT")
            and "FROM raw_fetch_result" in sql]
        metrics = {"component_ids": component_count, "candidates": len(candidates),
            "raw_select_count": len(raw_reads), "total_statements": len(statements),
            "total_selects": sum(sql.lstrip().upper().startswith("SELECT") for sql, _ in statements),
            "max_raw_binds": max(count for _, count in raw_reads),
            "raw_select_columns": raw_reads[0][0].split("\nFROM", 1)[0]}
        print(json.dumps(metrics, sort_keys=True))
        assert len(raw_reads) == (component_count + 399) // 400
        for sql, count in raw_reads:
            assert count <= 400
            selected = sql.split("\nFROM", 1)[0]
            assert selected.count("raw_fetch_result.") == 4
            assert all(f"raw_fetch_result.{column}" in selected for column in ("id", "source_id", "parser_version", "content_hash"))
            assert "raw_text" not in sql
        # Content/atomicity checks do not depend on the SQL count assertions.
        assert result.committed and result.observations_written == 12
        assert db.query(MarketIntradayBar).count() == db.query(MarketIntradayBarLineage).count() == 12
        assert all(json.loads(row.component_raw_result_ids_json) == list(candidate.component_raw_result_ids)
            for row in db.query(MarketIntradayBarLineage).all())
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("fault", ["duplicate_id", "missing_id", "empty_ids", "source", "parser", "empty_hash", "hash"])
@pytest.mark.parametrize("invalid_first", [False, True])
def test_component_metadata_invalid_candidate_keeps_original_validation_order(fault, invalid_first):
    db, engine = _db()
    inserted_bars = []
    try:
        candidate = _candidate(db)
        raw_id = candidate.component_raw_result_ids[0]
        raw = db.get(RawFetchResult, raw_id)
        invalid = candidate
        message = "component lineage mismatch"
        if fault == "duplicate_id":
            invalid = replace(candidate, component_raw_result_ids=(raw_id, raw_id))
            message = "component evidence missing"
        elif fault == "missing_id":
            invalid = replace(candidate, component_raw_result_ids=(raw_id, raw_id + 999))
            message = "component evidence missing"
        elif fault == "empty_ids":
            invalid = replace(candidate, component_raw_result_ids=())
            message = "component evidence missing"
        elif fault == "hash":
            invalid = replace(candidate, component_content_hashes=("wrong",))
            message = "component digest mismatch"
        else:
            bad = RawFetchResult(source_id=raw.source_id, parser_version=raw.parser_version,
                content_hash=raw.content_hash, raw_text="fixture invalid evidence")
            if fault == "source":
                other = SourceRegistry(source_name="fixture-other", source_type="test", category="market_data")
                db.add(other)
                db.flush()
                bad.source_id = other.id
            elif fault == "parser":
                bad.parser_version = "wrong.parser"
            else:
                bad.content_hash = ""
            db.add(bad)
            db.flush()
            invalid = replace(candidate, component_raw_result_ids=(bad.id,))
        db.commit()

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO market_intraday_bar "):
                inserted_bars.append(True)

        event.listen(engine, "before_cursor_execute", capture)
        # Same bar key: a valid later winner cannot hide an invalid earlier item.
        batch = (invalid, candidate) if invalid_first else (candidate, invalid)
        owner = TaiwanBarMaterializationTransaction(db)
        with pytest.raises(ValueError, match=message):
            owner.persist_materialized_bars(batch)
        event.remove(engine, "before_cursor_execute", capture)
        assert len(inserted_bars) == int(not invalid_first)
        assert db.query(MarketIntradayBar).count() == db.query(MarketIntradayBarLineage).count() == 0
        # Reuse the owner after rollback: the lookup cannot outlive its invocation.
        assert owner.persist_materialized_bars((candidate, candidate)).committed
        assert db.query(MarketIntradayBar).count() == db.query(MarketIntradayBarLineage).count() == 1
    finally:
        db.close()
        engine.dispose()
