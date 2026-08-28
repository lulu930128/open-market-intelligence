from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any

from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.trading_calendar import next_taiwan_trading_day


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def _technical_point_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def _indicator_value(values: dict[str, Any], key: str | None, legacy_key: str | None = None) -> Any:
    if not isinstance(values, dict):
        return None
    if key and values.get(key) is not None:
        return values.get(key)
    if legacy_key and values.get(legacy_key) is not None:
        return values.get(legacy_key)
    return None


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


def _intraday_report_is_scoreable(report: dict[str, Any] | None) -> bool:
    if not isinstance(report, dict) or report.get("phase") != "intraday":
        return False
    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    intraday = data.get("intraday") if isinstance(data.get("intraday"), dict) else {}
    latest_point = intraday.get("latest_point")
    point_count = intraday.get("point_count") if intraday else report.get("point_count")
    if intraday.get("is_current_session") is False:
        return False
    return bool(
        _report_score(report) is not None
        and (
            not intraday
            or (
                isinstance(latest_point, dict)
                and latest_point.get("time")
                and intraday.get("is_current_session") is True
            )
        )
        and isinstance(point_count, int)
        and point_count >= 5
    )


def _selected_score_title(score: int | float | None, *, intraday: bool) -> str:
    if score is None:
        return "資料不足"
    if intraday:
        if score >= 4:
            return "盤中偏強"
        if score >= 1:
            return "盤中震盪偏強"
        if score <= -4:
            return "盤中偏弱"
        if score <= -1:
            return "盤中震盪偏弱"
        return "盤中震盪"
    if score >= 4:
        return "波段偏多"
    if score >= 1:
        return "偏多觀察"
    if score <= -4:
        return "波段偏空"
    if score <= -1:
        return "偏弱觀察"
    return "方向未定"


def _selected_score_summary(
    score: int | float | None,
    *,
    selected_horizon: str,
    components: list[dict[str, Any]],
) -> str:
    included = [
        str(component.get("timeframe"))
        for component in components
        if component.get("included")
    ]
    score_text = "資料不足" if score is None else f"{int(round(score)):+d}"
    component_text = "、".join(included) if included else "無可用時間框架"
    return f"{selected_horizon} 綜合分數 {score_text}，依 {component_text} 證據加權。"


def _technical_analysis_summary(
    *,
    technical_reports: dict[str, Any],
    requested_horizon: str,
) -> dict[str, Any]:
    requested_selected_horizon = normalize_analysis_horizon(requested_horizon)
    intraday_scoreable = _intraday_report_is_scoreable(technical_reports.get("today"))
    selected_horizon = (
        "short"
        if requested_selected_horizon == "intraday" and not intraday_scoreable
        else requested_selected_horizon
    )
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
    if not intraday_scoreable:
        scores_by_horizon["intraday"] = None
        if isinstance(score_model.get("scores"), dict):
            score_model["scores"]["intraday"] = None
        if isinstance(score_model.get("base_scores"), dict):
            score_model["base_scores"]["intraday"] = None

    composite_score_title = _selected_score_title(
        selected_score,
        intraday=selected_horizon == "intraday",
    )
    today_report = (
        technical_reports.get("today")
        if isinstance(technical_reports.get("today"), dict)
        else {}
    )
    daily_report = (
        technical_reports.get("daily")
        if isinstance(technical_reports.get("daily"), dict)
        else {}
    )
    today_state = {
        "status": "ready" if intraday_scoreable else "unavailable",
        "timeframe": "today",
        "phase": today_report.get("phase"),
        "score": _report_score(today_report),
        "title": today_report.get("title"),
        "summary": today_report.get("summary"),
        "confidence": today_report.get("confidence"),
    }
    historical_structure = {
        "status": "ready" if _report_score(daily_report) is not None else "unavailable",
        "timeframe": "daily",
        "score": _report_score(daily_report),
        "title": daily_report.get("title"),
        "summary": daily_report.get("summary"),
        "confidence": daily_report.get("confidence"),
    }
    fallback_reason = (
        "intraday_evidence_unavailable"
        if requested_selected_horizon == "intraday" and selected_horizon == "short"
        else None
    )
    if requested_selected_horizon == "intraday":
        today_title = (
            str(today_state.get("title"))
            if intraday_scoreable and today_state.get("title")
            else "盤中證據不足"
        )
        history_title = str(
            historical_structure.get("title") or composite_score_title
        )
        selected_title = f"今日：{today_title}｜歷史結構：{history_title}"
        composite_state = (
            f"{today_title}；歷史結構為{history_title}。"
            if intraday_scoreable
            else f"盤中證據不足；目前僅能引用歷史結構：{history_title}。"
        )
    else:
        selected_title = composite_score_title
        composite_state = f"{composite_score_title}（{selected_horizon} 視角）"

    return {
        "requested_horizon": requested_horizon,
        "effective_horizon": selected_horizon,
        "selected_horizon": selected_horizon,
        "selected_timeframe": selected_report.get("timeframe") or preferred_timeframe,
        "selected_score": selected_score,
        "selected_title": selected_title,
        "composite_score_title": composite_score_title,
        "selected_summary": _selected_score_summary(
            selected_score,
            selected_horizon=selected_horizon,
            components=components,
        ),
        "selected_timeframe_title": selected_report.get("title"),
        "selected_timeframe_summary": selected_report.get("summary"),
        "selected_confidence": selected_report.get("confidence"),
        "scores": scores_by_horizon,
        "intraday_score": scores_by_horizon.get("intraday"),
        "today_state": today_state,
        "historical_structure": historical_structure,
        "composite_state": composite_state,
        "fallback_reason": fallback_reason,
        "horizon_fallback_reason": fallback_reason,
        "base_selected_score": base_selected_score,
        "base_scores": base_scores_by_horizon,
        "score_model": score_model,
        "components": components,
        "components_by_horizon": score_components_by_horizon,
    }


