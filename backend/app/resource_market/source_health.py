from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from app.db.models import ResourceOhlcvBar, ResourceQuoteSnapshot
from app.observability.provider_health import enrich_source_health_entries
from app.observability.source_health_contract import summarize_source_health
from app.resource_market.contract import (
    PROVIDER_BEST_EFFORT,
    YAHOO_CHART_PROVIDER,
    list_resource_instruments,
    normalize_resource_symbol,
)
from app.resource_market.sources import normalize_resource_interval
from app.resource_market.fx_freshness import (
    FxFreshnessEvaluation,
    evaluate_fx_freshness,
    fx_daily_data_date,
    latest_completed_fx_data_date,
)


RESOURCE_QUOTE_STALE_SECONDS = 30 * 60
RESOURCE_BEST_EFFORT_QUOTE_STALE_SECONDS = 4 * 60 * 60
RESOURCE_MAINTENANCE_QUOTE_STALE_SECONDS = 6 * 60 * 60
RESOURCE_CLOSED_SESSION_QUOTE_STALE_SECONDS = 72 * 60 * 60
RESOURCE_OHLCV_STALE_SECONDS_BY_INTERVAL = {
    "1m": 30 * 60,
    "5m": 2 * 60 * 60,
    "15m": 4 * 60 * 60,
    "30m": 8 * 60 * 60,
    "1h": 12 * 60 * 60,
    "1d": 7 * 24 * 60 * 60,
    "1w": 45 * 24 * 60 * 60,
    "1M": 400 * 24 * 60 * 60,
}
DEFAULT_HEALTH_INTERVALS = ("1m", "1d", "1w", "1M")
ERROR_STATUSES = {"error", "failed", "timeout", "rate_limited", "blocked", "partial_success"}
EXCHANGE_TIMEZONE_BY_EXCHANGE = {
    "COMEX": "America/New_York",
    "NYMEX": "America/New_York",
}
SESSION_OPEN = "open"
SESSION_MAINTENANCE = "maintenance"
SESSION_CLOSED = "closed"
SESSION_UNKNOWN = "unknown"
RESOURCE_QUOTE_HEALTH_COLUMNS = (
    ResourceQuoteSnapshot.id,
    ResourceQuoteSnapshot.provider_symbol,
    ResourceQuoteSnapshot.event_time,
    ResourceQuoteSnapshot.fetched_at,
)
RESOURCE_OHLCV_HEALTH_COLUMNS = (
    ResourceOhlcvBar.id,
    ResourceOhlcvBar.bar_time,
    ResourceOhlcvBar.raw_payload_json,
    ResourceOhlcvBar.fetched_at,
)


@dataclass(frozen=True)
class ResourceSourceHealthEntry:
    resource: str
    provider: str
    target: str
    status: str
    ok: bool
    row_count: int
    required: bool = True
    latest_fetched_at: datetime | None = None
    latest_data_key: str | None = None
    data_quality: str = "unknown"
    reason: str = ""
    age_seconds: int | None = None
    stale_seconds: int | None = None
    session_status: str = SESSION_UNKNOWN
    freshness: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "provider": self.provider,
            "target": self.target,
            "status": self.status,
            "ok": self.ok,
            "row_count": self.row_count,
            "required": self.required,
            "latest_fetched_at": self.latest_fetched_at.isoformat() if self.latest_fetched_at else None,
            "latest_data_key": self.latest_data_key,
            "data_quality": self.data_quality,
            "reason": self.reason,
            "age_seconds": self.age_seconds,
            "stale_seconds": self.stale_seconds,
            "session_status": self.session_status,
            "freshness": self.freshness,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(int((_as_utc(now) - _as_utc(value)).total_seconds()), 0)


def _exchange_session_status(exchange: str | None, now: datetime) -> str:
    timezone_name = EXCHANGE_TIMEZONE_BY_EXCHANGE.get((exchange or "").strip().upper())
    if not timezone_name:
        return SESSION_UNKNOWN

    try:
        exchange_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        exchange_tz = timezone(timedelta(hours=-5))

    local_time = _as_utc(now).astimezone(exchange_tz)
    weekday = local_time.weekday()
    hour = local_time.hour

    if weekday == 5:
        return SESSION_CLOSED
    if weekday == 6 and hour < 18:
        return SESSION_CLOSED
    if weekday == 4 and hour >= 17:
        return SESSION_CLOSED
    if hour == 17:
        return SESSION_MAINTENANCE
    return SESSION_OPEN


