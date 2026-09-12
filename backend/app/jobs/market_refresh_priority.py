"""Explicit foreground demand shared by market-owned background repairs.

This transaction owner is called only after refresh authorization, never by
cache readers. Priority changes order, not provider policy or freshness.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import MarketRefreshPriority, StockMaster, USStockMaster
from app.config import settings


def request_market_refresh_priority(
    db: Session, *, market: str, symbol: str, now: datetime | None = None,
) -> dict:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("priority time must be timezone-aware")
    normalized_market, normalized_symbol = market.strip().upper(), symbol.strip().upper()
    if normalized_market == "US":
        instrument = db.execute(select(USStockMaster).where(
            USStockMaster.symbol == normalized_symbol, USStockMaster.is_active.is_(True),
        )).scalar_one_or_none()
        venue = str(instrument.exchange or "") if instrument else ""
    elif normalized_market == "TW":
        instrument = db.execute(select(StockMaster).where(
            StockMaster.stock_id == normalized_symbol,
            StockMaster.is_active.is_(True),
        )).scalar_one_or_none()
        venue = str(instrument.market or "") if instrument else ""
    else:
        raise ValueError("foreground repair priority supports TW and US only")
    if not venue:
        return {"status": "not_registered", "reason": "canonical_instrument_unavailable"}
    identity = dict(market=normalized_market, venue=venue, symbol=normalized_symbol)
    predicate = [getattr(MarketRefreshPriority, key) == value for key, value in identity.items()]
    # Unique identity handles concurrent requests. A savepoint preserves the
    # caller transaction if another requester inserted the same target first.
    row = db.execute(select(MarketRefreshPriority).where(*predicate)).scalar_one_or_none()
    expiry = moment + timedelta(seconds=settings.market_refresh_priority_ttl_seconds)
    if row is None:
        try:
            with db.begin_nested():
                row = MarketRefreshPriority(**identity, requested_at=moment, expires_at=expiry)
                db.add(row)
                db.flush()
        except IntegrityError:
            row = db.execute(select(MarketRefreshPriority).where(*predicate)).scalar_one()
    row.requested_at = moment
    row.expires_at = expiry
    # Only short-lived demand is removed; no market observations are touched.
    db.execute(delete(MarketRefreshPriority).where(MarketRefreshPriority.expires_at < moment))
    db.commit()
    return {"status": "prioritized", **identity, "expires_at": expiry.isoformat()}


def active_market_refresh_priorities(db: Session, *, market: str, now: datetime | None = None) -> tuple[str, ...]:
    """Bounded read for the scheduler, with oldest foreground demand first."""
    moment = now or datetime.now(timezone.utc)
    return tuple(db.execute(select(MarketRefreshPriority.symbol).where(
        MarketRefreshPriority.market == market,
        MarketRefreshPriority.expires_at > moment,
    ).order_by(MarketRefreshPriority.requested_at, MarketRefreshPriority.id).limit(100)).scalars())
