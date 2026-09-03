from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.tw_bar_contracts import TaiwanHistoryStatus
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_intraday_capabilities import (
    FUGLE_INTRADAY_PARSER_VERSION,
    FUGLE_INTRADAY_PROVIDER,
    FUGLE_INTRADAY_SOURCE,
    KGI_INTRADAY_PARSER_VERSION,
    KGI_INTRADAY_PROVIDER,
    KGI_INTRADAY_SOURCE,
    NSTOCK_INTRADAY_PARSER_VERSION,
    NSTOCK_INTRADAY_PROVIDER,
    NSTOCK_INTRADAY_SOURCE,
    YAHOO_INTRADAY_PARSER_VERSION,
    YAHOO_INTRADAY_PROVIDER,
    YAHOO_INTRADAY_SOURCE,
)


TAIPEI = timezone(timedelta(hours=8))


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        StockMaster(
            stock_id="2330",
            stock_name="TSMC",
            market="TWSE",
            instrument_type="stock",
        )
    )
    session.commit()
    return session, engine


def _seed_session(
    db: Session,
    *,
    trade_date: date,
    provider: str,
    source_name: str,
    parser_version: str,
    authority: str,
    minutes: int = 5,
    start_minute: int = 0,
    start_second: int = 0,
) -> None:
    source = db.query(SourceRegistry).filter_by(source_name=source_name).first()
    if source is None:
        source = SourceRegistry(
            source_name=source_name,
            source_type="stream",
            category="market_data",
            enabled=True,
            priority=5,
            parser_type=parser_version,
            auth_type="test",
            reliability_level=authority,
        )
        db.add(source)
        db.flush()
    fetched_at = (
        datetime.combine(trade_date, time(9, 0), TAIPEI)
        + timedelta(minutes=start_minute + minutes, seconds=1)
    ).astimezone(timezone.utc)
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=fetched_at,
        method="GET",
        status_code=200,
        content_type="application/json",
        content_hash=f"{provider}-{trade_date}",
        parser_version=parser_version,
    )
    db.add(raw)
    db.flush()
    for minute in range(minutes):
        start = datetime.combine(trade_date, time(9, 0), TAIPEI) + timedelta(
            minutes=start_minute + minute,
            seconds=start_second,
        )
        bar = MarketIntradayBar(
            source_id=source.id,
            provider=provider,
            stock_id="2330",
            market="TWSE",
            canonical_market="TW",
            venue="TWSE",
            instrument_type="stock",
            symbol="2330",
            interval="1m",
            bar_time=start,
            open_price=100 + minute,
            high_price=101 + minute,
            low_price=99 + minute,
            close_price=100.5 + minute,
            trade_volume=10 + minute,
            trade_value=1000 + minute,
            source=source_name,
        )
        db.add(bar)
        db.flush()
        db.add(
            MarketIntradayBarLineage(
                bar_id=bar.id,
                source_id=source.id,
                raw_result_id=raw.id,
                provider=provider,
                source=source_name,
                authority=authority,
                raw_contract_version=parser_version,
                event_at=start + timedelta(minutes=1),
                received_at=(
                    start + timedelta(minutes=1, seconds=1)
                ).astimezone(timezone.utc),
                fetched_at=raw.fetched_at,
                finalization="final",
                source_interval="1m",
            )
        )
    db.commit()


def test_multisession_read_resolves_each_session_then_derives_one_series() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 8, 31),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
        )
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=FUGLE_INTRADAY_PROVIDER,
            source_name=FUGLE_INTRADAY_SOURCE,
            parser_version=FUGLE_INTRADAY_PARSER_VERSION,
            authority="vendor",
        )

        result = TaiwanBarService(db).read_bars(
            instrument_id="2330",
            interval="5m",
            from_time=datetime(2026, 8, 31, 8, 59, tzinfo=TAIPEI),
            to_time=datetime(2026, 9, 1, 9, 10, tzinfo=TAIPEI),
            requested_at=datetime(2026, 9, 1, 9, 10, tzinfo=TAIPEI),
        )

        assert [item.trade_date for item in result.session_resolution] == [
            date(2026, 8, 31),
            date(2026, 9, 1),
        ]
        assert result.session_resolution[0].resolution_mode.value == "compose_by_timestamp"
        assert result.session_resolution[1].resolution_mode.value == "compose_by_timestamp"
        assert result.session_resolution[1].selected_candidate_id is None
        assert result.session_resolution[1].contributor_candidate_ids == (
            f"{FUGLE_INTRADAY_PROVIDER}:{FUGLE_INTRADAY_SOURCE}",
        )
        assert len(result.bars) == 2
        assert result.bars[0].start_at.date() == date(2026, 8, 31)
        assert result.bars[1].start_at.date() == date(2026, 9, 1)
        assert result.derived is True
        assert result.base_interval == "1m"
        assert result.identity.series_revision
    finally:
        db.close()
        engine.dispose()


