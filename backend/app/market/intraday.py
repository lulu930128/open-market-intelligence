from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from threading import Lock
import time as monotonic_time

from sqlalchemy.orm import Session

from app.db.models import MarketIntradayBar, StockMaster
from app.market.public_quote_platform import read_taiwan_public_last_trade_quote
from app.market.tw_disposition import get_taiwan_disposition_status
from app.market.tw_instrument_trading_policy import (
    TaiwanInstrumentTradingMode,
    resolve_taiwan_instrument_trading_policy,
)
from app.market.tw_intraday_platform import (
    intraday_history_config,
    project_taiwan_intraday_bars,
    read_taiwan_intraday_bars,
)
from app.market_data.contracts import (
    ResolvedEvidenceStatus,
    TradeObservationState,
)
from app.market_data.integration_contracts import MarketDataResultV1
from app.observability.provider_fallback import observe_provider_fallback


TAIPEI_TZ = timezone(timedelta(hours=8))
INTRADAY_CACHE_TTL_SECONDS = 4.75
_INTRADAY_CACHE: dict[str, tuple[float, dict]] = {}
_INTRADAY_CACHE_LOCK = Lock()
_INTRADAY_FETCH_LOCKS: dict[str, Lock] = {}

# Yahoo's `5d` minute range is trading-day based. Query the local DB with a
# wider calendar-day window so weekends and holidays do not hide persisted bars.


def _cache_get(cache_key: str) -> dict | None:
    with _INTRADAY_CACHE_LOCK:
        cached = _INTRADAY_CACHE.get(cache_key)
        if cached is None:
            return None

        cached_at, payload = cached
        if monotonic_time.monotonic() - cached_at > INTRADAY_CACHE_TTL_SECONDS:
            _INTRADAY_CACHE.pop(cache_key, None)
            return None

        return deepcopy(payload)


def _cache_set(cache_key: str, payload: dict) -> dict:
    with _INTRADAY_CACHE_LOCK:
        _INTRADAY_CACHE[cache_key] = (
            monotonic_time.monotonic(),
            deepcopy(payload),
        )
    return payload


def _get_intraday_fetch_lock(cache_key: str) -> Lock:
    with _INTRADAY_CACHE_LOCK:
        return _INTRADAY_FETCH_LOCKS.setdefault(cache_key, Lock())


def _as_float(value) -> float | None:
    if value is None:
        return None

    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _as_int(value) -> int | None:
    if value is None:
        return None

    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def _get_stock(db: Session, stock_id: str) -> StockMaster | None:
    return db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()


def _yahoo_symbol(stock_id: str, market: str | None) -> str:
    if market == "TPEX":
        return f"{stock_id}.TWO"

    return f"{stock_id}.TW"


def _point_datetime(point: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(point["time"]))
    except (KeyError, ValueError):
        return None


def _normalize_bar_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIPEI_TZ)

    return value.astimezone(TAIPEI_TZ)


def _is_taiwan_regular_session_time(value: datetime) -> bool:
    local_time = _normalize_bar_time(value)
    minutes = local_time.hour * 60 + local_time.minute

    return 9 * 60 <= minutes <= 13 * 60 + 30


def _intraday_row_to_point(row: MarketIntradayBar) -> dict:
    return {
        "time": _normalize_bar_time(row.bar_time),
        "open": row.open_price,
        "high": row.high_price,
        "low": row.low_price,
        "close": row.close_price,
        "volume": row.trade_volume,
        "trade_value": row.trade_value,
        "transaction_count": None,
    }


def _interval_seconds(interval: str) -> int:
    normalized = str(interval or "1m").strip().lower()
    if normalized.endswith("s") and normalized[:-1].isdigit():
        return int(normalized[:-1])
    if normalized.endswith("m") and normalized[:-1].isdigit():
        return int(normalized[:-1]) * 60
    if normalized.endswith("h") and normalized[:-1].isdigit():
        return int(normalized[:-1]) * 3600
    return 60


