from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.market.providers.tw_corporate_events import (
    MOPS_CONFERENCE_URL,
    MOPS_PROVIDER,
    MopsConferenceBatch,
    TPEX_EX_DIVIDEND_HISTORY_URL,
    TPEX_EX_DIVIDEND_URL,
    TPEX_PROVIDER,
    TWSE_EX_DIVIDEND_HISTORY_URL,
    TWSE_EX_DIVIDEND_URL,
    TWSE_PROVIDER,
    fetch_mops_conference_history,
    fetch_mops_conferences,
    fetch_tpex_ex_dividend_history,
    fetch_tpex_ex_dividends,
    fetch_twse_ex_dividend_history,
    fetch_twse_ex_dividends,
)
from app.observability.provider_health import record_provider_event
from app.observability.provider_http import provider_http_failure
from app.runtime_lock import ProcessFileLock


logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1
TAIWAN_TZ = ZoneInfo("Asia/Taipei")
PROVIDER_CONFIG = {
    "twse_ex_dividend": {
        "provider": TWSE_PROVIDER,
        "market": "TWSE",
        "source": "TWSE 上市股票除權除息預告表",
        "source_url": TWSE_EX_DIVIDEND_URL,
    },
    "tpex_ex_dividend": {
        "provider": TPEX_PROVIDER,
        "market": "TPEX",
        "source": "TPEx 上櫃股票除權除息預告表",
        "source_url": TPEX_EX_DIVIDEND_URL,
    },
    "mops_conference": {
        "provider": MOPS_PROVIDER,
        "market": "TWSE,TPEX",
        "source": "MOPS 法人說明會一覽表",
        "source_url": MOPS_CONFERENCE_URL,
    },
    "twse_ex_dividend_history": {
        "provider": TWSE_PROVIDER,
        "market": "TWSE",
        "source": "TWSE 除權除息計算結果表",
        "source_url": TWSE_EX_DIVIDEND_HISTORY_URL,
        "archive": True,
    },
    "tpex_ex_dividend_history": {
        "provider": TPEX_PROVIDER,
        "market": "TPEX",
        "source": "TPEx 除權除息計算結果表",
        "source_url": TPEX_EX_DIVIDEND_HISTORY_URL,
        "archive": True,
    },
    "mops_conference_history": {
        "provider": MOPS_PROVIDER,
        "market": "TWSE,TPEX",
        "source": "MOPS 法人說明會歷史資料",
        "source_url": MOPS_CONFERENCE_URL,
        "archive": True,
    },
}

CURRENT_PROVIDER_KEYS = (
    "twse_ex_dividend",
    "tpex_ex_dividend",
    "mops_conference",
)
HISTORY_PROVIDER_KEYS = (
    "twse_ex_dividend_history",
    "tpex_ex_dividend_history",
    "mops_conference_history",
)
STOCK_REMINDER_EVENT_TYPES = frozenset(
    {"ex_dividend", "financial_report", "investor_conference"}
)

_CACHE_LOCK = RLock()
_CACHE_STATE: dict[str, Any] | None = None
_CACHE_PATH: Path | None = None
_CACHE_MTIME_NS: int | None = None


def _empty_cache() -> dict[str, Any]:
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "updated_at": None,
        "providers": {},
    }


def _resolved_path(path: Path | None = None) -> Path:
    configured = getattr(
        settings,
        "tw_corporate_event_cache_path",
        Path("data") / "tw_corporate_events.json",
    )
    return Path(path or configured).expanduser().resolve()


def _resolved_mops_max_attempts() -> int:
    return max(
        1,
        min(
            int(getattr(settings, "tw_corporate_event_mops_max_attempts", 2)),
            3,
        ),
    )


def invalidate_taiwan_corporate_event_cache() -> None:
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
    if not isinstance(payload.get("providers"), dict):
        return _empty_cache()
    return payload


def read_taiwan_corporate_event_cache(
    *, path: Path | None = None
) -> dict[str, Any]:
    global _CACHE_STATE, _CACHE_PATH, _CACHE_MTIME_NS
    cache_path = _resolved_path(path)
    try:
        mtime_ns = cache_path.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = None
    except OSError:
        logger.warning("Could not stat Taiwan corporate-event cache path=%s.", cache_path)
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
                    "Could not read Taiwan corporate-event cache path=%s.",
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
            temp_path.unlink(missing_ok=True)


def _json_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in entry.items()
    }


