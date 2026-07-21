from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.market.providers.tw_disposition import (
    TPEX_DISPOSITION_URL,
    TPEX_PROVIDER,
    TWSE_DISPOSITION_URL,
    TWSE_PROVIDER,
    fetch_tpex_dispositions,
    fetch_twse_dispositions,
)
from app.observability.provider_health import record_provider_event
from app.observability.provider_http import provider_http_failure
from app.runtime_lock import ProcessFileLock


logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1
TAIWAN_TZ = ZoneInfo("Asia/Taipei")
PROVIDER_CONFIG = {
    "twse": {
        "provider": TWSE_PROVIDER,
        "market": "TWSE",
        "source": "TWSE 公布處置有價證券",
        "source_url": TWSE_DISPOSITION_URL,
    },
    "tpex": {
        "provider": TPEX_PROVIDER,
        "market": "TPEX",
        "source": "TPEx 上櫃處置有價證券資訊",
        "source_url": TPEX_DISPOSITION_URL,
    },
}

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
    return Path(path or settings.tw_disposition_cache_path).expanduser().resolve()


def invalidate_taiwan_disposition_cache() -> None:
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


def read_taiwan_disposition_cache(*, path: Path | None = None) -> dict[str, Any]:
    global _CACHE_STATE, _CACHE_PATH, _CACHE_MTIME_NS
    cache_path = _resolved_path(path)
    try:
        mtime_ns = cache_path.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = None
    except OSError:
        logger.warning("Could not stat Taiwan disposition cache path=%s.", cache_path)
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
                    "Could not read Taiwan disposition cache path=%s.",
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
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in entry.items()
    }


