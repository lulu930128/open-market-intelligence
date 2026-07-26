from sqlalchemy.orm import Session

from app.market.indicator_service import calculate_daily_indicators
from app.market.technical_parameters import get_technical_analysis_parameters
from app.market.technical_structure import build_price_moving_average_signals


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
        "bollinger",
        "kd",
        "support_resistance",
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


def _indicator_value(values: dict, key: str | None, legacy_key: str | None = None) -> float | None:
    if not isinstance(values, dict):
        return None
    if key and values.get(key) is not None:
        return _num(values.get(key))
    if legacy_key and values.get(legacy_key) is not None:
        return _num(values.get(legacy_key))
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


def _safe_ratio(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference == 0:
        return None

    return value / reference


def _near_level_pct(value: float, reference: float, threshold_pct: float) -> bool:
    if reference == 0:
        return False

    return abs(value - reference) / reference * 100 <= threshold_pct


def _indicator_snapshot(point: dict) -> dict[str, dict[str, float | None]]:
    snapshot: dict[str, dict[str, float | None]] = {}

    for key in [
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
        "bollinger",
        "kd",
        "support_resistance",
    ]:
        raw_values = point.get(key) or {}
        if not isinstance(raw_values, dict):
            snapshot[key] = {}
            continue

        snapshot[key] = {
            str(name): _num(value)
            for name, value in raw_values.items()
        }

    return snapshot


def calculate_latest_stock_signals(
    db: Session,
    stock_id: str,
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    limit: int = 100,
    volume_ratio_threshold: float | None = None,
) -> dict:
    """
    Calculate latest rule-based signals for a stock.

    This is intentionally rule-based and explainable.
    It does not make buy/sell decisions; it only emits observable conditions.
    """
    technical_parameters = get_technical_analysis_parameters(
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
        volume_ratio_threshold=volume_ratio_threshold,
    )
    volume_ratio_threshold = technical_parameters.volume_ratio_threshold
    points = calculate_daily_indicators(
        db=db,
        stock_id=stock_id,
        limit=limit,
        ma_windows=technical_parameters.ma_windows_text,
        volume_ma_windows=technical_parameters.volume_ma_windows_text,
        parameters=technical_parameters,
    )

    normalized_points = [_to_dict(point) for point in points]

    if not normalized_points:
        return {
            "stock_id": stock_id,
            "time": None,
            "close": None,
            "volume": None,
            "change": None,
            "change_pct": None,
            "score": 0,
            "status": "no_data",
            "signals": [],
            "indicator_snapshot": {},
        }

    latest = normalized_points[-1]
    previous = normalized_points[-2] if len(normalized_points) >= 2 else None

    close = _num(latest.get("close"))
    volume = _num(latest.get("volume"))
    change = _num(latest.get("change"))
    change_pct = _num(latest.get("change_pct"))

    ma = latest.get("ma") or {}
    volume_ma = latest.get("volume_ma") or {}
    ema = latest.get("ema") or {}
    macd = latest.get("macd") or {}
    rsi = latest.get("rsi") or {}
    adx = latest.get("adx") or {}
    roc = latest.get("roc") or {}
    mfi = latest.get("mfi") or {}
    atr = latest.get("atr") or {}
    donchian = latest.get("donchian") or {}
    bollinger = latest.get("bollinger") or {}
    kd = latest.get("kd") or {}
    support_resistance = latest.get("support_resistance") or {}

    ma5 = _indicator_value(ma, technical_parameters.ma_short_key, "ma5")
    ma20 = _indicator_value(ma, technical_parameters.ma_medium_key, "ma20")
    ma60 = _indicator_value(ma, technical_parameters.ma_long_key, "ma60")

    volume_ma5 = _indicator_value(volume_ma, technical_parameters.volume_ma_short_key, "volume_ma5")
    volume_ma20 = _indicator_value(volume_ma, technical_parameters.volume_ma_medium_key, "volume_ma20")
    ema12 = _indicator_value(ema, technical_parameters.ema_fast_key, "ema12")
    ema26 = _indicator_value(ema, technical_parameters.ema_slow_key, "ema26")
    macd_value = _num(macd.get("macd"))
    macd_signal = _num(macd.get("signal"))
    macd_histogram = _num(macd.get("histogram"))
    rsi14 = _indicator_value(rsi, technical_parameters.rsi_key, "rsi14")
    plus_di14 = _indicator_value(adx, technical_parameters.plus_di_key, "plus_di14")
    minus_di14 = _indicator_value(adx, technical_parameters.minus_di_key, "minus_di14")
    adx14 = _indicator_value(adx, technical_parameters.adx_key, "adx14")
    roc12 = _indicator_value(roc, technical_parameters.roc_key, "roc12")
    mfi14 = _indicator_value(mfi, technical_parameters.mfi_key, "mfi14")
    atr14 = _indicator_value(atr, technical_parameters.atr_key, "atr14")
    donchian_upper20 = _indicator_value(donchian, technical_parameters.donchian_upper_key, "upper20")
    donchian_lower20 = _indicator_value(donchian, technical_parameters.donchian_lower_key, "lower20")
    bollinger_upper20 = _indicator_value(bollinger, technical_parameters.bollinger_upper_key, "upper20")
    bollinger_lower20 = _indicator_value(bollinger, technical_parameters.bollinger_lower_key, "lower20")
    bollinger_bandwidth20_pct = _indicator_value(
        bollinger,
        technical_parameters.bollinger_bandwidth_key,
        "bandwidth20_pct",
    )
    kd_k9 = _indicator_value(kd, technical_parameters.kd_k_key, "k9")
    kd_d9 = _indicator_value(kd, technical_parameters.kd_d_key, "d9")
    support20 = _indicator_value(support_resistance, technical_parameters.support_key, "support20")
    resistance20 = _indicator_value(support_resistance, technical_parameters.resistance_key, "resistance20")

    signals: list[dict] = []
    score = 0

    indicator_snapshot = _indicator_snapshot(latest)

    if close is None:
        return {
            "stock_id": stock_id,
            "time": latest.get("time"),
            "close": None,
            "volume": int(volume) if volume is not None else None,
            "change": change,
            "change_pct": change_pct,
            "score": 0,
            "status": "no_data",
            "signals": [],
            "indicator_snapshot": indicator_snapshot,
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

    previous_close = _num(previous.get("close")) if previous is not None else None
    previous_ma = previous.get("ma") or {} if previous is not None else {}
    previous_ma20 = _indicator_value(
        previous_ma,
        technical_parameters.ma_medium_key,
        "ma20",
    )
    previous_ma60 = _indicator_value(
        previous_ma,
        technical_parameters.ma_long_key,
        "ma60",
    )
    price_ma_signals, price_ma_score = build_price_moving_average_signals(
        price=close,
        ma5=ma5,
        ma20=ma20,
        ma60=ma60,
        previous_price=previous_close,
        previous_ma20=previous_ma20,
        previous_ma60=previous_ma60,
    )
    signals.extend(price_ma_signals)
    score += price_ma_score

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
        if adx14 >= technical_parameters.adx_trend_threshold and plus_di14 > minus_di14:
            score += 2
            _add_signal(
                signals,
                key="adx_bull_trend",
                label="ADX 多方趨勢",
                direction="bullish",
                level="strong",
                message="ADX 高於 25 且 +DI 高於 -DI，趨勢強度偏多。",
                value=adx14,
                reference=technical_parameters.adx_trend_threshold,
            )
        elif adx14 >= technical_parameters.adx_trend_threshold and minus_di14 > plus_di14:
            score -= 2
            _add_signal(
                signals,
                key="adx_bear_trend",
                label="ADX 空方趨勢",
                direction="bearish",
                level="strong",
                message="ADX 高於 25 且 -DI 高於 +DI，趨勢強度偏空。",
                value=adx14,
                reference=technical_parameters.adx_trend_threshold,
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

    # Price structure beyond Donchian: previous 20-day support/resistance
    if support20 is not None and close < support20:
        score -= 2
        _add_signal(
            signals,
            key="structure_support_break",
            label="跌破 20 日支撐",
            direction="bearish",
            level="strong",
            message="收盤價跌破前 20 日區間支撐。",
            value=close,
            reference=support20,
        )
    elif resistance20 is not None and close > resistance20:
        score += 2
        _add_signal(
            signals,
            key="structure_resistance_breakout",
            label="突破 20 日壓力",
            direction="bullish",
            level="strong",
            message="收盤價突破前 20 日區間壓力。",
            value=close,
            reference=resistance20,
        )
    elif support20 is not None and _near_level_pct(
        close,
        support20,
        threshold_pct=technical_parameters.near_level_threshold_pct,
    ):
        _add_signal(
            signals,
            key="near_support",
            label="貼近 20 日支撐",
            direction="neutral",
            level="info",
            message="收盤價貼近前 20 日支撐，適合觀察是否止穩。",
            value=close,
            reference=support20,
        )
    elif resistance20 is not None and _near_level_pct(
        close,
        resistance20,
        threshold_pct=technical_parameters.near_level_threshold_pct,
    ):
        _add_signal(
            signals,
            key="near_resistance",
            label="貼近 20 日壓力",
            direction="neutral",
            level="info",
            message="收盤價貼近前 20 日壓力，適合觀察是否放量突破。",
            value=close,
            reference=resistance20,
        )

    # Bollinger Band breakout and compression
    if bollinger_upper20 is not None and close > bollinger_upper20:
        score += 2
        _add_signal(
            signals,
            key="bollinger_breakout",
            label="突破布林上緣",
            direction="bullish",
            level="strong",
            message="收盤價突破 Bollinger 20 日上緣，動能擴張。",
            value=close,
            reference=bollinger_upper20,
        )
    elif bollinger_lower20 is not None and close < bollinger_lower20:
        score -= 2
        _add_signal(
            signals,
            key="bollinger_breakdown",
            label="跌破布林下緣",
            direction="bearish",
            level="strong",
            message="收盤價跌破 Bollinger 20 日下緣，需優先控管下行風險。",
            value=close,
            reference=bollinger_lower20,
        )
    elif (
        bollinger_bandwidth20_pct is not None
        and bollinger_bandwidth20_pct <= technical_parameters.bollinger_squeeze_bandwidth_pct
    ):
        _add_signal(
            signals,
            key="bollinger_squeeze",
            label="布林壓縮",
            direction="neutral",
            level="info",
            message="Bollinger Band 寬度偏窄，後續方向突破值得追蹤。",
            value=bollinger_bandwidth20_pct,
            reference=technical_parameters.bollinger_squeeze_bandwidth_pct,
        )

    # Oscillator and flow confirmation
    if rsi14 is not None:
        if technical_parameters.rsi_bull_min <= rsi14 <= technical_parameters.rsi_bull_max:
            score += 1
            _add_signal(
                signals,
                key="rsi_bull_zone",
                label="RSI 多方區",
                direction="bullish",
                level="info",
                message="RSI 位於 50 至 70，動能健康偏多。",
                value=rsi14,
                reference=technical_parameters.rsi_bull_min,
            )
        elif rsi14 < technical_parameters.rsi_weak_below:
            score -= 1
            _add_signal(
                signals,
                key="rsi_weak",
                label="RSI 偏弱",
                direction="bearish",
                level="info",
                message="RSI 低於 40，短線動能偏弱。",
                value=rsi14,
                reference=technical_parameters.rsi_weak_below,
            )
        elif rsi14 >= technical_parameters.rsi_overheated_at:
            _add_signal(
                signals,
                key="rsi_overheated",
                label="RSI 過熱",
                direction="neutral",
                level="warning",
                message="RSI 高於 80，留意短線過熱。",
                value=rsi14,
                reference=technical_parameters.rsi_overheated_at,
            )

    if mfi14 is not None:
        if technical_parameters.mfi_inflow_min <= mfi14 <= technical_parameters.mfi_inflow_max:
            score += 1
            _add_signal(
                signals,
                key="mfi_inflow",
                label="MFI 資金流入",
                direction="bullish",
                level="info",
                message="MFI 位於多方區，量價資金流偏正向。",
                value=mfi14,
                reference=technical_parameters.mfi_inflow_min,
            )
        elif mfi14 < technical_parameters.mfi_outflow_below:
            score -= 1
            _add_signal(
                signals,
                key="mfi_outflow",
                label="MFI 偏弱",
                direction="bearish",
                level="info",
                message="MFI 低於 35，量價資金流偏弱。",
                value=mfi14,
                reference=technical_parameters.mfi_outflow_below,
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

    if kd_k9 is not None and kd_d9 is not None:
        if previous is not None:
            prev_kd = previous.get("kd") or {}
            prev_k9 = _num(prev_kd.get("k9"))
            prev_d9 = _num(prev_kd.get("d9"))

            if prev_k9 is not None and prev_d9 is not None:
                if prev_k9 <= prev_d9 and kd_k9 > kd_d9:
                    score += 1
                    _add_signal(
                        signals,
                        key="kd_bullish_cross",
                        label="KD 黃金交叉",
                        direction="bullish",
                        level="info",
                        message="KD K 值由下往上穿越 D 值，短線動能轉強。",
                        value=kd_k9,
                        reference=kd_d9,
                    )
                elif prev_k9 >= prev_d9 and kd_k9 < kd_d9:
                    score -= 1
                    _add_signal(
                        signals,
                        key="kd_bearish_cross",
                        label="KD 死亡交叉",
                        direction="bearish",
                        level="info",
                        message="KD K 值由上往下跌破 D 值，短線動能轉弱。",
                        value=kd_k9,
                        reference=kd_d9,
                    )

        if kd_k9 >= technical_parameters.kd_overbought_k and kd_d9 >= technical_parameters.kd_overbought_d:
            _add_signal(
                signals,
                key="kd_overbought",
                label="KD 過熱",
                direction="neutral",
                level="warning",
                message="KD 位於高檔，追價需確認量價延續。",
                value=kd_k9,
                reference=technical_parameters.kd_overbought_k,
            )
        elif kd_k9 <= technical_parameters.kd_oversold_k and kd_d9 <= technical_parameters.kd_oversold_d:
            _add_signal(
                signals,
                key="kd_oversold",
                label="KD 低檔",
                direction="neutral",
                level="info",
                message="KD 位於低檔，需等待止穩或轉強確認。",
                value=kd_k9,
                reference=technical_parameters.kd_oversold_k,
            )

    atr_pct = _safe_ratio(atr14, close)
    atr_pct = atr_pct * 100 if atr_pct is not None else None
    if atr_pct is not None and atr_pct >= technical_parameters.atr_high_volatility_pct:
        _add_signal(
            signals,
            key="atr_high_volatility",
            label="ATR 高波動",
            direction="neutral",
            level="warning",
            message="ATR 佔股價比重偏高，停損距離與追價風險需放大評估。",
            value=atr_pct,
            reference=technical_parameters.atr_high_volatility_pct,
        )
    elif previous is not None and atr_pct is not None:
        prev_atr = previous.get("atr") or {}
        prev_close = _num(previous.get("close"))
        prev_atr14 = _num(prev_atr.get("atr14"))
        prev_atr_pct = _safe_ratio(prev_atr14, prev_close)
        prev_atr_pct = prev_atr_pct * 100 if prev_atr_pct is not None else None

        if (
            prev_atr_pct is not None
            and atr_pct >= prev_atr_pct * technical_parameters.atr_expansion_multiplier
            and atr_pct >= technical_parameters.atr_expansion_min_pct
        ):
            _add_signal(
                signals,
                key="atr_expanding",
                label="ATR 波動擴大",
                direction="neutral",
                level="warning",
                message="ATR 較前一交易日明顯擴大，代表波動與失敗成本上升。",
                value=atr_pct,
                reference=prev_atr_pct,
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
        "change": change,
        "change_pct": change_pct,
        "score": score,
        "status": _score_to_status(score),
        "signals": signals,
        "indicator_snapshot": indicator_snapshot,
    }
