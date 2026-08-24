"""Pure provider-neutral technical indicator and structure calculations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from app.research.technical.profiles import MarketAnalysisProfile
from app.research.technical.series import ema_sma_seed, macd_sma_seed, wilder_rsi
from app.research.technical.usability import evaluate_technical_usability


TECHNICAL_INDICATOR_SCHEMA_VERSION = "omi.research.technical.indicators.v1"
TECHNICAL_STRUCTURE_SCHEMA_VERSION = "omi.research.technical.structure.v1"
TECHNICAL_ALGORITHM_VERSION = "omi.research.technical.shared.v1"


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return float(parsed) if parsed.is_finite() else None


def _time_value(bar: Mapping[str, Any]) -> str | None:
    value = bar.get("end_at") or bar.get("time") or bar.get("date")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if value not in (None, "") else None


def _normalize_bars(bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized_by_time: dict[str, dict[str, Any]] = {}
    for bar in bars:
        close = _number(bar.get("close_price", bar.get("close")))
        high = _number(bar.get("high_price", bar.get("high")))
        low = _number(bar.get("low_price", bar.get("low")))
        open_price = _number(bar.get("open_price", bar.get("open")))
        time_value = _time_value(bar)
        if (
            time_value is None
            or close is None
            or high is None
            or low is None
            or open_price is None
            or min(close, high, low, open_price) <= 0
            or high < max(open_price, low, close)
            or low > min(open_price, high, close)
        ):
            continue
        volume = _number(bar.get("volume"))
        if volume is not None and volume < 0:
            volume = None
        normalized_by_time[time_value] = {
            "time": time_value,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    return sorted(normalized_by_time.values(), key=lambda item: item["time"])


def _sma(values: Sequence[float | None], period: int) -> list[float | None]:
    result: list[float | None] = []
    window: list[float] = []
    for value in values:
        if value is None:
            window = []
            result.append(None)
            continue
        window.append(value)
        if len(window) > period:
            window.pop(0)
        result.append(sum(window) / period if len(window) == period else None)
    return result


def _ema(values: Sequence[float | None], period: int) -> list[float | None]:
    return ema_sma_seed(list(values), period)


def _wilder_rsi(closes: Sequence[float], period: int) -> list[float | None]:
    return wilder_rsi(list(closes), period)


def _wilder_atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int
) -> list[float | None]:
    true_ranges: list[float] = []
    for index, high in enumerate(highs):
        if index == 0:
            true_ranges.append(high - lows[index])
            continue
        true_ranges.append(
            max(
                high - lows[index],
                abs(high - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    result: list[float | None] = [None] * len(true_ranges)
    if len(true_ranges) < period:
        return result
    current = sum(true_ranges[:period]) / period
    result[period - 1] = current
    for index in range(period, len(true_ranges)):
        current = (current * (period - 1) + true_ranges[index]) / period
        result[index] = current
    return result


def _macd(
    closes: Sequence[float], fast_period: int, slow_period: int, signal_period: int
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    _, _, line, signal, histogram = macd_sma_seed(
        list(closes),
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period,
    )
    return line, signal, histogram


def _pct_difference(value: float | None, reference: float | None) -> float | None:
    if value is None or reference in (None, 0):
        return None
    return (value - reference) / reference * 100


def _latest(values: Sequence[float | None]) -> float | None:
    return values[-1] if values else None


def build_technical_indicators(
    *,
    market: str,
    symbol: str,
    bars: Sequence[Mapping[str, Any]],
    profile: MarketAnalysisProfile,
    freshness_status: str,
    resolved_facts_usable: bool,
    corporate_action_coverage: str = "unknown",
    lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_bars(bars)
    input_bar_count = len(bars)
    normalized_bar_count = len(normalized)
    usability = evaluate_technical_usability(
        bar_count=len(normalized),
        profile=profile,
        freshness_status=freshness_status,
        facts_usable=resolved_facts_usable,
        corporate_action_coverage=corporate_action_coverage,
    )
    if not normalized:
        return {
            "kind": "technical_indicators",
            "schema_version": TECHNICAL_INDICATOR_SCHEMA_VERSION,
            "algorithm_version": TECHNICAL_ALGORITHM_VERSION,
            "market": market,
            "symbol": symbol,
            "timeframe": profile.timeframe,
            "price_basis": profile.price_basis,
            "status": "missing",
            "as_of": None,
            "bar_count": 0,
            "profile": profile.as_dict(),
            "methods": {},
            "warmup": {},
            "period_completeness": {
                "latest_period": "missing",
                "provisional_included": False,
            },
            "current": {},
            "quality": usability,
            "input_quality": {
                "input_bar_count": input_bar_count,
                "normalized_bar_count": normalized_bar_count,
                "skipped_or_duplicate_count": input_bar_count - normalized_bar_count,
            },
            "lineage": dict(lineage or {}),
        }

    closes = [bar["close"] for bar in normalized]
    highs = [bar["high"] for bar in normalized]
    lows = [bar["low"] for bar in normalized]
    volumes = [bar["volume"] for bar in normalized]
    moving_averages = {
        f"ma{period}": _sma(closes, period)
        for period in profile.moving_average_periods
    }
    exponential_moving_averages = {
        f"ema{period}": _ema(closes, period)
        for period in profile.exponential_moving_average_periods
    }
    volume_average = _sma(volumes, profile.volume_average_period)
    rsi = _wilder_rsi(closes, profile.rsi_period)
    atr = _wilder_atr(highs, lows, closes, profile.atr_period)
    macd_line, macd_signal, macd_histogram = _macd(
        closes,
        profile.macd_fast_period,
        profile.macd_slow_period,
        profile.macd_signal_period,
    )
    latest = normalized[-1]
    previous_close = closes[-2] if len(closes) > 1 else None
    ma_values = {key: _latest(values) for key, values in moving_averages.items()}
    ema_values = {
        key: _latest(values) for key, values in exponential_moving_averages.items()
    }
    ma20 = ma_values.get("ma20")
    volume_ma = _latest(volume_average)
    current = {
        "time": latest["time"],
        "open": latest["open"],
        "high": latest["high"],
        "low": latest["low"],
        "close": latest["close"],
        "previous_close": previous_close,
        "change_pct": _pct_difference(latest["close"], previous_close),
        "volume": latest["volume"],
        "moving_averages": ma_values,
        "exponential_moving_averages": ema_values,
        "volume_ma": {f"volume_ma{profile.volume_average_period}": volume_ma},
        "rsi": {f"rsi{profile.rsi_period}": _latest(rsi)},
        "macd": {
            "line": _latest(macd_line),
            "signal": _latest(macd_signal),
            "histogram": _latest(macd_histogram),
        },
        "atr": {f"atr{profile.atr_period}": _latest(atr)},
        "price_vs_ma20_pct": _pct_difference(latest["close"], ma20),
        "volume_vs_ma20_pct": _pct_difference(latest["volume"], volume_ma),
    }
    return {
        "kind": "technical_indicators",
        "schema_version": TECHNICAL_INDICATOR_SCHEMA_VERSION,
        "algorithm_version": TECHNICAL_ALGORITHM_VERSION,
        "market": market,
        "symbol": symbol,
        "timeframe": profile.timeframe,
        "price_basis": profile.price_basis,
        "status": usability["status"],
        "as_of": latest["time"],
        "bar_count": len(normalized),
        "profile": profile.as_dict(),
        "methods": {
            "moving_average": "simple_arithmetic_mean",
            "exponential_moving_average": "sma_seed_recursive_ema",
            "rsi": "wilder_smoothed",
            "atr": "wilder_smoothed_true_range",
            "macd": "sma_seed_recursive_ema",
        },
        "warmup": {
            **{
                f"ma{period}": {
                    "required_bars": period,
                    "available_bars": len(normalized),
                    "ready": len(normalized) >= period,
                }
                for period in profile.moving_average_periods
            },
            f"rsi{profile.rsi_period}": {
                "required_bars": profile.rsi_period + 1,
                "available_bars": len(normalized),
                "ready": len(normalized) >= profile.rsi_period + 1,
            },
            "macd": {
                "required_bars": (
                    profile.macd_slow_period + profile.macd_signal_period - 1
                ),
                "available_bars": len(normalized),
                "ready": len(normalized)
                >= profile.macd_slow_period + profile.macd_signal_period - 1,
            },
            f"atr{profile.atr_period}": {
                "required_bars": profile.atr_period,
                "available_bars": len(normalized),
                "ready": len(normalized) >= profile.atr_period,
            },
        },
        "period_completeness": {
            "latest_period": "completed",
            "provisional_included": False,
        },
        "current": current,
        "quality": usability,
        "input_quality": {
            "input_bar_count": input_bar_count,
            "normalized_bar_count": normalized_bar_count,
            "skipped_or_duplicate_count": input_bar_count - normalized_bar_count,
        },
        "lineage": dict(lineage or {}),
    }


def build_technical_structure(
    *,
    indicators: Mapping[str, Any],
    bars: Sequence[Mapping[str, Any]],
    profile: MarketAnalysisProfile,
) -> dict[str, Any]:
    normalized = _normalize_bars(bars)
    current = indicators.get("current") if isinstance(indicators.get("current"), Mapping) else {}
    moving_averages = (
        current.get("moving_averages")
        if isinstance(current.get("moving_averages"), Mapping)
        else {}
    )
    close = _number(current.get("close"))
    ma5 = _number(moving_averages.get("ma5"))
    ma20 = _number(moving_averages.get("ma20"))
    ma60 = _number(moving_averages.get("ma60"))
    if close is None or ma20 is None:
        trend_state = "insufficient"
    elif close > ma20 and ma5 is not None and ma5 >= ma20 and (ma60 is None or ma20 >= ma60):
        trend_state = "bullish_stack"
    elif close < ma20:
        trend_state = "below_ma20"
    else:
        trend_state = "ma_consolidation"

    recent = normalized[-profile.structure_window :]
    support = min((bar["low"] for bar in recent), default=None)
    resistance = max((bar["high"] for bar in recent), default=None)
    prior = normalized[-(profile.breakout_window + 1) : -1]
    prior_resistance = max((bar["high"] for bar in prior), default=None)
    prior_support = min((bar["low"] for bar in prior), default=None)
    if close is None or not prior:
        breakout_state = "insufficient"
    elif prior_resistance is not None and close > prior_resistance:
        breakout_state = "upside_breakout"
    elif prior_support is not None and close < prior_support:
        breakout_state = "downside_breakdown"
    else:
        breakout_state = "inside_range"

    quality = indicators.get("quality") if isinstance(indicators.get("quality"), Mapping) else {}
    status = str(quality.get("status") or indicators.get("status") or "missing")
    rsi_values = current.get("rsi") if isinstance(current.get("rsi"), Mapping) else {}
    macd_values = current.get("macd") if isinstance(current.get("macd"), Mapping) else {}
    atr_values = current.get("atr") if isinstance(current.get("atr"), Mapping) else {}
    rsi = _number(rsi_values.get(f"rsi{profile.rsi_period}"))
    macd_histogram = _number(macd_values.get("histogram"))
    atr = _number(atr_values.get(f"atr{profile.atr_period}"))
    volume_vs_ma20 = _number(current.get("volume_vs_ma20_pct"))
    counter_evidence: list[str] = []
    if trend_state == "bullish_stack" and macd_histogram is not None and macd_histogram < 0:
        counter_evidence.append("NEGATIVE_MACD_HISTOGRAM")
    if trend_state == "bullish_stack" and rsi is not None and rsi >= 70:
        counter_evidence.append("RSI_OVERHEATED")
    if trend_state == "below_ma20" and macd_histogram is not None and macd_histogram > 0:
        counter_evidence.append("POSITIVE_MACD_HISTOGRAM")
    if breakout_state == "upside_breakout" and (
        volume_vs_ma20 is None or volume_vs_ma20 <= 0
    ):
        counter_evidence.append("BREAKOUT_WITHOUT_VOLUME_CONFIRMATION")
    limitations = list(quality.get("reason_codes") or [])
    if not profile.benchmark_status.startswith("configured"):
        limitations.append("RELATIVE_STRENGTH_BENCHMARK_NOT_CONFIGURED")
    invalidation = {
        "bullish_below": support if trend_state == "bullish_stack" else None,
        "bearish_above": resistance if trend_state == "below_ma20" else None,
        "basis": "recent_structure_window",
    }
    return {
        "kind": "technical_structure",
        "schema_version": TECHNICAL_STRUCTURE_SCHEMA_VERSION,
        "algorithm_version": TECHNICAL_ALGORITHM_VERSION,
        "market": indicators.get("market"),
        "symbol": indicators.get("symbol"),
        "timeframe": profile.timeframe,
        "price_basis": profile.price_basis,
        "status": status,
        "as_of": indicators.get("as_of"),
        "selected_title": trend_state,
        "trend_state": trend_state,
        "breakout_state": breakout_state,
        "current_state": {
            "trend": trend_state,
            "breakout": breakout_state,
            "momentum": {
                "rsi": rsi,
                "macd_histogram": macd_histogram,
            },
            "volatility": {
                "atr": atr,
                "atr_pct": atr / close * 100 if atr is not None and close not in {None, 0} else None,
            },
            "volume_state": (
                "above_average"
                if volume_vs_ma20 is not None and volume_vs_ma20 > 0
                else "below_average"
                if volume_vs_ma20 is not None
                else "unknown"
            ),
        },
        "levels": {
            "support": support,
            "resistance": resistance,
            "prior_support": prior_support,
            "prior_resistance": prior_resistance,
            "window_bars": profile.structure_window,
        },
        "metrics": {
            "price_vs_ma20_pct": current.get("price_vs_ma20_pct"),
            "volume_vs_ma20_pct": current.get("volume_vs_ma20_pct"),
            "day_change_pct": current.get("change_pct"),
        },
        "invalidation": invalidation,
        "counter_evidence": counter_evidence,
        "limitations": list(dict.fromkeys(limitations)),
        "quality": dict(quality),
        "input_quality": dict(indicators.get("input_quality") or {}),
        "lineage": dict(indicators.get("lineage") or {}),
    }


__all__ = [
    "TECHNICAL_ALGORITHM_VERSION",
    "TECHNICAL_INDICATOR_SCHEMA_VERSION",
    "TECHNICAL_STRUCTURE_SCHEMA_VERSION",
    "build_technical_indicators",
    "build_technical_structure",
]
