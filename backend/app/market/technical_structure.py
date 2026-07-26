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


def _move_to_level_pct(price: float | None, level: float | None) -> float | None:
    if price in {None, 0} or level is None:
        return None
    return round((level / price - 1) * 100, 4)


def _fmt_number(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    formatted = f"{value:.{digits}f}"
    return formatted.rstrip("0").rstrip(".") if digits > 0 else formatted


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}%"


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


def build_technical_current_state(
    *,
    price: Any,
    moving_average_structure: dict[str, Any],
    change_pct: Any = None,
    volume_ratio: Any = None,
    rsi14: Any = None,
    macd_histogram: Any = None,
    roc12: Any = None,
    mfi14: Any = None,
    adx14: Any = None,
    plus_di14: Any = None,
    minus_di14: Any = None,
    atr_pct: Any = None,
    donchian_position: Any = None,
    support20: Any = None,
    resistance20: Any = None,
    adx_trend_threshold: float = 25.0,
    volume_ratio_threshold: float = 1.5,
    rsi_oversold_threshold: float = 30.0,
    rsi_overheated_threshold: float = 80.0,
    atr_high_volatility_pct: float = 5.0,
) -> dict[str, Any]:
    """Build a compact, explainable snapshot of the current technical state.

    The contract intentionally separates trend, momentum, confirmation, and risk
    instead of compressing correlated indicators into one opaque score.
    """

    normalized_price = _number(price)
    change = _number(change_pct)
    normalized_volume_ratio = _number(volume_ratio)
    normalized_rsi = _number(rsi14)
    normalized_macd = _number(macd_histogram)
    normalized_roc = _number(roc12)
    normalized_mfi = _number(mfi14)
    normalized_adx = _number(adx14)
    normalized_plus_di = _number(plus_di14)
    normalized_minus_di = _number(minus_di14)
    normalized_atr_pct = _number(atr_pct)
    normalized_donchian_position = _number(donchian_position)
    normalized_support = _number(support20)
    normalized_resistance = _number(resistance20)

    price_state = str(moving_average_structure.get("price_state") or "missing")
    alignment = str(moving_average_structure.get("alignment") or "missing")
    positions = (
        moving_average_structure.get("position")
        if isinstance(moving_average_structure.get("position"), dict)
        else {}
    )
    averages = (
        moving_average_structure.get("moving_averages")
        if isinstance(moving_average_structure.get("moving_averages"), dict)
        else {}
    )
    distances = (
        moving_average_structure.get("distance_pct")
        if isinstance(moving_average_structure.get("distance_pct"), dict)
        else {}
    )

    available_positions = {
        key: value
        for key, value in positions.items()
        if value in {"above", "below", "at"}
    }
    below_count = sum(value == "below" for value in available_positions.values())
    above_count = sum(value == "above" for value in available_positions.values())
    available_count = len(available_positions)
    if available_count and below_count == available_count:
        position_label = f"{below_count}/{available_count} 均線下方"
    elif available_count and above_count == available_count:
        position_label = f"{above_count}/{available_count} 均線上方"
    elif available_count:
        position_label = f"{below_count}/{available_count} 均線下方"
    else:
        position_label = "均線位置資料不足"

    normalized_averages = {
        key: _number(value)
        for key, value in averages.items()
        if _number(value) is not None
    }
    ordered_average_keys = [
        key
        for key, _ in sorted(
            normalized_averages.items(),
            key=lambda item: item[1],
        )
    ]
    order_label = (
        " < ".join(key.upper() for key in ordered_average_keys)
        if ordered_average_keys
        else "均線排列資料不足"
    )
    alignment_label = (
        "均線排列轉換中"
        if alignment == "mixed"
        else str(moving_average_structure.get("alignment_label") or "均線排列資料不足")
    )

    has_trend_strength = (
        normalized_adx is not None and normalized_adx >= adx_trend_threshold
    )
    bearish_direction = (
        normalized_minus_di is not None
        and normalized_plus_di is not None
        and normalized_minus_di > normalized_plus_di
    )
    bullish_direction = (
        normalized_plus_di is not None
        and normalized_minus_di is not None
        and normalized_plus_di > normalized_minus_di
    )

    if price_state == "below_all" and has_trend_strength and bearish_direction:
        headline = {
            "key": "bearish_trend",
            "label": "空方趨勢延續",
            "tone": "negative",
        }
    elif price_state == "above_all" and has_trend_strength and bullish_direction:
        headline = {
            "key": "bullish_trend",
            "label": "多方趨勢延續",
            "tone": "positive",
        }
    elif price_state == "below_all" or alignment == "bearish":
        headline = {
            "key": "bearish_structure",
            "label": "弱勢結構",
            "tone": "negative",
        }
    elif price_state == "above_all" or alignment == "bullish":
        headline = {
            "key": "bullish_structure",
            "label": "偏多結構",
            "tone": "positive",
        }
    elif price_state == "mixed":
        headline = {
            "key": "transitioning_structure",
            "label": "均線結構轉換中",
            "tone": "warning",
        }
    else:
        headline = {
            "key": "insufficient_structure",
            "label": "結構資料不足",
            "tone": "neutral",
        }

    bearish_momentum = (
        (normalized_macd is not None and normalized_macd < 0)
        or (normalized_roc is not None and normalized_roc < 0)
    )
    bullish_momentum = (
        (normalized_macd is not None and normalized_macd > 0)
        and (normalized_roc is None or normalized_roc >= 0)
    )
    if normalized_rsi is not None and normalized_rsi <= rsi_oversold_threshold:
        qualifier = (
            {
                "key": "oversold_not_reversed",
                "label": "超賣但尚未止跌",
                "tone": "warning",
            }
            if bearish_momentum
            else {
                "key": "oversold_rebound_watch",
                "label": "超賣反彈觀察",
                "tone": "warning",
            }
        )
    elif normalized_rsi is not None and normalized_rsi >= rsi_overheated_threshold:
        qualifier = {
            "key": "overheated_pullback_risk",
            "label": "過熱，留意拉回",
            "tone": "warning",
        }
    elif bearish_momentum:
        qualifier = {
            "key": "weak_momentum",
            "label": "動能仍偏弱",
            "tone": "negative",
        }
    elif bullish_momentum:
        qualifier = {
            "key": "strong_momentum",
            "label": "動能仍偏強",
            "tone": "positive",
        }
    else:
        qualifier = {
            "key": "momentum_confirmation_pending",
            "label": "等待動能確認",
            "tone": "neutral",
        }

    levels: list[dict[str, Any]] = []
    if normalized_support is not None:
        levels.append(
            {
                "key": "support20",
                "role": "risk" if normalized_price is None or normalized_support <= normalized_price else "broken_support",
                "label": "20日低點／風險線",
                "price": normalized_support,
                "move_required_pct": _move_to_level_pct(normalized_price, normalized_support),
                "tone": "negative",
            }
        )

    moving_average_levels: list[dict[str, Any]] = []
    for key in ("ma5", "ma20", "ma60"):
        level = _number(averages.get(key))
        if level is None:
            continue
        move_required_pct = _move_to_level_pct(normalized_price, level)
        role = (
            "reclaim"
            if move_required_pct is not None and move_required_pct > 0
            else "support"
            if move_required_pct is not None and move_required_pct < 0
            else "current"
        )
        moving_average_levels.append(
            {
                "key": key,
                "role": role,
                "label": f"{'站回' if role == 'reclaim' else '守住'} {key.upper()}",
                "price": level,
                "move_required_pct": move_required_pct,
                "reference_distance_pct": _number(distances.get(key)),
                "tone": "negative" if role == "reclaim" else "positive",
            }
        )
    levels.extend(
        sorted(
            moving_average_levels,
            key=lambda item: item["price"],
        )
    )
    if (
        normalized_resistance is not None
        and normalized_price is not None
        and normalized_resistance > normalized_price
        and not any(item["role"] == "reclaim" for item in moving_average_levels)
    ):
        levels.append(
            {
                "key": "resistance20",
                "role": "resistance",
                "label": "20日壓力",
                "price": normalized_resistance,
                "move_required_pct": _move_to_level_pct(
                    normalized_price,
                    normalized_resistance,
                ),
                "tone": "warning",
            }
        )

    trend_direction_text = (
        f"-DI {_fmt_number(normalized_minus_di)} > +DI {_fmt_number(normalized_plus_di)}，跌勢具方向性"
        if has_trend_strength and bearish_direction
        else f"+DI {_fmt_number(normalized_plus_di)} > -DI {_fmt_number(normalized_minus_di)}，漲勢具方向性"
        if has_trend_strength and bullish_direction
        else "趨勢方向仍待確認"
    )
    trend_summary = (
        f"{position_label}；{order_label}。"
        f"ADX {_fmt_number(normalized_adx)}，{trend_direction_text}。"
    )

    momentum_parts = [
        f"RSI {_fmt_number(normalized_rsi)}",
        f"MACD H {_fmt_number(normalized_macd)}",
        f"ROC12 {_fmt_pct(normalized_roc)}",
    ]
    if normalized_mfi is not None:
        momentum_parts.append(f"MFI {_fmt_number(normalized_mfi)}")
    momentum_summary = f"{'、'.join(momentum_parts)}；{qualifier['label']}。"

    volume_is_expanded = (
        normalized_volume_ratio is not None
        and normalized_volume_ratio >= volume_ratio_threshold
    )
    if volume_is_expanded and change is not None and change < 0:
        volume_state = {
            "key": "down_on_high_volume",
            "label": "放量下跌",
            "tone": "negative",
        }
        volume_interpretation = "偏向賣壓確認"
    elif volume_is_expanded and change is not None and change > 0:
        volume_state = {
            "key": "up_on_high_volume",
            "label": "放量上漲",
            "tone": "positive",
        }
        volume_interpretation = "偏向買盤確認"
    else:
        volume_state = {
            "key": "volume_not_confirmed",
            "label": "量價未明顯確認",
            "tone": "neutral",
        }
        volume_interpretation = "量能尚未形成明確確認"
    volume_summary = (
        f"價格 {_fmt_pct(change)}，成交量為 20 日均量 "
        f"{_fmt_number(normalized_volume_ratio)} 倍；{volume_interpretation}。"
    )

    if (
        normalized_donchian_position is not None
        and normalized_donchian_position <= 20
    ):
        range_state = {
            "key": "near_range_bottom",
            "label": "接近20日區間底部",
            "tone": "warning",
        }
    elif (
        normalized_donchian_position is not None
        and normalized_donchian_position >= 80
    ):
        range_state = {
            "key": "near_range_top",
            "label": "接近20日區間頂部",
            "tone": "warning",
        }
    else:
        range_state = {
            "key": "range_middle",
            "label": "位於20日區間中段",
            "tone": "neutral",
        }
    high_volatility = (
        normalized_atr_pct is not None
        and normalized_atr_pct >= atr_high_volatility_pct
    )
    risk_summary = (
        f"位於 20 日區間第 {_fmt_number(normalized_donchian_position, 0)}% 位置"
        f"{f'，20 日低點 {_fmt_number(normalized_support)}' if normalized_support is not None else ''}；"
        f"ATR {_fmt_pct(normalized_atr_pct)}"
        f"{'，波動偏高' if high_volatility else ''}。"
    )

    evidence = [
        {
            "key": "trend",
            "label": "趨勢證據",
            "state_key": headline["key"],
            "state_label": headline["label"],
            "tone": headline["tone"],
            "summary": trend_summary,
            "metrics": {
                "adx14": normalized_adx,
                "plus_di14": normalized_plus_di,
                "minus_di14": normalized_minus_di,
            },
        },
        {
            "key": "momentum",
            "label": "動能與超賣",
            "state_key": qualifier["key"],
            "state_label": qualifier["label"],
            "tone": qualifier["tone"],
            "summary": momentum_summary,
            "metrics": {
                "rsi14": normalized_rsi,
                "macd_histogram": normalized_macd,
                "roc12": normalized_roc,
                "mfi14": normalized_mfi,
            },
        },
        {
            "key": "volume",
            "label": "量價確認",
            "state_key": volume_state["key"],
            "state_label": volume_state["label"],
            "tone": volume_state["tone"],
            "summary": volume_summary,
            "metrics": {
                "change_pct": change,
                "volume_ratio": normalized_volume_ratio,
            },
        },
        {
            "key": "risk",
            "label": "風險與區間",
            "state_key": range_state["key"],
            "state_label": range_state["label"],
            "tone": "warning" if high_volatility else range_state["tone"],
            "summary": risk_summary,
            "metrics": {
                "atr_pct": normalized_atr_pct,
                "donchian_position": normalized_donchian_position,
                "support20": normalized_support,
                "resistance20": normalized_resistance,
            },
        },
    ]

    reclaim_levels = sorted(
        (item for item in moving_average_levels if item["role"] == "reclaim"),
        key=lambda item: item["move_required_pct"],
    )
    next_conditions: list[dict[str, Any]] = []
    if reclaim_levels:
        first_reclaim = reclaim_levels[0]
        next_conditions.append(
            {
                "key": "first_reclaim",
                "label": (
                    f"先站回 {first_reclaim['key'].upper()} "
                    f"{_fmt_number(first_reclaim['price'])}，並確認不再破低"
                ),
                "tone": "neutral",
                "level_key": first_reclaim["key"],
                "price": first_reclaim["price"],
            }
        )
        structural_reclaim = next(
            (
                item
                for preferred_key in ("ma60", "ma20")
                for item in reclaim_levels
                if item["key"] == preferred_key and item["key"] != first_reclaim["key"]
            ),
            None,
        )
        if structural_reclaim is not None:
            next_conditions.append(
                {
                    "key": "structure_repair",
                    "label": (
                        f"站回 {structural_reclaim['key'].upper()} "
                        f"{_fmt_number(structural_reclaim['price'])}，視為初步結構修復"
                    ),
                    "tone": "positive",
                    "level_key": structural_reclaim["key"],
                    "price": structural_reclaim["price"],
                }
            )
    else:
        support_levels = sorted(
            (item for item in moving_average_levels if item["role"] == "support"),
            key=lambda item: abs(item["move_required_pct"]),
        )
        if support_levels:
            first_support = support_levels[0]
            next_conditions.append(
                {
                    "key": "first_defense",
                    "label": (
                        f"守住 {first_support['key'].upper()} "
                        f"{_fmt_number(first_support['price'])}，維持目前結構"
                    ),
                    "tone": "positive",
                    "level_key": first_support["key"],
                    "price": first_support["price"],
                }
            )
    if (
        normalized_support is not None
        and normalized_price is not None
        and normalized_support < normalized_price
    ):
        next_conditions.append(
            {
                "key": "risk_break",
                "label": (
                    f"跌破 20 日低點 {_fmt_number(normalized_support)} 且量能放大，"
                    "弱勢延續"
                ),
                "tone": "negative",
                "level_key": "support20",
                "price": normalized_support,
            }
        )

    return {
        "version": "tw_technical_current_state_v1",
        "headline": headline,
        "qualifier": qualifier,
        "summary": f"{headline['label']}，{qualifier['label']}",
        "position": {
            "price": normalized_price,
            "label": position_label,
            "below_count": below_count,
            "above_count": above_count,
            "available_count": available_count,
            "order": ordered_average_keys,
            "order_label": order_label,
            "alignment": alignment,
            "alignment_label": alignment_label,
            "distance_pct": {
                key: _number(value)
                for key, value in distances.items()
            },
        },
        "levels": levels,
        "evidence": evidence,
        "next_conditions": next_conditions,
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
