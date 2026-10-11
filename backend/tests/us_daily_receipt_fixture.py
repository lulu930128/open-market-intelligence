"""Synthetic receipts for isolated Daily read-cost tests; no provider IO."""

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, SourceRegistry, USDailyPrice, USStockMaster
from app.market_data.candidate_repository import DailyBarCandidateQuery
from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.us_market.trading_calendar import is_us_trading_day, us_session_close_time


NOW = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
EASTERN = ZoneInfo("America/New_York")
RECEIPT_CHARS = 277_000


def seed_daily_receipts(db: Session, *, days=180, shared=True, large=True):
    dates = []
    day = date(2026, 8, 21)
    while len(dates) < days:
        if is_us_trading_day(day):
            dates.append(day)
        day -= timedelta(days=1)
    dates.reverse()
    db.add(USStockMaster(symbol="AAPL", security_name="Synthetic AAPL",
                         exchange="NASDAQ", asset_type="stock", is_active=True))
    for provider in ("yahoo_chart", "alpaca"):
        source = SourceRegistry(source_name=f"{provider}.daily.fixture",
                                source_type="fixture", category="market_data", enabled=True)
        db.add(source)
        db.flush()
        raw = None
        for day in dates:
            if raw is None or not shared:
                content = f"SYNTHETIC:{provider}:{day}:".ljust(RECEIPT_CHARS if large else 64, "x")
                raw = RawFetchResult(source_id=source.id, fetched_at=NOW - timedelta(days=1),
                                     content_hash=sha256(content.encode()).hexdigest(),
                                     raw_text=content, parser_version="fixture.v1")
                db.add(raw)
                db.flush()
            db.add(USDailyPrice(
                provider=provider, symbol="AAPL", trade_date=day,
                open_price=100, high_price=102, low_price=99, close_price=101,
                trade_volume=1000, fetched_at=raw.fetched_at,
                source_id=source.id, raw_result_id=raw.id, authority="vendor",
                raw_contract_version="fixture.v1", finalization="final", price_basis="raw",
                event_at=datetime.combine(day, us_session_close_time(day), EASTERN),
                volume_unit="shares", volume_status="observed", raw_payload_hash=raw.content_hash,
            ))
    db.commit()
    return DailyBarCandidateQuery(
        instrument=InstrumentKey(market=Market.US, symbol="AAPL",
                                 instrument_type=InstrumentType.STOCK, venue="NASDAQ"),
        start_date=dates[0], end_date=dates[-1], available_at=NOW, max_rows=days * 2,
    )
