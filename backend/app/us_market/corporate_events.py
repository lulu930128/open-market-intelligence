from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
from io import StringIO
import json
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    ProviderEvent,
    USCorporateAction,
    USCorporateEvent,
    USStockMaster,
)
from app.observability.provider_health import ERROR_STATUSES, record_provider_event
from app.us_market.errors import USMarketDataFetchError
from app.us_market.providers.alphavantage import (
    fetch_alphavantage_earnings_calendar_csv,
)
from app.us_market.symbols import normalize_us_symbol


US_MARKET_TIMEZONE = ZoneInfo("America/New_York")
US_MARKET_TIMEZONE_NAME = "America/New_York"
EARNINGS_PROVIDER = "alphavantage"
EARNINGS_RESOURCE = "corporate_events"
EARNINGS_HORIZON = "3month"
SUPPORTED_EVENT_TYPES = frozenset({"earnings", "dividend", "split"})
REMINDER_EVENT_TYPES = SUPPORTED_EVENT_TYPES
ACTION_COVERAGE_WARNING = (
    "Dividend and split coverage is limited to symbols already refreshed in the "
    "local US watchlist cache."
)


class USCorporateEventConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class NormalizedUSEarningsEvent:
    event_uid: str
    provider: str
    symbol: str
    company_name: str | None
    title: str
    event_date: date
    fiscal_year: int | None
    fiscal_period_end: date | None
    estimated_eps: float | None
    currency: str | None
    raw_payload_hash: str