def evaluate_technical_evidence_sufficiency(
    *,
    chart: dict[str, Any],
    technical_reports: dict[str, Any],
    requested_horizon: str,
) -> dict[str, Any]:
    """Gate formal Taiwan technical scores on released daily evidence."""

    horizon = normalize_analysis_horizon(requested_horizon)
    required_daily_bars = {
        "intraday": 20,
        "short": 20,
        "swing": 60,
        "long": 120,
    }[horizon]
    required_factor_count = 2 if horizon in {"intraday", "short"} else 3
    points = [
        point
        for point in chart.get("points") or []
        if isinstance(point, dict)
    ]
    daily_bar_count = len(points)
    parsed_dates = [
        parsed.date()
        for point in points
        if (parsed := _technical_point_datetime(point.get("time"))) is not None
    ]
    continuity_status = "continuous"
    continuity_issues: list[str] = []
    if len(parsed_dates) < 2:
        continuity_status = "insufficient_history"
        continuity_issues.append("insufficient_series_points")
    else:
        for previous, current in zip(parsed_dates, parsed_dates[1:]):
            if current <= previous:
                continuity_status = (
                    "duplicate" if current == previous else "unordered"
                )
                continuity_issues.append(
                    "duplicate_trade_date"
                    if current == previous
                    else "unordered_trade_date"
                )
                break
            if current != next_taiwan_trading_day(
                previous,
                include_value=False,
            ):
                continuity_status = "gap_detected"
                continuity_issues.append("missing_trading_day")
                break

    daily_report = (
        technical_reports.get("daily")
        if isinstance(technical_reports.get("daily"), dict)
        else {}
    )
    daily_data = (
        daily_report.get("data")
        if isinstance(daily_report.get("data"), dict)
        else {}
    )
    indicator = (
        daily_data.get("daily_indicator")
        if isinstance(daily_data.get("daily_indicator"), dict)
        else daily_data.get("indicator")
        if isinstance(daily_data.get("indicator"), dict)
        else {}
    )
    major_indicator_groups = {
        key: indicator.get(key)
        for key in ("ma", "rsi", "macd", "kd")
    }
    available_factor_count = sum(
        1
        for value in major_indicator_groups.values()
        if isinstance(value, dict)
        and any(item is not None for item in value.values())
    )
    continuity_ok = continuity_status == "continuous"
    count_sufficient = daily_bar_count >= required_daily_bars
    factors_sufficient = available_factor_count >= required_factor_count
    volume_unit = str(chart.get("volume_unit") or "").strip().lower()
    volume_lineage_ok = volume_unit in {"share", "shares"}
    decision_usable = bool(
        count_sufficient
        and factors_sufficient
        and continuity_ok
        and volume_lineage_ok
        and chart.get("data_quality") not in {"missing", "stale"}
    )
    reason_codes: list[str] = []
    if not count_sufficient:
        reason_codes.append("INSUFFICIENT_DAILY_BARS")
    if not factors_sufficient:
        reason_codes.append("INSUFFICIENT_MAJOR_INDICATORS")
    if not continuity_ok:
        reason_codes.append("DAILY_CONTINUITY_NOT_SATISFIED")
    if not volume_lineage_ok:
        reason_codes.append("DAILY_VOLUME_UNIT_MISSING")
    if chart.get("data_quality") in {"missing", "stale"}:
        reason_codes.append("DAILY_DATA_QUALITY_NOT_USABLE")
    return {
        "status": "ready" if decision_usable else "partial",
        "decision_usable": decision_usable,
        "daily_bar_count": daily_bar_count,
        "required_daily_bar_count": required_daily_bars,
        "available_factor_count": available_factor_count,
        "required_factor_count": required_factor_count,
        "major_indicators": {
            key: bool(
                isinstance(value, dict)
                and any(item is not None for item in value.values())
            )
            for key, value in major_indicator_groups.items()
        },
        "continuity_status": continuity_status,
        "continuity_ok": continuity_ok,
        "continuity_issues": continuity_issues,
        "volume_unit": chart.get("volume_unit"),
        "volume_lineage_ok": volume_lineage_ok,
        "source_capability": "daily.ohlcv",
        "reason_codes": reason_codes,
    }


