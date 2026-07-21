from __future__ import annotations

import math
from typing import Any, Iterable


PRICE_MOVING_AVERAGE_SIGNAL_KEYS = frozenset(
    {
        "above_ma5",
        "below_ma5",
        "above_ma20",
        "below_ma20",
        "above_ma60",
        "below_ma60",
        "cross_above_ma20",
        "cross_below_ma20",
        "cross_above_ma60",
        "cross_below_ma60",
    }
)
PRICE_RANGE_SIGNAL_KEYS = frozenset(
    {
        "donchian_breakout",
        "donchian_breakdown",
        "structure_support_break",
        "structure_resistance_breakout",
        "near_support",
        "near_resistance",
        "bollinger_breakout",
        "bollinger_breakdown",
    }
)

MOVING_AVERAGE_SIGNAL_LABELS = {
    "above_ma5": "站在 MA5 之上",
    "below_ma5": "位於 MA5 下方",
    "above_ma20": "站在 MA20 之上",
    "below_ma20": "跌破 MA20",
    "above_ma60": "站在 MA60 之上",
    "below_ma60": "失守 MA60",
    "cross_above_ma20": "重新站上 MA20",
    "cross_below_ma20": "跌破 MA20",
    "cross_above_ma60": "重新站上 MA60",
    "cross_below_ma60": "跌破 MA60",
}

