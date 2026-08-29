from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.service import read_market_daily_snapshot
from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
from app.market.daily_ohlcv_platform import (
    build_taiwan_daily_cache_requirement,
    read_taiwan_official_daily,
)
from app.market_data.candidate_repository import (
    CandidateReadLimitExceeded,
    DailyBarCandidateQuery,
    MAX_DAILY_CANDIDATE_RANGE_DAYS,
)
from app.market_data.contracts import (
    BarSeriesCompositionStatus,
    InstrumentKey,
    InstrumentType,
    Market,
)
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
    TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source_and_raw(
    db: Session,
    *,
    source_name: str,
    parser_type: str,
    priority: int,
) -> tuple[SourceRegistry, RawFetchResult]:
    source = SourceRegistry(
        source_name=source_name,
        source_type="api",
        category="market_data",
        priority=priority,
        parser_type=parser_type,
        reliability_level="official",
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(
        source_id=source.id,
        fetched_at=datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc),
        content_hash=f"hash-{source.id}",
        parser_version=f"{parser_type}.v1",
        raw_text="[]",
    )
    db.add(raw)
    db.flush()
    return source, raw


def _query(
    *,
    venue: str = "TWSE",
    start_date: date = date(2026, 8, 20),
    end_date: date = date(2026, 8, 21),
    max_rows: int = 500,
) -> DailyBarCandidateQuery:
    return DailyBarCandidateQuery(
        instrument=InstrumentKey(
            market=Market.TW,
            symbol="2330",
            instrument_type=InstrumentType.STOCK,
            venue=venue,
        ),
        start_date=start_date,
        end_date=end_date,
        max_rows=max_rows,
    )


def _daily_row(
    *,
    source: SourceRegistry,
    raw: RawFetchResult,
    trade_date: date,
    open_price: float | None = 100,
    high_price: float | None = 110,
    low_price: float | None = 95,
    close_price: float | None = 105,
    trade_volume: int | None = 1_000_000,
    stock_id: str = "2330",
) -> MarketDailyPrice:
    return MarketDailyPrice(
        source_id=source.id,
        raw_result_id=raw.id,
        stock_id=stock_id,
        trade_date=trade_date,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        trade_volume=trade_volume,
    )


def test_candidate_range_supports_existing_monthly_research_but_stays_bounded() -> None:
    accepted = _query(
        start_date=date(2016, 6, 20),
        end_date=date(2026, 8, 25),
        max_rows=5000,
    )
    assert accepted.start_date == date(2016, 6, 20)

    with pytest.raises(
        ValidationError,
        match=rf"cannot exceed {MAX_DAILY_CANDIDATE_RANGE_DAYS} days",
    ):
        _query(
            start_date=date(1900, 1, 1),
            end_date=date(2026, 8, 25),
            max_rows=5000,
        )


def test_repository_reads_only_requested_venue_and_preserves_lineage(db: Session) -> None:
    twse, twse_raw = _source_and_raw(
        db,
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_daily_trading",
        priority=10,
    )
    tpex, tpex_raw = _source_and_raw(
        db,
        source_name=TPEX_DAILY_QUOTES_SOURCE_NAME,
        parser_type="tpex_daily_quotes",
        priority=40,
    )
    db.add_all(
        [
            _daily_row(source=twse, raw=twse_raw, trade_date=date(2026, 8, 20)),
            _daily_row(
                source=twse,
                raw=twse_raw,
                trade_date=date(2026, 8, 21),
                close_price=106,
            ),
            _daily_row(
                source=tpex,
                raw=tpex_raw,
                trade_date=date(2026, 8, 21),
                close_price=999,
            ),
        ]
    )
    db.commit()

    result = TaiwanOfficialDailyBarRepository(db).load_daily_bars(_query())

    assert result.rows_examined == 2
    assert result.rows_accepted == 2
    assert result.rejections == ()
    assert len(result.series) == 1
    series = result.series[0]
    assert series.provider == "twse_openapi"
    assert series.source == TWSE_DAILY_TRADING_SOURCE_NAME
    assert series.provider_priority == 10
    assert [bar.close_price for bar in series.bars] == [Decimal("105.0"), Decimal("106.0")]
    assert [bar.start_at.hour for bar in series.bars] == [9, 9]
    assert [bar.end_at.hour for bar in series.bars] == [13, 13]
    assert all(bar.end_at.minute == 30 for bar in series.bars)
    assert all(bar.lineage.cache_hit for bar in series.bars)
    assert all(bar.lineage.authority.value == "exchange" for bar in series.bars)
    assert all(bar.lineage.fetched_at is not None for bar in series.bars)
    assert all(bar.lineage.observation_id for bar in series.bars)
    assert series.bars[0].volume is not None
    assert series.bars[0].volume.value == Decimal("1000000")
    assert series.bars[0].volume.unit.value == "share"


