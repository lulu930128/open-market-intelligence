from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timezone
import logging
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.jp_market.providers.jpx import fetch_jpx_market_holidays
from app.kr_market.providers.krx import fetch_krx_market_holidays
from app.market.exchange_calendar_cache import (
    CalendarCacheUpdate,
    write_exchange_calendar_refresh,
)
from app.market.providers.twse import fetch_twse_holiday_schedule
from app.observability.provider_health import record_provider_event
from app.observability.provider_http import provider_http_failure
from app.us_market.providers.nyse import fetch_nyse_market_holidays


logger = logging.getLogger(__name__)

SUPPORTED_MARKETS = ("tw", "us", "jp", "kr")
PROVIDER_BY_MARKET = {
    "tw": "twse_openapi",
    "us": "nyse_calendar",
    "jp": "jpx_calendar",
    "kr": "krx_calendar",
}
SOURCE_BY_MARKET = {
    "tw": "TWSE Holiday Schedule OpenAPI",
    "us": "NYSE Holidays & Trading Hours",
    "jp": "JPX Market Holidays",
    "kr": "KRX Market Holidays",
}
TARGET_BY_MARKET = {
    "tw": "TWSE",
    "us": "NYSE",
    "jp": "TSE",
    "kr": "KRX",
}


def _normalize_markets(markets: Iterable[str] | None) -> list[str]:
    requested = list(markets) if markets is not None else list(SUPPORTED_MARKETS)
    normalized: list[str] = []
    for value in requested:
        market = str(value or "").strip().lower()
        if market not in SUPPORTED_MARKETS:
            raise ValueError(
                f"market must be one of: {', '.join(SUPPORTED_MARKETS)}."
            )
        if market not in normalized:
            normalized.append(market)
    if not normalized:
        raise ValueError("At least one market calendar must be requested.")
    return normalized


def _fetch_calendar(
    market: str,
    *,
    now: datetime,
    timeout_seconds: int,
) -> tuple[dict[date, str], str]:
    if market == "tw":
        return fetch_twse_holiday_schedule(timeout_seconds=timeout_seconds)
    if market == "us":
        return fetch_nyse_market_holidays(timeout_seconds=timeout_seconds)
    if market == "jp":
        return fetch_jpx_market_holidays(timeout_seconds=timeout_seconds)
    if market == "kr":
        korea_year = now.astimezone(ZoneInfo("Asia/Seoul")).year
        return fetch_krx_market_holidays(
            year=korea_year,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"Unsupported market calendar: {market}")


def _record_event(
    db: Session | None,
    *,
    market: str,
    status: str,
    message: str | None = None,
    error: BaseException | None = None,
    source_url: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    if db is None:
        return
    failure = provider_http_failure(error) if error is not None else None
    try:
        record_provider_event(
            db,
            market=market,
            provider=PROVIDER_BY_MARKET[market],
            resource="exchange_calendar",
            target=TARGET_BY_MARKET[market],
            status=failure.status if failure is not None else status,
            event_type="calendar_refresh",
            http_status_code=failure.http_status_code if failure is not None else None,
            rate_limited=failure.rate_limited if failure is not None else False,
            retry_after_seconds=(
                failure.retry_after_seconds if failure is not None else None
            ),
            source_url=failure.source_url if failure is not None else source_url,
            message=message,
            error_message=str(error) if error is not None else None,
            detail=detail,
        )
    except Exception:
        db.rollback()
        logger.warning(
            "Failed to record exchange-calendar provider event market=%s.",
            market,
            exc_info=True,
        )


def refresh_exchange_calendars(
    *,
    markets: Iterable[str] | None = None,
    now: datetime | None = None,
    timeout_seconds: int | None = None,
    cache_path: Path | None = None,
    db: Session | None = None,
    fetch_calendar: Callable[..., tuple[dict[date, str], str]] | None = None,
) -> dict[str, Any]:
    requested_markets = _normalize_markets(markets)
    started_at = now or datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    started_at = started_at.astimezone(timezone.utc)
    resolved_timeout = max(
        int(timeout_seconds or settings.market_calendar_http_timeout_seconds),
        1,
    )
    fetcher = fetch_calendar or _fetch_calendar

    updates: dict[str, CalendarCacheUpdate] = {}
    errors: dict[str, str] = {}
    exceptions: dict[str, BaseException] = {}
    results: dict[str, dict[str, Any]] = {}

    for market in requested_markets:
        try:
            holidays, source_url = fetcher(
                market,
                now=started_at,
                timeout_seconds=resolved_timeout,
            )
            years = frozenset(day.year for day in holidays)
            if not holidays or not years:
                raise ValueError(
                    f"{market.upper()} exchange calendar returned no usable holidays."
                )
            updates[market] = CalendarCacheUpdate(
                provider=PROVIDER_BY_MARKET[market],
                source=SOURCE_BY_MARKET[market],
                source_url=source_url,
                fetched_at=started_at,
                holidays=holidays,
                verified_years=years,
            )
            results[market] = {
                "market": market,
                "status": "success",
                "provider": PROVIDER_BY_MARKET[market],
                "source_url": source_url,
                "fetched_at": started_at.isoformat(),
                "holiday_count": len(holidays),
                "verified_years": sorted(years),
                "error_message": None,
            }
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            errors[market] = message
            exceptions[market] = exc
            results[market] = {
                "market": market,
                "status": "error",
                "provider": PROVIDER_BY_MARKET[market],
                "source_url": None,
                "fetched_at": None,
                "holiday_count": 0,
                "verified_years": [],
                "error_message": message,
            }

    try:
        write_exchange_calendar_refresh(
            updates=updates,
            errors=errors,
            attempted_at=started_at,
            path=cache_path,
        )
    except Exception as exc:
        cache_error = str(exc).strip() or type(exc).__name__
        for market in requested_markets:
            if market in updates:
                exceptions[market] = exc
                results[market].update(
                    status="error",
                    fetched_at=None,
                    error_message=f"Calendar cache write failed: {cache_error}",
                )
        logger.exception("Could not persist exchange-calendar refresh cache.")

    for market in requested_markets:
        result = results[market]
        if result["status"] == "success":
            _record_event(
                db,
                market=market,
                status="success",
                source_url=result["source_url"],
                message=(
                    f"Refreshed official exchange calendar for years "
                    f"{','.join(str(year) for year in result['verified_years'])}."
                ),
                detail={
                    "holiday_count": result["holiday_count"],
                    "verified_years": result["verified_years"],
                    "request_limit": 1 if market != "kr" else 3,
                },
            )
        else:
            _record_event(
                db,
                market=market,
                status="error",
                error=exceptions.get(market),
                message="Official exchange-calendar refresh failed; cached or fallback rules remain active.",
                detail={"timeout_seconds": resolved_timeout},
            )

    completed_at = datetime.now(timezone.utc)
    return {
        "kind": "market_calendar_refresh",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "requested_markets": requested_markets,
        "request_limit": sum(3 if market == "kr" else 1 for market in requested_markets),
        "success_count": sum(
            1 for result in results.values() if result["status"] == "success"
        ),
        "error_count": sum(
            1 for result in results.values() if result["status"] == "error"
        ),
        "results": results,
    }


__all__ = ["refresh_exchange_calendars"]
