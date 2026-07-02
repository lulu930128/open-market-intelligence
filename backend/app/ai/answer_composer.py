from __future__ import annotations

from typing import Any

from app.ai import decision_engine


SUMMARY_LIMIT_DEFAULT = 3
ANALYSIS_HORIZON_LABELS = {
    "intraday": "盤中",
    "short": "短線",
    "swing": "中短線",
    "long": "長線",
}
ANALYSIS_HORIZON_LABELS_EN = {
    "intraday": "Intraday",
    "short": "Short term",
    "swing": "Swing",
    "long": "Long term",
}
ANALYSIS_HORIZON_LABELS_JA = {
    "intraday": "ザラ場",
    "short": "短期",
    "swing": "スイング",
    "long": "長期",
}
STANCE_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "mixed": "多空分歧",
    "insufficient_data": "資料不足",
}
STANCE_LABELS_EN = {
    "bullish": "Bullish",
    "bearish": "Bearish",
    "neutral": "Neutral",
    "mixed": "Mixed",
    "insufficient_data": "Insufficient data",
}
STANCE_LABELS_JA = {
    "bullish": "強気寄り",
    "bearish": "弱気寄り",
    "neutral": "中立",
    "mixed": "強弱混在",
    "insufficient_data": "データ不足",
}
CONFIDENCE_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}
CONFIDENCE_LABELS_EN = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
}
CONFIDENCE_LABELS_JA = {
    "low": "低",
    "medium": "中",
    "high": "高",
}
CONFIDENCE_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
}
CRITICAL_SOURCE_HEALTH_RESOURCES = {
    "stock_master",
    "market_daily_price",
    "us_daily_price",
}
DATA_LIMIT_WARNING_HINTS = (
    "missing",
    "stale",
    "incomplete",
    "unavailable",
    "failed",
    "資料",
    "缺",
    "不足",
    "不完整",
    "過期",
    "失敗",
)
NON_DATA_LIMIT_WARNING_PREFIXES = (
    "LLM analysis was generated on demand",
    "Intraday analysis horizon was requested without live intraday access",
)
LLM_SOFT_DATA_GAP_HINTS = (
    "missing",
    "unavailable",
    "intraday_trend",
    "缺少",
    "缺乏",
    "未提供",
    "未取得",
    "不可用",
    "資料不足",
)
LLM_INTRADAY_GAP_HINTS = (
    "intraday",
    "盤中",
    "即時",
    "成交",
    "快照",
)
SOURCE_HEALTH_PROBLEM_STATUSES = {
    "stale",
    "empty",
    "error",
    "unavailable",
    "partial",
}
SOURCE_HEALTH_STATUS_LABELS = {
    "stale": "落後",
    "empty": "無本地資料",
    "error": "讀取失敗",
    "unavailable": "不可用",
    "partial": "不完整",
}
SOURCE_HEALTH_STATUS_LABELS_EN = {
    "stale": "stale",
    "empty": "no local data",
    "error": "read failed",
    "unavailable": "unavailable",
    "partial": "partial",
}
SOURCE_HEALTH_STATUS_LABELS_JA = {
    "stale": "遅延",
    "empty": "ローカルデータなし",
    "error": "読み取り失敗",
    "unavailable": "利用不可",
    "partial": "不完全",
}
SOURCE_HEALTH_RESOURCE_LABELS = {
    "stock_master": "股票主檔",
    "market_daily_price": "日收盤",
    "market_daily_price.time": "日收盤時間",
    "institutional_trade_daily": "法人買賣超",
    "margin_trading_daily": "融資融券",
    "broker_branch_trade_daily": "券商分點",
    "shareholding_distribution_weekly": "股權分散",
    "monthly_revenue": "月營收",
    "financial_metric_quarterly": "季財務",
    "market_chip_daily": "大盤籌碼",
    "intraday_trend": "盤中資料",
    "us_daily_price": "美股日線",
    "us_overnight_tw_impact": "美股隔夜影響",
}
SOURCE_HEALTH_RESOURCE_LABELS_EN = {
    "stock_master": "stock master",
    "market_daily_price": "daily price",
    "market_daily_price.time": "daily price timestamp",
    "institutional_trade_daily": "institutional trade",
    "margin_trading_daily": "margin trading",
    "broker_branch_trade_daily": "broker branch trade",
    "shareholding_distribution_weekly": "shareholding distribution",
    "monthly_revenue": "monthly revenue",
    "financial_metric_quarterly": "quarterly financial metrics",
    "market_chip_daily": "market chip flow",
    "intraday_trend": "intraday data",
    "us_daily_price": "US daily price",
    "us_overnight_tw_impact": "US overnight impact",
}
SOURCE_HEALTH_RESOURCE_LABELS_JA = {
    "stock_master": "銘柄マスター",
    "market_daily_price": "日足価格",
    "market_daily_price.time": "日足価格の時刻",
    "institutional_trade_daily": "法人売買超",
    "margin_trading_daily": "信用取引",
    "broker_branch_trade_daily": "証券会社支店別売買",
    "shareholding_distribution_weekly": "株主分布",
    "monthly_revenue": "月次売上",
    "financial_metric_quarterly": "四半期財務指標",
    "market_chip_daily": "市場需給",
    "intraday_trend": "日中データ",
    "us_daily_price": "米国日足価格",
    "us_overnight_tw_impact": "米国市場の一晩影響",
}
CONSUMER_TEXT_LABELS = {
    "zh-TW": {
        "conclusion": "結論",
        "direction": "方向",
        "confidence": "信心",
        "summary": "重點",
        "actions": "怎麼做",
        "scenarios": "情境",
        "counter_evidence": "反證",
        "risks": "風險",
        "data_limits": "資料限制",
        "separator": "：",
        "joiner": " / ",
    },
    "en-US": {
        "conclusion": "Conclusion",
        "direction": "Direction",
        "confidence": "Confidence",
        "summary": "Key points",
        "actions": "What to do",
        "scenarios": "Scenarios",
        "counter_evidence": "Counter evidence",
        "risks": "Risks",
        "data_limits": "Data limits",
        "separator": ": ",
        "joiner": " / ",
    },
    "ja-JP": {
        "conclusion": "結論",
        "direction": "方向",
        "confidence": "信頼度",
        "summary": "要点",
        "actions": "対応",
        "scenarios": "シナリオ",
        "counter_evidence": "反証",
        "risks": "リスク",
        "data_limits": "データ制約",
        "separator": "：",
        "joiner": " / ",
    },
}
DETAIL_SECTION_LABELS = {
    "zh-TW": {
        "conclusion": "結論",
        "key_observations": "重點",
        "interpretation": "解讀",
        "risks": "風險",
        "missing_data": "資料限制",
        "next_checks": "下一步",
        "disclaimer": "限制",
    },
    "en-US": {
        "conclusion": "Conclusion",
        "key_observations": "Key points",
        "interpretation": "Interpretation",
        "risks": "Risks",
        "missing_data": "Data limits",
        "next_checks": "Next checks",
        "disclaimer": "Limit",
    },
    "ja-JP": {
        "conclusion": "結論",
        "key_observations": "要点",
        "interpretation": "解釈",
        "risks": "リスク",
        "missing_data": "データ制約",
        "next_checks": "次の確認",
        "disclaimer": "制約",
    },
}
UNDECIDED_LABELS = {
    "zh-TW": "未定",
    "en-US": "Undecided",
    "ja-JP": "未定",
}
TARGET_FALLBACK_LABELS = {
    "zh-TW": "目前標的",
    "en-US": "Current target",
    "ja-JP": "現在の対象",
}
RADAR_BUCKET_LABELS_EN = {
    "limit_up_lock": "Limit-up lock",
    "surge_up": "Sharp surge",
    "limit_down_liquidity": "Limit-down liquidity",
    "selloff_risk": "Selloff risk",
    "overheated": "Overheated",
    "volatility_risk": "Volatility risk",
    "support_break": "Support break",
    "volume_down": "Volume-price weak",
    "bearish_momentum": "Momentum weakening",
    "breakout_high": "Breakout confirm",
    "trend_reclaim": "Trend reclaim",
    "volume_up": "Volume-price attack",
    "volume": "Volume anomaly",
    "compression_watch": "Compression watch",
    "pullback": "Strong pullback",
    "momentum": "Trend continuation",
    "watch": "Watch",
    "quiet": "No clear signal",
    "no_data": "Missing data",
    "error": "Data error",
    "breakout": "Breakout",
    "risk": "Risk",
    "limit_move": "Limit move",
    "limit_up_move": "Limit-up move",
    "limit_down_move": "Limit-down move",
}
RADAR_BUCKET_LABELS_JA = {
    "limit_up_lock": "ストップ高継続",
    "surge_up": "急騰",
    "limit_down_liquidity": "ストップ安流動性",
    "selloff_risk": "急落リスク",
    "overheated": "過熱",
    "volatility_risk": "ボラティリティリスク",
    "support_break": "サポート割れ",
    "volume_down": "出来高を伴う弱さ",
    "bearish_momentum": "モメンタム低下",
    "breakout_high": "ブレイク確認",
    "trend_reclaim": "トレンド回復",
    "volume_up": "出来高を伴う上昇",
    "volume": "出来高異常",
    "compression_watch": "収縮監視",
    "pullback": "強い押し目",
    "momentum": "トレンド継続",
    "watch": "監視",
    "quiet": "明確なシグナルなし",
    "no_data": "データ不足",
    "error": "データエラー",
    "breakout": "ブレイク",
    "risk": "リスク",
    "limit_move": "値幅制限",
    "limit_up_move": "ストップ高",
    "limit_down_move": "ストップ安",
}
RADAR_ACTION_LABELS_EN = {
    "limit_up_lock": "Confirm continuation or overheating",
    "surge_up": "Watch chase risk and next-day pullback",
    "limit_down_liquidity": "Check stop-loss and liquidity first",
    "selloff_risk": "Check for a line break or reduce risk",
    "overheated": "Control chasing and watch cooling",
    "volatility_risk": "Widen stops and reduce chase entries",
    "support_break": "Check support and stop-loss",
    "volume_down": "Confirm whether selling pressure continues",
    "bearish_momentum": "Check risk controls first",
    "risk": "Check risk controls first",
    "breakout_high": "Track breakout continuation",
    "trend_reclaim": "Confirm the strength reclaim holds",
    "volume_up": "Track the volume-price attack",
    "breakout": "Track breakout continuation",
    "volume": "Confirm volume-price direction",
    "compression_watch": "Wait for volume breakout or breakdown",
    "pullback": "Watch the pullback location",
    "momentum": "Track trend continuation",
    "watch": "General tracking",
    "quiet": "Low-priority watch",
    "no_data": "Backfill data first",
    "error": "Resolve data errors first",
    "limit_move": "Check continuation and risk first",
    "limit_up_move": "Confirm continuation or overheating",
    "limit_down_move": "Check stop-loss and liquidity first",
}
RADAR_ACTION_LABELS_JA = {
    "limit_up_lock": "継続性または過熱を確認",
    "surge_up": "追いかけ買いと翌日反落リスクを確認",
    "limit_down_liquidity": "損切りと流動性を優先確認",
    "selloff_risk": "支持線割れやリスク低下を確認",
    "overheated": "追いかけ買いを抑え、過熱冷却を確認",
    "volatility_risk": "損切り幅を広げ、追いかけ買いを抑える",
    "support_break": "サポートと損切り条件を確認",
    "volume_down": "売り圧力が続くか確認",
    "bearish_momentum": "リスク管理を優先確認",
    "risk": "リスク管理を優先確認",
    "breakout_high": "ブレイク継続を追跡",
    "trend_reclaim": "回復が維持されるか確認",
    "volume_up": "出来高を伴う上昇を追跡",
    "breakout": "ブレイク継続を追跡",
    "volume": "出来高と価格方向を確認",
    "compression_watch": "出来高を伴う上抜けまたは下抜けを待つ",
    "pullback": "押し目位置を確認",
    "momentum": "トレンド継続を追跡",
    "watch": "通常監視",
    "quiet": "低優先で監視",
    "no_data": "先にデータを補完",
    "error": "先にデータエラーを解消",
    "limit_move": "継続性とリスクを先に確認",
    "limit_up_move": "継続性または過熱を確認",
    "limit_down_move": "損切りと流動性を優先確認",
}
RADAR_SIGNAL_LABELS_EN = {
    "price_up": "Up",
    "price_down": "Down",
    "above_ma20": "Above MA20",
    "below_ma20": "Below MA20",
    "cross_above_ma20": "Reclaimed MA20",
    "cross_below_ma20": "Broke below MA20",
    "ema_bullish_cross": "EMA bullish cross",
    "ema_bearish_cross": "EMA bearish cross",
    "macd_positive": "MACD bullish",
    "macd_negative": "MACD bearish",
    "adx_bull_trend": "ADX bullish trend",
    "adx_bear_trend": "ADX bearish trend",
    "donchian_breakout": "20-day high breakout",
    "donchian_breakdown": "20-day low breakdown",
    "rsi_overheated": "RSI overheated",
    "mfi_inflow": "MFI inflow",
    "mfi_outflow": "MFI weak",
    "roc_positive": "ROC positive momentum",
    "roc_negative": "ROC negative momentum",
    "volume_price_up": "Volume up with price up",
    "volume_price_down": "Volume up with price down",
    "volume_expansion": "Volume expansion",
    "volume_above_ma5": "Volume above 5-day average",
    "structure_support_break": "20-day support break",
    "structure_resistance_breakout": "20-day resistance breakout",
    "bollinger_breakout": "Bollinger upper breakout",
    "bollinger_breakdown": "Bollinger lower breakdown",
    "bollinger_squeeze": "Bollinger squeeze",
    "kd_bullish_cross": "KD bullish cross",
    "kd_bearish_cross": "KD bearish cross",
    "atr_high_volatility": "ATR high volatility",
    "atr_expanding": "ATR expansion",
}
RADAR_SIGNAL_LABELS_JA = {
    "price_up": "上昇",
    "price_down": "下落",
    "above_ma20": "MA20上",
    "below_ma20": "MA20下",
    "cross_above_ma20": "MA20回復",
    "cross_below_ma20": "MA20割れ",
    "ema_bullish_cross": "EMA強気クロス",
    "ema_bearish_cross": "EMA弱気クロス",
    "macd_positive": "MACD強気",
    "macd_negative": "MACD弱気",
    "adx_bull_trend": "ADX強気トレンド",
    "adx_bear_trend": "ADX弱気トレンド",
    "donchian_breakout": "20日高値ブレイク",
    "donchian_breakdown": "20日安値割れ",
    "rsi_overheated": "RSI過熱",
    "mfi_inflow": "MFI流入",
    "mfi_outflow": "MFI弱含み",
    "roc_positive": "ROC正のモメンタム",
    "roc_negative": "ROC負のモメンタム",
    "volume_price_up": "出来高増かつ価格上昇",
    "volume_price_down": "出来高増かつ価格下落",
    "volume_expansion": "出来高拡大",
    "volume_above_ma5": "出来高が5日平均超え",
    "structure_support_break": "20日サポート割れ",
    "structure_resistance_breakout": "20日抵抗線ブレイク",
    "bollinger_breakout": "ボリンジャー上限ブレイク",
    "bollinger_breakdown": "ボリンジャー下限割れ",
    "bollinger_squeeze": "ボリンジャー収縮",
    "kd_bullish_cross": "KD強気クロス",
    "kd_bearish_cross": "KD弱気クロス",
    "atr_high_volatility": "ATR高ボラティリティ",
    "atr_expanding": "ATR拡大",
}
RADAR_SIGNAL_TEXT_EN = {
    "突破 20 日高": "20-day high breakout",
    "跌破 20 日低": "20-day low breakdown",
    "MACD偏多": "MACD bullish",
    "MACD 偏多": "MACD bullish",
    "MACD偏空": "MACD bearish",
    "量價上攻": "Volume-price attack",
    "動能轉弱": "Momentum weakening",
    "突破動能": "Breakout momentum",
    "風險優先": "Risk first",
    "上漲": "Up",
    "下跌": "Down",
    "跌破 MA20": "Below MA20",
    "重新站上 MA20": "Reclaimed MA20",
    "量能放大": "Volume expansion",
    "站在 MA20 之上": "Above MA20",
}
RADAR_SIGNAL_TEXT_JA = {
    "突破 20 日高": "20日高値ブレイク",
    "跌破 20 日低": "20日安値割れ",
    "MACD偏多": "MACD強気",
    "MACD 偏多": "MACD強気",
    "MACD偏空": "MACD弱気",
    "量價上攻": "出来高を伴う上昇",
    "動能轉弱": "モメンタム低下",
    "突破動能": "ブレイクモメンタム",
    "風險優先": "リスク優先",
    "上漲": "上昇",
    "下跌": "下落",
    "跌破 MA20": "MA20割れ",
    "重新站上 MA20": "MA20回復",
    "量能放大": "出来高拡大",
    "站在 MA20 之上": "MA20上",
}
RADAR_STANCE_LABELS_EN = {
    "結構偏多": "Structurally bullish",
    "偏多": "Bullish",
    "偏空": "Bearish",
    "中性": "Neutral",
    "多空分歧": "Mixed",
}
RADAR_STANCE_LABELS_JA = {
    "結構偏多": "構造は強気寄り",
    "偏多": "強気寄り",
    "偏空": "弱気寄り",
    "中性": "中立",
    "多空分歧": "強弱混在",
}


