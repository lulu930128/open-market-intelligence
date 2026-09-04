"""Bounded cache owner for the composed US intraday read model."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
import time

from app.us_market.symbols import normalize_us_symbol


# Keep this projection cache just below the canonical 180-second stale boundary
# so a bounded publisher has the full producer cycle to atomically replace it.
# The evidence-age guard can still expire it earlier; this cache never upgrades
# canonical freshness or survives into the stale window as current evidence.
US_INTRADAY_CACHE_TTL_SECONDS = 170.0
US_INTRADAY_CACHE_CURRENT_MAX_AGE_SECONDS = 180.0
US_INTRADAY_CACHE_MAX_ENTRIES = 256
USIntradayReadCacheKey = tuple[int, str, str, str, str]

_US_INTRADAY_CACHE: OrderedDict[
    USIntradayReadCacheKey, tuple[float, dict]
] = OrderedDict()
_US_INTRADAY_CACHE_LOCK = RLock()


def get_us_intraday_read_cache(cache_key: USIntradayReadCacheKey) -> dict | None:
    with _US_INTRADAY_CACHE_LOCK:
        cached = _US_INTRADAY_CACHE.get(cache_key)
        if cached is None:
            return None

        cached_at, payload = cached
        cache_age = time.monotonic() - cached_at
        claims_current = any(
            (payload.get(status_key) or {}).get("freshness_status") == "current"
            for status_key in ("current_source_status", "bar_source_status")
        )
        evidence_ages: list[float] = []
        for observed_at in (
            (payload.get("current_observation") or {}).get("observed_at"),
            payload.get("latest_bar_time"),
        ):
            if not observed_at:
                continue
            try:
                parsed_observed_at = datetime.fromisoformat(str(observed_at))
                if parsed_observed_at.tzinfo is None:
                    parsed_observed_at = parsed_observed_at.replace(tzinfo=timezone.utc)
                evidence_ages.append(
                    (
                        datetime.now(timezone.utc)
                        - parsed_observed_at.astimezone(timezone.utc)
                    ).total_seconds()
                )
            except (TypeError, ValueError):
                continue
        if (
            cache_age > US_INTRADAY_CACHE_TTL_SECONDS
            or (
                claims_current
                and evidence_ages
                and max(evidence_ages) > US_INTRADAY_CACHE_CURRENT_MAX_AGE_SECONDS
            )
        ):
            _US_INTRADAY_CACHE.pop(cache_key, None)
            return None

        _US_INTRADAY_CACHE.move_to_end(cache_key)
        return deepcopy(payload)


def set_us_intraday_read_cache(
    cache_key: USIntradayReadCacheKey,
    payload: dict,
) -> dict:
    with _US_INTRADAY_CACHE_LOCK:
        _US_INTRADAY_CACHE[cache_key] = (time.monotonic(), deepcopy(payload))
        _US_INTRADAY_CACHE.move_to_end(cache_key)
        while len(_US_INTRADAY_CACHE) > US_INTRADAY_CACHE_MAX_ENTRIES:
            _US_INTRADAY_CACHE.popitem(last=False)
    return payload


def invalidate_us_intraday_read_cache(symbol: str) -> None:
    normalized_symbol = normalize_us_symbol(symbol)
    with _US_INTRADAY_CACHE_LOCK:
        for cache_key in tuple(_US_INTRADAY_CACHE):
            if cache_key[1] == normalized_symbol:
                _US_INTRADAY_CACHE.pop(cache_key, None)
