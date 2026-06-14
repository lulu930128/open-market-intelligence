from datetime import date, datetime, timezone
import math
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
    StockMaster,
)
from app.ai.evidence_passport import build_evidence_passport
from app.market import service as market_service
from app.market.technical_report import build_stock_technical_report
from app.market.broker_branch import get_broker_branch_trade_summary
from app.market.indices import (
    get_market_index_contributions,
    get_market_index_intraday,
    get_market_index_ohlc_chart_data,
    get_market_index_summary,
)
from app.market.market_chips import get_latest_market_chip_daily, market_chip_daily_to_dict
from app.market.overnight_impact import build_us_overnight_impact_report
from app.market.tw_futures import (
    get_latest_taiwan_futures_quotes,
    list_taiwan_futures_daily_bars,
    list_taiwan_futures_intraday_bars,
    normalize_taiwan_futures_symbols,
    taiwan_futures_daily_bar_to_dict,
    taiwan_futures_intraday_bar_to_dict,
    taiwan_futures_quote_to_dict,
)
from app.stocks import service as stock_service
from app.watchlists import ranking_service
from app.watchlists import service as watchlist_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return value


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if row is None:
        return None

    return {field: _json_value(getattr(row, field, None)) for field in fields}


def _stock_dict(stock: StockMaster | None) -> dict[str, Any] | None:
    return _row_dict(
        stock,
        (
            "stock_id",
            "stock_name",
            "market",
            "instrument_type",
            "industry",
            "category",
            "is_active",
            "notes",
            "last_seen_at",
            "updated_at",
        ),
    )


def _latest_financial_period(row: FinancialMetricQuarterly | None) -> str | None:
    if row is None:
        return None

    return row.period or f"{row.fiscal_year}Q{row.quarter}"


def _latest_date_string(values: list[Any]) -> str | None:
    valid_values = [_json_value(value) for value in values if value is not None]

    if not valid_values:
        return None

    return str(max(valid_values))


def _broker_branch_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return {key: _json_value(value) for key, value in row.items()}

    return _row_dict(
        row,
        (
            "trade_date",
            "stock_id",
            "stock_name",
            "branch_code",
            "branch_name",
            "buy_lots",
            "sell_lots",
            "net_lots",
            "buy_avg_price",
            "sell_avg_price",
            "buy_rank",
            "sell_rank",
            "source_label",
        ),
    ) or {}


def _add_missing(missing: list[str], key: str, value: Any) -> None:
    if value is None or value == []:
        missing.append(key)