def _write_refresh(
    *,
    updates: Mapping[str, list[dict[str, Any]]],
    errors: Mapping[str, str],
    attempted_at: datetime,
    path: Path | None = None,
) -> dict[str, Any]:
    cache_path = _resolved_path(path)
    process_lock = ProcessFileLock(
        cache_path.with_suffix(f"{cache_path.suffix}.lock")
    )
    if not process_lock.acquire(timeout_seconds=5):
        raise TimeoutError(
            f"Timed out waiting for Taiwan disposition cache lock: {cache_path}"
        )

    try:
        with _CACHE_LOCK:
            invalidate_taiwan_disposition_cache()
            payload = read_taiwan_disposition_cache(path=cache_path)
            providers = dict(payload.get("providers") or {})
            attempted_text = attempted_at.astimezone(timezone.utc).isoformat()

            for provider_key, entries in updates.items():
                config = PROVIDER_CONFIG[provider_key]
                providers[provider_key] = {
                    **config,
                    "fetched_at": attempted_text,
                    "last_attempt_at": attempted_text,
                    "last_error": None,
                    "entries": [_json_entry(entry) for entry in entries],
                }

            for provider_key, error_message in errors.items():
                previous = providers.get(provider_key)
                entry = dict(previous) if isinstance(previous, dict) else {
                    **PROVIDER_CONFIG[provider_key],
                    "fetched_at": None,
                    "entries": [],
                }
                entry["last_attempt_at"] = attempted_text
                entry["last_error"] = str(error_message).strip() or "Refresh failed."
                providers[provider_key] = entry

            written = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "updated_at": attempted_text,
                "providers": providers,
            }
            _atomic_write(cache_path, written)
            invalidate_taiwan_disposition_cache()
            return read_taiwan_disposition_cache(path=cache_path)
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
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _local_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(TAIWAN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(TAIWAN_TZ)


def _provider_cache_status(entry: Any, *, now: datetime) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {
            "status": "missing",
            "fetched_at": None,
            "last_attempt_at": None,
            "last_error": None,
            "warning": "尚無官方處置名單 cache。",
        }
    fetched_at = _parse_datetime(entry.get("fetched_at"))
    last_attempt_at = _parse_datetime(entry.get("last_attempt_at"))
    last_error = str(entry.get("last_error") or "").strip() or None
    stale_hours = max(int(settings.tw_disposition_cache_stale_hours), 1)
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
        warning = f"官方處置名單更新失敗，沿用最近成功 cache：{last_error}"
    elif is_stale:
        warning = "官方處置名單 cache 已超過 freshness 門檻。"
    return {
        "status": status,
        "fetched_at": fetched_at,
        "last_attempt_at": last_attempt_at,
        "last_error": last_error,
        "warning": warning,
    }


def _entry_status(entry: Mapping[str, Any], *, as_of: date) -> str:
    start_date = _parse_date(entry.get("start_date"))
    end_date = _parse_date(entry.get("end_date"))
    if start_date is None or end_date is None:
        return "invalid"
    if start_date <= as_of <= end_date:
        return "active"
    if as_of < start_date:
        return "upcoming"
    return "expired"


def _entry_priority(entry: Mapping[str, Any]) -> tuple[int, int]:
    status = str(entry.get("status") or "invalid")
    start_date = entry.get("start_date")
    ordinal = start_date.toordinal() if isinstance(start_date, date) else 0
    if status == "active":
        return 0, -ordinal
    if status == "upcoming":
        return 1, ordinal
    if status == "expired":
        return 2, -ordinal
    return 3, 0


def _public_entry(entry: Mapping[str, Any], *, as_of: date) -> dict[str, Any]:
    return {
        **entry,
        "announced_date": _parse_date(entry.get("announced_date")),
        "start_date": _parse_date(entry.get("start_date")),
        "end_date": _parse_date(entry.get("end_date")),
        "status": _entry_status(entry, as_of=as_of),
        "is_active": _entry_status(entry, as_of=as_of) == "active",
    }


def _provider_key_for_market(market: str | None) -> str | None:
    normalized = str(market or "").strip().lower()
    if normalized == "twse":
        return "twse"
    if normalized in {"tpex", "otc"}:
        return "tpex"
    return None


def get_taiwan_disposition_status(
    stock_id: str,
    *,
    market: str | None = None,
    now: datetime | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    normalized_stock_id = str(stock_id or "").strip()
    local_now = _local_now(now)
    as_of = local_now.date()
    cache = read_taiwan_disposition_cache(path=cache_path)
    providers = cache.get("providers") or {}
    provider_key = _provider_key_for_market(market)
    provider_keys = [provider_key] if provider_key else list(PROVIDER_CONFIG)
    candidates: list[dict[str, Any]] = []

    for key in provider_keys:
        provider_entry = providers.get(key)
        if not isinstance(provider_entry, dict):
            continue
        for raw_entry in provider_entry.get("entries") or []:
            if (
                isinstance(raw_entry, dict)
                and str(raw_entry.get("stock_id") or "").strip() == normalized_stock_id
            ):
                candidates.append(_public_entry(raw_entry, as_of=as_of))

    candidates.sort(key=_entry_priority)
    selected = next(
        (item for item in candidates if item.get("status") in {"active", "upcoming"}),
        None,
    )
    metadata_key = provider_key or (
        str(selected.get("provider") or "").split("_")[0] if selected else None
    )
    if metadata_key not in PROVIDER_CONFIG:
        metadata_key = provider_keys[0] if len(provider_keys) == 1 else None

    if metadata_key:
        metadata = _provider_cache_status(providers.get(metadata_key), now=local_now)
    else:
        statuses = [
            _provider_cache_status(providers.get(key), now=local_now)
            for key in provider_keys
        ]
        metadata = next(
            (item for item in statuses if item["status"] != "current"),
            statuses[0] if statuses else _provider_cache_status(None, now=local_now),
        )

    base = {
        "stock_id": normalized_stock_id,
        "checked_at": local_now,
        "is_disposition": selected is not None,
        "is_active": bool(selected and selected.get("status") == "active"),
        "status": selected.get("status") if selected else "none",
        "cache_status": metadata["status"],
        "cache_fetched_at": metadata["fetched_at"],
        "warning": metadata["warning"],
    }
    if selected:
        base.update(selected)
    return base


def list_taiwan_dispositions(
    *,
    include_upcoming: bool = True,
    include_expired: bool = False,
    now: datetime | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    local_now = _local_now(now)
    as_of = local_now.date()
    cache = read_taiwan_disposition_cache(path=cache_path)
    providers = cache.get("providers") or {}
    results: list[dict[str, Any]] = []
    source_status: dict[str, dict[str, Any]] = {}

    for key, config in PROVIDER_CONFIG.items():
        provider_entry = providers.get(key)
        metadata = _provider_cache_status(provider_entry, now=local_now)
        source_status[key] = {
            **config,
            **metadata,
            "entry_count": len(provider_entry.get("entries") or [])
            if isinstance(provider_entry, dict)
            else 0,
        }
        if not isinstance(provider_entry, dict):
            continue
        for raw_entry in provider_entry.get("entries") or []:
            if not isinstance(raw_entry, dict):
                continue
            entry = _public_entry(raw_entry, as_of=as_of)
            status = entry["status"]
            if status == "active" or (status == "upcoming" and include_upcoming):
                results.append(entry)
            elif status == "expired" and include_expired:
                results.append(entry)

    selected_by_security: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in results:
        key = (str(entry.get("market") or ""), str(entry.get("stock_id") or ""))
        previous = selected_by_security.get(key)
        if previous is None or _entry_priority(entry) < _entry_priority(previous):
            selected_by_security[key] = entry
    results = sorted(
        selected_by_security.values(),
        key=lambda item: (
            _entry_priority(item),
            str(item.get("market") or ""),
            str(item.get("stock_id") or ""),
        ),
    )
    return {
        "kind": "taiwan_disposition_securities",
        "generated_at": local_now,
        "as_of": as_of,
        "active_count": sum(1 for item in results if item["status"] == "active"),
        "upcoming_count": sum(1 for item in results if item["status"] == "upcoming"),
        "result_count": len(results),
        "sources": source_status,
        "results": results,
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
            resource="disposition_securities",
            target=config["market"],
            status=failure.status if failure is not None else status,
            event_type="disposition_refresh",
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
            "Failed to record Taiwan disposition provider event provider=%s.",
            provider_key,
            exc_info=True,
        )


def refresh_taiwan_dispositions(
    *,
    now: datetime | None = None,
    timeout_seconds: int | None = None,
    cache_path: Path | None = None,
    db: Session | None = None,
    fetch_provider: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    started_at = now or datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    started_at = started_at.astimezone(timezone.utc)
    resolved_timeout = max(
        int(timeout_seconds or settings.tw_disposition_http_timeout_seconds),
        1,
    )
    updates: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    exceptions: dict[str, BaseException] = {}
    results: dict[str, dict[str, Any]] = {}

    for provider_key in PROVIDER_CONFIG:
        try:
            if fetch_provider is not None:
                entries = fetch_provider(
                    provider_key,
                    timeout_seconds=resolved_timeout,
                )
            elif provider_key == "twse":
                entries = fetch_twse_dispositions(timeout_seconds=resolved_timeout)
            else:
                entries = fetch_tpex_dispositions(timeout_seconds=resolved_timeout)
            updates[provider_key] = entries
            results[provider_key] = {
                "provider": PROVIDER_CONFIG[provider_key]["provider"],
                "market": PROVIDER_CONFIG[provider_key]["market"],
                "status": "success",
                "entry_count": len(entries),
                "source_url": PROVIDER_CONFIG[provider_key]["source_url"],
                "error_message": None,
            }
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            errors[provider_key] = message
            exceptions[provider_key] = exc
            results[provider_key] = {
                "provider": PROVIDER_CONFIG[provider_key]["provider"],
                "market": PROVIDER_CONFIG[provider_key]["market"],
                "status": "error",
                "entry_count": 0,
                "source_url": PROVIDER_CONFIG[provider_key]["source_url"],
                "error_message": message,
            }

    _write_refresh(
        updates=updates,
        errors=errors,
        attempted_at=started_at,
        path=cache_path,
    )

    for provider_key, result in results.items():
        if result["status"] == "success":
            _record_event(
                db,
                provider_key=provider_key,
                status="success",
                message="Refreshed official Taiwan disposition securities.",
                detail={"entry_count": result["entry_count"], "request_limit": 1},
            )
        else:
            _record_event(
                db,
                provider_key=provider_key,
                status="error",
                message="Official Taiwan disposition refresh failed; cached data remains active.",
                error=exceptions.get(provider_key),
                detail={"timeout_seconds": resolved_timeout},
            )

    completed_at = datetime.now(timezone.utc)
    snapshot = list_taiwan_dispositions(now=started_at, cache_path=cache_path)
    return {
        "kind": "taiwan_disposition_refresh",
        "started_at": started_at,
        "completed_at": completed_at,
        "request_limit": 2,
        "success_count": sum(1 for item in results.values() if item["status"] == "success"),
        "error_count": sum(1 for item in results.values() if item["status"] == "error"),
        "active_count": snapshot["active_count"],
        "upcoming_count": snapshot["upcoming_count"],
        "results": results,
    }


__all__ = [
    "get_taiwan_disposition_status",
    "invalidate_taiwan_disposition_cache",
    "list_taiwan_dispositions",
    "read_taiwan_disposition_cache",
    "refresh_taiwan_dispositions",
]
