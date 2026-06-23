from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from statistics import mean, pstdev
from typing import Any


ALLOWED_TECHNICAL_RADAR_MODES = {
    "action",
    "surge",
    "breakout",
    "volume",
    "overheat",
    "weakness",
    "risk",
    "momentum",
    "all",
}

BUCKET_META = [
    {
        "key": "surge_up",
        "label": "Sharp surge",
        "description": "Large move up based on OHLCV-only data.",
    },
    {
        "key": "selloff_risk",
        "label": "Selloff risk",
        "description": "Large move down based on OHLCV-only data.",
    },
    {
        "key": "overheated",
        "label": "Overheated",
        "description": "Price is stretched versus short-term technical levels.",
    },
    {
        "key": "volatility_risk",
        "label": "Volatility risk",
        "description": "Recent range volatility is elevated.",
    },
    {
        "key": "support_break",
        "label": "Support break",
        "description": "Price broke a moving-average or 20-day support level.",
    },
    {
        "key": "volume_down",
        "label": "Volume-price weakness",
        "description": "Volume expanded while price moved lower.",
    },
    {
        "key": "bearish_momentum",
        "label": "Momentum weakening",
        "description": "OHLCV momentum is weakening.",
    },
    {
        "key": "breakout_high",
        "label": "Breakout confirmation",
        "description": "Price broke a 20-day high or resistance level.",
    },
    {
        "key": "trend_reclaim",
        "label": "Trend reclaim",
        "description": "Price reclaimed a moving-average trend level.",
    },
    {
        "key": "volume_up",
        "label": "Volume-price attack",
        "description": "Volume expanded while price moved higher.",
    },
    {
        "key": "volume",
        "label": "Volume anomaly",
        "description": "Volume expanded without a clean directional setup.",
    },
    {
        "key": "compression_watch",
        "label": "Compression watch",
        "description": "Bollinger-style bandwidth is compressed.",
    },
    {
        "key": "pullback",
        "label": "Strong-trend pullback",
        "description": "Price is pulling back while the short trend is still constructive.",
    },
    {
        "key": "momentum",
        "label": "Trend continuation",
        "description": "OHLCV trend signals remain constructive.",
    },
    {
        "key": "quiet",
        "label": "No clear signal",
        "description": "No strong OHLCV-only signal is available.",
    },
    {
        "key": "no_data",
        "label": "Missing data",
        "description": "Insufficient daily OHLCV history.",
    },
]
BUCKET_META_BY_KEY = {bucket["key"]: bucket for bucket in BUCKET_META}
BUCKET_ORDER = {bucket["key"]: index for index, bucket in enumerate(BUCKET_META)}

MODE_BUCKETS = {
    "surge": {"surge_up", "overheated"},
    "breakout": {"breakout_high", "trend_reclaim", "compression_watch"},
    "volume": {"volume_up", "volume_down", "volume"},
    "overheat": {"overheated", "volatility_risk", "surge_up"},
    "weakness": {"selloff_risk", "support_break", "volume_down", "bearish_momentum"},
    "risk": {"selloff_risk", "support_break", "volume_down", "bearish_momentum", "overheated", "volatility_risk"},
    "momentum": {"breakout_high", "trend_reclaim", "volume_up", "pullback", "momentum"},
}

DATA_LIMITATIONS = [
    "OHLCV technical radar only; does not include local institutional flow, broker branches, news, or full fundamental coverage.",
]


