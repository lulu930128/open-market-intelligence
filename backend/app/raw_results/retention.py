from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import RawFetchResult


def _is_older_than(value: datetime, cutoff: datetime) -> bool:
    if value.tzinfo is None:
        return value < cutoff.replace(tzinfo=None)

    return value < cutoff


def compact_raw_fetch_results(
    db: Session,
    keep_latest_per_source: int = 200,
    max_age_days: int | None = None,
    dry_run: bool = True,
    limit: int = 1000,
) -> dict:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max_age_days)
        if max_age_days is not None
        else None
    )
    rows = (
        db.query(RawFetchResult)
        .filter(RawFetchResult.raw_text.isnot(None))
        .order_by(
            RawFetchResult.source_id.asc(),
            RawFetchResult.fetched_at.desc(),
            RawFetchResult.id.desc(),
        )
        .all()
    )

    source_seen: dict[int, int] = {}
    candidates: list[RawFetchResult] = []

    for row in rows:
        source_seen[row.source_id] = source_seen.get(row.source_id, 0) + 1

        if source_seen[row.source_id] <= keep_latest_per_source:
            continue

        if cutoff is not None and not _is_older_than(row.fetched_at, cutoff):
            continue

        candidates.append(row)

        if len(candidates) >= limit:
            break

    released_chars = sum(len(row.raw_text or "") for row in candidates)

    if not dry_run:
        for row in candidates:
            row.raw_text = None

        db.commit()

    return {
        "dry_run": dry_run,
        "keep_latest_per_source": keep_latest_per_source,
        "max_age_days": max_age_days,
        "limit": limit,
        "candidate_count": len(candidates),
        "compacted_count": 0 if dry_run else len(candidates),
        "released_chars": released_chars,
        "candidate_ids": [row.id for row in candidates[:100]],
    }
