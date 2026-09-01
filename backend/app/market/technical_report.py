from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.ai.evidence_passport import build_evidence_passport
from app.market import service as market_service
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.intraday import get_intraday_trend
from app.market.public_quote_platform import (
    project_taiwan_session_close,
    read_taiwan_session_close,
)
from app.market.stock_volume_pace import build_tw_stock_volume_pace
from app.market.technical_parameters import (
    TechnicalAnalysisParameters,
    get_technical_analysis_parameters,
)
from app.market.technical_evidence import classify_latest_period
from app.market.technical_indicator_gateway import (
    active_engine_contract,
    calculate_active_indicator_points,
    calculate_active_latest_daily_indicator,
)
from app.market.technical_intraday_projection import build_current_partial_daily_bar
from app.market.technical_structure import (
    build_moving_average_structure,
    build_price_range_signals,
    build_technical_current_state,
)


TAIPEI_TZ = timezone(timedelta(hours=8))
SESSION_START_MINUTES = 9 * 60
OPENING_OBSERVATION_MINUTES = 5
OPENING_OBSERVATION_MIN_POINTS = 5
AGGREGATED_REPORT_BARS = {
    "weekly": 180,
    "monthly": 120,
}
TIMEFRAME_LABELS = {
    "daily": "日K",
    "weekly": "週K",
    "monthly": "月K",
}
TIMEFRAME_TITLE_LABELS = {
    "daily": ("短線偏多", "短線整理", "短線偏弱"),
    "weekly": ("波段偏多", "波段整理", "波段偏弱"),
    "monthly": ("長線偏多", "長線整理", "長線偏弱"),
}
TIMEFRAME_SUMMARY_LABELS = {
    "daily": "短線",
    "weekly": "波段",
    "monthly": "長線",
}


def _now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    if not _finite(numerator) or not _finite(denominator) or denominator == 0:
        return None
    return numerator / denominator


def _indicator_value(values: dict[str, Any], key: str | None, legacy_key: str | None = None) -> Any:
    if not isinstance(values, dict):
        return None
    if key and values.get(key) is not None:
        return values.get(key)
    if legacy_key and values.get(legacy_key) is not None:
        return values.get(legacy_key)
    return None


def _pct_change(current: Any, reference: Any) -> float | None:
    ratio = _safe_ratio(current - reference, reference) if _finite(current) and _finite(reference) else None
    return None if ratio is None else round(ratio * 100, 4)


def _fmt_number(value: Any, digits: int = 0) -> str:
    if not _finite(value):
        return "-"
    return f"{value:,.{digits}f}"


def _fmt_price(value: Any) -> str:
    if not _finite(value):
        return "-"
    digits = 0 if abs(value) >= 1000 else 2
    formatted = _fmt_number(value, digits)
    return formatted if digits == 0 else formatted.rstrip("0").rstrip(".")


def _fmt_pct(value: Any) -> str:
    if not _finite(value):
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _fmt_lots(value: Any) -> str:
    if not _finite(value):
        return "-"
    return f"{round(value / 1000):,}"


def _fmt_ratio(value: Any) -> str:
    if not _finite(value):
        return "-"
    return f"{value:.2f}×"


def _volume_pace_description(volume_pace: dict[str, Any]) -> str:
    comparison_minute = volume_pace.get("comparison_minute") or "--:--"
    current_volume = volume_pace.get("current_cumulative_volume")
    baseline_5d = volume_pace.get("same_time_baseline_5d") or {}
    baseline_20d = volume_pace.get("same_time_baseline_20d") or {}
    pace_5d = baseline_5d.get("pace_ratio")
    pace_20d = baseline_20d.get("pace_ratio")
    sample_5d = int(baseline_5d.get("sample_days") or 0)
    sample_20d = int(baseline_20d.get("sample_days") or 0)
    current_text = "觀察中" if current_volume is None else f"{_fmt_lots(current_volume)}張"
    if _finite(pace_5d):
        pace_5d_text = f"5日 {_fmt_ratio(pace_5d)}"
        if sample_5d < 5:
            pace_5d_text += f"（n={sample_5d}，暫定）"
        comparison_parts = [pace_5d_text]
        if _finite(pace_20d) and sample_20d >= 20:
            comparison_parts.append(f"20日 {_fmt_ratio(pace_20d)}")
        return (
            f"截至 {comparison_minute} 累計 {current_text}；同時段量比 "
            f"{' / '.join(comparison_parts)}"
        )
    return (
        f"截至 {comparison_minute} 累計 {current_text}；"
        f"同時段完整分鐘歷史累積中（{sample_5d}/5日）"
    )


def _fmt_signed_lots(value: Any) -> str:
    if not _finite(value):
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{_fmt_lots(value)}"


def _fmt_signed_number(value: Any) -> str:
    if not _finite(value):
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.0f}"


def _tone(value: Any) -> str:
    if not _finite(value):
        return "neutral"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _badge(label: str, tone: str) -> dict[str, str]:
    return {"label": label, "tone": tone}


def _row(
    *,
    key: str,
    label: str,
    description: str,
    value: Any,
    display_value: str,
    direction: Any = None,
    tone: str | None = None,
    basis: str,
    source: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "description": description,
        "value": _json_value(value),
        "display_value": display_value,
        "direction": direction if _finite(direction) else None,
        "tone": tone or _tone(direction),
        "basis": basis,
        "source": source,
    }


def _title_from_score(score: int, *, positive: str, neutral: str, negative: str) -> str:
    if score >= 3:
        return positive
    if score <= -3:
        return negative
    return neutral


def _stock_market(db: Session, stock_id: str) -> str | None:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
    return stock.market.upper() if stock and stock.market else None


def _daily_indicator(
    db: Session,
    stock_id: str,
    parameters: TechnicalAnalysisParameters | None = None,
    to_date: date | None = None,
) -> dict[str, Any] | None:
    technical_parameters = parameters or get_technical_analysis_parameters()
    return calculate_active_latest_daily_indicator(
        db=db,
        stock_id=stock_id,
        to_date=to_date,
        parameters=technical_parameters,
    )


