from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any, Mapping

from app.config import settings
from app.runtime_lock import ProcessFileLock


logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1
SUPPORTED_MARKETS = frozenset({"tw", "us", "jp", "kr"})
_CACHE_LOCK = RLock()
_CACHE_STATE: dict[str, Any] | None = None
_CACHE_PATH: Path | None = None
_CACHE_MTIME_NS: int | None = None


@dataclass(frozen=True)
class CachedHolidayLookup:
    covered: bool
    name: str | None


@dataclass(frozen=True)
class CalendarCacheUpdate:
    provider: str
    source: str
    source_url: str
    fetched_at: datetime
    holidays: Mapping[date, str]
    verified_years: frozenset[int]


def _empty_cache() -> dict[str, Any]:
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "updated_at": None,
        "markets": {},
    }


def _resolved_path(path: Path | None = None) -> Path:
    return Path(path or settings.market_calendar_cache_path).expanduser().resolve()


def invalidate_exchange_calendar_cache() -> None:
    global _CACHE_STATE, _CACHE_PATH, _CACHE_MTIME_NS
    with _CACHE_LOCK:
        _CACHE_STATE = None
        _CACHE_PATH = None
        _CACHE_MTIME_NS = None


def _validated_cache(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_cache()
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        return _empty_cache()
    if not isinstance(payload.get("markets"), dict):
        return _empty_cache()
    return payload


def read_exchange_calendar_cache(
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    global _CACHE_STATE, _CACHE_PATH, _CACHE_MTIME_NS
    cache_path = _resolved_path(path)
    try:
        mtime_ns = cache_path.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = None
    except OSError:
        logger.warning("Could not stat market calendar cache path=%s.", cache_path, exc_info=True)
        mtime_ns = None

    with _CACHE_LOCK:
        if (
            _CACHE_STATE is not None
            and _CACHE_PATH == cache_path
            and _CACHE_MTIME_NS == mtime_ns
        ):
            return _CACHE_STATE

        if mtime_ns is None:
            payload = _empty_cache()
        else:
            try:
                payload = _validated_cache(
                    json.loads(cache_path.read_text(encoding="utf-8"))
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                logger.warning(
                    "Could not read market calendar cache path=%s; fallback rules remain active.",
                    cache_path,
                    exc_info=True,
                )
                payload = _empty_cache()

        _CACHE_STATE = payload
        _CACHE_PATH = cache_path
        _CACHE_MTIME_NS = mtime_ns
        return payload


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Could not remove temporary market calendar cache path=%s.",
                    temp_path,
                    exc_info=True,
                )


def write_exchange_calendar_refresh(
    *,
    updates: Mapping[str, CalendarCacheUpdate],
    errors: Mapping[str, str],
    attempted_at: datetime,
    path: Path | None = None,
) -> dict[str, Any]:
    cache_path = _resolved_path(path)
    lock = ProcessFileLock(cache_path.with_suffix(f"{cache_path.suffix}.lock"))
    if not lock.acquire(timeout_seconds=5):
        raise TimeoutError(f"Timed out waiting for market calendar cache lock: {cache_path}")

    try:
        with _CACHE_LOCK:
            invalidate_exchange_calendar_cache()
            payload = read_exchange_calendar_cache(path=cache_path)
            markets = dict(payload.get("markets") or {})

            for raw_market, update in updates.items():
                market = str(raw_market).strip().lower()
                if market not in SUPPORTED_MARKETS:
                    raise ValueError(f"Unsupported market calendar cache key: {market}")
                years = sorted({int(year) for year in update.verified_years})
                if not years:
                    raise ValueError(f"Market calendar update has no verified years: {market}")

                previous = markets.get(market)
                previous_holidays = (
                    dict(previous.get("holidays") or {})
                    if isinstance(previous, dict)
                    else {}
                )
                for day_text in list(previous_holidays):
                    try:
                        day_year = date.fromisoformat(day_text).year
                    except (TypeError, ValueError):
                        previous_holidays.pop(day_text, None)
                        continue
                    if day_year in years:
                        previous_holidays.pop(day_text, None)
                for day, name in update.holidays.items():
                    if day.year in years:
                        previous_holidays[day.isoformat()] = str(name).strip() or "Market Holiday"

                previous_year_values = (
                    previous.get("verified_years") or []
                    if isinstance(previous, dict)
                    else []
                )
                previous_years = {
                    int(year)
                    for year in previous_year_values
                    if str(year).isdigit()
                }
                markets[market] = {
                    "provider": update.provider,
                    "source": update.source,
                    "source_url": update.source_url,
                    "fetched_at": update.fetched_at.astimezone(timezone.utc).isoformat(),
                    "last_attempt_at": attempted_at.astimezone(timezone.utc).isoformat(),
                    "last_error": None,
                    "verified_years": sorted(previous_years | set(years)),
                    "holidays": dict(sorted(previous_holidays.items())),
                }

            for raw_market, error_message in errors.items():
                market = str(raw_market).strip().lower()
                if market not in SUPPORTED_MARKETS:
                    continue
                previous = markets.get(market)
                entry = dict(previous) if isinstance(previous, dict) else {}
                entry["last_attempt_at"] = attempted_at.astimezone(timezone.utc).isoformat()
                entry["last_error"] = str(error_message).strip() or "Calendar refresh failed."
                entry.setdefault("verified_years", [])
                entry.setdefault("holidays", {})
                markets[market] = entry

            written = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "updated_at": attempted_at.astimezone(timezone.utc).isoformat(),
                "markets": markets,
            }
            _atomic_write(cache_path, written)
            invalidate_exchange_calendar_cache()
            return read_exchange_calendar_cache(path=cache_path)
    finally:
        lock.release()


def cached_market_holiday(
    market: str,
    value: date,
    *,
    path: Path | None = None,
) -> CachedHolidayLookup:
    normalized_market = str(market or "").strip().lower()
    payload = read_exchange_calendar_cache(path=path)
    entry = (payload.get("markets") or {}).get(normalized_market)
    if not isinstance(entry, dict):
        return CachedHolidayLookup(covered=False, name=None)

    verified_years = {
        int(year)
        for year in (entry.get("verified_years") or [])
        if str(year).isdigit()
    }
    if value.year not in verified_years:
        return CachedHolidayLookup(covered=False, name=None)

    holidays = entry.get("holidays")
    name = holidays.get(value.isoformat()) if isinstance(holidays, dict) else None
    return CachedHolidayLookup(
        covered=True,
        name=str(name).strip() if name else None,
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def market_calendar_cache_metadata(
    market: str,
    *,
    year: int,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    normalized_market = str(market or "").strip().lower()
    payload = read_exchange_calendar_cache(path=path)
    entry = (payload.get("markets") or {}).get(normalized_market)
    if not isinstance(entry, dict):
        return {
            "calendar_cache_status": "fallback",
            "calendar_last_refreshed_at": None,
            "calendar_source_url": None,
            "calendar_warning": "Automatic exchange-calendar cache is not available; built-in fallback rules are in use.",
            "cached_verified_years": [],
        }

    verified_years = sorted(
        {
            int(value)
            for value in (entry.get("verified_years") or [])
            if str(value).isdigit()
        }
    )
    fetched_at = _parse_datetime(entry.get("fetched_at"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    stale_after_days = max(int(settings.market_calendar_cache_stale_days), 1)
    is_stale = (
        fetched_at is None
        or (current - fetched_at).total_seconds() > stale_after_days * 86400
    )
    covered = year in verified_years
    last_error = str(entry.get("last_error") or "").strip()

    if not covered:
        status = "fallback"
        warning = (
            f"Official exchange-calendar cache does not cover {year}; built-in fallback rules are in use."
        )
    elif is_stale:
        status = "stale"
        warning = "Official exchange-calendar cache is stale; cached dates remain active while refresh retries continue."
    elif last_error:
        status = "degraded"
        warning = "The latest automatic calendar refresh failed; the last successful official cache remains active."
    else:
        status = "current"
        warning = None

    return {
        "calendar_cache_status": status,
        "calendar_last_refreshed_at": fetched_at.isoformat() if fetched_at else None,
        "calendar_source_url": entry.get("source_url"),
        "calendar_warning": warning,
        "cached_verified_years": verified_years,
        "cached_calendar_source": entry.get("source"),
    }


__all__ = [
    "CalendarCacheUpdate",
    "CachedHolidayLookup",
    "cached_market_holiday",
    "invalidate_exchange_calendar_cache",
    "market_calendar_cache_metadata",
    "read_exchange_calendar_cache",
    "write_exchange_calendar_refresh",
]
