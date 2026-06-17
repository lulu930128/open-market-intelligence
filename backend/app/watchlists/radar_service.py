from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from math import ceil
from numbers import Real

from sqlalchemy.orm import Session

from app.watchlists import ranking_service


ALLOWED_RADAR_MODES = {
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
HIGH_MOVE_PCT_THRESHOLD = 7.0
LEGACY_LIMIT_MOVE_BUCKET = "limit_move"
SURGE_MODE_BUCKETS = {
    LEGACY_LIMIT_MOVE_BUCKET,
    "limit_up_lock",
    "surge_up",
    "limit_up_move",
}
BREAKOUT_MODE_BUCKETS = {
    "breakout_high",
    "trend_reclaim",
    "compression_watch",
    "breakout",
}
VOLUME_MODE_BUCKETS = {
    "volume_up",
    "volume",
    "volume_down",
}
OVERHEAT_MODE_BUCKETS = {
    "overheated",
    "volatility_risk",
}
WEAKNESS_MODE_BUCKETS = {
    LEGACY_LIMIT_MOVE_BUCKET,
    "limit_down_liquidity",
    "selloff_risk",
    "support_break",
    "volume_down",
    "bearish_momentum",
    "limit_down_move",
    "risk",
}
ACTION_MODE_BUCKETS = {
    LEGACY_LIMIT_MOVE_BUCKET,
    "limit_up_lock",
    "surge_up",
    "limit_down_liquidity",
    "selloff_risk",
    "overheated",
    "volatility_risk",
    "support_break",
    "volume_down",
    "bearish_momentum",
    "breakout_high",
    "trend_reclaim",
    "volume_up",
    "volume",
    "compression_watch",
    "limit_up_move",
    "limit_down_move",
    "risk",
    "breakout",
}
RISK_MODE_BUCKETS = {
    LEGACY_LIMIT_MOVE_BUCKET,
    "limit_down_liquidity",
    "selloff_risk",
    "overheated",
    "volatility_risk",
    "support_break",
    "volume_down",
    "bearish_momentum",
    "limit_down_move",
    "risk",
}
MOMENTUM_MODE_BUCKETS = {
    LEGACY_LIMIT_MOVE_BUCKET,
    "limit_up_lock",
    "surge_up",
    "breakout_high",
    "trend_reclaim",
    "volume_up",
    "volume",
    "compression_watch",
    "limit_up_move",
    "breakout",
    "pullback",
    "momentum",
}

BUCKET_META = [
    {
        "key": "limit_up_lock",
        "label": "漲停鎖強",
        "description": "觸及漲停，優先確認是否續強、鎖量或過熱。",
    },
    {
        "key": "surge_up",
        "label": "急漲追價",
        "description": "單日大幅上漲但未必漲停，優先留意追價與隔日回落風險。",
    },
    {
        "key": "limit_down_liquidity",
        "label": "跌停流動性",
        "description": "觸及跌停，優先確認停損、流動性與是否打開。",
    },
    {
        "key": "selloff_risk",
        "label": "急跌風控",
        "description": "單日大幅下跌但未必跌停，優先檢查破線與降風險。",
    },
    {
        "key": "overheated",
        "label": "過熱警戒",
        "description": "RSI、KD 等指標顯示過熱，需控制追價與觀察降溫。",
    },
    {
        "key": "volatility_risk",
        "label": "波動風險",
        "description": "ATR 顯示波動放大，需拉高停損距離與追價門檻。",
    },
    {
        "key": "support_break",
        "label": "跌破支撐",
        "description": "跌破 MA20、20 日低、布林下緣或關鍵支撐，適合先檢查停損。",
    },
    {
        "key": "volume_down",
        "label": "量價轉弱",
        "description": "量增價跌，需確認賣壓是否延續。",
    },
    {
        "key": "bearish_momentum",
        "label": "動能轉弱",
        "description": "MACD、EMA、ADX、MFI 或 ROC 顯示轉弱，適合降低風險或等待止穩。",
    },
    {
        "key": "breakout_high",
        "label": "突破確認",
        "description": "突破 20 日高、區間壓力或布林上緣，適合追蹤突破延續性。",
    },
    {
        "key": "trend_reclaim",
        "label": "轉強站回",
        "description": "重新站上 MA20、EMA 黃金交叉或 ADX 多方，適合確認是否站穩。",
    },
    {
        "key": "volume_up",
        "label": "量價攻擊",
        "description": "量增價漲，需確認攻擊量能是否延續。",
    },
    {
        "key": "volume",
        "label": "量能異動",
        "description": "成交量明顯放大，需搭配價格方向判斷有效性。",
    },
    {
        "key": "compression_watch",
        "label": "壓縮待突破",
        "description": "布林帶收斂，方向尚未確認但適合追蹤突破或跌破。",
    },
    {
        "key": "pullback",
        "label": "強勢回檔",
        "description": "趨勢分數仍偏多但當日回落，適合觀察回檔位置。",
    },
    {
        "key": "momentum",
        "label": "趨勢延續",
        "description": "均線、MACD、RSI、MFI 或 ROC 顯示多方延續。",
    },
    {
        "key": "watch",
        "label": "一般觀察",
        "description": "有部分訊號但優先級未達主要分類。",
    },
    {
        "key": "quiet",
        "label": "暫無明確訊號",
        "description": "目前訊號有限，適合作為低優先追蹤。",
    },
    {
        "key": "no_data",
        "label": "缺少資料",
        "description": "尚無足夠日線或指標資料，需補齊後再判斷。",
    },
    {
        "key": "error",
        "label": "資料錯誤",
        "description": "計算或資料讀取失敗，需先排除資料問題。",
    },
]
BUCKET_META_BY_KEY = {bucket["key"]: bucket for bucket in BUCKET_META}
BUCKET_ORDER = {bucket["key"]: index for index, bucket in enumerate(BUCKET_META)}
TECHNICAL_GRADE_META = {
    "strong": {
        "label": "強訊號",
        "description": "本批雷達中技術證據與優先級較前段，適合優先檢查方向是否延續。",
    },
    "medium": {
        "label": "中訊號",
        "description": "技術條件已有成形，但仍需搭配價位、量能或隔日確認。",
    },
    "watch": {
        "label": "觀察",
        "description": "訊號較早期或相對優先級較低，適合列入追蹤但不急著動作。",
    },
}
NON_ACTION_GRADE_BUCKETS = {"quiet", "no_data", "error"}

SIGNAL_LABELS = {
    "price_up": "上漲",
    "price_down": "下跌",
    "above_ma20": "站在 MA20 之上",
    "below_ma20": "跌破 MA20",
    "ma5_above_ma20": "MA5 高於 MA20",
    "ma5_below_ma20": "MA5 低於 MA20",
    "ma20_above_ma60": "MA20 高於 MA60",
    "ma20_below_ma60": "MA20 低於 MA60",
    "cross_above_ma20": "重新站上 MA20",
    "cross_below_ma20": "跌破 MA20",
    "ema_fast_above_slow": "EMA 快線高於慢線",
    "ema_fast_below_slow": "EMA 快線低於慢線",
    "ema_bullish_cross": "EMA 黃金交叉",
    "ema_bearish_cross": "EMA 死亡交叉",
    "macd_positive": "MACD 偏多",
    "macd_negative": "MACD 偏空",
    "adx_bull_trend": "ADX 多方趨勢",
    "adx_bear_trend": "ADX 空方趨勢",
    "donchian_breakout": "突破 20 日高",
    "donchian_breakdown": "跌破 20 日低",
    "rsi_bull_zone": "RSI 多方區",
    "rsi_weak": "RSI 偏弱",
    "rsi_overheated": "RSI 過熱",
    "mfi_inflow": "MFI 資金流入",
    "mfi_outflow": "MFI 偏弱",
    "roc_positive": "ROC 正動能",
    "roc_negative": "ROC 負動能",
    "volume_price_up": "量增價漲",
    "volume_price_down": "量增價跌",
    "volume_expansion": "量能放大",
    "volume_above_ma5": "成交量高於 5 日均量",
    "structure_support_break": "跌破 20 日支撐",
    "structure_resistance_breakout": "突破 20 日壓力",
    "near_support": "貼近 20 日支撐",
    "near_resistance": "貼近 20 日壓力",
    "bollinger_breakout": "突破布林上緣",
    "bollinger_breakdown": "跌破布林下緣",
    "bollinger_squeeze": "布林壓縮",
    "kd_bullish_cross": "KD 黃金交叉",
    "kd_bearish_cross": "KD 死亡交叉",
    "kd_overbought": "KD 過熱",
    "kd_oversold": "KD 低檔",
    "atr_high_volatility": "ATR 高波動",
    "atr_expanding": "ATR 波動擴大",
}

RISK_SIGNAL_KEYS = {
    "price_down",
    "below_ma20",
    "ma5_below_ma20",
    "ma20_below_ma60",
    "cross_below_ma20",
    "ema_fast_below_slow",
    "ema_bearish_cross",
    "macd_negative",
    "adx_bear_trend",
    "donchian_breakdown",
    "rsi_weak",
    "rsi_overheated",
    "mfi_outflow",
    "roc_negative",
    "volume_price_down",
    "structure_support_break",
    "bollinger_breakdown",
    "kd_bearish_cross",
}
SUPPORT_BREAK_SIGNAL_KEYS = {
    "below_ma20",
    "cross_below_ma20",
    "donchian_breakdown",
    "structure_support_break",
    "bollinger_breakdown",
}
BEARISH_MOMENTUM_SIGNAL_KEYS = RISK_SIGNAL_KEYS - SUPPORT_BREAK_SIGNAL_KEYS - {
    "volume_price_down",
    "rsi_overheated",
}
BREAKOUT_HIGH_SIGNAL_KEYS = {
    "donchian_breakout",
    "structure_resistance_breakout",
    "bollinger_breakout",
}
TREND_RECLAIM_SIGNAL_KEYS = {
    "cross_above_ma20",
    "ema_bullish_cross",
    "adx_bull_trend",
    "kd_bullish_cross",
}
BREAKOUT_SIGNAL_KEYS = {
    *TREND_RECLAIM_SIGNAL_KEYS,
    "donchian_breakout",
    "structure_resistance_breakout",
    "bollinger_breakout",
}
VOLUME_SIGNAL_KEYS = {
    "volume_price_up",
    "volume_price_down",
    "volume_expansion",
    "volume_above_ma5",
}
VOLUME_UP_SIGNAL_KEYS = {
    "volume_price_up",
}
VOLUME_DOWN_SIGNAL_KEYS = {
    "volume_price_down",
}
VOLUME_NEUTRAL_SIGNAL_KEYS = {
    "volume_expansion",
    "volume_above_ma5",
}
OVERHEATED_SIGNAL_KEYS = {
    "rsi_overheated",
    "kd_overbought",
}
VOLATILITY_RISK_SIGNAL_KEYS = {
    "atr_high_volatility",
    "atr_expanding",
}
COMPRESSION_SIGNAL_KEYS = {
    "bollinger_squeeze",
}
MOMENTUM_SIGNAL_KEYS = {
    "price_up",
    "above_ma20",
    "ma5_above_ma20",
    "ma20_above_ma60",
    "ema_fast_above_slow",
    "macd_positive",
    "rsi_bull_zone",
    "mfi_inflow",
    "roc_positive",
    "kd_bullish_cross",
}
PULLBACK_CONTEXT_KEYS = {
    "above_ma20",
    "ma5_above_ma20",
    "ma20_above_ma60",
    "ema_fast_above_slow",
    "macd_positive",
}
HIGH_RISK_SIGNAL_KEYS = {
    "cross_below_ma20",
    "ema_bearish_cross",
    "adx_bear_trend",
    "donchian_breakdown",
    "structure_support_break",
    "bollinger_breakdown",
    "volume_price_down",
}
HIGH_MOMENTUM_SIGNAL_KEYS = {
    "cross_above_ma20",
    "ema_bullish_cross",
    "adx_bull_trend",
    "donchian_breakout",
    "structure_resistance_breakout",
    "bollinger_breakout",
    "volume_price_up",
}
TECHNICAL_SIGNAL_WEIGHTS = {
    "donchian_breakdown": 3.5,
    "structure_support_break": 3.6,
    "bollinger_breakdown": 3.2,
    "cross_below_ma20": 3.0,
    "volume_price_down": 2.8,
    "ema_bearish_cross": 2.6,
    "adx_bear_trend": 2.5,
    "macd_negative": 2.3,
    "roc_negative": 2.2,
    "rsi_overheated": 2.1,
    "kd_bearish_cross": 2.1,
    "kd_overbought": 2.0,
    "atr_high_volatility": 2.2,
    "atr_expanding": 1.8,
    "mfi_outflow": 2.0,
    "rsi_weak": 1.8,
    "donchian_breakout": 3.2,
    "structure_resistance_breakout": 3.3,
    "bollinger_breakout": 3.0,
    "volume_price_up": 2.8,
    "cross_above_ma20": 2.6,
    "ema_bullish_cross": 2.5,
    "adx_bull_trend": 2.4,
    "macd_positive": 2.2,
    "roc_positive": 2.1,
    "kd_bullish_cross": 2.0,
    "mfi_inflow": 2.0,
    "rsi_bull_zone": 1.8,
    "volume_expansion": 1.7,
    "volume_above_ma5": 1.5,
    "bollinger_squeeze": 1.4,
    "near_support": 1.1,
    "near_resistance": 1.1,
    "kd_oversold": 1.0,
    "above_ma20": 1.4,
    "below_ma20": 1.4,
    "ma5_above_ma20": 1.2,
    "ma5_below_ma20": 1.2,
    "ma20_above_ma60": 1.0,
    "ma20_below_ma60": 1.0,
}
BUCKET_CONFIRMATION_KEYS = {
    "limit_down_liquidity": RISK_SIGNAL_KEYS,
    "selloff_risk": RISK_SIGNAL_KEYS,
    "overheated": OVERHEATED_SIGNAL_KEYS,
    "volatility_risk": VOLATILITY_RISK_SIGNAL_KEYS,
    "support_break": SUPPORT_BREAK_SIGNAL_KEYS,
    "volume_down": VOLUME_DOWN_SIGNAL_KEYS,
    "bearish_momentum": BEARISH_MOMENTUM_SIGNAL_KEYS,
    "limit_up_lock": HIGH_MOMENTUM_SIGNAL_KEYS | MOMENTUM_SIGNAL_KEYS | VOLUME_SIGNAL_KEYS,
    "surge_up": HIGH_MOMENTUM_SIGNAL_KEYS | MOMENTUM_SIGNAL_KEYS | VOLUME_SIGNAL_KEYS,
    "breakout_high": BREAKOUT_HIGH_SIGNAL_KEYS,
    "trend_reclaim": TREND_RECLAIM_SIGNAL_KEYS,
    "volume_up": VOLUME_UP_SIGNAL_KEYS,
    "volume": VOLUME_NEUTRAL_SIGNAL_KEYS,
    "compression_watch": COMPRESSION_SIGNAL_KEYS,
    "pullback": PULLBACK_CONTEXT_KEYS,
    "momentum": MOMENTUM_SIGNAL_KEYS,
}
RISK_BUCKETS = {
    "limit_down_liquidity",
    "selloff_risk",
    "overheated",
    "volatility_risk",
    "support_break",
    "volume_down",
    "bearish_momentum",
    "limit_down_move",
    "risk",
}
MOMENTUM_BUCKETS = {
    "limit_up_lock",
    "surge_up",
    "breakout_high",
    "trend_reclaim",
    "volume_up",
    "compression_watch",
    "limit_up_move",
    "breakout",
    "pullback",
    "momentum",
}


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, Real) and value == value:
        return float(value)

    return None


