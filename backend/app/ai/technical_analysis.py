from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def normalize_analysis_horizon(value: str | None) -> str:
    normalized = (value or "swing").strip().lower()
    aliases = {
        "auto": "swing",
        "today": "intraday",
        "live": "intraday",
        "realtime": "intraday",
        "real-time": "intraday",
        "now": "intraday",
        "daily": "short",
        "day": "short",
        "short_term": "short",
        "short-term": "short",
        "weekly": "swing",
        "medium": "swing",
        "medium_short": "swing",
        "medium-short": "swing",
        "monthly": "long",
        "fundamental": "long",
        "investment": "long",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"intraday", "short", "swing", "long"}:
        return "swing"
    return normalized


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _report_score(report: dict[str, Any] | None) -> int | None:
    if not isinstance(report, dict):
        return None
    if report.get("phase") in {"waiting_intraday", "market_closed"}:
        return None
    score = report.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return int(round(score))


TECHNICAL_FACTOR_ROW_KEYS = {
    "trend_structure": "trend",
    "momentum": "momentum",
    "volume_flow": "volume",
    "volatility_risk": "volatility",
    "institutional_flow": "chips",
}
TECHNICAL_FACTOR_WEIGHTS_BY_HORIZON = {
    "intraday": {"trend": 0.30, "momentum": 0.20, "volume": 0.20, "volatility": 0.20, "chips": 0.10},
    "short": {"trend": 0.30, "momentum": 0.25, "volume": 0.20, "volatility": 0.15, "chips": 0.10},
    "swing": {"trend": 0.35, "momentum": 0.20, "volume": 0.15, "volatility": 0.20, "chips": 0.10},
    "long": {"trend": 0.40, "momentum": 0.20, "volume": 0.10, "volatility": 0.20, "chips": 0.10},
}


def _score_direction(value: Any, *, positive_threshold: float = 0.0, negative_threshold: float = 0.0) -> float | None:
    number = _finite_number(value)
    if number is None:
        return None
    if number > positive_threshold:
        return 1.0
    if number < negative_threshold:
        return -1.0
    return 0.0


def _factor_score_from_row(row: dict[str, Any], factor: str) -> float | None:
    tone = str(row.get("tone") or "").lower()
    direction = _finite_number(row.get("direction"))
    value = _finite_number(row.get("value"))

    if factor == "trend":
        return _score_direction(direction, positive_threshold=0.1, negative_threshold=-0.1)

    if factor == "momentum":
        score = _score_direction(direction)
        if score is not None:
            return score
        if value is not None:
            if value >= 50:
                return 0.5
            if value < 40:
                return -1.0
            return 0.0
        return None

    if factor == "volume":
        if direction is None:
            return None
        if direction >= 20:
            return 1.0
        if direction <= -20:
            return -1.0
        return 0.0

    if factor == "volatility":
        if tone == "warning":
            return -1.0
        if value is None:
            return None
        if value >= 5:
            return -1.0
        if value >= 3:
            return -0.5
        return 0.0

    if factor == "chips":
        score = _score_direction(direction)
        if score is not None:
            return score
        if tone == "positive":
            return 1.0
        if tone == "negative":
            return -1.0
        return None

    return None