def _now_utc(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _market_now(now: datetime | None = None) -> datetime:
    return _now_utc(now).astimezone(US_MARKET_TIMEZONE)


def _clean_setting(value: str | None) -> str:
    return (value or "").strip().strip('"').strip("'")


def _require_api_key() -> str:
    api_key = _clean_setting(settings.alphavantage_api_key)
    if not api_key:
        raise USCorporateEventConfigurationError(
            "ALPHAVANTAGE_API_KEY is not configured."
        )
    return api_key


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "nan", "-"}:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _row_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(
        {str(key): value for key, value in row.items()},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _logical_event_uid(
    *,
    symbol: str,
    fiscal_period_end: date | None,
    event_date: date,
) -> str:
    period_key = (
        fiscal_period_end.isoformat()
        if fiscal_period_end is not None
        else f"report-{event_date.isoformat()}"
    )
    return f"us:{symbol}:earnings:{period_key}"


def parse_alphavantage_earnings_calendar_csv(
    payload: str,
) -> tuple[list[NormalizedUSEarningsEvent], int]:
    reader = csv.DictReader(StringIO(payload.lstrip("\ufeff")))
    field_names = {str(field or "").strip() for field in (reader.fieldnames or [])}
    required = {"symbol", "reportDate"}
    if not required.issubset(field_names):
        raise USMarketDataFetchError(
            "Alpha Vantage earnings calendar CSV is missing required columns: "
            f"{sorted(required - field_names)}."
        )

    normalized: dict[str, NormalizedUSEarningsEvent] = {}
    malformed_count = 0
    for raw_row in reader:
        row = {str(key or "").strip(): value for key, value in raw_row.items()}
        report_date = _parse_date(row.get("reportDate"))
        raw_symbol = str(row.get("symbol") or "").strip()
        if report_date is None or not raw_symbol:
            malformed_count += 1
            continue
        try:
            symbol = normalize_us_symbol(raw_symbol)
        except (TypeError, ValueError):
            malformed_count += 1
            continue

        fiscal_period_end = _parse_date(row.get("fiscalDateEnding"))
        company_name = str(row.get("name") or "").strip() or None
        event_uid = _logical_event_uid(
            symbol=symbol,
            fiscal_period_end=fiscal_period_end,
            event_date=report_date,
        )
        normalized[event_uid] = NormalizedUSEarningsEvent(
            event_uid=event_uid,
            provider=EARNINGS_PROVIDER,
            symbol=symbol,
            company_name=company_name,
            title=f"{company_name or symbol} Earnings",
            event_date=report_date,
            fiscal_year=fiscal_period_end.year if fiscal_period_end else None,
            fiscal_period_end=fiscal_period_end,
            estimated_eps=_parse_float(row.get("estimate")),
            currency=str(row.get("currency") or "").strip().upper() or None,
            raw_payload_hash=_row_hash(row),
        )
    if not normalized:
        raise USMarketDataFetchError(
            "Alpha Vantage earnings calendar CSV contained no valid events."
        )
    return list(normalized.values()), malformed_count


def _event_changed(
    existing: USCorporateEvent,
    record: NormalizedUSEarningsEvent,
    *,
    source_url: str,
) -> bool:
    return any(
        (
            existing.provider != record.provider,
            existing.symbol != record.symbol,
            existing.company_name != record.company_name,
            existing.title != record.title,
            existing.event_date != record.event_date,
            existing.fiscal_year != record.fiscal_year,
            existing.fiscal_period_end != record.fiscal_period_end,
            existing.estimated_eps != record.estimated_eps,
            existing.currency != record.currency,
            existing.source_url != source_url,
            existing.raw_payload_hash != record.raw_payload_hash,
            not existing.is_active,
        )
    )


def _upsert_earnings_events(
    *,
    db: Session,
    records: list[NormalizedUSEarningsEvent],
    source_url: str,
    fetched_at: datetime,
) -> tuple[int, int, int]:
    event_uids = [record.event_uid for record in records]
    existing_by_uid = {
        item.event_uid: item
        for item in db.query(USCorporateEvent)
        .filter(USCorporateEvent.event_uid.in_(event_uids))
        .all()
    }
    inserted_count = 0
    updated_count = 0
    unchanged_count = 0

    for record in records:
        existing = existing_by_uid.get(record.event_uid)
        if existing is None:
            db.add(
                USCorporateEvent(
                    event_uid=record.event_uid,
                    provider=record.provider,
                    source_event_id=None,
                    symbol=record.symbol,
                    company_name=record.company_name,
                    event_type="earnings",
                    event_subtype="quarterly_earnings",
                    title=record.title,
                    description=None,
                    event_status="scheduled",
                    verification_status="third_party",
                    event_date=record.event_date,
                    event_time=None,
                    timezone_name=US_MARKET_TIMEZONE_NAME,
                    market_session="unknown",
                    is_all_day=True,
                    fiscal_year=record.fiscal_year,
                    fiscal_quarter=None,
                    fiscal_period_end=record.fiscal_period_end,
                    estimated_eps=record.estimated_eps,
                    currency=record.currency,
                    source_url=source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    first_seen_at=fetched_at,
                    last_seen_at=fetched_at,
                    fetched_at=fetched_at,
                    is_active=True,
                    created_at=fetched_at,
                    updated_at=fetched_at,
                )
            )
            inserted_count += 1
            continue

        changed = _event_changed(existing, record, source_url=source_url)
        existing.provider = record.provider
        existing.symbol = record.symbol
        existing.company_name = record.company_name
        existing.title = record.title
        existing.event_date = record.event_date
        existing.fiscal_year = record.fiscal_year
        existing.fiscal_period_end = record.fiscal_period_end
        existing.estimated_eps = record.estimated_eps
        existing.currency = record.currency
        existing.source_url = source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.last_seen_at = fetched_at
        existing.fetched_at = fetched_at
        existing.is_active = True
        existing.updated_at = fetched_at
        if changed:
            updated_count += 1
        else:
            unchanged_count += 1

    return inserted_count, updated_count, unchanged_count


def refresh_us_corporate_events(
    *,
    db: Session,
    now: datetime | None = None,
) -> dict[str, Any]:
    started_at = _now_utc(now)
    api_key = _require_api_key()
    source_url: str | None = None
    try:
        payload, source_url = fetch_alphavantage_earnings_calendar_csv(
            api_key=api_key,
            horizon=EARNINGS_HORIZON,
            timeout_seconds=max(
                int(settings.us_corporate_event_http_timeout_seconds),
                1,
            ),
        )
        records, malformed_count = parse_alphavantage_earnings_calendar_csv(payload)
        inserted_count, updated_count, unchanged_count = _upsert_earnings_events(
            db=db,
            records=records,
            source_url=source_url,
            fetched_at=started_at,
        )
        warnings = (
            [f"Skipped {malformed_count} malformed earnings calendar rows."]
            if malformed_count
            else []
        )
        record_provider_event(
            db,
            market="us",
            provider=EARNINGS_PROVIDER,
            resource=EARNINGS_RESOURCE,
            target="all",
            status="success",
            source_url=source_url,
            message="US earnings calendar refresh completed.",
            detail={
                "horizon": EARNINGS_HORIZON,
                "fetched_count": len(records) + malformed_count,
                "valid_count": len(records),
                "malformed_count": malformed_count,
                "inserted_count": inserted_count,
                "updated_count": updated_count,
                "unchanged_count": unchanged_count,
                "request_count": 1,
                "request_limit": 1,
            },
            commit=False,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            record_provider_event(
                db,
                market="us",
                provider=EARNINGS_PROVIDER,
                resource=EARNINGS_RESOURCE,
                target="all",
                status="error",
                source_url=source_url,
                message="US earnings calendar refresh failed.",
                error_message=str(exc),
                detail={
                    "horizon": EARNINGS_HORIZON,
                    "request_count": 1,
                    "request_limit": 1,
                },
            )
        except Exception:
            db.rollback()
        raise

    completed_at = _now_utc()
    return {
        "status": "completed",
        "provider": EARNINGS_PROVIDER,
        "horizon": EARNINGS_HORIZON,
        "started_at": started_at,
        "completed_at": completed_at,
        "fetched_count": len(records) + malformed_count,
        "valid_count": len(records),
        "malformed_count": malformed_count,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "request_count": 1,
        "request_limit": 1,
        "source_url": source_url,
        "warnings": warnings,
        "message": "Refreshed the cached US earnings calendar.",
    }


def _freshness(
    fetched_at: datetime | None,
    *,
    now: datetime,
    stale_after_hours: int,
) -> str:
    normalized = _as_utc(fetched_at)
    if normalized is None:
        return "missing"
    age = max((now - normalized).total_seconds(), 0)
    return "stale" if age > max(stale_after_hours, 1) * 3600 else "current"


def _latest_provider_event(db: Session) -> ProviderEvent | None:
    return (
        db.query(ProviderEvent)
        .filter(
            ProviderEvent.market == "us",
            ProviderEvent.provider == EARNINGS_PROVIDER,
            ProviderEvent.resource == EARNINGS_RESOURCE,
            ProviderEvent.target == "all",
        )
        .order_by(ProviderEvent.event_time.desc(), ProviderEvent.id.desc())
        .first()
    )


def _source_statuses(
    *,
    db: Session,
    now: datetime,
) -> dict[str, dict[str, Any]]:
    stale_after_hours = max(
        int(settings.us_corporate_event_cache_stale_hours),
        1,
    )
    earnings_count, earnings_fetched_at = (
        db.query(
            func.count(USCorporateEvent.id),
            func.max(USCorporateEvent.fetched_at),
        )
        .filter(
            USCorporateEvent.provider == EARNINGS_PROVIDER,
            USCorporateEvent.event_type == "earnings",
            USCorporateEvent.is_active.is_(True),
        )
        .one()
    )
    action_count, actions_fetched_at = db.query(
        func.count(USCorporateAction.id),
        func.max(USCorporateAction.fetched_at),
    ).one()

    earnings_freshness = _freshness(
        earnings_fetched_at,
        now=now,
        stale_after_hours=stale_after_hours,
    )
    latest_provider_event = _latest_provider_event(db)
    latest_event_time = _as_utc(
        latest_provider_event.event_time if latest_provider_event else None
    )
    normalized_earnings_fetched_at = _as_utc(earnings_fetched_at)
    provider_failed_after_cache = bool(
        latest_provider_event
        and latest_provider_event.status in ERROR_STATUSES
        and latest_event_time is not None
        and (
            normalized_earnings_fetched_at is None
            or latest_event_time >= normalized_earnings_fetched_at
        )
    )
    key_configured = bool(_clean_setting(settings.alphavantage_api_key))
    if provider_failed_after_cache:
        earnings_status = "degraded"
        earnings_warning = (
            latest_provider_event.error_message
            or "The latest earnings calendar refresh failed; cached data is shown."
        )
    elif not key_configured:
        earnings_status = "provider_not_configured"
        earnings_warning = (
            "ALPHAVANTAGE_API_KEY is not configured; only existing cached earnings "
            "events are available."
        )
    elif earnings_freshness == "missing":
        earnings_status = "missing"
        earnings_warning = "The US earnings calendar has not been refreshed yet."
    else:
        earnings_status = earnings_freshness
        earnings_warning = (
            "The cached US earnings calendar is older than the freshness target."
            if earnings_freshness == "stale"
            else None
        )

    actions_freshness = _freshness(
        actions_fetched_at,
        now=now,
        stale_after_hours=max(stale_after_hours, 24),
    )
    return {
        "alphavantage_earnings": {
            "source": "Alpha Vantage Earnings Calendar",
            "status": earnings_status,
            "freshness": earnings_freshness,
            "coverage": "us_market_3month",
            "fetched_at": _as_utc(earnings_fetched_at),
            "entry_count": int(earnings_count or 0),
            "warning": earnings_warning,
        },
        "alphavantage_actions": {
            "source": "Alpha Vantage Corporate Actions",
            "status": "watchlist_only",
            "freshness": actions_freshness,
            "coverage": "cached_symbols_only",
            "fetched_at": _as_utc(actions_fetched_at),
            "entry_count": int(action_count or 0),
            "warning": ACTION_COVERAGE_WARNING,
        },
    }


def _stock_metadata(
    db: Session,
    symbols: set[str],
) -> dict[str, tuple[str | None, str | None]]:
    if not symbols:
        return {}
    return {
        item.symbol: (item.security_name, item.exchange)
        for item in db.query(USStockMaster)
        .filter(USStockMaster.symbol.in_(symbols))
        .all()
    }


def _earnings_public_event(
    item: USCorporateEvent,
    *,
    as_of: date,
    now: datetime,
    stock_metadata: dict[str, tuple[str | None, str | None]],
) -> dict[str, Any]:
    security_name, exchange = stock_metadata.get(item.symbol, (None, None))
    freshness = _freshness(
        item.fetched_at,
        now=now,
        stale_after_hours=max(int(settings.us_corporate_event_cache_stale_hours), 1),
    )
    return {
        "event_id": item.event_uid,
        "event_uid": item.event_uid,
        "symbol": item.symbol,
        "company_name": item.company_name or security_name,
        "exchange": exchange,
        "country": "US",
        "currency": item.currency,
        "event_type": item.event_type,
        "event_subtype": item.event_subtype,
        "title": item.title,
        "description": item.description,
        "event_status": item.event_status,
        "verification_status": item.verification_status,
        "event_date": item.event_date,
        "event_time": item.event_time,
        "event_datetime_utc": None,
        "timezone": item.timezone_name,
        "market_session": item.market_session,
        "is_all_day": item.is_all_day,
        "days_until": (item.event_date - as_of).days,
        "fiscal_year": item.fiscal_year,
        "fiscal_quarter": item.fiscal_quarter,
        "fiscal_period_end": item.fiscal_period_end,
        "estimated_eps": item.estimated_eps,
        "declaration_date": None,
        "ex_date": None,
        "record_date": None,
        "payment_date": None,
        "dividend_amount": None,
        "dividend_currency": None,
        "split_from": None,
        "split_to": None,
        "split_ratio": None,
        "source": item.provider,
        "source_type": "provider_api",
        "source_event_id": item.source_event_id,
        "source_url": item.source_url,
        "first_seen_at": _as_utc(item.first_seen_at),
        "last_seen_at": _as_utc(item.last_seen_at),
        "fetched_at": _as_utc(item.fetched_at),
        "freshness": "stale" if freshness == "stale" else "fresh",
        "data_mode": "stale_cache" if freshness == "stale" else "cached",
        "is_stale": freshness == "stale",
        "missing_fields": ["event_time"],
        "warnings": [
            "The provider does not supply a reliable earnings release time."
        ],
    }


def _action_public_event(
    item: USCorporateAction,
    *,
    as_of: date,
    now: datetime,
    stock_metadata: dict[str, tuple[str | None, str | None]],
) -> dict[str, Any]:
    security_name, exchange = stock_metadata.get(item.symbol, (None, None))
    is_dividend = item.action_type == "dividend"
    event_type = "dividend" if is_dividend else "split"
    title = (
        f"{security_name or item.symbol} Cash Dividend"
        if is_dividend
        else f"{security_name or item.symbol} Stock Split"
    )
    freshness = _freshness(
        item.fetched_at,
        now=now,
        stale_after_hours=max(
            int(settings.us_corporate_event_cache_stale_hours),
            24,
        ),
    )
    event_uid = (
        f"us:{item.symbol}:{event_type}:{item.event_date.isoformat()}:"
        f"{item.provider}"
    )
    return {
        "event_id": event_uid,
        "event_uid": event_uid,
        "symbol": item.symbol,
        "company_name": security_name,
        "exchange": exchange,
        "country": "US",
        "currency": "USD" if is_dividend else None,
        "event_type": event_type,
        "event_subtype": "cash_dividend" if is_dividend else "stock_split",
        "title": title,
        "description": None,
        "event_status": "scheduled",
        "verification_status": "third_party",
        "event_date": item.event_date,
        "event_time": None,
        "event_datetime_utc": None,
        "timezone": US_MARKET_TIMEZONE_NAME,
        "market_session": "unknown",
        "is_all_day": True,
        "days_until": (item.event_date - as_of).days,
        "fiscal_year": None,
        "fiscal_quarter": None,
        "fiscal_period_end": None,
        "estimated_eps": None,
        "declaration_date": item.declaration_date,
        "ex_date": item.event_date if is_dividend else None,
        "record_date": item.record_date,
        "payment_date": item.payment_date,
        "dividend_amount": item.amount,
        "dividend_currency": "USD" if is_dividend else None,
        "split_from": item.split_from,
        "split_to": item.split_to,
        "split_ratio": item.split_ratio,
        "source": item.provider,
        "source_type": "provider_api",
        "source_event_id": None,
        "source_url": item.source_url,
        "first_seen_at": _as_utc(item.created_at),
        "last_seen_at": _as_utc(item.updated_at),
        "fetched_at": _as_utc(item.fetched_at),
        "freshness": "stale" if freshness == "stale" else "fresh",
        "data_mode": "stale_cache" if freshness == "stale" else "cached",
        "is_stale": freshness == "stale",
        "missing_fields": ["event_time"],
        "warnings": [ACTION_COVERAGE_WARNING],
    }


def list_us_corporate_events(
    *,
    db: Session,
    symbol: str | None = None,
    event_types: set[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    offset: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_utc = _now_utc(now)
    market_now = current_utc.astimezone(US_MARKET_TIMEZONE)
    as_of = market_now.date()
    start_filter = date_from or as_of
    end_filter = date_to or (as_of + timedelta(days=90))
    if end_filter < start_filter:
        raise ValueError("date_to must be on or after date_from.")
    if (end_filter - start_filter).days > 366:
        raise ValueError("The corporate-event date range cannot exceed 366 days.")

    normalized_symbol = normalize_us_symbol(symbol) if symbol else None
    normalized_types = {
        str(item).strip().lower()
        for item in (event_types or set())
        if str(item).strip()
    }
    unsupported_types = normalized_types - SUPPORTED_EVENT_TYPES
    if unsupported_types:
        raise ValueError(
            f"Unsupported US corporate event types: {sorted(unsupported_types)}."
        )
    selected_types = normalized_types or set(SUPPORTED_EVENT_TYPES)
    normalized_limit = max(1, min(int(limit), 1000))
    normalized_offset = max(0, min(int(offset), 5000))

    earnings: list[USCorporateEvent] = []
    if "earnings" in selected_types:
        query = db.query(USCorporateEvent).filter(
            USCorporateEvent.is_active.is_(True),
            USCorporateEvent.event_type == "earnings",
            USCorporateEvent.event_date >= start_filter,
            USCorporateEvent.event_date <= end_filter,
        )
        if normalized_symbol:
            query = query.filter(USCorporateEvent.symbol == normalized_symbol)
        earnings = query.all()

    actions: list[USCorporateAction] = []
    action_types = selected_types & {"dividend", "split"}
    if action_types:
        query = db.query(USCorporateAction).filter(
            USCorporateAction.action_type.in_(action_types),
            USCorporateAction.event_date >= start_filter,
            USCorporateAction.event_date <= end_filter,
        )
        if normalized_symbol:
            query = query.filter(USCorporateAction.symbol == normalized_symbol)
        actions = query.all()

    symbols = {item.symbol for item in earnings}
    symbols.update(item.symbol for item in actions)
    stock_metadata = _stock_metadata(db, symbols)
    results = [
        _earnings_public_event(
            item,
            as_of=as_of,
            now=current_utc,
            stock_metadata=stock_metadata,
        )
        for item in earnings
    ]
    results.extend(
        _action_public_event(
            item,
            as_of=as_of,
            now=current_utc,
            stock_metadata=stock_metadata,
        )
        for item in actions
    )
    type_priority = {"earnings": 0, "dividend": 1, "split": 2}
    results.sort(
        key=lambda item: (
            item["event_date"],
            type_priority.get(str(item["event_type"]), 9),
            str(item["symbol"]),
        )
    )
    paged_results = results[
        normalized_offset : normalized_offset + normalized_limit
    ]
    sources = _source_statuses(db=db, now=current_utc)
    warnings = [
        str(source["warning"])
        for source in sources.values()
        if source.get("warning")
    ]
    return {
        "kind": "us_corporate_events",
        "generated_at": current_utc,
        "as_of": as_of,
        "timezone": US_MARKET_TIMEZONE_NAME,
        "date_from": start_filter,
        "date_to": end_filter,
        "symbol": normalized_symbol,
        "event_types": sorted(normalized_types),
        "offset": normalized_offset,
        "limit": normalized_limit,
        "total_count": len(results),
        "result_count": len(paged_results),
        "warning": " ".join(dict.fromkeys(warnings)) or None,
        "sources": sources,
        "results": paged_results,
    }


def get_us_stock_event_summary(
    *,
    db: Session,
    symbol: str,
    reminder_days: int | None = None,
    max_results: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_utc = _now_utc(now)
    market_now = current_utc.astimezone(US_MARKET_TIMEZONE)
    days = max(
        min(
            int(
                reminder_days
                if reminder_days is not None
                else settings.us_corporate_event_reminder_days
            ),
            30,
        ),
        1,
    )
    listing = list_us_corporate_events(
        db=db,
        symbol=symbol,
        event_types=set(REMINDER_EVENT_TYPES),
        date_from=market_now.date(),
        date_to=market_now.date() + timedelta(days=days),
        limit=max(max_results, 1) * 3,
        now=current_utc,
    )
    results = listing["results"][: max(1, min(max_results, 10))]
    status_rank = {
        "missing": 5,
        "provider_not_configured": 4,
        "degraded": 3,
        "stale": 2,
        "watchlist_only": 1,
        "current": 0,
    }
    statuses = [
        str(source.get("status") or "missing")
        for source in listing["sources"].values()
    ]
    cache_status = (
        max(statuses, key=lambda value: status_rank.get(value, 5))
        if statuses
        else "missing"
    )
    fetched_dates = [
        source.get("fetched_at")
        for source in listing["sources"].values()
        if source.get("fetched_at") is not None
    ]
    return {
        "symbol": normalize_us_symbol(symbol),
        "checked_at": current_utc,
        "as_of": market_now.date(),
        "timezone": US_MARKET_TIMEZONE_NAME,
        "reminder_days": days,
        "cache_status": cache_status,
        "cache_fetched_at": min(fetched_dates) if fetched_dates else None,
        "warning": listing["warning"],
        "result_count": len(results),
        "results": results,
    }