def _parse_trade_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    normalized = text.replace("/", "-")
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass

    try:
        return date.fromisoformat(normalized[:10])
    except ValueError:
        return None


def _signal_keys(row: dict) -> list[str]:
    return [
        str(key)
        for key in (row.get("signal_keys") or [])
        if str(key or "").strip()
    ]


def _signal_labels(signal_keys: list[str]) -> list[str]:
    return [SIGNAL_LABELS.get(key, key) for key in signal_keys]


def _format_pct(value: float | None) -> str | None:
    if value is None:
        return None

    return f"{value:+.2f}%"


def _is_stale(row: dict, target_trade_date: date | None) -> bool:
    if target_trade_date is None or row.get("status") in {"error", "no_data"}:
        return False

    row_trade_date = _parse_trade_date(row.get("time"))
    return row_trade_date is None or row_trade_date < target_trade_date


def _matched_keys(signal_keys: list[str], candidates: set[str]) -> list[str]:
    return [key for key in signal_keys if key in candidates]


def _technical_evidence_score(row: dict, bucket: str) -> float:
    keys = set(_signal_keys(row))
    if not keys:
        return 0.0

    score = sum(TECHNICAL_SIGNAL_WEIGHTS.get(key, 1.0) for key in keys)

    confirmation_keys = BUCKET_CONFIRMATION_KEYS.get(bucket, set())
    confirmation_count = len(keys.intersection(confirmation_keys))
    score += confirmation_count * 1.5

    signal_families = [
        SUPPORT_BREAK_SIGNAL_KEYS,
        VOLUME_DOWN_SIGNAL_KEYS,
        OVERHEATED_SIGNAL_KEYS,
        VOLATILITY_RISK_SIGNAL_KEYS,
        BEARISH_MOMENTUM_SIGNAL_KEYS,
        BREAKOUT_HIGH_SIGNAL_KEYS,
        TREND_RECLAIM_SIGNAL_KEYS,
        VOLUME_UP_SIGNAL_KEYS,
        VOLUME_NEUTRAL_SIGNAL_KEYS,
        COMPRESSION_SIGNAL_KEYS,
        MOMENTUM_SIGNAL_KEYS,
    ]
    family_count = sum(1 for family in signal_families if keys.intersection(family))
    score += min(family_count, 4) * 1.25

    change_pct = _number(row.get("change_pct"))
    if change_pct is not None:
        if bucket in RISK_BUCKETS and change_pct < 0:
            score += min(abs(change_pct), 10) * 0.35
        elif bucket in MOMENTUM_BUCKETS and change_pct > 0:
            score += min(abs(change_pct), 10) * 0.35

    if bucket in RISK_BUCKETS and keys.intersection(HIGH_MOMENTUM_SIGNAL_KEYS | VOLUME_UP_SIGNAL_KEYS):
        score -= 1.5
    elif bucket in MOMENTUM_BUCKETS and keys.intersection(RISK_SIGNAL_KEYS):
        score -= 1.5

    return max(0.0, score)