def _with_evidence_passport(
    envelope: dict[str, Any],
    *,
    freshness: dict[str, Any] | None = None,
    tool_runs: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    envelope["evidence_passport"] = build_evidence_passport(
        kind=str(envelope.get("kind") or "ai_data"),
        as_of=envelope.get("as_of"),
        source_refs=envelope.get("source_refs") or [],
        missing=envelope.get("missing") or [],
        warnings=envelope.get("warnings") or [],
        freshness=freshness,
        tool_runs=tool_runs,
        analysis=analysis or data.get("analysis"),
        confidence=confidence,
    )
    return envelope


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


def _format_lots(value: float | None) -> str | None:
    if value is None:
        return None
    lots = value / 1000
    if abs(lots) >= 100:
        return f"{lots:,.0f} 張"
    return f"{lots:,.1f}".rstrip("0").rstrip(".") + " 張"


def _decision_data_quality(
    *,
    latest_daily: Any,
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    close_price = _finite_number(_source_value(latest_daily, "close_price"))
    trade_volume = _finite_number(_source_value(latest_daily, "trade_volume"))
    trade_date = _json_value(_source_value(latest_daily, "trade_date"))
    return {
        "as_of": trade_date,
        "price": {
            "value": _round_price(close_price),
            "source": "market_daily_price.close_price",
            "as_of": trade_date,
        },
        "volume": {
            "value": trade_volume,
            "unit": "shares",
            "display_unit": "lots",
            "display_value": _format_lots(trade_volume),
            "source": "market_daily_price.trade_volume",
            "as_of": trade_date,
        },
        "source_names": [
            str(ref.get("name"))
            for ref in source_refs
            if isinstance(ref, dict) and ref.get("name")
        ],
    }


def _market_session_evidence(
    *,
    technical_reports: dict[str, Any],
    latest_daily: Any,
) -> dict[str, Any]:
    today_report = (
        technical_reports.get("today")
        if isinstance(technical_reports, dict) and isinstance(technical_reports.get("today"), dict)
        else {}
    )
    data = today_report.get("data") if isinstance(today_report.get("data"), dict) else {}
    market_session = (
        data.get("market_session")
        if isinstance(data.get("market_session"), dict)
        else {}
    )
    latest_daily_date = (
        _json_value(_source_value(latest_daily, "trade_date"))
        or market_session.get("latest_daily_date")
        or market_session.get("previous_trading_day")
    )
    phase = str(today_report.get("phase") or "")

    if phase == "market_closed":
        session_date = market_session.get("date")
        next_trading_day = market_session.get("next_trading_day")
        summary = (
            str(market_session.get("summary"))
            if market_session.get("summary")
            else (
                f"{session_date or '今日'} 台股休市，最新日線截至 {latest_daily_date or '-'}；"
                f"下一交易日 {next_trading_day or '-'} 再確認盤中價量。"
            )
        )
        return {
            "phase": phase,
            "is_trading_day": False,
            "date": session_date,
            "reason": market_session.get("reason"),
            "holiday_name": market_session.get("holiday_name"),
            "previous_trading_day": market_session.get("previous_trading_day"),
            "next_trading_day": next_trading_day,
            "latest_daily_date": latest_daily_date,
            "summary": summary,
            "source": "technical_reports.today.data.market_session",
        }

    if market_session:
        return {
            "phase": phase or None,
            "is_trading_day": market_session.get("is_trading_day"),
            "date": market_session.get("date"),
            "previous_trading_day": market_session.get("previous_trading_day"),
            "next_trading_day": market_session.get("next_trading_day"),
            "latest_daily_date": latest_daily_date,
            "summary": market_session.get("summary"),
            "source": "technical_reports.today.data.market_session",
        }

    return {
        "phase": phase or None,
        "is_trading_day": None,
        "latest_daily_date": latest_daily_date,
    }


def _recent_volatility_evidence(chart: dict[str, Any], *, lookback: int = 5) -> dict[str, Any]:
    raw_points = chart.get("points") if isinstance(chart, dict) else []
    points = _normalize_technical_points([point for point in raw_points if isinstance(point, dict)])
    if len(points) < 2:
        return {
            "lookback_days": lookback,
            "label": "unknown",
            "summary": "近幾日波動資料不足。",
            "returns": [],
        }

    recent = points[-(lookback + 1) :]
    returns: list[dict[str, Any]] = []
    for previous, current in zip(recent, recent[1:]):
        change_pct = _pct_change(previous.get("close"), current.get("close"))
        returns.append(
            {
                "time": current.get("time"),
                "close": _round_price(current.get("close")),
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
            }
        )

    recent_window = recent[1:] if len(recent) > 1 else recent
    highs = [_finite_number(point.get("high")) for point in recent_window]
    lows = [_finite_number(point.get("low")) for point in recent_window]
    highs = [value for value in highs if value is not None]
    lows = [value for value in lows if value is not None]
    latest_close = _finite_number(recent_window[-1].get("close")) if recent_window else None
    range_pct = (
        ((max(highs) - min(lows)) / latest_close) * 100
        if highs and lows and latest_close not in (None, 0.0)
        else None
    )
    abs_changes = [
        abs(float(item["change_pct"]))
        for item in returns
        if isinstance(item.get("change_pct"), (int, float))
    ]
    max_abs_change = max(abs_changes) if abs_changes else None
    large_move_days = sum(1 for value in abs_changes if value >= 5)

    if (max_abs_change is not None and max_abs_change >= 5) or (range_pct is not None and range_pct >= 12) or large_move_days >= 2:
        label = "high"
        label_text = "高波動"
    elif (max_abs_change is not None and max_abs_change >= 3) or (range_pct is not None and range_pct >= 7) or large_move_days >= 1:
        label = "elevated"
        label_text = "波動偏高"
    else:
        label = "normal"
        label_text = "波動正常"

    summary_parts = [f"近 {min(lookback, len(returns))} 日{label_text}"]
    if max_abs_change is not None:
        summary_parts.append(f"最大單日漲跌約 {_format_pct(max_abs_change)}")
    if range_pct is not None:
        summary_parts.append(f"區間振幅約 {_format_pct(range_pct)}")
    if large_move_days:
        summary_parts.append(f"{large_move_days} 日漲跌超過 5%")

    return {
        "lookback_days": min(lookback, len(returns)),
        "label": label,
        "summary": "，".join(summary_parts) + "。",
        "max_abs_change_pct": round(max_abs_change, 2) if max_abs_change is not None else None,
        "range_pct": round(range_pct, 2) if range_pct is not None else None,
        "large_move_days": large_move_days,
        "returns": returns,
    }


def _indicator_quality_evidence(technical_reports: dict[str, Any]) -> dict[str, Any]:
    daily_report = technical_reports.get("daily") if isinstance(technical_reports, dict) else {}
    indicator = _indicator_from_report(daily_report)
    macd = indicator.get("macd") if isinstance(indicator.get("macd"), dict) else {}
    macd_value = _finite_number(macd.get("macd"))
    signal_value = _finite_number(macd.get("signal"))
    histogram = _finite_number(macd.get("histogram"))
    expected_histogram = (
        macd_value - signal_value
        if macd_value is not None and signal_value is not None
        else None
    )
    histogram_delta = (
        abs(histogram - expected_histogram)
        if histogram is not None and expected_histogram is not None
        else None
    )
    tolerance = max(0.05, abs(expected_histogram or 0) * 0.05)
    is_consistent = histogram_delta is None or histogram_delta <= tolerance
    warnings = []
    if not is_consistent:
        warnings.append("MACD histogram 與 MACD-signal 不一致，需確認欄位口徑或正負號。")

    return {
        "macd": {
            "macd": round(macd_value, 4) if macd_value is not None else None,
            "signal": round(signal_value, 4) if signal_value is not None else None,
            "histogram": round(histogram, 4) if histogram is not None else None,
            "expected_histogram": round(expected_histogram, 4) if expected_histogram is not None else None,
            "is_consistent": is_consistent,
            "tone": "positive" if histogram is not None and histogram > 0 else "negative" if histogram is not None and histogram < 0 else "neutral",
            "source": "technical_reports.daily.data.daily_indicator.macd",
        },
        "warnings": warnings,
    }


def _fundamental_evidence(
    *,
    latest_revenue: Any,
    latest_financial: Any,
) -> dict[str, Any]:
    revenue_yoy = _finite_number(_source_value(latest_revenue, "year_over_year_pct"))
    revenue_mom = _finite_number(_source_value(latest_revenue, "month_over_month_pct"))
    cumulative_yoy = _finite_number(_source_value(latest_revenue, "cumulative_year_over_year_pct"))
    revenue_period = _json_value(_source_value(latest_revenue, "period"))
    revenue_summary = None
    if latest_revenue is not None:
        parts = [f"{revenue_period} 營收"] if revenue_period else ["最新營收"]
        if revenue_yoy is not None:
            parts.append(f"年增 {_format_pct(revenue_yoy)}")
        if revenue_mom is not None:
            parts.append(f"月增 {_format_pct(revenue_mom)}")
        if cumulative_yoy is not None:
            parts.append(f"累計年增 {_format_pct(cumulative_yoy)}")
        revenue_summary = "，".join(parts) + "。"

    eps = _finite_number(_source_value(latest_financial, "eps"))
    roe = _finite_number(_source_value(latest_financial, "roe"))
    financial_period = _latest_financial_period(latest_financial)
    financial_summary = None
    if latest_financial is not None:
        parts = [f"{financial_period} 財報"] if financial_period else ["最新財報"]
        if eps is not None:
            parts.append(f"EPS {_format_number(eps)}")
        if roe is not None:
            parts.append(f"ROE {_format_pct(roe)}")
        financial_summary = "，".join(parts) + "。"

    return {
        "monthly_revenue": {
            "period": revenue_period,
            "year_over_year_pct": revenue_yoy,
            "month_over_month_pct": revenue_mom,
            "cumulative_year_over_year_pct": cumulative_yoy,
            "summary": revenue_summary,
            "tone": "positive" if (revenue_yoy is not None and revenue_yoy >= 10) or (cumulative_yoy is not None and cumulative_yoy >= 10) else "negative" if revenue_yoy is not None and revenue_yoy < 0 else "neutral",
        },
        "financial": {
            "period": financial_period,
            "eps": eps,
            "roe": roe,
            "summary": financial_summary,
            "tone": "positive" if eps is not None and eps > 0 else "neutral",
        },
    }


def _decision_confidence_factors(
    *,
    technical_reports: dict[str, Any],
    volatility: dict[str, Any],
    indicator_quality: dict[str, Any],
    fundamentals: dict[str, Any],
    missing: list[str],
) -> dict[str, list[str]]:
    positives: list[str] = []
    negatives: list[str] = []
    data_limits: list[str] = []
    daily_indicator = _indicator_from_report(
        technical_reports.get("daily") if isinstance(technical_reports, dict) else {}
    )
    values = _indicator_level_values(daily_indicator)
    close = values.get("close")
    ma20 = values.get("ma20")
    if close is not None and ma20 is not None:
        if close >= ma20:
            positives.append("收盤站上 MA20。")
        else:
            negatives.append("收盤跌破 MA20。")

    volume_ratio = None
    volume_ma = daily_indicator.get("volume_ma") if isinstance(daily_indicator.get("volume_ma"), dict) else {}
    volume = _finite_number(daily_indicator.get("volume"))
    volume_ma20 = _finite_number(volume_ma.get("volume_ma20"))
    if volume is not None and volume_ma20 not in (None, 0.0):
        volume_ratio = volume / volume_ma20
    if volume_ratio is not None and volume_ratio >= 1.5:
        positives.append(f"量能約為 20 日均量 {volume_ratio:.1f} 倍。")

    if volatility.get("label") in {"high", "elevated"}:
        negatives.append(str(volatility.get("summary") or "近期波動偏高。"))

    macd = indicator_quality.get("macd") if isinstance(indicator_quality.get("macd"), dict) else {}
    if macd.get("is_consistent") is False:
        negatives.append("MACD histogram 口徑需校驗。")
    elif macd.get("tone") == "positive":
        positives.append("MACD histogram 為正。")
    elif macd.get("tone") == "negative":
        negatives.append("MACD histogram 為負。")

    revenue = fundamentals.get("monthly_revenue") if isinstance(fundamentals.get("monthly_revenue"), dict) else {}
    if revenue.get("summary"):
        if revenue.get("tone") == "positive":
            positives.append(str(revenue["summary"]))
        elif revenue.get("tone") == "negative":
            negatives.append(str(revenue["summary"]))

    for key in missing:
        if key in {"monthly_revenue", "financial_metric_quarterly", "institutional_trade_daily", "broker_branch_trade_daily"}:
            data_limits.append(f"{key} 尚缺或不完整。")

    return {
        "positive": list(dict.fromkeys(positives))[:4],
        "negative": list(dict.fromkeys(negatives))[:4],
        "data_limits": list(dict.fromkeys(data_limits))[:4],
    }


def _stock_decision_evidence(
    *,
    latest_daily: Any,
    chart: dict[str, Any],
    latest_revenue: Any,
    latest_financial: Any,
    technical_reports: dict[str, Any],
    missing: list[str],
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    market_session = _market_session_evidence(
        technical_reports=technical_reports,
        latest_daily=latest_daily,
    )
    volatility = _recent_volatility_evidence(chart)
    indicator_quality = _indicator_quality_evidence(technical_reports)
    fundamentals = _fundamental_evidence(
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
    )
    confidence_factors = _decision_confidence_factors(
        technical_reports=technical_reports,
        volatility=volatility,
        indicator_quality=indicator_quality,
        fundamentals=fundamentals,
        missing=missing,
    )
    return {
        "kind": "stock_decision_evidence_v1",
        "data_quality": _decision_data_quality(
            latest_daily=latest_daily,
            source_refs=source_refs,
        ),
        "market_session": market_session,
        "recent_volatility": volatility,
        "indicator_quality": indicator_quality,
        "fundamentals": fundamentals,
        "confidence_factors": confidence_factors,
    }


def _json_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _json_value(value) for key, value in row.items()}


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


def list_ai_tools(*, include_internal: bool = False) -> dict[str, Any]:
    tool_list = [
            {
                "name": "omi.ask",
                "title": "Ask OMI",
                "description": (
                    "Single OMI entry point. It chooses data_only, brief, analysis, or report mode "
                    "from a question and policy flags."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "contract_version": {
                            "type": "string",
                            "default": "omi.ai.ask.v2",
                        },
                        "question": {"type": "string"},
                        "target": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "auto",
                                        "market",
                                        "data_freshness",
                                        "tw_stock",
                                        "tw_watchlist",
                                        "tw_index",
                                        "tw_futures",
                                        "us_stock",
                                    ],
                                    "default": "auto",
                                },
                                "id": {"type": "string"},
                                "label": {"type": "string"},
                                "market": {"type": "string"},
                            },
                            "default": {"type": "auto"},
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["auto", "data_only", "brief", "analysis", "report"],
                            "default": "auto",
                        },
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                            "default": "short_term_momentum",
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                            "description": "Analysis horizon. auto defaults to swing, meaning medium-short-term evidence.",
                        },
                        "caller_profile": {
                            "type": "string",
                            "default": "kuro_readonly",
                            "description": "Caller label only. Server-side policy decides trust.",
                        },
                        "allow_llm": {
                            "type": "boolean",
                            "default": False,
                            "description": "Must be true for analysis/report mode and requires server-side trust.",
                        },
                        "allow_write": {
                            "type": "boolean",
                            "default": False,
                            "description": "Required only for persisted report mode.",
                        },
                        "allow_external_fetch": {
                            "type": "boolean",
                            "default": False,
                            "description": "Allow trusted OMI backend to call configured external market APIs and update local evidence cache.",
                        },
                        "tool_budget": {
                            "type": "object",
                            "properties": {
                                "max_calls": {"type": "integer", "minimum": 0, "maximum": 12, "default": 5},
                                "max_external_fetches": {"type": "integer", "minimum": 0, "maximum": 8, "default": 3},
                                "max_total_seconds": {"type": "integer", "minimum": 1, "maximum": 90, "default": 25},
                            },
                        },
                        "refresh_policy": {
                            "type": "object",
                            "properties": {
                                "mode": {"type": "string", "enum": ["stale_first", "off"], "default": "stale_first"},
                                "before_answer": {"type": "boolean", "default": True},
                                "fallback_to_cached": {"type": "boolean", "default": True},
                            },
                            "description": "Controls whether OMI should refresh stale local evidence before answering.",
                        },
                        "conversation_context": {
                            "type": "object",
                            "description": "Optional caller context such as prior OMI resolution.",
                        },
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "omi.read_market_overview",
                "title": "Read Market Overview",
                "description": "Read latest local market breadth and top movers from OMI data.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "omi.read_stock_context",
                "title": "Read Stock Context",
                "description": "Read an evidence pack for one stock from local OMI data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stock_id": {"type": "string"},
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                        "include_intraday": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include live Taiwan intraday technical report when trusted external fetch is allowed.",
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                    },
                    "required": ["stock_id"],
                },
            },
            {
                "name": "omi.read_tw_index_context",
                "title": "Read Taiwan Index Context",
                "description": "Read an evidence pack for TAIEX/TPEX from market index, chip, and chart data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "index_id": {"type": "string", "enum": ["TAIEX", "TPEX"]},
                        "include_intraday": {"type": "boolean", "default": False},
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                    },
                    "required": ["index_id"],
                },
            },
            {
                "name": "omi.read_tw_futures_context",
                "title": "Read Taiwan Futures Context",
                "description": "Read an evidence pack for TXF/MXF/TMF from TAIFEX futures quote and bar data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "enum": ["TXF", "MXF", "TMF"]},
                        "include_intraday": {"type": "boolean", "default": False},
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_us_stock_context",
                "title": "Read US Stock Context",
                "description": "Read an evidence pack for one US stock from local OMI data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.read_watchlist_context",
                "title": "Read Watchlist Context",
                "description": "Read ranking and signal context for a watchlist group.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "group_id": {"type": "integer"},
                        "rank_by": {
                            "type": "string",
                            "enum": ["watchlist", "score", "change_pct", "volume"],
                        },
                    },
                    "required": ["group_id"],
                },
            },
            {
                "name": "omi.read_data_freshness",
                "title": "Read Data Freshness",
                "description": "Read latest local data dates and row counts, optionally for one stock.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stock_id": {"type": "string"},
                    },
                },
            },
            {
                "name": "omi.generate_stock_brief",
                "title": "Generate Stock Brief",
                "description": "Generate a prompt-ready stock brief envelope from local OMI evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stock_id": {"type": "string"},
                        "include_intraday": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include live Taiwan intraday technical report when trusted external fetch is allowed.",
                        },
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                    },
                    "required": ["stock_id"],
                },
            },
            {
                "name": "omi.generate_us_stock_brief",
                "title": "Generate US Stock Brief",
                "description": "Generate a prompt-ready US stock brief envelope from local OMI evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.generate_watchlist_brief",
                "title": "Generate Watchlist Brief",
                "description": "Generate a prompt-ready watchlist brief envelope from local OMI evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "group_id": {"type": "integer"},
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                        },
                        "rank_by": {
                            "type": "string",
                            "enum": ["watchlist", "score", "change_pct", "volume"],
                        },
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                    },
                    "required": ["group_id"],
                },
            },
            {
                "name": "omi.generate_stock_llm_report",
                "title": "Generate Stock LLM Report",
                "description": "Generate and persist an OpenAI-backed stock research report from local OMI evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stock_id": {"type": "string"},
                        "include_intraday": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include live Taiwan intraday technical report when trusted external fetch is allowed.",
                        },
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                    },
                    "required": ["stock_id"],
                },
            },
            {
                "name": "omi.generate_us_stock_llm_report",
                "title": "Generate US Stock LLM Report",
                "description": "Generate and persist an OpenAI-backed US stock research report from local OMI evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.generate_watchlist_llm_report",
                "title": "Generate Watchlist LLM Report",
                "description": "Generate and persist an OpenAI-backed watchlist research report from local OMI evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "group_id": {"type": "integer"},
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                        },
                        "rank_by": {
                            "type": "string",
                            "enum": ["watchlist", "score", "change_pct", "volume"],
                        },
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                    },
                    "required": ["group_id"],
                },
            },
            {
                "name": "omi.read_memories",
                "title": "Read AI Memories",
                "description": "Read OMI AI research memories by scope, type, status, or keyword.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_type": {"type": "string"},
                        "scope_type": {"type": "string"},
                        "scope_id": {"type": "string"},
                        "status": {"type": "string"},
                        "keyword": {"type": "string"},
                    },
                },
            },
            {
                "name": "omi.write_memory",
                "title": "Write AI Memory",
                "description": "Create a correctable OMI AI research memory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_type": {"type": "string"},
                        "scope_type": {"type": "string"},
                        "scope_id": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                    "required": ["memory_type", "title", "content"],
                },
            },
            {
                "name": "omi.update_memory",
                "title": "Update AI Memory",
                "description": "Update an existing OMI AI research memory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
                        "status": {"type": "string"},
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "omi.archive_memory",
                "title": "Archive AI Memory",
                "description": "Archive an OMI AI research memory without deleting it.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "integer"},
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "omi.read_reports",
                "title": "Read AI Reports",
                "description": "List saved OMI AI reports.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "report_type": {"type": "string"},
                        "scope_type": {"type": "string"},
                        "scope_id": {"type": "string"},
                        "strategy_profile": {"type": "string"},
                    },
                },
            },
            {
                "name": "omi.read_report",
                "title": "Read AI Report",
                "description": "Read one saved OMI AI report by id.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "report_id": {"type": "integer"},
                    },
                    "required": ["report_id"],
                },
            },
            {
                "name": "omi.save_stock_brief",
                "title": "Save Stock Brief",
                "description": "Generate and persist a stock brief report in OMI.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stock_id": {"type": "string"},
                        "include_intraday": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include live Taiwan intraday technical report when trusted external fetch is allowed.",
                        },
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                        "branch_days": {"type": "integer", "minimum": 1, "maximum": 120},
                    },
                    "required": ["stock_id"],
                },
            },
            {
                "name": "omi.save_us_stock_brief",
                "title": "Save US Stock Brief",
                "description": "Generate and persist a US stock brief report in OMI.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                        },
                        "analysis_horizon": {
                            "type": "string",
                            "enum": ["auto", "intraday", "short", "swing", "long"],
                            "default": "auto",
                        },
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "omi.save_watchlist_brief",
                "title": "Save Watchlist Brief",
                "description": "Generate and persist a watchlist brief report in OMI.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "group_id": {"type": "integer"},
                        "strategy_profile": {
                            "type": "string",
                            "enum": [
                                "balanced",
                                "technical_swing",
                                "short_term_momentum",
                                "chip_flow",
                                "fundamentals_growth",
                                "dividend_value",
                            ],
                        },
                        "rank_by": {
                            "type": "string",
                            "enum": ["watchlist", "score", "change_pct", "volume"],
                        },
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                    },
                    "required": ["group_id"],
                },
            },
    ]

    if not include_internal:
        tool_list = tool_list[:1]

    return {"tools": tool_list}