def _aggregated_indicator(
    *,
    db: Session,
    stock_id: str,
    timeframe: str,
    parameters: TechnicalAnalysisParameters | None = None,
    to_date: date | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    technical_parameters = parameters or get_technical_analysis_parameters()
    chart = market_service.list_stock_ohlc_chart_data(
        db=db,
        stock_id=stock_id,
        timeframe=timeframe,
        bars=AGGREGATED_REPORT_BARS[timeframe],
        ensure_history=False,
        to_date=to_date,
    )
    points = chart.get("points") or []
    indicators = calculate_active_indicator_points(
        points,
        parameters=technical_parameters,
    )
    period = classify_latest_period(
        points,
        timeframe=timeframe,
        latest_observation_date=chart.get("latest_data_date"),
    )
    current_partial = None
    completed = indicators[-1] if indicators else None
    if period["status"] == "current_partial" and indicators:
        current_partial = indicators[-1]
        completed = indicators[-2] if len(indicators) > 1 else None
    chart["period"] = period
    chart["current_partial_indicator"] = current_partial
    chart["decision_snapshot"] = "completed"
    return completed, chart


def _daily_context(
    db: Session,
    stock_id: str,
    parameters: TechnicalAnalysisParameters | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    technical_parameters = parameters or get_technical_analysis_parameters()
    latest_indicator = _daily_indicator(
        db=db,
        stock_id=stock_id,
        parameters=technical_parameters,
        to_date=to_date,
    )
    if to_date is None:
        latest_institutional = market_service.get_latest_stock_institutional_trade(
            db,
            stock_id,
        )
        latest_margin = market_service.get_latest_stock_margin_trade(db, stock_id)
    else:
        institutional_rows = market_service.list_stock_institutional_trade_history(
            db=db,
            stock_id=stock_id,
            to_date=to_date,
            limit=1,
            ascending=False,
        )
        margin_rows = market_service.list_stock_margin_trade_history(
            db=db,
            stock_id=stock_id,
            to_date=to_date,
            limit=1,
            ascending=False,
        )
        latest_institutional = institutional_rows[0] if institutional_rows else None
        latest_margin = margin_rows[0] if margin_rows else None
    return {
        "indicator": latest_indicator,
        "institutional": latest_institutional,
        "margin": latest_margin,
    }


def _current_partial_daily_indicator(
    *,
    db: Session,
    stock_id: str,
    intraday_points: list[dict[str, Any]],
    market_session: dict[str, Any],
    parameters: TechnicalAnalysisParameters,
) -> dict[str, Any] | None:
    rows = market_service.list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        limit=400,
        ascending=True,
    )
    completed_points = [
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
    session_date = market_session.get("date")
    if not isinstance(session_date, date):
        return None
    current_quote: dict[str, Any] | None = None
    if market_session.get("is_after_close"):
        session_close_result = read_taiwan_session_close(
            db,
            stock_id=stock_id,
            requested_at=market_session.get("checked_at"),
        )
        session_close = project_taiwan_session_close(session_close_result)
        quote = session_close_result.resolved.quote
        if session_close.get("available") is True and quote is not None:
            current_quote = {
                "trade_date": quote.trade_date,
                "event_time": quote.lineage.event_at,
                "last_trade_price": float(quote.last_trade_price),
                "last_trade_is_current_session": True,
                "actual_trade_occurred": True,
                "session_close_available": True,
                "session_close_status": session_close.get("finalization"),
                "open_price": (
                    float(quote.open_price)
                    if quote.open_price is not None
                    else None
                ),
                "high_price": (
                    float(quote.high_price)
                    if quote.high_price is not None
                    else None
                ),
                "low_price": (
                    float(quote.low_price)
                    if quote.low_price is not None
                    else None
                ),
                "cumulative_volume_shares": (
                    float(quote.cumulative_quantity.value)
                    if quote.cumulative_quantity is not None
                    else None
                ),
                "provider": quote.lineage.provider,
                "source": quote.lineage.source,
            }
    partial_bar = build_current_partial_daily_bar(
        completed_daily_points=completed_points,
        intraday_points=intraday_points,
        quote=current_quote,
        session_date=session_date,
        session_phase=str(market_session.get("phase") or "unknown"),
    )
    if partial_bar is None:
        return None
    calculated = calculate_active_indicator_points(
        [*completed_points, partial_bar],
        parameters=parameters,
    )
    if not calculated:
        return None
    return {
        **calculated[-1],
        "open": partial_bar.get("open"),
        "high": partial_bar.get("high"),
        "low": partial_bar.get("low"),
        "bar_status": partial_bar.get("bar_status"),
        "session_close_finalization": partial_bar.get(
            "session_close_finalization"
        ),
        "official_daily_confirmed": False,
        "event_time": partial_bar.get("event_time"),
        "source": partial_bar.get("source"),
        "volume_semantics": partial_bar.get("volume_semantics"),
        "indicator_semantics": {
            "price_based": "intraday_partial",
            "range_based": "intraday_partial",
            "volume_based": "partial_cumulative_volume",
        },
        "decision_usable": False,
        "volume_based_decision_usable": False,
        "warnings": [
            "This is an intraday provisional daily indicator observation; completed daily evidence remains the decision snapshot.",
            "Volume-based values use cumulative partial-session volume and are not finalized daily indicators.",
        ],
    }


def _technical_state_projection_from_indicator(
    indicator: dict[str, Any],
    *,
    parameters: TechnicalAnalysisParameters,
) -> dict[str, Any]:
    price = indicator.get("close")
    ma = indicator.get("ma") or {}
    volume_ma = indicator.get("volume_ma") or {}
    macd = indicator.get("macd") or {}
    rsi = indicator.get("rsi") or {}
    atr = indicator.get("atr") or {}
    adx = indicator.get("adx") or {}
    roc = indicator.get("roc") or {}
    mfi = indicator.get("mfi") or {}
    donchian = indicator.get("donchian") or {}
    bollinger = indicator.get("bollinger") or {}
    support_resistance = indicator.get("support_resistance") or {}
    ma5 = _indicator_value(ma, parameters.ma_short_key, "ma5")
    ma20 = _indicator_value(ma, parameters.ma_medium_key, "ma20")
    ma60 = _indicator_value(ma, parameters.ma_long_key, "ma60")
    support20 = _indicator_value(
        support_resistance,
        parameters.support_key,
        "support20",
    )
    resistance20 = _indicator_value(
        support_resistance,
        parameters.resistance_key,
        "resistance20",
    )
    moving_average_structure = build_moving_average_structure(
        price=price,
        ma5=ma5,
        ma20=ma20,
        ma60=ma60,
    )
    range_signals, _ = build_price_range_signals(
        price=price,
        support=support20,
        resistance=resistance20,
        donchian_upper=_indicator_value(
            donchian,
            parameters.donchian_upper_key,
            "upper20",
        ),
        donchian_lower=_indicator_value(
            donchian,
            parameters.donchian_lower_key,
            "lower20",
        ),
        bollinger_upper=_indicator_value(
            bollinger,
            parameters.bollinger_upper_key,
            "upper20",
        ),
        bollinger_lower=_indicator_value(
            bollinger,
            parameters.bollinger_lower_key,
            "lower20",
        ),
        near_threshold_pct=parameters.near_level_threshold_pct,
    )
    volume_ratio = _safe_ratio(
        indicator.get("volume"),
        _indicator_value(
            volume_ma,
            parameters.volume_ma_medium_key,
            "volume_ma20",
        ),
    )
    rsi14 = _indicator_value(rsi, parameters.rsi_key, "rsi14")
    roc12 = _indicator_value(roc, parameters.roc_key, "roc12")
    mfi14 = _indicator_value(mfi, parameters.mfi_key, "mfi14")
    adx14 = _indicator_value(adx, parameters.adx_key, "adx14")
    plus_di14 = _indicator_value(adx, parameters.plus_di_key, "plus_di14")
    minus_di14 = _indicator_value(adx, parameters.minus_di_key, "minus_di14")
    atr14 = _indicator_value(atr, parameters.atr_key, "atr14")
    atr_pct = _safe_ratio(atr14, price)
    atr_pct = atr_pct * 100 if atr_pct is not None else None
    donchian_upper = _indicator_value(
        donchian,
        parameters.donchian_upper_key,
        "upper20",
    )
    donchian_lower = _indicator_value(
        donchian,
        parameters.donchian_lower_key,
        "lower20",
    )
    donchian_position = None
    if (
        _finite(price)
        and _finite(donchian_upper)
        and _finite(donchian_lower)
        and donchian_upper != donchian_lower
    ):
        donchian_position = (
            (price - donchian_lower)
            / (donchian_upper - donchian_lower)
            * 100
        )
    return {
        "state": build_technical_current_state(
            price=price,
            moving_average_structure=moving_average_structure,
            change_pct=indicator.get("change_pct"),
            volume_ratio=volume_ratio,
            rsi14=rsi14,
            macd_histogram=macd.get("histogram"),
            roc12=roc12,
            mfi14=mfi14,
            adx14=adx14,
            plus_di14=plus_di14,
            minus_di14=minus_di14,
            atr_pct=atr_pct,
            donchian_position=donchian_position,
            support20=support20,
            resistance20=resistance20,
            adx_trend_threshold=parameters.adx_trend_threshold,
            volume_ratio_threshold=parameters.volume_ratio_threshold,
            rsi_overheated_threshold=parameters.rsi_overheated_at,
            atr_high_volatility_pct=parameters.atr_high_volatility_pct,
        ),
        "moving_average_structure": moving_average_structure,
        "range_signals": range_signals,
        "volume_ratio": volume_ratio,
    }


def _intraday_minutes(value: Any) -> float | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)
    local = parsed.astimezone(TAIPEI_TZ)
    return local.hour * 60 + local.minute + local.second / 60


def _intraday_point_is_current_session(value: Any, session_date: date) -> bool:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return False
    else:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ).date() == session_date


def _intraday_stats(points: list[dict[str, Any]]) -> dict[str, Any]:
    valid_points = [point for point in points if _finite(point.get("price"))]
    if not valid_points:
        return {"open": None, "high": None, "low": None, "volume": None}

    highs = [
        point.get("high") if _finite(point.get("high")) else point.get("price")
        for point in valid_points
    ]
    lows = [
        point.get("low") if _finite(point.get("low")) else point.get("price")
        for point in valid_points
    ]
    volumes = [point.get("volume") for point in valid_points if _finite(point.get("volume"))]
    first = valid_points[0]
    return {
        "open": first.get("open") if _finite(first.get("open")) else first.get("price"),
        "high": max(highs) if highs else None,
        "low": min(lows) if lows else None,
        "volume": sum(volumes) if volumes else None,
    }


def _margin_balance_change(row: Any) -> int | None:
    if row is None:
        return None
    current = getattr(row, "margin_today_balance", None)
    previous = getattr(row, "margin_previous_balance", None)
    if current is None or previous is None:
        return None
    return current - previous


def _technical_source_refs(*, timeframe: str, include_intraday: bool) -> list[dict[str, str]]:
    refs = [
        {"type": "table", "name": "market_daily_price"},
        {"type": "derived", "name": "app.market.indicator_service"},
    ]
    if include_intraday:
        refs.append({"type": "external_or_cache", "name": "taiwan_intraday_trend"})
    if timeframe == "today" and include_intraday:
        refs.append({"type": "table", "name": "market_intraday_bar"})
    return refs


def _report_as_of(report: dict[str, Any]) -> Any:
    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    price_context = data.get("price_context")
    if isinstance(price_context, dict) and price_context.get("price_time"):
        return price_context.get("price_time")

    for key in ("indicator", "daily_indicator", "daily_background"):
        value = data.get(key)
        if isinstance(value, dict) and value.get("time"):
            return value.get("time")

    intraday = data.get("intraday")
    if isinstance(intraday, dict):
        latest_point = intraday.get("latest_point")
        if isinstance(latest_point, dict) and latest_point.get("time"):
            return latest_point.get("time")

    return None


def _today_market_session() -> dict[str, Any]:
    local_now = _now()
    current_date = local_now.date()
    calendar = build_taiwan_calendar_status(now=local_now)
    phase = str(calendar.get("phase") or "market_closed")
    is_trading_day = calendar.get("is_trading_day") is True
    return {
        "date": current_date,
        "is_trading_day": is_trading_day,
        "phase": phase,
        "is_intraday_window": phase
        in {"regular", "closing_auction", "close_resolution"},
        "is_after_close": phase == "post_close",
        "reason": calendar.get("reason"),
        "holiday_name": calendar.get("holiday_name"),
        "previous_trading_day": calendar.get("previous_trading_day"),
        "next_trading_day": calendar.get("next_trading_day"),
        "checked_at": local_now,
    }