def test_current_session_read_excludes_previous_session() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 8, 31),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
        )
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=FUGLE_INTRADAY_PROVIDER,
            source_name=FUGLE_INTRADAY_SOURCE,
            parser_version=FUGLE_INTRADAY_PARSER_VERSION,
            authority="vendor",
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )

        assert {item.start_at.date() for item in result.bars} == {
            date(2026, 9, 1)
        }
        assert [item.trade_date for item in result.session_resolution] == [
            date(2026, 9, 1)
        ]
        assert result.history.requested_from == datetime(
            2026, 9, 1, 9, 0, tzinfo=TAIPEI
        )
        assert result.history.requested_to == datetime(
            2026, 9, 1, 9, 5, tzinfo=TAIPEI
        )
        assert result.current_session_coverage is not None
        assert result.current_session_coverage.status.value == "complete_prefix"
        assert result.current_session_coverage.snapshot_phase.value == "ready"
        assert result.current_session_coverage.snapshot_bar_count == 5
        assert result.current_session_coverage.snapshot_available_from == datetime(
            2026, 9, 1, 9, 0, tzinfo=TAIPEI
        )
        assert result.current_session_coverage.snapshot_available_to == datetime(
            2026, 9, 1, 9, 5, tzinfo=TAIPEI
        )
        assert result.current_session_coverage.repair_recommended is False

        delta = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            limit=2,
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )
        assert len(delta.bars) == 2
        assert delta.current_session_coverage is not None
        assert (
            delta.current_session_coverage.snapshot_revision
            == result.current_session_coverage.snapshot_revision
        )
        assert delta.current_session_coverage.snapshot_bar_count == 5
        assert delta.identity.series_revision != result.identity.series_revision
    finally:
        db.close()
        engine.dispose()


def test_current_session_composes_baseline_with_kgi_tail_per_timestamp() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=NSTOCK_INTRADAY_PROVIDER,
            source_name=NSTOCK_INTRADAY_SOURCE,
            parser_version=NSTOCK_INTRADAY_PARSER_VERSION,
            authority="vendor",
            minutes=5,
        )
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
            minutes=2,
            start_minute=3,
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )

        assert [item.start_at.minute for item in result.bars] == [0, 1, 2, 3, 4]
        assert [item.lineage.provider for item in result.bars] == [
            NSTOCK_INTRADAY_PROVIDER,
            NSTOCK_INTRADAY_PROVIDER,
            NSTOCK_INTRADAY_PROVIDER,
            KGI_INTRADAY_PROVIDER,
            KGI_INTRADAY_PROVIDER,
        ]
        manifest = result.session_resolution[0]
        assert manifest.conflict_bucket_count == 2
        assert manifest.contributor_candidate_ids == (
            f"{NSTOCK_INTRADAY_PROVIDER}:{NSTOCK_INTRADAY_SOURCE}",
            f"{KGI_INTRADAY_PROVIDER}:{KGI_INTRADAY_SOURCE}",
        )
        assert (
            "PROVIDER_BUCKET_END_NORMALIZED_TO_CANONICAL_START"
            in result.limitations
        )
        assert (
            "PROVIDER_TOTAL_AMOUNT_CUMULATIVE_NOT_MINUTE_TURNOVER"
            in result.limitations
        )
    finally:
        db.close()
        engine.dispose()


def test_current_session_trailing_only_snapshot_remains_warming() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
            minutes=2,
            start_minute=3,
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )

        coverage = result.current_session_coverage
        assert coverage is not None
        assert coverage.status.value == "trailing_window"
        assert coverage.snapshot_phase.value == "warming"
        assert coverage.snapshot_reason_codes == (
            "TW_CHART_SNAPSHOT_TRAILING_ONLY",
        )
        assert coverage.snapshot_bar_count == 2
    finally:
        db.close()
        engine.dispose()


def test_current_session_sparse_snapshot_is_visible_as_degraded() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=NSTOCK_INTRADAY_PROVIDER,
            source_name=NSTOCK_INTRADAY_SOURCE,
            parser_version=NSTOCK_INTRADAY_PARSER_VERSION,
            authority="vendor",
            minutes=2,
        )
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
            minutes=2,
            start_minute=3,
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )

        coverage = result.current_session_coverage
        assert coverage is not None
        assert coverage.status.value == "sparse"
        assert coverage.snapshot_phase.value == "degraded"
        assert coverage.snapshot_reason_codes == (
            "TW_CHART_SNAPSHOT_SPARSE",
        )
        assert coverage.snapshot_bar_count == 4
        assert coverage.missing_bucket_count == 1
    finally:
        db.close()
        engine.dispose()


def test_current_session_sparse_snapshot_with_excessive_gaps_stays_warming() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=NSTOCK_INTRADAY_PROVIDER,
            source_name=NSTOCK_INTRADAY_SOURCE,
            parser_version=NSTOCK_INTRADAY_PARSER_VERSION,
            authority="vendor",
            minutes=1,
        )
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
            minutes=1,
            start_minute=4,
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )

        coverage = result.current_session_coverage
        assert coverage is not None
        assert coverage.status.value == "sparse"
        assert coverage.snapshot_phase.value == "warming"
        assert coverage.snapshot_reason_codes == (
            "TW_CHART_SNAPSHOT_SPARSE_EXCESSIVE_GAPS",
        )
    finally:
        db.close()
        engine.dispose()


