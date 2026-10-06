from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

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
from app.market import tw_bar_service as tw_bar_service_module
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
from app.market_data.contracts import (
    AuthorityClass,
    InstrumentKey,
    InstrumentType,
    Market,
    Quantity,
    QuantityUnit,
    QuoteObservation,
    SourceLineage,
    TradeObservationState,
)


TAIPEI = timezone(timedelta(hours=8))


def test_qualified_formal_close_component_preserves_close_without_making_1m_bar() -> None:
    trade_date = date(2026, 9, 3)
    close_at = datetime.combine(trade_date, time(13, 30), tzinfo=TAIPEI)
    requested_at = datetime.combine(trade_date, time(13, 34), tzinfo=TAIPEI)
    instrument = InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )
    quote = QuoteObservation(
        instrument=instrument,
        lineage=SourceLineage(
            provider="twse_mis",
            source="twse_mis_quote_depth",
            authority=AuthorityClass.EXCHANGE,
            raw_contract_version="test.v1",
            event_at=close_at,
            fetched_at=requested_at,
            content_hash="formal-close",
        ),
        trade_date=trade_date,
        trade_state=TradeObservationState.TRADE_OBSERVED,
        last_trade_price=Decimal("2390"),
        last_trade_quantity=Quantity(
            value=Decimal("1000"),
            unit=QuantityUnit.SHARE,
        ),
    )
    result = SimpleNamespace(resolved=SimpleNamespace(quote=quote))

    with (
        patch.object(
            tw_bar_service_module,
            "read_taiwan_session_close",
            return_value=result,
        ),
        patch.object(
            tw_bar_service_module,
            "project_taiwan_session_close",
            return_value={"available": True},
        ),
    ):
        component = tw_bar_service_module._qualified_formal_close_component(
            object(),
            instrument=instrument,
            trade_date=trade_date,
            requested_at=requested_at,
        )

    assert component is not None
    assert component.interval == "closing_match"
    assert component.end_at == close_at
    assert component.close_price == Decimal("2390")
    assert component.volume is not None
    assert component.volume.value == Decimal("1000")

    with (
        patch.object(tw_bar_service_module, "read_taiwan_latest_daily_evidence", return_value=SimpleNamespace(daily=None)),
        patch.object(tw_bar_service_module, "read_taiwan_session_close", return_value=result),
        patch.object(tw_bar_service_module, "project_taiwan_session_close", return_value={
            "available": True, "trade_date": trade_date, "price": 2390,
            "provider": "twse_mis", "source": "twse_mis_quote_depth", "event_time": close_at,
        }),
    ):
        events = TaiwanBarService(object()).read_current_session_presentation_events(
            series=SimpleNamespace(
                current_session_coverage=SimpleNamespace(trade_date=trade_date),
                bars=(), instrument=instrument,
            ), requested_at=requested_at,
        )

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "session_close_marker"
    assert event.event_at == close_at
    assert event.price == Decimal("2390")
    assert event.display_eligible is True
    assert event.technical_eligible is False
    assert event.official is False


def _db() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = spec_from_file_location("intraday_revision_migration", Path(__file__).parents[1] / "alembic/versions/20261006_0091_tw_intraday_revision.py")
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
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


