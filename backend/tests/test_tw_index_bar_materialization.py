from __future__ import annotations

from datetime import date, datetime, timezone
import json

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
    TaiwanCurrentIndexSnapshot,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_materialization_transaction import (
    TaiwanBarMaterializationTransaction,
)
from app.market.tw_bar_materializer import materialize_index_minute_candidates
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_INDEX_CAPABILITY_ID,
    current_source_binding,
)
from app.market.tw_current_market_repository import TaiwanCurrentMarketRepository


TRADE_DATE = date(2026, 9, 1)


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def _event(
    db: Session,
    *,
    provider: str,
    source_name: str,
    event_at: datetime,
    close: float,
    index_id: str = "TAIEX",
) -> None:
    binding = current_source_binding(
        provider=provider,
        source=source_name,
        capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
    )
    assert binding is not None
    source = db.query(SourceRegistry).filter_by(source_name=source_name).first()
    if source is None:
        source = SourceRegistry(
            source_name=source_name,
            source_type=binding.source_type,
            category="market_data",
            enabled=True,
            priority=binding.descriptor.priority,
            parser_type=binding.parser_version,
            auth_type=binding.auth_type,
            reliability_level=binding.descriptor.authority.value,
        )
        db.add(source)
        db.flush()
    raw_text = (
        json.dumps({"channel": "indices", "data": {"symbol": "IX0001"}})
        if provider == "fugle_marketdata"
        else json.dumps({"index_id": index_id, "close": close})
    )
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=event_at.astimezone(timezone.utc),
        method="STREAM" if provider == "fugle_marketdata" else "GET",
        content_hash=f"{provider}:{event_at.isoformat()}:{close}",
        raw_text=raw_text,
        parser_version=binding.parser_version,
    )
    db.add(raw)
    db.flush()
    db.add(
        TaiwanCurrentIndexSnapshot(
            source_id=source.id,
            raw_result_id=raw.id,
            provider=provider,
            source=source_name,
            authority=binding.descriptor.authority.value,
            raw_contract_version=binding.parser_version,
            index_id=index_id,
            venue="TWSE" if index_id == "TAIEX" else "TPEX",
            trade_date=TRADE_DATE,
            event_at=event_at,
            received_at=event_at.astimezone(timezone.utc),
            fetched_at=event_at.astimezone(timezone.utc),
            session="continuous",
            close_value=close,
            price_change=close - (45_000 if index_id == "TAIEX" else 299),
            observation_state="available",
            value_semantics="current_index_snapshot",
            finalization="provisional",
            official=False,
            provisional=True,
        )
    )


def test_index_event_read_paginates_each_source_and_preserves_late_tail() -> None:
    db, engine = _db()
    try:
        for provider, source in (
            ("fugle_marketdata", "fugle_indices_stream"),
            ("twse_mis", "twse_mis_index_snapshot"),
        ):
            for minute in (0, 1, 2, 260, 269):
                _event(
                    db,
                    provider=provider,
                    source_name=source,
                    event_at=datetime(
                        2026,
                        9,
                        1,
                        9 + minute // 60,
                        minute % 60,
                        10,
                        tzinfo=TAIWAN_TZ,
                    ),
                    close=45_000 + minute,
                )
        db.commit()

        batch = TaiwanCurrentMarketRepository(db).read_market_index_series_rows(
            index_id="TAIEX",
            trade_date=TRADE_DATE,
            max_rows=2,
        )

        assert len(batch.rows) == 10
        assert "TW_INDEX_INTRADAY_ROW_BOUND_REACHED" not in batch.limitations
        tails = {
            (row.provider, row.source): row.event_at.astimezone(TAIWAN_TZ).time()
            for row in batch.rows
            if row.event_at.astimezone(TAIWAN_TZ).hour == 13
            and row.event_at.astimezone(TAIWAN_TZ).minute == 29
        }
        assert set(tails) == {
            ("fugle_marketdata", "fugle_indices_stream"),
            ("twse_mis", "twse_mis_index_snapshot"),
        }
    finally:
        db.close()
        engine.dispose()