MOVING_AVERAGE_SIGNAL_SCORES = {
    "above_ma5": 1,
    "below_ma5": -1,
    "above_ma20": 1,
    "below_ma20": -1,
    "above_ma60": 2,
    "below_ma60": -2,
    "cross_above_ma20": 2,
    "cross_below_ma20": -2,
    "cross_above_ma60": 3,
    "cross_below_ma60": -3,
}
PRICE_RANGE_SIGNAL_LABELS = {
    "donchian_breakout": "突破 20 日高",
    "donchian_breakdown": "跌破 20 日低",
    "structure_support_break": "跌破 20 日支撐",
    "structure_resistance_breakout": "突破 20 日壓力",
    "near_support": "貼近 20 日支撐",
    "near_resistance": "貼近 20 日壓力",
    "bollinger_breakout": "突破布林上緣",
    "bollinger_breakdown": "跌破布林下緣",
}
PRICE_RANGE_SIGNAL_SCORES = {
    "donchian_breakout": 2,
    "donchian_breakdown": -2,
    "structure_support_break": -2,
    "structure_resistance_breakout": 2,
    "near_support": 0,
    "near_resistance": 0,
    "bollinger_breakout": 2,
    "bollinger_breakdown": -2,
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _distance_pct(price: float | None, reference: float | None) -> float | None:
    if price is None or reference in {None, 0}:
        return None
    return round((price - reference) / reference * 100, 4)


def build_moving_average_structure(
    *,
    price: Any,
    ma5: Any = None,
    ma20: Any = None,
    ma60: Any = None,
) -> dict[str, Any]:
    normalized_price = _number(price)
    averages = {
        "ma5": _number(ma5),
        "ma20": _number(ma20),
        "ma60": _number(ma60),
    }
    available = {key: value for key, value in averages.items() if value is not None}
    distances = {
        key: _distance_pct(normalized_price, value)
        for key, value in averages.items()
    }
    positions = {
        key: (
            "above"
            if normalized_price is not None and value is not None and normalized_price > value
            else "below"
            if normalized_price is not None and value is not None and normalized_price < value
            else "at"
            if normalized_price is not None and value is not None
            else "missing"
        )
        for key, value in averages.items()
    }

    if len(available) == 3 and all(positions[key] == "above" for key in averages):
        price_state = "above_all"
        price_state_label = "站上 MA5/MA20/MA60"
    elif len(available) == 3 and all(positions[key] == "below" for key in averages):
        price_state = "below_all"
        price_state_label = "失守 MA5/MA20/MA60"
    elif available:
        price_state = "mixed"
        below_labels = [key.upper() for key, value in positions.items() if value == "below"]
        price_state_label = (
            f"位於 {'/'.join(below_labels)} 下方" if below_labels else "均線附近整理"
        )
    else:
        price_state = "missing"
        price_state_label = "均線資料不足"

    if all(averages[key] is not None for key in ("ma5", "ma20", "ma60")):
        if averages["ma5"] > averages["ma20"] > averages["ma60"]:
            alignment = "bullish"
            alignment_label = "多頭排列"
        elif averages["ma5"] < averages["ma20"] < averages["ma60"]:
            alignment = "bearish"
            alignment_label = "空頭排列"
        else:
            alignment = "mixed"
            alignment_label = "均線糾結／轉換中"
    else:
        alignment = "missing"
        alignment_label = "均線排列資料不足"

    primary_key = (
        "ma60"
        if positions["ma60"] == "below"
        else "ma20"
        if averages["ma20"] is not None
        else "ma5"
        if averages["ma5"] is not None
        else None
    )

    return {
        "price": normalized_price,
        "moving_averages": averages,
        "distance_pct": distances,
        "position": positions,
        "price_state": price_state,
        "price_state_label": price_state_label,
        "alignment": alignment,
        "alignment_label": alignment_label,
        "primary_reference": primary_key,
        "primary_distance_pct": distances.get(primary_key) if primary_key else None,
    }


def _price_signal(key: str, *, price: float, reference: float) -> dict[str, Any]:
    bullish = key in {
        "above_ma5",
        "above_ma20",
        "above_ma60",
        "cross_above_ma20",
        "cross_above_ma60",
    }
    is_cross = key.startswith("cross_")
    average_label = key.rsplit("ma", 1)[-1]
    return {
        "key": key,
        "label": MOVING_AVERAGE_SIGNAL_LABELS[key],
        "direction": "bullish" if bullish else "bearish",
        "level": "strong" if is_cross else "warning" if not bullish else "info",
        "message": (
            f"價格由均線另一側穿越 MA{average_label}。"
            if is_cross
            else f"價格目前位於 MA{average_label} {'之上' if bullish else '下方'}。"
        ),
        "value": price,
        "reference": reference,
    }


def build_price_moving_average_signals(
    *,
    price: Any,
    ma5: Any = None,
    ma20: Any = None,
    ma60: Any = None,
    previous_price: Any = None,
    previous_ma20: Any = None,
    previous_ma60: Any = None,
) -> tuple[list[dict[str, Any]], int]:
    normalized_price = _number(price)
    if normalized_price is None:
        return [], 0

    averages = {
        5: _number(ma5),
        20: _number(ma20),
        60: _number(ma60),
    }
    signals: list[dict[str, Any]] = []

    for window, reference in averages.items():
        if reference is None or normalized_price == reference:
            continue
        key = f"{'above' if normalized_price > reference else 'below'}_ma{window}"
        signals.append(_price_signal(key, price=normalized_price, reference=reference))

    normalized_previous_price = _number(previous_price)
    previous_references = {
        20: _number(previous_ma20),
        60: _number(previous_ma60),
    }
    for window in (20, 60):
        reference = averages[window]
        previous_reference = previous_references[window]
        if (
            reference is None
            or previous_reference is None
            or normalized_previous_price is None
        ):
            continue
        if normalized_previous_price <= previous_reference and normalized_price > reference:
            key = f"cross_above_ma{window}"
            signals.append(_price_signal(key, price=normalized_price, reference=reference))
        elif normalized_previous_price >= previous_reference and normalized_price < reference:
            key = f"cross_below_ma{window}"
            signals.append(_price_signal(key, price=normalized_price, reference=reference))

    return signals, moving_average_signal_score(signal["key"] for signal in signals)


def moving_average_signal_score(keys: Iterable[str]) -> int:
    return sum(MOVING_AVERAGE_SIGNAL_SCORES.get(str(key), 0) for key in keys)


def build_price_range_signals(
    *,
    price: Any,
    support: Any = None,
    resistance: Any = None,
    donchian_upper: Any = None,
    donchian_lower: Any = None,
    bollinger_upper: Any = None,
    bollinger_lower: Any = None,
    near_threshold_pct: float = 1.5,
) -> tuple[list[dict[str, Any]], int]:
    normalized_price = _number(price)
    if normalized_price is None:
        return [], 0

    normalized_levels = {
        "support": _number(support),
        "resistance": _number(resistance),
        "donchian_upper": _number(donchian_upper),
        "donchian_lower": _number(donchian_lower),
        "bollinger_upper": _number(bollinger_upper),
        "bollinger_lower": _number(bollinger_lower),
    }
    conditions = [
        ("donchian_breakout", normalized_levels["donchian_upper"], "above"),
        ("donchian_breakdown", normalized_levels["donchian_lower"], "below"),
        ("structure_support_break", normalized_levels["support"], "below"),
        ("structure_resistance_breakout", normalized_levels["resistance"], "above"),
        ("bollinger_breakout", normalized_levels["bollinger_upper"], "above"),
        ("bollinger_breakdown", normalized_levels["bollinger_lower"], "below"),
    ]
    signals: list[dict[str, Any]] = []
    for key, reference, direction in conditions:
        if reference is None:
            continue
        matched = normalized_price > reference if direction == "above" else normalized_price < reference
        if not matched:
            continue
        bullish = direction == "above"
        signals.append(
            {
                "key": key,
                "label": PRICE_RANGE_SIGNAL_LABELS[key],
                "direction": "bullish" if bullish else "bearish",
                "level": "strong",
                "message": f"價格{'突破' if bullish else '跌破'} {reference:g}。",
                "value": normalized_price,
                "reference": reference,
            }
        )

    has_structure_break = any(
        signal["key"] in {"structure_support_break", "structure_resistance_breakout"}
        for signal in signals
    )
    if not has_structure_break:
        for key, level_key in (("near_support", "support"), ("near_resistance", "resistance")):
            reference = normalized_levels[level_key]
            if reference in {None, 0}:
                continue
            distance_pct = abs(normalized_price - reference) / reference * 100
            if distance_pct <= near_threshold_pct:
                signals.append(
                    {
                        "key": key,
                        "label": PRICE_RANGE_SIGNAL_LABELS[key],
                        "direction": "neutral",
                        "level": "info",
                        "message": f"價格距 {reference:g} 約 {distance_pct:.2f}%。",
                        "value": normalized_price,
                        "reference": reference,
                    }
                )
                break

    return signals, price_range_signal_score(signal["key"] for signal in signals)


def price_range_signal_score(keys: Iterable[str]) -> int:
    return sum(PRICE_RANGE_SIGNAL_SCORES.get(str(key), 0) for key in keys)
