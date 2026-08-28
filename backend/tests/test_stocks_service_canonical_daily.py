from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    StockProfile,
)
from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
from app.stocks.service import get_latest_stock_market_cap


def test_latest_market_cap_uses_release_qualified_daily_evidence() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            daily_source = SourceRegistry(
                source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
                source_type="official",
                category="market_daily_price",
                reliability_level="official",
            )
            profile_source = SourceRegistry(
                source_name="twse_company_profile_test",
                source_type="official",
                category="company_profile",
                reliability_level="official",
            )
            db.add_all([daily_source, profile_source])
            db.flush()
            daily_raw = RawFetchResult(
                source_id=daily_source.id,
                fetched_at=datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc),
                method="GET",
                content_hash="market-cap-daily",
                parser_version="market-cap-test-v1",
            )
            profile_raw = RawFetchResult(
                source_id=profile_source.id,
                fetched_at=datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc),
                method="GET",
                content_hash="market-cap-profile",
                parser_version="market-cap-profile-test-v1",
            )
            premature_raw = RawFetchResult(
                source_id=daily_source.id,
                fetched_at=datetime(2026, 6, 16, 1, 0, tzinfo=timezone.utc),
                method="GET",
                content_hash="market-cap-premature-daily",
                parser_version="market-cap-test-v1",
            )
            db.add_all([daily_raw, profile_raw, premature_raw])
            db.flush()
            db.add(
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=True,
                )
            )
            db.add(
                StockProfile(
                    source_id=profile_source.id,
                    raw_result_id=profile_raw.id,
                    report_date=date(2026, 6, 15),
                    stock_id="2330",
                    company_name="台積電",
                    market="TWSE",
                    issued_shares=10,
                )
            )
            db.add_all(
                [
                    MarketDailyPrice(
                        source_id=daily_source.id,
                        raw_result_id=daily_raw.id,
                        trade_date=date(2026, 6, 15),
                        stock_id="2330",
                        stock_name="台積電",
                        open_price=99,
                        high_price=102,
                        low_price=98,
                        close_price=100,
                        trade_volume=1_000,
                    ),
                    MarketDailyPrice(
                        source_id=daily_source.id,
                        raw_result_id=premature_raw.id,
                        trade_date=date(2026, 6, 16),
                        stock_id="2330",
                        stock_name="台積電",
                        open_price=999,
                        high_price=1_002,
                        low_price=998,
                        close_price=1_000,
                        trade_volume=1_000,
                    ),
                ]
            )
            db.commit()

            result = get_latest_stock_market_cap(db, "2330")

        assert result["trade_date"] == date(2026, 6, 15)
        assert result["close_price"] == 100
        assert result["market_cap"] == 1_000
    finally:
        engine.dispose()