def _bucket_for_row(row: dict) -> tuple[str, list[str]]:
    status = row.get("status")
    if status == "error":
        return "error", []
    if status == "no_data":
        return "no_data", []

    keys = _signal_keys(row)
    key_set = set(keys)
    score = int(row.get("score", 0) or 0)
    change_pct = _number(row.get("change_pct"))
    limit_status = row.get("limit_status")

    if limit_status in {"limit_up", "limit_down"} or (
        change_pct is not None and abs(change_pct) >= HIGH_MOVE_PCT_THRESHOLD
    ):
        if limit_status == "limit_down":
            return "limit_down_liquidity", _matched_keys(keys, RISK_SIGNAL_KEYS)

        if limit_status == "limit_up":
            return "limit_up_lock", _matched_keys(
                keys,
                HIGH_MOMENTUM_SIGNAL_KEYS | MOMENTUM_SIGNAL_KEYS | VOLUME_SIGNAL_KEYS,
            )

        if change_pct is not None and change_pct < 0:
            return "selloff_risk", _matched_keys(keys, RISK_SIGNAL_KEYS)

        return "surge_up", _matched_keys(
            keys,
            HIGH_MOMENTUM_SIGNAL_KEYS | MOMENTUM_SIGNAL_KEYS | VOLUME_SIGNAL_KEYS,
        )

    support_break_keys = _matched_keys(keys, SUPPORT_BREAK_SIGNAL_KEYS)
    if support_break_keys:
        return "support_break", support_break_keys

    volume_down_keys = _matched_keys(keys, VOLUME_DOWN_SIGNAL_KEYS)
    if volume_down_keys:
        return "volume_down", volume_down_keys

    overheated_keys = _matched_keys(keys, OVERHEATED_SIGNAL_KEYS)
    if overheated_keys:
        return "overheated", overheated_keys

    volatility_risk_keys = _matched_keys(keys, VOLATILITY_RISK_SIGNAL_KEYS)
    if volatility_risk_keys:
        return "volatility_risk", volatility_risk_keys

    bearish_momentum_keys = _matched_keys(keys, BEARISH_MOMENTUM_SIGNAL_KEYS)
    if bearish_momentum_keys or score <= -3:
        return "bearish_momentum", bearish_momentum_keys

    breakout_high_keys = _matched_keys(keys, BREAKOUT_HIGH_SIGNAL_KEYS)
    if breakout_high_keys:
        return "breakout_high", breakout_high_keys

    trend_reclaim_keys = _matched_keys(keys, TREND_RECLAIM_SIGNAL_KEYS)
    if trend_reclaim_keys:
        return "trend_reclaim", trend_reclaim_keys

    volume_up_keys = _matched_keys(keys, VOLUME_UP_SIGNAL_KEYS)
    if volume_up_keys:
        return "volume_up", volume_up_keys

    volume_keys = _matched_keys(keys, VOLUME_NEUTRAL_SIGNAL_KEYS)
    if volume_keys:
        return "volume", volume_keys

    compression_keys = _matched_keys(keys, COMPRESSION_SIGNAL_KEYS)
    if compression_keys:
        return "compression_watch", compression_keys

    if (
        score >= 3
        and change_pct is not None
        and change_pct < 0
        and key_set.intersection(PULLBACK_CONTEXT_KEYS)
    ):
        return "pullback", _matched_keys(keys, PULLBACK_CONTEXT_KEYS)

    momentum_keys = _matched_keys(keys, MOMENTUM_SIGNAL_KEYS)
    if momentum_keys or score >= 3:
        return "momentum", momentum_keys

    if keys or score != 0:
        return "watch", keys[:3]

    return "quiet", []