def _write_refresh(
    *,
    updates: Mapping[str, dict[str, Any]],
    errors: Mapping[str, str],
    attempted_at: datetime,
    path: Path | None = None,
    error_details: Mapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    cache_path = _resolved_path(path)
    process_lock = ProcessFileLock(
        cache_path.with_suffix(f"{cache_path.suffix}.lock")
    )
    if not process_lock.acquire(timeout_seconds=5):
        raise TimeoutError(
            f"Timed out waiting for Taiwan corporate-event cache lock: {cache_path}"
        )
    try:
        with _CACHE_LOCK:
            invalidate_taiwan_corporate_event_cache()
            payload = read_taiwan_corporate_event_cache(path=cache_path)
            providers = dict(payload.get("providers") or {})
            attempted_text = attempted_at.astimezone(timezone.utc).isoformat()

            for provider_key, update in updates.items():
                config = PROVIDER_CONFIG[provider_key]
                providers[provider_key] = {
                    **config,
                    "fetched_at": attempted_text,
                    "last_attempt_at": attempted_text,
                    "last_error": None,
                    "last_failure_details": list(
                        update.get("last_failure_details") or []
                    ),
                    "partial_success": bool(update.get("partial_success", False)),
                    "successful_windows": list(update.get("successful_windows") or []),
                    "recovered_windows": list(update.get("recovered_windows") or []),
                    "retry_count": max(int(update.get("retry_count") or 0), 0),
                    "request_count": int(update.get("request_count") or 0),
                    "coverage_start": _json_entry(
                        {"value": update.get("coverage_start")}
                    )["value"],
                    "coverage_end": _json_entry(
                        {"value": update.get("coverage_end")}
                    )["value"],
                    "coverage_years": sorted(
                        {
                            int(year)
                            for year in update.get("coverage_years") or []
                        }
                    ),
                    "failed_years": sorted(
                        {
                            int(year)
                            for year in update.get("failed_years") or []
                        }
                    ),
                    "entries": [
                        _json_entry(entry) for entry in update.get("entries") or []
                    ],
                }

            for provider_key, error_message in errors.items():
                previous = providers.get(provider_key)
                entry = dict(previous) if isinstance(previous, dict) else {
                    **PROVIDER_CONFIG[provider_key],
                    "fetched_at": None,
                    "request_count": 0,
                    "coverage_start": None,
                    "coverage_end": None,
                    "entries": [],
                }
                entry["last_attempt_at"] = attempted_text
                entry["last_error"] = str(error_message).strip() or "Refresh failed."
                entry["last_failure_details"] = list(
                    (error_details or {}).get(provider_key) or []
                )
                if provider_key not in updates:
                    entry["partial_success"] = False
                    entry["successful_windows"] = []
                    entry["recovered_windows"] = []
                    entry["retry_count"] = 0
                providers[provider_key] = entry

            written = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "updated_at": attempted_text,
                "providers": providers,
            }
            _atomic_write(cache_path, written)
            invalidate_taiwan_corporate_event_cache()
            return read_taiwan_corporate_event_cache(path=cache_path)
    finally:
        process_lock.release()


def _parse_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _mops_event_window_key(entry: Mapping[str, Any]) -> str | None:
    market = str(entry.get("market") or "").strip().upper()
    event_date = _parse_date(entry.get("start_date"))
    if not market or event_date is None:
        return None
    return f"{market}:{event_date.year}-{event_date.month:02d}"


