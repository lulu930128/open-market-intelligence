from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Query, Session

from app.db.models import (
    MacroSeriesObservation,
    USDailyPrice,
    USCompanyProfile,
    USCorporateAction,
    USSecCompanyFact,
    USShortVolumeDaily,
    USStockMaster,
)
from app.market.calendar_status import expected_us_trade_date
from app.observability.provider_health import (
    enrich_source_health_entries,
    sync_source_health_snapshots,
)
from app.us_market.sources import normalize_us_symbol


DAILY_PROVIDER_ORDER = ("yahoo_chart", "alphavantage")


@dataclass(frozen=True)
class USSourceHealthEntry:
    resource: str
    provider: str
    target: str
    status: str
    ok: bool
    row_count: int
    latest_data_date: date | None = None
    latest_fetched_at: datetime | None = None
    expected_data_date: date | None = None
    freshness_lag_days: int | None = None
    source_url: str | None = None
    data_quality: str = "unknown"
    reason: str = ""
    rate_limited: bool = False
    retry_after_seconds: int | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "provider": self.provider,
            "target": self.target,
            "status": self.status,
            "ok": self.ok,
            "row_count": self.row_count,
            "latest_data_date": self.latest_data_date.isoformat() if self.latest_data_date else None,
            "latest_fetched_at": self.latest_fetched_at.isoformat() if self.latest_fetched_at else None,
            "expected_data_date": self.expected_data_date.isoformat() if self.expected_data_date else None,
            "freshness_lag_days": self.freshness_lag_days,
            "source_url": self.source_url,
            "data_quality": self.data_quality,
            "reason": self.reason,
            "rate_limited": self.rate_limited,
            "retry_after_seconds": self.retry_after_seconds,
            "error_message": self.error_message,
        }


def _generated_at() -> datetime:
    return datetime.now(timezone.utc)


def _target(*, symbol: str | None = None, series_id: str | None = None) -> str:
    return symbol or series_id or "all"


def _freshness_lag(expected: date | None, latest: date | None) -> int | None:
    if expected is None or latest is None:
        return None
    return max((expected - latest).days, 0)


def _status_for(
    *,
    row_count: int,
    latest_data_date: date | None,
    expected_data_date: date | None = None,
    freshness_required: bool = False,
) -> tuple[str, bool, str, str]:
    if row_count <= 0:
        return "empty", False, "empty", "No local rows are available for this provider/resource."

    if freshness_required and expected_data_date is not None and latest_data_date is not None:
        if latest_data_date < expected_data_date:
            return (
                "stale",
                False,
                "stale",
                f"Latest data date {latest_data_date.isoformat()} is behind expected {expected_data_date.isoformat()}.",
            )
        return "current", True, "ok", "Latest local row is aligned with the expected US trade date."

    return "available", True, "ok", "Local rows are available; no daily freshness target is enforced."


def _latest_or_none(query: Query, *order_by):
    return query.order_by(*order_by).first()


def _entry_from_query(
    *,
    query: Query,
    resource: str,
    provider: str,
    target: str,
    latest_data_attr: str | None,
    latest_fetched_attr: str | None,
    expected_data_date: date | None = None,
    freshness_required: bool = False,
    source_url_attr: str | None = "source_url",
    order_by: tuple[Any, ...],
) -> USSourceHealthEntry:
    row_count = query.count()
    latest = _latest_or_none(query, *order_by)
    latest_data_date = getattr(latest, latest_data_attr, None) if latest and latest_data_attr else None
    latest_fetched_at = getattr(latest, latest_fetched_attr, None) if latest and latest_fetched_attr else None
    source_url = getattr(latest, source_url_attr, None) if latest and source_url_attr else None
    status_value, ok, data_quality, reason = _status_for(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=freshness_required,
    )

    return USSourceHealthEntry(
        resource=resource,
        provider=provider,
        target=target,
        status=status_value,
        ok=ok,
        row_count=row_count,
        latest_data_date=latest_data_date,
        latest_fetched_at=latest_fetched_at,
        expected_data_date=expected_data_date,
        freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
        source_url=source_url,
        data_quality=data_quality,
        reason=reason,
    )


def _daily_price_entries(
    db: Session,
    *,
    symbol: str | None,
    expected_daily_price_date: date | None,
) -> list[USSourceHealthEntry]:
    entries: list[USSourceHealthEntry] = []
    target = _target(symbol=symbol)

    for provider in DAILY_PROVIDER_ORDER:
        query = db.query(USDailyPrice).filter(USDailyPrice.provider == provider)
        if symbol is not None:
            query = query.filter(USDailyPrice.symbol == symbol)
        entries.append(
            _entry_from_query(
                query=query,
                resource="daily_price",
                provider=provider,
                target=target,
                latest_data_attr="trade_date",
                latest_fetched_attr="fetched_at",
                expected_data_date=expected_daily_price_date,
                freshness_required=True,
                order_by=(
                    USDailyPrice.trade_date.desc(),
                    USDailyPrice.fetched_at.desc(),
                    USDailyPrice.id.desc(),
                ),
            )
        )

    return entries


def _symbol_master_entry(db: Session, *, symbol: str | None) -> USSourceHealthEntry:
    query = db.query(USStockMaster)
    if symbol is not None:
        query = query.filter(USStockMaster.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="symbol_master",
        provider="nasdaq_trader+sec_edgar+yahoo_chart",
        target=_target(symbol=symbol),
        latest_data_attr=None,
        latest_fetched_attr="last_seen_at",
        source_url_attr=None,
        order_by=(USStockMaster.last_seen_at.desc(), USStockMaster.id.desc()),
    )


