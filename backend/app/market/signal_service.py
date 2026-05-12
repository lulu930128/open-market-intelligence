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

    ma5 = _num(ma.get("ma5"))
    ma20 = _num(ma.get("ma20"))
    ma60 = _num(ma.get("ma60"))

    volume_ma5 = _num(volume_ma.get("volume_ma5"))
    volume_ma20 = _num(volume_ma.get("volume_ma20"))

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