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
                parser_version="yahoo.chart.v8",
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
            assert result["corporate_action_coverage"]["applicability"] == "required"
            assert result["corporate_action_coverage"]["status"] == "unknown"
            assert result["market_coverage"]["full_market_ready"] is False
            classification = result["market_coverage"]["classification_coverage"]
            assert classification["taxonomy_id"] == (
                "us_company_profile.provider_reported"
            )
            assert classification["decision_usable"] is False
            assert "STANDARD_TAXONOMY_NOT_CONFIGURED" in classification["reason_codes"]

            compact = build_us_market_research(
                db,
                symbol="AAPL",
                bars=260,
                now=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
                include_market_coverage=False,
                include_daily_ohlcv=False,
            )
            assert compact["daily_ohlcv"] == {}
            assert compact["technical_indicators"]["bar_count"] == 220
            assert compact["market_coverage"] == {
                "kind": "market_coverage_reference",
                "schema_version": "omi.us_market.coverage_reference.v1",
                "status": "unavailable",
                "snapshot_id": None,
                "as_of": None,
                "reason_codes": ["US_MARKET_COVERAGE_SNAPSHOT_UNAVAILABLE"],
            }
            weekly = build_us_market_research(
                db,
                symbol="AAPL",
                bars=52,
                timeframe="weekly",
                now=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
                include_market_coverage=False,
                include_daily_ohlcv=False,
            )
            assert weekly["timeframe"] == "weekly"
            assert weekly["technical_indicators"]["timeframe"] == "1w"
            assert len(weekly["technical_indicators"]["series"]) == 44
            assert weekly["technical_indicators"]["series"][-1]["ma"]["ma20"] is not None
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


def test_index_research_uses_not_applicable_volume_and_corporate_actions() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    try:
        with Session(engine) as db:
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
                content_hash="i" * 64,
                raw_text="fixture",
                parser_version="yahoo.chart.v8",
            )
            db.add(raw)
            db.flush()
            for index, trade_date in enumerate(
                _trading_dates(220, latest=date(2026, 8, 21))
            ):
                close = 5_000 + index * 2
                db.add(
                    USDailyPrice(
                        provider="yahoo_chart",
                        symbol="^GSPC",
                        trade_date=trade_date,
                        open_price=close - 5,
                        high_price=close + 10,
                        low_price=close - 10,
                        close_price=close,
                        trade_volume=None,
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
                        volume_unit=None,
                        volume_status="not_applicable",
                        raw_payload_hash=raw.content_hash,
                    )
                )
            db.commit()
            before_count = db.query(USDailyPrice).count()

            result = build_us_market_research(
                db,
                symbol="^GSPC",
                bars=260,
                now=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
            )

            assert db.query(USDailyPrice).count() == before_count
            assert result["technical_indicators"]["bar_count"] == 220
            assert len(result["technical_indicators"]["series"]) == 220
            latest_indicator = result["technical_indicators"]["series"][-1]
            assert latest_indicator["calculation_role"] == "backend_authoritative"
            assert latest_indicator["algorithm_version"].startswith(
                "omi.research.technical."
            )
            assert latest_indicator["ma"]["ma20"] is not None
            assert result["technical_indicators"]["profile"]["profile_id"] == (
                "us.index.daily"
            )
            assert result["technical_indicators"]["profile"]["volume_unit"] is None
            assert result["technical_indicators"]["current"]["volume"] is None
            assert result["technical_indicators"]["quality"]["decision_usable"] is True
            assert result["corporate_action_coverage"]["applicability"] == (
                "not_applicable"
            )
            assert result["corporate_action_coverage"]["status"] == "not_applicable"
            assert "CORPORATE_ACTION_COVERAGE_INCOMPLETE" not in result[
                "technical_indicators"
            ]["quality"]["reason_codes"]
    finally:
        engine.dispose()