def test_intraday_write_revision_invalidates_corrections_deletes_and_rollbacks() -> None:
    from app.market.intraday_repository import TaiwanIntradayBarRepository
    from app.db.models import TaiwanTechnicalInputRevision

    db, engine = _db()
    try:
        now = datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI)
        repository = TaiwanIntradayBarRepository(db)
        def revision():
            return repository.current_session_storage_revision(instrument_id="2330", from_time=now, to_time=now)
        initial = revision()
        _seed_session(db, trade_date=now.date(), provider=FUGLE_INTRADAY_PROVIDER,
                      source_name=FUGLE_INTRADAY_SOURCE, parser_version=FUGLE_INTRADAY_PARSER_VERSION, authority="vendor")
        seeded = revision()
        assert seeded != initial
        service = TaiwanBarService(db)
        before = service.read_current_session_bars(instrument_id="2330", requested_at=now)
        bar = db.query(MarketIntradayBar).first()
        # Preserve timestamps deliberately: generation tracks semantic writes.
        stamp = bar.updated_at
        db.query(MarketIntradayBar).filter_by(id=bar.id).update({"close_price": 100.75, "updated_at": stamp})
        db.commit()
        corrected = revision()
        assert corrected != seeded
        after = service.read_current_session_bars(instrument_id="2330", requested_at=now)
        assert after.read_diagnostics.snapshot_cache_status == "miss"
        assert after.bars[0].close_price != before.bars[0].close_price
        lineage = db.query(MarketIntradayBarLineage).filter_by(bar_id=bar.id).one()
        lineage.finalization = "provisional"
        db.flush()
        assert revision() != corrected
        db.rollback()
        assert revision() == corrected
        lineage = db.query(MarketIntradayBarLineage).filter_by(bar_id=bar.id).one()
        lineage.finalization = "provisional"
        db.commit()
        lineage_revision = revision()
        assert lineage_revision != corrected
        db.delete(lineage)
        db.commit()
        deleted_lineage = revision()
        assert deleted_lineage != lineage_revision
        db.delete(bar)
        db.commit()
        assert revision() != deleted_lineage
        # Intraday writes must not invalidate daily geometry.
        assert db.query(TaiwanTechnicalInputRevision.generation).filter_by(stock_id="2330").scalar() == 0
    finally:
        db.close()
        engine.dispose()


def test_current_snapshot_reuses_storage_across_minute_and_keeps_missing_truth() -> None:
    db, engine = _db()
    try:
        _seed_session(db, trade_date=date(2026, 9, 1), provider=FUGLE_INTRADAY_PROVIDER,
                      source_name=FUGLE_INTRADAY_SOURCE, parser_version=FUGLE_INTRADAY_PARSER_VERSION, authority="vendor")
        service = TaiwanBarService(db)
        first = service.read_current_session_bars(instrument_id="2330", requested_at=datetime(2026, 9, 1, 9, 5, 59, tzinfo=TAIPEI))
        with patch.object(service, "read_bars", side_effect=AssertionError("sub-minute coverage rebuilt")):
            same_minute = service.read_current_session_bars(instrument_id="2330", requested_at=datetime(2026, 9, 1, 9, 5, 59, 500000, tzinfo=TAIPEI))
        assert same_minute.read_diagnostics.snapshot_cache_status == "hit"
        assert same_minute.history.requested_to.microsecond == 500000
        with patch.object(tw_bar_service_module.MarketDataGateway, "resolve_bars", side_effect=AssertionError("unchanged storage reread")):
            second = service.read_current_session_bars(instrument_id="2330", requested_at=datetime(2026, 9, 1, 9, 6, tzinfo=TAIPEI))
        assert first.bars == second.bars
        assert first.current_session_coverage.missing_bucket_count == 0
        assert second.current_session_coverage.missing_bucket_count == 1
        assert second.current_session_coverage.status.value == "partial_prefix"
        assert second.current_session_coverage.repair_recommended
        assert second.identity.series_revision != first.identity.series_revision
        assert all(bucket.status.value != "verified_no_trade" for bucket in second.bucket_coverage)
        # Cache-only reuse executes no INSERT/UPDATE/DELETE or provider port.
        statements = []
        event.listen(engine, "before_cursor_execute", lambda _c, _cur, sql, _p, _ctx, _many: statements.append(sql))
        with patch.object(service, "read_bars", side_effect=AssertionError("warm snapshot rebuilt")):
            for _ in range(10):
                service.read_current_session_bars(instrument_id="2330", requested_at=datetime(2026, 9, 1, 9, 6, tzinfo=TAIPEI))
        assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
    finally:
        db.close()
        engine.dispose()


