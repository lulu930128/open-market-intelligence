from sqlalchemy.orm import Session

from app.market.indicator_service import calculate_daily_indicators


def _to_dict(value) -> dict:
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if hasattr(value, "model_dump"):
        return value.model_dump()

    result = {}

    for key in [
        "time",
        "close",
        "volume",
        "change",
        "change_pct",
        "ma",
        "volume_ma",
        "ema",
        "macd",
        "rsi",
        "atr",
        "adx",
        "roc",
        "mfi",
        "donchian",
    ]:
        result[key] = getattr(value, key, None)

    return result


def _num(value) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _add_signal(
    signals: list[dict],
    key: str,
    label: str,
    direction: str,
    level: str,
    message: str,
    value: float | None = None,
    reference: float | None = None,
) -> None:
    signals.append(
        {
            "key": key,
            "label": label,
            "direction": direction,
            "level": level,
            "message": message,
            "value": value,
            "reference": reference,
        }
    )


def _score_to_status(score: int) -> str:
    if score >= 3:
        return "strong_bullish"

    if score >= 1:
        return "bullish"

    if score <= -3:
        return "strong_bearish"

    if score <= -1:
        return "bearish"

    return "neutral"


def calculate_latest_stock_signals(
    db: Session,
    stock_id: str,
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    limit: int = 100,
    volume_ratio_threshold: float = 1.5,
) -> dict:
    """
    Calculate latest rule-based signals for a stock.

    This is intentionally rule-based and explainable.
    It does not make buy/sell decisions; it only emits observable conditions.
    """
    points = calculate_daily_indicators(
        db=db,
        stock_id=stock_id,
        limit=limit,
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
    )

    normalized_points = [_to_dict(point) for point in points]

    if not normalized_points:
        return {
            "stock_id": stock_id,
            "time": None,
            "close": None,
            "volume": None,
            "change_pct": None,
            "score": 0,
            "status": "no_data",
            "signals": [],
        }

    latest = normalized_points[-1]
    previous = normalized_points[-2] if len(normalized_points) >= 2 else None

    close = _num(latest.get("close"))
    volume = _num(latest.get("volume"))
    change_pct = _num(latest.get("change_pct"))

    ma = latest.get("ma") or {}
    volume_ma = latest.get("volume_ma") or {}
    ema = latest.get("ema") or {}
    macd = latest.get("macd") or {}
    rsi = latest.get("rsi") or {}
    adx = latest.get("adx") or {}
    roc = latest.get("roc") or {}
    mfi = latest.get("mfi") or {}

    ma5 = _num(ma.get("ma5"))
    ma20 = _num(ma.get("ma20"))
    ma60 = _num(ma.get("ma60"))

    volume_ma5 = _num(volume_ma.get("volume_ma5"))
    volume_ma20 = _num(volume_ma.get("volume_ma20"))
    ema12 = _num(ema.get("ema12"))
    ema26 = _num(ema.get("ema26"))
    macd_value = _num(macd.get("macd"))
    macd_signal = _num(macd.get("signal"))
    macd_histogram = _num(macd.get("histogram"))
    rsi14 = _num(rsi.get("rsi14"))
    plus_di14 = _num(adx.get("plus_di14"))
    minus_di14 = _num(adx.get("minus_di14"))
    adx14 = _num(adx.get("adx14"))
    roc12 = _num(roc.get("roc12"))
    mfi14 = _num(mfi.get("mfi14"))

    signals: list[dict] = []
    score = 0

    if close is None:
        return {
            "stock_id": stock_id,
            "time": latest.get("time"),
            "close": None,
            "volume": int(volume) if volume is not None else None,
            "change_pct": change_pct,
            "score": 0,
            "status": "no_data",
            "signals": [],
        }

    # Price direction
    if change_pct is not None:
        if change_pct > 0:
            score += 1
            _add_signal(
                signals,
                key="price_up",
                label="上漲",
                direction="bullish",
                level="info",
                message="最新交易日收盤價上漲。",
                value=change_pct,
                reference=0,
            )
        elif change_pct < 0:
            score -= 1
            _add_signal(
                signals,
                key="price_down",
                label="下跌",
                direction="bearish",
                level="info",
                message="最新交易日收盤價下跌。",
                value=change_pct,
                reference=0,
            )

    # MA20 position
    if ma20 is not None:
        if close > ma20:
            score += 1
            _add_signal(
                signals,
                key="above_ma20",
                label="站在 MA20 之上",
                direction="bullish",
                level="info",
                message="收盤價高於 MA20，短中期價格位置偏強。",
                value=close,
                reference=ma20,
            )
        elif close < ma20:
            score -= 1
            _add_signal(
                signals,
                key="below_ma20",
                label="跌破 MA20",
                direction="bearish",
                level="warning",
                message="收盤價低於 MA20，短中期價格位置偏弱。",
                value=close,
                reference=ma20,
            )

    # MA5 vs MA20
    if ma5 is not None and ma20 is not None:
        if ma5 > ma20:
            score += 1
            _add_signal(
                signals,
                key="ma5_above_ma20",
                label="MA5 高於 MA20",
                direction="bullish",
                level="info",
                message="短期均線高於中期均線，短線動能偏強。",
                value=ma5,
                reference=ma20,
            )
        elif ma5 < ma20:
            score -= 1
            _add_signal(
                signals,
                key="ma5_below_ma20",
                label="MA5 低於 MA20",
                direction="bearish",
                level="info",
                message="短期均線低於中期均線，短線動能偏弱。",
                value=ma5,
                reference=ma20,
            )

    # MA20 vs MA60
    if ma20 is not None and ma60 is not None:
        if ma20 > ma60:
            score += 1
            _add_signal(
                signals,
                key="ma20_above_ma60",
                label="MA20 高於 MA60",
                direction="bullish",
                level="info",
                message="中期均線高於長期均線，中期趨勢偏強。",
                value=ma20,
                reference=ma60,
            )
        elif ma20 < ma60:
            score -= 1
            _add_signal(
                signals,
                key="ma20_below_ma60",
                label="MA20 低於 MA60",
                direction="bearish",
                level="info",
                message="中期均線低於長期均線，中期趨勢偏弱。",
                value=ma20,
                reference=ma60,
            )

    # Cross MA20
    if previous is not None:
        prev_close = _num(previous.get("close"))
        prev_ma = previous.get("ma") or {}
        prev_ma20 = _num(prev_ma.get("ma20"))

        if prev_close is not None and prev_ma20 is not None and ma20 is not None:
            if prev_close <= prev_ma20 and close > ma20:
                score += 2
                _add_signal(
                    signals,
                    key="cross_above_ma20",
                    label="重新站上 MA20",
                    direction="bullish",
                    level="strong",
                    message="收盤價由 MA20 下方重新站上 MA20。",
                    value=close,
                    reference=ma20,
                )
            elif prev_close >= prev_ma20 and close < ma20:
                score -= 2
                _add_signal(
                    signals,
                    key="cross_below_ma20",
                    label="跌破 MA20",
                    direction="bearish",
                    level="strong",
                    message="收盤價由 MA20 上方跌破 MA20。",
                    value=close,
                    reference=ma20,
                )

    # EMA and MACD momentum
    if ema12 is not None and ema26 is not None:
        if ema12 > ema26:
            score += 1
            _add_signal(
                signals,
                key="ema_fast_above_slow",
                label="EMA 快線高於慢線",
                direction="bullish",
                level="info",
                message="EMA12 高於 EMA26，短中期動能偏多。",
                value=ema12,
                reference=ema26,
            )
        elif ema12 < ema26:
            score -= 1
            _add_signal(
                signals,
                key="ema_fast_below_slow",
                label="EMA 快線低於慢線",
                direction="bearish",
                level="info",
                message="EMA12 低於 EMA26，短中期動能偏空。",
                value=ema12,
                reference=ema26,
            )

    if previous is not None:
        prev_ema = previous.get("ema") or {}
        prev_ema12 = _num(prev_ema.get("ema12"))
        prev_ema26 = _num(prev_ema.get("ema26"))

        if (
            prev_ema12 is not None
            and prev_ema26 is not None
            and ema12 is not None
            and ema26 is not None
        ):
            if prev_ema12 <= prev_ema26 and ema12 > ema26:
                score += 2
                _add_signal(
                    signals,
                    key="ema_bullish_cross",
                    label="EMA 黃金交叉",
                    direction="bullish",
                    level="strong",
                    message="EMA12 由下往上穿越 EMA26。",
                    value=ema12,
                    reference=ema26,
                )
            elif prev_ema12 >= prev_ema26 and ema12 < ema26:
                score -= 2
                _add_signal(
                    signals,
                    key="ema_bearish_cross",
                    label="EMA 死亡交叉",
                    direction="bearish",
                    level="strong",
                    message="EMA12 由上往下跌破 EMA26。",
                    value=ema12,
                    reference=ema26,
                )

    if macd_value is not None and macd_signal is not None:
        if macd_value > macd_signal and (macd_histogram or 0) > 0:
            score += 1
            _add_signal(
                signals,
                key="macd_positive",
                label="MACD 偏多",
                direction="bullish",
                level="info",
                message="MACD 高於 signal，動能偏多。",
                value=macd_histogram,
                reference=0,
            )
        elif macd_value < macd_signal and (macd_histogram or 0) < 0:
            score -= 1
            _add_signal(
                signals,
                key="macd_negative",
                label="MACD 偏空",
                direction="bearish",
                level="info",
                message="MACD 低於 signal，動能偏空。",
                value=macd_histogram,
                reference=0,
            )

    # Trend strength and breakout
    if adx14 is not None and plus_di14 is not None and minus_di14 is not None:
        if adx14 >= 25 and plus_di14 > minus_di14:
            score += 2
            _add_signal(
                signals,
                key="adx_bull_trend",
                label="ADX 多方趨勢",
                direction="bullish",
                level="strong",
                message="ADX 高於 25 且 +DI 高於 -DI，趨勢強度偏多。",
                value=adx14,
                reference=25,
            )
        elif adx14 >= 25 and minus_di14 > plus_di14:
            score -= 2
            _add_signal(
                signals,
                key="adx_bear_trend",
                label="ADX 空方趨勢",
                direction="bearish",
                level="strong",
                message="ADX 高於 25 且 -DI 高於 +DI，趨勢強度偏空。",
                value=adx14,
                reference=25,
            )

    if previous is not None:
        prev_donchian = previous.get("donchian") or {}
        prev_upper20 = _num(prev_donchian.get("upper20"))
        prev_lower20 = _num(prev_donchian.get("lower20"))

        if prev_upper20 is not None and close > prev_upper20:
            score += 2
            _add_signal(
                signals,
                key="donchian_breakout",
                label="突破 20 日高",
                direction="bullish",
                level="strong",
                message="收盤價突破前一日 Donchian 20 日上緣。",
                value=close,
                reference=prev_upper20,
            )
        elif prev_lower20 is not None and close < prev_lower20:
            score -= 2
            _add_signal(
                signals,
                key="donchian_breakdown",
                label="跌破 20 日低",
                direction="bearish",
                level="strong",
                message="收盤價跌破前一日 Donchian 20 日下緣。",
                value=close,
                reference=prev_lower20,
            )

    # Oscillator and flow confirmation
    if rsi14 is not None:
        if 50 <= rsi14 <= 70:
            score += 1
            _add_signal(
                signals,
                key="rsi_bull_zone",
                label="RSI 多方區",
                direction="bullish",
                level="info",
                message="RSI 位於 50 至 70，動能健康偏多。",
                value=rsi14,
                reference=50,
            )
        elif rsi14 < 40:
            score -= 1
            _add_signal(
                signals,
                key="rsi_weak",
                label="RSI 偏弱",
                direction="bearish",
                level="info",
                message="RSI 低於 40，短線動能偏弱。",
                value=rsi14,
                reference=40,
            )
        elif rsi14 >= 80:
            _add_signal(
                signals,
                key="rsi_overheated",
                label="RSI 過熱",
                direction="neutral",
                level="warning",
                message="RSI 高於 80，留意短線過熱。",
                value=rsi14,
                reference=80,
            )

    if mfi14 is not None:
        if 50 <= mfi14 <= 80:
            score += 1
            _add_signal(
                signals,
                key="mfi_inflow",
                label="MFI 資金流入",
                direction="bullish",
                level="info",
                message="MFI 位於多方區，量價資金流偏正向。",
                value=mfi14,
                reference=50,
            )
        elif mfi14 < 35:
            score -= 1
            _add_signal(
                signals,
                key="mfi_outflow",
                label="MFI 偏弱",
                direction="bearish",
                level="info",
                message="MFI 低於 35，量價資金流偏弱。",
                value=mfi14,
                reference=35,
            )

    if roc12 is not None:
        if roc12 > 0:
            score += 1
            _add_signal(
                signals,
                key="roc_positive",
                label="ROC 正動能",
                direction="bullish",
                level="info",
                message="12 日 ROC 為正，價格動能偏多。",
                value=roc12,
                reference=0,
            )
        elif roc12 < 0:
            score -= 1
            _add_signal(
                signals,
                key="roc_negative",
                label="ROC 負動能",
                direction="bearish",
                level="info",
                message="12 日 ROC 為負，價格動能偏空。",
                value=roc12,
                reference=0,
            )

    # Volume expansion
    if volume is not None and volume_ma20 is not None and volume_ma20 > 0:
        volume_ratio = volume / volume_ma20

        if volume_ratio >= volume_ratio_threshold:
            if change_pct is not None and change_pct > 0:
                score += 2
                _add_signal(
                    signals,
                    key="volume_price_up",
                    label="量增價漲",
                    direction="bullish",
                    level="strong",
                    message="成交量明顯高於量均線，且價格上漲。",
                    value=volume_ratio,
                    reference=volume_ratio_threshold,
                )
            elif change_pct is not None and change_pct < 0:
                score -= 2
                _add_signal(
                    signals,
                    key="volume_price_down",
                    label="量增價跌",
                    direction="bearish",
                    level="strong",
                    message="成交量明顯高於量均線，且價格下跌。",
                    value=volume_ratio,
                    reference=volume_ratio_threshold,
                )
            else:
                _add_signal(
                    signals,
                    key="volume_expansion",
                    label="量能放大",
                    direction="neutral",
                    level="info",
                    message="成交量明顯高於量均線。",
                    value=volume_ratio,
                    reference=volume_ratio_threshold,
                )

    # Short-term volume reference
    if volume is not None and volume_ma5 is not None and volume_ma5 > 0:
        volume_ratio_5 = volume / volume_ma5

        if volume_ratio_5 >= volume_ratio_threshold:
            _add_signal(
                signals,
                key="volume_above_ma5",
                label="成交量高於 5 日均量",
                direction="neutral",
                level="info",
                message="成交量高於 5 日均量，短線關注度提高。",
                value=volume_ratio_5,
                reference=volume_ratio_threshold,
            )

    return {
        "stock_id": stock_id,
        "time": latest.get("time"),
        "close": close,
        "volume": int(volume) if volume is not None else None,
        "change_pct": change_pct,
        "score": score,
        "status": _score_to_status(score),
        "signals": signals,
    }