def _mode_accepts_bucket(mode: str, bucket: str) -> bool:
    if mode == "all":
        return True

    if mode == "surge":
        return bucket in SURGE_MODE_BUCKETS

    if mode == "breakout":
        return bucket in BREAKOUT_MODE_BUCKETS

    if mode == "volume":
        return bucket in VOLUME_MODE_BUCKETS

    if mode == "overheat":
        return bucket in OVERHEAT_MODE_BUCKETS

    if mode == "weakness":
        return bucket in WEAKNESS_MODE_BUCKETS

    if mode == "risk":
        return bucket in RISK_MODE_BUCKETS

    if mode == "momentum":
        return bucket in MOMENTUM_MODE_BUCKETS

    return bucket in ACTION_MODE_BUCKETS


def _urgency(row: dict, bucket: str, stale: bool) -> str:
    if bucket in {"quiet", "no_data", "error"}:
        return "low"

    keys = set(_signal_keys(row))
    score = int(row.get("score", 0) or 0)
    change_pct = _number(row.get("change_pct"))
    limit_status = row.get("limit_status")

    if limit_status in {"limit_up", "limit_down"} or (
        change_pct is not None and abs(change_pct) >= HIGH_MOVE_PCT_THRESHOLD
    ):
        urgency = "high"
    elif bucket in {"support_break", "bearish_momentum", "risk"}:
        urgency = "high" if score <= -4 or keys.intersection(HIGH_RISK_SIGNAL_KEYS) else "medium"
    elif bucket == "volume_down":
        urgency = "high" if score <= -4 else "medium"
    elif bucket == "overheated":
        urgency = "medium"
    elif bucket == "volatility_risk":
        urgency = "high" if keys.intersection({"atr_high_volatility"}) else "medium"
    elif bucket in {"breakout_high", "trend_reclaim", "breakout"}:
        urgency = "high" if score >= 4 or keys.intersection(HIGH_MOMENTUM_SIGNAL_KEYS) else "medium"
    elif bucket in {"volume_up", "volume"}:
        urgency = "medium"
    elif bucket == "compression_watch":
        urgency = "low"
    elif bucket in {"pullback", "momentum"}:
        urgency = "medium" if abs(score) >= 3 else "low"
    else:
        urgency = "low"

    if stale and urgency == "high":
        return "medium"

    return urgency


def _action_label(row: dict, bucket: str, stale: bool) -> str:
    limit_status = row.get("limit_status")
    change_pct = _number(row.get("change_pct"))

    if bucket == "error":
        action = "先排除資料錯誤"
    elif bucket == "no_data":
        action = "先補齊資料"
    elif bucket == "limit_up_lock":
        action = "確認是否續強或過熱"
    elif bucket == "limit_down_liquidity":
        action = "優先檢查停損與流動性"
    elif limit_status == "limit_up":
        action = "確認是否續強或過熱"
    elif limit_status == "limit_down":
        action = "優先檢查停損與流動性"
    elif bucket == "surge_up":
        action = "留意追價與隔日回落風險"
    elif bucket == "selloff_risk":
        action = "檢查是否破線或需降風險"
    elif change_pct is not None and change_pct >= HIGH_MOVE_PCT_THRESHOLD:
        action = "留意追價與隔日回落風險"
    elif change_pct is not None and change_pct <= -HIGH_MOVE_PCT_THRESHOLD:
        action = "檢查是否破線或需降風險"
    elif bucket == "overheated":
        action = "控制追價並觀察降溫"
    elif bucket == "volatility_risk":
        action = "拉高停損距離並降低追價"
    elif bucket == "support_break":
        action = "檢查支撐與停損"
    elif bucket == "volume_down":
        action = "確認賣壓是否延續"
    elif bucket in {"bearish_momentum", "risk"}:
        action = "優先檢查風控"
    elif bucket == "breakout_high":
        action = "追蹤突破延續"
    elif bucket == "trend_reclaim":
        action = "確認轉強是否站穩"
    elif bucket == "volume_up":
        action = "追蹤量價攻擊"
    elif bucket == "breakout":
        action = "追蹤突破延續"
    elif bucket == "volume":
        action = "確認量價方向"
    elif bucket == "compression_watch":
        action = "等待放量突破或跌破"
    elif bucket == "pullback":
        action = "觀察回檔位置"
    elif bucket == "momentum":
        action = "追蹤趨勢延續"
    elif bucket == "watch":
        action = "一般追蹤"
    else:
        action = "低優先觀察"

    if stale and bucket not in {"error", "no_data"}:
        return f"{action}，但先確認資料更新"

    return action


def _reason(
    row: dict,
    bucket: str,
    matched_signal_keys: list[str],
    stale: bool,
    target_trade_date: date | None,
) -> str:
    parts: list[str] = []
    primary_label = row.get("primary_signal_label")
    signal_labels = _signal_labels(matched_signal_keys or _signal_keys(row)[:3])
    change_pct = _number(row.get("change_pct"))
    score = int(row.get("score", 0) or 0)
    row_trade_date = _parse_trade_date(row.get("time"))

    if bucket == "error" and row.get("error_message"):
        return f"資料計算失敗：{row['error_message']}"

    if bucket == "no_data":
        return "目前沒有足夠的日線或技術指標資料。"

    if primary_label:
        parts.append(f"主要訊號：{primary_label}")
    elif signal_labels:
        parts.append(f"訊號：{', '.join(signal_labels[:3])}")

    if change_pct is not None:
        parts.append(f"漲跌幅 {_format_pct(change_pct)}")

    parts.append(f"score {score}")

    if stale and target_trade_date is not None:
        row_date_text = row_trade_date.isoformat() if row_trade_date else "-"
        parts.append(f"資料日期 {row_date_text} 落後目標 {target_trade_date.isoformat()}")

    if not parts:
        parts.append(BUCKET_META_BY_KEY[bucket]["description"])

    return "；".join(parts)


