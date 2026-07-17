from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Query, Session

from app.db.models import (
    JPCompanyFundamental,
    JPDailyPrice,
    JPInvestorType,
    JPMarginInterest,
    JPStockMaster,
)
from app.jp_market.sources import normalize_jp_symbol
from app.jp_market.trading_calendar import (
    JPX_CALENDAR_SOURCE,
    JPX_VERIFIED_CALENDAR_YEARS,
    expected_jp_daily_price_date,
    jp_calendar_limit,
)
from app.observability.provider_health import (
    enrich_source_health_entries,
    sync_source_health_snapshots,
)
from app.observability.source_health_contract import (
    daily_row_status,
    freshness_lag_days,
    generated_at,
    summarize_source_health,
)


DAILY_PRICE_PROVIDERS = ("yahoo_chart",)
FUNDAMENTAL_PROVIDERS = ("jquants_statements", "yahoo_quote_summary")
MARGIN_INTEREST_PROVIDER = "jquants_margin_interest"
INVESTOR_TYPES_PROVIDER = "jquants_investor_types"


@dataclass(frozen=True)
class JPSourceHealthEntry:
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
        }


def _target(value: str | None) -> str:
    return value or "all"


def _latest_or_none(query: Query, *order_by):
    return query.order_by(*order_by).first()


def _status_for(
    *,
    row_count: int,
    latest_data_date: date | None,
    expected_data_date: date | None = None,
) -> tuple[str, bool, str, str]:
    return daily_row_status(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=expected_data_date is not None,
        empty_reason="No local rows are available for this Japan provider/resource.",
        current_reason="Latest local row is aligned with the supplied Japan trade date.",
        available_reason=(
            "Local rows are available; exact freshness is not enforced because a Japan "
            "exchange-calendar target was not supplied."
        ),
    )


def _entry_from_query(
    *,
    query: Query,
    resource: str,
    provider: str,
    target: str,
    latest_data_attr: str | None,
    latest_fetched_attr: str | None,
    order_by: tuple[Any, ...],
    expected_data_date: date | None = None,
    source_url_attr: str | None = "source_url",
) -> JPSourceHealthEntry:
    row_count = query.count()
    latest = _latest_or_none(query, *order_by)
    latest_data_date = getattr(latest, latest_data_attr, None) if latest and latest_data_attr else None
    latest_fetched_at = getattr(latest, latest_fetched_attr, None) if latest and latest_fetched_attr else None
    source_url = getattr(latest, source_url_attr, None) if latest and source_url_attr else None
    status_value, ok, data_quality, reason = _status_for(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
    )
    return JPSourceHealthEntry(
        resource=resource,
        provider=provider,
        target=target,
        status=status_value,
        ok=ok,
        row_count=row_count,
        latest_data_date=latest_data_date,
        latest_fetched_at=latest_fetched_at,
        expected_data_date=expected_data_date,
        freshness_lag_days=freshness_lag_days(expected_data_date, latest_data_date),
        source_url=source_url,
        data_quality=data_quality,
        reason=reason,
    )


def _symbol_master_entry(db: Session, *, symbol: str | None) -> JPSourceHealthEntry:
    query = db.query(JPStockMaster)
    if symbol is not None:
        query = query.filter(JPStockMaster.symbol == symbol)
    return _entry_from_query(
        query=query,
        resource="symbol_master",
        provider="jpx_listed_issues+yahoo_chart",
        target=_target(symbol),
        latest_data_attr=None,
        latest_fetched_attr="last_seen_at",
        source_url_attr=None,
        order_by=(JPStockMaster.last_seen_at.desc(), JPStockMaster.id.desc()),
    )


def _daily_price_entries(
    db: Session,
    *,
    symbol: str | None,
    expected_daily_price_date: date | None,
) -> list[JPSourceHealthEntry]:
    entries: list[JPSourceHealthEntry] = []
    for provider in DAILY_PRICE_PROVIDERS:
        query = db.query(JPDailyPrice).filter(JPDailyPrice.provider == provider)
        if symbol is not None:
            query = query.filter(JPDailyPrice.symbol == symbol)
        entries.append(
            _entry_from_query(
                query=query,
                resource="daily_price",
                provider=provider,
                target=_target(symbol),
                latest_data_attr="trade_date",
                latest_fetched_attr="fetched_at",
                expected_data_date=expected_daily_price_date,
                order_by=(
                    JPDailyPrice.trade_date.desc(),
                    JPDailyPrice.fetched_at.desc(),
                    JPDailyPrice.id.desc(),
                ),
            )
        )
    return entries