def apply_technical_sufficiency_gate(
    analysis: dict[str, Any],
    *,
    sufficiency: dict[str, Any],
) -> dict[str, Any]:
    result = dict(analysis)
    result["sufficiency"] = sufficiency
    result["status"] = sufficiency.get("status")
    result["decision_usable"] = bool(sufficiency.get("decision_usable"))
    if result["decision_usable"]:
        return result
    raw_selected_score = result.get("selected_score")
    result["raw_selected_score"] = raw_selected_score
    result["selected_score"] = None
    result["selected_title"] = "技術證據不足"
    result["composite_score_title"] = "技術證據不足"
    result["selected_summary"] = (
        "日線歷史、核心指標或序列連續性不足，無法形成正式技術方向。"
    )
    result["selected_confidence"] = None
    result["composite_state"] = "insufficient_evidence"
    result["scores"] = {
        key: None for key in (result.get("scores") or {})
    }
    result["intraday_score"] = None
    for state_key in ("today_state", "historical_structure"):
        state = dict(result.get(state_key) or {})
        if not state:
            continue
        state.update(
            {
                "status": "partial",
                "score": None,
                "title": "技術證據不足",
                "summary": result["selected_summary"],
                "confidence": None,
            }
        )
        result[state_key] = state
    score_model = dict(result.get("score_model") or {})
    score_model["raw_selected_score"] = raw_selected_score
    score_model["selected_score"] = None
    score_model["normalized_decision_score"] = None
    score_model["scores"] = {
        key: None for key in (score_model.get("scores") or {})
    }
    score_model["base_scores"] = {
        key: None for key in (score_model.get("base_scores") or {})
    }
    result["score_model"] = score_model
    return result


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
    # Keep calculation evidence independent from display formatting. Taiwan
    # prices above 100 can still carry valid half-unit or finer precision.
    return round(number, 4)


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