def test_snapshot_minute_boundary_reads_already_persisted_newly_eligible_bar() -> None:
    db, engine = _db()
    try:
        _seed_session(db, trade_date=date(2026, 9, 1), provider=FUGLE_INTRADAY_PROVIDER,
                      source_name=FUGLE_INTRADAY_SOURCE, parser_version=FUGLE_INTRADAY_PARSER_VERSION,
                      authority="vendor", minutes=6)
        service = TaiwanBarService(db)
        before = service.read_current_session_bars(instrument_id="2330", requested_at=datetime(2026, 9, 1, 9, 5, 59, tzinfo=TAIPEI))
        with tw_bar_service_module.taiwan_bar_read_scope():
            after = service.read_current_session_bars(instrument_id="2330", requested_at=datetime(2026, 9, 1, 9, 6, tzinfo=TAIPEI))
        assert len(before.bars) == 5
        assert len(after.bars) == 6
        assert before.read_diagnostics.storage_revision == after.read_diagnostics.storage_revision
    finally:
        db.close()
        engine.dispose()


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

        service = TaiwanBarService(db)
        result = service.read_current_session_bars(
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

        recent_snapshot_queries: list[str] = []
        event.listen(
            engine,
            "before_cursor_execute",
            lambda _conn, _cursor, statement, _parameters, _context, _many: (
                recent_snapshot_queries.append(statement)
            ),
        )
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
        revision_queries = [query for query in recent_snapshot_queries if query.lstrip().upper().startswith("SELECT")]
        assert len(revision_queries) == 2
        assert "intraday_generation" in revision_queries[-1]
        assert all("market_intraday_bar.open_price" not in query for query in revision_queries)
        assert delta.read_diagnostics.snapshot_cache_status == "hit"
        assert delta.read_diagnostics.final_series_revision == delta.identity.series_revision

        exact_snapshot_queries: list[str] = []
        event.listen(
            engine,
            "before_cursor_execute",
            lambda _conn, _cursor, statement, _parameters, _context, _many: (
                exact_snapshot_queries.append(statement)
            ),
        )
        exact_snapshot = service.read_current_session_snapshot_by_revision(
            instrument_id="2330",
            interval="1m",
            expected_snapshot_revision=(
                delta.current_session_coverage.snapshot_revision
            ),
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )
        assert len(exact_snapshot.bars) == 5
        assert (
            exact_snapshot.identity.series_revision
            == result.identity.series_revision
        )
        assert exact_snapshot_queries == []
    finally:
        db.close()
        engine.dispose()


def test_current_session_read_keeps_coverage_and_clamps_window_after_close() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
            minutes=5,
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 20, 0, tzinfo=TAIPEI),
        )

        assert result.history.requested_from == datetime(
            2026, 9, 1, 9, 0, tzinfo=TAIPEI
        )
        assert result.history.requested_to == datetime(
            2026, 9, 1, 13, 31, tzinfo=TAIPEI
        )
        assert result.current_session_coverage is not None
        assert result.current_session_coverage.snapshot_bar_count == 5
        assert result.session_resolution[0].current_session is True
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


def test_completed_missing_session_is_degraded_and_keeps_expected_coverage() -> None:
    db, engine = _db()
    try:
        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 5, 14, 0, tzinfo=TAIPEI),
        )
        coverage = result.current_session_coverage
        assert coverage is not None
        assert coverage.trade_date == date(2026, 9, 4)
        assert coverage.status.value == "missing"
        assert coverage.snapshot_phase.value == "degraded"
        assert coverage.expected_bucket_count == 265
        assert coverage.missing_bucket_count == 265
        assert coverage.repair_recommended is True
        assert coverage.snapshot_reason_codes == ("TW_CHART_SNAPSHOT_MISSING_POST_CLOSE",)
    finally:
        db.close()
        engine.dispose()