def test_completed_reader_emits_single_lineage_candidates_for_canonical_composition(
    db: Session,
) -> None:
    openapi, openapi_raw = _source_and_raw(
        db,
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_daily_trading",
        priority=10,
    )
    rwd, rwd_raw = _source_and_raw(
        db,
        source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_rwd_daily_trading",
        priority=5,
    )
    trade_dates = [date(2026, 8, day) for day in (18, 19, 20, 21)]
    db.add(
        StockMaster(
            stock_id="2330",
            stock_name="TSMC",
            market="TWSE",
            instrument_type="stock",
            is_active=True,
        )
    )
    db.add_all(
        [
            _daily_row(
                source=openapi,
                raw=openapi_raw,
                trade_date=trade_date,
                close_price=100 + index,
            )
            for index, trade_date in enumerate(trade_dates)
        ]
        + [
            _daily_row(
                source=rwd,
                raw=rwd_raw,
                trade_date=trade_date,
                close_price=200 + index,
                high_price=210 + index,
            )
            for index, trade_date in enumerate(trade_dates[-2:])
        ]
    )
    db.commit()
    instrument = _query(
        start_date=trade_dates[0],
        end_date=trade_dates[-1],
        max_rows=4,
    ).instrument
    requirement = build_taiwan_daily_cache_requirement(
        instrument=instrument,
        from_date=trade_dates[0],
        to_date=trade_dates[-1],
        requested_at=datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc),
        max_rows=4,
    )

    result = TaiwanCompletedDailyCandidateReader(
        TaiwanOfficialDailyBarRepository(db)
    ).read_bar_candidates(requirement)

    assert len(result.candidates) == 2
    assert all(
        len({bar.lineage.provider for bar in candidate.bars}) == 1
        for candidate in result.candidates
    )
    assert result.limitations == ()

    outward = read_taiwan_official_daily(
        db,
        stock_id="2330",
        from_date=trade_dates[0],
        to_date=trade_dates[-1],
        requested_at=datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc),
        limit=4,
    )
    bars = outward.resolved.bars
    assert [bar.close_price for bar in bars] == [
        Decimal("100.0"),
        Decimal("101.0"),
        Decimal("200.0"),
        Decimal("201.0"),
    ]
    assert [bar.lineage.provider for bar in bars] == [
        "twse_openapi",
        "twse_openapi",
        "twse_rwd",
        "twse_rwd",
    ]
    assert (
        outward.resolved.composition.status
        is BarSeriesCompositionStatus.COMPOSED_WITH_CONFLICTS
    )
    assert outward.resolved.composition.filled_bucket_count == 2
    assert outward.resolved.composition.conflict_bucket_count == 2
    assert "OFFICIAL_DAILY_SERIES_RECONCILED" in outward.limitations
    assert "OFFICIAL_DAILY_SAME_DATE_CONFLICT_RESOLVED" in outward.limitations


def test_rejected_alternate_source_does_not_poison_covered_canonical_date(
    db: Session,
) -> None:
    openapi, openapi_raw = _source_and_raw(
        db,
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_daily_trading",
        priority=10,
    )
    rwd, rwd_raw = _source_and_raw(
        db,
        source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_rwd_daily_trading",
        priority=5,
    )
    trade_date = date(2026, 8, 21)
    db.add_all(
        [
            _daily_row(
                source=openapi,
                raw=openapi_raw,
                trade_date=trade_date,
                open_price=None,
            ),
            _daily_row(
                source=rwd,
                raw=rwd_raw,
                trade_date=trade_date,
            ),
        ]
    )
    db.commit()
    requirement = build_taiwan_daily_cache_requirement(
        instrument=_query(start_date=trade_date, end_date=trade_date).instrument,
        from_date=trade_date,
        to_date=trade_date,
        requested_at=datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc),
        max_rows=1,
    )

    result = TaiwanCompletedDailyCandidateReader(
        TaiwanOfficialDailyBarRepository(db)
    ).read_bar_candidates(requirement)

    assert len(result.candidates[0].bars) == 1
    assert result.candidates[0].bars[0].lineage.provider == "twse_rwd"
    assert result.rejections
    assert "MISSING_REQUIRED_OHLC" not in result.limitations
    assert result.dataset_health is not None
    assert result.dataset_health.status.value == "healthy"


def test_incomplete_and_inconsistent_rows_are_explicit_rejections(db: Session) -> None:
    source, raw = _source_and_raw(
        db,
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_daily_trading",
        priority=10,
    )
    db.add_all(
        [
            _daily_row(
                source=source,
                raw=raw,
                trade_date=date(2026, 8, 20),
                open_price=None,
            ),
            _daily_row(
                source=source,
                raw=raw,
                trade_date=date(2026, 8, 21),
                high_price=101,
                close_price=105,
            ),
        ]
    )
    db.commit()

    result = TaiwanOfficialDailyBarRepository(db).load_daily_bars(_query())

    assert result.rows_examined == 2
    assert result.rows_accepted == 0
    assert result.series == ()
    assert [item.reason_code for item in result.rejections] == [
        "MISSING_REQUIRED_OHLC",
        "INVALID_CANONICAL_BAR",
    ]
    assert result.rejections[0].missing_fields == ("open_price",)