def _priority_score(
    row: dict,
    bucket: str,
    urgency: str,
    stale: bool,
    technical_evidence_score: float,
    context_score: float = 0.0,
) -> float:
    change_pct = _number(row.get("change_pct"))
    score = int(row.get("score", 0) or 0)
    signal_count = int(row.get("signal_count", 0) or 0)

    bucket_base = {
        "limit_move": 100,
        "limit_down_liquidity": 105,
        "selloff_risk": 102,
        "limit_up_lock": 100,
        "surge_up": 96,
        "support_break": 94,
        "volume_down": 90,
        "bearish_momentum": 86,
        "overheated": 84,
        "volatility_risk": 88,
        "breakout_high": 82,
        "trend_reclaim": 78,
        "volume_up": 72,
        "limit_up_move": 100,
        "limit_down_move": 100,
        "risk": 90,
        "breakout": 80,
        "volume": 70,
        "compression_watch": 68,
        "pullback": 65,
        "momentum": 60,
        "watch": 40,
        "quiet": 10,
        "no_data": 0,
        "error": 0,
    }.get(bucket, 0)
    urgency_bonus = {"high": 20, "medium": 10, "low": 0}.get(urgency, 0)
    change_bonus = abs(change_pct) * 2 if change_pct is not None else 0
    stale_penalty = 15 if stale else 0

    return (
        bucket_base
        + urgency_bonus
        + (abs(score) * 3)
        + signal_count
        + change_bonus
        + (technical_evidence_score * 1.8)
        + (context_score * 2.0)
        - stale_penalty
    )