def _provider_volume_unit(source: str) -> str:
    normalized = str(source or "").lower()
    if "twse_mis" in normalized or normalized.startswith("nstock"):
        return "lots"
    if "yahoo" in normalized:
        return "shares"
    return "unknown"


def _intraday_bar_semantics(
    point: dict,
    *,
    point_time: datetime | None,
    interval: str,
) -> dict:
    explicit_bar_type = str(point.get("bar_type") or "").strip().lower()
    known_bar_types = {
        "regular_interval",
        "closing_auction",
        "official_close_marker",
        "post_close_summary",
        "provider_irregular",
        "synthetic_fill",
    }
    synthetic = bool(point.get("synthetic")) or explicit_bar_type == "synthetic_fill"
    volume = _as_int(
        point.get("volume_shares")
        if point.get("volume_shares") is not None
        else point.get("volume")
    )

    if explicit_bar_type in known_bar_types:
        bar_type = explicit_bar_type
    elif synthetic:
        bar_type = "synthetic_fill"
    elif point_time is None:
        bar_type = "provider_irregular"
    else:
        local_time = point_time.astimezone(TAIPEI_TZ)
        interval_seconds = max(_interval_seconds(interval), 1)
        seconds_from_hour = local_time.minute * 60 + local_time.second
        interval_aligned = seconds_from_hour % interval_seconds == 0
        clock = local_time.time().replace(tzinfo=None)
        if not interval_aligned:
            bar_type = "provider_irregular"
        elif clock == time(13, 30) and (volume is None or volume == 0):
            bar_type = "official_close_marker"
        elif time(13, 25) <= clock <= time(13, 30):
            bar_type = "closing_auction"
        elif time(9, 0) <= clock < time(13, 25):
            bar_type = "regular_interval"
        else:
            bar_type = "provider_irregular"

    session_phase = {
        "regular_interval": "regular",
        "closing_auction": "closing_auction",
        "official_close_marker": "post_close",
        "post_close_summary": "post_close",
        "synthetic_fill": "synthetic",
        "provider_irregular": "provider_irregular",
    }[bar_type]
    market_event = {
        "regular_interval": "continuous_trading",
        "closing_auction": "closing_auction",
        "official_close_marker": "official_close",
        "post_close_summary": "post_close_confirmation",
        "synthetic_fill": "synthetic_fill",
        "provider_irregular": "provider_irregular",
    }[bar_type]
    source_event_type = (
        point.get("source_event_type")
        or ("synthetic" if synthetic else "provider_bar")
    )
    return {
        "bar_type": bar_type,
        "synthetic": synthetic,
        "session_phase": session_phase,
        "market_event": market_event,
        "source_event_type": source_event_type,
        "gap_reason": point.get("gap_reason"),
    }


def _latest_trade_date_points(
    points: list[dict],
) -> tuple[date | None, list[dict]]:
    dated_points: list[tuple[date, dict]] = []
    for point in points:
        point_time = _point_datetime(point)
        if point_time is None:
            continue
        dated_points.append((_normalize_bar_time(point_time).date(), point))

    if not dated_points:
        return None, []

    latest_trade_date = max(trade_date for trade_date, _ in dated_points)
    return latest_trade_date, [
        point
        for trade_date, point in dated_points
        if trade_date == latest_trade_date
    ]


def _intraday_bar_metrics(points: list[dict]) -> dict[str, int | float | None]:
    official_trade_value = 0
    estimated_trade_value = 0.0
    exact_value_points = 0
    volume_points = 0
    total_volume_shares = 0
    weighted_price_volume = 0.0

    for point in points:
        volume_shares = _as_int(point.get("volume_shares"))
        if volume_shares is not None:
            volume_points += 1
            total_volume_shares += max(volume_shares, 0)

        exact_trade_value = _as_int(point.get("trade_value"))
        approx_trade_value = _as_float(point.get("approx_trade_value"))
        if exact_trade_value is not None:
            exact_value_points += 1
            official_trade_value += exact_trade_value
            estimated_trade_value += exact_trade_value
        elif approx_trade_value is not None:
            estimated_trade_value += approx_trade_value

        close_price = _as_float(point.get("close") or point.get("price"))
        if close_price is not None and volume_shares is not None and volume_shares > 0:
            weighted_price_volume += close_price * volume_shares

    exact_complete = volume_points > 0 and exact_value_points == volume_points
    return {
        "volume_points": volume_points,
        "total_volume_shares": total_volume_shares,
        "official_trade_value": official_trade_value,
        "estimated_trade_value": estimated_trade_value,
        "exact_value_points": exact_value_points,
        "exact_complete": int(exact_complete),
        "approx_vwap": (
            weighted_price_volume / total_volume_shares
            if total_volume_shares > 0
            else None
        ),
        "official_vwap": (
            official_trade_value / total_volume_shares
            if exact_complete and total_volume_shares > 0
            else None
        ),
    }