def _quote_stale_seconds(*, provider_status: str, session_status: str) -> int:
    threshold = RESOURCE_QUOTE_STALE_SECONDS
    if provider_status == PROVIDER_BEST_EFFORT:
        threshold = max(threshold, RESOURCE_BEST_EFFORT_QUOTE_STALE_SECONDS)
    if session_status == SESSION_MAINTENANCE:
        threshold = max(threshold, RESOURCE_MAINTENANCE_QUOTE_STALE_SECONDS)
    if session_status == SESSION_CLOSED:
        threshold = max(threshold, RESOURCE_CLOSED_SESSION_QUOTE_STALE_SECONDS)
    return threshold


def _status_for_latest(
    *,
    row_count: int,
    latest_fetched_at: datetime | None,
    now: datetime,
    stale_seconds: int,
    provider_status: str,
    session_status: str,
) -> tuple[str, bool, str, str, int | None, int]:
    if row_count <= 0:
        return (
            "empty",
            False,
            "empty",
            "No local resource rows are available for this target.",
            None,
            stale_seconds,
        )

    age = _age_seconds(now, latest_fetched_at)
    if age is None:
        return (
            "stale",
            False,
            "stale",
            "Latest resource row is missing fetched_at.",
            None,
            stale_seconds,
        )
    if age > stale_seconds:
        return (
            "stale",
            False,
            "stale",
            f"Latest resource row is {age}s old; threshold is {stale_seconds}s; session is {session_status}.",
            age,
            stale_seconds,
        )
    if provider_status == PROVIDER_BEST_EFFORT:
        return (
            "delayed",
            True,
            PROVIDER_BEST_EFFORT,
            f"Latest resource row is within threshold; provider is best-effort delayed; session is {session_status}.",
            age,
            stale_seconds,
        )
    return (
        "live",
        True,
        "ok",
        f"Latest resource row is within threshold; session is {session_status}.",
        age,
        stale_seconds,
    )


def _fx_health_status(
    freshness: FxFreshnessEvaluation,
    *,
    provider_status: str,
) -> tuple[str, bool, str, str]:
    reason = (
        f"FX freshness={freshness.status}; session={freshness.session_status}; "
        f"reasons={','.join(freshness.reason_codes)}."
    )
    if freshness.status == "missing":
        return "empty", False, "empty", reason
    if not freshness.usable:
        return "stale", False, freshness.status, reason
    if provider_status == PROVIDER_BEST_EFFORT or freshness.status in {
        "delayed",
        "latest_completed_session",
    }:
        return "delayed", True, PROVIDER_BEST_EFFORT, reason
    return "live", True, "ok", reason


def _split_symbols(symbols: str | None) -> list[str] | None:
    if not symbols:
        return None
    normalized: list[str] = []
    for symbol in symbols.split(","):
        item = normalize_resource_symbol(symbol)
        if item and item not in normalized:
            normalized.append(item)
    return normalized or None


def _split_intervals(intervals: str | None) -> list[str]:
    raw_values = intervals.split(",") if intervals else list(DEFAULT_HEALTH_INTERVALS)
    normalized: list[str] = []
    for value in raw_values:
        if not value.strip():
            continue
        interval = normalize_resource_interval(value)
        if interval not in normalized:
            normalized.append(interval)
    return normalized or list(DEFAULT_HEALTH_INTERVALS)


def _matching_resource_instruments(
    *,
    symbols: str | None,
    group: str | None,
):
    symbol_values = _split_symbols(symbols)
    if not symbol_values:
        return list_resource_instruments(group=group)

    instruments = []
    for symbol in symbol_values:
        instruments.extend(list_resource_instruments(group=group, symbol=symbol))
    return instruments