def read_data_freshness(db: Session, stock_id: str | None = None) -> dict[str, Any]:
    def latest(model: Any, column: Any) -> Any:
        query = db.query(func.max(column))
        if stock_id and hasattr(model, "stock_id"):
            query = query.filter(model.stock_id == stock_id)
        return query.scalar()

    def count(model: Any) -> int:
        query = db.query(func.count(model.id))
        if stock_id and hasattr(model, "stock_id"):
            query = query.filter(model.stock_id == stock_id)
        return int(query.scalar() or 0)

    financial_latest = (
        db.query(FinancialMetricQuarterly)
        .filter(FinancialMetricQuarterly.stock_id == stock_id)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
        if stock_id
        else db.query(FinancialMetricQuarterly)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
    )

    tables = {
        "market_daily_price": {
            "latest": _json_value(latest(MarketDailyPrice, MarketDailyPrice.trade_date)),
            "row_count": count(MarketDailyPrice),
        },
        "institutional_trade_daily": {
            "latest": _json_value(latest(InstitutionalTradeDaily, InstitutionalTradeDaily.trade_date)),
            "row_count": count(InstitutionalTradeDaily),
        },
        "margin_trading_daily": {
            "latest": _json_value(latest(MarginTradingDaily, MarginTradingDaily.trade_date)),
            "row_count": count(MarginTradingDaily),
        },
        "broker_branch_trade_daily": {
            "latest": _json_value(latest(BrokerBranchTradeDaily, BrokerBranchTradeDaily.trade_date)),
            "row_count": count(BrokerBranchTradeDaily),
        },
        "shareholding_distribution_weekly": {
            "latest": _json_value(
                latest(ShareholdingDistributionWeekly, ShareholdingDistributionWeekly.data_date)
            ),
            "row_count": count(ShareholdingDistributionWeekly),
        },
        "monthly_revenue": {
            "latest": _json_value(latest(MonthlyRevenue, MonthlyRevenue.period)),
            "row_count": count(MonthlyRevenue),
        },
        "financial_metric_quarterly": {
            "latest": _latest_financial_period(financial_latest),
            "row_count": count(FinancialMetricQuarterly),
        },
    }

    missing = [name for name, info in tables.items() if not info["latest"] or info["row_count"] == 0]

    envelope = {
        "kind": "data_freshness",
        "generated_at": _now(),
        "as_of": _latest_date_string([info["latest"] for info in tables.values()]),
        "scope": {"stock_id": stock_id},
        "data": {"tables": tables},
        "missing": missing,
        "warnings": [
            "Freshness is based on the local OMI database, not direct exchange availability.",
        ],
        "source_refs": [{"type": "database", "name": "open_market_intelligence.db"}],
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "is_current": not missing,
            "missing": missing,
            "warnings": envelope["warnings"],
        },
    )