def test_repository_fails_closed_instead_of_silently_truncating(db: Session) -> None:
    source, raw = _source_and_raw(
        db,
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_daily_trading",
        priority=10,
    )
    db.add_all(
        [
            _daily_row(source=source, raw=raw, trade_date=date(2026, 8, day))
            for day in (19, 20, 21)
        ]
    )
    db.commit()

    with pytest.raises(CandidateReadLimitExceeded, match="exceeded max_rows"):
        TaiwanOfficialDailyBarRepository(db).load_daily_bars(
            _query(
                start_date=date(2026, 8, 19),
                end_date=date(2026, 8, 21),
                max_rows=2,
            )
        )


def test_repository_read_does_not_commit_or_rollback(db: Session, monkeypatch) -> None:
    source, raw = _source_and_raw(
        db,
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_daily_trading",
        priority=10,
    )
    db.add(_daily_row(source=source, raw=raw, trade_date=date(2026, 8, 21)))
    db.commit()

    def forbidden_transaction() -> None:
        raise AssertionError("read repository must not own a transaction")

    monkeypatch.setattr(db, "commit", forbidden_transaction)
    monkeypatch.setattr(db, "rollback", forbidden_transaction)

    result = TaiwanOfficialDailyBarRepository(db).load_daily_bars(_query())

    assert result.rows_accepted == 1


def test_market_universe_returns_stock_only_rows_and_matching_coverage(
    db: Session,
) -> None:
    twse, twse_raw = _source_and_raw(
        db,
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_daily_trading",
        priority=10,
    )
    tpex, tpex_raw = _source_and_raw(
        db,
        source_name=TPEX_DAILY_QUOTES_SOURCE_NAME,
        parser_type="tpex_daily_quotes",
        priority=40,
    )
    trade_date = date(2026, 8, 21)
    db.add_all(
        [
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
                is_active=True,
            ),
            StockMaster(
                stock_id="6488",
                stock_name="GlobalWafers",
                market="TPEX",
                instrument_type="stock",
                is_active=True,
            ),
            StockMaster(
                stock_id="0050",
                stock_name="Yuanta Taiwan 50",
                market="TWSE",
                instrument_type="ETF",
                is_active=True,
            ),
        ]
    )
    db.add_all(
        [
            _daily_row(
                source=twse,
                raw=twse_raw,
                trade_date=trade_date,
                stock_id="2330",
            ),
            _daily_row(
                source=tpex,
                raw=tpex_raw,
                trade_date=trade_date,
                stock_id="6488",
            ),
            _daily_row(
                source=twse,
                raw=twse_raw,
                trade_date=trade_date,
                stock_id="0050",
            ),
        ]
    )
    db.commit()

    stocks = TaiwanOfficialDailyBarRepository(db).load_market_universe(
        trade_date=trade_date,
        include_etf=False,
    )
    stocks_and_etfs = TaiwanOfficialDailyBarRepository(db).load_market_universe(
        trade_date=trade_date,
        include_etf=True,
    )
    snapshot = read_market_daily_snapshot(
        db,
        trade_date=trade_date,
        include_etf=False,
    )

    assert [bar.instrument.symbol for bar in stocks.bars] == ["2330", "6488"]
    assert stocks.universe_count == 2
    assert dict(stocks.universe_count_by_market) == {"TWSE": 1, "TPEX": 1}
    assert dict(stocks.selected_count_by_market) == {"TWSE": 1, "TPEX": 1}
    assert [row.stock_id for row in snapshot.rows] == ["2330", "6488"]
    assert snapshot.universe_count == 2
    assert snapshot.universe_count_by_market == stocks.universe_count_by_market
    assert [bar.instrument.symbol for bar in stocks_and_etfs.bars] == [
        "0050",
        "2330",
        "6488",
    ]
    assert stocks_and_etfs.universe_count == 3
    assert dict(stocks_and_etfs.universe_count_by_market) == {
        "TWSE": 2,
        "TPEX": 1,
    }


def test_query_rejects_unbounded_or_inverted_ranges() -> None:
    with pytest.raises(ValidationError, match="start_date"):
        _query(start_date=date(2026, 8, 22), end_date=date(2026, 8, 21))
    with pytest.raises(
        ValidationError,
        match=rf"{MAX_DAILY_CANDIDATE_RANGE_DAYS}",
    ):
        _query(start_date=date(1900, 1, 1), end_date=date(2026, 8, 21))


def test_repository_rejects_cross_market_and_unknown_venue(db: Session) -> None:
    us_query = DailyBarCandidateQuery(
        instrument=InstrumentKey(
            market=Market.US,
            symbol="AAPL",
            instrument_type=InstrumentType.STOCK,
            venue="NASDAQ",
        ),
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 21),
    )
    with pytest.raises(ValueError, match="market=TW"):
        TaiwanOfficialDailyBarRepository(db).load_daily_bars(us_query)
    with pytest.raises(ValueError, match="venue=TWSE or TPEX"):
        TaiwanOfficialDailyBarRepository(db).load_daily_bars(_query(venue="UNKNOWN"))