def _quote_entry(db: Session, *, instrument, now: datetime) -> ResourceSourceHealthEntry:
    session_status = _exchange_session_status(instrument.exchange, now)
    stale_seconds = _quote_stale_seconds(
        provider_status=instrument.provider_status,
        session_status=session_status,
    )
    query = (
        db.query(ResourceQuoteSnapshot)
        .filter(ResourceQuoteSnapshot.provider == instrument.provider)
        .filter(ResourceQuoteSnapshot.symbol == instrument.symbol)
        .filter(ResourceQuoteSnapshot.instrument_type == instrument.instrument_type)
        .filter(ResourceQuoteSnapshot.contract_key == instrument.contract_type)
    )
    row_count, latest_fetched_at = (
        query.with_entities(
            func.count(ResourceQuoteSnapshot.id),
            func.max(ResourceQuoteSnapshot.fetched_at),
        )
        .one()
    )
    latest = (
        query.options(load_only(*RESOURCE_QUOTE_HEALTH_COLUMNS))
        .filter(ResourceQuoteSnapshot.fetched_at == latest_fetched_at)
        .order_by(ResourceQuoteSnapshot.fetched_at.desc(), ResourceQuoteSnapshot.id.desc())
        .first()
        if latest_fetched_at is not None
        else None
    )
    latest_fetched_at = latest.fetched_at if latest else None
    if (instrument.exchange or "").strip().upper() == "FX":
        freshness = evaluate_fx_freshness(
            purpose="spot_quote",
            now=now,
            event_time=(latest.event_time or latest.fetched_at) if latest else None,
            fetched_at=latest.fetched_at if latest else None,
        )
        status, ok, data_quality, reason = _fx_health_status(
            freshness,
            provider_status=instrument.provider_status,
        )
        return ResourceSourceHealthEntry(
            resource="quote",
            provider=instrument.provider,
            target=instrument.symbol,
            status=status,
            ok=ok,
            row_count=row_count,
            latest_fetched_at=latest_fetched_at,
            latest_data_key=(
                latest.provider_symbol if latest else instrument.provider_symbol
            ),
            data_quality=data_quality,
            reason=reason,
            age_seconds=freshness.event_age_seconds,
            stale_seconds=freshness.stale_after_seconds,
            session_status=freshness.session_status,
            freshness=freshness.as_payload(),
        )
    status, ok, data_quality, reason, age_seconds, stale_seconds = _status_for_latest(
        row_count=row_count,
        latest_fetched_at=latest_fetched_at,
        now=now,
        stale_seconds=stale_seconds,
        provider_status=instrument.provider_status,
        session_status=session_status,
    )
    return ResourceSourceHealthEntry(
        resource="quote",
        provider=instrument.provider,
        target=instrument.symbol,
        status=status,
        ok=ok,
        row_count=row_count,
        latest_fetched_at=latest_fetched_at,
        latest_data_key=latest.provider_symbol if latest else instrument.provider_symbol,
        data_quality=data_quality,
        reason=reason,
        age_seconds=age_seconds,
        stale_seconds=stale_seconds,
        session_status=session_status,
    )