@dataclass(frozen=True)
class TechnicalRadarBar:
    trade_date: date | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _int_value(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def _date_value(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _mean(values: list[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None and math.isfinite(value)]
    if not cleaned:
        return None
    return mean(cleaned)


def _pct_change(value: float | None, reference: float | None) -> float | None:
    if value is None or reference in (None, 0):
        return None
    return ((value - reference) / reference) * 100


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _sorted_bars(history: list[TechnicalRadarBar]) -> list[TechnicalRadarBar]:
    return sorted(
        [bar for bar in history if bar.trade_date is not None and bar.close is not None],
        key=lambda bar: bar.trade_date or date.min,
    )


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    deltas = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    recent = deltas[-period:]
    gains = [max(delta, 0.0) for delta in recent]
    losses = [abs(min(delta, 0.0)) for delta in recent]
    average_gain = mean(gains)
    average_loss = mean(losses)
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def _atr(bars: list[TechnicalRadarBar], period: int = 14) -> float | None:
    if len(bars) < 2:
        return None
    true_ranges: list[float] = []
    for index in range(1, len(bars)):
        current = bars[index]
        previous = bars[index - 1]
        if current.high is None or current.low is None or previous.close is None:
            continue
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    if not true_ranges:
        return None
    return mean(true_ranges[-period:])


def _bucket_accepts_mode(mode: str, bucket: str) -> bool:
    if mode == "all":
        return True
    if mode == "action":
        return bucket not in {"quiet", "no_data"}
    return bucket in MODE_BUCKETS.get(mode, set())


def _bucket_summary(items: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(item.get("bucket") or "")
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "key": bucket["key"],
            "label": bucket["label"],
            "description": bucket["description"],
            "count": counts.get(bucket["key"], 0),
        }
        for bucket in BUCKET_META
        if _bucket_accepts_mode(mode, bucket["key"])
    ]


def _price_levels(
    *,
    bucket: str,
    close: float | None,
    ma20: float | None,
    support: float | None,
    resistance: float | None,
    atr14: float | None,
) -> dict[str, Any]:
    key_level = None
    key_level_label = None
    if bucket in {"support_break", "selloff_risk", "volume_down", "bearish_momentum"}:
        key_level = support if support is not None else ma20
        key_level_label = "invalidationSupport"
    elif bucket in {"breakout_high", "volume_up", "surge_up", "overheated"}:
        key_level = resistance if resistance is not None else ma20
        key_level_label = "breakoutResistance"
    elif bucket in {"trend_reclaim", "pullback", "momentum"}:
        key_level = ma20
        key_level_label = "reclaimResistance"

    atr_pct = _pct_change((close or 0) + (atr14 or 0), close) if close else None
    return {
        "support": _round(support, 4),
        "resistance": _round(resistance, 4),
        "ma20": _round(ma20, 4),
        "atr14": _round(atr14, 4),
        "atr_pct": _round(atr_pct, 4),
        "key_level": _round(key_level, 4),
        "key_level_label": key_level_label,
    }


def _technical_grade(score: float) -> tuple[str, str, str]:
    if score >= 70:
        return (
            "strong",
            "Strong signal",
            "High OHLCV evidence score within this radar batch.",
        )
    if score >= 45:
        return (
            "medium",
            "Medium signal",
            "Meaningful OHLCV setup that still needs confirmation.",
        )
    return (
        "watch",
        "Watch",
        "Early or lower-priority OHLCV setup.",
    )


def _make_no_data_item(row: dict[str, Any], target_trade_date: date | None) -> dict[str, Any]:
    symbol = str(row.get("symbol") or row.get("stock_id") or "").strip()
    trade_date = _date_value(row.get("trade_date"))
    stale = bool(target_trade_date and trade_date and trade_date < target_trade_date)
    return {
        "rank": 0,
        "source_rank": row.get("rank"),
        "bucket": "no_data",
        "bucket_label": BUCKET_META_BY_KEY["no_data"]["label"],
        "urgency": "low",
        "priority_score": 0.0,
        "technical_evidence_score": 0.0,
        "technical_score": 0.0,
        "technical_grade": "watch",
        "technical_grade_label": "Watch",
        "technical_grade_description": "Insufficient OHLCV history.",
        "direction": "neutral",
        "direction_label": "Neutral",
        "setup_label": "Missing data",
        "timing_label": "Backfill first",
        "risk_label": "Data gap",
        "factor_scores": {},
        "price_levels": {},
        "technical_notes": [],
        "action_label": "Backfill data first",
        "reason": "Insufficient daily OHLCV bars for technical radar.",
        "stock_id": symbol,
        "stock_name": row.get("security_name") or row.get("stock_name"),
        "time": row.get("time"),
        "trade_date": trade_date,
        "close": _number(row.get("close")),
        "volume": _int_value(row.get("volume")),
        "change": _number(row.get("change")),
        "previous_close": _number(row.get("previous_close")),
        "change_pct": _number(row.get("change_pct")),
        "limit_status": None,
        "score": 0,
        "status": row.get("status") or "no_data",
        "signal_count": 0,
        "signal_keys": [],
        "matched_signal_keys": [],
        "matched_signal_labels": [],
        "signal_labels": [],
        "primary_signal_key": None,
        "primary_signal_label": None,
        "indicator_snapshot": {},
        "context_snapshot": {},
        "context_signals": [],
        "context_summary": "OHLCV-only technical radar has insufficient history.",
        "context_score": 0.0,
        "stale": stale,
        "error_message": row.get("error_message"),
    }


def _radar_item(
    *,
    row: dict[str, Any],
    history: list[TechnicalRadarBar],
    target_trade_date: date | None,
) -> dict[str, Any]:
    bars = _sorted_bars(history)
    close = _number(row.get("close"))
    previous_close = _number(row.get("previous_close"))
    volume = _int_value(row.get("volume"))

    if bars:
        latest_bar = bars[-1]
        close = close if close is not None else latest_bar.close
        volume = volume if volume is not None else latest_bar.volume
        if previous_close is None and len(bars) >= 2:
            previous_close = bars[-2].close

    if len(bars) < 2 or close is None:
        return _make_no_data_item(row, target_trade_date)

    trade_date = _date_value(row.get("trade_date")) or bars[-1].trade_date
    stale = bool(target_trade_date and trade_date and trade_date < target_trade_date)
    change = _number(row.get("change"))
    if change is None and previous_close is not None:
        change = close - previous_close
    change_pct = _number(row.get("change_pct"))
    if change_pct is None:
        change_pct = _pct_change(close, previous_close)

    closes = [bar.close for bar in bars if bar.close is not None]
    ma5 = _mean(closes[-5:])
    ma20 = _mean(closes[-20:])
    ma60 = _mean(closes[-60:])
    previous_ma20 = _mean(closes[-21:-1]) if len(closes) >= 21 else _mean(closes[:-1][-20:])
    prior_bars = bars[:-1]
    prior20 = prior_bars[-20:]
    high20 = max((bar.high for bar in prior20 if bar.high is not None), default=None)
    low20 = min((bar.low for bar in prior20 if bar.low is not None), default=None)
    volume_ma5 = _mean([float(bar.volume) for bar in prior_bars[-5:] if bar.volume is not None])
    volume_ma20 = _mean([float(bar.volume) for bar in prior20 if bar.volume is not None])
    volume_ratio = (volume / volume_ma20) if volume is not None and volume_ma20 not in (None, 0) else None
    rsi14 = _rsi(closes[-15:]) if len(closes) >= 15 else None
    roc10 = _pct_change(close, closes[-11]) if len(closes) >= 11 else None
    atr14 = _atr(bars[-15:])
    atr_pct = (atr14 / close) * 100 if atr14 is not None and close else None
    bollinger_upper = None
    bollinger_lower = None
    bollinger_width_pct = None
    if len(closes) >= 20:
        recent20 = closes[-20:]
        basis = mean(recent20)
        deviation = pstdev(recent20)
        bollinger_upper = basis + (2 * deviation)
        bollinger_lower = basis - (2 * deviation)
        if basis:
            bollinger_width_pct = ((bollinger_upper - bollinger_lower) / basis) * 100

    signals: list[str] = []
    direction_score = 0
    evidence_score = 0.0

    if change_pct is not None:
        if change_pct > 0:
            signals.append("price_up")
            direction_score += 1
        elif change_pct < 0:
            signals.append("price_down")
            direction_score -= 1

    if ma20 is not None:
        if close >= ma20:
            signals.append("above_ma20")
            direction_score += 1
        else:
            signals.append("below_ma20")
            direction_score -= 1

    if ma5 is not None and ma20 is not None:
        if ma5 >= ma20:
            signals.append("ma5_above_ma20")
            direction_score += 1
        else:
            signals.append("ma5_below_ma20")
            direction_score -= 1

    if ma20 is not None and ma60 is not None:
        if ma20 >= ma60:
            signals.append("ma20_above_ma60")
            direction_score += 1
        else:
            signals.append("ma20_below_ma60")
            direction_score -= 1

    cross_above_ma20 = (
        previous_close is not None
        and previous_ma20 is not None
        and ma20 is not None
        and previous_close <= previous_ma20
        and close > ma20
    )
    cross_below_ma20 = (
        previous_close is not None
        and previous_ma20 is not None
        and ma20 is not None
        and previous_close >= previous_ma20
        and close < ma20
    )
    if cross_above_ma20:
        signals.append("cross_above_ma20")
        direction_score += 2
        evidence_score += 1.5
    if cross_below_ma20:
        signals.append("cross_below_ma20")
        direction_score -= 2
        evidence_score += 1.5

    breakout = high20 is not None and close > high20
    breakdown = low20 is not None and close < low20
    if breakout:
        signals.extend(["donchian_breakout", "structure_resistance_breakout"])
        direction_score += 3
        evidence_score += 2.5
    if breakdown:
        signals.extend(["donchian_breakdown", "structure_support_break"])
        direction_score -= 3
        evidence_score += 2.5

    near_support = low20 is not None and close >= low20 and abs(close - low20) / close <= 0.02
    near_resistance = high20 is not None and close <= high20 and abs(high20 - close) / close <= 0.02
    if near_support:
        signals.append("near_support")
    if near_resistance:
        signals.append("near_resistance")

    volume_expansion = volume_ratio is not None and volume_ratio >= 1.5
    if volume_expansion:
        signals.append("volume_expansion")
        evidence_score += min(volume_ratio or 0, 4) / 2
        if volume_ma5 is not None and volume is not None and volume > volume_ma5:
            signals.append("volume_above_ma5")
        if change_pct is not None and change_pct > 0:
            signals.append("volume_price_up")
            direction_score += 1
        elif change_pct is not None and change_pct < 0:
            signals.append("volume_price_down")
            direction_score -= 1

    bollinger_breakout = bollinger_upper is not None and close > bollinger_upper
    bollinger_breakdown = bollinger_lower is not None and close < bollinger_lower
    bollinger_squeeze = bollinger_width_pct is not None and bollinger_width_pct <= 8
    if bollinger_breakout:
        signals.append("bollinger_breakout")
        direction_score += 1
        evidence_score += 1
    if bollinger_breakdown:
        signals.append("bollinger_breakdown")
        direction_score -= 1
        evidence_score += 1
    if bollinger_squeeze:
        signals.append("bollinger_squeeze")
        evidence_score += 0.5

    if rsi14 is not None:
        if rsi14 >= 75:
            signals.append("rsi_overheated")
            evidence_score += 1
        elif rsi14 >= 55:
            signals.append("rsi_bull_zone")
            direction_score += 1
        elif rsi14 <= 45:
            signals.append("rsi_weak")
            direction_score -= 1

    if roc10 is not None:
        if roc10 > 0:
            signals.append("roc_positive")
            direction_score += 1
        elif roc10 < 0:
            signals.append("roc_negative")
            direction_score -= 1

    large_gain = change_pct is not None and change_pct >= 5
    large_loss = change_pct is not None and change_pct <= -5
    price_stretched = ma20 is not None and close >= ma20 * 1.1
    high_volatility = atr_pct is not None and atr_pct >= 5

    if breakdown or cross_below_ma20:
        bucket = "support_break"
    elif large_loss:
        bucket = "selloff_risk"
    elif "volume_price_down" in signals:
        bucket = "volume_down"
    elif high_volatility and change_pct is not None and abs(change_pct) >= 3:
        bucket = "volatility_risk"
    elif breakout or bollinger_breakout:
        bucket = "breakout_high"
    elif large_gain and (price_stretched or bollinger_breakout or (rsi14 is not None and rsi14 >= 75)):
        bucket = "overheated"
    elif large_gain:
        bucket = "surge_up"
    elif cross_above_ma20:
        bucket = "trend_reclaim"
    elif "volume_price_up" in signals:
        bucket = "volume_up"
    elif volume_expansion:
        bucket = "volume"
    elif bollinger_squeeze:
        bucket = "compression_watch"
    elif ma20 is not None and close > ma20 and change_pct is not None and change_pct < 0:
        bucket = "pullback"
    elif direction_score >= 3:
        bucket = "momentum"
    elif direction_score <= -3:
        bucket = "bearish_momentum"
    else:
        bucket = "quiet"

    if change_pct is not None:
        evidence_score += min(abs(change_pct) / 2, 3)
    if ma20 is not None and close != 0:
        evidence_score += min(abs((close - ma20) / close) * 20, 2)

    context_score = 0.0
    priority_score = evidence_score * 10
    if bucket in {"support_break", "selloff_risk", "overheated", "volatility_risk"}:
        priority_score += 18
    elif bucket in {"breakout_high", "trend_reclaim", "volume_up", "volume_down"}:
        priority_score += 14
    elif bucket in {"surge_up", "momentum", "pullback"}:
        priority_score += 10
    if stale:
        priority_score *= 0.6
    technical_score = max(0.0, min(100.0, priority_score))
    grade, grade_label, grade_description = _technical_grade(technical_score)
    urgency = "high" if technical_score >= 70 else "medium" if technical_score >= 45 else "low"
    direction = "bullish" if direction_score >= 2 else "bearish" if direction_score <= -2 else "neutral"
    direction_label = "Bullish" if direction == "bullish" else "Bearish" if direction == "bearish" else "Neutral"
    matched_signal_keys = signals[:5]

    indicator_snapshot = {
        "trend": {
            "ma5": _round(ma5, 4),
            "ma20": _round(ma20, 4),
            "ma60": _round(ma60, 4),
            "roc10": _round(roc10, 4),
        },
        "volume": {
            "volume": float(volume) if volume is not None else None,
            "volume_ma20": _round(volume_ma20, 4),
            "volume_ratio": _round(volume_ratio, 4),
        },
        "risk": {
            "rsi14": _round(rsi14, 4),
            "atr14": _round(atr14, 4),
            "atr_pct": _round(atr_pct, 4),
            "bollinger_width_pct": _round(bollinger_width_pct, 4),
        },
    }

    bucket_meta = BUCKET_META_BY_KEY[bucket]
    return {
        "rank": 0,
        "source_rank": row.get("rank"),
        "bucket": bucket,
        "bucket_label": bucket_meta["label"],
        "urgency": urgency,
        "priority_score": _round(priority_score, 4) or 0.0,
        "technical_evidence_score": _round(evidence_score, 4) or 0.0,
        "technical_score": _round(technical_score, 2) or 0.0,
        "technical_grade": grade,
        "technical_grade_label": grade_label,
        "technical_grade_description": grade_description,
        "direction": direction,
        "direction_label": direction_label,
        "setup_label": bucket_meta["label"],
        "timing_label": "Confirm with next session and key levels",
        "risk_label": "OHLCV-only evidence",
        "factor_scores": {
            "direction": float(direction_score),
            "volume_ratio": _round(volume_ratio, 4) or 0.0,
            "change_pct": _round(change_pct, 4) or 0.0,
            "evidence": _round(evidence_score, 4) or 0.0,
        },
        "price_levels": _price_levels(
            bucket=bucket,
            close=close,
            ma20=ma20,
            support=low20,
            resistance=high20,
            atr14=atr14,
        ),
        "technical_notes": [],
        "action_label": bucket_meta["label"],
        "reason": "OHLCV-only technical radar signal.",
        "stock_id": str(row.get("symbol") or row.get("stock_id") or "").strip(),
        "stock_name": row.get("security_name") or row.get("stock_name"),
        "time": row.get("time"),
        "trade_date": trade_date,
        "close": close,
        "volume": volume,
        "change": change,
        "previous_close": previous_close,
        "change_pct": change_pct,
        "limit_status": None,
        "score": direction_score,
        "status": row.get("status") or "ready",
        "signal_count": len(set(signals)),
        "signal_keys": list(dict.fromkeys(signals)),
        "matched_signal_keys": list(dict.fromkeys(matched_signal_keys)),
        "matched_signal_labels": [],
        "signal_labels": [],
        "primary_signal_key": matched_signal_keys[0] if matched_signal_keys else None,
        "primary_signal_label": None,
        "indicator_snapshot": indicator_snapshot,
        "context_snapshot": {
            "data_scope": {
                "coverage": "ohlcv_only",
                "fundamentals": "excluded",
                "chip_flow": "excluded",
                "news": "excluded",
            }
        },
        "context_signals": [],
        "context_summary": "OHLCV-only technical radar; chip flow, local news, and full fundamentals are excluded.",
        "context_score": context_score,
        "stale": stale,
        "error_message": row.get("error_message"),
    }


def build_technical_watchlist_radar(
    *,
    ranking: dict[str, Any],
    histories: dict[str, list[TechnicalRadarBar]],
    market: str,
    include_children: bool = True,
    mode: str = "action",
    max_results: int = 30,
) -> dict[str, Any]:
    normalized_mode = mode.lower().strip()
    if normalized_mode not in ALLOWED_TECHNICAL_RADAR_MODES:
        raise ValueError(
            f"Unsupported mode='{mode}'. Allowed values: {', '.join(sorted(ALLOWED_TECHNICAL_RADAR_MODES))}."
        )

    max_results = max(1, min(int(max_results), 200))
    target_trade_date = _date_value(ranking.get("target_trade_date"))
    items = [
        _radar_item(
            row=row,
            history=histories.get(str(row.get("symbol") or row.get("stock_id") or "").strip(), []),
            target_trade_date=target_trade_date,
        )
        for row in (ranking.get("results") or [])
    ]
    matched_items = [
        item for item in items if _bucket_accepts_mode(normalized_mode, item["bucket"])
    ]
    matched_items.sort(
        key=lambda item: (
            -float(item.get("priority_score") or 0),
            BUCKET_ORDER.get(str(item.get("bucket") or ""), 999),
            str(item.get("stock_id") or ""),
        )
    )

    results = matched_items[:max_results]
    for index, item in enumerate(results, start=1):
        item["rank"] = index

    return {
        "group_id": ranking.get("group_id"),
        "include_children": include_children,
        "mode": normalized_mode,
        "max_results": max_results,
        "requested_stock_count": ranking.get("requested_symbol_count", ranking.get("requested_stock_count", 0)),
        "ranked_count": ranking.get("ranked_count", 0),
        "matched_count": len(matched_items),
        "radar_count": len(results),
        "no_data_count": ranking.get("no_data_count", 0),
        "error_count": ranking.get("error_count", 0),
        "trade_date": ranking.get("trade_date"),
        "target_trade_date": target_trade_date,
        "is_current": ranking.get("is_current", True),
        "current_stock_count": ranking.get("current_symbol_count", ranking.get("current_stock_count", 0)),
        "stale_stock_count": ranking.get("stale_symbol_count", ranking.get("stale_stock_count", 0)),
        "market": market.upper(),
        "scope_label": f"{market.upper()} technical radar lite",
        "data_limitations": DATA_LIMITATIONS.copy(),
        "buckets": _bucket_summary(matched_items, mode=normalized_mode),
        "results": results,
    }


__all__ = [
    "DATA_LIMITATIONS",
    "TechnicalRadarBar",
    "build_technical_watchlist_radar",
]
