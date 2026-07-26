from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta, tzinfo
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import MarketDailyPrice, MarketIntradayBar
from app.market.trading_calendar import TAIWAN_TZ


HISTORY_CALENDAR_DAYS = 75
MAX_INTRADAY_ROWS = 12_000
MIN_DISPLAY_SAMPLE_DAYS = 3
COMPLETE_DAY_MIN_RATIO = 0.9
COMPLETE_DAY_MAX_RATIO = 1.1


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_market_datetime(value: Any, *, market_timezone: tzinfo) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=market_timezone)
    return value.astimezone(market_timezone)


def _current_cumulative_volume(
    points: list[dict[str, Any]],
    *,
    latest_at: datetime,
    market_timezone: tzinfo,
) -> int | None:
    latest_point = points[-1] if points else None
    cumulative = (
        _as_number(latest_point.get("cumulative_volume"))
        if isinstance(latest_point, dict)
        else None
    )
    if cumulative is not None and cumulative >= 0:
        return int(cumulative)

    total = 0
    has_volume = False
    for point in points:
        point_at = _as_market_datetime(point.get("time"), market_timezone=market_timezone)
        volume = _as_number(point.get("volume"))
        if (
            point_at is None
            or point_at.date() != latest_at.date()
            or point_at > latest_at
            or volume is None
            or volume < 0
        ):
            continue
        total += int(volume)
        has_volume = True
    return total if has_volume else None


def _baseline_payload(
    *,
    current_volume: int | None,
    samples: list[tuple[date, int]],
    requested_days: int,
) -> dict[str, Any]:
    selected = samples[-requested_days:]
    sample_values = [value for _, value in selected]
    baseline = int(median(sample_values)) if sample_values else None
    pace_ratio = (
        current_volume / baseline
        if current_volume is not None
        and baseline is not None
        and baseline > 0
        and len(selected) >= MIN_DISPLAY_SAMPLE_DAYS
        else None
    )
    return {
        "requested_days": requested_days,
        "sample_days": len(selected),
        "minimum_display_sample_days": MIN_DISPLAY_SAMPLE_DAYS,
        "median_cumulative_volume": baseline,
        "pace_ratio": pace_ratio,
        "difference_pct": (pace_ratio - 1) * 100 if pace_ratio is not None else None,
        "history_trade_dates": [trade_date.isoformat() for trade_date, _ in selected],
    }


def _daily_total_map(rows: Iterable[Any]) -> dict[date, int]:
    daily_totals: dict[date, int] = {}
    for row in rows:
        trade_date = getattr(row, "trade_date", None)
        volume = _as_number(getattr(row, "trade_volume", None))
        if not isinstance(trade_date, date) or volume is None or volume <= 0:
            continue
        daily_totals[trade_date] = max(daily_totals.get(trade_date, 0), int(volume))
    return daily_totals


def latest_market_trade_date_points(
    points: list[dict[str, Any]],
    *,
    market_timezone: tzinfo,
) -> list[dict[str, Any]]:
    parsed = [
        (point, _as_market_datetime(point.get("time"), market_timezone=market_timezone))
        for point in points
        if isinstance(point, dict)
    ]
    parsed = [(point, point_at) for point, point_at in parsed if point_at is not None]
    if not parsed:
        return []
    latest_trade_date = max(point_at.date() for _, point_at in parsed)
    return [
        point
        for point, point_at in sorted(parsed, key=lambda item: item[1])
        if point_at.date() == latest_trade_date
    ]


def intraday_history_needs_bootstrap(
    db: Session,
    *,
    stock_id: str,
    market: str,
    market_timezone: tzinfo,
    required_trade_dates: int = 5,
) -> bool:
    rows = (
        db.query(MarketIntradayBar.bar_time)
        .filter(MarketIntradayBar.stock_id == stock_id)
        .filter(MarketIntradayBar.market == market)
        .filter(MarketIntradayBar.interval == "1m")
        .order_by(MarketIntradayBar.bar_time.desc())
        .limit(MAX_INTRADAY_ROWS)
        .all()
    )
    trade_dates = {
        point_at.date()
        for (bar_time,) in rows
        if (point_at := _as_market_datetime(bar_time, market_timezone=market_timezone))
        is not None
    }
    return len(trade_dates) < required_trade_dates