def test_legacy_kgi_start_labeled_parser_rows_are_not_current_truth() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version="kgi.superpy.minute_kbars.v1",
            authority="broker",
            minutes=5,
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )

        assert result.bars == ()
        assert result.current_session_coverage is not None
        assert result.current_session_coverage.status.value == "missing"
        assert result.current_session_coverage.repair_recommended is True
    finally:
        db.close()
        engine.dispose()


def test_misaligned_persisted_intraday_rows_fail_closed() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=YAHOO_INTRADAY_PROVIDER,
            source_name=YAHOO_INTRADAY_SOURCE,
            parser_version=YAHOO_INTRADAY_PARSER_VERSION,
            authority="vendor",
            minutes=2,
            start_second=10,
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )

        assert result.bars == ()
        manifest = result.session_resolution[0]
        assert manifest.rejected_candidate_reasons == {
            f"{YAHOO_INTRADAY_PROVIDER}:{YAHOO_INTRADAY_SOURCE}": (
                "INTRADAY_BUCKET_NOT_MINUTE_ALIGNED",
            )
        }, manifest.model_dump()
    finally:
        db.close()
        engine.dispose()


def test_93_day_request_reports_warming_and_never_reads_legacy_1h_truth() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
        )
        source = db.query(SourceRegistry).filter_by(source_name=KGI_INTRADAY_SOURCE).one()
        db.add(
            MarketIntradayBar(
                source_id=source.id,
                provider=KGI_INTRADAY_PROVIDER,
                stock_id="2330",
                market="TWSE",
                canonical_market="TW",
                venue="TWSE",
                instrument_type="stock",
                symbol="2330",
                interval="1h",
                bar_time=datetime(2026, 6, 15, 9, 0, tzinfo=TAIPEI),
                open_price=999,
                high_price=999,
                low_price=999,
                close_price=999,
                source=KGI_INTRADAY_SOURCE,
            )
        )
        db.commit()

        result = TaiwanBarService(db).read_bars(
            instrument_id="2330",
            interval="1h",
            requested_at=datetime(2026, 9, 1, 14, 0, tzinfo=TAIPEI),
        )

        assert result.history.history_status is TaiwanHistoryStatus.WARMING_UP
        assert result.history.requested_coverage_satisfied is False
        assert "TW_CANONICAL_1M_HISTORY_INCOMPLETE" in result.limitations
        assert all(item.close_price != 999 for item in result.bars)
        assert all(item.lineage.source == "tw.bar.aggregate" for item in result.bars)
    finally:
        db.close()
        engine.dispose()


def test_bar_service_read_has_no_insert_update_delete_side_effect() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
        )
        mutations: list[str] = []

        @event.listens_for(engine, "before_cursor_execute")
        def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            verb = statement.lstrip().split(maxsplit=1)[0].upper()
            if verb in {"INSERT", "UPDATE", "DELETE"}:
                mutations.append(verb)

        TaiwanBarService(db).read_bars(
            instrument_id="2330",
            interval="1m",
            from_time=datetime(2026, 9, 1, 9, 0, tzinfo=TAIPEI),
            to_time=datetime(2026, 9, 1, 9, 10, tzinfo=TAIPEI),
            requested_at=datetime(2026, 9, 1, 9, 10, tzinfo=TAIPEI),
        )

        assert mutations == []
    finally:
        db.close()
        engine.dispose()


def test_bar_service_requires_qualified_trading_policy_for_complete_coverage(
    monkeypatch,
) -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
            minutes=265,
        )
        requested = {
            "instrument_id": "2330",
            "interval": "1m",
            "from_time": datetime(2026, 9, 1, 9, 0, tzinfo=TAIPEI),
            "to_time": datetime(2026, 9, 1, 14, 0, tzinfo=TAIPEI),
            "requested_at": datetime(2026, 9, 1, 14, 0, tzinfo=TAIPEI),
        }

        monkeypatch.setattr(
            "app.market.tw_bar_service.get_taiwan_disposition_status",
            lambda *_args, **_kwargs: {
                "cache_status": "missing",
                "is_active": False,
            },
        )
        unknown = TaiwanBarService(db).read_bars(**requested)
        assert unknown.history.requested_coverage_satisfied is False
        assert "DISPOSITION_CACHE_MISSING" in unknown.limitations

        monkeypatch.setattr(
            "app.market.tw_bar_service.get_taiwan_disposition_status",
            lambda *_args, **_kwargs: {
                "cache_status": "current",
                "is_active": False,
            },
        )
        continuous = TaiwanBarService(db).read_bars(**requested)
        assert continuous.history.requested_coverage_satisfied is True
        assert continuous.session_resolution[0].coverage_status is TaiwanHistoryStatus.READY
    finally:
        db.close()
        engine.dispose()
