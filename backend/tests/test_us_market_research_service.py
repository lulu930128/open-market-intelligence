from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    USDailyPrice,
    USStockMaster,
)
from app.us_market.research_service import build_us_market_research


def _trading_dates(count: int, *, latest: date) -> list[date]:
    dates: list[date] = []
    current = latest
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current)
        current -= timedelta(days=1)
    return list(reversed(dates))


def test_research_service_reads_resolved_cache_without_writes() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    try:
        with Session(engine) as db:
            db.add(
                USStockMaster(
                    symbol="AAPL",
                    security_name="Apple Inc.",
                    exchange="NASDAQ",
                    asset_type="stock",
                    is_active=True,
                )
            )
            source = SourceRegistry(
                source_name="yahoo_chart.daily",
                source_type="fixture",
                category="market_data",
                enabled=True,
            )
            db.add(source)
            db.flush()
            raw = RawFetchResult(
                source_id=source.id,
                fetched_at=datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc),
                content_hash="a" * 64,
                raw_text="fixture",
            )
            db.add(raw)
            db.flush()
            for index, trade_date in enumerate(
                _trading_dates(220, latest=date(2026, 8, 21))
            ):
                close = 100 + index * 0.25
                db.add(
                    USDailyPrice(
                        provider="yahoo_chart",
                        symbol="AAPL",
                        trade_date=trade_date,
                        open_price=close - 0.5,
                        high_price=close + 1,
                        low_price=close - 1,
                        close_price=close,
                        trade_volume=1_000_000 + index,
                        fetched_at=datetime.combine(
                            trade_date + timedelta(days=1),
                            time(2, 0),
                            tzinfo=timezone.utc,
                        ),
                        source_id=source.id,
                        raw_result_id=raw.id,
                        authority="vendor",
                        raw_contract_version="yahoo.chart.v8",
                        event_at=datetime.combine(
                            trade_date,
                            time(20, 0),
                            tzinfo=timezone.utc,
                        ),
                        finalization="final",
                        price_basis="raw",
                        volume_unit="shares",
                        volume_status="observed",
                        raw_payload_hash=raw.content_hash,
                    )
                )
            db.commit()
            before_count = db.query(USDailyPrice).count()

            result = build_us_market_research(
                db,
                symbol="AAPL",
                bars=260,
                now=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
            )

            assert db.query(USDailyPrice).count() == before_count
            assert result["schema_version"] == "omi.us_market.research.v1"
            assert result["daily_ohlcv"]["schema_version"] == "omi.market.bars.v1"
            assert result["daily_ohlcv"]["selected_provider"] == "yahoo_chart"
            assert result["technical_indicators"]["bar_count"] == 220
            assert result["technical_indicators"]["quality"]["facts_usable"] is True
            assert result["technical_indicators"]["quality"]["decision_usable"] is False
            assert result["technical_structure"]["trend_state"] == "bullish_stack"
            assert result["corporate_action_coverage"]["status"] == "unknown"
            assert result["market_coverage"]["full_market_ready"] is False
            classification = result["market_coverage"]["classification_coverage"]
            assert classification["taxonomy_id"] == (
                "us_company_profile.provider_reported"
            )
            assert classification["decision_usable"] is False
            assert "STANDARD_TAXONOMY_NOT_CONFIGURED" in classification["reason_codes"]
    finally:
        engine.dispose()


def test_research_service_fails_closed_when_venue_is_unknown() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    try:
        with Session(engine) as db:
            db.add(
                USStockMaster(
                    symbol="UNKNOWN",
                    exchange=None,
                    asset_type="stock",
                    is_active=True,
                )
            )
            db.commit()

            result = build_us_market_research(
                db,
                symbol="UNKNOWN",
                now=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
            )

            assert result["status"] == "missing"
            assert result["daily_ohlcv"] == {}
            assert "instrument_identity" in result["missing"]
            assert result["technical_indicators"]["current"] == {}
    finally:
        engine.dispose()