def text_value(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def text_list(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []

    texts: list[str] = []
    for item in value:
        text = text_value(item)
        if text is None:
            continue
        if text in texts:
            continue
        texts.append(text)
        if limit is not None and len(texts) >= limit:
            break
    return texts


def append_unique_texts(target: list[str], values: list[str], *, limit: int) -> None:
    for value in values:
        if value in target:
            continue
        target.append(value)
        if len(target) >= limit:
            return


def response_locale(response_preferences: dict[str, Any] | None = None) -> str:
    if not isinstance(response_preferences, dict):
        return "zh-TW"

    locale = (
        text_value(response_preferences.get("effective_locale"))
        or text_value(response_preferences.get("requested_locale"))
        or text_value(response_preferences.get("locale"))
    )
    if locale in {"en-US", "ja-JP"}:
        return locale
    return "zh-TW"


def response_is_english(response_preferences: dict[str, Any] | None = None) -> bool:
    return response_locale(response_preferences) == "en-US"


def response_is_japanese(response_preferences: dict[str, Any] | None = None) -> bool:
    return response_locale(response_preferences) == "ja-JP"


def text_labels(response_preferences: dict[str, Any] | None = None) -> dict[str, str]:
    return CONSUMER_TEXT_LABELS[response_locale(response_preferences)]


def detail_labels(response_preferences: dict[str, Any] | None = None) -> dict[str, str]:
    return DETAIL_SECTION_LABELS[response_locale(response_preferences)]


def undecided_label(response_preferences: dict[str, Any] | None = None) -> str:
    return UNDECIDED_LABELS[response_locale(response_preferences)]


def target_fallback_label(response_preferences: dict[str, Any] | None = None) -> str:
    return TARGET_FALLBACK_LABELS[response_locale(response_preferences)]


def analysis_horizon_label(
    key: Any,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    text = str(key)
    locale = response_locale(response_preferences)
    labels = {
        "en-US": ANALYSIS_HORIZON_LABELS_EN,
        "ja-JP": ANALYSIS_HORIZON_LABELS_JA,
    }.get(locale, ANALYSIS_HORIZON_LABELS)
    return labels.get(text, text)


def stance_label(
    stance: Any,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    text = text_value(stance)
    if not text:
        return undecided_label(response_preferences)

    locale = response_locale(response_preferences)
    labels = {
        "en-US": STANCE_LABELS_EN,
        "ja-JP": STANCE_LABELS_JA,
    }.get(locale, STANCE_LABELS)
    return labels.get(text, text)


def confidence_label(
    confidence: Any,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    text = text_value(confidence)
    if not text:
        return undecided_label(response_preferences)

    locale = response_locale(response_preferences)
    labels = {
        "en-US": CONFIDENCE_LABELS_EN,
        "ja-JP": CONFIDENCE_LABELS_JA,
    }.get(locale, CONFIDENCE_LABELS)
    return labels.get(text, text)


def pct_text(value: Any) -> str | None:
    number = decision_engine.numeric_score(value)
    if number is None:
        return None
    return decision_engine.format_pct_value(number)


def english_revenue_summary(revenue: dict[str, Any]) -> str | None:
    if not isinstance(revenue, dict):
        return None

    parts = []
    period = text_value(revenue.get("period"))
    parts.append(f"{period} revenue" if period else "Latest revenue")
    yoy = pct_text(revenue.get("year_over_year_pct"))
    mom = pct_text(revenue.get("month_over_month_pct"))
    cumulative_yoy = pct_text(revenue.get("cumulative_year_over_year_pct"))
    if yoy:
        parts.append(f"YoY {yoy}")
    if mom:
        parts.append(f"MoM {mom}")
    if cumulative_yoy:
        parts.append(f"cumulative YoY {cumulative_yoy}")
    return ", ".join(parts) + "." if len(parts) > 1 else None


def japanese_revenue_summary(revenue: dict[str, Any]) -> str | None:
    if not isinstance(revenue, dict):
        return None

    parts = []
    period = text_value(revenue.get("period"))
    parts.append(f"{period}の売上" if period else "最新売上")
    yoy = pct_text(revenue.get("year_over_year_pct"))
    mom = pct_text(revenue.get("month_over_month_pct"))
    cumulative_yoy = pct_text(revenue.get("cumulative_year_over_year_pct"))
    if yoy:
        parts.append(f"前年比 {yoy}")
    if mom:
        parts.append(f"前月比 {mom}")
    if cumulative_yoy:
        parts.append(f"累計前年比 {cumulative_yoy}")
    return "、".join(parts) + "。" if len(parts) > 1 else None


def english_volatility_summary(volatility: dict[str, Any]) -> str | None:
    if not isinstance(volatility, dict):
        return None

    label = text_value(volatility.get("label"))
    if label == "high":
        label_text = "high volatility"
    elif label == "elevated":
        label_text = "elevated volatility"
    elif label == "normal":
        label_text = "normal volatility"
    else:
        return None

    lookback = decision_engine.numeric_score(volatility.get("lookback_days"))
    window = f"Recent {int(lookback)} days" if lookback is not None else "Recent days"
    parts = [f"{window} show {label_text}"]
    max_abs_change = pct_text(volatility.get("max_abs_change_pct"))
    range_pct = pct_text(volatility.get("range_pct"))
    large_move_days = decision_engine.numeric_score(volatility.get("large_move_days"))
    if max_abs_change:
        parts.append(f"max one-day move about {max_abs_change}")
    if range_pct:
        parts.append(f"range about {range_pct}")
    if large_move_days:
        parts.append(f"{int(large_move_days)} days moved more than 5%")
    return ", ".join(parts) + "."


def japanese_volatility_summary(volatility: dict[str, Any]) -> str | None:
    if not isinstance(volatility, dict):
        return None

    label = text_value(volatility.get("label"))
    if label == "high":
        label_text = "高ボラティリティ"
    elif label == "elevated":
        label_text = "やや高いボラティリティ"
    elif label == "normal":
        label_text = "通常のボラティリティ"
    else:
        return None

    lookback = decision_engine.numeric_score(volatility.get("lookback_days"))
    window = f"直近 {int(lookback)} 日" if lookback is not None else "直近数日"
    parts = [f"{window}は{label_text}"]
    max_abs_change = pct_text(volatility.get("max_abs_change_pct"))
    range_pct = pct_text(volatility.get("range_pct"))
    large_move_days = decision_engine.numeric_score(volatility.get("large_move_days"))
    if max_abs_change:
        parts.append(f"最大日次変動は約 {max_abs_change}")
    if range_pct:
        parts.append(f"レンジは約 {range_pct}")
    if large_move_days:
        parts.append(f"5%超の変動が {int(large_move_days)} 日")
    return "、".join(parts) + "。"


def english_indicator_quality_warnings(indicator_quality: dict[str, Any]) -> list[str]:
    if not isinstance(indicator_quality, dict):
        return []

    lines: list[str] = []
    macd = indicator_quality.get("macd") if isinstance(indicator_quality.get("macd"), dict) else {}
    if macd.get("is_consistent") is False:
        lines.append("MACD histogram does not match MACD minus signal; verify field definitions or sign convention.")
    elif macd.get("tone") == "negative":
        lines.append("MACD histogram is negative.")
    return lines


def japanese_indicator_quality_warnings(indicator_quality: dict[str, Any]) -> list[str]:
    if not isinstance(indicator_quality, dict):
        return []

    lines: list[str] = []
    macd = indicator_quality.get("macd") if isinstance(indicator_quality.get("macd"), dict) else {}
    if macd.get("is_consistent") is False:
        lines.append("MACDヒストグラムがMACD minus signalと一致しません。項目定義または符号を確認してください。")
    elif macd.get("tone") == "negative":
        lines.append("MACDヒストグラムはマイナスです。")
    return lines


def english_data_limit_text(value: Any) -> str | None:
    text = text_value(value)
    if not text:
        return None

    suffix = " 尚缺或不完整。"
    if text.endswith(suffix):
        key = text.removesuffix(suffix)
        label = SOURCE_HEALTH_RESOURCE_LABELS_EN.get(key, key)
        return f"{label} is missing or incomplete."
    return text


def japanese_data_limit_text(value: Any) -> str | None:
    text = text_value(value)
    if not text:
        return None

    suffix = " 尚缺或不完整。"
    if text.endswith(suffix):
        key = text.removesuffix(suffix)
        label = SOURCE_HEALTH_RESOURCE_LABELS_JA.get(key, key)
        return f"{label}が不足、または不完全です。"
    return text


def radar_bucket_label(
    bucket: Any,
    fallback: Any = None,
    response_preferences: dict[str, Any] | None = None,
) -> str | None:
    bucket_key = text_value(bucket)
    fallback_text = text_value(fallback)
    if response_is_english(response_preferences):
        return RADAR_BUCKET_LABELS_EN.get(bucket_key or "", fallback_text or bucket_key)
    if response_is_japanese(response_preferences):
        return RADAR_BUCKET_LABELS_JA.get(bucket_key or "", fallback_text or bucket_key)
    return fallback_text or bucket_key


def radar_action_label(
    row: dict[str, Any],
    response_preferences: dict[str, Any] | None = None,
) -> str | None:
    bucket = text_value(row.get("bucket"))
    fallback = text_value(row.get("action_label"))
    if response_is_english(response_preferences):
        action = RADAR_ACTION_LABELS_EN.get(bucket or "", fallback)
        if row.get("stale") and action and bucket not in {"error", "no_data"}:
            return f"{action}, but confirm the data update first"
        return action
    if response_is_japanese(response_preferences):
        action = RADAR_ACTION_LABELS_JA.get(bucket or "", fallback)
        if row.get("stale") and action and bucket not in {"error", "no_data"}:
            return f"{action}。ただし先にデータ更新を確認してください"
        return action
    return fallback


def radar_signal_label(
    row: dict[str, Any],
    response_preferences: dict[str, Any] | None = None,
) -> str | None:
    fallback = text_value(row.get("primary_signal_label"))
    if response_is_english(response_preferences):
        signal_key = text_value(row.get("primary_signal_key"))
        return (
            RADAR_SIGNAL_LABELS_EN.get(signal_key or "")
            or RADAR_SIGNAL_TEXT_EN.get(fallback or "")
            or fallback
        )
    if response_is_japanese(response_preferences):
        signal_key = text_value(row.get("primary_signal_key"))
        return (
            RADAR_SIGNAL_LABELS_JA.get(signal_key or "")
            or RADAR_SIGNAL_TEXT_JA.get(fallback or "")
            or fallback
        )
    return fallback


def radar_stance_label(
    value: Any,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    text = text_value(value)
    if not text:
        return undecided_label(response_preferences)
    if response_is_english(response_preferences):
        return RADAR_STANCE_LABELS_EN.get(text, text)
    if response_is_japanese(response_preferences):
        return RADAR_STANCE_LABELS_JA.get(text, text)
    return text


def consumer_detail_from_llm_report(
    report: dict[str, Any],
    *,
    missing_data_label: str | None = None,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    labels = detail_labels(response_preferences)
    separator = ": " if response_is_english(response_preferences) else "："
    heading_separator = separator.rstrip()
    missing_label = missing_data_label or labels["missing_data"]
    lines: list[str] = []
    headline = text_value(report.get("headline"))
    if headline:
        lines.append(f"{labels['conclusion']}{separator}{headline}")

    sections = (
        ("key_observations", labels["key_observations"]),
        ("interpretation", labels["interpretation"]),
        ("risks", labels["risks"]),
        ("missing_data", missing_label),
        ("next_checks", labels["next_checks"]),
    )
    for key, label in sections:
        items = text_list(report.get(key))
        if not items:
            continue
        lines.append(f"{label}{heading_separator}")
        lines.extend(f"- {item}" for item in items)

    disclaimer = text_value(report.get("disclaimer"))
    if disclaimer:
        lines.append(f"{labels['disclaimer']}{separator}{disclaimer}")
    return "\n".join(lines)


def consumer_text(
    answer: dict[str, Any],
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    labels = text_labels(response_preferences)
    separator = labels["separator"]
    heading_separator = separator.rstrip()
    lines: list[str] = []
    headline = text_value(answer.get("headline"))
    if headline:
        lines.append(f"{labels['conclusion']}{separator}{headline}")

    stance = text_value(answer.get("stance_label"))
    confidence = text_value(answer.get("confidence_label"))
    if stance or confidence:
        parts = []
        if stance:
            parts.append(f"{labels['direction']}{separator}{stance}")
        if confidence:
            parts.append(f"{labels['confidence']}{separator}{confidence}")
        lines.append(labels["joiner"].join(parts))

    summary = text_list(answer.get("summary"), limit=summary_limit)
    if summary:
        lines.append(f"{labels['summary']}{heading_separator}")
        lines.extend(f"- {item}" for item in summary)

    actions = answer.get("action_plan")
    if isinstance(actions, list) and actions:
        lines.append(f"{labels['actions']}{heading_separator}")
        for item in actions[:summary_limit]:
            if not isinstance(item, dict):
                continue
            label = text_value(item.get("label"))
            text = text_value(item.get("text"))
            if text:
                lines.append(f"- {label + separator if label else ''}{text}")

    scenarios = answer.get("scenarios")
    if isinstance(scenarios, list) and scenarios:
        lines.append(f"{labels['scenarios']}{heading_separator}")
        for item in scenarios[:summary_limit]:
            if not isinstance(item, dict):
                continue
            label = text_value(item.get("label"))
            text = text_value(item.get("text"))
            if text:
                lines.append(f"- {label + separator if label else ''}{text}")

    counter_evidence = text_list(answer.get("counter_evidence"), limit=2)
    if counter_evidence:
        lines.append(f"{labels['counter_evidence']}{heading_separator}")
        lines.extend(f"- {item}" for item in counter_evidence)

    risks = text_list(answer.get("risks"), limit=2)
    if risks:
        lines.append(f"{labels['risks']}{heading_separator}")
        lines.extend(f"- {item}" for item in risks)

    data_limits = text_list(answer.get("data_limits"), limit=2)
    if data_limits:
        lines.append(f"{labels['data_limits']}{heading_separator}")
        lines.extend(f"- {item}" for item in data_limits)

    return "\n".join(lines)


def warning_is_data_limit(value: Any) -> bool:
    text = text_value(value)
    if not text:
        return False
    if any(text.startswith(prefix) for prefix in NON_DATA_LIMIT_WARNING_PREFIXES):
        return False
    lowered = text.lower()
    return any(hint in lowered for hint in DATA_LIMIT_WARNING_HINTS)


def source_health_resource_label(
    value: Any,
    *,
    response_preferences: dict[str, Any] | None = None,
) -> str:
    key = text_value(value) or ""
    base_key = key.split(".", 1)[0]
    locale = response_locale(response_preferences)
    labels = {
        "en-US": SOURCE_HEALTH_RESOURCE_LABELS_EN,
        "ja-JP": SOURCE_HEALTH_RESOURCE_LABELS_JA,
    }.get(locale, SOURCE_HEALTH_RESOURCE_LABELS)
    return labels.get(key) or labels.get(base_key) or key or (
        "data source"
        if locale == "en-US"
        else "データソース"
        if locale == "ja-JP"
        else "資料來源"
    )


def human_missing_data_limit(
    missing: list[Any],
    *,
    response_preferences: dict[str, Any] | None = None,
) -> str | None:
    labels = [
        source_health_resource_label(item, response_preferences=response_preferences)
        for item in missing
        if text_value(item)
    ]
    labels = list(dict.fromkeys(labels))
    if not labels:
        return None

    locale = response_locale(response_preferences)
    shown = labels[:4]
    remainder = len(labels) - len(shown)
    if locale == "en-US":
        detail = ", ".join(shown)
        if remainder > 0:
            detail += f", and {remainder} more"
        return f"Missing or stale data: {detail}. Keep the conclusion flexible."
    if locale == "ja-JP":
        detail = "、".join(shown)
        if remainder > 0:
            detail += f" ほか {remainder} 件"
        return f"不足または遅延データ：{detail}。結論は柔軟に扱ってください。"

    detail = "、".join(shown)
    if remainder > 0:
        detail += f" 等 {remainder} 項"
    return f"資料缺口或落後：{detail}；結論需保留彈性。"


def localized_data_limit_warning(
    value: Any,
    *,
    response_preferences: dict[str, Any] | None = None,
) -> str | None:
    text = text_value(value)
    if not text or not warning_is_data_limit(text):
        return None

    affected_marker = "affected datasets:"
    if text.startswith("Local OMI data is incomplete") and affected_marker in text:
        dataset_text = text.split(affected_marker, 1)[1].split(".", 1)[0]
        datasets = [item.strip() for item in dataset_text.split(",") if item.strip()]
        labels = [
            source_health_resource_label(item, response_preferences=response_preferences)
            for item in datasets
        ]
        labels = list(dict.fromkeys(labels))
        if labels:
            locale = response_locale(response_preferences)
            if locale == "en-US":
                return (
                    "Local OMI data is incomplete: "
                    + ", ".join(labels)
                    + ". Refresh before relying on the conclusion."
                )
            if locale == "ja-JP":
                return (
                    "ローカル OMI データが未更新です："
                    + "、".join(labels)
                    + "。結論に使う前に更新してください。"
                )
            return (
                "本地 OMI 資料尚未完整更新："
                + "、".join(labels)
                + "；刷新後再依賴結論。"
            )

    return text


def llm_text_is_soft_data_gap(value: Any) -> bool:
    text = text_value(value)
    if not text:
        return False
    lowered = text.lower()
    if any(hint in lowered for hint in LLM_SOFT_DATA_GAP_HINTS):
        return True
    if "無法確認" in text and any(hint in lowered for hint in LLM_INTRADAY_GAP_HINTS):
        return True
    return False


def filter_soft_data_gap_texts(values: list[str], *, has_backend_missing: bool) -> list[str]:
    if has_backend_missing:
        return values
    return [value for value in values if not llm_text_is_soft_data_gap(value)]


def generic_data_limits(
    *,
    missing: list[Any],
    warnings: list[Any],
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    limits: list[str] = []
    if missing:
        missing_limit = human_missing_data_limit(
            missing,
            response_preferences=response_preferences,
        )
        if missing_limit:
            limits.append(missing_limit)
    append_unique_texts(
        limits,
        [
            text
            for warning in text_list(warnings, limit=4)
            if (text := localized_data_limit_warning(
                warning,
                response_preferences=response_preferences,
            ))
        ],
        limit=3,
    )
    return limits


def source_health_data_limits(
    source_health: Any,
    *,
    limit: int = 3,
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(source_health, dict):
        return []

    locale = response_locale(response_preferences)
    english = locale == "en-US"
    japanese = locale == "ja-JP"
    entries = source_health.get("entries")
    if not isinstance(entries, list):
        return []

    limits: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("required") is False:
            continue

        status = text_value(entry.get("status"))
        if status not in SOURCE_HEALTH_PROBLEM_STATUSES:
            continue

        resource = text_value(entry.get("resource"))
        resource_labels = {
            "en-US": SOURCE_HEALTH_RESOURCE_LABELS_EN,
            "ja-JP": SOURCE_HEALTH_RESOURCE_LABELS_JA,
        }.get(locale, SOURCE_HEALTH_RESOURCE_LABELS)
        label = (
            resource_labels.get(resource or "")
            or text_value(entry.get("label"))
            or resource
            or ("data source" if english else "データソース" if japanese else "資料來源")
        )
        latest = text_value(entry.get("latest_data_date")) or text_value(entry.get("latest_data_key"))
        expected = text_value(entry.get("expected_data_date"))

        if status == "stale":
            if english:
                if latest and expected:
                    message = f"{label} data is stale: latest {latest}, expected {expected}."
                elif latest:
                    message = f"{label} data may be out of date: latest {latest}."
                else:
                    message = f"{label} data may be stale; refresh before relying on the conclusion."
            elif japanese:
                if latest and expected:
                    message = f"{label}データは遅延しています：最新 {latest}、想定 {expected}。"
                elif latest:
                    message = f"{label}データは古い可能性があります：最新 {latest}。"
                else:
                    message = f"{label}データは古い可能性があります。結論に使う前に更新を確認してください。"
            else:
                if latest and expected:
                    message = f"{label}資料落後：最新 {latest}，預期 {expected}。"
                elif latest:
                    message = f"{label}資料可能過期：最新 {latest}。"
                else:
                    message = f"{label}資料可能過期，需重新確認。"
        elif status == "empty":
            if english:
                message = f"{label} currently has no local data."
            elif japanese:
                message = f"{label}は現在ローカルデータがありません。"
            else:
                message = f"{label}目前沒有本地資料。"
        else:
            status_labels = {
                "en-US": SOURCE_HEALTH_STATUS_LABELS_EN,
                "ja-JP": SOURCE_HEALTH_STATUS_LABELS_JA,
            }.get(locale, SOURCE_HEALTH_STATUS_LABELS)
            status_label = status_labels.get(status, status)
            if english:
                message = f"{label} data status is {status_label}; keep the conclusion flexible."
            elif japanese:
                message = f"{label}データ状態は{status_label}です。結論は柔軟に扱ってください。"
            else:
                message = f"{label}資料狀態為{status_label}，結論需保留彈性。"

        if message not in limits:
            limits.append(message)
        if len(limits) >= limit:
            break

    return limits


def confidence_cap_from_evidence(
    *,
    analysis_digest: dict[str, Any],
    missing: list[Any] | None = None,
    warnings: list[Any] | None = None,
    response_preferences: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    caps: list[str] = []
    reasons: list[str] = []

    source_health = analysis_digest.get("source_health")
    if isinstance(source_health, dict):
        entries = source_health.get("entries")
        problem_entries = []
        critical_entries = []
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("required") is False:
                    continue
                status = text_value(entry.get("status"))
                if status not in SOURCE_HEALTH_PROBLEM_STATUSES:
                    continue
                problem_entries.append(entry)
                resource = text_value(entry.get("resource"))
                if resource in CRITICAL_SOURCE_HEALTH_RESOURCES or status in {"empty", "error", "unavailable"}:
                    critical_entries.append(entry)

        if critical_entries or len(problem_entries) >= 2:
            caps.append("low")
            if english:
                reasons.append("Critical source data has gaps, so confidence is capped at low.")
            elif japanese:
                reasons.append("重要なデータソースに不足があるため、信頼度の上限を低にします。")
            else:
                reasons.append("關鍵資料來源有缺口，信心上限降為低。")
        elif problem_entries:
            caps.append("medium")
            if english:
                reasons.append("Some source data is stale or incomplete, so confidence is capped at medium.")
            elif japanese:
                reasons.append("一部データソースが遅延または不完全なため、信頼度の上限を中にします。")
            else:
                reasons.append("部分資料來源落後或不完整，信心上限降為中。")

    clean_missing = text_list(missing or [], limit=6)
    if clean_missing:
        critical_missing = any(
            item in CRITICAL_SOURCE_HEALTH_RESOURCES or item.startswith("market_daily_price")
            for item in clean_missing
        )
        caps.append("low" if critical_missing else "medium")
        if english:
            reasons.append("Required data is still missing, so this cannot be marked as high confidence.")
        elif japanese:
            reasons.append("必要なデータがまだ不足しているため、高信頼とは表示できません。")
        else:
            reasons.append("仍有資料缺口，不能標示為高信心。")

    data_warning_count = sum(1 for warning in text_list(warnings or [], limit=6) if warning_is_data_limit(warning))
    if data_warning_count:
        caps.append("medium")
        if english:
            reasons.append("Data warnings are still present, so confidence is capped at medium.")
        elif japanese:
            reasons.append("データ警告が残っているため、信頼度の上限を中にします。")
        else:
            reasons.append("資料警示仍存在，信心上限降為中。")

    source_refs = analysis_digest.get("source_refs")
    if isinstance(source_refs, list) and not source_refs:
        caps.append("low" if clean_missing or data_warning_count else "medium")
        if english:
            reasons.append("No traceable source references were attached, so this cannot be marked as high confidence.")
        elif japanese:
            reasons.append("追跡可能なデータソースが添付されていないため、高信頼とは表示できません。")
        else:
            reasons.append("未取得可追溯資料來源，不能標示為高信心。")

    if not caps:
        return None, []

    cap = min(caps, key=lambda value: CONFIDENCE_ORDER[value])
    return cap, list(dict.fromkeys(reasons))[:2]


def apply_confidence_cap(
    answer: dict[str, Any],
    *,
    analysis_digest: dict[str, Any],
    missing: list[Any] | None = None,
    warnings: list[Any] | None = None,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    data_limit_cap: int = 3,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cap, reasons = confidence_cap_from_evidence(
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        response_preferences=response_preferences,
    )
    if cap is None:
        return answer

    current = text_value(answer.get("confidence"))
    if current not in CONFIDENCE_ORDER:
        return answer
    if CONFIDENCE_ORDER[current] <= CONFIDENCE_ORDER[cap]:
        return answer

    next_answer = dict(answer)
    next_answer["confidence"] = cap
    next_answer["confidence_label"] = confidence_label(cap, response_preferences)
    current_limits = text_list(next_answer.get("data_limits"))
    if response_is_english(response_preferences):
        reason_prefix = "Data reliability limit: "
    elif response_is_japanese(response_preferences):
        reason_prefix = "データ信頼度の制約："
    else:
        reason_prefix = "資料可信度限制："
    capped_reasons = [f"{reason_prefix}{reason}" for reason in reasons]
    next_answer["data_limits"] = list(dict.fromkeys(current_limits + capped_reasons))
    next_answer["text"] = consumer_text(
        next_answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return next_answer


def append_source_health_data_limits(
    answer: dict[str, Any],
    *,
    analysis_digest: dict[str, Any],
    missing: list[Any] | None = None,
    warnings: list[Any] | None = None,
    limit: int = 3,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_limits = source_health_data_limits(
        analysis_digest.get("source_health"),
        limit=limit,
        response_preferences=response_preferences,
    )
    next_answer = dict(answer)

    if source_limits:
        current_limits = text_list(next_answer.get("data_limits"))
        combined_limits = list(dict.fromkeys(source_limits[:limit] + current_limits))
        if combined_limits != current_limits:
            next_answer["data_limits"] = combined_limits
            next_answer["text"] = consumer_text(
                next_answer,
                response_preferences=response_preferences,
            )

    return apply_confidence_cap(
        next_answer,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        data_limit_cap=limit,
        response_preferences=response_preferences,
    )


def digest_summary_lines(
    analysis_digest: dict[str, Any],
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    summary: list[str] = []
    append_unique_texts(
        summary,
        [
            text
            for text in (
                text_value(analysis_digest.get("display")),
                text_value(analysis_digest.get("selected_summary")),
            )
            if text
        ],
        limit=summary_limit,
    )
    scores = analysis_digest.get("scores") if isinstance(analysis_digest.get("scores"), dict) else {}
    if scores and len(summary) < summary_limit:
        score_parts = [
            f"{analysis_horizon_label(key, response_preferences)} {decision_engine.score_display(value) or '-'}"
            for key, value in scores.items()
            if value is not None
        ]
        if score_parts:
            if response_is_english(response_preferences):
                summary.append("Score: " + ", ".join(score_parts[:4]))
            elif response_is_japanese(response_preferences):
                summary.append("スコア：" + "、".join(score_parts[:4]))
            else:
                summary.append("分數：" + "、".join(score_parts[:4]))
    return summary[:summary_limit]


def technical_level_summary_lines(
    technical_levels: dict[str, Any],
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    if not response_is_english(response_preferences) and not response_is_japanese(response_preferences):
        return decision_engine.technical_level_summary_lines(
            technical_levels,
            summary_limit=summary_limit,
        )

    japanese = response_is_japanese(response_preferences)
    fields = decision_engine.technical_level_fields(technical_levels)
    if not fields:
        return []

    lines: list[str] = []
    entry_parts = []
    if fields.get("latest"):
        entry_parts.append(f"現在値 {fields['latest']}" if japanese else f"Latest {fields['latest']}")
    if fields.get("preferred"):
        entry_parts.append(
            f"望ましい押し目ゾーン {fields['preferred']}"
            if japanese
            else f"preferred pullback zone {fields['preferred']}"
        )
    if fields.get("chase"):
        entry_parts.append(f"追いかけ上限 {fields['chase']}" if japanese else f"chase limit {fields['chase']}")
    if fields.get("breakout"):
        entry_parts.append(
            f"ブレイク確認 {fields['breakout']}"
            if japanese
            else f"breakout confirmation {fields['breakout']}"
        )
    if entry_parts:
        lines.append(("；".join(entry_parts) + "。") if japanese else ("; ".join(entry_parts) + "."))

    risk_parts = []
    if fields.get("stop"):
        risk_parts.append(f"短期損切り {fields['stop']}" if japanese else f"short-term stop {fields['stop']}")
    if fields.get("invalidation"):
        risk_parts.append(
            f"テクニカル失効 {fields['invalidation']}"
            if japanese
            else f"technical invalidation {fields['invalidation']}"
        )
    if risk_parts:
        lines.append(("；".join(risk_parts) + "。") if japanese else ("; ".join(risk_parts) + "."))

    context = technical_levels.get("context") if isinstance(technical_levels.get("context"), dict) else {}
    if context.get("extended"):
        lines.append(
            "現在位置はやや伸びています。追いかけるより、押し目またはブレイク確認を優先してください。"
            if japanese
            else "The current position looks extended; prefer a pullback or breakout confirmation over chasing."
        )
    return lines[:summary_limit]


def english_entry_decision_with_levels(
    *,
    target_label: str,
    score: float | None,
    weak_evidence: bool,
    fields: dict[str, str],
    numbers: dict[str, float | None],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> tuple[str, list[str], list[dict[str, str]]]:
    price_position = decision_engine.entry_price_position(numbers)
    latest = fields.get("latest") or "-"
    preferred = fields.get("preferred")
    chase = fields.get("chase")
    breakout = fields.get("breakout")
    conservative = fields.get("conservative")
    score_bearish = score is not None and score <= -1
    score_bullish = score is not None and score >= 2

    if weak_evidence:
        headline = f"{target_label} is not a direct buy yet; data or confidence is not strong enough"
    elif price_position == "in_preferred" and preferred:
        if score_bearish:
            headline = f"{target_label} is in the pullback zone, but the short-term setup is weak"
        elif score_bullish:
            headline = f"{target_label} is back in the preferred buy zone; wait for support and volume confirmation"
        else:
            headline = f"{target_label} is in the pullback zone; wait for support to hold"
    elif price_position == "above_chase" and chase:
        headline = f"{target_label} is above the chase limit {chase}; avoid chasing"
    elif price_position == "breakout_confirmed" and breakout:
        headline = f"{target_label} is at the breakout confirmation area; wait for it to hold"
    elif price_position == "below_preferred" and preferred:
        headline = f"{target_label} has not reached the preferred buy zone; wait for a pullback and stabilization"
    elif price_position == "above_preferred" and preferred:
        headline = f"{target_label} is above the pullback zone; wait for a retest of {preferred} or breakout confirmation"
    elif price_position in {"below_stop", "below_invalidation"}:
        headline = f"{target_label} is in the risk zone; do not bottom-fish first"
    elif score_bullish:
        headline = f"{target_label} can stay on the bullish watchlist, but avoid chasing"
    elif score_bearish:
        headline = f"{target_label} is not a direct buy setup right now; wait for price and momentum to improve"
    else:
        headline = f"{target_label} is a wait-and-see setup until price and direction confirm"

    summary = []
    if latest:
        parts = [f"Latest {latest}"]
        if preferred:
            parts.append(f"preferred zone {preferred}")
        if chase:
            parts.append(f"chase limit {chase}")
        if breakout:
            parts.append(f"breakout confirmation {breakout}")
        summary.append("; ".join(parts) + ".")
    risk_parts = []
    if fields.get("stop"):
        risk_parts.append(f"stop {fields['stop']}")
    if fields.get("invalidation"):
        risk_parts.append(f"invalidation {fields['invalidation']}")
    if risk_parts:
        summary.append("Risk line: " + "; ".join(risk_parts) + ".")

    if price_position == "in_preferred" and preferred:
        now_text = (
            f"Latest {latest} is inside {preferred}; it can be watched, but the weak score argues against an automatic buy."
            if score_bearish
            else f"Latest {latest} is inside {preferred}; treat it as a watchable buy zone only after support holds."
        )
        condition_parts = [f"{preferred} holds", "volume or momentum improves"]
        if chase:
            condition_parts.append(f"near or above {chase} should be treated as chasing")
        if conservative and numbers.get("conservative_low") and numbers.get("latest"):
            if numbers["conservative_low"] > numbers["latest"]:
                condition_parts.append(f"{conservative} becomes a re-strengthening confirmation zone")
        entry_text = "; ".join(condition_parts) + "."
    elif price_position == "above_chase" and preferred:
        now_text = f"Latest {latest} is away from the ideal buy zone; do not treat chasing as entry discipline."
        entry_text = (
            f"Wait for a pullback to {preferred} and stabilization, or reassess after a confirmed breakout above {breakout}."
            if breakout
            else f"Wait for a pullback to {preferred} and stabilization before reassessing."
        )
    elif price_position == "below_preferred" and preferred:
        now_text = f"Latest {latest} has not reached the preferred pullback zone yet."
        entry_text = f"Wait for price to approach {preferred} and show stabilization or recovering volume."
    elif price_position == "above_preferred" and preferred:
        now_text = f"Latest {latest} has moved above {preferred}; do not treat it as a pullback entry."
        entry_text = (
            f"Wait for a retest of {preferred} to hold, or reassess after a confirmed breakout above {breakout}."
            if breakout
            else f"Wait for a retest of {preferred} to hold before reassessing."
        )
        if chase:
            entry_text = entry_text.rstrip(".") + f"; near or above {chase} is chasing, so size should come down."
    elif price_position in {"below_stop", "below_invalidation"}:
        now_text = f"Latest {latest} is already in the risk zone; bottom-fishing risk is high."
        entry_text = "First wait for price to reclaim the risk line and confirm that weakness is not expanding."
    elif price_position == "breakout_confirmed":
        now_text = f"Latest {latest} is near or above the breakout confirmation zone; this is not a pullback entry."
        entry_text = "Only use a breakout-hold and successful retest condition; do not apply pullback-buy logic."
    else:
        now_text = f"Latest {latest}; do not use a single score as the buy decision."
        entry_text = "Increase entry weight only after price, volume, moving averages, or momentum turn in the same direction."

    risk_text = english_entry_risk_text(fields)
    action_plan = [
        {"label": "Now", "text": now_text},
        {"label": "Entry condition", "text": entry_text},
        {"label": "Risk control", "text": risk_text},
    ]
    return headline, summary[:summary_limit], action_plan


def english_entry_risk_text(fields: dict[str, str]) -> str:
    risk_parts = []
    if fields.get("stop"):
        risk_parts.append(f"stop buying dips if price breaks {fields['stop']}")
    if fields.get("invalidation"):
        risk_parts.append(f"the swing setup fails below {fields['invalidation']}")
    return "; ".join(risk_parts) + "." if risk_parts else "Downgrade the buy thesis if volume expands into weakness or price falls below key moving averages."


def japanese_entry_decision_with_levels(
    *,
    target_label: str,
    score: float | None,
    weak_evidence: bool,
    fields: dict[str, str],
    numbers: dict[str, float | None],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> tuple[str, list[str], list[dict[str, str]]]:
    price_position = decision_engine.entry_price_position(numbers)
    latest = fields.get("latest") or "-"
    preferred = fields.get("preferred")
    chase = fields.get("chase")
    breakout = fields.get("breakout")
    score_bearish = score is not None and score <= -1
    score_bullish = score is not None and score >= 2

    if weak_evidence:
        headline = f"{target_label} はまだ直接買いではありません。データまたは信頼度が不足しています"
    elif price_position == "in_preferred" and preferred:
        if score_bearish:
            headline = f"{target_label} は押し目ゾーン内ですが、短期形状は弱めです"
        elif score_bullish:
            headline = f"{target_label} は優先買いゾーンに戻っています。サポートと出来高確認を待ってください"
        else:
            headline = f"{target_label} は押し目ゾーン内です。サポート維持を確認してください"
    elif price_position == "above_chase" and chase:
        headline = f"{target_label} は追いかけ上限 {chase} を上回っています。追いかけ買いは避けてください"
    elif price_position == "breakout_confirmed" and breakout:
        headline = f"{target_label} はブレイク確認圏です。維持できるかを待ってください"
    elif price_position == "below_preferred" and preferred:
        headline = f"{target_label} はまだ優先買いゾーンに届いていません。押し目と安定を待ってください"
    elif price_position == "above_preferred" and preferred:
        headline = f"{target_label} は押し目ゾーンを上回っています。{preferred} の再テストまたはブレイク確認を待ってください"
    elif price_position in {"below_stop", "below_invalidation"}:
        headline = f"{target_label} はリスク圏です。先に底値拾いは避けてください"
    elif score_bullish:
        headline = f"{target_label} は強気候補として監視できますが、追いかけ買いは避けてください"
    elif score_bearish:
        headline = f"{target_label} は現時点で直接買いの形ではありません。価格とモメンタム改善を待ってください"
    else:
        headline = f"{target_label} は価格と方向確認まで様子見です"

    summary = []
    if latest:
        parts = [f"現在値 {latest}"]
        if preferred:
            parts.append(f"優先ゾーン {preferred}")
        if chase:
            parts.append(f"追いかけ上限 {chase}")
        if breakout:
            parts.append(f"ブレイク確認 {breakout}")
        summary.append("；".join(parts) + "。")
    risk_parts = []
    if fields.get("stop"):
        risk_parts.append(f"短期損切り {fields['stop']}")
    if fields.get("invalidation"):
        risk_parts.append(f"失効ライン {fields['invalidation']}")
    if risk_parts:
        summary.append("リスクライン：" + "；".join(risk_parts) + "。")

    if price_position == "in_preferred" and preferred:
        now_text = (
            f"現在値 {latest} は {preferred} 内です。ただしスコアが弱いため、自動的な買い判断にはしません。"
            if score_bearish
            else f"現在値 {latest} は {preferred} 内です。サポート維持を確認してから買いゾーンとして扱ってください。"
        )
        condition_parts = [f"{preferred} を維持", "出来高またはモメンタム改善"]
        if chase:
            condition_parts.append(f"{chase} 付近以上は追いかけ買いとして扱う")
        entry_text = "；".join(condition_parts) + "。"
    elif price_position == "above_chase" and preferred:
        now_text = f"現在値 {latest} は理想的な買いゾーンから離れています。追いかけ買いをエントリー規律にしないでください。"
        entry_text = (
            f"{preferred} までの押し目と安定を待つか、{breakout} 超えのブレイク確認後に再評価してください。"
            if breakout
            else f"{preferred} までの押し目と安定を待ってから再評価してください。"
        )
    elif price_position == "below_preferred" and preferred:
        now_text = f"現在値 {latest} はまだ優先押し目ゾーンに届いていません。"
        entry_text = f"{preferred} に近づき、価格安定または出来高回復が出るまで待ってください。"
    elif price_position == "above_preferred" and preferred:
        now_text = f"現在値 {latest} は {preferred} を上回っています。押し目エントリーとしては扱いません。"
        entry_text = (
            f"{preferred} の再テスト維持、または {breakout} 超えのブレイク確認後に再評価してください。"
            if breakout
            else f"{preferred} の再テスト維持を待ってから再評価してください。"
        )
        if chase:
            entry_text = entry_text.rstrip("。") + f"；{chase} 付近以上は追いかけ買いなので、サイズを抑えてください。"
    elif price_position in {"below_stop", "below_invalidation"}:
        now_text = f"現在値 {latest} はすでにリスク圏です。底値拾いのリスクが高い状態です。"
        entry_text = "まずリスクラインを回復し、弱さが広がっていないことを確認してください。"
    elif price_position == "breakout_confirmed":
        now_text = f"現在値 {latest} はブレイク確認圏付近または上です。押し目エントリーではありません。"
        entry_text = "ブレイク維持と再テスト成功だけを条件にしてください。押し目買いロジックは使わないでください。"
    else:
        now_text = f"現在値 {latest}。単一スコアだけで買い判断をしないでください。"
        entry_text = "価格、出来高、移動平均、またはモメンタムが同じ方向に改善してからエントリー比重を上げてください。"

    risk_parts = []
    if fields.get("stop"):
        risk_parts.append(f"{fields['stop']} を割れたら押し目買いを停止")
    if fields.get("invalidation"):
        risk_parts.append(f"{fields['invalidation']} 未満でスイング形状は失効")
    risk_text = "；".join(risk_parts) + "。" if risk_parts else "出来高を伴って弱含む、または主要移動平均を下回る場合は買いシナリオを下方修正してください。"

    action_plan = [
        {"label": "今", "text": now_text},
        {"label": "エントリー条件", "text": entry_text},
        {"label": "リスク管理", "text": risk_text},
    ]
    return headline, summary[:summary_limit], action_plan


def english_trend_view_with_levels(
    *,
    target_label: str,
    score: float | None,
    weak_evidence: bool,
    fields: dict[str, str],
    numbers: dict[str, float | None],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
) -> tuple[str, list[str], list[dict[str, str]], list[str]]:
    price_position = decision_engine.entry_price_position(numbers)
    latest = fields.get("latest") or "-"
    preferred = fields.get("preferred")
    breakout = fields.get("breakout")
    chase = fields.get("chase")
    stop = fields.get("stop")
    invalidation = fields.get("invalidation")
    score_bullish = score is not None and score >= 2
    score_bearish = score is not None and score <= -2

    if weak_evidence:
        headline = f"{target_label} direction should stay tentative until data and the next price-volume signal confirm"
    elif price_position == "above_chase" and chase:
        headline = f"{target_label} still leans bullish, but latest {latest} is near the chase limit {chase}"
    elif price_position == "above_preferred" and preferred:
        headline = f"{target_label} still leans bullish, but latest {latest} has moved away from support {preferred}"
    elif price_position == "in_preferred" and preferred:
        headline = f"{target_label} is back near support; watch whether {preferred} holds"
    elif price_position == "below_preferred" and preferred:
        headline = f"{target_label} has broken below the first support zone; watch whether {preferred} is reclaimed"
    elif price_position == "breakout_confirmed" and breakout:
        headline = f"{target_label} is at the breakout confirmation area; watch whether it holds above {breakout}"
    elif price_position in {"below_stop", "below_invalidation"}:
        guardrail = invalidation or stop or "-"
        headline = f"{target_label} is near the risk zone {guardrail}; the swing structure needs reconfirmation"
    elif score_bullish:
        headline = f"{target_label} trend leans bullish; watch support and breakout continuation"
    elif score_bearish:
        headline = f"{target_label} trend leans weak; watch whether support fails"
    else:
        headline = f"{target_label} is mixed; watch which side of support or resistance resolves first"

    summary = []
    parts = [f"Latest {latest}"]
    if preferred:
        parts.append(f"support zone {preferred}")
    if breakout:
        parts.append(f"breakout confirmation {breakout}")
    elif chase:
        parts.append(f"{chase} or higher looks extended")
    summary.append("; ".join(parts) + ".")

    risk_parts = []
    if invalidation:
        risk_parts.append(f"below {invalidation} invalidates the swing thesis")
    elif stop:
        risk_parts.append(f"below {stop} weakens the short-term structure")
    if risk_parts:
        summary.append("; ".join(risk_parts) + ".")

    if weak_evidence:
        trend_text = "Treat this as directional context first; do not turn a single score or close into the final conclusion."
    elif price_position == "above_chase" and chase:
        trend_text = f"Direction still leans bullish, but latest {latest} is extended and the chase risk/reward is poor."
    elif price_position == "above_preferred" and preferred:
        trend_text = f"Direction still leans bullish; the key shifts from chasing to whether a retest of {preferred} holds."
    elif price_position == "in_preferred" and preferred:
        trend_text = f"The key is support absorption now; if {preferred} holds, the swing setup can continue."
    elif price_position == "below_preferred" and preferred:
        trend_text = f"Direction is starting to weaken; failure to reclaim {preferred} downgrades the bullish structure."
    elif price_position == "breakout_confirmed" and breakout:
        trend_text = f"The key shifts to breakout continuation; watch whether price holds above {breakout}."
    else:
        trend_text = (
            "Use the multi-timeframe score for direction, then confirm with support, resistance, volume, and momentum."
            if score_bullish
            else "Confirm with price, volume, and moving averages before drawing a directional conclusion."
        )

    support_parts = []
    if preferred:
        support_parts.append(f"support starts around {preferred}")
    if breakout:
        support_parts.append(f"upside confirmation is {breakout}")
    if chase:
        support_parts.append(f"near or above {chase} is extended")
    if invalidation:
        support_parts.append(f"below {invalidation} invalidates the swing setup")
    support_text = (
        "; ".join(support_parts) + "."
        if support_parts
        else "Watch key moving averages, prior lows, and volume confirmation."
    )

    if price_position == "above_chase" and preferred:
        observation_text = (
            f"Prefer waiting for a retest of {preferred}; if price keeps pushing, require a clean break and hold above {breakout}."
            if breakout
            else f"Prefer waiting for a retest of {preferred}; do not treat the current extended area as new support."
        )
    elif price_position == "above_preferred" and preferred:
        observation_text = f"Watch whether volume contracts and momentum holds during a retest of {preferred}."
    elif price_position == "in_preferred" and preferred:
        observation_text = f"Watch whether {preferred} stabilizes and volume or momentum improves."
    elif price_position == "below_preferred" and preferred:
        observation_text = f"Watch whether price can quickly reclaim {preferred}; failure to do so keeps the swing view weak."
    elif price_position == "breakout_confirmed" and breakout:
        observation_text = f"Watch the next one to two candles after the break of {breakout}; avoid false-breakout follow-through."
    elif price_position in {"below_stop", "below_invalidation"}:
        guardrail = invalidation or stop or "-"
        observation_text = f"First watch whether price can reclaim {guardrail}; otherwise downgrade the trend view."
    else:
        observation_text = "Watch whether price, volume, moving averages, and relative market strength stay aligned."

    action_plan = [
        {"label": "Trend", "text": trend_text},
        {"label": "Support/resistance", "text": support_text},
        {"label": "Watch", "text": observation_text},
    ]

    risks: list[str] = []
    if chase:
        if price_position == "above_chase":
            risks.append(f"Latest price is near or above the chase limit {chase}, so short-term pullback risk is elevated.")
        else:
            risks.append(f"A move near or above {chase} is extended and should not be treated as new support.")
    if invalidation:
        risks.append(f"Below {invalidation}, the bullish swing thesis should be downgraded.")
    elif stop:
        risks.append(f"Below {stop}, the short-term structure weakens materially.")

    return headline, summary[:summary_limit], action_plan, risks[:2]


def decision_evidence_summary_lines(
    decision_evidence: dict[str, Any],
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(decision_evidence, dict):
        return []

    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    lines: list[str] = []
    market_session = (
        decision_evidence.get("market_session")
        if isinstance(decision_evidence.get("market_session"), dict)
        else {}
    )
    if market_session.get("is_trading_day") is False:
        if english:
            session_date = text_value(market_session.get("date")) or "Today"
            latest_daily_date = text_value(market_session.get("latest_daily_date"))
            next_trading_day = text_value(market_session.get("next_trading_day"))
            text = f"{session_date} is not a Taiwan trading day"
            if latest_daily_date:
                text += f"; latest daily data is through {latest_daily_date}"
            if next_trading_day:
                text += f"; recheck intraday price and volume on {next_trading_day}"
            text += "."
        elif japanese:
            session_date = text_value(market_session.get("date")) or "本日"
            latest_daily_date = text_value(market_session.get("latest_daily_date"))
            next_trading_day = text_value(market_session.get("next_trading_day"))
            text = f"{session_date} は台湾株式市場の取引日ではありません"
            if latest_daily_date:
                text += f"。最新の日足データは {latest_daily_date} までです"
            if next_trading_day:
                text += f"。{next_trading_day} にザラ場価格と出来高を再確認してください"
            text += "。"
        else:
            text = text_value(market_session.get("summary"))
        if text:
            lines.append(text)

    volatility = (
        decision_evidence.get("recent_volatility")
        if isinstance(decision_evidence.get("recent_volatility"), dict)
        else {}
    )
    if volatility.get("label") in {"high", "elevated"}:
        text = (
            english_volatility_summary(volatility)
            if english
            else japanese_volatility_summary(volatility)
            if japanese
            else text_value(volatility.get("summary"))
        )
        if text:
            lines.append(text)

    fundamentals = (
        decision_evidence.get("fundamentals")
        if isinstance(decision_evidence.get("fundamentals"), dict)
        else {}
    )
    revenue = (
        fundamentals.get("monthly_revenue")
        if isinstance(fundamentals.get("monthly_revenue"), dict)
        else {}
    )
    revenue_summary = text_value(revenue.get("summary"))
    if english:
        revenue_summary = english_revenue_summary(revenue)
    elif japanese:
        revenue_summary = japanese_revenue_summary(revenue)
    if revenue_summary:
        lines.append(revenue_summary)

    indicator_quality = (
        decision_evidence.get("indicator_quality")
        if isinstance(decision_evidence.get("indicator_quality"), dict)
        else {}
    )
    warnings = (
        english_indicator_quality_warnings(indicator_quality)[:1]
        if english
        else japanese_indicator_quality_warnings(indicator_quality)[:1]
        if japanese
        else text_list(indicator_quality.get("warnings"), limit=1)
    )
    lines.extend(warnings)
    return lines[:2]


def decision_evidence_risk_lines(
    decision_evidence: dict[str, Any],
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(decision_evidence, dict):
        return []
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    if english or japanese:
        lines: list[str] = []
        volatility = (
            decision_evidence.get("recent_volatility")
            if isinstance(decision_evidence.get("recent_volatility"), dict)
            else {}
        )
        if volatility.get("label") in {"high", "elevated"}:
            volatility_text = (
                english_volatility_summary(volatility)
                if english
                else japanese_volatility_summary(volatility)
            )
            if volatility_text:
                lines.append(
                    volatility_text.rstrip(".") + "; reduce size before chasing."
                    if english
                    else volatility_text.rstrip("。") + "。追いかけ買い前にポジションを抑えてください。"
                )
            else:
                lines.append(
                    "Recent volatility is elevated; reduce size before chasing."
                    if english
                    else "直近のボラティリティが高いため、追いかけ買い前にポジションを抑えてください。"
                )

        indicator_quality = (
            decision_evidence.get("indicator_quality")
            if isinstance(decision_evidence.get("indicator_quality"), dict)
            else {}
        )
        lines.extend(
            english_indicator_quality_warnings(indicator_quality)
            if english
            else japanese_indicator_quality_warnings(indicator_quality)
        )

        fundamentals = (
            decision_evidence.get("fundamentals")
            if isinstance(decision_evidence.get("fundamentals"), dict)
            else {}
        )
        revenue = (
            fundamentals.get("monthly_revenue")
            if isinstance(fundamentals.get("monthly_revenue"), dict)
            else {}
        )
        if revenue.get("tone") == "negative":
            revenue_text = (
                english_revenue_summary(revenue)
                if english
                else japanese_revenue_summary(revenue)
            )
            if revenue_text:
                lines.append(revenue_text)
        return list(dict.fromkeys(lines))[:2]

    factors = (
        decision_evidence.get("confidence_factors")
        if isinstance(decision_evidence.get("confidence_factors"), dict)
        else {}
    )
    negatives = text_list(factors.get("negative"), limit=3)
    return negatives[:2]


def decision_evidence_data_lines(
    decision_evidence: dict[str, Any],
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(decision_evidence, dict):
        return []
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    lines: list[str] = []
    market_session = (
        decision_evidence.get("market_session")
        if isinstance(decision_evidence.get("market_session"), dict)
        else {}
    )
    if market_session.get("is_trading_day") is False:
        session_date = text_value(market_session.get("date")) or (
            "today" if english else "本日" if japanese else "今日"
        )
        latest_daily_date = text_value(market_session.get("latest_daily_date"))
        next_trading_day = text_value(market_session.get("next_trading_day"))
        if english:
            line = f"{session_date} is not a Taiwan trading day, so intraday data is not used"
            if latest_daily_date:
                line += f"; latest daily data is through {latest_daily_date}"
            if next_trading_day:
                line += f"; recheck on the next trading day {next_trading_day}"
            lines.append(line + ".")
        elif japanese:
            line = f"{session_date} は台湾株式市場の取引日ではないため、ザラ場データは使用しません"
            if latest_daily_date:
                line += f"。最新の日足データは {latest_daily_date} までです"
            if next_trading_day:
                line += f"。次の取引日 {next_trading_day} に再確認してください"
            lines.append(line + "。")
        else:
            line = f"{session_date} 非台股交易日，不使用盤中資料"
            if latest_daily_date:
                line += f"；最新日線截至 {latest_daily_date}"
            if next_trading_day:
                line += f"，下一交易日 {next_trading_day} 再確認"
            lines.append(line + "。")

    data_quality = (
        decision_evidence.get("data_quality")
        if isinstance(decision_evidence.get("data_quality"), dict)
        else {}
    )
    price = data_quality.get("price") if isinstance(data_quality.get("price"), dict) else {}
    volume = data_quality.get("volume") if isinstance(data_quality.get("volume"), dict) else {}
    price_source = text_value(price.get("source"))
    price_as_of = text_value(price.get("as_of"))
    volume_source = text_value(volume.get("source"))
    volume_display = text_value(volume.get("display_value"))
    if price_source or price_as_of:
        if english:
            lines.append(
                "Price source "
                + (price_source or "-")
                + (f", as of {price_as_of}" if price_as_of else "")
                + "."
            )
        elif japanese:
            lines.append(
                "価格データ元 "
                + (price_source or "-")
                + (f"、{price_as_of} 時点" if price_as_of else "")
                + "。"
            )
        else:
            lines.append(
                "價格來源 "
                + (price_source or "-")
                + (f"，截至 {price_as_of}" if price_as_of else "")
                + "。"
            )
    if volume_source or volume_display:
        if english:
            lines.append(
                "Volume source "
                + (volume_source or "-")
                + (f", displayed as about {volume_display}" if volume_display else "")
                + "."
            )
        elif japanese:
            lines.append(
                "出来高データ元 "
                + (volume_source or "-")
                + (f"、表示値は約 {volume_display}" if volume_display else "")
                + "。"
            )
        else:
            lines.append(
                "成交量來源 "
                + (volume_source or "-")
                + (f"，折算約 {volume_display}" if volume_display else "")
                + "。"
            )

    factors = (
        decision_evidence.get("confidence_factors")
        if isinstance(decision_evidence.get("confidence_factors"), dict)
        else {}
    )
    if english:
        lines.extend(
            text
            for item in text_list(factors.get("data_limits"), limit=2)
            if (text := english_data_limit_text(item))
        )
    elif japanese:
        lines.extend(
            text
            for item in text_list(factors.get("data_limits"), limit=2)
            if (text := japanese_data_limit_text(item))
        )
    else:
        lines.extend(text_list(factors.get("data_limits"), limit=2))
    return list(dict.fromkeys(lines))[:3]


def scenario_plan_from_levels(
    *,
    question_intent: str,
    fields: dict[str, str],
    numbers: dict[str, float | None],
    score: float | None,
    weak_evidence: bool,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    if not fields or weak_evidence:
        return []

    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    latest = fields.get("latest")
    preferred = fields.get("preferred")
    breakout = fields.get("breakout")
    chase = fields.get("chase")
    stop = fields.get("stop")
    invalidation = fields.get("invalidation")
    price_position = decision_engine.entry_price_position(numbers)
    score_bullish = score is not None and score >= 2

    scenarios: list[dict[str, str]] = []

    if preferred:
        if english:
            if question_intent == "entry_decision":
                text = f"Treat a retest of {preferred} as watchable only if price stabilizes and volume does not expand into weakness."
            elif question_intent == "risk_check":
                text = f"If a retest of {preferred} fails, raise the risk level and reduce exposure or wait for a reclaim."
            else:
                text = f"During a retest of {preferred}, watch whether volume contracts and momentum holds; support matters only if it holds."
            scenarios.append({"label": "Support retest", "text": text})
        elif japanese:
            if question_intent == "entry_decision":
                text = f"{preferred} への押し目は、価格が安定し出来高が弱さ方向に膨らまない場合だけ監視対象にしてください。"
            elif question_intent == "risk_check":
                text = f"{preferred} の押し目が守れない場合はリスクを上げ、先にポジションを落とすか回復を待ってください。"
            else:
                text = f"{preferred} の押し目では、出来高が落ち着きモメンタムが維持されるかを確認してください。守れて初めてサポートとして扱えます。"
            scenarios.append({"label": "押し目確認", "text": text})
        else:
            if question_intent == "entry_decision":
                text = f"回測 {preferred} 且止跌、量能沒有放大轉弱，才把它視為買點觀察；沒有守住就不低接。"
            elif question_intent == "risk_check":
                text = f"若回測 {preferred} 無法守住，風險等級要上調，先降低部位或等待收復。"
            else:
                text = f"回測 {preferred} 時看量能是否收斂、動能是否守住；守住才代表支撐有效。"
            scenarios.append({"label": "回測支撐", "text": text})
    elif latest:
        scenarios.append(
            {
                "label": (
                    "Range watch"
                    if english
                    else "レンジ監視"
                    if japanese
                    else "盤整觀察"
                ),
                "text": (
                    f"Use latest {latest} as a reference, but do not treat one close as support; wait for volume and momentum confirmation."
                    if english
                    else f"最新値 {latest} を基準にしますが、1本の終値だけをサポート扱いせず、出来高とモメンタムの確認を待ってください。"
                    if japanese
                    else f"以現價 {latest} 當觀察基準，但不把單一收盤價當支撐；要等量能與動能同步確認。"
                ),
            }
        )

    if breakout:
        if english:
            if question_intent == "entry_decision":
                text = f"After a break and hold above {breakout}, entry logic shifts from buying a pullback to buying a successful retest."
            else:
                text = f"A break and hold above {breakout} supports swing extension; a fast drop back below it is a false breakout."
            scenarios.append({"label": "Breakout extension", "text": text})
        elif japanese:
            if question_intent == "entry_decision":
                text = f"{breakout} を突破して維持した後は、押し目買いではなく突破後の再テスト成功を買う形に切り替えます。"
            else:
                text = f"{breakout} を突破して維持できればスイング延長を支持します。すぐ下に戻る場合はダマシです。"
            scenarios.append({"label": "ブレイク継続", "text": text})
        else:
            if question_intent == "entry_decision":
                text = f"突破 {breakout} 並站穩後，買點邏輯要從低接改成突破後回測不破。"
            else:
                text = f"突破 {breakout} 並站穩，才代表波段延伸；若突破後快速跌回，視為假突破。"
            scenarios.append({"label": "突破延伸", "text": text})
    elif chase:
        scenarios.append(
            {
                "label": (
                    "Extended zone"
                    if english
                    else "過熱圏"
                    if japanese
                    else "偏熱延伸"
                ),
                "text": (
                    f"Near or above {chase}, treat the move as extended; do not treat the chase zone as new support."
                    if english
                    else f"{chase} 付近または上では上げ過ぎとして扱い、追いかけ買いの価格帯を新しいサポートとは見なしません。"
                    if japanese
                    else f"接近或高於 {chase} 時，先視為偏熱區；不要把追價區當新的支撐。"
                ),
            }
        )

    guardrail = invalidation or stop
    if guardrail:
        if english:
            text = (
                f"Below {guardrail}, downgrade the bullish thesis and defend first before recalculating."
                if score_bullish or price_position not in {"below_stop", "below_invalidation"}
                else f"If price cannot reclaim {guardrail}, the weak thesis remains active; do not assume a rebound."
            )
            scenarios.append({"label": "Invalidation defense", "text": text})
        elif japanese:
            text = (
                f"{guardrail} を下回る場合、強気シナリオを下方修正し、再計算の前に防御を優先してください。"
                if score_bullish or price_position not in {"below_stop", "below_invalidation"}
                else f"{guardrail} を回復できない場合、弱いシナリオが継続します。反発を前提にしないでください。"
            )
            scenarios.append({"label": "失効防御", "text": text})
        else:
            text = (
                f"跌破 {guardrail} 後，原本偏多假設降級，先防守再重新計算。"
                if score_bullish or price_position not in {"below_stop", "below_invalidation"}
                else f"若仍站不回 {guardrail}，弱勢假設延續，不用急著預設反彈。"
            )
            scenarios.append({"label": "失效防守", "text": text})

    return scenarios[:summary_limit]


def counter_evidence_from_levels(
    *,
    question_intent: str,
    fields: dict[str, str],
    score: float | None,
    weak_evidence: bool,
    evidence_risks: list[str],
    summary_limit: int = 2,
    response_preferences: dict[str, Any] | None = None,
) -> list[str]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    lines: list[str] = []
    if weak_evidence:
        lines.append(
            "When data or confidence is insufficient, do not treat the current conclusion as an executable signal."
            if english
            else "データまたは信頼度が不足している場合、現在の結論を実行可能なシグナルとして扱わないでください。"
            if japanese
            else "資料或信心不足時，不把目前結論當成可執行訊號。"
        )

    stop = fields.get("stop")
    invalidation = fields.get("invalidation")
    preferred = fields.get("preferred")
    breakout = fields.get("breakout")

    if invalidation:
        lines.append(
            f"A close below {invalidation} downgrades the original swing thesis."
            if english
            else f"{invalidation} を終値で下回る場合、元のスイングシナリオは下方修正です。"
            if japanese
            else f"收盤跌破 {invalidation}，原本波段假設需要降級。"
        )
    elif stop:
        lines.append(
            f"Below {stop}, treat the short-term structure as weakening first."
            if english
            else f"{stop} を下回る場合、短期構造はまず弱含みとして扱います。"
            if japanese
            else f"跌破 {stop}，短線結構先視為轉弱。"
        )

    if question_intent in {"entry_decision", "trend_view"} and preferred:
        lines.append(
            f"If a retest of {preferred} comes with expanding volume but price cannot hold, support absorption has failed."
            if english
            else f"{preferred} の押し目で出来高が増えたのに価格が維持できなければ、サポートの買い支えは失敗です。"
            if japanese
            else f"回測 {preferred} 量能放大但價格守不住，代表支撐承接失敗。"
        )

    if breakout:
        lines.append(
            f"If price breaks {breakout} but cannot hold and quickly falls back, breakout extension has failed."
            if english
            else f"{breakout} を突破しても維持できずすぐ戻る場合、ブレイク継続は失敗です。"
            if japanese
            else f"突破 {breakout} 後無法站穩並快速跌回，代表突破延伸失敗。"
        )

    if score is not None and score <= -2:
        lines.append(
            "When the multi-timeframe score weakens, do not keep a bullish thesis only because price looks cheaper."
            if english
            else "複数時間軸のスコアが弱い場合、価格が安く見えるだけで強気シナリオを維持しないでください。"
            if japanese
            else "多週期分數轉弱時，不應只因價格便宜就維持偏多假設。"
        )

    lines.extend(evidence_risks)
    return list(dict.fromkeys(lines))[:summary_limit]


def position_scenarios_from_decision(
    position_decision: dict[str, Any],
    *,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    if not isinstance(position_decision, dict):
        return [], []

    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    entry_price = decision_engine.numeric_data_value(position_decision.get("entry_price"))
    latest_price = decision_engine.numeric_data_value(position_decision.get("latest_price"))
    levels = position_decision.get("levels") if isinstance(position_decision.get("levels"), dict) else {}
    support_text = decision_engine.level_text(levels)
    return_pct = decision_engine.numeric_data_value(position_decision.get("unrealized_return_pct"))

    scenarios: list[dict[str, str]] = []
    if entry_price is not None and latest_price is not None:
        scenarios.append(
            {
                "label": (
                    "Near cost"
                    if english
                    else "コスト付近"
                    if japanese
                    else "成本附近"
                ),
                "text": (
                    (
                        f"Cost {decision_engine.format_price(entry_price)}, latest {decision_engine.format_price(latest_price)}; "
                        "if price is still near cost, use position size and technical lines instead of one price move to decide hold or exit."
                    )
                    if english
                    else (
                        f"取得単価 {decision_engine.format_price(entry_price)}、最新 {decision_engine.format_price(latest_price)}。"
                        "価格がまだコスト付近なら、1回の値動きではなくポジションサイズとテクニカルラインで保有・撤退を判断してください。"
                    )
                    if japanese
                    else (
                        f"成本 {decision_engine.format_price(entry_price)}、最新 {decision_engine.format_price(latest_price)}；"
                        "若價格仍在成本附近震盪，先用部位大小與技術線決定，不用單一漲跌判斷去留。"
                    )
                ),
            }
        )
    if support_text:
        scenarios.append(
            {
                "label": (
                    "Technical defense"
                    if english
                    else "テクニカル防御"
                    if japanese
                    else "技術防守"
                ),
                "text": (
                    f"If price breaks {support_text} and momentum weakens, downgrade the position thesis and trim or execute the stop rule."
                    if english
                    else f"{support_text} を割り込みモメンタムも弱まる場合、保有シナリオを下方修正し、減らすか損切りルールを実行してください。"
                    if japanese
                    else f"若跌破 {support_text} 且動能轉弱，持倉假設要降級，先減碼或執行停損規則。"
                ),
            }
        )
    scenarios.append(
        {
            "label": (
                "Hold condition"
                if english
                else "保有条件"
                if japanese
                else "續抱條件"
            ),
            "text": (
                "Treat it as holdable only if the retest holds, volume contracts, and price strengthens again; do not add if the rebound has no volume or cannot clear resistance."
                if english
                else "押し目を守り、出来高が落ち着き、価格が再び強まる場合だけ保有継続と見ます。出来高のない反発や抵抗線を超えられない反発では追加しないでください。"
                if japanese
                else "若回測不破、量能收斂且重新轉強，才把它視為續抱；反彈無量或站不上壓力就不要加碼。"
            ),
        }
    )

    counter: list[str] = []
    if return_pct is not None and return_pct <= -5:
        counter.append(
            "If your fixed stop rule is -5%, it has already triggered; do not use a bullish swing view to delay the stop."
            if english
            else "固定の損切りルールが -5% ならすでに発動しています。強気のスイング見通しを損切り先送りの理由にしないでください。"
            if japanese
            else "若你的固定停損規則是 -5%，目前已觸發，不應再用波段偏多作為延後停損理由。"
        )
    if support_text:
        counter.append(
            f"Breaking {support_text} and failing to reclaim it quickly means the technical stop condition is active."
            if english
            else f"{support_text} を割ってすぐ回復できなければ、テクニカル上の損切り条件が有効です。"
            if japanese
            else f"跌破 {support_text} 且無法快速收復，代表技術停損條件成立。"
        )
    counter.append(
        "If position size is too large or loss tolerance is insufficient, reduce risk even before the technical setup fully fails."
        if english
        else "ポジションが大きすぎる、または許容損失が不足している場合、テクニカル形状が完全に崩れる前でもリスクを下げてください。"
        if japanese
        else "若部位過大或可承受虧損不足，即使技術尚未失效，也要先降低風險。"
    )

    return scenarios[:summary_limit], list(dict.fromkeys(counter))[:2]


def build_position_decision_consumer_answer(
    *,
    position_decision: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    llm_payload = position_decision.get("llm") if isinstance(position_decision.get("llm"), dict) else {}
    llm_decision = llm_payload.get("decision") if isinstance(llm_payload.get("decision"), dict) else {}

    if llm_decision:
        summary = []
        append_unique_texts(
            summary,
            text_list(llm_decision.get("position_math"), limit=2),
            limit=summary_limit,
        )
        direct_answer = text_value(llm_decision.get("direct_answer"))
        if direct_answer:
            append_unique_texts(summary, [direct_answer], limit=summary_limit)
        if not summary:
            summary = text_list(position_decision.get("summary"), limit=summary_limit)

        conditions = text_list(llm_decision.get("decision_conditions"), limit=2)
        next_steps = text_list(llm_decision.get("next_steps"), limit=2)
        action_texts = list(dict.fromkeys(conditions + next_steps))[:summary_limit]
        labels = (
            ("Condition", "Action", "Follow-up")
            if english
            else ("条件", "実行", "フォロー")
            if japanese
            else ("條件", "執行", "追蹤")
        )
        action_plan = [
            {"label": labels[index], "text": text}
            for index, text in enumerate(action_texts)
        ] or position_decision.get("action_plan", [])

        confidence = text_value(llm_decision.get("confidence")) or text_value(position_decision.get("confidence"))
        answer = {
            "kind": "consumer_market_answer",
            "style": "position_decision_summary",
            "source": "position_decision_llm",
            "intent": "position_risk_decision",
            "headline": text_value(llm_decision.get("headline")) or text_value(position_decision.get("headline")),
            "stance": position_decision.get("stance"),
            "stance_label": stance_label(position_decision.get("stance"), response_preferences),
            "confidence": confidence,
            "confidence_label": confidence_label(confidence, response_preferences),
            "summary": summary[:summary_limit],
            "action_plan": action_plan[:summary_limit],
            "risks": text_list(llm_decision.get("risk_notes"), limit=2) or position_decision.get("risks", []),
            "data_limits": (
                text_list(llm_decision.get("missing_context"), limit=2)
                + generic_data_limits(
                    missing=missing,
                    warnings=warnings,
                    response_preferences=response_preferences,
                )
            )[:3],
            "detail": text_value(llm_decision.get("direct_answer")) or text_value(position_decision.get("direct_answer")) or "",
            "position_decision": position_decision,
        }
    else:
        confidence = text_value(position_decision.get("confidence"))
        answer = {
            "kind": "consumer_market_answer",
            "style": "position_decision_summary",
            "source": "position_decision",
            "intent": "position_risk_decision",
            "headline": text_value(position_decision.get("headline")) or (
                "Position risk decision is ready"
                if english
                else "ポジションリスク判断が完了しました"
                if japanese
                else "已完成部位風險判斷"
            ),
            "stance": position_decision.get("stance"),
            "stance_label": stance_label(position_decision.get("stance"), response_preferences),
            "confidence": confidence,
            "confidence_label": confidence_label(confidence, response_preferences),
            "summary": text_list(position_decision.get("summary"), limit=summary_limit),
            "action_plan": position_decision.get("action_plan", [])[:summary_limit],
            "risks": position_decision.get("risks", []),
            "data_limits": position_decision.get("data_limits", []),
            "detail": text_value(position_decision.get("direct_answer")) or "",
            "position_decision": position_decision,
        }

    scenarios, counter_evidence = position_scenarios_from_decision(
        position_decision,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    answer["scenarios"] = scenarios
    answer["counter_evidence"] = counter_evidence
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_question_aware_consumer_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if question_intent == "general" or not analysis_digest:
        return {}

    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    score = decision_engine.numeric_score(analysis_digest.get("selected_score"))
    score_text = decision_engine.score_display(score)
    confidence = text_value(analysis_digest.get("selected_confidence"))
    confidence_display = confidence_label(confidence, response_preferences)
    stance = decision_engine.stance_from_score(score)
    summary = digest_summary_lines(
        analysis_digest,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    target_label = text_value(target.get("label")) or text_value(target.get("id")) or target_fallback_label(response_preferences)
    data_limits = generic_data_limits(
        missing=missing,
        warnings=warnings,
        response_preferences=response_preferences,
    )
    decision_evidence = (
        analysis_digest.get("decision_evidence")
        if isinstance(analysis_digest.get("decision_evidence"), dict)
        else {}
    )
    evidence_summary = decision_evidence_summary_lines(
        decision_evidence,
        response_preferences=response_preferences,
    )
    evidence_risks = decision_evidence_risk_lines(
        decision_evidence,
        response_preferences=response_preferences,
    )
    answer_risks = list(evidence_risks)
    data_limits = list(
        dict.fromkeys(
            data_limits
            + decision_evidence_data_lines(
                decision_evidence,
                response_preferences=response_preferences,
            )
        )
    )
    weak_evidence = score is None or confidence == "low"
    technical_levels = (
        analysis_digest.get("technical_levels")
        if isinstance(analysis_digest.get("technical_levels"), dict)
        else {}
    )
    level_fields = decision_engine.technical_level_fields(technical_levels)
    level_numbers = decision_engine.technical_level_numbers(technical_levels)
    level_summary = (
        []
        if question_intent == "entry_decision" and level_fields
        else technical_level_summary_lines(
            technical_levels,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
    )
    if level_summary:
        summary = list(dict.fromkeys(level_summary + summary))[:summary_limit]

    if english:
        if question_intent == "entry_decision":
            if level_fields:
                headline, entry_summary, action_plan = english_entry_decision_with_levels(
                    target_label=target_label,
                    score=score,
                    weak_evidence=weak_evidence,
                    fields=level_fields,
                    numbers=level_numbers,
                    summary_limit=summary_limit,
                )
                if entry_summary:
                    summary = list(
                        dict.fromkeys(entry_summary[:1] + evidence_summary + entry_summary[1:] + summary)
                    )[:summary_limit]
            elif weak_evidence:
                headline = f"{target_label} is not a direct buy yet; data or confidence is not strong enough"
                action_plan = [
                    {"label": "Now", "text": "Do not chase; wait for the next price, volume, or indicator confirmation."},
                    {
                        "label": "Entry condition",
                        "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                    },
                    {
                        "label": "Risk control",
                        "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                    },
                ]
            elif score is not None and score >= 4:
                headline = f"{target_label} can stay on the bullish watchlist, but avoid chasing"
                action_plan = [
                    {"label": "Now", "text": "Treat it as a bullish watchlist candidate, not an automatic buy signal."},
                    {
                        "label": "Entry condition",
                        "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                    },
                    {
                        "label": "Risk control",
                        "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                    },
                ]
            elif score is not None and score >= 1:
                headline = f"{target_label} is worth watching; wait for price and volume confirmation"
                action_plan = [
                    {"label": "Now", "text": "Treat it as a watchlist candidate, not an automatic buy signal."},
                    {
                        "label": "Entry condition",
                        "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                    },
                    {
                        "label": "Risk control",
                        "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                    },
                ]
            elif score is not None and score <= -1:
                headline = f"{target_label} is not a direct buy setup right now"
                action_plan = [
                    {"label": "Now", "text": "Do not chase; wait for the next price, volume, or indicator confirmation."},
                    {
                        "label": "Entry condition",
                        "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                    },
                    {
                        "label": "Risk control",
                        "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                    },
                ]
            else:
                headline = f"{target_label} is a wait-and-see setup until direction confirms"
                action_plan = [
                    {"label": "Now", "text": "Do not chase; wait for the next price, volume, or indicator confirmation."},
                    {
                        "label": "Entry condition",
                        "text": "Increase entry weight only after price, volume, and key moving averages or momentum turn in the same direction.",
                    },
                    {
                        "label": "Risk control",
                        "text": "Downgrade the buy thesis if short-term momentum weakens, price falls below key moving averages, or volume expansion fails.",
                    },
                ]
        elif question_intent == "exit_decision":
            if evidence_summary:
                summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
            if level_fields and not weak_evidence and (level_fields.get("stop") or level_fields.get("invalidation")):
                guardrails = " / ".join(
                    value
                    for value in (level_fields.get("stop"), level_fields.get("invalidation"))
                    if value
                )
                headline = f"{target_label} can be held conditionally, but keep guardrails at {guardrails}"
            elif weak_evidence:
                headline = f"{target_label} needs a lower-conviction decision until data confirms the hold or exit case"
            elif score is not None and score >= 2:
                headline = f"{target_label} can still be held and watched, but only while weakness conditions stay inactive"
            elif score is not None and score <= -2:
                headline = f"{target_label} is weak; check trim or exit conditions first"
            else:
                headline = f"{target_label} direction is unclear; use conditional holding rules"

            action_plan = [
                {"label": "Now", "text": "Check cost basis and position size first; do not use one score for the whole exit decision."},
                {
                    "label": "Hold condition",
                    "text": (
                        f"Holding is more reasonable while price stays above {level_fields['stop']} and volume does not expand into weakness."
                        if level_fields.get("stop")
                        else "Holding is more reasonable while key moving averages or prior lows hold and volume does not expand into weakness."
                    ),
                },
                {
                    "label": "Exit condition",
                    "text": (
                        f"If price breaks {level_fields['invalidation']}, the technical thesis fails; reduce exposure or reassess."
                        if level_fields.get("invalidation")
                        else "If major support breaks, momentum turns down, or a rebound fails, reduce exposure or reassess."
                    ),
                },
            ]
        elif question_intent == "risk_check":
            if evidence_summary:
                summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
            guardrail = level_fields.get("stop") or level_fields.get("invalidation")
            if level_fields and not weak_evidence and guardrail:
                headline = f"{target_label} risk line is {guardrail}; defend first if it breaks"
            elif weak_evidence:
                headline = f"{target_label} risk confidence is limited; use conservative guardrails first"
            elif score is not None and score <= -2:
                headline = f"{target_label} risk is elevated; prioritize defense short term"
            elif score is not None and score >= 2:
                headline = f"{target_label} risk is not clearly elevated, but invalidation still matters"
            else:
                headline = f"{target_label} is mixed; confirm risk one condition at a time"

            action_plan = [
                {
                    "label": "Main risk",
                    "text": (
                        f"If price breaks the short-term stop {level_fields['stop']}, the short-term view downgrades quickly."
                        if level_fields.get("stop")
                        else "If price breaks key moving averages or prior lows, the short-term view downgrades quickly."
                    ),
                },
                {
                    "label": "Watch",
                    "text": (
                        f"Watch whether {level_fields['invalidation']} breaks, while confirming volume, institutional flow, or relative market strength."
                        if level_fields.get("invalidation")
                        else "Watch whether the next price, volume, institutional flow, or relative market strength signal turns weak at the same time."
                    ),
                },
                {"label": "Risk control", "text": "Do not wait for every data point to confirm before controlling risk; shrink exposure when conditions fail."},
            ]
        elif question_intent == "trend_view":
            if evidence_summary:
                summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
            if level_fields:
                headline, trend_summary, action_plan, trend_risks = english_trend_view_with_levels(
                    target_label=target_label,
                    score=score,
                    weak_evidence=weak_evidence,
                    fields=level_fields,
                    numbers=level_numbers,
                    summary_limit=summary_limit,
                )
                summary = list(dict.fromkeys(trend_summary + summary))[:summary_limit]
                answer_risks = list(dict.fromkeys(trend_risks + evidence_risks))
            elif weak_evidence:
                headline = f"{target_label} direction confidence is limited; wait for the next confirmation"
                action_plan = [
                    {"label": "Trend", "text": "Treat this as directional context first, not a final conclusion from a single score or close."},
                    {"label": "Support/resistance", "text": "Check key moving averages, prior lows, and volume to confirm whether support and resistance agree."},
                    {"label": "Watch", "text": "Raise conviction only after price, volume, and relative market strength align."},
                ]
            elif score is not None and score >= 2:
                headline = f"{target_label} trend leans bullish; watch support and breakout continuation"
                action_plan = [
                    {"label": "Trend", "text": "Use the multi-timeframe score for direction, then confirm continuation with support, resistance, and volume."},
                    {"label": "Support/resistance", "text": "Watch whether pullbacks hold support and whether upper resistance is broken and held."},
                    {"label": "Watch", "text": "Confirm that price, volume, moving averages, and relative market strength remain aligned."},
                ]
            elif score is not None and score <= -2:
                headline = f"{target_label} trend leans weak; watch whether support fails"
                action_plan = [
                    {"label": "Trend", "text": "Downgrade the directional view first; do not force the old bullish thesis from one close."},
                    {"label": "Support/resistance", "text": "Confirm whether major support has failed and whether rebound resistance is effective."},
                    {"label": "Watch", "text": "If volume and momentum both weaken, recalculate the swing view."},
                ]
            else:
                headline = f"{target_label} is undecided; watch which side of support or resistance resolves first"
                action_plan = [
                    {"label": "Trend", "text": f"Current score is {score_text or '-'}; use it as a direction clue, not a trade signal."},
                    {"label": "Support/resistance", "text": "Check whether key moving averages, prior lows, and upper resistance converge into one signal."},
                    {"label": "Watch", "text": "Raise conviction only after price, volume, and relative market strength align."},
                ]
        else:
            if evidence_summary:
                summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
            if weak_evidence:
                headline = f"{target_label} direction confidence is limited; wait for the next confirmation"
            elif score is not None and score >= 2:
                headline = f"{target_label} trend leans bullish, but confirmation still matters"
            elif score is not None and score <= -2:
                headline = f"{target_label} trend leans weak; do not chase against the move"
            else:
                headline = f"{target_label} direction is undecided; watch key price and volume confirmation"

            action_plan = [
                {"label": "Direction", "text": f"Current score is {score_text or '-'}; use it for directional strength, not as a direct trade signal."},
                {"label": "Confirm", "text": "Wait for price, volume, moving averages, or relative market strength to align."},
                {"label": "Invalidation", "text": "If key moving averages or momentum weaken, recalculate the trend view."},
            ]

        scenarios = scenario_plan_from_levels(
            question_intent=question_intent,
            fields=level_fields,
            numbers=level_numbers,
            score=score,
            weak_evidence=weak_evidence,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        counter_evidence = counter_evidence_from_levels(
            question_intent=question_intent,
            fields=level_fields,
            score=score,
            weak_evidence=weak_evidence,
            evidence_risks=answer_risks,
            response_preferences=response_preferences,
        )
        answer = {
            "kind": "consumer_market_answer",
            "style": "question_aware_summary",
            "source": "question_intent",
            "intent": question_intent,
            "headline": headline,
            "stance": stance,
            "stance_label": stance_label(stance, response_preferences),
            "confidence": confidence,
            "confidence_label": confidence_display,
            "summary": summary,
            "action_plan": action_plan,
            "scenarios": scenarios,
            "counter_evidence": counter_evidence,
            "risks": list(dict.fromkeys(answer_risks + (data_limits[:2] if weak_evidence else [])))[:2],
            "data_limits": data_limits,
            "detail": text_value(analysis_digest.get("display")) or "",
            "decision_evidence": decision_evidence,
        }
        answer["text"] = consumer_text(
            answer,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return answer

    if japanese:
        if question_intent == "entry_decision":
            if level_fields:
                headline, entry_summary, action_plan = japanese_entry_decision_with_levels(
                    target_label=target_label,
                    score=score,
                    weak_evidence=weak_evidence,
                    fields=level_fields,
                    numbers=level_numbers,
                    summary_limit=summary_limit,
                )
                if entry_summary:
                    summary = list(
                        dict.fromkeys(entry_summary[:1] + evidence_summary + entry_summary[1:] + summary)
                    )[:summary_limit]
            elif weak_evidence:
                headline = f"{target_label} はまだ直接買いではありません。データまたは信頼度が不足しています"
                action_plan = [
                    {"label": "今", "text": "追いかけ買いは避け、次の価格・出来高・指標確認を待ってください。"},
                    {
                        "label": "エントリー条件",
                        "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                    },
                    {
                        "label": "リスク管理",
                        "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                    },
                ]
            elif score is not None and score >= 4:
                headline = f"{target_label} は強気候補として監視できますが、追いかけ買いは避けてください"
                action_plan = [
                    {"label": "今", "text": "強気監視候補として扱い、自動的な買いシグナルとは見なさないでください。"},
                    {
                        "label": "エントリー条件",
                        "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                    },
                    {
                        "label": "リスク管理",
                        "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                    },
                ]
            elif score is not None and score >= 1:
                headline = f"{target_label} は監視候補です。価格と出来高の確認を待ってください"
                action_plan = [
                    {"label": "今", "text": "監視候補として扱い、自動的な買いシグナルとは見なさないでください。"},
                    {
                        "label": "エントリー条件",
                        "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                    },
                    {
                        "label": "リスク管理",
                        "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                    },
                ]
            elif score is not None and score <= -1:
                headline = f"{target_label} は現時点で直接買いの形ではありません"
                action_plan = [
                    {"label": "今", "text": "追いかけ買いは避け、次の価格・出来高・指標確認を待ってください。"},
                    {
                        "label": "エントリー条件",
                        "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                    },
                    {
                        "label": "リスク管理",
                        "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                    },
                ]
            else:
                headline = f"{target_label} は方向確認まで様子見です"
                action_plan = [
                    {"label": "今", "text": "追いかけ買いは避け、次の価格・出来高・指標確認を待ってください。"},
                    {
                        "label": "エントリー条件",
                        "text": "価格、出来高、主要移動平均またはモメンタムが同じ方向に強まった後に、エントリー比重を上げてください。",
                    },
                    {
                        "label": "リスク管理",
                        "text": "短期モメンタム低下、主要移動平均割れ、または出来高増を伴う失速が出たら買いシナリオを下方修正してください。",
                    },
                ]
        elif question_intent == "exit_decision":
            if evidence_summary:
                summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
            guardrails = " / ".join(
                value
                for value in (level_fields.get("stop"), level_fields.get("invalidation"))
                if value
            )
            if level_fields and not weak_evidence and guardrails:
                headline = f"{target_label} は条件付きで保有継続できますが、{guardrails} を守る必要があります"
            elif weak_evidence:
                headline = f"{target_label} はデータ確認まで判断の強さを下げてください"
            elif score is not None and score >= 2:
                headline = f"{target_label} はまだ保有監視できますが、弱化条件が出ないことが前提です"
            elif score is not None and score <= -2:
                headline = f"{target_label} は弱めです。減らす条件または退出条件を先に確認してください"
            else:
                headline = f"{target_label} は方向が不明確です。条件付き保有ルールで判断してください"

            action_plan = [
                {"label": "今", "text": "まず取得単価とポジションサイズを確認し、単一スコアだけで退出判断をしないでください。"},
                {
                    "label": "保有条件",
                    "text": (
                        f"価格が {level_fields['stop']} を維持し、出来高を伴う弱さが出ない間は保有監視が比較的合理的です。"
                        if level_fields.get("stop")
                        else "主要移動平均または前回安値を維持し、出来高を伴う弱さが出ない間は保有監視が比較的合理的です。"
                    ),
                },
                {
                    "label": "退出条件",
                    "text": (
                        f"{level_fields['invalidation']} を割る場合、テクニカル仮説は失効します。ポジションを減らすか再評価してください。"
                        if level_fields.get("invalidation")
                        else "主要サポート割れ、モメンタム低下、または反発失敗が出る場合は、ポジションを減らすか再評価してください。"
                    ),
                },
            ]
        elif question_intent == "risk_check":
            if evidence_summary:
                summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
            guardrail = level_fields.get("stop") or level_fields.get("invalidation")
            if level_fields and not weak_evidence and guardrail:
                headline = f"{target_label} のリスクラインは {guardrail} です。割れたら防御を優先してください"
            elif weak_evidence:
                headline = f"{target_label} のリスク判断は信頼度が限られます。まず保守的なラインで管理してください"
            elif score is not None and score <= -2:
                headline = f"{target_label} はリスクが高めです。短期は防御を優先してください"
            elif score is not None and score >= 2:
                headline = f"{target_label} のリスクは明確に拡大していませんが、失効条件は重要です"
            else:
                headline = f"{target_label} は強弱混在です。リスク条件を一つずつ確認してください"

            action_plan = [
                {
                    "label": "主なリスク",
                    "text": (
                        f"短期損切り {level_fields['stop']} を割る場合、短期見通しはすぐ下方修正です。"
                        if level_fields.get("stop")
                        else "主要移動平均または前回安値を割る場合、短期見通しはすぐ下方修正です。"
                    ),
                },
                {
                    "label": "監視",
                    "text": (
                        f"{level_fields['invalidation']} を割るかを見ながら、出来高、法人フロー、相対的な市場強度も確認してください。"
                        if level_fields.get("invalidation")
                        else "次の価格、出来高、法人フロー、相対的な市場強度が同時に弱くなるか確認してください。"
                    ),
                },
                {"label": "リスク管理", "text": "すべてのデータ確認を待たず、条件が崩れたら先にエクスポージャーを小さくしてください。"},
            ]
        elif question_intent == "trend_view":
            if evidence_summary:
                summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
            if weak_evidence:
                headline = f"{target_label} は方向判断の信頼度が限られます。次の確認を待ってください"
            elif score is not None and score >= 2:
                headline = f"{target_label} のトレンドは強気寄りです。サポート維持とブレイク継続を確認してください"
            elif score is not None and score <= -2:
                headline = f"{target_label} のトレンドは弱気寄りです。サポート割れを確認してください"
            else:
                headline = f"{target_label} は方向未定です。サポートか抵抗線のどちらが先に決まるか確認してください"

            action_plan = [
                {"label": "トレンド", "text": f"現在のスコアは {score_text or '-'} です。方向の手掛かりとして使い、直接の売買シグナルにはしないでください。"},
                {"label": "サポート/抵抗", "text": "主要移動平均、前回安値、上値抵抗が一つのシグナルに収束するか確認してください。"},
                {"label": "監視", "text": "価格、出来高、相対的な市場強度が同じ方向にそろってから判断を強めてください。"},
            ]
        else:
            if evidence_summary:
                summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
            if weak_evidence:
                headline = f"{target_label} は方向判断の信頼度が限られます。次の確認を待ってください"
            elif score is not None and score >= 2:
                headline = f"{target_label} のトレンドは強気寄りですが、確認はまだ必要です"
            elif score is not None and score <= -2:
                headline = f"{target_label} のトレンドは弱気寄りです。流れに逆らう追いかけ買いは避けてください"
            else:
                headline = f"{target_label} は方向未定です。重要な価格と出来高の確認を待ってください"

            action_plan = [
                {"label": "方向", "text": f"現在のスコアは {score_text or '-'} です。方向の強さを見る材料であり、直接の売買シグナルではありません。"},
                {"label": "確認", "text": "価格、出来高、移動平均、または相対的な市場強度が同じ方向にそろうまで待ってください。"},
                {"label": "失効", "text": "主要移動平均またはモメンタムが弱まる場合、トレンド見通しを再計算してください。"},
            ]

        scenarios = scenario_plan_from_levels(
            question_intent=question_intent,
            fields=level_fields,
            numbers=level_numbers,
            score=score,
            weak_evidence=weak_evidence,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        counter_evidence = counter_evidence_from_levels(
            question_intent=question_intent,
            fields=level_fields,
            score=score,
            weak_evidence=weak_evidence,
            evidence_risks=answer_risks,
            response_preferences=response_preferences,
        )
        answer = {
            "kind": "consumer_market_answer",
            "style": "question_aware_summary",
            "source": "question_intent",
            "intent": question_intent,
            "headline": headline,
            "stance": stance,
            "stance_label": stance_label(stance, response_preferences),
            "confidence": confidence,
            "confidence_label": confidence_display,
            "summary": summary,
            "action_plan": action_plan,
            "scenarios": scenarios,
            "counter_evidence": counter_evidence,
            "risks": list(dict.fromkeys(answer_risks + (data_limits[:2] if weak_evidence else [])))[:2],
            "data_limits": data_limits,
            "detail": text_value(analysis_digest.get("display")) or "",
            "decision_evidence": decision_evidence,
        }
        answer["text"] = consumer_text(
            answer,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return answer

    if question_intent == "entry_decision":
        if level_fields:
            headline, entry_summary, action_plan = decision_engine.entry_decision_with_levels(
                target_label=target_label,
                score=score,
                weak_evidence=weak_evidence,
                fields=level_fields,
                numbers=level_numbers,
                summary_limit=summary_limit,
            )
            if entry_summary:
                summary = list(
                    dict.fromkeys(entry_summary[:1] + evidence_summary + entry_summary[1:] + summary)
                )[:summary_limit]
        elif weak_evidence:
            headline = f"{target_label} 先不要直接買，資料或信心還不足"
            action_plan = [
                {"label": "現在", "text": "先不要追價，等下一筆價格、量能或指標確認。"},
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
        elif score is not None and score >= 4:
            headline = f"{target_label} 可以列入偏多觀察，但不建議直接追價"
            action_plan = [
                {
                    "label": "現在",
                    "text": "先把它當作偏多觀察標的，不把單一評分當成直接買進訊號。",
                },
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
        elif score is not None and score >= 1:
            headline = f"{target_label} 可以觀察，買點要等價格與量能確認"
            action_plan = [
                {
                    "label": "現在",
                    "text": "先把它當作觀察標的，不把單一評分當成直接買進訊號。",
                },
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
        elif score is not None and score <= -1:
            headline = f"{target_label} 目前不建議直接買"
            action_plan = [
                {"label": "現在", "text": "先不要追價，等下一筆價格、量能或指標確認。"},
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
        else:
            headline = f"{target_label} 先觀望，等方向確認"
            action_plan = [
                {"label": "現在", "text": "先不要追價，等下一筆價格、量能或指標確認。"},
                {
                    "label": "進場條件",
                    "text": "價格、量能與主要均線或動能同向轉強後，再把進場權重提高。",
                },
                {
                    "label": "風控",
                    "text": "若短線動能轉弱、跌回關鍵均線下方或放量失敗，這個買進假設要降級。",
                },
            ]
    elif question_intent == "exit_decision":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if level_fields and not weak_evidence and (level_fields.get("stop") or level_fields.get("invalidation")):
            guardrails = " / ".join(
                value
                for value in (level_fields.get("stop"), level_fields.get("invalidation"))
                if value
            )
            headline = f"{target_label} 還可條件式續抱，但要守住 {guardrails}"
        elif weak_evidence:
            headline = f"{target_label} 先降低判斷強度，等資料確認再決定去留"
        elif score >= 2:
            headline = f"{target_label} 還可續抱觀察，但要守住轉弱條件"
        elif score <= -2:
            headline = f"{target_label} 偏弱，應優先檢查減碼或出場條件"
        else:
            headline = f"{target_label} 方向未明，先用條件式續抱"

        action_plan = [
            {"label": "現在", "text": "先看持有成本與部位大小，不用單一分數做全部出場決策。"},
            {
                "label": "續抱條件",
                "text": (
                    f"價格守住 {level_fields['stop']} 以上，且量能沒有放大轉弱時，續抱觀察較合理。"
                    if level_fields.get("stop")
                    else "價格守住關鍵均線或前低，且量能沒有放大轉弱時，續抱觀察較合理。"
                ),
            },
            {
                "label": "出場條件",
                "text": (
                    f"若跌破 {level_fields['invalidation']}，技術假設失效，應降低部位或重新評估。"
                    if level_fields.get("invalidation")
                    else "若跌破主要支撐、動能轉空或反彈失敗，應降低部位或重新評估。"
                ),
            },
        ]
    elif question_intent == "risk_check":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if level_fields and not weak_evidence and (level_fields.get("stop") or level_fields.get("invalidation")):
            headline = (
                f"{target_label} 風險線在 {level_fields.get('stop') or level_fields.get('invalidation')}，"
                "跌破要先防守"
            )
        elif weak_evidence:
            headline = f"{target_label} 風險判斷信心不足，先用保守條件控管"
        elif score <= -2:
            headline = f"{target_label} 風險偏高，短線要優先防守"
        elif score >= 2:
            headline = f"{target_label} 目前風險未明顯放大，但仍要看失效條件"
        else:
            headline = f"{target_label} 多空拉扯，風險需要逐筆確認"

        action_plan = [
            {
                "label": "主要風險",
                "text": (
                    f"若跌破短線停損 {level_fields['stop']}，短線方向會快速降級。"
                    if level_fields.get("stop")
                    else "若價格跌破主要均線或前低，短線方向會快速降級。"
                ),
            },
            {
                "label": "觀察",
                "text": (
                    f"看 {level_fields['invalidation']} 是否被跌破，並同步確認量能、法人或市場相對強弱。"
                    if level_fields.get("invalidation")
                    else "看下一筆價格、量能、法人或市場相對強弱是否同步轉弱。"
                ),
            },
            {"label": "風控", "text": "不要等到資料完全確認才控風險；條件失效時先縮小部位。"},
        ]
    elif question_intent == "trend_view":
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if level_fields:
            headline, trend_summary, action_plan, trend_risks = decision_engine.trend_view_with_levels(
                target_label=target_label,
                score=score,
                weak_evidence=weak_evidence,
                fields=level_fields,
                numbers=level_numbers,
                summary_limit=summary_limit,
            )
            summary = list(dict.fromkeys(trend_summary + summary))[:summary_limit]
            answer_risks = list(dict.fromkeys(trend_risks + evidence_risks))
        elif weak_evidence:
            headline = f"{target_label} 目前方向信心不足，先看下一筆確認"
            action_plan = [
                {
                    "label": "趨勢",
                    "text": "先把這次解讀當方向參考，不把單一分數或單日收盤價當成最後結論。",
                },
                {"label": "支撐壓力", "text": "先看主要均線、前低與量能，確認支撐壓力是否一致。"},
                {"label": "觀察", "text": "等價格、量能與市場相對強弱出現同向訊號後，再提高判斷強度。"},
            ]
        elif score >= 2:
            headline = f"{target_label} 走勢偏多，先看支撐承接與突破延續"
            action_plan = [
                {"label": "趨勢", "text": "先用多週期分數判斷大方向，再用支撐壓力與量能確認延續性。"},
                {"label": "支撐壓力", "text": "先看回測支撐是否守住，再看上方壓力是否突破站穩。"},
                {"label": "觀察", "text": "觀察價格、量能、均線與相對市場是否持續同向。"},
            ]
        elif score <= -2:
            headline = f"{target_label} 走勢偏弱，先看支撐是否失守"
            action_plan = [
                {"label": "趨勢", "text": "先把方向降級，不用單一收盤價硬撐原本的多方假設。"},
                {"label": "支撐壓力", "text": "優先確認主要支撐是否失守，以及反彈壓力是否有效。"},
                {"label": "觀察", "text": "若量能與動能都轉弱，原本的波段判斷要重新計算。"},
            ]
        else:
            headline = f"{target_label} 方向未定，先看支撐壓力哪邊先表態"
            action_plan = [
                {"label": "趨勢", "text": f"目前評分為 {score_text or '-'}，先把它當方向線索，不直接等同買賣訊號。"},
                {"label": "支撐壓力", "text": "先看關鍵均線、前低與上方壓力是否收斂成一致訊號。"},
                {"label": "觀察", "text": "等價格、量能與市場相對強弱同向後，再提高結論強度。"},
            ]
    else:
        if evidence_summary:
            summary = list(dict.fromkeys(evidence_summary + summary))[:summary_limit]
        if weak_evidence:
            headline = f"{target_label} 目前方向信心不足，先看下一筆確認"
        elif score >= 2:
            headline = f"{target_label} 走勢偏多，但仍要等確認"
        elif score <= -2:
            headline = f"{target_label} 走勢偏弱，先不要逆勢追高"
        else:
            headline = f"{target_label} 方向未定，先看關鍵價量是否突破"

        action_plan = [
            {"label": "方向", "text": f"目前評分為 {score_text or '-'}，先用它判斷方向強弱，不直接等同買賣訊號。"},
            {"label": "確認", "text": "等價格、量能、均線或市場相對強弱出現同向訊號。"},
            {"label": "失效", "text": "若主要均線或動能轉弱，原本走勢判斷要重新計算。"},
        ]

    scenarios = scenario_plan_from_levels(
        question_intent=question_intent,
        fields=level_fields,
        numbers=level_numbers,
        score=score,
        weak_evidence=weak_evidence,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    counter_evidence = counter_evidence_from_levels(
        question_intent=question_intent,
        fields=level_fields,
        score=score,
        weak_evidence=weak_evidence,
        evidence_risks=answer_risks,
        response_preferences=response_preferences,
    )

    answer = {
        "kind": "consumer_market_answer",
        "style": "question_aware_summary",
        "source": "question_intent",
        "intent": question_intent,
        "headline": headline,
        "stance": stance,
        "stance_label": stance_label(stance, response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_display,
        "summary": summary,
        "action_plan": action_plan,
        "scenarios": scenarios,
        "counter_evidence": counter_evidence,
        "risks": list(dict.fromkeys(answer_risks + (data_limits[:2] if weak_evidence else [])))[:2],
        "data_limits": data_limits,
        "detail": text_value(analysis_digest.get("display")) or "",
        "decision_evidence": decision_evidence,
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_llm_consumer_answer(
    *,
    report: dict[str, Any],
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    stance = text_value(report.get("stance"))
    confidence = text_value(report.get("confidence"))
    headline = (
        text_value(report.get("headline"))
        or text_value(analysis_digest.get("selected_title"))
        or text_value(target.get("label"))
        or (
            "OMI analysis is ready"
            if english
            else "OMI分析が完了しました"
            if japanese
            else "OMI 已完成分析"
        )
    )

    backend_data_limits = generic_data_limits(
        missing=missing,
        warnings=warnings,
        response_preferences=response_preferences,
    )
    has_backend_missing = bool(text_list(missing))
    raw_observations = text_list(report.get("key_observations"))
    raw_interpretations = text_list(report.get("interpretation"))
    raw_next_checks = text_list(report.get("next_checks"))
    raw_risks = text_list(report.get("risks"))
    raw_missing_data = text_list(report.get("missing_data"))

    observations = filter_soft_data_gap_texts(raw_observations, has_backend_missing=has_backend_missing)
    interpretations = filter_soft_data_gap_texts(raw_interpretations, has_backend_missing=has_backend_missing)
    next_checks = filter_soft_data_gap_texts(raw_next_checks, has_backend_missing=has_backend_missing)
    risks = filter_soft_data_gap_texts(raw_risks, has_backend_missing=has_backend_missing)
    missing_data = raw_missing_data if has_backend_missing else []

    summary: list[str] = []
    append_unique_texts(summary, observations[:2], limit=summary_limit)
    append_unique_texts(summary, interpretations[:2], limit=summary_limit)
    if not summary and analysis_digest.get("display"):
        summary.append(str(analysis_digest["display"]))

    follow_up_checks = list(
        dict.fromkeys(next_checks + ([] if has_backend_missing else filter_soft_data_gap_texts(raw_missing_data, has_backend_missing=False)))
    )

    action_plan = [
        {
            "label": "Holding" if english else "保有中" if japanese else "已持有",
            "text": interpretations[0] if interpretations else (
                "Use the current conclusion as context first; do not treat one signal as confirmation."
                if english
                else "現在の結論はまず文脈として扱い、単一シグナルを確認済みとは見なさないでください。"
                if japanese
                else "先依目前結論觀察，不把單一訊號當成確認。"
            ),
        },
        {
            "label": "Entry" if english else "エントリー" if japanese else "想進場",
            "text": follow_up_checks[0] if follow_up_checks else (
                "Wait for the next price, volume, or key moving-average confirmation before deciding."
                if english
                else "次の価格、出来高、または主要移動平均の確認を待ってから判断してください。"
                if japanese
                else "等下一筆價格、量能或關鍵均線確認後再判斷。"
            ),
        },
        {
            "label": "Invalidation" if english else "失効" if japanese else "失效",
            "text": risks[0] if risks else (
                "Downgrade the view if price or volume weakens."
                if english
                else "価格または出来高が弱まる場合、見通しを下方修正してください。"
                if japanese
                else "若價格或量能轉弱，原本結論需要降級。"
            ),
        },
    ]
    data_limits = list(dict.fromkeys(missing_data[:3] + backend_data_limits))[:3] if has_backend_missing else backend_data_limits
    detail_report = dict(report)
    if not has_backend_missing:
        detail_report["missing_data"] = []

    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "llm_report",
        "headline": headline,
        "stance": stance,
        "stance_label": stance_label(stance, response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_label(confidence, response_preferences),
        "summary": summary,
        "action_plan": action_plan,
        "risks": risks[:2],
        "data_limits": data_limits,
        "detail": consumer_detail_from_llm_report(
            detail_report,
            missing_data_label=(
                ("Data limits" if data_limits else "Next checks")
                if english
                else ("データ制約" if data_limits else "次の確認")
                if japanese
                else ("資料限制" if data_limits else "後續確認")
            ),
            response_preferences=response_preferences,
        ),
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


WATCHLIST_RADAR_RISK_BUCKETS = {
    "risk",
    "limit_move",
    "limit_down_liquidity",
    "selloff_risk",
    "overheated",
    "volatility_risk",
    "support_break",
    "volume_down",
    "bearish_momentum",
    "limit_down_move",
}
WATCHLIST_RADAR_MOMENTUM_BUCKETS = {
    "breakout",
    "volume",
    "pullback",
    "momentum",
    "limit_move",
    "limit_up_lock",
    "surge_up",
    "breakout_high",
    "trend_reclaim",
    "volume_up",
    "compression_watch",
    "limit_up_move",
}


def watchlist_radar_rows_for_intent(
    analysis_digest: dict[str, Any],
    *,
    question_intent: str,
    limit: int = SUMMARY_LIMIT_DEFAULT,
) -> list[dict[str, Any]]:
    rows = analysis_digest.get("radar_rows") if isinstance(analysis_digest.get("radar_rows"), list) else []
    radar_rows = [row for row in rows if isinstance(row, dict)]
    if not radar_rows:
        return []

    if question_intent in {"risk_check", "exit_decision"}:
        risk_rows = [
            row
            for row in radar_rows
            if row.get("bucket") in WATCHLIST_RADAR_RISK_BUCKETS
        ]
        high_priority_rows = [
            row
            for row in radar_rows
            if row.get("bucket") not in WATCHLIST_RADAR_RISK_BUCKETS
            and row.get("urgency") == "high"
        ]
        selected = []
        seen: set[tuple[Any, Any]] = set()
        for row in [*risk_rows, *high_priority_rows]:
            key = (row.get("stock_id"), row.get("label"))
            if key in seen:
                continue
            seen.add(key)
            selected.append(row)
        return (selected or radar_rows)[:limit]

    if question_intent == "entry_decision":
        selected = [
            row
            for row in radar_rows
            if row.get("bucket") in WATCHLIST_RADAR_MOMENTUM_BUCKETS
            and row.get("bucket") != "risk"
        ]
        return (selected or radar_rows)[:limit]

    return radar_rows[:limit]


def watchlist_radar_row_text(
    row: dict[str, Any],
    response_preferences: dict[str, Any] | None = None,
) -> str:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    label = text_value(row.get("label"))
    if not label:
        stock_id = text_value(row.get("stock_id"))
        stock_name = text_value(row.get("stock_name"))
        label = " ".join(part for part in (stock_id, stock_name) if part) or (
            "Unnamed target" if english else "名称未設定の対象" if japanese else "未命名標的"
        )

    details: list[str] = []
    bucket_label = radar_bucket_label(
        row.get("bucket"),
        row.get("bucket_label"),
        response_preferences=response_preferences,
    )
    urgency = text_value(row.get("urgency"))
    action = radar_action_label(row, response_preferences=response_preferences)
    change_pct = text_value(row.get("change_pct_text"))
    primary_signal = radar_signal_label(row, response_preferences=response_preferences)

    if bucket_label:
        details.append(bucket_label)
    if urgency == "high":
        details.append("High priority" if english else "高優先度" if japanese else "高優先")
    elif urgency == "medium":
        details.append("Medium priority" if english else "中優先度" if japanese else "中優先")
    if change_pct:
        details.append(change_pct)
    if primary_signal:
        details.append(primary_signal)
    if action:
        details.append(action)

    if not details:
        return label
    if english:
        return f"{label} ({', '.join(details)})"
    return f"{label}（{'，'.join(details)}）"


def watchlist_radar_bucket_summary(
    radar: dict[str, Any],
    response_preferences: dict[str, Any] | None = None,
) -> str:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    buckets = radar.get("buckets") if isinstance(radar.get("buckets"), list) else []
    parts = [
        f"{radar_bucket_label(bucket.get('key'), bucket.get('label'), response_preferences=response_preferences)} {bucket.get('count')}"
        for bucket in buckets
        if (
            isinstance(bucket, dict)
            and radar_bucket_label(bucket.get("key"), bucket.get("label"), response_preferences=response_preferences)
            and int(bucket.get("count") or 0) > 0
        )
    ]
    return (", " if english else "、" if japanese else "、").join(parts[:4])


def build_watchlist_radar_consumer_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if analysis_digest.get("kind") != "watchlist_sector_digest":
        return {}

    radar = analysis_digest.get("radar") if isinstance(analysis_digest.get("radar"), dict) else {}
    if not radar:
        return {}

    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    selected_rows = watchlist_radar_rows_for_intent(
        analysis_digest,
        question_intent=question_intent,
        limit=summary_limit,
    )
    matched_count = int(radar.get("matched_count") or 0)
    bucket_text = watchlist_radar_bucket_summary(
        radar,
        response_preferences=response_preferences,
    )
    group_name = (
        text_value(analysis_digest.get("group_name"))
        or text_value(target.get("label"))
        or ("Watchlist" if english else "ウォッチリスト" if japanese else "自選股")
    )
    row_joiner = "; " if english else "、"
    row_text = row_joiner.join(
        watchlist_radar_row_text(row, response_preferences=response_preferences)
        for row in selected_rows
    )

    if question_intent in {"risk_check", "exit_decision"}:
        headline = (
            f"{group_name}: handle radar risk and invalidation names first"
            if english
            else f"{group_name} はレーダーが示すリスク銘柄と失効候補を先に処理してください"
            if japanese
            else f"{group_name} 先處理雷達標出的風險與失效名單"
        )
        focus_label = "Risk list" if english else "リスク候補" if japanese else "風險名單"
        primary_action = (
            "Check high-priority or weakening names first, and reduce weight when needed before waiting for complete confirmation."
            if english
            else "優先度が高い、または弱含みの銘柄を先に確認し、完全な確認を待つ前に必要なら比重を下げてください。"
            if japanese
            else "先檢查高優先或轉弱標的，必要時降低權重，不等完整確認才控風險。"
        )
    elif question_intent == "entry_decision":
        headline = (
            f"{group_name}: pick from radar strength candidates first; do not chase the whole basket"
            if english
            else f"{group_name} はレーダーの強い候補から選び、全体を追いかけ買いしないでください"
            if japanese
            else f"{group_name} 先從雷達命中的強勢候選挑，不建議整包追價"
        )
        focus_label = "Candidate list" if english else "候補リスト" if japanese else "候選名單"
        primary_action = (
            "Treat radar hits as candidates only; increase weight after price, volume, and pullback location confirm."
            if english
            else "レーダー命中は候補として扱い、価格・出来高・押し目位置が確認できてから比重を上げてください。"
            if japanese
            else "只把雷達命中當候選清單，等價格、量能與回測位置確認後再提高權重。"
        )
    else:
        headline = (
            f"{group_name}: start with today's radar matches"
            if english
            else f"{group_name} は今日のレーダー命中から確認してください"
            if japanese
            else f"{group_name} 今日先看雷達命中名單"
        )
        focus_label = "Priority list" if english else "優先リスト" if japanese else "優先名單"
        primary_action = (
            "Start with high-priority names and the densest signals, then confirm ranking and base data."
            if english
            else "優先度が高くシグナルが集中する銘柄から見て、その後ランキングと基礎データを確認してください。"
            if japanese
            else "先看高優先與訊號最集中的標的，再回到排名與基本資料確認。"
        )

    summary = []
    radar_line = (
        f"Radar matched {matched_count} names"
        if english
        else f"レーダーで {matched_count} 銘柄が一致"
        if japanese
        else f"雷達 {matched_count} 檔命中"
    )
    if bucket_text:
        radar_line += (f": {bucket_text}" if english else f"：{bucket_text}")
    if english:
        summary.append(radar_line + ".")
    else:
        summary.append(radar_line + "。")
    if row_text:
        summary.append(
            f"{focus_label}: {row_text}." if english else f"{focus_label}：{row_text}。"
        )
    elif matched_count <= 0:
        summary.append(
            "No radar items match current conditions; use the original ranking and data completeness first."
            if english
            else "現在の条件に一致するレーダー項目はありません。まず元のランキングとデータ完全性を確認してください。"
            if japanese
            else "目前沒有符合條件的雷達項目，先用原本排名與資料完整度觀察。"
        )
    if analysis_digest.get("display"):
        summary.append(str(analysis_digest["display"]))

    action_plan = [
        {
            "label": "Watch first" if english else "先に確認" if japanese else "先看",
            "text": row_text or (
                "No radar names matched; start with the original watchlist ranking."
                if english
                else "現在レーダー命中銘柄はありません。元のウォッチリスト順位から確認してください。"
                if japanese
                else "目前沒有雷達命中標的，先看原本自選股排名。"
            ),
        },
        {"label": "Confirm" if english else "確認" if japanese else "確認", "text": primary_action},
        {
            "label": "Exclude" if english else "除外" if japanese else "排除",
            "text": (
                "Downgrade names with stale data, missing data, or only one signal; do not treat radar as a direct trade signal."
                if english
                else "データ遅延、欠損、または単一シグナルだけの銘柄は下方修正し、レーダーを直接売買シグナルとして扱わないでください。"
                if japanese
                else "資料落後、缺資料或只靠單一訊號的標的先降級，避免把雷達當成直接買賣訊號。"
            ),
        },
    ]
    data_limits = generic_data_limits(
        missing=missing,
        warnings=warnings,
        response_preferences=response_preferences,
    )
    if radar.get("is_current") is False or radar.get("stale_stock_count"):
        data_limits.append(
            "Radar includes stale daily data; confirm ranking after the next update."
            if english
            else "レーダーには遅延した日足データが含まれます。次回更新後にランキングを再確認してください。"
            if japanese
            else "雷達含有落後日線資料，需等更新後再確認排序。"
        )

    answer = {
        "kind": "consumer_market_answer",
        "style": "watchlist_radar_summary",
        "source": "watchlist_radar",
        "intent": question_intent,
        "headline": headline,
        "stance": text_value(analysis_digest.get("stance")),
        "stance_label": radar_stance_label(
            analysis_digest.get("stance"),
            response_preferences=response_preferences,
        ),
        "confidence": text_value(analysis_digest.get("confidence")),
        "confidence_label": confidence_label(
            analysis_digest.get("confidence"),
            response_preferences,
        ),
        "summary": list(dict.fromkeys(summary))[:summary_limit],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": list(dict.fromkeys(data_limits))[:3],
        "detail": text_value(
            (analysis_digest.get("human_answer") or {}).get("text")
            if isinstance(analysis_digest.get("human_answer"), dict)
            else None
        ) or text_value(analysis_digest.get("display")) or "",
        "radar": radar,
        "radar_rows": selected_rows,
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_watchlist_consumer_answer(
    *,
    human_answer: dict[str, Any],
    overview: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sections = human_answer.get("sections") if isinstance(human_answer.get("sections"), list) else []
    section_map: dict[str, str] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = text_value(section.get("label"))
        text = text_value(section.get("text"))
        if label and text:
            section_map[label] = text

    lines = text_list(human_answer.get("lines")) or text_list(overview.get("answer_outline"))
    headline = section_map.get("結論") or text_value(overview.get("display")) or (lines[0] if lines else "自選股整理完成")
    summary = [
        text
        for key in ("雷達", "追蹤", "等回測", "保守")
        if (text := section_map.get(key))
    ]
    if not summary:
        summary = lines[1 : 1 + summary_limit]

    action_plan = []
    if section_map.get("雷達"):
        action_plan.append({"label": "雷達", "text": section_map["雷達"]})
    action_plan.extend([
        {"label": "優先看", "text": section_map.get("追蹤") or "先看排名與量價最明確的個股。"},
        {"label": "等回測", "text": section_map.get("等回測") or "漲幅過大的標的等回測後再確認。"},
        {"label": "保守", "text": section_map.get("保守") or "弱勢或資料不足標的先降低追蹤權重。"},
    ])
    data_limits = []
    if section_map.get("資料"):
        data_limits.append(section_map["資料"])
    data_limits.extend(
        generic_data_limits(
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )
    )

    confidence = text_value(overview.get("confidence"))
    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "watchlist_overview",
        "headline": headline,
        "stance": text_value(overview.get("stance")),
        "stance_label": text_value(overview.get("stance")) or "未定",
        "confidence": confidence,
        "confidence_label": confidence_label(confidence, response_preferences),
        "summary": summary[:summary_limit],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": list(dict.fromkeys(data_limits))[:3],
        "detail": text_value(human_answer.get("text")) or "\n".join(lines),
        "source_human_answer": human_answer,
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_digest_consumer_answer(
    *,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    english = response_is_english(response_preferences)
    japanese = response_is_japanese(response_preferences)
    confidence = text_value(analysis_digest.get("selected_confidence"))
    headline = (
        text_value(analysis_digest.get("selected_title"))
        or text_value(analysis_digest.get("display"))
        or text_value(target.get("label"))
        or (
            "OMI data summary is ready"
            if english
            else "OMIデータ整理が完了しました"
            if japanese
            else "OMI 已完成資料整理"
        )
    )
    summary = [
        text
        for text in (
            text_value(analysis_digest.get("display")),
            text_value(analysis_digest.get("selected_summary")),
        )
        if text
    ]
    scores = analysis_digest.get("scores") if isinstance(analysis_digest.get("scores"), dict) else {}
    if scores:
        score_parts = [
            f"{analysis_horizon_label(key, response_preferences)} {decision_engine.score_display(value) or '-'}"
            for key, value in scores.items()
            if value is not None
        ]
        if score_parts:
            summary.append(
                ("Score: " + ", ".join(score_parts[:4]))
                if english
                else ("スコア：" + "、".join(score_parts[:4]))
                if japanese
                else ("分數：" + "、".join(score_parts[:4]))
            )

    action_plan = [
        {
            "label": "Holding" if english else "保有中" if japanese else "已持有",
            "text": (
                "Observe with the current direction and wait for the next price-volume or indicator confirmation."
                if english
                else "現在の方向を参考にし、次の価格・出来高または指標確認を待ってください。"
                if japanese
                else "先依目前方向觀察，等待下一筆量價或指標確認。"
            ),
        },
        {
            "label": "Entry" if english else "エントリー" if japanese else "想進場",
            "text": (
                "Do not rely on one score; increase weight only after price, volume, and relative market strength align."
                if english
                else "単一スコアだけに頼らず、価格・出来高・相対的な市場強度がそろってから比重を上げてください。"
                if japanese
                else "不要只看單一評分，等價格、量能與市場相對強弱同向再提高權重。"
            ),
        },
        {
            "label": "Invalidation" if english else "失効" if japanese else "失效",
            "text": (
                "Recalculate this brief view if key moving averages or momentum weaken."
                if english
                else "主要移動平均またはモメンタムが弱まる場合、この短評を再計算してください。"
                if japanese
                else "若主要均線或動能轉弱，這份短評需要重新計算。"
            ),
        },
    ]
    answer = {
        "kind": "consumer_market_answer",
        "style": "layered_summary",
        "source": "analysis_digest",
        "headline": headline,
        "stance": None,
        "stance_label": undecided_label(response_preferences),
        "confidence": confidence,
        "confidence_label": confidence_label(confidence, response_preferences),
        "summary": list(dict.fromkeys(summary))[:summary_limit],
        "action_plan": action_plan,
        "risks": [],
        "data_limits": generic_data_limits(
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        ),
        "detail": text_value(analysis_digest.get("display")) or "",
    }
    answer["text"] = consumer_text(
        answer,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    return answer


def build_consumer_human_answer(
    *,
    question_intent: str,
    target: dict[str, Any],
    analysis_digest: dict[str, Any],
    missing: list[Any],
    warnings: list[Any],
    position_decision: dict[str, Any] | None = None,
    llm_report: dict[str, Any] | None = None,
    summary_limit: int = SUMMARY_LIMIT_DEFAULT,
    response_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if position_decision:
        answer = build_position_decision_consumer_answer(
            position_decision=position_decision,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    watchlist_radar_answer = build_watchlist_radar_consumer_answer(
        question_intent=question_intent,
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    if watchlist_radar_answer and (
        not llm_report
        or question_intent in {"entry_decision", "exit_decision", "risk_check", "trend_view"}
    ):
        return append_source_health_data_limits(
            watchlist_radar_answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    question_answer = build_question_aware_consumer_answer(
        question_intent=question_intent,
        target=target,
        analysis_digest=analysis_digest,
        missing=missing,
        warnings=warnings,
        summary_limit=summary_limit,
        response_preferences=response_preferences,
    )
    if question_intent in {"entry_decision", "exit_decision", "trend_view"} and question_answer:
        return append_source_health_data_limits(
            question_answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    if llm_report:
        answer = build_llm_consumer_answer(
            report=llm_report,
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    human_answer = analysis_digest.get("human_answer") if isinstance(analysis_digest.get("human_answer"), dict) else {}
    if human_answer:
        answer = build_watchlist_consumer_answer(
            human_answer=human_answer,
            overview=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    if question_answer:
        return append_source_health_data_limits(
            question_answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    if analysis_digest:
        answer = build_digest_consumer_answer(
            target=target,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            summary_limit=summary_limit,
            response_preferences=response_preferences,
        )
        return append_source_health_data_limits(
            answer,
            analysis_digest=analysis_digest,
            missing=missing,
            warnings=warnings,
            response_preferences=response_preferences,
        )

    return {}
