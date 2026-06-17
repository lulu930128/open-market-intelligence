from datetime import date

from sqlalchemy.orm import Session

from app.market.service import list_stock_daily_history


def _parse_windows(value: str, default: list[int]) -> list[int]:
    if not value or value.strip() == "":
        return default

    windows: list[int] = []

    for item in value.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            window = int(item)
        except ValueError as exc:
            raise ValueError(f"Invalid window value: '{item}'.") from exc

        if window <= 0:
            raise ValueError("Window value must be greater than 0.")

        if window > 1000:
            raise ValueError("Window value must be less than or equal to 1000.")

        windows.append(window)

    return sorted(set(windows))


def _moving_average(
    values: list[float | None],
    index: int,
    window: int,
    dates: list[date] | None = None,
    max_gap_days: int = 10,
) -> float | None:
    start = index - window + 1

    if start < 0:
        return None

    if dates is not None:
        window_dates = dates[start : index + 1]

        if any(
            (right - left).days > max_gap_days
            for left, right in zip(window_dates, window_dates[1:])
        ):
            return None

    window_values = values[start : index + 1]

    if any(value is None for value in window_values):
        return None

    total = sum(value for value in window_values if value is not None)

    return round(total / window, 4)


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


def _rsi_series(closes: list[float | None], period: int = 14) -> list[float | None]:
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
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
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
    period: int = 14,
) -> list[float | None]:
    return _wilder_average_series(_true_ranges(highs, lows, closes), period)


def _dmi_series(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    period: int = 14,
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


def _roc_series(closes: list[float | None], period: int = 12) -> list[float | None]:
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
    period: int = 14,
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
    period: int = 20,
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
    period: int = 20,
    std_dev: float = 2.0,
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
    period: int = 9,
    smooth_period: int = 3,
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
    period: int = 20,
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


def calculate_indicator_points_from_ohlc_points(
    points: list[dict],
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    *,
    max_gap_days: int | None = 10,
) -> list[dict]:
    ma_window_list = _parse_windows(ma_windows, default=[5, 20, 60])
    volume_ma_window_list = _parse_windows(volume_ma_windows, default=[5, 20])

    closes: list[float | None] = [point.get("close") for point in points]
    highs: list[float | None] = [point.get("high") for point in points]
    lows: list[float | None] = [point.get("low") for point in points]
    point_dates: list[date] | None = None
    if max_gap_days is not None and all(isinstance(point.get("time"), date) for point in points):
        point_dates = [point["time"] for point in points]
    volumes: list[float | None] = [
        float(point["volume"]) if point.get("volume") is not None else None
        for point in points
    ]
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    macd, macd_signal, macd_histogram = _macd_series(closes)
    rsi14 = _rsi_series(closes)
    atr14 = _atr_series(highs, lows, closes)
    plus_di14, minus_di14, adx14 = _dmi_series(highs, lows, closes)
    roc12 = _roc_series(closes)
    mfi14 = _mfi_series(highs, lows, closes, volumes)
    donchian_upper20, donchian_lower20 = _donchian_series(highs, lows)
    bollinger_upper20, bollinger_middle20, bollinger_lower20, bollinger_bandwidth20_pct = _bollinger_series(closes)
    kd_k9, kd_d9 = _kd_series(highs, lows, closes)
    support20, resistance20 = _support_resistance_series(highs, lows)

    results: list[dict] = []

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
                max_gap_days=max_gap_days or 10,
            )
            for window in ma_window_list
        }

        volume_ma_values = {
            f"volume_ma{window}": _moving_average(
                volumes,
                index,
                window,
                point_dates,
                max_gap_days=max_gap_days or 10,
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
                    "ema12": ema12[index],
                    "ema26": ema26[index],
                },
                "macd": {
                    "macd": macd[index],
                    "signal": macd_signal[index],
                    "histogram": macd_histogram[index],
                },
                "rsi": {
                    "rsi14": rsi14[index],
                },
                "atr": {
                    "atr14": atr14[index],
                },
                "adx": {
                    "plus_di14": plus_di14[index],
                    "minus_di14": minus_di14[index],
                    "adx14": adx14[index],
                },
                "roc": {
                    "roc12": roc12[index],
                },
                "mfi": {
                    "mfi14": mfi14[index],
                },
                "donchian": {
                    "upper20": donchian_upper20[index],
                    "lower20": donchian_lower20[index],
                },
                "bollinger": {
                    "upper20": bollinger_upper20[index],
                    "middle20": bollinger_middle20[index],
                    "lower20": bollinger_lower20[index],
                    "bandwidth20_pct": bollinger_bandwidth20_pct[index],
                },
                "kd": {
                    "k9": kd_k9[index],
                    "d9": kd_d9[index],
                },
                "support_resistance": {
                    "support20": support20[index],
                    "resistance20": resistance20[index],
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
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
) -> list[dict]:
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
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
        max_gap_days=10,
    )


def calculate_latest_daily_indicator(
    db: Session,
    stock_id: str,
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
) -> dict | None:
    ma_window_list = _parse_windows(ma_windows, default=[5, 20, 60])
    volume_ma_window_list = _parse_windows(volume_ma_windows, default=[5, 20])

    required_lookback = max(ma_window_list + volume_ma_window_list + [2])

    results = calculate_daily_indicators(
        db=db,
        stock_id=stock_id,
        limit=max(required_lookback, 250),
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
    )

    if not results:
        return None

    return results[-1]
