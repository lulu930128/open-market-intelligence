"""Backend-owned, expiring viewer intent for the US active-equity lane.

This registry does not read providers or market data.  It only records which
symbols currently have a product viewer so the recurring materializer can own
their acquisition lifecycle without moving refresh policy into the frontend.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from app.us_market.symbols import US_INDEX_SYMBOLS, normalize_us_symbol


_LEASES_LOCK = Lock()
_LEASES: dict[str, dict[str, Any]] = {}
_MAX_ACTIVE_VIEWER_LEASES = 128


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _normalize_owner(owner_id: str) -> str:
    value = owner_id.strip()
    if not value or len(value) > 128:
        raise ValueError("owner_id must be between 1 and 128 characters")
    return value


def _normalize_equity_symbol(symbol: str) -> str:
    normalized = normalize_us_symbol(symbol)
    if not normalized:
        raise ValueError("symbol must not be empty")
    if normalized in US_INDEX_SYMBOLS:
        raise ValueError("active equity viewer does not accept index symbols")
    return normalized


def _prune_locked(now: datetime) -> None:
    expired = [
        owner_id
        for owner_id, lease in _LEASES.items()
        if lease["expires_at"] <= now
    ]
    for owner_id in expired:
        _LEASES.pop(owner_id, None)


def claim_us_active_equity_viewer(
    *,
    symbol: str,
    owner_id: str,
    ttl_seconds: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    if ttl_seconds < 45 or ttl_seconds > 300:
        raise ValueError("ttl_seconds must be between 45 and 300")
    evaluated_at = _utc_now(now)
    normalized_symbol = _normalize_equity_symbol(symbol)
    normalized_owner = _normalize_owner(owner_id)
    with _LEASES_LOCK:
        _prune_locked(evaluated_at)
        existing = _LEASES.get(normalized_owner)
        if existing is None and len(_LEASES) >= _MAX_ACTIVE_VIEWER_LEASES:
            raise RuntimeError("US active viewer lease registry is full")
        lease_id = str(existing["lease_id"]) if existing else uuid4().hex
        lease = {
            "contract_version": "omi.us.active_equity_viewer_lease.v1",
            "lease_id": lease_id,
            "owner_id": normalized_owner,
            "symbol": normalized_symbol,
            "claimed_at": (
                existing["claimed_at"] if existing else evaluated_at
            ),
            "heartbeat_at": evaluated_at,
            "expires_at": evaluated_at + timedelta(seconds=ttl_seconds),
            "ttl_seconds": ttl_seconds,
        }
        _LEASES[normalized_owner] = lease
        return _serialize(lease)


def release_us_active_equity_viewer(*, owner_id: str) -> bool:
    normalized_owner = _normalize_owner(owner_id)
    with _LEASES_LOCK:
        return _LEASES.pop(normalized_owner, None) is not None


def active_us_equity_viewer_symbols(
    *,
    now: datetime | None = None,
) -> tuple[str, ...]:
    evaluated_at = _utc_now(now)
    with _LEASES_LOCK:
        _prune_locked(evaluated_at)
        ordered = sorted(
            _LEASES.values(),
            key=lambda lease: (
                -lease["heartbeat_at"].timestamp(),
                lease["symbol"],
            ),
        )
        return tuple(dict.fromkeys(str(lease["symbol"]) for lease in ordered))


def us_active_equity_viewer_summary(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    evaluated_at = _utc_now(now)
    with _LEASES_LOCK:
        _prune_locked(evaluated_at)
        leases = [
            _serialize(lease)
            for lease in sorted(
                _LEASES.values(),
                key=lambda item: (item["symbol"], item["owner_id"]),
            )
        ]
    return {
        "contract_version": "omi.us.active_equity_viewer_summary.v1",
        "evaluated_at": evaluated_at.isoformat(),
        "active_lease_count": len(leases),
        "symbols": list(dict.fromkeys(str(item["symbol"]) for item in leases)),
        "leases": leases,
    }


def _serialize(lease: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in lease.items()
    }


def _clear_us_active_equity_viewers_for_tests() -> None:
    with _LEASES_LOCK:
        _LEASES.clear()


__all__ = [
    "active_us_equity_viewer_symbols",
    "claim_us_active_equity_viewer",
    "release_us_active_equity_viewer",
    "us_active_equity_viewer_summary",
]
