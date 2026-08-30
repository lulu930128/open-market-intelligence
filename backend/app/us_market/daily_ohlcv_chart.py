"""Compatibility chart projection backed only by canonical resolved US daily bars."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.market.ohlc_overlay import aggregate_ohlc_points
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.ohlc_continuity import build_us_daily_continuity
from app.us_market.sources import normalize_us_symbol
from app.us_market.trading_calendar import previous_us_trading_day


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


def read_us_daily_ohlcv_chart(
    db: Session,
    *,
    symbol: str,
    timeframe: str = "daily",
    bars: int = 90,
    to_date: date | None = None,
    now: datetime | None = None,
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
        "intraday_overlay": None,
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
