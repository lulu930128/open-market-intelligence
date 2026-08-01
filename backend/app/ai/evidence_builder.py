from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any

from app.market.financial_metric_semantics import (
    financial_period_scope_label,
    source_reported_financial_semantics,
)


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def source_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def first_value(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row.get(key)
    return None


def pct_change(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None or previous == 0:
        return None
    return ((current - previous) / previous) * 100


def format_number(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def round_price(value: Any) -> float | None:
    number = finite_number(value)
    if number is None or number <= 0:
        return None
    if number >= 100:
        return float(round(number))
    if number >= 10:
        return round(number, 1)
    return round(number, 2)


def format_lots(value: float | None) -> str | None:
    if value is None:
        return None
    lots = value / 1000
    if abs(lots) >= 100:
        return f"{lots:,.0f} 張"
    return f"{lots:,.1f}".rstrip("0").rstrip(".") + " 張"


def latest_financial_period(row: Any) -> str | None:
    if row is None:
        return None

    period = source_value(row, "period")
    if period:
        return str(period)

    fiscal_year = source_value(row, "fiscal_year")
    quarter = source_value(row, "quarter")
    if fiscal_year is None or quarter is None:
        return None

    return f"{fiscal_year}Q{quarter}"


def indicator_from_report(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    indicator = data.get("daily_indicator") or data.get("indicator") or {}
    return indicator if isinstance(indicator, dict) else {}


def indicator_level_values(indicator: dict[str, Any]) -> dict[str, float | None]:
    ma = indicator.get("ma") if isinstance(indicator.get("ma"), dict) else {}
    atr = indicator.get("atr") if isinstance(indicator.get("atr"), dict) else {}
    donchian = indicator.get("donchian") if isinstance(indicator.get("donchian"), dict) else {}
    rsi = indicator.get("rsi") if isinstance(indicator.get("rsi"), dict) else {}
    return {
        "close": finite_number(indicator.get("close")),
        "ma5": finite_number(ma.get("ma5")),
        "ma20": finite_number(ma.get("ma20")),
        "ma60": finite_number(ma.get("ma60")),
        "atr14": finite_number(atr.get("atr14")),
        "donchian_upper20": finite_number(donchian.get("upper20")),
        "donchian_lower20": finite_number(donchian.get("lower20")),
        "rsi14": finite_number(rsi.get("rsi14")),
    }


def normalize_technical_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close = finite_number(first_value(row, ("close", "close_price", "last_price", "settlement_price")))
        if close is None:
            continue
        points.append(
            {
                "time": json_value(first_value(row, ("time", "trade_date", "bar_time", "quote_time"))),
                "open": finite_number(first_value(row, ("open", "open_price"))),
                "high": finite_number(first_value(row, ("high", "high_price"))),
                "low": finite_number(first_value(row, ("low", "low_price"))),
                "close": close,
                "volume": finite_number(first_value(row, ("volume", "trade_volume", "total_volume"))),
                "trade_value": finite_number(row.get("trade_value")),
            }
        )
    return points


def decision_data_quality(
    *,
    latest_daily: Any,
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    close_price = finite_number(source_value(latest_daily, "close_price"))
    trade_volume = finite_number(source_value(latest_daily, "trade_volume"))
    trade_date = json_value(source_value(latest_daily, "trade_date"))
    return {
        "as_of": trade_date,
        "price": {
            "value": round_price(close_price),
            "source": "market_daily_price.close_price",
            "as_of": trade_date,
        },
        "volume": {
            "value": trade_volume,
            "unit": "shares",
            "display_unit": "lots",
            "display_value": format_lots(trade_volume),
            "source": "market_daily_price.trade_volume",
            "as_of": trade_date,
        },
        "source_names": [
            str(ref.get("name"))
            for ref in source_refs
            if isinstance(ref, dict) and ref.get("name")
        ],
    }


def market_session_evidence(
    *,
    technical_reports: dict[str, Any],
    latest_daily: Any,
    calendar_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    calendar_market_status = _calendar_market_status(calendar_status, market="tw")
    if calendar_market_status:
        return _market_session_from_calendar_status(
            calendar_market_status,
            latest_daily=latest_daily,
        )

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
        json_value(source_value(latest_daily, "trade_date"))
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


def _calendar_market_status(
    calendar_status: dict[str, Any] | None,
    *,
    market: str,
) -> dict[str, Any]:
    if not isinstance(calendar_status, dict):
        return {}

    markets = calendar_status.get("markets")
    if isinstance(markets, dict) and isinstance(markets.get(market), dict):
        return markets[market]

    if calendar_status.get("market") == market:
        return calendar_status

    return {}


def _market_session_from_calendar_status(
    status: dict[str, Any],
    *,
    latest_daily: Any,
) -> dict[str, Any]:
    latest_daily_date = (
        json_value(source_value(latest_daily, "trade_date"))
        or status.get("previous_trading_day")
    )
    session_date = status.get("date")
    next_trading_day = status.get("next_trading_day")
    release_windows = (
        status.get("release_windows")
        if isinstance(status.get("release_windows"), dict)
        else {}
    )
    daily_price_release = (
        release_windows.get("market_daily_price")
        if isinstance(release_windows.get("market_daily_price"), dict)
        else {}
    )

    if status.get("is_trading_day") is False:
        summary = (
            f"{session_date or '今日'} 台股休市，最新日線截至 {latest_daily_date or '-'}；"
            f"下一交易日 {next_trading_day or '-'} 再確認盤中價量。"
        )
    elif daily_price_release.get("status") == "pending":
        summary = (
            f"{session_date or '今日'} 台股交易日，日線資料尚待 "
            f"{daily_price_release.get('release_time') or '-'} 發布；"
            f"目前最新日線截至 {latest_daily_date or '-'}。"
        )
    else:
        summary = (
            f"{session_date or '今日'} 台股交易日，session phase 為 "
            f"{status.get('phase') or '-'}；最新日線截至 {latest_daily_date or '-'}。"
        )

    return {
        "phase": status.get("phase"),
        "is_trading_day": status.get("is_trading_day"),
        "date": session_date,
        "reason": status.get("reason"),
        "holiday_name": status.get("holiday_name"),
        "previous_trading_day": status.get("previous_trading_day"),
        "next_trading_day": next_trading_day,
        "latest_daily_date": latest_daily_date,
        "daily_price_release": daily_price_release,
        "summary": summary,
        "source": "app.market.calendar_status",
    }


def recent_volatility_evidence(chart: dict[str, Any], *, lookback: int = 5) -> dict[str, Any]:
    raw_points = chart.get("points") if isinstance(chart, dict) else []
    points = normalize_technical_points([point for point in raw_points if isinstance(point, dict)])
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
        change_pct = pct_change(previous.get("close"), current.get("close"))
        returns.append(
            {
                "time": current.get("time"),
                "close": round_price(current.get("close")),
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
            }
        )

    recent_window = recent[1:] if len(recent) > 1 else recent
    highs = [finite_number(point.get("high")) for point in recent_window]
    lows = [finite_number(point.get("low")) for point in recent_window]
    highs = [value for value in highs if value is not None]
    lows = [value for value in lows if value is not None]
    latest_close = finite_number(recent_window[-1].get("close")) if recent_window else None
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
        summary_parts.append(f"最大單日漲跌約 {format_pct(max_abs_change)}")
    if range_pct is not None:
        summary_parts.append(f"區間振幅約 {format_pct(range_pct)}")
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


def indicator_quality_evidence(technical_reports: dict[str, Any]) -> dict[str, Any]:
    daily_report = technical_reports.get("daily") if isinstance(technical_reports, dict) else {}
    indicator = indicator_from_report(daily_report)
    macd = indicator.get("macd") if isinstance(indicator.get("macd"), dict) else {}
    macd_value = finite_number(macd.get("macd"))
    signal_value = finite_number(macd.get("signal"))
    histogram = finite_number(macd.get("histogram"))
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


def fundamental_evidence(
    *,
    latest_revenue: Any,
    latest_financial: Any,
) -> dict[str, Any]:
    revenue_yoy = finite_number(source_value(latest_revenue, "year_over_year_pct"))
    revenue_mom = finite_number(source_value(latest_revenue, "month_over_month_pct"))
    cumulative_yoy = finite_number(source_value(latest_revenue, "cumulative_year_over_year_pct"))
    revenue_period = json_value(source_value(latest_revenue, "period"))
    revenue_summary = None
    if latest_revenue is not None:
        parts = [f"{revenue_period} 營收"] if revenue_period else ["最新營收"]
        if revenue_yoy is not None:
            parts.append(f"年增 {format_pct(revenue_yoy)}")
        if revenue_mom is not None:
            parts.append(f"月增 {format_pct(revenue_mom)}")
        if cumulative_yoy is not None:
            parts.append(f"累計年增 {format_pct(cumulative_yoy)}")
        revenue_summary = "，".join(parts) + "。"

    financial_semantics = source_reported_financial_semantics(latest_financial)
    eps = finite_number(financial_semantics["raw_eps"])
    roe = finite_number(source_value(latest_financial, "roe"))
    financial_period = latest_financial_period(latest_financial)
    financial_summary = None
    if latest_financial is not None:
        parts = [f"{financial_period} 財報"] if financial_period else ["最新財報"]
        parts.append(
            financial_period_scope_label(
                financial_semantics["period_scope"],
                financial_semantics["months_covered"],
            )
        )
        if eps is not None:
            parts.append(f"來源揭露 EPS {format_number(eps)}")
        if roe is not None:
            parts.append(f"來源衍生 ROE {format_pct(roe)}")
        parts.append("尚未完成股本基準正規化，不可直接推導單季、TTM 或估值")
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
            **financial_semantics,
            "tone": "neutral",
        },
    }


def decision_confidence_factors(
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
    daily_indicator = indicator_from_report(
        technical_reports.get("daily") if isinstance(technical_reports, dict) else {}
    )
    values = indicator_level_values(daily_indicator)
    close = values.get("close")
    ma20 = values.get("ma20")
    if close is not None and ma20 is not None:
        if close >= ma20:
            positives.append("收盤站上 MA20。")
        else:
            negatives.append("收盤跌破 MA20。")

    volume_ratio = None
    volume_ma = daily_indicator.get("volume_ma") if isinstance(daily_indicator.get("volume_ma"), dict) else {}
    volume = finite_number(daily_indicator.get("volume"))
    volume_ma20 = finite_number(volume_ma.get("volume_ma20"))
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


def build_stock_decision_evidence(
    *,
    latest_daily: Any,
    chart: dict[str, Any],
    latest_revenue: Any,
    latest_financial: Any,
    technical_reports: dict[str, Any],
    calendar_status: dict[str, Any] | None = None,
    missing: list[str],
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    market_session = market_session_evidence(
        technical_reports=technical_reports,
        latest_daily=latest_daily,
        calendar_status=calendar_status,
    )
    volatility = recent_volatility_evidence(chart)
    indicator_quality = indicator_quality_evidence(technical_reports)
    fundamentals = fundamental_evidence(
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
    )
    confidence_factors = decision_confidence_factors(
        technical_reports=technical_reports,
        volatility=volatility,
        indicator_quality=indicator_quality,
        fundamentals=fundamentals,
        missing=missing,
    )
    return {
        "kind": "stock_decision_evidence_v1",
        "data_quality": decision_data_quality(
            latest_daily=latest_daily,
            source_refs=source_refs,
        ),
        "market_session": market_session,
        "recent_volatility": volatility,
        "indicator_quality": indicator_quality,
        "fundamentals": fundamentals,
        "confidence_factors": confidence_factors,
    }