def _ohlcv_entry(
    db: Session,
    *,
    instrument,
    interval: str,
    now: datetime,
) -> ResourceSourceHealthEntry:
    session_status = _exchange_session_status(instrument.exchange, now)
    stale_seconds = RESOURCE_OHLCV_STALE_SECONDS_BY_INTERVAL[interval]
    query = (
        db.query(ResourceOhlcvBar)
        .filter(ResourceOhlcvBar.provider == instrument.provider)
        .filter(ResourceOhlcvBar.symbol == instrument.symbol)
        .filter(ResourceOhlcvBar.instrument_type == instrument.instrument_type)
        .filter(ResourceOhlcvBar.contract_key == instrument.contract_type)
        .filter(ResourceOhlcvBar.interval == interval)
    )
    row_count, latest_fetched_at = (
        query.with_entities(
            func.count(ResourceOhlcvBar.id),
            func.max(ResourceOhlcvBar.fetched_at),
        )
        .one()
    )
    is_fx = (instrument.exchange or "").strip().upper() == "FX"
    if is_fx and interval == "1d":
        expected_data_date = latest_completed_fx_data_date(now)
        completed_cutoff = datetime.combine(
            expected_data_date + timedelta(days=1),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        candidate_rows = (
            query.options(load_only(*RESOURCE_OHLCV_HEALTH_COLUMNS))
            .filter(ResourceOhlcvBar.bar_time < completed_cutoff)
            .order_by(
                ResourceOhlcvBar.bar_time.desc(),
                ResourceOhlcvBar.fetched_at.desc(),
                ResourceOhlcvBar.id.desc(),
            )
            .limit(64)
            .all()
        )
        latest = next(
            (
                row
                for row in candidate_rows
                if (
                    fx_daily_data_date(row.bar_time, row.raw_payload_json)
                    or date.min
                )
                <= expected_data_date
            ),
            None,
        )
    else:
        latest = (
            query.options(load_only(*RESOURCE_OHLCV_HEALTH_COLUMNS))
            .filter(ResourceOhlcvBar.fetched_at == latest_fetched_at)
            .order_by(ResourceOhlcvBar.fetched_at.desc(), ResourceOhlcvBar.id.desc())
            .first()
            if latest_fetched_at is not None
            else None
        )
    latest_fetched_at = latest.fetched_at if latest else None
    if is_fx:
        data_date = (
            fx_daily_data_date(latest.bar_time, latest.raw_payload_json)
            if latest and interval == "1d"
            else None
        )
        freshness = evaluate_fx_freshness(
            purpose="daily_trend" if interval == "1d" else "spot_quote",
            now=now,
            event_time=latest.bar_time if latest else None,
            fetched_at=latest.fetched_at if latest else None,
            data_date=data_date,
        )
        status, ok, data_quality, reason = _fx_health_status(
            freshness,
            provider_status=instrument.provider_status,
        )
        return ResourceSourceHealthEntry(
            resource="ohlcv",
            provider=instrument.provider,
            target=f"{instrument.symbol}:{interval}",
            status=status,
            ok=ok,
            row_count=row_count,
            latest_fetched_at=latest_fetched_at,
            latest_data_key=latest.bar_time.isoformat() if latest else interval,
            data_quality=data_quality,
            reason=reason,
            age_seconds=freshness.event_age_seconds,
            stale_seconds=(
                freshness.stale_after_seconds
                if freshness.stale_after_seconds is not None
                else stale_seconds
            ),
            session_status=freshness.session_status,
            freshness=freshness.as_payload(),
        )
    status, ok, data_quality, reason, age_seconds, stale_seconds = _status_for_latest(
        row_count=row_count,
        latest_fetched_at=latest_fetched_at,
        now=now,
        stale_seconds=stale_seconds,
        provider_status=instrument.provider_status,
        session_status=session_status,
    )
    return ResourceSourceHealthEntry(
        resource="ohlcv",
        provider=instrument.provider,
        target=f"{instrument.symbol}:{interval}",
        status=status,
        ok=ok,
        row_count=row_count,
        latest_fetched_at=latest_fetched_at,
        latest_data_key=latest.bar_time.isoformat() if latest else interval,
        data_quality=data_quality,
        reason=reason,
        age_seconds=age_seconds,
        stale_seconds=stale_seconds,
        session_status=session_status,
    )


def _entry_status(entry: dict[str, Any]) -> str:
    return str(entry.get("status") or "unknown")


def _summary(entries: list[dict[str, Any]]) -> dict[str, int]:
    return summarize_source_health(
        entries,
        counted_statuses=("empty", "stale", "delayed", "error", "disabled"),
        error_statuses=ERROR_STATUSES,
        count_recent_errors=True,
    )


def build_resource_source_health(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | None = None,
    group: str | None = None,
    intervals: str | None = None,
    include_events: bool = True,
    max_entries: int | None = None,
) -> dict[str, Any]:
    now = _now()
    interval_values = _split_intervals(intervals)
    instruments = _matching_resource_instruments(symbols=symbols, group=group)
    if provider:
        instruments = [item for item in instruments if item.provider == provider.strip().lower()]

    entries: list[dict[str, Any]] = []
    for instrument in instruments:
        if instrument.provider != YAHOO_CHART_PROVIDER:
            entries.append(
                ResourceSourceHealthEntry(
                    resource="provider",
                    provider=instrument.provider,
                    target=instrument.symbol,
                    status="disabled",
                    ok=False,
                    row_count=0,
                    data_quality="unsupported_provider",
                    reason=f"Unsupported resource provider {instrument.provider}.",
                ).to_dict()
            )
            continue

        entries.append(_quote_entry(db, instrument=instrument, now=now).to_dict())
        for interval in interval_values:
            entries.append(_ohlcv_entry(db, instrument=instrument, interval=interval, now=now).to_dict())

    if include_events and entries:
        entries = enrich_source_health_entries(db, market="resource", entries=entries)

    if max_entries is not None:
        entries = entries[: max(1, min(max_entries, 500))]

    return {
        "kind": "resource_source_health",
        "generated_at": now.isoformat(),
        "filters": {
            "provider": provider,
            "symbols": _split_symbols(symbols),
            "group": group,
            "intervals": interval_values,
            "include_events": include_events,
            "max_entries": max_entries,
        },
        "summary": _summary(entries),
        "entries": entries,
    }