def _profile_entry(db: Session, *, symbol: str | None) -> USSourceHealthEntry:
    query = db.query(USCompanyProfile)
    if symbol is not None:
        query = query.filter(USCompanyProfile.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="profile",
        provider="alphavantage",
        target=_target(symbol=symbol),
        latest_data_attr="latest_quarter",
        latest_fetched_attr="fetched_at",
        order_by=(USCompanyProfile.fetched_at.desc(), USCompanyProfile.id.desc()),
    )


def _sec_facts_entry(db: Session, *, symbol: str | None) -> USSourceHealthEntry:
    query = db.query(USSecCompanyFact)
    if symbol is not None:
        query = query.filter(USSecCompanyFact.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="sec_facts",
        provider="sec_edgar",
        target=_target(symbol=symbol),
        latest_data_attr="period_end_date",
        latest_fetched_attr="fetched_at",
        order_by=(
            USSecCompanyFact.period_end_date.desc(),
            USSecCompanyFact.fetched_at.desc(),
            USSecCompanyFact.id.desc(),
        ),
    )


def _corporate_actions_entry(db: Session, *, symbol: str | None) -> USSourceHealthEntry:
    query = db.query(USCorporateAction)
    if symbol is not None:
        query = query.filter(USCorporateAction.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="corporate_actions",
        provider="alphavantage",
        target=_target(symbol=symbol),
        latest_data_attr="event_date",
        latest_fetched_attr="fetched_at",
        order_by=(
            USCorporateAction.event_date.desc(),
            USCorporateAction.fetched_at.desc(),
            USCorporateAction.id.desc(),
        ),
    )


def _short_volume_entry(
    db: Session,
    *,
    symbol: str | None,
    expected_daily_price_date: date | None,
) -> USSourceHealthEntry:
    query = db.query(USShortVolumeDaily)
    if symbol is not None:
        query = query.filter(USShortVolumeDaily.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="short_volume",
        provider="finra",
        target=_target(symbol=symbol),
        latest_data_attr="trade_date",
        latest_fetched_attr="fetched_at",
        expected_data_date=expected_daily_price_date,
        freshness_required=True,
        order_by=(
            USShortVolumeDaily.trade_date.desc(),
            USShortVolumeDaily.fetched_at.desc(),
            USShortVolumeDaily.id.desc(),
        ),
    )


def _macro_entry(db: Session, *, series_id: str | None) -> USSourceHealthEntry:
    normalized_series_id = series_id.strip().upper() if series_id else None
    query = db.query(MacroSeriesObservation)
    if normalized_series_id is not None:
        query = query.filter(MacroSeriesObservation.series_id == normalized_series_id)

    return _entry_from_query(
        query=query,
        resource="macro_series",
        provider="fred",
        target=_target(series_id=normalized_series_id),
        latest_data_attr="observation_date",
        latest_fetched_attr="fetched_at",
        order_by=(
            MacroSeriesObservation.observation_date.desc(),
            MacroSeriesObservation.fetched_at.desc(),
            MacroSeriesObservation.id.desc(),
        ),
    )


def _summary(entries: list[USSourceHealthEntry]) -> dict[str, int]:
    return {
        "entry_count": len(entries),
        "ok_count": sum(1 for entry in entries if entry.ok),
        "empty_count": sum(1 for entry in entries if entry.status == "empty"),
        "stale_count": sum(1 for entry in entries if entry.status == "stale"),
        "error_count": sum(1 for entry in entries if entry.status == "error"),
    }


def build_us_source_health(
    db: Session,
    *,
    symbol: str | None = None,
    series_id: str | None = None,
    now: datetime | None = None,
    expected_daily_price_date: date | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol) if symbol else None
    normalized_series_id = series_id.strip().upper() if series_id else None
    expected_date = expected_daily_price_date or expected_us_trade_date(
        "us_daily_price",
        now=now,
    )
    entries = [
        _symbol_master_entry(db, symbol=normalized_symbol),
        *_daily_price_entries(
            db,
            symbol=normalized_symbol,
            expected_daily_price_date=expected_date,
        ),
        _profile_entry(db, symbol=normalized_symbol),
        _sec_facts_entry(db, symbol=normalized_symbol),
        _corporate_actions_entry(db, symbol=normalized_symbol),
        _short_volume_entry(
            db,
            symbol=normalized_symbol,
            expected_daily_price_date=expected_date,
        ),
        _macro_entry(db, series_id=normalized_series_id),
    ]
    generated_at = _generated_at()
    entry_dicts = enrich_source_health_entries(
        db,
        market="us",
        entries=[entry.to_dict() for entry in entries],
    )
    sync_source_health_snapshots(
        db,
        market="us",
        entries=entry_dicts,
        checked_at=generated_at,
    )

    return {
        "kind": "us_source_health",
        "generated_at": generated_at.isoformat(),
        "filters": {
            "symbol": normalized_symbol,
            "series_id": normalized_series_id,
        },
        "expected_daily_price_date": expected_date.isoformat() if expected_date else None,
        "summary": _summary(entries),
        "entries": entry_dicts,
    }


__all__ = [
    "USSourceHealthEntry",
    "build_us_source_health",
]