def _timeframe_factor_scores(report: dict[str, Any] | None) -> dict[str, float]:
    if _report_score(report) is None or not isinstance(report, dict):
        return {}

    scores: dict[str, float] = {}
    rows = report.get("rows") if isinstance(report.get("rows"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        factor = TECHNICAL_FACTOR_ROW_KEYS.get(str(row.get("key") or ""))
        if factor is None:
            continue
        score = _factor_score_from_row(row, factor)
        if score is not None:
            scores[factor] = round(score, 2)
    return scores


def _weighted_factor_score(
    factor_scores: dict[str, float],
    factor_weights: dict[str, float],
) -> float | None:
    weighted_total = 0.0
    total_weight = 0.0
    for factor, weight in factor_weights.items():
        score = factor_scores.get(factor)
        if score is None:
            continue
        weighted_total += score * weight
        total_weight += weight
    if total_weight == 0:
        return None
    return round((weighted_total / total_weight) * 7, 1)


def _technical_factor_score_model(
    *,
    technical_reports: dict[str, Any],
    selected_horizon: str,
    weights_by_horizon: dict[str, list[tuple[str, float]]],
    base_selected_score: int | None,
    base_scores_by_horizon: dict[str, int | None],
) -> dict[str, Any]:
    timeframe_factor_scores = {
        timeframe: _timeframe_factor_scores(report)
        for timeframe, report in technical_reports.items()
        if isinstance(report, dict)
    }
    horizon_factor_scores: dict[str, dict[str, float]] = {}
    refined_scores: dict[str, float | None] = {}

    for horizon, timeframe_weights in weights_by_horizon.items():
        factor_weights = TECHNICAL_FACTOR_WEIGHTS_BY_HORIZON[horizon]
        combined: dict[str, float] = {}
        combined_weight: dict[str, float] = {}

        for timeframe, timeframe_weight in timeframe_weights:
            report_score = _report_score(technical_reports.get(timeframe))
            if report_score is None:
                continue
            factor_scores = timeframe_factor_scores.get(timeframe) or {}
            for factor, score in factor_scores.items():
                if factor not in factor_weights:
                    continue
                combined[factor] = combined.get(factor, 0.0) + score * timeframe_weight
                combined_weight[factor] = combined_weight.get(factor, 0.0) + timeframe_weight

        normalized = {
            factor: round(total / combined_weight[factor], 2)
            for factor, total in combined.items()
            if combined_weight.get(factor)
        }
        horizon_factor_scores[horizon] = normalized
        refined_scores[horizon] = _weighted_factor_score(normalized, factor_weights)

    selected_score = refined_scores.get(selected_horizon)
    return {
        "version": "technical_factor_weight_v1",
        "selected_score": selected_score,
        "base_selected_score": base_selected_score,
        "scores": refined_scores,
        "base_scores": base_scores_by_horizon,
        "factor_weights": TECHNICAL_FACTOR_WEIGHTS_BY_HORIZON,
        "timeframe_factor_scores": timeframe_factor_scores,
        "horizon_factor_scores": horizon_factor_scores,
        "score_range": "-7..+7",
    }


def _weighted_score(
    technical_reports: dict[str, Any],
    components: list[tuple[str, float]],
) -> tuple[int | None, list[dict[str, Any]]]:
    used: list[dict[str, Any]] = []
    total_weight = 0.0
    weighted_total = 0.0

    for timeframe, weight in components:
        report = technical_reports.get(timeframe)
        score = _report_score(report)
        if score is None:
            used.append(
                {
                    "timeframe": timeframe,
                    "weight": weight,
                    "score": None,
                    "included": False,
                }
            )
            continue

        total_weight += weight
        weighted_total += score * weight
        used.append(
            {
                "timeframe": timeframe,
                "weight": weight,
                "score": score,
                "included": True,
                "confidence": report.get("confidence") if isinstance(report, dict) else None,
            }
        )

    if total_weight == 0:
        return None, used

    return int(round(weighted_total / total_weight)), used


def _technical_analysis_summary(
    *,
    technical_reports: dict[str, Any],
    requested_horizon: str,
) -> dict[str, Any]:
    selected_horizon = normalize_analysis_horizon(requested_horizon)
    weights_by_horizon = {
        "intraday": [("today", 1.0), ("daily", 0.35)],
        "short": [("daily", 1.0)],
        "swing": [("daily", 0.45), ("weekly", 0.55)],
        "long": [("daily", 0.15), ("weekly", 0.30), ("monthly", 0.55)],
    }
    preferred_timeframe = {
        "intraday": "today",
        "short": "daily",
        "swing": "weekly",
        "long": "monthly",
    }[selected_horizon]
    base_selected_score, components = _weighted_score(
        technical_reports,
        weights_by_horizon[selected_horizon],
    )
    selected_report = technical_reports.get(preferred_timeframe)
    if not isinstance(selected_report, dict) or _report_score(selected_report) is None:
        selected_report = next(
            (
                technical_reports.get(component["timeframe"])
                for component in components
                if component.get("included")
            ),
            None,
        )
    if not isinstance(selected_report, dict):
        selected_report = {}

    base_scores_by_horizon: dict[str, int | None] = {}
    score_components_by_horizon: dict[str, list[dict[str, Any]]] = {}
    for horizon, components_for_horizon in weights_by_horizon.items():
        score, horizon_components = _weighted_score(
            technical_reports,
            components_for_horizon,
        )
        base_scores_by_horizon[horizon] = score
        score_components_by_horizon[horizon] = horizon_components

    score_model = _technical_factor_score_model(
        technical_reports=technical_reports,
        selected_horizon=selected_horizon,
        weights_by_horizon=weights_by_horizon,
        base_selected_score=base_selected_score,
        base_scores_by_horizon=base_scores_by_horizon,
    )
    refined_selected_score = score_model.get("selected_score")
    refined_scores = score_model.get("scores") if isinstance(score_model.get("scores"), dict) else {}
    selected_score = (
        refined_selected_score
        if isinstance(refined_selected_score, (int, float)) and not isinstance(refined_selected_score, bool)
        else base_selected_score
    )
    scores_by_horizon = {
        horizon: (
            refined_scores.get(horizon)
            if isinstance(refined_scores.get(horizon), (int, float))
            and not isinstance(refined_scores.get(horizon), bool)
            else base_scores_by_horizon.get(horizon)
        )
        for horizon in weights_by_horizon
    }

    return {
        "requested_horizon": requested_horizon,
        "selected_horizon": selected_horizon,
        "selected_timeframe": selected_report.get("timeframe") or preferred_timeframe,
        "selected_score": selected_score,
        "selected_title": selected_report.get("title"),
        "selected_summary": selected_report.get("summary"),
        "selected_confidence": selected_report.get("confidence"),
        "scores": scores_by_horizon,
        "base_selected_score": base_selected_score,
        "base_scores": base_scores_by_horizon,
        "score_model": score_model,
        "components": components,
        "components_by_horizon": score_components_by_horizon,
    }


def _first_value(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row.get(key)
    return None


def _moving_average(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def _pct_change(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None or previous == 0:
        return None
    return ((current - previous) / previous) * 100


def _format_number(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _source_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _round_price(value: Any) -> float | None:
    number = _finite_number(value)
    if number is None or number <= 0:
        return None
    if number >= 100:
        return float(round(number))
    if number >= 10:
        return round(number, 1)
    return round(number, 2)


def _price_zone(low: Any, high: Any, *, label: str, basis: str) -> dict[str, Any] | None:
    low_price = _round_price(low)
    high_price = _round_price(high)
    if low_price is None or high_price is None:
        return None
    if low_price > high_price:
        low_price, high_price = high_price, low_price
    return {
        "low": low_price,
        "high": high_price,
        "label": label,
        "basis": basis,
    }


def _price_level(price: Any, *, label: str, basis: str) -> dict[str, Any] | None:
    rounded = _round_price(price)
    if rounded is None:
        return None
    return {
        "price": rounded,
        "label": label,
        "basis": basis,
    }


def _indicator_from_report(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    indicator = data.get("daily_indicator") or data.get("indicator") or {}
    return indicator if isinstance(indicator, dict) else {}


def _indicator_level_values(indicator: dict[str, Any]) -> dict[str, float | None]:
    ma = indicator.get("ma") if isinstance(indicator.get("ma"), dict) else {}
    atr = indicator.get("atr") if isinstance(indicator.get("atr"), dict) else {}
    donchian = indicator.get("donchian") if isinstance(indicator.get("donchian"), dict) else {}
    rsi = indicator.get("rsi") if isinstance(indicator.get("rsi"), dict) else {}
    return {
        "close": _finite_number(indicator.get("close")),
        "ma5": _finite_number(ma.get("ma5")),
        "ma20": _finite_number(ma.get("ma20")),
        "ma60": _finite_number(ma.get("ma60")),
        "atr14": _finite_number(atr.get("atr14")),
        "donchian_upper20": _finite_number(donchian.get("upper20")),
        "donchian_lower20": _finite_number(donchian.get("lower20")),
        "rsi14": _finite_number(rsi.get("rsi14")),
    }


def _donchian_position(latest_price: float, upper: float | None, lower: float | None) -> float | None:
    if upper is None or lower is None or upper == lower:
        return None
    return round((latest_price - lower) / (upper - lower) * 100, 2)


def _technical_price_levels(
    *,
    technical_reports: dict[str, Any],
    latest_daily: Any,
) -> dict[str, Any]:
    daily_report = technical_reports.get("daily") if isinstance(technical_reports, dict) else {}
    daily_indicator = _indicator_from_report(daily_report)
    daily_values = _indicator_level_values(daily_indicator)

    latest_price = (
        _finite_number(_source_value(latest_daily, "close_price"))
        or _finite_number(_source_value(latest_daily, "close"))
        or daily_values.get("close")
    )
    if latest_price is None or latest_price <= 0:
        return {}

    ma5 = daily_values.get("ma5")
    ma20 = daily_values.get("ma20")
    ma60 = daily_values.get("ma60")
    atr14 = daily_values.get("atr14")
    upper20 = daily_values.get("donchian_upper20")
    lower20 = daily_values.get("donchian_lower20")
    atr_buffer = atr14 if atr14 is not None and atr14 > 0 else latest_price * 0.03
    atr_pct = round((atr_buffer / latest_price) * 100, 2) if latest_price else None
    daily_score = _report_score(daily_report)
    weekly_report = technical_reports.get("weekly") if isinstance(technical_reports, dict) else {}
    weekly_score = _report_score(weekly_report)
    weekly_values = _indicator_level_values(_indicator_from_report(weekly_report))
    weekly_rsi = weekly_values.get("rsi14")
    donchian_position = _donchian_position(latest_price, upper20, lower20)
    extended = bool(
        (donchian_position is not None and donchian_position >= 80)
        or (weekly_rsi is not None and weekly_rsi >= 80)
        or (atr_pct is not None and atr_pct >= 5)
    )

    aggressive_zone = _price_zone(
        latest_price - atr_buffer * 0.25,
        latest_price,
        label="現價附近的小回檔區",
        basis="latest close minus 0.25 ATR to latest close",
    )
    preferred_anchor = ma5 or ma20 or latest_price
    preferred_zone = _price_zone(
        preferred_anchor - atr_buffer * 0.25,
        preferred_anchor + atr_buffer * 0.25,
        label="偏好回檔區",
        basis="MA5 +/- 0.25 ATR; fallback to MA20/latest close when MA5 unavailable",
    )
    conservative_anchor = ma20 or ma60
    conservative_zone = (
        _price_zone(
            conservative_anchor - atr_buffer * 0.25,
            conservative_anchor + atr_buffer * 0.25,
            label="保守回檔區",
            basis="MA20 +/- 0.25 ATR; fallback to MA60 when MA20 unavailable",
        )
        if conservative_anchor is not None
        else None
    )
    breakout_price = upper20 if upper20 is not None and upper20 > latest_price else latest_price + atr_buffer * 0.5
    do_not_chase_price = latest_price + (atr_buffer * 0.25 if extended else atr_buffer * 0.5)
    preferred_low = preferred_zone.get("low") if isinstance(preferred_zone, dict) else None
    short_stop_anchor = ma5 - atr_buffer * 0.75 if ma5 is not None else latest_price - atr_buffer
    if preferred_low is not None:
        short_stop_anchor = min(short_stop_anchor, preferred_low - atr_buffer * 0.5)
    invalidation_anchor = ma20 if ma20 is not None and latest_price >= ma20 else lower20 or ma60

    entry = {
        "aggressive_zone": aggressive_zone,
        "preferred_zone": preferred_zone,
        "conservative_zone": conservative_zone,
        "breakout_confirm_above": _price_level(
            breakout_price,
            label="突破確認價",
            basis="20-day Donchian upper when above latest close; otherwise latest close + 0.5 ATR",
        ),
        "do_not_chase_above": _price_level(
            do_not_chase_price,
            label="追價上限",
            basis="latest close + 0.25 ATR when extended, otherwise latest close + 0.5 ATR",
        ),
    }
    risk = {
        "short_stop": _price_level(
            short_stop_anchor,
            label="短線停損",
            basis="MA5 - 0.75 ATR and preferred-zone lower bound - 0.5 ATR, choose the lower guardrail",
        ),
        "technical_invalidation": _price_level(
            invalidation_anchor,
            label="技術失效",
            basis="MA20 while price is above MA20; otherwise Donchian lower or MA60 fallback",
        ),
        "volatility_buffer": {
            "atr": _round_price(atr_buffer),
            "half_atr": _round_price(atr_buffer * 0.5),
            "one_atr": _round_price(atr_buffer),
            "atr_pct": atr_pct,
        },
    }
    summary = [
        "偏多但偏熱時，優先等 MA5 附近回檔或 Donchian 突破確認。",
        "ATR 偏高時不把現價當成最佳買點，停損距離也要放寬到技術失效線之外。",
    ]
    if not extended:
        summary[0] = "價格未明顯偏離區間上緣時，可用 MA5/MA20 回測與突破價作為條件式進場。"

    return {
        "kind": "technical_price_levels",
        "version": "price_levels_v1",
        "as_of": _json_value(_source_value(latest_daily, "trade_date")) or daily_indicator.get("time"),
        "latest_price": _round_price(latest_price),
        "basis_timeframe": "daily",
        "context": {
            "trend_state": (daily_report or {}).get("title") if isinstance(daily_report, dict) else None,
            "extended": extended,
            "atr_pct": atr_pct,
            "donchian_position": donchian_position,
            "daily_score": daily_score,
            "weekly_score": weekly_score,
            "weekly_rsi14": round(weekly_rsi, 2) if weekly_rsi is not None else None,
        },
        "levels": {
            "latest": _round_price(latest_price),
            "ma5": _round_price(ma5),
            "ma20": _round_price(ma20),
            "ma60": _round_price(ma60),
            "atr14": _round_price(atr_buffer),
            "donchian_upper20": _round_price(upper20),
            "donchian_lower20": _round_price(lower20),
        },
        "entry": {key: value for key, value in entry.items() if value is not None},
        "risk": {key: value for key, value in risk.items() if value is not None},
        "summary": summary,
    }


def _normalize_technical_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close = _finite_number(_first_value(row, ("close", "close_price", "last_price", "settlement_price")))
        if close is None:
            continue
        points.append(
            {
                "time": _json_value(_first_value(row, ("time", "trade_date", "bar_time", "quote_time"))),
                "open": _finite_number(_first_value(row, ("open", "open_price"))),
                "high": _finite_number(_first_value(row, ("high", "high_price"))),
                "low": _finite_number(_first_value(row, ("low", "low_price"))),
                "close": close,
                "volume": _finite_number(_first_value(row, ("volume", "trade_volume", "total_volume"))),
                "trade_value": _finite_number(row.get("trade_value")),
            }
        )
    return points


def _technical_report_from_points(
    *,
    points: list[dict[str, Any]],
    timeframe: str,
    asset_label: str,
) -> dict[str, Any]:
    closes = [_finite_number(point.get("close")) for point in points]
    closes = [value for value in closes if value is not None]
    if len(closes) < 2:
        return {
            "timeframe": timeframe,
            "score": None,
            "title": "資料不足",
            "summary": f"{asset_label} {timeframe} 可用價量點不足，暫時不能計算方向。",
            "confidence": "low",
            "point_count": len(closes),
        }

    latest = closes[-1]
    previous = closes[-2]
    ma5 = _moving_average(closes, 5)
    ma20 = _moving_average(closes, 20)
    ma60 = _moving_average(closes, 60)
    change_1 = _pct_change(previous, latest)
    change_5 = _pct_change(closes[-6], latest) if len(closes) >= 6 else None
    change_20 = _pct_change(closes[-21], latest) if len(closes) >= 21 else None

    score = 0
    if ma5 is not None:
        score += 1 if latest >= ma5 else -1
    if ma20 is not None:
        score += 1 if latest >= ma20 else -1
    if ma60 is not None:
        score += 1 if latest >= ma60 else -1
    if change_5 is not None:
        score += 1 if change_5 > 0 else -1 if change_5 < 0 else 0
    if change_20 is not None:
        score += 1 if change_20 > 0 else -1 if change_20 < 0 else 0

    recent_range = closes[-20:] if len(closes) >= 20 else closes
    recent_high = max(recent_range)
    recent_low = min(recent_range)
    if recent_high > recent_low:
        position = (latest - recent_low) / (recent_high - recent_low)
        if position >= 0.75:
            score += 1
        elif position <= 0.25:
            score -= 1

    score = max(-5, min(5, score))
    if score >= 4:
        title = "波段偏多"
    elif score >= 1:
        title = "偏多觀察"
    elif score <= -4:
        title = "波段偏空"
    elif score <= -1:
        title = "偏弱觀察"
    else:
        title = "方向未定"

    confidence = "high" if len(closes) >= 60 else "medium" if len(closes) >= 20 else "low"
    relation_parts = []
    if ma20 is not None:
        relation_parts.append(f"{'站上' if latest >= ma20 else '跌破'} MA20")
    if ma60 is not None:
        relation_parts.append(f"{'站上' if latest >= ma60 else '跌破'} MA60")
    relation_text = "、".join(relation_parts) if relation_parts else "均線資料有限"
    summary = (
        f"最新 {_format_number(latest)}，單期 {_format_pct(change_1)}、"
        f"5期 {_format_pct(change_5)}、20期 {_format_pct(change_20)}；{relation_text}。"
    )

    return {
        "timeframe": timeframe,
        "score": score,
        "title": title,
        "summary": summary,
        "confidence": confidence,
        "point_count": len(closes),
        "latest_close": latest,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "change_1_pct": change_1,
        "change_5_pct": change_5,
        "change_20_pct": change_20,
    }


def _serialized_chart(chart: dict[str, Any]) -> dict[str, Any]:
    points = [
        {key: _json_value(value) for key, value in point.items()}
        for point in chart.get("points", [])
        if isinstance(point, dict)
    ]
    return {
        **chart,
        "from_date": _json_value(chart.get("from_date")),
        "to_date": _json_value(chart.get("to_date")),
        "points": points,
    }


def _chart_from_points(*, timeframe: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "timeframe": timeframe,
        "point_count": len(points),
        "from_date": points[0]["time"] if points else None,
        "to_date": points[-1]["time"] if points else None,
        "points": points,
    }
