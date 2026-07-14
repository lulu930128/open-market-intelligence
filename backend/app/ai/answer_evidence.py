from __future__ import annotations

from typing import Any

from app.ai import decision_engine
from app.ai.answer_data_limits import (
    SOURCE_HEALTH_RESOURCE_LABELS_EN,
    SOURCE_HEALTH_RESOURCE_LABELS_JA,
)
from app.ai.answer_localization import (
    analysis_horizon_label,
    append_unique_texts,
    pct_text,
    response_is_english,
    response_is_japanese,
    text_list,
    text_value,
)


SUMMARY_LIMIT_DEFAULT = 3

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