def _indicator_snapshot(row: dict) -> dict:
    snapshot = row.get("indicator_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _context_snapshot(row: dict) -> dict:
    snapshot = row.get("context_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _context_group(row: dict, group: str) -> dict:
    value = _context_snapshot(row).get(group)
    return value if isinstance(value, dict) else {}


def _context_number(row: dict, group: str, key: str) -> float | None:
    return _number(_context_group(row, group).get(key))


def _indicator_group(row: dict, group: str) -> dict:
    value = _indicator_snapshot(row).get(group)
    return value if isinstance(value, dict) else {}


def _indicator_number(row: dict, group: str, key: str) -> float | None:
    return _number(_indicator_group(row, group).get(key))


def _first_number(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value

    return None


def _format_signed_lots(value: float | None) -> str | None:
    if value is None:
        return None

    return f"{int(round(value)):+,}張"


def _format_signed_pct(value: float | None) -> str | None:
    if value is None:
        return None

    return f"{value:+.1f}%"


def _context_signal(
    *,
    key: str,
    source: str,
    label: str,
    tone: str,
    stance: str,
    description: str,
    value_label: str | None = None,
) -> dict[str, object]:
    return {
        "key": key,
        "source": source,
        "label": label,
        "tone": tone,
        "stance": stance,
        "description": description,
        "value_label": value_label,
    }


def _institutional_context_signal(row: dict, direction: str) -> dict[str, object] | None:
    total_net = _context_number(row, "institutional", "total_net")
    if total_net is None or total_net == 0:
        return None

    value_label = _format_signed_lots(total_net)
    if direction == "bullish":
        label = "法人確認" if total_net > 0 else "法人背離"
        tone = "positive" if total_net > 0 else "warning"
        stance = "confirm" if total_net > 0 else "contradict"
    elif direction == "bearish":
        label = "法人確認" if total_net < 0 else "法人逆勢買"
        tone = "negative" if total_net < 0 else "warning"
        stance = "confirm" if total_net < 0 else "contradict"
    else:
        label = "法人偏多" if total_net > 0 else "法人偏空"
        tone = "positive" if total_net > 0 else "negative"
        stance = "info"

    side = "買超" if total_net > 0 else "賣超"
    return _context_signal(
        key="institutional_net",
        source="籌碼",
        label=label,
        tone=tone,
        stance=stance,
        value_label=value_label,
        description=f"最新三大法人合計{side} {value_label}",
    )


def _leverage_context_signal(
    row: dict,
    bucket: str,
    direction: str,
    threshold: int = 100,
) -> dict[str, object] | None:
    margin_change = _context_number(row, "margin", "margin_balance_change")
    if margin_change is not None and abs(margin_change) >= threshold:
        value_label = _format_signed_lots(margin_change)
        if margin_change > 0:
            if bucket in {"limit_up_lock", "surge_up", "overheated"}:
                label = "融資過熱"
                tone = "warning"
                stance = "risk"
            elif direction == "bullish":
                label = "融資跟進"
                tone = "positive"
                stance = "confirm"
            elif direction == "bearish":
                label = "融資撐盤"
                tone = "warning"
                stance = "contradict"
            else:
                label = "融資升溫"
                tone = "warning"
                stance = "info"
        else:
            if direction == "bullish":
                label = "融資降溫"
                tone = "positive"
                stance = "confirm"
            elif direction == "bearish":
                label = "融資退場"
                tone = "negative"
                stance = "confirm"
            else:
                label = "融資減少"
                tone = "neutral"
                stance = "info"

        return _context_signal(
            key="margin_balance_change",
            source="融資",
            label=label,
            tone=tone,
            stance=stance,
            value_label=value_label,
            description=f"最新融資餘額變化 {value_label}",
        )

    short_change = _context_number(row, "margin", "short_balance_change")
    if short_change is None or abs(short_change) < threshold:
        return None

    value_label = _format_signed_lots(short_change)
    if short_change > 0:
        if direction == "bearish":
            label = "融券加壓"
            tone = "negative"
            stance = "confirm"
        elif direction == "bullish":
            label = "空方加壓"
            tone = "warning"
            stance = "contradict"
        else:
            label = "融券增加"
            tone = "negative"
            stance = "info"
    else:
        if direction == "bullish":
            label = "回補助攻"
            tone = "positive"
            stance = "confirm"
        elif direction == "bearish":
            label = "空方回補"
            tone = "warning"
            stance = "contradict"
        else:
            label = "融券回補"
            tone = "neutral"
            stance = "info"

    return _context_signal(
        key="short_balance_change",
        source="融券",
        label=label,
        tone=tone,
        stance=stance,
        value_label=value_label,
        description=f"最新融券餘額變化 {value_label}",
    )


def _intraday_session_change_pct(row: dict) -> float | None:
    value = _context_number(row, "intraday", "session_change_pct")
    if value is not None:
        return value

    points = row.get("intraday_points") or []
    if not isinstance(points, list) or len(points) < 2:
        return None

    first_price = _number(points[0].get("price") if isinstance(points[0], dict) else None)
    last_price = _number(points[-1].get("price") if isinstance(points[-1], dict) else None)
    if first_price in {None, 0} or last_price is None:
        return None

    return (last_price - first_price) / first_price * 100


def _intraday_context_signal(row: dict, direction: str) -> dict[str, object] | None:
    intraday = _context_group(row, "intraday")
    points = row.get("intraday_points") or []
    if not intraday and not points:
        return None

    change_pct = _first_number(
        _context_number(row, "intraday", "change_pct"),
        _number(row.get("change_pct")),
    )
    session_change_pct = _intraday_session_change_pct(row)
    if change_pct is None and session_change_pct is None:
        return None

    if direction == "bullish":
        if change_pct is not None and change_pct >= 1 and (
            session_change_pct is None or session_change_pct >= -0.2
        ):
            label, tone, stance = "盤中續強", "positive", "confirm"
        elif session_change_pct is not None and session_change_pct <= -1:
            label, tone, stance = "盤中轉弱", "warning", "contradict"
        else:
            return None
    elif direction == "bearish":
        if change_pct is not None and change_pct <= -1 and (
            session_change_pct is None or session_change_pct <= 0.2
        ):
            label, tone, stance = "盤中續弱", "negative", "confirm"
        elif session_change_pct is not None and session_change_pct >= 1:
            label, tone, stance = "盤中反彈", "warning", "contradict"
        else:
            return None
    elif change_pct is not None and change_pct >= 1:
        label, tone, stance = "盤中偏多", "positive", "info"
    elif change_pct is not None and change_pct <= -1:
        label, tone, stance = "盤中偏空", "negative", "info"
    else:
        return None

    value_label = _format_signed_pct(change_pct)
    detail = f"盤中漲跌 {value_label}" if value_label else "盤中走勢已更新"
    if session_change_pct is not None:
        detail = f"{detail}，日內 {session_change_pct:+.1f}%"

    return _context_signal(
        key="intraday_trend",
        source="盤中",
        label=label,
        tone=tone,
        stance=stance,
        value_label=value_label,
        description=detail,
    )


def _revenue_context_signal(row: dict, direction: str, threshold_pct: float = 10.0) -> dict[str, object] | None:
    revenue_yoy = _first_number(
        _context_number(row, "revenue", "year_over_year_pct"),
        _context_number(row, "revenue", "cumulative_year_over_year_pct"),
    )
    if revenue_yoy is None or abs(revenue_yoy) < threshold_pct:
        return None

    value_label = _format_signed_pct(revenue_yoy)
    if revenue_yoy > 0:
        if direction == "bullish":
            label, tone, stance = "營收背書", "positive", "confirm"
        elif direction == "bearish":
            label, tone, stance = "營收逆勢強", "warning", "contradict"
        else:
            label, tone, stance = "營收成長", "positive", "info"
    elif direction == "bullish":
        label, tone, stance = "營收背離", "warning", "contradict"
    elif direction == "bearish":
        label, tone, stance = "營收同弱", "negative", "confirm"
    else:
        label, tone, stance = "營收衰退", "negative", "info"

    return _context_signal(
        key="revenue_yoy",
        source="營收",
        label=label,
        tone=tone,
        stance=stance,
        value_label=value_label,
        description=f"最新月營收 YoY {value_label}",
    )


def _financial_context_signal(row: dict, direction: str) -> dict[str, object] | None:
    eps = _context_number(row, "financial", "eps")
    roe = _context_number(row, "financial", "roe")
    if eps is None and roe is None:
        return None

    if eps is not None and eps <= 0:
        value_label = f"EPS {eps:.2f}"
        if direction == "bullish":
            label, tone, stance = "獲利背離", "warning", "contradict"
        elif direction == "bearish":
            label, tone, stance = "獲利同弱", "negative", "confirm"
        else:
            label, tone, stance = "獲利拖累", "negative", "info"
    elif roe is not None and roe >= 10 and (eps is None or eps > 0):
        value_label = f"ROE {roe:.1f}%"
        if direction == "bullish":
            label, tone, stance = "獲利背書", "positive", "confirm"
        elif direction == "bearish":
            label, tone, stance = "獲利逆勢強", "warning", "contradict"
        else:
            label, tone, stance = "獲利穩定", "positive", "info"
    elif roe is not None and roe < 0:
        value_label = f"ROE {roe:.1f}%"
        if direction == "bullish":
            label, tone, stance = "獲利背離", "warning", "contradict"
        elif direction == "bearish":
            label, tone, stance = "獲利同弱", "negative", "confirm"
        else:
            label, tone, stance = "獲利拖累", "negative", "info"
    else:
        return None

    return _context_signal(
        key="financial_quality",
        source="財務",
        label=label,
        tone=tone,
        stance=stance,
        value_label=value_label,
        description=value_label,
    )


def _context_signals(row: dict, bucket: str) -> list[dict[str, object]]:
    direction, _ = _technical_direction(bucket=bucket, row=row)
    candidates = [
        _intraday_context_signal(row=row, direction=direction),
        _institutional_context_signal(row=row, direction=direction),
        _leverage_context_signal(row=row, bucket=bucket, direction=direction),
        _revenue_context_signal(row=row, direction=direction),
        _financial_context_signal(row=row, direction=direction),
    ]
    return [signal for signal in candidates if signal is not None][:4]


def _context_score(signals: list[dict[str, object]]) -> float:
    score_by_stance = {
        "confirm": 1.0,
        "contradict": -1.0,
        "risk": -0.5,
        "info": 0.0,
    }
    return round(
        sum(score_by_stance.get(str(signal.get("stance") or ""), 0.0) for signal in signals),
        4,
    )


def _context_summary(signals: list[dict[str, object]]) -> str:
    return " · ".join(str(signal["label"]) for signal in signals[:3] if signal.get("label"))


def _family_score(keys: set[str], positive: set[str], negative: set[str] | None = None) -> float:
    negative = negative or set()
    positive_score = sum(TECHNICAL_SIGNAL_WEIGHTS.get(key, 1.0) for key in keys.intersection(positive))
    negative_score = sum(TECHNICAL_SIGNAL_WEIGHTS.get(key, 1.0) for key in keys.intersection(negative))
    return round(positive_score - negative_score, 4)


def _factor_scores(row: dict) -> dict[str, float]:
    keys = set(_signal_keys(row))

    return {
        "trend": _family_score(
            keys,
            {
                "above_ma20",
                "ma5_above_ma20",
                "ma20_above_ma60",
                "cross_above_ma20",
                "ema_fast_above_slow",
                "ema_bullish_cross",
                "adx_bull_trend",
            },
            {
                "below_ma20",
                "ma5_below_ma20",
                "ma20_below_ma60",
                "cross_below_ma20",
                "ema_fast_below_slow",
                "ema_bearish_cross",
                "adx_bear_trend",
            },
        ),
        "momentum": _family_score(
            keys,
            {"macd_positive", "roc_positive", "rsi_bull_zone", "kd_bullish_cross"},
            {
                "macd_negative",
                "roc_negative",
                "rsi_weak",
                "rsi_overheated",
                "kd_bearish_cross",
                "kd_overbought",
            },
        ),
        "volume": _family_score(
            keys,
            {"volume_price_up", "volume_expansion", "volume_above_ma5", "mfi_inflow"},
            {"volume_price_down", "mfi_outflow"},
        ),
        "structure": _family_score(
            keys,
            {"donchian_breakout", "structure_resistance_breakout", "bollinger_breakout"},
            {"donchian_breakdown", "structure_support_break", "bollinger_breakdown"},
        ),
        "volatility": round(
            sum(
                TECHNICAL_SIGNAL_WEIGHTS.get(key, 1.0)
                for key in keys.intersection(VOLATILITY_RISK_SIGNAL_KEYS | COMPRESSION_SIGNAL_KEYS)
            ),
            4,
        ),
    }


def _price_levels(row: dict, bucket: str) -> dict[str, object]:
    close = _number(row.get("close"))
    support = _first_number(
        _indicator_number(row, "support_resistance", "support20"),
        _indicator_number(row, "donchian", "lower20"),
        _indicator_number(row, "bollinger", "lower20"),
        _indicator_number(row, "ma", "ma20"),
    )
    resistance = _first_number(
        _indicator_number(row, "support_resistance", "resistance20"),
        _indicator_number(row, "donchian", "upper20"),
        _indicator_number(row, "bollinger", "upper20"),
        _indicator_number(row, "ma", "ma20"),
    )
    ma20 = _indicator_number(row, "ma", "ma20")
    atr14 = _indicator_number(row, "atr", "atr14")
    atr_pct = (atr14 / close * 100) if atr14 is not None and close not in {None, 0} else None
    bollinger_upper = _indicator_number(row, "bollinger", "upper20")
    bollinger_lower = _indicator_number(row, "bollinger", "lower20")

    if bucket in RISK_BUCKETS:
        key_level_label = "回收壓力"
        key_level = _first_number(resistance, ma20)
    elif bucket == "compression_watch":
        key_level_label = "突破壓力"
        key_level = resistance
    else:
        key_level_label = "失效支撐"
        key_level = _first_number(support, ma20)

    return {
        "close": close,
        "support": support,
        "resistance": resistance,
        "ma20": ma20,
        "atr14": atr14,
        "atr_pct": round(atr_pct, 4) if atr_pct is not None else None,
        "bollinger_upper": bollinger_upper,
        "bollinger_lower": bollinger_lower,
        "key_level": key_level,
        "key_level_label": key_level_label,
    }


def _technical_direction(bucket: str, row: dict) -> tuple[str, str]:
    if bucket in {"overheated", "volatility_risk"}:
        return "mixed", "分歧"
    if bucket == "compression_watch":
        return "neutral", "待突破"
    if bucket in RISK_BUCKETS:
        return "bearish", "偏空"
    if bucket in MOMENTUM_BUCKETS:
        return "bullish", "偏多"

    score = int(row.get("score", 0) or 0)
    if score >= 2:
        return "bullish", "偏多"
    if score <= -2:
        return "bearish", "偏空"
    return "neutral", "觀望"


def _setup_label(bucket: str) -> str:
    return {
        "limit_up_lock": "漲停續強",
        "surge_up": "急漲追價",
        "limit_down_liquidity": "跌停風控",
        "selloff_risk": "急跌風控",
        "overheated": "過熱追價",
        "volatility_risk": "高波動控風險",
        "support_break": "跌破支撐",
        "volume_down": "量價轉弱",
        "bearish_momentum": "動能轉弱",
        "breakout_high": "突破確認",
        "trend_reclaim": "站回轉強",
        "volume_up": "量價攻擊",
        "volume": "量能異動",
        "compression_watch": "壓縮待突破",
        "pullback": "強勢回檔",
        "momentum": "趨勢延續",
    }.get(bucket, BUCKET_META_BY_KEY.get(bucket, {}).get("label", "一般觀察"))


def _timing_label(bucket: str) -> str:
    if bucket in {"limit_up_lock", "surge_up", "overheated", "volatility_risk"}:
        return "追價需控風險"
    if bucket in {"limit_down_liquidity", "selloff_risk", "support_break"}:
        return "先處理失效"
    if bucket == "compression_watch":
        return "等方向確認"
    if bucket == "pullback":
        return "等回檔止穩"
    if bucket in {"breakout_high", "trend_reclaim", "volume_up"}:
        return "看延續確認"
    if bucket in {"volume_down", "bearish_momentum"}:
        return "等止跌訊號"
    return "一般追蹤"


def _risk_label(bucket: str) -> str:
    if bucket == "overheated":
        return "過熱降溫"
    if bucket == "volatility_risk":
        return "波動擴大"
    if bucket in {"support_break", "limit_down_liquidity", "selloff_risk"}:
        return "支撐失守"
    if bucket in {"breakout_high", "trend_reclaim", "volume_up"}:
        return "假突破"
    if bucket == "compression_watch":
        return "方向未定"
    if bucket == "volume_down":
        return "賣壓延續"
    if bucket == "bearish_momentum":
        return "動能續弱"
    return "依價位控管"


def _technical_notes(row: dict, matched_signal_keys: list[str]) -> list[str]:
    labels = _signal_labels(matched_signal_keys or _signal_keys(row))
    return list(dict.fromkeys(labels))[:4]


def _technical_context(
    row: dict,
    bucket: str,
    matched_signal_keys: list[str],
    technical_evidence_score: float,
) -> dict[str, object]:
    direction, direction_label = _technical_direction(bucket=bucket, row=row)
    score = min(
        100.0,
        max(
            0.0,
            (technical_evidence_score * 7)
            + (abs(int(row.get("score", 0) or 0)) * 4)
            + min(abs(_number(row.get("change_pct")) or 0) * 2, 16),
        ),
    )

    return {
        "technical_score": round(score, 2),
        "technical_grade": "watch",
        "technical_grade_label": TECHNICAL_GRADE_META["watch"]["label"],
        "technical_grade_description": TECHNICAL_GRADE_META["watch"]["description"],
        "direction": direction,
        "direction_label": direction_label,
        "setup_label": _setup_label(bucket),
        "timing_label": _timing_label(bucket),
        "risk_label": _risk_label(bucket),
        "factor_scores": _factor_scores(row),
        "price_levels": _price_levels(row=row, bucket=bucket),
        "technical_notes": _technical_notes(row=row, matched_signal_keys=matched_signal_keys),
    }


def _radar_item(row: dict, target_trade_date: date | None) -> dict:
    bucket, matched_signal_keys = _bucket_for_row(row)
    stale = _is_stale(row, target_trade_date)
    urgency = _urgency(row=row, bucket=bucket, stale=stale)
    technical_evidence_score = _technical_evidence_score(row=row, bucket=bucket)
    context_signals = _context_signals(row=row, bucket=bucket)
    context_score = _context_score(context_signals)
    priority_score = _priority_score(
        row=row,
        bucket=bucket,
        urgency=urgency,
        stale=stale,
        technical_evidence_score=technical_evidence_score,
        context_score=context_score,
    )
    signal_keys = _signal_keys(row)
    bucket_meta = BUCKET_META_BY_KEY[bucket]
    row_trade_date = _parse_trade_date(row.get("time"))
    technical_context = _technical_context(
        row=row,
        bucket=bucket,
        matched_signal_keys=matched_signal_keys,
        technical_evidence_score=technical_evidence_score,
    )

    return {
        "rank": 0,
        "source_rank": row.get("rank"),
        "bucket": bucket,
        "bucket_label": bucket_meta["label"],
        "urgency": urgency,
        "priority_score": round(priority_score, 4),
        "technical_evidence_score": round(technical_evidence_score, 4),
        **technical_context,
        "action_label": _action_label(row=row, bucket=bucket, stale=stale),
        "reason": _reason(
            row=row,
            bucket=bucket,
            matched_signal_keys=matched_signal_keys,
            stale=stale,
            target_trade_date=target_trade_date,
        ),
        "stock_id": row.get("stock_id"),
        "stock_name": row.get("stock_name"),
        "time": row.get("time"),
        "trade_date": row_trade_date,
        "close": row.get("close"),
        "volume": row.get("volume"),
        "change": row.get("change"),
        "previous_close": row.get("previous_close"),
        "change_pct": row.get("change_pct"),
        "limit_status": row.get("limit_status"),
        "score": int(row.get("score", 0) or 0),
        "status": row.get("status", "unknown"),
        "signal_count": int(row.get("signal_count", 0) or 0),
        "signal_keys": signal_keys,
        "matched_signal_keys": matched_signal_keys,
        "matched_signal_labels": _signal_labels(matched_signal_keys),
        "signal_labels": _signal_labels(signal_keys),
        "primary_signal_key": row.get("primary_signal_key"),
        "primary_signal_label": row.get("primary_signal_label"),
        "indicator_snapshot": _indicator_snapshot(row),
        "context_snapshot": _context_snapshot(row),
        "context_signals": context_signals,
        "context_summary": _context_summary(context_signals),
        "context_score": context_score,
        "stale": stale,
        "error_message": row.get("error_message"),
    }


def _set_technical_grade(item: dict, grade: str) -> None:
    meta = TECHNICAL_GRADE_META[grade]
    item["technical_grade"] = grade
    item["technical_grade_label"] = meta["label"]
    item["technical_grade_description"] = meta["description"]


def _assign_technical_grades(results: list[dict]) -> None:
    if not results:
        return

    if len(results) < 3:
        for item in results:
            evidence_score = float(item.get("technical_evidence_score") or 0)
            if item.get("bucket") in NON_ACTION_GRADE_BUCKETS or evidence_score <= 0:
                grade = "watch"
            elif item.get("urgency") == "high" or evidence_score >= 10:
                grade = "strong"
            elif item.get("urgency") == "medium" or evidence_score >= 5:
                grade = "medium"
            else:
                grade = "watch"
            _set_technical_grade(item, grade)
        return

    strong_cutoff_rank = max(1, len(results) // 4)
    medium_cutoff_rank = max(strong_cutoff_rank + 1, ceil(len(results) * 0.7))

    for index, item in enumerate(results, start=1):
        evidence_score = float(item.get("technical_evidence_score") or 0)
        if item.get("bucket") in NON_ACTION_GRADE_BUCKETS or evidence_score <= 0:
            grade = "watch"
        elif index <= strong_cutoff_rank and (item.get("urgency") == "high" or evidence_score >= 8):
            grade = "strong"
        elif index <= medium_cutoff_rank and evidence_score >= 4:
            grade = "medium"
        elif evidence_score >= 10:
            grade = "medium"
        else:
            grade = "watch"
        _set_technical_grade(item, grade)


def _bucket_summary(items: list[dict], mode: str) -> list[dict]:
    counts = Counter(item["bucket"] for item in items)

    return [
        {
            "key": bucket["key"],
            "label": bucket["label"],
            "description": bucket["description"],
            "count": counts.get(bucket["key"], 0),
        }
        for bucket in BUCKET_META
        if _mode_accepts_bucket(mode, bucket["key"])
    ]


def build_watchlist_radar_from_ranking(
    *,
    ranking: dict,
    include_children: bool = True,
    mode: str = "action",
    max_results: int = 30,
) -> dict:
    mode = mode.lower().strip()
    if mode not in ALLOWED_RADAR_MODES:
        raise ValueError(
            f"Unsupported mode='{mode}'. "
            f"Allowed values: {', '.join(sorted(ALLOWED_RADAR_MODES))}."
        )

    max_results = max(1, min(int(max_results), 200))
    target_trade_date = _parse_trade_date(ranking.get("target_trade_date"))
    items = [
        _radar_item(row=row, target_trade_date=target_trade_date)
        for row in (ranking.get("results") or [])
    ]
    matched_items = [
        item
        for item in items
        if _mode_accepts_bucket(mode=mode, bucket=item["bucket"])
    ]
    matched_items.sort(
        key=lambda item: (
            -item["priority_score"],
            BUCKET_ORDER.get(item["bucket"], 999),
            item.get("stock_id") or "",
        )
    )

    results = matched_items[:max_results]
    for index, item in enumerate(results, start=1):
        item["rank"] = index
    _assign_technical_grades(results)

    return {
        "group_id": ranking.get("group_id"),
        "include_children": include_children,
        "mode": mode,
        "max_results": max_results,
        "requested_stock_count": ranking.get("requested_stock_count", 0),
        "ranked_count": ranking.get("ranked_count", 0),
        "matched_count": len(matched_items),
        "radar_count": len(results),
        "no_data_count": ranking.get("no_data_count", 0),
        "error_count": ranking.get("error_count", 0),
        "trade_date": ranking.get("trade_date"),
        "target_trade_date": target_trade_date,
        "is_current": ranking.get("is_current", True),
        "current_stock_count": ranking.get("current_stock_count", 0),
        "stale_stock_count": ranking.get("stale_stock_count", 0),
        "buckets": _bucket_summary(matched_items, mode=mode),
        "results": results,
    }


def get_watchlist_group_radar(
    db: Session,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = "action",
    max_results: int = 30,
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    calculation_limit: int = 100,
    volume_ratio_threshold: float = 1.5,
    use_intraday: bool = False,
    intraday_limit: int = 30,
) -> dict:
    ranking = ranking_service.get_watchlist_group_latest_ranking(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by="score",
        sort_order="desc",
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
        limit=calculation_limit,
        volume_ratio_threshold=volume_ratio_threshold,
        use_intraday=use_intraday,
        intraday_limit=intraday_limit,
    )

    radar = build_watchlist_radar_from_ranking(
        ranking=ranking,
        include_children=include_children,
        mode=mode,
        max_results=max_results,
    )
    radar["group_id"] = radar.get("group_id") or group_id
    return radar
