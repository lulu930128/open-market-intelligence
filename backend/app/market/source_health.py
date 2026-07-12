from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Query, Session

from app.db.models import MarketChipDaily, StockMaster
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.taiwan_rules import (
    TAIWAN_DATASET_SPECS,
    TaiwanDatasetSpec,
    is_equity_only_dataset_required,
)
from app.observability.provider_health import (
    enrich_source_health_entries,
    sync_source_health_snapshots,
)
from app.observability.source_health_contract import (
    daily_row_status,
    freshness_lag_days as _freshness_lag,
    generated_at as _generated_at,
    summarize_source_health,
)


MARKET_CHIP_RESOURCE = "market_chip_daily"


@dataclass(frozen=True)
class TaiwanSourceHealthEntry:
    resource: str
    label: str
    frequency: str
    target: str
    status: str
    ok: bool
    row_count: int
    required: bool = True
    latest_data_date: date | None = None
    latest_data_key: str | None = None
    latest_updated_at: datetime | None = None
    expected_data_date: date | None = None
    freshness_lag_days: int | None = None
    release_status: str | None = None
    release_is_released: bool | None = None
    data_quality: str = "unknown"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "label": self.label,
            "frequency": self.frequency,
            "target": self.target,
            "status": self.status,
            "ok": self.ok,
            "row_count": self.row_count,
            "required": self.required,
            "latest_data_date": self.latest_data_date.isoformat() if self.latest_data_date else None,
            "latest_data_key": self.latest_data_key,
            "latest_updated_at": self.latest_updated_at.isoformat() if self.latest_updated_at else None,
            "expected_data_date": self.expected_data_date.isoformat() if self.expected_data_date else None,
            "freshness_lag_days": self.freshness_lag_days,
            "release_status": self.release_status,
            "release_is_released": self.release_is_released,
            "data_quality": self.data_quality,
            "reason": self.reason,
        }


def _normalized_stock_id(stock_id: str | None) -> str | None:
    normalized = (stock_id or "").strip()
    return normalized or None


def _normalized_index_id(index_id: str | None) -> str | None:
    normalized = (index_id or "").strip().upper()
    return normalized or None


def _target(*, stock_id: str | None = None, index_id: str | None = None) -> str:
    return stock_id or index_id or "all"


