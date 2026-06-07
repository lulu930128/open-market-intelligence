from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market import indicator_service
from app.market import service as market_service
from app.market.intraday import get_intraday_trend


TAIPEI_TZ = timezone(timedelta(hours=8))
SESSION_START_MINUTES = 9 * 60
OPENING_OBSERVATION_MINUTES = 5
OPENING_OBSERVATION_MIN_POINTS = 5


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
    return _fmt_number(value, digits).rstrip("0").rstrip(".")


def _fmt_pct(value: Any) -> str:
    if not _finite(value):
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _fmt_lots(value: Any) -> str:
    if not _finite(value):
        return "-"
    return f"{round(value / 1000):,}"


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


def _daily_indicator(db: Session, stock_id: str) -> dict[str, Any] | None:
    return indicator_service.calculate_latest_daily_indicator(
        db=db,
        stock_id=stock_id,
        ma_windows="5,20,60",
        volume_ma_windows="5,20",
    )


def _daily_context(db: Session, stock_id: str) -> dict[str, Any]:
    latest_indicator = _daily_indicator(db=db, stock_id=stock_id)
    latest_institutional = market_service.get_latest_stock_institutional_trade(db, stock_id)
    latest_margin = market_service.get_latest_stock_margin_trade(db, stock_id)
    return {
        "indicator": latest_indicator,
        "institutional": latest_institutional,
        "margin": latest_margin,
    }


def _intraday_minutes(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)
    local = parsed.astimezone(TAIPEI_TZ)
    return local.hour * 60 + local.minute + local.second / 60


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
    if timeframe == "today" and include_intraday:
        refs.append({"type": "external_or_cache", "name": "taiwan_intraday_trend"})
    return refs


