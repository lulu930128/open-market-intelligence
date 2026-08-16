from datetime import date

from sqlalchemy.orm import Session

from app.market.service import list_stock_daily_history
from app.market.technical_parameters import (
    TechnicalAnalysisParameters,
    get_technical_analysis_parameters,
)
from app.market.trading_calendar import (
    is_taiwan_trading_day,
    next_taiwan_trading_day,
)


_DEFAULT_MAX_GAP_DAYS = object()


def _moving_average(
    values: list[float | None],
    index: int,
    window: int,
    dates: list[date] | None = None,
    max_gap_days: int = 10,
    unexpected_gap_prefix: list[int] | None = None,
) -> float | None:
    start = index - window + 1

    if start < 0:
        return None

    if unexpected_gap_prefix is not None:
        if len(unexpected_gap_prefix) != len(values):
            raise ValueError("unexpected_gap_prefix must match values length.")
        if unexpected_gap_prefix[index] > unexpected_gap_prefix[start]:
            return None
    elif dates is not None:
        window_dates = dates[start : index + 1]

        if any(
            _has_unexpected_taiwan_gap(
                left,
                right,
                fallback_max_gap_days=max_gap_days,
            )
            for left, right in zip(window_dates, window_dates[1:])
        ):
            return None

    window_values = values[start : index + 1]

    if any(value is None for value in window_values):
        return None

    total = sum(value for value in window_values if value is not None)

    return round(total / window, 4)


def _has_unexpected_taiwan_gap(
    left: date,
    right: date,
    *,
    fallback_max_gap_days: int,
) -> bool:
    """Distinguish a missing Taiwan trading day from a legitimate closure.

    Real daily rows are exchange trading dates, so their successor must match
    the calendar's next trading date. The fallback preserves generic/synthetic
    OHLC callers that deliberately include non-trading calendar dates.
    """

    if right <= left:
        return True
    if is_taiwan_trading_day(left) and is_taiwan_trading_day(right):
        return right != next_taiwan_trading_day(left, include_value=False)
    return (right - left).days > fallback_max_gap_days


def _build_unexpected_gap_prefix(
    dates: list[date],
    *,
    fallback_max_gap_days: int,
) -> list[int]:
    """Count continuity breaks once so every moving-average window is O(1)."""

    prefix = [0] * len(dates)
    for index in range(1, len(dates)):
        prefix[index] = prefix[index - 1] + int(
            _has_unexpected_taiwan_gap(
                dates[index - 1],
                dates[index],
                fallback_max_gap_days=fallback_max_gap_days,
            )
        )
    return prefix


def _calculate_change(
    current: float | None,
    previous: float | None,
) -> tuple[float | None, float | None]:
    if current is None or previous is None:
        return None, None

    if previous == 0:
        return None, None

    change = current - previous
    change_pct = change / previous * 100

    return round(change, 4), round(change_pct, 4)


def _calculate_change_from_price_change(
    current: float | None,
    price_change: float | None,
) -> tuple[float | None, float | None]:
    if current is None or price_change is None:
        return None, None

    previous = current - price_change

    if previous == 0:
        return round(price_change, 4), None

    change_pct = price_change / previous * 100
    return round(price_change, 4), round(change_pct, 4)


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None

    return round(value, digits)


def _ema_series(values: list[float | None], period: int) -> list[float | None]:
    multiplier = 2 / (period + 1)
    previous_ema: float | None = None
    results: list[float | None] = []

    for value in values:
        if value is None:
            results.append(None)
            continue

        if previous_ema is None:
            previous_ema = value
        else:
            previous_ema = value * multiplier + previous_ema * (1 - multiplier)

        results.append(_round(previous_ema))

    return results


def _rsi_series(closes: list[float | None], period: int) -> list[float | None]:
    results: list[float | None] = []

    for index, close in enumerate(closes):
        if close is None or index < period:
            results.append(None)
            continue

        gain = 0.0
        loss = 0.0
        valid = True

        for cursor in range(index - period + 1, index + 1):
            current = closes[cursor]
            previous = closes[cursor - 1]

            if current is None or previous is None:
                valid = False
                break

            change = current - previous

            if change >= 0:
                gain += change
            else:
                loss += abs(change)

        if not valid:
            results.append(None)
            continue

        average_gain = gain / period
        average_loss = loss / period

        if average_loss == 0:
            results.append(100)
        elif average_gain == 0:
            results.append(0)
        else:
            rs = average_gain / average_loss
            results.append(_round(100 - 100 / (1 + rs)))

    return results


