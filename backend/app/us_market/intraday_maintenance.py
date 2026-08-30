"""Bounded maintenance transactions for persisted US intraday datasets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import USQuoteSnapshot


US_QUOTE_RETENTION_DAYS = 30


def prune_expired_us_quote_snapshots(
    db: Session,
    *,
    now: datetime | None = None,
    retention_days: int = US_QUOTE_RETENTION_DAYS,
    max_rows: int = 10_000,
) -> dict[str, object]:
    """Delete one bounded batch of Quote snapshots outside the retention horizon."""

    requested_at = now or datetime.now(timezone.utc)
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if retention_days < 1 or retention_days > 365:
        raise ValueError("retention_days must be between 1 and 365")
    if max_rows < 1 or max_rows > 50_000:
        raise ValueError("max_rows must be between 1 and 50000")

    cutoff = requested_at.astimezone(timezone.utc) - timedelta(days=retention_days)
    expired_ids = [
        row_id
        for (row_id,) in (
            db.query(USQuoteSnapshot.id)
            .filter(USQuoteSnapshot.event_at < cutoff)
            .order_by(USQuoteSnapshot.event_at.asc(), USQuoteSnapshot.id.asc())
            .limit(max_rows)
            .all()
        )
    ]
    try:
        deleted_count = 0
        if expired_ids:
            deleted_count = (
                db.query(USQuoteSnapshot)
                .filter(USQuoteSnapshot.id.in_(expired_ids))
                .delete(synchronize_session=False)
            )
        remaining_expired = (
            db.query(USQuoteSnapshot.id)
            .filter(USQuoteSnapshot.event_at < cutoff)
            .first()
            is not None
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "contract_version": "omi.us.quote_retention.v1",
        "status": "partial" if remaining_expired else "complete",
        "cutoff": cutoff.isoformat(),
        "retention_days": retention_days,
        "max_rows": max_rows,
        "deleted_count": deleted_count,
        "remaining_expired": remaining_expired,
    }


__all__ = ["US_QUOTE_RETENTION_DAYS", "prune_expired_us_quote_snapshots"]