def _validate_long_price_levels(levels: dict[str, Any]) -> dict[str, Any]:
    latest_price = _finite_number(levels.get("latest_price"))
    if latest_price is None or latest_price <= 0:
        return {
            **levels,
            "entry": {},
            "risk": {},
            "validation": {
                "status": "unavailable",
                "position_side": "long",
                "decision_ready": False,
                "violations": [
                    {
                        "code": "LATEST_PRICE_UNAVAILABLE",
                        "field": "latest_price",
                        "reason": "Latest price is required before directional price levels can be exposed.",
                    }
                ],
            },
        }

    entry = dict(levels.get("entry") or {})
    risk = dict(levels.get("risk") or {})
    legacy_short_stop = risk.pop("short_stop", None)
    if "short_term_stop" not in risk and isinstance(legacy_short_stop, dict):
        risk["short_term_stop"] = legacy_short_stop
    resistance: dict[str, Any] = {}
    violations: list[dict[str, str]] = []
    reclassified_fields: list[str] = []

    for field in ("aggressive_zone", "preferred_zone", "conservative_zone"):
        zone = entry.get(field)
        if not isinstance(zone, dict):
            continue
        low = _finite_number(zone.get("low"))
        high = _finite_number(zone.get("high"))
        if low is None or high is None:
            entry.pop(field, None)
            violations.append(
                {
                    "code": "ENTRY_ZONE_INVALID",
                    "field": f"entry.{field}",
                    "reason": "Entry zone was omitted because its bounds were incomplete.",
                }
            )
            continue
        if low > high:
            low, high = high, low
        if low >= latest_price:
            resistance[field] = {
                **zone,
                "low": _round_price(low),
                "high": _round_price(high),
                "label": "上方壓力區" if field != "aggressive_zone" else "反彈確認區",
                "basis": f"{zone.get('basis') or field}; reclassified because the full zone is above latest price",
            }
            entry.pop(field, None)
            reclassified_fields.append(f"entry.{field}")
            violations.append(
                {
                    "code": "ENTRY_ZONE_ABOVE_LATEST",
                    "field": f"entry.{field}",
                    "reason": "A zone fully above latest price cannot be labeled as a long pullback entry zone.",
                }
            )
            continue
        if high > latest_price:
            entry[field] = {
                **zone,
                "low": _round_price(low),
                "high": _round_price(latest_price),
                "basis": f"{zone.get('basis') or field}; capped at latest price by long-side invariant",
            }
            violations.append(
                {
                    "code": "ENTRY_ZONE_CAPPED_AT_LATEST",
                    "field": f"entry.{field}",
                    "reason": "The upper bound was capped so a long pullback zone does not extend above latest price.",
                }
            )

    for field in ("breakout_confirm_above", "do_not_chase_above"):
        level = entry.get(field)
        if not isinstance(level, dict):
            continue
        price = _finite_number(level.get("price"))
        if price is None or price <= latest_price:
            entry.pop(field, None)
            violations.append(
                {
                    "code": "UPSIDE_LEVEL_NOT_ABOVE_LATEST",
                    "field": f"entry.{field}",
                    "reason": "Breakout and chase thresholds must be strictly above latest price.",
                }
            )

    for field in ("short_term_stop", "technical_invalidation"):
        level = risk.get(field)
        if not isinstance(level, dict):
            continue
        price = _finite_number(level.get("price"))
        if price is None or price >= latest_price:
            risk.pop(field, None)
            violations.append(
                {
                    "code": "LONG_RISK_LEVEL_NOT_BELOW_LATEST",
                    "field": f"risk.{field}",
                    "reason": "A long-side stop or invalidation level must be strictly below latest price.",
                }
            )

    has_actionable_entry = any(
        field in entry
        for field in (
            "aggressive_zone",
            "preferred_zone",
            "conservative_zone",
            "breakout_confirm_above",
        )
    )
    has_risk_guardrail = any(
        field in risk for field in ("short_term_stop", "technical_invalidation")
    )
    decision_ready = has_actionable_entry and has_risk_guardrail
    if not has_actionable_entry:
        violations.append(
            {
                "code": "ENTRY_LEVELS_UNAVAILABLE",
                "field": "entry",
                "reason": "No valid long-side entry or breakout level remains after validation.",
            }
        )
    if not has_risk_guardrail:
        violations.append(
            {
                "code": "RISK_GUARDRAIL_UNAVAILABLE",
                "field": "risk",
                "reason": "No valid long-side stop or invalidation level remains after validation.",
            }
        )

    status = "ready" if decision_ready and not violations else "adjusted" if decision_ready else "unavailable"
    validated = {
        **levels,
        "entry": entry,
        "risk": risk,
        "validation": {
            "status": status,
            "position_side": "long",
            "latest_price": _round_price(latest_price),
            "decision_ready": decision_ready,
            "has_actionable_entry": has_actionable_entry,
            "has_risk_guardrail": has_risk_guardrail,
            "reclassified_fields": reclassified_fields,
            "violations": violations,
        },
    }
    if resistance:
        validated["resistance"] = resistance
    canonical_stop = validated["risk"].get("short_term_stop")
    if isinstance(canonical_stop, dict):
        validated["risk"]["short_stop"] = {
            **canonical_stop,
            "deprecated_alias_for": "short_term_stop",
        }
    if not decision_ready:
        validated["summary"] = list(levels.get("summary") or []) + [
            "部分價位未通過多方不變量檢查；在有效進場與風控線同時可用前，不形成可執行交易建議。"
        ]
    return validated