def _with_evidence_passport(report: dict[str, Any]) -> dict[str, Any]:
    wrapped = dict(report)
    engine = active_engine_contract()
    wrapped["algorithm_version"] = engine["algorithm_version"]
    wrapped["indicator_engine"] = engine
    wrapped.setdefault("data", {})["indicator_engine"] = engine
    wrapped["evidence_passport"] = build_evidence_passport(
        kind=str(wrapped.get("kind") or "technical_report"),
        as_of=_report_as_of(wrapped),
        source_refs=wrapped.get("source_refs") or [],
        missing=wrapped.get("missing") or [],
        warnings=wrapped.get("warnings") or [],
        confidence=str(wrapped.get("confidence") or ""),
    )
    return wrapped


def _indicator_data_missing_report(
    *,
    stock_id: str,
    timeframe: str,
    point_count: int | None = None,
) -> dict[str, Any]:
    label = TIMEFRAME_LABELS.get(timeframe, timeframe)
    missing_key = "market_daily_price" if timeframe == "daily" else f"market_daily_price.{timeframe}"
    return {
        "kind": "tw_stock_technical_report",
        "stock_id": stock_id,
        "timeframe": timeframe,
        "phase": timeframe,
        "confidence": "low",
        "generated_at": _now(),
        "title": "資料不足",
        "summary": f"尚無足夠{label}資料產生技術報告",
        "score": 0,
        "value": None,
        "value_label": "vs MA20",
        "rows": [
            _row(
                key="data_status",
                label="資料狀態",
                description=f"{label}價格或技術指標不足",
                value=point_count,
                display_value="-" if point_count is None else f"{point_count}筆",
                basis=f"{timeframe} indicator availability",
                source="market_daily_price",
            )
        ],
        "badges": [],
        "data": {
            "indicator": None,
            "timeframe": timeframe,
            "point_count": point_count,
        },
        "missing": [missing_key],
        "warnings": [],
        "source_refs": _technical_source_refs(timeframe=timeframe, include_intraday=False),
    }