def test_regular_bar_phase_survives_ai_pipeline_without_execution_promotion() -> None:
    from app.ai.capability_contract import _canonical_intraday_value
    from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
    from app.ai.market_context.taiwan_projection import _compact_intraday_history
    from app.ai.realtime_contract import classify_observation

    db, engine = _db()
    try:
        _seed_session(db, trade_date=date(2026, 9, 1), provider=KGI_INTRADAY_PROVIDER,
                      source_name=KGI_INTRADAY_SOURCE, parser_version=KGI_INTRADAY_PARSER_VERSION,
                      authority="broker", minutes=5)
        now = datetime(2026, 9, 1, 9, 6, tzinfo=TAIPEI)
        series = TaiwanBarService(db).read_current_session_bars(instrument_id="2330", interval="1m", requested_at=now)
        history = project_taiwan_bar_series(series, session_scope="current_session")
        compact = _compact_intraday_history(history, point_limit=160)
        projected = _canonical_intraday_value({"series": {"1m": compact}})
        assert projected["market_phase"] == "regular"
        for surface in (history, compact, projected):
            assessment = classify_observation(surface, market="TW", realtime_policy="require_live", now=now)
            assert assessment["state"] == "live"
            assert assessment["execution_grade_usable"] is False
            historical = classify_observation(surface, market="TW", realtime_policy="require_live", now=now + timedelta(days=1))
            assert historical["state"] != "live"
            assert historical["execution_grade_usable"] is False
    finally:
        db.close()
        engine.dispose()


def test_complete_snapshot_survives_bar_limit_and_ai_projection_pipeline() -> None:
    from app.ai.capability_contract import _canonical_intraday_value
    from app.ai.data_quality_contract import build_quality_contract
    from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
    from app.ai.market_context.taiwan_projection import _compact_intraday_history

    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=NSTOCK_INTRADAY_PROVIDER,
            source_name=NSTOCK_INTRADAY_SOURCE,
            parser_version=NSTOCK_INTRADAY_PARSER_VERSION,
            authority="vendor",
            minutes=265,
        )
        for limit in (160, 500):
            series = TaiwanBarService(db).read_current_session_bars(
                instrument_id="2330", interval="1m", limit=limit,
                requested_at=datetime(2026, 9, 1, 14, 0, tzinfo=TAIPEI),
            )
            history = project_taiwan_bar_series(series, session_scope="current_session")
            compact = _compact_intraday_history(history, point_limit=limit)
            projected = _canonical_intraday_value({"series": {"1m": compact}})
            assert projected["market_phase"] == series.market_phase == "post_close"
            returned_count = min(limit, 265)
            assert projected["point_count"] == 265
            assert projected["returned_point_count"] == returned_count
            assert projected["truncated"] is (limit < 265)
            assert projected["series_coverage"]["missing_bucket_count"] == 0
            quality = build_quality_contract(
                canonical={
                    "ok": True, "request_status": "completed",
                    "target": {"type": "tw_stock", "market": "TW"},
                    "status": {"readiness": {"decision_required": False}},
                    "evidence": {},
                },
                selection={"output": "evidence_only"},
                manifest={"capabilities": [{
                    "capability": "intraday.bars", "domain": "price",
                    "slot": "intraday_bars", "required": True, "status": "available",
                    "returned_count": returned_count, "canonical_available_count": 265,
                    "truncated": projected["truncated"],
                }]},
                projected_data={"intraday.bars": projected},
                realtime_assessments={}, scope_type="stock",
            )["capabilities"]["intraday.bars"]
            assert quality["canonical_dataset_coverage"] == "complete"
            assert quality["consumer_projection_coverage"] == (
                "truncated" if limit < 265 else "complete"
            )
    finally:
        db.close()
        engine.dispose()