def _indicator_from_report(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    indicator = data.get("daily_indicator") or data.get("indicator") or {}
    return indicator if isinstance(indicator, dict) else {}


def _indicator_level_values(indicator: dict[str, Any]) -> dict[str, float | None]:
    technical_parameters = get_technical_analysis_parameters()
    ma = indicator.get("ma") if isinstance(indicator.get("ma"), dict) else {}
    atr = indicator.get("atr") if isinstance(indicator.get("atr"), dict) else {}
    donchian = indicator.get("donchian") if isinstance(indicator.get("donchian"), dict) else {}
    rsi = indicator.get("rsi") if isinstance(indicator.get("rsi"), dict) else {}
    return {
        "close": _finite_number(indicator.get("close")),
        "ma5": _finite_number(_indicator_value(ma, technical_parameters.ma_short_key, "ma5")),
        "ma20": _finite_number(_indicator_value(ma, technical_parameters.ma_medium_key, "ma20")),
        "ma60": _finite_number(_indicator_value(ma, technical_parameters.ma_long_key, "ma60")),
        "atr14": _finite_number(_indicator_value(atr, technical_parameters.atr_key, "atr14")),
        "donchian_upper20": _finite_number(
            _indicator_value(donchian, technical_parameters.donchian_upper_key, "upper20")
        ),
        "donchian_lower20": _finite_number(
            _indicator_value(donchian, technical_parameters.donchian_lower_key, "lower20")
        ),
        "rsi14": _finite_number(_indicator_value(rsi, technical_parameters.rsi_key, "rsi14")),
    }


def _donchian_position(latest_price: float, upper: float | None, lower: float | None) -> float | None:
    if upper is None or lower is None or upper == lower:
        return None
    return round((latest_price - lower) / (upper - lower) * 100, 2)


def _technical_price_levels(
    *,
    technical_reports: dict[str, Any],
    latest_daily: Any,
    resolved_current_price: dict[str, Any] | None = None,
) -> dict[str, Any]:
    technical_parameters = get_technical_analysis_parameters()
    daily_report = technical_reports.get("daily") if isinstance(technical_reports, dict) else {}
    daily_indicator = _indicator_from_report(daily_report)
    daily_values = _indicator_level_values(daily_indicator)

    daily_basis_price = (
        _finite_number(_source_value(latest_daily, "close_price"))
        or _finite_number(_source_value(latest_daily, "close"))
        or daily_values.get("close")
    )
    resolved = (
        resolved_current_price
        if isinstance(resolved_current_price, dict)
        else {}
    )
    resolved_price = (
        _finite_number(resolved.get("value"))
        if resolved.get("is_estimate") is not True
        else None
    )
    latest_price = resolved_price or daily_basis_price
    if latest_price is None or latest_price <= 0:
        return {}
    daily_basis_date = (
        _json_value(_source_value(latest_daily, "trade_date"))
        or daily_indicator.get("time")
    )
    current_price_time = (
        _json_value(resolved.get("event_time"))
        if resolved_price is not None
        else None
    )
    price_basis_date = (
        _json_value(resolved.get("trade_date"))
        or (
            str(current_price_time)[:10]
            if current_price_time
            else None
        )
        or daily_basis_date
    )

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
        or (weekly_rsi is not None and weekly_rsi >= technical_parameters.rsi_overheated_at)
        or (atr_pct is not None and atr_pct >= technical_parameters.atr_high_volatility_pct)
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
    short_term_stop_anchor = ma5 - atr_buffer * 0.75 if ma5 is not None else latest_price - atr_buffer
    if preferred_low is not None:
        short_term_stop_anchor = min(
            short_term_stop_anchor,
            preferred_low - atr_buffer * 0.5,
        )
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
        "short_term_stop": _price_level(
            short_term_stop_anchor,
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

    levels = {
        "kind": "technical_price_levels",
        "version": "price_levels_v1",
        "as_of": current_price_time or daily_basis_date,
        "latest_price": _round_price(latest_price),
        "basis_timeframe": (
            "intraday_with_daily_structure"
            if resolved_price is not None
            else "daily"
        ),
        "price_basis_date": price_basis_date,
        "current_price_time": current_price_time,
        "current_price_source": (
            resolved.get("source_kind")
            if resolved_price is not None
            else "completed_daily_close"
        ),
        "technical_price_basis": (
            resolved.get("semantics")
            or resolved.get("source_kind")
            or "resolved_current_price"
        )
        if resolved_price is not None
        else "official_completed_daily_close",
        "bid_ask_price_used": False,
        "daily_basis_date": daily_basis_date,
        "daily_basis_price": _round_price(daily_basis_price),
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
    return _validate_long_price_levels(levels)


def _normalize_technical_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close = _finite_number(
            _first_value(
                row,
                (
                    "close",
                    "close_price",
                    "last_price",
                    "settlement_price",
                    "price",
                ),
            )
        )
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
                "session": _json_value(row.get("session")),
            }
        )
    return points


def _technical_report_from_points(
    *,
    points: list[dict[str, Any]],
    timeframe: str,
    asset_label: str,
) -> dict[str, Any]:
    technical_parameters = get_technical_analysis_parameters()
    short_window = technical_parameters.ma_short_window or 5
    medium_window = technical_parameters.ma_medium_window or 20
    long_window = technical_parameters.ma_long_window or 60
    structure_window = technical_parameters.donchian_period
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
    ma5 = _moving_average(closes, short_window)
    ma20 = _moving_average(closes, medium_window)
    ma60 = _moving_average(closes, long_window)
    change_1 = _pct_change(previous, latest)
    change_5 = _pct_change(closes[-(short_window + 1)], latest) if len(closes) >= short_window + 1 else None
    change_20 = _pct_change(closes[-(medium_window + 1)], latest) if len(closes) >= medium_window + 1 else None

    is_intraday = timeframe == "today"
    change_deadband_pct = 0.15 if is_intraday else 0.0
    ma_deadband_pct = 0.10 if is_intraday else 0.0
    range_signal_min_span_pct = 0.30 if is_intraday else 0.0

    def direction_score(value: float | None, *, deadband: float) -> int:
        if value is None or abs(value) <= deadband:
            return 0
        return 1 if value > 0 else -1

    def ma_distance_pct(average: float | None) -> float | None:
        return _pct_change(average, latest)

    ma5_distance = ma_distance_pct(ma5)
    ma20_distance = ma_distance_pct(ma20)
    ma60_distance = ma_distance_pct(ma60)
    factor_scores: dict[str, dict[str, Any]] = {
        "ma_short": {
            "observed_pct": ma5_distance,
            "deadband_pct": ma_deadband_pct,
            "score": direction_score(ma5_distance, deadband=ma_deadband_pct),
        },
        "ma_medium": {
            "observed_pct": ma20_distance,
            "deadband_pct": ma_deadband_pct,
            "score": direction_score(ma20_distance, deadband=ma_deadband_pct),
        },
        "ma_long": {
            "observed_pct": ma60_distance,
            "deadband_pct": ma_deadband_pct,
            "score": direction_score(ma60_distance, deadband=ma_deadband_pct),
        },
        "change_short": {
            "observed_pct": change_5,
            "deadband_pct": change_deadband_pct,
            "score": direction_score(change_5, deadband=change_deadband_pct),
        },
        "change_medium": {
            "observed_pct": change_20,
            "deadband_pct": change_deadband_pct,
            "score": direction_score(change_20, deadband=change_deadband_pct),
        },
    }

    recent_range = closes[-structure_window:] if len(closes) >= structure_window else closes
    recent_high = max(recent_range)
    recent_low = min(recent_range)
    range_span_pct = _pct_change(recent_low, recent_high)
    range_position_score = 0
    position = None
    if recent_high > recent_low:
        position = (latest - recent_low) / (recent_high - recent_low)
        if range_span_pct is not None and range_span_pct >= range_signal_min_span_pct:
            if position >= 0.75:
                range_position_score = 1
            elif position <= 0.25:
                range_position_score = -1

    factor_scores["range_position"] = {
        "position": position,
        "range_span_pct": range_span_pct,
        "minimum_span_pct": range_signal_min_span_pct,
        "score": range_position_score,
    }
    raw_score = sum(int(factor["score"]) for factor in factor_scores.values())

    score = max(-5, min(5, raw_score))
    if is_intraday and score >= 4:
        title = "盤中偏強"
    elif is_intraday and score >= 1:
        title = "盤中震盪偏強"
    elif is_intraday and score <= -4:
        title = "盤中偏弱"
    elif is_intraday and score <= -1:
        title = "盤中震盪偏弱"
    elif is_intraday:
        title = "盤中震盪"
    elif score >= 4:
        title = "波段偏多"
    elif score >= 1:
        title = "偏多觀察"
    elif score <= -4:
        title = "波段偏空"
    elif score <= -1:
        title = "偏弱觀察"
    else:
        title = "方向未定"

    confidence = "high" if len(closes) >= long_window else "medium" if len(closes) >= medium_window else "low"
    effect_size_pct = max(
        (abs(value) for value in (change_1, change_5, change_20) if value is not None),
        default=0.0,
    )
    confidence_reasons = [
        f"point_count={len(closes)}",
        f"max_observed_change={effect_size_pct:.4f}%",
    ]
    if is_intraday and effect_size_pct <= change_deadband_pct:
        confidence = "low"
        confidence_reasons.append(
            f"盤中變動未超過 {change_deadband_pct:.2f}% deadband，不支持高信心方向判定。"
        )
    elif is_intraday and effect_size_pct <= change_deadband_pct * 2 and confidence == "high":
        confidence = "medium"
        confidence_reasons.append("盤中變動幅度有限，信心上限調降為 medium。")
    else:
        confidence_reasons.append("樣本數與變動幅度支持目前信心等級。")
    relation_parts = []
    if ma20_distance is not None:
        relation_parts.append(
            f"{'貼近' if abs(ma20_distance) <= ma_deadband_pct else '站上' if ma20_distance > 0 else '跌破'} MA{medium_window}"
        )
    if ma60_distance is not None:
        relation_parts.append(
            f"{'貼近' if abs(ma60_distance) <= ma_deadband_pct else '站上' if ma60_distance > 0 else '跌破'} MA{long_window}"
        )
    relation_text = "、".join(relation_parts) if relation_parts else "均線資料有限"
    summary = (
        f"最新 {_format_number(latest)}，單期 {_format_pct(change_1)}、"
        f"{short_window}期 {_format_pct(change_5)}、{medium_window}期 {_format_pct(change_20)}；{relation_text}。"
    )

    return {
        "timeframe": timeframe,
        "phase": "intraday" if is_intraday else "historical",
        "score": score,
        "title": title,
        "summary": summary,
        "confidence": confidence,
        "confidence_reasons": confidence_reasons,
        "point_count": len(closes),
        "latest_close": latest,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "change_1_pct": change_1,
        "change_5_pct": change_5,
        "change_20_pct": change_20,
        "effect_size": {
            "max_observed_change_pct": effect_size_pct,
            "range_span_pct": range_span_pct,
            "change_deadband_pct": change_deadband_pct,
            "ma_deadband_pct": ma_deadband_pct,
        },
        "factor_scores": factor_scores,
        "raw_score": raw_score,
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
