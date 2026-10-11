"""Finalized canonical Daily points with an opt-in, separate intraday overlay."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.market.ohlc_overlay import aggregate_ohlc_points
from app.market.calendar_status import build_us_calendar_status
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.historical_intraday import regular_intraday_coverage
from app.us_market.schemas import USProvisionalDailyOverlayRead
from app.us_market.temporal_expectedness import (
    USCapabilitySessionScope,
    evaluate_us_selected_evidence_temporal,
)
from app.market_data.contracts import BarFinalization
from app.us_market.session_policy import us_session_for_timestamp
from app.us_market.ohlc_continuity import build_us_daily_continuity
from app.us_market.sources import normalize_us_symbol
from app.us_market.trading_calendar import (
    previous_us_trading_day, is_us_trading_day, us_session_close_time,
    us_daily_price_finalization_time,
)


US_EASTERN = ZoneInfo("America/New_York")
US_CHART_LOOKBACK_MULTIPLIER = {
    "daily": 3,
    "weekly": 8,
    "monthly": 35,
}
MAX_US_CHART_BARS = 5000


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _volume(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    integral = value.to_integral_value()
    return int(integral) if value == integral else float(value)


def _read_provisional_daily_overlay(db: Session, *, symbol: str, now: datetime) -> dict | None:
    """Chart-only derived evidence; daily/technical finalized inputs stay intact."""
    day = now.astimezone(US_EASTERN).date()
    start = datetime.combine(day, time(9, 30), US_EASTERN)
    end = datetime.combine(day, us_session_close_time(day), US_EASTERN)
    if not is_us_trading_day(day) or now < start:
        return None
    read = USIntradayMarketPlatform(db).read_intraday_bars_for_trade_date(
        symbol=symbol, trade_date=day, bars=1000, now=now,
    )
    resolved = read.result.resolved
    selected = [
        bar for bar in resolved.bars
        if start <= bar.start_at < end and bar.start_at <= now and bar.interval == "1m"
    ]
    if not selected or not resolved.health.facts_usable:
        return None
    coverage = regular_intraday_coverage([bar.start_at for bar in selected], trade_date=day)
    if (
        any(coverage[key] for key in ("duplicate_count", "non_monotonic_count", "off_grid_count"))
        or len({bar.price_basis for bar in selected}) != 1
    ):
        return None
    coverage["unfinalized_count"] = sum(
        bar.finalization not in {BarFinalization.FINAL, BarFinalization.CORRECTED}
        for bar in selected
    )
    if coverage["unfinalized_count"]:
        coverage["coverage_status"] = "partial"
    latest = selected[-1]
    temporal = evaluate_us_selected_evidence_temporal(
        now=now, market_phase=build_us_calendar_status(now)["phase"],
        session_scope=USCapabilitySessionScope.REGULAR,
        event_at=latest.lineage.event_at or latest.end_at,
        fetched_at=latest.lineage.fetched_at or latest.lineage.received_at,
    )
    volume = (
        sum(bar.volume.value for bar in selected)
        if all(bar.volume is not None and bar.volume_status == "observed" for bar in selected)
        and read.identity.instrument.instrument_type.value != "index" else None
    )
    limitations = [
        *resolved.health.limitations,
        "PROVISIONAL_DAILY_FROM_CANONICAL_INTRADAY",
        "NOT_FINALIZED_DAILY",
    ]
    if coverage["coverage_status"] != "complete":
        limitations.append("REGULAR_SESSION_COVERAGE_INCOMPLETE")
    return USProvisionalDailyOverlayRead(
        trade_date=day,
        point={"time": day, "open": _number(selected[0].open_price),
               "high": _number(max(bar.high_price for bar in selected)),
               "low": _number(min(bar.low_price for bar in selected)),
               "close": _number(latest.close_price), "volume": _volume(volume)},
        release_status="pending_release" if now < us_daily_price_finalization_time(day) else "unavailable",
        market_session=us_session_for_timestamp(latest.start_at).value, freshness=temporal.evidence_freshness.value,
        coverage=coverage, event_at=latest.lineage.event_at or latest.end_at,
        selected_provider=resolved.health.selected_provider, selected_source=resolved.health.selected_source,
        limitations=list(dict.fromkeys(limitations)),
    ).model_dump()


def read_us_daily_ohlcv_chart(
    db: Session,
    *,
    symbol: str,
    timeframe: str = "daily",
    bars: int = 90,
    to_date: date | None = None,
    now: datetime | None = None,
    include_intraday_overlay: bool = False,
) -> dict:
    """Return the existing chart contract without legacy provider selection or repair."""

    if timeframe not in US_CHART_LOOKBACK_MULTIPLIER:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")
    if bars < 1 or bars > MAX_US_CHART_BARS:
        raise ValueError(f"bars must be between 1 and {MAX_US_CHART_BARS}.")
    resolved_now = now or datetime.now(timezone.utc)
    source_multiplier = {"daily": 1, "weekly": 6, "monthly": 24}[timeframe]
    requested_source_bars = min(
        MAX_US_CHART_BARS,
        max(bars + 1, bars * source_multiplier),
    )
    platform_result = USDailyOhlcvPlatform(db).read(
        symbol=symbol,
        bars=requested_source_bars,
        now=resolved_now,
        to_date=to_date,
    )
    resolved_bars = list(platform_result.result.resolved.bars)
    is_index = platform_result.identity.instrument.instrument_type.value == "index"
    daily_points = [
        {
            "time": bar.end_at.astimezone(US_EASTERN).date(),
            "open": _number(bar.open_price),
            "high": _number(bar.high_price),
            "low": _number(bar.low_price),
            "close": _number(bar.close_price),
            "volume": (
                None
                if is_index
                else _volume(bar.volume.value)
                if bar.volume is not None
                else None
            ),
        }
        for bar in resolved_bars
    ]
    today = resolved_now.astimezone(US_EASTERN).date()
    overlay = None
    if (
        include_intraday_overlay
        and timeframe == "daily"
        and (to_date is None or to_date == today)
        and not any(point["time"] == today for point in daily_points)
    ):
        overlay = _read_provisional_daily_overlay(db, symbol=symbol, now=resolved_now)
    points = aggregate_ohlc_points(
        points=daily_points,
        timeframe=timeframe,
    )[-bars:]
    expected_date = platform_result.expected_state.expected_trade_date
    end_date = to_date or expected_date
    lookback_days = bars * US_CHART_LOOKBACK_MULTIPLIER[timeframe]
    start_date = end_date - timedelta(days=lookback_days)
    latest_date = daily_points[-1]["time"] if daily_points else None
    continuity = build_us_daily_continuity(
        available_dates=(point["time"] for point in daily_points),
        expected_data_date=expected_date,
        available_bar_count=len(points),
        requested_bar_count=bars,
        history_fetch_scope="canonical_cache",
    )
    latest_display_date = points[-1]["time"] if timeframe == "daily" and points else None
    previous_expected = (
        previous_us_trading_day(latest_display_date, include_value=False)
        if latest_display_date is not None
        else None
    )
    previous_bar = next(
        (
            bar
            for bar in reversed(resolved_bars)
            if bar.end_at.astimezone(US_EASTERN).date() == previous_expected
        ),
        None,
    )
    previous_close = _number(previous_bar.close_price) if previous_bar else None
    previous_status = "current" if previous_close is not None else "missing"
    has_volume = any(point.get("volume") is not None for point in points)
    normalized_symbol = normalize_us_symbol(symbol)
    is_current = bool(platform_result.projection.get("is_current"))
    facts_usable = bool(platform_result.projection.get("facts_usable"))
    decision_usable = bool(platform_result.projection.get("decision_usable"))
    limitations = list(
        dict.fromkeys(
            (
                *platform_result.result.limitations,
                *platform_result.projection.get("limitations", []),
            )
        )
    )
    return {
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "bars": bars,
        "lookback_days": lookback_days,
        "from_date": start_date,
        "to_date": end_date,
        "point_count": len(points),
        "points": points,
        "volume_unit": "shares" if has_volume and not is_index else None,
        "volume_semantics": (
            f"{timeframe}_traded_shares"
            if has_volume and not is_index
            else "index_volume_not_equivalent_to_market_volume"
            if is_index
            else None
        ),
        "volume_status": (
            "available"
            if has_volume and not is_index
            else "not_applicable"
            if is_index
            else "not_provided"
        ),
        "backfill": None,
        "intraday_overlay": overlay,
        "latest_data_date": latest_date,
        "latest_trade_date": latest_date,
        **continuity,
        "request_coverage_status": continuity["coverage_status"],
        "expected_data_date": expected_date,
        "expected_trade_date": expected_date,
        "expected_previous_close_trade_date": previous_expected,
        "previous_close": previous_close,
        "previous_close_trade_date": previous_expected if previous_close is not None else None,
        "previous_close_provider": (
            previous_bar.lineage.provider if previous_bar is not None else None
        ),
        "previous_close_fetched_at": (
            previous_bar.lineage.fetched_at if previous_bar is not None else None
        ),
        "previous_close_status": previous_status,
        "freshness_status": platform_result.projection.get("freshness_status"),
        "is_current": is_current,
        "refresh_recommended": bool(
            platform_result.projection.get("refresh_recommended")
        ),
        "coverage_refresh_recommended": (
            continuity["coverage_status"] != "complete"
        ),
        "selected_provider": platform_result.projection.get("selected_provider"),
        "selected_source": platform_result.projection.get("selected_source"),
        "selected_event_at": platform_result.projection.get("selected_event_at"),
        "fallback_used": bool(platform_result.projection.get("fallback_used")),
        "selection_reason": platform_result.projection.get("selection_reason"),
        "facts_usable": facts_usable,
        "decision_usable": decision_usable,
        "usability_status": platform_result.projection.get("usability_status"),
        "limitations": limitations,
    }


def read_us_daily_ohlcv_history(
    db: Session,
    *,
    symbol: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
    now: datetime | None = None,
) -> list[dict]:
    """Project selected canonical bars into the deprecated daily-row schema."""

    if limit < 1 or limit > MAX_US_CHART_BARS:
        raise ValueError(f"limit must be between 1 and {MAX_US_CHART_BARS}")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    result = USDailyOhlcvPlatform(db).read(
        symbol=symbol,
        bars=MAX_US_CHART_BARS,
        now=now,
        to_date=to_date,
    )
    selected = [
        bar
        for bar in result.result.resolved.bars
        if from_date is None
        or bar.end_at.astimezone(US_EASTERN).date() >= from_date
    ]
    page = list(reversed(selected))[offset : offset + limit]
    rows: list[dict] = []
    for bar in page:
        trade_date = bar.end_at.astimezone(US_EASTERN).date()
        observation_id = str(bar.lineage.observation_id or "")
        try:
            storage_id = int(observation_id.rsplit(":", 1)[-1])
        except ValueError:
            storage_id = 0
        fetched_at = bar.lineage.fetched_at or bar.lineage.received_at
        rows.append(
            {
                "id": storage_id,
                "provider": bar.lineage.provider,
                "symbol": result.identity.instrument.symbol,
                "trade_date": trade_date,
                "currency": "USD",
                "open_price": _number(bar.open_price),
                "high_price": _number(bar.high_price),
                "low_price": _number(bar.low_price),
                "close_price": _number(bar.close_price),
                "adjusted_close": None,
                "trade_volume": (
                    _volume(bar.volume.value) if bar.volume is not None else None
                ),
                "dividend_amount": None,
                "split_coefficient": None,
                "source_url": None,
                "raw_payload_hash": bar.lineage.content_hash,
                "fetched_at": fetched_at,
                "created_at": fetched_at,
                "updated_at": fetched_at,
            }
        )
    return rows


__all__ = [
    "MAX_US_CHART_BARS",
    "read_us_daily_ohlcv_chart",
    "read_us_daily_ohlcv_history",
]
