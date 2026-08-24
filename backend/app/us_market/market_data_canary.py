"""Resolved, provider-neutral projections for bounded US market-data canaries."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    EvidenceFreshness,
    InstrumentKey,
    MarketSession,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.policies import RealtimePolicy
from app.market_data.resolution import (
    BarSeriesCandidate,
    ResolutionCandidate,
    resolve_bar_series,
    resolve_quote,
)
from app.us_market.market_data_projection import (
    project_resolved_us_daily_bars,
    project_resolved_us_bars,
    project_resolved_us_quote,
)
from app.us_market.market_data_policy import us_provider_priority
from app.us_market.providers.canonical import (
    US_EASTERN,
    canonical_yahoo_chart_payload,
    us_session_for_timestamp,
)
from app.us_market.trading_calendar import us_session_close_time
US_CANARY_MAX_AGE = timedelta(minutes=5)
US_CANARY_MAX_BARS = 500
US_DAILY_CANARY_MAX_AGE = timedelta(days=7)

_DAILY_PROVIDER_SOURCE = {
    "alphavantage": "alphavantage.time_series_daily",
    "yahoo_chart": "yahoo.chart.1d",
}


def _row_value(row: Any, field: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(field)
    return getattr(row, field, None)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _aware_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _cached_daily_bar(
    *,
    instrument: InstrumentKey,
    row: Any,
) -> BarObservation | None:
    provider = str(_row_value(row, "provider") or "").strip().lower()
    symbol = str(_row_value(row, "symbol") or "").strip().upper()
    trade_date = _row_value(row, "trade_date")
    fetched_at = _aware_utc(_row_value(row, "fetched_at"))
    prices = tuple(
        _decimal(_row_value(row, field))
        for field in ("open_price", "high_price", "low_price", "close_price")
    )
    if (
        not provider
        or symbol != instrument.symbol
        or not isinstance(trade_date, date)
        or fetched_at is None
        or any(value is None or value <= 0 for value in prices)
    ):
        return None
    open_price, high_price, low_price, close_price = prices
    if high_price < max(open_price, low_price, close_price):
        return None
    if low_price > min(open_price, high_price, close_price):
        return None
    volume_value = _decimal(_row_value(row, "trade_volume"))
    if volume_value is not None and volume_value < 0:
        return None
    start_at = datetime.combine(trade_date, time(9, 30), tzinfo=US_EASTERN)
    end_at = datetime.combine(
        trade_date,
        us_session_close_time(trade_date),
        tzinfo=US_EASTERN,
    )
    return BarObservation(
        instrument=instrument,
        lineage=SourceLineage(
            provider=provider,
            source=_DAILY_PROVIDER_SOURCE.get(
                provider,
                f"us_daily_price.{provider}",
            ),
            authority=AuthorityClass.CACHE,
            raw_contract_version="omi.us_daily_price.cache.v1",
            event_at=end_at,
            fetched_at=fetched_at,
            cache_hit=True,
        ),
        interval="1d",
        start_at=start_at,
        end_at=end_at,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=(
            Quantity(value=volume_value, unit=QuantityUnit.SHARE)
            if volume_value is not None
            else None
        ),
        finalization=BarFinalization.FINAL,
    )


def build_cached_daily_resolved_canary(
    *,
    instrument: InstrumentKey,
    rows: Sequence[Any],
    expected_trade_date: date,
    now: datetime,
    max_bars: int = US_CANARY_MAX_BARS,
) -> dict[str, Any]:
    """Resolve finalized cached daily rows without provider IO or persistence."""

    if max_bars < 1 or max_bars > US_CANARY_MAX_BARS:
        raise ValueError(
            f"max_bars must be between 1 and {US_CANARY_MAX_BARS}"
        )
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    provider_rows: dict[str, dict[date, tuple[datetime, BarObservation]]] = defaultdict(dict)
    skipped = 0
    for row in rows:
        bar = _cached_daily_bar(instrument=instrument, row=row)
        if bar is None:
            skipped += 1
            continue
        provider = bar.lineage.provider
        trade_date = bar.start_at.astimezone(US_EASTERN).date()
        fetched_at = bar.lineage.fetched_at
        assert fetched_at is not None
        existing = provider_rows[provider].get(trade_date)
        if existing is None or fetched_at > existing[0]:
            provider_rows[provider][trade_date] = (fetched_at, bar)

    candidates: list[BarSeriesCandidate] = []
    for provider in sorted(
        provider_rows,
        key=lambda value: (us_provider_priority(value, "daily.ohlcv"), value),
    ):
        bars = tuple(
            item[1]
            for _, item in sorted(provider_rows[provider].items())
        )[-max_bars:]
        if not bars:
            continue
        latest_trade_date = bars[-1].start_at.astimezone(US_EASTERN).date()
        candidates.append(
            BarSeriesCandidate(
                bars=bars,
                freshness=(
                    EvidenceFreshness.FRESH
                    if latest_trade_date >= expected_trade_date
                    else EvidenceFreshness.STALE
                ),
                provider_priority=us_provider_priority(provider, "daily.ohlcv"),
                session=MarketSession.CLOSED,
            )
        )
    if not candidates:
        return {}

    resolved = resolve_bar_series(
        candidates,
        policy=RealtimePolicy.COMPLETED_SESSION,
        now=now,
        max_age=US_DAILY_CANARY_MAX_AGE,
    )
    projected = project_resolved_us_daily_bars(resolved, max_bars=max_bars)
    if skipped:
        projected["limitations"] = list(
            dict.fromkeys([*projected.get("limitations", []), "CACHE_ROWS_SKIPPED"])
        )
    return projected


def _resolution_context(
    *,
    latest_event_at: datetime,
    fetched_at: datetime,
    session_scope: str,
) -> tuple[RealtimePolicy, EvidenceFreshness, MarketSession]:
    fetched_local = fetched_at.astimezone(US_EASTERN)
    event_local = latest_event_at.astimezone(US_EASTERN)
    current_session = us_session_for_timestamp(fetched_local)
    completed = event_local.date() < fetched_local.date() or (
        session_scope == "regular"
        and current_session in {MarketSession.POST_CLOSE, MarketSession.CLOSED}
    ) or (
        session_scope in {"extended", "all"}
        and current_session is MarketSession.CLOSED
    )
    if completed:
        return (
            RealtimePolicy.COMPLETED_SESSION,
            EvidenceFreshness.FRESH,
            MarketSession.CLOSED,
        )
    age = fetched_at - latest_event_at
    freshness = (
        EvidenceFreshness.LIVE
        if -US_CANARY_MAX_AGE <= age <= US_CANARY_MAX_AGE
        else EvidenceFreshness.STALE
    )
    return RealtimePolicy.PREFER_LIVE, freshness, current_session


def build_yahoo_intraday_resolved_canary(
    *,
    instrument: InstrumentKey,
    payload: Mapping[str, Any],
    fetched_at: datetime,
    session_scope: str,
) -> dict[str, dict[str, Any]]:
    """Resolve one already-fetched Yahoo payload without IO or persistence."""

    batch = canonical_yahoo_chart_payload(
        instrument=instrument,
        payload=payload,
        fetched_at=fetched_at,
        interval="1m",
        session_scope=session_scope,
    )
    if not batch.bars or batch.snapshot is None or batch.snapshot.quote is None:
        return {}
    latest_event_at = batch.bars[-1].lineage.event_at or batch.bars[-1].end_at
    policy, freshness, session = _resolution_context(
        latest_event_at=latest_event_at,
        fetched_at=fetched_at,
        session_scope=session_scope,
    )
    quote = resolve_quote(
        [
            ResolutionCandidate(
                observation=batch.snapshot.quote,
                freshness=freshness,
                provider_priority=us_provider_priority("yahoo_chart", "quote.snapshot"),
                session=session,
            )
        ],
        policy=policy,
        now=fetched_at,
        max_age=US_CANARY_MAX_AGE,
    )
    bars = resolve_bar_series(
        [
            BarSeriesCandidate(
                bars=batch.bars,
                freshness=freshness,
                provider_priority=us_provider_priority("yahoo_chart", "intraday.bars"),
                session=session,
            )
        ],
        policy=policy,
        now=fetched_at,
        max_age=US_CANARY_MAX_AGE,
    )
    return {
        "quote_snapshot": project_resolved_us_quote(quote),
        "intraday_bars": project_resolved_us_bars(
            bars,
            max_bars=US_CANARY_MAX_BARS,
        ),
    }


__all__ = [
    "US_CANARY_MAX_AGE",
    "US_CANARY_MAX_BARS",
    "US_DAILY_CANARY_MAX_AGE",
    "build_cached_daily_resolved_canary",
    "build_yahoo_intraday_resolved_canary",
]
