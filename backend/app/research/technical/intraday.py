"""Backend-owned technical projection for resolved intraday OHLCV points."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from app.research.technical.series import ema_sma_seed, macd_sma_seed, wilder_rsi


INTRADAY_TECHNICAL_ALGORITHM_VERSION = "omi.research.technical.intraday.v1"
INTRADAY_TECHNICAL_PARAMETER_CONTRACT = {
    "ema_fast": 12,
    "ema_slow": 26,
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "vwap_basis": "close_x_interval_volume",
    "session_reset": True,
}


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if parsed == parsed else None
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def enrich_intraday_technical_points(
    points: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Add canonical indicator fields without changing OHLCV or ordering."""

    output = [dict(point) for point in points]
    indices_by_session: dict[str, list[int]] = defaultdict(list)
    for index, point in enumerate(output):
        indices_by_session[str(point.get("session") or "regular")].append(index)

    for indices in indices_by_session.values():
        closes = [
            _number(output[index].get("price", output[index].get("close")))
            for index in indices
        ]
        numeric_closes = [value if value is not None else float("nan") for value in closes]
        ema_fast = ema_sma_seed(numeric_closes, 12)
        ema_slow = ema_sma_seed(numeric_closes, 26)
        _, _, macd, macd_signal, macd_histogram = macd_sma_seed(
            numeric_closes,
            fast_period=12,
            slow_period=26,
            signal_period=9,
        )
        rsi = wilder_rsi(numeric_closes, 14)
        cumulative_price = 0.0
        cumulative_volume = 0.0
        cumulative_weighted_price = 0.0
        for offset, point_index in enumerate(indices):
            point = output[point_index]
            close = closes[offset]
            volume = _number(point.get("volume"))
            finalized = point.get("finalized") is not False
            if close is not None:
                cumulative_price += close
            if close is not None and volume is not None and volume > 0:
                cumulative_volume += volume
                cumulative_weighted_price += close * volume
            point.update(
                {
                    "ema_fast": ema_fast[offset],
                    "ema_slow": ema_slow[offset],
                    "rsi_value": rsi[offset],
                    "macd_value": macd[offset],
                    "macd_signal_value": macd_signal[offset],
                    "macd_histogram_value": macd_histogram[offset],
                    "vwap_value": (
                        cumulative_weighted_price / cumulative_volume
                        if cumulative_volume > 0
                        else None
                    ),
                    "twap_value": (
                        cumulative_price / (offset + 1)
                        if close is not None
                        else None
                    ),
                    "technical_algorithm_version": INTRADAY_TECHNICAL_ALGORITHM_VERSION,
                    "price_basis": "resolved_intraday_bar_close",
                    "calculation_role": "backend_authoritative",
                    "bar_status": "completed" if finalized else "current_partial",
                    "decision_usable": finalized and close is not None,
                    "volume_based_decision_usable": (
                        finalized and close is not None and volume is not None
                    ),
                }
            )
    return output


__all__ = [
    "INTRADAY_TECHNICAL_ALGORITHM_VERSION",
    "INTRADAY_TECHNICAL_PARAMETER_CONTRACT",
    "enrich_intraday_technical_points",
]
