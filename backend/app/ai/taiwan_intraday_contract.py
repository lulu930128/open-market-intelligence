from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Iterable


CURRENT_PRICE_CONTRACT_VERSION = "tw.current_price.v1"
SESSION_DATE_RELATION_VERSION = "tw.session_date_relation.v1"
SOURCE_HEALTH_RESOLUTION_VERSION = "tw.source_health_resolution.v1"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _positive_number(value: Any) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif value is not None:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _iso(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = str(value).strip() if value is not None else ""
    return text or None


def _age_seconds(
    *,
    checked_at: datetime | None,
    event_time: Any,
) -> int | None:
    event_at = _datetime(event_time)
    if checked_at is None or event_at is None:
        return None
    checked = checked_at
    if checked.tzinfo is None and event_at.tzinfo is not None:
        checked = checked.replace(tzinfo=timezone.utc)
    if checked.tzinfo is not None and event_at.tzinfo is None:
        event_at = event_at.replace(tzinfo=checked.tzinfo)
    try:
        return max(int((checked - event_at).total_seconds()), 0)
    except TypeError:
        return None


def _same_session(
    *,
    observation_date: Any,
    current_session_date: Any,
) -> bool:
    expected = _date(current_session_date)
    observed = _date(observation_date)
    return expected is None or observed is None or expected == observed


def _point_time(point: dict[str, Any]) -> Any:
    return (
        point.get("bar_close_time")
        or point.get("time")
        or point.get("bar_time")
    )


def _point_trade_date(
    point: dict[str, Any],
    *,
    series: dict[str, Any],
) -> Any:
    return (
        point.get("trade_date")
        or series.get("trade_date")
        or _iso(_point_time(point))
    )


def _intraday_candidates(
    intraday_bars: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    series_by_interval = _mapping(intraday_bars.get("series"))
    ordered_series: list[tuple[str, dict[str, Any]]] = []
    if isinstance(series_by_interval.get("1m"), dict):
        ordered_series.append(("1m", series_by_interval["1m"]))
    ordered_series.extend(
        (str(interval), series)
        for interval, series in series_by_interval.items()
        if interval != "1m" and isinstance(series, dict)
    )

    finalized: list[dict[str, Any]] = []
    provisional: list[dict[str, Any]] = []
    for interval, series in ordered_series:
        points = [
            point
            for point in series.get("points") or []
            if isinstance(point, dict)
        ]
        latest = series.get("latest")
        if isinstance(latest, dict) and latest not in points:
            points.append(latest)
        for point in points:
            price = _positive_number(
                point.get("close")
                if point.get("close") is not None
                else point.get("price")
            )
            if price is None:
                continue
            candidate = {
                "value": price,
                "event_time": _iso(_point_time(point) or series.get("to_time")),
                "trade_date": _iso(
                    _point_trade_date(point, series=series)
                ),
                "provider": series.get("provider"),
                "source": series.get("source"),
                "interval": (
                    series.get("effective_interval")
                    or series.get("interval")
                    or interval
                ),
                "finalized": point.get("finalized"),
                "indicator_eligible": point.get("indicator_eligible"),
                "is_partial": point.get("is_partial"),
                "synthetic": bool(point.get("synthetic")),
            }
            if (
                point.get("finalized") is True
                or point.get("indicator_eligible") is True
            ):
                finalized.append(candidate)
            else:
                provisional.append(candidate)
    return finalized, provisional


def _latest_candidate(
    candidates: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    rows = list(candidates)
    if not rows:
        return None

    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        parsed = _datetime(item.get("event_time"))
        if parsed is None:
            return (0, "")
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return (1, parsed.isoformat())

    return max(rows, key=sort_key)


def resolve_taiwan_current_price(
    *,
    quote: dict[str, Any] | None,
    intraday_bars: dict[str, Any] | None,
    current_session_date: Any = None,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    raw_quote = _mapping(quote)
    raw_intraday = _mapping(intraday_bars)
    quote_trade_date = raw_quote.get("trade_date")
    quote_price = _positive_number(
        raw_quote.get("last_trade_price")
        if raw_quote.get("last_trade_price") is not None
        else raw_quote.get("last_price")
    )
    quote_trade_available = bool(
        raw_quote.get("last_trade_available")
        if isinstance(raw_quote.get("last_trade_available"), bool)
        else raw_quote.get("price_available")
        if isinstance(raw_quote.get("price_available"), bool)
        else quote_price is not None
    )
    quote_current_session = _same_session(
        observation_date=quote_trade_date,
        current_session_date=current_session_date,
    )
    quote_freshness = _mapping(raw_quote.get("freshness"))
    quote_current_session = bool(
        quote_current_session
        or raw_quote.get("is_realtime") is True
        and quote_freshness.get("is_stale") is not True
    )
    if quote_price is not None and quote_trade_available and quote_current_session:
        event_time = (
            raw_quote.get("last_trade_time")
            or raw_quote.get("event_time")
            or raw_quote.get("provider_event_time")
            or raw_quote.get("quote_time")
        )
        return {
            "kind": "resolved_current_price",
            "version": CURRENT_PRICE_CONTRACT_VERSION,
            "value": quote_price,
            "source_kind": "quote_last_trade",
            "source": raw_quote.get("source"),
            "provider": raw_quote.get("provider"),
            "semantics": (
                raw_quote.get("quote_semantics")
                or "current_session_last_trade"
            ),
            "event_time": _iso(event_time),
            "trade_date": _iso(quote_trade_date or event_time),
            "age_seconds": _age_seconds(
                checked_at=checked_at,
                event_time=event_time,
            ),
            "confidence": "high",
            "is_estimate": False,
            "is_current_session": True,
            "fallback_reason": None,
            "reference_price": _positive_number(
                raw_quote.get("previous_close")
            ),
        }

    finalized, provisional = _intraday_candidates(raw_intraday)
    for candidates, semantics, confidence in (
        (
            finalized,
            "delayed_last_trade_finalized_bar",
            "high",
        ),
        (
            provisional,
            "delayed_last_trade_partial_bar",
            "medium",
        ),
    ):
        candidate = _latest_candidate(
            item
            for item in candidates
            if _same_session(
                observation_date=item.get("trade_date"),
                current_session_date=current_session_date,
            )
        )
        if candidate is None:
            continue
        return {
            "kind": "resolved_current_price",
            "version": CURRENT_PRICE_CONTRACT_VERSION,
            "value": candidate["value"],
            "source_kind": "intraday_bar_latest",
            "source": candidate.get("source"),
            "provider": candidate.get("provider"),
            "semantics": semantics,
            "event_time": candidate.get("event_time"),
            "trade_date": candidate.get("trade_date"),
            "age_seconds": _age_seconds(
                checked_at=checked_at,
                event_time=candidate.get("event_time"),
            ),
            "confidence": (
                "limited"
                if candidate.get("synthetic")
                else confidence
            ),
            "is_estimate": bool(candidate.get("synthetic")),
            "is_current_session": True,
            "fallback_reason": "quote_last_trade_unavailable",
            "interval": candidate.get("interval"),
            "finalized": candidate.get("finalized"),
            "indicator_eligible": candidate.get("indicator_eligible"),
            "reference_price": _positive_number(
                raw_quote.get("previous_close")
            ),
        }

    best_bid = _positive_number(raw_quote.get("best_bid_price"))
    best_ask = _positive_number(raw_quote.get("best_ask_price"))
    if (
        best_bid is not None
        and best_ask is not None
        and best_ask >= best_bid
    ):
        event_time = (
            raw_quote.get("snapshot_time")
            or raw_quote.get("quote_time")
            or raw_quote.get("fetched_at")
        )
        return {
            "kind": "resolved_current_price",
            "version": CURRENT_PRICE_CONTRACT_VERSION,
            "value": round((best_bid + best_ask) / 2, 6),
            "source_kind": "order_book_midpoint_estimate",
            "source": raw_quote.get("source"),
            "provider": raw_quote.get("provider"),
            "semantics": "order_book_midpoint_estimate",
            "event_time": _iso(event_time),
            "trade_date": _iso(quote_trade_date or event_time),
            "age_seconds": _age_seconds(
                checked_at=checked_at,
                event_time=event_time,
            ),
            "confidence": "estimate",
            "is_estimate": True,
            "is_current_session": quote_current_session,
            "fallback_reason": "trade_observation_unavailable",
            "reference_price": _positive_number(
                raw_quote.get("previous_close")
            ),
        }

    reference_price = _positive_number(raw_quote.get("previous_close"))
    return {
        "kind": "resolved_current_price",
        "version": CURRENT_PRICE_CONTRACT_VERSION,
        "value": None,
        "source_kind": (
            "previous_close_reference"
            if reference_price is not None
            else "unavailable"
        ),
        "source": raw_quote.get("source"),
        "provider": raw_quote.get("provider"),
        "semantics": (
            "reference_close_only"
            if reference_price is not None
            else "unavailable"
        ),
        "event_time": None,
        "trade_date": None,
        "age_seconds": None,
        "confidence": "reference" if reference_price is not None else "none",
        "is_estimate": False,
        "is_current_session": False,
        "fallback_reason": "current_session_trade_unavailable",
        "reference_price": reference_price,
    }


def classify_taiwan_session_date_relation(
    *,
    quote_date: Any,
    completed_daily_date: Any,
    current_session_date: Any = None,
    previous_trading_day: Any = None,
    is_trading_day: bool | None = None,
    session_phase: str | None = None,
) -> dict[str, Any]:
    quote = _date(quote_date)
    daily = _date(completed_daily_date)
    current = _date(current_session_date)
    previous = _date(previous_trading_day)
    phase = str(session_phase or "").casefold()

    relation = "unknown"
    status = "unknown"
    expected = False
    if quote is None or daily is None:
        relation = "insufficient_dates"
        status = "missing"
    elif quote == daily:
        relation = "same_observation_date"
        status = "aligned"
        expected = True
    elif (
        is_trading_day is True
        and current is not None
        and previous is not None
        and quote == current
        and daily == previous
        and phase
        in {
            "preopen",
            "preopen_auction",
            "regular",
            "regular_live",
            "closing_auction",
            "close_resolution",
            "post_close_snapshot",
        }
    ):
        relation = "expected_current_session_vs_completed_daily"
        status = "aligned"
        expected = True
    elif previous is not None and daily < previous:
        relation = "completed_daily_lagging_expected_session"
        status = "mismatch"
    else:
        relation = "unexpected_cross_date_relation"
        status = "mismatch"

    return {
        "kind": "session_date_relation",
        "version": SESSION_DATE_RELATION_VERSION,
        "relation": relation,
        "status": status,
        "expected": expected,
        "quote_date": quote.isoformat() if quote else None,
        "completed_daily_date": daily.isoformat() if daily else None,
        "current_session_date": current.isoformat() if current else None,
        "previous_trading_day": previous.isoformat() if previous else None,
        "session_phase": session_phase,
    }


def resolve_effective_source_health(
    *,
    request_health: dict[str, Any] | None,
    persisted_health: dict[str, Any] | None,
) -> dict[str, Any]:
    request = _mapping(request_health)
    persisted = _mapping(persisted_health)
    request_status = str(request.get("status") or "").casefold()
    persisted_status = str(persisted.get("status") or "").casefold()
    persisted_expired = bool(
        persisted.get("snapshot_is_stale")
        or persisted.get("is_expired")
        or persisted_status in {"expired", "stale"}
    )
    request_succeeded = request_status in {
        "ok",
        "ready",
        "success",
        "current",
        "live",
    }
    warnings: list[str] = []
    if persisted_expired:
        warnings.append("persisted_health_snapshot_expired")

    if request_succeeded:
        status = "request_succeeded"
        source = "request_health"
    elif request:
        status = (
            "request_failed_with_persisted_fallback"
            if persisted
            else "request_failed"
        )
        source = "request_health"
    elif persisted:
        status = (
            "persisted_snapshot_expired"
            if persisted_expired
            else persisted_status or "persisted_snapshot"
        )
        source = "persisted_health"
    else:
        status = "unknown"
        source = "none"

    return {
        "kind": "effective_source_health",
        "version": SOURCE_HEALTH_RESOLUTION_VERSION,
        "status": status,
        "authority": source,
        "request_health": request or None,
        "persisted_health": persisted or None,
        "request_succeeded": request_succeeded,
        "persisted_snapshot_expired": persisted_expired,
        "warnings": warnings,
    }


__all__ = [
    "CURRENT_PRICE_CONTRACT_VERSION",
    "SESSION_DATE_RELATION_VERSION",
    "SOURCE_HEALTH_RESOLUTION_VERSION",
    "classify_taiwan_session_date_relation",
    "resolve_effective_source_health",
    "resolve_taiwan_current_price",
]