def _fundamental_entries(db: Session, *, symbol: str | None) -> list[JPSourceHealthEntry]:
    entries: list[JPSourceHealthEntry] = []
    for provider in FUNDAMENTAL_PROVIDERS:
        query = db.query(JPCompanyFundamental).filter(JPCompanyFundamental.provider == provider)
        if symbol is not None:
            query = query.filter(JPCompanyFundamental.symbol == symbol)
        entries.append(
            _entry_from_query(
                query=query,
                resource="fundamentals",
                provider=provider,
                target=_target(symbol),
                latest_data_attr="disclosed_date",
                latest_fetched_attr="fetched_at",
                order_by=(
                    JPCompanyFundamental.disclosed_date.desc(),
                    JPCompanyFundamental.fetched_at.desc(),
                    JPCompanyFundamental.id.desc(),
                ),
            )
        )
    return entries


def _margin_interest_entry(db: Session, *, symbol: str | None) -> JPSourceHealthEntry:
    query = db.query(JPMarginInterest).filter(JPMarginInterest.provider == MARGIN_INTEREST_PROVIDER)
    if symbol is not None:
        query = query.filter(JPMarginInterest.symbol == symbol)
    return _entry_from_query(
        query=query,
        resource="margin_interest",
        provider=MARGIN_INTEREST_PROVIDER,
        target=_target(symbol),
        latest_data_attr="report_date",
        latest_fetched_attr="fetched_at",
        order_by=(
            JPMarginInterest.report_date.desc(),
            JPMarginInterest.fetched_at.desc(),
            JPMarginInterest.id.desc(),
        ),
    )


def _investor_section(stock: JPStockMaster | None) -> str | None:
    segment = (stock.market_segment or "").lower() if stock is not None else ""
    if "prime" in segment:
        return "TSEPrime"
    if "standard" in segment:
        return "TSEStandard"
    if "growth" in segment or "mothers" in segment:
        return "TSEGrowth"
    return None


def _investor_types_entry(
    db: Session,
    *,
    stock: JPStockMaster | None,
    requested_symbol: str | None,
) -> JPSourceHealthEntry:
    section = _investor_section(stock)
    if requested_symbol is not None and section is None:
        return JPSourceHealthEntry(
            resource="investor_types",
            provider=INVESTOR_TYPES_PROVIDER,
            target=requested_symbol,
            status="empty",
            ok=False,
            row_count=0,
            data_quality="empty",
            reason=(
                "The selected Japan symbol cannot be mapped to a J-Quants investor "
                "section, so market-wide rows are not treated as symbol coverage."
            ),
        )
    query = db.query(JPInvestorType).filter(JPInvestorType.provider == INVESTOR_TYPES_PROVIDER)
    if section is not None:
        query = query.filter(JPInvestorType.section == section)
    return _entry_from_query(
        query=query,
        resource="investor_types",
        provider=INVESTOR_TYPES_PROVIDER,
        target=_target(section),
        latest_data_attr="published_date",
        latest_fetched_attr="fetched_at",
        order_by=(
            JPInvestorType.published_date.desc(),
            JPInvestorType.fetched_at.desc(),
            JPInvestorType.id.desc(),
        ),
    )


def build_jp_source_health(
    db: Session,
    *,
    symbol: str | None = None,
    expected_daily_price_date: date | None = None,
    use_expected_date: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_jp_symbol(symbol) if symbol else None
    resolved_expected_date = expected_daily_price_date
    if resolved_expected_date is None and use_expected_date:
        resolved_expected_date = expected_jp_daily_price_date(now=now)
    stock = (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == normalized_symbol)
        .first()
        if normalized_symbol is not None
        else None
    )
    entries = [
        _symbol_master_entry(db, symbol=normalized_symbol),
        *_daily_price_entries(
            db,
            symbol=normalized_symbol,
            expected_daily_price_date=resolved_expected_date,
        ),
        *_fundamental_entries(db, symbol=normalized_symbol),
        _margin_interest_entry(db, symbol=normalized_symbol),
        _investor_types_entry(
            db,
            stock=stock,
            requested_symbol=normalized_symbol,
        ),
    ]
    entry_dicts = enrich_source_health_entries(
        db,
        market="jp",
        entries=[entry.to_dict() for entry in entries],
    )
    checked_at = generated_at()
    sync_source_health_snapshots(
        db,
        market="jp",
        entries=entry_dicts,
        checked_at=checked_at,
    )
    return {
        "kind": "jp_source_health",
        "generated_at": checked_at.isoformat(),
        "filters": {"symbol": normalized_symbol},
        "expected_daily_price_date": (
            resolved_expected_date.isoformat() if resolved_expected_date else None
        ),
        "freshness_policy": {
            "mode": "expected_date" if resolved_expected_date else "availability_only",
            "calendar_source": JPX_CALENDAR_SOURCE,
            "calendar_verified_years": sorted(JPX_VERIFIED_CALENDAR_YEARS),
            "calendar_limit": (
                jp_calendar_limit(resolved_expected_date.year)
                if resolved_expected_date
                else "Expected-date enforcement was disabled for this diagnostic request."
            ),
        },
        "summary": summarize_source_health(
            entries,
            counted_statuses=("empty", "stale", "error"),
        ),
        "entries": entry_dicts,
    }


__all__ = ["JPSourceHealthEntry", "build_jp_source_health"]
