"""Repeat acquisition must not rewrite identical canonical bars or lineage."""
from dataclasses import replace
from datetime import datetime, timedelta
import json

import pytest
from sqlalchemy import event

from app.db.models import MarketIntradayBar, MarketIntradayBarLineage
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_materialization_transaction import TaiwanBarMaterializationTransaction
from app.market.tw_bar_materializer import materialize_index_minute_candidates
from app.market_data.contracts import BarFinalization
from test_tw_index_bar_materialization import _db, _event, TRADE_DATE


@pytest.mark.parametrize("reverse", [False, True])
def test_same_provider_source_collision_preserves_final_result_without_repeated_writes(reverse):
    db, engine = _db()
    try:
        for minute in (0, 1):
            for source, close in (("fugle_http_index_quote", 45000), ("fugle_indices_stream", 45002)):
                _event(db, provider="fugle_marketdata", source_name=source,
                    event_at=datetime(2026, 9, 1, 9, minute, 20, tzinfo=TAIWAN_TZ), close=close + minute)
        db.commit()
        candidates = materialize_index_minute_candidates(db, index_id="TAIEX", trade_date=TRADE_DATE,
            as_of=datetime(2026, 9, 1, 9, 2, tzinfo=TAIWAN_TZ)).candidates
        if reverse:
            candidates = tuple(reversed(candidates))
        owner = TaiwanBarMaterializationTransaction(db)
        first = owner.persist_materialized_bars(candidates)
        assert first.observations_written == 2
        assert first.limitations == ("TW_INDEX_LEGACY_STORAGE_KEY_COALESCED:2",)
        bars = db.query(MarketIntradayBar).order_by(MarketIntradayBar.bar_time).all()
        before = [(bar.id, bar.source, bar.close_price, bar.updated_at) for bar in bars]
        for bar in bars:
            last = [c for c in candidates if c.observation.start_at.replace(tzinfo=None) == bar.bar_time][-1]
            assert bar.source == last.observation.lineage.source
            assert bar.close_price == float(last.observation.close_price)
            lineage = db.query(MarketIntradayBarLineage).filter_by(bar_id=bar.id).one()
            assert lineage.source_id == last.source_id
            assert json.loads(lineage.component_raw_result_ids_json) == list(last.component_raw_result_ids)
        writes = []
        def capture(conn, cursor, sql, parameters, context, many):
            if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(sql)
        event.listen(engine, "before_cursor_execute", capture)
        repeated = owner.persist_materialized_bars(candidates)
        event.remove(engine, "before_cursor_execute", capture)
        assert repeated.observations_written == 0 and repeated.observations_unchanged == 2
        assert writes == []
        db.expire_all()
        assert [(bar.id, bar.source, bar.close_price, bar.updated_at) for bar in bars] == before
        invalid = replace(candidates[0], component_content_hashes=("invalid-superseded-receipt",))
        with pytest.raises(ValueError, match="digest mismatch"):
            owner.persist_materialized_bars((invalid, *candidates[1:]))
        assert [(bar.id, bar.source, bar.close_price, bar.updated_at) for bar in bars] == before
    finally:
        db.close()
        engine.dispose()


def _seed(db):
    _event(db, provider="twse_mis", source_name="twse_mis_index_snapshot",
        event_at=datetime(2026, 9, 1, 9, 0, 20, tzinfo=TAIWAN_TZ), close=45000)
    db.commit()
    return materialize_index_minute_candidates(db, index_id="TAIEX", trade_date=TRADE_DATE,
        as_of=datetime(2026, 9, 1, 9, 0, 30, tzinfo=TAIWAN_TZ)).candidates[0]


def test_identical_persisted_candidate_is_noop_after_sqlite_timezone_roundtrip():
    db, engine = _db()
    try:
        candidate = _seed(db)
        owner = TaiwanBarMaterializationTransaction(db)
        first = owner.persist_materialized_bars((candidate,))
        assert first.observations_written == 1
        db.expire_all()
        bar = db.query(MarketIntradayBar).one()
        lineage = db.query(MarketIntradayBarLineage).one()
        before = bar.updated_at, lineage.updated_at, bar.bar_time, lineage.event_at, lineage.received_at
        assert before[2].tzinfo is None
        writes = []

        def capture(conn, cursor, sql, parameters, context, many):
            if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(sql)

        event.listen(engine, "before_cursor_execute", capture)
        repeated = owner.persist_materialized_bars((candidate, candidate))
        event.remove(engine, "before_cursor_execute", capture)
        assert repeated.committed and repeated.observations_written == 0
        assert repeated.observations_unchanged == 2
        assert writes == []
        db.expire_all()
        assert (bar.updated_at, lineage.updated_at, bar.bar_time, lineage.event_at, lineage.received_at) == before
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("change", ["finalization", "receipt_time", "components", "price"])
def test_real_revision_remains_a_write_and_retains_component_identity(change):
    db, engine = _db()
    try:
        candidate = _seed(db)
        owner = TaiwanBarMaterializationTransaction(db)
        owner.persist_materialized_bars((candidate,))
        original = db.query(MarketIntradayBar).one()
        original_id = original.id
        obs = candidate.observation
        if change == "finalization":
            candidate = replace(candidate, observation=obs.model_copy(update={"finalization": BarFinalization.FINAL}))
        elif change == "receipt_time":
            candidate = replace(candidate, observation=obs.model_copy(update={"lineage":obs.lineage.model_copy(update={
                "received_at": obs.lineage.received_at + timedelta(seconds=1),
                "fetched_at": obs.lineage.fetched_at + timedelta(seconds=1)})}))
        elif change == "components":
            _event(db, provider="twse_mis", source_name="twse_mis_index_snapshot",
                event_at=datetime(2026, 9, 1, 9, 0, 25, tzinfo=TAIWAN_TZ), close=45000)
            db.commit()
            candidate = materialize_index_minute_candidates(db, index_id="TAIEX", trade_date=TRADE_DATE,
                as_of=datetime(2026, 9, 1, 9, 0, 30, tzinfo=TAIWAN_TZ)).candidates[0]
        else:
            candidate = replace(candidate, observation=obs.model_copy(update={
                "high_price":obs.high_price + 1, "close_price":obs.close_price + 1}))
        result = owner.persist_materialized_bars((candidate,))
        assert result.observations_written == 1 and result.observations_unchanged == 0
        db.expire_all()
        bar = db.query(MarketIntradayBar).one()
        lineage = db.query(MarketIntradayBarLineage).one()
        assert bar.id == original_id
        assert bar.close_price == float(candidate.observation.close_price)
        assert lineage.finalization == candidate.observation.finalization.value
        assert json.loads(lineage.component_raw_result_ids_json) == list(candidate.component_raw_result_ids)
        assert owner.persist_materialized_bars((candidate,)).observations_unchanged == 1
    finally:
        db.close()
        engine.dispose()


def test_noop_candidate_still_validates_evidence_and_rolls_back_later_change():
    db, engine = _db()
    try:
        candidate = _seed(db)
        owner = TaiwanBarMaterializationTransaction(db)
        owner.persist_materialized_bars((candidate,))
        final = replace(candidate, observation=candidate.observation.model_copy(update={"finalization":BarFinalization.FINAL}))
        invalid = replace(candidate, component_content_hashes=("wrong",))
        with pytest.raises(ValueError, match="digest mismatch"):
            owner.persist_materialized_bars((candidate, final, invalid))
        assert db.query(MarketIntradayBarLineage).one().finalization == "provisional"
        assert owner.persist_materialized_bars((candidate,)).observations_unchanged == 1
    finally:
        db.close()
        engine.dispose()