def read_market_overview(db: Session, limit: int = 10) -> dict[str, Any]:
    latest_trade_date = market_service.get_latest_trade_date(db)
    missing: list[str] = []

    if latest_trade_date is None:
        envelope = {
            "kind": "market_overview",
            "generated_at": _now(),
            "as_of": None,
            "scope": {},
            "data": {
                "latest_trade_date": None,
                "breadth": {},
                "top_gainers": [],
                "top_losers": [],
            },
            "missing": ["market_daily_price"],
            "warnings": ["No market daily rows are available in the local database."],
            "source_refs": [{"type": "table", "name": "market_daily_price"}],
        }
        return _with_evidence_passport(
            envelope,
            freshness={
                "is_current": False,
                "missing": envelope["missing"],
                "warnings": envelope["warnings"],
            },
        )

    rows = market_service.list_market_daily_prices(
        db=db,
        trade_date=latest_trade_date,
        limit=10000,
    )
    ranked = [
        {
            "stock_id": row.stock_id,
            "stock_name": row.stock_name,
            "close_price": row.close_price,
            "price_change": row.price_change,
            "change_pct": (
                (row.price_change / (row.close_price - row.price_change)) * 100
                if row.price_change is not None
                and row.close_price is not None
                and row.close_price != row.price_change
                else None
            ),
            "trade_volume": row.trade_volume,
            "trade_value": row.trade_value,
        }
        for row in rows
    ]
    ranked_with_change = [row for row in ranked if row["change_pct"] is not None]
    top_gainers = sorted(ranked_with_change, key=lambda row: row["change_pct"], reverse=True)[:limit]
    top_losers = sorted(ranked_with_change, key=lambda row: row["change_pct"])[:limit]

    advance_count = sum(1 for row in rows if (row.price_change or 0) > 0)
    decline_count = sum(1 for row in rows if (row.price_change or 0) < 0)
    unchanged_count = sum(1 for row in rows if (row.price_change or 0) == 0)
    total_trade_value = sum(row.trade_value or 0 for row in rows) or None

    if not ranked_with_change:
        missing.append("market_daily_price.change_pct")

    envelope = {
        "kind": "market_overview",
        "generated_at": _now(),
        "as_of": latest_trade_date.isoformat(),
        "scope": {},
        "data": {
            "latest_trade_date": latest_trade_date.isoformat(),
            "breadth": {
                "advance_count": advance_count,
                "decline_count": decline_count,
                "unchanged_count": unchanged_count,
                "total_count": len(rows),
                "trade_value": total_trade_value,
            },
            "top_gainers": top_gainers,
            "top_losers": top_losers,
        },
        "missing": missing,
        "warnings": [
            "This overview uses the latest local daily market rows and does not fetch live quotes.",
        ],
        "source_refs": [{"type": "table", "name": "market_daily_price"}],
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "is_current": not missing,
            "missing": missing,
            "warnings": envelope["warnings"],
        },
    )