def test_legacy_current_session_and_derived_projection_share_full_snapshot() -> None:
    from app.market.tw_intraday_platform import read_taiwan_intraday_bars, project_taiwan_intraday_bars
    from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
    from app.market.intraday import get_market_intraday_history

    db, engine = _db()
    now = datetime(2026, 9, 1, 14, 0, tzinfo=TAIPEI)
    try:
        before = read_taiwan_intraday_bars(db, stock_id="2330", range_value="1d", requested_at=now)
        assert before.current_session_coverage.missing_bucket_count == 265
        _seed_session(
            db, trade_date=now.date(), provider=NSTOCK_INTRADAY_PROVIDER,
            source_name=NSTOCK_INTRADAY_SOURCE, parser_version=NSTOCK_INTRADAY_PARSER_VERSION,
            authority="vendor", minutes=265,
        )
        repaired = read_taiwan_intraday_bars(
            db, stock_id="2330", range_value="1d", requested_at=now,
            bypass_snapshot_cache=True,
        )
        points, metadata = project_taiwan_intraday_bars(db, repaired)
        assert len(points) == 265
        assert metadata["series_coverage"]["continuous_session_covered"] is True
        assert repaired.current_session_coverage.session_completed is True
        assert repaired.current_session_coverage.snapshot_revision != before.current_session_coverage.snapshot_revision
        current = TaiwanBarService(db).read_current_session_bars(instrument_id="2330", requested_at=now)
        assert current.current_session_coverage == repaired.current_session_coverage
        history = get_market_intraday_history(db, stock_id="2330", range_value="1d", requested_at=now)
        assert history["series_coverage"] == metadata["series_coverage"]
        derived = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330", interval="5m", limit=20, requested_at=now,
        )
        projected = project_taiwan_bar_series(derived, session_scope="current_session")
        assert projected["point_count"] == 53
        assert projected["returned_point_count"] == 20
        assert projected["truncated"] is True
        assert projected["series_coverage"]["expected_bucket_count"] == 265
        assert projected["series_coverage"]["missing_bucket_count"] == 0
        # A physical row with unknown finalization cannot fill a canonical slot.
        db.query(MarketIntradayBarLineage).first().finalization = "unknown"
        db.commit()
        unfinalized = read_taiwan_intraday_bars(
            db, stock_id="2330", range_value="1d", requested_at=now,
            bypass_snapshot_cache=True,
        )
        assert len(unfinalized.bars) == 264
        assert unfinalized.current_session_coverage.missing_bucket_count == 1
        _, metadata = project_taiwan_intraday_bars(db, unfinalized)
        assert metadata["series_coverage"]["continuous_session_covered"] is False
        assert project_taiwan_bar_series(unfinalized, session_scope="current_session")["is_partial"] is True
    finally:
        db.close()
        engine.dispose()


def test_current_session_mostly_complete_trailing_window_is_degraded() -> None:
    db, engine = _db()
    try:
        _seed_session(
            db,
            trade_date=date(2026, 9, 1),
            provider=KGI_INTRADAY_PROVIDER,
            source_name=KGI_INTRADAY_SOURCE,
            parser_version=KGI_INTRADAY_PARSER_VERSION,
            authority="broker",
            minutes=4,
            start_minute=1,
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 9, 5, tzinfo=TAIPEI),
        )

        coverage = result.current_session_coverage
        assert coverage is not None
        assert coverage.status.value == "trailing_window"
        assert coverage.snapshot_phase.value == "degraded"
        assert coverage.snapshot_reason_codes == (
            "TW_CHART_SNAPSHOT_TRAILING_WINDOW",
        )
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


def test_completed_session_sparse_snapshot_with_excessive_gaps_is_visible() -> None:
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
            start_minute=264,
        )

        result = TaiwanBarService(db).read_current_session_bars(
            instrument_id="2330",
            interval="1m",
            requested_at=datetime(2026, 9, 1, 13, 34, tzinfo=TAIPEI),
        )

        coverage = result.current_session_coverage
        assert coverage is not None
        assert coverage.status.value == "sparse"
        assert coverage.snapshot_phase.value == "degraded"
        assert coverage.snapshot_reason_codes == (
            "TW_CHART_SNAPSHOT_SPARSE_POST_CLOSE",
        )
        assert coverage.snapshot_bar_count == 2
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
