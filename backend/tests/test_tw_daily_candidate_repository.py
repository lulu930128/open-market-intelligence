from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketDailyPrice, RawFetchResult, SourceRegistry
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market_data.candidate_repository import (
    CandidateReadLimitExceeded,
    DailyBarCandidateQuery,
    MAX_DAILY_CANDIDATE_RANGE_DAYS,
)
from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
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
) -> MarketDailyPrice:
    return MarketDailyPrice(
        source_id=source.id,
        raw_result_id=raw.id,
        stock_id="2330",
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