def _enrich_intraday_contract(
    points: list[dict],
    *,
    interval: str,
    source: str,
    now: datetime | None = None,
) -> tuple[list[dict], dict]:
    checked_at = (now or datetime.now(TAIPEI_TZ)).astimezone(TAIPEI_TZ)
    provider_volume_unit = _provider_volume_unit(source)
    interval_delta = timedelta(seconds=_interval_seconds(interval))
    enriched: list[dict] = []

    for raw_point in points:
        point = dict(raw_point)
        point_time = _point_datetime(point)
        volume_shares = _as_int(point.get("volume"))
        exact_trade_value = _as_int(point.get("trade_value"))
        open_price = _as_float(point.get("open"))
        high_price = _as_float(point.get("high"))
        low_price = _as_float(point.get("low"))
        close_price = _as_float(point.get("close") or point.get("price"))
        typical_prices = [
            value
            for value in (high_price, low_price, close_price)
            if value is not None
        ]
        typical_price = (
            sum(typical_prices) / len(typical_prices)
            if typical_prices
            else open_price
        )
        approx_trade_value = (
            typical_price * volume_shares
            if typical_price is not None
            and volume_shares is not None
            and volume_shares >= 0
            else None
        )
        bar_close_time = point_time + interval_delta if point_time is not None else None
        is_partial = bool(
            bar_close_time is not None
            and point_time is not None
            and point_time.date() == checked_at.date()
            and checked_at < bar_close_time
        )
        elapsed_seconds = (
            max(int((checked_at - point_time).total_seconds()), 0)
            if point_time is not None
            else None
        )
        bar_semantics = _intraday_bar_semantics(
            point,
            point_time=point_time,
            interval=interval,
        )
        finalized = not is_partial if point_time is not None else False
        indicator_eligible = bool(
            finalized
            and not bar_semantics["synthetic"]
            and bar_semantics["bar_type"]
            in {"regular_interval", "closing_auction"}
        )
        point.update(
            {
                "close": close_price,
                "volume_shares": volume_shares,
                "volume_lots": (
                    volume_shares / 1000 if volume_shares is not None else None
                ),
                "canonical_volume_unit": "shares",
                "provider_volume_unit": provider_volume_unit,
                "volume_status": (
                    "available" if volume_shares is not None else "not_provided"
                ),
                "approx_trade_value": approx_trade_value,
                "trade_value_status": (
                    "official"
                    if exact_trade_value is not None
                    else "estimated"
                    if approx_trade_value is not None
                    else "not_provided"
                ),
                "bar_close_time": (
                    bar_close_time.isoformat() if bar_close_time is not None else None
                ),
                "elapsed_seconds": elapsed_seconds,
                "is_partial": is_partial,
                "finalized": finalized,
                "indicator_eligible": indicator_eligible,
                **bar_semantics,
            }
        )
        enriched.append(point)

    latest_trade_date, session_points = _latest_trade_date_points(enriched)
    session_metrics = _intraday_bar_metrics(session_points)
    window_metrics = _intraday_bar_metrics(enriched)
    volume_points = int(session_metrics["volume_points"] or 0)
    total_volume_shares = int(session_metrics["total_volume_shares"] or 0)
    exact_value_points = int(session_metrics["exact_value_points"] or 0)
    official_trade_value = int(session_metrics["official_trade_value"] or 0)
    estimated_trade_value = float(session_metrics["estimated_trade_value"] or 0.0)
    exact_complete = bool(session_metrics["exact_complete"])
    approximate_vwap = _as_float(session_metrics["approx_vwap"])
    official_vwap = _as_float(session_metrics["official_vwap"])
    bar_latest_time = (
        _point_datetime(session_points[-1]) if session_points else None
    )
    bar_volume_sum_shares = total_volume_shares if volume_points else None
    window_volume_points = int(window_metrics["volume_points"] or 0)
    window_volume_sum_shares = (
        int(window_metrics["total_volume_shares"] or 0)
        if window_volume_points
        else None
    )
    trade_dates = {
        _normalize_bar_time(point_time).date()
        for point in enriched
        if (point_time := _point_datetime(point)) is not None
    }
    trade_value_status = (
        "complete"
        if exact_complete
        else "partial"
        if exact_value_points > 0
        else "estimated"
        if estimated_trade_value > 0
        else "not_provided"
    )
    metadata = {
        "canonical_volume_unit": "shares",
        "provider_volume_unit": provider_volume_unit,
        "volume_conversion": (
            "provider_lots_x_1000_to_shares"
            if provider_volume_unit == "lots"
            else "identity"
            if provider_volume_unit == "shares"
            else "unknown"
        ),
        "volume_semantics": "latest_trade_date_interval_bar_sum_fallback",
        "volume_scope": "latest_trade_date_interval_bar_sum",
        "bar_volume_sum_shares": bar_volume_sum_shares,
        "bar_volume_sum_lots": (
            bar_volume_sum_shares / 1000
            if bar_volume_sum_shares is not None
            else None
        ),
        "bar_volume_trade_date": (
            latest_trade_date.isoformat() if latest_trade_date is not None else None
        ),
        "bar_volume_latest_time": (
            _normalize_bar_time(bar_latest_time).isoformat()
            if bar_latest_time is not None
            else None
        ),
        "bar_volume_scope": "latest_trade_date_interval_bar_sum",
        "bar_volume_provider": source or None,
        "window_volume_sum_shares": window_volume_sum_shares,
        "window_volume_sum_lots": (
            window_volume_sum_shares / 1000
            if window_volume_sum_shares is not None
            else None
        ),
        "window_volume_scope": "query_window_interval_bar_sum",
        "window_trade_date_count": len(trade_dates),
        "session_cumulative_volume_shares": None,
        "session_cumulative_volume_lots": None,
        "session_cumulative_volume_trade_date": None,
        "session_cumulative_volume_source": None,
        "session_cumulative_volume_source_field": None,
        "session_cumulative_volume_event_time": None,
        "session_cumulative_volume_status": (
            "fallback_bar_sum"
            if bar_volume_sum_shares is not None
            else "unavailable"
        ),
        "cumulative_volume_shares": (
            bar_volume_sum_shares
        ),
        "cumulative_volume_lots": (
            bar_volume_sum_shares / 1000
            if bar_volume_sum_shares is not None
            else None
        ),
        "cumulative_volume_trade_date": (
            latest_trade_date.isoformat() if latest_trade_date is not None else None
        ),
        "cumulative_volume_source": (
            "intraday_bar_sum" if bar_volume_sum_shares is not None else None
        ),
        "cumulative_volume_source_field": (
            "interval_bar.volume" if bar_volume_sum_shares is not None else None
        ),
        "cumulative_volume_event_time": (
            _normalize_bar_time(bar_latest_time).isoformat()
            if bar_latest_time is not None
            else None
        ),
        "cumulative_volume_status": (
            "fallback_bar_sum"
            if bar_volume_sum_shares is not None
            else "unavailable"
        ),
        "unallocated_volume_shares": None,
        "unallocated_volume_lots": None,
        "volume_reconciliation": {
            "status": "unavailable",
            "trade_date": (
                latest_trade_date.isoformat()
                if latest_trade_date is not None
                else None
            ),
            "exchange_cumulative_shares": None,
            "bar_volume_sum_shares": bar_volume_sum_shares,
            "difference_shares": None,
            "difference_lots": None,
            "difference_pct": None,
            "exchange_event_time": None,
            "bar_latest_time": (
                _normalize_bar_time(bar_latest_time).isoformat()
                if bar_latest_time is not None
                else None
            ),
            "time_skew_seconds": None,
            "reason": "exchange_cumulative_unavailable",
        },
        "cumulative_trade_value": (
            official_trade_value if exact_complete else None
        ),
        "available_cumulative_trade_value": (
            official_trade_value if exact_value_points else None
        ),
        "estimated_cumulative_trade_value": (
            int(round(estimated_trade_value))
            if estimated_trade_value > 0
            else None
        ),
        "trade_value_unit": "TWD",
        "trade_value_status": trade_value_status,
        "official_vwap": official_vwap,
        "approx_vwap": approximate_vwap,
        "vwap_method": (
            "official_trade_value_divided_by_volume_shares"
            if official_vwap is not None
            else "close_price_volume_weighted_approximation"
            if approximate_vwap is not None
            else "unavailable"
        ),
        "vwap_confidence": (
            "high"
            if official_vwap is not None
            else "medium"
            if approximate_vwap is not None
            else "unavailable"
        ),
        "vwap_volume_scope": "latest_trade_date_interval_bars",
        "partial_bar_count": sum(
            1 for point in enriched if point.get("is_partial") is True
        ),
        "indicator_eligible_point_count": sum(
            1 for point in enriched if point.get("indicator_eligible") is True
        ),
        "bar_classification_policy": "taiwan_cash_session_v1",
        "indicator_policy": (
            "finalized_regular_interval_or_closing_auction_only"
        ),
        "partial_bar_policy": "exclude_partial_bars_from_indicators",
        "aggregation_method": (
            "provider_interval_bars_with_explicit_market_event_markers"
        ),
    }
    return enriched, metadata


