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
        + timedelta(minutes=minutes, seconds=1)
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
            minutes=minute
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
        assert result.session_resolution[1].resolution_mode.value == "single_candidate"
        assert result.session_resolution[1].selected_candidate_id == (
            f"{FUGLE_INTRADAY_PROVIDER}:{FUGLE_INTRADAY_SOURCE}"
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
