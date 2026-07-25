from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Query, Session

from app.db.models import (
    KRCompanyFundamental,
    KRDailyPrice,
    KRIndexDailyPrice,
    KRInvestorTradeDaily,
    KRStockMaster,
)
from app.kr_market.sources import normalize_kr_index_id, normalize_kr_symbol
from app.kr_market.trading_calendar import expected_kr_daily_price_date
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


DAILY_PROVIDER_ORDER = ("krx_data", "yahoo_chart")


@dataclass(frozen=True)
class KRSourceHealthEntry:
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


def _target(*, symbol: str | None = None) -> str:
    return symbol or "all"


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
        empty_reason="No local rows are available for this provider/resource.",
        current_reason="Latest local row is aligned with the expected KR trade date.",
        available_reason="Local rows are available; no daily freshness target is enforced.",
    )


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
) -> KRSourceHealthEntry:
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

    return KRSourceHealthEntry(
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


def _symbol_master_entry(db: Session, *, symbol: str | None) -> KRSourceHealthEntry:
    query = db.query(KRStockMaster)
    if symbol is not None:
        query = query.filter(KRStockMaster.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="symbol_master",
        provider="krx_data+yahoo_chart",
        target=_target(symbol=symbol),
        latest_data_attr=None,
        latest_fetched_attr="last_seen_at",
        source_url_attr=None,
        order_by=(KRStockMaster.last_seen_at.desc(), KRStockMaster.id.desc()),
    )


def _daily_price_entries(
    db: Session,
    *,
    symbol: str | None,
    expected_daily_price_date: date | None,
) -> list[KRSourceHealthEntry]:
    entries: list[KRSourceHealthEntry] = []
    target = _target(symbol=symbol)

    for provider in DAILY_PROVIDER_ORDER:
        query = db.query(KRDailyPrice).filter(KRDailyPrice.provider == provider)
        if symbol is not None:
            query = query.filter(KRDailyPrice.symbol == symbol)
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
                    KRDailyPrice.trade_date.desc(),
                    KRDailyPrice.fetched_at.desc(),
                    KRDailyPrice.id.desc(),
                ),
            )
        )

    return entries


def _index_daily_price_entry(
    db: Session,
    *,
    index_id: str,
    expected_daily_price_date: date | None,
) -> KRSourceHealthEntry:
    query = db.query(KRIndexDailyPrice).filter(
        KRIndexDailyPrice.index_id == index_id
    )
    return _entry_from_query(
        query=query,
        resource="index_daily_price",
        provider="naver_sise_index",
        target=index_id,
        latest_data_attr="trade_date",
        latest_fetched_attr="fetched_at",
        expected_data_date=expected_daily_price_date,
        freshness_required=True,
        order_by=(
            KRIndexDailyPrice.trade_date.desc(),
            KRIndexDailyPrice.fetched_at.desc(),
            KRIndexDailyPrice.id.desc(),
        ),
    )


def _fundamentals_entry(db: Session, *, symbol: str | None) -> KRSourceHealthEntry:
    query = db.query(KRCompanyFundamental)
    if symbol is not None:
        query = query.filter(KRCompanyFundamental.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="financials",
        provider="opendart_fnltt_singl_acnt_all",
        target=_target(symbol=symbol),
        latest_data_attr="disclosed_date",
        latest_fetched_attr="fetched_at",
        order_by=(
            KRCompanyFundamental.disclosed_date.desc(),
            KRCompanyFundamental.fetched_at.desc(),
            KRCompanyFundamental.id.desc(),
        ),
    )


def _investor_trade_entry(db: Session, *, symbol: str | None) -> KRSourceHealthEntry:
    query = db.query(KRInvestorTradeDaily)
    if symbol is not None:
        query = query.filter(KRInvestorTradeDaily.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="investor_trading",
        provider="krx_investor_trading",
        target=_target(symbol=symbol),
        latest_data_attr="trade_date",
        latest_fetched_attr="fetched_at",
        order_by=(
            KRInvestorTradeDaily.trade_date.desc(),
            KRInvestorTradeDaily.fetched_at.desc(),
            KRInvestorTradeDaily.id.desc(),
        ),
    )


def _summary(entries: list[KRSourceHealthEntry]) -> dict[str, int]:
    return summarize_source_health(
        entries,
        counted_statuses=("empty", "stale", "error"),
    )


def build_kr_source_health(
    db: Session,
    *,
    symbol: str | None = None,
    index_id: str | None = None,
    now: datetime | None = None,
    expected_daily_price_date: date | None = None,
) -> dict[str, Any]:
    if symbol and index_id:
        raise ValueError("symbol and index_id are mutually exclusive.")
    normalized_symbol = normalize_kr_symbol(symbol) if symbol else None
    normalized_index_id = normalize_kr_index_id(index_id) if index_id else None
    expected_date = expected_daily_price_date or expected_kr_daily_price_date(now=now)
    entries = (
        [
            _index_daily_price_entry(
                db,
                index_id=normalized_index_id,
                expected_daily_price_date=expected_date,
            )
        ]
        if normalized_index_id
        else [
            _symbol_master_entry(db, symbol=normalized_symbol),
            *_daily_price_entries(
                db,
                symbol=normalized_symbol,
                expected_daily_price_date=expected_date,
            ),
            _fundamentals_entry(db, symbol=normalized_symbol),
            _investor_trade_entry(db, symbol=normalized_symbol),
        ]
    )
    generated_at = _generated_at()
    entry_dicts = enrich_source_health_entries(
        db,
        market="kr",
        entries=[entry.to_dict() for entry in entries],
    )
    sync_source_health_snapshots(
        db,
        market="kr",
        entries=entry_dicts,
        checked_at=generated_at,
    )

    return {
        "kind": "kr_source_health",
        "generated_at": generated_at.isoformat(),
        "filters": {
            "symbol": normalized_symbol,
            "index_id": normalized_index_id,
        },
        "expected_daily_price_date": expected_date.isoformat() if expected_date else None,
        "summary": _summary(entries),
        "entries": entry_dicts,
    }


__all__ = [
    "KRSourceHealthEntry",
    "build_kr_source_health",
]