def _macd_series(
    closes: list[float | None],
    fast_period: int,
    slow_period: int,
    signal_period: int,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    fast_ema = _ema_series(closes, fast_period)
    slow_ema = _ema_series(closes, slow_period)
    macd = [
        _round(fast - slow) if fast is not None and slow is not None else None
        for fast, slow in zip(fast_ema, slow_ema)
    ]
    signal = _ema_series(macd, signal_period)
    histogram = [
        _round(value - signal_value)
        if value is not None and signal_value is not None
        else None
        for value, signal_value in zip(macd, signal)
    ]

    return macd, signal, histogram


def _true_ranges(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
) -> list[float | None]:
    results: list[float | None] = []

    for index, (high, low) in enumerate(zip(highs, lows)):
        if high is None or low is None:
            results.append(None)
            continue

        previous_close = closes[index - 1] if index > 0 else None
        high_low = high - low

        if previous_close is None:
            results.append(_round(high_low))
            continue

        results.append(
            _round(
                max(
                    high_low,
                    abs(high - previous_close),
                    abs(low - previous_close),
                )
            )
        )

    return results


def _wilder_average_series(values: list[float | None], period: int) -> list[float | None]:
    results: list[float | None] = []
    previous_average: float | None = None

    for index, value in enumerate(values):
        if value is None or index + 1 < period:
            results.append(None)
            continue

        if previous_average is None:
            window = values[index + 1 - period : index + 1]

            if any(item is None for item in window):
                results.append(None)
                continue

            previous_average = sum(item for item in window if item is not None) / period
        else:
            previous_average = (previous_average * (period - 1) + value) / period

        results.append(_round(previous_average))

    return results


def _atr_series(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    period: int,
) -> list[float | None]:
    return _wilder_average_series(_true_ranges(highs, lows, closes), period)


def _dmi_series(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    period: int,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    true_ranges = _true_ranges(highs, lows, closes)
    plus_dm: list[float | None] = [None]
    minus_dm: list[float | None] = [None]

    for index in range(1, len(highs)):
        high = highs[index]
        low = lows[index]
        previous_high = highs[index - 1]
        previous_low = lows[index - 1]

        if high is None or low is None or previous_high is None or previous_low is None:
            plus_dm.append(None)
            minus_dm.append(None)
            continue

        up_move = high - previous_high
        down_move = previous_low - low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

    smoothed_tr = _wilder_average_series(true_ranges, period)
    smoothed_plus = _wilder_average_series(plus_dm, period)
    smoothed_minus = _wilder_average_series(minus_dm, period)

    plus_di: list[float | None] = []
    minus_di: list[float | None] = []
    dx: list[float | None] = []

    for tr, plus, minus in zip(smoothed_tr, smoothed_plus, smoothed_minus):
        if tr is None or plus is None or minus is None or tr == 0:
            plus_di.append(None)
            minus_di.append(None)
            dx.append(None)
            continue

        plus_value = plus / tr * 100
        minus_value = minus / tr * 100
        total = plus_value + minus_value

        plus_di.append(_round(plus_value))
        minus_di.append(_round(minus_value))
        dx.append(_round(abs(plus_value - minus_value) / total * 100 if total else 0))

    adx = _wilder_average_series(dx, period)
    return plus_di, minus_di, adx


def _roc_series(closes: list[float | None], period: int) -> list[float | None]:
    results: list[float | None] = []

    for index, close in enumerate(closes):
        previous = closes[index - period] if index >= period else None

        if close is None or previous is None or previous == 0:
            results.append(None)
        else:
            results.append(_round((close - previous) / previous * 100))

    return results


def _typical_price(
    high: float | None,
    low: float | None,
    close: float | None,
) -> float | None:
    if high is None or low is None or close is None:
        return None

    return (high + low + close) / 3


def _mfi_series(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    volumes: list[float | None],
    period: int,
) -> list[float | None]:
    typical_prices = [
        _typical_price(high, low, close)
        for high, low, close in zip(highs, lows, closes)
    ]
    positive_flow: list[float | None] = [None]
    negative_flow: list[float | None] = [None]

    for index in range(1, len(typical_prices)):
        price = typical_prices[index]
        previous_price = typical_prices[index - 1]
        volume = volumes[index]

        if price is None or previous_price is None or volume is None:
            positive_flow.append(None)
            negative_flow.append(None)
            continue

        money_flow = price * volume
        positive_flow.append(money_flow if price > previous_price else 0)
        negative_flow.append(money_flow if price < previous_price else 0)

    results: list[float | None] = []

    for index in range(len(typical_prices)):
        if index + 1 < period:
            results.append(None)
            continue

        positive_window = positive_flow[index + 1 - period : index + 1]
        negative_window = negative_flow[index + 1 - period : index + 1]

        if any(value is None for value in positive_window + negative_window):
            results.append(None)
            continue

        positive = sum(value for value in positive_window if value is not None)
        negative = sum(value for value in negative_window if value is not None)

        if negative == 0:
            results.append(100)
        elif positive == 0:
            results.append(0)
        else:
            money_ratio = positive / negative
            results.append(_round(100 - 100 / (1 + money_ratio)))

    return results


def _donchian_series(
    highs: list[float | None],
    lows: list[float | None],
    period: int,
) -> tuple[list[float | None], list[float | None]]:
    upper: list[float | None] = []
    lower: list[float | None] = []

    for index in range(len(highs)):
        if index + 1 < period:
            upper.append(None)
            lower.append(None)
            continue

        high_window = highs[index + 1 - period : index + 1]
        low_window = lows[index + 1 - period : index + 1]

        if any(value is None for value in high_window + low_window):
            upper.append(None)
            lower.append(None)
            continue

        upper.append(_round(max(value for value in high_window if value is not None)))
        lower.append(_round(min(value for value in low_window if value is not None)))

    return upper, lower


def _standard_deviation(values: list[float]) -> float | None:
    if not values:
        return None

    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance**0.5


def _bollinger_series(
    closes: list[float | None],
    period: int,
    std_dev: float,
) -> tuple[list[float | None], list[float | None], list[float | None], list[float | None]]:
    upper: list[float | None] = []
    middle: list[float | None] = []
    lower: list[float | None] = []
    bandwidth_pct: list[float | None] = []

    for index in range(len(closes)):
        if index + 1 < period:
            upper.append(None)
            middle.append(None)
            lower.append(None)
            bandwidth_pct.append(None)
            continue

        window = closes[index + 1 - period : index + 1]
        if any(value is None for value in window):
            upper.append(None)
            middle.append(None)
            lower.append(None)
            bandwidth_pct.append(None)
            continue

        values = [float(value) for value in window if value is not None]
        middle_value = sum(values) / period
        std_value = _standard_deviation(values)

        if std_value is None:
            upper.append(None)
            middle.append(None)
            lower.append(None)
            bandwidth_pct.append(None)
            continue

        upper_value = middle_value + (std_value * std_dev)
        lower_value = middle_value - (std_value * std_dev)
        upper.append(_round(upper_value))
        middle.append(_round(middle_value))
        lower.append(_round(lower_value))
        bandwidth_pct.append(
            _round(((upper_value - lower_value) / middle_value) * 100)
            if middle_value != 0
            else None
        )

    return upper, middle, lower, bandwidth_pct


def _simple_average_from_series(
    values: list[float | None],
    index: int,
    period: int,
) -> float | None:
    if index + 1 < period:
        return None

    window = values[index + 1 - period : index + 1]
    if any(value is None for value in window):
        return None

    return _round(sum(value for value in window if value is not None) / period)


def _kd_series(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    period: int,
    smooth_period: int,
) -> tuple[list[float | None], list[float | None]]:
    rsv_values: list[float | None] = []

    for index, close in enumerate(closes):
        if close is None or index + 1 < period:
            rsv_values.append(None)
            continue

        high_window = highs[index + 1 - period : index + 1]
        low_window = lows[index + 1 - period : index + 1]

        if any(value is None for value in high_window + low_window):
            rsv_values.append(None)
            continue

        highest = max(value for value in high_window if value is not None)
        lowest = min(value for value in low_window if value is not None)

        if highest == lowest:
            rsv_values.append(50)
        else:
            rsv_values.append(_round((close - lowest) / (highest - lowest) * 100))

    k_values = [
        _simple_average_from_series(rsv_values, index, smooth_period)
        for index in range(len(rsv_values))
    ]
    d_values = [
        _simple_average_from_series(k_values, index, smooth_period)
        for index in range(len(k_values))
    ]

    return k_values, d_values


def _support_resistance_series(
    highs: list[float | None],
    lows: list[float | None],
    period: int,
) -> tuple[list[float | None], list[float | None]]:
    support: list[float | None] = []
    resistance: list[float | None] = []

    for index in range(len(highs)):
        start = index - period

        if start < 0:
            support.append(None)
            resistance.append(None)
            continue

        high_window = highs[start:index]
        low_window = lows[start:index]

        if any(value is None for value in high_window + low_window):
            support.append(None)
            resistance.append(None)
            continue

        support.append(_round(min(value for value in low_window if value is not None)))
        resistance.append(_round(max(value for value in high_window if value is not None)))

    return support, resistance


def _with_legacy_alias(key: str, legacy_key: str, value: float | None) -> dict[str, float | None]:
    values = {key: value}
    if key != legacy_key:
        values[legacy_key] = value
    return values


def calculate_indicator_points_from_ohlc_points(
    points: list[dict],
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    *,
    max_gap_days: int | None | object = _DEFAULT_MAX_GAP_DAYS,
    parameters: TechnicalAnalysisParameters | None = None,
) -> list[dict]:
    technical_parameters = parameters or get_technical_analysis_parameters(
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
    )
    ma_window_list = technical_parameters.ma_windows
    volume_ma_window_list = technical_parameters.volume_ma_windows
    effective_max_gap_days = (
        technical_parameters.max_gap_days
        if max_gap_days is _DEFAULT_MAX_GAP_DAYS
        else max_gap_days
    )

    closes: list[float | None] = [point.get("close") for point in points]
    highs: list[float | None] = [point.get("high") for point in points]
    lows: list[float | None] = [point.get("low") for point in points]
    point_dates: list[date] | None = None
    if effective_max_gap_days is not None and all(isinstance(point.get("time"), date) for point in points):
        point_dates = [point["time"] for point in points]
    volumes: list[float | None] = [
        float(point["volume"]) if point.get("volume") is not None else None
        for point in points
    ]
    ema_fast = _ema_series(closes, technical_parameters.macd_fast_period)
    ema_slow = _ema_series(closes, technical_parameters.macd_slow_period)
    macd, macd_signal, macd_histogram = _macd_series(
        closes,
        fast_period=technical_parameters.macd_fast_period,
        slow_period=technical_parameters.macd_slow_period,
        signal_period=technical_parameters.macd_signal_period,
    )
    rsi = _rsi_series(closes, period=technical_parameters.rsi_period)
    atr = _atr_series(highs, lows, closes, period=technical_parameters.atr_period)
    plus_di, minus_di, adx = _dmi_series(highs, lows, closes, period=technical_parameters.adx_period)
    roc = _roc_series(closes, period=technical_parameters.roc_period)
    mfi = _mfi_series(highs, lows, closes, volumes, period=technical_parameters.mfi_period)
    donchian_upper, donchian_lower = _donchian_series(
        highs,
        lows,
        period=technical_parameters.donchian_period,
    )
    (
        bollinger_upper,
        bollinger_middle,
        bollinger_lower,
        bollinger_bandwidth_pct,
    ) = _bollinger_series(
        closes,
        period=technical_parameters.bollinger_period,
        std_dev=technical_parameters.bollinger_std_dev,
    )
    kd_k, kd_d = _kd_series(
        highs,
        lows,
        closes,
        period=technical_parameters.kd_period,
        smooth_period=technical_parameters.kd_smooth_period,
    )
    support, resistance = _support_resistance_series(
        highs,
        lows,
        period=technical_parameters.support_resistance_period,
    )

    results: list[dict] = []
    gap_days_for_ma = (
        effective_max_gap_days
        if isinstance(effective_max_gap_days, int)
        else technical_parameters.max_gap_days
    )
    unexpected_gap_prefix = (
        _build_unexpected_gap_prefix(
            point_dates,
            fallback_max_gap_days=gap_days_for_ma,
        )
        if point_dates is not None
        else None
    )

    for index, point in enumerate(points):
        previous_close = closes[index - 1] if index > 0 else None
        change, change_pct = _calculate_change_from_price_change(
            point.get("close"),
            point.get("price_change"),
        )

        if change is None and change_pct is None:
            change, change_pct = _calculate_change(point.get("close"), previous_close)

        ma_values = {
            f"ma{window}": _moving_average(
                closes,
                index,
                window,
                point_dates,
                max_gap_days=gap_days_for_ma,
                unexpected_gap_prefix=unexpected_gap_prefix,
            )
            for window in ma_window_list
        }

        volume_ma_values = {
            f"volume_ma{window}": _moving_average(
                volumes,
                index,
                window,
                point_dates,
                max_gap_days=gap_days_for_ma,
                unexpected_gap_prefix=unexpected_gap_prefix,
            )
            for window in volume_ma_window_list
        }

        results.append(
            {
                "time": point.get("time"),
                "close": point.get("close"),
                "volume": point.get("volume"),
                "change": change,
                "change_pct": change_pct,
                "ma": ma_values,
                "volume_ma": volume_ma_values,
                "ema": {
                    **_with_legacy_alias(technical_parameters.ema_fast_key, "ema12", ema_fast[index]),
                    **_with_legacy_alias(technical_parameters.ema_slow_key, "ema26", ema_slow[index]),
                },
                "macd": {
                    "macd": macd[index],
                    "signal": macd_signal[index],
                    "histogram": macd_histogram[index],
                },
                "rsi": _with_legacy_alias(technical_parameters.rsi_key, "rsi14", rsi[index]),
                "atr": _with_legacy_alias(technical_parameters.atr_key, "atr14", atr[index]),
                "adx": {
                    **_with_legacy_alias(technical_parameters.plus_di_key, "plus_di14", plus_di[index]),
                    **_with_legacy_alias(technical_parameters.minus_di_key, "minus_di14", minus_di[index]),
                    **_with_legacy_alias(technical_parameters.adx_key, "adx14", adx[index]),
                },
                "roc": _with_legacy_alias(technical_parameters.roc_key, "roc12", roc[index]),
                "mfi": _with_legacy_alias(technical_parameters.mfi_key, "mfi14", mfi[index]),
                "donchian": {
                    **_with_legacy_alias(
                        technical_parameters.donchian_upper_key,
                        "upper20",
                        donchian_upper[index],
                    ),
                    **_with_legacy_alias(
                        technical_parameters.donchian_lower_key,
                        "lower20",
                        donchian_lower[index],
                    ),
                },
                "bollinger": {
                    **_with_legacy_alias(
                        technical_parameters.bollinger_upper_key,
                        "upper20",
                        bollinger_upper[index],
                    ),
                    **_with_legacy_alias(
                        technical_parameters.bollinger_middle_key,
                        "middle20",
                        bollinger_middle[index],
                    ),
                    **_with_legacy_alias(
                        technical_parameters.bollinger_lower_key,
                        "lower20",
                        bollinger_lower[index],
                    ),
                    **_with_legacy_alias(
                        technical_parameters.bollinger_bandwidth_key,
                        "bandwidth20_pct",
                        bollinger_bandwidth_pct[index],
                    ),
                },
                "kd": {
                    **_with_legacy_alias(technical_parameters.kd_k_key, "k9", kd_k[index]),
                    **_with_legacy_alias(technical_parameters.kd_d_key, "d9", kd_d[index]),
                },
                "support_resistance": {
                    **_with_legacy_alias(
                        technical_parameters.support_key,
                        "support20",
                        support[index],
                    ),
                    **_with_legacy_alias(
                        technical_parameters.resistance_key,
                        "resistance20",
                        resistance[index],
                    ),
                },
            }
        )

    return results


def calculate_daily_indicators(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    parameters: TechnicalAnalysisParameters | None = None,
) -> list[dict]:
    technical_parameters = parameters or get_technical_analysis_parameters(
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
    )
    rows = list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        ascending=True,
    )

    points = [
        {
            "time": row.trade_date,
            "open": row.open_price,
            "high": row.high_price,
            "low": row.low_price,
            "close": row.close_price,
            "volume": row.trade_volume,
            "price_change": row.price_change,
        }
        for row in rows
    ]
    return calculate_indicator_points_from_ohlc_points(
        points,
        ma_windows=technical_parameters.ma_windows_text,
        volume_ma_windows=technical_parameters.volume_ma_windows_text,
        max_gap_days=technical_parameters.max_gap_days,
        parameters=technical_parameters,
    )


def calculate_latest_daily_indicator(
    db: Session,
    stock_id: str,
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    parameters: TechnicalAnalysisParameters | None = None,
) -> dict | None:
    technical_parameters = parameters or get_technical_analysis_parameters(
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
    )

    required_lookback = max(
        list(technical_parameters.ma_windows)
        + list(technical_parameters.volume_ma_windows)
        + [
            technical_parameters.macd_slow_period,
            technical_parameters.rsi_period,
            technical_parameters.atr_period,
            technical_parameters.adx_period,
            technical_parameters.roc_period,
            technical_parameters.mfi_period,
            technical_parameters.donchian_period,
            technical_parameters.bollinger_period,
            technical_parameters.kd_period + (technical_parameters.kd_smooth_period * 2),
            technical_parameters.support_resistance_period + 1,
            2,
        ]
    )

    results = calculate_daily_indicators(
        db=db,
        stock_id=stock_id,
        limit=max(required_lookback, 250),
        ma_windows=technical_parameters.ma_windows_text,
        volume_ma_windows=technical_parameters.volume_ma_windows_text,
        parameters=technical_parameters,
    )

    if not results:
        return None

    return results[-1]
