from __future__ import annotations

from typing import Any

from app.ai.answer_data_limits import generic_data_limits
from app.ai.answer_localization import (
    confidence_label,
    consumer_text,
    response_is_english,
    response_is_japanese,
    text_value,
    undecided_label,
)


SUMMARY_LIMIT_DEFAULT = 3
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