def _build_today_report(
    *,
    db: Session,
    stock_id: str,
    include_intraday: bool,
) -> dict[str, Any]:
    warnings: list[str] = []
    missing: list[str] = []
    rows: list[dict[str, Any]] = []
    badges: list[dict[str, str]] = []
    daily = _daily_context(db=db, stock_id=stock_id)
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

    if include_intraday:
        intraday = get_intraday_trend(db=db, stock_id=stock_id)
    else:
        missing.append("intraday_trend")
        warnings.append("Intraday report was requested without live intraday access.")

    points = intraday.get("points") or []
    latest_point = points[-1] if points else None
    reference_close = intraday.get("previous_close") or previous_close

    if latest_point is None:
        if include_intraday:
            missing.append("intraday_trend.points")
        rows.extend(
            [
                _row(
                    key="data_status",
                    label="資料狀態",
                    description="尚未取得今日第一筆成交或即時快照",
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
        badges.append(_badge("等待盤中", "neutral"))
        return {
            "kind": "tw_stock_technical_report",
            "stock_id": stock_id,
            "timeframe": "today",
            "phase": "waiting_intraday",
            "confidence": "low",
            "generated_at": _now(),
            "title": "等待盤中資料",
            "summary": "尚未取得今日第一筆成交，日線資料暫不作盤中判斷",
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

    stats = _intraday_stats(points)
    latest_price = latest_point.get("price")
    latest_minutes = _intraday_minutes(latest_point.get("time"))
    minutes_from_open = latest_minutes - SESSION_START_MINUTES if _finite(latest_minutes) else None
    point_count = len(points)
    opening_phase = (
        minutes_from_open is None
        or minutes_from_open < OPENING_OBSERVATION_MINUTES
        or point_count < OPENING_OBSERVATION_MIN_POINTS
    )
    phase = "opening" if opening_phase else "intraday"
    confidence = "low" if opening_phase else ("high" if point_count >= 20 else "medium")
    open_price = stats["open"]
    high_price = stats["high"]
    low_price = stats["low"]
    current_volume = stats["volume"] or latest_point.get("volume")
    change_pct = _pct_change(latest_price, reference_close)
    change = latest_price - reference_close if _finite(latest_price) and _finite(reference_close) else None
    price_vs_open_pct = _pct_change(latest_price, open_price)
    opening_gap_pct = _pct_change(open_price, reference_close)
    intraday_range_pct = (
        _pct_change(high_price, low_price)
        if _finite(high_price) and _finite(low_price) and low_price != 0
        else None
    )
    volume_ma20 = volume_ma.get("volume_ma20")
    volume_vs_daily_average_pct = (
        _safe_ratio(current_volume, volume_ma20) * 100
        if _safe_ratio(current_volume, volume_ma20) is not None
        else None
    )
    ma20 = ma.get("ma20")
    price_vs_ma20 = _pct_change(latest_price, ma20)
    rsi14 = rsi.get("rsi14")
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
                key="live_price",
                label="即時價格",
                description=f"相對昨收 {_fmt_pct(change_pct)}，{point_count} 筆盤中資料",
                value=latest_price,
                display_value=_fmt_price(latest_price),
                direction=change_pct,
                basis="latest intraday price vs previous close",
                source=str(intraday.get("source") or "intraday"),
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
                description=f"目前累計量，20日均量占比 {_fmt_pct(volume_vs_daily_average_pct)}",
                value=current_volume,
                display_value="觀察中" if current_volume is None else f"{_fmt_lots(current_volume)}張",
                direction=None,
                tone="neutral",
                basis="current intraday cumulative volume; no same-time baseline yet",
                source=str(intraday.get("source") or "intraday"),
            ),
            _row(
                key="daily_background",
                label="日線背景",
                description=f"RSI {_fmt_number(rsi14, 2)}，MACD H {_fmt_number(macd_histogram, 2)}，MA20 {_fmt_price(ma20)}",
                value=price_vs_ma20,
                display_value=_fmt_pct(price_vs_ma20),
                direction=price_vs_ma20,
                tone="warning" if _finite(rsi14) and rsi14 >= 80 else _tone(price_vs_ma20),
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
    if _finite(rsi14) and rsi14 >= 80:
        badges.append(_badge("日線 RSI 過熱", "warning"))

    title = (
        _title_from_score(score, positive="開盤偏強", neutral="開盤觀察", negative="開盤偏弱")
        if opening_phase
        else _title_from_score(score, positive="盤中偏多", neutral="盤中觀察", negative="盤中偏弱")
    )
    summary_parts = [
        f"{point_count} 筆盤中資料",
        "現價高於昨收" if _finite(change_pct) and change_pct >= 0 else "現價低於昨收" if _finite(change_pct) else "漲跌資料不足",
        "開高" if _finite(opening_gap_pct) and opening_gap_pct >= 0 else "開低" if _finite(opening_gap_pct) else "開盤資料不足",
        "日線指標僅作背景" if opening_phase else "盤中資料已進入觀察期",
    ]

    return {
        "kind": "tw_stock_technical_report",
        "stock_id": stock_id,
        "timeframe": "today",
        "phase": phase,
        "confidence": confidence,
        "generated_at": _now(),
        "title": title,
        "summary": "，".join(summary_parts),
        "score": score,
        "value": change_pct,
        "value_label": "vs 昨收",
        "rows": rows,
        "badges": badges,
        "data": {
            "intraday": {
                "source": intraday.get("source"),
                "point_count": point_count,
                "previous_close": reference_close,
                "latest_point": latest_point,
                "stats": stats,
                "change": change,
                "change_pct": change_pct,
                "opening_gap_pct": opening_gap_pct,
                "price_vs_open_pct": price_vs_open_pct,
                "volume_vs_daily_average_pct": volume_vs_daily_average_pct,
            },
            "daily_background": indicator,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": _technical_source_refs(timeframe="today", include_intraday=include_intraday),
    }


def _build_daily_report(*, db: Session, stock_id: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    badges: list[dict[str, str]] = []
    warnings: list[str] = []
    missing: list[str] = []
    daily = _daily_context(db=db, stock_id=stock_id)
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
    ma5 = ma.get("ma5")
    ma20 = ma.get("ma20")
    ma60 = ma.get("ma60")
    price_vs_ma20 = _pct_change(close, ma20)
    volume_ratio = _safe_ratio(volume, volume_ma.get("volume_ma20"))
    volume_ratio_pct = (volume_ratio - 1) * 100 if volume_ratio is not None else None
    macd_histogram = macd.get("histogram")
    rsi14 = rsi.get("rsi14")
    adx14 = adx.get("adx14")
    plus_di14 = adx.get("plus_di14")
    minus_di14 = adx.get("minus_di14")
    atr14 = atr.get("atr14")
    atr_pct = _safe_ratio(atr14, close)
    atr_pct = atr_pct * 100 if atr_pct is not None else None
    donchian_position = None
    if _finite(donchian.get("upper20")) and _finite(donchian.get("lower20")) and donchian["upper20"] != donchian["lower20"]:
        donchian_position = (close - donchian["lower20"]) / (donchian["upper20"] - donchian["lower20"]) * 100
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
        if 50 <= rsi14 < 80:
            score += 1
        elif rsi14 < 40:
            score -= 1
    if _finite(adx14) and adx14 >= 25 and _finite(plus_di14) and _finite(minus_di14):
        score += 1 if plus_di14 >= minus_di14 else -1
    if _finite(institutional_net):
        score += 1 if institutional_net > 0 else -1

    rows.extend(
        [
            _row(
                key="trend_structure",
                label="趨勢結構",
                description=f"MA5/20/60 {_fmt_price(ma5)} / {_fmt_price(ma20)} / {_fmt_price(ma60)}，ADX {_fmt_number(adx14, 2)}",
                value=price_vs_ma20,
                display_value=_fmt_pct(price_vs_ma20),
                direction=price_vs_ma20,
                basis="close vs MA20 and moving average alignment",
                source="market_daily_price",
            ),
            _row(
                key="momentum",
                label="動能指標",
                description=f"RSI {_fmt_number(rsi14, 2)}，MACD H {_fmt_number(macd_histogram, 2)}，ROC12 {_fmt_pct(roc.get('roc12'))}",
                value=rsi14,
                display_value=_fmt_number(rsi14, 2),
                direction=macd_histogram,
                tone="warning" if _finite(rsi14) and rsi14 >= 80 else _tone(macd_histogram),
                basis="daily RSI, MACD histogram, and ROC",
                source="market_daily_price",
            ),
            _row(
                key="volume_flow",
                label="量價資金",
                description=f"量能 {_fmt_pct(volume_ratio_pct)} vs 20日均量，MFI {_fmt_number(mfi.get('mfi14'), 2)}",
                value=volume_ratio_pct,
                display_value=_fmt_pct(volume_ratio_pct),
                direction=volume_ratio_pct,
                tone="warning" if _finite(volume_ratio) and volume_ratio >= 1.5 else "neutral",
                basis="daily volume vs 20-day average volume",
                source="market_daily_price",
            ),
            _row(
                key="volatility_risk",
                label="波動風險",
                description=f"ATR {_fmt_pct(atr_pct)}，Donchian 位置 {_fmt_pct(donchian_position)}",
                value=atr_pct,
                display_value=_fmt_pct(atr_pct),
                direction=1 if _finite(atr_pct) and atr_pct > 5 else 0,
                tone="warning" if _finite(atr_pct) and atr_pct > 5 else "neutral",
                basis="daily ATR and 20-day Donchian range position",
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
    if _finite(rsi14) and rsi14 >= 80:
        badges.append(_badge("RSI 過熱", "warning"))
    if _finite(volume_ratio) and volume_ratio >= 1.5:
        badges.append(_badge("放量", "warning"))

    summary_parts = [
        "站上 MA20" if _finite(price_vs_ma20) and price_vs_ma20 >= 0 else "跌破 MA20" if _finite(price_vs_ma20) else "價格結構不足",
        "MACD 偏多" if _finite(macd_histogram) and macd_histogram >= 0 else "MACD 偏弱" if _finite(macd_histogram) else "動能資料不足",
        "放量" if _finite(volume_ratio) and volume_ratio >= 1.5 else "量能一般" if _finite(volume_ratio) else "量能資料不足",
    ]
    if indicator.get("time") is None:
        missing.append("market_daily_price.time")

    return {
        "kind": "tw_stock_technical_report",
        "stock_id": stock_id,
        "timeframe": "daily",
        "phase": "daily",
        "confidence": "high" if not missing else "medium",
        "generated_at": _now(),
        "title": _title_from_score(score, positive="短線偏多", neutral="短線整理", negative="短線偏弱"),
        "summary": "，".join(summary_parts),
        "score": score,
        "value": price_vs_ma20,
        "value_label": "vs MA20",
        "rows": rows,
        "badges": badges,
        "data": {
            "daily_indicator": indicator,
            "market": _stock_market(db=db, stock_id=stock_id),
            "change_pct": change_pct,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": warnings,
        "source_refs": _technical_source_refs(timeframe="daily", include_intraday=False),
    }


def build_stock_technical_report(
    *,
    db: Session,
    stock_id: str,
    timeframe: str = "daily",
    include_intraday: bool = True,
) -> dict[str, Any]:
    normalized_timeframe = timeframe.strip().lower()
    normalized_stock_id = stock_id.strip()

    if normalized_timeframe == "today":
        return _build_today_report(
            db=db,
            stock_id=normalized_stock_id,
            include_intraday=include_intraday,
        )

    if normalized_timeframe == "daily":
        return _build_daily_report(db=db, stock_id=normalized_stock_id)

    raise ValueError("timeframe must be one of: today, daily.")