def previous_regular_close_from_history(
    points: list[dict[str, Any]],
    *,
    market_timezone: tzinfo,
    current_trade_date: date,
) -> dict[str, Any] | None:
    candidates: list[tuple[dict[str, Any], datetime]] = []
    for point in points:
        if not isinstance(point, dict) or point.get("session", "regular") != "regular":
            continue
        point_at = _as_market_datetime(point.get("time"), market_timezone=market_timezone)
        price = _as_number(point.get("price"))
        if point_at is None or point_at.date() >= current_trade_date or price is None:
            continue
        candidates.append((point, point_at))
    if not candidates:
        return None
    point, point_at = max(candidates, key=lambda item: item[1])
    return {
        "previous_close": _as_number(point.get("price")),
        "previous_close_source": "yahoo_finance_chart_intraday_history",
        "previous_close_trade_date": point_at.date().isoformat(),
        "previous_close_provider": "yahoo_chart",
    }


def mutate_market_intraday_history(
    db: Session,
    *,
    provider: str,
    stock_id: str,
    market: str,
    symbol: str,
    interval: str,
    source: str,
    source_url: str | None,
    points: list[dict[str, Any]],
    market_timezone: tzinfo,
) -> int:
    parsed: list[tuple[dict[str, Any], datetime]] = []
    for point in points:
        if not isinstance(point, dict) or point.get("session", "regular") != "regular":
            continue
        point_at = _as_market_datetime(point.get("time"), market_timezone=market_timezone)
        price = _as_number(point.get("price"))
        if point_at is None or price is None:
            continue
        parsed.append((point, point_at.replace(tzinfo=None)))
    if not parsed:
        return 0

    first_at = min(point_at for _, point_at in parsed)
    last_at = max(point_at for _, point_at in parsed)
    existing_rows = (
        db.query(MarketIntradayBar)
        .filter(MarketIntradayBar.provider == provider)
        .filter(MarketIntradayBar.stock_id == stock_id)
        .filter(MarketIntradayBar.interval == interval)
        .filter(MarketIntradayBar.bar_time >= first_at)
        .filter(MarketIntradayBar.bar_time <= last_at)
        .all()
    )
    existing_by_time = {
        (
            row.bar_time.astimezone(market_timezone).replace(tzinfo=None)
            if row.bar_time.tzinfo is not None
            else row.bar_time
        ): row
        for row in existing_rows
    }
    changed_count = 0
    for point, point_at in parsed:
        price = _as_number(point.get("price"))
        values = {
            "market": market,
            "symbol": symbol,
            "open_price": _as_number(point.get("open")) or price,
            "high_price": _as_number(point.get("high")) or price,
            "low_price": _as_number(point.get("low")) or price,
            "close_price": price,
            "trade_volume": (
                int(volume)
                if (volume := _as_number(point.get("volume"))) is not None and volume >= 0
                else None
            ),
            "trade_value": (
                int(trade_value)
                if (trade_value := _as_number(point.get("trade_value"))) is not None
                and trade_value >= 0
                else None
            ),
            "source": source,
            "source_url": source_url,
        }
        existing = existing_by_time.get(point_at)
        if existing is None:
            db.add(
                MarketIntradayBar(
                    provider=provider,
                    stock_id=stock_id,
                    interval=interval,
                    bar_time=point_at,
                    **values,
                )
            )
            changed_count += 1
            continue
        if not any(getattr(existing, key) != value for key, value in values.items()):
            continue
        for key, value in values.items():
            setattr(existing, key, value)
        changed_count += 1
    return changed_count