def _build_indicator_report(
    *,
    db: Session,
    stock_id: str,
    timeframe: str,
    indicator: dict[str, Any] | None,
    point_count: int | None = None,
    parameters: TechnicalAnalysisParameters | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    technical_parameters = parameters or get_technical_analysis_parameters()
    if indicator is None:
        return _indicator_data_missing_report(
            stock_id=stock_id,
            timeframe=timeframe,
            point_count=point_count,
        )

    rows: list[dict[str, Any]] = []
    badges: list[dict[str, str]] = []
    warnings: list[str] = []
    missing: list[str] = []
    label = TIMEFRAME_LABELS.get(timeframe, timeframe)
    summary_label = TIMEFRAME_SUMMARY_LABELS.get(timeframe, label)
    close = indicator.get("close")
    volume = indicator.get("volume")
    change_pct = indicator.get("change_pct")
    ma = indicator.get("ma") or {}
    volume_ma = indicator.get("volume_ma") or {}
    macd = indicator.get("macd") or {}
    rsi = indicator.get("rsi") or {}
    atr = indicator.get("atr") or {}
    adx = indicator.get("adx") or {}
    roc = indicator.get("roc") or {}
    mfi = indicator.get("mfi") or {}
    donchian = indicator.get("donchian") or {}
    ma5 = _indicator_value(ma, technical_parameters.ma_short_key, "ma5")
    ma20 = _indicator_value(ma, technical_parameters.ma_medium_key, "ma20")
    ma60 = _indicator_value(ma, technical_parameters.ma_long_key, "ma60")
    price_vs_ma20 = _pct_change(close, ma20)
    volume_ratio = _safe_ratio(
        volume,
        _indicator_value(volume_ma, technical_parameters.volume_ma_medium_key, "volume_ma20"),
    )
    volume_ratio_pct = (volume_ratio - 1) * 100 if volume_ratio is not None else None
    macd_histogram = macd.get("histogram")
    rsi14 = _indicator_value(rsi, technical_parameters.rsi_key, "rsi14")
    adx14 = _indicator_value(adx, technical_parameters.adx_key, "adx14")
    plus_di14 = _indicator_value(adx, technical_parameters.plus_di_key, "plus_di14")
    minus_di14 = _indicator_value(adx, technical_parameters.minus_di_key, "minus_di14")
    atr14 = _indicator_value(atr, technical_parameters.atr_key, "atr14")
    atr_pct = _safe_ratio(atr14, close)
    atr_pct = atr_pct * 100 if atr_pct is not None else None
    donchian_upper = _indicator_value(donchian, technical_parameters.donchian_upper_key, "upper20")
    donchian_lower = _indicator_value(donchian, technical_parameters.donchian_lower_key, "lower20")
    donchian_position = None
    if _finite(donchian_upper) and _finite(donchian_lower) and donchian_upper != donchian_lower:
        donchian_position = (close - donchian_lower) / (donchian_upper - donchian_lower) * 100
    daily = _daily_context(
        db=db,
        stock_id=stock_id,
        parameters=technical_parameters,
        to_date=to_date,
    )
    latest_institutional = daily["institutional"]
    institutional_net = (
        getattr(latest_institutional, "total_institutional_net", None)
        if latest_institutional is not None
        else None
    )
    margin_change = _margin_balance_change(daily["margin"])
    score = 0

    if _finite(price_vs_ma20):
        score += 1 if price_vs_ma20 >= 0 else -1
    if _finite(ma5) and _finite(ma20):
        score += 1 if ma5 >= ma20 else -1
    if _finite(ma20) and _finite(ma60):
        score += 1 if ma20 >= ma60 else -1
    if _finite(macd_histogram):
        score += 1 if macd_histogram >= 0 else -1
    if _finite(rsi14):
        if technical_parameters.rsi_bull_min <= rsi14 < technical_parameters.rsi_overheated_at:
            score += 1
        elif rsi14 < technical_parameters.rsi_weak_below:
            score -= 1
    if (
        _finite(adx14)
        and adx14 >= technical_parameters.adx_trend_threshold
        and _finite(plus_di14)
        and _finite(minus_di14)
    ):
        score += 1 if plus_di14 >= minus_di14 else -1
    if timeframe == "daily" and _finite(institutional_net):
        score += 1 if institutional_net > 0 else -1

    rows.extend(
        [
            _row(
                key="trend_structure",
                label="趨勢結構",
                description=f"{label} MA5/20/60 {_fmt_price(ma5)} / {_fmt_price(ma20)} / {_fmt_price(ma60)}，ADX {_fmt_number(adx14, 2)}",
                value=price_vs_ma20,
                display_value=_fmt_pct(price_vs_ma20),
                direction=price_vs_ma20,
                basis=f"{timeframe} close vs MA20 and moving average alignment",
                source="market_daily_price",
            ),
            _row(
                key="momentum",
                label="動能指標",
                description=f"RSI {_fmt_number(rsi14, 2)}，MACD H {_fmt_number(macd_histogram, 2)}，ROC12 {_fmt_pct(_indicator_value(roc, technical_parameters.roc_key, 'roc12'))}",
                value=rsi14,
                display_value=_fmt_number(rsi14, 2),
                direction=macd_histogram,
                tone="warning" if _finite(rsi14) and rsi14 >= technical_parameters.rsi_overheated_at else _tone(macd_histogram),
                basis=f"{timeframe} RSI, MACD histogram, and ROC",
                source="market_daily_price",
            ),
            _row(
                key="volume_flow",
                label="量價資金",
                description=f"{label}量能 {_fmt_pct(volume_ratio_pct)} vs 20期均量，MFI {_fmt_number(_indicator_value(mfi, technical_parameters.mfi_key, 'mfi14'), 2)}",
                value=volume_ratio_pct,
                display_value=_fmt_pct(volume_ratio_pct),
                direction=volume_ratio_pct,
                tone="warning" if _finite(volume_ratio) and volume_ratio >= technical_parameters.volume_ratio_threshold else "neutral",
                basis=f"{timeframe} volume vs 20-period average volume",
                source="market_daily_price",
            ),
            _row(
                key="volatility_risk",
                label="波動風險",
                description=f"ATR {_fmt_pct(atr_pct)}，Donchian 位置 {_fmt_pct(donchian_position)}",
                value=atr_pct,
                display_value=_fmt_pct(atr_pct),
                direction=1 if _finite(atr_pct) and atr_pct > technical_parameters.atr_high_volatility_pct else 0,
                tone="warning" if _finite(atr_pct) and atr_pct > technical_parameters.atr_high_volatility_pct else "neutral",
                basis=f"{timeframe} ATR and 20-period Donchian range position",
                source="market_daily_price",
            ),
            _row(
                key="institutional_flow",
                label="法人籌碼",
                description=f"最新三大法人合計，融資餘額 {_fmt_signed_number(margin_change)}",
                value=institutional_net,
                display_value="-" if institutional_net is None else f"{_fmt_signed_lots(institutional_net)}張",
                direction=institutional_net,
                basis="latest published institutional trade and margin balance",
                source="institutional_trade_daily",
            ),
        ]
    )

    if _finite(price_vs_ma20):
        badges.append(_badge("站上 MA20" if price_vs_ma20 >= 0 else "跌破 MA20", "positive" if price_vs_ma20 >= 0 else "negative"))
    if _finite(macd_histogram):
        badges.append(_badge("MACD 偏多" if macd_histogram >= 0 else "MACD 偏弱", "positive" if macd_histogram >= 0 else "negative"))
    if _finite(rsi14) and rsi14 >= technical_parameters.rsi_overheated_at:
        badges.append(_badge("RSI 過熱", "warning"))
    if _finite(volume_ratio) and volume_ratio >= technical_parameters.volume_ratio_threshold:
        badges.append(_badge("放量", "warning"))

    summary_parts = [
        "站上 MA20"
        if _finite(price_vs_ma20) and price_vs_ma20 >= 0
        else "跌破 MA20"
        if _finite(price_vs_ma20)
        else "價格結構不足",
        "MACD 偏多"
        if _finite(macd_histogram) and macd_histogram >= 0
        else "MACD 偏弱"
        if _finite(macd_histogram)
        else "動能資料不足",
        "放量"
        if _finite(volume_ratio)
        and volume_ratio >= technical_parameters.volume_ratio_threshold
        else "量能一般"
        if _finite(volume_ratio)
        else "量能資料不足",
    ]
    if indicator.get("time") is None:
        missing.append("market_daily_price.time")
    long_window = technical_parameters.ma_long_window or 60
    if point_count is not None and point_count < long_window:
        missing.append(f"market_daily_price.{timeframe}.ma{long_window}")
        warnings.append(f"{label}資料少於 {long_window} 根，長均線與趨勢分數信心較低。")

    confidence = "high"
    if missing:
        confidence = "medium"
    if point_count is not None and point_count < 20:
        confidence = "low"

    positive, neutral, negative = TIMEFRAME_TITLE_LABELS.get(
        timeframe,
        ("技術偏多", "技術整理", "技術偏弱"),
    )
    return {
        "kind": "tw_stock_technical_report",
        "stock_id": stock_id,
        "timeframe": timeframe,
        "phase": timeframe,
        "confidence": confidence,
        "generated_at": _now(),
        "title": _title_from_score(score, positive=positive, neutral=neutral, negative=negative),
        "summary": f"{summary_label}：" + "，".join(summary_parts),
        "score": score,
        "value": price_vs_ma20,
        "value_label": "vs MA20",
        "rows": rows,
        "badges": badges,
        "data": {
            "indicator": indicator,
            "market": _stock_market(db=db, stock_id=stock_id),
            "change_pct": change_pct,
            "timeframe": timeframe,
            "point_count": point_count,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": _technical_source_refs(timeframe=timeframe, include_intraday=False),
    }


def _build_today_report(
    *,
    db: Session,
    stock_id: str,
    include_intraday: bool,
    intraday_override: dict[str, Any] | None = None,
    parameters: TechnicalAnalysisParameters | None = None,
) -> dict[str, Any]:
    technical_parameters = parameters or get_technical_analysis_parameters()
    warnings: list[str] = []
    missing: list[str] = []
    rows: list[dict[str, Any]] = []
    badges: list[dict[str, str]] = []
    daily = _daily_context(db=db, stock_id=stock_id, parameters=technical_parameters)
    indicator = daily["indicator"] or {}
    ma = indicator.get("ma") or {}
    volume_ma = indicator.get("volume_ma") or {}
    rsi = indicator.get("rsi") or {}
    macd = indicator.get("macd") or {}
    previous_close = indicator.get("close")
    intraday = {
        "source": "not_requested",
        "previous_close": None,
        "point_count": 0,
        "points": [],
    }
    market_session = _today_market_session()
    latest_daily_date = indicator.get("time")

    if not market_session["is_trading_day"]:
        reference_close = previous_close
        session_date = _json_value(market_session["date"])
        previous_trading_day = _json_value(market_session["previous_trading_day"])
        next_trading_day = _json_value(market_session["next_trading_day"])
        latest_daily_text = _json_value(latest_daily_date) or previous_trading_day
        rows.extend(
            [
                _row(
                    key="market_session",
                    label="市場狀態",
                    description=f"{session_date} 台股休市，沒有今日盤中成交資料",
                    value=0,
                    display_value="休市",
                    basis="Taiwan trading calendar",
                    source="app.market.trading_calendar",
                ),
                _row(
                    key="reference_close",
                    label="參考基準",
                    description="休市日以最近已公布日線作為判斷基準",
                    value=reference_close,
                    display_value=_fmt_price(reference_close),
                    basis="latest published daily close",
                    source="market_daily_price",
                ),
            ]
        )
        badges.append(_badge("台股休市", "neutral"))
        warnings.append(
            f"{session_date} is not a Taiwan trading day; intraday data is skipped."
        )
        return {
            "kind": "tw_stock_technical_report",
            "stock_id": stock_id,
            "timeframe": "today",
            "phase": "market_closed",
            "confidence": "medium" if reference_close is not None else "low",
            "generated_at": _now(),
            "title": "台股休市",
            "summary": (
                f"{session_date} 台股休市，OMI 以最新日線 {latest_daily_text} "
                "的日線資料作為背景；盤中突破或回測需等下一交易日確認。"
            ),
            "score": 0,
            "value": None,
            "value_label": "market session",
            "rows": rows,
            "badges": badges,
            "data": {
                "intraday": {
                    "source": "market_closed",
                    "point_count": 0,
                    "previous_close": reference_close,
                    "latest_point": None,
                },
                "daily_background": indicator,
                "market_session": {
                    **{key: _json_value(value) for key, value in market_session.items()},
                    "latest_daily_date": _json_value(latest_daily_date),
                    "summary": (
                        f"{session_date} 台股休市，最新日線截至 "
                        f"{latest_daily_text}；"
                        f"下一交易日 {next_trading_day} 再確認盤中價量。"
                    ),
                },
            },
            "missing": [],
            "warnings": list(dict.fromkeys(warnings)),
            "source_refs": _technical_source_refs(timeframe="today", include_intraday=False),
        }

    if intraday_override is not None:
        intraday = intraday_override
    elif include_intraday:
        intraday = get_intraday_trend(db=db, stock_id=stock_id)
    else:
        missing.append("intraday_trend")
        warnings.append("Intraday report was requested without live intraday access.")

    points = intraday.get("points") or []
    latest_point = points[-1] if points else None
    reference_close = intraday.get("previous_close") or previous_close
    after_close = market_session.get("is_after_close") is True
    official_daily_confirmed = bool(
        after_close
        and _json_value(latest_daily_date) == _json_value(market_session.get("date"))
        and _finite(indicator.get("close"))
    )
    official_daily_reference = (
        indicator.get("close") - indicator.get("change")
        if official_daily_confirmed
        and _finite(indicator.get("change"))
        else None
    )
    if official_daily_confirmed and _finite(official_daily_reference):
        reference_close = official_daily_reference
    if latest_point is None and official_daily_confirmed:
        latest_point = {
            "time": latest_daily_date,
            "price": indicator.get("close"),
            "open": indicator.get("open"),
            "high": indicator.get("high"),
            "low": indicator.get("low"),
            "volume": indicator.get("volume"),
        }
        points = [latest_point]
    preloaded_current_partial_indicator: dict[str, Any] | None = None
    if latest_point is None and market_session.get("is_after_close"):
        preloaded_current_partial_indicator = _current_partial_daily_indicator(
            db=db,
            stock_id=stock_id,
            intraday_points=[],
            market_session=market_session,
            parameters=technical_parameters,
        )
        if (
            isinstance(preloaded_current_partial_indicator, dict)
            and preloaded_current_partial_indicator.get(
                "session_close_finalization"
            )
            == "session_final"
            and _finite(preloaded_current_partial_indicator.get("close"))
        ):
            latest_point = {
                "time": preloaded_current_partial_indicator.get("event_time"),
                "price": preloaded_current_partial_indicator.get("close"),
                "open": preloaded_current_partial_indicator.get("open"),
                "high": preloaded_current_partial_indicator.get("high"),
                "low": preloaded_current_partial_indicator.get("low"),
                "volume": preloaded_current_partial_indicator.get("volume"),
            }
            points = [latest_point]

    if latest_point is None:
        after_close_pending = after_close
        if include_intraday:
            missing.append("intraday_trend.points")
        rows.extend(
            [
                _row(
                    key="data_status",
                    label="資料狀態",
                    description=(
                        "收盤後尚未取得 canonical session close"
                        if after_close_pending
                        else "尚未取得今日第一筆成交或即時快照"
                    ),
                    value=0,
                    display_value="0筆",
                    basis="intraday point count",
                    source=str(intraday.get("source") or "intraday"),
                ),
                _row(
                    key="reference_close",
                    label="參考基準",
                    description="今日漲跌幅將以上一交易日收盤價計算",
                    value=reference_close,
                    display_value=_fmt_price(reference_close),
                    basis="previous trading day close",
                    source="market_daily_price",
                ),
            ]
        )
        badges.append(
            _badge(
                "收盤待確認" if after_close_pending else "等待盤中",
                "warning" if after_close_pending else "neutral",
            )
        )
        if after_close_pending:
            warnings.append(
                "The market is post-close but canonical session-close evidence is not yet available."
            )
        return {
            "kind": "tw_stock_technical_report",
            "stock_id": stock_id,
            "timeframe": "today",
            "phase": (
                "post_close_pending_close"
                if after_close_pending
                else "waiting_intraday"
            ),
            "confidence": "low",
            "generated_at": _now(),
            "title": (
                "等待收盤成交確認"
                if after_close_pending
                else "等待盤中資料"
            ),
            "summary": (
                "收盤成交尚未確認，不產生收盤後技術判斷"
                if after_close_pending
                else "尚未取得今日第一筆成交，日線資料暫不作盤中判斷"
            ),
            "score": 0,
            "value": None,
            "value_label": "vs 昨收",
            "rows": rows,
            "badges": badges,
            "data": {
                "intraday": {
                    "source": intraday.get("source"),
                    "point_count": intraday.get("point_count") or 0,
                    "previous_close": reference_close,
                    "latest_point": None,
                },
                "daily_background": indicator,
            },
            "missing": list(dict.fromkeys(missing)),
            "warnings": list(dict.fromkeys(warnings)),
            "source_refs": _technical_source_refs(timeframe="today", include_intraday=include_intraday),
        }

    series_coverage = (
        intraday.get("series_coverage")
        if isinstance(intraday.get("series_coverage"), dict)
        else None
    )
    coverage_analysis_usable = bool(
        series_coverage is None
        or series_coverage.get("status")
        in {"complete_prefix", "complete_session"}
    )
    stats = _intraday_stats(points)
    if series_coverage is not None:
        if series_coverage.get("opening_covered") is not True:
            stats["open"] = None
        if series_coverage.get("current_window_complete") is not True:
            stats["high"] = None
            stats["low"] = None
        if series_coverage.get("current_cumulative_volume_complete") is not True:
            stats["volume"] = None
    latest_price = latest_point.get("price")
    latest_minutes = _intraday_minutes(latest_point.get("time"))
    minutes_from_open = latest_minutes - SESSION_START_MINUTES if _finite(latest_minutes) else None
    point_count = len(points)
    latest_in_current_session = _intraday_point_is_current_session(
        latest_point.get("time"),
        market_session["date"],
    )
    current_partial_indicator = (
        preloaded_current_partial_indicator
        or _current_partial_daily_indicator(
            db=db,
            stock_id=stock_id,
            intraday_points=points,
            market_session=market_session,
            parameters=technical_parameters,
        )
        if latest_in_current_session
        and (coverage_analysis_usable or after_close)
        else None
    )
    session_close_confirmed = bool(
        after_close
        and isinstance(current_partial_indicator, dict)
        and current_partial_indicator.get("session_close_finalization")
        == "session_final"
        and _finite(current_partial_indicator.get("close"))
    )
    if session_close_confirmed:
        latest_price = current_partial_indicator.get("close")
        latest_point = {
            **latest_point,
            "price": latest_price,
            "time": current_partial_indicator.get("event_time")
            or latest_point.get("time"),
        }
        stats = {
            **stats,
            "open": current_partial_indicator.get("open") or stats.get("open"),
            "high": current_partial_indicator.get("high") or stats.get("high"),
            "low": current_partial_indicator.get("low") or stats.get("low"),
            "volume": current_partial_indicator.get("volume")
            or stats.get("volume"),
        }
    elif official_daily_confirmed:
        latest_price = indicator.get("close")
        latest_point = {
            **latest_point,
            "price": latest_price,
            "time": latest_daily_date,
        }
        stats = {
            **stats,
            "open": indicator.get("open") or stats.get("open"),
            "high": indicator.get("high") or stats.get("high"),
            "low": indicator.get("low") or stats.get("low"),
            "volume": indicator.get("volume") or stats.get("volume"),
        }
    opening_phase = (
        not after_close
        and (
            minutes_from_open is None
            or minutes_from_open < OPENING_OBSERVATION_MINUTES
            or point_count < OPENING_OBSERVATION_MIN_POINTS
        )
    )
    phase = (
        "post_close"
        if session_close_confirmed or official_daily_confirmed
        else "post_close_pending_close"
        if after_close
        else "stale_intraday"
        if not latest_in_current_session
        else "opening"
        if opening_phase
        else "intraday"
    )
    confidence = (
        "medium"
        if phase == "post_close"
        else "low"
        if phase == "intraday" and not coverage_analysis_usable
        else "low"
        if phase != "intraday"
        else "high"
        if point_count >= 20
        else "medium"
    )
    open_price = stats["open"]
    high_price = stats["high"]
    low_price = stats["low"]
    volume_pace = (
        build_tw_stock_volume_pace(
            db,
            stock_id=stock_id,
            current_points=points,
        )
        if series_coverage is None
        or series_coverage.get("current_cumulative_volume_complete") is True
        else {
            "kind": "tw_stock_same_time_volume_pace",
            "stock_id": stock_id,
            "status": "partial",
            "as_of": latest_point.get("time"),
            "trade_date": _json_value(market_session.get("date")),
            "comparison_minute": None,
            "current_cumulative_volume": None,
            "same_time_baseline_5d": {"sample_days": 0, "pace_ratio": None},
            "same_time_baseline_20d": {"sample_days": 0, "pace_ratio": None},
            "calculation_basis": "unavailable_due_to_partial_intraday_series_coverage",
            "warnings": [
                "Current intraday series does not cover the full regular session; volume pace is unavailable."
            ],
            "series_coverage": series_coverage,
        }
    )
    pace_current_volume = volume_pace.get("current_cumulative_volume")
    current_volume = (
        pace_current_volume
        if pace_current_volume is not None
        else stats["volume"]
        if (
            series_coverage is None
            or series_coverage.get("current_cumulative_volume_complete") is True
            or session_close_confirmed
            or official_daily_confirmed
        )
        else None
    )
    change_pct = _pct_change(latest_price, reference_close)
    change = latest_price - reference_close if _finite(latest_price) and _finite(reference_close) else None
    price_vs_open_pct = _pct_change(latest_price, open_price)
    opening_gap_pct = _pct_change(open_price, reference_close)
    intraday_range_pct = (
        _pct_change(high_price, low_price)
        if _finite(high_price) and _finite(low_price) and low_price != 0
        else None
    )
    volume_ma20 = _indicator_value(volume_ma, technical_parameters.volume_ma_medium_key, "volume_ma20")
    volume_vs_daily_average_pct = (
        _safe_ratio(current_volume, volume_ma20) * 100
        if _safe_ratio(current_volume, volume_ma20) is not None
        else None
    )
    volume_pace_5d = volume_pace.get("same_time_baseline_5d") or {}
    volume_pace_ratio = volume_pace_5d.get("pace_ratio")
    if volume_pace.get("status") != "ready":
        warnings.extend(str(item) for item in volume_pace.get("warnings") or [] if item)
    if not _finite(volume_pace_ratio):
        missing.append("intraday_volume.same_time_baseline_5d")
    ma20 = _indicator_value(ma, technical_parameters.ma_medium_key, "ma20")
    price_vs_ma20 = _pct_change(latest_price, ma20)
    rsi14 = _indicator_value(rsi, technical_parameters.rsi_key, "rsi14")
    macd_histogram = macd.get("histogram")
    latest_institutional = daily["institutional"]
    institutional_net = (
        getattr(latest_institutional, "total_institutional_net", None)
        if latest_institutional is not None
        else None
    )
    margin_change = _margin_balance_change(daily["margin"])
    score = 0

    if _finite(change_pct):
        score += 1 if change_pct > 0 else -1 if change_pct < 0 else 0
    if _finite(opening_gap_pct):
        score += 1 if opening_gap_pct > 0 else -1 if opening_gap_pct < 0 else 0
    if not opening_phase and _finite(price_vs_open_pct):
        score += 1 if price_vs_open_pct > 0 else -1 if price_vs_open_pct < 0 else 0

    rows.extend(
        [
            _row(
                key=(
                    "official_close_price"
                    if official_daily_confirmed
                    else "session_close_price"
                    if session_close_confirmed
                    else "last_intraday_price"
                    if after_close
                    else "live_price"
                ),
                label=(
                    "正式收盤"
                    if official_daily_confirmed
                    else "收盤成交"
                    if session_close_confirmed
                    else "最後盤中成交"
                    if after_close
                    else "即時價格"
                ),
                description=(
                    f"相對昨收 {_fmt_pct(change_pct)}，正式日線已發布"
                    if official_daily_confirmed
                    else f"相對昨收 {_fmt_pct(change_pct)}，已由 canonical session close 確認"
                    if session_close_confirmed
                    else f"相對昨收 {_fmt_pct(change_pct)}，收盤成交尚未確認"
                    if after_close
                    else f"相對昨收 {_fmt_pct(change_pct)}，{point_count} 筆盤中資料"
                ),
                value=latest_price,
                display_value=_fmt_price(latest_price),
                direction=change_pct,
                basis=(
                    "official daily close vs official previous close"
                    if official_daily_confirmed
                    else "canonical session close vs previous close"
                    if session_close_confirmed
                    else "last observed intraday price pending session close"
                    if after_close
                    else "latest intraday price vs previous close"
                ),
                source=str(
                    "market_daily_price"
                    if official_daily_confirmed
                    else current_partial_indicator.get("source")
                    if session_close_confirmed
                    and isinstance(current_partial_indicator, dict)
                    else intraday.get("source") or "intraday"
                ),
            ),
            _row(
                key="opening_structure",
                label="開盤結構",
                description=(
                    f"開盤 {_fmt_price(open_price)}，高低 {_fmt_price(high_price)} / "
                    f"{_fmt_price(low_price)}，振幅 {_fmt_pct(intraday_range_pct)}"
                ),
                value=price_vs_open_pct,
                display_value=_fmt_pct(price_vs_open_pct),
                direction=price_vs_open_pct,
                basis="latest price vs opening price",
                source=str(intraday.get("source") or "intraday"),
            ),
            _row(
                key="volume_pace",
                label="量能速度",
                description=_volume_pace_description(volume_pace),
                value=volume_pace_ratio,
                display_value=(
                    "累積中" if not _finite(volume_pace_ratio) else _fmt_ratio(volume_pace_ratio)
                ),
                direction=None,
                tone=(
                    "warning"
                    if _finite(volume_pace_ratio) and volume_pace_ratio >= 1.5
                    else "neutral"
                ),
                basis=str(volume_pace.get("calculation_basis") or "same-time volume history unavailable"),
                source="market_intraday_bar+market_daily_price",
            ),
            _row(
                key="daily_background",
                label="日線背景",
                description=f"RSI {_fmt_number(rsi14, 2)}，MACD H {_fmt_number(macd_histogram, 2)}，MA20 {_fmt_price(ma20)}",
                value=price_vs_ma20,
                display_value=_fmt_pct(price_vs_ma20),
                direction=price_vs_ma20,
                tone="warning" if _finite(rsi14) and rsi14 >= technical_parameters.rsi_overheated_at else _tone(price_vs_ma20),
                basis="latest daily indicators, not live intraday momentum",
                source="market_daily_price",
            ),
            _row(
                key="institutional_flow",
                label="法人籌碼",
                description=f"最新已公布三大法人，融資餘額 {_fmt_signed_number(margin_change)}",
                value=institutional_net,
                display_value="-" if institutional_net is None else f"{_fmt_signed_lots(institutional_net)}張",
                direction=institutional_net,
                basis="latest published institutional trade, not intraday",
                source="institutional_trade_daily",
            ),
        ]
    )

    if opening_phase:
        badges.append(_badge("開盤資料少", "warning"))
    if _finite(opening_gap_pct):
        badges.append(_badge("開高" if opening_gap_pct >= 0 else "開低", "positive" if opening_gap_pct >= 0 else "negative"))
    if _finite(price_vs_ma20):
        badges.append(_badge("日線站上 MA20" if price_vs_ma20 >= 0 else "日線跌破 MA20", "positive" if price_vs_ma20 >= 0 else "negative"))
    if _finite(rsi14) and rsi14 >= technical_parameters.rsi_overheated_at:
        badges.append(_badge("日線 RSI 過熱", "warning"))

    if phase == "post_close":
        if official_daily_confirmed:
            title = "正式日線已發布"
            badges.append(_badge("正式收盤", "neutral"))
        else:
            title = "收盤成交已確認"
            badges.append(_badge("收盤成交", "neutral"))
            warnings.append(
                "Session close is current-session evidence; completed official daily indicators remain the decision snapshot."
            )
    elif phase == "post_close_pending_close":
        title = "等待收盤成交確認"
        badges.append(_badge("收盤待確認", "warning"))
        warnings.append(
            "The market is post-close but canonical session-close evidence is not yet available."
        )
    elif phase == "stale_intraday":
        title = "盤中資料非當前交易時段"
        warnings.append("Latest intraday point is not from the current Taiwan trading session.")
    elif phase == "opening":
        title = "開盤資料尚不足"
        warnings.append(
            f"Intraday scoring requires at least {OPENING_OBSERVATION_MIN_POINTS} current-session points after the opening observation window."
        )
    elif phase == "intraday" and not coverage_analysis_usable:
        title = "盤中資料涵蓋不完整"
        badges.append(_badge("盤中涵蓋不完整", "warning"))
        warnings.append(
            "Current intraday coverage is partial; opening, full-session range, cumulative volume, and technical score are unavailable."
        )
    else:
        title = _title_from_score(
            score,
            positive="盤中偏多",
            neutral="盤中觀察",
            negative="盤中偏弱",
        )
    summary_parts = (
        [
            "正式日線已發布" if official_daily_confirmed else "收盤成交已確認",
            "收盤高於昨收" if _finite(change_pct) and change_pct >= 0 else "收盤低於昨收" if _finite(change_pct) else "漲跌資料不足",
            (
                "今日正式日線是決策快照"
                if official_daily_confirmed
                else "正式日線尚待發布，既有完成日線仍是決策快照"
            ),
        ]
        if phase == "post_close"
        else [
            "收盤成交尚未確認",
            "僅保留最後盤中成交作參考",
            "不產生收盤後技術判斷",
        ]
        if phase == "post_close_pending_close"
        else [
            f"{point_count} 筆盤中資料",
            "現價高於昨收" if _finite(change_pct) and change_pct >= 0 else "現價低於昨收" if _finite(change_pct) else "漲跌資料不足",
            "開高" if _finite(opening_gap_pct) and opening_gap_pct >= 0 else "開低" if _finite(opening_gap_pct) else "開盤資料不足",
            "日線指標僅作背景"
            if opening_phase
            else "盤中資料涵蓋不足，只保留最新成交作參考"
            if not coverage_analysis_usable
            else "盤中資料已進入觀察期",
        ]
    )

    return {
        "kind": "tw_stock_technical_report",
        "stock_id": stock_id,
        "timeframe": "today",
        "phase": phase,
        "confidence": confidence,
        "generated_at": _now(),
        "title": title,
        "summary": "，".join(summary_parts),
        "score": (
            score if phase == "intraday" and coverage_analysis_usable else 0
        ),
        "value": change_pct,
        "value_label": "vs 昨收",
        "rows": rows,
        "badges": badges,
        "data": {
            "intraday": {
                "source": intraday.get("source"),
                "technical_price_basis": "intraday_series_latest_price",
                "price_semantics": (
                    "official_daily_close"
                    if official_daily_confirmed
                    else "session_close"
                    if session_close_confirmed
                    else "last_intraday_trade_pending_session_close"
                    if after_close
                    else "intraday_last_trade"
                ),
                "bid_ask_price_used": False,
                "point_count": point_count,
                "previous_close": reference_close,
                "latest_point": latest_point,
                "is_current_session": latest_in_current_session,
                "score_eligible": (
                    phase == "intraday" and coverage_analysis_usable
                ),
                "series_coverage": series_coverage,
                "stats": stats,
                "change": change,
                "change_pct": change_pct,
                "opening_gap_pct": opening_gap_pct,
                "price_vs_open_pct": price_vs_open_pct,
                "volume_vs_daily_average_pct": volume_vs_daily_average_pct,
                "volume_vs_daily_average_role": "context_only_not_intraday_pace",
                "volume_pace": volume_pace,
            },
            "daily_background": indicator,
            "current_partial_indicator": current_partial_indicator,
            "decision_snapshot": "completed",
            "market_session": {
                **{key: _json_value(value) for key, value in market_session.items()},
                "latest_daily_date": _json_value(latest_daily_date),
            },
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": _technical_source_refs(timeframe="today", include_intraday=include_intraday),
    }


def _build_daily_report(
    *,
    db: Session,
    stock_id: str,
    include_intraday: bool = False,
    parameters: TechnicalAnalysisParameters | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    technical_parameters = parameters or get_technical_analysis_parameters()
    rows: list[dict[str, Any]] = []
    badges: list[dict[str, str]] = []
    warnings: list[str] = []
    missing: list[str] = []
    daily = _daily_context(
        db=db,
        stock_id=stock_id,
        parameters=technical_parameters,
        to_date=to_date,
    )
    indicator = daily["indicator"]

    if indicator is None:
        return {
            "kind": "tw_stock_technical_report",
            "stock_id": stock_id,
            "timeframe": "daily",
            "phase": "daily",
            "confidence": "low",
            "generated_at": _now(),
            "title": "資料不足",
            "summary": "尚無足夠日線資料產生短線報告",
            "score": 0,
            "value": None,
            "value_label": "vs MA20",
            "rows": [
                _row(
                    key="data_status",
                    label="資料狀態",
                    description="日線價格或技術指標不足",
                    value=None,
                    display_value="-",
                    basis="daily indicator availability",
                    source="market_daily_price",
                )
            ],
            "badges": [],
            "data": {"daily_indicator": None},
            "missing": ["market_daily_price"],
            "warnings": warnings,
            "source_refs": _technical_source_refs(timeframe="daily", include_intraday=False),
        }

    close = indicator.get("close")
    volume = indicator.get("volume")
    change_pct = indicator.get("change_pct")
    ma = indicator.get("ma") or {}
    volume_ma = indicator.get("volume_ma") or {}
    macd = indicator.get("macd") or {}
    rsi = indicator.get("rsi") or {}
    atr = indicator.get("atr") or {}
    adx = indicator.get("adx") or {}
    roc = indicator.get("roc") or {}
    mfi = indicator.get("mfi") or {}
    donchian = indicator.get("donchian") or {}
    bollinger = indicator.get("bollinger") or {}
    support_resistance = indicator.get("support_resistance") or {}
    ma5 = _indicator_value(ma, technical_parameters.ma_short_key, "ma5")
    ma20 = _indicator_value(ma, technical_parameters.ma_medium_key, "ma20")
    ma60 = _indicator_value(ma, technical_parameters.ma_long_key, "ma60")
    support20 = _indicator_value(
        support_resistance,
        technical_parameters.support_key,
        "support20",
    )
    resistance20 = _indicator_value(
        support_resistance,
        technical_parameters.resistance_key,
        "resistance20",
    )
    analysis_price = close
    analysis_price_time = indicator.get("time")
    analysis_price_source = "market_daily_price"
    analysis_is_intraday = False
    current_partial_indicator: dict[str, Any] | None = None
    intraday_context: dict[str, Any] | None = None
    market_session = _today_market_session()
    indicator_time = indicator.get("time")
    if isinstance(indicator_time, datetime):
        indicator_date = indicator_time.astimezone(TAIPEI_TZ).date()
    elif isinstance(indicator_time, date):
        indicator_date = indicator_time
    elif isinstance(indicator_time, str):
        try:
            indicator_date = date.fromisoformat(indicator_time[:10])
        except ValueError:
            indicator_date = None
    else:
        indicator_date = None
    has_current_daily_indicator = indicator_date == market_session["date"]
    should_load_intraday = (
        to_date is None
        and include_intraday
        and market_session["is_trading_day"]
        and (
            market_session["is_intraday_window"]
            or (
                market_session["is_after_close"]
                and not has_current_daily_indicator
            )
        )
    )

    if should_load_intraday:
        intraday = get_intraday_trend(db=db, stock_id=stock_id)
        intraday_points = intraday.get("points") or []
        intraday_series_coverage = (
            intraday.get("series_coverage")
            if isinstance(intraday.get("series_coverage"), dict)
            else None
        )
        intraday_coverage_usable = bool(
            intraday_series_coverage is None
            or intraday_series_coverage.get("status")
            in {"complete_prefix", "complete_session"}
        )
        latest_intraday_point = intraday_points[-1] if intraday_points else None
        latest_intraday_price = (
            latest_intraday_point.get("price")
            if isinstance(latest_intraday_point, dict)
            else None
        )
        latest_intraday_time = (
            latest_intraday_point.get("time")
            if isinstance(latest_intraday_point, dict)
            else None
        )
        is_current_session = _intraday_point_is_current_session(
            latest_intraday_time,
            market_session["date"],
        )
        intraday_context = {
            "source": intraday.get("source"),
            "point_count": len(intraday_points),
            "previous_close": intraday.get("previous_close"),
            "latest_point": latest_intraday_point,
            "is_current_session": is_current_session,
            "series_coverage": intraday_series_coverage,
        }
        if _finite(latest_intraday_price) and is_current_session:
            analysis_price = latest_intraday_price
            analysis_price_time = latest_intraday_time
            analysis_price_source = str(intraday.get("source") or "intraday")
            analysis_is_intraday = True
            current_partial_indicator = _current_partial_daily_indicator(
                db=db,
                stock_id=stock_id,
                intraday_points=intraday_points,
                market_session=market_session,
                parameters=technical_parameters,
            )
        elif latest_intraday_point is not None:
            warnings.append(
                "Latest intraday point is not from the current Taiwan trading session; session-close evidence will be used when available."
            )
        else:
            missing.append("intraday_trend.points")
            warnings.append(
                "No current-session intraday series is available; session-close evidence will be used when available."
            )
        if market_session["is_after_close"] and current_partial_indicator is None:
            if intraday_coverage_usable or market_session["is_after_close"]:
                current_partial_indicator = _current_partial_daily_indicator(
                    db=db,
                    stock_id=stock_id,
                    intraday_points=intraday_points,
                    market_session=market_session,
                    parameters=technical_parameters,
                )
            else:
                warnings.append(
                    "Current intraday coverage is partial; provisional OHLCV indicators are unavailable and only the latest trade remains contextual."
                )
        partial_price = (
            current_partial_indicator.get("close")
            if current_partial_indicator is not None
            else None
        )
        if _finite(partial_price):
            analysis_price = partial_price
            analysis_price_time = (
                current_partial_indicator.get("event_time")
                or current_partial_indicator.get("time")
            )
            analysis_price_source = str(
                current_partial_indicator.get("source")
                or intraday.get("source")
                or "current_partial_indicator"
            )
            analysis_is_intraday = True
        elif market_session["is_after_close"]:
            warnings.append(
                "No usable current-session provisional indicator is available; the finalized daily snapshot remains the only technical state."
            )
    elif include_intraday and not market_session["is_trading_day"]:
        warnings.append(
            f"{market_session['date']} is not a Taiwan trading day; daily close remains the analysis price."
        )

    moving_average_structure = build_moving_average_structure(
        price=close,
        ma5=ma5,
        ma20=ma20,
        ma60=ma60,
    )
    distance_pct = moving_average_structure["distance_pct"]
    price_vs_ma5 = distance_pct.get("ma5")
    price_vs_ma20 = distance_pct.get("ma20")
    price_vs_ma60 = distance_pct.get("ma60")
    range_signals, range_signal_score = build_price_range_signals(
        price=close,
        support=support20,
        resistance=resistance20,
        donchian_upper=_indicator_value(
            donchian,
            technical_parameters.donchian_upper_key,
            "upper20",
        ),
        donchian_lower=_indicator_value(
            donchian,
            technical_parameters.donchian_lower_key,
            "lower20",
        ),
        bollinger_upper=_indicator_value(
            bollinger,
            technical_parameters.bollinger_upper_key,
            "upper20",
        ),
        bollinger_lower=_indicator_value(
            bollinger,
            technical_parameters.bollinger_lower_key,
            "lower20",
        ),
        near_threshold_pct=technical_parameters.near_level_threshold_pct,
    )
    volume_ratio = _safe_ratio(
        volume,
        _indicator_value(volume_ma, technical_parameters.volume_ma_medium_key, "volume_ma20"),
    )
    volume_ratio_pct = (volume_ratio - 1) * 100 if volume_ratio is not None else None
    macd_histogram = macd.get("histogram")
    rsi14 = _indicator_value(rsi, technical_parameters.rsi_key, "rsi14")
    roc12 = _indicator_value(roc, technical_parameters.roc_key, "roc12")
    mfi14 = _indicator_value(mfi, technical_parameters.mfi_key, "mfi14")
    adx14 = _indicator_value(adx, technical_parameters.adx_key, "adx14")
    plus_di14 = _indicator_value(adx, technical_parameters.plus_di_key, "plus_di14")
    minus_di14 = _indicator_value(adx, technical_parameters.minus_di_key, "minus_di14")
    atr14 = _indicator_value(atr, technical_parameters.atr_key, "atr14")
    atr_pct = _safe_ratio(atr14, close)
    atr_pct = atr_pct * 100 if atr_pct is not None else None
    donchian_upper = _indicator_value(donchian, technical_parameters.donchian_upper_key, "upper20")
    donchian_lower = _indicator_value(donchian, technical_parameters.donchian_lower_key, "lower20")
    donchian_position = None
    if _finite(donchian_upper) and _finite(donchian_lower) and donchian_upper != donchian_lower:
        donchian_position = (
            (close - donchian_lower)
            / (donchian_upper - donchian_lower)
            * 100
        )
    analysis_change_pct = (
        _pct_change(analysis_price, intraday_context.get("previous_close"))
        if analysis_is_intraday and intraday_context
        else change_pct
    )
    current_state = build_technical_current_state(
        price=close,
        moving_average_structure=moving_average_structure,
        change_pct=change_pct,
        volume_ratio=volume_ratio,
        rsi14=rsi14,
        macd_histogram=macd_histogram,
        roc12=roc12,
        mfi14=mfi14,
        adx14=adx14,
        plus_di14=plus_di14,
        minus_di14=minus_di14,
        atr_pct=atr_pct,
        donchian_position=donchian_position,
        support20=support20,
        resistance20=resistance20,
        adx_trend_threshold=technical_parameters.adx_trend_threshold,
        volume_ratio_threshold=technical_parameters.volume_ratio_threshold,
        rsi_overheated_threshold=technical_parameters.rsi_overheated_at,
        atr_high_volatility_pct=technical_parameters.atr_high_volatility_pct,
    )
    current_projection = (
        _technical_state_projection_from_indicator(
            current_partial_indicator,
            parameters=technical_parameters,
        )
        if current_partial_indicator is not None
        else None
    )
    outward_current_state = (
        current_projection["state"]
        if current_projection is not None
        else current_state
    )
    current_observation = (
        {
            "status": current_partial_indicator.get("bar_status"),
            "time": _json_value(current_partial_indicator.get("time")),
            "decision_usable": bool(
                current_partial_indicator.get("decision_usable") is True
            ),
            "official_daily_confirmed": bool(
                current_partial_indicator.get("official_daily_confirmed") is True
            ),
            "indicator": current_partial_indicator,
            "current_state": outward_current_state,
        }
        if current_partial_indicator is not None
        else None
    )
    current_evidence = {
        item["key"]: item
        for item in current_state["evidence"]
    }
    latest_institutional = daily["institutional"]
    institutional_net = (
        getattr(latest_institutional, "total_institutional_net", None)
        if latest_institutional is not None
        else None
    )
    margin_change = _margin_balance_change(daily["margin"])
    score = range_signal_score

    if _finite(price_vs_ma5):
        score += 1 if price_vs_ma5 >= 0 else -1
    if _finite(price_vs_ma20):
        score += 1 if price_vs_ma20 >= 0 else -1
    for range_signal in range_signals[:2]:
        badges.append(
            _badge(
                str(range_signal["label"]),
                "positive" if range_signal["direction"] == "bullish" else "negative",
            )
        )
    if _finite(price_vs_ma60):
        score += 2 if price_vs_ma60 >= 0 else -2
    if _finite(ma5) and _finite(ma20):
        score += 1 if ma5 >= ma20 else -1
    if _finite(ma20) and _finite(ma60):
        score += 1 if ma20 >= ma60 else -1
    if _finite(macd_histogram):
        score += 1 if macd_histogram >= 0 else -1
    if _finite(rsi14):
        if technical_parameters.rsi_bull_min <= rsi14 < technical_parameters.rsi_overheated_at:
            score += 1
        elif rsi14 < technical_parameters.rsi_weak_below:
            score -= 1
    if (
        _finite(adx14)
        and adx14 >= technical_parameters.adx_trend_threshold
        and _finite(plus_di14)
        and _finite(minus_di14)
    ):
        score += 1 if plus_di14 >= minus_di14 else -1
    if _finite(institutional_net):
        score += 1 if institutional_net > 0 else -1

    rows.extend(
        [
            _row(
                key="price_position",
                label="價格位置",
                description=(
                    f"已完成日線收盤價 {_fmt_price(close)}；"
                    f"vs MA5/20/60 {_fmt_pct(price_vs_ma5)} / {_fmt_pct(price_vs_ma20)} / "
                    f"{_fmt_pct(price_vs_ma60)}"
                ),
                value=price_vs_ma60,
                display_value=current_state["position"]["label"],
                direction=price_vs_ma60,
                basis="finalized daily close vs finalized daily moving averages",
                source="market_daily_price",
            ),
            _row(
                key="trend_structure",
                label="趨勢結構",
                description=(
                    f"{moving_average_structure['price_state_label']}，"
                    f"{current_state['position']['alignment_label']}；"
                    f"MA5/20/60 {_fmt_price(ma5)} / {_fmt_price(ma20)} / {_fmt_price(ma60)}，"
                    f"ADX {_fmt_number(adx14, 2)}，"
                    f"+DI {_fmt_number(plus_di14, 2)} / -DI {_fmt_number(minus_di14, 2)}"
                ),
                value=score,
                display_value=current_state["headline"]["label"],
                direction=score,
                basis="price position, moving average alignment, and ADX direction",
                source="market_daily_price",
            ),
            _row(
                key="momentum",
                label="動能指標",
                description=current_evidence["momentum"]["summary"],
                value=rsi14,
                display_value=current_state["qualifier"]["label"],
                direction=macd_histogram,
                tone=current_evidence["momentum"]["tone"],
                basis="daily RSI, MACD histogram, and ROC",
                source="market_daily_price",
            ),
            _row(
                key="volume_flow",
                label="量價資金",
                description=current_evidence["volume"]["summary"],
                value=volume_ratio_pct,
                display_value=current_evidence["volume"]["state_label"],
                direction=volume_ratio_pct,
                tone=current_evidence["volume"]["tone"],
                basis="daily volume vs 20-day average volume",
                source="market_daily_price",
            ),
            _row(
                key="volatility_risk",
                label="波動風險",
                description=current_evidence["risk"]["summary"],
                value=atr_pct,
                display_value=current_evidence["risk"]["state_label"],
                direction=1 if _finite(atr_pct) and atr_pct > technical_parameters.atr_high_volatility_pct else 0,
                tone=current_evidence["risk"]["tone"],
                basis="finalized daily ATR and close vs finalized 20-day Donchian range",
                source="market_daily_price",
            ),
            _row(
                key="institutional_flow",
                label="法人籌碼",
                description=f"最新三大法人合計，融資餘額 {_fmt_signed_number(margin_change)}",
                value=institutional_net,
                display_value="-" if institutional_net is None else f"{_fmt_signed_lots(institutional_net)}張",
                direction=institutional_net,
                basis="latest published institutional trade and margin balance",
                source="institutional_trade_daily",
            ),
        ]
    )

    if _finite(price_vs_ma20):
        badges.append(_badge("站上 MA20" if price_vs_ma20 >= 0 else "跌破 MA20", "positive" if price_vs_ma20 >= 0 else "negative"))
    if _finite(macd_histogram):
        badges.append(_badge("MACD 偏多" if macd_histogram >= 0 else "MACD 偏弱", "positive" if macd_histogram >= 0 else "negative"))
    if _finite(rsi14) and rsi14 >= technical_parameters.rsi_overheated_at:
        badges.append(_badge("RSI 過熱", "warning"))
    if _finite(volume_ratio) and volume_ratio >= technical_parameters.volume_ratio_threshold:
        badges.append(_badge("放量", "warning"))

    if indicator.get("time") is None:
        missing.append("market_daily_price.time")

    if _finite(price_vs_ma60):
        badges.append(
            _badge(
                "站上 MA60" if price_vs_ma60 >= 0 else "失守 MA60",
                "positive" if price_vs_ma60 >= 0 else "negative",
            )
        )
    if moving_average_structure["price_state"] in {"above_all", "below_all"}:
        badges.append(
            _badge(
                moving_average_structure["price_state_label"],
                "positive"
                if moving_average_structure["price_state"] == "above_all"
                else "negative",
            )
        )
    if analysis_is_intraday:
        badges.append(_badge("今日暫估指標另列", "warning"))
        warnings.append(
            "Decision fields and rows use the finalized daily snapshot; current_observation exposes a coherent provisional calculation and is not decision-usable."
        )
    summary_parts = [
        current_state["position"]["label"],
        current_state["qualifier"]["label"],
        current_evidence["volume"]["state_label"],
    ]

    return {
        "kind": "tw_stock_technical_report",
        "stock_id": stock_id,
        "timeframe": "daily",
        "phase": "daily_intraday" if analysis_is_intraday else "daily",
        "confidence": "medium" if analysis_is_intraday or missing else "high",
        "generated_at": _now(),
        "title": current_state["headline"]["label"],
        "summary": "，".join(summary_parts),
        "score": score,
        "value": price_vs_ma20,
        "value_label": "vs MA20",
        "rows": rows,
        "badges": badges,
        "data": {
            "daily_indicator": indicator,
            "current_partial_indicator": current_partial_indicator,
            "current_observation": current_observation,
            "decision_snapshot": "completed",
            "decision_state": current_state,
            "decision_state_time": _json_value(indicator.get("time")),
            "decision_state_status": "official_daily_finalized",
            "market": _stock_market(db=db, stock_id=stock_id),
            "change_pct": analysis_change_pct,
            "decision_change_pct": change_pct,
            "current_state": outward_current_state,
            "current_state_time": (
                _json_value(current_partial_indicator.get("time"))
                if current_partial_indicator is not None
                else _json_value(indicator.get("time"))
            ),
            "current_state_status": (
                current_partial_indicator.get("bar_status")
                if current_partial_indicator is not None
                else "official_daily_finalized"
            ),
            "current_state_decision_usable": current_partial_indicator is None,
            "price_context": {
                "price": analysis_price,
                "price_time": _json_value(analysis_price_time),
                "price_source": analysis_price_source,
                "technical_price_basis": (
                    "session_close_provisional_daily_bar"
                    if current_partial_indicator is not None
                    and current_partial_indicator.get("bar_status")
                    == "provisional_close"
                    else "intraday_partial_daily_bar"
                    if current_partial_indicator is not None
                    else "intraday_series_latest_price"
                    if analysis_is_intraday
                    else "official_completed_daily_close"
                ),
                "bid_ask_price_used": False,
                "is_intraday": analysis_is_intraday,
                "is_provisional": analysis_is_intraday,
                "daily_indicator_time": _json_value(indicator.get("time")),
                "moving_average_structure": (
                    current_projection["moving_average_structure"]
                    if current_projection is not None
                    else moving_average_structure
                ),
                "range_signals": (
                    current_projection["range_signals"]
                    if current_projection is not None
                    else range_signals
                ),
            },
            "intraday": intraday_context,
            "market_session": {
                key: _json_value(value)
                for key, value in market_session.items()
            },
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": _technical_source_refs(
            timeframe="daily",
            include_intraday=intraday_context is not None,
        ),
    }


def _build_aggregated_report(
    *,
    db: Session,
    stock_id: str,
    timeframe: str,
    parameters: TechnicalAnalysisParameters | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    technical_parameters = parameters or get_technical_analysis_parameters()
    indicator, chart = _aggregated_indicator(
        db=db,
        stock_id=stock_id,
        timeframe=timeframe,
        parameters=technical_parameters,
        to_date=to_date,
    )
    report = _build_indicator_report(
        db=db,
        stock_id=stock_id,
        timeframe=timeframe,
        indicator=indicator,
        point_count=chart.get("point_count"),
        parameters=technical_parameters,
        to_date=to_date,
    )
    period = chart.get("period") or {}
    report.setdefault("data", {})["period"] = period
    report["data"]["current_partial_indicator"] = chart.get(
        "current_partial_indicator"
    )
    report["data"]["decision_snapshot"] = chart.get(
        "decision_snapshot",
        "completed",
    )
    if period.get("status") == "current_partial":
        report.setdefault("warnings", []).append(
            "The current weekly/monthly bar is incomplete; decision fields use the latest completed period while current_partial_indicator is observational only."
        )
    return report


def build_stock_technical_report(
    *,
    db: Session,
    stock_id: str,
    timeframe: str = "daily",
    include_intraday: bool = True,
    intraday_override: dict[str, Any] | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    normalized_timeframe = timeframe.strip().lower()
    normalized_stock_id = stock_id.strip()
    technical_parameters = get_technical_analysis_parameters()

    if normalized_timeframe == "today":
        if to_date is not None:
            raise ValueError(
                "Historical technical cutoff is not compatible with timeframe=today."
            )
        return _with_evidence_passport(
            _build_today_report(
                db=db,
                stock_id=normalized_stock_id,
                include_intraday=include_intraday,
                intraday_override=intraday_override,
                parameters=technical_parameters,
            )
        )

    if normalized_timeframe == "daily":
        return _with_evidence_passport(
            _build_daily_report(
                db=db,
                stock_id=normalized_stock_id,
                include_intraday=include_intraday,
                parameters=technical_parameters,
                to_date=to_date,
            )
        )

    if normalized_timeframe in {"weekly", "monthly"}:
        return _with_evidence_passport(
            _build_aggregated_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe=normalized_timeframe,
                parameters=technical_parameters,
                to_date=to_date,
            )
        )

    raise ValueError("timeframe must be one of: today, daily, weekly, monthly.")
