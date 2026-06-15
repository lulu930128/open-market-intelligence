from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from numbers import Real

from sqlalchemy.orm import Session

from app.watchlists import ranking_service


ALLOWED_RADAR_MODES = {"action", "risk", "momentum", "all"}
HIGH_MOVE_PCT_THRESHOLD = 7.0

BUCKET_META = [
    {
        "key": "limit_move",
        "label": "漲跌停 / 急漲急跌",
        "description": "漲跌停或單日大幅波動，優先確認追價與停損風險。",
    },
    {
        "key": "risk",
        "label": "風險優先",
        "description": "跌破關鍵均線、弱勢趨勢或量增價跌，適合先檢查風控。",
    },
    {
        "key": "breakout",
        "label": "突破動能",
        "description": "突破 20 日高、重新站上 MA20 或動能交叉，適合追蹤延續性。",
    },
    {
        "key": "volume",
        "label": "量能異動",
        "description": "成交量明顯放大，需搭配價格方向判斷有效性。",
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
}
BREAKOUT_SIGNAL_KEYS = {
    "cross_above_ma20",
    "ema_bullish_cross",
    "adx_bull_trend",
    "donchian_breakout",
}
VOLUME_SIGNAL_KEYS = {
    "volume_price_up",
    "volume_price_down",
    "volume_expansion",
    "volume_above_ma5",
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
    "volume_price_down",
}
HIGH_MOMENTUM_SIGNAL_KEYS = {
    "cross_above_ma20",
    "ema_bullish_cross",
    "adx_bull_trend",
    "donchian_breakout",
    "volume_price_up",
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
        if limit_status == "limit_down" or (change_pct is not None and change_pct < 0):
            return "limit_move", _matched_keys(keys, RISK_SIGNAL_KEYS)

        return "limit_move", _matched_keys(
            keys,
            HIGH_MOMENTUM_SIGNAL_KEYS | MOMENTUM_SIGNAL_KEYS | VOLUME_SIGNAL_KEYS,
        )

    risk_keys = _matched_keys(keys, RISK_SIGNAL_KEYS)
    if risk_keys or score <= -3:
        return "risk", risk_keys

    breakout_keys = _matched_keys(keys, BREAKOUT_SIGNAL_KEYS)
    if breakout_keys:
        return "breakout", breakout_keys

    volume_keys = _matched_keys(keys, VOLUME_SIGNAL_KEYS)
    if volume_keys:
        return "volume", volume_keys

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

    if mode == "risk":
        return bucket in {"limit_move", "risk"}

    if mode == "momentum":
        return bucket in {"breakout", "volume", "pullback", "momentum"}

    return bucket not in {"quiet", "no_data", "error"}


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
    elif bucket == "risk":
        urgency = "high" if score <= -4 or keys.intersection(HIGH_RISK_SIGNAL_KEYS) else "medium"
    elif bucket == "breakout":
        urgency = "high" if score >= 4 or keys.intersection(HIGH_MOMENTUM_SIGNAL_KEYS) else "medium"
    elif bucket == "volume":
        urgency = "medium"
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
    elif limit_status == "limit_up":
        action = "確認是否續強或過熱"
    elif limit_status == "limit_down":
        action = "優先檢查停損與流動性"
    elif change_pct is not None and change_pct >= HIGH_MOVE_PCT_THRESHOLD:
        action = "留意追價與隔日回落風險"
    elif change_pct is not None and change_pct <= -HIGH_MOVE_PCT_THRESHOLD:
        action = "檢查是否破線或需降風險"
    elif bucket == "risk":
        action = "優先檢查風控"
    elif bucket == "breakout":
        action = "追蹤突破延續"
    elif bucket == "volume":
        action = "確認量價方向"
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


def _priority_score(row: dict, bucket: str, urgency: str, stale: bool) -> float:
    change_pct = _number(row.get("change_pct"))
    score = int(row.get("score", 0) or 0)
    signal_count = int(row.get("signal_count", 0) or 0)

    bucket_base = {
        "limit_move": 100,
        "risk": 90,
        "breakout": 80,
        "volume": 70,
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

    return bucket_base + urgency_bonus + (abs(score) * 3) + signal_count + change_bonus - stale_penalty


def _radar_item(row: dict, target_trade_date: date | None) -> dict:
    bucket, matched_signal_keys = _bucket_for_row(row)
    stale = _is_stale(row, target_trade_date)
    urgency = _urgency(row=row, bucket=bucket, stale=stale)
    priority_score = _priority_score(row=row, bucket=bucket, urgency=urgency, stale=stale)
    signal_keys = _signal_keys(row)
    bucket_meta = BUCKET_META_BY_KEY[bucket]
    row_trade_date = _parse_trade_date(row.get("time"))

    return {
        "rank": 0,
        "source_rank": row.get("rank"),
        "bucket": bucket,
        "bucket_label": bucket_meta["label"],
        "urgency": urgency,
        "priority_score": round(priority_score, 4),
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
        "signal_labels": _signal_labels(signal_keys),
        "primary_signal_key": row.get("primary_signal_key"),
        "primary_signal_label": row.get("primary_signal_label"),
        "stale": stale,
        "error_message": row.get("error_message"),
    }


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