def build_stock_volume_pace(
    db: Session,
    *,
    stock_id: str,
    market: str,
    current_points: list[dict[str, Any]],
    market_timezone: tzinfo,
    daily_totals: dict[date, int],
    daily_source_name: str,
    history_market: str | None = None,
    complete_day_min_ratio: float = COMPLETE_DAY_MIN_RATIO,
    complete_day_max_ratio: float = COMPLETE_DAY_MAX_RATIO,
    minimum_history_points_per_day: int = 0,
) -> dict[str, Any]:
    parsed_points = [
        (point, _as_market_datetime(point.get("time"), market_timezone=market_timezone))
        for point in current_points
        if isinstance(point, dict)
    ]
    parsed_points = [(point, point_at) for point, point_at in parsed_points if point_at]
    parsed_points.sort(key=lambda item: item[1])
    empty_samples: list[tuple[date, int]] = []
    if not parsed_points:
        return {
            "kind": "stock_same_time_volume_pace",
            "stock_id": stock_id,
            "market": market,
            "session_scope": "regular",
            "status": "empty",
            "as_of": None,
            "trade_date": None,
            "comparison_minute": None,
            "current_cumulative_volume": None,
            "same_time_baseline_5d": _baseline_payload(
                current_volume=None,
                samples=empty_samples,
                requested_days=5,
            ),
            "same_time_baseline_20d": _baseline_payload(
                current_volume=None,
                samples=empty_samples,
                requested_days=20,
            ),
            "history_acceptance": {
                "minimum_daily_volume_coverage_ratio": complete_day_min_ratio,
                "maximum_daily_volume_coverage_ratio": complete_day_max_ratio,
                "minimum_minute_points_per_day": minimum_history_points_per_day,
            },
            "warnings": ["Current regular-session intraday volume is unavailable."],
            "source_refs": [
                {"type": "table", "name": "market_intraday_bar"},
                {"type": "table", "name": daily_source_name},
            ],
        }

    latest_at = max(point_at for _, point_at in parsed_points)
    current_volume = _current_cumulative_volume(
        [point for point, _ in parsed_points],
        latest_at=latest_at,
        market_timezone=market_timezone,
    )
    history_start = latest_at.date() - timedelta(days=HISTORY_CALENDAR_DAYS)
    history_query = (
        db.query(MarketIntradayBar)
        .filter(MarketIntradayBar.stock_id == stock_id)
        .filter(MarketIntradayBar.interval == "1m")
        .filter(MarketIntradayBar.bar_time >= datetime.combine(history_start, datetime.min.time()))
    )
    if history_market is not None:
        history_query = history_query.filter(MarketIntradayBar.market == history_market)
    history_rows = (
        history_query.order_by(MarketIntradayBar.bar_time.desc())
        .limit(MAX_INTRADAY_ROWS)
        .all()
    )

    minute_volumes: dict[date, dict[tuple[int, int], int]] = defaultdict(dict)
    for row in history_rows:
        row_at = _as_market_datetime(row.bar_time, market_timezone=market_timezone)
        volume = _as_number(row.trade_volume)
        if (
            row_at is None
            or row_at.date() >= latest_at.date()
            or volume is None
            or volume < 0
        ):
            continue
        minute_key = (row_at.hour, row_at.minute)
        minute_volumes[row_at.date()][minute_key] = max(
            minute_volumes[row_at.date()].get(minute_key, 0),
            int(volume),
        )

    comparison_key = (latest_at.hour, latest_at.minute)
    complete_samples: list[tuple[date, int]] = []
    incomplete_dates: list[str] = []
    missing_daily_dates: list[str] = []
    for trade_date in sorted(minute_volumes):
        volumes_by_minute = minute_volumes[trade_date]
        intraday_total = sum(volumes_by_minute.values())
        daily_total = daily_totals.get(trade_date)
        if daily_total is None:
            missing_daily_dates.append(trade_date.isoformat())
            continue
        completion_ratio = intraday_total / daily_total if daily_total > 0 else 0
        if (
            len(volumes_by_minute) < minimum_history_points_per_day
            or not complete_day_min_ratio <= completion_ratio <= complete_day_max_ratio
        ):
            incomplete_dates.append(trade_date.isoformat())
            continue
        cumulative_at_time = sum(
            volume for minute_key, volume in volumes_by_minute.items() if minute_key <= comparison_key
        )
        complete_samples.append((trade_date, cumulative_at_time))

    complete_samples = complete_samples[-20:]
    baseline_5d = _baseline_payload(
        current_volume=current_volume,
        samples=complete_samples,
        requested_days=5,
    )
    baseline_20d = _baseline_payload(
        current_volume=current_volume,
        samples=complete_samples,
        requested_days=20,
    )
    warnings: list[str] = []
    if baseline_5d["sample_days"] < 5:
        warnings.append(
            "Fewer than 5 complete prior sessions are available at the same minute; volume pace is provisional."
        )
    if baseline_20d["sample_days"] < 20:
        warnings.append(
            "The 20-session same-time baseline is incomplete and will improve as minute history accumulates."
        )
    if incomplete_dates:
        warnings.append(
            f"Excluded {len(incomplete_dates)} incomplete intraday session(s) after daily-volume reconciliation."
        )
    if missing_daily_dates:
        warnings.append(
            f"Excluded {len(missing_daily_dates)} session(s) without a finalized daily-volume reference."
        )

    return {
        "kind": "stock_same_time_volume_pace",
        "stock_id": stock_id,
        "market": market,
        "session_scope": "regular",
        "status": (
            "ready"
            if baseline_5d["sample_days"] >= 5 and current_volume is not None
            else "partial"
            if baseline_5d["sample_days"] > 0 or current_volume is not None
            else "empty"
        ),
        "as_of": latest_at.isoformat(),
        "trade_date": latest_at.date().isoformat(),
        "comparison_minute": latest_at.strftime("%H:%M"),
        "calculation_basis": (
            "Current regular-session cumulative share volume compared with the median cumulative "
            f"volume of prior complete {market} sessions at or before the same local market minute."
        ),
        "current_cumulative_volume": current_volume,
        "same_time_baseline_5d": baseline_5d,
        "same_time_baseline_20d": baseline_20d,
        "excluded_incomplete_trade_dates": incomplete_dates,
        "excluded_missing_daily_trade_dates": missing_daily_dates,
        "history_acceptance": {
            "minimum_daily_volume_coverage_ratio": complete_day_min_ratio,
            "maximum_daily_volume_coverage_ratio": complete_day_max_ratio,
            "minimum_minute_points_per_day": minimum_history_points_per_day,
        },
        "warnings": warnings,
        "source_refs": [
            {"type": "table", "name": "market_intraday_bar"},
            {"type": "table", "name": daily_source_name},
        ],
    }


def build_tw_stock_volume_pace(
    db: Session,
    *,
    stock_id: str,
    current_points: list[dict[str, Any]],
) -> dict[str, Any]:
    daily_rows = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .order_by(MarketDailyPrice.trade_date.desc())
        .limit(90)
        .all()
    )
    result = build_stock_volume_pace(
        db,
        stock_id=stock_id,
        market="TW",
        current_points=current_points,
        market_timezone=TAIWAN_TZ,
        daily_totals=_daily_total_map(daily_rows),
        daily_source_name="market_daily_price",
    )
    result["kind"] = "tw_stock_same_time_volume_pace"
    return result


__all__ = [
    "build_stock_volume_pace",
    "build_tw_stock_volume_pace",
    "intraday_history_needs_bootstrap",
    "latest_market_trade_date_points",
    "mutate_market_intraday_history",
    "previous_regular_close_from_history",
]
