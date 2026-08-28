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
from app.market_data.eod_coverage import compute_eod_coverage, persist_eod_coverage
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)


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
    fetched_at: datetime | None = None,
) -> None:
    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
        fetched_at=fetched_at or datetime(
            trade_date.year,
            trade_date.month,
            trade_date.day,
            8,
        ),
    )
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
        _price(
            db,
            source=official,
            stock_id="2317",
            trade_date=date(2026, 8, 25),
            fetched_at=datetime(2026, 8, 27, 8, 0),
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
        assert evidence["2317"].storage_latest_date == date(2026, 8, 25)
    finally:
        db.close()


def test_daily_freshness_separates_storage_from_release_qualified_state() -> None:
    db = _session()
    try:
        db.add(
            StockMaster(
                stock_id="3711",
                stock_name="ASE Technology",
                market="TWSE",
                instrument_type="stock",
            )
        )
        official = _source(db, TWSE_DAILY_TRADING_SOURCE_NAME)
        _price(
            db,
            source=official,
            stock_id="3711",
            trade_date=date(2026, 8, 27),
            fetched_at=datetime(2026, 8, 27, 8, 0),
        )
        _price(
            db,
            source=official,
            stock_id="3711",
            trade_date=date(2026, 8, 28),
            fetched_at=datetime(2026, 8, 28, 6, 1),
        )
        db.commit()

        before_release = read_taiwan_daily_freshness(
            db,
            stock_id="3711",
            checked_at=datetime(2026, 8, 28, 14, 18, tzinfo=TAIPEI_TZ),
        )
        assert before_release.storage_latest_date == date(2026, 8, 28)
        assert before_release.latest_date == date(2026, 8, 27)
        assert before_release.health.status is DatasetHealthStatus.HEALTHY

        after_clock_only = read_taiwan_daily_freshness(
            db,
            stock_id="3711",
            checked_at=datetime(2026, 8, 28, 15, 20, tzinfo=TAIPEI_TZ),
        )
        assert after_clock_only.storage_latest_date == date(2026, 8, 28)
        assert after_clock_only.latest_date == date(2026, 8, 27)
        assert after_clock_only.health.status is DatasetHealthStatus.STALE

        later_expected_date = read_taiwan_daily_freshness(
            db,
            stock_id="3711",
            checked_at=datetime(2026, 9, 1, 16, 0, tzinfo=TAIPEI_TZ),
            expected_date=date(2026, 9, 1),
        )
        assert later_expected_date.storage_latest_date == date(2026, 8, 28)
        assert later_expected_date.latest_date == date(2026, 8, 27)

        today_row = (
            db.query(MarketDailyPrice)
            .filter(MarketDailyPrice.stock_id == "3711")
            .filter(MarketDailyPrice.trade_date == date(2026, 8, 28))
            .one()
        )
        released_receipt = RawFetchResult(
            source_id=official.id,
            method="GET",
            fetched_at=datetime(2026, 8, 28, 7, 18),
        )
        db.add(released_receipt)
        db.flush()
        today_row.raw_result_id = released_receipt.id
        db.commit()

        after_refresh = read_taiwan_daily_freshness(
            db,
            stock_id="3711",
            checked_at=datetime(2026, 8, 28, 15, 20, tzinfo=TAIPEI_TZ),
        )
        assert after_refresh.latest_date == date(2026, 8, 28)
        assert after_refresh.health.status is DatasetHealthStatus.HEALTHY
    finally:
        db.close()


def test_all_market_freshness_uses_full_market_checkpoint_not_cross_venue_max() -> None:
    db = _session()
    try:
        db.add_all(
            [
                StockMaster(
                    stock_id="2330",
                    stock_name="TSMC",
                    market="TWSE",
                    instrument_type="stock",
                ),
                StockMaster(
                    stock_id="6488",
                    stock_name="GlobalWafers",
                    market="TPEX",
                    instrument_type="stock",
                ),
            ]
        )
        twse = _source(db, TWSE_DAILY_TRADING_SOURCE_NAME)
        tpex = _source(db, TPEX_DAILY_QUOTES_SOURCE_NAME)
        _price(
            db,
            source=twse,
            stock_id="2330",
            trade_date=date(2026, 8, 26),
        )
        _price(
            db,
            source=tpex,
            stock_id="6488",
            trade_date=date(2026, 8, 27),
        )
        db.commit()
        checkpoint = persist_eod_coverage(
            db,
            compute_eod_coverage(
                db,
                market="TW",
                expected_trade_date=date(2026, 8, 27),
            ),
        )
        checkpoint.checked_at = datetime(2026, 8, 27, 8, 0)
        db.commit()

        evidence = read_taiwan_daily_freshness(
            db,
            checked_at=datetime(2026, 8, 27, 16, 0, tzinfo=TAIPEI_TZ),
            expected_date=date(2026, 8, 27),
        )

        assert evidence.latest_date == date(2026, 8, 27)
        assert evidence.health.status is DatasetHealthStatus.PARTIAL
        assert "FULL_MARKET_COVERAGE_CHECKPOINT_APPLIED" in evidence.limitations
        assert "FULL_MARKET_CURRENT_1_OF_2" in evidence.limitations
        assert "FULL_MARKET_STALE_1" in evidence.limitations
    finally:
        db.close()
