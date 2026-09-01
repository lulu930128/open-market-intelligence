from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session

from app.market import indicator_service
from app.market.ohlc_overlay import point_date
from app.market.technical_parameters import (
    TechnicalAnalysisParameters,
    get_technical_analysis_parameters,
)
from app.market.trading_calendar import next_taiwan_trading_day
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_bar_service import TaiwanBarService
from app.research.technical.series import (
    ema_sma_seed,
    macd_sma_seed,
    number,
    percentage_volume_oscillator,
    recursive_kd,
    round_value,
    wilder_rsi,
)


INDICATOR_ALGORITHM_VERSION = "tw.technical.indicators.v4"
ADVANCED_ALGORITHM_VERSION = "tw.technical.advanced.v2"
PRICE_BASIS = "raw_unadjusted"
MAX_DAILY_BARS = 1800
PROFILE_LOOKBACK = 60
SWING_LOOKBACK = 252
BREAKOUT_LIFECYCLE_BARS = 60


def _number(value: Any) -> float | None:
    return number(value)


def _round(value: Any, digits: int = 4) -> float | None:
    return round_value(value, digits)


def _json_date(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = str(value or "").strip()
    return text or None


def _period_key(value: date, timeframe: str) -> tuple[int, int]:
    if timeframe == "weekly":
        iso_year, iso_week, _ = value.isocalendar()
        return iso_year, iso_week
    if timeframe == "monthly":
        return value.year, value.month
    return value.year, value.toordinal()


def classify_latest_period(
    points: list[dict[str, Any]],
    *,
    timeframe: str,
    latest_observation_date: date | None = None,
) -> dict[str, Any]:
    latest_date = latest_observation_date or (
        point_date(points[-1].get("time")) if points else None
    )
    if latest_date is None:
        return {
            "status": "missing",
            "latest_period_start": None,
            "latest_observation_date": None,
            "next_trading_date": None,
        }
    if timeframe == "daily":
        return {
            "status": "completed",
            "latest_period_start": latest_date.isoformat(),
            "latest_observation_date": latest_date.isoformat(),
            "next_trading_date": next_taiwan_trading_day(
                latest_date,
                include_value=False,
            ).isoformat(),
        }
    next_date = next_taiwan_trading_day(latest_date, include_value=False)
    status = (
        "completed"
        if _period_key(next_date, timeframe) != _period_key(latest_date, timeframe)
        else "current_partial"
    )
    period_start = (
        latest_date - timedelta(days=latest_date.weekday())
        if timeframe == "weekly"
        else date(latest_date.year, latest_date.month, 1)
    )
    return {
        "status": status,
        "latest_period_start": period_start.isoformat(),
        "latest_observation_date": latest_date.isoformat(),
        "next_trading_date": next_date.isoformat(),
    }


def _ema_sma_seed(
    values: list[float | None],
    period: int,
) -> list[float | None]:
    return ema_sma_seed(values, period)


def _wilder_rsi(
    closes: list[float | None],
    period: int,
) -> list[float | None]:
    return wilder_rsi(closes, period)


def _macd_sma_seed(
    closes: list[float | None],
    *,
    fast_period: int,
    slow_period: int,
    signal_period: int,
) -> tuple[
    list[float | None],
    list[float | None],
    list[float | None],
    list[float | None],
    list[float | None],
]:
    return macd_sma_seed(
        closes,
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period,
    )


def _recursive_kd(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    *,
    period: int,
    smooth_period: int,
) -> tuple[
    list[float | None],
    list[float | None],
    list[float | None],
    list[float | None],
]:
    return recursive_kd(
        highs,
        lows,
        closes,
        period=period,
        smooth_period=smooth_period,
    )


def _pvo(
    volumes: list[float | None],
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    return percentage_volume_oscillator(
        volumes,
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period,
    )


def _vwap(
    points: list[dict[str, Any]],
    *,
    interval: str | None = None,
) -> list[float | None]:
    """Calculate session VWAP only for intraday evidence.

    ``interval=None`` preserves the compatibility behavior for older report
    callers that do not carry an explicit Bar interval. Canonical Taiwan Bar
    callers always pass their interval and therefore cannot expose a
    request-window cumulative value as daily/weekly/monthly session VWAP.
    """

    if interval in {"1d", "1w", "1mo"}:
        return [None] * len(points)

    dates = [point_date(point.get("time")) for point in points]
    session_scoped = interval in {"1m", "5m", "15m", "30m", "1h", "4h"} or any(
        current is not None and current == previous
        for previous, current in zip(dates, dates[1:])
    )
    cumulative_price_volume = 0.0
    cumulative_volume = 0.0
    active_date: date | None = None
    output: list[float | None] = []
    for index, point in enumerate(points):
        current_date = dates[index]
        if session_scoped and active_date is not None and current_date != active_date:
            cumulative_price_volume = 0.0
            cumulative_volume = 0.0
        active_date = current_date
        high = _number(point.get("high"))
        low = _number(point.get("low"))
        close = _number(point.get("close"))
        volume = _number(point.get("volume"))
        if high is None or low is None or close is None or volume is None or volume <= 0:
            cumulative_price_volume = 0.0
            cumulative_volume = 0.0
            output.append(None)
            continue
        typical_price = (high + low + close) / 3
        cumulative_price_volume += typical_price * volume
        cumulative_volume += volume
        output.append(_round(cumulative_price_volume / cumulative_volume, 8))
    return output


def _twap(points: list[dict[str, Any]]) -> list[float | None]:
    output: list[float | None] = []
    total = 0.0
    count = 0
    for point in points:
        close = _number(point.get("close"))
        if close is None:
            output.append(None)
            continue
        total += close
        count += 1
        output.append(total / count)
    return output


def _obv(
    closes: list[float | None],
    volumes: list[float | None],
) -> list[float | None]:
    """Calculate OBV with an explicit reset after missing-volume evidence."""

    output: list[float | None] = []
    previous_close: float | None = None
    current_obv = 0.0
    for close, volume in zip(closes, volumes):
        if close is None or volume is None or volume < 0:
            previous_close = None
            current_obv = 0.0
            output.append(None)
            continue
        if previous_close is not None:
            if close > previous_close:
                current_obv += volume
            elif close < previous_close:
                current_obv -= volume
        output.append(_round(current_obv, 4))
        previous_close = close
    return output


def indicator_method_catalog(
    parameters: TechnicalAnalysisParameters,
) -> dict[str, dict[str, Any]]:
    return {
        "ma": {
            "method": "simple_moving_average",
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "parameters": {"windows": list(parameters.ma_windows)},
            "warmup_bars": max(parameters.ma_windows),
        },
        "volume_ma": {
            "method": "simple_moving_average",
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "parameters": {"windows": list(parameters.volume_ma_windows)},
            "warmup_bars": max(parameters.volume_ma_windows),
        },
        "ema_macd": {
            "method": "ema_sma_seed",
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "parameters": {
                "fast": parameters.macd_fast_period,
                "slow": parameters.macd_slow_period,
                "signal": parameters.macd_signal_period,
            },
            "warmup_bars": parameters.macd_slow_period + parameters.macd_signal_period - 1,
        },
        "rsi": {
            "method": "wilder_smoothed_gain_loss",
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "parameters": {"period": parameters.rsi_period},
            "warmup_bars": parameters.rsi_period + 1,
        },
        "atr_dmi_adx": {
            "method": "wilder_smoothed_true_range_directional_movement",
            "algorithm_version": "tw.technical.indicators.v1-compatible",
            "parameters": {
                "atr_period": parameters.atr_period,
                "adx_period": parameters.adx_period,
            },
            "warmup_bars": parameters.adx_period * 2,
        },
        "roc": {
            "method": "close_rate_of_change",
            "algorithm_version": "tw.technical.indicators.v1-compatible",
            "parameters": {"period": parameters.roc_period},
            "warmup_bars": parameters.roc_period + 1,
        },
        "mfi": {
            "method": "typical_price_raw_money_flow",
            "algorithm_version": "tw.technical.indicators.v1-compatible",
            "parameters": {"period": parameters.mfi_period},
            "warmup_bars": parameters.mfi_period + 1,
        },
        "donchian_bollinger": {
            "method": "rolling_extrema_and_population_stddev",
            "algorithm_version": "tw.technical.indicators.v1-compatible",
            "parameters": {
                "donchian_period": parameters.donchian_period,
                "bollinger_period": parameters.bollinger_period,
                "bollinger_std_dev": parameters.bollinger_std_dev,
            },
            "warmup_bars": max(parameters.donchian_period, parameters.bollinger_period),
        },
        "kd": {
            "method": "rsv_recursive_alpha_seed_50",
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "parameters": {
                "period": parameters.kd_period,
                "smooth_period": parameters.kd_smooth_period,
                "alpha": _round(1 / parameters.kd_smooth_period, 8),
                "seed": 50,
                "j_formula": "3*k-2*d",
            },
            "warmup_bars": parameters.kd_period,
        },
        "support_resistance": {
            "method": "prior_window_extrema_excluding_current_bar",
            "algorithm_version": "tw.technical.indicators.v1-compatible",
            "parameters": {"period": parameters.support_resistance_period},
            "warmup_bars": parameters.support_resistance_period + 1,
        },
        "pvo": {
            "method": "percentage_volume_oscillator_ema_sma_seed",
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "parameters": {
                "fast": parameters.pvo_fast_period,
                "slow": parameters.pvo_slow_period,
                "signal": parameters.pvo_signal_period,
            },
            "warmup_bars": parameters.pvo_slow_period + parameters.pvo_signal_period - 1,
        },
        "vwap": {
            "method": "intraday_session_reset_typical_price_volume",
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "parameters": {},
            "warmup_bars": 1,
            "applicable_intervals": ["1m", "5m", "15m", "30m", "1h", "4h"],
        },
        "obv": {
            "method": "on_balance_volume_no_missing_carry",
            "algorithm_version": INDICATOR_ALGORITHM_VERSION,
            "parameters": {},
            "warmup_bars": 2,
        },
    }


def _indicator_parameter_contract(
    parameters: TechnicalAnalysisParameters,
) -> dict[str, Any]:
    return {
        "ma_windows": list(parameters.ma_windows),
        "volume_ma_windows": list(parameters.volume_ma_windows),
        "ema_fast": parameters.macd_fast_period,
        "ema_slow": parameters.macd_slow_period,
        "macd_fast": parameters.macd_fast_period,
        "macd_slow": parameters.macd_slow_period,
        "macd_signal": parameters.macd_signal_period,
        "rsi_period": parameters.rsi_period,
        "atr_period": parameters.atr_period,
        "adx_period": parameters.adx_period,
        "roc_period": parameters.roc_period,
        "mfi_period": parameters.mfi_period,
        "donchian_period": parameters.donchian_period,
        "bollinger_period": parameters.bollinger_period,
        "bollinger_std_dev": parameters.bollinger_std_dev,
        "kd_period": parameters.kd_period,
        "kd_smooth_period": parameters.kd_smooth_period,
        "support_resistance_period": parameters.support_resistance_period,
    }


def calculate_canonical_indicator_points(
    points: list[dict[str, Any]],
    *,
    parameters: TechnicalAnalysisParameters | None = None,
    interval: str | None = None,
) -> list[dict[str, Any]]:
    resolved = parameters or get_technical_analysis_parameters()
    base_points = indicator_service.calculate_indicator_points_from_ohlc_points(
        points,
        max_gap_days=None,
        parameters=resolved,
    )
    closes = [_number(point.get("close")) for point in points]
    highs = [_number(point.get("high")) for point in points]
    lows = [_number(point.get("low")) for point in points]
    volumes = [_number(point.get("volume")) for point in points]
    fast, slow, macd, signal, histogram = _macd_sma_seed(
        closes,
        fast_period=resolved.macd_fast_period,
        slow_period=resolved.macd_slow_period,
        signal_period=resolved.macd_signal_period,
    )
    rsi = _wilder_rsi(closes, resolved.rsi_period)
    rsv, kd_k, kd_d, kd_j = _recursive_kd(
        highs,
        lows,
        closes,
        period=resolved.kd_period,
        smooth_period=resolved.kd_smooth_period,
    )
    pvo, pvo_signal, pvo_histogram = _pvo(
        volumes,
        fast_period=resolved.pvo_fast_period,
        slow_period=resolved.pvo_slow_period,
        signal_period=resolved.pvo_signal_period,
    )
    vwap = _vwap(points, interval=interval)
    twap = _twap(points)
    obv = _obv(closes, volumes)
    output: list[dict[str, Any]] = []
    parameter_contract = _indicator_parameter_contract(resolved)
    for index, base_point in enumerate(base_points):
        output.append(
            {
                **base_point,
                "algorithm_version": INDICATOR_ALGORITHM_VERSION,
                "price_basis": PRICE_BASIS,
                "calculation_role": "backend_authoritative",
                "parameter_contract": parameter_contract,
                "ema": {
                    f"ema{resolved.macd_fast_period}": fast[index],
                    f"ema{resolved.macd_slow_period}": slow[index],
                },
                "macd": {
                    "macd": macd[index],
                    "signal": signal[index],
                    "histogram": histogram[index],
                },
                "rsi": {f"rsi{resolved.rsi_period}": rsi[index]},
                "kd": {
                    "rsv": rsv[index],
                    f"k{resolved.kd_period}": kd_k[index],
                    f"d{resolved.kd_period}": kd_d[index],
                    f"j{resolved.kd_period}": kd_j[index],
                },
                "pvo": {
                    "pvo": pvo[index],
                    "signal": pvo_signal[index],
                    "histogram": pvo_histogram[index],
                },
                "vwap": vwap[index],
                "twap": twap[index],
                "obv": obv[index],
            }
        )
    return output


def _warmup_status(
    snapshot: Mapping[str, Any] | None,
    *,
    available_bars: int,
    method_catalog: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    snapshot = snapshot or {}
    status: dict[str, Any] = {}
    for key, method in method_catalog.items():
        required = int(method.get("warmup_bars") or 1)
        value = snapshot.get(key)
        if key == "ema_macd":
            value = snapshot.get("macd")
        elif key == "atr_dmi_adx":
            value = snapshot.get("adx")
        elif key == "donchian_bollinger":
            value = snapshot.get("bollinger")
        status[key] = {
            "status": "ready" if available_bars >= required and value not in (None, {}) else "warming_up",
            "required_bars": required,
            "available_bars": available_bars,
        }
    return status


def _snapshot_for_timeframe(
    points: list[dict[str, Any]],
    *,
    timeframe: str,
    parameters: TechnicalAnalysisParameters,
    method_catalog: dict[str, dict[str, Any]],
    latest_observation_date: date | None = None,
    current_partial_point: Mapping[str, Any] | None = None,
    volume_unit: str = "shares",
    calculated_points: list[dict[str, Any]] | None = None,
    current_partial_calculated: dict[str, Any] | None = None,
    allow_internal_calculation: bool = True,
) -> dict[str, Any]:
    period = classify_latest_period(
        points,
        timeframe=timeframe,
        latest_observation_date=latest_observation_date,
    )
    calculated = (
        calculate_canonical_indicator_points(points, parameters=parameters)
        if allow_internal_calculation
        else list(calculated_points or [])
    )
    latest = calculated[-1] if calculated else None
    completed = latest
    partial = None
    completed_bars = len(calculated)
    if timeframe == "daily" and current_partial_point is not None:
        if allow_internal_calculation:
            projected = calculate_canonical_indicator_points(
                [*points, dict(current_partial_point)],
                parameters=parameters,
            )
            partial = projected[-1] if projected else None
        else:
            partial = current_partial_calculated
        if partial is not None:
            partial = {
                **partial,
                "open": current_partial_point.get("open"),
                "high": current_partial_point.get("high"),
                "low": current_partial_point.get("low"),
                "bar_status": current_partial_point.get("bar_status") or "intraday_partial",
                "session_close_finalization": current_partial_point.get(
                    "session_close_finalization"
                ),
                "official_daily_confirmed": current_partial_point.get(
                    "official_daily_confirmed",
                    False,
                ),
                "event_time": current_partial_point.get("event_time"),
                "source": current_partial_point.get("source"),
                "volume_semantics": current_partial_point.get("volume_semantics"),
                "volume_unit": volume_unit,
                "price_unit": "TWD",
                "currency": "TWD",
                "source_capability": "daily.ohlcv",
                "indicator_semantics": {
                    "price_based": "intraday_partial",
                    "range_based": "intraday_partial",
                    "volume_based": "partial_cumulative_volume",
                },
                "decision_usable": False,
                "volume_based_decision_usable": False,
                "warnings": [
                    "Volume-based values use current cumulative session volume and are not finalized daily indicators."
                ],
            }
        period = {
            "status": current_partial_point.get("bar_status") or "intraday_partial",
            "latest_period_start": _json_date(current_partial_point.get("time")),
            "latest_observation_date": _json_date(current_partial_point.get("time")),
            "next_trading_date": period.get("next_trading_date"),
        }
    elif period["status"] == "current_partial" and calculated:
        partial = latest
        completed = calculated[-2] if len(calculated) > 1 else None
        completed_bars = max(0, len(calculated) - 1)
        if partial is not None:
            partial = {**partial, "bar_status": "current_period_partial"}
    if completed is not None:
        completed = {
            **completed,
            "bar_status": "completed",
            "volume_unit": volume_unit,
            "price_unit": "TWD",
            "currency": "TWD",
            "source_capability": "daily.ohlcv",
        }
    if partial is not None:
        partial = {
            **partial,
            "volume_unit": volume_unit,
            "price_unit": "TWD",
            "currency": "TWD",
            "source_capability": "daily.ohlcv",
        }
    return {
        "timeframe": timeframe,
        "period": period,
        "completed": completed,
        "current_partial": partial,
        "decision_snapshot": "completed",
        "available_bars": len(calculated) + (1 if current_partial_point is not None else 0),
        "completed_bars": completed_bars,
        "warmup": _warmup_status(
            completed,
            available_bars=completed_bars,
            method_catalog=method_catalog,
        ),
    }


def build_corporate_action_contract(
    history: Mapping[str, Any] | None,
    *,
    analysis_start: date | None,
    analysis_end: date | None,
) -> dict[str, Any]:
    history = history or {}
    cache_status = str(history.get("cache_status") or "missing")
    coverage_start = point_date(history.get("coverage_start"))
    coverage_end = point_date(history.get("coverage_end"))
    actions: list[dict[str, Any]] = []
    affected_dates: set[date] = set()
    for event in history.get("results") or []:
        if not isinstance(event, Mapping) or str(event.get("event_type") or "") != "ex_dividend":
            continue
        event_date = point_date(event.get("start_date"))
        if event_date is None:
            continue
        if analysis_start and event_date < analysis_start:
            continue
        if analysis_end and event_date > analysis_end:
            continue
        affected_dates.add(event_date)
        actions.append(
            {
                "event_id": event.get("event_id"),
                "effective_date": event_date.isoformat(),
                "cash_dividend": event.get("cash_dividend"),
                "stock_dividend_ratio": event.get("stock_dividend_ratio"),
                "source": event.get("source_name") or event.get("source"),
            }
        )
    coverage_status = (
        "missing"
        if cache_status == "missing"
        else "complete"
        if cache_status == "current"
        and analysis_start is not None
        and analysis_end is not None
        and coverage_start is not None
        and coverage_end is not None
        and coverage_start <= analysis_start
        and coverage_end >= analysis_end
        else "partial"
    )
    warnings = []
    if coverage_status != "complete":
        warnings.append(
            "Corporate-action coverage is incomplete; calculations use raw unadjusted prices and affected-window signals are downgraded."
        )
    if actions:
        warnings.append(
            "Known ex-dividend events occur inside the analysis window; affected pivots and breakout evidence are excluded or suppressed."
        )
    source_names = sorted(
        {
            str(value).strip()
            for value in [
                *(history.get("sources") or []),
                *(action.get("source") for action in actions),
            ]
            if str(value or "").strip()
        }
    )
    absence_semantics = (
        "matching_events_observed"
        if actions
        else "none_observed_in_complete_checked_range"
        if coverage_status == "complete"
        else "unknown_outside_checked_range"
    )
    return {
        "price_basis": PRICE_BASIS,
        "adjustment_applied": False,
        "adjustment_method": "none",
        "coverage_status": coverage_status,
        "cache_status": cache_status,
        "coverage_start": _json_date(coverage_start),
        "coverage_end": _json_date(coverage_end),
        "checked_through_date": _json_date(coverage_end),
        "source_scope": {
            "providers": source_names,
            "coverage_start": _json_date(coverage_start),
            "coverage_end": _json_date(coverage_end),
            "cache_status": cache_status,
        },
        "absence_semantics": absence_semantics,
        "relevant_analysis_start": _json_date(analysis_start),
        "relevant_analysis_end": _json_date(analysis_end),
        "affected_events": actions,
        "affected_dates": sorted(value.isoformat() for value in affected_dates),
        "warnings": warnings,
    }


def _corporate_contract_for_points(
    history: Mapping[str, Any] | None,
    points: list[dict[str, Any]],
    *,
    lookback_bars: int | None = None,
) -> dict[str, Any]:
    selected = points[-lookback_bars:] if lookback_bars is not None else points
    return build_corporate_action_contract(
        history,
        analysis_start=(point_date(selected[0].get("time")) if selected else None),
        analysis_end=(point_date(selected[-1].get("time")) if selected else None),
    )


def _corporate_summary(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: contract.get(key)
        for key in (
            "price_basis",
            "adjustment_applied",
            "adjustment_method",
            "coverage_status",
            "coverage_start",
            "coverage_end",
            "checked_through_date",
            "source_scope",
            "absence_semantics",
            "relevant_analysis_start",
            "relevant_analysis_end",
            "affected_dates",
        )
    }


def _apply_capability_corporate_contract(
    payload: dict[str, Any],
    *,
    contract: Mapping[str, Any],
    source_refs: list[dict[str, str]],
) -> None:
    payload["corporate_action"] = _corporate_summary(contract)
    payload["source_refs"] = source_refs
    payload["warnings"] = list(
        dict.fromkeys(
            [
                *list(payload.get("warnings") or []),
                *list(contract.get("warnings") or []),
            ]
        )
    )
    if (
        contract.get("coverage_status") != "complete"
        and payload.get("status") not in {"missing", "unavailable"}
    ):
        payload["status"] = "partial"
        payload["decision_usable"] = False


def _atr_values(points: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    highs = [_number(point.get("high")) for point in points]
    lows = [_number(point.get("low")) for point in points]
    closes = [_number(point.get("close")) for point in points]
    return indicator_service._atr_series(highs, lows, closes, period)


def build_swing_evidence(
    points: list[dict[str, Any]],
    *,
    affected_dates: Iterable[str] = (),
    left_bars: int = 2,
    right_bars: int = 2,
    atr_multiplier: float = 0.5,
) -> dict[str, Any]:
    dates = [point_date(point.get("time")) for point in points]
    highs = [_number(point.get("high")) for point in points]
    lows = [_number(point.get("low")) for point in points]
    atr = _atr_values(points)
    blocked_dates = {
        item + timedelta(days=offset)
        for raw in affected_dates
        if (item := point_date(raw)) is not None
        for offset in (-1, 0, 1)
    }
    pivots: list[dict[str, Any]] = []
    for index in range(left_bars, len(points) - right_bars):
        current_date = dates[index]
        if current_date is None or current_date in blocked_dates:
            continue
        high = highs[index]
        low = lows[index]
        window_highs = highs[index - left_bars : index + right_bars + 1]
        window_lows = lows[index - left_bars : index + right_bars + 1]
        if any(value is None for value in window_highs + window_lows):
            continue
        candidates: list[tuple[str, float, float]] = []
        if high is not None and high == max(value for value in window_highs if value is not None):
            neighbor_floor = min(
                value for value in window_lows if value is not None
            )
            candidates.append(("high", high, high - neighbor_floor))
        if low is not None and low == min(value for value in window_lows if value is not None):
            neighbor_ceiling = max(
                value for value in window_highs if value is not None
            )
            candidates.append(("low", low, neighbor_ceiling - low))
        for pivot_type, price, prominence in candidates:
            atr_value = atr[index]
            if atr_value is not None and prominence < atr_value * atr_multiplier:
                continue
            confirmed_index = index + right_bars
            confirmed_at = dates[confirmed_index]
            evidence_id = f"swing:{pivot_type}:{current_date.isoformat()}:{price:.4f}"
            pivots.append(
                {
                    "evidence_id": evidence_id,
                    "type": pivot_type,
                    "price": _round(price),
                    "pivot_time": current_date.isoformat(),
                    "confirmed_at": _json_date(confirmed_at),
                    "pivot_index": index,
                    "confirmed_index": confirmed_index,
                    "left_bars": left_bars,
                    "right_bars": right_bars,
                    "prominence": _round(prominence),
                    "prominence_atr": _round(prominence / atr_value) if atr_value not in {None, 0} else None,
                    "status": "confirmed",
                    "price_basis": PRICE_BASIS,
                }
            )
    provisional: list[dict[str, Any]] = []
    for index in range(max(left_bars, len(points) - right_bars), len(points)):
        current_date = dates[index]
        if current_date is None or current_date in blocked_dates:
            continue
        start = max(0, index - left_bars)
        high = highs[index]
        low = lows[index]
        previous_highs = [item for item in highs[start:index] if item is not None]
        previous_lows = [item for item in lows[start:index] if item is not None]
        pivot_type = (
            "high"
            if high is not None and previous_highs and high >= max(previous_highs)
            else "low"
            if low is not None and previous_lows and low <= min(previous_lows)
            else None
        )
        price = high if pivot_type == "high" else low
        if pivot_type and price is not None:
            provisional.append(
                {
                    "evidence_id": f"swing:{pivot_type}:{current_date.isoformat()}:{price:.4f}:provisional",
                    "type": pivot_type,
                    "price": _round(price),
                    "pivot_time": current_date.isoformat(),
                    "confirmed_at": None,
                    "pivot_index": index,
                    "left_bars": left_bars,
                    "right_bars": right_bars,
                    "status": "provisional",
                    "price_basis": PRICE_BASIS,
                }
            )
    return {
        "kind": "tw_technical_swings",
        "algorithm_version": ADVANCED_ALGORITHM_VERSION,
        "method": "local_extrema_fractal_with_atr_prominence",
        "parameters": {
            "left_bars": left_bars,
            "right_bars": right_bars,
            "atr_multiplier": atr_multiplier,
        },
        "status": "ready" if pivots else "partial",
        "price_basis": PRICE_BASIS,
        "pivots": pivots[-16:],
        "provisional": provisional[-4:],
        "confirmed_count": len(pivots),
        "limitations": [
            "A pivot becomes confirmed only after right_bars later observations; provisional pivots are never treated as confirmed signals."
        ],
    }


def _last_opposite_pivot_pair(
    pivots: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for right_index in range(len(pivots) - 1, 0, -1):
        right = pivots[right_index]
        for left_index in range(right_index - 1, -1, -1):
            left = pivots[left_index]
            if left.get("type") != right.get("type"):
                return left, right
    return None


def build_fibonacci_evidence(swings: Mapping[str, Any]) -> dict[str, Any]:
    pivots = [
        item
        for item in swings.get("pivots") or []
        if isinstance(item, Mapping) and item.get("status") == "confirmed"
    ]
    pair = _last_opposite_pivot_pair(pivots)
    if pair is None:
        return {
            "kind": "tw_technical_fibonacci",
            "algorithm_version": ADVANCED_ALGORITHM_VERSION,
            "status": "missing",
            "levels": [],
            "missing": ["technical.swings.confirmed_anchor_pair"],
        }
    start, end = pair
    start_price = _number(start.get("price"))
    end_price = _number(end.get("price"))
    if start_price is None or end_price is None or start_price == end_price:
        return {
            "kind": "tw_technical_fibonacci",
            "algorithm_version": ADVANCED_ALGORITHM_VERSION,
            "status": "missing",
            "levels": [],
            "missing": ["technical.swings.nonzero_anchor_range"],
        }
    direction = "up" if start.get("type") == "low" and end.get("type") == "high" else "down"
    distance = abs(end_price - start_price)
    levels: list[dict[str, Any]] = []
    for ratio in (0.236, 0.382, 0.5, 0.618, 0.786):
        price = end_price - distance * ratio if direction == "up" else end_price + distance * ratio
        levels.append(
            {
                "kind": "retracement",
                "ratio": ratio,
                "price": _round(price),
                "price_basis": PRICE_BASIS,
            }
        )
    for ratio in (1.272, 1.618):
        price = end_price + distance * (ratio - 1) if direction == "up" else end_price - distance * (ratio - 1)
        levels.append(
            {
                "kind": "extension",
                "ratio": ratio,
                "price": _round(price),
                "price_basis": PRICE_BASIS,
            }
        )
    return {
        "kind": "tw_technical_fibonacci",
        "algorithm_version": ADVANCED_ALGORITHM_VERSION,
        "method": "confirmed_swing_anchor_retracement_extension",
        "status": "ready",
        "direction": direction,
        "anchor_ids": [start.get("evidence_id"), end.get("evidence_id")],
        "anchor_start_id": start.get("evidence_id"),
        "anchor_end_id": end.get("evidence_id"),
        "anchor_start": start,
        "anchor_end": end,
        "price_basis": PRICE_BASIS,
        "levels": levels,
        "confluence_method": "exact_level_only_v1",
    }


def build_divergence_evidence(
    swings: Mapping[str, Any],
    canonical_points: list[dict[str, Any]],
    *,
    parameters: TechnicalAnalysisParameters,
) -> dict[str, Any]:
    rsi_by_index = {
        index: _number((point.get("rsi") or {}).get(parameters.rsi_key))
        for index, point in enumerate(canonical_points)
    }
    divergences: list[dict[str, Any]] = []
    pivots = [item for item in swings.get("pivots") or [] if isinstance(item, Mapping)]
    for pivot_type, direction in (("low", "bullish"), ("high", "bearish")):
        selected = [item for item in pivots if item.get("type") == pivot_type]
        if len(selected) < 2:
            continue
        previous, current = selected[-2], selected[-1]
        previous_price = _number(previous.get("price"))
        current_price = _number(current.get("price"))
        previous_rsi = rsi_by_index.get(int(previous.get("pivot_index") or 0))
        current_rsi = rsi_by_index.get(int(current.get("pivot_index") or 0))
        matches = (
            direction == "bullish"
            and previous_price is not None
            and current_price is not None
            and current_price < previous_price
            and previous_rsi is not None
            and current_rsi is not None
            and current_rsi > previous_rsi
        ) or (
            direction == "bearish"
            and previous_price is not None
            and current_price is not None
            and current_price > previous_price
            and previous_rsi is not None
            and current_rsi is not None
            and current_rsi < previous_rsi
        )
        if matches:
            divergences.append(
                {
                    "type": f"regular_{direction}",
                    "direction": direction,
                    "first_pivot_id": previous.get("evidence_id"),
                    "second_pivot_id": current.get("evidence_id"),
                    "price_change_pct": _round((current_price - previous_price) / previous_price * 100),
                    "indicator": parameters.rsi_key,
                    "indicator_change": _round(current_rsi - previous_rsi),
                    "bars_apart": int(current.get("pivot_index") or 0) - int(previous.get("pivot_index") or 0),
                    "status": "confirmed",
                }
            )
    return {
        "kind": "tw_technical_divergence",
        "algorithm_version": ADVANCED_ALGORITHM_VERSION,
        "method": "confirmed_price_pivots_aligned_to_wilder_rsi",
        "status": "ready" if divergences else "ready_empty",
        "divergences": divergences,
        "hidden_divergence_enabled": False,
        "limitations": ["Only regular RSI divergence on confirmed price pivots is enabled in v1."],
    }


def build_breakout_evidence(
    points: list[dict[str, Any]],
    canonical_points: list[dict[str, Any]],
    *,
    corporate_action_contract: Mapping[str, Any],
    level: float | None = None,
    parameters: TechnicalAnalysisParameters | None = None,
) -> dict[str, Any]:
    resolved = parameters or get_technical_analysis_parameters()
    if len(points) < 2 or not canonical_points:
        return {
            "kind": "tw_technical_breakout",
            "algorithm_version": ADVANCED_ALGORITHM_VERSION,
            "status": "missing",
            "state": "unavailable",
        }
    current_index = len(points) - 1
    current = points[current_index]

    def level_for_index(index: int) -> float | None:
        explicit = _number(level)
        if explicit is not None:
            return explicit
        indicator = canonical_points[index] if index < len(canonical_points) else {}
        configured = _number(
            (indicator.get("support_resistance") or {}).get(resolved.resistance_key)
        )
        if configured is not None:
            return configured
        start = max(0, index - resolved.support_resistance_period)
        prior_highs = [_number(point.get("high")) for point in points[start:index]]
        valid_highs = [value for value in prior_highs if value is not None]
        if len(valid_highs) < min(resolved.support_resistance_period, index):
            return None
        return max(valid_highs) if valid_highs else None

    def confirmation_for_index(index: int, breakout_level: float) -> dict[str, Any] | None:
        point = points[index]
        indicator = canonical_points[index] if index < len(canonical_points) else {}
        candidate_close = _number(point.get("close"))
        if candidate_close is None or candidate_close <= breakout_level:
            return None
        previous_close = _number(points[index - 1].get("close")) if index > 0 else None
        if previous_close is not None and previous_close > breakout_level:
            return None
        candidate_volume = _number(point.get("volume"))
        candidate_volume_ma = _number(
            (indicator.get("volume_ma") or {}).get(resolved.volume_ma_medium_key)
        )
        candidate_ratio = (
            candidate_volume / candidate_volume_ma
            if candidate_volume is not None and candidate_volume_ma not in {None, 0}
            else None
        )
        candidate_pvo = _number((indicator.get("pvo") or {}).get("pvo"))
        confirmed = bool(
            (candidate_ratio or 0) >= resolved.breakout_volume_ratio_threshold
            and (candidate_pvo or 0) > 0
        )
        event_date = _json_date(point.get("time"))
        return {
            "breakout_event_id": f"breakout:{event_date}:{_round(breakout_level)}",
            "breakout_level": breakout_level,
            "breakout_confirmed_at": event_date,
            "breakout_index": index,
            "confirmation_state": "confirmed" if confirmed else "weak_confirmation",
            "volume_ratio": candidate_ratio,
            "pvo": candidate_pvo,
        }

    events: list[dict[str, Any]] = []
    event_scan_start = max(
        1,
        len(points) - resolved.support_resistance_period - BREAKOUT_LIFECYCLE_BARS,
    )
    for index in range(event_scan_start, len(points)):
        candidate_level = level_for_index(index)
        if candidate_level is None:
            continue
        event = confirmation_for_index(index, candidate_level)
        if event is not None:
            events.append(event)

    current_event = next(
        (event for event in reversed(events) if event["breakout_index"] == current_index),
        None,
    )
    prior_event = next(
        (event for event in reversed(events) if event["breakout_index"] < current_index),
        None,
    )
    active_event = current_event or prior_event
    resistance = (
        _number(active_event.get("breakout_level"))
        if active_event is not None
        else level_for_index(current_index)
    )
    high = _number(current.get("high"))
    low = _number(current.get("low"))
    close = _number(current.get("close"))
    volume = _number(current.get("volume"))
    current_indicator = canonical_points[-1]
    volume_ma = _number(
        (current_indicator.get("volume_ma") or {}).get(resolved.volume_ma_medium_key)
    )
    volume_ratio = volume / volume_ma if volume is not None and volume_ma not in {None, 0} else None
    pvo = _number((current_indicator.get("pvo") or {}).get("pvo"))
    previously_confirmed = prior_event is not None
    state = "inside_range"
    quality = "neutral"
    if resistance is not None and close is not None:
        if current_event is not None:
            state = str(current_event["confirmation_state"])
            quality = "positive" if state == "confirmed" else "warning"
        elif prior_event is not None and close < resistance:
            state = "failed"
            quality = "negative"
        elif prior_event is not None and low is not None and low <= resistance <= close:
            state = "retest_held"
            quality = "positive"
        elif prior_event is not None and close > resistance:
            state = "continuation"
            quality = "positive"
        else:
            candidate_level = level_for_index(current_index)
            if high is not None and candidate_level is not None and high > candidate_level >= close:
                state = "rejected_attempt"
                quality = "negative"
    affected_dates = set(corporate_action_contract.get("affected_dates") or [])
    corporate_coverage = str(
        corporate_action_contract.get("coverage_status") or "missing"
    )
    current_date = _json_date(current.get("time"))
    event_date = (
        str(active_event.get("breakout_confirmed_at"))
        if active_event is not None
        else None
    )
    suppressed = bool(current_date in affected_dates or event_date in affected_dates)
    if suppressed:
        state = "suppressed_corporate_action_window"
        quality = "unavailable"
    return {
        "kind": "tw_technical_breakout",
        "algorithm_version": ADVANCED_ALGORITHM_VERSION,
        "method": "completed_bar_close_level_volume_pvo_state_machine",
        "status": (
            "partial"
            if suppressed or resistance is None or corporate_coverage != "complete"
            else "ready"
        ),
        "state": state,
        "quality": quality,
        "level": _round(resistance),
        "breakout_event_id": (
            active_event.get("breakout_event_id") if active_event is not None else None
        ),
        "breakout_level": _round(resistance),
        "breakout_confirmed_at": event_date,
        "last_evaluated_at": current_date,
        "confirmation_state": (
            active_event.get("confirmation_state") if active_event is not None else None
        ),
        "level_evidence": (
            "explicit_level" if level is not None else "prior_configured_window_resistance_excluding_candidate_bar"
        ),
        "parameters": {
            "lookback_bars": resolved.support_resistance_period,
            "volume_ratio_threshold": resolved.breakout_volume_ratio_threshold,
            "pvo_threshold": 0,
        },
        "bar_time": current_date,
        "high": _round(high),
        "low": _round(low),
        "close": _round(close),
        "close_distance_pct": _round((close - resistance) / resistance * 100) if close is not None and resistance not in {None, 0} else None,
        "wick_rejected": bool(high is not None and close is not None and resistance is not None and high > resistance >= close),
        "volume_ratio": _round(volume_ratio),
        "pvo": _round(pvo),
        "previously_confirmed": previously_confirmed,
        "bar_status": "completed",
        "price_basis": PRICE_BASIS,
        "decision_usable": (
            not suppressed
            and resistance is not None
            and corporate_coverage == "complete"
        ),
        "corporate_action_coverage_status": corporate_coverage,
    }


def build_volume_profile(
    points: list[dict[str, Any]],
    *,
    bins: int = 24,
    value_area_pct: float = 0.70,
) -> dict[str, Any]:
    selected = points[-PROFILE_LOOKBACK:]
    rows: list[tuple[float, float]] = []
    for point in selected:
        high = _number(point.get("high"))
        low = _number(point.get("low"))
        close = _number(point.get("close"))
        volume = _number(point.get("volume"))
        if high is None or low is None or close is None or volume is None or volume <= 0:
            continue
        rows.append(((high + low + close) / 3, volume))
    if not rows:
        return {
            "kind": "tw_technical_volume_profile",
            "algorithm_version": ADVANCED_ALGORITHM_VERSION,
            "status": "missing",
            "bins": [],
        }
    minimum = min(price for price, _ in rows)
    maximum = max(price for price, _ in rows)
    width = (maximum - minimum) / bins if maximum > minimum else 1.0
    volumes = [0.0] * bins
    for price, volume in rows:
        index = min(bins - 1, max(0, int((price - minimum) / width)))
        volumes[index] += volume
    total = sum(volumes)
    poc_index = max(range(bins), key=lambda index: (volumes[index], -index))
    included = {poc_index}
    accumulated = volumes[poc_index]
    left = poc_index - 1
    right = poc_index + 1
    while accumulated < total * value_area_pct and (left >= 0 or right < bins):
        left_volume = volumes[left] if left >= 0 else -1
        right_volume = volumes[right] if right < bins else -1
        if right_volume > left_volume:
            included.add(right)
            accumulated += max(0, right_volume)
            right += 1
        else:
            included.add(left)
            accumulated += max(0, left_volume)
            left -= 1
    bin_rows = [
        {
            "index": index,
            "low": _round(minimum + width * index),
            "high": _round(minimum + width * (index + 1)),
            "mid": _round(minimum + width * (index + 0.5)),
            "volume": _round(volume, 2),
            "volume_pct": _round(volume / total * 100) if total else None,
            "in_value_area": index in included,
        }
        for index, volume in enumerate(volumes)
    ]
    return {
        "kind": "tw_technical_volume_profile",
        "algorithm_version": ADVANCED_ALGORITHM_VERSION,
        "status": "partial",
        "method": "daily_bar_typical_price_single_bin_allocation",
        "source_granularity": "daily_ohlcv",
        "confidence": "low",
        "price_basis": PRICE_BASIS,
        "lookback_bars": len(selected),
        "source_row_count": len(rows),
        "poc": bin_rows[poc_index]["mid"],
        "val": bin_rows[min(included)]["low"],
        "vah": bin_rows[max(included)]["high"],
        "value_area_pct": value_area_pct,
        "bins": bin_rows,
        "high_volume_nodes": sorted(bin_rows, key=lambda item: (-float(item["volume"] or 0), item["index"]))[:3],
        "limitations": [
            "Daily bars do not expose trade-by-price or aggressor-side volume; this profile is a low-confidence approximation."
        ],
    }


def build_anchored_vwap(
    points: list[dict[str, Any]],
    swings: Mapping[str, Any],
) -> dict[str, Any]:
    pivots = [item for item in swings.get("pivots") or [] if isinstance(item, Mapping)]
    if not pivots:
        return {
            "kind": "tw_technical_anchored_vwap",
            "algorithm_version": ADVANCED_ALGORITHM_VERSION,
            "status": "missing",
            "missing": ["technical.swings.confirmed_anchor"],
        }
    anchor = pivots[-1]
    anchor_index = int(anchor.get("pivot_index") or 0)
    numerator = 0.0
    denominator = 0.0
    used = 0
    for point in points[anchor_index:]:
        high = _number(point.get("high"))
        low = _number(point.get("low"))
        close = _number(point.get("close"))
        volume = _number(point.get("volume"))
        if high is None or low is None or close is None or volume is None or volume <= 0:
            continue
        typical = (high + low + close) / 3
        numerator += typical * volume
        denominator += volume
        used += 1
    return {
        "kind": "tw_technical_anchored_vwap",
        "algorithm_version": ADVANCED_ALGORITHM_VERSION,
        "status": "ready" if denominator > 0 else "missing",
        "method": "daily_typical_price_volume_weighted_from_confirmed_swing",
        "source_granularity": "daily_ohlcv",
        "confidence": "medium" if used >= 5 else "low",
        "anchor_evidence_id": anchor.get("evidence_id"),
        "anchor_time": anchor.get("pivot_time"),
        "anchor_price": anchor.get("price"),
        "value": _round(numerator / denominator) if denominator > 0 else None,
        "cumulative_volume": _round(denominator, 2) if denominator > 0 else None,
        "used_bars": used,
        "price_basis": PRICE_BASIS,
        "limitations": ["Daily-bar typical price is used; this is not an official intraday VWAP."],
    }


def build_relative_strength(
    stock_points: list[dict[str, Any]],
    benchmark_points: list[dict[str, Any]],
) -> dict[str, Any]:
    stock_by_date = {
        parsed: _number(point.get("close"))
        for point in stock_points
        if (parsed := point_date(point.get("time"))) is not None
    }
    benchmark_by_date = {
        parsed: _number(point.get("close"))
        for point in benchmark_points
        if (parsed := point_date(point.get("time"))) is not None
    }
    stock_dates = sorted(value for value, close in stock_by_date.items() if close is not None)
    benchmark_dates = sorted(
        value for value, close in benchmark_by_date.items() if close is not None
    )
    aligned_dates = sorted(
        value
        for value in set(stock_by_date) & set(benchmark_by_date)
        if stock_by_date[value] is not None and benchmark_by_date[value] is not None
    )
    horizons: dict[str, Any] = {}
    for bars in (5, 20, 60):
        if len(aligned_dates) <= bars:
            horizons[f"{bars}d"] = {
                "stock_return_pct": None,
                "benchmark_return_pct": None,
                "excess_return_pct": None,
                "status": "warming_up",
            }
            continue
        end_date = aligned_dates[-1]
        start_date = aligned_dates[-bars - 1]
        stock_start = stock_by_date[start_date]
        stock_end = stock_by_date[end_date]
        benchmark_start = benchmark_by_date[start_date]
        benchmark_end = benchmark_by_date[end_date]
        stock_return = (stock_end / stock_start - 1) * 100 if stock_start not in {None, 0} and stock_end is not None else None
        benchmark_return = (benchmark_end / benchmark_start - 1) * 100 if benchmark_start not in {None, 0} and benchmark_end is not None else None
        excess = stock_return - benchmark_return if stock_return is not None and benchmark_return is not None else None
        horizons[f"{bars}d"] = {
            "from_date": start_date.isoformat(),
            "to_date": end_date.isoformat(),
            "stock_return_pct": _round(stock_return),
            "benchmark_return_pct": _round(benchmark_return),
            "excess_return_pct": _round(excess),
            "status": "ready" if excess is not None else "missing",
        }
    stock_latest = stock_dates[-1] if stock_dates else None
    benchmark_latest = benchmark_dates[-1] if benchmark_dates else None
    aligned_latest = aligned_dates[-1] if aligned_dates else None
    coverage_aligned = bool(
        stock_latest is not None
        and benchmark_latest is not None
        and stock_latest == benchmark_latest == aligned_latest
    )
    return {
        "kind": "tw_technical_relative_strength",
        "algorithm_version": ADVANCED_ALGORITHM_VERSION,
        "status": "ready" if len(aligned_dates) > 60 and coverage_aligned else "partial",
        "method": "aligned_trading_date_total_price_return_difference",
        "benchmark": "TAIEX",
        "aligned_trade_date_count": len(aligned_dates),
        "as_of": _json_date(aligned_latest),
        "stock_latest_date": _json_date(stock_latest),
        "benchmark_latest_date": _json_date(benchmark_latest),
        "horizons": horizons,
        "sector": {
            "status": "not_available",
            "reason": "Canonical sector benchmark mapping is not connected in v1.",
        },
        "price_basis": PRICE_BASIS,
        "freshness": {
            "status": "current" if coverage_aligned else "partial",
            "latest_data_date": _json_date(aligned_latest),
            "stock_latest_date": _json_date(stock_latest),
            "benchmark_latest_date": _json_date(benchmark_latest),
        },
        "limitations": ["This is price relative strength, not RSI and not total return adjusted for distributions."],
    }


def build_technical_structure_v2(
    *,
    indicators: Mapping[str, Any],
    swings: Mapping[str, Any],
    fibonacci: Mapping[str, Any],
    divergence: Mapping[str, Any],
    breakout: Mapping[str, Any],
    volume_profile: Mapping[str, Any],
    anchored_vwap: Mapping[str, Any],
    relative_strength: Mapping[str, Any],
    parameters: TechnicalAnalysisParameters,
) -> dict[str, Any]:
    timeframes = (
        indicators.get("timeframes")
        if isinstance(indicators.get("timeframes"), Mapping)
        else {}
    )
    daily = (
        timeframes.get("daily")
        if isinstance(timeframes.get("daily"), Mapping)
        else {}
    )
    completed = (
        daily.get("completed")
        if isinstance(daily.get("completed"), Mapping)
        else {}
    )
    close = _number(completed.get("close"))
    rsi_values = completed.get("rsi") if isinstance(completed.get("rsi"), Mapping) else {}
    rsi = next(
        (_number(value) for key, value in rsi_values.items() if str(key).startswith("rsi")),
        None,
    )
    macd_histogram = _number(
        (completed.get("macd") or {}).get("histogram")
        if isinstance(completed.get("macd"), Mapping)
        else None
    )
    pvo_value = _number(
        (completed.get("pvo") or {}).get("pvo")
        if isinstance(completed.get("pvo"), Mapping)
        else None
    )
    atr_values = completed.get("atr") if isinstance(completed.get("atr"), Mapping) else {}
    atr = next(
        (_number(value) for key, value in atr_values.items() if str(key).startswith("atr")),
        None,
    )
    bollinger = (
        completed.get("bollinger")
        if isinstance(completed.get("bollinger"), Mapping)
        else {}
    )
    support_resistance = (
        completed.get("support_resistance")
        if isinstance(completed.get("support_resistance"), Mapping)
        else {}
    )
    support = next(
        (
            _number(value)
            for key, value in support_resistance.items()
            if str(key).startswith("support")
        ),
        None,
    )
    resistance = next(
        (
            _number(value)
            for key, value in support_resistance.items()
            if str(key).startswith("resistance")
        ),
        None,
    )
    fib_levels = [
        item
        for item in fibonacci.get("levels") or []
        if isinstance(item, Mapping) and _number(item.get("price")) is not None
    ]
    nearest_fib = (
        min(
            fib_levels,
            key=lambda item: (
                abs((_number(item.get("price")) or 0) - close),
                float(item.get("ratio") or 0),
            ),
        )
        if close is not None and fib_levels
        else None
    )
    avwap = _number(anchored_vwap.get("value"))
    poc = _number(volume_profile.get("poc"))
    relative_20d = (
        (relative_strength.get("horizons") or {}).get("20d")
        if isinstance(relative_strength.get("horizons"), Mapping)
        else {}
    )
    counter_evidence: list[dict[str, Any]] = []
    if macd_histogram is not None and macd_histogram < 0:
        counter_evidence.append(
            {"type": "momentum", "evidence": "negative_macd_histogram", "value": macd_histogram}
        )
    if rsi is not None and rsi >= parameters.rsi_overheated_at:
        counter_evidence.append(
            {"type": "momentum", "evidence": "rsi_overheated", "value": rsi}
        )
    if breakout.get("state") in {"rejected_attempt", "failed"}:
        counter_evidence.append(
            {
                "type": "breakout",
                "evidence": breakout.get("state"),
                "level": breakout.get("level"),
            }
        )
    for item in divergence.get("divergences") or []:
        if isinstance(item, Mapping) and item.get("direction") == "bearish":
            counter_evidence.append(
                {"type": "divergence", "evidence": item.get("type"), "detail": dict(item)}
            )
    invalidation_levels = [
        {"type": "support", "price": _round(support), "source": "support_resistance"},
        {"type": "anchored_vwap", "price": _round(avwap), "source": "confirmed_swing_anchor"},
        {
            "type": "nearest_fibonacci",
            "price": _round(nearest_fib.get("price")) if nearest_fib else None,
            "source": "confirmed_swing_anchor_pair",
        },
    ]
    invalidation_levels = [item for item in invalidation_levels if item["price"] is not None]
    corporate_action = (
        indicators.get("corporate_action")
        if isinstance(indicators.get("corporate_action"), Mapping)
        else {}
    )
    decision_usable = bool(
        completed
        and indicators.get("status") in {"ready", "partial"}
        and corporate_action.get("coverage_status") == "complete"
    )
    return {
        "kind": "tw_technical_current_state_v2",
        "version": "tw_technical_current_state_v2",
        "algorithm_version": ADVANCED_ALGORITHM_VERSION,
        "mode": "shadow",
        "active_score_impact": False,
        "status": "ready" if decision_usable else "partial",
        "decision_usable": decision_usable,
        "as_of": indicators.get("as_of"),
        "price_basis": indicators.get("price_basis") or PRICE_BASIS,
        "decision_snapshot": daily.get("decision_snapshot"),
        "current_period": daily.get("period") or {},
        "momentum_confirmation": {
            "rsi": _round(rsi),
            "macd_histogram": _round(macd_histogram),
            "pvo": _round(pvo_value),
            "state": (
                "positive"
                if (macd_histogram or 0) > 0 and (pvo_value or 0) > 0
                else "negative"
                if (macd_histogram or 0) < 0 and (pvo_value or 0) < 0
                else "mixed"
            ),
        },
        "volatility_context": {
            "atr": _round(atr),
            "atr_pct": _round(atr / close * 100) if atr is not None and close not in {None, 0} else None,
            "bollinger": dict(bollinger),
        },
        "breakout_context": dict(breakout),
        "swing_context": {
            "confirmed_count": swings.get("confirmed_count"),
            "latest_confirmed": (swings.get("pivots") or [None])[-1],
            "provisional": list(swings.get("provisional") or []),
        },
        "fibonacci_context": {
            "status": fibonacci.get("status"),
            "anchor_ids": fibonacci.get("anchor_ids") or [],
            "nearest_level": dict(nearest_fib) if nearest_fib else None,
        },
        "cost_context": {
            "anchored_vwap": _round(avwap),
            "volume_profile_poc": _round(poc),
            "value_area_low": volume_profile.get("val"),
            "value_area_high": volume_profile.get("vah"),
            "source_granularity": volume_profile.get("source_granularity"),
            "confidence": volume_profile.get("confidence"),
        },
        "relative_strength": {
            "benchmark": relative_strength.get("benchmark"),
            "20d": relative_20d,
            "sector": relative_strength.get("sector"),
        },
        "levels": {
            "support": _round(support),
            "resistance": _round(resistance),
            "nearest_fibonacci": _round(nearest_fib.get("price")) if nearest_fib else None,
            "anchored_vwap": _round(avwap),
            "volume_profile_poc": _round(poc),
        },
        "scenarios": [
            {
                "id": "continuation_confirmation",
                "condition": "Completed close holds above resistance with supportive volume ratio and positive PVO.",
                "current_state": breakout.get("state"),
            },
            {
                "id": "pullback_observation",
                "condition": "Observe support, confirmed-swing AVWAP, and nearby Fibonacci evidence without treating provisional pivots as confirmed.",
                "levels": invalidation_levels,
            },
        ],
        "invalidation": {
            "levels": invalidation_levels,
            "rule": "A completed close below a selected support level with worsening volume/momentum evidence invalidates the corresponding bullish scenario.",
        },
        "counter_evidence": counter_evidence,
        "corporate_action": dict(corporate_action),
        "warnings": list(indicators.get("warnings") or []),
        "limitations": [
            "This v2 structure is shadow evidence and does not change the active Radar or legacy technical score.",
            "Volume Profile and anchored VWAP are daily-bar approximations, not official intraday trade-by-price measures.",
        ],
    }


def _daily_points(
    db: Session,
    stock_id: str,
    *,
    to_date: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], Any]:
    to_time = (
        datetime.combine(to_date + timedelta(days=1), datetime.min.time(), TAIWAN_TZ)
        if to_date is not None
        else None
    )
    series = TaiwanBarService(db).read_bars(
        instrument_id=stock_id,
        interval="1d",
        to_time=to_time,
        limit=MAX_DAILY_BARS,
        include_partial=False,
    )
    bars = series.bars
    points = [
        {
            "time": bar.end_at.date(),
            "open": float(bar.open_price),
            "high": float(bar.high_price),
            "low": float(bar.low_price),
            "close": float(bar.close_price),
            "volume": int(bar.volume.value) if bar.volume is not None else None,
            "price_change": None,
        }
        for bar in bars
    ]
    latest = bars[-1] if bars else None
    lineage = {
        "dataset_id": "tw.daily.ohlcv",
        "component_count": len(bars),
        "series_fingerprint": series.identity.series_fingerprint,
        "lineage_digest": series.identity.lineage_digest,
        "state_digest": series.identity.state_digest,
        "series_revision": series.identity.series_revision,
        "resolved_health": {
            "status": series.history.history_status.value,
            "selected_provider": latest.lineage.provider if latest else None,
            "requested_coverage_satisfied": (
                series.history.requested_coverage_satisfied
            ),
        },
        "dataset_health": None,
        "latest_component": (
            {
                "provider": latest.lineage.provider,
                "source": latest.lineage.source,
                "event_at": latest.lineage.event_at,
                "fetched_at": latest.lineage.fetched_at,
                "observation_id": latest.lineage.observation_id,
                "raw_receipt_id": latest.lineage.raw_receipt_id,
                "content_hash": latest.lineage.content_hash,
            }
            if latest is not None
            else None
        ),
        "limitations": [*series.limitations, *series.warnings],
    }
    return points, lineage, series


def _benchmark_points(
    db: Session,
    *,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    to_time = (
        datetime.combine(to_date + timedelta(days=1), datetime.min.time(), TAIWAN_TZ)
        if to_date is not None
        else None
    )
    series = TaiwanBarService(db).read_bars(
        instrument_id="TAIEX",
        interval="1d",
        to_time=to_time,
        limit=MAX_DAILY_BARS,
        include_partial=False,
    )
    return [
        {
            "time": bar.start_at.date(),
            "close": float(bar.close_price),
        }
        for bar in series.bars
    ]


def _series_points(series: Any) -> list[dict[str, Any]]:
    return [
        {
            "time": bar.start_at.date(),
            "open": float(bar.open_price),
            "high": float(bar.high_price),
            "low": float(bar.low_price),
            "close": float(bar.close_price),
            "volume": int(bar.volume.value) if bar.volume is not None else None,
            "price_change": None,
        }
        for bar in series.bars
    ]


def _technical_points(series: Any, parameters: TechnicalAnalysisParameters):
    from app.market.tw_technical_service import TaiwanTechnicalService

    result = TaiwanTechnicalService().calculate(series, parameters=parameters)
    points = []
    for point in result.points:
        normalized = dict(point)
        normalized["time"] = point_date(normalized.get("time"))
        points.append(normalized)
    return points, result


def build_tw_stock_technical_evidence(
    *,
    db: Session,
    stock_id: str,
    corporate_event_history: Mapping[str, Any] | None = None,
    current_quote: Mapping[str, Any] | None = None,
    intraday_points: list[Mapping[str, Any]] | None = None,
    market_calendar_status: Mapping[str, Any] | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    parameters = get_technical_analysis_parameters()
    daily, daily_lineage, daily_series = _daily_points(
        db,
        stock_id,
        to_date=to_date,
    )
    if not daily:
        return {
            "kind": "tw_stock_technical_evidence",
            "version": "tw.stock.technical.evidence.v1",
            "status": "missing",
            "missing": ["tw.daily.ohlcv"],
            "warnings": [],
            "source_refs": [{"type": "resolved_market_data", "name": "tw.daily.ohlcv"}],
        }
    to_time = (
        datetime.combine(to_date + timedelta(days=1), datetime.min.time(), TAIWAN_TZ)
        if to_date is not None
        else None
    )
    bar_service = TaiwanBarService(db)
    weekly_series = bar_service.read_bars(
        instrument_id=stock_id,
        interval="1w",
        to_time=to_time,
        limit=MAX_DAILY_BARS,
        include_partial=False,
    )
    monthly_series = bar_service.read_bars(
        instrument_id=stock_id,
        interval="1mo",
        to_time=to_time,
        limit=MAX_DAILY_BARS,
        include_partial=False,
    )
    weekly = _series_points(weekly_series)
    monthly = _series_points(monthly_series)
    methods = indicator_method_catalog(parameters)
    end_date = point_date(daily[-1].get("time"))
    current_partial_daily = None
    current_partial_calculated = None
    if to_date is None:
        current_series = bar_service.read_bars(
            instrument_id=stock_id,
            interval="1d",
            limit=MAX_DAILY_BARS,
            include_partial=True,
        )
        if len(current_series.bars) > len(daily_series.bars):
            current_partial_daily = _series_points(current_series)[-1]
            current_calculated, _ = _technical_points(current_series, parameters)
            current_partial_calculated = (
                current_calculated[-1] if current_calculated else None
            )
    canonical_daily, daily_technical = _technical_points(daily_series, parameters)
    canonical_weekly, _ = _technical_points(weekly_series, parameters)
    canonical_monthly, _ = _technical_points(monthly_series, parameters)
    timeframes = {
        "daily": _snapshot_for_timeframe(
            daily,
            timeframe="daily",
            parameters=parameters,
            method_catalog=methods,
            latest_observation_date=end_date,
            current_partial_point=current_partial_daily,
            calculated_points=canonical_daily,
            current_partial_calculated=current_partial_calculated,
            allow_internal_calculation=False,
        ),
        "weekly": _snapshot_for_timeframe(
            weekly,
            timeframe="weekly",
            parameters=parameters,
            method_catalog=methods,
            latest_observation_date=end_date,
            calculated_points=canonical_weekly,
            allow_internal_calculation=False,
        ),
        "monthly": _snapshot_for_timeframe(
            monthly,
            timeframe="monthly",
            parameters=parameters,
            method_catalog=methods,
            latest_observation_date=end_date,
            calculated_points=canonical_monthly,
            allow_internal_calculation=False,
        ),
    }
    maximum_indicator_warmup = max(
        int(method.get("warmup_bars") or 1)
        for method in methods.values()
    )
    daily_coverage_points = [
        *daily,
        *([current_partial_daily] if current_partial_daily is not None else []),
    ]
    timeframe_corporate_actions = {
        "daily": _corporate_contract_for_points(
            corporate_event_history,
            daily_coverage_points,
            lookback_bars=maximum_indicator_warmup,
        ),
        "weekly": _corporate_contract_for_points(
            corporate_event_history,
            weekly,
            lookback_bars=maximum_indicator_warmup,
        ),
        "monthly": _corporate_contract_for_points(
            corporate_event_history,
            monthly,
            lookback_bars=maximum_indicator_warmup,
        ),
    }
    for timeframe_name, snapshot in timeframes.items():
        timeframe_contract = timeframe_corporate_actions[timeframe_name]
        snapshot["corporate_action"] = _corporate_summary(timeframe_contract)
        snapshot["decision_usable"] = bool(
            timeframe_contract.get("coverage_status") == "complete"
            and snapshot.get("completed")
        )

    swing_daily = daily[-SWING_LOOKBACK:]
    swing_corporate_actions = _corporate_contract_for_points(
        corporate_event_history,
        swing_daily,
    )
    breakout_corporate_actions = _corporate_contract_for_points(
        corporate_event_history,
        daily,
        lookback_bars=(
            parameters.support_resistance_period + BREAKOUT_LIFECYCLE_BARS
        ),
    )
    from app.market.tw_technical_service import TaiwanTechnicalService

    advanced = TaiwanTechnicalService().calculate_advanced(
        points=daily,
        canonical_points=canonical_daily,
        benchmark_points=_benchmark_points(db, to_date=to_date),
        parameters=parameters,
        affected_swing_dates=tuple(swing_corporate_actions["affected_dates"]),
        breakout_corporate_action_contract=dict(breakout_corporate_actions),
    )
    swings = advanced["swings"]
    fibonacci = advanced["fibonacci"]
    divergence = advanced["divergence"]
    breakout = advanced["breakout"]
    volume_profile = advanced["volume_profile"]
    anchored_vwap = advanced["anchored_vwap"]
    relative_strength = advanced["relative_strength"]
    profile_corporate_actions = _corporate_contract_for_points(
        corporate_event_history,
        daily,
        lookback_bars=PROFILE_LOOKBACK,
    )
    relative_strength_corporate_actions = _corporate_contract_for_points(
        corporate_event_history,
        daily,
        lookback_bars=61,
    )
    anchor_start = point_date(anchored_vwap.get("anchor_time"))
    anchored_vwap_corporate_actions = build_corporate_action_contract(
        corporate_event_history,
        analysis_start=anchor_start,
        analysis_end=end_date,
    )
    indicator_source_refs = [
        {"type": "resolved_market_data", "name": "tw.daily.ohlcv"},
        {"type": "derived", "name": "app.market.technical_evidence"},
        {"type": "external_or_cache", "name": "taiwan_corporate_event_history"},
    ]
    technical_source_refs = [
        *indicator_source_refs,
        {"type": "table", "name": "market_index_daily_stat"},
    ]
    capability_contracts = {
        "swings": swing_corporate_actions,
        "fibonacci": swing_corporate_actions,
        "divergence": swing_corporate_actions,
        "breakout": breakout_corporate_actions,
        "volume_profile": profile_corporate_actions,
        "anchored_vwap": anchored_vwap_corporate_actions,
        "relative_strength": relative_strength_corporate_actions,
    }
    advanced_payloads = {
        "swings": swings,
        "fibonacci": fibonacci,
        "divergence": divergence,
        "breakout": breakout,
        "volume_profile": volume_profile,
        "anchored_vwap": anchored_vwap,
        "relative_strength": relative_strength,
    }
    for capability_name, payload in advanced_payloads.items():
        _apply_capability_corporate_contract(
            payload,
            contract=capability_contracts[capability_name],
            source_refs=technical_source_refs,
        )

    indicator_warnings = list(
        dict.fromkeys(
            warning
            for contract in timeframe_corporate_actions.values()
            for warning in contract.get("warnings") or []
        )
    )
    warnings = list(
        dict.fromkeys(
            warning
            for contract in [
                *timeframe_corporate_actions.values(),
                *capability_contracts.values(),
            ]
            for warning in contract.get("warnings") or []
        )
    )
    daily_corporate_actions = timeframe_corporate_actions["daily"]
    status = (
        "partial"
        if any(
            contract.get("coverage_status") != "complete"
            for contract in capability_contracts.values()
        )
        or relative_strength["status"] != "ready"
        else "ready"
    )
    indicators = {
        "kind": "tw_technical_indicator_snapshot",
        "schema_version": INDICATOR_ALGORITHM_VERSION,
        "algorithm_version": INDICATOR_ALGORITHM_VERSION,
        "bar_series_fingerprint": daily_technical.bar_series_fingerprint,
        "bar_series_revision": daily_technical.bar_series_revision,
        "technical_revision": daily_technical.technical_revision,
        "calculation_role": "backend_authoritative",
        "parameter_contract": _indicator_parameter_contract(parameters),
        "status": "partial" if daily_corporate_actions["coverage_status"] != "complete" else "ready",
        "stock_id": stock_id,
        "as_of": _json_date(end_date),
        "price_basis": PRICE_BASIS,
        "currency": "TWD",
        "price_unit": "TWD",
        "volume_unit": "shares",
        "source_capability": "daily.ohlcv",
        "measurement_lineage": {
            "currency": "TWD",
            "price_unit": "TWD",
            "volume_unit": "shares",
            "source_capability": "daily.ohlcv",
        },
        "methods": methods,
        "timeframes": timeframes,
        "corporate_action": daily_corporate_actions,
        "corporate_action_coverage_by_timeframe": {
            name: _corporate_summary(contract)
            for name, contract in timeframe_corporate_actions.items()
        },
        "missing": [],
        "warnings": indicator_warnings,
        "source_refs": indicator_source_refs,
        "lineage": daily_lineage,
        "freshness": {
            "status": "current",
            "latest_data_date": _json_date(
                current_partial_daily.get("time") if current_partial_daily else end_date
            ),
            "finalized_daily_date": _json_date(end_date),
            "period_semantics": "daily/weekly/monthly completed snapshots plus explicit current_partial when observed",
        },
    }
    structure_v2 = build_technical_structure_v2(
        indicators=indicators,
        swings=swings,
        fibonacci=fibonacci,
        divergence=divergence,
        breakout=breakout,
        volume_profile=volume_profile,
        anchored_vwap=anchored_vwap,
        relative_strength=relative_strength,
        parameters=parameters,
    )
    return {
        "kind": "tw_stock_technical_evidence",
        "version": "tw.stock.technical.evidence.v1",
        "status": status,
        "as_of": _json_date(end_date),
        "price_basis": PRICE_BASIS,
        "indicators": indicators,
        "swings": swings,
        "fibonacci": fibonacci,
        "divergence": divergence,
        "breakout": breakout,
        "volume_profile": volume_profile,
        "anchored_vwap": anchored_vwap,
        "relative_strength": relative_strength,
        "structure_v2": structure_v2,
        "missing": [],
        "warnings": warnings,
        "source_refs": technical_source_refs,
    }


__all__ = [
    "ADVANCED_ALGORITHM_VERSION",
    "INDICATOR_ALGORITHM_VERSION",
    "PRICE_BASIS",
    "build_anchored_vwap",
    "build_breakout_evidence",
    "build_corporate_action_contract",
    "build_divergence_evidence",
    "build_fibonacci_evidence",
    "build_relative_strength",
    "build_swing_evidence",
    "build_tw_stock_technical_evidence",
    "build_technical_structure_v2",
    "build_volume_profile",
    "calculate_canonical_indicator_points",
    "classify_latest_period",
    "indicator_method_catalog",
]
