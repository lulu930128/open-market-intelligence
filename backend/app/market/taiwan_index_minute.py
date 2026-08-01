from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import TaiwanIndexMinuteSnapshot, utc_now
from app.market.trading_calendar import TAIWAN_TZ


INDEX_MINUTE_VERSION = "tw.index.synthetic_minute.v1"
SUPPORTED_INDEX_IDS = {"TAIEX": "TWSE", "TPEX": "TPEX"}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _taipei_datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def persist_taiwan_index_minute_snapshots(
    db: Session,
    *,
    payload: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = _taipei_datetime(now) or datetime.now(TAIWAN_TZ)
    inserted_count = 0
    updated_count = 0
    skipped: list[str] = []

    for item in payload.get("indices") or []:
        if not isinstance(item, dict):
            continue
        index_id = str(item.get("index_id") or "").strip().upper()
        market = str(item.get("market") or "").strip().upper()
        close_value = _number(item.get("close"))
        event_time = _taipei_datetime(
            item.get("as_of")
            or item.get("time")
            or payload.get("as_of")
        )
        if (
            index_id not in SUPPORTED_INDEX_IDS
            or market != SUPPORTED_INDEX_IDS[index_id]
            or close_value is None
            or event_time is None
        ):
            skipped.append(index_id or "unknown")
            continue

        minute_at = event_time.replace(second=0, microsecond=0)
        provider = str(item.get("provider") or item.get("source") or "unknown")
        existing = (
            db.query(TaiwanIndexMinuteSnapshot)
            .filter(TaiwanIndexMinuteSnapshot.provider == provider)
            .filter(TaiwanIndexMinuteSnapshot.index_id == index_id)
            .filter(TaiwanIndexMinuteSnapshot.minute_at == minute_at)
            .first()
        )
        if existing is None:
            row = TaiwanIndexMinuteSnapshot(
                provider=provider,
                index_id=index_id,
                market=market,
                trade_date=event_time.date(),
                minute_at=minute_at,
                event_time=event_time,
                open_value=close_value,
                high_value=close_value,
                low_value=close_value,
                close_value=close_value,
                previous_close=_number(item.get("previous_close")),
                source_interval="snapshot",
                source_point_count=1,
                synthetic=True,
                indicator_eligible=False,
                quality_status="partial",
                source=str(item.get("source") or provider),
                source_url=item.get("source_url"),
            )
            db.add(row)
            inserted_count += 1
            continue

        if (
            _taipei_datetime(existing.event_time) == event_time
            and existing.close_value == close_value
        ):
            continue
        existing.event_time = event_time
        existing.open_value = (
            existing.open_value
            if existing.open_value is not None
            else close_value
        )
        existing.high_value = max(
            value
            for value in (existing.high_value, close_value)
            if value is not None
        )
        existing.low_value = min(
            value
            for value in (existing.low_value, close_value)
            if value is not None
        )
        existing.close_value = close_value
        existing.previous_close = (
            _number(item.get("previous_close"))
            if item.get("previous_close") is not None
            else existing.previous_close
        )
        existing.source_point_count = int(existing.source_point_count or 0) + 1
        existing.synthetic = True
        existing.indicator_eligible = False
        existing.quality_status = (
            "synthetic_complete"
            if existing.source_point_count >= 3
            else "partial"
        )
        existing.source = str(item.get("source") or provider)
        existing.source_url = item.get("source_url")
        existing.updated_at = utc_now()
        updated_count += 1

    if inserted_count or updated_count:
        db.commit()
    return {
        "kind": "taiwan_index_minute_snapshot_persist",
        "version": INDEX_MINUTE_VERSION,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "skipped": skipped,
    }


def read_taiwan_index_minute_series(
    db: Session,
    *,
    index_id: str,
    trade_date: date | None = None,
) -> dict[str, Any]:
    normalized_index_id = str(index_id or "").strip().upper()
    market = SUPPORTED_INDEX_IDS.get(normalized_index_id)
    if market is None:
        raise ValueError(
            "Taiwan synthetic index minute series supports TAIEX and TPEX."
        )
    target_date = trade_date
    if target_date is None:
        target_date = (
            db.query(TaiwanIndexMinuteSnapshot.trade_date)
            .filter(
                TaiwanIndexMinuteSnapshot.index_id
                == normalized_index_id
            )
            .order_by(TaiwanIndexMinuteSnapshot.trade_date.desc())
            .limit(1)
            .scalar()
        )
    rows = (
        db.query(TaiwanIndexMinuteSnapshot)
        .filter(TaiwanIndexMinuteSnapshot.index_id == normalized_index_id)
        .filter(TaiwanIndexMinuteSnapshot.trade_date == target_date)
        .order_by(TaiwanIndexMinuteSnapshot.minute_at.asc())
        .all()
        if target_date is not None
        else []
    )
    points = [
        {
            "time": (
                _taipei_datetime(row.minute_at) or row.minute_at
            ).isoformat(),
            "open": row.open_value,
            "high": row.high_value,
            "low": row.low_value,
            "price": row.close_value,
            "close": row.close_value,
            "volume": None,
            "synthetic": True,
            "source_interval": row.source_interval,
            "source_point_count": row.source_point_count,
            "indicator_eligible": row.indicator_eligible,
            "quality_status": row.quality_status,
        }
        for row in rows
        if row.close_value is not None
    ]
    previous_close = next(
        (
            row.previous_close
            for row in reversed(rows)
            if row.previous_close is not None
        ),
        None,
    )
    return {
        "stock_id": normalized_index_id,
        "symbol": "^TWOII"
        if normalized_index_id == "TPEX"
        else "^TWII",
        "market": market,
        "source": "taiwan_index_minute_snapshot",
        "provider": "scheduler_snapshot_aggregation",
        "interval": "1m",
        "requested_interval": "1m",
        "source_interval": "snapshot",
        "effective_interval": "1m",
        "interval_status": (
            "synthetic_partial" if points else "unsupported"
        ),
        "trade_date": (
            target_date.isoformat() if target_date is not None else None
        ),
        "coverage_status": (
            "synthetic_partial" if points else "missing"
        ),
        "is_partial": True,
        "synthetic": True,
        "synthetic_semantics": (
            "scheduler_collected_snapshots_aggregated_to_minute_ohlc"
        ),
        "indicator_eligible": False,
        "volume_unit": None,
        "volume_semantics": "not_provided_for_cash_index",
        "previous_close": previous_close,
        "point_count": len(points),
        "points": points,
        "warnings": (
            [
                "Synthetic index minutes are snapshot aggregates and are "
                "not indicator-eligible."
            ]
            if points
            else []
        ),
    }


def read_persisted_taiwan_index_minute_series(
    index_id: str,
) -> dict[str, Any]:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return read_taiwan_index_minute_series(
            db,
            index_id=index_id,
        )
    finally:
        db.close()


__all__ = [
    "INDEX_MINUTE_VERSION",
    "persist_taiwan_index_minute_snapshots",
    "read_persisted_taiwan_index_minute_series",
    "read_taiwan_index_minute_series",
]