def _merge_partial_mops_entries(
    batch: MopsConferenceBatch,
    *,
    previous_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    failed_windows = {
        f"{failure.market.upper()}:{failure.window}"
        for failure in batch.failures
    }
    preserved = [
        entry
        for entry in previous_entries
        if _mops_event_window_key(entry) in failed_windows
    ]
    combined = {
        str(entry.get("event_id")): entry
        for entry in [*preserved, *batch.entries]
        if entry.get("event_id")
    }
    return sorted(
        combined.values(),
        key=lambda item: (
            _parse_date(item.get("start_date")) or date.max,
            str(item.get("start_time") or ""),
            str(item.get("stock_id") or ""),
            str(item.get("event_type") or ""),
        ),
    )


def _local_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(TAIWAN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(TAIWAN_TZ)


def _provider_cache_status(
    entry: Any,
    *,
    now: datetime,
    archive: bool = False,
) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {
            "status": "missing",
            "fetched_at": None,
            "last_attempt_at": None,
            "last_error": None,
            "warning": "尚無官方公司事件 cache。",
        }
    fetched_at = _parse_datetime(entry.get("fetched_at"))
    last_attempt_at = _parse_datetime(entry.get("last_attempt_at"))
    last_error = str(entry.get("last_error") or "").strip() or None
    last_failure_details = [
        dict(item)
        for item in entry.get("last_failure_details") or []
        if isinstance(item, dict)
    ]
    partial_success = bool(entry.get("partial_success"))
    stale_hours = (
        max(
            int(
                getattr(
                    settings,
                    "tw_corporate_event_history_refresh_days",
                    7,
                )
            ),
            1,
        )
        * 24
        * 2
        if archive
        else max(
            int(getattr(settings, "tw_corporate_event_cache_stale_hours", 48)),
            1,
        )
    )
    age_seconds = (
        max(0, int((now.astimezone(timezone.utc) - fetched_at).total_seconds()))
        if fetched_at is not None
        else None
    )
    is_stale = age_seconds is None or age_seconds > stale_hours * 3600
    if fetched_at is None:
        status = "missing"
    elif last_error:
        status = "degraded"
    elif is_stale:
        status = "stale"
    else:
        status = "current"
    warning = None
    if last_error:
        warning = (
            f"官方公司事件部分更新失敗，已套用成功窗口並保留失敗窗口最近成功 cache：{last_error}"
            if partial_success
            else f"官方公司事件更新失敗，沿用最近成功 cache：{last_error}"
        )
    elif is_stale:
        warning = "官方公司事件 cache 已超過 freshness 門檻。"
    return {
        "status": status,
        "fetched_at": fetched_at,
        "last_attempt_at": last_attempt_at,
        "last_error": last_error,
        "last_failure_details": last_failure_details,
        "partial_success": partial_success,
        "successful_windows": list(entry.get("successful_windows") or []),
        "recovered_windows": list(entry.get("recovered_windows") or []),
        "retry_count": max(int(entry.get("retry_count") or 0), 0),
        "warning": warning,
    }


def _public_event(entry: Mapping[str, Any], *, as_of: date) -> dict[str, Any] | None:
    start_date = _parse_date(entry.get("start_date"))
    end_date = _parse_date(entry.get("end_date"))
    if start_date is None or end_date is None:
        return None
    if start_date <= as_of <= end_date:
        status = "today" if start_date == end_date else "ongoing"
        days_until = 0
    elif start_date > as_of:
        status = "upcoming"
        days_until = (start_date - as_of).days
    else:
        status = "past"
        days_until = (start_date - as_of).days
    return {
        **entry,
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "days_until": days_until,
    }


def _provider_matches_market(provider_key: str, market: str | None) -> bool:
    normalized = str(market or "").strip().upper()
    if not normalized:
        return True
    configured = str(PROVIDER_CONFIG[provider_key]["market"])
    return normalized in {part.strip().upper() for part in configured.split(",")}


def list_taiwan_corporate_events(
    *,
    stock_id: str | None = None,
    market: str | None = None,
    event_types: set[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    now: datetime | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    local_now = _local_now(now)
    as_of = local_now.date()
    start_filter = date_from or as_of
    end_filter = date_to or (as_of + timedelta(days=90))
    normalized_stock_id = str(stock_id or "").strip() or None
    normalized_market = str(market or "").strip().upper() or None
    normalized_types = {
        str(item).strip().lower() for item in (event_types or set()) if str(item).strip()
    }
    cache = read_taiwan_corporate_event_cache(path=cache_path)
    providers = cache.get("providers") or {}
    results: list[dict[str, Any]] = []
    source_status: dict[str, dict[str, Any]] = {}

    if end_filter < as_of:
        provider_keys = HISTORY_PROVIDER_KEYS
    elif start_filter >= as_of:
        provider_keys = CURRENT_PROVIDER_KEYS
    else:
        provider_keys = tuple(PROVIDER_CONFIG)

    for provider_key in provider_keys:
        config = PROVIDER_CONFIG[provider_key]
        if not _provider_matches_market(provider_key, normalized_market):
            continue
        provider_entry = providers.get(provider_key)
        metadata = _provider_cache_status(
            provider_entry,
            now=local_now,
            archive=bool(config.get("archive")),
        )
        source_status[provider_key] = {
            **config,
            **metadata,
            "coverage_start": _parse_date(provider_entry.get("coverage_start"))
            if isinstance(provider_entry, dict)
            else None,
            "coverage_end": _parse_date(provider_entry.get("coverage_end"))
            if isinstance(provider_entry, dict)
            else None,
            "entry_count": len(provider_entry.get("entries") or [])
            if isinstance(provider_entry, dict)
            else 0,
        }
        if not isinstance(provider_entry, dict):
            continue
        for raw_entry in provider_entry.get("entries") or []:
            if not isinstance(raw_entry, dict):
                continue
            event = _public_event(raw_entry, as_of=as_of)
            if event is None:
                continue
            if normalized_stock_id and event.get("stock_id") != normalized_stock_id:
                continue
            if normalized_market and str(event.get("market") or "").upper() != normalized_market:
                continue
            if normalized_types and str(event.get("event_type") or "").lower() not in normalized_types:
                continue
            if event["start_date"] < start_filter or event["start_date"] > end_filter:
                continue
            results.append(event)

    deduped: dict[tuple[str, ...], dict[str, Any]] = {}
    timing_priority = {"actual": 2, "scheduled": 1}
    for item in results:
        logical_key = (
            str(item.get("event_type") or ""),
            str(item.get("market") or ""),
            str(item.get("stock_id") or ""),
            str(item.get("start_date") or ""),
            str(item.get("end_date") or ""),
            str(item.get("start_time") or ""),
            str(item.get("title") or ""),
        )
        previous = deduped.get(logical_key)
        if previous is None or timing_priority.get(
            str(item.get("timing_status")), 0
        ) > timing_priority.get(str(previous.get("timing_status")), 0):
            deduped[logical_key] = item
    type_priority = {"financial_report": 0, "ex_dividend": 1, "investor_conference": 2}
    sorted_results = sorted(
        deduped.values(),
        key=lambda item: (
            item["start_date"],
            item.get("start_time") or "",
            type_priority.get(str(item.get("event_type")), 9),
            str(item.get("stock_id") or ""),
        ),
    )[: max(1, min(int(limit), 1000))]
    warnings = [
        str(source["warning"])
        for source in source_status.values()
        if source.get("warning")
    ]
    return {
        "kind": "taiwan_corporate_events",
        "generated_at": local_now,
        "as_of": as_of,
        "date_from": start_filter,
        "date_to": end_filter,
        "stock_id": normalized_stock_id,
        "market": normalized_market,
        "event_types": sorted(normalized_types),
        "result_count": len(sorted_results),
        "warning": "；".join(dict.fromkeys(warnings)) or None,
        "sources": source_status,
        "results": sorted_results,
    }


def get_taiwan_stock_event_summary(
    stock_id: str,
    *,
    market: str | None = None,
    reminder_days: int | None = None,
    max_results: int = 3,
    now: datetime | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    local_now = _local_now(now)
    days = max(
        int(
            reminder_days
            if reminder_days is not None
            else getattr(settings, "tw_corporate_event_reminder_days", 7)
        ),
        1,
    )
    listing = list_taiwan_corporate_events(
        stock_id=stock_id,
        market=market,
        event_types=set(STOCK_REMINDER_EVENT_TYPES),
        date_from=local_now.date(),
        date_to=local_now.date() + timedelta(days=days),
        limit=max(max_results, 1) * 3,
        now=local_now,
        cache_path=cache_path,
    )
    results = listing["results"][: max(1, min(max_results, 10))]
    status_rank = {"missing": 3, "degraded": 2, "stale": 1, "current": 0}
    statuses = [
        source.get("status", "missing") for source in listing["sources"].values()
    ]
    cache_status = max(statuses, key=lambda value: status_rank.get(str(value), 3)) if statuses else "missing"
    fetched_dates = [
        source.get("fetched_at")
        for source in listing["sources"].values()
        if source.get("fetched_at") is not None
    ]
    return {
        "stock_id": str(stock_id).strip(),
        "checked_at": local_now,
        "reminder_days": days,
        "cache_status": cache_status,
        "cache_fetched_at": min(fetched_dates) if fetched_dates else None,
        "warning": listing["warning"],
        "result_count": len(results),
        "results": results,
    }


def get_taiwan_stock_event_history(
    stock_id: str,
    *,
    market: str | None = None,
    years: int | None = None,
    max_results: int = 20,
    now: datetime | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    local_now = _local_now(now)
    history_years = max(
        min(
            int(
                years
                if years is not None
                else getattr(settings, "tw_corporate_event_history_years", 5)
            ),
            10,
        ),
        1,
    )
    date_to = local_now.date() - timedelta(days=1)
    date_from = date(local_now.year - history_years + 1, 1, 1)
    listing = list_taiwan_corporate_events(
        stock_id=stock_id,
        market=market,
        date_from=date_from,
        date_to=date_to,
        limit=1000,
        now=local_now,
        cache_path=cache_path,
    )
    ordered = list(reversed(listing["results"]))
    results = ordered[: max(1, min(max_results, 200))]
    status_rank = {"missing": 3, "degraded": 2, "stale": 1, "current": 0}
    statuses = [
        source.get("status", "missing") for source in listing["sources"].values()
    ]
    cache_status = (
        max(statuses, key=lambda value: status_rank.get(str(value), 3))
        if statuses
        else "missing"
    )
    fetched_dates = [
        source.get("fetched_at")
        for source in listing["sources"].values()
        if source.get("fetched_at") is not None
    ]
    coverage_starts = [
        source.get("coverage_start")
        for source in listing["sources"].values()
        if source.get("coverage_start") is not None
    ]
    coverage_ends = [
        source.get("coverage_end")
        for source in listing["sources"].values()
        if source.get("coverage_end") is not None
    ]
    return {
        "stock_id": str(stock_id).strip(),
        "checked_at": local_now,
        "history_years": history_years,
        "cache_status": cache_status,
        "cache_fetched_at": min(fetched_dates) if fetched_dates else None,
        "coverage_start": min(coverage_starts) if coverage_starts else None,
        "coverage_end": max(coverage_ends) if coverage_ends else None,
        "warning": listing["warning"],
        "total_count": listing["result_count"],
        "result_count": len(results),
        "results": results,
    }


def _provider_error_detail(
    provider_key: str,
    error: BaseException,
) -> dict[str, Any]:
    config = PROVIDER_CONFIG[provider_key]
    failure = provider_http_failure(error)
    if failure is not None:
        target_parts = failure.context.target.rsplit(":", 1)
        return {
            "provider": config["provider"],
            "market": config["market"],
            "window": failure.context.target,
            "stage": target_parts[-1] if len(target_parts) == 2 else "request",
            "status": failure.status,
            "exception_type": failure.exception_type or type(error).__name__,
            "attempt_count": 1,
            "retryable": failure.status in {"error", "timeout"},
            "message": failure.error_message or str(error),
            "http_status_code": failure.http_status_code,
            "rate_limited": failure.rate_limited,
            "retry_after_seconds": failure.retry_after_seconds,
        }
    return {
        "provider": config["provider"],
        "market": config["market"],
        "window": "all",
        "stage": "provider",
        "status": "error",
        "exception_type": type(error).__name__,
        "attempt_count": 1,
        "retryable": False,
        "message": str(error).strip() or type(error).__name__,
        "http_status_code": None,
        "rate_limited": False,
        "retry_after_seconds": None,
    }


def _record_event(
    db: Session | None,
    *,
    provider_key: str,
    status: str,
    message: str,
    error: BaseException | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    if db is None:
        return
    config = PROVIDER_CONFIG[provider_key]
    failure = provider_http_failure(error) if error is not None else None
    try:
        record_provider_event(
            db,
            market="tw",
            provider=config["provider"],
            resource="corporate_events",
            target=config["market"],
            status=failure.status if failure is not None else status,
            event_type="corporate_event_refresh",
            http_status_code=failure.http_status_code if failure is not None else None,
            rate_limited=failure.rate_limited if failure is not None else False,
            retry_after_seconds=failure.retry_after_seconds if failure is not None else None,
            source_url=failure.source_url if failure is not None else config["source_url"],
            message=message,
            error_message=str(error) if error is not None else None,
            detail=detail,
        )
    except Exception:
        db.rollback()
        logger.warning(
            "Failed to record Taiwan corporate-event provider event provider=%s.",
            provider_key,
            exc_info=True,
        )


def refresh_taiwan_corporate_events(
    *,
    now: datetime | None = None,
    timeout_seconds: int | None = None,
    cache_path: Path | None = None,
    db: Session | None = None,
    fetch_provider: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    started_at = now or datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    started_at = started_at.astimezone(timezone.utc)
    local_started = started_at.astimezone(TAIWAN_TZ)
    resolved_timeout = max(
        int(
            timeout_seconds
            or getattr(settings, "tw_corporate_event_http_timeout_seconds", 20)
        ),
        1,
    )
    month_count = max(
        min(int(getattr(settings, "tw_corporate_event_lookahead_months", 2)), 3),
        1,
    )
    mops_max_attempts = _resolved_mops_max_attempts()
    previous_cache = read_taiwan_corporate_event_cache(path=cache_path)
    previous_providers = previous_cache.get("providers") or {}
    updates: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    error_details: dict[str, list[dict[str, Any]]] = {}
    exceptions: dict[str, BaseException] = {}
    results: dict[str, dict[str, Any]] = {}

    for provider_key in CURRENT_PROVIDER_KEYS:
        request_count = 1
        try:
            if fetch_provider is not None:
                fetched = fetch_provider(
                    provider_key,
                    as_of=local_started.date(),
                    month_count=month_count,
                    timeout_seconds=resolved_timeout,
                    max_attempts=mops_max_attempts,
                )
            elif provider_key == "twse_ex_dividend":
                fetched = fetch_twse_ex_dividends(timeout_seconds=resolved_timeout)
            elif provider_key == "tpex_ex_dividend":
                fetched = fetch_tpex_ex_dividends(timeout_seconds=resolved_timeout)
            else:
                fetched = fetch_mops_conferences(
                    as_of=local_started.date(),
                    month_count=month_count,
                    timeout_seconds=resolved_timeout,
                    max_attempts=mops_max_attempts,
                )

            if isinstance(fetched, MopsConferenceBatch):
                request_count = fetched.request_count
                if fetched.errors:
                    message = "; ".join(fetched.errors)
                    errors[provider_key] = message
                    exceptions[provider_key] = RuntimeError(message)
                    error_details[provider_key] = [
                        failure.to_dict() for failure in fetched.failures
                    ]
                    if fetched.successful_windows and fetched.failures:
                        previous = previous_providers.get(provider_key)
                        previous_entries = (
                            list(previous.get("entries") or [])
                            if isinstance(previous, dict)
                            else []
                        )
                        merged_entries = _merge_partial_mops_entries(
                            fetched,
                            previous_entries=previous_entries,
                        )
                        update = {
                            "entries": merged_entries,
                            "request_count": request_count,
                            "coverage_start": fetched.coverage_start,
                            "coverage_end": fetched.coverage_end,
                            "partial_success": True,
                            "successful_windows": fetched.successful_windows,
                            "recovered_windows": fetched.recovered_windows,
                            "retry_count": fetched.retry_count,
                            "last_failure_details": error_details[provider_key],
                        }
                        updates[provider_key] = update
                        results[provider_key] = {
                            "provider": PROVIDER_CONFIG[provider_key]["provider"],
                            "market": PROVIDER_CONFIG[provider_key]["market"],
                            "status": "partial",
                            "entry_count": len(merged_entries),
                            "request_count": request_count,
                            "retry_count": fetched.retry_count,
                            "successful_windows": fetched.successful_windows,
                            "recovered_windows": fetched.recovered_windows,
                            "failure_details": error_details[provider_key],
                            "source_url": PROVIDER_CONFIG[provider_key]["source_url"],
                            "error_message": message,
                        }
                        continue
                    results[provider_key] = {
                        "provider": PROVIDER_CONFIG[provider_key]["provider"],
                        "market": PROVIDER_CONFIG[provider_key]["market"],
                        "status": "error",
                        "entry_count": 0,
                        "request_count": request_count,
                        "retry_count": fetched.retry_count,
                        "successful_windows": [],
                        "recovered_windows": fetched.recovered_windows,
                        "failure_details": error_details[provider_key],
                        "source_url": PROVIDER_CONFIG[provider_key]["source_url"],
                        "error_message": message,
                    }
                    continue
                update = {
                    "entries": fetched.entries,
                    "request_count": request_count,
                    "coverage_start": fetched.coverage_start,
                    "coverage_end": fetched.coverage_end,
                    "partial_success": False,
                    "successful_windows": fetched.successful_windows,
                    "recovered_windows": fetched.recovered_windows,
                    "retry_count": fetched.retry_count,
                    "last_failure_details": [],
                }
            elif isinstance(fetched, dict) and "entries" in fetched:
                request_count = int(fetched.get("request_count") or request_count)
                if fetched.get("errors"):
                    raise RuntimeError("; ".join(str(item) for item in fetched["errors"]))
                update = {
                    "entries": list(fetched.get("entries") or []),
                    "request_count": request_count,
                    "coverage_start": fetched.get("coverage_start"),
                    "coverage_end": fetched.get("coverage_end"),
                }
            else:
                update = {
                    "entries": list(fetched or []),
                    "request_count": request_count,
                    "coverage_start": None,
                    "coverage_end": None,
                }
            updates[provider_key] = update
            results[provider_key] = {
                "provider": PROVIDER_CONFIG[provider_key]["provider"],
                "market": PROVIDER_CONFIG[provider_key]["market"],
                "status": "success",
                "entry_count": len(update["entries"]),
                "request_count": request_count,
                "retry_count": int(update.get("retry_count") or 0),
                "successful_windows": list(update.get("successful_windows") or []),
                "recovered_windows": list(update.get("recovered_windows") or []),
                "failure_details": [],
                "source_url": PROVIDER_CONFIG[provider_key]["source_url"],
                "error_message": None,
            }
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            errors[provider_key] = message
            exceptions[provider_key] = exc
            error_details[provider_key] = [_provider_error_detail(provider_key, exc)]
            results[provider_key] = {
                "provider": PROVIDER_CONFIG[provider_key]["provider"],
                "market": PROVIDER_CONFIG[provider_key]["market"],
                "status": "error",
                "entry_count": 0,
                "request_count": request_count,
                "retry_count": 0,
                "successful_windows": [],
                "recovered_windows": [],
                "failure_details": error_details[provider_key],
                "source_url": PROVIDER_CONFIG[provider_key]["source_url"],
                "error_message": message,
            }

    _write_refresh(
        updates=updates,
        errors=errors,
        attempted_at=started_at,
        path=cache_path,
        error_details=error_details,
    )

    for provider_key, result in results.items():
        detail = {
            "entry_count": result["entry_count"],
            "request_count": result["request_count"],
            "retry_count": result.get("retry_count", 0),
            "successful_windows": result.get("successful_windows", []),
            "recovered_windows": result.get("recovered_windows", []),
            "failures": result.get("failure_details", []),
        }
        if result["status"] == "success":
            _record_event(
                db,
                provider_key=provider_key,
                status="success",
                message="Refreshed official Taiwan corporate events.",
                detail=detail,
            )
        elif result["status"] == "partial":
            _record_event(
                db,
                provider_key=provider_key,
                status="partial_success",
                message=(
                    "Taiwan corporate-event refresh was partial; successful windows "
                    "were updated and failed windows kept their last successful cache."
                ),
                error=exceptions.get(provider_key),
                detail=detail,
            )
        else:
            _record_event(
                db,
                provider_key=provider_key,
                status="error",
                message="Official Taiwan corporate-event refresh failed; cached data remains active.",
                error=exceptions.get(provider_key),
                detail={**detail, "timeout_seconds": resolved_timeout},
            )

    completed_at = datetime.now(timezone.utc)
    snapshot = list_taiwan_corporate_events(
        date_from=local_started.date(),
        date_to=local_started.date() + timedelta(days=90),
        now=started_at,
        cache_path=cache_path,
    )
    return {
        "kind": "taiwan_corporate_event_refresh",
        "started_at": started_at,
        "completed_at": completed_at,
        "request_limit": 2 + month_count * 4 * mops_max_attempts,
        "request_count": sum(int(item["request_count"]) for item in results.values()),
        "success_count": sum(1 for item in results.values() if item["status"] == "success"),
        "partial_count": sum(1 for item in results.values() if item["status"] == "partial"),
        "error_count": sum(
            1 for item in results.values() if item["status"] in {"partial", "error"}
        ),
        "event_count": snapshot["result_count"],
        "results": results,
    }


def _history_cache_complete(cache: Mapping[str, Any], *, target_start: date) -> bool:
    providers = cache.get("providers") or {}
    for provider_key in HISTORY_PROVIDER_KEYS:
        entry = providers.get(provider_key)
        coverage_start = _parse_date(entry.get("coverage_start")) if isinstance(entry, dict) else None
        if not isinstance(entry, dict) or entry.get("fetched_at") is None:
            return False
        if coverage_start is None or coverage_start > target_start:
            return False
    return True


def _history_refresh_is_recent(
    cache: Mapping[str, Any],
    *,
    now: datetime,
) -> bool:
    providers = cache.get("providers") or {}
    refresh_days = max(
        int(getattr(settings, "tw_corporate_event_history_refresh_days", 7)),
        1,
    )
    for provider_key in HISTORY_PROVIDER_KEYS:
        entry = providers.get(provider_key)
        fetched_at = _parse_datetime(entry.get("fetched_at")) if isinstance(entry, dict) else None
        if (
            not isinstance(entry, dict)
            or entry.get("last_error")
            or fetched_at is None
            or now - fetched_at >= timedelta(days=refresh_days)
        ):
            return False
    return True


def backfill_taiwan_corporate_event_history(
    *,
    years: int | None = None,
    force: bool = True,
    now: datetime | None = None,
    timeout_seconds: int | None = None,
    cache_path: Path | None = None,
    db: Session | None = None,
    fetch_provider: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    started_at = now or datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    started_at = started_at.astimezone(timezone.utc)
    local_started = started_at.astimezone(TAIWAN_TZ)
    history_years = max(
        min(
            int(
                years
                if years is not None
                else getattr(settings, "tw_corporate_event_history_years", 5)
            ),
            10,
        ),
        1,
    )
    resolved_timeout = max(
        int(
            timeout_seconds
            or getattr(settings, "tw_corporate_event_http_timeout_seconds", 20)
        ),
        1,
    )
    mops_max_attempts = _resolved_mops_max_attempts()
    as_of = local_started.date()
    history_end = as_of - timedelta(days=1)
    target_start = date(as_of.year - history_years + 1, 1, 1)
    cache = read_taiwan_corporate_event_cache(path=cache_path)
    full_backfill = force or not _history_cache_complete(
        cache,
        target_start=target_start,
    )
    if not force and not full_backfill and _history_refresh_is_recent(
        cache,
        now=started_at,
    ):
        return {
            "kind": "taiwan_corporate_event_history_backfill",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc),
            "request_limit": 0,
            "request_count": 0,
            "success_count": 0,
            "error_count": 0,
            "event_count": sum(
                len((cache.get("providers") or {}).get(key, {}).get("entries") or [])
                for key in HISTORY_PROVIDER_KEYS
            ),
            "results": {
                key: {
                    "provider": PROVIDER_CONFIG[key]["provider"],
                    "market": PROVIDER_CONFIG[key]["market"],
                    "status": "skipped",
                    "entry_count": len(
                        (cache.get("providers") or {}).get(key, {}).get("entries") or []
                    ),
                    "request_count": 0,
                    "source_url": PROVIDER_CONFIG[key]["source_url"],
                    "error_message": None,
                }
                for key in HISTORY_PROVIDER_KEYS
            },
        }

    providers = cache.get("providers") or {}
    all_years = list(range(target_start.year, as_of.year + 1))
    refresh_days = max(
        int(getattr(settings, "tw_corporate_event_history_refresh_days", 7)),
        1,
    )
    requested_years_by_provider: dict[str, list[int]] = {}
    for provider_key in HISTORY_PROVIDER_KEYS:
        previous = providers.get(provider_key)
        previous_fetched_at = (
            _parse_datetime(previous.get("fetched_at"))
            if isinstance(previous, dict)
            else None
        )
        previous_coverage_start = (
            _parse_date(previous.get("coverage_start"))
            if isinstance(previous, dict)
            else None
        )
        previous_failed_years = {
            int(year)
            for year in (
                previous.get("failed_years") or []
                if isinstance(previous, dict)
                else []
            )
            if str(year).isdigit()
        }
        if isinstance(previous, dict) and previous.get("last_error"):
            previous_failed_years.update(
                int(year)
                for year in re.findall(r"\b(20\d{2})\b", str(previous["last_error"]))
            )
        previous_failed_years.intersection_update(all_years)
        provider_recent = (
            previous_fetched_at is not None
            and started_at - previous_fetched_at < timedelta(days=refresh_days)
        )

        if force:
            provider_years = all_years
        elif previous_failed_years:
            provider_years = sorted(previous_failed_years)
        elif previous_coverage_start is None:
            provider_years = all_years
        elif previous_coverage_start > target_start:
            provider_years = list(
                range(target_start.year, previous_coverage_start.year)
            )
        elif full_backfill and provider_recent:
            provider_years = []
        else:
            provider_years = [as_of.year]
        requested_years_by_provider[provider_key] = provider_years

    updates: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    error_details: dict[str, list[dict[str, Any]]] = {}
    exceptions: dict[str, BaseException] = {}
    results: dict[str, dict[str, Any]] = {}

    for provider_key in HISTORY_PROVIDER_KEYS:
        requested_years = requested_years_by_provider[provider_key]
        previous = providers.get(provider_key)
        previous_entries = (
            list(previous.get("entries") or []) if isinstance(previous, dict) else []
        )
        if not requested_years:
            results[provider_key] = {
                "provider": PROVIDER_CONFIG[provider_key]["provider"],
                "market": PROVIDER_CONFIG[provider_key]["market"],
                "status": "skipped",
                "entry_count": len(previous_entries),
                "request_count": 0,
                "source_url": PROVIDER_CONFIG[provider_key]["source_url"],
                "error_message": None,
            }
            continue
        preserved_entries = [
            entry
            for entry in previous_entries
            if (_parse_date(entry.get("start_date")) or date.min).year
            not in requested_years
        ]
        fetched_entries: list[dict[str, Any]] = []
        failed_years: set[int] = set()
        provider_errors: list[str] = []
        provider_failure_details: list[dict[str, Any]] = []
        successful_windows: list[str] = []
        recovered_windows: list[str] = []
        retry_count = 0
        request_count = 0

        for year in requested_years:
            year_start = date(year, 1, 1)
            year_end = min(date(year, 12, 31), history_end)
            if year_end < year_start:
                continue
            try:
                if fetch_provider is not None:
                    fetched = fetch_provider(
                        provider_key,
                        year=year,
                        date_from=year_start,
                        date_to=year_end,
                        as_of=as_of,
                        timeout_seconds=resolved_timeout,
                        max_attempts=mops_max_attempts,
                    )
                elif provider_key == "twse_ex_dividend_history":
                    request_count += 1
                    fetched = fetch_twse_ex_dividend_history(
                        date_from=year_start,
                        date_to=year_end,
                        timeout_seconds=resolved_timeout,
                    )
                elif provider_key == "tpex_ex_dividend_history":
                    request_count += 1
                    fetched = fetch_tpex_ex_dividend_history(
                        date_from=year_start,
                        date_to=year_end,
                        timeout_seconds=resolved_timeout,
                    )
                else:
                    fetched = fetch_mops_conference_history(
                        year=year,
                        as_of=as_of,
                        timeout_seconds=resolved_timeout,
                        max_attempts=mops_max_attempts,
                    )

                if isinstance(fetched, MopsConferenceBatch):
                    request_count += fetched.request_count
                    retry_count += fetched.retry_count
                    successful_windows.extend(fetched.successful_windows)
                    recovered_windows.extend(fetched.recovered_windows)
                    provider_failure_details.extend(
                        failure.to_dict() for failure in fetched.failures
                    )
                    fetched_entries.extend(fetched.entries)
                    if fetched.errors:
                        failed_years.add(year)
                        provider_errors.extend(fetched.errors)
                elif isinstance(fetched, dict) and "entries" in fetched:
                    request_count += int(fetched.get("request_count") or 0)
                    fetched_entries.extend(list(fetched.get("entries") or []))
                    if fetched.get("errors"):
                        failed_years.add(year)
                        provider_errors.extend(
                            str(item) for item in fetched.get("errors") or []
                        )
                else:
                    if fetch_provider is not None:
                        request_count += 4 if provider_key == "mops_conference_history" else 1
                    fetched_entries.extend(list(fetched or []))
            except Exception as exc:
                failed_years.add(year)
                provider_errors.append(f"{year}: {str(exc).strip() or type(exc).__name__}")
                provider_failure_details.append(
                    _provider_error_detail(provider_key, exc)
                )
                exceptions[provider_key] = exc

        preserved_entries.extend(
            entry
            for entry in previous_entries
            if (_parse_date(entry.get("start_date")) or date.min).year in failed_years
        )
        combined = {
            str(entry.get("event_id")): entry
            for entry in [*preserved_entries, *fetched_entries]
            if entry.get("event_id")
        }
        coverage_dates = [
            parsed
            for entry in combined.values()
            if (parsed := _parse_date(entry.get("start_date"))) is not None
        ]
        previous_coverage_start = (
            _parse_date(previous.get("coverage_start"))
            if isinstance(previous, dict)
            else None
        )
        previous_coverage_end = (
            _parse_date(previous.get("coverage_end"))
            if isinstance(previous, dict)
            else None
        )
        previous_coverage_years = {
            int(year)
            for year in (
                previous.get("coverage_years") or []
                if isinstance(previous, dict)
                else []
            )
            if str(year).isdigit()
        }
        if (
            not previous_coverage_years
            and previous_coverage_start is not None
            and previous_coverage_end is not None
        ):
            previous_coverage_years.update(
                range(previous_coverage_start.year, previous_coverage_end.year + 1)
            )
        previous_failed_years = {
            int(year)
            for year in (
                previous.get("failed_years") or []
                if isinstance(previous, dict)
                else []
            )
            if str(year).isdigit()
        }
        if isinstance(previous, dict) and previous.get("last_error"):
            previous_failed_years.update(
                int(year)
                for year in re.findall(r"\b(20\d{2})\b", str(previous["last_error"]))
            )
        successful_years = [
            year for year in requested_years if year not in failed_years
        ]
        successful_starts = [date(year, 1, 1) for year in successful_years]
        successful_ends = [
            min(date(year, 12, 31), history_end) for year in successful_years
        ]
        coverage_start_candidates = [
            item
            for item in [previous_coverage_start, *successful_starts]
            if item is not None
        ]
        coverage_end_candidates = [
            item
            for item in [previous_coverage_end, *successful_ends]
            if item is not None
        ]
        if fetched_entries or not provider_errors:
            updates[provider_key] = {
                "entries": list(combined.values()),
                "request_count": request_count,
                "coverage_start": (
                    min(coverage_start_candidates)
                    if coverage_start_candidates
                    else (min(coverage_dates) if coverage_dates else target_start)
                ),
                "coverage_end": (
                    max(coverage_end_candidates)
                    if coverage_end_candidates
                    else (max(coverage_dates) if coverage_dates else history_end)
                ),
                "coverage_years": sorted(
                    (previous_coverage_years - set(requested_years))
                    | set(successful_years)
                ),
                "failed_years": sorted(
                    (previous_failed_years - set(successful_years)) | failed_years
                ),
                "partial_success": bool(provider_errors),
                "successful_windows": successful_windows,
                "recovered_windows": recovered_windows,
                "retry_count": retry_count,
                "last_failure_details": provider_failure_details,
            }
        if provider_errors:
            errors[provider_key] = "; ".join(provider_errors)
            error_details[provider_key] = provider_failure_details

        status = "partial" if provider_errors and updates.get(provider_key) else (
            "error" if provider_errors else "success"
        )
        results[provider_key] = {
            "provider": PROVIDER_CONFIG[provider_key]["provider"],
            "market": PROVIDER_CONFIG[provider_key]["market"],
            "status": status,
            "entry_count": len(combined),
            "request_count": request_count,
            "retry_count": retry_count,
            "successful_windows": successful_windows,
            "recovered_windows": recovered_windows,
            "failure_details": provider_failure_details,
            "source_url": PROVIDER_CONFIG[provider_key]["source_url"],
            "error_message": errors.get(provider_key),
        }

    _write_refresh(
        updates=updates,
        errors=errors,
        attempted_at=started_at,
        path=cache_path,
        error_details=error_details,
    )

    for provider_key, result in results.items():
        error = exceptions.get(provider_key)
        _record_event(
            db,
            provider_key=provider_key,
            status=str(result["status"]),
            message=(
                "Backfilled official Taiwan corporate-event history."
                if result["status"] == "success"
                else "Taiwan corporate-event history backfill was partial or failed; cached history remains active."
            ),
            error=error,
            detail={
                "history_years": history_years,
                "full_backfill": full_backfill,
                "entry_count": result["entry_count"],
                "request_count": result["request_count"],
                "retry_count": result.get("retry_count", 0),
                "successful_windows": result.get("successful_windows", []),
                "recovered_windows": result.get("recovered_windows", []),
                "failures": result.get("failure_details", []),
            },
        )

    return {
        "kind": "taiwan_corporate_event_history_backfill",
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc),
        "request_limit": sum(
            len(requested_years_by_provider[key])
            * (
                4 * mops_max_attempts
                if key == "mops_conference_history"
                else 1
            )
            for key in HISTORY_PROVIDER_KEYS
        ),
        "request_count": sum(int(item["request_count"]) for item in results.values()),
        "success_count": sum(
            1 for item in results.values() if item["status"] == "success"
        ),
        "error_count": sum(
            1 for item in results.values() if item["status"] in {"partial", "error"}
        ),
        "event_count": sum(int(item["entry_count"]) for item in results.values()),
        "results": results,
    }


__all__ = [
    "backfill_taiwan_corporate_event_history",
    "get_taiwan_stock_event_history",
    "get_taiwan_stock_event_summary",
    "invalidate_taiwan_corporate_event_cache",
    "list_taiwan_corporate_events",
    "read_taiwan_corporate_event_cache",
    "refresh_taiwan_corporate_events",
]