def test_index_materializes_candidates_then_shared_resolver_composes_timestamps() -> None:
    db, engine = _db()
    try:
        # Exchange has 09:00 and 09:02; vendor has 09:01 and 09:02. If a
        # provider-side minute-hop existed, the persisted candidates would lose
        # their independent lineage. The shared resolver composes timestamps.
        for provider, source, minutes in (
            ("twse_mis", "twse_mis_index_snapshot", (0, 2)),
            ("fugle_marketdata", "fugle_indices_stream", (1, 2)),
        ):
            for minute in minutes:
                _event(
                    db,
                    provider=provider,
                    source_name=source,
                    event_at=datetime(
                        2026, 9, 1, 9, minute, 20, tzinfo=TAIWAN_TZ
                    ),
                    close=45_000 + minute,
                )
        _event(
            db,
            provider="twse_mis",
            source_name="twse_mis_index_snapshot",
            event_at=datetime(2026, 9, 1, 13, 27, tzinfo=TAIWAN_TZ),
            close=45_270,
        )
        _event(
            db,
            provider="twse_mis",
            source_name="twse_mis_index_snapshot",
            event_at=datetime(2026, 9, 1, 13, 30, tzinfo=TAIWAN_TZ),
            close=45_300,
        )
        db.commit()
        raw_count = db.query(RawFetchResult).count()

        batch = materialize_index_minute_candidates(
            db,
            index_id="TAIEX",
            trade_date=TRADE_DATE,
            as_of=datetime(2026, 9, 1, 9, 3, tzinfo=TAIWAN_TZ),
            page_size=1,
        )
        assert len(batch.candidates) == 4
        assert all(item.observation.start_at.hour == 9 for item in batch.candidates)
        assert all(
            item.observation.start_at.minute != 30
            or item.observation.start_at.hour != 13
            for item in batch.candidates
        )
        candidate_sources = {
            (
                item.observation.lineage.provider,
                item.observation.lineage.source,
            )
            for item in batch.candidates
        }
        assert candidate_sources == {
            ("fugle_marketdata", "fugle_indices_stream"),
            ("twse_mis", "twse_mis_index_snapshot"),
        }

        persistence = TaiwanBarMaterializationTransaction(
            db
        ).persist_materialized_bars(batch.candidates)
        assert persistence.receipts_written == 0
        assert persistence.observations_written == 4
        assert db.query(RawFetchResult).count() == raw_count
        assert db.query(MarketIntradayBar).count() == 4
        assert all(
            row.raw_result_id is None
            and row.component_raw_result_ids_json
            for row in db.query(MarketIntradayBarLineage).all()
        )

        read_statements: list[str] = []

        def capture_read(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            read_statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture_read)
        outward = TaiwanBarService(db).read_bars(
            instrument_id="TAIEX",
            interval="1m",
            from_time=datetime(2026, 9, 1, 9, 0, tzinfo=TAIWAN_TZ),
            to_time=datetime(2026, 9, 1, 9, 4, tzinfo=TAIWAN_TZ),
            requested_at=datetime(2026, 9, 1, 14, 0, tzinfo=TAIWAN_TZ),
        )
        event.remove(engine, "before_cursor_execute", capture_read)

        assert [bar.start_at.minute for bar in outward.bars] == [0, 1, 2]
        assert {
            (bar.lineage.provider, bar.lineage.source) for bar in outward.bars
        } == {
            ("fugle_marketdata", "fugle_indices_stream"),
            ("twse_mis", "twse_mis_index_snapshot"),
        }
        assert outward.session_resolution[0].selected_candidate_id is None
        component_receipt_reads = [
            statement
            for statement in read_statements
            if "FROM raw_fetch_result" in statement
        ]
        assert len(component_receipt_reads) <= 1
    finally:
        db.close()
        engine.dispose()


def test_tpex_uses_same_materialization_persistence_and_bar_service() -> None:
    db, engine = _db()
    try:
        for second, close in ((5, 300.0), (45, 301.5)):
            _event(
                db,
                provider="twse_mis",
                source_name="twse_mis_index_snapshot",
                event_at=datetime(
                    2026, 9, 1, 9, 0, second, tzinfo=TAIWAN_TZ
                ),
                close=close,
                index_id="TPEX",
            )
        db.commit()

        batch = materialize_index_minute_candidates(
            db,
            index_id="TPEX",
            trade_date=TRADE_DATE,
            as_of=datetime(2026, 9, 1, 9, 1, tzinfo=TAIWAN_TZ),
            page_size=1,
        )
        TaiwanBarMaterializationTransaction(db).persist_materialized_bars(
            batch.candidates
        )
        outward = TaiwanBarService(db).read_bars(
            instrument_id="TPEX",
            interval="1m",
            from_time=datetime(2026, 9, 1, 9, 0, tzinfo=TAIWAN_TZ),
            to_time=datetime(2026, 9, 1, 9, 2, tzinfo=TAIWAN_TZ),
            requested_at=datetime(2026, 9, 1, 9, 1, tzinfo=TAIWAN_TZ),
        )

        assert outward.instrument.symbol == "TPEX"
        assert outward.instrument.venue == "TPEX"
        assert len(outward.bars) == 1
        assert float(outward.bars[0].open_price) == 300.0
        assert float(outward.bars[0].close_price) == 301.5
        assert outward.bars[0].volume_status == "not_applicable"
    finally:
        db.close()
        engine.dispose()
