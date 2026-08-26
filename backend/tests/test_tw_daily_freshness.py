from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.tw_daily_freshness import (
    read_taiwan_daily_freshness,
    read_taiwan_daily_freshness_batch,
)
from app.market_data.contracts import DatasetHealthStatus
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _source(db: Session, name: str) -> SourceRegistry:
    source = SourceRegistry(
        source_name=name,
        source_type="test",
        category="market_daily_price",
    )
    db.add(source)
    db.flush()
    return source


def _price(
    db: Session,
    *,
    source: SourceRegistry,
    stock_id: str,
    trade_date: date,
    complete: bool = True,
) -> None:
    raw = RawFetchResult(source_id=source.id, method="GET")
    db.add(raw)
    db.flush()
    db.add(
        MarketDailyPrice(
            source_id=source.id,
            raw_result_id=raw.id,
            stock_id=stock_id,
            stock_name=stock_id,
            trade_date=trade_date,
            open_price=100.0 if complete else None,
            high_price=101.0 if complete else None,
            low_price=99.0 if complete else None,
            close_price=100.0,
        )
    )


def test_daily_freshness_only_counts_complete_official_canonical_rows() -> None:
    db = _session()
    try:
        db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            )
        )
        official = _source(db, TWSE_DAILY_TRADING_SOURCE_NAME)
        compatibility = _source(db, "legacy_vendor_daily")
        _price(
            db,
            source=official,
            stock_id="2330",
            trade_date=date(2026, 8, 25),
        )
        _price(
            db,
            source=compatibility,
            stock_id="2330",
            trade_date=date(2026, 8, 26),
        )
        _price(
            db,
            source=official,
            stock_id="2330",
            trade_date=date(2026, 8, 26),
            complete=False,
        )
        db.commit()

        evidence = read_taiwan_daily_freshness(
            db,
            stock_id="2330",
            checked_at=datetime(2026, 8, 26, 16, 0, tzinfo=TAIPEI_TZ),
            expected_date=date(2026, 8, 25),
        )

        assert evidence.latest_date == date(2026, 8, 25)
        assert evidence.row_count == 1
        assert evidence.health.status is DatasetHealthStatus.HEALTHY
        assert evidence.health.dataset_id == "tw.daily.ohlcv"
    finally:
        db.close()


def test_daily_freshness_batch_returns_truthful_missing_and_stale_health() -> None:
    db = _session()
    try:
        db.add_all(
            [
                StockMaster(
                    stock_id=stock_id,
                    stock_name=stock_id,
                    market="TWSE",
                    instrument_type="stock",
                )
                for stock_id in ("2330", "2317")
            ]
        )
        official = _source(db, TWSE_DAILY_TRADING_SOURCE_NAME)
        _price(
            db,
            source=official,
            stock_id="2330",
            trade_date=date(2026, 8, 22),
        )
        db.commit()

        evidence = read_taiwan_daily_freshness_batch(
            db,
            stock_ids=["2330", "2317"],
            checked_at=datetime(2026, 8, 26, 16, 0, tzinfo=TAIPEI_TZ),
            expected_date=date(2026, 8, 25),
        )

        assert evidence["2330"].health.status is DatasetHealthStatus.STALE
        assert evidence["2317"].health.status is DatasetHealthStatus.MISSING
        assert evidence["2317"].latest_date is None
        assert evidence["2317"].row_count == 0
    finally:
        db.close()