def read_tw_index_context(
    db: Session,
    index_id: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    normalized_index_id = index_id.strip().upper()
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan index context uses market index evidence, not stock_master or individual stock daily tables.",
    ]
    charts: dict[str, Any] = {}
    technical_reports: dict[str, Any] = {}

    for timeframe in ("daily", "weekly", "monthly"):
        try:
            chart = get_market_index_ohlc_chart_data(
                index_id=normalized_index_id,
                timeframe=timeframe,
                bars=max(bars, 1),
                db=db,
            )
        except ValueError:
            raise
        except Exception as exc:
            warnings.append(f"{timeframe.title()} index chart unavailable: {exc}")
            missing.append(f"market_index_ohlc.{timeframe}")
            continue

        serialized = _serialized_chart(chart)
        charts[timeframe] = serialized
        points = _normalize_technical_points(serialized.get("points", []))
        technical_reports[timeframe] = _technical_report_from_points(
            points=points,
            timeframe=timeframe,
            asset_label=normalized_index_id,
        )
        if not points:
            missing.append(f"market_index_ohlc.{timeframe}")
        backfill = chart.get("backfill") if isinstance(chart.get("backfill"), dict) else {}
        if backfill.get("status") == "error":
            warnings.append(str(backfill.get("message") or "Index daily stat refresh failed."))

    intraday: dict[str, Any] | None = None
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    if include_intraday or normalized_horizon == "intraday":
        try:
            intraday = get_market_index_intraday(normalized_index_id)
            intraday_points = _normalize_technical_points(intraday.get("points", []))
            technical_reports["today"] = _technical_report_from_points(
                points=intraday_points,
                timeframe="today",
                asset_label=normalized_index_id,
            )
            if not intraday_points:
                missing.append("market_index_intraday")
        except Exception as exc:
            warnings.append(f"Index intraday unavailable: {exc}")
            missing.append("market_index_intraday")
    elif normalized_horizon == "intraday":
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily evidence is used as fallback context."
        )

    summary_payload: dict[str, Any] = {}
    index_snapshot: dict[str, Any] | None = None
    try:
        summary_payload = get_market_index_summary(db, force_refresh=False)
        for item in summary_payload.get("indices", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("index_id") or item.get("stock_id") or "").upper() == normalized_index_id:
                index_snapshot = {key: _json_value(value) for key, value in item.items()}
                break
        if index_snapshot is None:
            missing.append("market_index_summary")
    except Exception as exc:
        warnings.append(f"Index summary unavailable: {exc}")
        missing.append("market_index_summary")

    market_chip: dict[str, Any] | None = None
    try:
        chip_row = get_latest_market_chip_daily(db, index_id=normalized_index_id)
        market_chip = _json_dict(market_chip_daily_to_dict(chip_row)) if chip_row is not None else None
        if market_chip is None:
            missing.append("market_chip_daily")
    except Exception as exc:
        warnings.append(f"Market chip context unavailable: {exc}")
        missing.append("market_chip_daily")

    contributions: dict[str, Any] | None = None
    try:
        contributions_payload = get_market_index_contributions(normalized_index_id, limit=10)
        contributions = {
            key: _json_value(value)
            for key, value in contributions_payload.items()
            if key not in {"positive", "negative"}
        }
        contributions["positive"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("positive", [])
            if isinstance(item, dict)
        ]
        contributions["negative"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("negative", [])
            if isinstance(item, dict)
        ]
    except Exception as exc:
        warnings.append(f"Index contribution context unavailable: {exc}")

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    as_of = _latest_date_string(
        [
            (charts.get("daily") or {}).get("to_date"),
            (index_snapshot or {}).get("time"),
            (index_snapshot or {}).get("as_of"),
            (market_chip or {}).get("trade_date"),
        ]
    )

    envelope = {
        "kind": "tw_index_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"index_id": normalized_index_id},
        "data": {
            "index": index_snapshot,
            "charts": charts,
            "intraday": intraday,
            "market_chip": market_chip,
            "contributions": contributions,
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": [
            {"type": "table", "name": "market_index_daily_stat"},
            {"type": "table", "name": "market_chip_daily"},
            {"type": "derived", "name": "app.market.indices"},
            {"type": "external_or_cache", "name": "yahoo_finance_chart"},
        ],
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )


def read_tw_futures_context(
    db: Session,
    symbol: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan futures context uses TAIFEX futures quote and bar tables, not stock_master or stock daily tables.",
    ]

    quote_rows = get_latest_taiwan_futures_quotes(db, symbols=[normalized_symbol], refresh=False)
    quote_dicts = [_json_dict(taiwan_futures_quote_to_dict(row)) for row in quote_rows]
    latest_quote = quote_dicts[0] if quote_dicts else None
    if latest_quote is None:
        missing.append("taiwan_futures_quote_snapshot")

    daily_rows = list_taiwan_futures_daily_bars(
        db=db,
        symbol=normalized_symbol,
        limit=max(bars, 1),
        active_only=True,
    )
    daily_dicts = [
        _json_dict(taiwan_futures_daily_bar_to_dict(row))
        for row in daily_rows
    ]
    daily_points = _normalize_technical_points([row for row in daily_dicts if isinstance(row, dict)])
    if not daily_points:
        missing.append("taiwan_futures_daily_bar")

    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    intraday_dicts: list[dict[str, Any]] = []
    intraday_points: list[dict[str, Any]] = []
    if include_intraday or normalized_horizon == "intraday":
        intraday_rows = list_taiwan_futures_intraday_bars(
            db=db,
            symbol=normalized_symbol,
            limit=390,
        )
        intraday_dicts = [
            _json_dict(taiwan_futures_intraday_bar_to_dict(row))
            for row in intraday_rows
        ]
        intraday_points = _normalize_technical_points(
            [row for row in intraday_dicts if isinstance(row, dict)]
        )
        if not intraday_points:
            missing.append("taiwan_futures_intraday_bar")
    elif normalized_horizon == "intraday":
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily futures evidence is used as fallback context."
        )

    technical_reports: dict[str, Any] = {
        "daily": _technical_report_from_points(
            points=daily_points,
            timeframe="daily",
            asset_label=normalized_symbol,
        ),
    }
    if intraday_points:
        technical_reports["today"] = _technical_report_from_points(
            points=intraday_points,
            timeframe="today",
            asset_label=normalized_symbol,
        )

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    daily_chart = _chart_from_points(timeframe="daily", points=daily_points)
    intraday_chart = _chart_from_points(timeframe="today", points=intraday_points)
    as_of = _latest_date_string(
        [
            (latest_quote or {}).get("quote_time"),
            daily_chart.get("to_date"),
            intraday_chart.get("to_date"),
        ]
    )

    envelope = {
        "kind": "tw_futures_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"symbol": normalized_symbol},
        "data": {
            "latest_quote": latest_quote,
            "quotes": quote_dicts,
            "daily_chart": daily_chart,
            "intraday_chart": intraday_chart if intraday_points else None,
            "daily_bars": daily_dicts,
            "intraday_bars": intraday_dicts,
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": [
            {"type": "table", "name": "taiwan_futures_quote_snapshot"},
            {"type": "table", "name": "taiwan_futures_daily_bar"},
            {"type": "table", "name": "taiwan_futures_intraday_bar"},
            {"type": "derived", "name": "app.market.tw_futures"},
        ],
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )


def read_stock_context(
    db: Session,
    stock_id: str,
    *,
    branch_days: int = 5,
    bars: int = 120,
    revenue_months: int = 12,
    financial_quarters: int = 8,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    missing: list[str] = []
    warnings: list[str] = []

    try:
        stock = stock_service.get_stock(db=db, stock_id=normalized_stock_id)
    except stock_service.StockNotFoundError:
        stock = None
        missing.append("stock_master")

    latest_daily = market_service.get_latest_stock_daily_price(db, normalized_stock_id)
    latest_institutional = market_service.get_latest_stock_institutional_trade(db, normalized_stock_id)
    latest_margin = market_service.get_latest_stock_margin_trade(db, normalized_stock_id)
    latest_revenue = market_service.get_latest_stock_monthly_revenue(db, normalized_stock_id)
    latest_financial = market_service.get_latest_stock_financial_metric(db, normalized_stock_id)
    shareholding = market_service.list_latest_stock_shareholding_distribution(db, normalized_stock_id)
    revenue_history = market_service.list_stock_monthly_revenue_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(revenue_months, 1),
    )
    financial_history = market_service.list_stock_financial_metric_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(financial_quarters, 1),
    )
    chart = market_service.list_stock_ohlc_chart_data(
        db=db,
        stock_id=normalized_stock_id,
        timeframe="daily",
        bars=max(bars, 1),
        ensure_history=False,
    )
    branch_summary = get_broker_branch_trade_summary(
        db=db,
        stock_id=normalized_stock_id,
        days=max(branch_days, 1),
        ensure_daily=False,
    )
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    technical_reports: dict[str, Any] = {}

    for timeframe in ("daily", "weekly", "monthly"):
        try:
            technical_reports[timeframe] = build_stock_technical_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe=timeframe,
                include_intraday=False,
            )
        except Exception as exc:
            warnings.append(f"{timeframe.title()} technical report unavailable: {exc}")
            missing.append(f"technical_report.{timeframe}")

    if include_intraday or normalized_horizon == "intraday":
        try:
            technical_reports["today"] = build_stock_technical_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe="today",
                include_intraday=include_intraday,
            )
        except Exception as exc:
            warnings.append(f"Today technical report unavailable: {exc}")
            missing.append("technical_report.today")

    if normalized_horizon == "intraday" and not include_intraday:
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily evidence is used as fallback context."
        )

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    technical_levels = _technical_price_levels(
        technical_reports=technical_reports,
        latest_daily=latest_daily,
    )
    overnight_impact: dict[str, Any] | None = None

    if stock is not None:
        try:
            overnight_impact = build_us_overnight_impact_report(
                db=db,
                stock_id=normalized_stock_id,
            )
            for warning in overnight_impact.get("warnings") or []:
                warnings.append(f"US overnight impact warning: {warning}")
            if overnight_impact.get("missing"):
                warnings.append(
                    "US overnight impact is partial: "
                    + ", ".join(str(value) for value in overnight_impact.get("missing", [])[:5])
                )
        except Exception as exc:
            warnings.append(f"US overnight impact unavailable: {exc}")
            missing.append("us_overnight_tw_impact")

    if branch_summary.get("is_partial"):
        warnings.append(
            "Broker branch data is partial for the requested window: "
            f"{branch_summary.get('available_days')} / {branch_summary.get('requested_days')} days."
        )

    _add_missing(missing, "market_daily_price", latest_daily)
    _add_missing(missing, "institutional_trade_daily", latest_institutional)
    _add_missing(missing, "margin_trading_daily", latest_margin)
    _add_missing(missing, "shareholding_distribution_weekly", shareholding)
    _add_missing(missing, "monthly_revenue", latest_revenue)
    _add_missing(missing, "financial_metric_quarterly", latest_financial)
    _add_missing(missing, "broker_branch_trade_daily", branch_summary.get("buy_top") or branch_summary.get("sell_top"))
    _add_missing(missing, "us_overnight_tw_impact", overnight_impact)

    as_of = _latest_date_string(
        [
            getattr(latest_daily, "trade_date", None),
            getattr(latest_institutional, "trade_date", None),
            getattr(latest_margin, "trade_date", None),
            branch_summary.get("trade_date"),
            getattr(latest_revenue, "period", None),
            getattr(latest_financial, "report_date", None),
            overnight_impact.get("as_of") if isinstance(overnight_impact, dict) else None,
        ]
    )

    source_refs = [
        {"type": "table", "name": "stock_master"},
        {"type": "table", "name": "market_daily_price"},
        {"type": "table", "name": "institutional_trade_daily"},
        {"type": "table", "name": "margin_trading_daily"},
        {"type": "table", "name": "shareholding_distribution_weekly"},
        {"type": "table", "name": "broker_branch_trade_daily"},
        {"type": "table", "name": "monthly_revenue"},
        {"type": "table", "name": "financial_metric_quarterly"},
        {"type": "derived", "name": "app.market.technical_report"},
        {"type": "table", "name": "us_daily_price"},
        {"type": "table", "name": "us_watchlist_group"},
        {"type": "table", "name": "us_watchlist_item"},
        {"type": "derived", "name": "app.market.overnight_impact"},
    ]
    decision_evidence = _stock_decision_evidence(
        latest_daily=latest_daily,
        chart=chart,
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
        technical_reports=technical_reports,
        missing=missing,
        source_refs=source_refs,
    )

    envelope = {
        "kind": "stock_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"stock_id": normalized_stock_id},
        "data": {
            "stock": _stock_dict(stock),
            "latest_daily": _row_dict(
                latest_daily,
                (
                    "trade_date",
                    "stock_id",
                    "stock_name",
                    "trade_volume",
                    "trade_value",
                    "open_price",
                    "high_price",
                    "low_price",
                    "close_price",
                    "price_change",
                    "transaction_count",
                ),
            ),
            "chart": {
                **chart,
                "from_date": _json_value(chart.get("from_date")),
                "to_date": _json_value(chart.get("to_date")),
                "points": [
                    {key: _json_value(value) for key, value in point.items()}
                    for point in chart.get("points", [])
                ],
            },
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
            "technical_levels": technical_levels,
            "decision_evidence": decision_evidence,
            "overnight_impact": overnight_impact,
            "latest_institutional": _row_dict(
                latest_institutional,
                (
                    "trade_date",
                    "foreign_investor_net",
                    "investment_trust_net",
                    "dealer_net",
                    "total_institutional_net",
                ),
            ),
            "latest_margin": _row_dict(
                latest_margin,
                (
                    "trade_date",
                    "margin_buy",
                    "margin_sell",
                    "margin_today_balance",
                    "short_sale",
                    "short_covering",
                    "short_today_balance",
                ),
            ),
            "latest_shareholding": [
                _row_dict(
                    row,
                    (
                        "data_date",
                        "holding_level",
                        "holder_count",
                        "share_count",
                        "share_ratio",
                    ),
                )
                for row in shareholding
            ],
            "broker_branch": {
                **branch_summary,
                "trade_date": _json_value(branch_summary.get("trade_date")),
                "trade_dates": [_json_value(value) for value in branch_summary.get("trade_dates", [])],
                "buy_top": [_broker_branch_row(row) for row in branch_summary.get("buy_top", [])],
                "sell_top": [_broker_branch_row(row) for row in branch_summary.get("sell_top", [])],
            },
            "latest_revenue": _row_dict(
                latest_revenue,
                (
                    "period",
                    "monthly_revenue",
                    "month_over_month_pct",
                    "year_over_year_pct",
                    "cumulative_revenue",
                    "cumulative_year_over_year_pct",
                ),
            ),
            "revenue_history": [
                _row_dict(
                    row,
                    (
                        "period",
                        "monthly_revenue",
                        "month_over_month_pct",
                        "year_over_year_pct",
                        "cumulative_revenue",
                        "cumulative_year_over_year_pct",
                    ),
                )
                for row in revenue_history
            ],
            "latest_financial": _row_dict(
                latest_financial,
                (
                    "period",
                    "report_date",
                    "revenue",
                    "gross_profit",
                    "operating_income",
                    "net_income",
                    "eps",
                    "book_value_per_share",
                    "roe",
                    "roa",
                ),
            ),
            "financial_history": [
                _row_dict(
                    row,
                    (
                        "period",
                        "report_date",
                        "revenue",
                        "gross_profit",
                        "operating_income",
                        "net_income",
                        "eps",
                        "book_value_per_share",
                        "roe",
                        "roa",
                    ),
                )
                for row in financial_history
            ],
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )


def read_watchlist_context(
    db: Session,
    group_id: int,
    *,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "score",
    sort_order: str = "desc",
    limit: int = 100,
) -> dict[str, Any]:
    group = watchlist_service.get_group(db=db, group_id=group_id)
    ranking = ranking_service.get_watchlist_group_latest_ranking(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by=rank_by,
        sort_order=sort_order,
        limit=limit,
        use_intraday=False,
    )
    results = ranking.get("results", [])
    missing = []
    warnings = [
        "Watchlist context uses local daily indicator data and does not fetch live quotes.",
    ]

    if ranking.get("no_data_count"):
        missing.append("watchlist_items_with_market_data")

    ranked_as_of = _latest_date_string([row.get("time") for row in results])

    envelope = {
        "kind": "watchlist_context",
        "generated_at": _now(),
        "as_of": ranked_as_of,
        "scope": {
            "group_id": group_id,
            "group_name": group.group_name,
            "include_children": include_children,
            "enabled_only": enabled_only,
        },
        "data": {
            "ranking": ranking,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "table", "name": "watchlist_group"},
            {"type": "table", "name": "watchlist_item"},
            {"type": "table", "name": "market_daily_price"},
        ],
    }
    return _with_evidence_passport(envelope)