def _date_or_none(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _key_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return None
    return str(value)


def _release_window(calendar_status: dict[str, Any], key: str) -> dict[str, Any]:
    windows = calendar_status.get("release_windows")
    if not isinstance(windows, dict):
        return {}
    window = windows.get(key)
    return window if isinstance(window, dict) else {}


def _expected_date(window: dict[str, Any]) -> date | None:
    value = window.get("expected_trade_date")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _status_for(
    *,
    row_count: int,
    latest_data_date: date | None,
    expected_data_date: date | None = None,
    freshness_required: bool = False,
) -> tuple[str, bool, str, str]:
    return daily_row_status(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=freshness_required,
        empty_reason="No local rows are available for this resource.",
        current_reason="Latest local row is aligned with the expected Taiwan release window.",
        available_reason="Local rows are available; no exact release-date target is enforced.",
    )


def _latest_or_none(query: Query, *order_by):
    return query.order_by(*order_by).first()


def _stock_master_entry(
    db: Session,
    *,
    stock_id: str | None,
) -> TaiwanSourceHealthEntry:
    query = db.query(StockMaster)
    if stock_id is not None:
        query = query.filter(StockMaster.stock_id == stock_id)

    row_count = query.count()
    latest = _latest_or_none(query, StockMaster.updated_at.desc(), StockMaster.id.desc())
    status_value, ok, data_quality, reason = _status_for(
        row_count=row_count,
        latest_data_date=None,
    )
    return TaiwanSourceHealthEntry(
        resource="stock_master",
        label="Stock master",
        frequency="master",
        target=_target(stock_id=stock_id),
        status=status_value,
        ok=ok,
        row_count=row_count,
        latest_updated_at=getattr(latest, "updated_at", None) if latest else None,
        data_quality=data_quality,
        reason=reason,
    )


def _dataset_entry(
    db: Session,
    *,
    spec: TaiwanDatasetSpec,
    stock: StockMaster | None,
    stock_id: str | None,
    calendar_status: dict[str, Any],
) -> TaiwanSourceHealthEntry:
    required = is_equity_only_dataset_required(spec, stock)
    target = _target(stock_id=stock_id)
    window = _release_window(calendar_status, spec.key)
    expected_data_date = _expected_date(window) if spec.has_expected_date else None

    if not required:
        return TaiwanSourceHealthEntry(
            resource=spec.key,
            label=spec.label,
            frequency=spec.frequency,
            target=target,
            status="not_applicable",
            ok=True,
            row_count=0,
            required=False,
            expected_data_date=expected_data_date,
            release_status=window.get("status"),
            release_is_released=window.get("is_released"),
            data_quality="not_applicable",
            reason="This resource is equity-only and is not required for this instrument type.",
        )

    query = db.query(spec.model)
    if stock_id is not None and hasattr(spec.model, "stock_id"):
        query = query.filter(spec.model.stock_id == stock_id)

    row_count = query.count()
    order_by = [spec.latest_column.desc()]
    if hasattr(spec.model, "updated_at"):
        order_by.append(spec.model.updated_at.desc())
    order_by.append(spec.model.id.desc())
    latest = _latest_or_none(query, *order_by)
    latest_value = getattr(latest, spec.latest_column.key, None) if latest else None
    latest_data_date = _date_or_none(latest_value)
    latest_data_key = _key_or_none(latest_value)
    latest_updated_at = getattr(latest, "updated_at", None) if latest else None
    status_value, ok, data_quality, reason = _status_for(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=spec.has_expected_date,
    )

    return TaiwanSourceHealthEntry(
        resource=spec.key,
        label=spec.label,
        frequency=spec.frequency,
        target=target,
        status=status_value,
        ok=ok,
        row_count=row_count,
        latest_data_date=latest_data_date,
        latest_data_key=latest_data_key,
        latest_updated_at=latest_updated_at,
        expected_data_date=expected_data_date,
        freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
        release_status=window.get("status"),
        release_is_released=window.get("is_released"),
        data_quality=data_quality,
        reason=reason,
    )


def _market_chip_entry(
    db: Session,
    *,
    index_id: str | None,
    calendar_status: dict[str, Any],
) -> TaiwanSourceHealthEntry:
    window = _release_window(calendar_status, MARKET_CHIP_RESOURCE)
    expected_data_date = _expected_date(window)
    query = db.query(MarketChipDaily)
    if index_id is not None:
        query = query.filter(MarketChipDaily.index_id == index_id)

    row_count = query.count()
    latest = _latest_or_none(
        query,
        MarketChipDaily.trade_date.desc(),
        MarketChipDaily.updated_at.desc(),
        MarketChipDaily.id.desc(),
    )
    latest_data_date = latest.trade_date if latest else None
    status_value, ok, data_quality, reason = _status_for(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=True,
    )
    return TaiwanSourceHealthEntry(
        resource=MARKET_CHIP_RESOURCE,
        label="Market chip daily",
        frequency="daily",
        target=_target(index_id=index_id),
        status=status_value,
        ok=ok,
        row_count=row_count,
        latest_data_date=latest_data_date,
        latest_updated_at=getattr(latest, "updated_at", None) if latest else None,
        expected_data_date=expected_data_date,
        freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
        release_status=window.get("status"),
        release_is_released=window.get("is_released"),
        data_quality=data_quality,
        reason=reason,
    )


def _summary(entries: list[TaiwanSourceHealthEntry]) -> dict[str, int]:
    return summarize_source_health(
        entries,
        counted_statuses=("empty", "stale", "not_applicable", "error"),
    )


def build_taiwan_source_health(
    db: Session,
    *,
    stock_id: str | None = None,
    dataset: str | None = None,
    index_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_stock_id = _normalized_stock_id(stock_id)
    normalized_index_id = _normalized_index_id(index_id)
    normalized_dataset = (dataset or "").strip() or None
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized_stock_id)
        .first()
        if normalized_stock_id is not None
        else None
    )
    calendar_status = build_taiwan_calendar_status(now=now)
    entries = [
        _stock_master_entry(db, stock_id=normalized_stock_id),
        *[
            _dataset_entry(
                db,
                spec=spec,
                stock=stock,
                stock_id=normalized_stock_id,
                calendar_status=calendar_status,
            )
            for spec in TAIWAN_DATASET_SPECS
        ],
        _market_chip_entry(
            db,
            index_id=normalized_index_id,
            calendar_status=calendar_status,
        ),
    ]
    if normalized_dataset is not None:
        entries = [entry for entry in entries if entry.resource == normalized_dataset]
    entry_dicts = enrich_source_health_entries(
        db,
        market="tw",
        entries=[entry.to_dict() for entry in entries],
    )
    generated_at = _generated_at()
    sync_source_health_snapshots(
        db,
        market="tw",
        entries=entry_dicts,
        checked_at=generated_at,
    )

    return {
        "kind": "taiwan_source_health",
        "generated_at": generated_at.isoformat(),
        "filters": {
            "stock_id": normalized_stock_id,
            "dataset": normalized_dataset,
            "index_id": normalized_index_id,
        },
        "market_calendar": {
            "checked_at": calendar_status.get("checked_at"),
            "date": calendar_status.get("date"),
            "phase": calendar_status.get("phase"),
            "reason": calendar_status.get("reason"),
            "is_trading_day": calendar_status.get("is_trading_day"),
        },
        "summary": _summary(entries),
        "entries": entry_dicts,
    }


__all__ = [
    "TaiwanSourceHealthEntry",
    "build_taiwan_source_health",
]
