"""Shared numerical series primitives used by TW and US technical research."""

from __future__ import annotations

import math
from typing import Any


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def round_value(value: Any, digits: int = 4) -> float | None:
    parsed = number(value)
    return None if parsed is None else round(parsed, digits)


def ema_sma_seed(
    values: list[float | None], period: int
) -> list[float | None]:
    results: list[float | None] = [None] * len(values)
    multiplier = 2 / (period + 1)
    segment: list[float] = []
    previous: float | None = None
    for index, value in enumerate(values):
        if value is None:
            segment = []
            previous = None
            continue
        segment.append(value)
        if previous is None:
            if len(segment) < period:
                continue
            previous = sum(segment[-period:]) / period
        else:
            previous = value * multiplier + previous * (1 - multiplier)
        results[index] = round_value(previous)
    return results


def wilder_rsi(
    closes: list[float | None], period: int
) -> list[float | None]:
    results: list[float | None] = [None] * len(closes)
    gains: list[float] = []
    losses: list[float] = []
    average_gain: float | None = None
    average_loss: float | None = None
    for index in range(1, len(closes)):
        current = closes[index]
        previous = closes[index - 1]
        if current is None or previous is None:
            gains = []
            losses = []
            average_gain = None
            average_loss = None
            continue
        change = current - previous
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        if average_gain is None or average_loss is None:
            gains.append(gain)
            losses.append(loss)
            if len(gains) < period:
                continue
            average_gain = sum(gains[-period:]) / period
            average_loss = sum(losses[-period:]) / period
        else:
            average_gain = (average_gain * (period - 1) + gain) / period
            average_loss = (average_loss * (period - 1) + loss) / period
        if average_loss == 0:
            results[index] = 100.0
        elif average_gain == 0:
            results[index] = 0.0
        else:
            relative_strength = average_gain / average_loss
            results[index] = round_value(100 - 100 / (1 + relative_strength))
    return results


def macd_sma_seed(
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
    fast = ema_sma_seed(closes, fast_period)
    slow = ema_sma_seed(closes, slow_period)
    macd = [
        round_value(fast_value - slow_value)
        if fast_value is not None and slow_value is not None
        else None
        for fast_value, slow_value in zip(fast, slow)
    ]
    signal = ema_sma_seed(macd, signal_period)
    histogram = [
        round_value(value - signal_value)
        if value is not None and signal_value is not None
        else None
        for value, signal_value in zip(macd, signal)
    ]
    return fast, slow, macd, signal, histogram


def recursive_kd(
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
    rsv: list[float | None] = [None] * len(closes)
    k_values: list[float | None] = [None] * len(closes)
    d_values: list[float | None] = [None] * len(closes)
    j_values: list[float | None] = [None] * len(closes)
    previous_k = 50.0
    previous_d = 50.0
    alpha = 1 / smooth_period
    for index, close in enumerate(closes):
        if close is None or index + 1 < period:
            continue
        high_window = highs[index + 1 - period : index + 1]
        low_window = lows[index + 1 - period : index + 1]
        if any(item is None for item in high_window + low_window):
            previous_k = 50.0
            previous_d = 50.0
            continue
        highest = max(item for item in high_window if item is not None)
        lowest = min(item for item in low_window if item is not None)
        current_rsv = (
            50.0
            if highest == lowest
            else (close - lowest) / (highest - lowest) * 100
        )
        current_k = previous_k * (1 - alpha) + current_rsv * alpha
        current_d = previous_d * (1 - alpha) + current_k * alpha
        current_j = 3 * current_k - 2 * current_d
        rsv[index] = round_value(current_rsv)
        k_values[index] = round_value(current_k)
        d_values[index] = round_value(current_d)
        j_values[index] = round_value(current_j)
        previous_k = current_k
        previous_d = current_d
    return rsv, k_values, d_values, j_values


def percentage_volume_oscillator(
    volumes: list[float | None],
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    normalized = [value if value is not None and value >= 0 else None for value in volumes]
    fast = ema_sma_seed(normalized, fast_period)
    slow = ema_sma_seed(normalized, slow_period)
    values = [
        round_value((fast_value - slow_value) / slow_value * 100)
        if fast_value is not None and slow_value not in {None, 0}
        else None
        for fast_value, slow_value in zip(fast, slow)
    ]
    signal = ema_sma_seed(values, signal_period)
    histogram = [
        round_value(value - signal_value)
        if value is not None and signal_value is not None
        else None
        for value, signal_value in zip(values, signal)
    ]
    return values, signal, histogram


__all__ = [
    "ema_sma_seed",
    "macd_sma_seed",
    "number",
    "percentage_volume_oscillator",
    "recursive_kd",
    "round_value",
    "wilder_rsi",
]
