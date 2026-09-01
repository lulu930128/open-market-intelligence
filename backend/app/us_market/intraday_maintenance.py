"""Bounded maintenance transactions for persisted US intraday datasets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    MarketIntradayBar,
    MarketIntradayBarLineage,
    USQuoteSnapshot,
)


US_QUOTE_RETENTION_DAYS = 30
US_YAHOO_INTRADAY_PROVIDERS = ("yahoo_chart", "yahoo_finance_chart")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def inspect_us_yahoo_intraday_minute_integrity(
    db: Session,
    *,
    max_rows: int = 50_000,
    max_conflicts: int = 200,
) -> dict[str, Any]:
    """Inspect persisted Yahoo 1m identity conflicts without mutating the DB."""

    if max_rows < 1 or max_rows > 250_000:
        raise ValueError("max_rows must be between 1 and 250000")
    if max_conflicts < 0 or max_conflicts > 5_000:
        raise ValueError("max_conflicts must be between 0 and 5000")

    rows = (
        db.query(MarketIntradayBar, MarketIntradayBarLineage)
        .outerjoin(
            MarketIntradayBarLineage,
            MarketIntradayBarLineage.bar_id == MarketIntradayBar.id,
        )
        .filter(MarketIntradayBar.provider.in_(US_YAHOO_INTRADAY_PROVIDERS))
        .filter(MarketIntradayBar.interval == "1m")
        .order_by(MarketIntradayBar.id.asc())
        .limit(max_rows + 1)
        .all()
    )
    has_more = len(rows) > max_rows
    inspected = rows[:max_rows]
    grouped: dict[
        tuple[str, str, datetime],
        list[tuple[MarketIntradayBar, MarketIntradayBarLineage | None]],
    ] = {}
    non_minute_count = 0
    missing_lineage_count = 0
    for bar, lineage in inspected:
        observed_at = _utc(bar.bar_time)
        canonical_minute = observed_at.replace(second=0, microsecond=0)
        if observed_at != canonical_minute:
            non_minute_count += 1
        if lineage is None:
            missing_lineage_count += 1
        grouped.setdefault(
            (bar.provider, bar.stock_id, canonical_minute),
            [],
        ).append((bar, lineage))

    conflict_groups = [
        (key, candidates)
        for key, candidates in grouped.items()
        if len(candidates) > 1
    ]
    conflict_groups.sort(key=lambda item: item[0])
    conflicts: list[dict[str, Any]] = []
    for (provider, symbol, canonical_minute), candidates in conflict_groups[
        :max_conflicts
    ]:
        ranked = sorted(
            candidates,
            key=lambda item: (
                _utc(item[1].fetched_at)
                if item[1] is not None
                else datetime.min.replace(tzinfo=timezone.utc),
                item[0].id,
            ),
        )
        conflicts.append(
            {
                "provider": provider,
                "symbol": symbol,
                "canonical_minute": canonical_minute.isoformat(),
                "row_ids": [bar.id for bar, _ in candidates],
                "bar_times": [_utc(bar.bar_time).isoformat() for bar, _ in candidates],
                "raw_result_ids": [
                    lineage.raw_result_id if lineage is not None else None
                    for _, lineage in candidates
                ],
                "recommended_survivor_id": ranked[-1][0].id,
                "requires_lineage_review": any(
                    lineage is None for _, lineage in candidates
                ),
            }
        )

    return {
        "contract_version": "omi.us.intraday_minute_integrity.v1",
        "dry_run": True,
        "status": "partial" if has_more else "complete",
        "providers": list(US_YAHOO_INTRADAY_PROVIDERS),
        "interval": "1m",
        "max_rows": max_rows,
        "inspected_row_count": len(inspected),
        "non_minute_row_count": non_minute_count,
        "duplicate_minute_bucket_count": len(conflict_groups),
        "rows_in_duplicate_minute_buckets": sum(
            len(candidates) for _, candidates in conflict_groups
        ),
        "missing_lineage_count": missing_lineage_count,
        "reported_conflict_count": len(conflicts),
        "conflicts_truncated": len(conflict_groups) > len(conflicts),
        "has_more_rows": has_more,
        "writes_performed": 0,
        "conflicts": conflicts,
    }


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


__all__ = [
    "US_QUOTE_RETENTION_DAYS",
    "US_YAHOO_INTRADAY_PROVIDERS",
    "inspect_us_yahoo_intraday_minute_integrity",
    "prune_expired_us_quote_snapshots",
]