def _dedupe_disposition_points(points: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    previous_state: tuple[float | None, int | None, str | None] | None = None
    for point in sorted(points, key=lambda item: str(item.get("time") or "")):
        state = (
            _as_float(point.get("price") if point.get("price") is not None else point.get("close")),
            _as_int(point.get("cumulative_volume") if point.get("cumulative_volume") is not None else point.get("volume")),
            str(
                point.get("official_trade_timestamp")
                or point.get("official_trade_time")
                or ""
            )
            or None,
        )
        if previous_state is not None and state == previous_state:
            continue
        deduped.append(point)
        previous_state = state
    return deduped


def _apply_disposition_intraday_contract(
    result: dict,
    disposition: dict,
) -> dict:
    policy = resolve_taiwan_instrument_trading_policy(disposition)
    if (
        policy.trading_mode
        is not TaiwanInstrumentTradingMode.DISPOSITION_BATCH_AUCTION
    ):
        return {
            **result,
            **policy.projection(),
            "effective_match_count": None,
            "batch_interval_minutes": None,
            "disposition_start_date": None,
            "disposition_end_date": None,
        }
    points = _dedupe_disposition_points(
        [point for point in result.get("points") or [] if isinstance(point, dict)]
    )
    return {
        **result,
        **policy.projection(),
        "points": points,
        "point_count": len(points),
        "effective_match_count": len(points),
        "batch_interval_minutes": disposition.get("matching_interval_minutes"),
        "disposition_start_date": disposition.get("start_date"),
        "disposition_end_date": disposition.get("end_date"),
    }


def _apply_platform_quote_contract(
    result: dict,
    quote_result: MarketDataResultV1 | None,
    *,
    unavailable_reason: str | None = None,
) -> dict:
    """Project a resolved quote beside bars without manufacturing a new bar."""

    original_source = str(result.get("source") or "unknown")
    price_provider = (
        "nstock"
        if original_source.startswith("nstock")
        else "yahoo_finance_chart"
        if original_source.startswith("yahoo")
        else original_source
    )
    points = [
        point for point in result.get("points") or [] if isinstance(point, dict)
    ]
    latest_history_point = max(
        points,
        key=lambda point: (
            _normalize_bar_time(point_time).timestamp()
            if (point_time := _point_datetime(point)) is not None
            else float("-inf")
        ),
        default=None,
    )
    latest_history_time = (
        _normalize_bar_time(point_time)
        if latest_history_point is not None
        and (point_time := _point_datetime(latest_history_point)) is not None
        else None
    )
    latest_history_price = (
        _as_float(
            latest_history_point.get("price")
            if latest_history_point.get("price") is not None
            else latest_history_point.get("close")
        )
        if latest_history_point is not None
        else None
    )
    quote = quote_result.resolved.quote if quote_result is not None else None
    health = quote_result.resolved.health if quote_result is not None else None
    event_at = quote.lineage.event_at if quote is not None else None
    actual_trade_observed = bool(
        quote is not None
        and quote.trade_state is TradeObservationState.TRADE_OBSERVED
        and quote.last_trade_price is not None
        and event_at is not None
    )
    current_trade_available = bool(
        actual_trade_observed
        and health is not None
        and health.status
        in {
            ResolvedEvidenceStatus.SELECTED,
            ResolvedEvidenceStatus.FALLBACK,
        }
        and health.research_usable
    )
    actual_trade_price = (
        float(quote.last_trade_price)
        if actual_trade_observed and quote is not None
        else None
    )
    lag_seconds = (
        (event_at - latest_history_time).total_seconds()
        if event_at is not None and latest_history_time is not None
        else None
    )
    history_observation = (
        {
            "value": latest_history_price,
            "observed_at": latest_history_time.isoformat(),
            "confirmed_at": None,
            "price_semantics": "intraday_bar_close",
            "provider": price_provider,
            "freshness_status": "history_latest",
            "decision_usable": False,
        }
        if latest_history_price is not None and latest_history_time is not None
        else None
    )
    current_observation = (
        {
            "value": actual_trade_price,
            "observed_at": event_at.isoformat(),
            "confirmed_at": event_at.isoformat(),
            "price_semantics": "actual_trade",
            "provider": quote.lineage.provider,
            "freshness_status": health.status.value,
            "decision_usable": True,
        }
        if current_trade_available
        and quote is not None
        and health is not None
        and event_at is not None
        else history_observation
    )
    source_components = []
    if points:
        source_components.extend(
            (
                {
                    "domain": "price_bars",
                    "provider": price_provider,
                    "source": original_source,
                },
                {
                    "domain": "bar_volume",
                    "provider": price_provider,
                    "source": original_source,
                },
            )
        )
    if actual_trade_observed and quote is not None and health is not None:
        source_components.append(
            {
                "domain": "current_trade",
                "provider": quote.lineage.provider,
                "source": quote.lineage.source,
                "event_at": event_at.isoformat() if event_at else None,
                "resolved_status": health.status.value,
            }
        )
    if unavailable_reason is None and not current_trade_available:
        unavailable_reason = (
            health.selection_reason
            if health is not None
            else "PUBLIC_QUOTE_PLATFORM_UNAVAILABLE"
        )
    result.update(
        {
            "provider": price_provider,
            "price_provider": price_provider,
            "volume_provider": price_provider,
            "source_components": source_components,
            "points": points,
            "point_count": len(points),
            "history_price_source": price_provider,
            "latest_history_time": (
                latest_history_time.isoformat() if latest_history_time else None
            ),
            "latest_history_price": latest_history_price,
            "latest_actual_trade_time": (
                event_at.isoformat() if actual_trade_observed and event_at else None
            ),
            "latest_actual_trade_price": actual_trade_price,
            "current_price_source": (
                quote.lineage.source
                if current_trade_available and quote is not None
                else None
            ),
            "lag_seconds": lag_seconds,
            "current_trade_available": current_trade_available,
            "current_trade_unavailable_reason": (
                None if current_trade_available else unavailable_reason
            ),
            "current_price_applied_to_history": False,
            "capabilities": {
                "supports_volume": True,
                "supports_vwap": True,
                "supports_price_limit": True,
                "supports_quote_depth": True,
            },
            "current_observation": current_observation,
            "observations": (
                [current_observation] if current_observation is not None else []
            ),
            "resolution_version": (
                quote_result.contract_version if quote_result is not None else None
            ),
            "resolution_id": (
                quote.lineage.observation_id if quote is not None else None
            ),
            "acquisition_policy": (
                quote_result.requirement.realtime_policy.value
                if quote_result is not None
                else "cache_only"
            ),
            "acquisition_status": (
                quote_result.acquisition.status.value
                if quote_result is not None
                else "not_attempted"
            ),
            "canonical_observation": (
                quote.model_dump(mode="json") if quote is not None else None
            ),
            "decision_usable": bool(
                current_trade_available and health and health.research_usable
            ),
            "resolution": (
                {
                    "health": health.model_dump(mode="json"),
                    "dataset_health": (
                        quote_result.dataset_health.model_dump(mode="json")
                        if quote_result.dataset_health is not None
                        else None
                    ),
                    "provider_health": [
                        item.model_dump(mode="json")
                        for item in quote_result.provider_health
                    ],
                    "limitations": list(quote_result.limitations),
                }
                if quote_result is not None and health is not None
                else None
            ),
            "source_provenance": (
                quote.lineage.model_dump(mode="json")
                if quote is not None
                else None
            ),
        }
    )
    if unavailable_reason and quote_result is None:
        warnings = list(result.get("warnings") or [])
        if unavailable_reason not in warnings:
            warnings.append(unavailable_reason)
        result["warnings"] = warnings
    return result


def _attach_cached_public_quote(
    db: Session,
    *,
    stock_id: str,
    result: dict,
) -> dict:
    try:
        quote_result = read_taiwan_public_last_trade_quote(
            db,
            stock_id=stock_id,
        )
    except Exception as exc:
        observe_provider_fallback(
            exc,
            operation="intraday.public_quote_cache_read",
        )
        return _apply_platform_quote_contract(
            result,
            None,
            unavailable_reason=(
                f"PUBLIC_QUOTE_PLATFORM_{type(exc).__name__.upper()}"
            ),
        )
    return _apply_platform_quote_contract(result, quote_result)


def _load_intraday_trend_uncached(
    db: Session,
    *,
    stock_id: str,
    market: str | None,
    cache_key: str,
) -> dict:
    disposition = get_taiwan_disposition_status(
        stock_id,
        market=market,
    )
    try:
        resolved = read_taiwan_intraday_bars(
            db,
            stock_id=stock_id,
            interval="1m",
            range_value="1d",
        )
        points, metadata = project_taiwan_intraday_bars(db, resolved)
    except Exception as exc:
        observe_provider_fallback(
            exc,
            operation="intraday.shared_cache_read",
        )
        points = []
        metadata = {
            "provider": None,
            "source": None,
            "limitations": [
                f"TW_INTRADAY_PLATFORM_{type(exc).__name__.upper()}"
            ],
        }
    source = str(metadata.get("source") or "unavailable")
    result = {
        "stock_id": stock_id,
        "symbol": _yahoo_symbol(stock_id=stock_id, market=market),
        "source": source,
        "provider": metadata.get("provider"),
        "previous_close": None,
        "point_count": len(points),
        "points": points,
        "interval": "1m",
        "source_interval": metadata.get("source_interval") or "1m",
        "effective_interval": "1m",
        "warnings": list(metadata.get("limitations") or []),
        "bar_resolution": metadata.get("resolved_health"),
        "bar_candidate_rejections": metadata.get("candidate_rejections") or [],
        "bar_component_raw_result_ids": (
            metadata.get("component_raw_result_ids") or []
        ),
        "bar_calculation_versions": metadata.get("calculation_versions") or [],
    }
    return _cache_set(
        cache_key,
        _apply_disposition_intraday_contract(
            _attach_cached_public_quote(db, stock_id=stock_id, result=result),
            disposition,
        ),
    )


def get_intraday_trend(db: Session, stock_id: str) -> dict:
    stock = _get_stock(db=db, stock_id=stock_id)
    market = stock.market.upper() if stock else None
    cache_key = f"{market or 'UNKNOWN'}:{stock_id}"
    cached = _cache_get(cache_key)

    if cached is not None:
        return cached

    # Ranking and radar requests can ask for the same stock concurrently. The
    # lock only deduplicates cache-only projection work; GET never owns IO.
    with _get_intraday_fetch_lock(cache_key):
        cached = _cache_get(cache_key)

        if cached is not None:
            return cached

        return _load_intraday_trend_uncached(
            db,
            stock_id=stock_id,
            market=market,
            cache_key=cache_key,
        )


def get_market_intraday_history(
    db: Session,
    *,
    stock_id: str,
    interval: str = "1m",
    range_value: str = "auto",
    refresh: bool = False,
) -> dict:
    del refresh  # legacy GET input is intentionally non-operative.
    stock = _get_stock(db=db, stock_id=stock_id)
    market = stock.market.upper() if stock else None
    disposition = get_taiwan_disposition_status(stock_id, market=market)
    trading_policy = resolve_taiwan_instrument_trading_policy(disposition)
    symbol = _yahoo_symbol(stock_id=stock_id, market=market)
    config = intraday_history_config(interval=interval, range_value=range_value)
    fetch_range = str(config["range"])
    resolved = read_taiwan_intraday_bars(
        db,
        stock_id=stock_id,
        interval=interval,
        range_value=range_value,
    )
    points, resolution_metadata = project_taiwan_intraday_bars(db, resolved)
    source = str(resolution_metadata.get("source") or "unavailable")
    provider = str(resolution_metadata.get("provider") or "unavailable")
    is_disposition_batch = (
        trading_policy.trading_mode
        is TaiwanInstrumentTradingMode.DISPOSITION_BATCH_AUCTION
    )
    if is_disposition_batch:
        points = _dedupe_disposition_points(points)
    points, contract_metadata = _enrich_intraday_contract(
        points,
        interval=interval,
        source=source,
    )

    return {
        "stock_id": stock_id,
        "symbol": symbol,
        "interval": interval,
        "requested_interval": interval,
        "source_interval": resolution_metadata.get("source_interval") or interval,
        "effective_interval": interval,
        "interval_status": "ready",
        "range": fetch_range if range_value == "auto" else range_value,
        "provider": provider,
        "source": source,
        "source_url": None,
        "from_time": _point_datetime(points[0]) if points else None,
        "to_time": _point_datetime(points[-1]) if points else None,
        "point_count": len(points),
        "cached_count": len(points),
        "refreshed_count": 0,
        "cache_status": "persisted_hit" if points else "persisted_miss",
        "cache_hit": bool(points),
        "cache_trade_date": (
            _normalize_bar_time(_point_datetime(points[-1])).date().isoformat()
            if points and _point_datetime(points[-1]) is not None
            else None
        ),
        "cache_latest_time": (
            _normalize_bar_time(_point_datetime(points[-1]))
            if points and _point_datetime(points[-1]) is not None
            else None
        ),
        "fallback_used": resolved.resolved.health.fallback_used,
        **trading_policy.projection(),
        "effective_match_count": len(points)
        if is_disposition_batch
        else None,
        "batch_interval_minutes": disposition.get("matching_interval_minutes")
        if is_disposition_batch
        else None,
        "disposition_start_date": disposition.get("start_date")
        if is_disposition_batch
        else None,
        "disposition_end_date": disposition.get("end_date")
        if is_disposition_batch
        else None,
        **contract_metadata,
        "read_policy": "cache_only",
        "acquisition_status": resolved.acquisition.status.value,
        "resolved_health": resolution_metadata.get("resolved_health"),
        "candidate_rejections": resolution_metadata.get("candidate_rejections"),
        "limitations": resolution_metadata.get("limitations"),
        "component_raw_result_ids": resolution_metadata.get(
            "component_raw_result_ids"
        ),
        "calculation_versions": resolution_metadata.get("calculation_versions"),
        "points": points,
    }
