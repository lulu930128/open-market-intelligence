"""JP provider attempt persistence; diagnostic health never replaces resolved health."""

import json
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.db.models import SourceHealthSnapshot
from app.market_data.contracts import OperationalStatus, ProviderResourceHealth
from app.observability.provider_health import sync_source_health_snapshots


RESOURCE = "jp.daily.ohlcv.provider_attempt"


class JPDailyProviderAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latest_attempt: ProviderResourceHealth
    last_good: ProviderResourceHealth | None = None


def read_daily_attempts(db: Session, *, symbol: str, now: datetime) -> tuple[JPDailyProviderAttempt, ...]:
    with db.no_autoflush:
        rows = db.query(SourceHealthSnapshot).filter_by(market="jp", resource=RESOURCE, target=symbol).filter(
            SourceHealthSnapshot.checked_at <= now,
        ).order_by(SourceHealthSnapshot.provider).limit(8).all()
    results = []
    for row in rows:
        try:
            item = JPDailyProviderAttempt.model_validate(json.loads(row.snapshot_json or "{}")["attempt"])
            if item.latest_attempt.provider == row.provider and item.latest_attempt.checked_at <= now:
                results.append(item)
        except (ValueError, KeyError, ValidationError):
            # Corrupt diagnostics must not be promoted into provider eligibility.
            continue
    return tuple(results)


def planning_daily_health(db: Session, *, symbol: str, now: datetime):
    return tuple(item.latest_attempt for item in read_daily_attempts(db, symbol=symbol, now=now)
                 if now - item.latest_attempt.checked_at <= timedelta(minutes=15))


def publish_daily_attempts(db: Session, *, symbol: str, result) -> None:
    if not result.acquisition.attempted or not result.provider_health:
        return
    checked_at = max(item.checked_at for item in result.provider_health)
    previous = {item.latest_attempt.provider: item for item in read_daily_attempts(db, symbol=symbol, now=checked_at)}
    attempted = set(result.acquisition.providers_attempted)
    entries = []
    for health in result.provider_health:
        if health.provider not in attempted:
            continue
        prior = previous.get(health.provider)
        good = health.operational is OperationalStatus.HEALTHY
        attempt = JPDailyProviderAttempt(latest_attempt=health, last_good=health if good else prior.last_good if prior else None)
        entries.append({
            "resource": RESOURCE, "target": symbol, "provider": health.provider,
            "status": "ok" if good else "error", "ok": good, "row_count": 0,
            "required": False, "data_quality": "provider_attempt", "reason": health.detail_code,
            "attempt": attempt.model_dump(mode="json"),
        })
    try:
        sync_source_health_snapshots(db, market="jp", entries=entries, checked_at=checked_at)
    except Exception:
        db.rollback()
        raise
